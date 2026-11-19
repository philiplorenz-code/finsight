"""Net worth: ownership share on accounts and manually tracked holdings.

Revision ID: 0007_net_worth
Revises: 0006_transfer_auto
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_net_worth"
down_revision = "0006_transfer_auto"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounts", sa.Column("owner_share", sa.Numeric(7, 4), nullable=False, server_default="100"))
    op.create_table(
        "holdings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("value", sa.Numeric(24, 8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("share", sa.Numeric(7, 4), nullable=False),
        sa.Column("monthly_payment", sa.Numeric(24, 8), nullable=True),
        sa.Column("interest_rate", sa.Numeric(9, 4), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("valued_on", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_holdings_user_id", "holdings", ["user_id"])


def downgrade():
    op.drop_index("ix_holdings_user_id", table_name="holdings")
    op.drop_table("holdings")
    op.drop_column("accounts", "owner_share")
