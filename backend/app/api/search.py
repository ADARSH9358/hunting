from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.resume import active_profile
from app.core.security import get_current_user
from app.db import get_db
from app.models import JobMatch, SearchLog, SearchSession, User
from app.schemas import RunSearchIn, page
from app.services.search_service import SearchConflict, active_session, create_session, reap_stale
from app.worker.runner import dispatch_search

router = APIRouter(prefix="/api/search", tags=["search"])


def serialize_session(s: SearchSession, logs: list[SearchLog] | None = None) -> dict:
    d = {
        "id": s.id, "status": s.status, "progress": s.progress, "current_step": s.current_step,
        "keywords": s.keywords or [], "stats": s.stats or {}, "source_results": s.source_results or {},
        "error": s.error, "cancel_requested": s.cancel_requested, "created_at": s.created_at,
        "started_at": s.started_at, "finished_at": s.finished_at, "config": s.config or {},
    }
    if logs is not None:
        d["logs"] = [{"id": l.id, "ts": l.ts, "level": l.level, "source": l.source_key, "message": l.message} for l in logs]
    return d


async def _owned(db: AsyncSession, user: User, search_id: int) -> SearchSession:
    s = await db.get(SearchSession, search_id)
    if not s or s.user_id != user.id:
        raise HTTPException(404, "Search not found")
    return s


@router.post("/run", status_code=202)
async def run_search(body: RunSearchIn | None = None, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    profile = await active_profile(db, user.id)
    if profile is None:
        raise HTTPException(400, "Upload your resume before running a search")
    config = body.overrides.model_dump() if body and body.overrides else {}
    try:
        sess = await create_session(db, user.id, config)
    except SearchConflict as e:
        raise HTTPException(409, {"message": "A search is already running", "search_id": e.session.id})
    backend = dispatch_search(sess.id)
    return {"search_id": sess.id, "status": sess.status, "backend": backend}


@router.get("/active")
async def get_active(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await reap_stale(db)
    await db.commit()
    s = await active_session(db, user.id)
    return serialize_session(s) if s else None


@router.get("/status/{search_id}")
async def status(search_id: int, after_log_id: int = 0, user: User = Depends(get_current_user),
                 db: AsyncSession = Depends(get_db)):
    s = await _owned(db, user, search_id)
    logs = (await db.execute(select(SearchLog).where(SearchLog.session_id == s.id, SearchLog.id > after_log_id)
                             .order_by(SearchLog.id).limit(300))).scalars().all()
    return serialize_session(s, list(logs))


@router.post("/stop/{search_id}")
async def stop(search_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    s = await _owned(db, user, search_id)
    if s.status not in ("queued", "running"):
        raise HTTPException(409, f"Search is already {s.status}")
    s.cancel_requested = True
    s.current_step = "Stopping… saving results collected so far"
    await db.commit()
    return {"search_id": s.id, "status": "stopping"}


@router.get("/history")
async def history(page_no: int = 1, page_size: int = 20, user: User = Depends(get_current_user),
                  db: AsyncSession = Depends(get_db)):
    page_size = max(1, min(page_size, 100))
    total = (await db.execute(select(func.count()).select_from(SearchSession).where(SearchSession.user_id == user.id))).scalar_one()
    rows = (await db.execute(select(SearchSession).where(SearchSession.user_id == user.id)
                             .order_by(SearchSession.id.desc()).offset((page_no - 1) * page_size).limit(page_size))).scalars().all()
    items = [serialize_session(s) for s in rows]
    # compare each run with the run before it
    for i, d in enumerate(items):
        nxt = items[i + 1] if i + 1 < len(items) else None
        if nxt:
            d["delta_matching"] = (d["stats"].get("matching_jobs") or 0) - (nxt["stats"].get("matching_jobs") or 0)
    return page(items, total, page_no, page_size)


@router.get("/{search_id}/jobs")
async def jobs_for_search(search_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Jobs whose match was (re)computed in a given run, i.e. what that run found."""
    await _owned(db, user, search_id)
    n = (await db.execute(select(func.count()).select_from(JobMatch).where(
        JobMatch.user_id == user.id, JobMatch.session_id == search_id))).scalar_one()
    return {"search_id": search_id, "jobs": n}
