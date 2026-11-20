"""Retained uploads so an interrupted background import can be resumed or retried without a re-upload.

Files live in a private directory outside Git, named only by their SHA-256 (never by the user's file name),
are removed as soon as the import completed and are purged after a bounded retention if they were never
needed again. When the directory is not writable, imports still work; they are just not resumable.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

RETENTION_DAYS = 7
HASH = re.compile(r"^[0-9a-f]{64}$")


def upload_dir() -> Path:
    return Path(os.environ.get("FINSIGHT_UPLOAD_DIR", "/data/app/uploads"))


def _path(digest: str) -> Path:
    if not HASH.match(digest):
        raise ValueError("invalid_digest")
    return upload_dir() / f"{digest}.xlsx"


def retain(digest: str, data: bytes) -> bool:
    try:
        directory = upload_dir()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = _path(digest)
        partial = target.with_suffix(".partial")
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(partial, target)
        return True
    except OSError:
        return False


def load(digest: str) -> bytes | None:
    try:
        return _path(digest).read_bytes()
    except (OSError, ValueError):
        return None


def exists(digest: str) -> bool:
    try:
        return _path(digest).is_file()
    except ValueError:
        return False


def discard(digest: str) -> None:
    try:
        _path(digest).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def purge_old(days: int = RETENTION_DAYS) -> int:
    removed = 0
    try:
        cutoff = time.time() - days * 86400
        for item in upload_dir().glob("*.xlsx"):
            if item.stat().st_mtime < cutoff:
                item.unlink(missing_ok=True)
                removed += 1
    except OSError:
        pass
    return removed
