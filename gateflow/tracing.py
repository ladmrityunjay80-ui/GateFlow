from __future__ import annotations

import atexit
import contextlib
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger("gateflow.tracing")

_Provider = None
_Tracer = None


def shutdown_tracing() -> None:
    """Flush and stop OpenTelemetry tracing to avoid closed stream errors."""
    global _Provider
    if _Provider is not None:
        with contextlib.suppress(Exception):
            _Provider.shutdown()


def init_tracing(service_name: str = "gateflow") -> None:
    """Initialise OpenTelemetry tracing when the package is installed.

    Without OpenTelemetry, this is a no-op and the application continues to
    work normally.
    """
    global _Provider, _Tracer

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
    except ImportError as exc:
        logger.debug("opentelemetry_not_available", extra={"error": str(exc)})
        return

    resource = Resource(attributes={SERVICE_NAME: service_name})
    _Provider = TracerProvider(resource=resource)

    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        exporter: Any = OTLPSpanExporter(endpoint=otlp_endpoint)
    else:
        exporter = ConsoleSpanExporter()

    if otlp_endpoint:
        _Provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        _Provider.add_span_processor(SimpleSpanProcessor(exporter))
    atexit.register(shutdown_tracing)
    trace.set_tracer_provider(_Provider)
    _Tracer = trace.get_tracer(__name__)

    try:
        HTTPXClientInstrumentor().instrument()
    except Exception as exc:
        logger.warning("httpx_instrumentation_failed", extra={"error": str(exc)})


@contextmanager
def start_span(name: str, **attributes: Any) -> Iterator[Any]:
    """Open a span if OpenTelemetry is configured, else a no-op context."""
    if _Tracer is None:
        yield None
        return

    with _Tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None and span is not None:
                span.set_attribute(key, value)
        yield span
