"""Income source rules: split income into employment, business and other.

Rules are evaluated in `position` order; the first match wins. A rule matches when its optional
account equals the booking's account and its pattern (case-insensitive substring; empty = any)
appears in the merchant, the description or either. Unmatched income is "other".
A rule with `shift_from_day` counts matching bookings made on or after that day of the month in the
following month (salary paid at month end covers the next month).
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .finance import ZERO, serialize
from .locking import lock_owner
from .models import Account, IncomeRule

router = APIRouter(tags=["income"])

SOURCES = ("employment", "business", "other")
Source = Literal["employment", "business", "other"]
MatchField = Literal["merchant", "description", "any"]


def load_rules(db, user_id) -> list[IncomeRule]:
    return list(db.scalars(select(IncomeRule).where(IncomeRule.user_id == user_id)
                           .order_by(IncomeRule.position, IncomeRule.created_at)))


def match_rule(tx, rules) -> IncomeRule | None:
    merchant = (tx.merchant or "").casefold()
    description = (tx.description or "").casefold()
    for rule in rules:
        if rule.account_id and rule.account_id != tx.account_id:
            continue
        pattern = (rule.pattern or "").strip().casefold()
        haystack = {"merchant": merchant, "description": description}.get(rule.match_field, f"{merchant}\n{description}")
        if not pattern or pattern in haystack:
            return rule
    return None


def classify(tx, rules) -> str:
    rule = match_rule(tx, rules)
    return rule.source if rule else "other"


def shifts_to_next_month(tx, rule) -> bool:
    """Pay booked at month end (from `shift_from_day`) belongs to the following month."""
    return bool(rule and rule.shift_from_day and tx.booking_date.day >= rule.shift_from_day)


def source_stats(series: dict[str, list[Decimal]]) -> dict[str, dict]:
    """Per source: monthly average, lower quartile and number of months with income."""
    total = sum((sum(v, ZERO) for v in series.values()), ZERO)
    out = {}
    for source in SOURCES:
        values = series.get(source, [])
        count = len(values)
        ordered = sorted(values)
        out[source] = {
            "monthly_average": sum(values, ZERO) / count if count else ZERO,
            "monthly_lower_quartile": ordered[(count - 1) // 4] if count else ZERO,
            "months_with_income": sum(1 for v in values if v > ZERO),
            "share": (sum(values, ZERO) / total) if total else ZERO,
        }
    return out


class RuleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    source: Source
    pattern: str = Field(default="", max_length=200)
    match_field: MatchField = "any"
    account_id: str | None = None
    position: int = Field(default=0, ge=0, le=1000)
    shift_from_day: int | None = Field(default=None, ge=1, le=31)


class RulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    source: Source | None = None
    pattern: str | None = Field(default=None, max_length=200)
    match_field: MatchField | None = None
    account_id: str | None = None
    position: int | None = Field(default=None, ge=0, le=1000)
    shift_from_day: int | None = Field(default=None, ge=1, le=31)


def check_account(db, user, account_id):
    if account_id and db.scalar(select(Account.id).where(Account.id == account_id, Account.user_id == user.id)) is None:
        raise HTTPException(422, "Unknown account")


def owned_rule(db, ident, user) -> IncomeRule:
    rule = db.scalar(select(IncomeRule).where(IncomeRule.id == ident, IncomeRule.user_id == user.id)
                     .execution_options(populate_existing=True))
    if rule is None:
        raise HTTPException(404, "Not found")
    return rule


def rule_json(rule) -> dict:
    data = serialize(rule)
    data.pop("user_id", None)
    return data


@router.get("/income-rules")
def list_rules(db: Session = Depends(get_db), user=Depends(current_user)):
    return [rule_json(r) for r in load_rules(db, user.id)]


@router.post("/income-rules", status_code=201)
def create_rule(body: RuleBody, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    check_account(db, user, body.account_id)
    if not body.pattern.strip() and not body.account_id:
        raise HTTPException(422, "A rule needs a pattern or an account")
    rule = IncomeRule(user_id=user.id, **{**body.model_dump(), "pattern": body.pattern.strip()})
    db.add(rule)
    db.commit()
    return rule_json(rule)


@router.patch("/income-rules/{ident}")
def patch_rule(ident: str, body: RulePatch, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    rule = owned_rule(db, ident, user)
    changes = body.model_dump(exclude_unset=True)
    if "account_id" in changes:
        check_account(db, user, changes["account_id"])
    for key, value in changes.items():
        if value is None and key not in ("account_id", "shift_from_day"):
            raise HTTPException(422, f"{key} cannot be null")
    pattern = (changes["pattern"] if "pattern" in changes else rule.pattern or "").strip()
    account_id = changes["account_id"] if "account_id" in changes else rule.account_id
    if not pattern and not account_id:
        raise HTTPException(422, "A rule needs a pattern or an account")
    for key, value in changes.items():
        setattr(rule, key, value.strip() if key == "pattern" else value)
    db.commit()
    return rule_json(rule)


@router.delete("/income-rules/{ident}")
def delete_rule(ident: str, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    db.delete(owned_rule(db, ident, user))
    db.commit()
    return {"ok": True}
