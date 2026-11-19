"""Wishlist and affordability assessment.

All arithmetic uses Decimal. The assessment is a deterministic planning aid, not financial
advice: it states its assumptions, uses a conservative and an expected income variant, and never
combines currencies.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date
from decimal import ROUND_CEILING, Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .finance import ZERO, eligible, latest_balance, local_today, serialize
from .income import SOURCES, classify, load_rules, source_stats
from .locking import lock_owner
from .models import Account, Allocation, Transaction, Wish, WishlistPrefs

router = APIRouter(tags=["wishlist"])

WINDOW_MONTHS = 12
MIN_MONTHS_FOR_MEDIUM_CONFIDENCE = 6
STALE_DATA_DAYS = 45
SAVING_CATEGORIES = {"sparen", "kapitalanlage"}
CASHFLOW_PURPOSES = {"checking", "cash"}
CASH_PURPOSES = {"checking", "savings", "cash"}
CONSERVATIVE_HORIZON_MONTHS = 12
EXPECTED_HORIZON_MONTHS = 24


def add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def month_start(day: date) -> date:
    return day.replace(day=1)


def get_prefs(db, user_id) -> dict:
    row = db.get(WishlistPrefs, user_id)
    return {"self_names": list(row.self_names or []) if row else [],
            "reserve_months": row.reserve_months if row else 3,
            "monthly_tax_reserve": row.monthly_tax_reserve if row else ZERO}


def lower_quartile(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 4]


def complete_months(data_through: date, count: int) -> list[date]:
    """Month starts of the latest `count` months that end on or before `data_through`."""
    last = month_start(data_through)
    if data_through.day != calendar.monthrange(data_through.year, data_through.month)[1]:
        last = add_months(last, -1)
    return [add_months(last, -i) for i in range(count - 1, -1, -1)]


def baseline(db: Session, user_id: str, currency: str = "EUR", today: date | None = None) -> dict:
    today = today or local_today(db, user_id)
    prefs = get_prefs(db, user_id)
    self_names = {name.strip().casefold() for name in prefs["self_names"] if name.strip()}
    accounts = [a for a in db.scalars(select(Account).where(Account.user_id == user_id))
                if a.included and a.ownership == "owned" and a.currency == currency]
    cashflow_ids = {a.id for a in accounts if a.purpose in CASHFLOW_PURPOSES}
    tax_ids = {a.id for a in accounts if a.purpose == "other"}
    warnings: list[str] = []
    if not any(a.ownership == "owned" for a in db.scalars(select(Account).where(Account.user_id == user_id))):
        warnings.append("No account is marked as owned; classify accounts before relying on this assessment")

    rows = [tx for tx in db.scalars(select(Transaction).where(
            Transaction.user_id == user_id, Transaction.currency == currency, Transaction.booking_date <= today))
            if tx.account_id in cashflow_ids | tax_ids]
    in_cashflow = [tx for tx in rows if tx.account_id in cashflow_ids]
    data_through = max((tx.booking_date for tx in in_cashflow), default=None)

    months: list[date] = []
    income: dict[date, Decimal] = defaultdict(lambda: ZERO)
    income_by_source: dict[str, dict[date, Decimal]] = {s: defaultdict(lambda: ZERO) for s in SOURCES}
    unassigned: dict[str, Decimal] = defaultdict(lambda: ZERO)
    rules = load_rules(db, user_id)
    expenses: dict[date, Decimal] = defaultdict(lambda: ZERO)
    tax_paid = ZERO
    if data_through:
        months = complete_months(data_through, WINDOW_MONTHS)
        first_booking = min(tx.booking_date for tx in in_cashflow)
        months = [m for m in months if add_months(m, 1) > first_booking]
        window = set(months)
        for tx in rows:
            key = month_start(tx.booking_date)
            if key not in window or not eligible(tx):
                continue
            if tx.merchant.strip().casefold() in self_names:
                continue
            if (tx.category_override or tx.category or "").strip().casefold() in SAVING_CATEGORIES:
                continue
            if tx.account_id in tax_ids:
                if tx.amount < 0:
                    tax_paid += -tx.amount
                continue
            if tx.amount >= 0:
                income[key] += tx.amount
                source = classify(tx, rules)
                income_by_source[source][key] += tx.amount
                if source == "other":
                    unassigned[(tx.merchant or "").strip() or "?"] += tx.amount
            else:
                expenses[key] += -tx.amount
        if any(tx.transfer_uncertain for tx in in_cashflow if month_start(tx.booking_date) in window):
            warnings.append("Some transfers are uncertain; the consumption figure may be slightly off")
    count = len(months)
    if count < MIN_MONTHS_FOR_MEDIUM_CONFIDENCE:
        warnings.append(f"Only {count} complete month(s) of data are available")
    if data_through and (today - data_through).days > STALE_DATA_DAYS:
        warnings.append("Transaction data is stale; import a fresh export")

    tax_monthly = max(tax_paid / count if count else ZERO, prefs["monthly_tax_reserve"])
    if tax_ids and tax_monthly == ZERO:
        warnings.append("Tax accounts exist but no tax outflow was found; set a monthly tax reserve")
    if not tax_ids and prefs["monthly_tax_reserve"] == ZERO:
        warnings.append("No tax cost is modelled; if you owe tax on irregular income, set a monthly tax reserve")
    surplus_series = [income[m] - expenses[m] - tax_monthly for m in months]
    expected = sum(surplus_series, ZERO) / count if count else ZERO
    conservative = min(lower_quartile(surplus_series), expected) if count else ZERO
    consumption = sum((expenses[m] for m in months), ZERO) / count if count else ZERO
    monthly_income = sum((income[m] for m in months), ZERO) / count if count else ZERO

    sources = source_stats({s: [income_by_source[s][m] for m in months] for s in SOURCES})
    top_unassigned = [{"merchant": m, "total": v} for m, v in sorted(unassigned.items(), key=lambda kv: -kv[1])[:10]]

    cash = ZERO
    observed = 0
    for account in accounts:
        if account.purpose not in CASH_PURPOSES:
            continue
        observation = latest_balance(db, account.id, today)
        if observation:
            observed += 1
            cash += observation.amount
            if (today - observation.observed_date).days > 7:
                warnings.append("Some observed balances are stale")
    if not observed:
        warnings.append("No observed balances; cash on hand is assumed to be zero")
    allocated = sum((a.amount for a in db.scalars(select(Allocation).where(
        Allocation.account_id.in_([a.id for a in accounts]))) ), ZERO) if accounts else ZERO
    reserve = consumption * prefs["reserve_months"]
    usable = max(ZERO, cash - allocated - reserve)
    confident = count >= MIN_MONTHS_FOR_MEDIUM_CONFIDENCE and observed and not any("stale" in w for w in warnings)
    return {"currency": currency, "months_used": count, "data_through": data_through,
            "income_sources": sources, "unassigned_income": top_unassigned,
            "monthly_income": monthly_income, "monthly_consumption": consumption, "monthly_tax": tax_monthly,
            "expected_surplus": expected, "conservative_surplus": conservative,
            "cash_on_hand": cash, "allocated": allocated, "reserve_months": prefs["reserve_months"],
            "reserve": reserve, "usable_cash": usable,
            "confidence": "medium" if confident else "low",
            "assumptions": ["Surplus = income - consumption - tax, excluding transfers, savings and your own transfers",
                            "Conservative = lower quartile of monthly surplus; expected = 12-month average",
                            "Cash on hand uses observed balances, which are not a complete net worth"],
            "warnings": sorted(set(warnings))}


def months_needed(shortfall: Decimal, monthly: Decimal) -> int | None:
    if monthly <= 0:
        return None
    return int((shortfall / monthly).to_integral_value(rounding=ROUND_CEILING))


def assess(base: dict, wishes: list[Wish], today: date) -> list[dict]:
    expected, conservative, usable = base["expected_surplus"], base["conservative_surplus"], base["usable_cash"]
    open_wishes = sorted((w for w in wishes if w.status == "open"),
                         key=lambda w: (w.priority, w.due_date or date.max, w.price, w.created_at))
    results, committed, follow_up = [], ZERO, ZERO
    for wish in open_wishes:
        if wish.currency != base["currency"]:
            results.append({"id": wish.id, "verdict": "unsupported_currency",
                            "warnings": [f"Wish is in {wish.currency}; assessment covers {base['currency']} only"]})
            continue
        committed += wish.price
        follow_up += wish.follow_up_monthly_cost
        shortfall = max(ZERO, committed - usable)
        months_c = months_needed(shortfall, conservative)
        months_e = months_needed(shortfall, expected)
        if shortfall == 0:
            verdict = "affordable"
        elif months_c is not None and months_c <= CONSERVATIVE_HORIZON_MONTHS:
            verdict = "save_up"
        elif months_e is not None and months_e <= EXPECTED_HORIZON_MONTHS:
            verdict = "tight"
        else:
            verdict = "not_now"
        item = {"id": wish.id, "verdict": verdict, "cumulative_price": committed, "shortfall": shortfall,
                "months_conservative": 0 if shortfall == 0 else months_c, "months_expected": 0 if shortfall == 0 else months_e,
                "date_conservative": today if shortfall == 0 else (add_months(today, months_c) if months_c is not None else None),
                "date_expected": today if shortfall == 0 else (add_months(today, months_e) if months_e is not None else None),
                "share_of_annual_surplus": wish.price / (expected * 12) if expected > 0 else None,
                "surplus_after_follow_up_costs": expected - follow_up, "warnings": []}
        if wish.due_date:
            months_until = max(1, (wish.due_date.year - today.year) * 12 + wish.due_date.month - today.month)
            item["required_monthly_for_due_date"] = shortfall / months_until
            item["on_time_conservative"] = shortfall == 0 or (months_c is not None and months_c <= months_until)
            item["on_time_expected"] = shortfall == 0 or (months_e is not None and months_e <= months_until)
        if expected - follow_up <= 0 and follow_up > 0:
            item["warnings"].append("Running costs of this and earlier wishes would consume the whole expected surplus")
        results.append(item)
    return results


def wish_json(wish: Wish) -> dict:
    data = serialize(wish)
    data.pop("user_id", None)
    return data


class WishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=300)
    price: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    currency: str = Field(default="EUR", pattern="^[A-Z]{3}$")
    priority: int = Field(default=3, ge=1, le=5)
    due_date: date | None = None
    follow_up_monthly_cost: Decimal = Field(default=ZERO, ge=0, max_digits=24, decimal_places=8)
    note: str = Field(default="", max_length=2000)
    status: Literal["open", "bought", "dropped"] = "open"


class WishPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=300)
    price: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    priority: int | None = Field(default=None, ge=1, le=5)
    due_date: date | None = None
    follow_up_monthly_cost: Decimal | None = Field(default=None, ge=0, max_digits=24, decimal_places=8)
    note: str | None = Field(default=None, max_length=2000)
    status: Literal["open", "bought", "dropped"] | None = None


class PrefsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    self_names: list[str] = Field(default_factory=list, max_length=20)
    reserve_months: int = Field(default=3, ge=0, le=24)
    monthly_tax_reserve: Decimal = Field(default=ZERO, ge=0, max_digits=24, decimal_places=8)


def owned_wish(db, ident, user) -> Wish:
    wish = db.scalar(select(Wish).where(Wish.id == ident, Wish.user_id == user.id).execution_options(populate_existing=True))
    if wish is None:
        raise HTTPException(404, "Not found")
    return wish


def overview_payload(db, user, currency="EUR"):
    today = local_today(db, user.id)
    base = baseline(db, user.id, currency, today)
    wishes = list(db.scalars(select(Wish).where(Wish.user_id == user.id).order_by(Wish.created_at)))
    assessments = {a["id"]: a for a in assess(base, wishes, today)}
    prefs = get_prefs(db, user.id)
    return serialize({"baseline": base, "prefs": prefs,
                      "wishes": [{**wish_json(w), "assessment": assessments.get(w.id)} for w in wishes],
                      "disclaimer": "Planning aid based on your own data; not financial, tax or investment advice."})


@router.get("/wishlist")
def get_wishlist(currency: str = "EUR", db: Session = Depends(get_db), user=Depends(current_user)):
    if len(currency) != 3 or not currency.isupper():
        raise HTTPException(422, "Invalid currency")
    return overview_payload(db, user, currency)


@router.post("/wishes", status_code=201)
def create_wish(body: WishBody, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    wish = Wish(user_id=user.id, **body.model_dump())
    db.add(wish)
    db.commit()
    return wish_json(wish)


@router.patch("/wishes/{ident}")
def patch_wish(ident: str, body: WishPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    wish = owned_wish(db, ident, user)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None and key != "due_date":
            raise HTTPException(422, f"{key} cannot be null")
        setattr(wish, key, value)
    db.commit()
    return wish_json(wish)


@router.delete("/wishes/{ident}")
def delete_wish(ident: str, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    db.delete(owned_wish(db, ident, user))
    db.commit()
    return {"ok": True}


@router.put("/wishlist/prefs")
def put_prefs(body: PrefsBody, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    names = [n.strip() for n in body.self_names if n.strip()]
    row = db.get(WishlistPrefs, user.id)
    if row is None:
        row = WishlistPrefs(user_id=user.id)
        db.add(row)
    row.self_names, row.reserve_months, row.monthly_tax_reserve = names, body.reserve_months, body.monthly_tax_reserve
    db.commit()
    return overview_payload(db, user)
