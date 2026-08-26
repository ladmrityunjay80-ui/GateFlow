from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import sys
import time
from typing import Any

import httpx

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .config import get_settings
from .constants import RedisKeys
from .redis_client import RedisManager

logger = logging.getLogger("gateflow.notifications")

ANOMALY_STREAM = RedisKeys.ANOMALIES_STREAM
NOTIFICATION_CONSUMER_GROUP = RedisKeys.NOTIFICATION_CONSUMER_GROUP
DEAD_LETTER_STREAM = RedisKeys.ANOMALIES_DEAD_LETTER
MAX_RETRIES = 3
RETRY_BASE_SECONDS = 1.0


def _consumer_name() -> str:
    import socket

    return os.environ.get("GATEFLOW_CONSUMER_NAME", f"{socket.gethostname()}-{os.getpid()}")


async def _ensure_consumer_group(client, stream: str) -> None:
    import redis

    try:
        await client.xgroup_create(stream, NOTIFICATION_CONSUMER_GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "already exists" not in str(exc).lower():
            raise


def _webhook_targets() -> list[str]:
    """Return the list of configured webhook URLs."""
    settings = get_settings()
    return [u.strip() for u in (settings.notification_webhook_url or "").split(",") if u.strip()]


def _sign_payload(payload: dict[str, Any]) -> str | None:
    """Compute a base64 HMAC-SHA256 signature for the payload if a secret is set."""
    settings = get_settings()
    secret = settings.webhook_signing_secret
    if not secret:
        return None
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


async def _send_webhook(url: str, payload: dict[str, Any]) -> None:
    headers = {"User-Agent": "GateFlow/1.0"}
    signature = _sign_payload(payload)
    if signature:
        headers["X-GateFlow-Signature"] = f"sha256={signature}"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
    except Exception as exc:
        logger.warning("notification_webhook_failed", extra={"url": url, "error": str(exc)})
        raise


async def _send_webhook_with_retry(payload: dict[str, Any]) -> None:
    """Attempt delivery to every configured webhook with exponential backoff."""
    targets = _webhook_targets()
    if not targets:
        logger.info("anomaly_notification", extra=payload)
        return

    errors: list[str] = []
    for url in targets:
        for attempt in range(MAX_RETRIES):
            try:
                await _send_webhook(url, payload)
                break
            except Exception as exc:
                if attempt == MAX_RETRIES - 1:
                    errors.append(f"{url}: {exc}")
                else:
                    await asyncio.sleep(RETRY_BASE_SECONDS * (2**attempt))

    if errors:
        raise Exception("; ".join(errors))


async def _write_dead_letter(client, payload: dict[str, Any], error: str) -> None:
    """Persist an undeliverable notification to a bounded dead-letter stream."""
    fields = dict(payload)
    fields["error"] = error
    fields["retries"] = str(MAX_RETRIES)
    fields["dead_lettered_at"] = str(int(time.time()))
    await client.xadd(DEAD_LETTER_STREAM, fields, maxlen=10000, approximate=True)


async def consume_anomalies(
    block_ms: int = 5000,
    count: int = 100,
) -> None:
    """Consume the anomaly stream and dispatch notifications.

    This gives the same consumer-group semantics as the metrics/audit workers,
    allowing multiple Gateway instances to share notification delivery.
    """
    settings = get_settings()
    if not settings.notification_worker_enabled:
        return

    client = RedisManager.client()
    await _ensure_consumer_group(client, ANOMALY_STREAM)
    consumer_name = _consumer_name()

    while True:
        try:
            pending = await client.xreadgroup(
                NOTIFICATION_CONSUMER_GROUP,
                consumer_name,
                {ANOMALY_STREAM: "0"},
                count=count,
            )
            new_entries = await client.xreadgroup(
                NOTIFICATION_CONSUMER_GROUP,
                consumer_name,
                {ANOMALY_STREAM: ">"},
                count=count,
                block=block_ms,
            )

            from typing import cast

            entries: list = []
            for _stream, messages in cast(list, pending):
                entries.extend(messages)
            for _stream, messages in cast(list, new_entries):
                entries.extend(messages)

            for message_id, fields in entries:
                try:
                    await _send_webhook_with_retry(fields)
                except Exception as exc:
                    logger.error("notification_delivery_failed", extra={"error": str(exc)})
                    await _write_dead_letter(client, fields, str(exc))
                await client.xack(ANOMALY_STREAM, NOTIFICATION_CONSUMER_GROUP, message_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("notification_worker_error", extra={"error": str(exc)})
            await asyncio.sleep(1.0)
