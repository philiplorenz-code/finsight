"""Open items with other people, synthetic data only."""
from datetime import date
from decimal import Decimal as D

import pytest

import app.finance as finance
import app.receivables as rv
from conftest import booking, upload


@pytest.fixture(autouse=True)
def today(monkeypatch):
    fixed = lambda db, user_id: date(2026, 11, 22)  # noqa: E731
    for module in (finance, rv):
        monkeypatch.setattr(module, "local_today", fixed)


def test_open_item_suggests_and_confirms_settlement(owner):
    rows = [booking("x1", "806.72", day="2026-11-25", **{"Empfänger": "Synthetic Mitbewohner", "Verwendungszweck": "Nebenkosten Anteil"}),
            booking("x2", "806.72", day="2026-10-01", **{"Empfänger": "Synthetic Other"})]
    assert upload(owner, rows).status_code == 200
    created = owner.post("/api/open-items", json={"direction": "receivable", "person": "Synthetic Mitbewohner", "title": "Nebenkosten 2025, Hälfte",
                                                   "amount": "806.72", "since": "2026-11-16", "due": "2026-12-15"}).json()
    sug = created["suggested_settlement"]
    assert sug and sug["date"] == "2026-11-25" and sug["name_matches"] is True  # the earlier booking is before 'since'
    listing = owner.get("/api/open-items").json()
    assert D(listing["totals"]["receivable"]) == D("806.72") and D(listing["totals"]["net"]) == D("806.72")
    done = owner.patch(f"/api/open-items/{created['id']}", json={"settled_transaction_id": sug["transaction_id"]}).json()
    assert done["status"] == "settled" and done["settled_on"] == "2026-11-25" and done["suggested_settlement"] is None
    assert D(owner.get("/api/open-items").json()["totals"]["receivable"]) == 0
    reopened = owner.patch(f"/api/open-items/{created['id']}", json={"status": "open"}).json()
    assert reopened["settled_transaction_id"] is None


def test_payable_overdue_and_validation(owner):
    item = owner.post("/api/open-items", json={"direction": "payable", "person": "Synthetic Person", "title": "Geliehen",
                                                "amount": "50", "since": "2026-10-01", "due": "2026-11-01"}).json()
    assert item["overdue"] is True and item["suggested_settlement"] is None
    assert owner.post("/api/open-items", json={"direction": "gift", "person": "X", "title": "Y", "amount": "1"}).status_code == 422
    assert owner.post("/api/open-items", json={"direction": "payable", "person": "X", "title": "Y", "amount": "0"}).status_code == 422
    assert owner.delete(f"/api/open-items/{item['id']}").status_code == 204
    assert owner.delete(f"/api/open-items/{item['id']}").status_code == 404
