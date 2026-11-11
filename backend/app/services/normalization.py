"""JobNormalizationService + JobExtractionService helpers.

Converts heterogeneous RawJob records into one common structure. Missing
values stay None (rendered as "Not specified") - nothing is guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.connectors.base import RawJob
from app.services import skills_taxonomy as tax
from app.services.text_utils import (
    detect_employment_type,
    detect_work_mode,
    format_salary,
    html_to_text,
    normalize_company,
    normalize_location,
    normalize_title,
    parse_experience_requirement,
    parse_salary_text,
    sha256,
)

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "source", "gh_src",
                   "lever-source", "lever-origin", "src", "trk", "refId", "trackingId"}


def canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        p = urlparse(url.strip())
    except ValueError:
        return None
    if p.scheme not in ("http", "https"):
        return None
    q = [(k, v) for k, v in parse_qsl(p.query) if k not in TRACKING_PARAMS and not k.startswith("utm_")]
    path = p.path.rstrip("/") or "/"
    return urlunparse(("https", p.netloc.lower().removeprefix("www."), path, "", urlencode(q), ""))


def safe_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    return url if urlparse(url).scheme in ("http", "https") else None


@dataclass
class NormalizedJob:
    raw: RawJob
    title: str
    normalized_title: str
    company_name: str
    normalized_company: str
    location: str | None
    normalized_location: str
    work_mode: str
    employment_type: str | None
    experience_min_years: float | None
    experience_max_years: float | None
    experience_text: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_period: str | None
    salary_text: str | None
    description: str
    description_hash: str
    apply_url: str | None
    canonical_url: str | None
    date_posted: datetime | None
    is_official: bool
    skills: list[tuple[str, str]] = field(default_factory=list)  # (canonical, category)
    company_size_stated: int | None = None
    company_type: str | None = None

    @property
    def fingerprint(self) -> str:
        return sha256(f"{self.normalized_title}|{self.normalized_company}|{_loc_key(self.normalized_location, self.work_mode)}")


def _loc_key(loc: str, mode: str) -> str:
    if mode == "remote" or not loc:
        return "remote" if mode == "remote" else ""
    return loc.split(",")[0].strip()


SIZE_RE = re.compile(
    r"(?:team of|we are|we're|company of|a group of|over|more than)\s+(\d{1,3}(?:,\d{3})*)\s*\+?\s*"
    r"(?:people|employees|engineers|teammates|team members|humans|staff)", re.I)
SIZE_RANGE_RE = re.compile(r"(\d{1,3}(?:,\d{3})*)\s*[-–]\s*(\d{1,3}(?:,\d{3})*)\s+employees", re.I)


def stated_company_size(text: str) -> int | None:
    """Only returns a size if the posting explicitly states it."""
    m = SIZE_RANGE_RE.search(text)
    if m:
        return int(m.group(2).replace(",", ""))
    m = SIZE_RE.search(text)
    if m:
        n = int(m.group(1).replace(",", ""))
        if 1 < n < 500000:
            return n
    return None


def detect_company_type(text: str) -> str | None:
    t = text.lower()
    if re.search(r"\b(ai|ml|llm|generative ai|machine learning)\b.{0,40}\b(startup|company)\b", t):
        return "AI startup"
    if re.search(r"\bremote[- ]first\b|\bfully remote company\b|\bdistributed company\b", t):
        return "Remote-first"
    if re.search(r"\b(seed|series [a-d]|y ?combinator|yc [sw]\d{2}|early[- ]stage)\b", t):
        return "Startup"
    if re.search(r"\b(saas|software as a service|b2b platform)\b", t):
        return "SaaS / Product"
    if re.search(r"\b(it services|consulting|outsourcing|client projects|service[- ]based|staff augmentation)\b", t):
        return "Service-based"
    if re.search(r"\bour (product|platform)\b", t):
        return "Product-based"
    return None


def normalize(raw: RawJob) -> NormalizedJob | None:
    title = re.sub(r"\s+", " ", html_to_text(raw.title or "")).strip()
    company = re.sub(r"\s+", " ", (raw.company_name or "")).strip()
    if not title or not company:
        return None
    desc = html_to_text(raw.description or "")
    exp = parse_experience_requirement(title, raw.experience_text or "", desc[:6000])
    exp_min, exp_max, exp_text = exp.min_years, exp.max_years, exp.text
    if raw.experience_min_months is not None:
        exp_min = round(raw.experience_min_months / 12, 1)
        exp_text = exp_text or f"{exp_min:g}+ years"

    smin, smax, cur, period, stext = raw.salary_min, raw.salary_max, raw.salary_currency, raw.salary_period, raw.salary_text
    if smin is None and smax is None:
        parsed = parse_salary_text(raw.salary_text) if raw.salary_text else parse_salary_text(None)
        if parsed.min is not None:
            smin, smax, cur, period = parsed.min, parsed.max, parsed.currency, parsed.period
    try:
        smin = float(smin) if smin not in (None, "", 0) else None
        smax = float(smax) if smax not in (None, "", 0) else None
    except (TypeError, ValueError):
        smin = smax = None
    if not stext:
        stext = format_salary(smin, smax, cur, period)

    work_mode = raw.work_mode or detect_work_mode(raw.location, title, remote_flag=raw.remote)
    if work_mode == "unknown":
        work_mode = detect_work_mode(raw.location, title, desc[:1500])
    location = raw.location.strip() if raw.location and raw.location.strip() else None
    apply_url = safe_url(raw.apply_url) or safe_url(raw.url)
    skills = [(s.canonical, s.category) for s in tax.extract_skills(f"{title}\n{desc}\n{' '.join(raw.tags or [])}")]
    return NormalizedJob(
        raw=raw, title=title[:300], normalized_title=normalize_title(title)[:300],
        company_name=company[:255], normalized_company=normalize_company(company)[:255],
        location=location[:300] if location else None, normalized_location=normalize_location(location),
        work_mode=work_mode, employment_type=raw.employment_type or detect_employment_type(title, desc[:2000]),
        experience_min_years=exp_min, experience_max_years=exp_max, experience_text=exp_text,
        salary_min=smin, salary_max=smax, salary_currency=cur, salary_period=period, salary_text=stext,
        description=desc[:30000], description_hash=sha256(desc[:30000]),
        apply_url=apply_url, canonical_url=canonical_url(apply_url), date_posted=raw.date_posted,
        is_official=raw.is_official, skills=skills,
        company_size_stated=stated_company_size(desc[:8000]),
        company_type=detect_company_type(desc[:8000]),
    )
