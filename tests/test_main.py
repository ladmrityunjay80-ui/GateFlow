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
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.anyio
async def test_ready(client):
    response = await client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["redis"] is True


@pytest.mark.anyio
async def test_ready_downstream(respx_mock, client, redis_client, seeded_data):
    from gateflow.models import Route
    from gateflow.store import save_route

    route = Route(
        prefix="users",
        target_url="http://localhost:9999",
        fallback_url=None,
        strip_prefix=True,
        requires_auth=True,
        allowed_methods={"GET"},
    )
    await save_route(route)

    respx_mock.get("http://localhost:9999/").respond(200, text="ok")
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json()["downstream"] is True


@pytest.mark.anyio
async def test_openapi_json(client, redis_client, seeded_data):
    from gateflow.models import Route
    from gateflow.store import save_route

    route = Route(
        prefix="users",
        target_url="http://localhost:9999",
        fallback_url=None,
        strip_prefix=True,
        requires_auth=True,
        allowed_methods={"GET"},
    )
    await save_route(route)

    response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert "openapi" in response.json()


@pytest.mark.anyio
async def test_metrics_endpoint(client):
    response = await client.get("/metrics")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_cors_wildcard_does_not_allow_credentials(client, redis_client, seeded_data, monkeypatch):
    from gateflow.config import get_settings

    monkeypatch.setenv("GATEFLOW_CORS_ORIGINS", "*")
    # Clear the settings cache so the new CORS config is picked up.
    get_settings.cache_clear()
    get_settings()  # force settings re-evaluation

    from gateflow.main import create_app

    RedisManager._client = redis_client
    test_app = create_app()
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as c:
        response = await c.get("/health", headers={"Origin": "http://example.com"})
        assert response.status_code == 200
        # Wildcard origins cannot be used with credentials; ensure the flag is not set.
        assert response.headers.get("access-control-allow-credentials") != "true"
