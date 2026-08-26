from __future__ import annotations

import asyncio
import contextlib

import pytest

from gateflow.metrics_worker import (
    CONSUMER_GROUP,
    _ensure_consumer_group,
    _get_ml_anomaly_detector,
    consume_stream,
)
from gateflow.redis_client import RedisManager


@pytest.fixture
def metrics_worker_client(redis_client):
    RedisManager._client = redis_client
    return redis_client


@pytest.mark.anyio
async def test_ensure_consumer_group_creates_group(metrics_worker_client):
    await _ensure_consumer_group(metrics_worker_client, "gateflow:metrics")
    info = await metrics_worker_client.xinfo_groups("gateflow:metrics")
    assert any(g["name"] == CONSUMER_GROUP for g in info)
    # Creating again should be idempotent.
    await _ensure_consumer_group(metrics_worker_client, "gateflow:metrics")


@pytest.mark.anyio
async def test_consume_stream_reads_and_acknowledges(metrics_worker_client):
    await metrics_worker_client.xadd("gateflow:audit:admin", {"action": "test"})

    task = asyncio.create_task(consume_stream("gateflow:audit:admin", block_ms=100, count=1))
    await asyncio.sleep(0.1)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    pending = await metrics_worker_client.xpending_range(
        "gateflow:audit:admin", CONSUMER_GROUP, "-", "+", count=10
    )
    assert pending == []


@pytest.mark.anyio
async def test_consume_stream_emits_rule_based_anomaly(metrics_worker_client, monkeypatch):
    from gateflow.metrics_worker import _anomaly_detector

    monkeypatch.setattr(_anomaly_detector, "error_rate_threshold", 0.1)

    for i in range(11):
        await metrics_worker_client.xadd(
            "gateflow:metrics",
            {
                "status_code": "500",
                "duration_ms": "10",
                "route": "test",
                "api_key": "k",
                "request_id": f"r{i}",
                "user_id": "u",
            },
        )

    task = asyncio.create_task(consume_stream("gateflow:metrics", block_ms=100, count=11))
    await asyncio.sleep(0.2)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    anomalies = await metrics_worker_client.xrevrange("gateflow:anomalies", count=5)
    assert any("error_rate_spike" in a.get("type", "") for _, a in anomalies)


@pytest.mark.anyio
async def test_consume_stream_ml_anomaly_feature_flag(metrics_worker_client, monkeypatch):
    monkeypatch.setenv("GATEFLOW_ML_ANOMALY_ENABLED", "true")
    monkeypatch.setenv("GATEFLOW_ML_ANOMALY_WINDOW_SIZE", "6")
    monkeypatch.setenv("GATEFLOW_ML_ANOMALY_THRESHOLD", "1.0")

    from gateflow.config import get_settings

    get_settings.cache_clear()

    # Insert a clear outlier after a stable window.
    for i in range(6):
        await metrics_worker_client.xadd(
            "gateflow:metrics",
            {
                "status_code": "200",
                "duration_ms": "10",
                "route": "ml-test",
                "api_key": "k",
                "request_id": f"r{i}",
                "user_id": "u",
            },
        )
    await metrics_worker_client.xadd(
        "gateflow:metrics",
        {
            "status_code": "200",
            "duration_ms": "500",
            "route": "ml-test",
            "api_key": "k",
            "request_id": "r7",
            "user_id": "u",
        },
    )

    task = asyncio.create_task(consume_stream("gateflow:metrics", block_ms=100, count=7))
    await asyncio.sleep(0.2)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    anomalies = await metrics_worker_client.xrevrange("gateflow:anomalies", count=10)
    assert any(a.get("type") == "ml_outlier" for _, a in anomalies)


def test_ml_anomaly_detector_stateful():
    detector = _get_ml_anomaly_detector()
    for _ in range(10):
        detector.update(10.0)
    outlier = detector.update(500.0)
    assert outlier["is_anomaly"] is True
    assert outlier["z_score"] > 0
