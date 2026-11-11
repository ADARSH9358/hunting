"""Application configuration. All secrets come from environment variables / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # --- core ---
    app_name: str = "JobHunt AI"
    environment: str = "development"
    secret_key: str = "change-me-in-production-please-32+chars"
    access_token_expire_minutes: int = 60 * 24
    cors_origins: str = "http://localhost:3000"

    # --- database / queue ---
    # PostgreSQL in production: postgresql+asyncpg://user:pass@host:5432/jobhunt
    database_url: str = "postgresql://postgres:Ek1mKcV9H0YwrKxL@db.uewhmujgcozqqqgmlqct.supabase.co:5432/postgres" 
    host="db.uewhmujgcozqqqgmlqct.supabase.co"
    port=5432
    database="postgres"
    user="postgres"   
    database_url: str = f"sqlite+aiosqlite:///{(BASE_DIR / 'jobhunt.db').as_posix()}"
    redis_url: str = "redis://localhost:6379/0"
    # "inprocess" runs the search pipeline as an asyncio task in the API process;
    # "celery" dispatches it to a Celery worker (requires Redis).
    task_backend: str = "inprocess"

    # --- storage ---
    storage_dir: Path = BASE_DIR / "storage"
    max_upload_mb: int = 5
    # Fernet key (urlsafe base64, 32 bytes). If set, resume files are encrypted at rest.
    resume_encryption_key: str | None = None

    # --- LLM ---
    llm_provider: str = "none"  # anthropic | openai | none
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    llm_timeout_seconds: int = 60

    # --- crawling ---
    http_user_agent: str = "JobHuntAI/1.0 (+personal job-search assistant; respects robots.txt)"
    http_timeout_seconds: float = 20.0
    default_host_rate_per_sec: float = 1.0
    max_companies_per_run: int = 150
    max_concurrent_requests: int = 8

    # --- optional licensed / keyed providers ---
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    adzuna_country: str = "in"
    jooble_api_key: str | None = None
    rapidapi_key: str | None = None  # JSearch (Google Jobs / LinkedIn / Indeed aggregation)
    serpapi_key: str | None = None  # Google Jobs via SerpAPI; also used for company discovery
    brave_search_api_key: str | None = None  # company/career-page discovery
    apify_token: str | None = None
    apify_linkedin_actor: str | None = None  # e.g. "curious_coder/linkedin-jobs-scraper"
    apify_naukri_actor: str | None = None
    apify_indeed_actor: str | None = None
    # LinkedIn recruiter "we're hiring" posts in India (enabled whenever APIFY_TOKEN is set)
    apify_linkedin_posts_actor: str = "harvestapi/linkedin-post-search"
    linkedin_posts_per_query: int = 25

    # --- Gmail API (job application emails) ---
    # OAuth 2.0 "Web application" client from Google Cloud Console. Scope requested: gmail.send
    google_client_id: str | None = None
    google_client_secret: str | None = None
    # Must exactly match an "Authorized redirect URI" of the OAuth client. The default goes
    # through the Next.js /api proxy so the browser stays on one origin.
    google_oauth_redirect_uri: str = "http://localhost:3000/api/gmail/callback"
    frontend_url: str = "http://localhost:3000"
    # Fernet key for OAuth tokens at rest. If empty, a key is derived from SECRET_KEY.
    token_encryption_key: str | None = None
    # Pause between automatic sends (Gmail quota / anti-spam friendliness)
    email_send_interval_seconds: float = 30.0
    # Hard ceiling for the user-configurable daily automatic-send limit
    email_daily_limit_max: int = 50

    # --- company size thresholds (configurable) ---
    small_company_max: int = 50
    medium_company_max: int = 500

    # --- rate limiting ---
    api_rate_limit_per_minute: int = 120

    # --- scheduling ---
    scheduled_search_cron_hours: int = 0  # >0 enables periodic RUN via Celery beat

    enabled_sources: str = Field(
        default="",
        description="Comma separated connector keys to enable; empty = all available",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    return s
