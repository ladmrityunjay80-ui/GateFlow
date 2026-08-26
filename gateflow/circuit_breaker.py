from __future__ import annotations

import hashlib
import os
import sys

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .config import get_settings
from .constants import RedisKeys
from .redis_client import RedisManager


class CircuitState:
    __slots__ = ("state", "retry_after")

    def __init__(self, state: str, retry_after: float = 0.0):
        self.state = state
        self.retry_after = retry_after


def _cb_key(target_url: str) -> str:
    hashed = hashlib.sha256(target_url.encode()).hexdigest()
    return f"{RedisKeys.CIRCUIT_PREFIX}{hashed}"


async def check_circuit(target_url: str) -> CircuitState:
    client = RedisManager.client()
    sha = RedisManager.scripts().get("circuit_breaker")
    if not sha:
        raise RuntimeError("Circuit breaker Lua script not loaded")

    settings = get_settings()
    key = _cb_key(target_url)
    result = await client.evalsha(
        sha,
        1,
        key,
        "check",
        "",
        settings.circuit_breaker_threshold,
        settings.circuit_breaker_window_seconds,
        settings.circuit_breaker_open_duration,
    )
    return CircuitState(result[0], float(result[1]) if len(result) > 1 else 0.0)


async def report_circuit(target_url: str, success: bool) -> str:
    client = RedisManager.client()
    sha = RedisManager.scripts().get("circuit_breaker")
    if not sha:
        raise RuntimeError("Circuit breaker Lua script not loaded")

    settings = get_settings()
    key = _cb_key(target_url)
    result = await client.evalsha(
        sha,
        1,
        key,
        "report",
        "success" if success else "failure",
        settings.circuit_breaker_threshold,
        settings.circuit_breaker_window_seconds,
        settings.circuit_breaker_open_duration,
    )
    return result[0]
