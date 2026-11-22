"""Cash book: withdrawals move money into the wallet, logged cash counts as spending. Synthetic only."""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select

import app.cashbook as cb
import app.finance as finance
from app.models import User
from conftest import booking, upload


@pytest.fixture(autouse=True)
def today(monkeypatch):
    fixed = lambda db, user_id: date(2026, 11, 22)  # noqa: E731
    for module in (finance, cb):
        monkeypatch.setattr(module, "local_today", fixed)


def setup(owner):
    rows = [booking("atm-old", "-50", day="2026-10-20", **{"Kategorie": "Bargeld"}),
            booking("atm", "-100", day="2026-11-05", **{"Kategorie": "Bargeld"}),
            booking("food", "-40", day="2026-11-06", **{"Kategorie": "Lebensmittel"})]
    assert upload(owner, rows).status_code == 200
    for a in owner.get("/api/accounts").json():
        owner.patch(f"/api/accounts/{a['id']}", json={"ownership": "owned"})


def nov_expenses(owner):
    data = owner.get("/api/overview", params={"start": "2026-11-01", "end": "2026-11-22"}).json()
    eur = next(c for c in data["currencies"] if c["currency"] == "EUR")
    return D(eur["expenses"]), {c["category"]: D(c["amount"]) for c in data["categories"]}


def test_without_cash_book_withdrawal_is_spending(owner):
    setup(owner)
    total, cats = nov_expenses(owner)
    assert total == D(140) and cats["Bargeld"] == D(100)
    assert owner.post("/api/cashbook/entries", json={"amount": "5", "category": "Snacks"}).status_code == 409


def test_cash_book_replaces_withdrawals_with_logged_spending(owner):
    setup(owner)
    assert owner.put("/api/cashbook/settings", json={"since": "2026-11-01"}).status_code == 200
    for amount, cat in (("12.50", "Restaurants"), ("7.50", "Lebensmittel")):
        assert owner.post("/api/cashbook/entries", json={"day": "2026-11-08", "amount": amount, "category": cat, "merchant": "Synthetic Kiosk"}).status_code == 201
    total, cats = nov_expenses(owner)
    assert total == D(60) and "Bargeld" not in cats and cats["Lebensmittel"] == D("47.50") and cats["Restaurants"] == D("12.50")
    wallet = owner.get("/api/cashbook").json()["wallet"]
    assert D(wallet["withdrawn"]) == D(100) and D(wallet["logged"]) == D(20) and D(wallet["in_wallet"]) == D(80)
    # October (before the start date) is unchanged
    data = owner.get("/api/overview", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    assert D(next(c for c in data["currencies"] if c["currency"] == "EUR")["expenses"]) == D(50)


def test_plan_counts_cash_entries_by_category(owner, db):
    setup(owner)
    owner.put("/api/cashbook/settings", json={"since": "2026-11-01"})
    owner.post("/api/cashbook/entries", json={"day": "2026-11-08", "amount": "7.50", "category": "Lebensmittel"})
    owner.post("/api/plan-items", json={"name": "Essen", "amount": "300", "category": "Lebensmittel"})
    import app.plan as plan
    report = plan.plan_report(db, db.scalar(select(User.id)), date(2026, 11, 1), 1)
    assert D(report["items"][0]["actual"]) == D("47.50")
