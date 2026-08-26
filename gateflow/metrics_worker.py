from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import sys
from typing import cast

import redis

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .anomaly import AnomalyDetector
from .config import get_settings
from .constants import RedisKeys
from .ml_anomaly import MLAnomalyDetector
from .redis_client import RedisManager

logger = logging.getLogger("gateflow.metrics_worker")

CONSUMER_GROUP = "gateflow-workers"
CONSUMER_NAME = os.environ.get(
    "GATEFLOW_CONSUMER_NAME",
    f"{socket.gethostname()}-{os.getpid()}",
)

_anomaly_detector = AnomalyDetector()
_ml_anomaly_detector: MLAnomalyDetector | None = None


def _get_ml_anomaly_detector() -> MLAnomalyDetector:
    """Return the shared ML detector, creating it lazily from settings."""
    global _ml_anomaly_detector
    if _ml_anomaly_detector is None:
        settings = get_settings()
        _ml_anomaly_detector = MLAnomalyDetector(
            window_size=settings.ml_anomaly_window_size,
            threshold=settings.ml_anomaly_threshold,
        )
    return _ml_anomaly_detector


async def _ensure_consumer_group(client, stream: str) -> None:
    try:
        await client.xgroup_create(stream, CONSUMER_GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "already exists" not in str(exc).lower():
            raise


async def consume_stream(
    stream: str,
    block_ms: int = 5000,
    count: int = 100,
) -> None:
    """Consume a Redis stream using a consumer group and acknowledge entries.

    This gives at-least-once delivery semantics and supports graceful failover
    between multiple Gateway instances.
    """
    client = RedisManager.client()
    await _ensure_consumer_group(client, stream)

    while True:
        try:
            # First, drain pending entries for this consumer on recovery.
            pending = await client.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {stream: "0"},
                count=count,
            )
            new_entries = await client.xreadgroup(
                CONSUMER_GROUP,
                CONSUMER_NAME,
                {stream: ">"},
                count=count,
                block=block_ms,
            )

            entries: list = []
            for _stream, messages in cast(list, pending):
                entries.extend(messages)
            for _stream, messages in cast(list, new_entries):
                entries.extend(messages)

            for message_id, fields in entries:
                logger.info(
                    f"{stream}_event",
                    extra={"stream": stream, "event_id": message_id, "event": fields},
                )
                if stream == RedisKeys.METRICS_STREAM:
                    anomalies = _anomaly_detector.check(fields)
                    settings = get_settings()
                    if settings.ml_anomaly_enabled:
                        try:
                            duration_ms = float(fields.get("duration_ms", 0))
                            ml_result = _get_ml_anomaly_detector().update(duration_ms)
                            if ml_result["is_anomaly"]:
                                anomalies.append({
                                    "type": "ml_outlier",
                                    "route": fields.get("route", ""),
                                    "api_key": fields.get("api_key", ""),
                                    "value": duration_ms,
                                    "z_score": ml_result.get("z_score", 0.0),
                                    "mean": ml_result.get("mean", 0.0),
                                    "std": ml_result.get("std", 0.0),
                                })
                        except (ValueError, TypeError) as exc:
                            logger.warning("ml_anomaly_parse_error", extra={"error": str(exc)})
                    for anomaly in anomalies:
                        await client.xadd(
                            RedisKeys.ANOMALIES_STREAM,
                            {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in anomaly.items()},
                            maxlen=10000,
                            approximate=True,
                        )
                await client.xack(stream, CONSUMER_GROUP, message_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"{stream}_worker_error", extra={"error": str(exc)})
            await asyncio.sleep(1.0)


async def consume_metrics() -> None:
    await consume_stream(RedisKeys.METRICS_STREAM)


async def consume_audit() -> None:
    await consume_stream(RedisKeys.AUDIT_ADMIN_STREAM)
