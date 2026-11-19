"""Wishlist and affordability preferences.

Revision ID: 0003_wishlist
Revises: 0002_mcp_oauth
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_wishlist"
down_revision = "0002_mcp_oauth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wishes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("price", sa.Numeric(24, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("follow_up_monthly_cost", sa.Numeric(24, 8), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_wishes_user_id", "wishes", ["user_id"])
    op.create_table(
        "wishlist_prefs",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("self_names", sa.JSON(), nullable=False),
        sa.Column("reserve_months", sa.Integer(), nullable=False),
        sa.Column("monthly_tax_reserve", sa.Numeric(24, 8), nullable=False),
    )


def downgrade():
    op.drop_table("wishlist_prefs")
    op.drop_index("ix_wishes_user_id", table_name="wishes")
    op.drop_table("wishes")
