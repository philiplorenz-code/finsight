"""Opt-in generic ntfy outbox, local-time schedules and auditable suppression."""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .ai import Base, authenticated_owner, env_bool, utcnow
from .jobs import Claim, JobDeferred, enqueue


class NotificationSettings(Base):
    __tablename__ = "notification_settings"
    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    server: Mapped[str] = mapped_column(String(500), default="")
    topic: Mapped[str] = mapped_column(String(100), default="")
    timezone: Mapped[str] = mapped_column(String(80), default="Europe/Berlin")
    quiet_start: Mapped[int] = mapped_column(Integer, default=22 * 60)
    quiet_end: Mapped[int] = mapped_column(Integer, default=8 * 60)
    stale_after_hours: Mapped[int] = mapped_column(Integer, default=7 * 24)
    last_import_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    events: Mapped[list] = mapped_column(JSON, default=list)
    reminder_hour: Mapped[int] = mapped_column(Integer, default=9)
    reminder_minute: Mapped[int] = mapped_column(Integer, default=0)
    weekly_day: Mapped[int] = mapped_column(Integer, default=0)


class Notification(Base):
    __tablename__ = "notification_history"
    __table_args__ = (UniqueConstraint("owner_id", "dedupe_key", name="uq_notification_dedupe"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    event: Mapped[str] = mapped_column(String(32))
    dedupe_key: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(32), default="queued")
    reason: Mapped[str | None] = mapped_column(String(48), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


EVENTS = {"weekly", "monthly", "report_ready", "anomaly", "import_changed", "test"}
MESSAGE = "FinSight: An update is available. Open your private dashboard to review it."


def dashboard_headers(event: str) -> dict[str, str]:
    """Optional generic deep link; never accept private paths, queries or auth."""
    origin = os.environ.get("APP_URL", "").rstrip("/")
    if not re.fullmatch(r"https?://[A-Za-z0-9.\-\[\]:]+", origin):
        return {}
    try:
        parsed = urlsplit(origin)
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return {}
        _ = parsed.port  # Reject malformed/out-of-range authorities.
    except ValueError:
        return {}
    path = "/insights" if event in {"report_ready", "anomaly"} else "/imports"
    url = origin + path
    return {"Click": url, "Actions": "view, Open FinSight, " + url}


def aware(value: datetime) -> datetime:
    # SQLite drops timezone metadata; production columns are PostgreSQL timestamptz.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def validate(settings: NotificationSettings) -> None:
    # SQLAlchemy insert defaults have not run when a newly constructed row is
    # validated by the core settings endpoint.
    if settings.reminder_minute is None:
        settings.reminder_minute = 0
    try:
        ZoneInfo(settings.timezone)
    except (ZoneInfoNotFoundError, TypeError):
        raise ValueError("invalid_timezone") from None
    if not (0 <= settings.quiet_start < 1440 and 0 <= settings.quiet_end < 1440
            and 1 <= settings.stale_after_hours <= 24 * 365
            and 0 <= settings.reminder_hour <= 23 and 0 <= settings.reminder_minute <= 59 and 0 <= settings.weekly_day <= 6):
        raise ValueError("invalid_notification_bounds")
    if not isinstance(settings.events, list) or any(event not in EVENTS - {"test"} for event in settings.events):
        raise ValueError("invalid_notification_events")


def is_quiet(settings: NotificationSettings, now: datetime) -> bool:
    validate(settings)
    local = aware(now).astimezone(ZoneInfo(settings.timezone))
    minute = local.hour * 60 + local.minute
    start, end = settings.quiet_start, settings.quiet_end
    if start == end:
        return False  # Explicitly disabled, not 24-hour suppression.
    return start <= minute < end if start < end else minute >= start or minute < end


def next_allowed(settings: NotificationSettings, now: datetime) -> datetime:
    now = aware(now)
    if not is_quiet(settings, now):
        return now
    # Search on the UTC timeline: DST gaps/folds cannot produce invalid wall times.
    candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(48 * 60):
        if not is_quiet(settings, candidate):
            return candidate
        candidate += timedelta(minutes=1)
    raise ValueError("quiet_window_unresolvable")


def suppression(settings: NotificationSettings | None, event: str, now: datetime) -> str | None:
    if not settings or not settings.enabled:
        return "disabled"
    validate(settings)
    if event != "test" and event not in settings.events:
        return "event_disabled"
    if event != "test" and (not settings.last_import_at or
            aware(now) - aware(settings.last_import_at) > timedelta(hours=settings.stale_after_hours) or
            aware(settings.last_import_at) > aware(now) + timedelta(minutes=5)):
        return "stale_import"
    return None


def queue_notification(session: Session, owner_id: str, event: str, dedupe_key: str,
                       now: datetime | None = None) -> Notification:
    if event not in EVENTS or not dedupe_key or len(dedupe_key) > 200:
        raise ValueError("invalid_notification")
    now = now or utcnow()
    # Settings lock serializes event dedupe with scheduling/sending. Missing settings
    # are disabled; unique constraint remains the concurrent last line of defence.
    settings = session.scalar(select(NotificationSettings).where(NotificationSettings.owner_id == str(owner_id)).with_for_update())
    previous = session.scalar(select(Notification).where(Notification.owner_id == str(owner_id), Notification.dedupe_key == dedupe_key))
    if previous:
        return previous
    reason = suppression(settings, event, now)
    available_at = next_allowed(settings, now) if reason is None else now
    row = Notification(owner_id=str(owner_id), event=event, dedupe_key=dedupe_key,
                       state="suppressed" if reason else "queued", reason=reason,
                       created_at=now, available_at=available_at)
    session.add(row)
    session.flush()
    if reason is None:
        # Replay-safe at the outbox level: a durable 'sending' state prevents a
        # second HTTP request after a crash. Known retryable HTTP failures may retry.
        enqueue(session, str(owner_id), "notify", {"notification_id": row.id}, dedupe_key="notify:" + row.id,
                replay_safe=True, max_attempts=3, available_at=available_at)
    return row


def schedule_reminders(session: Session, owner_id: str, now: datetime | None = None) -> list[str]:
    now = now or utcnow()
    settings = session.scalar(select(NotificationSettings).where(NotificationSettings.owner_id == str(owner_id)).with_for_update())
    if not settings or not settings.enabled:
        return []
    validate(settings)
    local = aware(now).astimezone(ZoneInfo(settings.timezone))
    if local.hour * 60 + local.minute < settings.reminder_hour * 60 + settings.reminder_minute:
        return []
    scheduled = []
    if local.weekday() == settings.weekly_day and "weekly" in settings.events:
        year, week, _ = local.isocalendar()
        row = queue_notification(session, str(owner_id), "weekly", f"weekly:{year}:{week}", now)
        scheduled.append(row.id)
    if local.day == 1 and "monthly" in settings.events:
        row = queue_notification(session, str(owner_id), "monthly", f"monthly:{local:%Y-%m}", now)
        scheduled.append(row.id)
    return scheduled


def ntfy_url(settings: NotificationSettings) -> str:
    parsed = urlsplit(settings.server)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", settings.topic)):
        raise ValueError("invalid_ntfy_configuration")
    # HTTP is supported for explicitly configured self-hosted LAN ntfy servers.
    # This is operator configuration, never an HTTP request parameter.
    return settings.server.rstrip("/") + "/" + settings.topic


def provision_notification_environment(session: Session, owner_id: str) -> NotificationSettings:
    """Provision only after an authenticated settings/consent request, never on import."""
    from .models import User
    if not env_bool("NTFY_ENABLED"):
        raise ValueError("operator_ntfy_disabled")
    def minute(name: str, default: str) -> int:
        value = os.environ.get(name, default)
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("invalid_notification_time")
        hours, minutes = map(int, value.split(":"))
        return hours * 60 + minutes
    try:
        days = int(os.environ.get("NTFY_REMINDER_DAYS", "14"))
    except ValueError:
        raise ValueError("invalid_notification_bounds") from None
    reminder = minute("NTFY_REMINDER_TIME", "09:00")
    row = NotificationSettings(owner_id=str(owner_id), enabled=False,
        server=os.environ.get("NTFY_SERVER_URL", "https://ntfy.sh"), topic=os.environ.get("NTFY_TOPIC", ""),
        timezone="Europe/Berlin", quiet_start=minute("NTFY_QUIET_START", "22:00"),
        quiet_end=minute("NTFY_QUIET_END", "08:00"), stale_after_hours=days * 24,
        reminder_hour=reminder // 60, reminder_minute=reminder % 60, weekly_day=0, events=[])
    validate(row)
    ntfy_url(row)
    session.scalar(select(User).where(User.id == str(owner_id)).with_for_update())
    existing = session.scalar(select(NotificationSettings).where(NotificationSettings.owner_id == str(owner_id)).with_for_update())
    if existing:
        return existing
    session.add(row)
    session.flush()
    return row


class DeliveryRetryable(RuntimeError):
    pass


class NotificationConsent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool
    events: list[Literal["weekly", "monthly", "report_ready", "anomaly", "import_changed"]] = Field(max_length=5)
    timezone: str = Field(default="Europe/Berlin", max_length=80)
    quiet_start: int = Field(default=1320, ge=0, lt=1440)
    quiet_end: int = Field(default=480, ge=0, lt=1440)
    stale_after_hours: int = Field(default=168, ge=1, le=8760)
    reminder_hour: int = Field(default=9, ge=0, le=23)
    reminder_minute: int = Field(default=0, ge=0, le=59)
    weekly_day: int = Field(default=0, ge=0, le=6)


async def send_notification(session_factory: Callable, item: Claim, *, auth_token: str | None = None,
                            client=None, now: datetime | None = None) -> None:
    """No financial data in body, title, URL or headers; no redirects or HTTP retries.

    Ambiguous timeout/crash -> uncertain, no automatic re-send. Authentication is
    passed from an operator secret, never stored in history or queue payloads.
    """
    import httpx

    now = now or utcnow()
    auth_token = auth_token if auth_token is not None else os.environ.get("NTFY_ACCESS_TOKEN")
    with session_factory() as session:
        settings = session.scalar(select(NotificationSettings).where(NotificationSettings.owner_id == item.owner_id).with_for_update())
        row = session.scalar(select(Notification).where(Notification.id == item.payload.get("notification_id"),
                                                        Notification.owner_id == item.owner_id).with_for_update())
        if not row or row.state in {"sent", "suppressed", "uncertain"}:
            return
        if row.state == "sending":
            row.state, row.reason = "uncertain", "previous_delivery_unconfirmed"
            session.commit()
            return
        reason = suppression(settings, row.event, now)
        if reason:
            row.state, row.reason = "suppressed", reason
            session.commit()
            return
        if is_quiet(settings, now) or aware(row.available_at) > aware(now):
            # Quiet hours are not failed delivery attempts; preserve retry budget.
            row.available_at = max(aware(row.available_at), next_allowed(settings, now))
            deferred_until = row.available_at
            session.commit()
            raise JobDeferred(deferred_until)
        try:
            url = ntfy_url(settings)
        except ValueError:
            row.state, row.reason = "suppressed", "invalid_configuration"
            session.commit()
            return
        row.state, row.reason, row.attempts = "sending", None, row.attempts + 1
        row_id, event = row.id, row.event
        session.commit()  # Crash after this point is ambiguous, never send twice.
    headers = {"Title": "FinSight", "Content-Type": "text/plain; charset=utf-8", **dashboard_headers(event)}
    if auth_token:
        headers["Authorization"] = "Bearer " + auth_token
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(10, connect=3), follow_redirects=False)
    state, reason, retry = "uncertain", "delivery_unconfirmed", False
    try:
        response = await client.post(url, content=MESSAGE.encode(), headers=headers, follow_redirects=False)
        if 200 <= response.status_code < 300:
            state, reason = "sent", None
        elif response.status_code == 429:
            state, reason, retry = "failed", "rate_limited", True
        elif response.status_code >= 500:
            # A 5xx can follow a successful publish. Retain uncertainty, no duplicate.
            state, reason = "uncertain", "server_failure_unconfirmed"
        else:
            state, reason = "suppressed", "server_rejected"
    except httpx.ConnectError:
        state, reason, retry = "failed", "connection_failed", True
    except Exception:
        pass  # No response text, URL, token or exception message is recorded.
    finally:
        if own_client:
            await client.aclose()
        with session_factory() as session:
            row = session.scalar(select(Notification).where(Notification.id == row_id,
                                                            Notification.owner_id == item.owner_id).with_for_update())
            if row and row.state == "sending":
                row.state, row.reason = state, reason
                if state == "sent":
                    row.sent_at = now
            session.commit()
    if retry:
        raise DeliveryRetryable(reason)


def notification_handler(session_factory: Callable, token_for_owner: Callable[[str], str | None] | None = None):
    async def handle(item: Claim):
        if token_for_owner is None and not env_bool("NTFY_ENABLED"):
            with session_factory() as session:
                row = session.scalar(select(Notification).where(Notification.id == item.payload.get("notification_id"),
                    Notification.owner_id == item.owner_id).with_for_update())
                if row and row.state in {"queued", "failed"}:
                    row.state, row.reason = "suppressed", "operator_disabled"
                    session.commit()
            return
        token = token_for_owner(item.owner_id) if token_for_owner else os.environ.get("NTFY_ACCESS_TOKEN")
        # A per-owner resolver returning None means anonymous for THAT owner,
        # never an accidental fallback to the process-wide owner's credential.
        await send_notification(session_factory, item, auth_token=token or "")
    return handle


def create_router(get_session: Callable, require_owner: Callable) -> APIRouter:
    router = APIRouter(tags=["notifications"])

    @router.get("/notifications/settings")
    def notification_settings(session: Session = Depends(get_session), owner=Depends(require_owner)):
        settings = session.get(NotificationSettings, str(owner))
        if not settings:
            return {"configured": False, "enabled": False, "events": []}
        return {"configured": True, "enabled": settings.enabled, "events": settings.events,
                "timezone": settings.timezone, "quiet_start": settings.quiet_start, "quiet_end": settings.quiet_end,
                "stale_after_hours": settings.stale_after_hours, "reminder_hour": settings.reminder_hour,
                "reminder_minute": settings.reminder_minute, "weekly_day": settings.weekly_day}

    @router.patch("/notifications/settings")
    @router.post("/notifications/consent")
    def notification_consent(body: NotificationConsent, session: Session = Depends(get_session), owner=Depends(require_owner)):
        settings = session.scalar(select(NotificationSettings).where(NotificationSettings.owner_id == str(owner)).with_for_update().execution_options(populate_existing=True))
        try:
            if not settings:
                settings = provision_notification_environment(session, str(owner))
            # On first provisioning, omitted fields use the documented env defaults.
            # Explicit request fields override schedule defaults, not endpoint/secrets.
            fields = body.model_dump()
            for key in body.model_fields_set:
                setattr(settings, key, fields[key])
            validate(settings)
            if settings.enabled:
                ntfy_url(settings)
        except ValueError:
            session.rollback()
            raise HTTPException(409, "invalid_notification_configuration") from None
        session.commit()
        return {"enabled": settings.enabled, "events": settings.events}

    @router.post("/notifications/test", status_code=202)
    def test_notification(session: Session = Depends(get_session), owner=Depends(require_owner)):
        try:
            row = queue_notification(session, str(owner), "test", "test:" + str(uuid.uuid4()))
            session.commit()
        except ValueError:
            session.rollback()
            raise HTTPException(409, "invalid_notification_settings") from None
        return {"id": row.id, "state": row.state, "reason": row.reason}

    @router.get("/notifications")
    def history(session: Session = Depends(get_session), owner=Depends(require_owner)):
        rows = session.scalars(select(Notification).where(Notification.owner_id == str(owner)).order_by(Notification.created_at.desc()).limit(100))
        return {"items": [{"id": r.id, "event": r.event, "state": r.state, "reason": r.reason,
                           "attempts": r.attempts, "created_at": r.created_at.isoformat(),
                           "sent_at": r.sent_at.isoformat() if r.sent_at else None} for r in rows]}

    return router


from .db import get_db

router = create_router(get_db, authenticated_owner)
