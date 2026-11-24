"""Contract terms remember the customer number and when the owner cancelled.

Revision ID: 0024_contract_cancellation
Revises: 0023_receipt_paperless
"""
from alembic import op
import sqlalchemy as sa

revision = "0024_contract_cancellation"
down_revision = "0023_receipt_paperless"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("contract_terms", sa.Column("customer_number", sa.String(120), nullable=False, server_default=""))
    op.add_column("contract_terms", sa.Column("cancelled_on", sa.Date(), nullable=True))
    op.add_column("contract_terms", sa.Column("cancelled_effective", sa.Date(), nullable=True))


def downgrade():
    op.drop_column("contract_terms", "cancelled_effective")
    op.drop_column("contract_terms", "cancelled_on")
    op.drop_column("contract_terms", "customer_number")
