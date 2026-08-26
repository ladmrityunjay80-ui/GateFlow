from __future__ import annotations

from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUEST_COUNT = Counter(
    "gateflow_requests_total",
    "Total proxied requests",
    ["route", "method", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "gateflow_request_duration_seconds",
    "End-to-end response time",
    ["route"],
    buckets=[0.001, 0.002, 0.005, 0.010, 0.025, 0.050, 0.100, 0.250, 0.500, 1.0, 2.5, 5.0],
)

OVERHEAD_LATENCY = Histogram(
    "gateflow_gateway_overhead_seconds",
    "Gateway internal processing time",
    ["route"],
    buckets=[0.0001, 0.0005, 0.001, 0.002, 0.005, 0.010, 0.025, 0.050],
)

RATE_LIMITED = Counter(
    "gateflow_rate_limited_total",
    "Requests rejected by rate limiter",
    ["route"],
)

CIRCUIT_OPENED = Counter(
    "gateflow_circuit_opened_total",
    "Circuit breaker opened",
    ["target"],
)

ERROR_COUNT = Counter(
    "gateflow_errors_total",
    "Gateway-generated error responses",
    ["route", "status_code"],
)


def metrics_response() -> Response:
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
