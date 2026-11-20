"""Side-business overview with an EÜR-style CSV, and merchant profiles. Read-only views over the bookings.

Side business: income matched by income rules with source "business" (the rule name is the client) and
expenses matched by business rules, per calendar month of the booking date (cash principle, so the income
rule's month shift is NOT applied here). The CSV is a preview for the tax adviser, not a tax return.

Merchant profile: all non-transfer bookings whose merchant equals the given name (case-insensitive) on
included accounts that are not mirrors, with monthly totals, categories, accounts and a contract match.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import current_user
from .business import TAX_RESERVE_RATE, is_business_expense, load_business_rules
from .db import get_db
from .finance import contracts, eligible, local_today
from .income import load_rules, match_rule
from .models import Account, Transaction

router = APIRouter(tags=["insights"])
ZERO = Decimal(0)


def counted_accounts(db: Session, user_id: str) -> dict[str, Account]:
    return {a.id: a for a in db.scalars(select(Account).where(Account.user_id == user_id))
            if a.included and a.ownership != "external" and a.purpose != "mirror"}


def business_rows(db: Session, user_id: str, year: int) -> list[dict]:
    accounts = counted_accounts(db, user_id)
    income_rules = [r for r in load_rules(db, user_id) if r.source == "business"]
    expense_rules = load_business_rules(db, user_id)
    out = []
    for tx in db.scalars(select(Transaction).where(Transaction.user_id == user_id, Transaction.booking_date >= date(year, 1, 1),
                                                   Transaction.booking_date <= date(year, 12, 31)).order_by(Transaction.booking_date)):
        if tx.account_id not in accounts or not eligible(tx):
            continue
        if tx.amount > 0:
            rule = match_rule(tx, income_rules) if income_rules else None
            if rule:
                out.append({"tx": tx, "kind": "income", "client": rule.name, "account": accounts[tx.account_id].name})
        elif expense_rules and is_business_expense(tx, expense_rules):
            out.append({"tx": tx, "kind": "expense", "client": (tx.merchant or "").strip() or "?", "account": accounts[tx.account_id].name})
    return out


def business_overview(db: Session, user_id: str, year: int) -> dict:
    rows = business_rows(db, user_id, year)
    today = local_today(db, user_id)
    last_month = 12 if year < today.year else today.month
    clients: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO] * 12)
    expenses: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO] * 12)
    for r in rows:
        m = r["tx"].booking_date.month - 1
        if r["kind"] == "income":
            clients[r["client"]][m] += r["tx"].amount
        else:
            expenses[(r["tx"].effective_category or "").strip() or "Sonstiges"][m] += -r["tx"].amount
    income_m = [sum((c[i] for c in clients.values()), ZERO) for i in range(12)]
    expense_m = [sum((c[i] for c in expenses.values()), ZERO) for i in range(12)]
    profit = sum(income_m, ZERO) - sum(expense_m, ZERO)
    return {"year": year, "months": [f"{year}-{i + 1:02d}" for i in range(12)],
            "clients": sorted(({"name": k, "monthly": v, "total": sum(v, ZERO), "months_paid": sum(1 for x in v if x > 0)} for k, v in clients.items()), key=lambda c: -c["total"]),
            "expenses": sorted(({"category": k, "monthly": v, "total": sum(v, ZERO)} for k, v in expenses.items()), key=lambda c: -c["total"]),
            "income_monthly": income_m, "expense_monthly": expense_m,
            "totals": {"income": sum(income_m, ZERO), "expenses": sum(expense_m, ZERO), "profit": profit,
                       "tax_reserve_suggestion": max(ZERO, profit) * TAX_RESERVE_RATE, "tax_reserve_rate": TAX_RESERVE_RATE},
            "months_without_income": [f"{year}-{i + 1:02d}" for i in range(last_month) if income_m[i] == 0],
            "has_rules": bool([r for r in load_rules(db, user_id) if r.source == "business"])}


@router.get("/business/overview")
def get_business_overview(year: int | None = Query(None, ge=2000, le=2100), db: Session = Depends(get_db), user=Depends(current_user)):
    return business_overview(db, user.id, year or local_today(db, user.id).year)


@router.get("/business/euer.csv")
def business_csv(year: int = Query(..., ge=2000, le=2100), db: Session = Depends(get_db), user=Depends(current_user)):
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Datum", "Art", "Auftraggeber/Empfänger", "Kategorie", "Konto", "Betrag", "Verwendungszweck"])
    for r in business_rows(db, user.id, year):
        tx = r["tx"]
        text = (tx.description or "").replace("\n", " ")[:200]
        if text[:1] in "=+-@":  # spreadsheet formula injection guard
            text = "'" + text
        writer.writerow([tx.booking_date.strftime("%d.%m.%Y"), "Einnahme" if r["kind"] == "income" else "Ausgabe", r["client"],
                         (tx.effective_category or "").strip(), r["account"], f"{tx.amount:.2f}".replace(".", ","), text])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="euer-vorschau-{year}.csv"', "Cache-Control": "no-store"})


@router.get("/merchants/profile")
def merchant_profile(name: str = Query(..., min_length=1, max_length=300), months: int = Query(12, ge=1, le=60),
                     db: Session = Depends(get_db), user=Depends(current_user)):
    today = local_today(db, user.id)
    start = date(today.year, today.month, 1)
    for _ in range(months - 1):
        start = (start - timedelta(days=1)).replace(day=1)
    accounts = counted_accounts(db, user.id)
    key = name.strip().casefold()
    rows = [tx for tx in db.scalars(select(Transaction).where(Transaction.user_id == user.id, func.lower(Transaction.merchant) == key,
                                                              Transaction.booking_date >= start).order_by(Transaction.booking_date))
            if tx.account_id in accounts and eligible(tx)]
    if not rows:
        raise HTTPException(404, "No bookings for this merchant")
    monthly: dict[str, Decimal] = defaultdict(lambda: ZERO)
    categories: dict[str, int] = defaultdict(int)
    by_account: dict[str, int] = defaultdict(int)
    for tx in rows:
        monthly[tx.booking_date.strftime("%Y-%m")] += -tx.amount
        categories[(tx.effective_category or "").strip() or "—"] += 1
        by_account[accounts[tx.account_id].name] += 1
    labels, cursor = [], start
    while cursor <= today:
        labels.append(cursor.strftime("%Y-%m"))
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    spent = sum((-tx.amount for tx in rows if tx.amount < 0), ZERO)
    refunds = sum((tx.amount for tx in rows if tx.amount > 0), ZERO)
    contract = next((c for c in contracts(db, user.id)["items"] if c["name"].strip().casefold() == key), None)
    return {"name": rows[-1].merchant, "months": [{"month": m, "net_spent": monthly.get(m, ZERO)} for m in labels],
            "count": len(rows), "spent": spent, "refunds": refunds, "average": spent / max(1, sum(1 for tx in rows if tx.amount < 0)),
            "first": rows[0].booking_date.isoformat(), "last": rows[-1].booking_date.isoformat(),
            "categories": sorted(({"name": k, "count": v} for k, v in categories.items()), key=lambda c: -c["count"]),
            "accounts": sorted(({"name": k, "count": v} for k, v in by_account.items()), key=lambda c: -c["count"]),
            "contract": {"period": contract["period"], "monthly": contract["monthly_cost"], "status": contract["status"], "kind": contract["kind"]} if contract else None,
            "recent": [{"id": tx.id, "date": tx.booking_date.isoformat(), "amount": tx.amount, "category": tx.effective_category} for tx in reversed(rows[-10:])]}


def anomalies(db: Session, user_id: str, days: int = 60, today: date | None = None) -> list[dict]:
    """Possible double debits, new recurring payments, unusually high amounts and price increases."""
    import statistics
    today = today or local_today(db, user_id)
    since = today - timedelta(days=days)
    accounts = counted_accounts(db, user_id)
    history = [tx for tx in db.scalars(select(Transaction).where(Transaction.user_id == user_id, Transaction.amount < 0,
                                                                 Transaction.booking_date >= today - timedelta(days=400)))
               if tx.account_id in accounts and eligible(tx)]
    recent = [tx for tx in history if tx.booking_date >= since]
    out: list[dict] = []
    # 1) same merchant and amount twice within three days on own accounts
    seen: dict[tuple, Transaction] = {}
    for tx in sorted(recent, key=lambda t: t.booking_date):
        key = ((tx.merchant or "").strip().casefold(), tx.amount)
        prev = seen.get(key)
        if prev and key[0] and (tx.booking_date - prev.booking_date).days <= 3 and prev.id != tx.id and -tx.amount >= 5:
            out.append({"key": f"double:{prev.id}:{tx.id}", "kind": "double_debit", "severity": "high", "date": tx.booking_date.isoformat(),
                        "merchant": tx.merchant, "amount": tx.amount, "transactions": [prev.id, tx.id]})
        seen[key] = tx
    # 2) unusually high amount for this merchant (>= 3x its median, at least 50 EUR more)
    by_merchant: dict[str, list[Decimal]] = defaultdict(list)
    for tx in history:
        if tx.booking_date < since:
            by_merchant[(tx.merchant or "").strip().casefold()].append(-tx.amount)
    for tx in recent:
        past = by_merchant.get((tx.merchant or "").strip().casefold(), [])
        if len(past) >= 3:
            median = Decimal(str(statistics.median(past)))
            if -tx.amount >= median * 3 and -tx.amount - median >= 50:
                out.append({"key": f"high:{tx.id}", "kind": "unusually_high", "severity": "medium", "date": tx.booking_date.isoformat(),
                            "merchant": tx.merchant, "amount": tx.amount, "typical": median, "transactions": [tx.id]})
    # 3) new recurring payments and 4) price increases, from the contract detection
    for item in contracts(db, user_id)["items"]:
        if item["status"] != "active":
            continue
        evidence = item.get("evidence") or []
        first = db.get(Transaction, evidence[0]) if evidence else None
        if first and first.booking_date >= since and item.get("charges", 0) >= 2:
            out.append({"key": f"new:{item['key']}", "kind": "new_recurring", "severity": "medium", "date": first.booking_date.isoformat(),
                        "merchant": item["name"], "amount": -Decimal(str(item["monthly_cost"])), "period": item["period"], "transactions": evidence[-3:]})
        change = Decimal(str(item.get("price_change") or 0))
        last = db.get(Transaction, evidence[-1]) if evidence else None
        if change > 0 and last and last.booking_date >= since:
            out.append({"key": f"price:{item['key']}:{last.id}", "kind": "price_increase", "severity": "medium", "date": last.booking_date.isoformat(),
                        "merchant": item["name"], "amount": last.amount, "change": change, "transactions": [last.id]})
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda a: (order[a["severity"]], a["date"]), reverse=False)


@router.get("/anomalies")
def get_anomalies(days: int = Query(60, ge=7, le=365), db: Session = Depends(get_db), user=Depends(current_user)):
    return {"days": days, "items": anomalies(db, user.id, days)}


def queue_anomaly_alerts(session: Session, owner_id: str, now=None) -> list[str]:
    from .notifications import NotificationSettings, queue_notification
    settings = session.get(NotificationSettings, str(owner_id))
    if not settings or not settings.enabled or "anomaly" not in (settings.events or []):
        return []
    found = [a for a in anomalies(session, str(owner_id), 14) if a["severity"] == "high" or a["kind"] in {"new_recurring", "price_increase"}]
    return [queue_notification(session, str(owner_id), "anomaly", "anomaly:" + a["key"][:180], now).id for a in found]
