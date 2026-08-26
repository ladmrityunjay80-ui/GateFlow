from __future__ import annotations

import asyncio

import httpx
import pytest

from gateflow.config import get_settings
from gateflow.main import create_app
from gateflow.redis_client import RedisManager


@pytest.fixture
async def seeded_proxy(redis_client, seeded_data, db_init):
    RedisManager._client = redis_client
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as c:
        yield c
    RedisManager._client = redis_client


@pytest.mark.anyio
async def test_proxy_missing_api_key(seeded_proxy):
    response = await seeded_proxy.get("/users/profile")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_proxy_success(seeded_proxy, seeded_data, respx_mock):
    respx_mock.get("http://localhost:9999/profile").respond(200, text="ok")

    response = await seeded_proxy.get("/users/profile", headers={"X-API-KEY": seeded_data})
    assert response.status_code == 200
    assert response.text == "ok"
    assert "X-RateLimit-Remaining" in response.headers
    assert response.headers["X-Request-ID"]


@pytest.mark.anyio
async def test_proxy_429_retry_after(seeded_proxy, seeded_data, respx_mock, redis_client):
    from gateflow.models import TierConfig
    from gateflow.store import save_tier_config

    # Limit the premium tier to a single request so we can hit 429 quickly.
    await save_tier_config(
        "premium",
        TierConfig(capacity=1, refill_rate=0.1, window_info="1s"),
    )
    respx_mock.get("http://localhost:9999/profile").respond(200, text="ok")

    first = await seeded_proxy.get("/users/profile", headers={"X-API-KEY": seeded_data})
    assert first.status_code == 200

    second = await seeded_proxy.get("/users/profile", headers={"X-API-KEY": seeded_data})
    assert second.status_code == 429
    assert "Retry-After" in second.headers
    assert int(second.headers["Retry-After"]) >= 1


@pytest.mark.anyio
async def test_proxy_fallback_on_downstream_failure(seeded_proxy, seeded_data, respx_mock, redis_client):
    from gateflow.models import Route
    from gateflow.store import save_route

    # Update the route with a fallback target.
    route = Route(
        prefix="users",
        target_url="http://localhost:9999",
        fallback_url="http://localhost:9998",
        strip_prefix=True,
        requires_auth=True,
        allowed_methods={"GET", "POST"},
    )
    await save_route(route)

    respx_mock.get("http://localhost:9999/profile").mock(side_effect=httpx.ConnectError("down"))
    respx_mock.get("http://localhost:9998/profile").respond(200, text="fallback-ok")

    response = await seeded_proxy.get("/users/profile", headers={"X-API-KEY": seeded_data})
    assert response.status_code == 200
    assert response.text == "fallback-ok"


@pytest.mark.anyio
async def test_proxy_body_limit(seeded_proxy, seeded_data, respx_mock):
    settings = get_settings()
    respx_mock.get("http://localhost:9999/profile").respond(200, text="ok")

    body = b"x" * (settings.max_request_body_bytes + 1)
    response = await seeded_proxy.post("/users/profile", headers={"X-API-KEY": seeded_data}, content=body)
    assert response.status_code == 413


@pytest.mark.anyio
async def test_proxy_telemetry_published(seeded_proxy, seeded_data, respx_mock, redis_client):
    respx_mock.get("http://localhost:9999/profile").respond(200, text="ok")

    await seeded_proxy.get("/users/profile", headers={"X-API-KEY": seeded_data})

    # Give the async telemetry task a chance to run.
    await asyncio.sleep(0.05)

    events = await redis_client.xrevrange("gateflow:metrics", count=5)
    assert len(events) >= 1


@pytest.mark.anyio
async def test_proxy_global_rate_limit(redis_client, seeded_data, respx_mock, monkeypatch, db_init):
    from gateflow.config import get_settings
    from gateflow.main import create_app

    monkeypatch.setenv("GATEFLOW_GLOBAL_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("GATEFLOW_GLOBAL_RATE_LIMIT_CAPACITY", "1")
    monkeypatch.setenv("GATEFLOW_GLOBAL_RATE_LIMIT_REFILL_RATE", "0.001")
    get_settings.cache_clear()

    respx_mock.get("http://localhost:9999/profile").respond(200, text="ok")

    RedisManager._client = redis_client
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as c:
        first = await c.get("/users/profile", headers={"X-API-KEY": seeded_data})
        assert first.status_code == 200

        second = await c.get("/users/profile", headers={"X-API-KEY": seeded_data})
        assert second.status_code == 429
        assert "Global rate limit exceeded" in second.text
