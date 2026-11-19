"""Detect transfers between the user's own accounts that the export did not flag.

Money moved from account A to account B shows up as an outflow and an inflow of the same amount
within a few days. When both accounts are owned, the pair is a transfer, not income or spending.
Matching is one-to-one (nearest booking date first) so repeated identical amounts pair up correctly.
Bookings the user already classified as employment/business income by an income rule are never paired.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .income import load_rules, match_rule
from .locking import lock_owner
from .models import Account, Transaction, TransferRejection

router = APIRouter(tags=["transfers"])

WINDOW_DAYS = 3
MIN_AMOUNT = Decimal("0.01")


def pair_key(a: Transaction, b: Transaction) -> str:
    return "|".join(sorted((a.id, b.id)))


def rejected_keys(db: Session, user_id: str) -> set[str]:
    return set(db.scalars(select(TransferRejection.key).where(TransferRejection.user_id == user_id)))


def find_pairs(db: Session, user_id: str) -> list[tuple[Transaction, Transaction]]:
    rejected = rejected_keys(db, user_id)
    owned = {a.id for a in db.scalars(select(Account).where(Account.user_id == user_id)) if a.ownership == "owned"}
    rules = load_rules(db, user_id)
    rows = [tx for tx in db.scalars(select(Transaction).where(Transaction.user_id == user_id))
            if tx.account_id in owned and abs(tx.amount) >= MIN_AMOUNT
            and tx.split_role not in {"parent", "excluded"}]
    outflows = defaultdict(list)
    for tx in rows:
        if tx.amount < 0:
            outflows[(tx.currency, -tx.amount)].append(tx)
    used: set[str] = set()
    pairs = []
    for tx in sorted((t for t in rows if t.amount > 0), key=lambda t: (t.booking_date, t.id)):
        rule = match_rule(tx, rules)
        if rule and rule.source in {"employment", "business"}:
            continue
        options = [o for o in outflows[(tx.currency, tx.amount)]
                   if o.id not in used and o.account_id != tx.account_id
                   and abs((o.booking_date - tx.booking_date).days) <= WINDOW_DAYS
                   and pair_key(tx, o) not in rejected]
        if not options:
            continue
        best = min(options, key=lambda o: (abs((o.booking_date - tx.booking_date).days), not o.is_transfer, o.id))
        used.add(best.id)
        pairs.append((tx, best))
    return pairs


def detect_transfers(db: Session, user_id: str, apply: bool = True) -> dict:
    """Mark matched pairs as transfers. Previously auto-detected marks are recomputed from scratch."""
    if apply:
        for tx in db.scalars(select(Transaction).where(Transaction.user_id == user_id, Transaction.transfer_auto.is_(True))):
            tx.transfer_auto = False
            tx.is_transfer = False
            tx.transfer_uncertain = False
        db.flush()
    pairs = find_pairs(db, user_id)
    newly = 0
    amount = Decimal(0)
    for inflow, outflow in pairs:
        for tx in (inflow, outflow):
            if not tx.is_transfer:
                newly += 1
                if tx.amount > 0:
                    amount += tx.amount
                if apply:
                    tx.is_transfer = True
                    tx.transfer_auto = True
            if apply:
                tx.transfer_uncertain = False
    if apply:
        db.flush()
    return {"pairs": len(pairs), "newly_marked": newly, "newly_marked_inflow_total": amount, "applied": apply}


@router.post("/transfers/detect")
def detect(dry_run: bool = False, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    result = detect_transfers(db, user.id, apply=not dry_run)
    if not dry_run:
        db.commit()
    return result


REVIEW_LIMIT = 300


def describe(tx: Transaction, names: dict[str, str]) -> dict:
    return {"id": tx.id, "account": names.get(tx.account_id, "?"), "merchant": (tx.merchant or "")[:80],
            "date": tx.booking_date.isoformat(), "flagged_by_source": bool(tx.is_transfer and not tx.transfer_auto)}


@router.get("/transfers/review")
def review(db: Session = Depends(get_db), user=Depends(current_user)):
    """Pairs that were marked as transfers by this app's matching (not by the export), newest first."""
    names = {a.id: a.name for a in db.scalars(select(Account).where(Account.user_id == user.id))}
    pairs = [(i, o) for i, o in find_pairs(db, user.id) if i.transfer_auto or o.transfer_auto]
    pairs.sort(key=lambda p: (p[0].booking_date, p[0].id), reverse=True)
    rejections = list(db.scalars(select(TransferRejection).where(TransferRejection.user_id == user.id)
                                 .order_by(TransferRejection.booking_date.desc())))
    return {"total": len(pairs), "limit": REVIEW_LIMIT,
            "pairs": [{"key": pair_key(i, o), "amount": i.amount, "currency": i.currency,
                       "inflow": describe(i, names), "outflow": describe(o, names)} for i, o in pairs[:REVIEW_LIMIT]],
            "rejections": [{"id": r.id, "key": r.key, "amount": r.amount, "currency": r.currency,
                            "booking_date": r.booking_date.isoformat(), "label": r.label} for r in rejections]}


class RejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=3, max_length=80)


@router.post("/transfers/reject")
def reject(body: RejectBody, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    names = {a.id: a.name for a in db.scalars(select(Account).where(Account.user_id == user.id))}
    match = next(((i, o) for i, o in find_pairs(db, user.id) if pair_key(i, o) == body.key and (i.transfer_auto or o.transfer_auto)), None)
    if match is None:
        raise HTTPException(404, "No such detected transfer pair")
    inflow, outflow = match
    db.add(TransferRejection(user_id=user.id, key=body.key, amount=inflow.amount, currency=inflow.currency,
                             booking_date=inflow.booking_date, label=f"{names.get(outflow.account_id, '?')} → {names.get(inflow.account_id, '?')}"[:300]))
    db.flush()
    result = detect_transfers(db, user.id, apply=True)
    db.commit()
    return {**result, "rejected": body.key}


@router.delete("/transfers/rejections/{ident}")
def restore(ident: str, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    row = db.scalar(select(TransferRejection).where(TransferRejection.id == ident, TransferRejection.user_id == user.id))
    if row is None:
        raise HTTPException(404, "Not found")
    db.delete(row)
    db.flush()
    result = detect_transfers(db, user.id, apply=True)
    db.commit()
    return {**result, "restored": True}
