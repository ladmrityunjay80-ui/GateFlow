from __future__ import annotations

import os
import sys

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .constants import RedisKeys
from .redis_client import RedisManager


class RateLimitResult:
    __slots__ = ("allowed", "remaining", "retry_after")

    def __init__(self, allowed: bool, remaining: float, retry_after: float = 0.0):
        self.allowed = allowed
        self.remaining = remaining
        self.retry_after = retry_after


async def check_rate_limit(
    key_id: str,
    route: str,
    capacity: int,
    refill_rate: float,
    cost: int = 1,
) -> RateLimitResult:
    client = RedisManager.client()
    sha = RedisManager.scripts().get("token_bucket")
    if not sha:
        raise RuntimeError("Token bucket Lua script not loaded")

    key = f"{RedisKeys.RATE_LIMIT_PREFIX}{key_id}:{route}"
    result = await client.evalsha(sha, 1, key, capacity, refill_rate, cost)
    allowed = int(result[0]) == 1
    remaining = float(result[1])
    retry_after = float(result[2])
    return RateLimitResult(allowed, remaining, retry_after)
