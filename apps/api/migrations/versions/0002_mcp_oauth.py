"""Owner-consented MCP OAuth schema (frozen).

Revision ID: 0002_mcp_oauth
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_mcp_oauth"
down_revision = "0001"
branch_labels = None
depends_on = None


def schema():
    metadata = sa.MetaData()
    # Reference only; never create or drop the existing owner table here.
    sa.Table("users", metadata, sa.Column("id", sa.String(36), primary_key=True))

    def string(name, length=36, fk=None, primary=False, index=False):
        args = [sa.ForeignKey(fk)] if fk else []
        return sa.Column(name, sa.String(length), *args, primary_key=primary, nullable=False, index=index)

    def ident(length=36):
        return string("id", length, primary=True)

    def date(name):
        return sa.Column(name, sa.DateTime(timezone=True), nullable=False)

    def boolean(name):
        return sa.Column(name, sa.Boolean(), nullable=False)

    def client():
        return string("client_id", fk="mcp_clients.id", index=True)

    def grant():
        return string("grant_id", fk="mcp_grants.id", index=True)

    sa.Table("mcp_clients", metadata, ident(), string("name", 160),
             sa.Column("redirect_uris", sa.JSON(), nullable=False), string("scopes", 128), date("created_at"))
    sa.Table("mcp_auth_requests", metadata, ident(), client(), string("redirect_uri", 2048),
             string("resource", 2048), string("scopes", 128), string("state", 1024),
             string("challenge", 43), date("expires_at"), boolean("decided"))
    sa.Table("mcp_grants", metadata, ident(), string("user_id", fk="users.id", index=True), client(),
             string("resource", 2048), string("scopes", 128), date("created_at"), date("expires_at"), boolean("revoked"))
    sa.Table("mcp_codes", metadata, ident(64), grant(), string("redirect_uri", 2048),
             string("challenge", 43), date("expires_at"), boolean("used"))
    sa.Table("mcp_tokens", metadata, ident(64), grant(), string("kind", 8), string("scopes", 128),
             date("expires_at"), boolean("used"))
    sa.Table("mcp_rate_limits", metadata, string("key", 64, primary=True), date("window_start"),
             sa.Column("count", sa.Integer(), nullable=False))
    return metadata


def upgrade():
    metadata = schema()
    metadata.create_all(op.get_bind(), tables=[t for t in metadata.sorted_tables if t.name != "users"], checkfirst=False)


def downgrade():
    metadata = schema()
    metadata.drop_all(op.get_bind(), tables=[t for t in metadata.sorted_tables if t.name != "users"], checkfirst=False)
