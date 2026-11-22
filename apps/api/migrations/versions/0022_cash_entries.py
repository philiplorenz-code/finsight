"""Cash book entries.

Revision ID: 0022_cash_entries
Revises: 0021_open_items
"""
from alembic import op
import sqlalchemy as sa

revision = "0022_cash_entries"
down_revision = "0021_open_items"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cash_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("merchant", sa.String(200), nullable=False, server_default=""),
        sa.Column("note", sa.String(300), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cash_entries_user_id", "cash_entries", ["user_id"])


def downgrade():
    op.drop_index("ix_cash_entries_user_id", table_name="cash_entries")
    op.drop_table("cash_entries")
