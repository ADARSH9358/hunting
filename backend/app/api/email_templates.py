"""Email template management."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db import get_db
from app.models import EmailTemplate, Job, JobMatch, User
from app.services import email_templates as tpl
from app.services.job_email_service import _profile, email_settings, save_email_settings

router = APIRouter(prefix="/api/email-templates", tags=["email templates"])


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    is_default: bool = False


class PreviewIn(BaseModel):
    subject: str = Field(max_length=300)
    body: str = Field(max_length=20000)
    job_id: int | None = None
    hr_name: str | None = Field(default=None, max_length=120)


def _check_vars(body: TemplateIn) -> None:
    bad = tpl.unknown_variables(body.subject, body.body)
    if bad:
        raise HTTPException(422, f"Unknown variable(s): {', '.join('{{' + b + '}}' for b in bad)}")


async def _owned(db: AsyncSession, user: User, tid: int) -> EmailTemplate:
    t = await db.get(EmailTemplate, tid)
    if not t or t.user_id != user.id:
        raise HTTPException(404, "Template not found")
    return t


@router.get("/variables")
async def variables(user: User = Depends(get_current_user)):
    return [{"name": k, "description": v} for k, v in tpl.VARIABLES.items()]


@router.get("")
async def list_templates(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await tpl.ensure_default(db, user.id)
    await db.commit()
    rows = (await db.execute(select(EmailTemplate).where(EmailTemplate.user_id == user.id)
                             .order_by(EmailTemplate.is_default.desc(), EmailTemplate.name))).scalars().all()
    return [tpl.template_out(t) for t in rows]


@router.post("", status_code=201)
async def create_template(body: TemplateIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    _check_vars(body)
    n = (await db.execute(select(func.count()).select_from(EmailTemplate).where(EmailTemplate.user_id == user.id))).scalar_one()
    if n >= 50:
        raise HTTPException(422, "You can keep at most 50 templates")
    t = EmailTemplate(user_id=user.id, name=body.name.strip(), subject=body.subject.strip(), body=body.body)
    db.add(t)
    await db.flush()
    if body.is_default or n == 0:
        await tpl.set_default(db, user.id, t.id)
        save_email_settings(user, {"default_template_id": t.id})
    await db.commit()
    await db.refresh(t)
    return tpl.template_out(t)


@router.put("/{template_id}")
async def update_template(template_id: int, body: TemplateIn, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_db)):
    _check_vars(body)
    t = await _owned(db, user, template_id)
    t.name, t.subject, t.body = body.name.strip(), body.subject.strip(), body.body
    if body.is_default:
        await tpl.set_default(db, user.id, t.id)
        save_email_settings(user, {"default_template_id": t.id})
    await db.commit()
    await db.refresh(t)
    return tpl.template_out(t)


@router.post("/{template_id}/default")
async def make_default(template_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    t = await _owned(db, user, template_id)
    await tpl.set_default(db, user.id, t.id)
    save_email_settings(user, {"default_template_id": t.id})
    await db.commit()
    return {"default_template_id": t.id}


@router.delete("/{template_id}")
async def delete_template(template_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    t = await _owned(db, user, template_id)
    n = (await db.execute(select(func.count()).select_from(EmailTemplate).where(EmailTemplate.user_id == user.id))).scalar_one()
    if n <= 1:
        raise HTTPException(422, "Keep at least one template")
    was_default = t.is_default
    await db.delete(t)  # sent emails keep a snapshot of the template name, subject and body
    await db.flush()
    if was_default or email_settings(user).get("default_template_id") == template_id:
        nxt = await tpl.ensure_default(db, user.id)
        save_email_settings(user, {"default_template_id": nxt.id})
    await db.commit()
    return {"deleted": True}


@router.post("/preview")
async def preview(body: PreviewIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Render a template against a real job (the given one, else your best current match)."""
    bad = tpl.unknown_variables(body.subject, body.body)
    job = None
    if body.job_id:
        job = await db.get(Job, body.job_id)
    if job is None:
        job = (await db.execute(select(Job).join(JobMatch, JobMatch.job_id == Job.id)
                                .where(JobMatch.user_id == user.id, Job.status == "active")
                                .order_by(JobMatch.score.desc()).limit(1))).unique().scalar_one_or_none()
    ctx = tpl.build_context(user, await _profile(db, user.id), job, body.hr_name)
    subject, text = tpl.render_template(body.subject, body.body, ctx)
    return {"subject": subject, "body": text, "unknown_variables": bad, "sample_job_id": job.id if job else None,
            "context": ctx}
