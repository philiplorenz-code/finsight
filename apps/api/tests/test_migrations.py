from alembic import command
from pathlib import Path
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.config import settings
from app.db import Base

CONFIG_PATH = str(Path(__file__).resolve().parents[1] / "alembic.ini")


def test_frozen_migration_matches_models_and_reverses(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "synthetic-migration.db")
    monkeypatch.setattr(settings, "database_url", url)
    config = Config(CONFIG_PATH)
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        assert diff == []
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_postgresql_offline_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://synthetic:synthetic-unused@localhost/synthetic")
    from io import StringIO
    stream = StringIO()
    command.upgrade(Config(CONFIG_PATH, output_buffer=stream), "head", sql=True)
    sql = stream.getvalue()
    assert "CREATE TABLE transactions" in sql
    assert "NUMERIC(24, 8)" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
