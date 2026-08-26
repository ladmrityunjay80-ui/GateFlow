from __future__ import annotations

import asyncio

import pytest

from gateflow.anomaly import AnomalyDetector
from gateflow.audit import flush_audit, log_admin_async
from gateflow.auth import resolve_rate_limits
from gateflow.cache import TTLCache
from gateflow.models import APIKeyRecord, TierConfig, normalise_prefix
from gateflow.redis_client import RedisManager
from gateflow.telemetry import fire_telemetry, flush_telemetry


@pytest.mark.anyio
async def test_ttl_cache_basic():
    cache = TTLCache(ttl=0.1, maxsize=2)
    await cache.set("a", 1)
    assert await cache.get("a") == 1
    await asyncio.sleep(0.15)
    assert await cache.get("a") is None


@pytest.mark.anyio
async def test_ttl_cache_maxsize():
    cache = TTLCache(ttl=10.0, maxsize=2)
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.set("c", 3)
    assert await cache.get("a") is None
    assert await cache.get("b") == 2
    assert await cache.get("c") == 3


@pytest.mark.anyio
async def test_ttl_cache_delete():
    cache = TTLCache(ttl=10.0, maxsize=2)
    await cache.set("a", 1)
    await cache.delete("a")
    assert await cache.get("a") is None


def test_normalise_prefix():
    assert normalise_prefix("/users/") == "users"
    assert normalise_prefix("//users//profile//") == "users/profile"
    assert normalise_prefix("users") == "users"


def test_normalise_prefix_invalid():
    with pytest.raises(ValueError):
        normalise_prefix("/")
    with pytest.raises(ValueError):
        normalise_prefix("/users/../")


def test_resolve_rate_limits_tier():
    record = APIKeyRecord(
        user_id="u",
        tier="free",
        active=1,
        rate_limit_custom=-1,
    )
    tier = TierConfig(capacity=10, refill_rate=1.0)
    assert resolve_rate_limits(record, tier) == (10, 1.0)


def test_resolve_rate_limits_custom():
    record = APIKeyRecord(
        user_id="u",
        tier="free",
        active=1,
        rate_limit_custom=100,
        rate_limit_custom_refill=50,
    )
    tier = TierConfig(capacity=10, refill_rate=1.0)
    assert resolve_rate_limits(record, tier) == (100, 50.0)


def test_resolve_rate_limits_custom_fallback_refill():
    record = APIKeyRecord(
        user_id="u",
        tier="free",
        active=1,
        rate_limit_custom=100,
    )
    tier = TierConfig(capacity=10, refill_rate=1.0)
    assert resolve_rate_limits(record, tier) == (100, 100.0)


def test_anomaly_detector_flags_error_spike():
    detector = AnomalyDetector(error_rate_threshold=0.2, window_size=10)
    for _ in range(9):
        detector.check({"status_code": "500", "duration_ms": "10", "route": "r", "api_key": "k"})
    anomalies = detector.check({"status_code": "500", "duration_ms": "10", "route": "r", "api_key": "k"})
    assert any(a["type"] == "error_rate_spike" for a in anomalies)


def test_anomaly_detector_flags_latency_spike():
    detector = AnomalyDetector(latency_threshold_ms=100.0, window_size=20)
    for i in range(20):
        detector.check({"status_code": "200", "duration_ms": str(i), "route": "r", "api_key": "k"})
    anomalies = detector.check({"status_code": "200", "duration_ms": "500", "route": "r", "api_key": "k"})
    assert any(a["type"] == "latency_spike" for a in anomalies)


@pytest.mark.anyio
async def test_fire_telemetry_publishes(redis_client):
    RedisManager._client = redis_client
    fire_telemetry("req-1", "test-key", "test-key-id", "u1", "users", 1.0, 200, 10, 20)
    await flush_telemetry()
    events = await redis_client.xrevrange("gateflow:metrics", count=5)
    assert any(fields.get("user_id") == "u1" for _, fields in events)


@pytest.mark.anyio
async def test_log_admin_async_publishes(redis_client, db_init):
    RedisManager._client = redis_client
    log_admin_async("create", "routes:users", "admin-key")
    await flush_audit()
    events = await redis_client.xrevrange("gateflow:audit:admin", count=5)
    assert any(fields.get("action") == "create" for _, fields in events)
