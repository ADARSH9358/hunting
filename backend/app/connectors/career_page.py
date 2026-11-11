"""GenericCareerPageConnector: crawls a company's own careers page.

Strategy (most to least structured):
1. If the page embeds / links to a known ATS board -> hand off to the ATS API.
2. Parse schema.org ``JobPosting`` JSON-LD (the format companies publish for
   Google for Jobs) on the careers page and on linked job-detail pages.
3. Optional Playwright rendering for JS-only pages (if installed & enabled).

robots.txt is honoured for every HTML page fetched.
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.connectors.ats import detect_ats
from app.connectors.base import CompanyCareerConnector, RawJob, SearchContext, is_tech_job
from app.services.http import PoliteHttp, RobotsDisallowed
from app.services.text_utils import parse_datetime

log = logging.getLogger(__name__)

CAREER_PATHS = ["/careers", "/jobs", "/careers/", "/company/careers", "/about/careers", "/join-us",
                "/work-with-us", "/open-positions", "/join", "/careers/jobs", "/en/careers"]
CAREER_LINK_RE = re.compile(r"career|jobs|join[- ]?(us|our[- ]team)|work[- ]with[- ]us|open[- ]positions|hiring|vacanc", re.I)
JOB_LINK_RE = re.compile(r"/(jobs?|careers?|positions?|openings?|vacanc(y|ies)|roles?)/[^/?#]{3,}", re.I)


def _jsonld_blocks(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    for tag in soup.find_all("script", type=lambda t: t and "ld+json" in t):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                if "@graph" in item:
                    stack.extend(item["@graph"] if isinstance(item["@graph"], list) else [item["@graph"]])
                t = item.get("@type")
                if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                    out.append(item)
                if isinstance(item.get("itemListElement"), list):
                    stack.extend(item["itemListElement"])
                if isinstance(item.get("item"), dict):
                    stack.append(item["item"])
            elif isinstance(item, list):
                stack.extend(item)
    return out


def _location(jp: dict) -> tuple[str | None, bool | None]:
    remote = (str(jp.get("jobLocationType") or "")).upper() == "TELECOMMUTE" or None
    locs = jp.get("jobLocation")
    locs = locs if isinstance(locs, list) else [locs] if locs else []
    names = []
    for l in locs:
        if not isinstance(l, dict):
            continue
        a = l.get("address") or {}
        if isinstance(a, str):
            names.append(a)
            continue
        parts = [a.get("addressLocality"), a.get("addressRegion"),
                 (a.get("addressCountry") or {}).get("name") if isinstance(a.get("addressCountry"), dict) else a.get("addressCountry")]
        names.append(", ".join(p for p in parts if p))
    loc = "; ".join(n for n in names if n) or None
    if remote and not loc:
        loc = "Remote"
    return loc, remote


def jobposting_to_raw(jp: dict, page_url: str, company_hint: str | None, source_key: str) -> RawJob | None:
    title = (jp.get("title") or jp.get("name") or "").strip()
    if not title:
        return None
    org = jp.get("hiringOrganization") or {}
    company = (org.get("name") if isinstance(org, dict) else str(org)) or company_hint or urlparse(page_url).netloc
    sal = jp.get("baseSalary") or {}
    smin = smax = cur = period = None
    if isinstance(sal, dict):
        cur = sal.get("currency")
        v = sal.get("value") or {}
        if isinstance(v, dict):
            smin, smax = v.get("minValue") or v.get("value"), v.get("maxValue")
            period = (v.get("unitText") or "").lower() or None
    url = jp.get("url") or page_url
    exp = jp.get("experienceRequirements")
    exp_months = None
    if isinstance(exp, dict):
        exp_months = exp.get("monthsOfExperience")
        exp = exp.get("description")
    loc, remote = _location(jp)
    ident = jp.get("identifier")
    ext = (ident.get("value") if isinstance(ident, dict) else ident) or url
    return RawJob(
        source_key=source_key, source_name="Company career page", external_id=str(ext)[:500],
        title=title, company_name=company, description=jp.get("description") or "",
        location=loc, remote=remote, apply_url=url, url=url,
        date_posted=parse_datetime(jp.get("datePosted")),
        employment_type=", ".join(jp["employmentType"]) if isinstance(jp.get("employmentType"), list) else jp.get("employmentType"),
        salary_min=_f(smin), salary_max=_f(smax), salary_currency=cur, salary_period=period,
        experience_text=exp if isinstance(exp, str) else None,
        experience_min_months=int(exp_months) if isinstance(exp_months, (int, float)) else None,
        company_logo=org.get("logo") if isinstance(org, dict) and isinstance(org.get("logo"), str) else None,
        company_website=org.get("sameAs") if isinstance(org, dict) and isinstance(org.get("sameAs"), str) else None,
        is_official=True, company_careers_url=page_url,
    )


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


class GenericCareerPageConnector(CompanyCareerConnector):
    key = "career_page"
    name = "Company career pages (schema.org JobPosting)"
    kind = "career_page"
    complete_listing = False
    notes = "Crawls official careers pages (robots.txt respected); parses JobPosting structured data or hands off to ATS APIs."
    max_detail_pages = 25

    def __init__(self) -> None:
        self._playwright_ok: bool | None = None

    async def find_careers_url(self, http: PoliteHttp, website: str) -> tuple[str | None, tuple[str, str] | None]:
        """Locate a careers page from a company homepage. Returns (careers_url, (ats, slug))."""
        if not website.startswith("http"):
            website = "https://" + website
        p = urlparse(website)
        root = f"{p.scheme}://{p.netloc}"
        ats = detect_ats(website)
        if ats:
            return website, ats
        try:
            r = await http.get(root, check_robots=True, retries=1)
            if r.status_code == 200 and "html" in r.headers.get("content-type", ""):
                soup = BeautifulSoup(r.text, "lxml")
                for a in soup.find_all("a", href=True):
                    href = urljoin(str(r.url), a["href"])
                    found = detect_ats(href)
                    if found:
                        return href, found
                for a in soup.find_all("a", href=True):
                    label = f"{a.get_text(' ', strip=True)} {a['href']}"
                    if CAREER_LINK_RE.search(label):
                        href = urljoin(str(r.url), a["href"])
                        if urlparse(href).scheme in ("http", "https"):
                            return href, detect_ats(href)
        except RobotsDisallowed:
            return None, None
        except Exception as e:  # noqa: BLE001
            log.debug("homepage fetch failed %s: %s", root, e)
        for path in CAREER_PATHS[:5]:
            url = root + path
            try:
                r = await http.get(url, check_robots=True, retries=0)
                if r.status_code == 200:
                    return str(r.url), detect_ats(str(r.url)) or self._ats_in_html(r.text)
            except Exception:  # noqa: BLE001
                continue
        return None, None

    @staticmethod
    def _ats_in_html(text: str) -> tuple[str, str] | None:
        for m in re.finditer(r"https?://[^\s\"'<>]+", text):
            found = detect_ats(m.group(0))
            if found:
                return found
        m = re.search(r"greenhouse\.io/embed/job_board/js\?for=([A-Za-z0-9_-]+)", text)
        if m:
            return "greenhouse", m.group(1)
        return None

    async def fetch_company(self, http: PoliteHttp, slug: str, company_name: str | None, ctx: SearchContext) -> list[RawJob]:
        """``slug`` is the careers page URL for this connector."""
        url = slug
        r = await http.get(url, check_robots=True)
        if r.status_code != 200:
            return []
        html_text = r.text
        soup = BeautifulSoup(html_text, "lxml")
        jobs = [j for jp in _jsonld_blocks(soup) if (j := jobposting_to_raw(jp, str(r.url), company_name, self.key))]
        if jobs:
            return jobs
        # follow job-detail links on the same site and read their JSON-LD
        host = urlparse(str(r.url)).netloc
        links: list[str] = []
        for a in soup.find_all("a", href=True):
            href = urljoin(str(r.url), a["href"]).split("#")[0]
            if urlparse(href).netloc == host and JOB_LINK_RE.search(urlparse(href).path) and href not in links:
                if is_tech_job(a.get_text(" ", strip=True)) or not a.get_text(strip=True):
                    links.append(href)
        for href in links[: self.max_detail_pages]:
            if await ctx.stopped():
                break
            try:
                d = await http.get(href, check_robots=True, retries=0)
                if d.status_code != 200:
                    continue
                for jp in _jsonld_blocks(BeautifulSoup(d.text, "lxml")):
                    j = jobposting_to_raw(jp, str(d.url), company_name, self.key)
                    if j:
                        jobs.append(j)
            except Exception:  # noqa: BLE001
                continue
        if not jobs and await self._playwright_available():
            jobs = await self._render_and_parse(url, company_name)
        return jobs

    async def _playwright_available(self) -> bool:
        if self._playwright_ok is None:
            import os
            if os.getenv("PLAYWRIGHT_ENABLED", "false").lower() != "true":
                self._playwright_ok = False
            else:
                try:
                    import playwright.async_api  # noqa: F401
                    self._playwright_ok = True
                except ImportError:
                    self._playwright_ok = False
        return self._playwright_ok

    async def _render_and_parse(self, url: str, company_name: str | None) -> list[RawJob]:
        from playwright.async_api import async_playwright
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page(user_agent="JobHuntAI/1.0 (+respects robots.txt)")
                await page.goto(url, wait_until="networkidle", timeout=30000)
                content = await page.content()
                await browser.close()
        except Exception as e:  # noqa: BLE001
            log.debug("playwright failed %s: %s", url, e)
            return []
        soup = BeautifulSoup(content, "lxml")
        return [j for jp in _jsonld_blocks(soup) if (j := jobposting_to_raw(jp, url, company_name, self.key))]
