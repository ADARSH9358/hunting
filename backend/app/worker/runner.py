"""Dispatch the search pipeline to the configured background backend.

inprocess: a dedicated daemon thread with its own event loop + DB engine, so the
           CPU-heavy parsing of thousands of postings never blocks the API.
celery:    a Celery worker process (requires Redis).
"""
from __future__ import annotations

import logging
import threading

from app.config import get_settings

log = logging.getLogger(__name__)


def dispatch_search(session_id: int) -> str:
    backend = get_settings().task_backend.lower()
    if backend == "celery":
        from app.worker.celery_app import run_search_task
        run_search_task.delay(session_id)
        return "celery"
    from app.services.orchestrator import run_search_blocking
    t = threading.Thread(target=run_search_blocking, args=(session_id,), name=f"search-{session_id}", daemon=True)
    t.start()
    return "inprocess"
