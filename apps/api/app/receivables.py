"""Open items between you and other people: money you will get back (receivable) or still owe (payable).

A matching booking (same amount, right direction, on or after the item's date, payee containing the person's
name when that is possible) is suggested as the settlement; the owner confirms it. Nothing is booked here.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import current_user
from .db import Base, get_db
from .finance import eligible, local_today, serialize
from .models import Account, Transaction

router = APIRouter(tags=["receivables"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OpenItem(Base):
    __tablename__ = "open_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    direction: Mapped[str] = mapped_column(String(10))  # receivable | payable
    person: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    since: Mapped[date] = mapped_column(Date)
    due: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | settled | dropped
    settled_transaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    settled_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: Literal["receivable", "payable"]
    person: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=0, le=Decimal("10000000"))
    since: date | None = None
    due: date | None = None
    note: str = Field(default="", max_length=300)


class ItemPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "settled", "dropped"] | None = None
    settled_transaction_id: str | None = Field(default=None, max_length=36)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    amount: Decimal | None = Field(default=None, gt=0, le=Decimal("10000000"))
    due: date | None = None
    note: str | None = Field(default=None, max_length=300)


def suggestion(db: Session, item: OpenItem) -> dict | None:
    if item.status != "open":
        return None
    sign = Decimal(1) if item.direction == "receivable" else Decimal(-1)
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.user_id == item.user_id)) if a.included and a.purpose != "mirror"}
    candidates = [tx for tx in db.scalars(select(Transaction).where(Transaction.user_id == item.user_id, Transaction.amount == sign * item.amount,
                                                                     Transaction.booking_date >= item.since)) if tx.account_id in accounts and not tx.is_transfer]
    if not candidates:
        return None
    word = item.person.split()[0].casefold() if item.person.split() else ""
    candidates.sort(key=lambda tx: (not (word and word in f"{tx.merchant} {tx.description}".casefold()), tx.booking_date))
    tx = candidates[0]
    return {"transaction_id": tx.id, "date": tx.booking_date.isoformat(), "merchant": tx.merchant, "account": accounts[tx.account_id].name,
            "name_matches": bool(word and word in f"{tx.merchant} {tx.description}".casefold())}


def item_json(db: Session, item: OpenItem, today: date) -> dict:
    data = serialize(item)
    data.pop("user_id", None)
    data["overdue"] = bool(item.status == "open" and item.due and item.due < today)
    data["suggested_settlement"] = suggestion(db, item)
    return data


def owned_item(db: Session, ident: str, user) -> OpenItem:
    item = db.scalar(select(OpenItem).where(OpenItem.id == ident, OpenItem.user_id == user.id))
    if not item:
        raise HTTPException(404, "Open item not found")
    return item


@router.get("/open-items")
def list_items(db: Session = Depends(get_db), user=Depends(current_user)):
    today = local_today(db, user.id)
    rows = [item_json(db, i, today) for i in db.scalars(select(OpenItem).where(OpenItem.user_id == user.id).order_by(OpenItem.created_at))]
    open_rows = [r for r in rows if r["status"] == "open"]
    total = lambda d: sum((Decimal(r["amount"]) for r in open_rows if r["direction"] == d), Decimal(0))  # noqa: E731
    return serialize({"items": rows, "totals": {"receivable": total("receivable"), "payable": total("payable"),
                                                "net": total("receivable") - total("payable")}})


@router.post("/open-items", status_code=201)
def create_item(body: ItemIn, db: Session = Depends(get_db), user=Depends(current_user)):
    item = OpenItem(user_id=user.id, direction=body.direction, person=body.person.strip(), title=body.title.strip(), amount=body.amount,
                    since=body.since or local_today(db, user.id), due=body.due, note=body.note.strip())
    db.add(item)
    db.commit()
    return item_json(db, item, local_today(db, user.id))


@router.patch("/open-items/{ident}")
def patch_item(ident: str, body: ItemPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    item = owned_item(db, ident, user)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("settled_transaction_id"):
        tx = db.scalar(select(Transaction).where(Transaction.id == changes["settled_transaction_id"], Transaction.user_id == user.id))
        if not tx or not eligible(tx):
            raise HTTPException(404, "Transaction not found")
        item.settled_on = tx.booking_date
        changes.setdefault("status", "settled")
    for key, value in changes.items():
        setattr(item, key, value)
    if item.status == "open":
        item.settled_transaction_id, item.settled_on = None, None
    elif item.status == "settled" and not item.settled_on:
        item.settled_on = local_today(db, user.id)
    db.commit()
    return item_json(db, item, local_today(db, user.id))


@router.delete("/open-items/{ident}", status_code=204)
def delete_item(ident: str, db: Session = Depends(get_db), user=Depends(current_user)):
    db.delete(owned_item(db, ident, user))
    db.commit()
