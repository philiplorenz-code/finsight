"""Synthetic-only financial health metrics, forecast and alert rules."""
from datetime import date
from decimal import Decimal

from app.health import category_anomalies, forecast, price_increases, ratio, volatility
from conftest import booking, upload

D = Decimal


def test_pure_helpers():
    assert ratio(D(5), D(0)) is None and ratio(D(5), D(10)) == D("0.5")
    assert volatility([D(100), D(100)]) is None, "needs three months"
    assert volatility([D(100), D(100), D(100)]) == 0
    assert volatility([D(0), D(0), D(0)]) is None
    path = forecast(D(1000), D(200), D(-300), date(2026, 1, 20), months=3)
    assert [p["month"] for p in path] == ["2026-02", "2026-03", "2026-04"]
    assert path[2]["expected"] == D(1600) and path[2]["cautious"] == D(100)


def test_anomaly_needs_factor_and_absolute_excess():
    series = {"categories": {"Food": [D(100)] * 5 + [D(400)], "Tiny": [D(10)] * 5 + [D(30)], "Steady": [D(200)] * 6}}
    found = category_anomalies(series)
    assert [a["category"] for a in found] == ["Food"]


def test_price_increase_detection():
    items = [{"key": "a", "name": "Gym", "status": "active", "price_change": D("3"), "annual_cost": D("240"), "period": "monthly"},
             {"key": "b", "name": "Tiny", "status": "active", "price_change": D("0.1"), "annual_cost": D("240"), "period": "monthly"},
             {"key": "c", "name": "Old", "status": "stopped", "price_change": D("9"), "annual_cost": D("240"), "period": "monthly"}]
    assert [r["key"] for r in price_increases(items)] == ["a"]


def classify(owner):
    account = owner.get("/api/accounts").json()[0]
    assert owner.patch(f"/api/accounts/{account['id']}", json={"ownership": "owned"}).status_code == 200


def test_endpoint_reports_metrics_and_marks_unavailable(owner):
    rows = []
    for month in range(1, 7):
        rows.append(booking(f"in-{month}", "3000", day=f"2026-{month:02d}-01"))
        rows.append(booking(f"out-{month}", "-3500", day=f"2026-{month:02d}-15", **({"Kontostand": "1000"} if month == 6 else {})))
    assert upload(owner, rows).status_code == 200
    classify(owner)
    data = owner.get("/api/health-metrics").json()
    m = data["metrics"]
    assert D(m["expected_surplus"]) == D(-500)
    assert "debt_service_ratio" in data["unavailable"] and m["debt_service_ratio"] is None
    codes = {a["code"] for a in data["alerts"]}
    assert {"negative_surplus", "cash_underfunded", "emergency_fund_low"} <= codes
    assert len(data["forecast"]["months"]) == 6


def test_no_data_does_not_invent_metrics(owner):
    data = owner.get("/api/health-metrics").json()
    assert data["metrics"]["savings_rate"] is None and "savings_rate" in data["unavailable"]
    assert data["metrics"]["emergency_fund_months"] is None
