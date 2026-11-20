"""Spending straight from pots counts; mirror accounts (PayPal) never double count. Synthetic data only."""
from datetime import date
from decimal import Decimal as D

from sqlalchemy import select

from app.models import User
from app.wishlist import baseline
from conftest import booking
from test_wishlist import workbook

POT = {"Konto-ID": "synthetic-pot", "Konto": "Synthetic groceries pot"}
MIRROR = {"Konto-ID": "synthetic-mirror", "Konto": "synthetic@example.test"}


def setup(owner, purposes):
    workbook(owner, [
        booking("pot-spend", "-300", day="2026-03-10", **POT, **{"Kategorie": "Lebensmittel"}),
        booking("pot-in", "50", day="2026-03-11", **POT, **{"Kategorie": "Zinsen"}),
        booking("pot-fill", "370", day="2026-03-01", **POT, **{"Umbuchung": "Ja"}),
        booking("mirror", "-2000", day="2026-03-15", **MIRROR, **{"Kategorie": "Shopping", "Kontostand": "0"}),
    ])
    accounts = {a["name"]: a for a in owner.get("/api/accounts").json()}
    for name, purpose in purposes.items():
        assert owner.patch(f"/api/accounts/{accounts[name]['id']}", json={"ownership": "owned", "purpose": purpose}).status_code == 200
    return accounts


def test_baseline_counts_pot_spending_and_ignores_mirrors(owner, db):
    setup(owner, {"Synthetic groceries pot": "savings", "synthetic@example.test": "mirror"})
    base = baseline(db, db.scalar(select(User.id)), today=date(2026, 7, 5))
    # workbook: 2000/month checking spending over 6 months; + 300 from the pot once; mirror -2000 ignored
    assert base["monthly_consumption"] == D(2000) + D(300) / 6
    assert base["monthly_income"] == D(3000)  # pot interest and pot refills are not income


def test_overview_ignores_mirror_bookings(owner):
    setup(owner, {"Synthetic groceries pot": "savings", "synthetic@example.test": "mirror"})
    data = owner.get("/api/overview", params={"start": "2026-03-01", "end": "2026-03-31"}).json()
    eur = next(c for c in data["currencies"] if c["currency"] == "EUR")
    assert D(eur["expenses"]) == D(2300)


def test_mirror_is_suggested_for_paypal_like_names():
    from app.account_setup import suggest
    assert suggest("PayPal", None, 10, 0)["purpose"] == "mirror"
    assert suggest("someone@example.test", None, 10, 0)["purpose"] == "mirror"
    assert suggest("Girokonto", None, 10, 0)["purpose"] == "checking"
