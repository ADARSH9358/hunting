"""Job board & aggregator connectors.

Public (no key):  Remotive, Arbeitnow, RemoteOK, Himalayas, Jobicy, HN "Who is hiring".
Keyed / licensed: Adzuna, Jooble, JSearch (RapidAPI - Google Jobs/LinkedIn/Indeed/Glassdoor
                  listings), SerpAPI Google Jobs, Apify actors (LinkedIn / Naukri / Indeed).
"""
from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings
from app.connectors.base import JobSourceConnector, RawJob, SearchContext, is_relevant, is_tech_job
from app.services.http import PoliteHttp
from app.services.text_utils import html_to_text, parse_datetime


def _recent(dt: datetime | None, days: int) -> bool:
    return dt is None or dt >= datetime.now(timezone.utc) - timedelta(days=days)


def _relevant(ctx: SearchContext, title: str, text: str) -> bool:
    return is_relevant(ctx, title, text)


# --------------------------------------------------------------------- public APIs

class RemotiveConnector(JobSourceConnector):
    key = "remotive"
    name = "Remotive"
    kind = "job_board_api"
    base_url = "https://remotive.com/api/remote-jobs"
    notes = "Public API (attribution required; they ask clients to limit calls to a few per day)."
    categories = ["software-dev", "data", "devops", "ai-ml"]

    async def search(self, http: PoliteHttp, ctx: SearchContext) -> list[RawJob]:
        out: dict[str, RawJob] = {}
        for cat in self.categories:
            r = await http.get(self.base_url, params={"category": cat})
            if r.status_code != 200:
                continue
            for j in r.json().get("jobs", []):
                title, desc = j.get("title", ""), j.get("description", "")
                dt = parse_datetime(j.get("publication_date"))
                if not _recent(dt, ctx.posted_within_days) or not _relevant(ctx, title, html_to_text(desc)):
                    continue
                out[str(j["id"])] = RawJob(
                    source_key=self.key, source_name=self.name, external_id=str(j["id"]),
                    title=title, company_name=j.get("company_name", ""), description=desc,
                    location=j.get("candidate_required_location"), apply_url=j.get("url"), url=j.get("url"),
                    date_posted=dt, remote=True, employment_type=(j.get("job_type") or "").replace("_", "-") or None,
                    salary_text=j.get("salary") or None, company_logo=j.get("company_logo"), tags=j.get("tags") or [],
                )
        return list(out.values())[: ctx.max_results_per_source]


class ArbeitnowConnector(JobSourceConnector):
    key = "arbeitnow"
    name = "Arbeitnow"
    base_url = "https://www.arbeitnow.com/api/job-board-api"
    notes = "Free public job board API (Europe-focused, includes remote)."
    pages = 4

    async def search(self, http: PoliteHttp, ctx: SearchContext) -> list[RawJob]:
        out = []
        for page in range(1, self.pages + 1):
            r = await http.get(self.base_url, params={"page": page})
            if r.status_code != 200:
                break
            data = r.json().get("data", [])
            if not data:
                break
            for j in data:
                title, desc = j.get("title", ""), j.get("description", "")
                dt = parse_datetime(j.get("created_at"))
                if not _recent(dt, ctx.posted_within_days) or not _relevant(ctx, title, html_to_text(desc)):
                    continue
                out.append(RawJob(
                    source_key=self.key, source_name=self.name, external_id=j.get("slug") or j.get("url"),
                    title=title, company_name=j.get("company_name", ""), description=desc,
                    location=j.get("location"), apply_url=j.get("url"), url=j.get("url"), date_posted=dt,
                    remote=j.get("remote"), employment_type=", ".join(j.get("job_types") or []) or None,
                    tags=j.get("tags") or [],
                ))
        return out[: ctx.max_results_per_source]


class RemoteOKConnector(JobSourceConnector):
    key = "remoteok"
    name = "RemoteOK"
    base_url = "https://remoteok.com/api"
    notes = "Public API; terms require linking back to RemoteOK (we keep the source URL)."

    async def search(self, http: PoliteHttp, ctx: SearchContext) -> list[RawJob]:
        r = await http.get(self.base_url)
        r.raise_for_status()
        out = []
        for j in r.json()[1:]:
            if not isinstance(j, dict) or not j.get("id"):
                continue
            title, desc = j.get("position", ""), j.get("description", "")
            dt = parse_datetime(j.get("date") or j.get("epoch"))
            if not _recent(dt, ctx.posted_within_days) or not _relevant(ctx, title, html_to_text(desc) + " " + " ".join(j.get("tags") or [])):
                continue
            smin, smax = j.get("salary_min") or None, j.get("salary_max") or None
            out.append(RawJob(
                source_key=self.key, source_name=self.name, external_id=str(j["id"]),
                title=title, company_name=j.get("company", ""), description=desc,
                location=j.get("location") or "Remote", apply_url=j.get("apply_url") or j.get("url"),
                url=j.get("url"), date_posted=dt, remote=True,
                salary_min=smin, salary_max=smax, salary_currency="USD" if (smin or smax) else None,
                salary_period="year" if (smin or smax) else None,
                company_logo=j.get("company_logo") or j.get("logo") or None, tags=j.get("tags") or [],
            ))
        return out[: ctx.max_results_per_source]


class HimalayasConnector(JobSourceConnector):
    key = "himalayas"
    name = "Himalayas"
    base_url = "https://himalayas.app/jobs/api"
    notes = "Public remote-jobs API (himalayas.app/jobs/api)."

    async def search(self, http: PoliteHttp, ctx: SearchContext) -> list[RawJob]:
        out: dict[str, RawJob] = {}
        for kw in ctx.keywords[:5]:
            if await ctx.stopped():
                break
            r = await http.get(f"{self.base_url}/search", params={"q": kw, "sort": "recent"})
            if r.status_code != 200:
                r = await http.get(self.base_url, params={"limit": 20})
                if r.status_code != 200:
                    break
            for j in r.json().get("jobs", []):
                title = j.get("title", "")
                desc = j.get("description") or j.get("excerpt") or ""
                dt = parse_datetime(j.get("pubDate"))
                if not _recent(dt, ctx.posted_within_days) or not _relevant(ctx, title, html_to_text(desc)):
                    continue
                gid = str(j.get("guid") or j.get("applicationLink"))
                locs = j.get("locationRestrictions") or []
                out[gid] = RawJob(
                    source_key=self.key, source_name=self.name, external_id=gid, title=title,
                    company_name=j.get("companyName", ""), description=desc,
                    location=("Remote - " + ", ".join(locs)) if locs else "Remote (worldwide)",
                    apply_url=j.get("applicationLink"), url=j.get("applicationLink"), date_posted=dt, remote=True,
                    employment_type=j.get("employmentType"),
                    salary_min=j.get("minSalary") or None, salary_max=j.get("maxSalary") or None,
                    salary_currency=j.get("currency") if (j.get("minSalary") or j.get("maxSalary")) else None,
                    salary_period="year" if (j.get("minSalary") or j.get("maxSalary")) else None,
                    company_logo=j.get("companyLogo"), experience_text=", ".join(j.get("seniority") or []) or None,
                )
        return list(out.values())[: ctx.max_results_per_source]


class JobicyConnector(JobSourceConnector):
    key = "jobicy"
    name = "Jobicy"
    base_url = "https://jobicy.com/api/v2/remote-jobs"
    notes = "Public remote-jobs API."
    tags = ["python", "javascript", "java", "react", "node", "devops", "ai", "machine-learning", "data"]

    async def search(self, http: PoliteHttp, ctx: SearchContext) -> list[RawJob]:
        r = await http.get(self.base_url, params={"count": 100, "industry": "dev"})
        if r.status_code != 200:
            r = await http.get(self.base_url, params={"count": 100})
        r.raise_for_status()
        out = []
        for j in r.json().get("jobs", []):
            title, desc = html.unescape(j.get("jobTitle", "")), j.get("jobDescription", "")
            dt = parse_datetime(j.get("pubDate"))
            if not _recent(dt, ctx.posted_within_days) or not _relevant(ctx, title, html_to_text(desc)):
                continue
            smin, smax = j.get("annualSalaryMin"), j.get("annualSalaryMax")
            out.append(RawJob(
                source_key=self.key, source_name=self.name, external_id=str(j["id"]), title=title,
                company_name=html.unescape(j.get("companyName", "")), description=desc,
                location=f"Remote - {j.get('jobGeo')}" if j.get("jobGeo") else "Remote",
                apply_url=j.get("url"), url=j.get("url"), date_posted=dt, remote=True,
                employment_type=", ".join(j.get("jobType") or []) if isinstance(j.get("jobType"), list) else j.get("jobType"),
                salary_min=_num(smin), salary_max=_num(smax),
                salary_currency=j.get("salaryCurrency") if (smin or smax) else None,
                salary_period="year" if (smin or smax) else None,
                company_logo=j.get("companyLogo"), experience_text=j.get("jobLevel"),
            ))
        return out[: ctx.max_results_per_source]


class HackerNewsHiringConnector(JobSourceConnector):
    """Monthly 'Ask HN: Who is hiring?' thread via the public Algolia HN API.

    Posts are written by the hiring companies themselves -> great source of
    small and mid-sized companies and their websites (fed into company discovery).
    """
    key = "hn_whoishiring"
    name = "Hacker News: Who is Hiring"
    kind = "aggregator"
    base_url = "https://hn.algolia.com/api/v1"
    notes = "Public Algolia HN API; parses the latest monthly hiring thread."

    async def search(self, http: PoliteHttp, ctx: SearchContext) -> list[RawJob]:
        r = await http.get(f"{self.base_url}/search_by_date",
                           params={"tags": "story,author_whoishiring", "query": "who is hiring", "hitsPerPage": 5})
        r.raise_for_status()
        story = next((h for h in r.json().get("hits", []) if "who is hiring" in (h.get("title") or "").lower()), None)
        if not story:
            return []
        thread_date = parse_datetime(story.get("created_at"))
        items = await http.get_json(f"{self.base_url}/items/{story['objectID']}")
        out = []
        for c in items.get("children") or []:
            text = c.get("text") or ""
            if not text or c.get("author") is None:
                continue
            plain = html_to_text(text)
            first = plain.split("\n", 1)[0]
            parts = [p.strip() for p in first.split("|")]
            if len(parts) < 2:
                continue
            company = re.sub(r"\(.*?\)", "", parts[0]).strip()
            if not company or len(company) > 80:
                continue
            title = next((p for p in parts[1:] if is_tech_job(p) and len(p) < 140), None)
            if not title:
                continue
            if not _relevant(ctx, title, plain):
                continue
            links = re.findall(r'href="([^"]+)"', text)
            links = [html.unescape(l) for l in links]
            location = next((p for p in parts[1:] if re.search(r"remote|onsite|on-site|hybrid|,|usa|india|uk|europe|sf|nyc|london|berlin|bangalore", p, re.I) and p != title), None)
            website = next((l for l in links if not re.search(r"news\.ycombinator|mailto:", l)), None)
            apply_link = next((l for l in links if re.search(r"greenhouse|lever|ashby|workable|careers|jobs|apply", l, re.I)), website)
            out.append(RawJob(
                source_key=self.key, source_name=self.name, external_id=str(c["id"]),
                title=title[:200], company_name=company, description=text, location=location,
                apply_url=apply_link, url=f"https://news.ycombinator.com/item?id={c['id']}",
                date_posted=parse_datetime(c.get("created_at")) or thread_date,
                company_website=website, extra={"links": links[:10]},
            ))
        return out[: ctx.max_results_per_source]


# --------------------------------------------------------------------- keyed providers

class AdzunaConnector(JobSourceConnector):
    key = "adzuna"
    name = "Adzuna"
    kind = "aggregator"
    requires_credentials = True
    base_url = "https://api.adzuna.com/v1/api/jobs"
    notes = "Free developer API (ADZUNA_APP_ID / ADZUNA_APP_KEY). Aggregates many boards incl. Indian portals. Predicted salaries are ignored."

    def is_configured(self) -> bool:
        s = get_settings()
        return bool(s.adzuna_app_id and s.adzuna_app_key)

    async def search(self, http: PoliteHttp, ctx: SearchContext) -> list[RawJob]:
        s = get_settings()
        out: dict[str, RawJob] = {}
        locs = ctx.locations[:2] or [""]
        for kw in ctx.keywords[:6]:
            for loc in locs:
                if await ctx.stopped():
                    return list(out.values())
                params = {"app_id": s.adzuna_app_id, "app_key": s.adzuna_app_key, "what": kw,
                          "results_per_page": 50, "max_days_old": ctx.posted_within_days,
                          "content-type": "application/json"}
                if loc and "remote" not in loc.lower():
                    params["where"] = loc
                r = await http.get(f"{self.base_url}/{s.adzuna_country}/search/1", params=params)
                r.raise_for_status()
                for j in r.json().get("results", []):
                    predicted = str(j.get("salary_is_predicted", "0")) == "1"
                    out[str(j["id"])] = RawJob(
                        source_key=self.key, source_name=self.name, external_id=str(j["id"]),
                        title=html_to_text(j.get("title", "")), company_name=(j.get("company") or {}).get("display_name", ""),
                        description=j.get("description", ""), location=(j.get("location") or {}).get("display_name"),
                        apply_url=j.get("redirect_url"), url=j.get("redirect_url"),
                        date_posted=parse_datetime(j.get("created")),
                        employment_type=j.get("contract_time"),
                        salary_min=None if predicted else j.get("salary_min"),
                        salary_max=None if predicted else j.get("salary_max"),
                        salary_currency=None if predicted or not j.get("salary_min") else ("INR" if s.adzuna_country == "in" else None),
                        salary_period=None if predicted or not j.get("salary_min") else "year",
                    )
        return list(out.values())[: ctx.max_results_per_source]


class JoobleConnector(JobSourceConnector):
    key = "jooble"
    name = "Jooble"
    kind = "aggregator"
    requires_credentials = True
    base_url = "https://jooble.org/api"
    notes = "Free partner API key (JOOBLE_API_KEY). Aggregates Naukri/TimesJobs/Shine and other boards."

    def is_configured(self) -> bool:
        return bool(get_settings().jooble_api_key)

    async def search(self, http: PoliteHttp, ctx: SearchContext) -> list[RawJob]:
        key = get_settings().jooble_api_key
        out: dict[str, RawJob] = {}
        for kw in ctx.keywords[:6]:
            if await ctx.stopped():
                break
            body = {"keywords": kw, "location": (ctx.locations or [""])[0], "page": "1"}
            r = await http.post(f"{self.base_url}/{key}", json=body)
            r.raise_for_status()
            for j in r.json().get("jobs", []):
                jid = str(j.get("id") or j.get("link"))
                out[jid] = RawJob(
                    source_key=self.key, source_name=f"Jooble · {j.get('source') or 'web'}", external_id=jid,
                    title=html_to_text(j.get("title", "")), company_name=j.get("company") or "",
                    description=j.get("snippet", ""), location=j.get("location"),
                    apply_url=j.get("link"), url=j.get("link"), date_posted=parse_datetime(j.get("updated")),
                    employment_type=j.get("type") or None, salary_text=j.get("salary") or None,
                )
        return list(out.values())[: ctx.max_results_per_source]


class JSearchConnector(JobSourceConnector):
    key = "jsearch"
    name = "JSearch (Google for Jobs: LinkedIn, Indeed, Glassdoor, Naukri…)"
    kind = "licensed"
    requires_credentials = True
    base_url = "https://jsearch.p.rapidapi.com/search"
    notes = "Licensed Google-for-Jobs data via RapidAPI (RAPIDAPI_KEY). Covers LinkedIn/Indeed/Glassdoor/ZipRecruiter/Naukri listings legally."

    def is_configured(self) -> bool:
        return bool(get_settings().rapidapi_key)

    async def search(self, http: PoliteHttp, ctx: SearchContext) -> list[RawJob]:
        key = get_settings().rapidapi_key
        out: dict[str, RawJob] = {}
        date_posted = "week" if ctx.posted_within_days <= 7 else "month"
        locs = ctx.locations[:2] or ([ctx.countries[0]] if ctx.countries else [""])
        for kw in ctx.keywords[:5]:
            for loc in locs:
                if await ctx.stopped():
                    return list(out.values())
                q = f"{kw} in {loc}" if loc else kw
                params = {"query": q, "page": 1, "num_pages": 2, "date_posted": date_posted}
                if ctx.remote_preference == "remote":
                    params["remote_jobs_only"] = "true"
                r = await http.get(self.base_url, params=params,
                                   headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})
                r.raise_for_status()
                for j in r.json().get("data", []):
                    loc_str = ", ".join(x for x in [j.get("job_city"), j.get("job_state"), j.get("job_country")] if x)
                    req = j.get("job_required_experience") or {}
                    publisher = j.get("job_publisher") or "Google Jobs"
                    out[j["job_id"]] = RawJob(
                        source_key=self.key, source_name=f"{publisher} (via JSearch)", external_id=j["job_id"],
                        title=j.get("job_title", ""), company_name=j.get("employer_name", ""),
                        description=j.get("job_description", ""), location=loc_str or None,
                        apply_url=j.get("job_apply_link"), url=j.get("job_google_link") or j.get("job_apply_link"),
                        date_posted=parse_datetime(j.get("job_posted_at_datetime_utc")),
                        remote=j.get("job_is_remote"), employment_type=j.get("job_employment_type"),
                        salary_min=j.get("job_min_salary"), salary_max=j.get("job_max_salary"),
                        salary_currency=j.get("job_salary_currency"), salary_period=(j.get("job_salary_period") or "").lower() or None,
                        experience_min_months=req.get("required_experience_in_months"),
                        company_website=j.get("employer_website"), company_logo=j.get("employer_logo"),
                        is_official=bool(j.get("job_apply_is_direct")),
                        extra={"publisher": publisher, "apply_options": j.get("apply_options") or []},
                    )
        return list(out.values())[: ctx.max_results_per_source]


class SerpApiGoogleJobsConnector(JobSourceConnector):
    key = "serpapi_google_jobs"
    name = "Google Jobs (via SerpAPI)"
    kind = "licensed"
    requires_credentials = True
    base_url = "https://serpapi.com/search.json"
    notes = "Licensed Google Jobs results via SerpAPI (SERPAPI_KEY)."

    def is_configured(self) -> bool:
        return bool(get_settings().serpapi_key)

    async def search(self, http: PoliteHttp, ctx: SearchContext) -> list[RawJob]:
        key = get_settings().serpapi_key
        out: dict[str, RawJob] = {}
        locs = ctx.locations[:2] or [""]
        for kw in ctx.keywords[:4]:
            for loc in locs:
                if await ctx.stopped():
                    return list(out.values())
                params = {"engine": "google_jobs", "q": kw, "api_key": key, "hl": "en"}
                if loc and "remote" not in loc.lower():
                    params["location"] = loc
                r = await http.get(self.base_url, params=params)
                r.raise_for_status()
                for j in r.json().get("jobs_results", []):
                    ext = j.get("detected_extensions") or {}
                    opts = j.get("apply_options") or []
                    jid = j.get("job_id") or (opts[0]["link"] if opts else j.get("title"))
                    out[jid] = RawJob(
                        source_key=self.key, source_name=f"{(j.get('via') or 'Google Jobs').replace('via ', '')} (via Google Jobs)",
                        external_id=jid[:500], title=j.get("title", ""), company_name=j.get("company_name", ""),
                        description=j.get("description", ""), location=j.get("location"),
                        apply_url=opts[0]["link"] if opts else j.get("share_link"), url=j.get("share_link"),
                        remote=ext.get("work_from_home"), employment_type=ext.get("schedule_type"),
                        salary_text=ext.get("salary"), company_logo=j.get("thumbnail"),
                        extra={"posted_at": ext.get("posted_at"), "apply_options": opts},
                    )
        return list(out.values())[: ctx.max_results_per_source]


class ApifyActorConnector(JobSourceConnector):
    """Runs a configured Apify actor (licensed third-party data provider).

    Disabled unless APIFY_TOKEN and the actor id env var are set. You are
    responsible for confirming the chosen actor's terms are acceptable for
    your use case.
    """
    kind = "licensed"
    requires_credentials = True
    actor_setting = ""

    def __init__(self, key: str, name: str, actor_setting: str, portal: str):
        self.key, self.name, self.actor_setting, self.portal = key, name, actor_setting, portal
        self.base_url = "https://api.apify.com/v2/acts"
        self.notes = f"Apify actor for {portal} (APIFY_TOKEN + {actor_setting.upper()})."

    def actor(self) -> str | None:
        return getattr(get_settings(), self.actor_setting, None)

    def is_configured(self) -> bool:
        return bool(get_settings().apify_token and self.actor())

    async def search(self, http: PoliteHttp, ctx: SearchContext) -> list[RawJob]:
        s = get_settings()
        actor = self.actor().replace("/", "~")
        out: dict[str, RawJob] = {}
        for kw in ctx.keywords[:3]:
            if await ctx.stopped():
                break
            loc = (ctx.locations or [""])[0]
            run_input = {"keyword": kw, "keywords": [kw], "title": kw, "searchTerms": [kw], "position": kw,
                         "location": loc, "maxItems": 50, "rows": 50, "count": 50}
            r = await http.post(f"{self.base_url}/{actor}/run-sync-get-dataset-items",
                                params={"token": s.apify_token, "timeout": 240}, json=run_input,
                                timeout=httpx.Timeout(300.0), retries=0)
            r.raise_for_status()
            for j in r.json() if isinstance(r.json(), list) else []:
                title = j.get("title") or j.get("jobTitle") or j.get("positionName") or ""
                url = j.get("jobUrl") or j.get("url") or j.get("link") or j.get("applyUrl")
                if not title or not url:
                    continue
                jid = str(j.get("id") or j.get("jobId") or url)
                out[jid] = RawJob(
                    source_key=self.key, source_name=f"{self.portal} (via Apify)", external_id=jid[:500],
                    title=title, company_name=j.get("companyName") or j.get("company") or "",
                    description=j.get("descriptionHtml") or j.get("description") or j.get("descriptionText") or "",
                    location=j.get("location") or j.get("jobLocation"), apply_url=j.get("applyUrl") or url, url=url,
                    date_posted=parse_datetime(j.get("postedAt") or j.get("publishedAt") or j.get("postedDate")),
                    salary_text=j.get("salary") if isinstance(j.get("salary"), str) else None,
                    experience_text=j.get("experience") if isinstance(j.get("experience"), str) else None,
                    company_logo=j.get("companyLogo"), company_website=j.get("companyWebsite"),
                )
        return list(out.values())[: ctx.max_results_per_source]


class LinkedInHiringPostsConnector(JobSourceConnector):
    """Recruiter "we're hiring" POSTS on LinkedIn (not LinkedIn Jobs listings), India only.

    Uses an Apify post-search actor (default ``harvestapi/linkedin-post-search``) - a
    third-party data provider; LinkedIn itself is never scraped from this app. Posts are
    kept only if they (a) announce an opening, (b) are not a job seeker's #OpenToWork
    post, (c) target India, and (d) match the search keywords / candidate skills.
    Every result links back to the original LinkedIn post.
    """
    key = "linkedin_posts"
    name = "LinkedIn hiring posts - India (via Apify)"
    kind = "licensed"
    requires_credentials = True
    base_url = "https://api.apify.com/v2/acts"
    notes = "Recruiter hiring posts on LinkedIn (India) via an Apify post-search actor. Needs APIFY_TOKEN."

    HIRING = re.compile(
        r"we(?:'|’)?re hiring|we are hiring|\bhiring\b|job opening|openings?\b|vacanc|immediate joiner|"
        r"walk-?in|join our team|share (?:your )?(?:cv|resume|profile)|send (?:your )?(?:cv|resume)", re.I)
    SEEKER = re.compile(
        r"#?open ?to ?work|\bi(?:'|’)?m (?:actively )?(?:looking|seeking)|\bi am (?:actively )?(?:looking|seeking)|"
        r"seeking (?:new )?(?:opportunities|a role|roles)|hire me\b|my resume|available to join", re.I)
    INDIA = re.compile(
        r"\b(?:india|indian|pan india|bangalore|bengaluru|hyderabad|pune|chennai|mumbai|delhi|ncr|noida|gurgaon|"
        r"gurugram|kolkata|ahmedabad|jaipur|kochi|indore|chandigarh|coimbatore|bhubaneswar|trivandrum|"
        r"thiruvananthapuram|mysore|mysuru|nagpur|lucknow|\d+\s*lpa)\b|₹", re.I)
    NOT_INDIA = re.compile(
        r"usa[- ]based|candidates? (?:currently )?(?:residing|based) in the (?:us|united states)|\bus citizens?\b|"
        r"residing in the (?:usa|us|united states)|\bw2\b|\bc2c\b|green card|\bh-?1b\b|\bopt\b|\bcpt\b", re.I)
    # "Applications from candidates based in India will NOT be considered"
    EXCLUDES_INDIA = re.compile(
        r"india[^.\n]{0,40}\b(?:not|won'?t|cannot|ineligible)\b|\b(?:no|not)\b[^.\n]{0,30}\bindia\b", re.I)
    ROLE_WORD = re.compile(
        r"developer|engineer|intern\b|architect|scientist|analyst|\blead\b|designer|specialist|\bsde\b|"
        r"programmer|consultant|stack|devops|tester|\bqa\b", re.I)
    INDIA_ONLY = re.compile(r"india only|based in india|across india|pan india|remote\s*[-–]\s*india", re.I)
    ROLE = [
        re.compile(r"(?:role|position|designation|job title)\s*[:\-–]\s*([^\n|•📍💼🏢]{3,80})", re.I),
        re.compile(r"hiring\s*(?:alert)?\s*(?:for)?\s*[:|\-–]\s*([^\n|•📍💼🏢!]{3,80})", re.I),
        re.compile(r"(?:looking for|hiring) (?:an? )?(?:experienced |passionate |skilled |talented )*"
                   r"([A-Za-z.+#/ ]{3,60}?(?:developer|engineer|intern|architect|scientist|analyst|lead))", re.I),
    ]
    COMPANY = re.compile(r"company\s*[:\-–]\s*([^\n|•📍💼🏢]{2,60})", re.I)
    QUERY_ROLES = 3

    def is_configured(self) -> bool:
        return bool(get_settings().apify_token)

    def queries(self, ctx: SearchContext) -> list[str]:
        roles = [k for k in ctx.keywords if k.strip()][: self.QUERY_ROLES] or ["software developer"]
        qs = [f"hiring {r} India" for r in roles]
        if ctx.candidate_skills:
            qs.append(f"hiring {' '.join(ctx.candidate_skills[:2])} developer India")
        return qs

    @classmethod
    def is_india_hiring_post(cls, text: str) -> bool:
        if not text or cls.SEEKER.search(text) or not cls.HIRING.search(text):
            return False
        if cls.EXCLUDES_INDIA.search(text):
            return False
        if cls.NOT_INDIA.search(text) and not cls.INDIA_ONLY.search(text):
            return False
        return bool(cls.INDIA.search(text))

    @classmethod
    def extract_title(cls, text: str) -> str:
        flat = re.sub(r"#\w+", " ", text)  # hashtags are not titles
        flat = re.sub(r"[ \t]+", " ", flat)
        for pat in cls.ROLE:
            for m in pat.finditer(flat):
                t = re.sub(r"\s+", " ", m.group(1)).strip(" -–|:.,!#*(🔹")
                if t.count("(") > t.count(")"):
                    t += ")"
                if 3 <= len(t) <= 80 and t[0].isalnum() and cls.ROLE_WORD.search(t):
                    return t
        first = re.sub(r"\s+", " ", text).strip()[:90]
        return f"Hiring post: {first}" if first else "Hiring post"

    @classmethod
    def extract_company(cls, text: str, author: dict) -> str:
        m = cls.COMPANY.search(text)
        if m:
            return m.group(1).strip(" -–|:.,")
        if (author.get("type") or "").lower() == "company" and author.get("name"):
            return author["name"]
        info = author.get("info") or author.get("position") or ""
        m = re.search(r"(?:\bat\b|@)\s*([^|,•]{2,60})", info)
        if m:
            return m.group(1).strip()
        return "Not specified"

    async def search(self, http: PoliteHttp, ctx: SearchContext) -> list[RawJob]:
        s = get_settings()
        actor = (s.apify_linkedin_posts_actor or "harvestapi/linkedin-post-search").replace("/", "~")
        run_input = {
            "searchQueries": self.queries(ctx),
            "maxPosts": s.linkedin_posts_per_query,
            "postedLimit": "week" if ctx.posted_within_days <= 7 else "month",
            "sortBy": "date",
            "profileScraperMode": "short",
        }
        r = await http.post(f"{self.base_url}/{actor}/run-sync-get-dataset-items",
                            params={"token": s.apify_token, "timeout": 240}, json=run_input,
                            timeout=httpx.Timeout(300.0), retries=0)
        r.raise_for_status()
        data = r.json()
        out: dict[str, RawJob] = {}
        seen_text: set[str] = set()
        for p in data if isinstance(data, list) else []:
            text = p.get("content") or ""
            post_url = p.get("linkedinUrl") or p.get("shareLinkedinUrl")
            if not post_url or not self.is_india_hiring_post(text):
                continue
            # recruiters often copy-paste the same post from many accounts - keep one
            sig = re.sub(r"\W+", "", text.lower())[:300]
            if sig in seen_text:
                continue
            title = self.extract_title(text)
            if not _relevant(ctx, title, text) and not is_relevant(ctx, "developer", text):
                continue
            seen_text.add(sig)
            author = p.get("author") or {}
            posted = p.get("postedAt") or {}
            pid = str(p.get("id") or p.get("entityId") or post_url)
            ext_links = [a.get("hyperlink") for a in (p.get("contentAttributes") or [])
                         if isinstance(a, dict) and a.get("hyperlink")]
            out[pid] = RawJob(
                source_key=self.key, source_name="LinkedIn post (via Apify)", external_id=pid[:500],
                title=title, company_name=self.extract_company(text, author),
                description=text, location="India", apply_url=post_url, url=post_url,
                date_posted=parse_datetime(posted.get("date")),
                tags=["linkedin-post"],
                extra={"post_url": post_url, "author": author.get("name"),
                       "author_headline": author.get("info"), "author_url": author.get("linkedinUrl"),
                       "links_in_post": ext_links[:5]},
            )
        return list(out.values())[: ctx.max_results_per_source]


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


async def gather_limited(coros, limit: int = 4):
    sem = asyncio.Semaphore(limit)

    async def run(c):
        async with sem:
            return await c
    return await asyncio.gather(*(run(c) for c in coros), return_exceptions=True)

