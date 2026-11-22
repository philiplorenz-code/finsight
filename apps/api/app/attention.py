"""What needs attention now: one list from deadlines, open items and plan items, plus reminder notifications.

Reminders are generic notifications (the message never contains financial details), deduplicated per item and
threshold, so each deadline reminds at most once at 14, 7 and 2 days and each open item once when it falls due.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .finance import local_today, serialize

router = APIRouter(tags=["attention"])
THRESHOLDS = (14, 7, 2)
_LAST_CHECK: dict[str, float] = {}  # worker polls every 30 s; reminders are checked at most hourly


def attention(db: Session, user_id: str, today: date | None = None) -> list[dict]:
    today = today or local_today(db, user_id)
    out: list[dict] = []
    from .contract_terms import deadlines
    for d in deadlines(db, user_id, today):
        if d.get("cancel_by") and not d.get("expired") and 0 <= d.get("days_left", 999) <= 30:
            out.append({"kind": "deadline", "severity": "high" if d["days_left"] <= 7 else "medium", "title": d["name"],
                        "date": d["cancel_by"], "days_left": d["days_left"], "link": "/contracts"})
    from .receivables import OpenItem, suggestion
    for item in db.scalars(select(OpenItem).where(OpenItem.user_id == user_id, OpenItem.status == "open")):
        if suggestion(db, item):
            out.append({"kind": "settle", "severity": "low", "title": item.title, "person": item.person, "amount": item.amount, "link": "/open-items"})
        elif item.due and item.due <= today:
            out.append({"kind": "overdue", "severity": "medium", "title": item.title, "person": item.person, "amount": item.amount,
                        "date": item.due.isoformat(), "direction": item.direction, "link": "/open-items"})
    from .plan import plan_report
    for p in plan_report(db, user_id, history=1)["items"]:
        if p["status"] == "over":
            out.append({"kind": "plan_over", "severity": "medium", "title": p["name"], "amount": p["actual"], "target": p["amount"], "link": "/plan"})
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda a: (order[a["severity"]], a.get("days_left", 99)))


@router.get("/attention")
def get_attention(db: Session = Depends(get_db), user=Depends(current_user)):
    return serialize({"items": attention(db, user.id)})


def queue_reminders(session: Session, owner_id: str, now=None) -> list[str]:
    from .notifications import NotificationSettings, queue_notification
    settings = session.get(NotificationSettings, str(owner_id))
    if not settings or not settings.enabled or "reminder" not in (settings.events or []):
        return []
    import time
    if time.monotonic() - _LAST_CHECK.get(str(owner_id), -1e9) < 3600:
        return []
    _LAST_CHECK[str(owner_id)] = time.monotonic()
    today = local_today(session, str(owner_id))
    queued = []
    from .contract_terms import deadlines
    for d in deadlines(session, str(owner_id), today):
        left = d.get("days_left")
        if d.get("expired") or left is None:
            continue
        for threshold in sorted(THRESHOLDS):  # the tightest threshold already reached: 9 days -> 14, 6 days -> 7
            if left <= threshold:
                queued.append(queue_notification(session, str(owner_id), "reminder", f"deadline:{d['key'][:120]}:{d['cancel_by']}:{threshold}", now).id)
                break
    from .receivables import OpenItem
    for item in session.scalars(select(OpenItem).where(OpenItem.user_id == str(owner_id), OpenItem.status == "open")):
        if item.due and item.due <= today:
            queued.append(queue_notification(session, str(owner_id), "reminder", f"open-item:{item.id}:{item.due.isoformat()}", now).id)
    return queued
