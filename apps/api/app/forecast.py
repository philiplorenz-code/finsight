"""Upcoming bookings and a money / net-worth forecast. Deterministic, from data the app already has.

Upcoming: next charges of active recurring contracts, standing orders into own pots and expected pay
(same day and amount as the last pay matched by an income rule, one month later). These are expectations,
not bank-confirmed bookings.

Forecast: month by month from today's cash (owner share) and net worth. Cash grows by the expected or the
cautious monthly surplus of the baseline; loan repayments are already part of spending, so net worth also
gains the principal repaid (from each loan's amortisation, owner share). After a loan is paid off its payment
adds to the surplus. Manually tracked assets are held flat (no depreciation or growth is assumed).
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .finance import contracts, local_today
from .models import Account, Holding, Transaction

router = APIRouter(tags=["forecast"])
ZERO = Decimal(0)
HUNDRED = Decimal(100)
PER_YEAR = {"monthly": 12, "quarterly": 4, "half_yearly": 2, "yearly": 1}


def on_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def next_month_day(d: date, day: int) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return on_day(y, m, day)


def upcoming(db: Session, user_id: str, days: int = 30, today: date | None = None) -> list[dict]:
    today = today or local_today(db, user_id)
    until = today + timedelta(days=days)
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.user_id == user_id))}
    out: list[dict] = []
    for item in contracts(db, user_id)["items"]:
        if item["status"] != "active" or item["period"] not in PER_YEAR or not item.get("next_charge"):
            continue
        due = date.fromisoformat(str(item["next_charge"])[:10])
        per = PER_YEAR[item["period"]]
        amount = Decimal(str(item["annual_cost"])) / per
        account = None
        if item.get("evidence"):
            tx = db.get(Transaction, item["evidence"][-1])
            account = accounts.get(tx.account_id).name if tx and tx.account_id in accounts else None
        step = 12 // per
        while due < today:  # overdue estimate: roll forward by the rhythm
            for _ in range(step):
                due = next_month_day(due, due.day)
        if due <= until:
            out.append({"date": due.isoformat(), "kind": "contract", "name": item["name"], "amount": -amount,
                        "currency": item["currency"], "account": account, "detail": item["kind"]})
    from .plan import standing_orders
    for order in standing_orders(db, user_id, today):
        if not order["active"]:
            continue
        due = on_day(today.year, today.month, order["day"])
        if due < today:
            due = next_month_day(due, order["day"])
        if due <= until:
            out.append({"date": due.isoformat(), "kind": "transfer", "name": order["account"], "amount": order["amount"],
                        "currency": "EUR", "account": order["account"], "detail": "standing_order"})
    from .income import load_rules, match_rule
    rules = load_rules(db, user_id)
    if rules:
        recent = db.scalars(select(Transaction).where(Transaction.user_id == user_id, Transaction.amount > 0,
                                                      Transaction.booking_date >= today - timedelta(days=62)))
        last: dict[str, Transaction] = {}
        for tx in recent:
            rule = match_rule(tx, rules)
            if rule and rule.source == "employment" and (rule.id not in last or tx.booking_date > last[rule.id].booking_date):
                last[rule.id] = tx
        names = {r.id: r.name for r in rules}
        for rule_id, tx in last.items():
            due = next_month_day(tx.booking_date, tx.booking_date.day)
            while due < today:
                due = next_month_day(due, tx.booking_date.day)
            if due <= until:
                acc = accounts.get(tx.account_id)
                out.append({"date": due.isoformat(), "kind": "income", "name": names[rule_id], "amount": tx.amount,
                            "currency": tx.currency, "account": acc.name if acc else None, "detail": "expected_pay"})
    return sorted(out, key=lambda o: (o["date"], o["kind"]))


def forecast(db: Session, user_id: str, months: int = 24, currency: str = "EUR") -> dict:
    from .networth import amortisation, net_worth
    from .wishlist import baseline
    today = local_today(db, user_id)
    base = baseline(db, user_id, currency, today)
    worth = net_worth(db, user_id, currency)["totals"]
    cash0, nw0 = Decimal(base["cash_on_hand"]), Decimal(str(worth["net_worth_mine"]))
    expected, cautious = Decimal(base["expected_surplus"]), Decimal(base["conservative_surplus"])
    loans = []
    for h in db.scalars(select(Holding).where(Holding.user_id == user_id, Holding.kind == "liability", Holding.currency == currency)):
        share = h.share / HUNDRED
        schedule = amortisation(h.value, h.monthly_payment, h.interest_rate, today)
        loans.append({"name": h.name, "start": h.value * share, "payment": (h.monthly_payment or ZERO) * share,
                      "remaining": [row["balance"] * share for row in schedule], "paid_off": schedule[-1]["month"] if schedule and schedule[-1]["balance"] == 0 else None})
    rows, cash_e, cash_c = [], cash0, cash0
    for i in range(1, months + 1):
        y, m = divmod(today.year * 12 + today.month - 1 + i, 12)
        label = f"{y}-{m + 1:02d}"
        freed = sum((l["payment"] for l in loans if l["remaining"] and len(l["remaining"]) < i), ZERO)
        cash_e += expected + freed
        cash_c += cautious + freed
        repaid = sum(((l["start"] - (l["remaining"][i - 1] if i <= len(l["remaining"]) else (l["remaining"][-1] if l["remaining"] else l["start"]))) for l in loans), ZERO)
        debt = sum(((l["remaining"][i - 1] if i <= len(l["remaining"]) else (l["remaining"][-1] if l["remaining"] else l["start"])) for l in loans), ZERO)
        rows.append({"month": label, "cash_expected": cash_e, "cash_cautious": cash_c,
                     "net_worth_expected": nw0 + (cash_e - cash0) + repaid, "net_worth_cautious": nw0 + (cash_c - cash0) + repaid, "debt": debt})
    return {"currency": currency, "start": {"month": today.isoformat()[:7], "cash": cash0, "net_worth": nw0},
            "monthly": {"expected_surplus": expected, "cautious_surplus": cautious}, "confidence": base["confidence"],
            "loans": [{"name": l["name"], "paid_off": l["paid_off"], "payment": l["payment"]} for l in loans], "months": rows,
            "assumptions": ["surplus_from_baseline", "assets_held_flat", "loan_payments_already_in_spending", "freed_payment_after_payoff"]}


@router.get("/upcoming")
def get_upcoming(days: int = Query(30, ge=1, le=120), db: Session = Depends(get_db), user=Depends(current_user)):
    return {"days": days, "items": upcoming(db, user.id, days)}


@router.get("/forecast")
def get_forecast(months: int = Query(24, ge=1, le=60), currency: str = Query("EUR", pattern="^[A-Z]{3}$"),
                 db: Session = Depends(get_db), user=Depends(current_user)):
    return forecast(db, user.id, months, currency)
