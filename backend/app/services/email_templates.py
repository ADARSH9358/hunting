"""Email template variables, rendering and the built-in default template."""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CandidateProfile, EmailTemplate, Job, User

VARIABLES: dict[str, str] = {
    "hr_name": "Recruiter's name (falls back to 'Hiring Manager')",
    "company_name": "Company name",
    "job_title": "Job title",
    "candidate_name": "Your name from the resume profile",
    "candidate_email": "Your email from the resume profile",
    "candidate_phone": "Your phone from the resume profile",
    "experience": "Your experience summary, e.g. '14 months of internship experience'",
    "skills": "Your top skills, comma separated",
    "resume_link": "Public resume link (set it in Applications → Settings)",
    "job_link": "Link to the job posting",
}
VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_]+)\s*\}\}")

DEFAULT_NAME = "Standard application"
DEFAULT_SUBJECT = "Application for {{job_title}} Position – {{candidate_name}}"
DEFAULT_BODY = """Dear {{hr_name}},

I hope you are doing well.

I am writing to express my interest in the {{job_title}} position at {{company_name}}.

I have experience working with {{skills}}. I believe my technical background would allow me to contribute effectively to your team.

Please find my resume attached for your consideration.

I would appreciate the opportunity to discuss my application further.

Best regards,
{{candidate_name}}
{{candidate_email}}
{{candidate_phone}}
"""


def unknown_variables(*texts: str) -> list[str]:
    found = {m.group(1) for t in texts for m in VAR_RE.finditer(t or "")}
    return sorted(found - set(VARIABLES))


def render(text: str, ctx: dict[str, str]) -> str:
    return VAR_RE.sub(lambda m: ctx.get(m.group(1), m.group(0)), text or "")


def _experience_text(p: CandidateProfile | None) -> str:
    if not p:
        return ""

    def fmt(m: int) -> str:
        y, mo = divmod(int(m or 0), 12)
        parts = ([f"{y} year{'s' if y != 1 else ''}"] if y else []) + ([f"{mo} month{'s' if mo != 1 else ''}"] if mo else [])
        return " ".join(parts)
    if p.professional_experience_months:
        out = f"{fmt(p.professional_experience_months)} of professional experience"
        if p.internship_experience_months:
            out += f" plus {fmt(p.internship_experience_months)} of internships"
        return out
    if p.internship_experience_months:
        return f"{fmt(p.internship_experience_months)} of internship experience"
    return "a strong project portfolio"


def build_context(user: User, profile: CandidateProfile | None, job: Job | None, hr_name: str | None) -> dict[str, str]:
    data: dict[str, Any] = (profile.data if profile else None) or {}
    skills = [s.canonical for s in profile.skills][:8] if profile else []
    email_cfg = (user.settings or {}).get("email") or {}
    return {
        "hr_name": (hr_name or "").strip() or "Hiring Manager",
        "company_name": (job.company.name if job and job.company else (job.company_name if job else "")) or "your company",
        "job_title": (job.title if job else "") or "the open",
        "candidate_name": data.get("candidate") or user.full_name or "",
        "candidate_email": data.get("email") or user.email,
        "candidate_phone": data.get("phone") or "",
        "experience": _experience_text(profile),
        "skills": ", ".join(skills),
        "resume_link": email_cfg.get("resume_link") or "",
        "job_link": (job.apply_url if job else "") or "",
    }


def render_template(subject: str, body: str, ctx: dict[str, str]) -> tuple[str, str]:
    s = re.sub(r"\s+", " ", render(subject, ctx)).strip()
    b = render(body, ctx)
    b = re.sub(r"\n{3,}", "\n\n", b).strip() + "\n"  # empty variables (e.g. no phone) leave no holes
    return s, b


async def ensure_default(db: AsyncSession, user_id: int) -> EmailTemplate:
    """Every user has at least one template; returns the default one."""
    rows = (await db.execute(select(EmailTemplate).where(EmailTemplate.user_id == user_id)
                             .order_by(EmailTemplate.is_default.desc(), EmailTemplate.id))).scalars().all()
    if not rows:
        t = EmailTemplate(user_id=user_id, name=DEFAULT_NAME, subject=DEFAULT_SUBJECT, body=DEFAULT_BODY, is_default=True)
        db.add(t)
        await db.flush()
        return t
    if not rows[0].is_default:
        rows[0].is_default = True
        await db.flush()
    return rows[0]


async def set_default(db: AsyncSession, user_id: int, template_id: int) -> None:
    await db.execute(update(EmailTemplate).where(EmailTemplate.user_id == user_id)
                     .values(is_default=EmailTemplate.id == template_id))


def template_out(t: EmailTemplate) -> dict:
    return {"id": t.id, "name": t.name, "subject": t.subject, "body": t.body, "is_default": t.is_default,
            "created_at": t.created_at, "updated_at": t.updated_at}
