"""MCP drilldowns and the authenticated explorer must resolve the same view."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import mcp_tools
from app.models import Account, Transaction, User
from conftest import booking, upload


@pytest.mark.parametrize("view", ["all_transactions", "included_spending", "owned_liquid"])
def test_explorer_and_mcp_canonical_view_match(owner, db, view):
    rows = []
    kinds = [("owned", "-10"), ("transfer", "-7"), ("external", "-13"),
             ("excluded", "-17"), ("investment", "-19"), ("unknown", "-23"),
             ("parent", "-29"), ("foreign-currency", "-31")]
    for kind, amount in kinds:
        rows.append(booking(ident="synthetic-" + kind, amount=amount,
                            **{"Konto-ID": "TEST-" + kind, "Konto": "TEST-" + kind,
                               "Währung": "USD" if kind == "foreign-currency" else "EUR",
                               "Umbuchung": "Ja" if kind == "transfer" else "Nein"}))
    assert upload(owner, rows).status_code == 200
    for account in db.scalars(select(Account)):
        kind = account.name.removeprefix("TEST-")
        account.ownership = "external" if kind == "external" else "unknown" if kind == "unknown" else "owned"
        account.included = kind != "excluded"
        account.purpose = "investment" if kind == "investment" else "checking"
    db.scalar(select(Transaction).join(Account).where(Account.name == "TEST-parent")).split_role = "parent"
    db.commit()
    user_id = db.scalar(select(User.id))
    query = mcp_tools.Query(start="2026-01-01", end="2026-01-31", currency="EUR", view=view)
    desc = mcp_tools.descriptor(query, date(2026, 1, 1), date(2026, 1, 31))
    response = owner.get("/api" + desc.transactions_link)
    assert response.status_code == 200
    actual = response.json()
    expected = list(db.scalars(mcp_tools.tx_query(user_id, query, date(2026, 1, 1), date(2026, 1, 31))))
    assert {row["id"] for row in actual["items"]} == {row.id for row in expected}
    assert actual["total"] == len(expected)
    total = mcp_tools.totals(db, user_id, query, date(2026, 1, 1), date(2026, 1, 31))
    assert sum((-Decimal(row["amount"]) for row in actual["items"]), Decimal(0)) == Decimal(total.expenses)
    assert len(expected) == {"all_transactions": 7, "included_spending": 3, "owned_liquid": 1}[view]


def test_explorer_rejects_unknown_view(owner):
    assert owner.get("/api/transactions?view=unrestricted_sql").status_code == 422
