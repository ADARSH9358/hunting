"""contacts table  
  
Revision ID: c3f4a5b6d7e8  
Revises: b7e1c2d4f9a0  
"""  
from typing import Sequence, Union  
import sqlalchemy as sa  
from alembic import op  
from sqlalchemy.dialects import postgresql  
  
revision: str = "c3f4a5b6d7e8"  
down_revision: Union[str, None] = "b7e1c2d4f9a0"  
branch_labels: Union[str, Sequence[str], None] = None  
depends_on: Union[str, Sequence[str], None] = None  
  
  
def upgrade() -> None:  
    op.create_table(  
        "contacts",  
        sa.Column("id", sa.Integer(), primary_key=True),  
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),  
        sa.Column("name", sa.String(200), nullable=False),  
        sa.Column("company_name", sa.String(255)),  
        sa.Column("position", sa.String(200)),  
        sa.Column("email_ids", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),  
                  nullable=False, server_default="[]"),  
        sa.Column("mobile_numbers", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),  
                  nullable=False, server_default="[]"),  
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),  
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),  
    )  
    op.create_index("ix_contacts_user_id", "contacts", ["user_id"])  
    op.create_index("ix_contacts_user_company", "contacts", ["user_id", "company_name"])  
  
  
def downgrade() -> None:  
    op.drop_table("contacts")