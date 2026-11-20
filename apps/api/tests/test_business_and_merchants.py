"""Side-business overview, EÜR CSV preview and merchant profile. Synthetic only."""
from datetime import date
from decimal import Decimal as D

import pytest

import app.insights_extra as ie
from conftest import booking, upload


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(ie, "local_today", lambda db, user_id: date(2026, 5, 20))


def seed(owner):
    rows = [booking("h1", "1200", day="2026-01-10", **{"Empfänger": "Synthetic Verlag A"}),
            booking("h2", "800", day="2026-03-10", **{"Empfänger": "Synthetic Verlag B"}),
            booking("h3", "500", day="2026-03-28", **{"Empfänger": "Synthetic Verlag A"}),
            booking("e1", "-70", day="2026-02-05", **{"Empfänger": "Synthetic Hosting", "Kategorie": "Cloud", "Verwendungszweck": "@synthetic note"}),
            booking("s1", "-40", day="2026-02-07", **{"Empfänger": "Synthetic Cafe", "Kategorie": "Restaurants"}),
            booking("s2", "-60", day="2026-04-07", **{"Empfänger": "synthetic cafe", "Kategorie": "Restaurants"}),
            booking("s3", "10", day="2026-04-09", **{"Empfänger": "Synthetic Cafe", "Kategorie": "Restaurants"})]
    assert upload(owner, rows).status_code == 200
    for a in owner.get("/api/accounts").json():
        owner.patch(f"/api/accounts/{a['id']}", json={"ownership": "owned"})
    for name, pattern in (("Verlag A", "Synthetic Verlag A"), ("Verlag B", "Synthetic Verlag B")):
        assert owner.post("/api/income-rules", json={"name": name, "source": "business", "pattern": pattern}).status_code == 201
    assert owner.post("/api/business-rules", json={"name": "Hosting", "pattern": "Synthetic Hosting"}).status_code == 201


def test_business_overview_per_client_and_gaps(owner):
    seed(owner)
    data = owner.get("/api/business/overview", params={"year": 2026}).json()
    assert [(c["name"], D(c["total"])) for c in data["clients"]] == [("Verlag A", D(1700)), ("Verlag B", D(800))]
    assert D(data["totals"]["profit"]) == D(2430) and D(data["totals"]["tax_reserve_suggestion"]) == D(729)
    assert data["months_without_income"] == ["2026-02", "2026-04", "2026-05"]


def test_euer_csv_is_semicolon_german_and_guards_formulas(owner):
    seed(owner)
    r = owner.get("/api/business/euer.csv", params={"year": 2026})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("Datum;Art;") and len(lines) == 5
    assert "10.01.2026;Einnahme;Verlag A" in lines[1] and lines[1].split(";")[5] == "1200,00"
    hosting = next(l for l in lines if "Ausgabe" in l)
    assert hosting.endswith("'@synthetic note") and "-70,00" in hosting


def test_merchant_profile_case_insensitive_with_refunds(owner):
    seed(owner)
    data = owner.get("/api/merchants/profile", params={"name": "SYNTHETIC CAFE", "months": 6}).json()
    assert data["count"] == 3 and D(data["spent"]) == D(100) and D(data["refunds"]) == D(10)
    april = next(m for m in data["months"] if m["month"] == "2026-04")
    assert D(april["net_spent"]) == D(50) and data["months"][0]["month"] == "2025-12"
    assert data["categories"][0]["name"] == "Restaurants" and data["contract"] is None
    assert owner.get("/api/merchants/profile", params={"name": "nobody"}).status_code == 404
