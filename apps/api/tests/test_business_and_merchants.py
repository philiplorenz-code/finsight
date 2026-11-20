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


def test_savings_goal_traffic_light_uses_standing_orders(owner, monkeypatch):
    import app.finance as fin
    monkeypatch.setattr(fin, "local_today", lambda db, user_id: date(2026, 5, 20))
    pot = {"Konto-ID": "synthetic-goal", "Konto": "Synthetic goal pot"}
    rows = [booking(f"g{m}", "200", day=f"2026-{m:02d}-01", **pot, **{"Umbuchung": "Ja", "Empfänger": "Synthetic me"}) for m in (3, 4, 5)]
    rows.append(booking("gb", "-0.01", day="2026-05-19", **pot, **{"Kontostand": "1000"}))
    assert upload(owner, rows).status_code == 200
    account = owner.get("/api/accounts").json()[0]
    owner.patch(f"/api/accounts/{account['id']}", json={"ownership": "owned", "purpose": "savings"})
    bucket = owner.post("/api/buckets", json={"name": "Notgroschen", "kind": "real", "target": "3000", "due_date": "2026-12-31"}).json()
    assert owner.put(f"/api/buckets/{bucket['id']}/allocations", json={"allocations": [{"account_id": account["id"], "amount": "1000"}]}).status_code == 200
    goal = next(b for b in owner.get("/api/buckets").json() if b["id"] == bucket["id"])["goal"]
    # needs 2000 in 7 months (~286/month), standing order brings 200 (70 % rule -> tight)
    assert goal["months_left"] == 7 and D(goal["planned_monthly"]) == D(200) and goal["status"] == "tight"
    assert D(goal["projected_at_due"]) == D(2400)


def test_anomalies_double_high_and_new_recurring(owner):
    rows = [booking(f"c{m}", "-20", day=f"2026-0{m}-05", **{"Empfänger": "Synthetic Cafe2", "Kategorie": "Restaurants"}) for m in (1, 2, 3)]
    rows += [booking("c-high", "-140", day="2026-05-02", **{"Empfänger": "Synthetic Cafe2", "Kategorie": "Restaurants"}),
             booking("d1", "-49.99", day="2026-05-10", **{"Empfänger": "Synthetic Shop"}),
             booking("d2", "-49.99", day="2026-05-11", **{"Empfänger": "Synthetic Shop"})]
    rows += [booking(f"n{m}", "-9.99", day=f"2026-0{m}-15", **{"Empfänger": "Synthetic Stream", "Kategorie": "Abos"}) for m in (4, 5)]
    assert upload(owner, rows).status_code == 200
    for a in owner.get("/api/accounts").json():
        owner.patch(f"/api/accounts/{a['id']}", json={"ownership": "owned"})
    items = owner.get("/api/anomalies", params={"days": 60}).json()["items"]
    kinds = {a["kind"]: a for a in items}
    assert kinds["double_debit"]["merchant"] == "Synthetic Shop" and kinds["double_debit"]["severity"] == "high"
    assert kinds["unusually_high"]["merchant"] == "Synthetic Cafe2" and D(kinds["unusually_high"]["typical"]) == D(20)
    assert items[0]["kind"] == "double_debit"


def test_flows_balance_in_and_out(owner):
    from test_wishlist import workbook
    workbook(owner)
    data = owner.get("/api/flows").json()
    hub = next(i for i, n in enumerate(data["nodes"]) if n["name"] == "Dein Geld")
    inflow = sum(D(str(l["value"])) for l in data["links"] if l["target"] == hub)
    outflow = sum(D(str(l["value"])) for l in data["links"] if l["source"] == hub)
    assert inflow == outflow and inflow > 0


def test_business_pnl_gross_to_net_with_pots(owner):
    vat_pot = {"Konto-ID": "synthetic-vat", "Konto": "2026 Umsatzsteuer"}
    est_pot = {"Konto-ID": "synthetic-est", "Konto": "2026 Einkommenssteuer"}
    adv_pot = {"Konto-ID": "synthetic-adv", "Konto": "2026 Steuerberater"}
    rows = [booking("g1", "1190", day="2026-03-10", **{"Empfänger": "Synthetic Verlag A"}),
            booking("e1", "-100", day="2026-03-12", **{"Empfänger": "Synthetic Hosting"}),
            booking("v1", "190", day="2026-03-11", **vat_pot, **{"Umbuchung": "Ja"}),
            booking("i1", "200", day="2026-03-11", **est_pot, **{"Umbuchung": "Ja"}),
            booking("a0", "150", day="2026-03-11", **adv_pot, **{"Umbuchung": "Ja"}),
            booking("a1", "-150", day="2026-03-20", **adv_pot, **{"Empfänger": "Synthetic Steuerberater"})]
    assert upload(owner, rows).status_code == 200
    for a in owner.get("/api/accounts").json():
        owner.patch(f"/api/accounts/{a['id']}", json={"ownership": "owned"})
    assert owner.post("/api/income-rules", json={"name": "Verlag A", "source": "business", "pattern": "Synthetic Verlag A"}).status_code == 201
    assert owner.post("/api/business-rules", json={"name": "Hosting", "pattern": "Synthetic Hosting"}).status_code == 201
    pnl = owner.get("/api/business/overview", params={"year": 2026}).json()["pnl"]
    march = pnl["months"][2]
    assert D(march["gross"]) == D(1190) and D(march["vat"]) == D(190) and D(march["net_revenue"]) == D(1000)
    assert D(march["ebitda"]) == D(900) and D(march["tax_adviser"]) == D(150) and D(march["profit_before_tax"]) == D(750)
    assert D(march["income_tax_reserve"]) == D(225) and D(march["left"]) == D(525)
    assert D(march["moved_vat"]) == D(190) and D(pnl["reserve_gap"]["income_tax"]) == D(25)
    small = owner.get("/api/business/overview", params={"year": 2026, "vat_rate": "0"}).json()["pnl"]
    assert D(small["months"][2]["vat"]) == 0 and D(small["months"][2]["net_revenue"]) == D(1190)
