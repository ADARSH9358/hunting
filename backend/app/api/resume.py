from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import get_current_user
from app.db import get_db
from app.models import CandidateProfile, CandidateSkill, Resume, User
from app.schemas import Preferences, ProfileUpdate
from app.services import skills_taxonomy as tax
from app.services.resume_analysis import analyze_resume, categorize, compute_experience, default_preferences
from app.services.resume_parser import ResumeValidationError, detect_type, extract_text
from app.services.storage import ResumeStorage
from app.services.text_utils import detect_education_level, experience_level

router = APIRouter(prefix="/api/resume", tags=["resume"])


async def active_profile(db: AsyncSession, user_id: int) -> CandidateProfile | None:
    return (await db.execute(select(CandidateProfile).where(
        CandidateProfile.user_id == user_id, CandidateProfile.is_active.is_(True))
        .order_by(CandidateProfile.updated_at.desc()).limit(1))).scalar_one_or_none()


def _set_skills(profile: CandidateProfile, skills: list[str], source: str) -> list[str]:
    """Diff-update skills (avoids delete+insert unique-constraint races on flush)."""
    wanted: dict[str, str] = {}
    for s in skills:
        canon = tax.canonical_name(s)[:100]
        wanted.setdefault(canon.lower(), canon)
    existing = {sk.canonical.lower(): sk for sk in profile.skills}
    for key, sk in existing.items():
        if key not in wanted:
            profile.skills.remove(sk)
    for key, canon in wanted.items():
        if key not in existing:
            profile.skills.append(CandidateSkill(name=canon, canonical=canon, category=tax.category_of(canon), source=source))
    order = list(wanted)
    profile.skills.sort(key=lambda sk: order.index(sk.canonical.lower()) if sk.canonical.lower() in order else 999)
    return [x.canonical for x in profile.skills]


def serialize_profile(p: CandidateProfile, resume: Resume | None = None) -> dict[str, Any]:
    d = dict(p.data or {})
    d.update({
        "id": p.id,
        "experience_level": p.experience_level,
        "total_experience_months": p.total_experience_months,
        "professional_experience_months": p.professional_experience_months,
        "internship_experience_months": p.internship_experience_months,
        "relevant_experience_months": p.relevant_experience_months,
        "education_level": p.education_level,
        "skills": [s.canonical for s in p.skills],
        "skills_by_category": categorize([s.canonical for s in p.skills]),
        "analysis_method": p.analysis_method,
        "edited_by_user": p.edited_by_user,
        "preferences": p.preferences or {},
        "updated_at": p.updated_at,
    })
    if resume:
        d["resume"] = {"id": resume.id, "filename": resume.original_filename, "uploaded_at": resume.uploaded_at,
                       "size_bytes": resume.size_bytes, "encrypted": resume.encrypted}
    return d


@router.post("/upload", status_code=201)
async def upload_resume(file: UploadFile = File(...), user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    s = get_settings()
    max_bytes = s.max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, f"File too large (max {s.max_upload_mb} MB)")
    if not data:
        raise HTTPException(400, "Empty file")
    try:
        mime, ext = detect_type(file.filename or "", data)
        text = extract_text(data, mime)
    except ResumeValidationError as e:
        raise HTTPException(422, str(e))

    rel, digest, encrypted = ResumeStorage().save(user.id, data, ext)
    await db.execute(update(Resume).where(Resume.user_id == user.id).values(is_active=False))
    resume = Resume(user_id=user.id, original_filename=(file.filename or f"resume{ext}")[:255], stored_path=rel,
                    content_type=mime, size_bytes=len(data), sha256=digest, encrypted=encrypted, raw_text=text)
    db.add(resume)
    await db.flush()

    analysis = await analyze_resume(text)
    old = await active_profile(db, user.id)
    await db.execute(update(CandidateProfile).where(CandidateProfile.user_id == user.id).values(is_active=False))
    prefs = default_preferences(analysis)
    if old and old.preferences:
        # keep user-chosen preferences, refresh resume-derived suggestions
        prefs = {**prefs, **{k: v for k, v in old.preferences.items() if k not in ("preferred_roles", "preferred_technologies")}}
    profile = CandidateProfile(
        user_id=user.id, resume_id=resume.id, data=analysis, preferences=prefs,
        experience_level=analysis["experience_level"],
        total_experience_months=analysis["total_experience_months"],
        professional_experience_months=analysis["professional_experience_months"],
        internship_experience_months=analysis["internship_experience_months"],
        relevant_experience_months=analysis["relevant_experience_months"],
        education_level=analysis["education_level"], analysis_method=analysis["analysis_method"], is_active=True,
        skills=[],
    )
    _set_skills(profile, analysis["skills"], "resume")
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return serialize_profile(profile, resume)


@router.get("/profile")
async def get_profile(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await active_profile(db, user.id)
    if not p:
        raise HTTPException(404, "No resume uploaded yet")
    resume = await db.get(Resume, p.resume_id) if p.resume_id else None
    return serialize_profile(p, resume)


@router.put("/profile")
async def update_profile(body: ProfileUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await active_profile(db, user.id)
    if not p:
        raise HTTPException(404, "No resume uploaded yet")
    data = dict(p.data or {})
    patch = body.model_dump(exclude_unset=True)
    for k in ("candidate", "email", "phone", "location", "summary", "certifications", "job_roles",
              "transferable_skills", "preferred_industries"):
        if k in patch:
            data[k] = patch[k]
    if "projects" in patch:
        data["projects"] = patch["projects"]
    if "education" in patch:
        data["education"] = patch["education"]
        lvl = detect_education_level(" ".join(f"{e.get('degree') or ''}" for e in patch["education"]))
        if lvl:
            p.education_level = lvl
    if "education_level" in patch:
        p.education_level = patch["education_level"]
    if "experience" in patch:
        data["experience"] = patch["experience"]
        exp = compute_experience(data["experience"])
        data.update(exp)
        p.total_experience_months = exp["total_experience_months"]
        p.professional_experience_months = exp["professional_experience_months"]
        p.internship_experience_months = exp["internship_experience_months"]
        p.relevant_experience_months = exp["relevant_experience_months"]
    if "professional_experience_months" in patch:
        p.professional_experience_months = patch["professional_experience_months"]
    if "internship_experience_months" in patch:
        p.internship_experience_months = patch["internship_experience_months"]
    if "skills" in patch:
        data["skills"] = _set_skills(p, patch["skills"], "user")
    p.experience_level = experience_level(p.professional_experience_months, p.internship_experience_months)
    data["experience_level"] = p.experience_level
    data["previous_companies"] = list(dict.fromkeys(e.get("company") for e in data.get("experience", []) if e.get("company")))
    p.data = data
    p.edited_by_user = True
    await db.commit()
    await db.refresh(p)
    return serialize_profile(p)


@router.get("/preferences")
async def get_preferences(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await active_profile(db, user.id)
    if not p:
        raise HTTPException(404, "No resume uploaded yet")
    return {**Preferences().model_dump(), **(p.preferences or {}), "suggested": default_preferences(serialize_profile(p))}


@router.put("/preferences")
async def put_preferences(body: Preferences, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await active_profile(db, user.id)
    if not p:
        raise HTTPException(404, "No resume uploaded yet")
    p.preferences = body.model_dump()
    await db.commit()
    return p.preferences


@router.get("/history")
async def resume_history(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Resume).where(Resume.user_id == user.id).order_by(Resume.uploaded_at.desc()))).scalars().all()
    return [{"id": r.id, "filename": r.original_filename, "uploaded_at": r.uploaded_at, "is_active": r.is_active,
             "size_bytes": r.size_bytes} for r in rows]
