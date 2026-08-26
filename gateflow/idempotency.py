from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sys
import time
from typing import Any

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .constants import RedisKeys
from .redis_client import RedisManager

logger = logging.getLogger("gateflow.idempotency")

IDEMPOTENCY_PREFIX = RedisKeys.IDEMPOTENCY_PREFIX
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _fingerprint(method: str, path: str, idempotency_key: str, body: bytes) -> str:
    raw = f"{method}:{path}:{idempotency_key}:{body.hex()}".encode()
    return hashlib.sha256(raw).hexdigest()


def idempotency_applies(method: str, idempotency_key: str | None) -> bool:
    return method.upper() in MUTATING_METHODS and idempotency_key is not None and idempotency_key != ""


async def lookup_idempotent_response(
    method: str,
    path: str,
    idempotency_key: str,
    body: bytes,
) -> dict[str, Any] | None:
    client = RedisManager.client()
    key = f"{IDEMPOTENCY_PREFIX}{_fingerprint(method, path, idempotency_key, body)}"
    raw = await client.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        await client.delete(key)
        return None


async def store_idempotent_response(
    method: str,
    path: str,
    idempotency_key: str,
    body: bytes,
    status_code: int,
    response_headers: dict[str, str],
    response_body: bytes,
    ttl: int,
) -> None:
    client = RedisManager.client()
    key = f"{IDEMPOTENCY_PREFIX}{_fingerprint(method, path, idempotency_key, body)}"
    payload = {
        "status_code": status_code,
        "headers": response_headers,
        "body": base64.b64encode(response_body).decode(),
        "created_at": time.time(),
    }
    await client.set(key, json.dumps(payload), ex=ttl)
