from __future__ import annotations

import logging
import os
import sys
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .proxy import handle_request

logger = logging.getLogger("gateflow.middleware")

# Paths handled by the FastAPI app rather than the proxy.
LOCAL_PATHS = {
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/ready",
    "/metrics",
    "/portal",
}


class ProxyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path.startswith(("/api/admin", "/api/me", "/static")) or path in LOCAL_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        response: Response | None = None
        try:
            response = await handle_request(request)
        except Exception as exc:
            logger.error(
                "unhandled_request_error",
                extra={"path": path, "method": request.method, "error": str(exc)},
                exc_info=True,
            )
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            logger.info(
                "request",
                extra={
                    "path": path,
                    "method": request.method,
                    "status_code": getattr(response, "status_code", 0),
                    "elapsed_ms": elapsed_ms,
                },
            )
        return response
