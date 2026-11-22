"""Monthly close: one page per month comparing it with the month before and the six-month average.

Built only from existing calculations (overview with pay shift and owner share, plan vs. actual, anomalies),
so the numbers match the rest of the app. Read-only.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .finance import eligible, local_today, overview, serialize
from .models import Account, Transaction

router = APIRouter(tags=["report"])
ZERO = Decimal(0)


def month_bounds(month: date) -> tuple[date, date]:
    nxt = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return month, nxt - timedelta(days=1)


def shift(month: date, by: int) -> date:
    index = month.year * 12 + month.month - 1 + by
    return date(index // 12, index % 12 + 1, 1)


def totals(db: Session, user_id: str, month: date, currency: str) -> dict:
    start, end = month_bounds(month)
    data = overview(db, user_id, start, end)
    cur = next((c for c in data["currencies"] if c["currency"] == currency), None) or {}
    cats = {c["category"]: Decimal(c["amount"]) for c in data["categories"] if c["currency"] == currency}
    return {"income": Decimal(cur.get("income", 0)), "expenses": Decimal(cur.get("expenses", 0)),
            "surplus": Decimal(cur.get("surplus", 0)), "money": Decimal(cur.get("observed_mine", cur.get("observed_balance", 0))),
            "categories": cats}


def monthly_report(db: Session, user_id: str, month: date, currency: str = "EUR") -> dict:
    this = totals(db, user_id, month, currency)
    prev = totals(db, user_id, shift(month, -1), currency)
    history = [totals(db, user_id, shift(month, -i), currency) for i in range(1, 7)]
    avg = {k: sum((h[k] for h in history), ZERO) / len(history) for k in ("income", "expenses", "surplus")}
    names = set(this["categories"]) | set(prev["categories"])
    avg_cat = {n: sum((h["categories"].get(n, ZERO) for h in history), ZERO) / len(history) for n in names}
    categories = sorted(({"category": n, "amount": this["categories"].get(n, ZERO), "previous": prev["categories"].get(n, ZERO),
                          "average": avg_cat.get(n, ZERO), "change": this["categories"].get(n, ZERO) - avg_cat.get(n, ZERO)}
                         for n in names if this["categories"].get(n) or prev["categories"].get(n)), key=lambda c: -c["amount"])
    start, end = month_bounds(month)
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.user_id == user_id))
                if a.included and a.ownership != "external" and a.purpose != "mirror"}
    rows = [tx for tx in db.scalars(select(Transaction).where(Transaction.user_id == user_id, Transaction.booking_date >= start,
                                                             Transaction.booking_date <= end, Transaction.amount < 0, Transaction.currency == currency))
            if tx.account_id in accounts and eligible(tx)]
    biggest = [{"id": tx.id, "date": tx.booking_date, "merchant": tx.merchant, "category": tx.effective_category,
                "account": accounts[tx.account_id].name, "amount": tx.amount} for tx in sorted(rows, key=lambda t: t.amount)[:8]]
    from .plan import plan_report
    plan = plan_report(db, user_id, month, 1)
    from .insights_extra import anomalies
    days = (local_today(db, user_id) - start).days + 1
    found = [a for a in anomalies(db, user_id, max(7, min(365, days))) if start.isoformat() <= a["date"] <= end.isoformat()]
    rate = this["surplus"] / this["income"] if this["income"] else None
    highlights = []
    if this["expenses"] > avg["expenses"] * Decimal("1.15") and avg["expenses"]:
        highlights.append({"kind": "spending_high", "amount": this["expenses"] - avg["expenses"]})
    if this["expenses"] < avg["expenses"] * Decimal("0.9") and avg["expenses"]:
        highlights.append({"kind": "spending_low", "amount": avg["expenses"] - this["expenses"]})
    if categories and categories[0]["change"] > 50:
        top = max(categories, key=lambda c: c["change"])
        highlights.append({"kind": "category_up", "category": top["category"], "amount": top["change"]})
    over = [i for i in plan["items"] if i["status"] == "over"]
    if over:
        highlights.append({"kind": "plan_over", "count": len(over)})
    return serialize({"month": month.isoformat()[:7], "currency": currency, "complete": end < local_today(db, user_id),
                      "income": this["income"], "expenses": this["expenses"], "surplus": this["surplus"], "savings_rate": rate,
                      "previous": {k: prev[k] for k in ("income", "expenses", "surplus")}, "average_6m": avg,
                      "money_end": this["money"], "money_change": this["money"] - prev["money"],
                      "categories": categories[:12], "biggest": biggest,
                      "plan": [{"name": i["name"], "amount": i["amount"], "actual": i["actual"], "status": i["status"]} for i in plan["items"]],
                      "anomalies": found[:10], "highlights": highlights})


@router.get("/reports/monthly")
def get_monthly_report(month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"), currency: str = Query("EUR", pattern="^[A-Z]{3}$"),
                       db: Session = Depends(get_db), user=Depends(current_user)):
    today = local_today(db, user.id)
    if month:
        year, mon = int(month[:4]), int(month[5:])
        if not 1 <= mon <= 12:
            raise HTTPException(422, "Invalid month")
        target = date(year, mon, 1)
    else:
        target = shift(today.replace(day=1), -1)  # default: last complete month
    return monthly_report(db, user.id, target, currency)
