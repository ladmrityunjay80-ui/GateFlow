from __future__ import annotations

import asyncio
import base64
import logging
import os
import sys
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urljoin

import httpx
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.requests import Request

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .auth import AuthError, authenticate, get_client_ip, resolve_rate_limits, verify_mtls
from .circuit_breaker import check_circuit, report_circuit
from .config import Settings, get_settings
from .governance import refund_monthly_quota, reserve_monthly_quota
from .idempotency import (
    idempotency_applies,
    lookup_idempotent_response,
    store_idempotent_response,
)
from .metrics import (
    CIRCUIT_OPENED,
    ERROR_COUNT,
    OVERHEAD_LATENCY,
    RATE_LIMITED,
    REQUEST_COUNT,
    REQUEST_LATENCY,
)
from .models import APIKeyRecord, Route, TierConfig
from .rate_limiter import RateLimitResult, check_rate_limit
from .router import build_downstream_path, match_route
from .store import increment_request_count
from .telemetry import fire_telemetry, get_request_id

logger = logging.getLogger("gateflow.proxy")

UNIFORM_ERROR_SCHEMA = {"error": str, "detail": str, "status_code": int}

# Reusable httpx clients keyed by downstream base URL.  A single client per
# target keeps long-lived HTTP/1.1 or HTTP/2 connections and avoids the cost
# of creating and tearing down a client on every request.
_HTTP_CLIENTS: dict[str, httpx.AsyncClient] = {}
_HTTP_CLIENTS_LOCK = asyncio.Lock()


async def close_clients() -> None:
    """Close all pooled downstream clients.  Called on application shutdown."""
    async with _HTTP_CLIENTS_LOCK:
        for client in _HTTP_CLIENTS.values():
            await client.aclose()
        _HTTP_CLIENTS.clear()


async def _get_client(service_url: str) -> httpx.AsyncClient:
    async with _HTTP_CLIENTS_LOCK:
        client = _HTTP_CLIENTS.get(service_url)
        if client is None:
            client = httpx.AsyncClient(
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )
            _HTTP_CLIENTS[service_url] = client
        return client


def _error_response(
    status_code: int,
    detail: str,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    route: Route | None = None,
) -> JSONResponse:
    route_label = route.prefix if route else "unknown"
    ERROR_COUNT.labels(route=route_label, status_code=str(status_code)).inc()
    logger.warning("gateway_error", extra={"status_code": status_code, "detail": detail, "route": route_label})
    body = {"error": _http_label(status_code), "detail": detail, "status_code": status_code}
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status_code, headers=headers)


def _http_label(status_code: int) -> str:
    labels = {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        429: "Too Many Requests",
        502: "Bad Gateway",
        504: "Gateway Timeout",
    }
    return labels.get(status_code, "Internal Server Error")


async def handle_request(request: Request) -> Response:
    start = time.perf_counter()
    settings = get_settings()

    try:
        verify_mtls(request)
    except AuthError as exc:
        return _error_response(exc.status_code, exc.detail, exc.extra)

    path = request.url.path
    method = request.method
    headers = dict(request.headers)
    request_id = get_request_id(headers)

    # Remove hop-by-hop headers that should not be forwarded.
    hop_by_hop = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-length",
    }
    for h in list(headers.keys()):
        if h.lower() in hop_by_hop:
            headers.pop(h)

    route = match_route(path)
    if route is None:
        return _error_response(404, "No route matches the request path", route=route)

    if not route.allows(method):
        return _error_response(405, f"Method {method} not allowed for this route", route=route)

    record: APIKeyRecord | None = None
    tier: TierConfig | None = None

    if route.requires_auth:
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            return _error_response(401, "Missing X-API-KEY header", route=route)
        try:
            record, tier, key_id = await authenticate(api_key, get_client_ip(request))
        except AuthError as exc:
            return _error_response(exc.status_code, exc.detail, exc.extra, route=route)

        capacity, refill_rate = resolve_rate_limits(record, tier)
        rate_key = route.prefix
        rate = await check_rate_limit(key_id, rate_key, capacity, refill_rate)
        if not rate.allowed:
            retry_after = max(1, int(rate.retry_after))
            RATE_LIMITED.labels(route=route.prefix).inc()
            return _error_response(
                429,
                "Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
                route=route,
            )

        settings = get_settings()
        if settings.global_rate_limit_enabled:
            global_rate = await check_rate_limit(
                "global",
                "__global__",
                settings.global_rate_limit_capacity,
                settings.global_rate_limit_refill_rate,
            )
            if not global_rate.allowed:
                retry_after = max(1, int(global_rate.retry_after))
                RATE_LIMITED.labels(route="global").inc()
                return _error_response(
                    429,
                    "Global rate limit exceeded",
                    headers={"Retry-After": str(retry_after)},
                    route=route,
                )

        if not await reserve_monthly_quota(record.user_id, tier.monthly_quota):
            RATE_LIMITED.labels(route=route.prefix).inc()
            return _error_response(429, "Monthly quota exceeded", route=route)
    else:
        api_key = request.headers.get("X-API-KEY", "anonymous")
        key_id = ""
        record = APIKeyRecord(
            user_id="anonymous",
            tier="anonymous",
            active=1,
            rate_limit_custom=-1,
        )
        tier = TierConfig(capacity=1000, refill_rate=1000.0, window_info="1s")
        rate = RateLimitResult(True, 1000.0)

    # Decide whether to stream or fully materialise the request body.
    # Streaming is only safe when there is no idempotency, no retries, no
    # fallback, and the client sent a Content-Length header we can trust.
    idempotency_key = request.headers.get("idempotency-key")
    use_idempotency = settings.idempotency_enabled and idempotency_applies(method, idempotency_key)
    content_length_header = request.headers.get("content-length")
    use_streaming = (
        not use_idempotency
        and settings.downstream_max_retries == 1
        and not route.fallback_url
        and content_length_header is not None
    )

    if use_streaming:
        try:
            content_length = int(content_length_header)
        except (ValueError, TypeError):
            return _error_response(400, "Invalid Content-Length header", route=route)
        if content_length < 0:
            return _error_response(400, "Invalid Content-Length header", route=route)
        if content_length > settings.max_request_body_bytes:
            return _error_response(413, f"Request body exceeds {settings.max_request_body_bytes} bytes", route=route)
        bytes_in = content_length
        body: bytes | AsyncIterator[bytes] = _request_stream(request)
    else:
        # Enforce max body size by reading the inbound payload fully.
        # The user scope is small structured API text; this keeps retry logic simple.
        body = await request.body()
        if len(body) > settings.max_request_body_bytes:
            return _error_response(413, f"Request body exceeds {settings.max_request_body_bytes} bytes", route=route)
        bytes_in = len(body)

    # Check idempotency cache for mutating requests before hitting downstream.
    if use_idempotency:
        cached = await lookup_idempotent_response(method, path, idempotency_key, body)
        if cached:
            return await _rebuild_idempotent_response(
                cached,
                request_id,
                rate,
                route,
                start=start,
                method=method,
                api_key=api_key,
                key_id=key_id,
                record=record,
                bytes_in=bytes_in,
            )

    downstream_path = build_downstream_path(route, path)
    primary_url = urljoin(route.target_url.rstrip("/") + "/", downstream_path.lstrip("/"))

    # Inject downstream context headers.
    headers["X-Request-ID"] = request_id
    headers["X-User-Id"] = record.user_id
    headers["X-User-Tier"] = record.tier

    gateway_ready = time.perf_counter()

    primary_resp = None
    primary_client = None
    use_primary = False
    for attempt in range(settings.downstream_max_retries):
        primary_resp, primary_client, use_primary = await _try_target(
            method,
            route.target_url,
            primary_url,
            headers,
            body,
            settings.downstream_timeout_seconds,
            report_circuit_state=attempt == settings.downstream_max_retries - 1,
        )
        if use_primary:
            break
        if primary_resp:
            await primary_resp.aclose()
            primary_resp = None
        if attempt < settings.downstream_max_retries - 1:
            await asyncio.sleep(settings.downstream_retry_base_seconds * (2**attempt))

    if not use_primary and route.fallback_url:
        if primary_resp:
            await primary_resp.aclose()
        fallback_url = urljoin(route.fallback_url.rstrip("/") + "/", downstream_path.lstrip("/"))
        fallback_resp, fallback_client, _ = await _try_target(
            method,
            route.fallback_url,
            fallback_url,
            headers,
            body,
            settings.downstream_timeout_seconds,
            is_fallback=True,
        )
        if fallback_resp and fallback_client:
            return await _build_response(
                fallback_resp,
                fallback_client,
                request_id,
                method,
                route,
                rate,
                overhead_ms=(gateway_ready - start) * 1000.0,
                api_key=api_key,
                key_id=key_id,
                record=record,
                bytes_in=bytes_in,
                start=start,
                path=path,
                idempotency_key=idempotency_key,
                body=body,
                settings=settings,
            )
        if route.requires_auth and record:
            await refund_monthly_quota(record.user_id)
        return _error_response(504, f"Downstream service unavailable for route {route.prefix}", route=route)

    if primary_resp and primary_client:
        return await _build_response(
            primary_resp,
            primary_client,
            request_id,
            method,
            route,
            rate,
            overhead_ms=(gateway_ready - start) * 1000.0,
            api_key=api_key,
            key_id=key_id,
            record=record,
            bytes_in=bytes_in,
            start=start,
            path=path,
            idempotency_key=idempotency_key,
            body=body,
            settings=settings,
        )

    if route.requires_auth and record:
        await refund_monthly_quota(record.user_id)
    return _error_response(504, f"Downstream service unreachable for route {route.prefix}", route=route)


async def _request_stream(request: Request) -> AsyncIterator[bytes]:
    """Yield request body chunks without materialising the full payload."""
    async for chunk in request.stream():
        yield chunk


async def _try_target(
    method: str,
    service_url: str,
    request_url: str,
    headers: dict[str, str],
    body: bytes | AsyncIterator[bytes],
    timeout: float,
    is_fallback: bool = False,
    report_circuit_state: bool = True,
) -> tuple[httpx.Response | None, httpx.AsyncClient | None, bool]:
    if not is_fallback:
        state = await check_circuit(service_url)
        if state.state == "OPEN":
            CIRCUIT_OPENED.labels(target=service_url).inc()
            return None, None, False

    http_client = await _get_client(service_url)
    try:
        request = http_client.build_request(
            method,
            request_url,
            headers=headers,
            content=body,
            timeout=timeout,
        )
        response = await http_client.send(request, stream=True, follow_redirects=False)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError):
        if not is_fallback and report_circuit_state:
            await report_circuit(service_url, success=False)
        return None, None, False

    if not is_fallback and report_circuit_state:
        if response.status_code >= 500:
            await report_circuit(service_url, success=False)
            return response, http_client, False
        await report_circuit(service_url, success=True)

    return response, http_client, response.status_code < 500


async def _rebuild_idempotent_response(
    cached: dict,
    request_id: str,
    rate: RateLimitResult,
    route: Route,
    start: float,
    method: str,
    api_key: str,
    key_id: str,
    record: APIKeyRecord | None,
    bytes_in: int,
) -> Response:
    gateway_end = time.perf_counter()
    total_ms = (gateway_end - start) * 1000.0
    overhead_ms = 0.0

    response_headers = dict(cached.get("headers", {}))
    response_headers.pop("content-length", None)
    response_headers.pop("transfer-encoding", None)
    response_headers["X-Request-ID"] = request_id
    response_headers["X-Gateway-Overhead-MS"] = f"{overhead_ms:.3f}"
    response_headers["X-Response-Time-MS"] = f"{total_ms:.3f}"
    if not route.requires_auth or rate.allowed:
        response_headers["X-RateLimit-Remaining"] = str(int(rate.remaining))

    body = base64.b64decode(cached.get("body", ""))

    if record and route.requires_auth:
        await increment_request_count(key_id)

    REQUEST_COUNT.labels(
        route=route.prefix,
        method=method,
        status_code=str(cached["status_code"]),
    ).inc()
    REQUEST_LATENCY.labels(route=route.prefix).observe(total_ms / 1000.0)
    OVERHEAD_LATENCY.labels(route=route.prefix).observe(overhead_ms / 1000.0)

    if record and route.requires_auth:
        fire_telemetry(
            request_id,
            api_key,
            key_id,
            record.user_id,
            route.prefix,
            overhead_ms,
            cached["status_code"],
            bytes_in,
            len(body),
        )

    return Response(
        content=body,
        status_code=cached["status_code"],
        headers=response_headers,
        media_type=response_headers.get("content-type"),
    )


async def _build_response(
    response: httpx.Response,
    http_client: httpx.AsyncClient,
    request_id: str,
    method: str,
    route: Route,
    rate: RateLimitResult,
    overhead_ms: float,
    api_key: str,
    key_id: str,
    record: APIKeyRecord | None,
    bytes_in: int,
    start: float,
    path: str,
    idempotency_key: str | None,
    body: bytes,
    settings: Settings,
) -> Response:
    gateway_end = time.perf_counter()
    total_ms = (gateway_end - start) * 1000.0

    if record and route.requires_auth:
        await increment_request_count(key_id)

    response_headers = dict(response.headers)
    response_headers.pop("content-length", None)
    response_headers.pop("transfer-encoding", None)

    response_headers["X-Request-ID"] = request_id
    response_headers["X-Gateway-Overhead-MS"] = f"{overhead_ms:.3f}"
    response_headers["X-Response-Time-MS"] = f"{total_ms:.3f}"
    if not route.requires_auth or rate.allowed:
        response_headers["X-RateLimit-Remaining"] = str(int(rate.remaining))

    REQUEST_COUNT.labels(
        route=route.prefix,
        method=method,
        status_code=str(response.status_code),
    ).inc()
    REQUEST_LATENCY.labels(route=route.prefix).observe(total_ms / 1000.0)
    OVERHEAD_LATENCY.labels(route=route.prefix).observe(overhead_ms / 1000.0)

    if record and route.requires_auth and response.status_code >= 500:
        await refund_monthly_quota(record.user_id)

    logger.info(
        "proxy_response",
        extra={
            "request_id": request_id,
            "route": route.prefix,
            "method": method,
            "status_code": response.status_code,
            "overhead_ms": overhead_ms,
            "total_ms": total_ms,
        },
    )

    if settings.idempotency_enabled and idempotency_applies(method, idempotency_key):
        response_body = await response.aread()
        await response.aclose()

        if 200 <= response.status_code < 300 and len(response_body) <= settings.idempotency_max_body_bytes:
            await store_idempotent_response(
                method,
                path,
                idempotency_key,
                body,
                response.status_code,
                response_headers,
                response_body,
                settings.idempotency_ttl,
            )

        if record and route.requires_auth:
            fire_telemetry(
                request_id,
                api_key,
                key_id,
                record.user_id,
                route.prefix,
                overhead_ms,
                response.status_code,
                bytes_in,
                len(response_body),
            )

        return Response(
            content=response_body,
            status_code=response.status_code,
            headers=response_headers,
            media_type=response.headers.get("content-type"),
        )

    async def stream_body():
        bytes_out = 0
        try:
            async for chunk in response.aiter_raw():
                bytes_out += len(chunk)
                yield chunk
        finally:
            await response.aclose()
            if record and route.requires_auth:
                fire_telemetry(
                    request_id,
                    api_key,
                    key_id,
                    record.user_id,
                    route.prefix,
                    overhead_ms,
                    response.status_code,
                    bytes_in,
                    bytes_out,
                )

    return StreamingResponse(
        content=stream_body(),
        status_code=response.status_code,
        headers=response_headers,
        media_type=response.headers.get("content-type"),
    )
