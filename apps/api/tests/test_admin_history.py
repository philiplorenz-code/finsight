"""Synthetic-only: obligation editing, allocation history and revision diffs."""
from decimal import Decimal

from conftest import booking, upload


def test_obligation_can_be_edited_and_cleared(owner):
    bucket = owner.post("/api/buckets", json={"name": "Reserve", "kind": "virtual", "currency": "EUR"}).json()
    ob = owner.post(f"/api/buckets/{bucket['id']}/obligations", json={"name": "Versicherung", "amount": "120", "period": "yearly",
                                                                       "due_date": "2027-03-01"}).json()
    url = f"/api/buckets/{bucket['id']}/obligations/{ob['id']}"
    changed = owner.patch(url, json={"amount": "150", "name": "Haftpflicht", "due_date": None})
    assert changed.status_code == 200 and Decimal(changed.json()["amount"]) == 150 and changed.json()["due_date"] is None
    assert owner.patch(url, json={"amount": None}).status_code == 422
    assert owner.patch(url, json={"amount": "0"}).status_code == 422
    assert owner.patch(f"/api/buckets/{bucket['id']}/obligations/missing", json={"name": "x"}).status_code == 404


def test_allocation_history_is_append_only(owner):
    assert upload(owner, [booking("a", "10", **{"Kontostand": "1000"})]).status_code == 200
    account = owner.get("/api/accounts").json()[0]
    owner.patch(f"/api/accounts/{account['id']}", json={"ownership": "owned"})
    bucket = owner.post("/api/buckets", json={"name": "Urlaub", "kind": "virtual", "currency": "EUR"}).json()
    put = lambda amount: owner.put(f"/api/buckets/{bucket['id']}/allocations", json={"allocations": [{"account_id": account["id"], "amount": amount}]})
    assert put("100").status_code == 200 and put("250").status_code == 200
    assert owner.put(f"/api/buckets/{bucket['id']}/allocations", json={"allocations": []}).status_code == 200
    history = owner.get(f"/api/buckets/{bucket['id']}/allocation-history").json()
    assert [Decimal(h["amount"]) for h in history] == [0, 250, 100]
    assert history[1]["account_name"] and history[1]["bucket_name"] == "Urlaub"
    owner.delete(f"/api/buckets/{bucket['id']}")
    assert len(owner.get(f"/api/buckets/{bucket['id']}/allocation-history").json()) == 3, "deleting a bucket keeps its history"


def test_revision_diff_names_changed_columns(owner):
    assert upload(owner, [booking("r1", "-10", **{"Verwendungszweck": "Version one"})]).status_code == 200
    assert upload(owner, [booking("r1", "-10", **{"Verwendungszweck": "Version two"})]).status_code == 200
    tx = owner.get("/api/transactions").json()["items"][0]
    revisions = owner.get(f"/api/transactions/{tx['id']}/revisions").json()
    assert len(revisions) == 1
    changes = {c["column"]: (c["was"], c["now"]) for c in revisions[0]["changes"]}
    assert changes["Verwendungszweck"] == ("Version one", "Version two")
    assert owner.get("/api/transactions/unknown/revisions").status_code == 404
