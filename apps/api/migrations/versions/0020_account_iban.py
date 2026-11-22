"""IBAN per account, shown on the account card (from the export's Referenzkonto).

Revision ID: 0020_account_iban
Revises: 0019_contract_terms
"""
from alembic import op
import sqlalchemy as sa

revision = "0020_account_iban"
down_revision = "0019_contract_terms"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounts", sa.Column("iban", sa.String(34), nullable=True))


def downgrade():
    op.drop_column("accounts", "iban")
