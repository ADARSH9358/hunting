"""SQLAlchemy ORM models.

Jobs and companies are global (shared, de-duplicated catalogue). Matches, saved
jobs, profiles and search sessions are per user.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)


class Resume(Base):
    __tablename__ = "resumes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_text: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CandidateProfile(TimestampMixin, Base):
    __tablename__ = "candidate_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    preferences: Mapped[dict] = mapped_column(JSONType, default=dict)
    experience_level: Mapped[str | None] = mapped_column(String(50))
    total_experience_months: Mapped[int] = mapped_column(Integer, default=0)
    professional_experience_months: Mapped[int] = mapped_column(Integer, default=0)
    internship_experience_months: Mapped[int] = mapped_column(Integer, default=0)
    relevant_experience_months: Mapped[int] = mapped_column(Integer, default=0)
    education_level: Mapped[str | None] = mapped_column(String(50))
    analysis_method: Mapped[str] = mapped_column(String(20), default="rules")
    edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    skills: Mapped[list[CandidateSkill]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", lazy="selectin"
    )


class CandidateSkill(Base):
    __tablename__ = "candidate_skills"
    __table_args__ = (UniqueConstraint("profile_id", "canonical", name="uq_profile_skill"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    canonical: Mapped[str] = mapped_column(String(100), index=True)
    category: Mapped[str] = mapped_column(String(40), default="other")
    source: Mapped[str] = mapped_column(String(20), default="resume")
    profile: Mapped[CandidateProfile] = relationship(back_populates="skills")


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    website: Mapped[str | None] = mapped_column(String(512))
    careers_url: Mapped[str | None] = mapped_column(String(512))
    logo_url: Mapped[str | None] = mapped_column(String(512))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    size_category: Mapped[str | None] = mapped_column(String(20), index=True)  # small|medium|large
    size_source: Mapped[str | None] = mapped_column(String(100))
    company_type: Mapped[str | None] = mapped_column(String(50))
    industry: Mapped[str | None] = mapped_column(String(100))
    ats_type: Mapped[str | None] = mapped_column(String(40))
    ats_slug: Mapped[str | None] = mapped_column(String(255))
    discovered_via: Mapped[str | None] = mapped_column(String(100))
    first_discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_check_status: Mapped[str | None] = mapped_column(String(40))
    open_jobs_count: Mapped[int] = mapped_column(Integer, default=0)

    career_pages: Mapped[list[CompanyCareerPage]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class CompanyCareerPage(Base):
    __tablename__ = "company_career_pages"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(1024), unique=True)
    page_type: Mapped[str] = mapped_column(String(30), default="html")  # ats_api|html|jsonld
    ats_type: Mapped[str | None] = mapped_column(String(40))
    robots_allowed: Mapped[bool | None] = mapped_column(Boolean)
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(40))
    job_count: Mapped[int] = mapped_column(Integer, default=0)
    company: Mapped[Company] = relationship(back_populates="career_pages")


class JobSource(Base):
    __tablename__ = "job_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))  # ats|job_board_api|aggregator|career_page|licensed
    base_url: Mapped[str | None] = mapped_column(String(512))
    is_official_company_source: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_credentials: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30), default="unknown")
    notes: Mapped[str | None] = mapped_column(Text)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_job_count: Mapped[int] = mapped_column(Integer, default=0)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_company_title", "company_id", "normalized_title"),
        Index("ix_jobs_status_posted", "status", "date_posted"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    normalized_title: Mapped[str] = mapped_column(String(300), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    company_name: Mapped[str] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(300))
    normalized_location: Mapped[str | None] = mapped_column(String(300))
    work_mode: Mapped[str] = mapped_column(String(20), default="unknown")  # remote|hybrid|onsite|unknown
    employment_type: Mapped[str | None] = mapped_column(String(50))
    experience_min_years: Mapped[float | None] = mapped_column(Float)
    experience_max_years: Mapped[float | None] = mapped_column(Float)
    experience_text: Mapped[str | None] = mapped_column(String(200))
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    salary_currency: Mapped[str | None] = mapped_column(String(10))
    salary_period: Mapped[str | None] = mapped_column(String(20))
    salary_text: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    description_hash: Mapped[str | None] = mapped_column(String(64))
    apply_url: Mapped[str | None] = mapped_column(String(2048))
    canonical_url: Mapped[str | None] = mapped_column(String(2048), index=True)
    company_careers_url: Mapped[str | None] = mapped_column(String(1024))
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)
    date_posted: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|unavailable
    first_seen_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("search_sessions.id", ondelete="SET NULL")
    )

    company: Mapped[Company | None] = relationship(lazy="joined")
    skills: Mapped[list[JobSkill]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    source_links: Mapped[list[JobSourceLink]] = relationship(
        back_populates="job", cascade="all, delete-orphan", lazy="selectin"
    )


class JobSourceLink(Base):
    """One row per place a job was found (portal listing, ATS board, career page)."""

    __tablename__ = "job_source_links"
    __table_args__ = (UniqueConstraint("source_key", "external_id", name="uq_source_external"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("job_sources.id", ondelete="SET NULL"))
    source_key: Mapped[str] = mapped_column(String(60))
    source_name: Mapped[str] = mapped_column(String(120))
    external_id: Mapped[str] = mapped_column(String(512))
    url: Mapped[str | None] = mapped_column(String(2048))
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="active")
    job: Mapped[Job] = relationship(back_populates="source_links")


class JobSkill(Base):
    __tablename__ = "job_skills"
    __table_args__ = (UniqueConstraint("job_id", "canonical", name="uq_job_skill"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    canonical: Mapped[str] = mapped_column(String(100), index=True)
    category: Mapped[str] = mapped_column(String(40), default="other")


class JobMatch(Base):
    __tablename__ = "job_matches"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_user_job_match"),
        Index("ix_match_user_score", "user_id", "score"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="SET NULL"))
    session_id: Mapped[int | None] = mapped_column(ForeignKey("search_sessions.id", ondelete="SET NULL"))
    score: Mapped[float] = mapped_column(Float, default=0)
    breakdown: Mapped[dict] = mapped_column(JSONType, default=dict)
    matched_skills: Mapped[list] = mapped_column(JSONType, default=list)
    missing_skills: Mapped[list] = mapped_column(JSONType, default=list)
    experience_fit: Mapped[str | None] = mapped_column(String(200))
    explanation: Mapped[str | None] = mapped_column(Text)
    llm_explanation: Mapped[str | None] = mapped_column(Text)
    gaps: Mapped[list] = mapped_column(JSONType, default=list)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    job: Mapped[Job] = relationship(lazy="joined")


class SavedJob(Base):
    __tablename__ = "saved_jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_saved"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    notes: Mapped[str | None] = mapped_column(Text)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SearchSession(Base):
    __tablename__ = "search_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str | None] = mapped_column(String(200))
    keywords: Mapped[list] = mapped_column(JSONType, default=list)
    config: Mapped[dict] = mapped_column(JSONType, default=dict)
    stats: Mapped[dict] = mapped_column(JSONType, default=dict)
    source_results: Mapped[dict] = mapped_column(JSONType, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SearchLog(Base):
    __tablename__ = "search_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("search_sessions.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    level: Mapped[str] = mapped_column(String(10), default="info")
    source_key: Mapped[str | None] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONType, default=dict)


# ------------------------------------------------------------------ job application emails
class GmailAccount(TimestampMixin, Base):
    """A Gmail account the user connected via Google OAuth 2.0 (scope: gmail.send).

    Tokens are encrypted at rest (see ``app.core.crypto``) and never leave the backend."""

    __tablename__ = "gmail_accounts"
    __table_args__ = (UniqueConstraint("user_id", "email", name="uq_user_gmail"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    encrypted_access_token: Mapped[str | None] = mapped_column(Text)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text)
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[str | None] = mapped_column(String(1000))
    is_connected: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailTemplate(TimestampMixin, Base):
    __tablename__ = "email_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class JobEmail(TimestampMixin, Base):
    """One application email for one job and one recipient.

    status: pending (no recipient yet) | ready | sending | sent | failed | skipped.
    The unique constraint makes it impossible to create a second email to the same
    recipient for the same job, so a job recipient can never be emailed twice by accident."""

    __tablename__ = "job_emails"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", "recipient_email", name="uq_job_email_recipient"),
        Index("ix_job_emails_user_status", "user_id", "status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    recipient_email: Mapped[str | None] = mapped_column(String(320))
    recipient_source: Mapped[str | None] = mapped_column(String(20))  # posting | manual
    hr_name: Mapped[str | None] = mapped_column(String(120))
    sender_account_id: Mapped[int | None] = mapped_column(ForeignKey("gmail_accounts.id", ondelete="SET NULL"))
    sender_email: Mapped[str | None] = mapped_column(String(320))
    template_id: Mapped[int | None] = mapped_column(ForeignKey("email_templates.id", ondelete="SET NULL"))
    template_name: Mapped[str | None] = mapped_column(String(120))
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    attach_resume: Mapped[bool] = mapped_column(Boolean, default=True)
    mode: Mapped[str] = mapped_column(String(10), default="manual")  # manual | auto
    status: Mapped[str] = mapped_column(String(20), default="pending")
    gmail_message_id: Mapped[str | None] = mapped_column(String(100))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    error_message: Mapped[str | None] = mapped_column(String(1000))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False)

    job: Mapped[Job] = relationship(lazy="joined")



class Contact(TimestampMixin, Base):  
    """A recruiter/HR contact: arrays of emails and mobile numbers per person."""  
    __tablename__ = "contacts"  
    __table_args__ = (Index("ix_contacts_user_company", "user_id", "company_name"),)  
    id: Mapped[int] = mapped_column(primary_key=True)  
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)  
    name: Mapped[str] = mapped_column(String(200))  
    company_name: Mapped[str | None] = mapped_column(String(255))  
    position: Mapped[str | None] = mapped_column(String(200))  
    email_ids: Mapped[list] = mapped_column(JSONType, default=list)      # ["hr@x.com", ...]  
    mobile_numbers: Mapped[list] = mapped_column(JSONType, default=list) # ["+91...", ...]
