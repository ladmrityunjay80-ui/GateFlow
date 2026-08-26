from __future__ import annotations

import httpx
import pytest

from gateflow.main import create_app
from gateflow.redis_client import RedisManager


@pytest.fixture
async def portal_client(redis_client, seeded_data, db_init):
    RedisManager._client = redis_client
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as c:
        yield c, seeded_data
    RedisManager._client = redis_client


@pytest.mark.anyio
async def test_portal_quota_requires_key(portal_client):
    client, _ = portal_client
    response = await client.get("/api/me/quota")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_portal_quota_returns_key_info(portal_client):
    client, key = portal_client
    response = await client.get("/api/me/quota", headers={"X-API-KEY": key})
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "usr_test_123"
    assert data["tier"] == "premium"
    assert data["capacity"] == 100


@pytest.mark.anyio
async def test_portal_index(portal_client):
    client, _ = portal_client
    response = await client.get("/api/me/portal")
    assert response.status_code == 200
    assert "quota" in response.json()["endpoints"]
