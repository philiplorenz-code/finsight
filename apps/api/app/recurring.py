"""Recurring payment detection: insurances, housing, loans, subscriptions, utilities and other fixed costs.

Evidence, not magic: a payee counts as a recurring contract when its bookings repeat at a monthly,
quarterly, half-yearly or yearly rhythm (a single missing booking is tolerated) with a stable amount.
The class (insurance, housing, ...) comes from the source category and keywords in the payee text; both are
hints, never the only evidence. The user's confirm/dismiss/rename/reclassify decisions are stored by a
normalized payee key and therefore survive re-imports.
"""
from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal
from statistics import median
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .locking import lock_owner
from .models import ContractDecision

router = APIRouter(tags=["contracts"])

# name, typical days, min gap, max gap, minimum bookings, tolerated multiples of the gap (missing booking)
PERIODS = [("monthly", 30, 24, 36, 4, (1, 2)), ("quarterly", 91, 80, 102, 3, (1, 2)),
           ("half_yearly", 182, 165, 200, 3, (1, 2)), ("yearly", 365, 340, 390, 2, (1,))]
MIN_FIT = 0.75
AMOUNT_TOLERANCE = Decimal("0.20")
MIN_STABLE_AMOUNTS = 0.7
STOPPED_AFTER = Decimal("1.6")  # periods without a booking before a contract counts as stopped

KINDS = ("insurance", "housing", "loan", "subscription", "utility", "other")
Kind = Literal["insurance", "housing", "loan", "subscription", "utility", "other"]
KEYWORDS = {
    "loan": ("kredit", "darlehen", "tilgung", "finanzierung", "leasing"),
    "insurance": ("versicher", "haftpflicht", "hausrat", "rechtsschutz", "unfall", "berufsunf", "allianz", "huk", "ergo ",
                  "axa", "signal iduna", "barmenia", "debeka", "zurich", "generali", "devk", "cosmos", "tk ", "aok", "barmer"),
    "housing": ("miete", "hausgeld", "vermieter", "wohnung", "nebenkosten"),
    "utility": ("strom", "gas ", "wasser", "stadtwerke", "vattenfall", "e.on", "enbw", "telekom", "vodafone", "o2", "1&1",
                "congstar", "internet", "mobilfunk", "rundfunk", "beitragsservice", "müll"),
    "subscription": ("netflix", "spotify", "disney", "prime", "apple", "icloud", "youtube", "dazn", "paramount", "audible",
                     "adobe", "microsoft", "google", "dropbox", "openai", "anthropic", "patreon", "abo", "zeitung",
                     "magazin", "fitness", "fitx", "mcfit", "gym", "sky ", "wow"),
}
KIND_ORDER = ("loan", "insurance", "housing", "utility", "subscription")


def normalize_key(name: str) -> str:
    text = re.sub(r"[0-9]+", "", (name or "").casefold())
    return " ".join(re.sub(r"[^a-zäöüß&. ]+", " ", text).split())[:200]


def classify(name: str, category: str | None) -> str:
    text = f"{name} {category or ''}".casefold() + " "
    for kind in KIND_ORDER:
        if any(word in text for word in KEYWORDS[kind]):
            return kind
    return "other"


def infer_period(dates: list, amounts: list[Decimal]):
    """Return (period, typical_days) for a payee's bookings or None."""
    if len(dates) < 2:
        return None
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    mid = Decimal(str(median(amounts)))
    if mid <= 0:
        return None
    stable = sum(1 for a in amounts if abs(a - mid) <= mid * AMOUNT_TOLERANCE) / len(amounts)
    if stable < MIN_STABLE_AMOUNTS:
        return None
    for name, typical, low, high, minimum, multiples in PERIODS:
        if len(dates) < minimum:
            continue
        fits = sum(1 for gap in gaps if any(low <= gap / k <= high for k in multiples))
        single = sum(1 for gap in gaps if low <= gap <= high)
        if fits / len(gaps) >= MIN_FIT and single >= 1:
            return name, typical
    return None


def status_of(last_date, typical_days: int, today) -> str:
    return "stopped" if (today - last_date).days > float(STOPPED_AFTER) * typical_days else "active"


def load_decisions(db: Session, user_id: str) -> dict[str, ContractDecision]:
    return {d.key: d for d in db.scalars(select(ContractDecision).where(ContractDecision.user_id == user_id))}


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=300)
    decision: Literal["confirm", "dismiss", "reset"]
    name: str | None = Field(default=None, min_length=1, max_length=300)
    kind: Kind | None = None


@router.put("/contracts/decision")
def decide(body: DecisionBody, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    existing = db.scalar(select(ContractDecision).where(ContractDecision.user_id == user.id, ContractDecision.key == body.key))
    if body.decision == "reset":
        if existing:
            db.delete(existing)
            db.commit()
        return {"key": body.key, "decision": None}
    if existing is None:
        existing = ContractDecision(user_id=user.id, key=body.key)
        db.add(existing)
    existing.decision = "confirmed" if body.decision == "confirm" else "dismissed"
    if "name" in body.model_fields_set:
        existing.name = body.name
    if "kind" in body.model_fields_set:
        existing.kind = body.kind
    db.commit()
    return {"key": body.key, "decision": existing.decision, "name": existing.name, "kind": existing.kind}
