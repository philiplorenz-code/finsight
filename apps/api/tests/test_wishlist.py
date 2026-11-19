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


def test_income_rules_split_sources_and_validate(owner, db):
    workbook(owner, [booking("biz", "1200", day="2026-04-05", **{"Empfänger": "Kunde GmbH"}),
                     booking("pay", "500", day="2026-05-05", **{"Empfänger": "Bauhaus AG", "Verwendungszweck": "Gehalt"})])
    base = baseline(db, user_id(db), today=date(2026, 7, 5))
    assert base["income_sources"]["other"]["monthly_average"] == D(3000) + D(1700) / 6
    assert {x["merchant"] for x in base["unassigned_income"]} >= {"Kunde GmbH", "Bauhaus AG"}
    assert owner.post("/api/income-rules", json={"name": "x", "source": "business"}).status_code == 422
    assert owner.post("/api/income-rules", json={"name": "x", "source": "bogus", "pattern": "a"}).status_code == 422
    assert owner.post("/api/income-rules", json={"name": "x", "source": "business", "pattern": "a",
                                                  "account_id": "nope"}).status_code == 422
    r = owner.post("/api/income-rules", json={"name": "Bauhaus", "source": "employment", "pattern": "bauhaus",
                                               "match_field": "merchant", "position": 0})
    assert r.status_code == 201
    owner.post("/api/income-rules", json={"name": "Gewerbe", "source": "business", "pattern": "kunde", "position": 1})
    base = baseline(db, user_id(db), today=date(2026, 7, 5))
    src = base["income_sources"]
    assert src["employment"]["monthly_average"] == D(500) / 6
    assert src["business"]["monthly_average"] == D(1200) / 6
    assert src["other"]["monthly_average"] == D(3000)
    assert base["monthly_income"] == D(3000) + D(1700) / 6
    assert sum(s["share"] for s in src.values()) == D(1) or abs(sum(s["share"] for s in src.values()) - 1) < D("0.0001")
    rid = r.json()["id"]
    assert owner.patch(f"/api/income-rules/{rid}", json={"pattern": "", "account_id": None}).status_code == 422
    assert owner.patch(f"/api/income-rules/{rid}", json={"source": "business"}).json()["source"] == "business"
    assert len(owner.get("/api/income-rules").json()) == 2
    assert owner.delete(f"/api/income-rules/{rid}").status_code == 200
    assert owner.delete(f"/api/income-rules/{rid}").status_code == 404


def test_analytics_series_align_with_baseline(owner, db):
    workbook(owner, [booking("shop", "-100", day="2026-03-10", **{"Kategorie": "Einkaufen", "Empfänger": "Laden"})])
    data = owner.get("/api/analytics").json()
    s = data["series"]
    n = data["months_used"]
    assert n == 6 and len(s["months"]) == n and len(s["expenses"]) == n and len(s["surplus"]) == n
    assert all(len(v) == n for v in s["income"].values()) and all(len(v) == n for v in s["categories"].values())
    assert D(s["expenses"][2]) == D(2100)
    assert D(s["categories"]["Einkaufen"][2]) == D(100)
    assert s["top_merchants"] and D(s["top_merchants"][0]["total"]) > 0
    assert "series" not in owner.get("/api/wishlist").json()["baseline"]
    assert owner.get("/api/analytics?currency=eur").status_code == 422


def test_month_end_pay_counts_for_following_month(owner, db):
    workbook(owner, [booking("p3", "1000", day="2026-03-30", **{"Empfänger": "Bauhaus AG"}),
                     booking("p6", "1000", day="2026-06-30", **{"Empfänger": "Bauhaus AG"}),
                     booking("p2", "400", day="2026-02-10", **{"Empfänger": "Bauhaus AG"})])
    base_rule = {"name": "Bauhaus", "source": "employment", "pattern": "bauhaus", "match_field": "merchant"}
    assert owner.post("/api/income-rules", json={**base_rule, "shift_from_day": 40}).status_code == 422
    rid = owner.post("/api/income-rules", json=base_rule).json()["id"]
    plain = owner.get("/api/analytics").json()["series"]["income"]["employment"]
    assert [D(x) for x in plain] == [0, 400, 1000, 0, 0, 1000]
    assert owner.patch(f"/api/income-rules/{rid}", json={"shift_from_day": 25}).json()["shift_from_day"] == 25
    shifted = owner.get("/api/analytics").json()["series"]["income"]["employment"]
    assert [D(x) for x in shifted] == [0, 400, 0, 1000, 0, 0], "30 Mar counts for April; 30 Jun leaves the window"
    assert owner.patch(f"/api/income-rules/{rid}", json={"shift_from_day": None}).json()["shift_from_day"] is None
    assert [D(x) for x in owner.get("/api/analytics").json()["series"]["income"]["employment"]] == [0, 400, 1000, 0, 0, 1000]


def test_transfer_detection_pairs_owned_accounts_and_keeps_salary(owner, db):
    from app.models import Account, Transaction
    workbook(owner)
    sav = {"Konto-ID": "savings-2", "Konto": "Savings"}
    assert upload(owner, [booking("t-in", "700", day="2026-03-12", **sav),
                          booking("pay-in", "800", day="2026-04-05", **{**sav, "Empfänger": "Bauhaus AG"})]).status_code == 200
    assert upload(owner, [booking("t-out", "-700", day="2026-03-10"),
                          booking("rent", "-800", day="2026-04-06", **{"Empfänger": "Vermieter"})]).status_code == 200
    accounts = {a["name"]: a for a in owner.get("/api/accounts").json()}
    assert owner.patch(f"/api/accounts/{accounts['Savings']['id']}", json={"ownership": "owned"}).status_code == 200
    assert owner.post("/api/income-rules", json={"name": "B", "source": "employment", "pattern": "bauhaus"}).status_code == 201

    dry = owner.post("/api/transfers/detect?dry_run=true").json()
    assert dry["applied"] is False and dry["pairs"] == 1, "salary must not pair with rent"
    assert db.query(Transaction).filter(Transaction.transfer_auto.is_(True)).count() == 0
    done = owner.post("/api/transfers/detect").json()
    assert done["pairs"] == 1 and done["newly_marked"] == 2
    db.expire_all()
    marked = {t.source_key for t in db.query(Transaction).filter(Transaction.transfer_auto.is_(True))}
    assert len(marked) == 2
    assert not any(t.is_transfer for t in db.query(Transaction).filter(Transaction.merchant.in_(["Bauhaus AG", "Vermieter"])))
    again = owner.post("/api/transfers/detect").json()
    assert again["pairs"] == 1 and again["newly_marked"] == 2, "recomputed from scratch, same result"


def test_savings_insights_fixed_variable_and_potential(owner, db):
    from app.savings import is_fixed, savings_insights
    months = [date(2026, m, 1) for m in range(1, 9)]
    by_cat = {m: {"Miete": D(800), "Essen": D(200) if i < 5 else D(350), "Einmalig": D(900) if i == 2 else D(0)}
              for i, m in enumerate(months)}
    out = savings_insights(months, by_cat, {"items": [{"name": "Netflix", "monthly_cost": "12", "period": "monthly", "source": "export"}]})
    assert out["enough_data"] and out["recurring_monthly"] == D(12)
    cats = {c["category"]: c for c in out["categories"]}
    assert cats["Miete"]["fixed"] and not cats["Essen"]["fixed"]
    assert cats["Essen"]["delta"] == D(350) - D(200), "last 3 months against the 5 before"
    assert out["potential_monthly"] == D(150) and out["potential_categories"] == ["Essen"]
    assert "Einmalig" not in out["potential_categories"], "a single one-off month is not a trend"
    assert out["fixed_monthly"] == D(800)
    assert len(out["fixed_by_month"]) == len(out["variable_by_month"]) == 8
    assert not is_fixed([D(100), D(0), D(0), D(100)])
    short = savings_insights(months[:3], {m: by_cat[m] for m in months[:3]})
    assert short["enough_data"] is False and short["potential_monthly"] == 0


def test_analytics_includes_savings_but_wishlist_does_not(owner):
    workbook(owner)
    data = owner.get("/api/analytics").json()
    assert data["savings"]["enough_data"] is True and "categories" in data["savings"]
    assert "savings" not in owner.get("/api/wishlist").json()["baseline"]


def test_savings_rent_with_gap_and_spike_is_fixed_not_a_trend():
    from app.savings import savings_insights
    rent = [950, 950, 950, 950, 950, 950, 950, 0, 0, 950, 950, 1260]
    months = [date(2025 + (m > 11), (m % 12) + 1, 1) for m in range(12)]
    out = savings_insights(months, {m: {"Miete": D(rent[i])} for i, m in enumerate(months)})
    row = out["categories"][0]
    assert row["fixed"] and row["delta"] == 0
    assert out["potential_monthly"] == 0 and out["fixed_monthly"] > 0


def test_business_rules_split_expenses_and_make_conservative_cautious(owner, db):
    extra = [booking("biz-in", "3000", day="2026-02-10", **{"Empfänger": "Kunde GmbH"}),
             booking("biz-in2", "3000", day="2026-05-10", **{"Empfänger": "Kunde GmbH"}),
             booking("biz-out", "-400", day="2026-02-12", **{"Empfänger": "Hosting AG", "Kategorie": "Arbeit"}),
             booking("biz-out2", "-100", day="2026-03-12", **{"Empfänger": "Kleinkram", "Kategorie": "Arbeit"})]
    workbook(owner, extra)
    assert owner.post("/api/income-rules", json={"name": "K", "source": "business", "pattern": "kunde"}).status_code == 201
    before = baseline(db, user_id(db), today=date(2026, 7, 5))
    assert owner.post("/api/business-rules", json={"name": "x"}).status_code == 422, "needs a condition"
    assert owner.post("/api/business-rules", json={"name": "x", "pattern": "a", "account_id": "nope"}).status_code == 422
    r = owner.post("/api/business-rules", json={"name": "Hosting", "pattern": "hosting", "match_field": "merchant"})
    assert r.status_code == 201
    assert owner.post("/api/business-rules", json={"name": "Arbeit", "category": "arbeit", "position": 1}).status_code == 201
    after = baseline(db, user_id(db), today=date(2026, 7, 5))
    assert after["expected_surplus"] == before["expected_surplus"], "rules only split, totals unchanged"
    assert after["monthly_consumption"] == D(2000), "business spending left private consumption"
    assert after["business"]["expenses_monthly"] == D(500) / 6
    assert after["business"]["income_monthly"] == D(6000) / 6
    assert after["business"]["profit_monthly"] == D(5500) / 6
    assert after["business"]["tax_reserve_suggestion"] == D(5500) / 6 * D("0.30")
    assert after["conservative_surplus"] < before["conservative_surplus"] or after["conservative_surplus"] <= after["expected_surplus"]
    series = owner.get("/api/analytics").json()["series"]
    assert [D(x) for x in series["business_expenses"]] == [0, 400, 100, 0, 0, 0]
    assert "Arbeit" not in series["categories"]
    rid = r.json()["id"]
    assert owner.patch(f"/api/business-rules/{rid}", json={"pattern": ""}).status_code == 422, "no condition left"
    assert owner.patch(f"/api/business-rules/{rid}", json={"category": "Arbeit"}).json()["category"] == "Arbeit"
    assert owner.patch(f"/api/business-rules/{rid}", json={"name": None}).status_code == 422
    assert len(owner.get("/api/business-rules").json()) == 2
    assert owner.delete(f"/api/business-rules/{rid}").status_code == 200
    assert owner.delete(f"/api/business-rules/{rid}").status_code == 404


def test_full_snapshot_confirms_balance_freshness(owner, db):
    from app.models import Account
    assert upload(owner, [booking("old", "10", day="2026-01-05", **{"Kontostand": "100"})]).status_code == 200
    account = owner.get("/api/accounts").json()[0]
    assert owner.patch(f"/api/accounts/{account['id']}", json={"ownership": "owned"}).status_code == 200
    assert owner.get("/api/net-worth").json()["stale_balances"] == 1, "last booking is months old"
    partial = upload(owner, [booking("old", "10", day="2026-01-05", **{"Kontostand": "100"}), booking("n1", "5", day="2026-01-06", **{"Kontostand": "105"})])
    assert partial.status_code == 200 and owner.get("/api/net-worth").json()["stale_balances"] == 1, "a non-full import confirms nothing"
    full = upload(owner, [booking("old", "10", day="2026-01-05", **{"Kontostand": "100"}), booking("n2", "7", day="2026-01-07", **{"Kontostand": "112"})],
                  data={"full_snapshot": "true"})
    assert full.status_code == 200
    db.expire_all()
    assert db.query(Account).one().confirmed_through is not None
    assert owner.get("/api/net-worth").json()["stale_balances"] == 0, "the account is in the latest full import"
