from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models import Account, Finding, User
from conftest import booking, upload


def period(client):
    return client.get("/api/overview", params={"start": "2026-01-01", "end": "2026-01-31"}).json()


def test_cashflow_transfers_future_currencies_negative_balances(owner):
    rows = [booking("income", "1000"), booking("expense", "-100"),
            booking("transfer", "-200", **{"Umbuchung": "Ja"}),
            booking("future", "-999", day=(date.today() + timedelta(days=30)).isoformat()),
            booking("usd", "-20", **{"Währung": "USD", "Konto-ID": "usd-account", "Kontostand": "-50"}),
            booking("balance", "0", **{"Kontostand": "100"})]
    assert upload(owner, rows).status_code == 200
    result = period(owner)
    eur, usd = result["currencies"]
    assert eur["currency"] == "EUR"
    assert eur["income"] == "1000"
    assert eur["expenses"] == "100"
    assert eur["surplus"] == "900"
    assert eur["savings_rate"] == "0.9"
    assert usd["observed_balance"] == "-50"
    assert any("One-sided" in w for w in result["warnings"])
    assert owner.get("/api/overview", params={"start": "2026-03-01", "end": "2026-01-01"}).status_code == 422


def test_balanced_and_uncertain_splits_no_double_count(owner):
    rows = [booking("parent", "-100"), booking("child1", "-60", **{"Parent ID": "parent"}),
            booking("child2", "-40", **{"Parent ID": "parent"})]
    assert upload(owner, rows).status_code == 200
    assert period(owner)["currencies"][0]["expenses"] == "100"
    rows[2]["Betrag"] = "-30"
    assert upload(owner, rows).status_code == 200
    result = period(owner)
    assert result["currencies"][0]["expenses"] == "100"
    assert "Split reconciliation uncertain" in result["warnings"]


def test_paired_transfers_deposits_and_withdrawals(owner):
    rows = [booking("transfer-a", "-50", **{"Umbuchung": "Ja"}),
            booking("transfer-b", "50", **{"Umbuchung": "Ja", "Konto-ID": "cash-account"}),
            booking("external-deposit", "80"), booking("cash-spend", "-20", **{"Konto-ID": "cash-account"})]
    upload(owner, rows)
    result = period(owner)
    assert result["currencies"][0]["income"] == "80"
    assert result["currencies"][0]["expenses"] == "20"
    assert not any("One-sided" in w for w in result["warnings"])


def test_transaction_filters_and_reversible_override(owner):
    upload(owner, [booking("first", "-10"), booking("second", "-50", **{"Kategorie": "Other"})])
    page = owner.get("/api/transactions", params={"page_size": 1}).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    found = owner.get("/api/transactions", params={"min_amount": "-20", "max_amount": "0", "search": "Synthetic"}).json()
    assert found["total"] == 1
    tx = found["items"][0]
    owner.patch(f"/api/transactions/{tx['id']}", json={"category_override": "New", "tags": ["tag"]})
    assert owner.get("/api/transactions", params={"category": "New", "tag": "tag"}).json()["total"] == 1
    assert owner.get("/api/transactions", params={"search": "%"}).json()["total"] == 0
    owner.post(f"/api/transactions/{tx['id']}/reset")
    assert owner.get("/api/transactions", params={"category": "New"}).json()["total"] == 0


def test_buckets_obligations_no_overlapping_allocations(owner):
    upload(owner, [booking(**{"Kontostand": "1000"})])
    account = owner.get("/api/accounts").json()[0]
    owner.patch(f"/api/accounts/{account['id']}", json={"ownership": "owned"})
    a = owner.post("/api/buckets", json={"name": "Annual insurance"}).json()
    b = owner.post("/api/buckets", json={"name": "Other"}).json()
    obligation = owner.post(f"/api/buckets/{a['id']}/obligations", json={"name": "Insurance", "amount": "720", "period": "yearly"})
    assert obligation.status_code == 201
    allocation = {"allocations": [{"account_id": account["id"], "amount": "600"}]}
    assert owner.put(f"/api/buckets/{a['id']}/allocations", json=allocation).status_code == 200
    assert owner.put(f"/api/buckets/{b['id']}/allocations", json=allocation).status_code == 409
    allocation["allocations"][0]["amount"] = "400"
    assert owner.put(f"/api/buckets/{b['id']}/allocations", json=allocation).status_code == 200
    buckets = {x["id"]: x for x in owner.get("/api/buckets").json()}
    assert buckets[a["id"]]["monthly_obligation"] == "60"
    assert buckets[a["id"]]["required_monthly_contribution"] == "120"
    assert owner.delete(f"/api/buckets/{b['id']}").status_code == 200


def test_multiple_obligations_do_not_reuse_funds(owner):
    upload(owner, [booking(**{"Kontostand": "500"})])
    account = owner.get("/api/accounts").json()[0]
    owner.patch(f"/api/accounts/{account['id']}", json={"ownership": "owned"})
    bucket = owner.post("/api/buckets", json={"name": "Shared"}).json()
    for name in ["first", "second"]:
        assert owner.post(f"/api/buckets/{bucket['id']}/obligations", json={"name": name, "amount": "400", "period": "once"}).status_code == 201
    assert owner.put(f"/api/buckets/{bucket['id']}/allocations", json={"allocations": [{"account_id": account["id"], "amount": "500"}]}).status_code == 200
    assert owner.get("/api/buckets").json()[0]["required_monthly_contribution"] == "300"


def test_contracts_recurrence_price_changes_and_nulls(owner):
    rows = [booking("one", "-60", day="2024-01-15", **{"Vertrag": "Insurance"}),
            booking("two", "-65", day="2025-01-15", **{"Vertrag": "Insurance"}),
            booking("three", "-70", day="2026-01-15", **{"Vertrag": "Insurance"})]
    upload(owner, rows)
    contract = owner.get("/api/contracts").json()["items"][0]
    assert contract["period"] == "yearly"
    assert contract["annual_cost"] == "70"
    assert contract["price_change"] == "5"
    assert len(contract["evidence"]) == 3


def test_owner_isolation_settings_findings(owner, db):
    other = User(owner_slot=2, email="other@synthetic.test", password_hash="not-for-login")
    db.add(other)
    db.flush()
    account = Account(user_id=other.id, source_key="private", name="Other", currency="EUR")
    finding = Finding(user_id=other.id, title="Other")
    db.add_all([account, finding])
    db.commit()
    assert owner.get("/api/accounts").json() == []
    assert owner.patch(f"/api/accounts/{account.id}", json={"name": "Not permitted"}).status_code == 404
    assert owner.get(f"/api/accounts/{account.id}/balances").status_code == 404
    assert owner.patch(f"/api/findings/{finding.id}", json={"status": "dismissed"}).status_code == 404
    assert owner.get("/api/findings").json() == []
    assert owner.get("/api/settings").json()["ai_enabled"] is False
    settings = owner.patch("/api/settings", json={"locale": "en", "provider": {"api_key": "synthetic-secret", "name": "local"}})
    assert settings.status_code == 200
    assert "synthetic-secret" not in settings.text
    assert owner.patch("/api/settings", json={"timezone": "Invalid/Zone"}).status_code == 422


def test_settings_configure_real_integrations_without_network(owner, db):
    from app.ai import AIPolicy
    from app.notifications import NotificationSettings
    policy = {"enabled": False, "external_consent": False, "model": "synthetic/model",
              "prices": {"synthetic/model": {"input": "1", "output": "2", "currency": "EUR", "verified": True}},
              "monthly_limit": "1", "total_limit": "2", "run_limit": "0.05", "channel_limits": {"chat": "1"}}
    result = owner.patch("/api/settings", json={"ai": policy, "notifications": {"enabled": False, "timezone": "Europe/Berlin"}})
    assert result.status_code == 200
    assert result.json()["ai"]["max_input_tokens"] == 4096
    assert result.json()["ai"]["monthly_limit"] == "1"
    user_id = owner.get("/api/auth/me").json()["id"]
    assert db.get(AIPolicy, user_id).model == "synthetic/model"
    assert db.get(NotificationSettings, user_id).enabled is False
    assert owner.get("/api/ai/usage").status_code == 200
    assert owner.post("/api/notifications/test").status_code == 202
    upload(owner, [booking()])
    assert db.get(NotificationSettings, user_id).last_import_at is not None
    assert owner.patch("/api/settings", json={"ai": {"max_steps": 900}}).status_code == 422
    assert owner.patch("/api/settings", json={"notifications": {"timezone": "No/Such_Zone"}}).status_code == 422


def test_split_transfer_parent_does_not_turn_children_into_consumption(owner):
    rows = [booking("parent", "-100", **{"Umbuchung": "Ja"}),
            booking("child1", "-60", **{"Parent ID": "parent"}),
            booking("child2", "-40", **{"Parent ID": "parent"})]
    assert upload(owner, rows).status_code == 200
    result = period(owner)
    assert result["currencies"][0]["expenses"] == "0"


def test_investments_not_available_liquidity_and_historical_balance_no_lookahead(owner):
    upload(owner, [booking("old", "0", day="2026-01-01", **{"Kontostand": "100"}),
                   booking("later", "0", day="2026-03-01", **{"Kontostand": "200"})])
    assert period(owner)["currencies"][0]["observed_balance"] == "100"
    account = owner.get("/api/accounts").json()[0]
    owner.patch(f"/api/accounts/{account['id']}", json={"purpose": "investment"})
    result = period(owner)["currencies"][0]
    assert result["observed_balance"] == "100"
    assert result["available_liquidity"] == "0"


def test_latest_same_date_balance_uses_latest_import(owner):
    upload(owner, [booking(**{"Kontostand": "100"})])
    upload(owner, [booking(**{"Kontostand": "120"})])
    assert owner.get("/api/accounts").json()[0]["balance"] == "120"


def test_allocated_account_exclusion_invalidates_backing_and_balance_reduction_warns(owner):
    upload(owner, [booking(**{"Kontostand": "500"})])
    account = owner.get("/api/accounts").json()[0]
    owner.patch(f"/api/accounts/{account['id']}", json={"ownership": "owned"})
    bucket = owner.post("/api/buckets", json={"name": "Reserved"}).json()
    assert owner.put(f"/api/buckets/{bucket['id']}/allocations", json={"allocations": [{"account_id": account["id"], "amount": "500"}]}).status_code == 200
    assert owner.patch(f"/api/accounts/{account['id']}", json={"included": False}).status_code == 200
    assert owner.get("/api/buckets").json()[0]["funded"] == "0"
    upload(owner, [booking(**{"Kontostand": "100"})])
    assert owner.get("/api/buckets").json()[0]["warnings"]
