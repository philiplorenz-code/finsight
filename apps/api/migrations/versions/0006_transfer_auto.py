"""Mark transfers detected by amount matching between owned accounts.

Revision ID: 0006_transfer_auto
Revises: 0005_income_shift
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_transfer_auto"
down_revision = "0005_income_shift"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("transactions", sa.Column("transfer_auto", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("transactions", "transfer_auto")
