"""Accounts that still need a decision after an import, with suggestions, and one-step classification.

New accounts arrive with unknown ownership and are excluded from every calculation until the user decides
whether they are theirs and what they are used for. The suggestions are hints from the account name, the
balance and how the account is used; the user always confirms.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .finance import latest_balance, local_today, serialize
from .locking import lock_owner
from .models import Account, Transaction

router = APIRouter(tags=["accounts"])

Ownership = Literal["owned", "external"]
Purpose = Literal["checking", "savings", "investment", "credit", "cash", "other"]
KEYWORDS = {
    "investment": ("depot", "etf", "broker", "wertpapier", "invest", "trade republic", "scalable", "aktien", "msci"),
    "credit": ("kredit", "visa", "mastercard", "amex", "american express", "kreditkarte", "card"),
    "savings": ("spar", "tagesgeld", "festgeld", "ziel", "topf", "pot", "rücklage", "ruecklage", "umzug", "urlaub", "notgroschen"),
    "cash": ("bargeld", "cash", "kasse", "wallet"),
}


def suggest(name: str, balance, bookings: int, transfers: int) -> dict:
    text = (name or "").casefold()
    for purpose in ("investment", "credit", "savings", "cash"):
        if any(word in text for word in KEYWORDS[purpose]):
            return {"ownership": "owned", "purpose": purpose, "reason": f"name:{purpose}"}
    if balance is not None and balance < 0:
        return {"ownership": "owned", "purpose": "credit", "reason": "negative_balance"}
    if bookings and transfers / bookings >= 0.8:
        return {"ownership": "owned", "purpose": "savings", "reason": "mostly_transfers"}
    return {"ownership": "owned", "purpose": "checking", "reason": "default"}


@router.get("/accounts/unclassified")
def unclassified(db: Session = Depends(get_db), user=Depends(current_user)):
    today = local_today(db, user.id)
    accounts = [a for a in db.scalars(select(Account).where(Account.user_id == user.id, Account.ownership == "unknown").order_by(Account.name))]
    stats = {row[0]: (row[1], row[2] or 0, row[3]) for row in db.execute(
        select(Transaction.account_id, func.count(), func.sum(cast(Transaction.is_transfer, Integer)),
               func.max(Transaction.booking_date)).where(Transaction.user_id == user.id).group_by(Transaction.account_id))}
    items = []
    for account in accounts:
        observation = latest_balance(db, account.id, today)
        bookings, transfers, last = stats.get(account.id, (0, 0, None))
        balance = observation.amount if observation else None
        items.append({"id": account.id, "name": account.name, "currency": account.currency, "balance": balance,
                      "bookings": bookings, "last_booking": last, "suggestion": suggest(account.name, balance, bookings, int(transfers))})
    return serialize({"count": len(items), "items": items})


class ClassifyItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=36)
    ownership: Ownership
    purpose: Purpose = "checking"
    included: bool = True


class ClassifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ClassifyItem] = Field(min_length=1, max_length=200)


@router.post("/accounts/classify")
def classify(body: ClassifyBody, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    ids = [item.id for item in body.items]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "Duplicate account")
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.user_id == user.id, Account.id.in_(ids)))}
    if len(accounts) != len(ids):
        raise HTTPException(404, "Unknown account")
    for item in body.items:
        account = accounts[item.id]
        account.ownership, account.purpose, account.included = item.ownership, item.purpose, item.included
    db.commit()
    return {"classified": len(body.items)}
