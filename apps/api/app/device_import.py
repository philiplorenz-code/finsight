"""Import from the phone: an iOS Shortcut (share sheet) posts the export file with an import-only device key.

The key is shown once, stored only as SHA-256, can be revoked, and allows exactly one thing: starting a
background import for its owner. It is not a session: it cannot read data or change settings. The endpoint
does not use cookies, so CSRF does not apply; it lives on its own router without the CSRF dependency.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import current_user
from .db import Base, get_db
from .models import User

router = APIRouter(tags=["device-import"])  # session-authenticated management, CSRF applied by main.py
public_router = APIRouter(tags=["device-import"])  # bearer-key upload only, no cookies
PREFIX = "fsd_"
MAX_KEYS = 10
MAX_PER_HOUR = 30


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DeviceKey(Base):
    __tablename__ = "device_keys"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    hint: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_count: Mapped[int] = mapped_column(Integer, default=0)


def digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class KeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="iPhone", min_length=1, max_length=80)


def key_json(k: DeviceKey) -> dict:
    return {"id": k.id, "name": k.name, "hint": k.hint, "created_at": k.created_at.isoformat(),
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None}


@router.get("/device-keys")
def list_keys(db: Session = Depends(get_db), user=Depends(current_user)):
    return [key_json(k) for k in db.scalars(select(DeviceKey).where(DeviceKey.user_id == user.id).order_by(DeviceKey.created_at))]


@router.post("/device-keys", status_code=201)
def create_key(body: KeyBody, request: Request, db: Session = Depends(get_db), user=Depends(current_user)):
    if db.query(DeviceKey).filter(DeviceKey.user_id == user.id).count() >= MAX_KEYS:
        raise HTTPException(409, "Too many device keys")
    key = PREFIX + secrets.token_urlsafe(32)
    row = DeviceKey(user_id=user.id, name=body.name.strip(), key_hash=digest(key), hint=key[-4:])
    db.add(row)
    db.commit()
    return {**key_json(row), "key": key, "upload_url": str(request.base_url).rstrip("/") + "/api/device/import"}


@router.delete("/device-keys/{ident}", status_code=204)
def revoke_key(ident: str, db: Session = Depends(get_db), user=Depends(current_user)):
    row = db.scalar(select(DeviceKey).where(DeviceKey.id == ident, DeviceKey.user_id == user.id))
    if not row:
        raise HTTPException(404, "Device key not found")
    db.delete(row)
    db.commit()


def device_owner(authorization: str | None, db: Session) -> tuple[DeviceKey, User]:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token.startswith(PREFIX):
        raise HTTPException(401, "Device key required")
    row = db.scalar(select(DeviceKey).where(DeviceKey.key_hash == digest(token)))
    if not row or not secrets.compare_digest(row.key_hash, digest(token)):
        raise HTTPException(401, "Device key invalid or revoked")
    now = utcnow()
    start = row.window_start if row.window_start is None or row.window_start.tzinfo else row.window_start.replace(tzinfo=timezone.utc)
    if start is None or now - start > timedelta(hours=1):
        row.window_start, row.window_count = now, 0
    if row.window_count >= MAX_PER_HOUR:
        raise HTTPException(429, "Too many uploads, try again later")
    row.window_count += 1
    row.last_used_at = now
    user = db.get(User, row.user_id)
    if not user:
        raise HTTPException(401, "Device key invalid or revoked")
    return row, user


@public_router.post("/api/device/import", status_code=202)
async def device_import(background_tasks: BackgroundTasks, file: UploadFile = File(...), full_snapshot: bool = Form(False),
                        authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    from fastapi.responses import JSONResponse
    from .routes import upload
    _, user = device_owner(authorization, db)
    db.commit()
    head = await file.read(4)
    await file.seek(0)
    if head != b"PK\x03\x04":  # .xlsx is a ZIP container
        raise HTTPException(415, "Bitte die Excel-Datei (.xlsx) aus dem Finanzguru-Export teilen.")
    result = await upload(background_tasks, file, full_snapshot, True, db, user)
    body = result.body if isinstance(result, JSONResponse) else None
    if body is not None:
        import json
        data = json.loads(body)
    else:
        data = result
    return {"status": data.get("status"), "filename": data.get("filename"), "duplicate": data.get("duplicate", False),
            "message": "Import gestartet – Ergebnis siehst du in FinSight unter Datenimport."}
