from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from . import portal
from .admin import keys, routes, tiers
from .audit import flush_audit
from .auth import AuthError
from .config import Settings, get_settings
from .db import close_db, init_db
from .logging_config import setup_logging
from .metrics import metrics_response
from .metrics_worker import consume_audit, consume_metrics
from .middleware import ProxyMiddleware
from .notifications import consume_anomalies
from .openapi import build_merged_openapi
from .proxy import close_clients
from .redis_client import RedisManager
from .telemetry import flush_telemetry
from .tracing import init_tracing

logger = logging.getLogger("gateflow.main")

setup_logging()


def _validate_secrets(settings: Settings) -> None:
    """Refuse to start if any critical secret still has a default or empty value."""
    checks = {
        "admin_key": (settings.admin_key, Settings.model_fields["admin_key"].default),
        "key_secret": (settings.key_secret, Settings.model_fields["key_secret"].default),
    }
    for name, (value, default) in checks.items():
        if not value or value == default:
            raise RuntimeError(
                f"GATEFLOW_{name.upper()} is not set or still uses the default value. "
                "Change it before running in production."
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await RedisManager.connect()
    metrics_worker = asyncio.create_task(consume_metrics())
    audit_worker = asyncio.create_task(consume_audit())
    notification_worker = asyncio.create_task(consume_anomalies())
    try:
        yield
    finally:
        for task in (metrics_worker, audit_worker, notification_worker):
            task.cancel()
        for task in (metrics_worker, audit_worker, notification_worker):
            with suppress(asyncio.CancelledError):
                await task
        await flush_telemetry()
        await flush_audit()
        await close_clients()
        await RedisManager.close()
        await close_db()


def create_app() -> FastAPI:
    settings = get_settings()
    _validate_secrets(settings)
    init_tracing()

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi/admin.json",
    )

    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
            if settings.forwarded_allow_ips:
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            return response

    app.add_middleware(SecurityHeadersMiddleware)

    @app.exception_handler(AuthError)
    async def auth_error_handler(request, exc: AuthError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, **exc.extra})

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except ImportError:
        pass

    app.include_router(routes.router, prefix="/api/admin")
    app.include_router(keys.router, prefix="/api/admin")
    app.include_router(tiers.router, prefix="/api/admin")
    app.include_router(portal.router)

    if settings.cors_origins:
        allow_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
        allow_credentials = "*" not in allow_origins
        if not allow_credentials:
            logger.warning("cors_wildcard_origin_cannot_use_credentials")
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_credentials=allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "healthy", "app": settings.app_name}

    @app.get("/ready")
    async def ready() -> dict:
        redis_ok = await _redis_ready()
        downstream_ok = await _downstream_ready()
        overall = redis_ok and (not settings.ready_downstream_required or downstream_ok)
        return {
            "status": "ready" if overall else "not_ready",
            "redis": redis_ok,
            "downstream": downstream_ok,
        }

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return metrics_response()

    @app.get("/openapi.json", include_in_schema=False)
    async def openapi_json() -> JSONResponse:
        spec = await build_merged_openapi()
        return JSONResponse(spec)

    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    app.add_middleware(ProxyMiddleware)
    return app


async def _redis_ready() -> bool:
    try:
        await RedisManager.client().ping()
        return True
    except Exception:
        return False


_DOWNSTREAM_CACHE: dict[str, bool] = {}
_DOWNSTREAM_CACHE_AT = 0.0


async def _downstream_ready() -> bool:
    settings = get_settings()
    if not settings.ready_downstream_probe:
        return True

    global _DOWNSTREAM_CACHE, _DOWNSTREAM_CACHE_AT
    now = time.monotonic()
    if _DOWNSTREAM_CACHE and now - _DOWNSTREAM_CACHE_AT < 5.0:
        return any(_DOWNSTREAM_CACHE.values())

    routes = RedisManager.routes().values()
    if not routes:
        return True

    client = httpx.AsyncClient(timeout=settings.ready_downstream_timeout)
    try:
        results: dict[str, bool] = {}
        for route in routes:
            url = route.target_url.rstrip("/") + "/"
            try:
                response = await client.get(url, follow_redirects=False)
                results[route.prefix] = response.status_code < 400
            except Exception:
                results[route.prefix] = False
        _DOWNSTREAM_CACHE = results
        _DOWNSTREAM_CACHE_AT = now
        return any(results.values())
    finally:
        await client.aclose()


app = create_app()
