"""Connector registry + catalogue of portals and how each is (legitimately) covered."""
from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.connectors.ats import ATS_CONNECTORS
from app.connectors.base import BaseConnector, CompanyCareerConnector, JobSourceConnector
from app.connectors.career_page import GenericCareerPageConnector
from app.connectors.job_boards import (
    AdzunaConnector,
    ApifyActorConnector,
    ArbeitnowConnector,
    HackerNewsHiringConnector,
    HimalayasConnector,
    JobicyConnector,
    JoobleConnector,
    JSearchConnector,
    LinkedInHiringPostsConnector,
    RemoteOKConnector,
    RemotiveConnector,
    SerpApiGoogleJobsConnector,
)


@dataclass
class PortalInfo:
    key: str
    name: str
    url: str
    access: str  # how it is covered


# Portals that have NO public job-search API and whose terms prohibit scraping.
# We never scrape them directly; they are covered via licensed providers.
PORTALS: list[PortalInfo] = [
    PortalInfo("linkedin", "LinkedIn Jobs", "https://www.linkedin.com/jobs",
               "No public jobs API (partner-only). Covered via JSearch (RAPIDAPI_KEY) or an Apify actor (APIFY_LINKEDIN_ACTOR). Recruiter hiring posts in India come via the linkedin_posts source (APIFY_TOKEN)."),
    PortalInfo("naukri", "Naukri", "https://www.naukri.com",
               "No public API. Listings reach us via Jooble/Adzuna/JSearch aggregation, or an Apify actor (APIFY_NAUKRI_ACTOR)."),
    PortalInfo("indeed", "Indeed", "https://www.indeed.com",
               "Publisher API closed to new partners. Covered via JSearch / SerpAPI Google Jobs, or APIFY_INDEED_ACTOR."),
    PortalInfo("glassdoor", "Glassdoor", "https://www.glassdoor.com",
               "No public API. Listings surface through JSearch / Google Jobs."),
    PortalInfo("foundit", "Foundit (Monster India)", "https://www.foundit.in",
               "No public API. Listings surface through Jooble / Google Jobs."),
    PortalInfo("instahyre", "Instahyre", "https://www.instahyre.com",
               "Login-gated; no public API. Not collected (would require bypassing auth)."),
    PortalInfo("wellfound", "Wellfound (AngelList Talent)", "https://wellfound.com",
               "No public API; anti-bot protected. Startups found there usually use Greenhouse/Lever/Ashby, which we query directly."),
    PortalInfo("cutshort", "Cutshort", "https://cutshort.io",
               "No public API. Covered indirectly via Google Jobs (JSearch/SerpAPI)."),
    PortalInfo("hirist", "Hirist", "https://www.hirist.tech",
               "No public API. Covered indirectly via Google Jobs / Jooble."),
    PortalInfo("iimjobs", "iimjobs", "https://www.iimjobs.com",
               "No public API. Covered indirectly via Google Jobs / Jooble."),
    PortalInfo("timesjobs", "TimesJobs", "https://www.timesjobs.com",
               "No public API. Listings surface through Jooble / Adzuna."),
    PortalInfo("shine", "Shine", "https://www.shine.com",
               "No public API. Listings surface through Jooble / Google Jobs."),
    PortalInfo("google_jobs", "Google Jobs", "https://www.google.com/search?q=jobs",
               "Via authorized providers: JSearch (RAPIDAPI_KEY) or SerpAPI (SERPAPI_KEY)."),
]


def search_connectors() -> list[JobSourceConnector]:
    return [
        RemotiveConnector(), ArbeitnowConnector(), RemoteOKConnector(), HimalayasConnector(), JobicyConnector(),
        HackerNewsHiringConnector(), AdzunaConnector(), JoobleConnector(), JSearchConnector(),
        SerpApiGoogleJobsConnector(),
        LinkedInHiringPostsConnector(),
        ApifyActorConnector("apify_linkedin", "LinkedIn Jobs (via Apify)", "apify_linkedin_actor", "LinkedIn"),
        ApifyActorConnector("apify_naukri", "Naukri (via Apify)", "apify_naukri_actor", "Naukri"),
        ApifyActorConnector("apify_indeed", "Indeed (via Apify)", "apify_indeed_actor", "Indeed"),
    ]


GENERIC_CAREER = GenericCareerPageConnector()


def career_connectors() -> dict[str, CompanyCareerConnector]:
    return {**ATS_CONNECTORS, GENERIC_CAREER.key: GENERIC_CAREER}


def all_connectors() -> list[BaseConnector]:
    return [*search_connectors(), *career_connectors().values()]


def enabled_keys() -> set[str] | None:
    raw = get_settings().enabled_sources.strip()
    return {k.strip() for k in raw.split(",") if k.strip()} if raw else None


def is_enabled(c: BaseConnector, db_enabled: bool = True) -> bool:
    keys = enabled_keys()
    return db_enabled and c.is_configured() and (keys is None or c.key in keys)
