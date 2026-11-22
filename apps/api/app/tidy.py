"""Tidy up: bookings without a useful category, grouped by merchant, with a suggested category.

Suggestion order: the category this merchant already has on other bookings (by count), then keyword hints.
Applying a suggestion creates an ordinary category rule (merchant contains name), so it also covers future
imports and can be edited under category rules. Read-only apart from that.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .finance import eligible, local_today, serialize
from .models import Account, Transaction

router = APIRouter(tags=["tidy"])
VAGUE = {"", "sonstige ausgaben", "sonstiges", "uncategorized", "sonstige einnahmen", "unkategorisiert", "other"}
HINTS = (
    (("rewe", "edeka", "aldi", "lidl", "penny", "netto", "kaufland", "marktkauf", "wasgau", "globus", "tegut"), "Lebensmittel"),
    (("aral", "esso", "shell", "jet ", "total", "tankstelle", "agip", "omv"), "Tanken"),
    (("dm ", "dm-", "rossmann", "müller", "mueller"), "Drogerie"),
    (("amazon", "otto", "zalando", "ebay", "about you"), "Shopping"),
    (("restaurant", "pizza", "burger", "mcdonald", "lieferando", "wolt", "uber eats", "café", "cafe", "bar "), "Restaurants"),
    (("uber", "bolt", "taxi", "free now"), "Taxi"),
    (("db ", "deutsche bahn", "bahn", "flixbus", "vrn", "kvv"), "Öffentliche Verkehrsmittel"),
    (("netflix", "spotify", "disney", "apple.com", "google", "youtube", "patreon"), "Abos"),
    (("apotheke", "arzt", "praxis", "zahnarzt"), "Gesundheit"),
    (("ikea", "xxxl", "höffner", "poco", "bauhaus", "obi", "hornbach", "toom"), "Einrichtung"),
    (("geldautomat", "atm", "barzahlen", "bargeld"), "Bargeld"),
    (("paypal",), "PayPal (prüfen)"),
)


def hint_for(merchant: str, description: str) -> str | None:
    text = f" {merchant} {description} ".casefold()
    for words, category in HINTS:
        if any(w in text for w in words):
            return category
    return None


def is_vague(category: str | None) -> bool:
    return (category or "").strip().casefold() in VAGUE


def inbox(db: Session, user_id: str, months: int = 12, limit: int = 60) -> dict:
    today = local_today(db, user_id)
    since = today - timedelta(days=31 * months)
    accounts = {a.id for a in db.scalars(select(Account).where(Account.user_id == user_id)) if a.included and a.ownership != "external" and a.purpose != "mirror"}
    known: dict[str, Counter] = defaultdict(Counter)
    groups: dict[str, dict] = {}
    for tx in db.scalars(select(Transaction).where(Transaction.user_id == user_id, Transaction.booking_date >= since)):
        if tx.account_id not in accounts or not eligible(tx) or tx.amount >= 0:
            continue
        merchant = (tx.merchant or "").strip()
        if not merchant:
            continue
        key = merchant.casefold()
        if is_vague(tx.effective_category):
            g = groups.setdefault(key, {"merchant": merchant, "count": 0, "total": Decimal(0), "last": tx.booking_date, "sample": (tx.description or "")[:80]})
            g["count"] += 1
            g["total"] += -tx.amount
            g["last"] = max(g["last"], tx.booking_date)
        else:
            known[key][tx.effective_category.strip()] += 1
    rows = []
    for key, g in groups.items():
        suggestion, source = None, None
        if known.get(key):
            suggestion, source = known[key].most_common(1)[0][0], "same_merchant"
        else:
            hint = hint_for(g["merchant"], g["sample"])
            if hint:
                suggestion, source = hint, "keyword"
        rows.append({**g, "suggestion": suggestion, "suggestion_source": source})
    rows.sort(key=lambda r: -r["total"])
    total = sum((r["total"] for r in rows), Decimal(0))
    return {"months": months, "groups": rows[:limit], "group_count": len(rows), "total": total,
            "monthly": total / months if months else total}


@router.get("/tidy/inbox")
def get_inbox(months: int = Query(12, ge=1, le=36), db: Session = Depends(get_db), user=Depends(current_user)):
    return serialize(inbox(db, user.id, months))
