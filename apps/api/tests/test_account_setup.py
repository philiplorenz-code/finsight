"""Synthetic-only: accounts that need a decision after an import, suggestions and batch classification."""
from decimal import Decimal

from app.account_setup import suggest
from conftest import booking, upload


def import_accounts(owner):
    rows = [booking("m1", "-20", **{"Konto-ID": "main", "Konto": "Girokonto", "Kontostand": "500"}),
            booking("c1", "-300", day="2026-01-16", **{"Konto-ID": "card", "Konto": "Visa Kreditkarte", "Kontostand": "-300"}),
            booking("s1", "100", day="2026-01-17", **{"Konto-ID": "pot", "Konto": "Urlaub", "Kontostand": "100", "Umbuchung": "Ja"}),
            booking("s2", "50", day="2026-01-18", **{"Konto-ID": "pot", "Konto": "Urlaub", "Kontostand": "150", "Umbuchung": "Ja"}),
            booking("d1", "-1", day="2026-01-19", **{"Konto-ID": "dep", "Konto": "Depot Beispiel", "Kontostand": "9000"})]
    return upload(owner, rows)


def test_suggestions_are_hints_from_name_balance_and_usage():
    assert suggest("ETF Sparplan Depot", Decimal(1), 5, 0)["purpose"] == "investment"
    assert suggest("Visa Gold", Decimal(5), 5, 0)["purpose"] == "credit"
    assert suggest("Irgendwas", Decimal(-40), 5, 0) == {"ownership": "owned", "purpose": "credit", "reason": "negative_balance"}
    assert suggest("Mac Mini", Decimal(10), 10, 9)["purpose"] == "savings", "mostly transfers: looks like a savings pot"
    assert suggest("Umzug", Decimal(0), 3, 0)["purpose"] == "savings"
    assert suggest("Girokonto", Decimal(100), 10, 1)["purpose"] == "checking"
    assert suggest("Bargeld Kasse", None, 0, 0)["purpose"] == "cash"


def test_import_reports_new_accounts_and_lists_unclassified_ones(owner):
    result = import_accounts(owner)
    assert result.status_code == 200 and result.json()["summary"]["new_accounts"] == 4
    data = owner.get("/api/accounts/unclassified").json()
    assert data["count"] == 4
    by_name = {i["name"]: i for i in data["items"]}
    assert by_name["Visa Kreditkarte"]["suggestion"]["purpose"] == "credit"
    assert by_name["Urlaub"]["suggestion"]["purpose"] == "savings" and by_name["Urlaub"]["bookings"] == 2
    assert by_name["Depot Beispiel"]["suggestion"]["purpose"] == "investment"
    assert by_name["Girokonto"]["suggestion"] == {"ownership": "owned", "purpose": "checking", "reason": "default"}
    assert Decimal(by_name["Girokonto"]["balance"]) == 500
    again = upload(owner, [booking("m1", "-20", **{"Konto-ID": "main", "Konto": "Girokonto", "Kontostand": "500"}), booking("m2", "-1", day="2026-01-20", **{"Konto-ID": "main", "Konto": "Girokonto", "Kontostand": "499"})])
    assert again.json()["summary"]["new_accounts"] == 0


def test_batch_classification_validates_and_clears_the_list(owner):
    import_accounts(owner)
    items = owner.get("/api/accounts/unclassified").json()["items"]
    payload = [{"id": i["id"], "ownership": i["suggestion"]["ownership"], "purpose": i["suggestion"]["purpose"]} for i in items]
    assert owner.post("/api/accounts/classify", json={"items": []}).status_code == 422
    assert owner.post("/api/accounts/classify", json={"items": [{**payload[0], "ownership": "unknown"}]}).status_code == 422
    assert owner.post("/api/accounts/classify", json={"items": [{**payload[0], "purpose": "bogus"}]}).status_code == 422
    assert owner.post("/api/accounts/classify", json={"items": [payload[0], payload[0]]}).status_code == 422, "duplicates"
    assert owner.post("/api/accounts/classify", json={"items": [{"id": "nope", "ownership": "owned"}]}).status_code == 404
    first = payload[0]
    assert owner.post("/api/accounts/classify", json={"items": [first]}).json() == {"classified": 1}
    assert owner.get("/api/accounts/unclassified").json()["count"] == 3
    assert owner.post("/api/accounts/classify", json={"items": payload[1:]}).json() == {"classified": 3}
    assert owner.get("/api/accounts/unclassified").json() == {"count": 0, "items": []}
    accounts = {a["name"]: a for a in owner.get("/api/accounts").json()}
    assert accounts["Visa Kreditkarte"]["ownership"] == "owned" and accounts["Visa Kreditkarte"]["purpose"] == "credit"


def test_only_own_unclassified_accounts_and_login_required(owner, client):
    import_accounts(owner)
    ids = [i["id"] for i in owner.get("/api/accounts/unclassified").json()["items"]]
    from fastapi.testclient import TestClient
    from app.main import app
    anonymous = TestClient(app)
    assert anonymous.get("/api/accounts/unclassified").status_code in {401, 403}
    assert anonymous.post("/api/accounts/classify", json={"items": [{"id": ids[0], "ownership": "owned"}]}).status_code in {401, 403}
