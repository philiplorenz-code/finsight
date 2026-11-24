"""Watched account: where does the money on one account come from, and how often must it be topped up?

An account such as "Freizeit" gets a regular budget (one transfer per month from the same account on about
the same day with about the same amount). Everything else moved in from the user's own accounts is a top-up
("Nachschuss"). Per month the report shows the concrete budget, each top-up source, the spending and the
calculated month-end balance, so the user sees how much is really needed instead of an average.
"""
from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from statistics import median, pstdev

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .finance import eligible, latest_balance, local_today, serialize
from .models import Account, Setting, Transaction
from .transfers import find_pairs

router = APIRouter(tags=["watch"])
SETTING_KEY = "watched_account"
ZERO = Decimal(0)
DAY_WINDOW = 3
BALANCE_ROLES = {"none", "parent", "uncertain"}


def month_key(day: date) -> str:
    return day.strftime("%Y-%m")


def months_back(today: date, count: int) -> list[str]:
    year, month = today.year, today.month
    out = []
    for _ in range(count):
        out.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(out))


def regular_budget(inflows: list[tuple[Transaction, str]], months: list[str], force: bool = False) -> dict[str, dict]:
    """Per source account, the one transfer per month that arrives on the usual day with the usual amount."""
    by_source: dict[str, list[Transaction]] = defaultdict(list)
    for tx, source in inflows:
        by_source[source].append(tx)
    found = {}
    for source, rows in by_source.items():
        day = Counter(tx.booking_date.day for tx in rows).most_common(1)[0][0]
        picks = {}
        for tx in rows:
            distance = abs(tx.booking_date.day - day)
            if distance > DAY_WINDOW:
                continue
            key = month_key(tx.booking_date)
            if key not in picks or (distance, -tx.amount) < (abs(picks[key].booking_date.day - day), -picks[key].amount):
                picks[key] = tx
        hits = [picks[m] for m in months if m in picks] or list(picks.values())
        if not hits:
            continue
        amounts = [float(tx.amount) for tx in hits]
        if not force and (len(hits) < max(3, round(len(months) * 2 / 3)) or pstdev(amounts) / median(amounts) > 0.25):
            continue
        found[source] = {"day": day, "amount": Decimal(str(median(amounts))), "ids": {tx.id for tx in picks.values()}}
    return found


def watch_report(db: Session, user_id: str, account_id: str, months_count: int = 12, budget_source: str | None = None) -> dict:
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.user_id == user_id))}
    account = accounts.get(account_id)
    if account is None:
        raise HTTPException(404, "Account not found")
    today = local_today(db, user_id)
    months = months_back(today, months_count)
    first = date.fromisoformat(f"{months[0]}-01")

    inflows, outflows = [], []
    for inflow, outflow in find_pairs(db, user_id):
        if inflow.account_id == account.id and inflow.booking_date >= first:
            inflows.append((inflow, outflow.account_id))
        elif outflow.account_id == account.id and outflow.booking_date >= first:
            outflows.append((outflow, inflow.account_id))
    paired = {tx.id for tx, _ in inflows + outflows}

    # Only full past months decide what the regular budget is; the running month may not have it yet.
    if budget_source is None:
        budget = regular_budget(inflows, months[:-1] or months)
    else:
        budget = regular_budget([row for row in inflows if row[1] == budget_source], months[:-1] or months, force=True) if budget_source else {}
    budget_ids = set().union(*(b["ids"] for b in budget.values())) if budget else set()

    rows = list(db.scalars(select(Transaction).where(Transaction.account_id == account.id, Transaction.booking_date >= first)))
    month = {m: {"month": m, "budget": ZERO, "topups": ZERO, "topup_count": 0, "sources": defaultdict(lambda: [ZERO, 0]),
                 "spending": ZERO, "refunds": ZERO, "moved_out": ZERO, "first_topup": None} for m in months}
    categories: dict[str, Decimal] = defaultdict(lambda: ZERO)
    sources_total: dict[str, list] = defaultdict(lambda: [ZERO, 0, set()])
    for tx, source in inflows:
        bucket = month.get(month_key(tx.booking_date))
        if bucket is None:
            continue
        if tx.id in budget_ids:
            bucket["budget"] += tx.amount
            continue
        bucket["topups"] += tx.amount
        bucket["topup_count"] += 1
        bucket["sources"][source][0] += tx.amount
        bucket["sources"][source][1] += 1
        if bucket["first_topup"] is None or tx.booking_date < bucket["first_topup"]:
            bucket["first_topup"] = tx.booking_date
        sources_total[source][0] += tx.amount
        sources_total[source][1] += 1
        sources_total[source][2].add(bucket["month"])
    for tx, _target in outflows:
        bucket = month.get(month_key(tx.booking_date))
        if bucket is not None:
            bucket["moved_out"] += -tx.amount
    for tx in rows:
        bucket = month.get(month_key(tx.booking_date))
        if bucket is None or tx.id in paired or not eligible(tx):
            continue
        if tx.amount < 0:
            bucket["spending"] += -tx.amount
            categories[tx.effective_category or "Ohne Kategorie"] += -tx.amount
        else:
            bucket["refunds"] += tx.amount

    # Month-end balances, calculated back from the latest observed balance with the bank lines in between.
    observation = latest_balance(db, account.id, today)
    ends: dict[str, Decimal | None] = {m: None for m in months}
    if observation is not None:
        later = [tx for tx in db.scalars(select(Transaction).where(Transaction.account_id == account.id, Transaction.booking_date > first))
                 if tx.split_role in BALANCE_ROLES]
        for m in months:
            y, mo = map(int, m.split("-"))
            end = date(y, mo, calendar.monthrange(y, mo)[1])
            if end >= observation.observed_date:
                if end >= today and m == months[-1]:
                    ends[m] = observation.amount
                continue
            ends[m] = observation.amount - sum((tx.amount for tx in later if end < tx.booking_date <= observation.observed_date), ZERO)

    out_months = []
    for m in months:
        b = month[m]
        net_spending = b["spending"] - b["refunds"]
        out_months.append({
            "month": m, "budget": b["budget"], "topups": b["topups"], "topup_count": b["topup_count"],
            "spending": b["spending"], "refunds": b["refunds"], "moved_out": b["moved_out"],
            "gap": max(net_spending - b["budget"], ZERO), "first_topup": b["first_topup"], "end_balance": ends[m],
            "sources": sorted(({"account_id": k, "name": accounts[k].name if k in accounts else "?", "amount": v[0], "count": v[1]}
                               for k, v in b["sources"].items()), key=lambda s: -s["amount"]),
        })
    full = [m for m in out_months if m["month"] != months[-1]] or out_months
    total = lambda key, rows=full: sum((m[key] for m in rows), ZERO)  # noqa: E731
    spent = total("spending") - total("refunds")
    return serialize({
        "account": {"id": account.id, "name": account.name, "provider": account.provider},
        "months": out_months,
        "budget_sources": [{"account_id": k, "name": accounts[k].name if k in accounts else "?", "day": v["day"], "amount": v["amount"]}
                           for k, v in budget.items()],
        "budget_source_override": budget_source,
        "candidates": sorted(({"account_id": k, "name": accounts[k].name} for k in {s for _, s in inflows} if k in accounts), key=lambda c: c["name"]),
        "summary": {
            "full_months": len(full), "running_month": months[-1],
            "budget": total("budget"), "topups": total("topups"), "topup_count": sum(m["topup_count"] for m in full),
            "months_with_topups": sum(1 for m in full if m["topup_count"]), "spending": spent,
            "covered_by_topups": (total("topups") / spent).quantize(Decimal("0.01")) if spent > 0 else None,
            "biggest_month": max(full, key=lambda m: m["topups"])["month"] if any(m["topups"] for m in full) else None,
        },
        "sources": sorted(({"account_id": k, "name": accounts[k].name if k in accounts else "?", "amount": v[0], "count": v[1], "months": len(v[2])}
                           for k, v in sources_total.items()), key=lambda s: -s["amount"]),
        "categories": [{"name": k, "amount": v} for k, v in sorted(categories.items(), key=lambda kv: -kv[1])[:10]],
        "balance_observed": observation.observed_date if observation else None,
    })


def load_setting(db: Session, user_id: str) -> dict:
    row = db.get(Setting, user_id)
    return dict((row.data or {}).get(SETTING_KEY) or {}) if row else {}


def default_account(db: Session, user_id: str) -> str | None:
    chosen = load_setting(db, user_id).get("account_id")
    if chosen:
        return chosen
    return db.scalar(select(Account.id).where(Account.user_id == user_id, Account.name == "Freizeit").limit(1))


@router.get("/watch")
def get_watch(account_id: str | None = None, months: int = 12, db: Session = Depends(get_db), user=Depends(current_user)):
    setting = load_setting(db, user.id)
    target = account_id or default_account(db, user.id)
    if not target:
        return {"account": None, "watched": None}
    override = setting.get("budget_source") if setting.get("account_id") == target and "budget_source" in setting else None
    report = watch_report(db, user.id, target, max(3, min(months, 36)), override)
    report["watched"] = setting.get("account_id")
    return report


class WatchBody(BaseModel):
    account_id: str = Field(min_length=1, max_length=36)
    budget_source: str | None = Field(default=None, max_length=36)
    auto_budget: bool = True


@router.put("/watch")
def put_watch(body: WatchBody, db: Session = Depends(get_db), user=Depends(current_user)):
    if not db.scalar(select(Account.id).where(Account.user_id == user.id, Account.id == body.account_id)):
        raise HTTPException(404, "Account not found")
    row = db.get(Setting, user.id)
    if row is None:
        row = Setting(user_id=user.id, data={})
        db.add(row)
    data = dict(row.data or {})
    value = {"account_id": body.account_id}
    if not body.auto_budget:
        value["budget_source"] = body.budget_source or ""
    data[SETTING_KEY] = value
    row.data = data
    db.commit()
    return value
