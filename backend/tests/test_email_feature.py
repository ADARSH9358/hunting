"""Job application emails via the Gmail API.

Google's HTTP endpoints (OAuth token/revoke, Gmail send) are mocked with respx; everything
else - OAuth state/PKCE handling, token encryption and refresh, MIME building, duplicate
protection, the auto-send queue - runs the real application code.
"""
import base64
import email
import email.policy
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
import respx
from sqlalchemy import select

from app.services.hr_email_detection import best_hr_email, detect_hr_emails
from app.services import email_templates as tpl

CLIENT_ID = "test-client.apps.googleusercontent.com"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"


# ---------------------------------------------------------------- unit: detection & templates
def test_hr_email_detection_only_uses_addresses_in_the_posting():
    text = ("We're hiring a Backend Developer in Noida! Send your CV to careers@tinystartup.io. "
            "Questions about the product? support@tinystartup.io. Logo: banner@2x.png. noreply@tinystartup.io")
    found = detect_hr_emails(text)
    assert [d.email for d in found] == ["careers@tinystartup.io"]
    assert best_hr_email("No email in this posting, apply on our site.") is None
    assert best_hr_email("Contact: Vijay Kumar, vijay.d@vgaisolutions.com for this role").hr_name == "Vijay Kumar"
    assert best_hr_email("share resume at hr [at] acme [dot] in").email == "hr@acme.in"
    assert best_hr_email("mail hr@example.com") is None  # placeholder domains never used
    assert best_hr_email("bad hr@@x") is None


def test_template_rendering_and_unknown_variables():
    ctx = {"hr_name": "Hiring Manager", "job_title": "Backend Developer", "candidate_name": "Deep",
           "candidate_phone": ""}
    s, b = tpl.render_template("Application for {{job_title}} – {{ candidate_name }}",
                               "Dear {{hr_name}},\n\nThanks\n{{candidate_phone}}\n\n\n", ctx)
    assert s == "Application for Backend Developer – Deep"
    assert b == "Dear Hiring Manager,\n\nThanks\n"
    assert tpl.unknown_variables("{{job_title}} {{salary}}") == ["salary"]


# ---------------------------------------------------------------- end-to-end
@pytest.fixture
async def client(monkeypatch):
    from app import db as dbmod
    from app.config import get_settings
    from app.main import app
    from app.services import job_email_service as svc

    s = get_settings()
    monkeypatch.setattr(s, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(s, "google_client_secret", "test-secret")
    monkeypatch.setattr(s, "email_send_interval_seconds", 0)

    async def deliverable(addr):
        return (not addr.endswith("@no-mail-domain.co"), None if not addr.endswith("@no-mail-domain.co") else "no MX")
    monkeypatch.setattr(svc, "check_deliverable", deliverable)
    async with dbmod.engine.begin() as conn:
        await conn.run_sync(dbmod.Base.metadata.drop_all)
        await conn.run_sync(dbmod.Base.metadata.create_all)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c


def _id_token(email_addr: str) -> str:
    return jwt.encode({"aud": CLIENT_ID, "iss": "https://accounts.google.com", "email": email_addr,
                       "email_verified": True, "sub": "123"}, "irrelevant", algorithm="HS256")


async def _setup_user(client, resume_pdf) -> dict:
    r = await client.post("/api/auth/register", json={"email": "deep@example.com", "password": "s3cret-pass!", "full_name": "Deep Sen"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = await client.post("/api/resume/upload", headers=h, files={"file": ("Deep_Sen_Resume.pdf", resume_pdf, "application/pdf")})
    assert r.status_code == 201, r.text
    return h


async def _connect_gmail(client, h, addr="deep.sen@gmail.com") -> int:
    r = await client.post("/api/gmail/connect", headers=h)
    assert r.status_code == 200, r.text
    q = parse_qs(urlparse(r.json()["auth_url"]).query)
    assert "https://www.googleapis.com/auth/gmail.send" in q["scope"][0]
    assert q["code_challenge_method"] == ["S256"] and q["access_type"] == ["offline"]
    state = q["state"][0]
    with respx.mock(assert_all_called=True) as m:
        tok = m.post(TOKEN_URL).respond(200, json={
            "access_token": "ya29.access-1", "refresh_token": "1//refresh-1", "expires_in": 3599,
            "scope": "openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/gmail.send",
            "id_token": _id_token(addr)})
        r = await client.get("/api/gmail/callback", params={"code": "auth-code", "state": state})
        assert "code_verifier=" in tok.calls[0].request.content.decode()
    assert r.status_code == 303 and "gmail=connected" in r.headers["location"]
    # the same state cannot be replayed (CSRF / one-time)
    r2 = await client.get("/api/gmail/callback", params={"code": "auth-code", "state": state})
    assert "gmail=error" in r2.headers["location"]
    accs = (await client.get("/api/gmail/accounts", headers=h)).json()
    acc = next(a for a in accs["accounts"] if a["email"] == addr)
    assert "token" not in str(acc).lower()  # tokens never reach the frontend
    return acc["id"]


async def _add_job(title, description, score=85.0, company="Tiny Startup") -> int:
    from app import db as dbmod
    from app.models import Job, JobMatch, User
    async with dbmod.SessionLocal() as db:
        uid = (await db.execute(select(User.id))).scalar_one()
        job = Job(fingerprint=f"fp-{title}-{company}", title=title, normalized_title=title.lower(), company_name=company,
                  description=description, apply_url=f"https://jobs.example.org/{re.sub(r'\W+', '-', title)}")
        db.add(job)
        await db.flush()
        db.add(JobMatch(user_id=uid, job_id=job.id, score=score))
        await db.commit()
        return job.id


@pytest.mark.asyncio
async def test_gmail_application_email_workflow(client, resume_pdf):
    h = await _setup_user(client, resume_pdf)
    acc_id = await _connect_gmail(client, h)

    # tokens are encrypted at rest
    from app import db as dbmod
    from app.models import GmailAccount
    async with dbmod.SessionLocal() as db:
        acc = await db.get(GmailAccount, acc_id)
        assert "refresh-1" not in acc.encrypted_refresh_token and "access-1" not in acc.encrypted_access_token

    # templates: default exists, unknown variables rejected, preview renders a real job
    t = (await client.get("/api/email-templates", headers=h)).json()
    assert len(t) == 1 and t[0]["is_default"]
    r = await client.post("/api/email-templates", headers=h, json={"name": "x", "subject": "{{salary}}", "body": "hi"})
    assert r.status_code == 422
    r = await client.post("/api/email-templates", headers=h, json={
        "name": "Short", "subject": "{{job_title}} at {{company_name}}", "body": "Hi {{hr_name}},\n{{candidate_name}}"})
    short_id = r.json()["id"]

    job1 = await _add_job("Backend Developer", "We are hiring! Contact: Ritu Sharma, careers@tinystartup.io. Node.js, Python.")
    job2 = await _add_job("Frontend Intern", "Apply on our website. No email here.", company="Other Co")

    # draft with the HR email found in the posting
    r = await client.post("/api/job-emails/drafts", headers=h, json={"job_id": job1})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "ready" and d["recipient_email"] == "careers@tinystartup.io" and d["recipient_source"] == "posting"
    assert d["hr_name"] == "Ritu Sharma" and d["sender_email"] == "deep.sen@gmail.com"
    assert d["subject"] == "Application for Backend Developer Position – Priya Sharma"
    assert d["body"].startswith("Dear Ritu Sharma,")
    # no email in posting -> pending, nothing invented; sending is refused
    p = (await client.post("/api/job-emails/drafts", headers=h, json={"job_id": job2})).json()
    assert p["status"] == "pending" and p["recipient_email"] is None
    assert (await client.post(f"/api/job-emails/{p['id']}/send", headers=h)).status_code == 422

    # switch template, then edit subject manually
    r = await client.put(f"/api/job-emails/{d['id']}", headers=h, json={"template_id": short_id})
    assert r.json()["subject"] == "Backend Developer at Tiny Startup"
    r = await client.put(f"/api/job-emails/{d['id']}", headers=h, json={"subject": "Backend Developer – Deep Sen"})
    assert r.json()["edited_by_user"] is True

    # attachment preview is the real PDF
    r = await client.get(f"/api/job-emails/{d['id']}/attachment", headers=h)
    assert r.status_code == 200 and r.content.startswith(b"%PDF-")

    # send through the Gmail API
    with respx.mock(assert_all_called=True) as m:
        send = m.post(SEND_URL).respond(200, json={"id": "18c0ffee", "threadId": "t1"})
        r = await client.post(f"/api/job-emails/{d['id']}/send", headers=h)
    assert r.status_code == 200, r.text
    sent = r.json()
    assert sent["status"] == "sent" and sent["gmail_message_id"] == "18c0ffee" and sent["sent_at"]
    req = send.calls[0].request
    assert req.headers["authorization"] == "Bearer ya29.access-1"
    raw = base64.urlsafe_b64decode(__import__("json").loads(req.content)["raw"])
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    assert msg["To"] == "careers@tinystartup.io" and msg["Subject"] == "Backend Developer – Deep Sen"
    assert "deep.sen@gmail.com" in msg["From"]
    parts = [p for p in msg.walk() if p.get_content_type() == "application/pdf"]
    assert len(parts) == 1 and parts[0].get_payload(decode=True).startswith(b"%PDF-")

    # duplicate protection: re-send, retry, editing or re-drafting the same recipient
    assert (await client.post(f"/api/job-emails/{d['id']}/send", headers=h)).status_code == 409
    assert (await client.post(f"/api/job-emails/{d['id']}/retry", headers=h)).status_code == 409
    assert (await client.put(f"/api/job-emails/{d['id']}", headers=h, json={"subject": "x"})).status_code == 409
    again = (await client.post("/api/job-emails/drafts", headers=h, json={"job_id": job1})).json()
    assert again["id"] == d["id"]
    r = await client.put(f"/api/job-emails/{p['id']}", headers=h, json={"recipient_email": "not-an-email"})
    assert r.status_code == 422

    # manual recipient + undeliverable domain -> failed with a reason, never sent
    r = await client.put(f"/api/job-emails/{p['id']}", headers=h, json={"recipient_email": "hr@no-mail-domain.co"})
    assert r.json()["status"] == "ready" and r.json()["recipient_source"] == "manual"
    with respx.mock(assert_all_called=False) as m:
        send = m.post(SEND_URL).respond(200, json={"id": "never"})
        r = await client.post(f"/api/job-emails/{p['id']}/send", headers=h)
        assert not send.called
    assert r.status_code == 422
    failed = (await client.get(f"/api/job-emails/{p['id']}", headers=h)).json()
    assert failed["status"] == "failed" and "cannot receive" in failed["error_message"]

    # Gmail error -> failed; retry after fixing; access token is refreshed when expired
    r = await client.put(f"/api/job-emails/{p['id']}", headers=h, json={"recipient_email": "talent@otherco.com"})
    async with dbmod.SessionLocal() as db:
        acc = await db.get(GmailAccount, acc_id)
        acc.token_expiry = datetime.now(timezone.utc) - timedelta(minutes=5)
        await db.commit()
    with respx.mock() as m:
        refresh = m.post(TOKEN_URL).respond(200, json={"access_token": "ya29.access-2", "expires_in": 3599})
        m.post(SEND_URL).respond(503, json={"error": {"code": 503, "status": "UNAVAILABLE", "message": "backend error"}})
        r = await client.post(f"/api/job-emails/{p['id']}/send", headers=h)
        assert refresh.called and "refresh_token=1%2F%2Frefresh-1" in refresh.calls[0].request.content.decode()
    assert r.status_code == 429  # transient
    assert (await client.get(f"/api/job-emails/{p['id']}", headers=h)).json()["status"] == "failed"
    with respx.mock() as m:
        send = m.post(SEND_URL).respond(200, json={"id": "18c0ffef"})
        r = await client.post(f"/api/job-emails/{p['id']}/retry", headers=h)
        assert send.calls[0].request.headers["authorization"] == "Bearer ya29.access-2"
    assert r.json()["status"] == "sent" and r.json()["attempts"] == 3

    # history filters
    hist = (await client.get("/api/job-emails", headers=h, params={"status": "sent"})).json()
    assert hist["total"] == 2
    assert (await client.get("/api/job-emails", headers=h, params={"status": "sent", "q": "other co"})).json()["total"] == 1
    stats = (await client.get("/api/job-emails/stats", headers=h)).json()
    assert stats["by_status"]["sent"] == 2 and stats["sent_last_24h"] == 2

    # disconnect revokes at Google and deletes the tokens
    with respx.mock(assert_all_called=True) as m:
        m.post(REVOKE_URL).respond(200)
        assert (await client.delete(f"/api/gmail/disconnect/{acc_id}", headers=h)).status_code == 200
    assert (await client.get("/api/gmail/accounts", headers=h)).json()["accounts"] == []
    hist = (await client.get("/api/job-emails", headers=h, params={"status": "sent"})).json()
    assert {x["sender_email"] for x in hist["items"]} == {"deep.sen@gmail.com"}  # history keeps the sender


@pytest.mark.asyncio
async def test_automatic_sending_is_opt_in_limited_and_pausable(client, resume_pdf):
    from app import db as dbmod
    from app.services.job_email_service import process_auto_queue, prepare_for_jobs
    from app.models import User

    h = await _setup_user(client, resume_pdf)
    await _connect_gmail(client, h)
    jobs = {
        await _add_job("GenAI Engineer", "Send resume to jobs@alpha.ai", 90, "Alpha"),
        await _add_job("Backend Engineer", "Send resume to jobs@beta.io", 80, "Beta"),
        await _add_job("Node.js Developer", "Send resume to jobs@beta.io", 75, "Beta"),  # same recruiter
        await _add_job("Data Analyst", "Send resume to hr@gamma.in", 20, "Gamma"),  # below auto threshold
    }
    async with dbmod.SessionLocal() as db:
        user = (await db.execute(select(User))).scalar_one()
        res = await prepare_for_jobs(db, user, jobs)
    assert res["hr_emails_found"] == 3  # the 20-score job is below the profile's minimum match score

    with respx.mock(assert_all_called=False) as m:
        send = m.post(SEND_URL).respond(200, json={"id": "auto"})
        # OFF by default: nothing is sent
        assert (await process_auto_queue(dbmod.SessionLocal, 1))["note"] == "automatic sending is off"
        assert (await client.post("/api/job-emails/auto-send", headers=h)).status_code == 409
        assert not send.called

        r = await client.put("/api/job-emails/settings", headers=h, json={"daily_limit": 1})
        assert r.json()["daily_limit"] == 1 and r.json()["auto_send_enabled"] is False
        async with dbmod.SessionLocal() as db:  # enable without triggering the background run
            user = await db.get(User, 1)
            from app.services.job_email_service import save_email_settings
            save_email_settings(user, {"auto_send_enabled": True})
            await db.commit()
        out = await process_auto_queue(dbmod.SessionLocal, 1)
        assert out == {"sent": 1, "failed": 0, "skipped": 0, "note": "daily limit reached"}
        to = email.message_from_bytes(base64.urlsafe_b64decode(__import__("json").loads(send.calls[0].request.content)["raw"]))["To"]
        assert to == "jobs@alpha.ai"  # highest match first

        await client.put("/api/job-emails/settings", headers=h, json={"daily_limit": 10})
        async with dbmod.SessionLocal() as db:
            user = await db.get(User, 1)
            save_email_settings(user, {"auto_send_enabled": False})  # pause
            await db.commit()
        assert (await process_auto_queue(dbmod.SessionLocal, 1))["sent"] == 0
        async with dbmod.SessionLocal() as db:
            user = await db.get(User, 1)
            save_email_settings(user, {"auto_send_enabled": True})
            await db.commit()
        out = await process_auto_queue(dbmod.SessionLocal, 1)
        # Beta's recruiter gets ONE email for two jobs; the second is held back
        assert out["sent"] == 1 and out["skipped"] == 1
        assert send.call_count == 2
        out = await process_auto_queue(dbmod.SessionLocal, 1)
        assert out["sent"] == 0  # 7-day recruiter cool-down keeps it from going out on the next run either
    sent = (await client.get("/api/job-emails", headers=h, params={"status": "sent"})).json()["items"]
    assert {x["mode"] for x in sent} == {"auto"}


@pytest.mark.asyncio
async def test_invalid_token_encryption_key_gives_clear_error(client, resume_pdf, monkeypatch):
    from app.config import get_settings
    from app.core import crypto
    h = await _setup_user(client, resume_pdf)
    monkeypatch.setattr(get_settings(), "token_encryption_key", "not-a-key")
    crypto._fernet.cache_clear()
    try:
        r = await client.post("/api/gmail/connect", headers=h)
        assert r.status_code == 503 and "TOKEN_ENCRYPTION_KEY" in r.json()["detail"]
    finally:
        monkeypatch.undo()
        crypto._fernet.cache_clear()
