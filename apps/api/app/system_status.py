"""Host health hints that protect the database: free disk space of the volume the API runs on.

A full Docker VM disk once pushed PostgreSQL into crash recovery, so the app warns early. Only
percentages and rounded gigabytes are exposed, nothing about the data itself.
"""
from __future__ import annotations

import os
import shutil

from fastapi import APIRouter, Depends

from .auth import current_user

router = APIRouter(tags=["system"])

WARN_FREE_PERCENT = 15.0
CRITICAL_FREE_PERCENT = 7.0


def disk_status(path: str | None = None) -> dict:
    usage = shutil.disk_usage(path or os.environ.get("FINSIGHT_DISK_PATH", "/"))
    free_percent = round(usage.free / usage.total * 100, 1) if usage.total else 100.0
    level = "critical" if free_percent < CRITICAL_FREE_PERCENT else "warning" if free_percent < WARN_FREE_PERCENT else "ok"
    return {"level": level, "free_percent": free_percent, "free_gb": round(usage.free / 1e9, 1), "total_gb": round(usage.total / 1e9, 1)}


@router.get("/system/disk")
def disk(user=Depends(current_user)):
    return disk_status()
