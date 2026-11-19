"""Income source rules (employment vs business).

Revision ID: 0004_income_rules
Revises: 0003_wishlist
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_income_rules"
down_revision = "0003_wishlist"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "income_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("pattern", sa.String(200), nullable=False),
        sa.Column("match_field", sa.String(20), nullable=False),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_income_rules_user_id", "income_rules", ["user_id"])


def downgrade():
    op.drop_index("ix_income_rules_user_id", table_name="income_rules")
    op.drop_table("income_rules")
