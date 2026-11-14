"""Synthetic only. SQLite verifies logic, NOT PostgreSQL distributed locking."""
import asyncio
import os
import subprocess
import sys
import uuid
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai import (AIBlocked, AIPolicy, AIRun, Aggregate, Base, ChatRequest, Finding,
                    ToolRequest, cost, create_router, enqueue_report, execute_chat,
                    litellm_provider, operator_environment, provision_from_environment,
                    reserve, run_graph, schedule_reports, settle)
from app.jobs import (Claim, Job, JobAttempt, JobDeferred, StableWatcher, claim,
                      defer, enqueue, finish, heartbeat, run_worker)
from app.notifications import (MESSAGE, Notification, NotificationSettings,
                               DeliveryRetryable, is_quiet, next_allowed, ntfy_url,
                               queue_notification, schedule_reminders, send_notification)
from app.models import Account, Import, Setting, Transaction, User

NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
REQUEST = ChatRequest(start=date(2026, 10, 1), end=date(2026, 10, 31))


@pytest.fixture(autouse=True)
def isolated_operator_environment(monkeypatch):
    # Tests must not inherit a developer's real operator credentials/configuration.
    for name in list(os.environ):
        if name.startswith(("AI_", "NTFY_")) or name == "FINSIGHT_NTFY_TOKEN":
            monkeypatch.delenv(name)


def configure_operator(monkeypatch, **overrides):
    values = {"AI_ENABLED": "true", "AI_EXTERNAL_CONSENT": "true", "AI_PROACTIVE_ENABLED": "false",
              "AI_PROVIDER_BASE_URL": "https://provider.invalid/v1", "AI_API_KEY": "synthetic-provider-secret",
              "AI_MODEL": "synthetic/model", "AI_MODEL_ALLOWLIST": "synthetic/model,other/unpriced",
              "AI_INPUT_EUR_PER_MILLION": "1", "AI_OUTPUT_EUR_PER_MILLION": "2",
              "AI_MONTHLY_BUDGET_EUR": "1", "AI_TOTAL_BUDGET_EUR": "2", "AI_CHAT_BUDGET_EUR": "0.6",
              "AI_SCHEDULED_BUDGET_EUR": "0.4", "AI_MAX_RUN_COST_EUR": "0.1",
              "AI_MAX_INPUT_TOKENS": "4096", "AI_MAX_OUTPUT_TOKENS": "512",
              "AI_MAX_AGENT_STEPS": "3", "AI_MAX_TOOL_CALLS": "1", "AI_MAX_RUNTIME_SECONDS": "2",
              "AI_MAX_CONCURRENT_RUNS": "1", "AI_RETRY_LIMIT": "0"}
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add(User(id="owner", email="owner@synthetic.invalid", password_hash="synthetic-not-a-password-hash"))
        session.commit()
    yield factory
    engine.dispose()


def policy(session, **kwargs):
    values = dict(owner_id="owner", enabled=True, external_consent=True, proactive_consent=False,
                  model="synthetic/model", prices={"synthetic/model": {"input": "1", "output": "2", "currency": "EUR", "verified": True}},
                  total_limit=Decimal("1"), monthly_limit=Decimal("1"), run_limit=Decimal("0.1"),
                  channel_limits={"chat": "1", "weekly": "1"}, max_concurrent=2,
                  max_input_tokens=4096, max_output_tokens=512, max_steps=3, max_tools=1, timeout_seconds=2)
    values.update(kwargs)
    row = AIPolicy(**values)
    session.add(row)
    session.commit()
    return row


def settings(session, **kwargs):
    values = dict(owner_id="owner", enabled=True, server="https://ntfy.invalid", topic="synthetic",
                  timezone="Europe/Berlin", quiet_start=22 * 60, quiet_end=8 * 60,
                  stale_after_hours=168, last_import_at=NOW, events=["weekly", "monthly", "report_ready"],
                  reminder_hour=9, weekly_day=0)
    values.update(kwargs)
    row = NotificationSettings(**values)
    session.add(row)
    session.commit()
    return row


async def query(owner_id, request):
    assert owner_id == "owner"
    assert isinstance(request, ToolRequest)
    return [Aggregate(metric="income", value="100.25", currency="EUR")]


async def provider(model, messages, max_tokens, timeout):
    assert model == "synthetic/model"
    assert max_tokens == 512
    assert "100.25" in messages[1]["content"]
    return "Synthetic aggregate summary; coverage is incomplete.", {"prompt_tokens": 120, "completion_tokens": 20}


def test_disabled_by_default(factory):
    with factory() as session:
        with pytest.raises(AIBlocked, match="external_ai_disabled"):
            reserve(session, "owner")
        session.add(AIPolicy(owner_id="owner"))
        session.commit()
        with pytest.raises(AIBlocked, match="external_ai_disabled"):
            reserve(session, "owner")


@pytest.mark.parametrize("overrides,reason", [
    ({"external_consent": False}, "external_ai_disabled"),
    ({"model": "not-allowed"}, "model_not_allowlisted"),
    ({"prices": {"synthetic/model": {"verified": False}}}, "unverified_pricing"),
    ({"prices": {"synthetic/model": {"input": 0.5, "output": "1", "verified": True, "currency": "EUR"}}}, "invalid_pricing"),
    ({"prices": {"synthetic/model": {"input": "1", "output": "2", "verified": True, "currency": "USD"}}}, "unverified_pricing"),
    ({"budget_currency": "USD"}, "legacy_currency_reconciliation_required"),
    ({"run_limit": Decimal("0")}, "run_budget"),
    ({"total_limit": Decimal("0")}, "budget_exhausted"),
    ({"monthly_limit": Decimal("0")}, "budget_exhausted"),
    ({"channel_limits": {}}, "channel_budget"),
    ({"max_steps": 2}, "invalid_runtime"),
    ({"max_concurrent": 9}, "invalid_runtime"),
])
def test_reservation_fail_closed(factory, overrides, reason):
    with factory() as session:
        policy(session, **overrides)
        with pytest.raises(AIBlocked, match=reason):
            reserve(session, "owner", now=NOW)


def test_decimal_reservation_and_settlement(factory):
    with factory() as session:
        policy(session)
        run, config = reserve(session, "owner", now=NOW)
        assert run.reserved == Decimal("0.00512000")
        session.commit()
        assert settle(session, run.id, "owner", {"prompt_tokens": 100, "completion_tokens": 20}, config)
        session.commit()
        assert session.get(AIRun, run.id).charged == Decimal("0.00014000")
        with pytest.raises(AIBlocked, match="run_not_reservable"):
            settle(session, run.id, "owner", {"prompt_tokens": 1, "completion_tokens": 1}, config)


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": True, "completion_tokens": 1},
                                  {"prompt_tokens": 0, "completion_tokens": 1},
                                  {"prompt_tokens": 4097, "completion_tokens": 1},
                                  {"prompt_tokens": 1, "completion_tokens": 513}])
def test_missing_or_excess_usage_retains_reservation(factory, usage):
    with factory() as session:
        policy(session, max_concurrent=1)
        run, config = reserve(session, "owner", now=NOW)
        session.commit()
        assert not settle(session, run.id, "owner", usage, config)
        session.commit()
        assert session.get(AIRun, run.id).reserved == Decimal("0.00512000")
        assert session.get(AIRun, run.id).state == "uncertain"
        with pytest.raises(AIBlocked, match="concurrency_exhausted"):
            reserve(session, "owner", now=NOW)


def test_monthly_cap_and_carry_forward(factory):
    with factory() as session:
        policy(session, monthly_limit=Decimal("0.006"), max_concurrent=8)
        reserve(session, "owner", now=NOW.replace(month=10))
        session.commit()
        with pytest.raises(AIBlocked, match="budget_exhausted"):
            reserve(session, "owner", now=NOW)


def test_proactive_requires_separate_consent(factory):
    with factory() as session:
        row = policy(session)
        with pytest.raises(AIBlocked, match="proactive_disabled"):
            enqueue_report(session, "owner", REQUEST, "weekly", "synthetic-week")
        row.proactive_consent = True
        session.commit()
        job = enqueue_report(session, "owner", REQUEST, "weekly", "synthetic-week")
        session.commit()
        assert job.kind == "ai_report" and not job.replay_safe and job.max_attempts == 1
        assert enqueue_report(session, "owner", REQUEST, "weekly", "synthetic-week").id == job.id


def test_typed_tool_rejects_sql_and_raw_values():
    with pytest.raises(ValidationError):
        ToolRequest(tool="sql", start=REQUEST.start, end=REQUEST.end)
    with pytest.raises(ValidationError):
        Aggregate(metric="income", value="100", currency="EUR", iban="synthetic-private")
    with pytest.raises(ValidationError):
        ChatRequest(start=REQUEST.start, end=REQUEST.end, prompt="Do arbitrary SQL")


def test_real_langgraph_and_structured_finding(factory):
    with factory() as session:
        policy(session)
        result = asyncio.run(execute_chat(session, "owner", REQUEST, query, provider=provider))
        run = session.get(AIRun, result["run_id"])
        assert run.state == "settled"
        finding = session.scalar(select(Finding))
        assert finding.user_id == "owner" and finding.kind == "ai"
        assert finding.evidence[0]["query"]["tool"] == "cashflow"
        assert finding.evidence[0]["run_id"] == run.id


def test_graph_failure_keeps_durable_reservation_and_no_retry(factory):
    calls = []
    async def broken(*args):
        calls.append(1)
        raise RuntimeError("synthetic-private-provider-error")
    with factory() as session:
        policy(session)
        with pytest.raises(RuntimeError):
            asyncio.run(execute_chat(session, "owner", REQUEST, query, provider=broken))
        assert len(calls) == 1
        run = session.scalar(select(AIRun))
        assert run.state == "uncertain" and run.error_code == "execution_failed"
        assert session.scalar(select(Finding)) is None


def test_graph_timeout_no_retry(factory):
    async def slow(*args):
        await asyncio.sleep(2)
    with factory() as session:
        policy(session, timeout_seconds=1)
        with pytest.raises(TimeoutError):
            asyncio.run(execute_chat(session, "owner", REQUEST, query, provider=slow))
        assert session.scalar(select(AIRun)).state == "uncertain"


def test_graph_step_input_and_tool_limits(factory):
    with factory() as session:
        policy(session)
        run, config = reserve(session, "owner")
        config["max_steps"] = 2
        with pytest.raises(AIBlocked, match="step_limit"):
            asyncio.run(run_graph(REQUEST, "owner", run.model, config, query, provider))
        config["max_steps"], config["max_tools"] = 3, 0
        with pytest.raises(AIBlocked, match="tool_limit"):
            asyncio.run(run_graph(REQUEST, "owner", run.model, config, query, provider))
        config["max_tools"], config["max_input_tokens"] = 1, 128
        with pytest.raises(AIBlocked, match="input_token_limit"):
            asyncio.run(run_graph(REQUEST, "owner", run.model, config, query, provider))


def test_invalid_date_range_never_reserves(factory):
    with factory() as session:
        policy(session)
        invalid = ChatRequest(start=date(2020, 1, 1), end=date(2026, 1, 1))
        with pytest.raises(AIBlocked, match="invalid_date_range"):
            asyncio.run(execute_chat(session, "owner", invalid, query, provider=provider))
        assert session.scalar(select(AIRun)) is None


def test_api_owner_isolation(factory):
    def get_session():
        with factory() as session:
            yield session
    with factory() as session:
        policy(session)
        run, _ = reserve(session, "owner")
        session.add(Finding(user_id="owner", title="Synthetic", body="Synthetic evidence", evidence=[]))
        session.commit()
    app = FastAPI()
    app.include_router(create_router(get_session, lambda: "other", query))
    with TestClient(app) as client:
        assert client.get("/ai/usage").json()["runs"] == []
        assert client.get("/findings").json() == []
        assert client.post("/ai/chat", json=REQUEST.model_dump(mode="json")).status_code == 409


def test_default_routers_require_real_authentication(factory):
    from app.db import get_db
    from app.main import app
    def get_session():
        with factory() as session:
            yield session
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = get_session
    try:
        with TestClient(app) as client:
            for path in ("/api/ai/settings", "/api/ai/usage", "/api/notifications", "/api/notifications/settings"):
                assert client.get(path).status_code == 401
            assert client.post("/api/ai/chat", json=REQUEST.model_dump(mode="json")).status_code == 401
            assert client.post("/api/ai/consent", json={"enabled": True, "external_consent": True}).status_code == 401
            assert client.post("/api/notifications/consent", json={"enabled": True, "events": []}).status_code == 401
            assert client.post("/api/notifications/test").status_code == 401
    finally:
        app.dependency_overrides = previous


def test_queue_claim_lease_reclaim_and_fencing(factory):
    with factory() as session:
        job = enqueue(session, "owner", "synthetic", {}, replay_safe=True)
        session.commit()
        first = claim(session, {"synthetic"}, now=NOW + timedelta(days=1000))
        session.commit()
        assert first.id == job.id
        assert claim(session, {"synthetic"}, now=NOW + timedelta(days=1000, seconds=1)) is None
        second = claim(session, {"synthetic"}, now=NOW + timedelta(days=1000, seconds=91))
        session.commit()
        assert second.token != first.token
        assert not finish(session, first, success=True, now=NOW + timedelta(days=1000, seconds=92))
        assert finish(session, second, success=True, now=NOW + timedelta(days=1000, seconds=92))
        session.commit()
        assert session.get(Job, job.id).state == "succeeded"
        assert [r.outcome for r in session.scalars(select(JobAttempt).order_by(JobAttempt.started_at))] == ["lease_expired", "succeeded"]


def test_non_replayable_expired_job_is_uncertain(factory):
    with factory() as session:
        job = enqueue(session, "owner", "ai_report", {}, available_at=NOW)
        session.commit()
        first = claim(session, {"ai_report"}, now=NOW)
        session.commit()
        assert claim(session, {"ai_report"}, now=NOW + timedelta(seconds=91)) is None
        session.commit()
        assert session.get(Job, job.id).state == "uncertain"
        assert not heartbeat(session, first, now=NOW + timedelta(seconds=92))


def test_retry_backoff_dedupe_heartbeat_and_deferral(factory):
    with factory() as session:
        job = enqueue(session, "owner", "synthetic", {}, available_at=NOW, dedupe_key="same", replay_safe=True)
        session.commit()
        assert enqueue(session, "owner", "synthetic", {}, dedupe_key="same").id == job.id
        first = claim(session, {"synthetic"}, now=NOW)
        session.commit()
        assert heartbeat(session, first, now=NOW + timedelta(seconds=1))
        assert finish(session, first, success=False, retryable=True, now=NOW + timedelta(seconds=2))
        session.commit()
        assert claim(session, {"synthetic"}, now=NOW + timedelta(seconds=3)) is None
        second = claim(session, {"synthetic"}, now=NOW + timedelta(seconds=20))
        assert defer(session, second, NOW + timedelta(hours=1), now=NOW + timedelta(seconds=21))
        session.commit()
        assert session.get(Job, job.id).attempts == 1
        assert claim(session, {"synthetic"}, now=NOW + timedelta(minutes=30)) is None


def test_worker_runs_registered_handler(factory):
    with factory() as session:
        job = enqueue(session, "owner", "synthetic", {}, replay_safe=True)
        session.commit()
        job_id = job.id
    async def scenario():
        stop = asyncio.Event()
        async def handler(item):
            assert item.owner_id == "owner"
            stop.set()
        await run_worker(factory, {"synthetic": handler}, stop=stop)
    asyncio.run(scenario())
    with factory() as session:
        assert session.get(Job, job_id).state == "succeeded"


def test_watcher_stability_digest_dedupe_no_delete(factory, tmp_path):
    path = tmp_path / "synthetic.xlsx"
    path.write_bytes(b"not a workbook: synthetic watcher-only fixture")
    (tmp_path / "ignored.txt").write_text("synthetic")
    (tmp_path / "link.xlsx").symlink_to(path)
    watcher = StableWatcher(tmp_path, stable_seconds=10)
    start = datetime.now(timezone.utc) + timedelta(seconds=1)
    with factory() as session:
        assert watcher.poll(session, "owner", now=start) == 0
        assert watcher.poll(session, "owner", now=start + timedelta(seconds=11)) == 1
        session.commit()
        assert watcher.poll(session, "owner", now=start + timedelta(seconds=22)) == 0
        assert path.exists()
        job = session.scalar(select(Job))
        assert job.payload["filename"] == "synthetic.xlsx" and len(job.payload["sha256"]) == 64
        path.write_bytes(b"changed synthetic bytes")
        assert watcher.poll(session, "owner", now=start + timedelta(seconds=23)) == 0
        assert watcher.poll(session, "owner", now=start + timedelta(seconds=34)) == 1


def test_quiet_hours_local_dst_and_daytime(factory):
    with factory() as session:
        row = settings(session)
        assert is_quiet(row, datetime(2026, 11, 14, 21, tzinfo=timezone.utc))
        assert not is_quiet(row, NOW)
        assert next_allowed(row, datetime(2026, 11, 14, 21, tzinfo=timezone.utc)) == datetime(2026, 11, 15, 7, tzinfo=timezone.utc)
        # Spring-forward: 22:00 CET -> 08:00 CEST must be 06:00 UTC.
        assert next_allowed(row, datetime(2026, 3, 28, 22, tzinfo=timezone.utc)) == datetime(2026, 3, 29, 6, tzinfo=timezone.utc)
        # Fall-back: repeated local 02:00 never produces an invalid interval.
        assert next_allowed(row, datetime(2026, 10, 24, 22, tzinfo=timezone.utc)) == datetime(2026, 10, 25, 7, tzinfo=timezone.utc)
        row.quiet_start, row.quiet_end = 12 * 60, 14 * 60
        assert is_quiet(row, NOW)
        row.quiet_end = row.quiet_start
        assert not is_quiet(row, NOW)


def test_stale_disabled_suppression_and_test_exception(factory):
    with factory() as session:
        row = settings(session, last_import_at=NOW - timedelta(days=8))
        stale = queue_notification(session, "owner", "weekly", "week-1", NOW)
        assert stale.state == "suppressed" and stale.reason == "stale_import"
        test = queue_notification(session, "owner", "test", "test-1", NOW)
        assert test.state == "queued"
        assert queue_notification(session, "owner", "test", "test-1", NOW).id == test.id
        row.enabled = False
        session.commit()
        disabled = queue_notification(session, "owner", "test", "test-2", NOW)
        assert disabled.state == "suppressed" and disabled.reason == "disabled"


def test_schedule_weekly_monthly_local_dedupe(factory):
    first = datetime(2026, 6, 1, 9, tzinfo=timezone.utc)  # Monday and first of month.
    with factory() as session:
        settings(session, last_import_at=first)
        one = schedule_reminders(session, "owner", first)
        session.commit()
        two = schedule_reminders(session, "owner", first + timedelta(minutes=1))
        assert len(one) == 2 and one == two
        assert len(list(session.scalars(select(Notification)))) == 2


def notification_claim(session, now=NOW):
    notification = queue_notification(session, "owner", "report_ready", "synthetic-report", now)
    session.commit()
    item = claim(session, {"notify"}, now=now)
    session.commit()
    return notification.id, item


def test_ntfy_generic_authenticated_history_and_idempotence(factory):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"id": "synthetic"})
    with factory() as session:
        settings(session)
        row_id, item = notification_claim(session)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await send_notification(factory, item, auth_token="synthetic-secret", client=client, now=NOW)
            await send_notification(factory, item, auth_token="synthetic-secret", client=client, now=NOW)
    asyncio.run(scenario())
    assert len(requests) == 1 and requests[0].content.decode() == MESSAGE
    assert requests[0].headers["authorization"] == "Bearer synthetic-secret"
    with factory() as session:
        row = session.get(Notification, row_id)
        assert row.state == "sent" and row.attempts == 1


@pytest.mark.parametrize("status,state,raises", [(429, "failed", True), (503, "uncertain", False), (401, "suppressed", False)])
def test_ntfy_failure_history_and_retries(factory, status, state, raises):
    with factory() as session:
        settings(session)
        row_id, item = notification_claim(session)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status))) as client:
            if raises:
                with pytest.raises(DeliveryRetryable):
                    await send_notification(factory, item, client=client, now=NOW)
            else:
                await send_notification(factory, item, client=client, now=NOW)
    asyncio.run(scenario())
    with factory() as session:
        assert session.get(Notification, row_id).state == state


def test_ntfy_timeout_and_crash_are_not_resent(factory):
    calls = []
    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("synthetic-private-response")
    with factory() as session:
        settings(session)
        row_id, item = notification_claim(session)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await send_notification(factory, item, client=client, now=NOW)
            await send_notification(factory, item, client=client, now=NOW)
    asyncio.run(scenario())
    assert len(calls) == 1
    with factory() as session:
        row = session.get(Notification, row_id)
        assert row.state == "uncertain" and row.reason == "delivery_unconfirmed"


def test_delivery_rechecks_stale_import(factory):
    with factory() as session:
        row = settings(session)
        row_id, item = notification_claim(session)
        row.last_import_at = NOW - timedelta(days=10)
        session.commit()
    asyncio.run(send_notification(factory, item, now=NOW))
    with factory() as session:
        assert session.get(Notification, row_id).reason == "stale_import"


def test_ntfy_url_no_credentials_redirect_or_topic_injection(factory):
    with factory() as session:
        row = settings(session)
        assert ntfy_url(row) == "https://ntfy.invalid/synthetic"
        row.server = "https://secret@ntfy.invalid"
        with pytest.raises(ValueError):
            ntfy_url(row)
        row.server, row.topic = "https://ntfy.invalid", "../private"
        with pytest.raises(ValueError):
            ntfy_url(row)


def test_ai_settings_require_operator_prices_and_decimal_strings(factory):
    def get_session():
        with factory() as session:
            yield session
    app = FastAPI()
    app.include_router(create_router(get_session, lambda: "owner", query))
    payload = {"enabled": True, "external_consent": True, "proactive_consent": False,
               "model": "synthetic/model", "total_limit": "1", "monthly_limit": "1",
               "run_limit": "0.01", "channel_limits": {"chat": "1"}}
    with TestClient(app) as client:
        assert client.get("/ai/settings").json()["enabled"] is False
        assert client.patch("/ai/settings", json=payload).status_code == 409
        with factory() as session:
            policy(session, enabled=False, external_consent=False)
        assert client.patch("/ai/settings", json=payload).status_code == 200
        assert client.get("/ai/settings").json()["enabled"] is True
        payload["total_limit"] = 1.5
        assert client.patch("/ai/settings", json=payload).status_code == 422


def test_proactive_schedule_freshness_and_channel_opt_in(factory):
    now = datetime(2026, 6, 1, 9, tzinfo=timezone.utc)
    with factory() as session:
        policy(session, proactive_consent=True, channel_limits={"weekly": "1", "monthly": "1", "changed_import": "1"})
        ids = schedule_reports(session, "owner", "synthetic-import", now, now=now, latest_import_summary={"added": 1, "changed": 0})
        session.commit()
        assert len(ids) == 3
        assert schedule_reports(session, "owner", "synthetic-import", now, now=now, latest_import_summary={"added": 1, "changed": 0}) == ids
        assert schedule_reports(session, "owner", "stale-import", now - timedelta(days=8), now=now) == []
        assert all(not row.replay_safe for row in session.scalars(select(Job)))


def test_finance_adapter_minimizes_labels(factory, monkeypatch):
    from app import ai, db, finance
    monkeypatch.setattr(db, "SessionLocal", factory)
    def overview(session, owner, start, end):
        assert owner == "owner"
        return {"currencies": [{"currency": "EUR", "income": "100.25", "expenses": "20", "surplus": "80.25"}],
                "categories": [{"category": "synthetic-private-label", "amount": "20"}]}
    monkeypatch.setattr(finance, "overview", overview)
    result = asyncio.run(ai.finance_query("owner", ToolRequest(tool="categories", start=REQUEST.start, end=REQUEST.end)))
    assert [r.model_dump() for r in result] == [{"metric": "expense", "value": "20", "currency": "EUR"}]


def test_quiet_window_change_defers_without_sending(factory):
    with factory() as session:
        row = settings(session)
        row_id, item = notification_claim(session)
        row.quiet_start, row.quiet_end = 12 * 60, 14 * 60
        session.commit()
    with pytest.raises(JobDeferred) as exc:
        asyncio.run(send_notification(factory, item, now=NOW))
    assert exc.value.until == NOW + timedelta(hours=1)
    with factory() as session:
        assert session.get(Notification, row_id).attempts == 0


def test_notification_settings_explicit_opt_in(factory):
    from app.notifications import create_router as notification_router
    def get_session():
        with factory() as session:
            yield session
    app = FastAPI()
    app.include_router(notification_router(get_session, lambda: "owner"))
    with factory() as session:
        settings(session, enabled=False)
    payload = {"enabled": True, "events": ["weekly"], "timezone": "Europe/Berlin"}
    with TestClient(app) as client:
        assert client.get("/notifications/settings").json()["enabled"] is False
        assert client.patch("/notifications/settings", json=payload).status_code == 200
        assert client.get("/notifications/settings").json()["enabled"] is True
        payload["timezone"] = "invalid/zone"
        assert client.patch("/notifications/settings", json=payload).status_code == 409


def test_worker_module_entrypoint_constructs_factory_without_duplicate_metadata():
    # Construct the shipped factory without entering its event loop or touching DB,
    # files, networks or real imports. In particular test the -m canonical alias.
    code = """import asyncio, runpy, sys
asyncio.run = lambda coroutine: coroutine.close()
sys.argv = ['app.jobs']
runpy.run_module('app.jobs', run_name='__main__', alter_sys=True)
"""
    env = {**os.environ, "FINSIGHT_WATCH_IMPORTS": "false", "FINSIGHT_WORKER_FACTORY": "app.jobs:default_worker_factory",
           "FINSIGHT_DATABASE_URL": "postgresql+psycopg://synthetic@127.0.0.1:1/synthetic"}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("failure", ["input", "aggregate", "currency", "tool_rows"])
def test_proven_pre_provider_failures_release_budget_and_slot(factory, failure):
    calls = []
    async def spy(*args):
        calls.append(1)
        return await provider(*args)
    async def invalid_query(owner, request):
        if failure == "aggregate":
            return [{"metric": "private-merchant", "value": "1", "currency": "EUR"}]
        if failure == "currency":
            return [Aggregate(metric="income", value="1", currency="USD")]
        if failure == "tool_rows":
            return [Aggregate(metric="income", value="1", currency="EUR")] * 25
        return await query(owner, request)
    with factory() as session:
        row = policy(session, max_concurrent=1, max_input_tokens=128 if failure == "input" else 4096,
                     total_limit=Decimal("0.00512"), monthly_limit=Decimal("0.00512"))
        with pytest.raises((AIBlocked, ValidationError)):
            asyncio.run(execute_chat(session, "owner", REQUEST, invalid_query, provider=spy))
        run = session.scalar(select(AIRun))
        assert calls == [] and run.state == "released" and run.charged == Decimal(0)
        assert run.error_code == "pre_provider_failure" and run.reserved > 0
        row.max_input_tokens = 4096
        session.commit()
        # Same total/month budget and concurrency=1 must immediately be usable.
        result = asyncio.run(execute_chat(session, "owner", REQUEST, query, provider=spy))
        assert calls == [1] and session.get(AIRun, result["run_id"]).state == "settled"


@pytest.mark.parametrize("cancel_at", ["query", "provider"])
def test_cancellation_tracks_the_transmission_boundary(factory, cancel_at):
    async def scenario(session):
        entered = asyncio.Event()
        async def pending_query(*args):
            entered.set()
            await asyncio.sleep(10)
        async def pending_provider(*args):
            entered.set()
            await asyncio.sleep(10)
        task = asyncio.create_task(execute_chat(session, "owner", REQUEST,
            pending_query if cancel_at == "query" else query,
            provider=pending_provider if cancel_at == "provider" else provider))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    with factory() as session:
        policy(session, max_concurrent=1)
        asyncio.run(scenario(session))
        run = session.scalar(select(AIRun))
        assert run.state == ("released" if cancel_at == "query" else "uncertain")
        assert (run.charged == 0) if cancel_at == "query" else run.charged is None


def test_litellm_uses_documented_base_url_and_key_without_network(monkeypatch):
    configure_operator(monkeypatch)
    calls, boundaries = [], []
    async def completion(**kwargs):
        calls.append(kwargs)
        assert boundaries == ["transmit"]
        return SimpleNamespace(usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 10, "completion_tokens": 2}),
                               choices=[SimpleNamespace(message=SimpleNamespace(content="synthetic summary"))])
    fake = SimpleNamespace(acompletion=completion)
    monkeypatch.setitem(sys.modules, "litellm", fake)
    result = asyncio.run(litellm_provider("synthetic/model", [{"role": "user", "content": "synthetic aggregate"}], 512, 2,
                                         on_transmit=lambda: boundaries.append("transmit")))
    assert result[0] == "synthetic summary"
    assert calls[0]["api_base"] == "https://provider.invalid/v1"
    assert calls[0]["api_key"] == "synthetic-provider-secret"
    assert calls[0]["num_retries"] == 0 and calls[0]["stream"] is False
    assert fake.telemetry is False


@pytest.mark.parametrize("overrides,reason", [
    ({"AI_ENABLED": "false"}, "operator_external_ai_disabled"),
    ({"AI_EXTERNAL_CONSENT": "false"}, "operator_external_ai_disabled"),
    ({"AI_API_KEY": ""}, "provider_credentials_not_configured"),
    ({"AI_PROVIDER_BASE_URL": "https://secret@provider.invalid/v1"}, "provider_credentials_not_configured"),
    ({"AI_MODEL_ALLOWLIST": "synthetic/model-prefix"}, "model_not_allowlisted"),
    ({"AI_RETRY_LIMIT": "1"}, "provider_retries_unsupported"),
    ({"AI_INPUT_EUR_PER_MILLION": ""}, "invalid_pricing_or_budget"),
    ({"AI_MAX_TOOL_CALLS": "21"}, "invalid_runtime_environment"),
])
def test_environment_preflight_fails_before_reservation(factory, monkeypatch, overrides, reason):
    configure_operator(monkeypatch, **overrides)
    with factory() as session:
        with pytest.raises(AIBlocked, match=reason):
            provision_from_environment(session, "owner", enabled=True, external_consent=True, proactive_consent=False)
        assert session.scalar(select(AIRun)) is None and session.get(AIPolicy, "owner") is None


def test_environment_consent_is_usable_secret_free_and_applies_all_limits(factory, monkeypatch):
    configure_operator(monkeypatch, AI_MAX_TOOL_CALLS="20", AI_MAX_AGENT_STEPS="8", AI_MAX_INPUT_TOKENS="8000",
                       AI_MAX_OUTPUT_TOKENS="2000", AI_MAX_RUNTIME_SECONDS="90", AI_MAX_CONCURRENT_RUNS="2")
    def get_session():
        with factory() as session:
            yield session
    app = FastAPI()
    app.include_router(create_router(get_session, lambda: "owner", query))
    with TestClient(app) as client:
        assert client.get("/ai/settings").json()["configured"] is False  # Env alone is not consent.
        response = client.post("/ai/consent", json={"enabled": True, "external_consent": True})
        assert response.status_code == 200 and response.json()["budget_currency"] == "EUR"
        info = client.get("/ai/settings").json()
        assert info["budget_currency"] == "EUR" and info["models"] == ["synthetic/model"]
        assert info["runtime_limits"] == {"max_input_tokens": 8000, "max_output_tokens": 2000, "max_steps": 8,
                                          "max_tools": 20, "timeout_seconds": 90, "max_concurrent": 2}
        assert "synthetic-provider-secret" not in str(info) and "provider.invalid" not in str(info)
        assert client.get("/ai/usage").json()["currency"] == "EUR"
        monkeypatch.setenv("AI_API_KEY", "")  # Revocation works after operator removal.
        assert client.post("/ai/consent", json={"enabled": False, "external_consent": False}).status_code == 200
        assert client.get("/ai/settings").json()["enabled"] is False


def test_operator_ceilings_override_more_permissive_persisted_policy(factory, monkeypatch):
    configure_operator(monkeypatch, AI_MAX_INPUT_TOKENS="1024", AI_MAX_OUTPUT_TOKENS="256", AI_MAX_CONCURRENT_RUNS="1",
                       AI_MONTHLY_BUDGET_EUR="0.002", AI_CHAT_BUDGET_EUR="0.002")
    operator = operator_environment()
    with factory() as session:
        policy(session, max_concurrent=8)
        run, config = reserve(session, "owner", operator=operator)
        session.commit()
        assert config["max_input_tokens"] == 1024 and config["max_output_tokens"] == 256
        assert run.reserved == Decimal("0.001536")
        with pytest.raises(AIBlocked, match="concurrency_exhausted"):
            reserve(session, "owner", operator=operator)
        assert settle(session, run.id, "owner", {"prompt_tokens": 1024, "completion_tokens": 256}, config)
        session.commit()
        with pytest.raises(AIBlocked, match="budget_exhausted"):
            reserve(session, "owner", operator=operator)


def test_scheduled_channels_share_one_operator_eur_cap(factory, monkeypatch):
    configure_operator(monkeypatch, AI_PROACTIVE_ENABLED="true", AI_SCHEDULED_BUDGET_EUR="0.006")
    operator = operator_environment()
    with factory() as session:
        policy(session, proactive_consent=True, channel_limits={"weekly": "1", "monthly": "1"})
        run, config = reserve(session, "owner", "weekly", operator=operator)
        session.commit()
        assert settle(session, run.id, "owner", {"prompt_tokens": 4096, "completion_tokens": 512}, config)
        session.commit()
        with pytest.raises(AIBlocked, match="scheduled_budget_exhausted"):
            reserve(session, "owner", "monthly", operator=operator)


def test_legacy_usd_runs_are_not_silently_counted_as_eur(factory):
    with factory() as session:
        policy(session)
        run, _ = reserve(session, "owner")
        run.currency = "USD"
        session.commit()
        with pytest.raises(AIBlocked, match="legacy_currency_reconciliation_required"):
            reserve(session, "owner")
        assert session.get(AIRun, run.id).currency == "USD"


def test_schedules_use_owner_currency_and_timezone_without_notifications(factory, monkeypatch):
    from app import ai, db
    monkeypatch.setattr(db, "SessionLocal", factory)
    now = datetime(2026, 6, 1, 2, tzinfo=timezone.utc)  # Still Sunday May 31 in New York.
    with factory() as session:
        policy(session, proactive_consent=True, channel_limits={"weekly": "1", "monthly": "1", "changed_import": "1"})
        session.add(Setting(user_id="owner", data={"currency": "USD", "timezone": "America/New_York"}))
        account = Account(id="synthetic-usd-account", user_id="owner", source_key="synthetic-usd", name="Synthetic", currency="USD", ownership="owned")
        imported = Import(id="synthetic-import", user_id="owner", filename="synthetic.xlsx", sha256="a" * 64,
                          status="completed", summary={"added": 1, "changed": 0}, created_at=now)
        session.add_all([account, imported])
        session.flush()
        session.add(Transaction(user_id="owner", account_id=account.id, import_id=imported.id, source_key="synthetic-booking",
                                booking_date=date(2026, 5, 25), amount=Decimal("100.25"), currency="USD"))
        session.commit()
        ids = schedule_reports(session, "owner", "synthetic-import", now, now=now, latest_import_summary={"changed": 1, "added": 0})
        session.commit()
        assert len(ids) == 1
        job = session.get(Job, ids[0])
        assert job.payload["channel"] == "changed_import"
        assert job.payload["request"]["currency"] == "USD" and job.payload["request"]["end"] == "2026-05-31"
        assert session.get(NotificationSettings, "owner") is None
        results = ai._finance_query_sync("owner", ToolRequest(tool="cashflow", start=date(2026, 5, 1), end=date(2026, 5, 31), currency="USD"))
        assert all(row.currency == "USD" for row in results)
        assert next(row.value for row in results if row.metric == "income") == "100.25"


@pytest.mark.parametrize("summary", [{"added": 0, "changed": 0}, {"added": "1"}, {}, None])
def test_unchanged_import_never_queues_changed_import_report(factory, summary):
    with factory() as session:
        policy(session, proactive_consent=True, channel_limits={"changed_import": "1"})
        assert schedule_reports(session, "owner", "unchanged", NOW, now=NOW, latest_import_summary=summary) == []
        assert session.scalar(select(Job)) is None


def test_notification_provision_and_documented_access_token(factory, monkeypatch):
    from app.notifications import create_router as notification_router, notification_handler
    env = {"NTFY_ENABLED": "true", "NTFY_SERVER_URL": "https://ntfy.invalid", "NTFY_TOPIC": "synthetic-env-topic",
           "NTFY_ACCESS_TOKEN": "synthetic-ntfy-secret", "NTFY_REMINDER_DAYS": "14", "NTFY_REMINDER_TIME": "09:30",
           "NTFY_QUIET_START": "23:15", "NTFY_QUIET_END": "07:45"}
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    def get_session():
        with factory() as session:
            yield session
    app = FastAPI()
    app.include_router(notification_router(get_session, lambda: "owner"))
    with TestClient(app) as client:
        response = client.post("/notifications/consent", json={"enabled": True, "events": ["report_ready"]})
        assert response.status_code == 200
        info = client.get("/notifications/settings").json()
        assert info["reminder_hour"] == 9 and info["reminder_minute"] == 30
        assert info["stale_after_hours"] == 336 and info["quiet_start"] == 1395 and info["quiet_end"] == 465
        assert "synthetic-ntfy-secret" not in str(info)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200)
    with factory() as session:
        row = session.get(NotificationSettings, "owner")
        row.last_import_at = NOW
        session.commit()
        row_id, item = notification_claim(session)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            # No auth_token argument: documented NTFY_ACCESS_TOKEN is consumed.
            await send_notification(factory, item, client=client, now=NOW)
    asyncio.run(scenario())
    assert str(requests[0].url) == "https://ntfy.invalid/synthetic-env-topic"
    assert requests[0].headers["authorization"] == "Bearer synthetic-ntfy-secret"


def test_default_notification_worker_uses_documented_secret(factory, monkeypatch):
    from app import notifications
    monkeypatch.setenv("NTFY_ENABLED", "true")
    monkeypatch.setenv("NTFY_ACCESS_TOKEN", "synthetic-worker-secret")
    calls = []
    async def spy(session_factory, item, *, auth_token):
        calls.append(auth_token)
    monkeypatch.setattr(notifications, "send_notification", spy)
    item = Claim("synthetic-job", "owner", "notify", {"notification_id": "synthetic-notification"}, "synthetic-token")
    asyncio.run(notifications.notification_handler(factory)(item))
    assert calls == ["synthetic-worker-secret"]
    asyncio.run(notifications.notification_handler(factory, lambda owner: None)(item))
    assert calls[-1] == ""  # No cross-owner fallback to process secret.


def test_default_notification_worker_honors_operator_kill_switch(factory, monkeypatch):
    from app import notifications
    calls = []
    async def spy(*args, **kwargs):
        calls.append(1)
    monkeypatch.setattr(notifications, "send_notification", spy)
    with factory() as session:
        settings(session)
        row_id, item = notification_claim(session)
    asyncio.run(notifications.notification_handler(factory)(item))  # NTFY_ENABLED defaults false.
    with factory() as session:
        row = session.get(Notification, row_id)
        assert row.state == "suppressed" and row.reason == "operator_disabled"
        assert row.attempts == 0 and calls == []


@pytest.mark.skipif(not os.environ.get("FINSIGHT_TEST_POSTGRES_URL"), reason="requires explicit isolated PostgreSQL test URL")
def test_postgresql_concurrent_reservation_and_skip_locked():
    """Random synthetic schema, dropped afterwards; never use a production DB URL."""
    from sqlalchemy import text
    url = os.environ["FINSIGHT_TEST_POSTGRES_URL"]
    admin = create_engine(url)
    schema = "synthetic_ai_" + uuid.uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    sessions = sessionmaker(engine, expire_on_commit=False)
    try:
        Base.metadata.create_all(engine)
        with sessions() as session:
            policy(session, max_concurrent=8, monthly_limit=Decimal("0.006"))
        barrier = Barrier(2)
        def attempt():
            with sessions() as session:
                barrier.wait(timeout=10)
                try:
                    reserve(session, "owner")
                    session.commit()
                    return "reserved"
                except AIBlocked:
                    session.rollback()
                    return "blocked"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: attempt(), range(2)))
        assert sorted(results) == ["blocked", "reserved"]
        with sessions() as session:
            enqueue(session, "owner", "synthetic", {}, replay_safe=True)
            enqueue(session, "owner", "synthetic", {}, replay_safe=True)
            session.commit()
        with sessions() as first, sessions() as second:
            first_claim = claim(first, {"synthetic"})
            second_claim = claim(second, {"synthetic"})
            assert first_claim.id != second_claim.id
            first.commit()
            second.commit()
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
