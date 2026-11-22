"""Global search across bookings, merchants, contracts and accounts (case-insensitive substring)."""
from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .finance import contracts, serialize
from .models import Account, Transaction

router = APIRouter(tags=["search"])


@router.get("/search")
def search(q: str = Query(..., min_length=2, max_length=100), db: Session = Depends(get_db), user=Depends(current_user)):
    needle = q.strip().casefold()
    like = f"%{needle}%"
    accounts = list(db.scalars(select(Account).where(Account.user_id == user.id)))
    names = {a.id: a.name for a in accounts}
    txs = list(db.scalars(select(Transaction).where(Transaction.user_id == user.id, or_(func.lower(Transaction.merchant).like(like),
                                                   func.lower(Transaction.description).like(like))).order_by(Transaction.booking_date.desc()).limit(200)))
    merchants = Counter((tx.merchant or "").strip() for tx in txs if needle in (tx.merchant or "").casefold())
    compact = needle.replace(" ", "")
    return serialize({
        "transactions": [{"id": tx.id, "date": tx.booking_date, "merchant": tx.merchant, "amount": tx.amount, "category": tx.effective_category,
                          "account": names.get(tx.account_id)} for tx in txs[:8]],
        "merchants": [{"name": m, "count": n} for m, n in merchants.most_common(6) if m],
        "contracts": [{"name": c["name"], "monthly": c["monthly_cost"], "kind": c["kind"], "status": c["status"]}
                      for c in contracts(db, user.id)["items"] if needle in c["name"].casefold()][:6],
        "accounts": [{"id": a.id, "name": a.name, "provider": a.provider} for a in accounts
                     if needle in a.name.casefold() or needle in (a.provider or "").casefold() or (len(compact) >= 4 and compact in (a.iban or "").casefold())][:6],
    })
