"""Synthetic-only category rules and the transfer review list."""
from decimal import Decimal

from sqlalchemy import select

from app.models import Transaction
from conftest import booking, upload

D = Decimal


def cats(owner):
    return {t["source_key"] if "source_key" in t else t["id"]: t for t in owner.get("/api/transactions?page_size=200").json()["items"]}


def by_merchant(owner):
    out = {}
    for t in owner.get("/api/transactions?page_size=200").json()["items"]:
        out.setdefault(t["merchant"], []).append(t)
    return out


def test_rules_assign_categories_without_touching_the_import_and_manual_wins(owner, db):
    rows = [booking("a", "-20", **{"Empfänger": "Kunde Beispiel GmbH", "Kategorie": "Buecher"}),
            booking("b", "300", day="2026-01-20", **{"Empfänger": "Kunde Beispiel GmbH", "Kategorie": "Buecher"}),
            booking("c", "-9", day="2026-01-21", **{"Empfänger": "Anderer Laden", "Kategorie": "Food"})]
    assert upload(owner, rows).status_code == 200
    assert owner.post("/api/category-rules", json={"name": "x"}).status_code == 422, "category required"
    assert owner.post("/api/category-rules", json={"name": "x", "category": "Gewerbe"}).status_code == 422, "needs a condition"
    assert owner.post("/api/category-rules", json={"name": "x", "category": "Gewerbe", "pattern": "a", "account_id": "nope"}).status_code == 422
    r = owner.post("/api/category-rules", json={"name": "Kunde Einnahme", "category": "Gewerbe-Einnahmen", "pattern": "KUNDE", "flow": "income"})
    assert r.status_code == 201 and r.json()["matches"] == 1 and r.json()["reapplied"] == 1
    owner.post("/api/category-rules", json={"name": "Kunde Ausgabe", "category": "Gewerbe-Kosten", "pattern": "kunde", "flow": "expense", "position": 1})
    items = by_merchant(owner)
    inc = next(t for t in items["Kunde Beispiel GmbH"] if D(t["amount"]) > 0)
    exp = next(t for t in items["Kunde Beispiel GmbH"] if D(t["amount"]) < 0)
    assert inc["effective_category"] == "Gewerbe-Einnahmen" and exp["effective_category"] == "Gewerbe-Kosten"
    assert items["Anderer Laden"][0]["effective_category"] == "Food"
    tx = db.scalar(select(Transaction).where(Transaction.merchant == "Anderer Laden"))
    assert tx.category == "Food" and tx.rule_category is None
    rule_tx = db.scalar(select(Transaction).where(Transaction.amount == D(300)))
    assert rule_tx.category == "Buecher", "the imported category is untouched"
    # a manual correction beats the rule
    assert owner.patch(f"/api/transactions/{inc['id']}", json={"category_override": "Manuell"}).status_code == 200
    assert next(t for t in by_merchant(owner)["Kunde Beispiel GmbH"] if D(t["amount"]) > 0)["effective_category"] == "Manuell"
    # filter by the effective category
    assert [t["merchant"] for t in owner.get("/api/transactions?category=Gewerbe-Kosten").json()["items"]] == ["Kunde Beispiel GmbH"]


def test_rule_changes_and_deletion_reapply_and_validate(owner):
    assert upload(owner, [booking("a", "-5", **{"Empfänger": "Muster Markt", "Kategorie": "Food"})]).status_code == 200
    rid = owner.post("/api/category-rules", json={"name": "Markt", "category": "Haushalt", "pattern": "markt"}).json()["id"]
    assert by_merchant(owner)["Muster Markt"][0]["effective_category"] == "Haushalt"
    assert owner.patch(f"/api/category-rules/{rid}", json={"pattern": ""}).status_code == 422, "no condition left"
    assert owner.patch(f"/api/category-rules/{rid}", json={"category": None}).status_code == 422
    assert owner.patch(f"/api/category-rules/{rid}", json={"category": "Lebensmittel"}).json()["category"] == "Lebensmittel"
    assert by_merchant(owner)["Muster Markt"][0]["effective_category"] == "Lebensmittel"
    assert len(owner.get("/api/category-rules").json()) == 1 and owner.get("/api/category-rules").json()[0]["matches"] == 1
    assert owner.delete(f"/api/category-rules/{rid}").json()["reapplied"] == 1
    assert by_merchant(owner)["Muster Markt"][0]["effective_category"] == "Food"
    assert owner.delete(f"/api/category-rules/{rid}").status_code == 404


def test_rules_feed_the_analytics_categories_and_survive_reimports(owner):
    rows = [booking(f"s{i}", "-30", day=f"2026-0{i}-10", **{"Empfänger": "Beispiel Shop", "Kategorie": "Shopping"}) for i in range(1, 7)]
    assert upload(owner, rows).status_code == 200
    owner.post("/api/category-rules", json={"name": "Shop", "category": "Arbeitsmittel", "pattern": "beispiel shop"})
    more = rows + [booking("s7", "-30", day="2026-07-10", **{"Empfänger": "Beispiel Shop", "Kategorie": "Shopping"})]
    assert upload(owner, more).status_code == 200
    assert {t["effective_category"] for t in by_merchant(owner)["Beispiel Shop"]} == {"Arbeitsmittel"}, "the new booking got the rule too"
    overview = owner.get("/api/overview?start=2026-01-01&end=2026-12-31").json()
    assert [c["category"] for c in overview["categories"]] == ["Arbeitsmittel"]


def make_pair(owner):
    sav = {"Konto-ID": "synthetic-second", "Konto": "Second"}
    assert upload(owner, [booking("out", "-250", day="2026-03-10", **{"Empfänger": "Mein Sparkonto"})]).status_code == 200
    assert upload(owner, [booking("in", "250", day="2026-03-11", **{**sav, "Empfänger": "Mein Girokonto"})]).status_code == 200
    for account in owner.get("/api/accounts").json():
        assert owner.patch(f"/api/accounts/{account['id']}", json={"ownership": "owned"}).status_code == 200


def test_transfer_review_lists_auto_pairs_and_rejections_persist(owner, db):
    make_pair(owner)
    assert owner.post("/api/transfers/detect").json()["pairs"] == 1
    review = owner.get("/api/transfers/review").json()
    assert review["total"] == 1 and review["rejections"] == []
    pair = review["pairs"][0]
    assert D(pair["amount"]) == 250 and {pair["inflow"]["account"], pair["outflow"]["account"]} == {"Synthetic checking", "Second"}
    assert pair["inflow"]["flagged_by_source"] is False
    assert owner.post("/api/transfers/reject", json={"key": "does|not-exist"}).status_code == 404
    result = owner.post("/api/transfers/reject", json={"key": pair["key"]})
    assert result.status_code == 200 and result.json()["rejected"] == pair["key"]
    assert db.query(Transaction).filter(Transaction.transfer_auto.is_(True)).count() == 0
    assert db.query(Transaction).filter(Transaction.is_transfer.is_(True)).count() == 0, "both bookings count again"
    after = owner.get("/api/transfers/review").json()
    assert after["total"] == 0 and len(after["rejections"]) == 1 and after["rejections"][0]["label"] == "Synthetic checking → Second"
    # a re-run (and a re-import) never marks the rejected pair again
    assert owner.post("/api/transfers/detect").json()["newly_marked"] == 0
    assert upload(owner, [booking("out", "-250", day="2026-03-10", **{"Empfänger": "Mein Sparkonto"}), booking("extra", "-1", day="2026-03-12")]).status_code == 200
    assert db.query(Transaction).filter(Transaction.transfer_auto.is_(True)).count() == 0
    # restoring the rejection detects the pair again
    restored = owner.delete(f"/api/transfers/rejections/{after['rejections'][0]['id']}")
    assert restored.status_code == 200 and restored.json()["newly_marked"] == 2
    assert owner.get("/api/transfers/review").json()["total"] == 1
    assert owner.delete(f"/api/transfers/rejections/{after['rejections'][0]['id']}").status_code == 404


def test_new_endpoints_require_login(client):
    for method, path in (("get", "/api/category-rules"), ("get", "/api/transfers/review")):
        assert getattr(client, method)(path).status_code in {401, 403}
