"""Dated value snapshots for manual holdings.

Revision ID: 0012_holding_snapshots
Revises: 0011_category_rules
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_holding_snapshots"
down_revision = "0011_category_rules"
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table(
        "holding_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("holding_id", sa.String(36), sa.ForeignKey("holdings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(24, 8), nullable=False),
        sa.UniqueConstraint("holding_id", "observed_on", name="uq_holding_snapshot_day"),
    )
    op.create_index("ix_holding_snapshots_holding_id", "holding_snapshots", ["holding_id"])
    from alembic import context
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    import uuid
    rows = bind.execute(sa.text("SELECT id, valued_on, value FROM holdings")).fetchall()
    if rows:
        op.bulk_insert(table, [{"id": str(uuid.uuid4()), "holding_id": r[0], "observed_on": r[1], "value": r[2]} for r in rows])


def downgrade():
    op.drop_index("ix_holding_snapshots_holding_id", table_name="holding_snapshots")
    op.drop_table("holding_snapshots")
