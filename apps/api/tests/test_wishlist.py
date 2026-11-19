"""Synthetic-only wishlist and affordability regressions."""
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models import User, Wish
from app.wishlist import add_months, assess, baseline, complete_months, months_needed
from conftest import booking, upload

D = Decimal


def workbook(owner, extra=()):
    rows = []
    for month in range(1, 7):
        rows.append(booking(f"in-{month}", "3000", day=f"2026-{month:02d}-01"))
        last = month == 6
        rows.append(booking(f"out-{month}", "-2000", day=f"2026-{month:02d}-{'30' if last else '15'}",
                            **({"Kontostand": "5000"} if last else {})))
    rows.extend(extra)
    assert upload(owner, rows).status_code == 200
    account = owner.get("/api/accounts").json()[0]
    assert owner.patch(f"/api/accounts/{account['id']}", json={"ownership": "owned"}).status_code == 200
    return account


def user_id(db):
    return db.query(User).one().id


def test_baseline_excludes_transfers_savings_and_own_transfers(owner, db):
    workbook(owner, [booking("own", "-500", day="2026-03-10", **{"Empfänger": "Me Myself"}),
                     booking("save", "-300", day="2026-03-11", **{"Kategorie": "Sparen"}),
                     booking("move", "-200", day="2026-03-12", **{"Umbuchung": "Ja"})])
    assert owner.put("/api/wishlist/prefs", json={"self_names": ["me myself"], "reserve_months": 3}).status_code == 200
    base = baseline(db, user_id(db), today=date(2026, 7, 5))
    assert base["months_used"] == 6
    assert base["monthly_income"] == D(3000)
    assert base["monthly_consumption"] == D(2000)
    assert base["expected_surplus"] == D(1000) and base["conservative_surplus"] == D(1000)
    assert base["reserve"] == D(6000) and base["cash_on_hand"] == D(5000) and base["usable_cash"] == D(0)
    assert base["confidence"] == "medium"


def test_unclassified_accounts_are_not_counted(owner, db):
    assert upload(owner, [booking("x", "100", day="2026-01-01")]).status_code == 200
    base = baseline(db, user_id(db), today=date(2026, 7, 5))
    assert base["months_used"] == 0 and base["confidence"] == "low"
    assert any("owned" in w for w in base["warnings"])


def test_tax_reserve_lowers_surplus_and_incomplete_month_is_dropped(owner, db):
    workbook(owner, [booking("partial", "-9999", day="2026-07-02")])
    assert owner.put("/api/wishlist/prefs", json={"monthly_tax_reserve": "250"}).status_code == 200
    base = baseline(db, user_id(db), today=date(2026, 7, 5))
    assert base["months_used"] == 6, "July is incomplete and must not distort the average"
    assert base["monthly_consumption"] == D(2000)
    assert base["expected_surplus"] == D(750)


def test_conservative_uses_lower_quartile(owner, db):
    rows = []
    for month in range(1, 7):
        income = "500" if month in (2, 4) else "3000"
        rows.append(booking(f"in-{month}", income, day=f"2026-{month:02d}-01"))
        rows.append(booking(f"out-{month}", "-2000", day=f"2026-{month:02d}-{'30' if month == 6 else '15'}"))
    assert upload(owner, rows).status_code == 200
    account = owner.get("/api/accounts").json()[0]
    owner.patch(f"/api/accounts/{account['id']}", json={"ownership": "owned"})
    base = baseline(db, user_id(db), today=date(2026, 7, 5))
    assert round(base["expected_surplus"], 2) == D("166.67")  # (4 * 1000 - 2 * 1500) / 6
    assert base["conservative_surplus"] == D(-1500)


def wish(name, price, priority=1, **kwargs):
    return Wish(id=name, user_id="u", name=name, price=D(price), currency=kwargs.pop("currency", "EUR"), priority=priority,
                follow_up_monthly_cost=D(kwargs.pop("follow", 0)), created_at=datetime(2026, 1, priority, tzinfo=timezone.utc),
                status=kwargs.pop("status", "open"), due_date=kwargs.pop("due", None))


def base(**kw):
    value = {"currency": "EUR", "usable_cash": D(500), "conservative_surplus": D(400), "expected_surplus": D(1000)}
    value.update(kw)
    return value


def test_verdicts_are_cumulative_in_priority_order():
    today = date(2026, 7, 5)
    wishes = [wish("w4", 90000, 4), wish("w2", 600, 2), wish("w1", 300, 1), wish("w3", 5000, 3), wish("gone", 1, 1, status="dropped")]
    result = {r["id"]: r for r in assess(base(), wishes, today)}
    assert "gone" not in result
    assert result["w1"]["verdict"] == "affordable" and result["w1"]["months_conservative"] == 0
    assert result["w2"]["verdict"] == "save_up" and result["w2"]["months_conservative"] == 1
    assert result["w2"]["cumulative_price"] == D(900)
    assert result["w3"]["verdict"] == "tight"
    assert result["w3"]["months_conservative"] == 14 and result["w3"]["months_expected"] == 6
    assert result["w4"]["verdict"] == "not_now"


def test_no_surplus_never_claims_a_date():
    result = assess(base(conservative_surplus=D(-50), expected_surplus=D(0)), [wish("a", 900)], date(2026, 7, 5))[0]
    assert result["verdict"] == "not_now"
    assert result["months_conservative"] is None and result["date_expected"] is None


def test_due_date_feasibility_and_follow_up_costs():
    today = date(2026, 7, 5)
    result = assess(base(), [wish("a", 1300, due=date(2026, 9, 20), follow=950)], today)[0]
    assert result["months_conservative"] == 2
    assert result["on_time_conservative"] is True
    assert result["required_monthly_for_due_date"] == D(800) / 2
    assert result["surplus_after_follow_up_costs"] == D(50)
    late = assess(base(), [wish("a", 1300, due=date(2026, 7, 20))], today)[0]
    assert late["on_time_conservative"] is False


def test_currency_mismatch_is_not_converted():
    result = assess(base(), [wish("usd", 10, currency="USD")], date(2026, 7, 5))[0]
    assert result["verdict"] == "unsupported_currency"


def test_helpers():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 18), 3) == date(2027, 2, 18)
    assert complete_months(date(2026, 6, 30), 2) == [date(2026, 5, 1), date(2026, 6, 1)]
    assert complete_months(date(2026, 6, 16), 2) == [date(2026, 4, 1), date(2026, 5, 1)]
    assert months_needed(D(100), D(30)) == 4 and months_needed(D(100), D(0)) is None


def test_api_crud_validation_and_isolation(owner, db):
    workbook(owner)
    created = owner.post("/api/wishes", json={"name": "Robot vacuum", "price": "600.00", "priority": 2})
    assert created.status_code == 201 and created.json()["price"] == "600"
    ident = created.json()["id"]
    assert owner.post("/api/wishes", json={"name": "Bad", "price": "0"}).status_code == 422
    assert owner.post("/api/wishes", json={"name": "Bad", "price": "5", "priority": 9}).status_code == 422
    assert owner.post("/api/wishes", json={"name": "Bad", "price": "5", "surprise": 1}).status_code == 422
    listing = owner.get("/api/wishlist").json()
    assert listing["wishes"][0]["assessment"]["verdict"] in {"affordable", "save_up", "tight", "not_now"}
    assert "advice" in listing["disclaimer"]
    patched = owner.patch(f"/api/wishes/{ident}", json={"status": "bought"})
    assert patched.status_code == 200 and owner.get("/api/wishlist").json()["wishes"][0]["assessment"] is None
    stranger = User(id="stranger", owner_slot=2, email="other@example.test", password_hash="x")
    db.add_all([stranger, Wish(id="theirs", user_id="stranger", name="Secret", price=D(1))])
    db.commit()
    assert owner.patch("/api/wishes/theirs", json={"name": "mine"}).status_code == 404
    assert owner.delete("/api/wishes/theirs").status_code == 404
    assert all(w["id"] != "theirs" for w in owner.get("/api/wishlist").json()["wishes"])
    assert owner.delete(f"/api/wishes/{ident}").status_code == 200


def test_wishlist_requires_login(client):
    assert client.get("/api/wishlist").status_code in {401, 403}
