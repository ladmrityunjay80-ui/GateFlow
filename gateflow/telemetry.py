from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .constants import RedisKeys
from .redis_client import RedisManager
from .store import record_usage

logger = logging.getLogger("gateflow.telemetry")

# Batched, bounded queue for telemetry writes. A single worker per process
# avoids the per-request task overhead and memory growth at high RPS.
_telemetry_queue: asyncio.Queue | None = None
_telemetry_worker: asyncio.Task | None = None

_TELEMETRY_BATCH_SIZE = int(os.environ.get("GATEFLOW_TELEMETRY_BATCH_SIZE", "50"))


def get_request_id(request_headers: dict[str, str]) -> str:
    return request_headers.get("X-Request-ID") or str(uuid.uuid4())


def _ensure_worker() -> asyncio.Queue:
    """Start the telemetry batch worker if it is not already running."""
    global _telemetry_queue, _telemetry_worker
    if _telemetry_queue is None or (_telemetry_worker and _telemetry_worker.done()):
        _telemetry_queue = asyncio.Queue(maxsize=10000)
        _telemetry_worker = asyncio.create_task(_telemetry_worker_loop())
    return _telemetry_queue


def fire_telemetry(
    request_id: str,
    api_key: str,
    key_id: str,
    user_id: str,
    route: str,
    duration_ms: float,
    status_code: int,
    bytes_in: int,
    bytes_out: int,
) -> None:
    # Mask the API key to last 4 characters for the stream.
    masked_key = f"***{api_key[-4:]}" if len(api_key) >= 4 else "****"
    payload = {
        "request_id": request_id,
        "api_key": masked_key,
        "user_id": user_id,
        "route": route,
        "duration_ms": str(duration_ms),
        "status_code": str(status_code),
        "bytes_in": str(bytes_in),
        "bytes_out": str(bytes_out),
    }

    queue = _ensure_worker()
    try:
        queue.put_nowait((payload, api_key, key_id))
    except asyncio.QueueFull:
        logger.warning("telemetry_queue_full", extra={"request_id": request_id})


async def flush_telemetry() -> None:
    """Stop the worker and drain any remaining telemetry before shutdown."""
    global _telemetry_queue, _telemetry_worker
    if _telemetry_worker:
        _telemetry_worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _telemetry_worker
        _telemetry_worker = None
    if _telemetry_queue:
        while not _telemetry_queue.empty():
            payload, api_key, key_id = _telemetry_queue.get_nowait()
            await _push_telemetry(payload, api_key, key_id)
        _telemetry_queue = None


async def _telemetry_worker_loop() -> None:
    """Collect telemetry into batches and write them via a Redis pipeline."""
    while True:
        try:
            first_payload, first_api_key, first_key_id = await _telemetry_queue.get()
            batch = [(first_payload, first_api_key, first_key_id)]
            while True:
                try:
                    payload, api_key, key_id = _telemetry_queue.get_nowait()
                    batch.append((payload, api_key, key_id))
                except asyncio.QueueEmpty:
                    break
            await _flush_telemetry_batch(batch)
        except asyncio.CancelledError:
            while not _telemetry_queue.empty():
                batch = []
                while not _telemetry_queue.empty():
                    payload, api_key, key_id = _telemetry_queue.get_nowait()
                    batch.append((payload, api_key, key_id))
                await _flush_telemetry_batch(batch)
            raise


async def _flush_telemetry_batch(batch: list[tuple[dict[str, Any], str, str]]) -> None:
    if not batch:
        return
    try:
        client = RedisManager.client()
    except RuntimeError as exc:
        # Redis client may be closed during shutdown; best-effort drop.
        logger.warning("telemetry_batch_no_client", extra={"batch_size": len(batch), "error": str(exc)})
        return

    today = datetime.now(UTC).date()
    try:
        async with client.pipeline() as pipe:
            for payload, _api_key, _key_id in batch:
                pipe.xadd(RedisKeys.METRICS_STREAM, payload, maxlen=10000, approximate=True)
            await pipe.execute()

        for payload, _api_key, _key_id in batch:
            try:
                await record_usage(
                    user_id=payload["user_id"],
                    route=payload["route"],
                    day=today,
                    bytes_in=int(payload["bytes_in"]),
                    bytes_out=int(payload["bytes_out"]),
                )
            except Exception as exc:
                logger.debug("record_usage_failed", extra={"error": str(exc)})
    except Exception as exc:
        logger.warning("telemetry_batch_push_failed", extra={"error": str(exc), "batch_size": len(batch)})


async def _push_telemetry(payload: dict[str, Any], api_key: str, key_id: str) -> None:
    """Write a single telemetry payload (used for final drain)."""
    await _flush_telemetry_batch([(payload, api_key, key_id)])
