"""Official ATS job-board connectors.

These read the PUBLIC job-board APIs that companies expose via their applicant
tracking system specifically so job listings can be embedded/consumed. They are
official company sources (not third-party re-listings).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import httpx

from app.connectors.base import CompanyCareerConnector, RawJob, SearchContext
from app.services.http import PoliteHttp
from app.services.text_utils import html_to_text, parse_datetime


class GreenhouseConnector(CompanyCareerConnector):
    key = "greenhouse"
    name = "Greenhouse (official company boards)"
    base_url = "https://boards-api.greenhouse.io"
    notes = "Public Job Board API: boards-api.greenhouse.io/v1/boards/{token}/jobs"
    url_patterns = [
        re.compile(r"boards(?:-api)?\.greenhouse\.io/(?:v1/boards/|embed/job_board\?for=)?([A-Za-z0-9_-]+)", re.I),
        re.compile(r"job-boards(?:\.eu)?\.greenhouse\.io/([A-Za-z0-9_-]+)", re.I),
        re.compile(r"greenhouse\.io/embed/job_board(?:/js)?\?for=([A-Za-z0-9_-]+)", re.I),
    ]

    def board_url(self, slug: str) -> str:
        return f"https://job-boards.greenhouse.io/{slug}"

    async def fetch_company(self, http: PoliteHttp, slug: str, company_name: str | None, ctx: SearchContext) -> list[RawJob]:
        r = await http.get(f"{self.base_url}/v1/boards/{slug}/jobs", params={"content": "true"})
        if r.status_code == 404:
            return []
        r.raise_for_status()
        out = []
        for j in r.json().get("jobs", []):
            loc = (j.get("location") or {}).get("name")
            out.append(RawJob(
                source_key=self.key, source_name="Greenhouse",
                external_id=f"{slug}:{j['id']}", title=j.get("title", ""),
                company_name=j.get("company_name") or company_name or slug,
                description=j.get("content") or "", location=loc,
                apply_url=j.get("absolute_url"), url=j.get("absolute_url"),
                date_posted=parse_datetime(j.get("first_published") or j.get("updated_at")),
                is_official=True, ats_type=self.key, ats_slug=slug,
                company_careers_url=self.board_url(slug),
            ))
        return out


class LeverConnector(CompanyCareerConnector):
    key = "lever"
    name = "Lever (official company boards)"
    base_url = "https://api.lever.co"
    notes = "Public Postings API: api.lever.co/v0/postings/{company}?mode=json"
    url_patterns = [re.compile(r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_.-]+)", re.I)]

    def board_url(self, slug: str) -> str:
        return f"https://jobs.lever.co/{slug}"

    async def fetch_company(self, http: PoliteHttp, slug: str, company_name: str | None, ctx: SearchContext) -> list[RawJob]:
        r = await http.get(f"{self.base_url}/v0/postings/{slug}", params={"mode": "json"})
        if r.status_code == 404:
            r = await http.get(f"https://api.eu.lever.co/v0/postings/{slug}", params={"mode": "json"})
            if r.status_code == 404:
                return []
        r.raise_for_status()
        out = []
        for j in r.json():
            cats = j.get("categories") or {}
            desc = j.get("description") or j.get("descriptionPlain") or ""
            for lst in j.get("lists") or []:
                desc += f"<h3>{lst.get('text', '')}</h3><ul>{lst.get('content', '')}</ul>"
            desc += j.get("additional") or ""
            sal = j.get("salaryRange") or {}
            wt = (j.get("workplaceType") or "").lower()
            out.append(RawJob(
                source_key=self.key, source_name="Lever",
                external_id=f"{slug}:{j['id']}", title=j.get("text", ""),
                company_name=company_name or slug, description=desc,
                location=cats.get("location") or ", ".join(cats.get("allLocations") or []) or None,
                apply_url=j.get("applyUrl") or j.get("hostedUrl"), url=j.get("hostedUrl"),
                date_posted=parse_datetime(j.get("createdAt")),
                work_mode={"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}.get(wt),
                employment_type=cats.get("commitment"),
                salary_min=sal.get("min"), salary_max=sal.get("max"), salary_currency=sal.get("currency"),
                salary_period=(sal.get("interval") or "").replace("per-", "") or None,
                is_official=True, ats_type=self.key, ats_slug=slug, company_careers_url=self.board_url(slug),
            ))
        return out


class AshbyConnector(CompanyCareerConnector):
    key = "ashby"
    name = "Ashby (official company boards)"
    base_url = "https://api.ashbyhq.com"
    notes = "Public Job Posting API: api.ashbyhq.com/posting-api/job-board/{name}"
    url_patterns = [re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)", re.I)]

    def board_url(self, slug: str) -> str:
        return f"https://jobs.ashbyhq.com/{slug}"

    async def fetch_company(self, http: PoliteHttp, slug: str, company_name: str | None, ctx: SearchContext) -> list[RawJob]:
        r = await http.get(f"{self.base_url}/posting-api/job-board/{slug}", params={"includeCompensation": "true"})
        if r.status_code == 404:
            return []
        r.raise_for_status()
        out = []
        for j in r.json().get("jobs", []):
            if j.get("isListed") is False:
                continue
            comp = j.get("compensation") or {}
            smin = smax = cur = period = None
            for c in comp.get("summaryComponents") or []:
                if c.get("compensationType") == "Salary":
                    smin, smax, cur = c.get("minValue"), c.get("maxValue"), c.get("currencyCode")
                    period = (c.get("interval") or "").replace("1 ", "").lower() or None
            wt = (j.get("workplaceType") or "").lower()
            out.append(RawJob(
                source_key=self.key, source_name="Ashby",
                external_id=f"{slug}:{j['id']}", title=j.get("title", ""),
                company_name=company_name or slug,
                description=j.get("descriptionHtml") or j.get("descriptionPlain") or "",
                location=j.get("location"), apply_url=j.get("applyUrl") or j.get("jobUrl"), url=j.get("jobUrl"),
                date_posted=parse_datetime(j.get("publishedAt")),
                remote=j.get("isRemote"),
                work_mode={"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}.get(wt),
                employment_type=j.get("employmentType"),
                salary_min=smin, salary_max=smax, salary_currency=cur, salary_period=period,
                salary_text=comp.get("compensationTierSummary"),
                is_official=True, ats_type=self.key, ats_slug=slug, company_careers_url=self.board_url(slug),
            ))
        return out


class SmartRecruitersConnector(CompanyCareerConnector):
    key = "smartrecruiters"
    name = "SmartRecruiters (official company boards)"
    base_url = "https://api.smartrecruiters.com"
    notes = "Public Posting API: api.smartrecruiters.com/v1/companies/{id}/postings"
    url_patterns = [re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I)]
    max_details = 40

    def board_url(self, slug: str) -> str:
        return f"https://careers.smartrecruiters.com/{slug}"

    async def fetch_company(self, http: PoliteHttp, slug: str, company_name: str | None, ctx: SearchContext) -> list[RawJob]:
        r = await http.get(f"{self.base_url}/v1/companies/{slug}/postings", params={"limit": 100})
        if r.status_code == 404:
            return []
        r.raise_for_status()
        data = r.json()
        from app.connectors.base import is_tech_job
        out = []
        details = 0
        for j in data.get("content", []):
            loc = j.get("location") or {}
            title = j.get("name", "")
            desc = ""
            if is_tech_job(title) and details < self.max_details:
                details += 1
                try:
                    d = await http.get_json(f"{self.base_url}/v1/companies/{slug}/postings/{j['id']}")
                    secs = ((d.get("jobAd") or {}).get("sections") or {})
                    desc = "\n".join((secs.get(k) or {}).get("text", "") for k in
                                     ("jobDescription", "qualifications", "additionalInformation", "companyDescription"))
                except (httpx.HTTPError, ValueError):
                    pass
            loc_str = ", ".join(x for x in [loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()] if x)
            url = f"https://jobs.smartrecruiters.com/{slug}/{j['id']}"
            out.append(RawJob(
                source_key=self.key, source_name="SmartRecruiters",
                external_id=f"{slug}:{j['id']}", title=title,
                company_name=(j.get("company") or {}).get("name") or company_name or slug,
                description=desc, location=loc_str or None, apply_url=url, url=url,
                date_posted=parse_datetime(j.get("releasedDate")),
                remote=loc.get("remote"), work_mode="hybrid" if loc.get("hybrid") else None,
                employment_type=(j.get("typeOfEmployment") or {}).get("label"),
                experience_text=(j.get("experienceLevel") or {}).get("label"),
                is_official=True, ats_type=self.key, ats_slug=slug, company_careers_url=self.board_url(slug),
            ))
        return out


class WorkableConnector(CompanyCareerConnector):
    key = "workable"
    name = "Workable (official company boards)"
    base_url = "https://apply.workable.com"
    notes = "Public widget API: apply.workable.com/api/v1/widget/accounts/{subdomain}"
    url_patterns = [re.compile(r"apply\.workable\.com/([A-Za-z0-9_-]+)", re.I),
                    re.compile(r"([A-Za-z0-9_-]+)\.workable\.com", re.I)]

    def board_url(self, slug: str) -> str:
        return f"https://apply.workable.com/{slug}/"

    async def fetch_company(self, http: PoliteHttp, slug: str, company_name: str | None, ctx: SearchContext) -> list[RawJob]:
        r = await http.get(f"{self.base_url}/api/v1/widget/accounts/{slug}", params={"details": "true"})
        if r.status_code == 404:
            return []
        r.raise_for_status()
        data = r.json()
        out = []
        for j in data.get("jobs", []):
            loc = ", ".join(x for x in [j.get("city"), j.get("state"), j.get("country")] if x) or None
            out.append(RawJob(
                source_key=self.key, source_name="Workable",
                external_id=f"{slug}:{j.get('shortcode') or j.get('code')}", title=j.get("title", ""),
                company_name=data.get("name") or company_name or slug,
                description=j.get("description") or "", location=loc,
                apply_url=j.get("application_url") or j.get("url"), url=j.get("url") or j.get("shortlink"),
                date_posted=parse_datetime(j.get("published_on") or j.get("created_at")),
                remote=j.get("telecommuting"), employment_type=j.get("employment_type"),
                is_official=True, ats_type=self.key, ats_slug=slug, company_careers_url=self.board_url(slug),
            ))
        return out


class RecruiteeConnector(CompanyCareerConnector):
    key = "recruitee"
    name = "Recruitee (official company boards)"
    base_url = "https://{slug}.recruitee.com"
    notes = "Public Careers Site API: {company}.recruitee.com/api/offers/"
    url_patterns = [re.compile(r"([A-Za-z0-9_-]+)\.recruitee\.com", re.I)]

    def board_url(self, slug: str) -> str:
        return f"https://{slug}.recruitee.com/"

    async def fetch_company(self, http: PoliteHttp, slug: str, company_name: str | None, ctx: SearchContext) -> list[RawJob]:
        r = await http.get(f"https://{slug}.recruitee.com/api/offers/")
        if r.status_code == 404:
            return []
        r.raise_for_status()
        out = []
        for j in r.json().get("offers", []):
            sal = j.get("salary") or {}
            out.append(RawJob(
                source_key=self.key, source_name="Recruitee",
                external_id=f"{slug}:{j['id']}", title=j.get("title", ""),
                company_name=j.get("company_name") or company_name or slug,
                description=(j.get("description") or "") + (j.get("requirements") or ""),
                location=j.get("location"), apply_url=j.get("careers_apply_url") or j.get("careers_url"),
                url=j.get("careers_url"), date_posted=parse_datetime(j.get("published_at") or j.get("created_at")),
                remote=j.get("remote"), work_mode="hybrid" if j.get("hybrid") else None,
                employment_type=j.get("employment_type_code"),
                salary_min=_f(sal.get("min")), salary_max=_f(sal.get("max")), salary_currency=sal.get("currency"),
                salary_period=sal.get("period"),
                is_official=True, ats_type=self.key, ats_slug=slug, company_careers_url=self.board_url(slug),
            ))
        return out


class PersonioConnector(CompanyCareerConnector):
    key = "personio"
    name = "Personio (official company boards)"
    base_url = "https://{slug}.jobs.personio.de"
    notes = "Public XML feed: {company}.jobs.personio.de/xml"
    url_patterns = [re.compile(r"([A-Za-z0-9_-]+)\.jobs\.personio\.(?:de|com)", re.I)]

    def board_url(self, slug: str) -> str:
        return f"https://{slug}.jobs.personio.de/"

    async def fetch_company(self, http: PoliteHttp, slug: str, company_name: str | None, ctx: SearchContext) -> list[RawJob]:
        r = await http.get(f"https://{slug}.jobs.personio.de/xml", params={"language": "en"})
        if r.status_code == 404:
            return []
        r.raise_for_status()
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            return []
        out = []
        for pos in root.findall("position"):
            pid = pos.findtext("id")
            desc = "".join(f"<h3>{d.findtext('name') or ''}</h3>{d.findtext('value') or ''}"
                           for d in pos.findall("jobDescriptions/jobDescription"))
            url = f"https://{slug}.jobs.personio.de/job/{pid}"
            out.append(RawJob(
                source_key=self.key, source_name="Personio",
                external_id=f"{slug}:{pid}", title=pos.findtext("name") or "",
                company_name=company_name or pos.findtext("subcompany") or slug,
                description=desc, location=pos.findtext("office"), apply_url=url, url=url,
                date_posted=parse_datetime(pos.findtext("createdAt")),
                employment_type=pos.findtext("schedule"),
                is_official=True, ats_type=self.key, ats_slug=slug, company_careers_url=self.board_url(slug),
            ))
        return out


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


ATS_CONNECTORS: dict[str, CompanyCareerConnector] = {
    c.key: c for c in [
        GreenhouseConnector(), LeverConnector(), AshbyConnector(), SmartRecruitersConnector(),
        WorkableConnector(), RecruiteeConnector(), PersonioConnector(),
    ]
}


def detect_ats(url: str) -> tuple[str, str] | None:
    """Return (ats_key, slug) if the URL points to a known ATS board."""
    for key, c in ATS_CONNECTORS.items():
        slug = c.detect(url)
        if slug:
            return key, slug
    return None
