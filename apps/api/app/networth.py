"""Net worth: observed account balances plus manually tracked assets and debts, split by ownership share.

`share` is the percentage that belongs to the user. The remainder belongs to someone else (a car financed
together, a joint account) and is shown separately instead of being counted as the user's wealth.
"""
from __future__ import annotations

import calendar
import math
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .finance import ZERO, balance_is_stale, latest_balance, local_today, serialize
from .locking import lock_owner
from .models import Account, Holding

router = APIRouter(tags=["net-worth"])

Kind = Literal["asset", "liability"]
Category = Literal["car", "property", "loan", "depot", "cash", "other"]
HUNDRED = Decimal(100)
HISTORY_MONTHS = 24


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def payoff(balance: Decimal, payment: Decimal | None, rate_percent: Decimal | None, today: date) -> dict:
    """Months until a debt is repaid by a fixed payment; None when the payment never covers the interest."""
    if balance <= 0:
        return {"months_left": 0, "payoff_date": today.isoformat()}
    if not payment or payment <= 0:
        return {"months_left": None, "payoff_date": None}
    monthly_rate = float((rate_percent or ZERO) / HUNDRED / 12)
    b, p = float(balance), float(payment)
    if monthly_rate == 0:
        months = math.ceil(b / p)
    else:
        if p <= b * monthly_rate:
            return {"months_left": None, "payoff_date": None}
        months = math.ceil(-math.log(1 - b * monthly_rate / p) / math.log(1 + monthly_rate))
    index = today.year * 12 + today.month - 1 + months
    year, month = divmod(index, 12)
    return {"months_left": months, "payoff_date": date(year, month + 1, 1).isoformat()}


def split(value: Decimal, share: Decimal) -> tuple[Decimal, Decimal]:
    mine = value * share / HUNDRED
    return mine, value - mine


def net_worth(db: Session, user_id: str, currency: str = "EUR") -> dict:
    today = local_today(db, user_id)
    accounts = [a for a in db.scalars(select(Account).where(Account.user_id == user_id))
                if a.included and a.ownership == "owned" and a.currency == currency]
    rows, assets, liabilities = [], [], []
    stale = 0
    missing = 0
    for account in accounts:
        obs = latest_balance(db, account.id, today)
        if not obs:
            missing += 1
            continue
        if balance_is_stale(account, obs, today):
            stale += 1
        mine, others = split(obs.amount, account.owner_share)
        rows.append({"id": account.id, "name": account.name, "purpose": account.purpose, "balance": obs.amount,
                     "observed_date": obs.observed_date, "share": account.owner_share, "mine": mine, "others": others})
        (assets if obs.amount >= 0 else liabilities).append((abs(mine), abs(others)))

    holdings, ignored = [], 0
    monthly_debt_service = ZERO
    for h in db.scalars(select(Holding).where(Holding.user_id == user_id).order_by(Holding.kind, Holding.name)):
        if h.currency != currency:
            ignored += 1
            continue
        mine, others = split(h.value, h.share)
        item = {"id": h.id, "name": h.name, "kind": h.kind, "category": h.category, "value": h.value,
                "share": h.share, "mine": mine, "others": others, "monthly_payment": h.monthly_payment,
                "interest_rate": h.interest_rate, "note": h.note, "valued_on": h.valued_on}
        if h.kind == "liability":
            item.update(payoff(h.value, h.monthly_payment, h.interest_rate, today))
            monthly_debt_service += (h.monthly_payment or ZERO) * h.share / HUNDRED
            liabilities.append((mine, others))
        else:
            assets.append((mine, others))
        holdings.append(item)

    a_mine = sum((m for m, _ in assets), ZERO)
    a_oth = sum((o for _, o in assets), ZERO)
    l_mine = sum((m for m, _ in liabilities), ZERO)
    l_oth = sum((o for _, o in liabilities), ZERO)
    totals = {"assets_mine": a_mine, "assets_others": a_oth, "liabilities_mine": l_mine, "liabilities_others": l_oth,
              "net_worth_mine": a_mine - l_mine, "net_worth_others": a_oth - l_oth,
              "net_worth_gross": a_mine + a_oth - l_mine - l_oth, "monthly_debt_service": monthly_debt_service}

    history = []
    index = today.year * 12 + today.month - 1
    for back in range(HISTORY_MONTHS - 1, -1, -1):
        year, month = divmod(index - back, 12)
        end = min(month_end(year, month + 1), today)
        total, seen = ZERO, 0
        for account in accounts:
            obs = latest_balance(db, account.id, end)
            if obs:
                total += obs.amount * account.owner_share / HUNDRED
                seen += 1
        if seen:
            history.append({"month": f"{year}-{month + 1:02d}", "accounts_mine": total, "accounts_counted": seen})
    return serialize({"currency": currency, "accounts": rows, "holdings": holdings, "totals": totals, "history": history,
                      "accounts_without_balance": missing, "stale_balances": stale, "other_currency_holdings": ignored})


class HoldingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=300)
    kind: Kind
    category: Category = "other"
    value: Decimal = Field(ge=0, max_digits=20, decimal_places=2)
    currency: str = Field(default="EUR", pattern="^[A-Z]{3}$")
    share: Decimal = Field(default=HUNDRED, ge=0, le=100)
    monthly_payment: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=2)
    interest_rate: Decimal | None = Field(default=None, ge=0, le=100)
    note: str = Field(default="", max_length=1000)


class HoldingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=300)
    kind: Kind | None = None
    category: Category | None = None
    value: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=2)
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    share: Decimal | None = Field(default=None, ge=0, le=100)
    monthly_payment: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=2)
    interest_rate: Decimal | None = Field(default=None, ge=0, le=100)
    note: str | None = Field(default=None, max_length=1000)


def owned_holding(db, ident, user) -> Holding:
    holding = db.scalar(select(Holding).where(Holding.id == ident, Holding.user_id == user.id)
                        .execution_options(populate_existing=True))
    if holding is None:
        raise HTTPException(404, "Not found")
    return holding


@router.get("/net-worth")
def get_net_worth(currency: str = Query("EUR", pattern="^[A-Z]{3}$"), db: Session = Depends(get_db), user=Depends(current_user)):
    return net_worth(db, user.id, currency)


@router.post("/holdings", status_code=201)
def create_holding(body: HoldingBody, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    holding = Holding(user_id=user.id, valued_on=local_today(db, user.id), **body.model_dump())
    db.add(holding)
    db.commit()
    return serialize(holding)


@router.patch("/holdings/{ident}")
def patch_holding(ident: str, body: HoldingPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    holding = owned_holding(db, ident, user)
    changes = body.model_dump(exclude_unset=True)
    for key in ("name", "kind", "category", "value", "currency", "share", "note"):
        if key in changes and changes[key] is None:
            raise HTTPException(422, f"{key} cannot be null")
    for key, value in changes.items():
        setattr(holding, key, value)
    if "value" in changes:
        holding.valued_on = local_today(db, user.id)
    db.commit()
    return serialize(holding)


@router.delete("/holdings/{ident}")
def delete_holding(ident: str, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    db.delete(owned_holding(db, ident, user))
    db.commit()
    return {"ok": True}
