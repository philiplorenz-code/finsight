"""Plan vs. actual (SOLL/IST): monthly targets the owner maintains, compared with real spending.

An item's actual (IST) is the net outflow of non-transfer bookings that either leave the item's pot account
or carry the item's category on any other included, owned account (e.g. fuel paid with the main card instead
of the fuel pot). Each booking counts once per item, weighted by the owner share that applied on its booking day. Refunds reduce it.
Status: "over" when the actual exceeds the target; for the running month also "warning" when the linear
projection to month end exceeds it or 90 % is used. No booking data is changed here.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .finance import eligible, local_today
from .models import Account, AccountChange, PlanItem, Transaction
from .wishlist import add_months, month_start

router = APIRouter(tags=["plan"])

ZERO = Decimal(0)
HUNDRED = Decimal(100)
MAX_ITEMS = 60
MAX_HISTORY = 12
WARN_SHARE = Decimal("0.9")


class PlanItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(ge=0, le=Decimal("1000000"))
    category: str | None = Field(default=None, max_length=100)
    account_id: str | None = Field(default=None, max_length=36)
    position: int = Field(default=0, ge=0, le=10000)


class PlanItemPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    amount: Decimal | None = Field(default=None, ge=0, le=Decimal("1000000"))
    category: str | None = Field(default=None, max_length=100)
    account_id: str | None = Field(default=None, max_length=36)
    position: int | None = Field(default=None, ge=0, le=10000)


def month_end(start: date) -> date:
    return add_months(start, 1) - timedelta(days=1)


def classify(actual: Decimal, target: Decimal, projected: Decimal | None) -> str:
    if actual > target:
        return "over"
    if target > 0 and (actual >= target * WARN_SHARE or (projected is not None and projected > target)):
        return "warning"
    return "ok"


def actuals(db: Session, user_id: str, items: list[PlanItem], first: date, last: date) -> dict[tuple[str, date], dict]:
    """Per (item, month start): total, part from the pot and part from the category elsewhere."""
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.user_id == user_id))}
    counted = {a.id for a in accounts.values() if a.included and a.ownership == "owned" and a.purpose != "mirror"}
    history = defaultdict(list)
    if counted:
        for change in db.scalars(select(AccountChange).where(AccountChange.account_id.in_(counted))):
            history[change.account_id].append(change)
    shares: dict[tuple[str, date], Decimal] = {}

    def share_on(account, day):
        # The owner share that applied on the booking day (e.g. 50 % while a flat was shared).
        if not history.get(account.id):
            return account.owner_share
        key = (account.id, day)
        if key not in shares:
            from .asof import settings_on
            shares[key] = Decimal(str(settings_on(account, history[account.id], day)[0]["owner_share"]))
        return shares[key]
    by_category = defaultdict(list)
    by_pot = defaultdict(list)
    for item in items:
        if item.account_id:
            by_pot[item.account_id].append(item)
        if item.category:
            by_category[item.category.strip().casefold()].append(item)
    out: dict[tuple[str, date], dict] = defaultdict(lambda: {"actual": ZERO, "from_pot": ZERO, "elsewhere": ZERO, "count": 0})
    rows = db.scalars(select(Transaction).where(Transaction.user_id == user_id, Transaction.booking_date >= first,
                                                Transaction.booking_date <= last))
    from .cashbook import entries as cash_entries, is_withdrawal, since as cash_book_since
    cash_since = cash_book_since(db, user_id)
    for entry in cash_entries(db, user_id, first, last):
        for item in by_category.get(entry.category.strip().casefold(), []):
            bucket = out[(item.id, month_start(entry.day))]
            bucket["actual"] += entry.amount
            bucket["elsewhere"] += entry.amount
            bucket["count"] += 1
    for tx in rows:
        if tx.account_id not in counted or not eligible(tx) or is_withdrawal(tx, cash_since):
            continue
        account = accounts[tx.account_id]
        value = -tx.amount * share_on(account, tx.booking_date) / HUNDRED
        key_month = month_start(tx.booking_date)
        matched: dict[str, str] = {}
        for item in by_pot.get(tx.account_id, []):
            matched[item.id] = "from_pot"
        for item in by_category.get((tx.effective_category or "").strip().casefold(), []):
            matched.setdefault(item.id, "elsewhere")
        for item_id, part in matched.items():
            bucket = out[(item_id, key_month)]
            bucket["actual"] += value
            bucket[part] += value
            bucket["count"] += 1
    return out


def plan_report(db: Session, user_id: str, month: date | None = None, history: int = 6) -> dict:
    today = local_today(db, user_id)
    current = month_start(today)
    month = month or current
    history = max(1, min(history, MAX_HISTORY))
    items = list(db.scalars(select(PlanItem).where(PlanItem.user_id == user_id).order_by(PlanItem.position, PlanItem.created_at)))
    months = [add_months(month, -i) for i in range(history - 1, -1, -1)]
    data = actuals(db, user_id, items, months[0], month_end(month)) if items else {}
    names = {a.id: a.name for a in db.scalars(select(Account).where(Account.user_id == user_id))}
    days = calendar.monthrange(month.year, month.month)[1]
    elapsed = (min(today, month_end(month)) - month).days + 1 if month <= today else 0
    running = month == current
    rows, total_target, total_actual = [], ZERO, ZERO
    for item in items:
        target = Decimal(item.amount)
        now = data.get((item.id, month), {"actual": ZERO, "from_pot": ZERO, "elsewhere": ZERO, "count": 0})
        actual = max(now["actual"], ZERO)
        projected = (actual / elapsed * days) if running and elapsed > 0 else None
        trail = []
        for m in months:
            past = data.get((item.id, m), {"actual": ZERO})
            value = max(past["actual"], ZERO)
            trail.append({"month": m.isoformat()[:7], "actual": value, "status": classify(value, target, None) if m < current else None})
        rows.append({"id": item.id, "name": item.name, "category": item.category, "account_id": item.account_id,
                     "account_name": names.get(item.account_id), "amount": target, "actual": actual,
                     "from_pot": max(now["from_pot"], ZERO), "elsewhere": now["elsewhere"], "bookings": now["count"],
                     "remaining": target - actual, "projected": projected,
                     "status": classify(actual, target, projected), "history": trail})
        total_target += target
        total_actual += actual
    return {"month": month.isoformat()[:7], "running": running, "days_elapsed": elapsed, "days_in_month": days,
            "items": rows, "totals": {"amount": total_target, "actual": total_actual, "remaining": total_target - total_actual},
            "over": [r["id"] for r in rows if r["status"] == "over"]}


def known_categories(db: Session, user_id: str) -> list[str]:
    seen = set()
    for value in db.scalars(select(Transaction.category).where(Transaction.user_id == user_id).distinct()):
        if value:
            seen.add(value.strip())
    for value in db.scalars(select(Transaction.category_override).where(Transaction.user_id == user_id).distinct()):
        if value:
            seen.add(value.strip())
    return sorted(seen, key=str.casefold)


def check_account(db: Session, user_id: str, account_id: str | None) -> None:
    if account_id and not db.scalar(select(Account.id).where(Account.id == account_id, Account.user_id == user_id)):
        raise HTTPException(404, "Account not found")


def parse_month(value: str | None) -> date | None:
    if not value:
        return None
    try:
        year, mon = value.split("-")
        return date(int(year), int(mon), 1)
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid month") from None


@router.get("/plan")
def get_plan(month: str | None = None, history: int = 6, db: Session = Depends(get_db), user=Depends(current_user)):
    report = plan_report(db, user.id, parse_month(month), history)
    report["categories"] = known_categories(db, user.id)
    return report


@router.post("/plan-items", status_code=201)
def create_item(body: PlanItemIn, db: Session = Depends(get_db), user=Depends(current_user)):
    if not body.category and not body.account_id:
        raise HTTPException(422, "Choose a category, a pot account or both")
    if db.query(PlanItem).filter(PlanItem.user_id == user.id).count() >= MAX_ITEMS:
        raise HTTPException(409, "Too many plan items")
    check_account(db, user.id, body.account_id)
    item = PlanItem(user_id=user.id, name=body.name.strip(), amount=body.amount,
                    category=(body.category or "").strip() or None, account_id=body.account_id, position=body.position)
    db.add(item)
    db.commit()
    return {"id": item.id}


@router.patch("/plan-items/{item_id}")
def update_item(item_id: str, body: PlanItemPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    item = db.scalar(select(PlanItem).where(PlanItem.id == item_id, PlanItem.user_id == user.id))
    if not item:
        raise HTTPException(404, "Plan item not found")
    changes = body.model_dump(exclude_unset=True)
    if "account_id" in changes:
        check_account(db, user.id, changes["account_id"])
    for key in ("category", "name"):
        if isinstance(changes.get(key), str):
            changes[key] = changes[key].strip() or None
    merged = {"category": item.category, "account_id": item.account_id, "name": item.name, **changes}
    if not merged["category"] and not merged["account_id"]:
        raise HTTPException(422, "Choose a category, a pot account or both")
    if not merged["name"] or ("amount" in changes and changes["amount"] is None):
        raise HTTPException(422, "Name and amount required")
    for key, value in changes.items():
        setattr(item, key, value)
    db.commit()
    return {"id": item.id}


@router.delete("/plan-items/{item_id}", status_code=204)
def delete_item(item_id: str, db: Session = Depends(get_db), user=Depends(current_user)):
    item = db.scalar(select(PlanItem).where(PlanItem.id == item_id, PlanItem.user_id == user.id))
    if not item:
        raise HTTPException(404, "Plan item not found")
    db.delete(item)
    db.commit()


def standing_orders(db: Session, user_id: str, today: date | None = None) -> list[dict]:
    """Regular transfers into own accounts: same target and amount in at least two of the last three months."""
    today = today or local_today(db, user_id)
    start = add_months(month_start(today), -2)
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.user_id == user_id)) if a.ownership == "owned"}
    groups: dict[tuple[str, Decimal], list[date]] = defaultdict(list)
    for tx in db.scalars(select(Transaction).where(Transaction.user_id == user_id, Transaction.booking_date >= start,
                                                    Transaction.booking_date <= today, Transaction.is_transfer.is_(True))):
        if tx.amount >= 5 and tx.account_id in accounts:
            groups[(tx.account_id, Decimal(tx.amount))].append(tx.booking_date)
    out = []
    for (account_id, amount), days in groups.items():
        months = sorted({month_start(d) for d in days})
        if len(months) < 2 or len(days) > len(months) + 1:
            continue  # not monthly, or several identical transfers a month (likely manual)
        typical = sorted(d.day for d in days)[len(days) // 2]
        out.append({"account_id": account_id, "account": accounts[account_id].name, "amount": amount,
                    "day": typical, "months": [m.isoformat()[:7] for m in months], "last": max(days).isoformat(),
                    "active": max(months) >= add_months(month_start(today), -1)})
    return sorted(out, key=lambda o: (not o["active"], -o["amount"]))


@router.get("/standing-orders")
def get_standing_orders(db: Session = Depends(get_db), user=Depends(current_user)):
    from .finance import contracts
    orders = standing_orders(db, user.id)
    debits = [{"name": i["name"], "kind": i["kind"], "period": i["period"], "monthly": i["monthly_cost"], "annual": i["annual_cost"],
               "next_charge": i["next_charge"], "last_charge": i["last_charge"], "currency": i["currency"]}
              for i in contracts(db, user.id)["items"] if i["status"] == "active"]
    return {"transfers": orders, "transfers_monthly": sum((o["amount"] for o in orders if o["active"]), ZERO), "debits": debits}


def queue_plan_alerts(session: Session, owner_id: str, now=None) -> list[str]:
    """Generic notification for each item over target this month; deduplicated per item and month."""
    from .notifications import NotificationSettings, queue_notification
    settings = session.get(NotificationSettings, str(owner_id))
    if not settings or not settings.enabled or "plan_exceeded" not in (settings.events or []):
        return []
    report = plan_report(session, str(owner_id), history=1)
    queued = []
    for item_id in report["over"]:
        row = queue_notification(session, str(owner_id), "plan_exceeded", f"plan:{item_id}:{report['month']}", now)
        queued.append(row.id)
    for item in early_warnings(report):
        row = queue_notification(session, str(owner_id), "plan_exceeded", f"plan-warn:{item['id']}:{report['month']}", now)
        queued.append(row.id)
    return queued


def early_warnings(report: dict) -> list[dict]:
    """Items close to their target in the running month: 90 % spent, or projected above target after a week."""
    if not report["running"]:
        return []
    out = []
    for item in report["items"]:
        if item["status"] != "warning":
            continue
        near = item["amount"] > 0 and item["actual"] >= item["amount"] * WARN_SHARE
        if near or report["days_elapsed"] >= 7:
            out.append(item)
    return out
