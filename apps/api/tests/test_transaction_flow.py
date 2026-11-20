"""Transaction detail shows own account and the counter account of a transfer. Synthetic only."""
from conftest import booking, upload

MAIN = {"Konto-ID": "synthetic-main", "Konto": "Synthetic main"}
POT = {"Konto-ID": "synthetic-tax", "Konto": "Synthetic tax pot"}


def test_transaction_detail_names_account_and_transfer_counterpart(owner):
    rows = [booking("t-out", "-180", day="2026-10-01", **MAIN, **{"Umbuchung": "Ja", "Empfänger": "Synthetic me"}),
            booking("t-in", "180", day="2026-10-02", **POT, **{"Umbuchung": "Ja", "Empfänger": "Synthetic me"})]
    assert upload(owner, rows).status_code == 200
    out = next(t for t in owner.get("/api/transactions", params={"limit": 50}).json()["items"] if float(t["amount"]) == -180)
    detail = owner.get(f"/api/transactions/{out['id']}").json()
    assert detail["account"]["name"] == "Synthetic main"
    assert detail["counterpart"]["account_name"] == "Synthetic tax pot" and detail["counterpart"]["booking_date"] == "2026-10-02"
