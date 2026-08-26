from __future__ import annotations

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


@pytest.mark.anyio
async def test_openapi_merge_from_downstream(client, seeded_data, respx_mock):
    respx_mock.get("http://localhost:9999/openapi.json").respond(200, json={
        "openapi": "3.1.0",
        "info": {"title": "Users API", "version": "1.0.0"},
        "paths": {
            "/profile": {
                "get": {"summary": "Get user profile"},
            },
        },
        "components": {
            "schemas": {
                "User": {"type": "object"},
            },
        },
    })

    response = await client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert data["openapi"] == "3.1.0"
    assert "/users/profile" in data["paths"]
    assert "users_User" in data["components"]["schemas"]
