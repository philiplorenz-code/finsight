"""Detect transfers between the user's own accounts that the export did not flag.

Money moved from account A to account B shows up as an outflow and an inflow of the same amount
within a few days. When both accounts are owned, the pair is a transfer, not income or spending.
Matching is one-to-one (nearest booking date first) so repeated identical amounts pair up correctly.
Bookings the user already classified as employment/business income by an income rule are never paired.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .income import load_rules, match_rule
from .locking import lock_owner
from .models import Account, Transaction

router = APIRouter(tags=["transfers"])

WINDOW_DAYS = 3
MIN_AMOUNT = Decimal("0.01")


def find_pairs(db: Session, user_id: str) -> list[tuple[Transaction, Transaction]]:
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
                   and abs((o.booking_date - tx.booking_date).days) <= WINDOW_DAYS]
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
