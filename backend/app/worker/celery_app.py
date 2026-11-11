"""Celery worker: `celery -A app.worker.celery_app worker -l info` (and `beat` for schedules)."""
from __future__ import annotations

import asyncio

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

s = get_settings()
celery = Celery("jobhunt", broker=s.redis_url, backend=s.redis_url)
celery.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_time_limit=60 * 60,
                   task_soft_time_limit=55 * 60, broker_connection_retry_on_startup=True)

if s.scheduled_search_cron_hours > 0:
    celery.conf.beat_schedule = {
        "scheduled-search": {
            "task": "jobhunt.scheduled_search",
            "schedule": crontab(minute=0, hour=f"*/{s.scheduled_search_cron_hours}"),
        }
    }


@celery.task(name="jobhunt.run_search", bind=True, max_retries=1, default_retry_delay=60)
def run_search_task(self, session_id: int) -> None:
    from app.services.orchestrator import run_search_blocking
    run_search_blocking(session_id)


@celery.task(name="jobhunt.scheduled_search")
def scheduled_search() -> int:
    """Start a RUN for every user that has a profile and no active search."""
    from app.services.search_service import start_scheduled_searches
    return asyncio.run(start_scheduled_searches())
