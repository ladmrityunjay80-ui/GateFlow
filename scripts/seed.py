"""Seed GateFlow with sample routes, tiers, and API keys.

Usage:
    python -m scripts.seed
"""
from __future__ import annotations

import asyncio
import os
import sys

import redis.asyncio as redis

# Ensure the project root is on the path so `gateflow` is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gateflow.crypto import hash_api_key
from gateflow.models import Route


async def main() -> None:
    redis_url = os.environ.get("GATEFLOW_REDIS_URL", "redis://localhost:6379/0")
    client = redis.from_url(redis_url, decode_responses=True)

    # Tiers
    await client.hset("gateflow:tiers:free", mapping={
        "capacity": "15",
        "refill_rate": "2.0",
        "window_info": "1s",
    })
    await client.hset("gateflow:tiers:premium", mapping={
        "capacity": "100",
        "refill_rate": "20.0",
        "window_info": "1s",
    })

    # API keys (plain keys are hashed at rest)
    free_key = "gf_dev_free_001"
    premium_key = "gf_dev_premium_001"
    await client.hset(f"gateflow:auth:keys:{hash_api_key(free_key)}", mapping={
        "user_id": "usr_free_001",
        "tier": "free",
        "active": "1",
        "expires_at": "9999999999",
        "rate_limit_custom": "-1",
        "request_count_lifetime": "0",
    })
    await client.hset(f"gateflow:auth:keys:{hash_api_key(premium_key)}", mapping={
        "user_id": "usr_premium_001",
        "tier": "premium",
        "active": "1",
        "expires_at": "9999999999",
        "rate_limit_custom": "-1",
        "request_count_lifetime": "0",
    })

    # Routes
    users_route = Route(
        prefix="users",
        target_url="http://users-service:8000",
        fallback_url=None,
        strip_prefix=True,
        requires_auth=True,
        allowed_methods="GET,POST",
    )
    orders_route = Route(
        prefix="orders",
        target_url="http://orders-service:8000",
        fallback_url=None,
        strip_prefix=True,
        requires_auth=True,
        allowed_methods="GET,POST",
    )
    await client.hset("gateflow:routes", mapping={
        "users": users_route.to_json(),
        "orders": orders_route.to_json(),
    })

    await client.aclose()
    print("GateFlow sample data seeded.")
    print(f"Free key: {free_key}")
    print(f"Premium key: {premium_key}")


if __name__ == "__main__":
    asyncio.run(main())
