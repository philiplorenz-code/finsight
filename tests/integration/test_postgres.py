"""Production database locking regressions; every test uses an isolated schema.

FINSIGHT_TEST_POSTGRES_URL must point at a disposable local/CI PostgreSQL database.
No financial fixtures or external provider calls are used.
"""
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def pg_sessions():
    url = os.getenv("FINSIGHT_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set FINSIGHT_TEST_POSTGRES_URL for real PostgreSQL locking tests")
    from app.db import Base
    import app.ai  # noqa: F401 -- register models
    import app.jobs  # noqa: F401
    import app.notifications  # noqa: F401

    schema = "test_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_atomic_monthly_budget_reservation(pg_sessions):
    from app.ai import AIPolicy, AIRun, AIBlocked, reserve

    with pg_sessions() as session:
        session.add(AIPolicy(owner_id="synthetic-owner", enabled=True, external_consent=True,
                             proactive_consent=False, model="synthetic-model",
                             prices={"synthetic-model": {"currency": "EUR", "verified": True, "input": "1", "output": "1"}},
                             total_limit=Decimal("1"), monthly_limit=Decimal("0.0002"),
                             channel_limits={"chat": "1"}, run_limit=Decimal("1"),
                             max_concurrent=8, max_input_tokens=128, max_output_tokens=1,
                             max_tools=3, max_steps=6, timeout_seconds=30))
        session.commit()
    barrier = threading.Barrier(2)

    def attempt():
        with pg_sessions() as session:
            barrier.wait(timeout=10)
            try:
                reserve(session, "synthetic-owner")
                session.commit()
                return "reserved"
            except AIBlocked as exc:
                session.rollback()
                return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))
    assert sorted(results) == ["budget_exhausted", "reserved"]
    with pg_sessions() as session:
        assert len(list(session.scalars(select(AIRun)))) == 1


def test_exclusive_persistent_job_claim(pg_sessions):
    from app.jobs import claim, enqueue

    with pg_sessions() as session:
        enqueue(session, "synthetic-owner", "synthetic", {}, dedupe_key="one")
        session.commit()
    barrier = threading.Barrier(2)

    def attempt():
        with pg_sessions() as session:
            barrier.wait(timeout=10)
            item = claim(session, {"synthetic"})
            session.commit()
            return item is not None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: attempt(), range(2)))
    assert sum(results) == 1


def test_concurrent_overlapping_import_revisions(pg_sessions):
    import io
    from datetime import datetime
    from openpyxl import Workbook
    from app.importer import ingest
    from app.models import Transaction, TransactionRevision, User

    def synthetic_export(amount):
        book = Workbook()
        book.active.append(["Buchungstag", "Referenzkonto", "Betrag", "Kontostand", "Waehrung", "Buchungs-ID"])
        book.active.append([datetime(2025, 1, 1), "TEST-ACCOUNT", amount, 100 + amount, "EUR", "TEST-BOOKING"])
        stream = io.BytesIO()
        book.save(stream)
        return stream.getvalue()

    with pg_sessions() as session:
        owner = User(email="synthetic@example.invalid", password_hash="synthetic-unusable-hash")
        session.add(owner)
        session.commit()
        owner_id = owner.id
        ingest(session, owner, synthetic_export(-10), "synthetic-initial.xlsx")
    exports = [synthetic_export(-20), synthetic_export(-30)]
    barrier = threading.Barrier(2)

    def import_revision(data):
        with pg_sessions() as session:
            owner = session.get(User, owner_id)
            barrier.wait(timeout=10)
            ingest(session, owner, data, "synthetic-revision.xlsx")

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(import_revision, exports))
    with pg_sessions() as session:
        transaction = session.scalar(select(Transaction))
        history = [Decimal(revision.source["columns"]["Betrag"]) for revision in session.scalars(select(TransactionRevision))]
        assert len(history) == 2
        assert Decimal("-10") in history
        assert len(set(history)) == 2, "Serialized revisions must not both retain the same stale source"
        assert set(history + [transaction.amount]) == {Decimal("-10"), Decimal("-20"), Decimal("-30")}
