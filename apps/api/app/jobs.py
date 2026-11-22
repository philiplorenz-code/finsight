"""PostgreSQL durable queue, fenced leases and non-destructive stable-file watcher."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import os
import stat
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint, and_, or_, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

# ``python -m app.jobs`` must share the same model classes with integrations that
# import app.jobs while constructing the default worker factory.
if __name__ == "__main__":
    sys.modules.setdefault(__package__ + ".jobs", sys.modules[__name__])

from .ai import Base, utcnow


class Job(Base):
    __tablename__ = "worker_jobs"
    __table_args__ = (UniqueConstraint("owner_id", "dedupe_key", name="uq_worker_job_dedupe"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(48), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    state: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    # Only jobs whose handler is replay-safe may reclaim an expired lease.
    replay_safe: Mapped[bool] = mapped_column(Boolean, default=False)


class JobAttempt(Base):
    __tablename__ = "worker_job_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    token: Mapped[str] = mapped_column(String(36), unique=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), default="running")
    # Fixed reason codes only: exception text often contains paths/private data.
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)


@dataclass(frozen=True)
class Claim:
    id: str
    owner_id: str
    kind: str
    payload: dict
    token: str


class JobDeferred(Exception):
    def __init__(self, until: datetime):
        self.until = until
        super().__init__("job_deferred")


def enqueue(session: Session, owner_id: str, kind: str, payload: dict, *, dedupe_key: str | None = None,
            replay_safe: bool = False, max_attempts: int = 3, available_at: datetime | None = None) -> Job:
    if (not kind or len(kind) > 48 or not 1 <= max_attempts <= 8 or len(json.dumps(payload).encode()) > 16384
            or (dedupe_key is not None and (not dedupe_key or len(dedupe_key) > 200))):
        raise ValueError("invalid_job")
    if dedupe_key:
        found = session.scalar(select(Job).where(Job.owner_id == str(owner_id), Job.dedupe_key == dedupe_key))
        if found:
            return found
    job = Job(owner_id=str(owner_id), kind=kind, payload=payload, dedupe_key=dedupe_key,
              replay_safe=replay_safe, max_attempts=max_attempts, available_at=available_at or utcnow())
    # Unique constraint is the final concurrent dedupe guard; the caller should
    # retry its transaction on IntegrityError, never dispatch before committing.
    session.add(job)
    session.flush()
    return job


def claim(session: Session, kinds: set[str], *, lease_seconds: int = 90, now: datetime | None = None) -> Claim | None:
    if not 5 <= lease_seconds <= 3600:
        raise ValueError("invalid_lease")
    now = now or utcnow()
    # Reap exhausted/non-replayable expired work under row locks. Such work is
    # uncertain, not silently retried (e.g. an external request may have succeeded).
    expired = session.scalars(select(Job).where(Job.state == "running", Job.lease_until <= now,
        or_(Job.replay_safe.is_(False), Job.attempts >= Job.max_attempts)).with_for_update(skip_locked=True))
    for row in expired:
        previous = session.scalar(select(JobAttempt).where(JobAttempt.token == row.lease_token))
        if previous and previous.outcome == "running":
            previous.outcome, previous.finished_at, previous.error_code = "lease_expired", now, "lease_expired"
        row.state = "uncertain"
        row.lease_token = None
    row = session.scalar(select(Job).where(Job.kind.in_(kinds), Job.attempts < Job.max_attempts,
        or_(and_(Job.state == "queued", Job.available_at <= now),
            and_(Job.state == "running", Job.replay_safe.is_(True), Job.lease_until <= now)))
        .order_by(Job.available_at, Job.id).with_for_update(skip_locked=True).limit(1))
    if not row:
        return None
    if row.lease_token:
        previous = session.scalar(select(JobAttempt).where(JobAttempt.token == row.lease_token))
        if previous and previous.outcome == "running":
            previous.outcome, previous.finished_at, previous.error_code = "lease_expired", now, "lease_expired"
    token = str(uuid.uuid4())
    row.state, row.lease_token, row.lease_until = "running", token, now + timedelta(seconds=lease_seconds)
    row.attempts += 1
    session.add(JobAttempt(job_id=row.id, token=token, started_at=now))
    session.flush()
    return Claim(row.id, row.owner_id, row.kind, row.payload, token)


def heartbeat(session: Session, item: Claim, lease_seconds: int = 90, now: datetime | None = None) -> bool:
    now = now or utcnow()
    if not 5 <= lease_seconds <= 3600:
        raise ValueError("invalid_lease")
    result = session.execute(update(Job).where(Job.id == item.id, Job.lease_token == item.token,
        Job.state == "running", Job.lease_until > now).values(lease_until=now + timedelta(seconds=lease_seconds)))
    return result.rowcount == 1


def finish(session: Session, item: Claim, *, success: bool, retryable: bool = False,
           now: datetime | None = None) -> bool:
    now = now or utcnow()
    row = session.scalar(select(Job).where(Job.id == item.id, Job.lease_token == item.token,
        Job.state == "running", Job.lease_until > now).with_for_update())
    if not row:
        return False  # Fencing: an old worker cannot complete or retry a newer claim.
    history = session.scalar(select(JobAttempt).where(JobAttempt.token == item.token))
    history.finished_at, history.outcome = now, "succeeded" if success else "failed"
    history.error_code = None if success else "handler_failed"
    if success:
        row.state = "succeeded"
    elif retryable and row.replay_safe and row.attempts < row.max_attempts:
        row.state, row.available_at = "queued", now + timedelta(seconds=min(3600, 5 * 2 ** row.attempts))
    else:
        row.state = "failed" if row.replay_safe else "uncertain"
    row.lease_token, row.lease_until = None, None
    return True


def defer(session: Session, item: Claim, until: datetime, *, now: datetime | None = None) -> bool:
    now = now or utcnow()
    if until.tzinfo is None or not now < until <= now + timedelta(days=2):
        raise ValueError("invalid_deferral")
    row = session.scalar(select(Job).where(Job.id == item.id, Job.lease_token == item.token,
        Job.state == "running", Job.lease_until > now).with_for_update())
    if not row:
        return False
    history = session.scalar(select(JobAttempt).where(JobAttempt.token == item.token))
    history.finished_at, history.outcome = now, "deferred"
    row.state, row.available_at, row.attempts = "queued", until, max(0, row.attempts - 1)
    row.lease_token, row.lease_until = None, None
    return True


class StableWatcher:
    """Two unchanged observations + minimum age; bounded hash, no file deletion.

    Handler must revalidate digest while importing. The watcher never opens real
    source data during application startup: poll is an explicit worker operation.
    """
    def __init__(self, root: Path = Path("/data/imports"), stable_seconds: int = 30, max_bytes: int = 32 * 1024 * 1024):
        self.root = root.resolve()
        self.stable_seconds = max(1, stable_seconds)
        self.max_bytes = max_bytes
        self.observations: dict[str, tuple[int, int, float]] = {}

    def poll(self, session: Session, owner_id: str, *, now: datetime | None = None) -> int:
        now = now or utcnow()
        if not self.root.is_dir():
            return 0
        count, seen = 0, set()
        for path in sorted(self.root.glob("*.xlsx"))[:1000]:
            try:
                before = path.lstat()
                if not stat.S_ISREG(before.st_mode) or path.resolve().parent != self.root:
                    continue
                if not 0 < before.st_size <= self.max_bytes:
                    continue
                name, signature = path.name, (before.st_size, before.st_mtime_ns)
                seen.add(name)
                prior = self.observations.get(name)
                if not prior or prior[:2] != signature:
                    self.observations[name] = (*signature, now.timestamp())
                    continue
                if now.timestamp() - max(prior[2], before.st_mtime) < self.stable_seconds:
                    continue
                digest = hashlib.sha256()
                # O_NOFOLLOW prevents symlink replacement between lstat and open.
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if (opened.st_ino, opened.st_size, opened.st_mtime_ns) != (before.st_ino, *signature):
                        continue
                    read_bytes = 0
                    while block := stream.read(1024 * 1024):
                        read_bytes += len(block)
                        if read_bytes > self.max_bytes:
                            break
                        digest.update(block)
                    after = os.fstat(stream.fileno())
                if read_bytes != before.st_size or (after.st_size, after.st_mtime_ns) != signature:
                    continue
                sha = digest.hexdigest()
                existing = session.scalar(select(Job.id).where(Job.owner_id == str(owner_id), Job.dedupe_key == "import:" + sha))
                if existing:
                    continue
                enqueue(session, str(owner_id), "import_file", {"filename": name, "sha256": sha},
                        dedupe_key="import:" + sha, replay_safe=True)
                count += 1
            except (OSError, ValueError):
                continue
        self.observations = {k: v for k, v in self.observations.items() if k in seen}
        return count


Handler = Callable[[Claim], Awaitable[None]]


async def run_worker(session_factory: Callable, handlers: dict[str, Handler], *, stop: asyncio.Event | None = None,
                     lease_seconds: int = 90, handler_timeout: int = 60,
                     poll_hook: Callable[[Session], None] | None = None) -> None:
    """One task per process; parallelism is multiple workers. No hidden background threads.

    Handler timeout is shorter than lease. An expired handler must not be replayed
    unless idempotent; database handlers should verify the claim token transactionally.
    """
    if not 1 <= handler_timeout < lease_seconds or not 5 <= lease_seconds <= 3600:
        raise ValueError("invalid_worker_bounds")
    stop = stop or asyncio.Event()
    while not stop.is_set():
        with session_factory() as session:
            if poll_hook:
                poll_hook(session)
            item = claim(session, set(handlers), lease_seconds=lease_seconds)
            session.commit()
        if not item:
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass
            continue
        success, deferred = False, None
        try:
            async with asyncio.timeout(handler_timeout):
                await handlers[item.kind](item)
            success = True
        except JobDeferred as exc:
            deferred = exc.until
        except Exception:
            pass  # Persist a safe code, not exception messages or private payloads.
        with session_factory() as session:
            if deferred is not None:
                defer(session, item, deferred)
            else:
                finish(session, item, success=success, retryable=True)
            session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="FinSight durable worker")
    parser.add_argument("--factory", default=os.environ.get("FINSIGHT_WORKER_FACTORY", "app.jobs:default_worker_factory"),
                        help="Trusted operator module:function returning (session_factory, handlers, poll_hook)")
    args = parser.parse_args()
    if not args.factory or ":" not in args.factory:
        parser.error("configure --factory app.integration:worker_factory; no handlers are enabled by default")
    module, name = args.factory.split(":", 1)
    session_factory, handlers, poll_hook = getattr(importlib.import_module(module), name)()
    from .ai import runtime_environment
    runtime = runtime_environment()["timeout_seconds"]
    timeout = max(60, runtime + 5)
    asyncio.run(run_worker(session_factory, handlers, poll_hook=poll_hook, handler_timeout=timeout, lease_seconds=timeout + 30))


def watch_full_snapshot(filename: str) -> bool:
    """FINSIGHT_WATCH_FULL_SNAPSHOT: auto (default) treats 'Alle Buchungen' exports as full snapshots."""
    mode = os.environ.get("FINSIGHT_WATCH_FULL_SNAPSHOT", "auto").strip().lower()
    if mode in ("true", "1", "yes"):
        return True
    if mode == "auto":
        return "alle_buchungen" in filename.lower().replace("-", "_").replace(" ", "_")
    return False


def watched_import_handler(session_factory: Callable, root: Path = Path("/data/imports"), max_bytes: int = 32 * 1024 * 1024):
    """Core importer adapter: owner-scoped, digest-verified, claim-fenced, never delete.

    The core parser enforces ZIP/XML/formula/resource checks. XLSX is not interpreted
    by the watcher. Import is synchronous and transactionally serializes per owner.
    """
    root = root.resolve()
    async def handle(item: Claim):
        from .importer import ingest
        from .models import User
        name, expected = item.payload.get("filename"), item.payload.get("sha256")
        if not isinstance(name, str) or Path(name).name != name or not name.endswith(".xlsx") or not isinstance(expected, str) or len(expected) != 64:
            raise ValueError("invalid_import_job")
        path = root / name
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= max_bytes:
                raise ValueError("invalid_import_file")
            data = stream.read(max_bytes + 1)
        if len(data) > max_bytes or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("import_file_changed")
        with session_factory() as session:
            # Hold this queue row until ingest commits. PostgreSQL claimers skip it
            # even if the lease expires during the bounded synchronous parser.
            locked = session.scalar(select(Job).where(Job.id == item.id, Job.owner_id == item.owner_id,
                Job.lease_token == item.token, Job.state == "running", Job.lease_until > utcnow()).with_for_update())
            if not locked:
                raise ValueError("lease_lost")
            owner = session.scalar(select(User).where(User.id == item.owner_id).with_for_update())
            if not owner:
                raise ValueError("owner_missing")
            ingest(session, owner, data, name, full_snapshot=watch_full_snapshot(name))
    return handle


def default_worker_factory():
    """Safe shipped worker; external effects require persisted owner opt-in.

    Watching is additionally opt-in via FINSIGHT_WATCH_IMPORTS=true and requires
    FINSIGHT_WATCH_OWNER_ID. No directory under the source tree is ever scanned.
    """
    from .ai import AIPolicy, env_bool, import_has_changes, report_handler, schedule_reports
    from .db import SessionLocal, engine
    from .models import Import, User
    from .notifications import (NotificationSettings, notification_handler,
                                queue_notification, schedule_reminders)

    if engine.dialect.name != "postgresql":
        raise ValueError("postgresql_required_for_worker")

    watch_enabled = os.environ.get("FINSIGHT_WATCH_IMPORTS", "false").lower() == "true"
    watch_owner = os.environ.get("FINSIGHT_WATCH_OWNER_ID", "")
    if watch_enabled and not watch_owner:
        raise ValueError("watch_owner_required")
    # The fixed mount is deliberate: operator factory overrides can customize it.
    watcher = StableWatcher(Path("/data/imports")) if watch_enabled else None
    handlers = {"ai_report": report_handler(SessionLocal),
                 "notify": notification_handler(SessionLocal)}
    if watcher:
        handlers["import_file"] = watched_import_handler(SessionLocal)
    last_poll = 0.0

    def poll(session: Session):
        nonlocal last_poll
        now = utcnow()
        if now.timestamp() - last_poll < 30:
            return
        last_poll = now.timestamp()
        owners = list(session.scalars(select(User.id).order_by(User.id).limit(100)))
        if watcher and watch_owner not in owners:
            raise ValueError("watch_owner_missing")
        for owner_id in owners:
            # Uniform cross-module lock order: policy -> notification settings.
            session.scalar(select(AIPolicy).where(AIPolicy.owner_id == owner_id).with_for_update())
            latest = session.scalar(select(Import).where(Import.user_id == owner_id, Import.status == "completed")
                                    .order_by(Import.created_at.desc(), Import.id.desc()).limit(1))
            preferences = session.scalar(select(NotificationSettings).where(NotificationSettings.owner_id == owner_id).with_for_update())
            if preferences and latest:
                preferences.last_import_at = latest.created_at
                session.flush()
            if latest:
                if env_bool("AI_ENABLED") and env_bool("AI_EXTERNAL_CONSENT") and env_bool("AI_PROACTIVE_ENABLED"):
                    schedule_reports(session, owner_id, latest.id, latest.created_at, now=now,
                                     latest_import_summary=latest.summary)
                if preferences and preferences.enabled and "import_changed" in preferences.events and import_has_changes(latest.summary):
                    queue_notification(session, owner_id, "import_changed", "import:" + latest.id, now)
                from .plan import queue_plan_alerts
                queue_plan_alerts(session, owner_id, now)
                if latest.id != getattr(poll, "anomaly_import", None):
                    from .insights_extra import queue_anomaly_alerts
                    queue_anomaly_alerts(session, owner_id, now)
                    poll.anomaly_import = latest.id
            schedule_reminders(session, owner_id, now)
            from .attention import queue_reminders
            queue_reminders(session, owner_id, now)
            if watcher and owner_id == watch_owner:
                watcher.poll(session, owner_id, now=now)
    return SessionLocal, handlers, poll


if __name__ == "__main__":
    main()
