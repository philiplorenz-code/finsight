"""Overview places month-end pay in the next month and shows the owner's share of balances. Synthetic only."""
from conftest import booking, upload

MAIN = {"Konto-ID": "synthetic-main", "Konto": "Synthetic main"}
POT = {"Konto-ID": "synthetic-tax", "Konto": "Synthetic tax pot"}


def setup(owner):
    rows = [booking("pay-oct", "3000", day="2026-10-29", **MAIN, **{"Empfänger": "Synthetic Employer"}),
            booking("pay-sep", "3000", day="2026-09-29", **MAIN, **{"Empfänger": "Synthetic Employer"}),
            booking("other", "100", day="2026-10-10", **MAIN, **{"Empfänger": "Synthetic Refund"}),
            booking("bal", "-1", day="2026-10-30", **MAIN, **{"Kontostand": "1000"}),
            booking("tax", "-1", day="2026-10-30", **POT, **{"Kontostand": "500"})]
    assert upload(owner, rows).status_code == 200
    for a in owner.get("/api/accounts").json():
        assert owner.patch(f"/api/accounts/{a['id']}", json={"ownership": "owned", **({"owner_share": 0} if a["name"] == "Synthetic tax pot" else {})}).status_code == 200


def eur(owner, start, end):
    data = owner.get("/api/overview", params={"start": start, "end": end}).json()
    return next(c for c in data["currencies"] if c["currency"] == "EUR"), data


def test_month_end_pay_counts_in_the_following_month(owner):
    setup(owner)
    assert owner.post("/api/income-rules", json={"name": "Job", "source": "employment", "pattern": "Synthetic Employer", "shift_from_day": 20}).status_code == 201
    october, data = eur(owner, "2026-10-01", "2026-10-31")
    november, _ = eur(owner, "2026-11-01", "2026-11-19")
    assert float(october["income"]) == 3100  # September pay + refund, not the October 29 pay
    assert float(november["income"]) == 3000
    assert {t["month"] for t in data["trends"]} == {"2026-10"}


def test_without_shift_rule_booking_date_applies(owner):
    setup(owner)
    november, _ = eur(owner, "2026-11-01", "2026-11-19")
    assert float(november.get("income", 0)) == 0


def test_balances_show_owner_share_and_others_money(owner):
    setup(owner)
    october, _ = eur(owner, "2026-10-01", "2026-10-31")
    assert float(october["observed_balance"]) == 1500 and float(october["observed_mine"]) == 1000 and float(october["held_for_others"]) == 500
