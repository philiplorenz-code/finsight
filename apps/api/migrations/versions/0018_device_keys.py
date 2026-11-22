"""Import-only device keys for uploads from the phone (stored as SHA-256 only).

Revision ID: 0018_device_keys
Revises: 0017_receipts
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_device_keys"
down_revision = "0017_receipts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "device_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("hint", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_device_keys_user_id", "device_keys", ["user_id"])


def downgrade():
    op.drop_index("ix_device_keys_user_id", table_name="device_keys")
    op.drop_table("device_keys")
