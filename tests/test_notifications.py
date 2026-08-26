from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json

import httpx
import pytest

from gateflow.config import get_settings
from gateflow.notifications import _send_webhook, _send_webhook_with_retry, _sign_payload, consume_anomalies
from gateflow.redis_client import RedisManager


@pytest.mark.anyio
async def test_consume_anomalies_dispatches_to_webhook(redis_client, monkeypatch, respx_mock):
    RedisManager._client = redis_client

    monkeypatch.setenv("GATEFLOW_NOTIFICATION_WORKER_ENABLED", "true")
    monkeypatch.setenv("GATEFLOW_NOTIFICATION_WEBHOOK_URL", "http://localhost:9999/notify")
    get_settings.cache_clear()

    route = respx_mock.post("http://localhost:9999/notify").respond(204)

    await redis_client.xadd(
        "gateflow:anomalies",
        {
            "type": "error_rate_spike",
            "route": "orders",
            "value": "0.5",
        },
    )

    task = asyncio.create_task(consume_anomalies(block_ms=100, count=1))
    await asyncio.sleep(0.3)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert route.called


@pytest.mark.anyio
async def test_send_webhook_disabled_just_logs(caplog, monkeypatch):
    from gateflow.config import Settings, get_settings

    monkeypatch.delenv("GATEFLOW_NOTIFICATION_WEBHOOK_URL", raising=False)
    get_settings.cache_clear()

    settings = Settings()
    assert settings.notification_webhook_url == ""
    with caplog.at_level("INFO", logger="gateflow.notifications"):
        await _send_webhook_with_retry({"type": "test"})
    assert any(
        record.message == "anomaly_notification" and getattr(record, "type", None) == "test"
        for record in caplog.records
    )


@pytest.mark.anyio
async def test_send_webhook_with_signature(respx_mock, monkeypatch):
    from gateflow.config import get_settings

    monkeypatch.setenv("GATEFLOW_NOTIFICATION_WEBHOOK_URL", "http://localhost:9999/notify")
    monkeypatch.setenv("GATEFLOW_WEBHOOK_SIGNING_SECRET", "test-secret")
    get_settings.cache_clear()

    payload = {"type": "error_rate_spike", "route": "orders"}
    expected_body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    expected_sig = base64.b64encode(hmac.new(b"test-secret", expected_body, hashlib.sha256).digest()).decode()

    def _check_signature(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-GateFlow-Signature") == f"sha256={expected_sig}"
        return httpx.Response(204)

    route = respx_mock.post("http://localhost:9999/notify").mock(side_effect=_check_signature)

    await _send_webhook("http://localhost:9999/notify", payload)
    assert route.called


@pytest.mark.anyio
async def test_sign_payload_without_secret(monkeypatch):
    from gateflow.config import get_settings

    monkeypatch.delenv("GATEFLOW_WEBHOOK_SIGNING_SECRET", raising=False)
    get_settings.cache_clear()
    assert _sign_payload({"a": 1}) is None
