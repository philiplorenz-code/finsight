"""Contract decisions (confirm, dismiss, rename, reclassify detected recurring payments).

Revision ID: 0010_contract_decisions
Revises: 0009_confirmed_through
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_contract_decisions"
down_revision = "0009_confirmed_through"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contract_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key", sa.String(300), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("name", sa.String(300), nullable=True),
        sa.Column("kind", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "key"),
    )
    op.create_index("ix_contract_decisions_user_id", "contract_decisions", ["user_id"])


def downgrade():
    op.drop_index("ix_contract_decisions_user_id", table_name="contract_decisions")
    op.drop_table("contract_decisions")
