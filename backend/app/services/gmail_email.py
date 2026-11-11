"""Send one email through the Gmail API (users.messages.send) with an optional PDF attachment."""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import httpx

SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # Gmail allows 25 MB total; resumes never need more than this


class GmailSendError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class Attachment:
    filename: str
    data: bytes
    mime: str = "application/pdf"


def _one_line(v: str) -> str:
    """Header values must never contain CR/LF (header injection)."""
    return re.sub(r"[\r\n]+", " ", v or "").strip()


def validate_pdf(data: bytes) -> None:
    if not data.startswith(b"%PDF-"):
        raise GmailSendError("Resume attachment must be a PDF file")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise GmailSendError(f"Resume attachment is larger than {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB")


def build_message(sender: str, sender_name: str | None, to: str, subject: str, body: str,
                  attachment: Attachment | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((_one_line(sender_name or ""), sender)) if sender_name else sender
    msg["To"] = _one_line(to)
    msg["Subject"] = _one_line(subject)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    msg.set_content(body)
    if attachment is not None:
        validate_pdf(attachment.data)
        name = re.sub(r"[^\w.\- ]+", "_", attachment.filename) or "resume.pdf"
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        msg.add_attachment(attachment.data, maintype="application", subtype="pdf", filename=name)
    return msg


async def send_message(access_token: str, msg: EmailMessage) -> str:
    """Returns the Gmail message id."""
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(SEND_URL, json={"raw": raw}, headers={"Authorization": f"Bearer {access_token}"})
    except httpx.HTTPError as e:
        raise GmailSendError(f"Network error talking to Gmail: {type(e).__name__}", retryable=True) from e
    if r.status_code == 200:
        return r.json().get("id", "")
    try:
        err = r.json().get("error", {})
        detail = f"{err.get('status') or r.status_code}: {err.get('message', '')}"[:400]
    except ValueError:
        detail = f"HTTP {r.status_code}"
    # 429 / 5xx are transient; 403 rateLimitExceeded / dailyLimitExceeded is quota
    retryable = r.status_code == 429 or r.status_code >= 500 or "rateLimitExceeded" in r.text
    raise GmailSendError(f"Gmail refused the message - {detail}", retryable=retryable)
