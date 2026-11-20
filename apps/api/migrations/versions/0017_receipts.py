"""Receipts and their line items (image stays in the upload directory).

Revision ID: 0017_receipts
Revises: 0016_account_provider
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_receipts"
down_revision = "0016_account_provider"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("image_path", sa.String(200), nullable=False),
        sa.Column("image_sha256", sa.String(64), nullable=False),
        sa.Column("image_type", sa.String(10), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("merchant", sa.String(200), nullable=True),
        sa.Column("receipt_date", sa.Date(), nullable=True),
        sa.Column("total", sa.Numeric(24, 8), nullable=True),
        sa.Column("transaction_id", sa.String(36), sa.ForeignKey("transactions.id"), nullable=True),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_receipts_user_id", "receipts", ["user_id"])
    op.create_index("ix_receipts_image_sha256", "receipts", ["image_sha256"])
    op.create_table(
        "receipt_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("receipt_id", sa.String(36), sa.ForeignKey("receipts.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 4), nullable=False),
        sa.Column("unit_price", sa.Numeric(24, 8), nullable=True),
        sa.Column("total", sa.Numeric(24, 8), nullable=False),
        sa.Column("category", sa.String(60), nullable=False),
    )
    op.create_index("ix_receipt_items_receipt_id", "receipt_items", ["receipt_id"])


def downgrade():
    op.drop_index("ix_receipt_items_receipt_id", table_name="receipt_items")
    op.drop_table("receipt_items")
    op.drop_index("ix_receipts_image_sha256", table_name="receipts")
    op.drop_index("ix_receipts_user_id", table_name="receipts")
    op.drop_table("receipts")
