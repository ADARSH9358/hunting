"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import db as dbmod
from app.api import auth, contacts, email_templates, gmail, job_emails, jobs, misc, resume, search
from app.config import get_settings
from app.core.ratelimit import RateLimitMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("jobhunt")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.database_url.startswith("sqlite"):
        # Local dev convenience; PostgreSQL deployments use `alembic upgrade head`.
        async with dbmod.engine.begin() as conn:
            await conn.run_sync(dbmod.Base.metadata.create_all)
    from app.services.search_service import reap_stale
    async with dbmod.SessionLocal() as db:
        n = await reap_stale(db)
        await db.commit()
        if n:
            log.warning("Marked %s interrupted searches as failed", n)
    if s.secret_key.startswith("change-me") and s.environment == "production":
        raise RuntimeError("SECRET_KEY must be set in production")
    yield
    await dbmod.engine.dispose()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title=f"{s.app_name} API",
        version="1.0.0",
        description="AI-powered job discovery: resume analysis, multi-source job collection, company discovery and matching.",
        lifespan=lifespan,
    )
    app.add_middleware(RateLimitMiddleware, per_minute=s.api_rate_limit_per_minute)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": "Validation error", "errors": exc.errors()[:20]})

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error: %s", exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    for r in (auth.router, resume.router, search.router, jobs.router, misc.router,
              gmail.router, email_templates.router, job_emails.router, contacts.router):
        app.include_router(r)

    @app.get("/api/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
