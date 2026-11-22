"""Tidy-up inbox, synthetic data only."""
from datetime import date
from decimal import Decimal as D

import pytest

import app.finance as finance
import app.tidy as tidy
from conftest import booking, upload


@pytest.fixture(autouse=True)
def today(monkeypatch):
    fixed = lambda db, user_id: date(2026, 11, 22)  # noqa: E731
    for module in (finance, tidy):
        monkeypatch.setattr(module, "local_today", fixed)


def test_inbox_groups_vague_bookings_with_suggestions(owner):
    rows = [booking("a", "-20", day="2026-10-01", **{"Empfänger": "Synthetic Laden", "Kategorie": "Sonstige Ausgaben"}),
            booking("b", "-30", day="2026-10-05", **{"Empfänger": "Synthetic Laden", "Kategorie": "Sonstige Ausgaben"}),
            booking("c", "-10", day="2026-09-05", **{"Empfänger": "Synthetic Laden", "Kategorie": "Hobby"}),
            booking("d", "-45", day="2026-10-07", **{"Empfänger": "REWE Synthetic", "Kategorie": "Sonstiges"}),
            booking("e", "-5", day="2026-10-08", **{"Empfänger": "Unbekannt Synthetic", "Kategorie": "Sonstiges"}),
            booking("f", "-99", day="2026-10-09", **{"Empfänger": "Synthetic Markt", "Kategorie": "Lebensmittel"})]
    assert upload(owner, rows).status_code == 200
    for a in owner.get("/api/accounts").json():
        owner.patch(f"/api/accounts/{a['id']}", json={"ownership": "owned"})
    data = owner.get("/api/tidy/inbox").json()
    by = {g["merchant"]: g for g in data["groups"]}
    assert set(by) == {"Synthetic Laden", "REWE Synthetic", "Unbekannt Synthetic"}
    assert D(by["Synthetic Laden"]["total"]) == D(50) and by["Synthetic Laden"]["count"] == 2
    assert by["Synthetic Laden"]["suggestion"] == "Hobby" and by["Synthetic Laden"]["suggestion_source"] == "same_merchant"
    assert by["REWE Synthetic"]["suggestion"] == "Lebensmittel" and by["REWE Synthetic"]["suggestion_source"] == "keyword"
    assert by["Unbekannt Synthetic"]["suggestion"] is None
    assert data["groups"][0]["merchant"] == "Synthetic Laden" and D(data["total"]) == D(100)


def test_search_finds_bookings_merchants_and_accounts(owner):
    rows = [booking("s1", "-12", **{"Empfänger": "Synthetic Bäckerei", "Konto": "Synthetic Giro"}),
            booking("s2", "-8", **{"Empfänger": "Other", "Verwendungszweck": "Synthetic Bäckerei Rest"})]
    assert upload(owner, rows).status_code == 200
    data = owner.get("/api/search", params={"q": "bäckerei"}).json()
    assert len(data["transactions"]) == 2 and data["merchants"] == [{"name": "Synthetic Bäckerei", "count": 1}]
    assert owner.get("/api/search", params={"q": "synthetic giro"}).json()["accounts"][0]["name"] == "Synthetic Giro"
    assert owner.get("/api/search", params={"q": "x"}).status_code == 422


def test_rule_from_inbox_removes_merchant(owner):
    rows = [booking("r1", "-20", day="2026-10-01", **{"Empfänger": "Synthetic Kiosk", "Kategorie": "Sonstiges"}),
            booking("r2", "-15", day="2026-10-02", **{"Empfänger": "Synthetic Kiosk", "Kategorie": "Sonstiges"})]
    assert upload(owner, rows).status_code == 200
    for a in owner.get("/api/accounts").json():
        owner.patch(f"/api/accounts/{a['id']}", json={"ownership": "owned"})
    assert [g["merchant"] for g in owner.get("/api/tidy/inbox").json()["groups"]] == ["Synthetic Kiosk"]
    created = owner.post("/api/category-rules", json={"name": "Synthetic Kiosk → Getränke", "category": "Getränke",
                                                       "pattern": "Synthetic Kiosk", "match_field": "merchant", "flow": "expense"})
    assert created.status_code == 201 and created.json()["reapplied"] == 2
    assert owner.get("/api/tidy/inbox").json()["groups"] == []
