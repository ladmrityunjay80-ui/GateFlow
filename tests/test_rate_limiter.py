from __future__ import annotations

import asyncio

import pytest

from gateflow.auth import resolve_rate_limits
from gateflow.rate_limiter import check_rate_limit
from gateflow.redis_client import RedisManager


@pytest.mark.anyio
async def test_token_bucket_initial_capacity(seeded_data, redis_client):
    record, tier, key_id = await _get_record_tier(redis_client, seeded_data)
    capacity, refill = resolve_rate_limits(record, tier)

    result = await check_rate_limit(key_id, "users", capacity, refill)
    assert result.allowed
    assert 0 < result.remaining <= capacity


@pytest.mark.anyio
async def test_token_bucket_exhausts_and_refills(seeded_data, redis_client):
    record, tier, key_id = await _get_record_tier(redis_client, seeded_data)
    capacity, refill = resolve_rate_limits(record, tier)

    # Drain the bucket.
    for _ in range(capacity):
        result = await check_rate_limit(key_id, "users", capacity, refill)
        assert result.allowed

    # Next request should be denied.
    denied = await check_rate_limit(key_id, "users", capacity, refill)
    assert not denied.allowed
    assert denied.retry_after > 0

    # Wait for a token to refill.
    await asyncio.sleep(1.0 / refill + 0.05)
    refilled = await check_rate_limit(key_id, "users", capacity, refill)
    assert refilled.allowed


async def _get_record_tier(redis_client, api_key):
    from gateflow.auth import authenticate

    RedisManager._client = redis_client
    return await authenticate(api_key)
