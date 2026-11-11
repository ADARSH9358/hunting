"""Job application emails: drafts, sending, the automatic queue and history.

Safety rails
* A row moves to ``sending`` with a conditional UPDATE (``WHERE status IN ('ready','failed')``),
  so a double click, a retry racing the auto-queue, or two workers can never send it twice.
* (user, job, recipient) is UNIQUE in the database - one email per job recipient, ever.
* Automatic sending is OFF until the user enables it, re-checks that flag before every
  message, respects the user's daily limit and a global hard cap, never emails the same
  recruiter twice within a cool-down window, and only uses recipients that were found in
  the posting itself or entered by the user, after a DNS deliverability check.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models import CandidateProfile, EmailTemplate, GmailAccount, Job, JobEmail, JobMatch, Resume, User
from app.services import email_templates as tpl
from app.services.gmail_email import Attachment, GmailSendError, build_message, send_message, validate_pdf
from app.services.gmail_oauth import GmailAuthError, GmailNotConfigured, get_access_token
from app.services.hr_email_detection import best_hr_email, check_deliverable, normalize_email
from app.services.storage import ResumeStorage

log = logging.getLogger(__name__)

STATUSES = ("pending", "ready", "sending", "sent", "failed", "skipped")
SENDABLE = ("ready", "failed")
RECRUITER_COOLDOWN_DAYS = 7
DEFAULT_EMAIL_SETTINGS: dict[str, Any] = {
    "auto_send_enabled": False,
    "daily_limit": 10,
    "auto_min_score": 60,
    "default_account_id": None,
    "default_template_id": None,
    "attach_resume": True,
    "resume_link": "",
    "detect_on_run": True,
}


class EmailError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ------------------------------------------------------------------ settings
def email_settings(user: User) -> dict[str, Any]:
    return {**DEFAULT_EMAIL_SETTINGS, **((user.settings or {}).get("email") or {})}


def save_email_settings(user: User, patch: dict[str, Any]) -> dict[str, Any]:
    cur = email_settings(user)
    cur.update({k: v for k, v in patch.items() if k in DEFAULT_EMAIL_SETTINGS})
    cur["daily_limit"] = max(1, min(int(cur["daily_limit"]), get_settings().email_daily_limit_max))
    user.settings = {**(user.settings or {}), "email": cur}
    return cur


async def sent_in_last_24h(db: AsyncSession, user_id: int, mode: str | None = None) -> int:
    conds = [JobEmail.user_id == user_id, JobEmail.status == "sent",
             JobEmail.sent_at >= datetime.now(timezone.utc) - timedelta(hours=24)]
    if mode:
        conds.append(JobEmail.mode == mode)
    return (await db.execute(select(func.count()).select_from(JobEmail).where(*conds))).scalar_one()


# ------------------------------------------------------------------ helpers
async def _profile(db: AsyncSession, user_id: int) -> CandidateProfile | None:
    return (await db.execute(select(CandidateProfile).where(
        CandidateProfile.user_id == user_id, CandidateProfile.is_active.is_(True))
        .order_by(CandidateProfile.updated_at.desc()).limit(1))).scalar_one_or_none()


async def _default_account(db: AsyncSession, user: User) -> GmailAccount | None:
    cfg = email_settings(user)
    if cfg.get("default_account_id"):
        acc = await db.get(GmailAccount, int(cfg["default_account_id"]))
        if acc and acc.user_id == user.id and acc.is_connected:
            return acc
    return (await db.execute(select(GmailAccount).where(GmailAccount.user_id == user.id, GmailAccount.is_connected.is_(True))
                             .order_by(GmailAccount.id).limit(1))).scalar_one_or_none()


async def _template(db: AsyncSession, user: User, template_id: int | None) -> EmailTemplate:
    tid = template_id or email_settings(user).get("default_template_id")
    if tid:
        t = await db.get(EmailTemplate, int(tid))
        if t and t.user_id == user.id:
            return t
    return await tpl.ensure_default(db, user.id)


async def render_for(db: AsyncSession, user: User, job: Job, template: EmailTemplate, hr_name: str | None,
                     profile: CandidateProfile | None = None) -> tuple[str, str]:
    profile = profile or await _profile(db, user.id)
    return tpl.render_template(template.subject, template.body, tpl.build_context(user, profile, job, hr_name))


async def owned(db: AsyncSession, user_id: int, email_id: int) -> JobEmail:
    je = await db.get(JobEmail, email_id)
    if je is None or je.user_id != user_id:
        raise EmailError("Application email not found", 404)
    return je


# ------------------------------------------------------------------ drafts
async def create_draft(db: AsyncSession, user: User, job: Job, *, recipient: str | None = None,
                       recipient_source: str | None = None, hr_name: str | None = None,
                       template_id: int | None = None, account_id: int | None = None,
                       profile: CandidateProfile | None = None) -> JobEmail:
    """Create (or return the existing open) application email for a job.

    With no explicit recipient the posting is scanned; if nothing is found the draft stays
    ``pending`` with an empty recipient - an address is never invented."""
    if recipient:
        recipient = normalize_email(recipient)
        if not recipient:
            raise EmailError("That recipient email address is not valid", 422)
        recipient_source = recipient_source or "manual"
    else:
        det = best_hr_email(job.description)
        if det:
            recipient, recipient_source, hr_name = det.email, "posting", hr_name or det.hr_name
    existing = (await db.execute(select(JobEmail).where(
        JobEmail.user_id == user.id, JobEmail.job_id == job.id,
        JobEmail.recipient_email == recipient if recipient else JobEmail.recipient_email.is_(None)))).scalar_one_or_none()
    if existing is None and recipient is None:
        # reuse any unsent draft for this job rather than piling up empty ones
        existing = (await db.execute(select(JobEmail).where(
            JobEmail.user_id == user.id, JobEmail.job_id == job.id,
            JobEmail.status.in_(("pending", "ready", "failed"))).limit(1))).scalar_one_or_none()
    if existing:
        return existing
    profile = profile or await _profile(db, user.id)
    t = await _template(db, user, template_id)
    acc = None
    if account_id:
        acc = await db.get(GmailAccount, account_id)
        if not acc or acc.user_id != user.id:
            raise EmailError("Gmail account not found", 404)
    else:
        acc = await _default_account(db, user)
    subject, body = await render_for(db, user, job, t, hr_name, profile)
    je = JobEmail(user_id=user.id, job_id=job.id, recipient_email=recipient, recipient_source=recipient_source,
                  hr_name=hr_name, sender_account_id=acc.id if acc else None, sender_email=acc.email if acc else None,
                  template_id=t.id, template_name=t.name, subject=subject, body=body,
                  resume_id=profile.resume_id if profile else None,
                  attach_resume=bool(email_settings(user).get("attach_resume", True)),
                  status="ready" if recipient else "pending")
    db.add(je)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        raise EmailError("An application email to this recipient already exists for this job", 409) from e
    return je


async def update_draft(db: AsyncSession, user: User, je: JobEmail, data: dict[str, Any]) -> JobEmail:
    if je.status in ("sent", "sending"):
        raise EmailError("This email has already been sent and cannot be edited", 409)
    job = await db.get(Job, je.job_id)
    rerender = False
    if "recipient_email" in data:
        raw = (data["recipient_email"] or "").strip()
        if raw:
            addr = normalize_email(raw)
            if not addr:
                raise EmailError("That recipient email address is not valid", 422)
            if addr != je.recipient_email:
                dup = (await db.execute(select(JobEmail.id).where(
                    JobEmail.user_id == user.id, JobEmail.job_id == je.job_id,
                    JobEmail.recipient_email == addr, JobEmail.id != je.id))).first()
                if dup:
                    raise EmailError("You already have an application email to this recipient for this job", 409)
                je.recipient_email, je.recipient_source = addr, "manual"
        else:
            je.recipient_email, je.recipient_source = None, None
    if "hr_name" in data:
        je.hr_name = (data["hr_name"] or "").strip()[:120] or None
        rerender = not ({"subject", "body"} & data.keys()) and not je.edited_by_user
    if data.get("sender_account_id") is not None:
        acc = await db.get(GmailAccount, int(data["sender_account_id"]))
        if not acc or acc.user_id != user.id:
            raise EmailError("Gmail account not found", 404)
        je.sender_account_id, je.sender_email = acc.id, acc.email
    if data.get("template_id") is not None:
        t = await _template(db, user, int(data["template_id"]))
        je.template_id, je.template_name = t.id, t.name
        rerender = not ({"subject", "body"} & data.keys())
        je.edited_by_user = False if rerender else je.edited_by_user
    if data.get("resume_id") is not None:
        r = await db.get(Resume, int(data["resume_id"]))
        if not r or r.user_id != user.id:
            raise EmailError("Resume not found", 404)
        je.resume_id = r.id
    if "attach_resume" in data and data["attach_resume"] is not None:
        je.attach_resume = bool(data["attach_resume"])
    if "subject" in data and data["subject"] is not None:
        je.subject, je.edited_by_user = data["subject"].strip()[:300], True
    if "body" in data and data["body"] is not None:
        je.body, je.edited_by_user = data["body"], True
    if rerender and job:
        t = await _template(db, user, je.template_id)
        je.subject, je.body = await render_for(db, user, job, t, je.hr_name)
    if je.status in ("pending", "ready", "skipped") or (je.status == "failed" and "recipient_email" in data):
        je.status = "ready" if je.recipient_email else "pending"
    await db.flush()
    return je


# ------------------------------------------------------------------ sending
async def _attachment(db: AsyncSession, je: JobEmail) -> Attachment | None:
    if not je.attach_resume:
        return None
    if not je.resume_id:
        raise EmailError("No resume selected to attach - upload a PDF resume or turn off the attachment")
    r = await db.get(Resume, je.resume_id)
    if not r or r.user_id != je.user_id:
        raise EmailError("The selected resume no longer exists")
    data = ResumeStorage().load(r.stored_path, r.encrypted)
    try:
        validate_pdf(data)
    except GmailSendError as e:
        raise EmailError(f"{e} - upload a PDF resume or turn off the attachment") from e
    return Attachment(filename=r.original_filename, data=data)


async def _claim(db: AsyncSession, je_id: int, user_id: int) -> bool:
    res = await db.execute(update(JobEmail).where(
        JobEmail.id == je_id, JobEmail.user_id == user_id, JobEmail.status.in_(SENDABLE))
        .values(status="sending", attempts=JobEmail.attempts + 1, error_message=None))
    await db.commit()
    return res.rowcount == 1


async def send_job_email(db: AsyncSession, user: User, je_id: int, mode: str = "manual") -> JobEmail:
    je = await owned(db, user.id, je_id)
    if je.status == "sent":
        raise EmailError("This email was already sent", 409)
    if je.status == "sending":
        raise EmailError("This email is being sent right now", 409)
    if je.status in ("pending", "skipped"):
        if not je.recipient_email:
            raise EmailError("Add the recipient's email address first", 422)
        je.status = "ready"
        await db.commit()
    s = get_settings()
    if await sent_in_last_24h(db, user.id) >= s.email_daily_limit_max:
        raise EmailError(f"Daily safety cap of {s.email_daily_limit_max} emails reached - try again tomorrow", 429)
    if not await _claim(db, je.id, user.id):
        raise EmailError("This email is already being sent or was sent", 409)
    await db.refresh(je)
    try:
        if not je.recipient_email or not normalize_email(je.recipient_email):
            raise EmailError("The recipient address is missing or invalid", 422)
        ok, why = await check_deliverable(je.recipient_email)
        if not ok:
            raise EmailError(f"Recipient domain cannot receive email: {why}", 422)
        dup = (await db.execute(select(JobEmail.id).where(
            JobEmail.user_id == user.id, JobEmail.job_id == je.job_id, JobEmail.id != je.id,
            func.lower(JobEmail.recipient_email) == je.recipient_email.lower(), JobEmail.status == "sent"))).first()
        if dup:
            raise EmailError("You already emailed this recipient about this job", 409)
        acc = await db.get(GmailAccount, je.sender_account_id) if je.sender_account_id else await _default_account(db, user)
        if not acc or acc.user_id != user.id:
            raise EmailError("Choose the Gmail account to send from (connect one in Applications → Settings)", 422)
        je.sender_account_id, je.sender_email = acc.id, acc.email
        if not je.subject.strip() or not je.body.strip():
            raise EmailError("Subject and message cannot be empty", 422)
        attachment = await _attachment(db, je)
        token = await get_access_token(db, acc)
        profile = await _profile(db, user.id)
        sender_name = ((profile.data or {}).get("candidate") if profile else None) or user.full_name
        msg = build_message(acc.email, sender_name, je.recipient_email, je.subject, je.body, attachment)
        message_id = await send_message(token, msg)
    except (EmailError, GmailSendError, GmailAuthError, GmailNotConfigured, OSError, RuntimeError) as e:
        je.status, je.error_message = "failed", str(e)[:1000]
        await db.commit()
        log.info("Application email %s failed: %s", je.id, type(e).__name__)
        # never 401: the frontend treats 401 as "your login expired"
        code = getattr(e, "status_code", None) or (429 if getattr(e, "retryable", False) else 422)
        raise EmailError(str(e), code) from e
    je.status, je.mode, je.gmail_message_id = "sent", mode, message_id
    je.sent_at, je.error_message = datetime.now(timezone.utc), None
    acc.last_used_at = je.sent_at
    await db.commit()
    log.info("Application email %s sent (%s)", je.id, mode)
    return je


# ------------------------------------------------------------------ RUN integration + auto queue
async def prepare_for_jobs(db: AsyncSession, user: User, job_ids: set[int]) -> dict[str, int]:
    """After a RUN: create ready-to-send drafts for matching jobs whose posting names an HR email."""
    cfg = email_settings(user)
    if not cfg.get("detect_on_run", True) or not job_ids:
        return {"hr_emails_found": 0}
    profile = await _profile(db, user.id)
    min_score = float((profile.preferences or {}).get("min_match_score", 40)) if profile else 40.0
    rows = (await db.execute(select(Job).join(JobMatch, and_(JobMatch.job_id == Job.id, JobMatch.user_id == user.id))
                             .where(Job.id.in_(job_ids), Job.status == "active", JobMatch.hidden.is_(False),
                                    JobMatch.score >= min_score))).unique().scalars().all()
    have = {jid for (jid,) in (await db.execute(select(JobEmail.job_id).where(
        JobEmail.user_id == user.id, JobEmail.job_id.in_([j.id for j in rows])))).all()}
    created = 0
    for job in rows:
        if job.id in have or not best_hr_email(job.description):
            continue
        try:
            await create_draft(db, user, job, profile=profile)
            created += 1
        except EmailError:
            continue
    await db.commit()
    return {"hr_emails_found": created}


_queue_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _user_lock(user_id: int) -> threading.Lock:
    with _locks_guard:
        return _queue_locks.setdefault(user_id, threading.Lock())


async def auto_send_candidates(db: AsyncSession, user: User) -> list[int]:
    cfg = email_settings(user)
    cooldown = datetime.now(timezone.utc) - timedelta(days=RECRUITER_COOLDOWN_DAYS)
    recently = select(JobEmail.recipient_email).where(
        JobEmail.user_id == user.id, JobEmail.status == "sent", JobEmail.sent_at >= cooldown)
    rows = (await db.execute(
        select(JobEmail.id).join(Job, Job.id == JobEmail.job_id)
        .join(JobMatch, and_(JobMatch.job_id == JobEmail.job_id, JobMatch.user_id == user.id))
        .where(JobEmail.user_id == user.id, JobEmail.status == "ready", JobEmail.attempts == 0,
               JobEmail.recipient_email.is_not(None), JobEmail.recipient_source.in_(("posting", "manual")),
               JobEmail.recipient_email.not_in(recently), Job.status == "active", JobMatch.hidden.is_(False),
               JobMatch.score >= float(cfg.get("auto_min_score") or 60))
        .order_by(JobMatch.score.desc()))).all()
    return [r[0] for r in rows]


async def process_auto_queue(session_factory: async_sessionmaker, user_id: int) -> dict[str, Any]:
    """Send ready emails automatically, one at a time, until the queue or the daily limit is exhausted.

    Re-reads the user's settings before every message, so switching auto-send off pauses it."""
    lock = _user_lock(user_id)
    if not lock.acquire(blocking=False):
        return {"sent": 0, "failed": 0, "skipped": 0, "note": "auto-send already running"}
    sent = failed = skipped = 0
    stop_reason = "queue empty"
    try:
        async with session_factory() as db:
            user = await db.get(User, user_id)
            if not user or not email_settings(user)["auto_send_enabled"]:
                return {"sent": 0, "failed": 0, "skipped": 0, "note": "automatic sending is off"}
            ids = await auto_send_candidates(db, user)
        recipients_done: set[str] = set()
        for i, je_id in enumerate(ids):
            async with session_factory() as db:
                user = await db.get(User, user_id)
                cfg = email_settings(user)
                if not cfg["auto_send_enabled"]:
                    stop_reason = "paused by user"
                    break
                if await sent_in_last_24h(db, user_id) >= int(cfg["daily_limit"]):
                    stop_reason = "daily limit reached"
                    break
                je = await db.get(JobEmail, je_id)
                if je is None or je.status != "ready":
                    continue
                if je.recipient_email in recipients_done:  # same recruiter, several jobs: one email per run
                    skipped += 1
                    continue
                job = await db.get(Job, je.job_id)
                if not je.edited_by_user and job:  # pick up template / profile changes made since drafting
                    t = await _template(db, user, je.template_id)
                    je.subject, je.body = await render_for(db, user, job, t, je.hr_name)
                    await db.commit()
                try:
                    await send_job_email(db, user, je_id, mode="auto")
                    sent += 1
                    recipients_done.add(je.recipient_email)
                except EmailError as e:
                    failed += 1
                    msg = str(e).lower()
                    if e.status_code == 429 or any(w in msg for w in ("reconnect", "not configured", "disconnected", "quota", "rate")):
                        stop_reason = str(e)
                        break
            if i < len(ids) - 1:
                await asyncio.sleep(get_settings().email_send_interval_seconds)
    finally:
        lock.release()
    return {"sent": sent, "failed": failed, "skipped": skipped, "note": stop_reason}


async def after_search(session_factory: async_sessionmaker, user_id: int, job_ids: set[int]) -> dict[str, Any]:
    """Hook called at the end of a RUN. Never raises - email problems must not affect searches."""
    try:
        async with session_factory() as db:
            user = await db.get(User, user_id)
            if user is None:
                return {}
            stats = await prepare_for_jobs(db, user, job_ids)
            auto = email_settings(user)["auto_send_enabled"]
        if auto:
            stats["auto_send"] = await process_auto_queue(session_factory, user_id)
        return stats
    except Exception:  # noqa: BLE001
        log.exception("application-email step failed for user %s", user_id)
        return {"email_step_error": True}


# ------------------------------------------------------------------ serialization / history
async def serialize(db: AsyncSession, rows: list[JobEmail], user_id: int) -> list[dict[str, Any]]:
    scores = {}
    if rows:
        scores = dict((await db.execute(select(JobMatch.job_id, JobMatch.score).where(
            JobMatch.user_id == user_id, JobMatch.job_id.in_([r.job_id for r in rows])))).all())
    out = []
    for r in rows:
        j = r.job
        out.append({
            "id": r.id, "job_id": r.job_id, "job_title": j.title if j else None,
            "company_name": (j.company.name if j and j.company else (j.company_name if j else None)),
            "job_url": j.apply_url if j else None, "job_status": j.status if j else None,
            "match_score": scores.get(r.job_id),
            "recipient_email": r.recipient_email, "recipient_source": r.recipient_source, "hr_name": r.hr_name,
            "sender_account_id": r.sender_account_id, "sender_email": r.sender_email,
            "template_id": r.template_id, "template_name": r.template_name,
            "subject": r.subject, "body": r.body, "resume_id": r.resume_id, "attach_resume": r.attach_resume,
            "mode": r.mode, "status": r.status, "gmail_message_id": r.gmail_message_id, "sent_at": r.sent_at,
            "error_message": r.error_message, "attempts": r.attempts, "edited_by_user": r.edited_by_user,
            "created_at": r.created_at, "updated_at": r.updated_at,
        })
    return out


def history_query(user_id: int, status: list[str], q: str | None, date_from: datetime | None,
                  date_to: datetime | None):
    stmt = select(JobEmail).join(Job, Job.id == JobEmail.job_id).where(JobEmail.user_id == user_id)
    if status:
        stmt = stmt.where(JobEmail.status.in_(status))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Job.company_name).like(like), func.lower(Job.title).like(like),
                              func.lower(JobEmail.recipient_email).like(like)))
    ts = func.coalesce(JobEmail.sent_at, JobEmail.updated_at)
    if date_from:
        stmt = stmt.where(ts >= date_from)
    if date_to:
        stmt = stmt.where(ts < date_to)
    return stmt.order_by(ts.desc(), JobEmail.id.desc())
