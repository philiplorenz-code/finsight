"""Paperless-ngx: archive receipts there and find matching documents for a booking.

Configured by the operator in .env (never stored in the database, never returned by the API):
PAPERLESS_URL (as the API container reaches it, e.g. http://host.docker.internal:8010), PAPERLESS_TOKEN
(an API token from Paperless → My Profile) and optionally PAPERLESS_PUBLIC_URL (links for the browser,
default http://127.0.0.1:8010). Only the receipt image, a title and the date are sent; no bookings.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db

router = APIRouter(tags=["paperless"])
TIMEOUT = httpx.Timeout(15.0, connect=4.0)
transport: httpx.BaseTransport | None = None  # tests inject httpx.MockTransport
URL_RE = re.compile(r"https?://[A-Za-z0-9.\-\[\]:]+(/[A-Za-z0-9._~\-/]*)?")


def token_header(token: str) -> dict:
    return {"Authorization": f"Token {token}", "Accept": "application/json"}


def config() -> tuple[str, str, str] | None:
    base = os.environ.get("PAPERLESS_URL", "").strip().rstrip("/")
    token = os.environ.get("PAPERLESS_TOKEN", "").strip()
    public = (os.environ.get("PAPERLESS_PUBLIC_URL", "").strip() or "http://127.0.0.1:8010").rstrip("/")
    if not base or not token or not URL_RE.fullmatch(base) or not URL_RE.fullmatch(public) or any(c in token for c in "\r\n "):
        return None
    if "@" in base:
        return None
    return base, token, public


def client(token: str) -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers=token_header(token), transport=transport, follow_redirects=False)


def require() -> tuple[str, str, str]:
    cfg = config()
    if not cfg:
        raise HTTPException(409, "Paperless is not configured (PAPERLESS_URL and PAPERLESS_TOKEN in .env)")
    return cfg


def upstream_error(exc: Exception) -> HTTPException:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403):
        return HTTPException(502, "Paperless rejected the token")
    return HTTPException(502, "Paperless is not reachable")


@router.get("/paperless/status")
def status(user=Depends(current_user)):
    cfg = config()
    if not cfg:
        return {"configured": False, "reachable": False}
    base, token, public = cfg
    try:
        with client(token) as c:
            c.get(f"{base}/api/documents/", params={"page_size": 1}).raise_for_status()
        return {"configured": True, "reachable": True, "url": public}
    except (httpx.HTTPError, ValueError) as exc:
        return {"configured": True, "reachable": False, "url": public, "error": upstream_error(exc).detail}


@router.get("/paperless/documents")
def documents(q: str = Query(min_length=2, max_length=100), user=Depends(current_user)):
    base, token, public = require()
    try:
        with client(token) as c:
            r = c.get(f"{base}/api/documents/", params={"query": q, "page_size": 8, "ordering": "-created",
                                                        "fields": "id,title,created,original_file_name"})
            r.raise_for_status()
            results = r.json().get("results", [])
    except (httpx.HTTPError, ValueError) as exc:
        raise upstream_error(exc) from None
    out = []
    for d in results[:8]:
        if not isinstance(d, dict) or not isinstance(d.get("id"), int):
            continue
        out.append({"id": d["id"], "title": str(d.get("title") or "")[:200], "created": str(d.get("created") or "")[:10],
                    "url": f"{public}/documents/{d['id']}/details"})
    return {"items": out, "url": public}


def send_receipt(db: Session, receipt, user) -> dict:
    from .receipts import MIME, receipt_dir
    base, token, public = require()
    path = receipt_dir() / Path(receipt.image_path).name
    if not path.exists():
        raise HTTPException(404, "Image no longer stored")
    title = " ".join(x for x in ["Kassenzettel", receipt.merchant or "", receipt.receipt_date.isoformat() if receipt.receipt_date else ""] if x)[:120]
    data = {"title": title}
    if receipt.receipt_date:
        data["created"] = receipt.receipt_date.isoformat()
    try:
        with client(token) as c:
            r = c.post(f"{base}/api/documents/post_document/", data=data,
                       files={"document": (f"kassenzettel.{receipt.image_type}", path.read_bytes(), MIME.get(receipt.image_type, "application/octet-stream"))})
            r.raise_for_status()
            task = r.json() if r.content else ""
    except (httpx.HTTPError, ValueError) as exc:
        raise upstream_error(exc) from None
    receipt.paperless_task = str(task)[:64] if isinstance(task, str) else ""
    receipt.paperless_sent_at = datetime.now(timezone.utc)
    db.commit()
    return {"sent": True, "url": public}
