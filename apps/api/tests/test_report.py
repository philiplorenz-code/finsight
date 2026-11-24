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


def test_yearly_report_compares_same_period_last_year(owner):
    rows = []
    for year in (2025, 2026):
        for m in range(1, 8):
            rows.append(booking(f"in{year}{m}", "3000", day=f"{year}-{m:02d}-01", **{"Empfänger": "Synthetic Employer"}))
            rows.append(booking(f"food{year}{m}", "-400" if year == 2026 else "-300", day=f"{year}-{m:02d}-05",
                                **{"Kategorie": "Lebensmittel", "Empfänger": "Synthetic Markt"}))
    rows.append(booking("late2025", "-1000", day="2025-11-20", **{"Kategorie": "Urlaub", "Empfänger": "Synthetic Reisen"}))
    rows.append(booking("new2026", "-120", day="2026-03-03", **{"Kategorie": "Sport", "Empfänger": "Synthetic Gym"}))
    assert upload(owner, rows).status_code == 200
    for a in owner.get("/api/accounts").json():
        owner.patch(f"/api/accounts/{a['id']}", json={"ownership": "owned"})
    data = owner.get("/api/reports/yearly").json()
    assert data["year"] == 2026 and data["running"] is True and data["compared_until"] == "2025-07-10"
    # Jan..Jul 2026 against Jan..Jul 2025: the November trip of 2025 is not part of the comparison
    assert D(data["expenses"]) == 7 * 400 + 120 and D(data["previous"]["expenses"]) == 7 * 300
    food = next(c for c in data["categories"] if c["name"] == "Lebensmittel")
    assert D(food["change"]) == 700
    assert data["merchants"][0]["name"] == "Synthetic Markt" and data["merchants"][0]["count"] == 7
    assert [m["name"] for m in data["new_merchants"]] == ["Synthetic Gym"]
    november = next(m for m in data["months"] if m["month"] == "2026-11")
    assert november["expenses"] is None and D(november["previous_expenses"]) == 1000
    assert data["years"] == [2025, 2026]
    past = owner.get("/api/reports/yearly", params={"year": 2025}).json()
    assert past["running"] is False and D(past["expenses"]) == 7 * 300 + 1000
