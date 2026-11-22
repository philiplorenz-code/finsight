"""Contract terms and cancellation deadlines, entered by the owner per detected contract (keyed like decisions).

term_end + notice period give the last day to cancel. With automatic renewal the term rolls forward by the
renewal length until the deadline is in the future, so the calendar always shows the next real chance.
"""
from __future__ import annotations

import calendar
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import current_user
from .db import Base, get_db
from .finance import contracts, local_today

router = APIRouter(tags=["contract-terms"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ContractTerm(Base):
    __tablename__ = "contract_terms"
    __table_args__ = (UniqueConstraint("user_id", "key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(String(300))
    term_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    notice_days: Mapped[int] = mapped_column(Integer, default=30)
    renew_months: Mapped[int] = mapped_column(Integer, default=12)  # 0 = ends without renewal
    note: Mapped[str] = mapped_column(String(300), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def next_deadline(term: ContractTerm, today: date) -> dict | None:
    if not term.term_end:
        return None
    end = term.term_end
    deadline = end - timedelta(days=term.notice_days)
    rolled = 0
    while deadline < today and term.renew_months > 0 and rolled < 600:
        end = add_months(end, term.renew_months)
        deadline = end - timedelta(days=term.notice_days)
        rolled += 1
    expired = deadline < today
    return {"term_end": end.isoformat(), "cancel_by": deadline.isoformat(), "days_left": (deadline - today).days, "expired": expired}


class TermBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term_end: date | None = None
    notice_days: int = Field(default=30, ge=0, le=730)
    renew_months: int = Field(default=12, ge=0, le=120)
    note: str = Field(default="", max_length=300)


def deadlines(db: Session, user_id: str, today: date | None = None) -> list[dict]:
    today = today or local_today(db, user_id)
    items = {i["key"]: i for i in contracts(db, user_id)["items"]}
    out = []
    for term in db.scalars(select(ContractTerm).where(ContractTerm.user_id == user_id)):
        nxt = next_deadline(term, today)
        item = items.get(term.key)
        out.append({"key": term.key, "name": item["name"] if item else term.key, "kind": item["kind"] if item else None,
                    "annual_cost": item["annual_cost"] if item else None, "status": item["status"] if item else "unknown",
                    "notice_days": term.notice_days, "renew_months": term.renew_months, "note": term.note,
                    "configured_term_end": term.term_end.isoformat() if term.term_end else None, **(nxt or {})})
    return sorted(out, key=lambda d: d.get("cancel_by") or "9999")


@router.get("/contract-terms")
def list_terms(db: Session = Depends(get_db), user=Depends(current_user)):
    return {"items": deadlines(db, user.id)}


@router.put("/contract-terms")
def put_term(body: TermBody, key: str = Query(..., min_length=1, max_length=300), db: Session = Depends(get_db), user=Depends(current_user)):
    term = db.scalar(select(ContractTerm).where(ContractTerm.user_id == user.id, ContractTerm.key == key))
    if term is None:
        term = ContractTerm(user_id=user.id, key=key)
        db.add(term)
    for field, value in body.model_dump().items():
        setattr(term, field, value)
    term.updated_at = utcnow()
    db.commit()
    return next(d for d in deadlines(db, user.id) if d["key"] == key)


@router.delete("/contract-terms", status_code=204)
def delete_term(key: str = Query(..., min_length=1, max_length=300), db: Session = Depends(get_db), user=Depends(current_user)):
    term = db.scalar(select(ContractTerm).where(ContractTerm.user_id == user.id, ContractTerm.key == key))
    if not term:
        raise HTTPException(404, "No terms stored for this contract")
    db.delete(term)
    db.commit()
