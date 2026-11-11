"""Google OAuth 2.0 for Gmail (authorization-code flow, confidential web client + PKCE).

Scopes are the minimum needed: ``gmail.send`` to send mail and ``openid email`` so we
learn WHICH address was connected (read from the ID token Google returns directly from
its token endpoint - no mailbox read access is requested).

CSRF protection: the ``state`` parameter is a short-lived JWT signed with SECRET_KEY that
carries the user id and a one-time nonce; the nonce and the PKCE verifier are stored on
the user row and consumed on callback, so a state can be used once, by that user only.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.models import GmailAccount, User

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
SCOPES = ["openid", "email", GMAIL_SEND_SCOPE]
STATE_TTL_MINUTES = 10
STATE_PURPOSE = "gmail_oauth"


class GmailNotConfigured(Exception):
    """GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are missing."""


class GmailAuthError(Exception):
    """OAuth failed or the account needs to be reconnected."""


def is_configured() -> bool:
    s = get_settings()
    return bool(s.google_client_id and s.google_client_secret)


def _require_config():
    if not is_configured():
        raise GmailNotConfigured("Gmail integration is not configured: set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET")
    return get_settings()


def _google_error(r: httpx.Response) -> str:
    """Error code/description only - never echo request data (it may contain tokens)."""
    try:
        d = r.json()
        err = d.get("error")
        if isinstance(err, dict):
            return f"{err.get('status') or err.get('code')}: {err.get('message', '')}"[:300]
        return f"{err}: {d.get('error_description', '')}"[:300]
    except ValueError:
        return f"HTTP {r.status_code}"


# ------------------------------------------------------------------ connect / callback
def build_authorization_url(user: User) -> str:
    s = _require_config()
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    user.settings = {**(user.settings or {}), "gmail_oauth": {
        "nonce": nonce, "verifier": verifier,
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)).isoformat()}}
    state = jwt.encode({"sub": str(user.id), "nonce": nonce, "purpose": STATE_PURPOSE,
                        "exp": datetime.now(timezone.utc) + timedelta(minutes=STATE_TTL_MINUTES)},
                       s.secret_key, algorithm="HS256")
    params = {
        "client_id": s.google_client_id, "redirect_uri": s.google_oauth_redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "include_granted_scopes": "false",
        # consent every time so Google always returns a refresh token (also for re-connects)
        "prompt": "consent select_account", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def consume_state(db: AsyncSession, state: str) -> tuple[User, str]:
    """Validate the OAuth ``state``; returns the user and the PKCE verifier (one-time)."""
    s = get_settings()
    try:
        payload = jwt.decode(state, s.secret_key, algorithms=["HS256"])
        if payload.get("purpose") != STATE_PURPOSE:
            raise ValueError("wrong purpose")
        uid = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as e:
        raise GmailAuthError("Invalid or expired OAuth state - please try connecting again") from e
    user = await db.get(User, uid)
    pending = (user.settings or {}).get("gmail_oauth") if user else None
    if not user or not pending or not secrets.compare_digest(str(pending.get("nonce", "")), str(payload.get("nonce", ""))):
        raise GmailAuthError("OAuth state was already used or does not match - please try connecting again")
    user.settings = {k: v for k, v in (user.settings or {}).items() if k != "gmail_oauth"}  # one-time
    return user, pending["verifier"]


def _email_from_id_token(id_token: str | None) -> str | None:
    """The ID token comes straight from Google's token endpoint over TLS, which per OpenID
    Connect Core 3.1.3.7 lets the client skip signature validation; we still check aud/iss."""
    if not id_token:
        return None
    try:
        claims = jwt.decode(id_token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return None
    if claims.get("aud") != get_settings().google_client_id:
        return None
    if claims.get("iss") not in ("https://accounts.google.com", "accounts.google.com"):
        return None
    if not claims.get("email_verified", False):
        return None
    return (claims.get("email") or "").lower() or None


async def exchange_code(db: AsyncSession, user: User, code: str, verifier: str) -> GmailAccount:
    s = _require_config()
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(TOKEN_URL, data={
            "code": code, "client_id": s.google_client_id, "client_secret": s.google_client_secret,
            "redirect_uri": s.google_oauth_redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier})
    if r.status_code != 200:
        raise GmailAuthError(f"Google rejected the authorization: {_google_error(r)}")
    tok = r.json()
    granted = set((tok.get("scope") or "").split())
    if GMAIL_SEND_SCOPE not in granted:
        raise GmailAuthError("Permission to send email was not granted. Tick the Gmail checkbox on Google's consent screen.")
    email = _email_from_id_token(tok.get("id_token"))
    if not email:
        raise GmailAuthError("Could not determine the connected Gmail address")
    if not tok.get("refresh_token"):
        raise GmailAuthError("Google did not return a refresh token - remove the app at myaccount.google.com/permissions and connect again")
    acc = (await db.execute(select(GmailAccount).where(GmailAccount.user_id == user.id,
                                                        GmailAccount.email == email))).scalar_one_or_none()
    if acc is None:
        acc = GmailAccount(user_id=user.id, email=email)
        db.add(acc)
    acc.encrypted_access_token = encrypt_secret(tok["access_token"])
    acc.encrypted_refresh_token = encrypt_secret(tok["refresh_token"])
    acc.token_expiry = datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 3600)))
    acc.scopes = " ".join(sorted(granted))
    acc.is_connected, acc.last_error = True, None
    await db.flush()
    log.info("Gmail account connected for user %s", user.id)  # no address / tokens in logs
    return acc


# ------------------------------------------------------------------ tokens
async def get_access_token(db: AsyncSession, acc: GmailAccount) -> str:
    """A valid access token, refreshing it first when it expires within 2 minutes."""
    if not acc.is_connected or not acc.encrypted_refresh_token:
        raise GmailAuthError("This Gmail account is disconnected - reconnect it in Applications → Settings")
    exp = acc.token_expiry
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if acc.encrypted_access_token and exp and exp > datetime.now(timezone.utc) + timedelta(minutes=2):
        return decrypt_secret(acc.encrypted_access_token)
    s = _require_config()
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(TOKEN_URL, data={
            "client_id": s.google_client_id, "client_secret": s.google_client_secret,
            "refresh_token": decrypt_secret(acc.encrypted_refresh_token), "grant_type": "refresh_token"})
    if r.status_code != 200:
        err = _google_error(r)
        if r.status_code in (400, 401) and "invalid_grant" in err:
            # revoked by the user in their Google account, or the refresh token expired
            acc.is_connected = False
            acc.last_error = "Access was revoked or expired - reconnect this account"
            await db.flush()
            raise GmailAuthError(acc.last_error)
        raise GmailAuthError(f"Could not refresh Gmail access: {err}")
    tok = r.json()
    acc.encrypted_access_token = encrypt_secret(tok["access_token"])
    acc.token_expiry = datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 3600)))
    if tok.get("refresh_token"):  # Google may rotate it
        acc.encrypted_refresh_token = encrypt_secret(tok["refresh_token"])
    await db.flush()
    return tok["access_token"]


async def revoke(acc: GmailAccount) -> None:
    """Best effort: tell Google to revoke the grant. Local tokens are deleted regardless."""
    token = None
    try:
        token = decrypt_secret(acc.encrypted_refresh_token) or decrypt_secret(acc.encrypted_access_token)
    except RuntimeError:
        return
    if not token:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(REVOKE_URL, data={"token": token})
    except httpx.HTTPError:
        log.warning("Gmail token revocation request failed; local tokens deleted anyway")


def account_out(acc: GmailAccount) -> dict:
    return {"id": acc.id, "email": acc.email, "is_connected": acc.is_connected, "last_error": acc.last_error,
            "connected_at": acc.created_at, "last_used_at": acc.last_used_at}


__all__ = ["GmailAuthError", "GmailNotConfigured", "build_authorization_url", "consume_state", "exchange_code",
           "get_access_token", "revoke", "is_configured", "account_out"]
