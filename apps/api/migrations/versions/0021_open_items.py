"""Open items with other people (money to get back or still owed).

Revision ID: 0021_open_items
Revises: 0020_account_iban
"""
from alembic import op
import sqlalchemy as sa

revision = "0021_open_items"
down_revision = "0020_account_iban"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "open_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("person", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("since", sa.Date(), nullable=False),
        sa.Column("due", sa.Date(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("settled_transaction_id", sa.String(36), nullable=True),
        sa.Column("settled_on", sa.Date(), nullable=True),
        sa.Column("note", sa.String(300), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_open_items_user_id", "open_items", ["user_id"])


def downgrade():
    op.drop_index("ix_open_items_user_id", table_name="open_items")
    op.drop_table("open_items")
