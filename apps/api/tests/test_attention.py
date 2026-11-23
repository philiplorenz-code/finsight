"""Attention list and reminder notifications, synthetic data only."""
from datetime import date

import pytest
from sqlalchemy import select

import app.attention as att
import app.contract_terms as ct
import app.finance as finance
import app.receivables as rv
from app.models import User
from app.notifications import Notification, NotificationSettings
from conftest import booking, upload


@pytest.fixture(autouse=True)
def today(monkeypatch):
    fixed = lambda db, user_id: date(2026, 11, 22)  # noqa: E731
    for module in (finance, ct, rv, att):
        monkeypatch.setattr(module, "local_today", fixed)
    att._LAST_CHECK.clear()


def seed(owner):
    rows = [booking(f"g{m}", "-30", day=f"2026-{m:02d}-05", **{"Empfänger": "Synthetic Gym", "Kategorie": "Sport"}) for m in range(5, 12)]
    assert upload(owner, rows).status_code == 200
    for a in owner.get("/api/accounts").json():
        owner.patch(f"/api/accounts/{a['id']}", json={"ownership": "owned"})
    key = next(i["key"] for i in owner.get("/api/contracts").json()["items"] if i["name"] == "Synthetic Gym")
    owner.put("/api/contract-terms", params={"key": key}, json={"term_end": "2026-12-31", "notice_days": 30, "renew_months": 12})
    owner.post("/api/open-items", json={"direction": "payable", "person": "Synthetic Person", "title": "Synthetic loan", "amount": "50",
                                         "since": "2026-10-01", "due": "2026-11-20"})


def test_attention_lists_deadline_and_overdue_item(owner):
    seed(owner)
    items = owner.get("/api/attention").json()["items"]
    kinds = [i["kind"] for i in items]
    assert kinds[0] == "deadline" and items[0]["days_left"] == 9 and "overdue" in kinds


def test_reminders_are_queued_once(owner, db):
    seed(owner)
    user_id = db.scalar(select(User.id))
    assert att.queue_reminders(db, user_id) == []  # notifications off
    db.add(NotificationSettings(owner_id=user_id, enabled=True, server="https://ntfy.example.test", topic="synthetic-topic", events=["reminder"]))
    db.commit()
    first = att.queue_reminders(db, user_id)
    att._LAST_CHECK.clear()
    second = att.queue_reminders(db, user_id)
    db.commit()
    assert len(first) == 2 and sorted(first) == sorted(second)
    keys = sorted(n.dedupe_key for n in db.scalars(select(Notification)))
    assert keys[0].startswith("deadline:") and keys[0].endswith(":14") and keys[1].startswith("open-item:")


def test_threshold_picks_the_tightest_reached():
    picks = {left: next(t for t in sorted(att.THRESHOLDS) if left <= t) for left in (13, 9, 6, 2, 0)}
    assert picks == {13: 14, 9: 14, 6: 7, 2: 2, 0: 2}


def test_budget_close_to_target_shows_early_warning(owner, db, monkeypatch):
    import app.plan as plan
    monkeypatch.setattr(plan, "local_today", lambda db, user_id: date(2026, 11, 22))
    rows = [booking("w1", "-95", day="2026-11-03", **{"Empfänger": "Synthetic Markt", "Kategorie": "Lebensmittel"})]
    assert upload(owner, rows).status_code == 200
    for a in owner.get("/api/accounts").json():
        owner.patch(f"/api/accounts/{a['id']}", json={"ownership": "owned"})
    owner.post("/api/plan-items", json={"name": "Essen", "amount": "100", "category": "Lebensmittel"})
    owner.post("/api/plan-items", json={"name": "Luxus", "amount": "1000", "category": "Hobby"})
    items = owner.get("/api/attention").json()["items"]
    warn = [i for i in items if i["kind"] == "plan_warning"]
    assert [i["title"] for i in warn] == ["Essen"] and warn[0]["remaining"] == "5"
    user_id = db.scalar(select(User.id))
    db.add(NotificationSettings(owner_id=user_id, enabled=True, server="https://ntfy.example.test", topic="synthetic-topic", events=["plan_exceeded"]))
    db.commit()
    assert len(plan.queue_plan_alerts(db, user_id)) == 1
    assert plan.queue_plan_alerts(db, user_id) == plan.queue_plan_alerts(db, user_id)
    keys = [n.dedupe_key for n in db.scalars(select(Notification))]
    assert len(keys) == 1 and keys[0].startswith("plan-warn:")
