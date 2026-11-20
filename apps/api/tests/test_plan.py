"""Plan vs. actual (SOLL/IST) and standing orders, synthetic data only."""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select

import app.plan as plan
from app.models import User
from app.notifications import Notification, NotificationSettings
from conftest import booking, upload

POT = {"Konto-ID": "synthetic-fuel-pot", "Konto": "Synthetic fuel pot"}
MAIN = {"Konto-ID": "synthetic-main", "Konto": "Synthetic main"}


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(plan, "local_today", lambda db, user_id: date(2026, 10, 15))


def seed(owner):
    rows = [
        booking("p1", "-60", day="2026-10-03", **POT, **{"Kategorie": "Tanken", "Empfänger": "Synthetic fuel"}),
        booking("p2", "-40", day="2026-10-10", **POT, **{"Kategorie": "Sonstiges", "Empfänger": "Synthetic kiosk"}),
        booking("p3", "-20", day="2026-10-11", **POT, **{"Umbuchung": "Ja", "Empfänger": "Synthetic me"}),
        booking("m1", "-50", day="2026-10-05", **MAIN, **{"Kategorie": "Tanken", "Empfänger": "Synthetic fuel"}),
        booking("m2", "-30", day="2026-10-06", **MAIN, **{"Kategorie": "Lebensmittel"}),
        booking("m3", "10", day="2026-10-07", **MAIN, **{"Kategorie": "Tanken", "Empfänger": "Synthetic refund"}),
        booking("s1", "-70", day="2026-09-12", **MAIN, **{"Kategorie": "Tanken"}),
        booking("t1", "180", day="2026-08-01", **POT, **{"Umbuchung": "Ja", "Empfänger": "Synthetic me"}),
        booking("t2", "180", day="2026-09-01", **POT, **{"Umbuchung": "Ja", "Empfänger": "Synthetic me"}),
        booking("t3", "180", day="2026-10-01", **POT, **{"Umbuchung": "Ja", "Empfänger": "Synthetic me"}),
        booking("t4", "25", day="2026-10-02", **MAIN, **{"Umbuchung": "Ja", "Empfänger": "Synthetic me"}),
    ]
    assert upload(owner, rows).status_code == 200
    accounts = {a["name"]: a for a in owner.get("/api/accounts").json()}
    for a in accounts.values():
        assert owner.patch(f"/api/accounts/{a['id']}", json={"ownership": "owned"}).status_code == 200
    return accounts


def test_actual_counts_pot_and_category_once_and_classifies(owner):
    accounts = seed(owner)
    pot = accounts["Synthetic fuel pot"]["id"]
    assert owner.post("/api/plan-items", json={"name": "Tanken", "amount": "180", "category": "Tanken", "account_id": pot}).status_code == 201
    assert owner.post("/api/plan-items", json={"name": "Essen", "amount": "30", "category": "lebensmittel"}).status_code == 201
    report = owner.get("/api/plan", params={"history": 3}).json()
    fuel, food = report["items"]
    # pot: 60 + 40 (any category, transfer excluded); elsewhere: 50 fuel - 10 refund
    assert D(fuel["actual"]) == D(140) and D(fuel["from_pot"]) == D(100) and D(fuel["elsewhere"]) == D(40)
    assert fuel["status"] == "warning"  # 140 of 180 by mid-month projects to ~289
    assert D(fuel["projected"]) > D(180) and fuel["account_name"] == "Synthetic fuel pot"
    assert [h["month"] for h in fuel["history"]] == ["2026-08", "2026-09", "2026-10"]
    assert D(fuel["history"][1]["actual"]) == D(70) and fuel["history"][1]["status"] == "ok" and fuel["history"][2]["status"] is None
    assert D(food["actual"]) == D(30) and food["status"] == "warning"  # 100 % used counts as warning, not over
    assert D(report["totals"]["amount"]) == D(210) and report["running"] and report["days_elapsed"] == 15
    assert "Tanken" in report["categories"]


def test_owner_share_weights_actuals_and_past_month_over(owner, db):
    from app.models import Account, AccountChange
    accounts = seed(owner)
    main = accounts["Synthetic main"]["id"]
    db.query(AccountChange).filter(AccountChange.account_id == main).delete()
    db.get(Account, main).owner_share = D(50)  # no change history: the current share applies
    db.commit()
    assert owner.post("/api/plan-items", json={"name": "Tanken", "amount": "30", "category": "Tanken"}).status_code == 201
    report = owner.get("/api/plan", params={"month": "2026-09"}).json()
    item = report["items"][0]
    assert D(item["actual"]) == D(35) and item["status"] == "over" and not report["running"] and report["over"] == [item["id"]]


def test_validation_and_ownership(owner, client):
    assert owner.post("/api/plan-items", json={"name": "Nichts", "amount": "10"}).status_code == 422
    assert owner.post("/api/plan-items", json={"name": "X", "amount": "-1", "category": "A"}).status_code == 422
    assert owner.post("/api/plan-items", json={"name": "X", "amount": "1", "account_id": "missing"}).status_code == 404
    created = owner.post("/api/plan-items", json={"name": "X", "amount": "1", "category": "A"}).json()
    assert owner.patch(f"/api/plan-items/{created['id']}", json={"category": None}).status_code == 422
    assert owner.patch(f"/api/plan-items/{created['id']}", json={"amount": "5", "name": "Y"}).status_code == 200
    assert owner.get("/api/plan", params={"month": "2026-13"}).status_code == 422
    assert owner.delete(f"/api/plan-items/{created['id']}").status_code == 204
    assert owner.delete(f"/api/plan-items/{created['id']}").status_code == 404


def test_requires_login(client):
    assert client.get("/api/plan").status_code == 401
    assert client.get("/api/standing-orders").status_code == 401


def test_standing_orders_need_two_months_with_the_same_amount(owner, db):
    seed(owner)
    user_id = db.scalar(select(User.id))
    orders = plan.standing_orders(db, user_id, today=date(2026, 10, 15))
    assert [(o["account"], o["amount"], o["day"]) for o in orders] == [("Synthetic fuel pot", D(180), 1)]
    assert orders[0]["months"] == ["2026-08", "2026-09", "2026-10"] and orders[0]["active"]
    body = owner.get("/api/standing-orders").json()
    assert "debits" in body and "transfers" in body


def test_over_target_queues_one_generic_notification_per_month(owner, db):
    seed(owner)
    user_id = db.scalar(select(User.id))
    assert owner.post("/api/plan-items", json={"name": "Essen", "amount": "10", "category": "Lebensmittel"}).status_code == 201
    assert plan.queue_plan_alerts(db, user_id) == []  # notifications off
    db.add(NotificationSettings(owner_id=user_id, enabled=True, server="https://ntfy.example.test", topic="synthetic-topic",
                                events=["plan_exceeded"], last_import_at=plan.local_today(db, user_id) and None))
    db.commit()
    first = plan.queue_plan_alerts(db, user_id)
    second = plan.queue_plan_alerts(db, user_id)
    db.commit()
    assert len(first) == 1 and first == second
    row = db.scalar(select(Notification).where(Notification.owner_id == user_id))
    assert row.event == "plan_exceeded" and row.dedupe_key.endswith(":2026-10")


def test_actuals_use_the_owner_share_of_the_booking_day(owner, db):
    from datetime import datetime, timezone
    from app.asof import snapshot
    from app.models import Account, AccountChange
    accounts = seed(owner)
    main = db.get(Account, accounts["Synthetic main"]["id"])
    after = snapshot(main)
    db.add(AccountChange(account_id=main.id, changed_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                         before=dict(after, owner_share="50.0000"), after=after))
    db.commit()
    assert owner.post("/api/plan-items", json={"name": "Tanken", "amount": "100", "category": "Tanken"}).status_code == 201
    report = owner.get("/api/plan", params={"history": 2}).json()
    september, october = report["items"][0]["history"]
    assert D(september["actual"]) == D(35)  # shared flat: half of 70
    assert D(october["actual"]) == D(100)   # after the move: pot fuel 60 + main 50 - 10 refund, all at 100 %
