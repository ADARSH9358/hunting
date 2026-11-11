"""Common connector interface.

Two connector families:
* ``JobSourceConnector`` - keyword searches against a job board / aggregator API.
* ``CompanyCareerConnector`` - fetches the full official job list of ONE company
  (ATS boards like Greenhouse/Lever/Ashby, or a generic career page).
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.services.http import PoliteHttp


@dataclass
class RawJob:
    source_key: str
    source_name: str
    external_id: str
    title: str
    company_name: str
    description: str = ""  # html or text
    location: str | None = None
    apply_url: str | None = None
    url: str | None = None
    date_posted: datetime | None = None
    remote: bool | None = None
    work_mode: str | None = None
    employment_type: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    salary_text: str | None = None
    experience_text: str | None = None
    experience_min_months: int | None = None
    company_website: str | None = None
    company_logo: str | None = None
    company_careers_url: str | None = None
    ats_type: str | None = None
    ats_slug: str | None = None
    is_official: bool = False
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchContext:
    keywords: list[str]
    locations: list[str] = field(default_factory=list)
    remote_preference: str = "any"
    countries: list[str] = field(default_factory=list)
    candidate_skills: list[str] = field(default_factory=list)
    posted_within_days: int = 30
    max_results_per_source: int = 200
    log: Callable[[str, str, str | None], Awaitable[None]] | None = None
    should_stop: Callable[[], Awaitable[bool]] | None = None

    async def info(self, msg: str, source: str | None = None) -> None:
        if self.log:
            await self.log("info", msg, source)

    async def warn(self, msg: str, source: str | None = None) -> None:
        if self.log:
            await self.log("warning", msg, source)

    async def stopped(self) -> bool:
        return bool(self.should_stop and await self.should_stop())


class ConnectorNotConfigured(Exception):
    pass


class BaseConnector(ABC):
    key: str = ""
    name: str = ""
    kind: str = "job_board_api"  # job_board_api | aggregator | ats | career_page | licensed | portal
    base_url: str | None = None
    is_official_company_source: bool = False
    requires_credentials: bool = False
    # Whether a successful fetch returns the COMPLETE current listing (lets us
    # mark jobs that disappeared as unavailable).
    complete_listing: bool = False
    notes: str = ""
    host_rate_per_sec: dict[str, float] = {}

    def is_configured(self) -> bool:
        return True

    def status(self) -> str:
        return "available" if self.is_configured() else "needs_credentials"


class JobSourceConnector(BaseConnector):
    @abstractmethod
    async def search(self, http: PoliteHttp, ctx: SearchContext) -> list[RawJob]:
        ...


class CompanyCareerConnector(BaseConnector):
    kind = "ats"
    is_official_company_source = True
    complete_listing = True
    # regex to detect this ATS in a URL and capture the board slug
    url_patterns: list[re.Pattern] = []

    @abstractmethod
    async def fetch_company(self, http: PoliteHttp, slug: str, company_name: str | None,
                            ctx: SearchContext) -> list[RawJob]:
        ...

    def detect(self, url: str) -> str | None:
        for p in self.url_patterns:
            m = p.search(url)
            if m:
                slug = m.group(1)
                if slug.lower() not in {"embed", "api", "v1", "jobs", "www", "boards", "job-board", "careers", "apply", "app", "help", "blog"}:
                    return slug
        return None

    def board_url(self, slug: str) -> str:
        return ""


TECH_TITLE = re.compile(
    r"engineer|developer|programmer|software|backend|back-end|frontend|front-end|full[- ]?stack|"
    r"devops|sre|site reliability|data scien|data engineer|machine learning|\bml\b|\bai\b|\bllm|"
    r"genai|gen ai|platform|cloud|architect|mlops|qa |test automation|sdet|python|java|golang|node|react|"
    r"mobile|android|ios|web|analytics engineer|research scientist|infrastructure",
    re.I,
)


def is_tech_job(title: str, description: str = "", candidate_skills: list[str] | None = None) -> bool:
    if TECH_TITLE.search(title or ""):
        return True
    if candidate_skills:
        from app.services.skills_taxonomy import extract_skills
        found = {s.canonical for s in extract_skills(f"{title} {description[:3000]}")}
        return len(found & set(candidate_skills)) >= 3
    return False


def keyword_match(job_text: str, keywords: list[str]) -> bool:
    """Keyword relevance with word boundaries (all significant words of a keyword must appear)."""
    generic = {"developer", "engineer", "senior", "junior", "lead", "the", "and", "of"}
    for kw in keywords:
        words = [w for w in re.findall(r"[a-z0-9+#.]+", kw.lower()) if w not in generic]
        if words and all(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", job_text, re.I) for w in words):
            return True
    return False


def is_relevant(ctx: "SearchContext", title: str, text: str = "") -> bool:
    """Keep a posting if its TITLE matches a search keyword, or it is a tech role whose
    description mentions at least two of the candidate's skills."""
    if keyword_match(title, ctx.keywords):
        return True
    if not TECH_TITLE.search(title or ""):
        return False
    if not ctx.candidate_skills:
        return True
    from app.services.skills_taxonomy import extract_skills
    found = {s.canonical for s in extract_skills(f"{title} {text[:5000]}")}
    return len(found & set(ctx.candidate_skills)) >= 2
