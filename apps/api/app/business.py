"""Business expense rules: spending that belongs to the business is reported apart from private consumption.

A rule matches an outflow when every condition it sets holds: account, category (case-insensitive equality
with the effective category) and pattern (case-insensitive substring in merchant/description/either).
A rule needs at least one condition. Totals are unchanged; the rules only split spending.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .finance import serialize
from .locking import lock_owner
from .models import Account, BusinessRule

router = APIRouter(tags=["business"])

MatchField = Literal["merchant", "description", "any"]
TAX_RESERVE_RATE = Decimal("0.30")


def load_business_rules(db, user_id) -> list[BusinessRule]:
    return list(db.scalars(select(BusinessRule).where(BusinessRule.user_id == user_id)
                           .order_by(BusinessRule.position, BusinessRule.created_at)))


def is_business_expense(tx, rules) -> bool:
    if tx.amount >= 0:
        return False
    merchant = (tx.merchant or "").casefold()
    description = (tx.description or "").casefold()
    category = (tx.effective_category or "").strip().casefold()
    for rule in rules:
        if rule.account_id and rule.account_id != tx.account_id:
            continue
        if rule.category and rule.category.strip().casefold() != category:
            continue
        pattern = (rule.pattern or "").strip().casefold()
        haystack = {"merchant": merchant, "description": description}.get(rule.match_field, f"{merchant}\n{description}")
        if pattern and pattern not in haystack:
            continue
        return True
    return False


class RuleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    pattern: str = Field(default="", max_length=200)
    match_field: MatchField = "any"
    category: str | None = Field(default=None, max_length=300)
    account_id: str | None = None
    position: int = Field(default=0, ge=0, le=1000)


class RulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    pattern: str | None = Field(default=None, max_length=200)
    match_field: MatchField | None = None
    category: str | None = Field(default=None, max_length=300)
    account_id: str | None = None
    position: int | None = Field(default=None, ge=0, le=1000)


def check_account(db, user, account_id):
    if account_id and db.scalar(select(Account.id).where(Account.id == account_id, Account.user_id == user.id)) is None:
        raise HTTPException(422, "Unknown account")


def owned_rule(db, ident, user) -> BusinessRule:
    rule = db.scalar(select(BusinessRule).where(BusinessRule.id == ident, BusinessRule.user_id == user.id)
                     .execution_options(populate_existing=True))
    if rule is None:
        raise HTTPException(404, "Not found")
    return rule


def rule_json(rule) -> dict:
    data = serialize(rule)
    data.pop("user_id", None)
    return data


def has_condition(pattern, category, account_id) -> bool:
    return bool((pattern or "").strip() or (category or "").strip() or account_id)


@router.get("/business-rules")
def list_rules(db: Session = Depends(get_db), user=Depends(current_user)):
    return [rule_json(r) for r in load_business_rules(db, user.id)]


@router.post("/business-rules", status_code=201)
def create_rule(body: RuleBody, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    check_account(db, user, body.account_id)
    if not has_condition(body.pattern, body.category, body.account_id):
        raise HTTPException(422, "A rule needs a pattern, a category or an account")
    data = {**body.model_dump(), "pattern": body.pattern.strip(), "category": (body.category or "").strip() or None}
    rule = BusinessRule(user_id=user.id, **data)
    db.add(rule)
    db.commit()
    return rule_json(rule)


@router.patch("/business-rules/{ident}")
def patch_rule(ident: str, body: RulePatch, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    rule = owned_rule(db, ident, user)
    changes = body.model_dump(exclude_unset=True)
    if "account_id" in changes:
        check_account(db, user, changes["account_id"])
    for key in ("name", "pattern", "match_field", "position"):
        if key in changes and changes[key] is None:
            raise HTTPException(422, f"{key} cannot be null")
    pattern = changes["pattern"] if "pattern" in changes else rule.pattern
    category = changes["category"] if "category" in changes else rule.category
    account_id = changes["account_id"] if "account_id" in changes else rule.account_id
    if not has_condition(pattern, category, account_id):
        raise HTTPException(422, "A rule needs a pattern, a category or an account")
    for key, value in changes.items():
        if key == "pattern":
            value = value.strip()
        if key == "category":
            value = (value or "").strip() or None
        setattr(rule, key, value)
    db.commit()
    return rule_json(rule)


@router.delete("/business-rules/{ident}")
def delete_rule(ident: str, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    db.delete(owned_rule(db, ident, user))
    db.commit()
    return {"ok": True}
