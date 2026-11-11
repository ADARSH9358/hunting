"""Companies, dashboard stats, sources and settings endpoints."""
from __future__ import annotations

from datetime import datetime, timezone  # noqa: F401
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.resume import active_profile
from app.config import get_settings
from app.core.security import get_current_user
from app.db import get_db
from app.models import Company, Job, JobMatch, JobSource, SearchSession, User
from app.schemas import CompanyUpdate, UserSettings, page
from app.services.company_discovery import domain_of, size_category
from app.services.orchestrator import sync_sources

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/companies")
async def companies(
    q: str | None = Query(None, max_length=100),
    size: list[Literal["small", "medium", "large", "unknown"]] = Query(default=[]),
    with_jobs: bool = False,
    sort: Literal["matches", "name", "recent", "checked"] = "matches",
    page_no: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    match_count = (select(Job.company_id.label("cid"), func.count(JobMatch.id).label("n"),
                          func.max(JobMatch.score).label("best"))
                   .join(JobMatch, and_(JobMatch.job_id == Job.id, JobMatch.user_id == user.id))
                   .where(Job.status == "active").group_by(Job.company_id).subquery())
    stmt = select(Company, func.coalesce(match_count.c.n, 0), match_count.c.best).outerjoin(
        match_count, match_count.c.cid == Company.id)
    if q:
        stmt = stmt.where(func.lower(Company.name).like(f"%{q.lower()}%"))
    if size:
        conds = [Company.size_category.in_([s for s in size if s != "unknown"])]
        if "unknown" in size:
            conds.append(Company.size_category.is_(None))
        stmt = stmt.where(or_(*conds))
    if with_jobs:
        stmt = stmt.where(match_count.c.n > 0)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    order = {"matches": [func.coalesce(match_count.c.n, 0).desc(), Company.name],
             "name": [Company.name], "recent": [Company.first_discovered_at.desc()],
             "checked": [Company.last_checked_at.desc()]}[sort]
    rows = (await db.execute(stmt.order_by(*order).offset((page_no - 1) * page_size).limit(page_size))).all()
    items = [{
        "id": c.id, "name": c.name, "website": c.website, "domain": c.domain, "careers_url": c.careers_url,
        "logo_url": c.logo_url, "size_category": c.size_category, "employee_count": c.employee_count,
        "size_label": {"small": "Small", "medium": "Medium", "large": "Large"}.get(c.size_category or "", "Size not verified"),
        "size_source": c.size_source, "company_type": c.company_type,
        "ats_type": c.ats_type if c.ats_type != "none" else None, "discovered_via": c.discovered_via,
        "first_discovered_at": c.first_discovered_at, "last_checked_at": c.last_checked_at,
        "last_check_status": c.last_check_status, "open_jobs_count": c.open_jobs_count,
        "matching_jobs": n, "best_score": best,
    } for c, n, best in rows]
    return page(items, total, page_no, page_size)


@router.put("/companies/{company_id}")
async def update_company(company_id: int, body: CompanyUpdate, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    c = await db.get(Company, company_id)
    if not c:
        raise HTTPException(404, "Company not found")
    data = body.model_dump(exclude_unset=True)
    if "employee_count" in data:
        c.employee_count = data["employee_count"]
        c.size_category = size_category(data["employee_count"], (user.settings or {}).get("small_company_max"),
                                        (user.settings or {}).get("medium_company_max"))
        c.size_source = "user" if data["employee_count"] else None
    if "company_type" in data:
        c.company_type = data["company_type"]
    for k in ("careers_url", "website"):
        if k in data and data[k]:
            if not data[k].startswith(("http://", "https://")):
                raise HTTPException(422, f"{k} must be an http(s) URL")
            setattr(c, k, data[k])
            if k == "website":
                c.domain = domain_of(data[k])
    if "careers_url" in data and data["careers_url"]:
        c.ats_type = None if c.ats_type == "none" else c.ats_type
    await db.commit()
    return {"id": c.id, "size_category": c.size_category}


@router.get("/dashboard/stats")
async def dashboard_stats(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await active_profile(db, user.id)
    min_score = float((p.preferences or {}).get("min_match_score", 40)) if p else 40
    base = (select(JobMatch.score, Company.size_category, JobMatch.is_new, Job.is_official)
            .join(Job, Job.id == JobMatch.job_id).outerjoin(Company, Company.id == Job.company_id)
            .where(JobMatch.user_id == user.id, JobMatch.hidden.is_(False), Job.status == "active")).subquery()
    row = (await db.execute(select(
        func.count(),
        func.sum(case((base.c.score >= min_score, 1), else_=0)),
        func.sum(case((base.c.score >= 75, 1), else_=0)),
        func.sum(case((and_(base.c.size_category == "small", base.c.score >= min_score), 1), else_=0)),
        func.sum(case((and_(base.c.size_category == "medium", base.c.score >= min_score), 1), else_=0)),
        func.sum(case((and_(base.c.is_new.is_(True), base.c.score >= min_score), 1), else_=0)),
        func.sum(case((and_(base.c.is_official.is_(True), base.c.score >= min_score), 1), else_=0)),
    ))).one()
    last = (await db.execute(select(SearchSession).where(SearchSession.user_id == user.id)
                             .order_by(SearchSession.id.desc()).limit(1))).scalar_one_or_none()
    last_done = (await db.execute(select(SearchSession).where(
        SearchSession.user_id == user.id, SearchSession.status.in_(["completed", "cancelled"]))
        .order_by(SearchSession.id.desc()).limit(1))).scalar_one_or_none()
    companies = (await db.execute(select(func.count()).select_from(Company))).scalar_one()
    score_hist = (await db.execute(select(
        func.sum(case((base.c.score >= 75, 1), else_=0)),
        func.sum(case((and_(base.c.score >= 60, base.c.score < 75), 1), else_=0)),
        func.sum(case((and_(base.c.score >= 40, base.c.score < 60), 1), else_=0)),
        func.sum(case((base.c.score < 40, 1), else_=0)),
    ))).one()
    return {
        "profile": None if not p else {
            "candidate": (p.data or {}).get("candidate"), "experience_level": p.experience_level,
            "professional_experience_months": p.professional_experience_months,
            "internship_experience_months": p.internship_experience_months,
            "skills_count": len(p.skills), "top_skills": [s.canonical for s in p.skills][:8],
            "job_roles": (p.data or {}).get("job_roles", [])[:5], "updated_at": p.updated_at,
        },
        "min_match_score": min_score,
        "total_jobs": row[0] or 0,
        "matching_jobs": int(row[1] or 0),
        "highly_relevant": int(row[2] or 0),
        "small_company_jobs": int(row[3] or 0),
        "medium_company_jobs": int(row[4] or 0),
        "new_jobs": int(row[5] or 0),
        "official_jobs": int(row[6] or 0),
        "companies_tracked": companies,
        "score_distribution": {"75+": int(score_hist[0] or 0), "60-74": int(score_hist[1] or 0),
                               "40-59": int(score_hist[2] or 0), "<40": int(score_hist[3] or 0)},
        "last_search": None if not last else {"id": last.id, "status": last.status, "created_at": last.created_at,
                                              "finished_at": last.finished_at, "progress": last.progress},
        "last_completed_search": None if not last_done else {"id": last_done.id, "finished_at": last_done.finished_at,
                                                             "stats": last_done.stats},
    }


@router.get("/sources")
async def sources(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await sync_sources(db)
    await db.commit()
    order = {"ok": 0, "available": 1, "via_provider": 3, "needs_credentials": 2}
    return sorted([{
        "key": s.key, "name": s.name, "kind": s.kind, "status": s.status, "enabled": s.enabled,
        "requires_credentials": s.requires_credentials, "is_official_company_source": s.is_official_company_source,
        "notes": s.notes, "base_url": s.base_url, "last_run_at": s.last_run_at, "last_error": s.last_error,
        "last_job_count": s.last_job_count,
    } for s in rows.values()], key=lambda x: (order.get(x["status"], 1), x["name"]))


@router.put("/sources/{key}")
async def toggle_source(key: str, enabled: bool, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    s = (await db.execute(select(JobSource).where(JobSource.key == key))).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Unknown source")
    s.enabled = enabled
    await db.commit()
    return {"key": key, "enabled": enabled}


@router.get("/settings")
async def get_user_settings(user: User = Depends(get_current_user)):
    s = get_settings()
    from app.services.llm import get_llm
    return {
        **UserSettings(small_company_max=s.small_company_max, medium_company_max=s.medium_company_max).model_dump(),
        **(user.settings or {}),
        "llm_provider": get_llm().provider, "task_backend": s.task_backend,
        "database": "postgresql" if s.database_url.startswith("postgresql") else "sqlite",
        "resume_encryption": bool(s.resume_encryption_key),
    }


@router.put("/settings")
async def put_user_settings(body: UserSettings, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if body.medium_company_max <= body.small_company_max:
        raise HTTPException(422, "medium_company_max must be greater than small_company_max")
    user.settings = {**(user.settings or {}), **body.model_dump()}
    # re-classify companies with known employee counts under the new thresholds
    rows = (await db.execute(select(Company).where(Company.employee_count.is_not(None)))).scalars().all()
    for c in rows:
        c.size_category = size_category(c.employee_count, body.small_company_max, body.medium_company_max)
    await db.commit()
    return user.settings
