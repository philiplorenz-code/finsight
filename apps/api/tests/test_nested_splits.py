"""Unsupported split graphs fail atomically; synthetic records only."""
from itertools import permutations

import pytest
from sqlalchemy import func, select

from app.importer import digest
from app.models import Account, Balance, Import, Transaction, TransactionRevision
from conftest import booking, upload, xlsx


def chain():
    return {
        "A": booking("synthetic-A", "-100"),
        "B": booking("synthetic-B", "-100", **{"Parent ID": "synthetic-A"}),
        "C": booking("synthetic-C", "-100", **{"Parent ID": "synthetic-B"}),
    }


def financial_state(db):
    return {
        "accounts": [(a.id, a.source_key) for a in db.scalars(select(Account).order_by(Account.id))],
        "transactions": [(t.id, t.amount, t.source, t.split_parent_key, t.split_role, t.is_transfer,
                          t.missing_from_latest, t.import_id) for t in db.scalars(select(Transaction).order_by(Transaction.id))],
        "balances": [(b.id, b.amount) for b in db.scalars(select(Balance).order_by(Balance.id))],
        "revisions": db.scalar(select(func.count()).select_from(TransactionRevision)),
    }


def assert_rejected(response):
    assert response.status_code == 422
    assert response.json() == {"detail": "Unsupported nested, cyclic or self-referencing split relationships; import rejected"}
    assert "synthetic-" not in response.text


@pytest.mark.parametrize("order", list(permutations("ABC")))
def test_nested_chain_rejected_in_all_orders_and_reuploads_without_partial_financial_writes(owner, db, order):
    rows = chain()
    data = xlsx([rows[key] for key in order])
    before = financial_state(db)
    for _ in range(2):
        assert_rejected(owner.post("/api/imports", files={"file": ("synthetic.xlsx", data)}, data={"full_snapshot": "true"}))
        assert financial_state(db) == before
    history = list(db.scalars(select(Import)))
    assert history and all(i.status == "failed" for i in history)


@pytest.mark.parametrize("order", list(permutations("ABC")))
def test_nested_chain_rejected_when_partial_merges_complete_graph_in_any_order(owner, db, order):
    rows = chain()
    for index, key in enumerate(order):
        before = financial_state(db)
        response = upload(owner, [rows[key]])
        if index == 2 or (index == 1 and set(order[:2]) == {"B", "C"}):
            # B->A and C->B is already unsupported even if A is absent.
            assert_rejected(response)
            assert financial_state(db) == before
            assert_rejected(upload(owner, [rows[key]], data={"full_snapshot": "true"}))
            assert financial_state(db) == before
            break
        assert response.status_code == 200


@pytest.mark.parametrize("ids", [("synthetic-A", "synthetic-B"), ("synthetic-B", "synthetic-A")])
def test_two_node_cycle_rejected_in_both_orders_and_partial_import(owner, db, ids):
    first, second = ids
    rows = [booking(first, "-100", **{"Parent ID": second}), booking(second, "-100", **{"Parent ID": first})]
    empty = financial_state(db)
    assert_rejected(upload(owner, rows))
    assert financial_state(db) == empty
    assert upload(owner, [rows[0]]).status_code == 200
    retained = financial_state(db)
    assert_rejected(upload(owner, [rows[1]]))
    assert financial_state(db) == retained


def test_self_loop_rejected_and_revising_existing_root_is_atomic(owner, db):
    self_loop = booking("synthetic-self", "-100", **{"Parent ID": "synthetic-self", "Kontostand": "900"})
    empty = financial_state(db)
    assert_rejected(upload(owner, [self_loop]))
    assert financial_state(db) == empty
    assert upload(owner, [booking("synthetic-self", "-100", **{"Kontostand": "1000"})]).status_code == 200
    retained = financial_state(db)
    assert_rejected(upload(owner, [self_loop], data={"full_snapshot": "true"}))
    assert financial_state(db) == retained


def test_validation_uses_retained_source_links_not_mutable_derived_state(owner, db):
    rows = chain()
    assert upload(owner, [rows["A"], rows["B"]]).status_code == 200
    child = db.scalar(select(Transaction).where(Transaction.source_key == digest(["source", "synthetic-B"])))
    child.split_parent_key = None
    child.split_role = "none"
    db.commit()
    retained = financial_state(db)
    assert_rejected(upload(owner, [rows["C"]]))
    assert financial_state(db) == retained


def test_retained_legacy_nested_source_is_rejected_on_duplicate_but_partial_repair_is_allowed(owner, db):
    rows = chain()
    rows["C"]["Parent ID"] = None
    data = xlsx(list(rows.values()))
    assert owner.post("/api/imports", files={"file": ("synthetic.xlsx", data)}).status_code == 200
    child = db.scalar(select(Transaction).where(Transaction.source_key == digest(["source", "synthetic-C"])))
    # Simulate a legacy source graph while leaving normalized/derived links flat.
    child.source = {**child.source, "columns": {**child.source["columns"], "Parent ID": "synthetic-B"}}
    db.commit()
    retained = financial_state(db)
    assert_rejected(owner.post("/api/imports", files={"file": ("synthetic.xlsx", data)}))
    assert financial_state(db) == retained
    assert upload(owner, [rows["C"]]).status_code == 200
    result = owner.get("/api/overview", params={"start": "2026-01-01", "end": "2026-01-31"}).json()
    assert result["currencies"][0]["expenses"] == "200"


@pytest.mark.parametrize("order", list(permutations("ABC")))
def test_valid_flat_splits_still_reconcile_once_after_partial_and_identical_imports(owner, order):
    rows = chain()
    rows["B"]["Betrag"] = "-60"
    rows["C"].update({"Betrag": "-40", "Parent ID": "synthetic-A"})
    ordered = [rows[key] for key in order]
    data = xlsx(ordered)
    assert owner.post("/api/imports", files={"file": ("synthetic.xlsx", data)}).status_code == 200
    assert owner.post("/api/imports", files={"file": ("synthetic.xlsx", data)}).json()["duplicate"] is True
    for key in order:
        assert upload(owner, [rows[key]]).status_code == 200
        data = owner.get("/api/overview", params={"start": "2026-01-01", "end": "2026-01-31"}).json()
        assert data["currencies"][0]["expenses"] == "100"
