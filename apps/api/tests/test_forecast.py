"""Upcoming bookings and money / net-worth forecast, synthetic data only."""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select

import app.forecast as fc
from app.models import User
from conftest import booking, upload

MAIN = {"Konto-ID": "synthetic-main", "Konto": "Synthetic main"}
POT = {"Konto-ID": "synthetic-pot", "Konto": "Synthetic pot"}


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(fc, "local_today", lambda db, user_id: date(2026, 10, 20))


def seed(owner):
    rows = []
    for m in range(4, 11):
        rows.append(booking(f"pay{m}", "3000", day=f"2026-{m:02d}-01" if m < 10 else "2026-09-29", **MAIN, **{"Empfänger": "Synthetic Employer"}) if m < 10 else booking("pay10", "3000", day="2026-10-01", **MAIN, **{"Empfänger": "Synthetic Employer"}))
        rows.append(booking(f"ins{m}", "-50", day=f"2026-{m:02d}-03", **MAIN, **{"Empfänger": "Synthetic Insurance", "Kategorie": "Versicherung"}))
        rows.append(booking(f"spend{m}", "-1000", day=f"2026-{m:02d}-15", **MAIN))
    for m in (8, 9, 10):
        rows.append(booking(f"so{m}", "180", day=f"2026-{m:02d}-01", **POT, **{"Umbuchung": "Ja", "Empfänger": "Synthetic me"}))
    rows.append(booking("bal", "-1", day="2026-10-19", **MAIN, **{"Kontostand": "2000"}))
    assert upload(owner, rows).status_code == 200
    for a in owner.get("/api/accounts").json():
        assert owner.patch(f"/api/accounts/{a['id']}", json={"ownership": "owned", "purpose": "checking"}).status_code == 200
    assert owner.post("/api/income-rules", json={"name": "Job", "source": "employment", "pattern": "Synthetic Employer"}).status_code == 201


def test_upcoming_lists_contracts_standing_orders_and_pay(owner, db):
    seed(owner)
    items = fc.upcoming(db, db.scalar(select(User.id)), days=20)
    kinds = {(i["kind"], i["date"]) for i in items}
    assert ("transfer", "2026-11-01") in kinds and ("income", "2026-11-01") in kinds
    assert any(i["kind"] == "contract" and i["date"].startswith("2026-11-0") and i["account"] == "Synthetic main" and D(i["amount"]) == D(-50) for i in items)
    assert [i["date"] for i in items] == sorted(i["date"] for i in items)
    assert owner.get("/api/upcoming", params={"days": 200}).status_code == 422


def test_forecast_adds_surplus_and_loan_principal_then_freed_payment(owner, db):
    seed(owner)
    assert owner.post("/api/holdings", json={"name": "Synthetic loan", "kind": "liability", "category": "loan", "value": "1000",
                                             "monthly_payment": "500", "interest_rate": "0", "share": "50"}).status_code == 201
    data = owner.get("/api/forecast", params={"months": 4}).json()
    m = data["months"]
    expected = D(data["monthly"]["expected_surplus"])
    assert len(m) == 4 and m[0]["month"] == "2026-11"
    # 50 % of a 1000 loan paid 500/month: own debt 250 after month 1, 0 after month 2; own payment 250 freed from month 3
    assert D(m[0]["debt"]) == D(250) and D(m[1]["debt"]) == D(0)
    assert D(m[2]["cash_expected"]) - D(m[1]["cash_expected"]) == expected + D(250)
    assert D(m[1]["net_worth_expected"]) - D(data["start"]["net_worth"]) == 2 * expected + D(500)
    assert data["loans"][0]["paid_off"] == "2026-12"
