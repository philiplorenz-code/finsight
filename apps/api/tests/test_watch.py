"""Watched account (budget vs. top-ups), synthetic data only."""
from datetime import date
from decimal import Decimal as D

import pytest

import app.finance as finance
import app.watch as watch
from conftest import booking, upload


@pytest.fixture(autouse=True)
def today(monkeypatch):
    fixed = lambda db, user_id: date(2026, 7, 20)  # noqa: E731
    for module in (finance, watch):
        monkeypatch.setattr(module, "local_today", fixed)


def acct(ident, name):
    return {"Konto-ID": ident, "Konto": name}


def move(ident, amount, day, source, target, **extra):
    """An own-account transfer: outflow on the source, inflow on the target."""
    return [booking(f"{ident}-out", f"-{amount}", day=day, **acct(*source), **extra),
            booking(f"{ident}-in", amount, day=day, **acct(*target), **extra)]


def test_watch_splits_budget_from_topups(owner):
    salary, income, fun = ("synthetic-salary", "Synthetic Gehalt"), ("synthetic-income", "Synthetic Einnahmen"), ("synthetic-fun", "Freizeit")
    rows = []
    for m in range(1, 8):
        rows += move(f"budget{m}", "330", f"2026-{m:02d}-06", salary, fun)
        rows.append(booking(f"bar{m}", "-500", day=f"2026-{m:02d}-15", **acct(*fun), **{"Kategorie": "Ausgehen"}))
    for m in (2, 4, 5):
        rows += move(f"top{m}", "100", f"2026-{m:02d}-25", income, fun)
    rows += move("extra-salary", "50", "2026-05-27", salary, fun)
    rows.append(booking("refund", "20", day="2026-03-18", **acct(*fun), **{"Kategorie": "Ausgehen"}))
    rows[-1]["Kontostand"] = "0"
    rows.append(booking("last", "-1", day="2026-07-18", **acct(*fun), Kontostand="45"))
    assert upload(owner, rows).status_code == 200
    for a in owner.get("/api/accounts").json():
        owner.patch(f"/api/accounts/{a['id']}", json={"ownership": "owned"})
    owner.post("/api/transfers/detect")
    data = owner.get("/api/watch", params={"months": 7}).json()
    assert data["account"]["name"] == "Freizeit"
    assert [s["name"] for s in data["budget_sources"]] == ["Synthetic Gehalt"] and D(data["budget_sources"][0]["amount"]) == 330
    may = next(m for m in data["months"] if m["month"] == "2026-05")
    # the regular 330 is budget; the second transfer from the same account is a top-up, like the 100 from Einnahmen
    assert D(may["budget"]) == 330 and D(may["topups"]) == 150 and may["topup_count"] == 2
    assert {s["name"]: D(s["amount"]) for s in may["sources"]} == {"Synthetic Einnahmen": 100, "Synthetic Gehalt": 50}
    assert D(may["gap"]) == 170 and may["first_topup"] == "2026-05-25"
    summary = data["summary"]
    assert summary["full_months"] == 6 and summary["months_with_topups"] == 3 and D(summary["topups"]) == 350
    assert data["sources"][0]["name"] == "Synthetic Einnahmen" and D(data["sources"][0]["amount"]) == 300
    assert data["categories"][0]["name"] == "Ausgehen"
    # month-end balance is calculated back from the observed balance
    june = next(m for m in data["months"] if m["month"] == "2026-06")
    assert D(june["end_balance"]) == 45 - (330 - 500 - 1)

    # manual choice: no regular budget at all -> everything counts as top-up
    fun_id = data["account"]["id"]
    assert owner.put("/api/watch", json={"account_id": fun_id, "auto_budget": False, "budget_source": None}).status_code == 200
    manual = owner.get("/api/watch").json()
    assert manual["budget_sources"] == [] and manual["watched"] == fun_id
    assert D(next(m for m in manual["months"] if m["month"] == "2026-05")["topups"]) == 480
    assert owner.put("/api/watch", json={"account_id": "synthetic-missing"}).status_code == 404
