from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.resume import active_profile
from app.core.security import get_current_user
from app.db import get_db
from app.models import Company, Job, JobMatch, JobSkill, SavedJob, User
from app.schemas import SaveJobIn, page
from app.services.matching import llm_explain
from app.services.text_utils import normalize_location

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

NS = "Not specified"

# Postings often list only a city, so a country filter also matches its major cities.
COUNTRY_CITIES = {
    "india": ["bangalore", "mumbai", "delhi", "new delhi", "gurgaon", "noida", "pune", "hyderabad", "chennai",
              "kolkata", "ahmedabad", "kochi", "jaipur", "chandigarh", "indore", "coimbatore", "thiruvananthapuram",
              "trivandrum", "mysore", "nagpur", "bhubaneswar", "visakhapatnam", "lucknow", "karnataka",
              "maharashtra", "telangana", "tamil nadu", "kerala", "haryana", "uttar pradesh", "gujarat"],
}


def serialize_job(job: Job, m: JobMatch | None, saved: bool, detail: bool = False) -> dict[str, Any]:
    c = job.company
    sources = sorted(job.source_links, key=lambda l: (not l.is_official, l.first_seen_at))
    d: dict[str, Any] = {
        "id": job.id,
        "title": job.title,
        "company": {
            "id": c.id if c else None, "name": c.name if c else job.company_name,
            "logo_url": c.logo_url if c else None,
            "size_category": c.size_category if c else None,
            "size_label": ({"small": "Small (1–50)", "medium": "Medium (51–500)", "large": "Large (501+)"}
                           .get(c.size_category) if c and c.size_category else "Size not verified"),
            "employee_count": c.employee_count if c else None, "size_source": c.size_source if c else None,
            "company_type": c.company_type if c else None, "website": c.website if c else None,
            "careers_url": (c.careers_url if c else None) or job.company_careers_url,
        },
        "location": job.location or NS,
        "work_mode": job.work_mode,
        "employment_type": job.employment_type or NS,
        "experience": job.experience_text or NS,
        "experience_min_years": job.experience_min_years,
        "experience_max_years": job.experience_max_years,
        "salary": job.salary_text or NS,
        "date_posted": job.date_posted,
        "first_seen_at": job.first_seen_at,
        "last_seen_at": job.last_seen_at,
        "last_verified_at": job.last_verified_at,
        "status": job.status,
        "is_official": job.is_official,
        "apply_url": job.apply_url,
        "sources": [{"key": l.source_key, "name": l.source_name, "url": l.url, "is_official": l.is_official,
                     "first_seen_at": l.first_seen_at, "last_seen_at": l.last_seen_at, "status": l.status}
                    for l in sources],
        "skills": [s.canonical for s in job.skills],
        "saved": saved,
        "match": None,
    }
    if m:
        d["match"] = {"score": m.score, "matched_skills": m.matched_skills, "missing_skills": m.missing_skills,
                      "experience_fit": m.experience_fit, "explanation": m.explanation, "gaps": m.gaps,
                      "is_new": m.is_new, "hidden": m.hidden, "computed_at": m.computed_at}
        if detail:
            d["match"]["breakdown"] = m.breakdown
            d["match"]["llm_explanation"] = m.llm_explanation
    if detail:
        d["description"] = job.description or ""
    return d


@router.get("")
async def list_jobs(
    q: str | None = Query(None, max_length=200),
    min_score: float = Query(0, ge=0, le=100),
    max_experience: float | None = Query(None, ge=0, le=50, description="Jobs requiring at most N years"),
    location: list[str] = Query(default=[], description="One or more locations (OR). 'Remote' matches remote jobs."),
    include_remote: bool = Query(False, description="Also include remote jobs when filtering by location"),
    company_size: list[Literal["small", "medium", "large", "unknown"]] = Query(default=[]),
    work_mode: list[Literal["remote", "hybrid", "onsite", "unknown"]] = Query(default=[]),
    job_type: str | None = Query(None, max_length=50),
    salary_min: float | None = Query(None, ge=0),
    has_salary: bool = False,
    posted_within_days: int | None = Query(None, ge=1, le=365),
    skills: list[str] = Query(default=[]),
    company_type: str | None = Query(None, max_length=50),
    source: str | None = Query(None, max_length=60),
    official_only: bool = False,
    new_only: bool = False,
    include_hidden: bool = False,
    include_unavailable: bool = False,
    company_id: int | None = None,
    sort: Literal["score", "date", "salary", "company", "discovered"] = "score",
    page_no: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conds = [JobMatch.user_id == user.id, JobMatch.score >= min_score]
    if not include_hidden:
        conds.append(JobMatch.hidden.is_(False))
    if not include_unavailable:
        conds.append(Job.status == "active")
    if new_only:
        conds.append(JobMatch.is_new.is_(True))
    if q:
        like = f"%{q.lower()}%"
        conds.append(or_(func.lower(Job.title).like(like), func.lower(Job.company_name).like(like),
                         func.lower(Job.description).like(like)))
    if max_experience is not None:
        conds.append(or_(Job.experience_min_years.is_(None), Job.experience_min_years <= max_experience))
    terms = [t.strip() for raw in location for t in raw.split(",") if t.strip()][:20]
    if terms:
        loc_conds = []
        want_remote = include_remote
        for t in terms:
            if t.lower() in {"remote", "work from home", "wfh", "anywhere"}:
                want_remote = True
                continue
            norm = normalize_location(t)
            loc_conds.append(func.lower(Job.location).like(f"%{t.lower()}%"))
            if norm:
                loc_conds.append(Job.normalized_location.like(f"%{norm}%"))
            for city in COUNTRY_CITIES.get(norm, []):
                loc_conds.append(Job.normalized_location.like(f"%{city}%"))
        if want_remote:
            loc_conds.append(Job.work_mode == "remote")
        conds.append(or_(*loc_conds))
    if company_size:
        size_conds = [Company.size_category.in_([s for s in company_size if s != "unknown"])]
        if "unknown" in company_size:
            size_conds.append(Company.size_category.is_(None))
        conds.append(or_(*size_conds))
    if work_mode:
        conds.append(Job.work_mode.in_(work_mode))
    if job_type:
        conds.append(func.lower(Job.employment_type).like(f"%{job_type.lower()}%"))
    if salary_min is not None:
        conds.append(or_(Job.salary_max >= salary_min, Job.salary_min >= salary_min))
    if has_salary:
        conds.append(or_(Job.salary_min.is_not(None), Job.salary_text.is_not(None)))
    if posted_within_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=posted_within_days)
        conds.append(func.coalesce(Job.date_posted, Job.first_seen_at) >= cutoff)
    for sk in skills[:10]:
        conds.append(exists().where(and_(JobSkill.job_id == Job.id, func.lower(JobSkill.canonical) == sk.lower())))
    if company_type:
        conds.append(Company.company_type == company_type)
    if source:
        from app.models import JobSourceLink
        conds.append(exists().where(and_(JobSourceLink.job_id == Job.id, JobSourceLink.source_key == source)))
    if official_only:
        conds.append(Job.is_official.is_(True))
    if company_id:
        conds.append(Job.company_id == company_id)

    base = (select(JobMatch, Job).join(Job, Job.id == JobMatch.job_id)
            .outerjoin(Company, Company.id == Job.company_id).where(*conds))
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    order = {
        "score": [JobMatch.score.desc(), Job.date_posted.desc()],
        "date": [func.coalesce(Job.date_posted, Job.first_seen_at).desc()],
        "salary": [func.coalesce(Job.salary_max, Job.salary_min, -1).desc(), JobMatch.score.desc()],
        "company": [Job.company_name.asc(), JobMatch.score.desc()],
        "discovered": [Job.first_seen_at.desc()],
    }[sort]
    rows = (await db.execute(base.order_by(*order).offset((page_no - 1) * page_size).limit(page_size))).unique().all()
    saved = set((await db.execute(select(SavedJob.job_id).where(SavedJob.user_id == user.id))).scalars().all())
    items = [serialize_job(job, m, job.id in saved) for m, job in rows]
    return page(items, total, page_no, page_size)


@router.get("/new")
async def new_jobs(page_no: int = 1, page_size: int = 20, user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    return await list_jobs(q=None, min_score=0, max_experience=None, location=[], include_remote=False, company_size=[], work_mode=[],
                           job_type=None, salary_min=None, has_salary=False, posted_within_days=None, skills=[],
                           company_type=None, source=None, official_only=False, new_only=True, include_hidden=False,
                           include_unavailable=False, company_id=None, sort="score", page_no=page_no,
                           page_size=min(page_size, 100), user=user, db=db)


@router.get("/saved")
async def saved_jobs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(SavedJob, Job).join(Job, Job.id == SavedJob.job_id)
                             .where(SavedJob.user_id == user.id).order_by(SavedJob.saved_at.desc()))).unique().all()
    matches = {m.job_id: m for m in (await db.execute(select(JobMatch).where(
        JobMatch.user_id == user.id, JobMatch.job_id.in_([j.id for _, j in rows])))).unique().scalars().all()}
    out = []
    for sj, job in rows:
        d = serialize_job(job, matches.get(job.id), True)
        d["saved_at"], d["notes"] = sj.saved_at, sj.notes
        out.append(d)
    return out


@router.get("/{job_id}")
async def get_job(job_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    m = (await db.execute(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_id == job_id))).unique().scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Job not found")
    saved = (await db.execute(select(SavedJob.id).where(SavedJob.user_id == user.id, SavedJob.job_id == job_id))).first() is not None
    return serialize_job(job, m, saved, detail=True)


@router.post("/{job_id}/explain")
async def explain_job(job_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """LLM narrative for one match (on demand, cached)."""
    job = await db.get(Job, job_id)
    m = (await db.execute(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_id == job_id))).unique().scalar_one_or_none()
    if not job or not m:
        raise HTTPException(404, "Job not found")
    if m.llm_explanation:
        return {"llm_explanation": m.llm_explanation, "cached": True}
    p = await active_profile(db, user.id)
    d = p.data if p else {}
    summary = (f"Level: {p.experience_level if p else ''}; professional months: {p.professional_experience_months if p else 0}; "
               f"internship months: {p.internship_experience_months if p else 0}; education: {p.education_level if p else ''}; "
               f"skills: {', '.join(s.canonical for s in p.skills) if p else ''}; roles: {', '.join(d.get('job_roles', []))}")
    res = await llm_explain(summary, f"{job.title} at {job.company_name}\n{job.experience_text or ''}\n{job.description[:7000]}")
    if not res:
        raise HTTPException(503, "No LLM provider configured (set LLM_PROVIDER and an API key). The deterministic explanation is shown instead.")
    text = str(res.get("assessment", ""))[:2000]
    tips = [str(t)[:300] for t in (res.get("tips") or [])][:5]
    m.llm_explanation = text + ("\n\nTips:\n- " + "\n- ".join(tips) if tips else "")
    await db.commit()
    return {"llm_explanation": m.llm_explanation, "cached": False}


@router.post("/{job_id}/save", status_code=201)
async def save_job(job_id: int, body: SaveJobIn | None = None, user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    if not await db.get(Job, job_id):
        raise HTTPException(404, "Job not found")
    existing = (await db.execute(select(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_id == job_id))).scalar_one_or_none()
    if existing:
        if body and body.notes is not None:
            existing.notes = body.notes
    else:
        db.add(SavedJob(user_id=user.id, job_id=job_id, notes=body.notes if body else None))
    await db.commit()
    return {"job_id": job_id, "saved": True}


@router.delete("/{job_id}/save")
async def unsave_job(job_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    sj = (await db.execute(select(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_id == job_id))).scalar_one_or_none()
    if sj:
        await db.delete(sj)
        await db.commit()
    return {"job_id": job_id, "saved": False}


@router.post("/{job_id}/hide")
async def hide_job(job_id: int, hidden: bool = True, user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)):
    m = (await db.execute(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.job_id == job_id))).unique().scalar_one_or_none()
    if not m:
        raise HTTPException(404, "Job not found")
    m.hidden = hidden
    await db.commit()
    return {"job_id": job_id, "hidden": hidden}
