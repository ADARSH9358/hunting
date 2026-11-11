"""JobDeduplicationService: one Job row per real opening, many source links.

Duplicate detection, in order:
  1. same (source, external id)              -> same posting re-seen
  2. same fingerprint (title|company|location)
  3. same canonical application URL
  4. same company + very similar title + similar description (shingle Jaccard)

Lookups for 1-3 are prefetched per chunk with IN queries so large runs stay fast.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from rapidfuzz import fuzz
from sqlalchemy import or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Job, JobSkill, JobSourceLink
from app.services.normalization import NormalizedJob
from app.services.text_utils import jaccard, shingles


@dataclass
class UpsertResult:
    new_ids: set[int] = field(default_factory=set)
    seen_ids: set[int] = field(default_factory=set)
    merged_duplicates: int = 0


def _better(existing: Job, nj: NormalizedJob) -> bool:
    """Prefer official company data, then substantially longer descriptions."""
    if nj.is_official and not existing.is_official:
        return True
    return nj.is_official == existing.is_official and len(nj.description) > len(existing.description or "") * 1.3


def _apply(job: Job, nj: NormalizedJob, overwrite: bool) -> None:
    fields = {
        "title": nj.title, "normalized_title": nj.normalized_title, "location": nj.location,
        "normalized_location": nj.normalized_location, "employment_type": nj.employment_type,
        "experience_min_years": nj.experience_min_years, "experience_max_years": nj.experience_max_years,
        "experience_text": nj.experience_text, "salary_min": nj.salary_min, "salary_max": nj.salary_max,
        "salary_currency": nj.salary_currency, "salary_period": nj.salary_period, "salary_text": nj.salary_text,
        "description": nj.description, "description_hash": nj.description_hash, "apply_url": nj.apply_url,
        "canonical_url": nj.canonical_url, "date_posted": nj.date_posted,
        "company_careers_url": nj.raw.company_careers_url,
    }
    for k, v in fields.items():
        cur = getattr(job, k)
        if (overwrite and v not in (None, "")) or (cur in (None, "") and v not in (None, "")):
            setattr(job, k, v)
    if job.work_mode in (None, "unknown") or (overwrite and nj.work_mode != "unknown"):
        job.work_mode = nj.work_mode
    if nj.is_official:
        job.is_official = True


class CompanyJobIndex:
    """Lightweight (id, title, hash) index of a company's existing jobs for fuzzy matching."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.rows: dict[int, list[list]] = {}

    async def _get(self, company_id: int) -> list[list]:
        if company_id not in self.rows:
            res = await self.db.execute(select(Job.id, Job.normalized_title, Job.description_hash)
                                        .where(Job.company_id == company_id).limit(2000))
            self.rows[company_id] = [list(r) for r in res.all()]
        return self.rows[company_id]

    def add(self, company_id: int, job: Job) -> None:
        if company_id in self.rows:
            self.rows[company_id].append([job.id, job.normalized_title, job.description_hash])

    async def find(self, company_id: int, nj: NormalizedJob) -> int | None:
        sh = None
        for jid, title, dhash in await self._get(company_id):
            if fuzz.token_set_ratio(title or "", nj.normalized_title) < 92:
                continue
            if dhash and dhash == nj.description_hash:
                return jid
            desc = (await self.db.execute(select(Job.description).where(Job.id == jid))).scalar_one_or_none()
            sh = sh or shingles(nj.description)
            if jaccard(sh, shingles(desc or "")) >= 0.75:
                return jid
        return None


async def upsert_jobs(db: AsyncSession, items: list[tuple[NormalizedJob, Company | None]], session_id: int,
                      source_ids: dict[str, int], company_index: CompanyJobIndex | None = None) -> UpsertResult:
    res = UpsertResult()
    now = datetime.now(timezone.utc)
    cidx = company_index or CompanyJobIndex(db)

    # ---- prefetch everything this chunk could collide with
    keys = {(nj.raw.source_key, nj.raw.external_id[:512]) for nj, _ in items}
    links: dict[tuple[str, str], JobSourceLink] = {}
    if keys:
        for l in (await db.execute(select(JobSourceLink).where(
                tuple_(JobSourceLink.source_key, JobSourceLink.external_id).in_(list(keys))))).scalars().all():
            links[(l.source_key, l.external_id)] = l
    fps = {nj.fingerprint for nj, _ in items}
    urls = {nj.canonical_url for nj, _ in items if nj.canonical_url}
    conds = [Job.fingerprint.in_(fps)]
    if links:
        conds.append(Job.id.in_({l.job_id for l in links.values()}))
    if urls:
        conds.append(Job.canonical_url.in_(urls))
    jobs_by_id: dict[int, Job] = {}
    by_fp: dict[str, Job] = {}
    by_url: dict[str, Job] = {}
    for j in (await db.execute(select(Job).where(or_(*conds)))).unique().scalars().all():
        jobs_by_id[j.id] = j
        by_fp[j.fingerprint] = j
        if j.canonical_url:
            by_url.setdefault(j.canonical_url, j)

    for nj, company in items:
        raw = nj.raw
        ext_id = raw.external_id[:512]
        link = links.get((raw.source_key, ext_id))
        job: Job | None = jobs_by_id.get(link.job_id) if link else None
        if job is None:
            job = by_fp.get(nj.fingerprint)
        if job is None and nj.canonical_url:
            job = by_url.get(nj.canonical_url)
        if job is None and company is not None and company.id is not None:
            jid = await cidx.find(company.id, nj)
            if jid is not None:
                job = jobs_by_id.get(jid) or await db.get(Job, jid)
                if job is not None:
                    jobs_by_id[job.id] = job

        if job is None:
            job = Job(fingerprint=nj.fingerprint, company_id=company.id if company else None,
                      company_name=nj.company_name, first_seen_at=now, first_seen_session_id=session_id,
                      is_official=nj.is_official, status="active", work_mode=nj.work_mode,
                      skills=[JobSkill(canonical=c, category=cat) for c, cat in dict(nj.skills).items()],
                      source_links=[])
            _apply(job, nj, overwrite=True)
            db.add(job)
            await db.flush()
            res.new_ids.add(job.id)
            jobs_by_id[job.id] = job
            if company is not None and company.id is not None:
                cidx.add(company.id, job)
        else:
            if link is None:
                res.merged_duplicates += 1
            overwrite = _better(job, nj)
            _apply(job, nj, overwrite=overwrite)
            if overwrite:
                existing = {s.canonical for s in job.skills}
                for canon, cat in nj.skills:
                    if canon not in existing:
                        job.skills.append(JobSkill(canonical=canon, category=cat))
                        existing.add(canon)
            if job.company_id is None and company is not None:
                job.company_id = company.id
        job.last_seen_at = now
        job.status = "active"
        if raw.is_official:
            job.last_verified_at = now
        by_fp[nj.fingerprint] = job
        if nj.canonical_url:
            by_url[nj.canonical_url] = job

        if link is None:
            link = JobSourceLink(source_id=source_ids.get(raw.source_key), source_key=raw.source_key,
                                 source_name=raw.source_name, external_id=ext_id,
                                 url=(raw.url or raw.apply_url or "")[:2048] or None, is_official=raw.is_official,
                                 first_seen_at=now)
            job.source_links.append(link)
            links[(raw.source_key, ext_id)] = link
        link.last_seen_at = now
        link.status = "active"
        if job.id not in res.new_ids:
            res.seen_ids.add(job.id)
    await db.flush()
    return res
