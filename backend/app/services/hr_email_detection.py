"""Find the recruiter / HR email address in a job posting.

Rules (deliberately conservative):
* Only addresses that literally appear in the posting text are used - nothing is guessed
  or constructed (no "hr@<company domain>" patterns).
* Obvious non-recipients are dropped (no-reply, example domains, image file names, tracking).
* Addresses near hiring words ("send your CV", "HR", "careers", "apply") or with a
  recruiting local part (hr@, careers@, jobs@, talent@ …) rank first; an address with
  no hiring context at all is only accepted when it is the single address in the posting.
* Syntax is validated with ``email-validator``; deliverability (the domain has MX/A
  records) is checked right before sending.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from email_validator import EmailNotValidError, validate_email

EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24})(?![\w-])")
# "name [at] company [dot] com" - common in recruiter posts
OBFUSCATED_RE = re.compile(
    r"([A-Za-z0-9._%+-]{1,64})\s*[\[(]\s*at\s*[\])]\s*([A-Za-z0-9-]+(?:\s*[\[(]\s*dot\s*[\])]\s*[A-Za-z0-9-]+)+)", re.I)
HR_CONTEXT = re.compile(
    r"\b(hr|human resources?|recruit\w*|talent|hiring|careers?|jobs?|apply|application|resume|cv|"
    r"send|share|mail|email|e-mail|reach out|contact|interested|profiles?)\b", re.I)
HR_LOCAL = re.compile(r"^(hr|careers?|jobs?|recruit\w*|talent\w*|hiring|people|apply|resumes?|cv|work|join\w*|team)([._-].*)?$", re.I)
BLOCKED_LOCAL = re.compile(r"(no-?reply|do-?not-?reply|donotreply|mailer-daemon|postmaster|abuse|privacy|gdpr|"
                           r"unsubscribe|bounce|notifications?|support|billing|sales|info@?$|press|media|legal|security|webmaster)", re.I)
BLOCKED_DOMAIN = re.compile(r"(^|\.)(example\.(com|org|net)|test\.com|domain\.com|email\.com|yourcompany\.com|"
                            r"sentry\.io|wixpress\.com|sentry-next\.wixpress\.com|users\.noreply\.github\.com)$", re.I)
FILE_TLD = re.compile(r"\.(png|jpe?g|gif|svg|webp|css|js|ico)$", re.I)
NAME_RE = re.compile(
    r"(?i:contact(?: person)?|reach out to|connect with|share (?:your )?(?:cv|resume|profile)s? (?:with|to)|"
    r"send (?:your )?(?:cv|resume|profile)s? to|hr|recruiter|poc)\s*[:\-–]?\s*"
    r"((?:Mr\.?|Ms\.?|Mrs\.?)?\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*(?:[,(\-–|:]|\bat\b|\bon\b|$)")


@dataclass
class DetectedEmail:
    email: str
    score: int
    hr_name: str | None = None


def normalize_email(addr: str) -> str | None:
    """Syntax validation; returns the normalized address or None."""
    try:
        return validate_email(addr.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None


def _candidates(text: str) -> list[tuple[str, int]]:
    out = [(m.group(1), m.start()) for m in EMAIL_RE.finditer(text)]
    for m in OBFUSCATED_RE.finditer(text):
        domain = re.sub(r"\s*[\[(]\s*dot\s*[\])]\s*", ".", m.group(2), flags=re.I)
        out.append((f"{m.group(1)}@{domain}", m.start()))
    return out


def detect_hr_emails(text: str | None) -> list[DetectedEmail]:
    if not text:
        return []
    found: dict[str, DetectedEmail] = {}
    for raw, pos in _candidates(text):
        local, _, domain = raw.rpartition("@")
        if FILE_TLD.search(raw) or BLOCKED_DOMAIN.search(domain) or BLOCKED_LOCAL.search(local):
            continue
        addr = normalize_email(raw)
        if not addr:
            continue
        window = text[max(0, pos - 160): pos + len(raw) + 40]
        score = 0
        if HR_LOCAL.match(local):
            score += 3
        score += min(3, len(HR_CONTEXT.findall(window)))
        name_m = NAME_RE.search(text[max(0, pos - 120): pos])
        hr_name = re.sub(r"^(Mr|Ms|Mrs)\.?\s*", "", name_m.group(1)).strip() if name_m else None
        prev = found.get(addr)
        if prev is None or score > prev.score:
            found[addr] = DetectedEmail(addr, score, hr_name or (prev.hr_name if prev else None))
    ranked = sorted(found.values(), key=lambda d: -d.score)
    if len(ranked) > 1:
        ranked = [d for d in ranked if d.score > 0]  # several addresses: keep those with hiring context
    return ranked


def best_hr_email(text: str | None) -> DetectedEmail | None:
    r = detect_hr_emails(text)
    return r[0] if r else None


def _deliverable_sync(addr: str) -> tuple[bool, str | None]:
    try:
        validate_email(addr, check_deliverability=True, timeout=8)
        return True, None
    except EmailNotValidError as e:
        return False, str(e)[:200]


async def check_deliverable(addr: str) -> tuple[bool, str | None]:
    """DNS check that the recipient domain accepts mail (MX, or A fallback)."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(_deliverable_sync, addr), timeout=15)
    except asyncio.TimeoutError:
        return False, "Timed out checking the recipient's mail domain"
