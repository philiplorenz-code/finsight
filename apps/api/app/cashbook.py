"""Cash book: log what you spend in cash, without counting it twice.

From the start date the owner sets, ATM withdrawals (effective category "Bargeld") stop counting as spending:
the money only moves into the wallet. Logged cash expenses count instead, each with its own category, in the
overview, the baseline (wishlist, forecast, health) and plan vs. actual. Wallet = withdrawals - logged cash.
Before the start date nothing changes.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import current_user
from .db import Base, get_db
from .finance import eligible, local_today, serialize

router = APIRouter(tags=["cashbook"])
CASH_CATEGORIES = {"bargeld", "cash", "geldautomat"}
SETTING_KEY = "cashbook_since"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CashEntry(Base):
    __tablename__ = "cash_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    category: Mapped[str] = mapped_column(String(120))
    merchant: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def since(db: Session, user_id: str) -> date | None:
    from .models import Setting
    row = db.get(Setting, user_id)
    value = (row.data or {}).get(SETTING_KEY) if row else None
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def is_withdrawal(tx, start: date | None) -> bool:
    return bool(start and tx.amount < 0 and tx.booking_date >= start
                and (tx.effective_category or "").strip().casefold() in CASH_CATEGORIES)


def entries(db: Session, user_id: str, first: date, last: date) -> list[CashEntry]:
    start = since(db, user_id)
    if not start:
        return []
    return list(db.scalars(select(CashEntry).where(CashEntry.user_id == user_id, CashEntry.day >= max(first, start), CashEntry.day <= last)))


def wallet(db: Session, user_id: str) -> dict:
    from .models import Account, Transaction
    start = since(db, user_id)
    if not start:
        return {"enabled": False}
    accounts = {a.id for a in db.scalars(select(Account).where(Account.user_id == user_id)) if a.included and a.ownership != "external" and a.purpose != "mirror"}
    withdrawn = sum((-tx.amount for tx in db.scalars(select(Transaction).where(Transaction.user_id == user_id, Transaction.booking_date >= start))
                     if tx.account_id in accounts and eligible(tx) and is_withdrawal(tx, start)), Decimal(0))
    spent = sum((e.amount for e in db.scalars(select(CashEntry).where(CashEntry.user_id == user_id, CashEntry.day >= start))), Decimal(0))
    return {"enabled": True, "since": start.isoformat(), "withdrawn": withdrawn, "logged": spent, "in_wallet": withdrawn - spent}


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    since: date | None = None


class EntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: date | None = None
    amount: Decimal = Field(gt=0, le=Decimal("100000"))
    category: str = Field(min_length=1, max_length=120)
    merchant: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=300)


@router.get("/cashbook")
def get_cashbook(db: Session = Depends(get_db), user=Depends(current_user)):
    rows = db.scalars(select(CashEntry).where(CashEntry.user_id == user.id).order_by(CashEntry.day.desc(), CashEntry.created_at.desc()).limit(500))
    return serialize({"wallet": wallet(db, user.id), "entries": [{k: v for k, v in serialize(e).items() if k != "user_id"} for e in rows]})


@router.put("/cashbook/settings")
def put_settings(body: Settings, db: Session = Depends(get_db), user=Depends(current_user)):
    from .models import Setting
    row = db.get(Setting, user.id)
    if row is None:
        row = Setting(user_id=user.id, data={})
        db.add(row)
    data = dict(row.data or {})
    if body.since:
        data[SETTING_KEY] = body.since.isoformat()
    else:
        data.pop(SETTING_KEY, None)
    row.data = data
    db.commit()
    return serialize(wallet(db, user.id))


@router.post("/cashbook/entries", status_code=201)
def add_entry(body: EntryIn, db: Session = Depends(get_db), user=Depends(current_user)):
    if not since(db, user.id):
        raise HTTPException(409, "Start the cash book first (choose a start date)")
    entry = CashEntry(user_id=user.id, day=body.day or local_today(db, user.id), amount=body.amount, category=body.category.strip(),
                      merchant=body.merchant.strip(), note=body.note.strip())
    db.add(entry)
    db.commit()
    return {k: v for k, v in serialize(entry).items() if k != "user_id"}


@router.delete("/cashbook/entries/{ident}", status_code=204)
def delete_entry(ident: str, db: Session = Depends(get_db), user=Depends(current_user)):
    entry = db.scalar(select(CashEntry).where(CashEntry.id == ident, CashEntry.user_id == user.id))
    if not entry:
        raise HTTPException(404, "Entry not found")
    db.delete(entry)
    db.commit()
