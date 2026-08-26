from __future__ import annotations

import asyncio

import pytest
from pytest import MonkeyPatch

from gateflow.config import Settings, get_settings
from gateflow.models import Route
from gateflow.redis_client import RedisManager, _build_redis_client, _parse_sentinels


def test_parse_sentinels():
    assert _parse_sentinels("") == []
    assert _parse_sentinels("redis1:26379,redis2") == [("redis1", 26379), ("redis2", 26379)]
    assert _parse_sentinels("  redis1:5000  ,  ") == [("redis1", 5000)]


@pytest.mark.anyio
async def test_build_redis_client_from_url():
    settings = get_settings()
    client, sentinel = _build_redis_client(settings)
    assert sentinel is None
    assert client is not None
    await client.aclose()  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_build_redis_client_with_sentinel():
    settings = Settings()
    settings.redis_sentinels = "sentinel1:26379,sentinel2:26379"
    client, sentinel = _build_redis_client(settings)
    assert sentinel is not None
    assert client is not None
    await client.aclose()  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_redis_manager_refresh_and_reload(redis_client, db_init):
    from gateflow.store import save_route

    RedisManager._client = redis_client
    RedisManager._route_cache = {}

    route = Route(
        prefix="orders",
        target_url="http://orders-service:8000",
        fallback_url=None,
        strip_prefix=True,
        requires_auth=False,
        allowed_methods=set(),
    )
    await save_route(route, skip_redis_publish=True)
    await RedisManager._refresh_routes()
    assert "orders" in RedisManager.routes()
    assert RedisManager.routes()["orders"].target_url == "http://orders-service:8000"

    await RedisManager.reload_routes()
    assert "orders" in RedisManager.routes()


@pytest.mark.anyio
async def test_redis_manager_scripts_and_client(redis_client):
    RedisManager._client = redis_client
    await RedisManager._load_scripts()
    assert "token_bucket" in RedisManager.scripts()
    assert "circuit_breaker" in RedisManager.scripts()
    assert RedisManager.client() is redis_client


@pytest.mark.anyio
async def test_redis_manager_connect_close(redis_client, db_init, monkeypatch: MonkeyPatch):
    from gateflow import redis_client as rc
    from gateflow.store import save_route

    fast_settings = get_settings().model_copy(update={"redis_health_check_interval": 1})
    monkeypatch.setattr(rc, "get_settings", lambda: fast_settings)

    # Store a route so the listener has something to refresh.
    await save_route(
        Route(
            prefix="health",
            target_url="http://health-service:8000",
            fallback_url=None,
            strip_prefix=True,
            requires_auth=False,
            allowed_methods=set(),
        ),
        skip_redis_publish=True,
    )

    await RedisManager.connect()
    await asyncio.sleep(0.05)
    await RedisManager.close()


def test_redis_manager_client_raises_when_disconnected():
    RedisManager._client = None
    with pytest.raises(RuntimeError, match="not connected"):
        RedisManager.client()


@pytest.mark.anyio
async def test_redis_manager_reconnect_replaces_client(redis_client, monkeypatch: MonkeyPatch):

    RedisManager._client = redis_client
    RedisManager._sentinel = None
    RedisManager._closing = False

    called: list = []

    async def fake_initialize():
        called.append("init")
        # Use the existing client to avoid needing a second Redis instance.
        RedisManager._client = redis_client

    monkeypatch.setattr(RedisManager, "_initialize_client", fake_initialize)

    old_client = redis_client
    await RedisManager._reconnect()

    assert "init" in called
    assert RedisManager._client is old_client
