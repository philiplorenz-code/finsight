"""Synthetic-only net worth, ownership share and debt payoff regressions."""
from decimal import Decimal

from app.networth import payoff
from conftest import booking, upload
from datetime import date

D = Decimal


def setup_account(owner, balance="5000"):
    assert upload(owner, [booking("a", "100", day="2026-06-30", **{"Kontostand": balance})]).status_code == 200
    account = owner.get("/api/accounts").json()[0]
    assert owner.patch(f"/api/accounts/{account['id']}", json={"ownership": "owned"}).status_code == 200
    return account


def test_net_worth_splits_ownership_and_debt(owner):
    account = setup_account(owner)
    assert owner.patch(f"/api/accounts/{account['id']}", json={"owner_share": 50}).status_code == 200
    assert owner.patch(f"/api/accounts/{account['id']}", json={"owner_share": 150}).status_code == 422
    car = owner.post("/api/holdings", json={"name": "Auto", "kind": "asset", "category": "car", "value": "20000", "share": 100})
    assert car.status_code == 201
    loan = owner.post("/api/holdings", json={"name": "Autokredit", "kind": "liability", "category": "loan", "value": "12000",
                                              "share": 100, "monthly_payment": "400", "interest_rate": "0"}).json()
    other = owner.post("/api/holdings", json={"name": "Gemeinsames Haus", "kind": "asset", "category": "property",
                                               "value": "100000", "share": 25}).json()
    data = owner.get("/api/net-worth").json()
    t = data["totals"]
    assert D(t["assets_mine"]) == D(2500) + D(20000) + D(25000)
    assert D(t["assets_others"]) == D(2500) + D(75000)
    assert D(t["liabilities_mine"]) == D(12000)
    assert D(t["net_worth_mine"]) == D(47500) - D(12000)
    assert D(t["net_worth_gross"]) == D(t["net_worth_mine"]) + D(t["net_worth_others"])
    assert D(t["monthly_debt_service"]) == D(400)
    debt = next(h for h in data["holdings"] if h["kind"] == "liability")
    assert debt["months_left"] == 30 and debt["payoff_date"]
    assert D(owner.patch(f"/api/holdings/{loan['id']}", json={"value": "6000"}).json()["value"]) == D(6000)
    assert owner.patch(f"/api/holdings/{loan['id']}", json={"name": None}).status_code == 422
    assert owner.delete(f"/api/holdings/{other['id']}").status_code == 200
    assert owner.delete(f"/api/holdings/{other['id']}").status_code == 404
    assert owner.post("/api/holdings", json={"name": "x", "kind": "bogus", "value": "1"}).status_code == 422
    assert owner.post("/api/holdings", json={"name": "x", "kind": "asset", "value": "-1"}).status_code == 422


def test_negative_account_balance_counts_as_liability(owner):
    setup_account(owner, balance="-300")
    t = owner.get("/api/net-worth").json()["totals"]
    assert D(t["liabilities_mine"]) == D(300) and D(t["assets_mine"]) == 0


def test_payoff_with_interest_and_unpayable():
    today = date(2026, 1, 15)
    assert payoff(D(1200), D(100), D(0), today) == {"months_left": 12, "payoff_date": "2027-01-01"}
    assert payoff(D(1000), D(5), D(12), today)["months_left"] is None, "payment below the interest never repays"
    assert 11 <= payoff(D(1200), D(105), D(6), today)["months_left"] <= 12
    assert payoff(D(0), None, None, today)["months_left"] == 0
    assert payoff(D(500), None, None, today)["months_left"] is None


def test_net_worth_requires_login(client):
    assert client.get("/api/net-worth").status_code in {401, 403}


def test_amortisation_schedule_is_deterministic():
    from app.networth import amortisation
    today = date(2026, 1, 15)
    zero = amortisation(D(1200), D(400), D(0), today)
    assert [r["balance"] for r in zero] == [D(800), D(400), D(0)] and zero[0]["month"] == "2026-02"
    # 12 % p.a. -> 1 % per month: 1000 + 10 - 300 = 710, then 710 + 7.10 - 300 = 417.10
    rate = amortisation(D(1000), D(300), D(12), today)
    assert rate[0]["balance"] == D("710.00") and rate[1]["balance"] == D("417.10") and rate[-1]["balance"] == 0
    assert amortisation(D(1000), D(10), D(12), today) == [], "payment below interest never repays"
    assert amortisation(D(1000), None, D(5), today) == [] and amortisation(D(0), D(10), D(5), today) == []


def test_payoff_edge_cases():
    today = date(2026, 1, 15)
    assert payoff(D(1000), D(10), D(12), today)["months_left"] is None
    assert payoff(D(1000), D(1000), D(0), today)["months_left"] == 1
    assert payoff(D(0), D(10), D(5), today)["months_left"] == 0


def test_snapshots_history_and_wishlist_scenario(owner, db):
    from datetime import timedelta
    from app.models import Holding, HoldingSnapshot
    setup_account(owner)
    car = owner.post("/api/holdings", json={"name": "Auto", "kind": "asset", "category": "car", "value": "20000"}).json()
    loan = owner.post("/api/holdings", json={"name": "Kredit", "kind": "liability", "category": "loan", "value": "3000",
                                              "share": 50, "monthly_payment": "300", "interest_rate": "0"}).json()
    from sqlalchemy import select
    assert len(db.scalars(select(HoldingSnapshot)).all()) == 2
    owner.patch(f"/api/holdings/{car['id']}", json={"value": "19000"})
    owner.patch(f"/api/holdings/{car['id']}", json={"value": "18500"})
    snaps = db.scalars(select(HoldingSnapshot).where(HoldingSnapshot.holding_id == car["id"])).all()
    assert len(snaps) == 1 and snaps[0].value == D(18500), "one snapshot per day, latest value wins"
    data = owner.get("/api/net-worth").json()
    last = data["history"][-1]
    assert D(last["holdings_mine"]) == D(18500) - D(1500) and last["holdings_counted"] == 2
    assert D(last["net_worth_mine"]) == D(last["accounts_mine"]) + D(17000)
    schedule = next(h for h in data["holdings"] if h["kind"] == "liability")["schedule"]
    assert len(schedule) == 10 and D(schedule[-1]["balance"]) == 0
    scenario = owner.get("/api/wishlist").json()["payoff_scenarios"]
    assert len(scenario) == 1 and scenario[0]["months_left"] == 10 and D(scenario[0]["freed_monthly"]) == D(150)
    assert D(scenario[0]["expected_surplus_after"]) - D(owner.get("/api/wishlist").json()["baseline"]["expected_surplus"]) == D(150)
    owner.delete(f"/api/holdings/{car['id']}")
    assert not db.scalars(select(HoldingSnapshot).where(HoldingSnapshot.holding_id == car["id"])).all()
