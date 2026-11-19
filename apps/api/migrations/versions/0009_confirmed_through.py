"""Accounts: date until which the latest balance is confirmed by a full-snapshot import.

Revision ID: 0009_confirmed_through
Revises: 0008_business_rules
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_confirmed_through"
down_revision = "0008_business_rules"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounts", sa.Column("confirmed_through", sa.Date(), nullable=True))
    # Backfill from the latest explicit full-snapshot import: accounts with a balance row from it were present.
    bind = op.get_bind()
    imports = bind.execute(sa.text("SELECT id, summary, created_at FROM imports WHERE status = 'completed' ORDER BY created_at DESC")).fetchall()
    import json
    for row in imports:
        summary = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
        if not summary.get("full_snapshot"):
            continue
        created = row[2] if not isinstance(row[2], str) else __import__("datetime").datetime.fromisoformat(row[2])
        bind.execute(sa.text("UPDATE accounts SET confirmed_through = :day WHERE id IN (SELECT account_id FROM balances WHERE import_id = :imp)"),
                     {"day": created.date(), "imp": row[0]})
        break


def downgrade():
    op.drop_column("accounts", "confirmed_through")
