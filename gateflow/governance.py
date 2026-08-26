from __future__ import annotations

import calendar
import logging
import os
import sys
from datetime import UTC, datetime

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .constants import RedisKeys
from .redis_client import RedisManager

logger = logging.getLogger("gateflow.governance")

MONTHLY_PREFIX = RedisKeys.MONTHLY_PREFIX


def _month_key(user_id: str, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return f"{MONTHLY_PREFIX}{user_id}:{now.strftime('%Y-%m')}"


def _seconds_until_month_end(now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    last_day = calendar.monthrange(now.year, now.month)[1]
    end = now.replace(day=last_day, hour=23, minute=59, second=59, microsecond=0)
    if now > end:
        return 1
    return int((end - now).total_seconds())


async def get_monthly_usage(user_id: str) -> int:
    client = RedisManager.client()
    raw = await client.get(_month_key(user_id))
    return int(raw or 0)


async def reserve_monthly_quota(user_id: str, monthly_quota: int) -> bool:
    """Atomically reserve one unit of monthly quota.

    Returns True if the reservation succeeded, False if the quota is exhausted.
    """
    if monthly_quota <= 0:
        return True
    client = RedisManager.client()
    sha = RedisManager.scripts().get("monthly_quota_reserve")
    if not sha:
        raise RuntimeError("Monthly quota reserve Lua script not loaded")
    key = _month_key(user_id)
    ttl = _seconds_until_month_end()
    result = await client.evalsha(sha, 1, key, monthly_quota, ttl)
    return int(result[0]) == 1


async def refund_monthly_quota(user_id: str) -> None:
    """Refund one unit of monthly quota after a failed downstream request."""
    client = RedisManager.client()
    sha = RedisManager.scripts().get("monthly_quota_refund")
    if not sha:
        raise RuntimeError("Monthly quota refund Lua script not loaded")
    key = _month_key(user_id)
    await client.evalsha(sha, 1, key)
