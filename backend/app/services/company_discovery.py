"""CompanyDiscoveryService + company database helpers.

Companies are discovered continuously (never restricted to a fixed list):
  1. Every company seen in any job source result (with its website / ATS link).
  2. Hacker News "Who is hiring" posts (companies post themselves; many small firms).
  3. Search-engine discovery of ATS boards and career pages (Brave / SerpAPI, if keyed).
  4. ATS slug probing: for a newly discovered company, check whether it has a
     public Greenhouse / Lever / Ashby / Workable board.
  5. Career-page detection from the company homepage (robots.txt respected).
A small set of verified ATS boards bootstraps an empty database.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.connectors.ats import ATS_CONNECTORS, detect_ats
from app.connectors.base import RawJob, SearchContext
from app.connectors.registry import GENERIC_CAREER
from app.models import Company, CompanyCareerPage
from app.services.http import PoliteHttp
from app.services.text_utils import normalize_company

log = logging.getLogger(__name__)

# Verified public ATS boards used ONLY to bootstrap an empty company database.
SEED_BOARDS: dict[str, list[str]] = {
    "greenhouse": ["razorpaysoftwareprivatelimited", "groww", "hackerrank", "druva", "slice", "cockroachlabs",
                   "planetscale", "netlify", "contentful", "pagerduty", "newrelic", "discord", "dropbox", "vercel",
                   "grafanalabs", "mercury", "duolingo", "chime", "fivetran", "airtable", "gitlab", "anthropic",
                   "cloudflare", "databricks", "stripe", "figma", "mongodb", "elastic", "twilio", "okta"],
    "lever": ["cred", "meesho", "paytm", "fi", "mindtickle", "zeta", "outreach", "palantir", "spotify"],
    "ashby": ["sarvam", "langchain", "pinecone", "weaviate", "posthog", "modal", "replit", "linear", "resend",
              "mintlify", "llamaindex", "infisical", "plane", "composio", "e2b", "unstructured", "vapi", "clerk",
              "airbyte", "prefect", "astronomer", "baseten", "fireworks", "writer", "lovable", "cursor",
              "deepgram", "perplexity", "cohere", "notion", "ramp", "elevenlabs", "openai", "zapier", "snyk"],
    "workable": ["huggingface"],
    "recruitee": ["channable", "bunq"],
    "smartrecruiters": ["Experian", "ServiceNow"],
}

IGNORED_DOMAINS = re.compile(
    r"(news\.ycombinator|linkedin\.com|twitter\.com|x\.com|github\.com|google\.|youtube\.|facebook\.|"
    r"medium\.com|notion\.site|docs\.google|bit\.ly|t\.co|calendly|forms\.gle|typeform|wikipedia|"
    r"remoteok|remotive|himalayas|jobicy|arbeitnow|indeed|glassdoor|naukri|adzuna|jooble|apify)", re.I)


def size_category(employees: int | None, small_max: int | None = None, medium_max: int | None = None) -> str | None:
    if employees is None:
        return None
    s = get_settings()
    small_max = small_max or s.small_company_max
    medium_max = medium_max or s.medium_company_max
    if employees <= small_max:
        return "small"
    if employees <= medium_max:
        return "medium"
    return "large"


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    if not url.startswith("http"):
        url = "https://" + url
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
    except ValueError:
        return None
    if not host or IGNORED_DOMAINS.search(host) or detect_ats(url):
        return None
    return host


def slug_candidates(name: str) -> list[str]:
    n = normalize_company(name)
    full = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
    out = []
    for s in [n.replace(" ", ""), n.replace(" ", "-"), full]:
        if s and len(s) >= 2 and s not in out:
            out.append(s)
    return out[:2]


async def upsert_company(db: AsyncSession, *, name: str, website: str | None = None, logo: str | None = None,
                         ats_type: str | None = None, ats_slug: str | None = None, careers_url: str | None = None,
                         discovered_via: str | None = None, employees: int | None = None,
                         size_source: str | None = None, company_type: str | None = None,
                         cache: dict[str, Company] | None = None) -> Company | None:
    norm = normalize_company(name)
    if not norm:
        return None
    if cache is not None and norm in cache:
        c = cache[norm]
    else:
        c = (await db.execute(select(Company).where(Company.normalized_name == norm))).scalar_one_or_none()
        if c is None:
            dom = domain_of(website)
            if dom:
                c = (await db.execute(select(Company).where(Company.domain == dom))).scalars().first()
    if c is None:
        c = Company(name=name.strip()[:255], normalized_name=norm[:255], discovered_via=discovered_via)
        db.add(c)
    dom = domain_of(website)
    if dom and not c.domain:
        c.domain, c.website = dom, f"https://{dom}"
    if logo and not c.logo_url and logo.startswith("http"):
        c.logo_url = logo[:512]
    if ats_type and ats_slug and (not c.ats_type or c.ats_type == "none"):
        c.ats_type, c.ats_slug = ats_type, ats_slug
    if careers_url and not c.careers_url:
        c.careers_url = careers_url[:512]
    if employees and (c.employee_count is None or c.size_source != "user"):
        c.employee_count = employees
        c.size_category = size_category(employees)
        c.size_source = size_source or "stated in job posting"
    if company_type and not c.company_type:
        c.company_type = company_type
    if cache is not None:
        cache[norm] = c
    return c


class CompanyDiscoveryService:
    def __init__(self, db: AsyncSession, http: PoliteHttp, ctx: SearchContext):
        self.db, self.http, self.ctx = db, http, ctx
        self.s = get_settings()
        self.cache: dict[str, Company] = {}
        self.discovered = 0

    async def bootstrap(self) -> int:
        count = (await self.db.execute(select(Company.id).where(Company.ats_type.in_(list(ATS_CONNECTORS))).limit(5))).all()
        if len(count) >= 5:
            return 0
        n = 0
        for ats, slugs in SEED_BOARDS.items():
            for slug in slugs:
                if await upsert_company(self.db, name=slug, ats_type=ats, ats_slug=slug,
                                        careers_url=ATS_CONNECTORS[ats].board_url(slug),
                                        discovered_via="seed (verified ATS board)", cache=self.cache):
                    n += 1
        await self.db.flush()
        return n

    async def from_raw_jobs(self, raws: list[RawJob]) -> int:
        """Register every company that appears in source results."""
        before = len(self.cache)
        for r in raws:
            links = [r.apply_url or "", r.url or "", r.company_careers_url or "", *(r.extra.get("links") or [])]
            ats = None
            for l in links:
                ats = detect_ats(l) if l else None
                if ats:
                    break
            website = r.company_website or next((l for l in r.extra.get("links") or [] if domain_of(l)), None)
            await upsert_company(
                self.db, name=r.company_name, website=website, logo=r.company_logo,
                ats_type=ats[0] if ats else r.ats_type, ats_slug=ats[1] if ats else r.ats_slug,
                careers_url=r.company_careers_url, discovered_via=r.source_name, cache=self.cache,
            )
        await self.db.flush()
        self.discovered += len(self.cache) - before
        return len(self.cache) - before

    async def via_search_engine(self) -> int:
        """Discover ATS boards / career pages with a search API (Brave or SerpAPI)."""
        if not (self.s.brave_search_api_key or self.s.serpapi_key):
            return 0
        queries = []
        for kw in self.ctx.keywords[:3]:
            for site in ("jobs.lever.co", "job-boards.greenhouse.io", "jobs.ashbyhq.com", "apply.workable.com"):
                loc = f" {self.ctx.locations[0]}" if self.ctx.locations else ""
                queries.append(f'site:{site} "{kw}"{loc}')
        found = 0
        for q in queries:
            if await self.ctx.stopped():
                break
            try:
                urls = await self._search(q)
            except Exception as e:  # noqa: BLE001
                await self.ctx.warn(f"search discovery failed: {e}", "company_discovery")
                break
            for u in urls:
                ats = detect_ats(u)
                if ats:
                    c = await upsert_company(self.db, name=ats[1], ats_type=ats[0], ats_slug=ats[1],
                                             careers_url=ATS_CONNECTORS[ats[0]].board_url(ats[1]),
                                             discovered_via="search engine", cache=self.cache)
                    if c is not None and c.id is None:
                        found += 1
        await self.db.flush()
        self.discovered += found
        return found

    async def _search(self, q: str) -> list[str]:
        if self.s.brave_search_api_key:
            r = await self.http.get("https://api.search.brave.com/res/v1/web/search", params={"q": q, "count": 20},
                                    headers={"X-Subscription-Token": self.s.brave_search_api_key, "Accept": "application/json"})
            r.raise_for_status()
            return [x.get("url", "") for x in (r.json().get("web") or {}).get("results", [])]
        r = await self.http.get("https://serpapi.com/search.json", params={"engine": "google", "q": q, "num": 20, "api_key": self.s.serpapi_key})
        r.raise_for_status()
        return [x.get("link", "") for x in r.json().get("organic_results", [])]

    async def probe_ats(self, limit: int = 30) -> int:
        """For companies without a known board, check if they publish one on a common ATS."""
        stale = datetime.now(timezone.utc) - timedelta(days=30)
        rows = (await self.db.execute(
            select(Company).where(Company.ats_type.is_(None))
            .where(or_(Company.last_checked_at.is_(None), Company.last_checked_at < stale))
            .order_by(Company.first_discovered_at.desc()).limit(limit)
        )).scalars().all()
        # network probing runs concurrently; DB updates are applied sequentially afterwards
        sem = asyncio.Semaphore(8)

        async def probe(c: Company):
            async with sem:
                if await self.ctx.stopped():
                    return c, None, None, "stopped"
                try:
                    return await asyncio.wait_for(self._probe_one(c.name, c.normalized_name, c.domain), 45)
                except Exception:  # noqa: BLE001 - slow/broken sites are simply skipped
                    return c, None, None, "error"

        results = await asyncio.gather(*(probe(c) for c in rows))
        found = 0
        now = datetime.now(timezone.utc)
        for c, (ats, careers, status) in zip(rows, [(r[1], r[2], r[3]) for r in results]):
            if status == "stopped":
                continue
            if ats:
                c.ats_type, c.ats_slug = ats
                c.careers_url = c.careers_url or (careers or ATS_CONNECTORS[ats[0]].board_url(ats[1]))
                found += 1
            elif careers:
                c.careers_url = careers[:512]
            else:
                c.ats_type = "none"
            if careers:
                await self._add_career_page(c, careers, ats)
            c.last_checked_at = now
        await self.db.flush()
        return found

    async def _probe_one(self, name: str, norm: str, domain: str | None):
        for slug in slug_candidates(name):
            for ats in ("greenhouse", "lever", "ashby"):
                try:
                    jobs = await ATS_CONNECTORS[ats].fetch_company(self.http, slug, name, self.ctx)
                except Exception:  # noqa: BLE001
                    continue
                if jobs and normalize_company(jobs[0].company_name) in (norm, normalize_company(slug)):
                    return None, (ats, slug), None, "ok"
        if domain:
            careers, ats = await GENERIC_CAREER.find_careers_url(self.http, domain)
            return None, ats, careers, "ok"
        return None, None, None, "ok"

    async def _add_career_page(self, c: Company, url: str, ats: tuple[str, str] | None) -> None:
        exists = (await self.db.execute(select(CompanyCareerPage).where(CompanyCareerPage.url == url[:1024]))).scalar_one_or_none()
        if not exists:
            self.db.add(CompanyCareerPage(company_id=c.id, url=url[:1024],
                                          page_type="ats_api" if ats else "html",
                                          ats_type=ats[0] if ats else None))

    async def companies_to_crawl(self, sizes: list[str] | None, limit: int) -> list[Company]:
        """Pick companies to check this run: never-checked first, then least recently
        checked; small/medium/unknown-size companies are prioritised."""
        q = select(Company).where(
            or_(Company.ats_type.in_(list(ATS_CONNECTORS)), Company.careers_url.is_not(None))
        )
        rows = (await self.db.execute(q)).scalars().all()
        allowed = set(sizes or ["small", "medium", "large", "unknown"])
        rows = [c for c in rows if (c.size_category or "unknown") in allowed]
        prio = {"small": 0, "medium": 1, None: 2, "large": 3}
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

        def key(c: Company):
            checked = c.last_checked_at or epoch
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=timezone.utc)
            return (checked, prio.get(c.size_category, 2))
        rows.sort(key=key)
        return rows[:limit]
