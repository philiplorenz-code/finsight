"""Category rules: assign a category to matching bookings without touching the imported data.

A rule matches when every condition it sets holds: account, flow (income = amount > 0, expense = amount < 0)
and pattern (case-insensitive substring in merchant/description/either). The first rule by `position` wins.
The result is stored in `Transaction.rule_category`; a manual correction (`category_override`) always wins over
a rule, and a rule wins over the imported category. Rules are re-applied after every import and rule change.
"""
from __future__ import annotations

from collections import Counter
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .finance import serialize
from .locking import lock_owner
from .models import Account, CategoryRule, Transaction

router = APIRouter(tags=["category-rules"])

MatchField = Literal["merchant", "description", "any"]
Flow = Literal["any", "income", "expense"]


def load_category_rules(db, user_id) -> list[CategoryRule]:
    return list(db.scalars(select(CategoryRule).where(CategoryRule.user_id == user_id)
                           .order_by(CategoryRule.position, CategoryRule.created_at)))


def rule_matches(rule, tx, merchant: str, description: str) -> bool:
    if rule.account_id and rule.account_id != tx.account_id:
        return False
    if rule.flow == "income" and tx.amount <= 0:
        return False
    if rule.flow == "expense" and tx.amount >= 0:
        return False
    pattern = (rule.pattern or "").strip().casefold()
    if not pattern:
        return True
    haystack = {"merchant": merchant, "description": description}.get(rule.match_field, f"{merchant}\n{description}")
    return pattern in haystack


def category_for(tx, rules) -> tuple[str | None, str | None]:
    merchant, description = (tx.merchant or "").casefold(), (tx.description or "").casefold()
    for rule in rules:
        if rule_matches(rule, tx, merchant, description):
            return rule.category, rule.id
    return None, None


def apply_category_rules(db: Session, user_id: str) -> dict:
    """Recompute `rule_category` for every booking; returns first-match counts per rule id."""
    rules = load_category_rules(db, user_id)
    counts: Counter = Counter()
    changed = 0
    for tx in db.scalars(select(Transaction).where(Transaction.user_id == user_id)):
        category, rule_id = category_for(tx, rules)
        if rule_id:
            counts[rule_id] += 1
        if tx.rule_category != category:
            tx.rule_category = category
            changed += 1
    db.flush()
    return {"changed": changed, "matches": dict(counts)}


class RuleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=300)
    pattern: str = Field(default="", max_length=200)
    match_field: MatchField = "any"
    flow: Flow = "any"
    account_id: str | None = None
    position: int = Field(default=0, ge=0, le=1000)


class RulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=300)
    pattern: str | None = Field(default=None, max_length=200)
    match_field: MatchField | None = None
    flow: Flow | None = None
    account_id: str | None = None
    position: int | None = Field(default=None, ge=0, le=1000)


def check_account(db, user, account_id):
    if account_id and db.scalar(select(Account.id).where(Account.id == account_id, Account.user_id == user.id)) is None:
        raise HTTPException(422, "Unknown account")


def owned_rule(db, ident, user) -> CategoryRule:
    rule = db.scalar(select(CategoryRule).where(CategoryRule.id == ident, CategoryRule.user_id == user.id)
                     .execution_options(populate_existing=True))
    if rule is None:
        raise HTTPException(404, "Not found")
    return rule


def has_condition(pattern, flow, account_id) -> bool:
    return bool((pattern or "").strip() or account_id or (flow and flow != "any"))


def rule_json(rule, matches: dict | None = None) -> dict:
    data = serialize(rule)
    data.pop("user_id", None)
    if matches is not None:
        data["matches"] = matches.get(rule.id, 0)
    return data


@router.get("/category-rules")
def list_rules(db: Session = Depends(get_db), user=Depends(current_user)):
    rules = load_category_rules(db, user.id)
    counts: Counter = Counter()
    for tx in db.scalars(select(Transaction).where(Transaction.user_id == user.id)):
        _, rule_id = category_for(tx, rules)
        if rule_id:
            counts[rule_id] += 1
    return [rule_json(r, counts) for r in rules]


def commit_with_reapply(db, user):
    result = apply_category_rules(db, user.id)
    db.commit()
    return result


@router.post("/category-rules", status_code=201)
def create_rule(body: RuleBody, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    check_account(db, user, body.account_id)
    if not has_condition(body.pattern, body.flow, body.account_id):
        raise HTTPException(422, "A rule needs a pattern, an account or a flow")
    rule = CategoryRule(user_id=user.id, **{**body.model_dump(), "pattern": body.pattern.strip(), "category": body.category.strip()})
    db.add(rule)
    db.flush()
    result = commit_with_reapply(db, user)
    return {**rule_json(rule, result["matches"]), "reapplied": result["changed"]}


@router.patch("/category-rules/{ident}")
def patch_rule(ident: str, body: RulePatch, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    rule = owned_rule(db, ident, user)
    changes = body.model_dump(exclude_unset=True)
    if "account_id" in changes:
        check_account(db, user, changes["account_id"])
    for key in ("name", "category", "pattern", "match_field", "flow", "position"):
        if key in changes and changes[key] is None:
            raise HTTPException(422, f"{key} cannot be null")
    pattern = changes["pattern"] if "pattern" in changes else rule.pattern
    flow = changes["flow"] if "flow" in changes else rule.flow
    account_id = changes["account_id"] if "account_id" in changes else rule.account_id
    if not has_condition(pattern, flow, account_id):
        raise HTTPException(422, "A rule needs a pattern, an account or a flow")
    for key, value in changes.items():
        setattr(rule, key, value.strip() if key in {"pattern", "category"} else value)
    db.flush()
    result = commit_with_reapply(db, user)
    return {**rule_json(rule, result["matches"]), "reapplied": result["changed"]}


@router.delete("/category-rules/{ident}")
def delete_rule(ident: str, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    db.delete(owned_rule(db, ident, user))
    db.flush()
    result = commit_with_reapply(db, user)
    return {"ok": True, "reapplied": result["changed"]}
