from __future__ import annotations

import os

import httpx
import pytest

from gateflow.main import create_app


@pytest.fixture
async def client(redis_client, db_init):
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as c:
        yield c
    from gateflow.redis_client import RedisManager
    RedisManager._client = redis_client


@pytest.fixture
def admin_headers():
    return {"X-Admin-API-Key": os.environ.get("GATEFLOW_ADMIN_KEY", "gateflow-admin-dev")}


@pytest.fixture
def read_only_headers():
    return {"X-Admin-API-Key": os.environ.get("GATEFLOW_ADMIN_READ_KEYS", "gateflow-admin-read-dev").split(",")[0]}


@pytest.mark.anyio
async def test_list_routes_empty(client, admin_headers):
    response = await client.get("/api/admin/routes", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["routes"] == {}


@pytest.mark.anyio
async def test_create_and_get_route(client, admin_headers):
    payload = {
        "target_url": "http://users-service:8000",
        "fallback_url": None,
        "strip_prefix": True,
        "requires_auth": True,
        "allowed_methods": "GET,POST",
    }
    response = await client.post("/api/admin/routes/users", headers=admin_headers, json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["prefix"] == "users"

    response = await client.get("/api/admin/routes/users", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["target_url"] == "http://users-service:8000"


@pytest.mark.anyio
async def test_admin_requires_key(client):
    response = await client.get("/api/admin/routes")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_read_only_admin_can_list(client, read_only_headers):
    response = await client.get("/api/admin/routes", headers=read_only_headers)
    assert response.status_code == 200


@pytest.mark.anyio
async def test_read_only_admin_cannot_write(client, read_only_headers):
    payload = {
        "target_url": "http://users-service:8000",
        "fallback_url": None,
        "strip_prefix": True,
        "requires_auth": True,
        "allowed_methods": "GET,POST",
    }
    response = await client.post("/api/admin/routes/users", headers=read_only_headers, json=payload)
    assert response.status_code == 401
