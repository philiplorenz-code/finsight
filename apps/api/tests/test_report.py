"""Monthly close report, synthetic data only."""
from datetime import date
from decimal import Decimal as D

import pytest

import app.finance as finance
import app.report as report
from conftest import booking, upload


@pytest.fixture(autouse=True)
def today(monkeypatch):
    fixed = lambda db, user_id: date(2026, 7, 10)  # noqa: E731
    for module in (finance, report):
        monkeypatch.setattr(module, "local_today", fixed)


def test_monthly_report_compares_with_previous_and_average(owner):
    rows = []
    for m in range(1, 7):
        rows.append(booking(f"in{m}", "3000", day=f"2026-{m:02d}-01", **{"Empfänger": "Synthetic Employer"}))
        rows.append(booking(f"food{m}", "-400", day=f"2026-{m:02d}-10", **{"Kategorie": "Lebensmittel"}))
    rows.append(booking("big", "-900", day="2026-06-15", **{"Kategorie": "Einrichtung", "Empfänger": "Synthetic Moebel"}))
    assert upload(owner, rows).status_code == 200
    for a in owner.get("/api/accounts").json():
        owner.patch(f"/api/accounts/{a['id']}", json={"ownership": "owned"})
    data = owner.get("/api/reports/monthly").json()
    assert data["month"] == "2026-06" and data["complete"] is True
    assert D(data["income"]) == 3000 and D(data["expenses"]) == 1300 and D(data["previous"]["expenses"]) == 400
    assert data["biggest"][0]["merchant"] == "Synthetic Moebel"
    assert data["categories"][0]["category"] == "Einrichtung"
    assert any(h["kind"] == "spending_high" for h in data["highlights"])
    assert owner.get("/api/reports/monthly", params={"month": "2026-13"}).status_code == 422
