from __future__ import annotations

import os

import httpx
import pytest

from gateflow.main import create_app
from gateflow.redis_client import RedisManager


@pytest.fixture
async def client(redis_client, db_init):
    RedisManager._client = redis_client
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as c:
        yield c
    RedisManager._client = redis_client


@pytest.fixture
def admin_headers():
    return {"X-Admin-API-Key": os.environ.get("GATEFLOW_ADMIN_KEY", "gateflow-admin-dev")}


@pytest.mark.anyio
async def test_create_and_get_tier(client, admin_headers):
    payload = {"capacity": 20, "refill_rate": 2.0, "window_info": "1s"}
    response = await client.post("/api/admin/tiers/gold", headers=admin_headers, json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["tier"] == "gold"
    assert data["capacity"] == 20

    response = await client.get("/api/admin/tiers/gold", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["refill_rate"] == 2.0


@pytest.mark.anyio
async def test_update_and_delete_tier(client, admin_headers):
    payload = {"capacity": 10, "refill_rate": 1.0, "window_info": "1s"}
    await client.post("/api/admin/tiers/silver", headers=admin_headers, json=payload)

    update = {"capacity": 15, "refill_rate": 1.5, "window_info": "1s"}
    response = await client.put("/api/admin/tiers/silver", headers=admin_headers, json=update)
    assert response.status_code == 200
    assert response.json()["capacity"] == 15

    response = await client.delete("/api/admin/tiers/silver", headers=admin_headers)
    assert response.status_code == 200

    response = await client.get("/api/admin/tiers/silver", headers=admin_headers)
    assert response.status_code == 404


@pytest.mark.anyio
async def test_list_tiers(client, admin_headers):
    payload = {"capacity": 5, "refill_rate": 0.5, "window_info": "1s"}
    await client.post("/api/admin/tiers/bronze", headers=admin_headers, json=payload)
    response = await client.get("/api/admin/tiers", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 1


@pytest.mark.anyio
async def test_create_duplicate_tier(client, admin_headers):
    payload = {"capacity": 5, "refill_rate": 0.5, "window_info": "1s"}
    await client.post("/api/admin/tiers/dup", headers=admin_headers, json=payload)
    response = await client.post("/api/admin/tiers/dup", headers=admin_headers, json=payload)
    assert response.status_code == 409
