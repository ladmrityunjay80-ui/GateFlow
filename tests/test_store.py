from __future__ import annotations

import pytest

from gateflow.db import init_db
from gateflow.models import APIKeyRecord, Route, TierConfig
from gateflow.redis_client import RedisManager
from gateflow.store import (
    delete_route,
    delete_tier_config,
    get_key_record,
    get_route,
    get_tier_config,
    get_usage_summary,
    list_routes,
    list_tier_configs,
    record_usage,
    save_key_record,
    save_route,
    save_tier_config,
)


@pytest.fixture
async def store_db(redis_client, db_init):
    RedisManager._client = redis_client
    await init_db()
    yield


@pytest.mark.anyio
async def test_save_and_get_key_record(store_db):
    record = APIKeyRecord(
        user_id="u1",
        tier="basic",
        active=1,
        expires_at=None,
        rate_limit_custom=-1,
        request_count_lifetime=0,
    )
    await save_key_record("hash1", record)
    found = await get_key_record("hash1")
    assert found is not None
    assert found.user_id == "u1"
    assert found.tier == "basic"


@pytest.mark.anyio
async def test_save_and_get_route(store_db):
    route = Route(
        prefix="orders",
        target_url="http://orders-service:8000",
        fallback_url=None,
        strip_prefix=True,
        requires_auth=False,
        allowed_methods={"GET"},
    )
    await save_route(route, skip_redis_publish=True)
    found = await get_route("orders")
    assert found is not None
    assert found.target_url == "http://orders-service:8000"
    assert await delete_route("orders")
    assert await get_route("orders") is None


@pytest.mark.anyio
async def test_list_routes(store_db):
    r1 = Route(
        prefix="a",
        target_url="http://a",
        fallback_url=None,
        strip_prefix=True,
        requires_auth=False,
        allowed_methods=set(),
    )
    r2 = Route(
        prefix="b",
        target_url="http://b",
        fallback_url=None,
        strip_prefix=True,
        requires_auth=False,
        allowed_methods=set(),
    )
    await save_route(r1, skip_redis_publish=True)
    await save_route(r2, skip_redis_publish=True)
    routes = await list_routes()
    assert {"a", "b"} <= set(routes)


@pytest.mark.anyio
async def test_save_and_get_tier_config(store_db):
    config = TierConfig(capacity=50, refill_rate=5.0, window_info="1s", monthly_quota=100)
    await save_tier_config("basic", config)
    found = await get_tier_config("basic")
    assert found is not None
    assert found.capacity == 50
    assert found.monthly_quota == 100
    assert await delete_tier_config("basic")
    assert await get_tier_config("basic") is None


@pytest.mark.anyio
async def test_list_tier_configs(store_db):
    await save_tier_config("t1", TierConfig(capacity=10, refill_rate=1.0))
    await save_tier_config("t2", TierConfig(capacity=20, refill_rate=2.0))
    tiers = await list_tier_configs()
    assert {"t1", "t2"} <= set(tiers)


@pytest.mark.anyio
async def test_record_and_get_usage(store_db):
    from datetime import UTC, datetime

    day = datetime.now(UTC).date()
    await record_usage("u1", "users", day, bytes_in=100, bytes_out=200)
    await record_usage("u1", "users", day, bytes_in=50, bytes_out=80)
    rows = await get_usage_summary("u1", day, day)
    assert len(rows) == 1
    assert rows[0].requests == 2
    assert rows[0].bytes_in == 150
    assert rows[0].bytes_out == 280
