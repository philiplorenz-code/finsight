"""Synthetic-only as-of reconstruction: no future data, explicit flags, versioned settings and earmarks."""
from datetime import date, timedelta
from decimal import Decimal

from conftest import booking, upload

D = Decimal


def seed(owner):
    rows = [booking("a", "10", day="2026-01-10", **{"Kontostand": "1000"}),
            booking("b", "10", day="2026-03-10", **{"Kontostand": "2000"})]
    assert upload(owner, rows).status_code == 200
    account = owner.get("/api/accounts").json()[0]
    assert owner.patch(f"/api/accounts/{account['id']}", json={"ownership": "owned"}).status_code == 200
    return account


def view(owner, day):
    return owner.get("/api/as-of", params={"date": day}).json()


def test_balance_never_uses_future_observations(owner):
    seed(owner)
    assert D(view(owner, "2026-02-01")["accounts"][0]["balance"]) == 1000
    assert D(view(owner, "2026-03-15")["accounts"][0]["balance"]) == 2000
    early = view(owner, "2025-12-01")["accounts"][0]
    assert early["flags"] == ["no_opening_balance"] and "balance" not in early
    assert any("no balance" in w for w in view(owner, "2025-12-01")["warnings"])
    assert owner.get("/api/as-of", params={"date": (date.today() + timedelta(days=1)).isoformat()}).status_code == 422


def test_conflicting_same_day_balances_are_flagged(owner):
    rows = [booking("a", "10", day="2026-01-10", **{"Kontostand": "1000"}), booking("b", "5", day="2026-01-10", **{"Kontostand": "1005"})]
    assert upload(owner, rows).status_code == 200
    account = owner.get("/api/accounts").json()[0]
    owner.patch(f"/api/accounts/{account['id']}", json={"ownership": "owned"})
    row = view(owner, "2026-01-20")["accounts"][0]
    # the importer keeps one observation per account and day, so the view reports a single value without a conflict flag
    assert D(row["balance"]) == 1005 and "ambiguous_same_day" not in row["flags"]


def test_settings_history_is_used_for_the_past(owner):
    account = seed(owner)
    # Changed to external now: today it no longer counts, but the history says it was owned before.
    owner.patch(f"/api/accounts/{account['id']}", json={"ownership": "external"})
    now_view = view(owner, date.today().isoformat())
    assert now_view["accounts"] == []
    past = view(owner, "2026-02-01")["accounts"]
    assert len(past) == 1 and D(past[0]["balance"]) == 1000, "the account counted as owned when the past view is taken"


def test_change_history_before_first_change_uses_before_state(owner, db):
    from app.asof import settings_on
    from app.models import Account, AccountChange
    account = seed(owner)
    stored = db.get(Account, account["id"])
    changes = db.query(AccountChange).filter_by(account_id=account["id"]).all()
    assert len(changes) == 1 and changes[0].before["ownership"] == "unknown" and changes[0].after["ownership"] == "owned"
    state, versioned = settings_on(stored, changes, date(2000, 1, 1))
    assert versioned and state["ownership"] == "owned", "'unknown' is an undecided state: the first decision applies retroactively"
    assert state["purpose"] == "checking"
    state, _ = settings_on(stored, changes, date.today())
    assert state["ownership"] == "owned"


def test_earmarks_follow_the_allocation_history(owner):
    account = seed(owner)
    bucket = owner.post("/api/buckets", json={"name": "Urlaub", "kind": "virtual", "currency": "EUR"}).json()
    put = lambda items: owner.put(f"/api/buckets/{bucket['id']}/allocations", json={"allocations": items})
    assert put([{"account_id": account["id"], "amount": "300"}]).status_code == 200
    assert put([{"account_id": account["id"], "amount": "500"}]).status_code == 200
    today = view(owner, date.today().isoformat())
    assert [D(e["amount"]) for e in today["earmarked"]] == [500]
    assert view(owner, "2026-02-01")["earmarked"] == [], "allocations made later are not applied to the past"
    assert put([]).status_code == 200
    assert view(owner, date.today().isoformat())["earmarked"] == [], "a release removes the earmark"


def test_same_day_conflict_from_two_imports_is_flagged(owner, db):
    from app.models import Balance, Import, User
    account = seed(owner)
    uid = db.query(User).one().id
    other = Import(user_id=uid, filename="second.xlsx", sha256="c" * 64, status="completed", row_count=0, summary={})
    db.add(other)
    db.flush()
    db.add(Balance(account_id=account["id"], import_id=other.id, observed_date=date(2026, 1, 10), amount=D("1111")))
    db.commit()
    row = view(owner, "2026-02-01")["accounts"][0]
    assert "ambiguous_same_day" in row["flags"]
