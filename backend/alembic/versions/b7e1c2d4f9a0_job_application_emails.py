"""job application emails: gmail accounts, email templates, job emails

Revision ID: b7e1c2d4f9a0
Revises: 03ab5f84aca4
Create Date: 2026-11-10 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e1c2d4f9a0"
down_revision: Union[str, None] = "03ab5f84aca4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ts():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]


def upgrade() -> None:
    op.create_table(
        "gmail_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("encrypted_access_token", sa.Text()),
        sa.Column("encrypted_refresh_token", sa.Text()),
        sa.Column("token_expiry", sa.DateTime(timezone=True)),
        sa.Column("scopes", sa.String(1000)),
        sa.Column("is_connected", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_error", sa.String(500)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        *_ts(),
        sa.UniqueConstraint("user_id", "email", name="uq_user_gmail"),
    )
    op.create_index("ix_gmail_accounts_user_id", "gmail_accounts", ["user_id"])

    op.create_table(
        "email_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_ts(),
    )
    op.create_index("ix_email_templates_user_id", "email_templates", ["user_id"])

    op.create_table(
        "job_emails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_email", sa.String(320)),
        sa.Column("recipient_source", sa.String(20)),
        sa.Column("hr_name", sa.String(120)),
        sa.Column("sender_account_id", sa.Integer(), sa.ForeignKey("gmail_accounts.id", ondelete="SET NULL")),
        sa.Column("sender_email", sa.String(320)),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("email_templates.id", ondelete="SET NULL")),
        sa.Column("template_name", sa.String(120)),
        sa.Column("subject", sa.String(300), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("resume_id", sa.Integer(), sa.ForeignKey("resumes.id", ondelete="SET NULL")),
        sa.Column("attach_resume", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("mode", sa.String(10), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("gmail_message_id", sa.String(100)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.String(1000)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("edited_by_user", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_ts(),
        sa.UniqueConstraint("user_id", "job_id", "recipient_email", name="uq_job_email_recipient"),
    )
    op.create_index("ix_job_emails_user_id", "job_emails", ["user_id"])
    op.create_index("ix_job_emails_job_id", "job_emails", ["job_id"])
    op.create_index("ix_job_emails_sent_at", "job_emails", ["sent_at"])
    op.create_index("ix_job_emails_user_status", "job_emails", ["user_id", "status"])


def downgrade() -> None:
    op.drop_table("job_emails")
    op.drop_table("email_templates")
    op.drop_table("gmail_accounts")
