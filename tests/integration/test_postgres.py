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
    import app.mcp_auth  # noqa: F401

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


def test_mcp_single_use_codes_and_refresh_family_replay_on_postgresql(pg_sessions, monkeypatch):
    """Separate HTTP requests and DB sessions must serialize token-family changes."""
    import base64
    import hashlib
    import json
    from datetime import timedelta
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from app import mcp_auth as oauth
    from app.db import get_db
    from app.models import User

    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("APP_URL", "https://synthetic-finance.example.invalid")
    resource = oauth.resource_url()
    verifier = "synthetic-verifier-" + "a" * 48
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    redirect = "https://synthetic-client.example.invalid/callback"
    with pg_sessions() as session:
        user = User(email="synthetic-mcp@example.invalid", password_hash="unusable", owner_slot=1)
        client = oauth.MCPClient(name="Synthetic PostgreSQL client", redirect_uris=[redirect], scopes="finance:read")
        session.add_all([user, client])
        session.flush()
        grant = oauth.MCPGrant(user_id=user.id, client_id=client.id, resource=resource, scopes="finance:read",
                               expires_at=oauth.now() + timedelta(days=1))
        session.add(grant)
        session.flush()
        session.add(oauth.MCPCode(id=oauth.digest("synthetic-code"), grant_id=grant.id,
                                 redirect_uri=redirect, challenge=challenge,
                                 expires_at=oauth.now() + timedelta(minutes=2)))
        client_id, grant_id = client.id, grant.id
        session.commit()

    app = FastAPI()
    app.include_router(oauth.router)

    def database():
        with pg_sessions() as session:
            yield session

    app.dependency_overrides[get_db] = database

    def concurrent_exchange(payload):
        barrier = threading.Barrier(2)

        def attempt(_):
            with TestClient(app) as client:
                barrier.wait(timeout=10)
                response = client.post("/oauth/token", data=payload)
                return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(attempt, range(2)))

    results = concurrent_exchange({"grant_type": "authorization_code", "client_id": client_id,
                                   "code": "synthetic-code", "code_verifier": verifier,
                                   "redirect_uri": redirect, "resource": resource})
    assert sorted(status for status, _ in results) == [200, 400]
    tokens = next(body for status, body in results if status == 200)
    with pg_sessions() as session:
        assert session.get(oauth.MCPCode, oauth.digest("synthetic-code")).used
        assert len(list(session.scalars(select(oauth.MCPToken)))) == 2
        # Correctly bound replay deliberately revokes the winning family too.
        assert session.get(oauth.MCPGrant, grant_id).revoked
        with pytest.raises(HTTPException):
            oauth.verify_bearer_in_session(session, tokens["access_token"])
        # A separate, explicitly authorized family isolates the refresh race.
        grant = oauth.MCPGrant(user_id=session.get(oauth.MCPGrant, grant_id).user_id,
                               client_id=client_id, resource=resource, scopes="finance:read",
                               expires_at=oauth.now() + timedelta(days=1))
        session.add(grant)
        session.flush()
        grant_id = grant.id
        tokens = json.loads(oauth.issue_tokens(session, grant, "finance:read").body)

    results = concurrent_exchange({"grant_type": "refresh_token", "client_id": client_id,
                                   "refresh_token": tokens["refresh_token"], "resource": resource})
    assert sorted(status for status, _ in results) == [200, 400]
    rotated = next(body for status, body in results if status == 200)
    with pg_sessions() as session:
        assert session.get(oauth.MCPGrant, grant_id).revoked
        for token in (tokens["access_token"], rotated["access_token"]):
            with pytest.raises(HTTPException) as error:
                oauth.verify_bearer_in_session(session, token)
            assert error.value.status_code == 401
