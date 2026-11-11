"""Job application emails: drafts, preview, send, retry, automatic sending, history."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import db as dbmod
from app.config import get_settings
from app.core.security import get_current_user
from app.db import get_db
from app.models import Job, JobEmail, Resume, User
from app.schemas import page
from app.services import job_email_service as svc
from app.services.storage import ResumeStorage

router = APIRouter(prefix="/api/job-emails", tags=["job emails"])
Status = Literal["pending", "ready", "sending", "sent", "failed", "skipped"]


class DraftIn(BaseModel):
    job_id: int
    recipient_email: str | None = Field(default=None, max_length=320)
    hr_name: str | None = Field(default=None, max_length=120)
    template_id: int | None = None
    sender_account_id: int | None = None


class DraftUpdate(BaseModel):
    recipient_email: str | None = Field(default=None, max_length=320)
    hr_name: str | None = Field(default=None, max_length=120)
    sender_account_id: int | None = None
    template_id: int | None = None
    resume_id: int | None = None
    attach_resume: bool | None = None
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, max_length=20000)


class PreviewIn(BaseModel):
    job_id: int
    template_id: int | None = None
    hr_name: str | None = Field(default=None, max_length=120)


class EmailSettingsIn(BaseModel):
    auto_send_enabled: bool | None = None
    daily_limit: int | None = Field(default=None, ge=1, le=500)
    auto_min_score: float | None = Field(default=None, ge=0, le=100)
    default_account_id: int | None = None
    default_template_id: int | None = None
    attach_resume: bool | None = None
    resume_link: str | None = Field(default=None, max_length=500)
    detect_on_run: bool | None = None


def _raise(e: svc.EmailError):
    raise HTTPException(e.status_code, str(e))


async def _one(db: AsyncSession, user: User, je: JobEmail) -> dict:
    await db.refresh(je)
    return (await svc.serialize(db, [je], user.id))[0]


# ------------------------------------------------------------------ settings / stats
@router.get("/settings")
async def get_email_settings(user: User = Depends(get_current_user)):
    return {**svc.email_settings(user), "daily_limit_max": get_settings().email_daily_limit_max}


@router.put("/settings")
async def put_email_settings(body: EmailSettingsIn, background: BackgroundTasks, user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    patch = body.model_dump(exclude_unset=True)
    if patch.get("resume_link") and not patch["resume_link"].startswith(("https://", "http://")):
        raise HTTPException(422, "Resume link must be an http(s) URL")
    was_on = svc.email_settings(user)["auto_send_enabled"]
    cfg = svc.save_email_settings(user, patch)
    await db.commit()
    if cfg["auto_send_enabled"] and not was_on:
        background.add_task(svc.process_auto_queue, dbmod.session_factory(), user.id)
    return {**cfg, "daily_limit_max": get_settings().email_daily_limit_max}


@router.get("/stats")
async def stats(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = dict((await db.execute(select(JobEmail.status, func.count()).where(JobEmail.user_id == user.id)
                                  .group_by(JobEmail.status))).all())
    cfg = svc.email_settings(user)
    return {"by_status": {s: int(rows.get(s, 0)) for s in svc.STATUSES},
            "sent_last_24h": await svc.sent_in_last_24h(db, user.id),
            "daily_limit": cfg["daily_limit"], "auto_send_enabled": cfg["auto_send_enabled"]}


# ------------------------------------------------------------------ list / history
@router.get("")
async def list_emails(
    status: list[Status] = Query(default=[]), q: str | None = Query(None, max_length=100),
    date_from: date | None = None, date_to: date | None = None, job_id: int | None = None,
    page_no: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    df = datetime.combine(date_from, time.min, tzinfo=timezone.utc) if date_from else None
    dt = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc) if date_to else None
    stmt = svc.history_query(user.id, list(status), q, df, dt)
    if job_id:
        stmt = stmt.where(JobEmail.job_id == job_id)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((page_no - 1) * page_size).limit(page_size))).unique().scalars().all()
    return page(await svc.serialize(db, list(rows), user.id), total, page_no, page_size)


# ------------------------------------------------------------------ drafts / preview
@router.post("/preview")
async def preview(body: PreviewIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, body.job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    from app.services.hr_email_detection import detect_hr_emails
    found = detect_hr_emails(job.description)
    t = await svc._template(db, user, body.template_id)
    subject, text = await svc.render_for(db, user, job, t, body.hr_name or (found[0].hr_name if found else None))
    return {"subject": subject, "body": text, "template_id": t.id,
            "detected_recipients": [{"email": d.email, "hr_name": d.hr_name} for d in found[:5]]}


@router.post("/drafts", status_code=201)
async def create_draft(body: DraftIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, body.job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    try:
        je = await svc.create_draft(db, user, job, recipient=body.recipient_email, hr_name=body.hr_name,
                                    template_id=body.template_id, account_id=body.sender_account_id)
    except svc.EmailError as e:
        _raise(e)
    await db.commit()
    return await _one(db, user, je)


@router.post("/auto-send", status_code=202)
async def auto_send(background: BackgroundTasks, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Process the automatic-send queue now (only when automatic sending is enabled)."""
    if not svc.email_settings(user)["auto_send_enabled"]:
        raise HTTPException(409, "Automatic sending is off - enable it in Applications → Settings first")
    n = len(await svc.auto_send_candidates(db, user))
    background.add_task(svc.process_auto_queue, dbmod.session_factory(), user.id)
    return {"queued": n}


@router.get("/{email_id}")
async def get_email(email_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        je = await svc.owned(db, user.id, email_id)
    except svc.EmailError as e:
        _raise(e)
    return await _one(db, user, je)


@router.put("/{email_id}")
async def update_email(email_id: int, body: DraftUpdate, user: User = Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    try:
        je = await svc.owned(db, user.id, email_id)
        await svc.update_draft(db, user, je, body.model_dump(exclude_unset=True))
    except svc.EmailError as e:
        _raise(e)
    await db.commit()
    return await _one(db, user, je)


@router.post("/{email_id}/send")
async def send(email_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        je = await svc.send_job_email(db, user, email_id, mode="manual")
    except svc.EmailError as e:
        _raise(e)
    return await _one(db, user, je)


@router.post("/{email_id}/retry")
async def retry(email_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        je = await svc.owned(db, user.id, email_id)
        if je.status != "failed":
            raise svc.EmailError("Only failed emails can be retried", 409)
        je = await svc.send_job_email(db, user, email_id, mode="manual")
    except svc.EmailError as e:
        _raise(e)
    return await _one(db, user, je)


@router.post("/{email_id}/skip")
async def skip(email_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        je = await svc.owned(db, user.id, email_id)
    except svc.EmailError as e:
        _raise(e)
    if je.status in ("sent", "sending"):
        raise HTTPException(409, "This email was already sent")
    je.status = "skipped"
    await db.commit()
    return await _one(db, user, je)


@router.delete("/{email_id}")
async def delete_draft(email_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        je = await svc.owned(db, user.id, email_id)
    except svc.EmailError as e:
        _raise(e)
    if je.status in ("sent", "sending"):
        raise HTTPException(409, "Sent emails stay in your history")
    await db.delete(je)
    await db.commit()
    return {"deleted": True}


@router.get("/{email_id}/attachment")
async def attachment(email_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The resume PDF that will be (or was) attached - for previewing before sending."""
    try:
        je = await svc.owned(db, user.id, email_id)
    except svc.EmailError as e:
        _raise(e)
    r = await db.get(Resume, je.resume_id) if je.resume_id else None
    if not r or r.user_id != user.id:
        raise HTTPException(404, "No resume selected for this email")
    data = ResumeStorage().load(r.stored_path, r.encrypted)
    if not data.startswith(b"%PDF-"):
        raise HTTPException(422, "The selected resume is not a PDF, so it cannot be attached")
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": "inline; filename=resume.pdf", "Cache-Control": "no-store"})
