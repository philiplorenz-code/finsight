"""Account setting history (included, ownership, purpose, share) for as-of views.

Revision ID: 0014_account_changes
Revises: 0013_allocation_events
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_account_changes"
down_revision = "0013_allocation_events"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("allocation_events", sa.Column("batch_id", sa.String(36), nullable=True))
    op.create_table(
        "account_changes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
    )
    op.create_index("ix_account_changes_account_id", "account_changes", ["account_id"])


def downgrade():
    op.drop_column("allocation_events", "batch_id")
    op.drop_index("ix_account_changes_account_id", table_name="account_changes")
    op.drop_table("account_changes")
