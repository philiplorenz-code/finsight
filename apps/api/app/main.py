import importlib

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from starlette.responses import JSONResponse

from . import models
from .auth import require_csrf, router as auth_router
from .db import get_db
from .routes import router as finance_router
from .limits import RequestSizeLimit

app = FastAPI(title="FinSight API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(RequestSizeLimit)
app.include_router(auth_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(finance_router, prefix="/api", dependencies=[Depends(require_csrf)])

for module_name in ("ai", "notifications", "jobs"):
    try:
        module = importlib.import_module(f"app.{module_name}")
    except ModuleNotFoundError as exc:
        if exc.name != f"app.{module_name}":
            raise
        continue
    if getattr(module, "router", None) is not None:
        app.include_router(module.router, prefix="/api", dependencies=[Depends(require_csrf)])


@app.get("/api/health")
def health(db=Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "Database unavailable") from None
    return {"status": "ok", "database": "ok"}


@app.middleware("http")
async def security_headers(request, call_next):
    try:
        response = await call_next(request)
    except Exception:
        # SQL/parser/provider exceptions can embed bound values. Do not hand them
        # to the ASGI server's traceback logger or expose exception text.
        response = JSONResponse({"detail": "Request could not be completed"}, status_code=503)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response
