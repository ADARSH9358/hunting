"""SearchOrchestrator - the RUN button pipeline.

 1 load profile        2 generate keywords      3 search job sources
 4 discover companies  5 find career pages      6 collect official postings
 7 normalize           8 de-duplicate & save    9 match against resume
10 persist results    11 live progress (polled) 12 completion summary

A failing source never stops the run: each connector is isolated, timed out,
and its error recorded. Stop requests are honoured between and within steps;
whatever was collected before the stop is still saved and matched.
"""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import db as dbmod
from app.config import get_settings
from app.connectors.ats import ATS_CONNECTORS
from app.connectors.base import RawJob, SearchContext, is_relevant
from app.services.text_utils import html_to_text
from app.connectors.registry import GENERIC_CAREER, PORTALS, all_connectors, is_enabled, search_connectors
from app.models import (
    CandidateProfile,
    Company,
    Job,
    JobMatch,
    JobSource,
    JobSourceLink,
    SearchLog,
    SearchSession,
)
from app.services.company_discovery import CompanyDiscoveryService, size_category, upsert_company
from app.services.dedup import CompanyJobIndex, upsert_jobs
from app.services.http import AccessDenied, PoliteHttp, RobotsDisallowed
from app.services.keyword_generator import generate_keywords
from app.services.matching import CandidateView, score_job
from app.services.normalization import NormalizedJob, normalize

log = logging.getLogger(__name__)
SOURCE_TIMEOUT = 240
COMPANY_TIMEOUT = 90


async def sync_sources(db: AsyncSession) -> dict[str, JobSource]:
    """Ensure every connector & portal has a job_sources row with current status."""
    rows = {s.key: s for s in (await db.execute(select(JobSource))).scalars().all()}
    for c in all_connectors():
        row = rows.get(c.key)
        if row is None:
            row = JobSource(key=c.key, name=c.name, kind=c.kind)
            db.add(row)
            rows[c.key] = row
        row.name, row.kind, row.base_url = c.name, c.kind, c.base_url
        row.requires_credentials = c.requires_credentials
        row.is_official_company_source = c.is_official_company_source
        row.notes = c.notes
        if not c.is_configured():
            row.status = "needs_credentials"
        elif row.status in ("needs_credentials", "unknown", None):
            row.status = "available"
    for p in PORTALS:
        row = rows.get(p.key)
        if row is None:
            row = JobSource(key=p.key, name=p.name, kind="portal")
            db.add(row)
            rows[p.key] = row
        row.name, row.base_url, row.notes, row.status = p.name, p.url, p.access, "via_provider"
        row.requires_credentials = True
    await db.flush()
    return rows


class SearchOrchestrator:
    def __init__(self, session_id: int, session_factory=None):
        self.session_id = session_id
        self.Session = session_factory or dbmod.SessionLocal
        self.s = get_settings()
        self._cancel_cache = (0.0, False)
        self.stats: dict[str, Any] = {}
        self.source_results: dict[str, Any] = {}

    # ------------------------------------------------------------- helpers
    async def _log(self, level: str, message: str, source: str | None = None, **details) -> None:
        try:
            async with self.Session() as db:
                db.add(SearchLog(session_id=self.session_id, level=level, message=message[:2000],
                                 source_key=source, details=details or {}))
                await db.commit()
        except Exception as e:  # noqa: BLE001 - logging must never break the pipeline
            log.warning("could not persist search log: %s", e)
        getattr(log, "warning" if level == "warning" else "error" if level == "error" else "info")(
            "[search %s] %s%s", self.session_id, f"[{source}] " if source else "", message)

    async def _progress(self, pct: int, step: str) -> None:
        try:
            async with self.Session() as db:
                await db.execute(update(SearchSession).where(SearchSession.id == self.session_id).values(
                    progress=pct, current_step=step, heartbeat_at=datetime.now(timezone.utc),
                    stats=dict(self.stats), source_results=dict(self.source_results)))
                await db.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("could not persist progress: %s", e)

    async def should_stop(self) -> bool:
        ts, val = self._cancel_cache
        if val or time.monotonic() - ts < 1.5:
            return val
        async with self.Session() as db:
            v = (await db.execute(select(SearchSession.cancel_requested).where(
                SearchSession.id == self.session_id))).scalar_one_or_none()
        self._cancel_cache = (time.monotonic(), bool(v))
        return bool(v)

    async def _ctx_log(self, level: str, msg: str, source: str | None) -> None:
        await self._log(level, msg, source)

    # ------------------------------------------------------------- main
    async def run(self) -> None:
        try:
            await self._run()
        except Exception as e:  # noqa: BLE001
            log.exception("search %s crashed", self.session_id)
            async with self.Session() as db:
                await db.execute(update(SearchSession).where(SearchSession.id == self.session_id).values(
                    status="failed", error=f"{type(e).__name__}: {e}", finished_at=datetime.now(timezone.utc),
                    stats=self.stats, source_results=self.source_results))
                await db.commit()
            await self._log("error", f"Search failed: {e}", details_trace=traceback.format_exc()[-2000:])

    async def _run(self) -> None:
        t0 = time.monotonic()
        async with self.Session() as db:
            sess = await db.get(SearchSession, self.session_id)
            if sess is None:
                return
            sess.status, sess.started_at, sess.heartbeat_at = "running", datetime.now(timezone.utc), datetime.now(timezone.utc)
            user_id = sess.user_id
            await db.commit()

            # STEP 1 ------------------------------------------------- profile
            await self._progress(2, "Loading your latest resume profile")
            profile = (await db.execute(select(CandidateProfile).where(
                CandidateProfile.user_id == user_id, CandidateProfile.is_active.is_(True))
                .order_by(CandidateProfile.updated_at.desc()).limit(1))).scalar_one_or_none()
            if profile is None:
                raise RuntimeError("No resume profile found. Upload a resume first.")
            prefs = {**(profile.preferences or {}), **(sess.config or {})}
            cand = CandidateView.from_profile(profile)
            cand.preferences = prefs
            weights = (sess.config or {}).get("weights")
            sess.profile_id = profile.id

            # STEP 2 ------------------------------------------------- keywords
            await self._progress(5, "Generating search keywords")
            keywords, kw_method = await generate_keywords(profile.data or {}, prefs)
            sess.keywords = keywords
            await db.commit()
            await self._log("info", f"Keywords ({kw_method}): {', '.join(keywords)}")

            ctx = SearchContext(
                keywords=keywords, locations=prefs.get("preferred_locations") or [],
                remote_preference=prefs.get("remote_preference", "any"), countries=prefs.get("countries") or [],
                candidate_skills=cand.skills, posted_within_days=int(prefs.get("posted_within_days") or 30),
                log=self._ctx_log, should_stop=self.should_stop,
            )
            sources = await sync_sources(db)
            source_ids = {k: v.id for k, v in sources.items()}
            await db.commit()

            all_raw: list[RawJob] = []
            complete_listings: dict[tuple[str, int], set[str]] = {}
            raw_company: dict[int, Company] = {}

            async with PoliteHttp() as http:
                # STEP 3 --------------------------------------------- job sources
                conns = [c for c in search_connectors() if is_enabled(c, sources[c.key].enabled)]
                skipped = [c.key for c in search_connectors() if not c.is_configured()]
                for k in skipped:
                    self.source_results[k] = {"status": "needs_credentials", "count": 0}
                await self._progress(8, f"Searching {len(conns)} job sources")
                done = 0

                async def run_conn(c):
                    nonlocal done
                    started = time.monotonic()
                    try:
                        jobs = await asyncio.wait_for(c.search(http, ctx), SOURCE_TIMEOUT)
                        res = {"status": "ok", "count": len(jobs)}
                        await self._log("info", f"{c.name}: {len(jobs)} relevant postings", c.key)
                    except asyncio.TimeoutError:
                        jobs, res = [], {"status": "timeout", "count": 0, "error": f"timed out after {SOURCE_TIMEOUT}s"}
                        await self._log("warning", f"{c.name}: timed out", c.key)
                    except (AccessDenied, RobotsDisallowed) as e:
                        jobs, res = [], {"status": "blocked", "count": 0, "error": str(e)}
                        await self._log("warning", f"{c.name}: access not permitted ({e})", c.key)
                    except Exception as e:  # noqa: BLE001
                        jobs, res = [], {"status": "error", "count": 0, "error": f"{type(e).__name__}: {str(e)[:300]}"}
                        await self._log("warning", f"{c.name}: failed - {type(e).__name__}: {str(e)[:200]}", c.key)
                    res["seconds"] = round(time.monotonic() - started, 1)
                    self.source_results[c.key] = res
                    done += 1
                    await self._progress(8 + int(32 * done / max(1, len(conns))), f"Searched {done}/{len(conns)} job sources")
                    return c.key, jobs, res

                results = await asyncio.gather(*(run_conn(c) for c in conns))
                async with self.Session() as sdb:
                    for key, jobs, res in results:
                        all_raw.extend(jobs)
                        row = await sdb.get(JobSource, source_ids[key])
                        row.last_run_at = datetime.now(timezone.utc)
                        row.status = "ok" if res["status"] == "ok" else res["status"]
                        row.last_error = res.get("error")
                        row.last_job_count = res["count"]
                    await sdb.commit()
                self.stats["portal_postings"] = len(all_raw)

                # STEP 4 --------------------------------------------- company discovery
                discovery = CompanyDiscoveryService(db, http, ctx)
                if not await self.should_stop():
                    await self._progress(42, "Discovering IT companies")
                    seeded = await discovery.bootstrap()
                    added = await discovery.from_raw_jobs(all_raw)
                    via_search = await discovery.via_search_engine()
                    await db.commit()
                    await self._log("info", f"Company discovery: {added} companies from job sources, "
                                            f"{via_search} via search engine, {seeded} bootstrap boards")
                    # STEP 5 ------------------------------------------- career pages
                    await self._progress(48, "Finding official career pages")
                    probed = await discovery.probe_ats(limit=25)
                    await db.commit()
                    await self._log("info", f"Career page detection: {probed} new official job boards found")

                # STEP 6 --------------------------------------------- official postings
                sizes = prefs.get("company_sizes") or ["small", "medium", "large", "unknown"]
                companies = [] if await self.should_stop() else await discovery.companies_to_crawl(sizes, self.s.max_companies_per_run)
                await self._progress(52, f"Checking {len(companies)} company career pages")
                checked = 0
                company_errors = 0
                sem = asyncio.Semaphore(8)
                cutoff = datetime.now(timezone.utc) - timedelta(days=int(prefs.get("posted_within_days") or 30))

                async def crawl(company: Company):
                    nonlocal checked, company_errors
                    async with sem:
                        if await self.should_stop():
                            return []
                        ats_key = company.ats_type if company.ats_type in ATS_CONNECTORS else None
                        conn = ATS_CONNECTORS[ats_key] if ats_key else GENERIC_CAREER
                        target = company.ats_slug if ats_key else company.careers_url
                        status, jobs = "ok", []
                        try:
                            jobs = await asyncio.wait_for(conn.fetch_company(http, target, company.name, ctx), COMPANY_TIMEOUT)
                            if conn.complete_listing:
                                complete_listings[(conn.key, company.id)] = {j.external_id for j in jobs}
                        except (AccessDenied, RobotsDisallowed) as e:
                            status = "not_permitted"
                            await self._log("warning", f"{company.name}: {e}", conn.key)
                        except Exception as e:  # noqa: BLE001
                            status, company_errors = "error", company_errors + 1
                            await self._log("warning", f"{company.name}: {type(e).__name__}: {str(e)[:150]}", conn.key)
                        company.last_checked_at = datetime.now(timezone.utc)
                        company.last_check_status = status
                        if jobs:
                            nice = jobs[0].company_name
                            if company.name == company.ats_slug and nice and nice != company.ats_slug:
                                company.name = nice[:255]
                            elif company.name == company.ats_slug:
                                company.name = company.ats_slug.replace("-", " ").title()
                        relevant = [j for j in jobs if not (j.date_posted and j.date_posted < cutoff)
                                    and is_relevant(ctx, j.title, html_to_text(j.description)[:5000])]
                        company.open_jobs_count = len(jobs)
                        for j in relevant:
                            j.company_name = company.name
                            raw_company[id(j)] = company
                        checked += 1
                        if checked % 5 == 0 or checked == len(companies):
                            await self._progress(52 + int(26 * checked / max(1, len(companies))),
                                                 f"Checked {checked}/{len(companies)} company career pages")
                        return relevant

                company_results = await asyncio.gather(*(crawl(c) for c in companies))
                official_count = 0
                for jobs in company_results:
                    all_raw.extend(jobs)
                    official_count += len(jobs)
                await db.commit()
                self.stats.update({"companies_checked": checked, "company_errors": company_errors,
                                   "official_postings": official_count,
                                   "companies_discovered": discovery.discovered})
                await self._log("info", f"Career pages: {checked} companies checked, {official_count} relevant official postings")

            # STEP 7 ------------------------------------------------- normalize
            await self._progress(80, f"Normalizing {len(all_raw)} postings")
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(prefs.get("posted_within_days") or 30))
            normalized: list[tuple[NormalizedJob, Company | None]] = []
            dropped_old = dropped_exp = 0
            max_exp = prefs.get("max_experience_years")
            for r in all_raw:
                nj = normalize(r)
                if nj is None:
                    continue
                if nj.date_posted and nj.date_posted < cutoff:
                    dropped_old += 1
                    continue
                if max_exp is not None and nj.experience_min_years is not None and nj.experience_min_years > float(max_exp):
                    dropped_exp += 1  # respects the user's "maximum experience" preference
                    continue
                company = raw_company.get(id(r)) or discovery.cache.get(nj.normalized_company)
                if company is None:
                    company = await upsert_company(db, name=nj.company_name, website=r.company_website,
                                                   logo=r.company_logo, discovered_via=r.source_name, cache=discovery.cache)
                if company is not None:
                    if nj.company_size_stated and company.employee_count is None:
                        company.employee_count = nj.company_size_stated
                        company.size_category = size_category(nj.company_size_stated)
                        company.size_source = "stated in job posting"
                    if nj.company_type and not company.company_type:
                        company.company_type = nj.company_type
                normalized.append((nj, company))
            await db.flush()
            await db.commit()
            self.stats.update({"total_collected": len(all_raw), "older_than_range": dropped_old,
                               "above_max_experience": dropped_exp})

            # STEP 8 ------------------------------------------------- dedupe & save
            await self._progress(84, "Removing duplicates and saving jobs")
            new_ids: set[int] = set()
            seen_ids: set[int] = set()
            merged = 0
            cidx = CompanyJobIndex(db)
            for i in range(0, len(normalized), 250):
                if i:
                    await self._progress(84 + int(5 * i / len(normalized)), f"Saved {i}/{len(normalized)} postings")
                res = await upsert_jobs(db, normalized[i:i + 250], self.session_id, source_ids, cidx)
                new_ids |= res.new_ids
                seen_ids |= res.seen_ids
                merged += res.merged_duplicates
                await db.commit()
            run_job_ids = new_ids | seen_ids
            expired = await self._mark_unavailable(db, complete_listings)
            await db.commit()
            self.stats.update({"unique_jobs": len(run_job_ids), "duplicates_merged": merged,
                               "new_in_catalog": len(new_ids), "marked_unavailable": expired})

            # STEP 9 ------------------------------------------------- matching
            await self._progress(90, f"Matching {len(run_job_ids)} jobs against your resume")
            matching_stats = await self._match(db, user_id, profile.id, cand, run_job_ids, weights,
                                               float(prefs.get("min_match_score") or 40))
            self.stats.update(matching_stats)
            await db.commit()

            # STEP 10 ------------------------------------------------ application emails
            # Finds recruiter emails in matching postings and drafts applications; when the user
            # has enabled automatic sending, the queue is sent after the search is marked complete.
            cancelled = await self.should_stop()
            if not cancelled:
                await self._progress(96, "Looking for recruiter emails in matching jobs")
                from app.services.job_email_service import email_settings, prepare_for_jobs
                from app.models import User
                try:
                    u = await db.get(User, user_id)
                    self.stats.update(await prepare_for_jobs(db, u, run_job_ids))
                    auto_send = email_settings(u)["auto_send_enabled"]
                except Exception:  # noqa: BLE001 - email drafting must never fail a search
                    log.exception("application-email drafting failed")
                    await db.rollback()
                    auto_send = False
            else:
                auto_send = False

            # STEP 11-12 -------------------------------------------- finish
            self.stats["duration_seconds"] = round(time.monotonic() - t0, 1)
            self.stats["sources_ok"] = sum(1 for r in self.source_results.values() if r.get("status") == "ok")
            self.stats["sources_failed"] = sum(1 for r in self.source_results.values() if r.get("status") in ("error", "timeout", "blocked"))
            async with self.Session() as fdb:
                await fdb.execute(update(SearchSession).where(SearchSession.id == self.session_id).values(
                    status="cancelled" if cancelled else "completed", progress=100,
                    current_step="Stopped - partial results saved" if cancelled else "Search completed",
                    finished_at=datetime.now(timezone.utc), stats=self.stats, source_results=self.source_results))
                await fdb.commit()
            await self._log("info", ("Search stopped by user; partial results saved. " if cancelled else "Search completed. ")
                            + f"{self.stats.get('total_collected', 0)} postings collected, "
                            + f"{self.stats.get('matching_jobs', 0)} matching, {self.stats.get('new_jobs', 0)} new.")
            if auto_send:
                from app.services.job_email_service import process_auto_queue
                res = await process_auto_queue(self.Session, user_id)
                if res.get("sent") or res.get("failed"):
                    await self._log("info", f"Automatic application emails: {res['sent']} sent, {res['failed']} failed ({res['note']}).")

    async def _mark_unavailable(self, db: AsyncSession, listings: dict[tuple[str, int], set[str]]) -> int:
        """For complete ATS listings fetched successfully this run, postings that
        are no longer listed become unavailable."""
        expired = 0
        now = datetime.now(timezone.utc)
        for (source_key, company_id), ext_ids in listings.items():
            links = (await db.execute(
                select(JobSourceLink).join(Job, Job.id == JobSourceLink.job_id)
                .where(Job.company_id == company_id, JobSourceLink.source_key == source_key,
                       JobSourceLink.status == "active"))).scalars().all()
            for link in links:
                if link.external_id not in ext_ids:
                    link.status = "unavailable"
                    job = await db.get(Job, link.job_id)
                    if job and all(l.status != "active" or l.id == link.id for l in job.source_links):
                        job.status = "unavailable"
                        job.last_verified_at = now
                        expired += 1
        await db.flush()
        return expired

    async def _match(self, db: AsyncSession, user_id: int, profile_id: int, cand: CandidateView,
                     job_ids: set[int], weights: dict | None, min_score: float) -> dict[str, int]:
        existing = {m.job_id: m for m in (await db.execute(
            select(JobMatch).where(JobMatch.user_id == user_id))).unique().scalars().all()}
        # NEW flags only describe the latest run
        await db.execute(update(JobMatch).where(JobMatch.user_id == user_id).values(is_new=False))
        counts = {"matching_jobs": 0, "highly_relevant": 0, "small_company_jobs": 0, "medium_company_jobs": 0,
                  "new_jobs": 0, "official_jobs": 0}
        ids = sorted(job_ids)
        for i in range(0, len(ids), 200):
            jobs = (await db.execute(select(Job).where(Job.id.in_(ids[i:i + 200])))).unique().scalars().all()
            for job in jobs:
                r = score_job(cand, title=job.title, description=job.description or "",
                              job_skills=[s.canonical for s in job.skills], exp_min=job.experience_min_years,
                              exp_max=job.experience_max_years, location=job.location, work_mode=job.work_mode,
                              weights=weights)
                m = existing.get(job.id)
                is_new = m is None
                if m is None:
                    m = JobMatch(user_id=user_id, job_id=job.id)
                    db.add(m)
                    existing[job.id] = m
                m.profile_id, m.session_id, m.score, m.breakdown = profile_id, self.session_id, r.score, r.breakdown
                m.matched_skills, m.missing_skills, m.experience_fit = r.matched_skills, r.missing_skills, r.experience_fit
                m.explanation, m.gaps, m.is_new, m.computed_at = r.explanation, r.gaps, is_new, datetime.now(timezone.utc)
                if r.score >= min_score:
                    counts["matching_jobs"] += 1
                    counts["highly_relevant"] += r.score >= 75
                    size = job.company.size_category if job.company else None
                    counts["small_company_jobs"] += size == "small"
                    counts["medium_company_jobs"] += size == "medium"
                    counts["new_jobs"] += is_new
                    counts["official_jobs"] += bool(job.is_official)
            await db.flush()
        return {k: int(v) for k, v in counts.items()}


async def run_search(session_id: int, own_engine: bool = False) -> None:
    """Run a search. ``own_engine`` creates a DB engine bound to the current event
    loop (needed when running in a worker thread or a Celery ``asyncio.run``)."""
    if not own_engine:
        await SearchOrchestrator(session_id).run()
        return
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    engine = dbmod._make_engine(get_settings().database_url)
    try:
        await SearchOrchestrator(session_id, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)).run()
    finally:
        await engine.dispose()


def run_search_blocking(session_id: int) -> None:
    """Entry point for threads / Celery: a private event loop and DB engine."""
    asyncio.run(run_search(session_id, own_engine=True))
