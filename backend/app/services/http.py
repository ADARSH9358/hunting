"""PoliteHttp: shared HTTP client with per-host rate limiting, robots.txt
compliance, retries with backoff, response size caps and timeouts.

It never attempts to bypass CAPTCHAs, logins or anti-bot protection: a 401/403
or challenge page is treated as "access not permitted" and the source is skipped.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

MAX_BYTES = 30 * 1024 * 1024


class AccessDenied(Exception):
    pass


class RobotsDisallowed(Exception):
    pass


class PoliteHttp:
    def __init__(self, host_rates: dict[str, float] | None = None) -> None:
        s = get_settings()
        self.s = s
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(s.http_timeout_seconds, connect=10.0),
            follow_redirects=True,
            headers={"User-Agent": s.http_user_agent, "Accept-Language": "en"},
            limits=httpx.Limits(max_connections=s.max_concurrent_requests * 2),
        )
        self.sem = asyncio.Semaphore(s.max_concurrent_requests)
        # Official public job-board APIs are built for programmatic consumption and are
        # shared by many companies, so they get a higher (still polite) rate.
        self.host_rates = {
            "boards-api.greenhouse.io": 4.0, "api.lever.co": 4.0, "api.eu.lever.co": 4.0,
            "api.ashbyhq.com": 4.0, "api.smartrecruiters.com": 3.0, "apply.workable.com": 2.0,
            **(host_rates or {}),
        }
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self.request_count = 0

    async def __aenter__(self) -> "PoliteHttp":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self.client.aclose()

    # ------------------------------------------------------------ robots
    async def allowed(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp: RobotFileParser | None = RobotFileParser()
            try:
                r = await self.client.get(f"{base}/robots.txt", timeout=10)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                elif r.status_code in (401, 403):
                    rp.parse(["User-agent: *", "Disallow: /"])
                else:
                    rp = None  # no robots.txt => allowed
            except httpx.HTTPError:
                rp = None
            self._robots[base] = rp
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(self.s.http_user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        p = urlparse(url)
        rp = self._robots.get(f"{p.scheme}://{p.netloc}")
        if rp is None:
            return None
        try:
            d = rp.crawl_delay(self.s.http_user_agent)
            return float(d) if d else None
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------ rate limit
    async def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        rate = self.host_rates.get(host, self.s.default_host_rate_per_sec)
        delay = self.crawl_delay(url)
        interval = max(1.0 / rate if rate > 0 else 0, delay or 0)
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._host_last.get(host, 0) + interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._host_last[host] = time.monotonic()

    # ------------------------------------------------------------ request
    async def request(self, method: str, url: str, *, check_robots: bool = False, retries: int = 2,
                      **kwargs) -> httpx.Response:
        if check_robots and not await self.allowed(url):
            raise RobotsDisallowed(url)
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            await self._throttle(url)
            async with self.sem:
                try:
                    self.request_count += 1
                    r = await self.client.request(method, url, **kwargs)
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    last_exc = e
                    await asyncio.sleep((2 ** attempt) + random.random())
                    continue
            if len(r.content) > MAX_BYTES:
                raise httpx.HTTPError(f"Response too large from {url}")
            if r.status_code in (429, 502, 503, 504) and attempt < retries:
                ra = r.headers.get("retry-after")
                await asyncio.sleep(min(float(ra) if ra and ra.isdigit() else 2 ** (attempt + 1), 30))
                continue
            if r.status_code in (401, 403):
                raise AccessDenied(f"{r.status_code} from {urlparse(url).netloc} (access not permitted)")
            return r
        raise last_exc or httpx.HTTPError(f"Failed to fetch {url}")

    async def get_json(self, url: str, **kwargs):
        r = await self.request("GET", url, **kwargs)
        r.raise_for_status()
        return r.json()

    async def get(self, url: str, **kwargs) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        return await self.request("POST", url, **kwargs)
