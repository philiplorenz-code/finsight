"""Data-quality checks on the booking history: months an account has no or unusually few bookings.

Gaps silently distort averages, trends and the wish assessment, so they are reported per account and
month (never with amounts). Only regularly used spending accounts are assessed: an account needs bookings
in at least MIN_ACTIVE_MONTHS months and in at least 80% of the months between its first and last booking, and savings or investment accounts are skipped because empty months
are normal there. Accounts marked inactive or excluded are skipped as well.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .finance import local_today
from .models import Account, Transaction

router = APIRouter(tags=["data-quality"])

ASSESSED_PURPOSES = {"checking", "cash", "credit"}
MIN_ACTIVE_MONTHS = 6
MIN_COVERAGE = Decimal("0.8")  # share of months between first and last booking with any booking
LOW_VOLUME_RATIO = Decimal("0.25")
MIN_TYPICAL_BOOKINGS = 4
ENDED_EARLY_AFTER_MONTHS = 2
WINDOW_MONTHS = 12
MAX_LISTED_MONTHS = 12


def month_no(day: date) -> int:
    return day.year * 12 + day.month - 1


def label(index: int) -> str:
    year, month = divmod(index, 12)
    return f"{year}-{month + 1:02d}"


def median(values: list[int]) -> Decimal:
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        return Decimal(0)
    return Decimal(ordered[n // 2]) if n % 2 else Decimal(ordered[n // 2 - 1] + ordered[n // 2]) / 2


def assess_account(counts: Counter, last_complete: int) -> dict | None:
    """`counts` maps month number -> number of bookings. Returns None when the account is not regularly used."""
    if len(counts) < MIN_ACTIVE_MONTHS:
        return None
    first, last = min(counts), max(counts)
    if Decimal(len(counts)) / (last - first + 1) < MIN_COVERAGE:
        return None  # used only now and then: empty months are normal here
    typical = median(list(counts.values()))
    empty = [m for m in range(first + 1, last) if m not in counts]
    low = []
    if typical >= MIN_TYPICAL_BOOKINGS:
        low = [m for m in range(first + 1, last) if m in counts and Decimal(counts[m]) < typical * LOW_VOLUME_RATIO]
    ended = max(0, last_complete - last) if last < last_complete else 0
    return {"first": label(first), "last": label(last), "empty": empty, "low": low,
            "ended_early_months": ended if ended >= ENDED_EARLY_AFTER_MONTHS else 0}


def data_gaps(db: Session, user_id: str, today: date | None = None) -> dict:
    today = today or local_today(db, user_id)
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.user_id == user_id))
                if a.included and not a.inactive and a.ownership == "owned" and a.purpose in ASSESSED_PURPOSES}
    if not accounts:
        return {"accounts": [], "window_gap_accounts": 0, "affected_accounts": 0}
    rows = db.execute(select(Transaction.account_id, Transaction.booking_date, func.count())
                      .where(Transaction.user_id == user_id, Transaction.account_id.in_(list(accounts)))
                      .group_by(Transaction.account_id, Transaction.booking_date)).all()
    per_account: dict[str, Counter] = defaultdict(Counter)
    latest = None
    for account_id, day, n in rows:
        per_account[account_id][month_no(day)] += n
        latest = max(latest, day) if latest else day
    if latest is None:
        return {"accounts": [], "window_gap_accounts": 0, "affected_accounts": 0}
    # The newest month may be unfinished; the last complete month is the one before it unless the data ends on a month end.
    ends_on_month_end = (date.fromordinal(latest.toordinal() + 1)).day == 1
    last_complete = month_no(latest) if ends_on_month_end else month_no(latest) - 1
    window_start = last_complete - WINDOW_MONTHS + 1
    out = []
    window_accounts = 0
    for account_id, counts in per_account.items():
        result = assess_account(counts, last_complete)
        if result is None:
            continue
        ended_months = list(range(max(counts) + 1, last_complete + 1)) if result["ended_early_months"] else []
        flagged = sorted(set(result["empty"]) | set(result["low"]) | set(ended_months))
        if not flagged:
            continue
        in_window = any(m >= window_start for m in flagged)
        window_accounts += in_window
        out.append({"id": account_id, "name": accounts[account_id].name, "first_month": result["first"], "last_month": result["last"],
                    "empty_months": [label(m) for m in result["empty"]][-MAX_LISTED_MONTHS:],
                    "low_months": [label(m) for m in result["low"]][-MAX_LISTED_MONTHS:],
                    "ended_early_months": result["ended_early_months"], "in_window": in_window})
    out.sort(key=lambda a: (not a["in_window"], a["name"].casefold()))
    return {"accounts": out, "window_gap_accounts": window_accounts, "affected_accounts": len(out),
            "last_complete_month": label(last_complete), "window_start_month": label(window_start)}


@router.get("/data-quality")
def get_data_quality(db: Session = Depends(get_db), user=Depends(current_user)):
    return data_gaps(db, user.id)
