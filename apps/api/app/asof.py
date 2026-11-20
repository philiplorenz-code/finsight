"""As-of reconstruction: balances, account settings and earmarks as they were on a past day.

Rules (never apply the future, never pretend completeness):
- a balance is the latest observation on or before the day; none -> `no_opening_balance`, the account is left out;
- several different amounts observed on the same day -> `ambiguous_same_day` (the latest import's value is used);
- account settings come from the change history; accounts changed before history existed show their earliest known state;
- earmarks come from the append-only allocation history; releases are respected.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .finance import ZERO, latest_balance, serialize
from .models import Account, AccountChange, AllocationEvent, Balance

router = APIRouter(tags=["as-of"])
TRACKED = ("included", "ownership", "purpose", "owner_share")


def snapshot(account: Account) -> dict:
    return {"included": account.included, "ownership": account.ownership, "purpose": account.purpose, "owner_share": str(account.owner_share)}


def record_account_change(db: Session, account: Account, before: dict) -> None:
    after = snapshot(account)
    if after != before:
        db.add(AccountChange(account_id=account.id, before=before, after=after))


def end_of_day(day: date) -> datetime:
    return datetime.combine(day, time.max, tzinfo=timezone.utc)


def settings_on(account: Account, changes: list[AccountChange], day: date) -> tuple[dict, bool]:
    """Returns the settings that applied on `day` and whether they come from history (True) or are the current ones."""
    if not changes:
        return snapshot(account), False
    limit = end_of_day(day)
    ordered = sorted(changes, key=lambda c: c.changed_at if c.changed_at.tzinfo else c.changed_at.replace(tzinfo=timezone.utc))
    applied = None
    for change in ordered:
        stamp = change.changed_at if change.changed_at.tzinfo else change.changed_at.replace(tzinfo=timezone.utc)
        if stamp <= limit:
            applied = change
    if applied:
        return applied.after, True
    state = dict(ordered[0].before)
    if state.get("ownership") == "unknown":
        # "Unknown" means not yet decided, not a fact about the past: the first decision applies retroactively.
        state["ownership"] = ordered[0].after.get("ownership", "unknown")
    return state, True


def as_of(db: Session, user_id: str, day: date, currency: str = "EUR") -> dict:
    accounts = [a for a in db.scalars(select(Account).where(Account.user_id == user_id, Account.currency == currency))]
    changes: dict[str, list[AccountChange]] = {}
    for change in db.scalars(select(AccountChange).where(AccountChange.account_id.in_([a.id for a in accounts]) if accounts else False)):
        changes.setdefault(change.account_id, []).append(change)
    rows, warnings = [], []
    total_mine = ZERO
    for account in accounts:
        state, versioned = settings_on(account, changes.get(account.id, []), day)
        if not state["included"] or state["ownership"] != "owned":
            continue
        obs = latest_balance(db, account.id, day)
        if obs is None:
            rows.append({"id": account.id, "name": account.name, "flags": ["no_opening_balance"], "purpose": state["purpose"]})
            continue
        same_day = {b.amount for b in db.scalars(select(Balance).where(Balance.account_id == account.id, Balance.observed_date == obs.observed_date))}
        flags = []
        if len(same_day) > 1:
            flags.append("ambiguous_same_day")
        if (day - obs.observed_date).days > 45:
            flags.append("observation_old")
        if account.inactive:
            flags.append("closed_or_inactive")
        if not versioned:
            flags.append("settings_not_versioned")
        share = Decimal(str(state["owner_share"]))
        mine = obs.amount * share / 100
        total_mine += mine
        rows.append({"id": account.id, "name": account.name, "purpose": state["purpose"], "balance": obs.amount,
                     "observed_date": obs.observed_date, "share": share, "mine": mine, "flags": flags})
    events = list(db.scalars(select(AllocationEvent).where(AllocationEvent.user_id == user_id, AllocationEvent.recorded_at <= end_of_day(day))
                             .order_by(AllocationEvent.recorded_at)))
    newest: dict[str, str | None] = {}
    for event in events:  # the batch of the newest event wins per bucket
        newest[event.bucket_id] = event.batch_id or event.id
    batches: dict[str, dict] = {}
    for event in events:
        if (event.batch_id or event.id) != newest[event.bucket_id]:
            continue
        entry = batches.setdefault(event.bucket_id, {"bucket": event.bucket_name, "amount": ZERO})
        if event.account_id:
            entry["amount"] += event.amount
    earmarks = [v for v in batches.values() if v["amount"] > 0]
    if any(r["flags"] and "no_opening_balance" in r["flags"] for r in rows):
        warnings.append("Some accounts have no balance observation on or before this day and are not counted")
    warnings.append("Planned obligations and bucket targets are current values, not versioned")
    return serialize({"date": day, "currency": currency, "accounts": rows, "total_mine": total_mine, "earmarked": earmarks, "warnings": warnings})


@router.get("/as-of")
def get_as_of(date_: date = Query(alias="date"), currency: str = Query("EUR", pattern="^[A-Z]{3}$"),
              db: Session = Depends(get_db), user=Depends(current_user)):
    if date_ > date.today():
        raise HTTPException(422, "The date must not be in the future")
    return as_of(db, user.id, date_, currency)
