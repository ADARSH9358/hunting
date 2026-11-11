"""Simple per-client sliding-window rate limiter (in-memory; use Redis-backed
limits behind a load balancer)."""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

STRICT = {"/api/auth/token": 10, "/api/auth/register": 5, "/api/resume/upload": 10, "/api/search/run": 10,
          "/api/gmail/connect": 10, "/api/job-emails/auto-send": 5}
# per-path-pattern limits (POST): sending email is deliberately slow
STRICT_PATTERNS = [(re.compile(r"^/api/job-emails/\d+/(send|retry)$"), "/api/job-emails/*/send", 20)]


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, per_minute: int = 120):
        super().__init__(app)
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api"):
            return await call_next(request)
        client = request.client.host if request.client else "anon"
        path = request.url.path
        limit = STRICT.get(path, self.per_minute) if request.method == "POST" else self.per_minute
        key = f"{client}:{path if path in STRICT else '*'}"
        if request.method == "POST":
            for rx, bucket, n in STRICT_PATTERNS:
                if rx.match(path):
                    limit, key = n, f"{client}:{bucket}"
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            return JSONResponse({"detail": "Too many requests, please slow down."}, status_code=429,
                                headers={"Retry-After": "60"})
        q.append(now)
        return await call_next(request)
