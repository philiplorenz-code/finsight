"""Business expense rules.

Revision ID: 0008_business_rules
Revises: 0007_net_worth
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_business_rules"
down_revision = "0007_net_worth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "business_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("pattern", sa.String(200), nullable=False),
        sa.Column("match_field", sa.String(20), nullable=False),
        sa.Column("category", sa.String(300), nullable=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_business_rules_user_id", "business_rules", ["user_id"])


def downgrade():
    op.drop_index("ix_business_rules_user_id", table_name="business_rules")
    op.drop_table("business_rules")
