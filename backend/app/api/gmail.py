"""Gmail account connection (Google OAuth 2.0)."""
from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.crypto import _fernet
from app.core.security import get_current_user
from app.db import get_db
from app.models import GmailAccount, JobEmail, User
from app.services import gmail_oauth as oauth
from app.services.job_email_service import email_settings, save_email_settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/gmail", tags=["gmail"])


def _back_to_app(**params: str) -> RedirectResponse:
    return RedirectResponse(f"{get_settings().frontend_url.rstrip('/')}/applications?{urlencode({'tab': 'settings', **params})}",
                            status_code=303)


@router.post("/connect")
async def connect(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Returns the Google consent URL; the browser navigates there."""
    try:
        _fernet()  # fail here, before the Google round-trip, if the encryption key is broken
        url = oauth.build_authorization_url(user)
    except (oauth.GmailNotConfigured, RuntimeError) as e:
        raise HTTPException(503, str(e))
    await db.commit()
    return {"auth_url": url}


@router.get("/callback", include_in_schema=False)
async def callback(code: str | None = Query(None, max_length=2048), state: str | None = Query(None, max_length=4096),
                   error: str | None = Query(None, max_length=200), db: AsyncSession = Depends(get_db)):
    """Google redirects the browser here (no bearer token: the signed one-time ``state`` identifies the user)."""
    if error:
        return _back_to_app(gmail="error", message="Google sign-in was cancelled" if error == "access_denied" else f"Google error: {error}")
    if not code or not state:
        return _back_to_app(gmail="error", message="Missing authorization code")
    try:
        user, verifier = await oauth.consume_state(db, state)
        await db.commit()  # the state is spent even if the exchange fails
        acc = await oauth.exchange_code(db, user, code, verifier)
        if not email_settings(user).get("default_account_id"):
            save_email_settings(user, {"default_account_id": acc.id})
        await db.commit()
    except (oauth.GmailAuthError, oauth.GmailNotConfigured, RuntimeError) as e:
        await db.rollback()
        return _back_to_app(gmail="error", message=str(e))
    return _back_to_app(gmail="connected", account=acc.email)


@router.get("/accounts")
async def accounts(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(GmailAccount).where(GmailAccount.user_id == user.id)
                             .order_by(GmailAccount.id))).scalars().all()
    s = get_settings()
    return {"configured": oauth.is_configured(), "redirect_uri": s.google_oauth_redirect_uri,
            "default_account_id": email_settings(user).get("default_account_id"),
            "accounts": [oauth.account_out(a) for a in rows]}


@router.delete("/disconnect/{account_id}")
async def disconnect(account_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    acc = await db.get(GmailAccount, account_id)
    if not acc or acc.user_id != user.id:
        raise HTTPException(404, "Gmail account not found")
    await oauth.revoke(acc)
    # unsent drafts that would have used this sender fall back to the default account
    await db.execute(update(JobEmail).where(JobEmail.user_id == user.id, JobEmail.sender_account_id == acc.id,
                                            JobEmail.status.in_(("pending", "ready", "failed")))
                     .values(sender_account_id=None, sender_email=None))
    if email_settings(user).get("default_account_id") == acc.id:
        save_email_settings(user, {"default_account_id": None})
    await db.delete(acc)  # tokens are deleted with the row; sent history keeps the sender address
    await db.commit()
    return {"disconnected": True}
