from __future__ import annotations

import httpx
import pytest

from gateflow.main import create_app
from gateflow.redis_client import RedisManager


@pytest.fixture
async def mtls_proxy(redis_client, seeded_data, db_init, monkeypatch):
    monkeypatch.setenv("GATEFLOW_MTLS_ENABLED", "true")
    from gateflow.config import get_settings

    get_settings.cache_clear()
    RedisManager._client = redis_client
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as c:
        yield c
    RedisManager._client = redis_client


@pytest.mark.anyio
async def test_mtls_missing_header_rejected(mtls_proxy, respx_mock):
    respx_mock.get("http://localhost:9999/profile").respond(200, text="ok")
    response = await mtls_proxy.get("/users/profile", headers={"X-API-KEY": "test-api-key"})
    assert response.status_code == 403
    assert "certificate" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_mtls_valid_header_allowed(mtls_proxy, respx_mock, monkeypatch):
    respx_mock.get("http://localhost:9999/profile").respond(200, text="ok")
    response = await mtls_proxy.get(
        "/users/profile",
        headers={"X-API-KEY": "test-api-key", "X-Client-Verify": "SUCCESS"},
    )
    assert response.status_code == 200


@pytest.mark.anyio
async def test_mtls_custom_header_and_value(mtls_proxy, respx_mock, monkeypatch):
    monkeypatch.setenv("GATEFLOW_MTLS_HEADER", "X-Verified-Client")
    monkeypatch.setenv("GATEFLOW_MTLS_REQUIRED_VALUE", "verified")
    from gateflow.config import get_settings

    get_settings.cache_clear()

    respx_mock.get("http://localhost:9999/profile").respond(200, text="ok")
    response = await mtls_proxy.get(
        "/users/profile",
        headers={"X-API-KEY": "test-api-key", "X-Client-Verify": "SUCCESS"},
    )
    assert response.status_code == 403

    response = await mtls_proxy.get(
        "/users/profile",
        headers={"X-API-KEY": "test-api-key", "X-Verified-Client": "verified"},
    )
    assert response.status_code == 200
