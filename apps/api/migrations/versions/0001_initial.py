"""Initial owner-scoped finance and integration schema.

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def schema():
    """Frozen initial schema, independent of future application model changes."""
    metadata = sa.MetaData()

    def column(name, type_, nullable=False, primary_key=False, index=False, fk=None):
        args = [sa.ForeignKey(fk)] if fk else []
        return sa.Column(name, type_, *args, nullable=nullable, primary_key=primary_key, index=index)

    def string(name, length=36, **kwargs):
        return column(name, sa.String(length), **kwargs)

    def ident():
        return string("id", primary_key=True)

    def owner():
        return string("user_id", fk="users.id", index=True)

    def timestamp(name="created_at", nullable=False):
        return column(name, sa.DateTime(timezone=True), nullable=nullable)

    def numeric(name, nullable=False, precision=24):
        return column(name, sa.Numeric(precision, 8), nullable=nullable)

    def boolean(name):
        return column(name, sa.Boolean())

    def integer(name):
        return column(name, sa.Integer())

    def json(name):
        return column(name, sa.JSON())

    def table(name, *columns):
        return sa.Table(name, metadata, *columns)

    table("users", ident(), integer("owner_slot"), string("email", 254), column("password_hash", sa.Text()), timestamp(),
          sa.UniqueConstraint("owner_slot"), sa.UniqueConstraint("email"))
    table("sessions", string("id", 64, primary_key=True), owner(), string("csrf_token", 64), timestamp("expires_at"))
    table("login_attempts", ident(), string("key", 64, index=True), timestamp())
    table("accounts", ident(), owner(), string("source_key", 128), string("name", 300), string("currency", 3),
          boolean("included"), string("ownership", 20), string("purpose", 80), boolean("inactive"),
          sa.UniqueConstraint("user_id", "source_key"))
    table("imports", ident(), owner(), string("filename", 255), string("sha256", 64), string("status", 30),
          integer("row_count"), timestamp(), json("summary"), sa.UniqueConstraint("user_id", "sha256"))
    table("transactions", ident(), owner(), string("account_id", fk="accounts.id", index=True), string("source_key", 128),
          column("booking_date", sa.Date(), index=True), column("value_date", sa.Date(), nullable=True), numeric("amount"),
          string("currency", 3), column("merchant", sa.Text()), column("description", sa.Text()), string("category", 300),
          string("category_override", 300, nullable=True), boolean("is_transfer"), boolean("transfer_uncertain"),
          string("split_parent_key", 128, nullable=True), string("split_role", 20), string("contract_name", 300, nullable=True),
          json("tags"), json("source"), string("import_id", fk="imports.id"), boolean("missing_from_latest"), timestamp(),
          sa.UniqueConstraint("user_id", "account_id", "source_key"))
    table("transaction_revisions", ident(), string("transaction_id", fk="transactions.id", index=True),
          string("import_id", fk="imports.id"), json("source"), timestamp())
    table("balances", ident(), string("account_id", fk="accounts.id", index=True), string("import_id", fk="imports.id"),
          column("observed_date", sa.Date()), numeric("amount"), sa.UniqueConstraint("account_id", "observed_date", "import_id"))
    table("buckets", ident(), owner(), string("name", 300), string("currency", 3), string("kind", 20),
          numeric("target", nullable=True), column("due_date", sa.Date(), nullable=True))
    table("allocations", ident(), string("bucket_id", fk="buckets.id", index=True),
          string("account_id", fk="accounts.id", index=True), numeric("amount"), sa.UniqueConstraint("bucket_id", "account_id"))
    table("obligations", ident(), string("bucket_id", fk="buckets.id", index=True), string("name", 300), numeric("amount"),
          string("period", 20), column("due_date", sa.Date(), nullable=True), numeric("scheduled_contributions"))
    table("findings", ident(), owner(), string("title", 300), column("body", sa.Text()), string("kind", 50),
          string("status", 30), json("evidence"), timestamp())
    table("settings", string("user_id", fk="users.id", primary_key=True), json("data"))
    table("ai_policies", string("owner_id", 64, primary_key=True), boolean("enabled"), boolean("external_consent"),
          boolean("proactive_consent"), string("model", 160), string("budget_currency", 3, nullable=True), json("prices"), numeric("total_limit", precision=20),
          numeric("monthly_limit", precision=20), json("channel_limits"), numeric("run_limit", precision=20),
          integer("max_concurrent"), integer("max_input_tokens"), integer("max_output_tokens"), integer("max_tools"),
          integer("max_steps"), integer("timeout_seconds"))
    runs = table("ai_runs", ident(), string("owner_id", 64, index=True), string("channel", 24), string("model", 160), string("currency", 3, nullable=True),
          timestamp(), timestamp("settled_at", nullable=True), string("state", 24), numeric("reserved", precision=20),
          numeric("charged", nullable=True, precision=20), numeric("input_rate", precision=20), numeric("output_rate", precision=20),
          column("input_tokens", sa.Integer(), nullable=True), column("output_tokens", sa.Integer(), nullable=True),
          string("error_code", 48, nullable=True), json("evidence"))
    sa.Index("ix_ai_runs_created_at", runs.c.created_at)
    table("notification_settings", string("owner_id", 64, primary_key=True), boolean("enabled"), string("server", 500),
          string("topic", 100), string("timezone", 80), integer("quiet_start"), integer("quiet_end"), integer("stale_after_hours"),
          timestamp("last_import_at", nullable=True), json("events"), integer("reminder_hour"), integer("reminder_minute"), integer("weekly_day"))
    table("notification_history", ident(), string("owner_id", 64, index=True), string("event", 32), string("dedupe_key", 200),
          string("state", 32), string("reason", 48, nullable=True), timestamp(), timestamp("available_at"),
          timestamp("sent_at", nullable=True), integer("attempts"), sa.UniqueConstraint("owner_id", "dedupe_key", name="uq_notification_dedupe"))
    jobs = table("worker_jobs", ident(), string("owner_id", 64, index=True), string("kind", 48, index=True), json("payload"),
          string("dedupe_key", 200, nullable=True), string("state", 24, index=True), timestamp("available_at"), timestamp(),
          timestamp("lease_until", nullable=True), string("lease_token", nullable=True), integer("attempts"), integer("max_attempts"),
          boolean("replay_safe"), sa.UniqueConstraint("owner_id", "dedupe_key", name="uq_worker_job_dedupe"))
    sa.Index("ix_worker_jobs_available_at", jobs.c.available_at)
    table("worker_job_attempts", ident(), string("job_id", index=True), string("token"), timestamp("started_at"),
          timestamp("finished_at", nullable=True), string("outcome", 32), string("error_code", 48, nullable=True), sa.UniqueConstraint("token"))
    return metadata


def upgrade():
    schema().create_all(bind=op.get_bind(), checkfirst=False)


def downgrade():
    schema().drop_all(bind=op.get_bind(), checkfirst=False)
