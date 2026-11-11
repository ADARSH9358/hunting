"""SearchHistoryService + search start/stop with concurrency protection."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import db as dbmod
from app.models import CandidateProfile, SearchSession, User

STALE_AFTER = timedelta(minutes=10)
ACTIVE = ("queued", "running")
_start_lock = asyncio.Lock()


class SearchConflict(Exception):
    def __init__(self, session: SearchSession):
        self.session = session


async def reap_stale(db: AsyncSession) -> int:
    """Sessions whose worker died (no heartbeat) are marked failed."""
    cutoff = datetime.now(timezone.utc) - STALE_AFTER
    res = await db.execute(
        update(SearchSession)
        .where(SearchSession.status.in_(ACTIVE))
        .where((SearchSession.heartbeat_at < cutoff) | (SearchSession.heartbeat_at.is_(None) & (SearchSession.created_at < cutoff)))
        .values(status="failed", error="Search worker stopped unexpectedly", finished_at=datetime.now(timezone.utc))
    )
    return res.rowcount or 0


async def active_session(db: AsyncSession, user_id: int) -> SearchSession | None:
    return (await db.execute(select(SearchSession).where(
        SearchSession.user_id == user_id, SearchSession.status.in_(ACTIVE))
        .order_by(SearchSession.id.desc()).limit(1))).scalar_one_or_none()


async def create_session(db: AsyncSession, user_id: int, config: dict | None = None) -> SearchSession:
    async with _start_lock:  # guards double clicks within one API process; DB check guards the rest
        await reap_stale(db)
        current = await active_session(db, user_id)
        if current:
            raise SearchConflict(current)
        now = datetime.now(timezone.utc)
        sess = SearchSession(user_id=user_id, status="queued", config=config or {}, heartbeat_at=now, created_at=now)
        db.add(sess)
        await db.commit()
        await db.refresh(sess)
        return sess


async def start_scheduled_searches() -> int:
    """Called from Celery beat inside asyncio.run(): uses a loop-local engine."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.config import get_settings
    from app.services.orchestrator import run_search
    started = 0
    engine = dbmod._make_engine(get_settings().database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as db:
        users = (await db.execute(select(User.id).join(CandidateProfile, CandidateProfile.user_id == User.id)
                                  .where(User.is_active.is_(True)).distinct())).scalars().all()
        sessions = []
        for uid in users:
            try:
                sessions.append(await create_session(db, uid, {"trigger": "scheduled"}))
                started += 1
            except SearchConflict:
                continue
    await engine.dispose()
    for s in sessions:
        await run_search(s.id, own_engine=True)
    return started
