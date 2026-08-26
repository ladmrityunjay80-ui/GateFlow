from __future__ import annotations

import os

import httpx
import pytest

from gateflow.config import get_settings
from gateflow.main import create_app
from gateflow.redis_client import RedisManager


@pytest.fixture
async def idempotency_client(redis_client, seeded_data):
    os.environ["GATEFLOW_IDEMPOTENCY_ENABLED"] = "true"
    os.environ["GATEFLOW_IDEMPOTENCY_TTL"] = "10"
    get_settings.cache_clear()

    RedisManager._client = redis_client
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as c:
        yield c, seeded_data
    RedisManager._client = redis_client


@pytest.mark.anyio
async def test_idempotent_post_caches_and_replays(idempotency_client, respx_mock):
    client, key = idempotency_client
    respx_mock.post("http://localhost:9999/profile").respond(201, json={"created": True})

    headers = {
        "X-API-KEY": key,
        "Idempotency-Key": "idem-001",
        "Content-Type": "application/json",
    }
    first = await client.post("/users/profile", headers=headers, json={"name": "test"})
    assert first.status_code == 201
    assert first.json() == {"created": True}

    second = await client.post("/users/profile", headers=headers, json={"name": "test"})
    assert second.status_code == 201
    assert second.json() == {"created": True}

    assert len(respx_mock.calls) == 1


@pytest.mark.anyio
async def test_get_does_not_cache(idempotency_client, respx_mock):
    client, key = idempotency_client
    respx_mock.get("http://localhost:9999/profile").respond(200, text="ok")

    headers = {"X-API-KEY": key, "Idempotency-Key": "idem-002"}
    first = await client.get("/users/profile", headers=headers)
    assert first.status_code == 200

    second = await client.get("/users/profile", headers=headers)
    assert second.status_code == 200

    assert len(respx_mock.calls) == 2
