from __future__ import annotations

import os

import httpx
import pytest

from gateflow.crypto import hash_api_key
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
async def test_create_and_get_key(client, admin_headers):
    payload = {
        "user_id": "usr_001",
        "tier": "premium",
        "active": 1,
        "expires_at": None,
        "rate_limit_custom": -1,
    }
    response = await client.post("/api/admin/keys/gf_test_001", headers=admin_headers, json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["api_key"] == hash_api_key("gf_test_001")

    response = await client.get("/api/admin/keys/gf_test_001", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["user_id"] == "usr_001"


@pytest.mark.anyio
async def test_update_and_delete_key(client, admin_headers):
    payload = {
        "user_id": "usr_002",
        "tier": "free",
        "active": 1,
        "expires_at": None,
        "rate_limit_custom": 50,
        "rate_limit_custom_refill": 25,
    }
    response = await client.post("/api/admin/keys/gf_test_002", headers=admin_headers, json=payload)
    assert response.status_code == 201

    update = {**payload, "tier": "premium"}
    response = await client.put("/api/admin/keys/gf_test_002", headers=admin_headers, json=update)
    assert response.status_code == 200
    assert response.json()["tier"] == "premium"

    response = await client.delete("/api/admin/keys/gf_test_002", headers=admin_headers)
    assert response.status_code == 200

    response = await client.get("/api/admin/keys/gf_test_002", headers=admin_headers)
    assert response.status_code == 404


@pytest.mark.anyio
async def test_list_keys(client, admin_headers):
    payload = {
        "user_id": "usr_003",
        "tier": "free",
        "active": 1,
    }
    await client.post("/api/admin/keys/gf_test_003", headers=admin_headers, json=payload)
    response = await client.get("/api/admin/keys", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 1


@pytest.mark.anyio
async def test_create_duplicate_key(client, admin_headers):
    payload = {"user_id": "usr_004", "tier": "free", "active": 1}
    await client.post("/api/admin/keys/gf_test_004", headers=admin_headers, json=payload)
    response = await client.post("/api/admin/keys/gf_test_004", headers=admin_headers, json=payload)
    assert response.status_code == 409
