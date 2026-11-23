"""Receipts remember when they were sent to Paperless.

Revision ID: 0023_receipt_paperless
Revises: 0022_cash_entries
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_receipt_paperless"
down_revision = "0022_cash_entries"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("receipts", sa.Column("paperless_task", sa.String(64), nullable=True))
    op.add_column("receipts", sa.Column("paperless_sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("receipts", "paperless_sent_at")
    op.drop_column("receipts", "paperless_task")
