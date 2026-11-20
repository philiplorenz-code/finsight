"""Bank/provider name per account (derived from the IBAN or set by the owner; the IBAN itself is not stored).

Revision ID: 0016_account_provider
Revises: 0015_plan_items
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_account_provider"
down_revision = "0015_plan_items"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounts", sa.Column("provider", sa.String(80), nullable=True))
    op.add_column("accounts", sa.Column("provider_source", sa.String(20), nullable=True))


def downgrade():
    op.drop_column("accounts", "provider_source")
    op.drop_column("accounts", "provider")
