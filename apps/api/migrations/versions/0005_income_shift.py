"""Income rule month shift (pay booked at month end counts for the next month).

Revision ID: 0005_income_shift
Revises: 0004_income_rules
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_income_shift"
down_revision = "0004_income_rules"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("income_rules", sa.Column("shift_from_day", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("income_rules", "shift_from_day")
