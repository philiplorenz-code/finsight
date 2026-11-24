import importlib
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import models
from .auth import require_csrf, router as auth_router
from .db import get_db
from .routes import router as finance_router
from .income import router as income_router
from .transfers import router as transfers_router
from .account_setup import router as account_setup_router
from .category_rules import router as category_rules_router
from .ai_analyst import router as ai_analyst_router
from .recurring import router as recurring_router
from .quality import router as quality_router
from .business import router as business_router
from .networth import router as networth_router
from .system_status import router as system_router
from .plan import router as plan_router
from .tidy import router as tidy_router
from .paperless import router as paperless_router
from .search import router as search_router
from .attention import router as attention_router
from .cashbook import router as cashbook_router
from .receivables import router as receivables_router
from .contract_terms import router as contract_terms_router
from .report import router as report_router
from .receipts import router as receipts_router
from .device_import import public_router as device_public_router, router as device_router
from .insights_extra import router as insights_extra_router
from .forecast import router as forecast_router
from .watch import router as watch_router
from .health import router as health_router
from .asof import router as asof_router
from .wishlist import router as wishlist_router
from .limits import RequestSizeLimit
from .mcp_server import CanonicalEndpoint, enabled as mcp_enabled, http_app as mcp_http_app, mcp
from .mcp_auth import router as mcp_auth_router


@asynccontextmanager
async def lifespan(app):
    import threading
    from .db import engine
    from .routes import resume_interrupted_imports
    # Imports a previous process left half-way continue from their retained upload, off the request path.
    def resume():
        try:
            resume_interrupted_imports(engine)
        except Exception:  # best effort: a missing schema or database must not stop the API from starting
            pass
    threading.Thread(target=resume, daemon=True, name="resume-imports").start()
    if mcp_enabled():
        async with mcp.session_manager.run():
            yield
    else:
        yield


app = FastAPI(title="FinSight API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
app.add_middleware(RequestSizeLimit)
app.router.routes.append(Route("/mcp", endpoint=CanonicalEndpoint(mcp_http_app), methods=["GET", "POST", "DELETE", "OPTIONS"]))
app.mount("/mcp", mcp_http_app)
app.include_router(auth_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(finance_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(wishlist_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(income_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(transfers_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(account_setup_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(category_rules_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(ai_analyst_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(recurring_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(quality_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(business_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(networth_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(asof_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(health_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(system_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(plan_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(tidy_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(paperless_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(search_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(attention_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(cashbook_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(receivables_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(contract_terms_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(report_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(receipts_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(device_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(device_public_router)  # bearer device key, no cookies -> no CSRF
app.include_router(insights_extra_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(forecast_router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(watch_router, prefix="/api", dependencies=[Depends(require_csrf)])

# OAuth routes have absolute root discovery and /api/mcp paths. Their module
# applies CSRF selectively: public OAuth exchanges must not inherit cookie CSRF.
app.include_router(mcp_auth_router)

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
