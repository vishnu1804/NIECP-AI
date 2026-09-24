"""
NIECP-AI FastAPI application.

Startup sequence: create tables if absent → seed reference data → mount routers
→ serve the built frontend. Production deployment should run Alembic migrations
explicitly (`alembic upgrade head`) — create_all is the local convenience path.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .database import init_models
from .routers import (
    admin,
    applications,
    assistant,
    auth,
    compliance,
    demo_government,
    documents,
    govconnect,
    govdata,
    msme,
    projects,
    pwa,
    system,
)

log = logging.getLogger("niecp.main")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from .database import engine
    from .services.seed import needs_seeding, run_seed
    from .database import SessionLocal

    for attempt in range(10):
        try:
            init_models()
            break
        except Exception as exc:  # pragma: no cover
            log.warning("database not ready (attempt %s): %s", attempt + 1, exc)
            time.sleep(2)
    try:
        db = SessionLocal()
        try:
            if needs_seeding(db):
                counts = run_seed(db)
                log.info("seeded reference data: %s", counts)
            from .services.gov_manager import sync_registry

            registry_n = sync_registry(db)
            if registry_n:
                log.info("government integration registry synced: %s providers", registry_n)
        finally:
            db.close()
    except Exception:
        log.exception("seeding failed — API still starts, reference data can be seeded via /api/v1/admin/seed")
    log.info("NIECP-AI %s ready (env=%s db=%s)", settings.version, settings.environment, engine.dialect.name)
    yield


app = FastAPI(
    title=settings.app_name,
    description=settings.app_long_name,
    version=settings.version,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redirect_slashes=False,
)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-NIECP-SW-Version"],
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        response = await call_next(request)
        response.headers.setdefault("X-Request-ID", request.state.request_id)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "microphone=(self), camera=(), geolocation=()")
        if settings.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple fixed-window limiter per client IP (spec §39). Good enough for a
    single-node deployment; use a shared store (e.g. Redis) when clustering."""

    def __init__(self, app: FastAPI) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._buckets: dict[str, tuple[int, float]] = {}

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path.startswith("/api/"):
            ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")
            now = time.time()
            count, window_start = self._buckets.get(ip, (0, now))
            if now - window_start > 60:
                count, window_start = 0, now
            count += 1
            self._buckets[ip] = (count, window_start)
            if len(self._buckets) > 5000:  # bound memory
                cutoff = now - 120
                self._buckets = {k: v for k, v in self._buckets.items() if v[1] > cutoff}
            if count > settings.rate_limit_per_minute:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please slow down."},
                    headers={"Retry-After": "30"},
                )
        return await call_next(request)


app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our side. Your saved data is safe. Please retry — if it persists, note the request ID."},
    )


API = settings.api_prefix
app.include_router(system.router, prefix=API)
app.include_router(auth.router, prefix=API)
app.include_router(projects.router, prefix=API)
app.include_router(documents.router, prefix=API)
app.include_router(applications.router, prefix=API)
app.include_router(compliance.router, prefix=API)
app.include_router(govdata.router, prefix=API)
app.include_router(govconnect.router, prefix=API)
app.include_router(msme.router, prefix=API)
app.include_router(demo_government.router, prefix=API)
app.include_router(assistant.router, prefix=API)
app.include_router(admin.router, prefix=API)
app.include_router(pwa.router, prefix=API)


@app.post(API + "/admin/seed")
def admin_seed(force: bool = False) -> dict[str, object]:
    """Operator endpoint: seed/refresh reference catalogues (idempotent)."""
    from .database import SessionLocal
    from .services.portal_seed import seed_reference_data

    db = SessionLocal()
    try:
        counts = seed_reference_data(db)
        return {"ok": True, "counts": counts}
    finally:
        db.close()


# ────────────────────────────────────────────── frontend (built SPA) ──
# Built by `vite build` into frontend/static (see frontend/vite.config.ts).
# app/main.py → backend/app → backend → niecp-ai/frontend/static
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "static"
if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")
    for icon_dir in ("icons",):
        if (FRONTEND_DIST / icon_dir).is_dir():
            app.mount(f"/{icon_dir}", StaticFiles(directory=str(FRONTEND_DIST / icon_dir)), name=icon_dir)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file() and ".." not in full_path:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
