"""Contract terms and cancellation deadlines entered by the owner.

Revision ID: 0019_contract_terms
Revises: 0018_device_keys
"""
from alembic import op
import sqlalchemy as sa

revision = "0019_contract_terms"
down_revision = "0018_device_keys"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contract_terms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key", sa.String(300), nullable=False),
        sa.Column("term_end", sa.Date(), nullable=True),
        sa.Column("notice_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("renew_months", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("note", sa.String(300), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "key"),
    )
    op.create_index("ix_contract_terms_user_id", "contract_terms", ["user_id"])


def downgrade():
    op.drop_index("ix_contract_terms_user_id", table_name="contract_terms")
    op.drop_table("contract_terms")
