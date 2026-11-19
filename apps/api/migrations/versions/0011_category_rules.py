"""Category rules, the rule category on bookings and rejected transfer pairs.

Revision ID: 0011_category_rules
Revises: 0010_contract_decisions
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_category_rules"
down_revision = "0010_contract_decisions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("transactions", sa.Column("rule_category", sa.String(300), nullable=True))
    op.create_table(
        "category_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("pattern", sa.String(200), nullable=False),
        sa.Column("match_field", sa.String(20), nullable=False),
        sa.Column("flow", sa.String(10), nullable=False),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("category", sa.String(300), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_category_rules_user_id", "category_rules", ["user_id"])
    op.create_table(
        "transfer_rejections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("booking_date", sa.Date(), nullable=False),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "key"),
    )
    op.create_index("ix_transfer_rejections_user_id", "transfer_rejections", ["user_id"])


def downgrade():
    op.drop_index("ix_transfer_rejections_user_id", table_name="transfer_rejections")
    op.drop_table("transfer_rejections")
    op.drop_index("ix_category_rules_user_id", table_name="category_rules")
    op.drop_table("category_rules")
    op.drop_column("transactions", "rule_category")
