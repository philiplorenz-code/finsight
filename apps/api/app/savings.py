"""Savings insights derived from the monthly category spend of the analysis window.

Everything here is deterministic arithmetic on the user's own data:
- category trend: median of the last three complete months against the median of the months before them
  (medians, so a missing booking or a single spike does not look like a trend)
- fixed vs variable: a category is "fixed" when at least 75% of the months are within 25% of its median
- potential: what you would save if categories that grew recently returned to their earlier average
"""
from __future__ import annotations

from decimal import Decimal

ZERO = Decimal(0)
RECENT_MONTHS = 3
MIN_MONTHS = 6
FIXED_MIN_SHARE_OF_MONTHS = Decimal("0.75")
FIXED_MAX_VARIATION = Decimal("0.25")
MIN_SPEND_MONTHS_FOR_POTENTIAL = 4


def mean(values: list[Decimal]) -> Decimal:
    return sum(values, ZERO) / len(values) if values else ZERO


def median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        return ZERO
    return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2


def is_fixed(values: list[Decimal]) -> bool:
    mid = median(values)
    if mid <= 0:
        return False
    close = sum(1 for v in values if abs(v - mid) <= mid * FIXED_MAX_VARIATION)
    return Decimal(close) / len(values) >= FIXED_MIN_SHARE_OF_MONTHS


def savings_insights(months: list, by_category: dict, recurring: dict | None = None) -> dict:
    """`by_category[month][category]` is the spend per month; `recurring` is the contracts payload for the currency."""
    n = len(months)
    labels = sorted({c for m in months for c in by_category[m]})
    series = {c: [by_category[m].get(c, ZERO) for m in months] for c in labels}
    enough = n >= MIN_MONTHS
    rows = []
    for category, values in series.items():
        recent = values[-RECENT_MONTHS:] if enough else []
        prior = values[:-RECENT_MONTHS] if enough else []
        spend_months = sum(1 for v in values if v > 0)
        rows.append({"category": category, "average": mean(values), "recent": median(recent), "prior": median(prior),
                     "delta": median(recent) - median(prior) if enough else ZERO, "months_with_spend": spend_months,
                     "fixed": is_fixed(values)})
    total = sum((r["average"] for r in rows), ZERO)
    for r in rows:
        r["share"] = r["average"] / total if total else ZERO
    rows.sort(key=lambda r: -r["average"])

    fixed = {r["category"] for r in rows if r["fixed"]}
    fixed_by_month = [sum((v[i] for c, v in series.items() if c in fixed), ZERO) for i in range(n)]
    variable_by_month = [sum((v[i] for c, v in series.items() if c not in fixed), ZERO) for i in range(n)]
    growing = [r for r in rows if r["delta"] > 0 and r["months_with_spend"] >= MIN_SPEND_MONTHS_FOR_POTENTIAL and not r["fixed"]]
    potential = sum((r["delta"] for r in growing), ZERO)
    items = (recurring or {}).get("items", [])
    recurring_monthly = sum((Decimal(str(i["monthly_cost"])) for i in items if i.get("monthly_cost")), ZERO)
    return {
        "enough_data": enough,
        "categories": rows[:20],
        "fixed_monthly": mean(fixed_by_month), "variable_monthly": mean(variable_by_month),
        "fixed_by_month": fixed_by_month, "variable_by_month": variable_by_month,
        "potential_monthly": potential,
        "potential_categories": [r["category"] for r in sorted(growing, key=lambda r: -r["delta"])[:5]],
        "recurring_monthly": recurring_monthly,
        "recurring": sorted(({"name": i["name"], "monthly_cost": i["monthly_cost"], "period": i["period"],
                              "price_change": i.get("price_change"), "source": i["source"]}
                             for i in items if i.get("monthly_cost")),
                            key=lambda i: -Decimal(str(i["monthly_cost"])))[:12],
    }
