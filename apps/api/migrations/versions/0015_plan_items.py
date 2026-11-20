"""Monthly plan items (SOLL) compared against actual spending.

Revision ID: 0015_plan_items
Revises: 0014_account_changes
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_plan_items"
down_revision = "0014_account_changes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plan_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_plan_items_user_id", "plan_items", ["user_id"])


def downgrade():
    op.drop_index("ix_plan_items_user_id", table_name="plan_items")
    op.drop_table("plan_items")
