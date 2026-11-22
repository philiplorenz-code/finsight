"""Contract terms and cancellation deadlines, synthetic data only."""
from datetime import date

import pytest

import app.contract_terms as ct
import app.finance as finance
from conftest import booking, upload


@pytest.fixture(autouse=True)
def today(monkeypatch):
    fixed = lambda db, user_id: date(2026, 7, 10)  # noqa: E731
    for module in (finance, ct):
        monkeypatch.setattr(module, "local_today", fixed)


def test_next_deadline_rolls_with_renewal():
    term = ct.ContractTerm(term_end=date(2026, 3, 31), notice_days=90, renew_months=12)
    assert ct.next_deadline(term, date(2026, 7, 10)) == {"term_end": "2027-03-31", "cancel_by": "2026-12-31", "days_left": 174, "expired": False}
    fixed = ct.ContractTerm(term_end=date(2026, 3, 31), notice_days=30, renew_months=0)
    assert ct.next_deadline(fixed, date(2026, 7, 10))["expired"] is True


def test_terms_api_and_upcoming(owner):
    rows = [booking(f"g{m}", "-30", day=f"2026-0{m}-05", **{"Empfänger": "Synthetic Gym", "Kategorie": "Sport"}) for m in range(1, 7)]
    assert upload(owner, rows).status_code == 200
    for a in owner.get("/api/accounts").json():
        owner.patch(f"/api/accounts/{a['id']}", json={"ownership": "owned"})
    key = next(i["key"] for i in owner.get("/api/contracts").json()["items"] if i["name"] == "Synthetic Gym")
    saved = owner.put("/api/contract-terms", params={"key": key}, json={"term_end": "2026-08-31", "notice_days": 30, "renew_months": 12, "note": "Synthetic"}).json()
    assert saved["cancel_by"] == "2026-08-01" and saved["name"] == "Synthetic Gym" and saved["days_left"] == 22
    assert [d["key"] for d in owner.get("/api/contract-terms").json()["items"]] == [key]
    assert owner.put("/api/contract-terms", params={"key": key}, json={"notice_days": -1}).status_code == 422
    assert owner.delete("/api/contract-terms", params={"key": key}).status_code == 204
    assert owner.delete("/api/contract-terms", params={"key": key}).status_code == 404
