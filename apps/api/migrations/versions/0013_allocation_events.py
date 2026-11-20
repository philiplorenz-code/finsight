"""Append-only allocation history.

Revision ID: 0013_allocation_events
Revises: 0012_holding_snapshots
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_allocation_events"
down_revision = "0012_holding_snapshots"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "allocation_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("bucket_id", sa.String(36), nullable=False),
        sa.Column("bucket_name", sa.String(300), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_allocation_events_bucket_id", "allocation_events", ["bucket_id"])
    op.create_index("ix_allocation_events_user_id", "allocation_events", ["user_id"])


def downgrade():
    op.drop_index("ix_allocation_events_user_id", table_name="allocation_events")
    op.drop_index("ix_allocation_events_bucket_id", table_name="allocation_events")
    op.drop_table("allocation_events")
