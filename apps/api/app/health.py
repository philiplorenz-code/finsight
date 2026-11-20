"""Financial health metrics, a deterministic cash forecast and alerts.

Everything is derived from the wishlist baseline (cashflow accounts, transfers and savings excluded,
income shifts applied) and the net-worth module. A metric that lacks its inputs is reported as
``None`` with a reason instead of being invented. Alerts carry codes, never amounts in free text.
"""
from __future__ import annotations

import statistics
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .finance import ZERO, local_today, serialize
from .networth import net_worth
from .wishlist import add_months, baseline

router = APIRouter(tags=["health"])

FORECAST_MONTHS = 6
EMERGENCY_TARGET_MONTHS = Decimal(3)
ANOMALY_FACTOR = Decimal("1.5")
ANOMALY_MIN_EXCESS = Decimal(50)
PRICE_INCREASE_MIN = Decimal("0.05")


def ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return numerator / denominator if denominator > 0 else None


def volatility(values: list[Decimal]) -> Decimal | None:
    """Coefficient of variation of monthly consumption; needs at least three months."""
    if len(values) < 3:
        return None
    mean = sum(values, ZERO) / len(values)
    if mean <= 0:
        return None
    return Decimal(str(statistics.pstdev([float(v) for v in values]))) / mean


def category_anomalies(series: dict) -> list[dict]:
    """Categories whose latest complete month is far above their own median of the earlier months."""
    out = []
    for label, values in series.get("categories", {}).items():
        if len(values) < 4:
            continue
        latest, earlier = values[-1], values[:-1]
        median = Decimal(str(statistics.median([float(v) for v in earlier])))
        if median > 0 and latest >= median * ANOMALY_FACTOR and latest - median >= ANOMALY_MIN_EXCESS:
            out.append({"category": label, "latest": latest, "typical": median})
    return sorted(out, key=lambda a: -(a["latest"] - a["typical"]))[:5]


def price_increases(contracts_items: list[dict]) -> list[dict]:
    out = []
    for item in contracts_items:
        change, annual = item.get("price_change"), item.get("annual_cost")
        if item.get("status") != "active" or not change or change <= 0 or not annual:
            continue
        per_charge = annual / {"monthly": 12, "quarterly": 4, "half_yearly": 2, "yearly": 1}.get(item.get("period"), 12)
        previous = per_charge - change
        if previous > 0 and change / previous >= PRICE_INCREASE_MIN:
            out.append({"key": item["key"], "name": item["name"], "increase": change, "period": item["period"]})
    return out[:5]


def forecast(start: Decimal, expected: Decimal, cautious: Decimal, today, months: int = FORECAST_MONTHS) -> list[dict]:
    rows = []
    for step in range(1, months + 1):
        rows.append({"month": add_months(today.replace(day=1), step).strftime("%Y-%m"),
                     "expected": start + expected * step, "cautious": start + cautious * step})
    return rows


def health(db: Session, user_id: str, currency: str = "EUR") -> dict:
    from .finance import contracts
    today = local_today(db, user_id)
    base = baseline(db, user_id, currency, today)
    worth = net_worth(db, user_id, currency)
    series = base["series"]
    income, consumption = base["monthly_income"], base["monthly_consumption"]
    unavailable: dict[str, str] = {}

    savings_rate = None
    if income > 0:
        savings_rate = (income - consumption - base["monthly_tax"]) / income
    else:
        unavailable["savings_rate"] = "no_income"

    emergency = ratio(base["cash_on_hand"] - base["allocated"], consumption)
    if emergency is None:
        unavailable["emergency_fund_months"] = "no_consumption"
    debt_service = Decimal(worth["totals"]["monthly_debt_service"])
    debt_ratio = ratio(debt_service, income) if debt_service > 0 else None
    if debt_service <= 0:
        unavailable["debt_service_ratio"] = "no_tracked_debt"
    elif debt_ratio is None:
        unavailable["debt_service_ratio"] = "no_income"
    vol = volatility(series["expenses"])
    if vol is None:
        unavailable["spending_volatility"] = "too_few_months"

    cash = base["cash_on_hand"] - base["allocated"]
    path = forecast(cash, base["expected_surplus"], base["conservative_surplus"], today)
    alerts: list[dict] = []
    first_negative = next((p["month"] for p in path if p["cautious"] < 0), None)
    if first_negative:
        alerts.append({"code": "cash_underfunded", "severity": "high", "month": first_negative})
    if emergency is not None and emergency < EMERGENCY_TARGET_MONTHS:
        alerts.append({"code": "emergency_fund_low", "severity": "medium" if emergency >= 1 else "high"})
    if base["expected_surplus"] < 0:
        alerts.append({"code": "negative_surplus", "severity": "high"})
    if vol is not None and vol > Decimal("0.35"):
        alerts.append({"code": "volatile_spending", "severity": "low"})
    for anomaly in category_anomalies(series):
        alerts.append({"code": "category_anomaly", "severity": "low", **anomaly})
    items = [i for i in contracts(db, user_id)["items"] if i["currency"] == currency]
    for rise in price_increases(items):
        alerts.append({"code": "price_increase", "severity": "low", **rise})
    for warning in base["warnings"]:
        if "gap" in warning.lower() or "stale" in warning.lower():
            alerts.append({"code": "data_quality", "severity": "info", "detail": warning})
            break
    return serialize({
        "currency": currency, "months_used": base["months_used"], "confidence": base["confidence"],
        "metrics": {"savings_rate": savings_rate, "emergency_fund_months": emergency, "emergency_target_months": EMERGENCY_TARGET_MONTHS,
                    "debt_service_ratio": debt_ratio, "spending_volatility": vol, "monthly_income": income,
                    "monthly_consumption": consumption, "expected_surplus": base["expected_surplus"],
                    "conservative_surplus": base["conservative_surplus"], "net_worth_mine": worth["totals"]["net_worth_mine"]},
        "unavailable": unavailable, "forecast": {"start_cash": cash, "months": path},
        "alerts": alerts, "assumptions": ["Forecast = free cash today + monthly surplus x months; no one-off events are predicted",
                                           "Cautious uses the lower-quartile surplus; unavailable metrics are never estimated"],
    })


@router.get("/health-metrics")
def get_health(currency: str = Query("EUR", pattern="^[A-Z]{3}$"), db: Session = Depends(get_db), user=Depends(current_user)):
    return health(db, user.id, currency)
