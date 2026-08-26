from __future__ import annotations

import httpx
import pytest

from gateflow.main import create_app
from gateflow.redis_client import RedisManager


@pytest.fixture
async def governance_client(redis_client, seeded_data):
    from gateflow.models import TierConfig
    from gateflow.store import save_tier_config

    # Apply a monthly quota to the premium tier used by the seeded key.
    await save_tier_config(
        "premium",
        TierConfig(capacity=100, refill_rate=20.0, window_info="1s", monthly_quota=2),
    )
    RedisManager._client = redis_client
    await RedisManager._refresh_routes()

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as c:
        yield c, seeded_data
    RedisManager._client = redis_client


@pytest.mark.anyio
async def test_monthly_quota_enforced(governance_client, respx_mock):
    client, key = governance_client
    respx_mock.get("http://localhost:9999/limited").respond(200, text="ok")

    headers = {"X-API-KEY": key}
    first = await client.get("/users/limited", headers=headers)
    assert first.status_code == 200

    second = await client.get("/users/limited", headers=headers)
    assert second.status_code == 200

    third = await client.get("/users/limited", headers=headers)
    assert third.status_code == 429


@pytest.mark.anyio
async def test_monthly_usage_shown_in_portal(governance_client, respx_mock):
    client, key = governance_client
    respx_mock.get("http://localhost:9999/limited").respond(200, text="ok")

    await client.get("/users/limited", headers={"X-API-KEY": key})
    response = await client.get("/api/me/quota", headers={"X-API-KEY": key})
    assert response.status_code == 200
    data = response.json()
    assert data["monthly_quota"] == 2
    assert data["monthly_used"] == 1
