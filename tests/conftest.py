from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import time

import pytest
import redis.asyncio as redis

# Use an isolated Redis DB for tests.
REDIS_URL = os.environ.get("GATEFLOW_TEST_REDIS_URL", "redis://localhost:6379/15")
TEST_CONTAINER_NAME = "gateflow-test-redis"


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    os.environ["GATEFLOW_REDIS_URL"] = REDIS_URL
    os.environ.setdefault("GATEFLOW_ADMIN_KEY", "gateflow-admin-test")
    os.environ.setdefault("GATEFLOW_ADMIN_READ_KEYS", "gateflow-admin-read-test")
    os.environ.setdefault("GATEFLOW_KEY_SECRET", "gateflow-test-secret")
    os.environ.setdefault("GATEFLOW_CIRCUIT_BREAKER_OPEN_DURATION", "0.1")
    os.environ.setdefault("GATEFLOW_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    # Try to ensure a real Redis is running, but do not fail if it is not.
    # The redis_client fixture will connect and load Lua scripts.
    try:
        if not _redis_port_open():
            _start_redis_container()
    except Exception:
        pass


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    _stop_redis_container()


def _redis_port_open(host: str = "127.0.0.1", port: int = 6379) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _start_redis_container() -> bool:
    try:
        result = subprocess.run(
            ["docker", "ps", "-q", "-f", f"name={TEST_CONTAINER_NAME}"],
            capture_output=True,
            text=True,
            check=True,
        )
        if not result.stdout.strip():
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    TEST_CONTAINER_NAME,
                    "-p",
                    "127.0.0.1:6379:6379",
                    "redis:7-alpine",
                ],
                check=True,
                capture_output=True,
            )
        return _wait_for_redis_sync()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _wait_for_redis_sync() -> bool:
    deadline = time.time() + 15
    while time.time() < deadline:
        if _redis_port_open():
            return True
        time.sleep(0.2)
    return False


def _stop_redis_container() -> None:
    with contextlib.suppress(FileNotFoundError):
        subprocess.run(
            ["docker", "rm", "-f", TEST_CONTAINER_NAME],
            check=False,
            capture_output=True,
        )


@pytest.fixture(scope="session")
def redis_url() -> str:
    return REDIS_URL


@pytest.fixture
async def redis_client():
    client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await client.ping()
        await client.flushdb()
    except Exception as exc:
        await client.aclose()  # type: ignore[attr-defined]
        pytest.fail(f"Redis at {REDIS_URL} is not reachable: {exc}")

    from gateflow.cache import clear_caches
    from gateflow.redis_client import RedisManager

    RedisManager._client = client
    RedisManager._route_cache = {}
    await clear_caches()
    await RedisManager._load_scripts()
    yield client
    RedisManager._client = None
    RedisManager._route_cache = {}
    await client.aclose()  # type: ignore[attr-defined]


@pytest.fixture
async def db_init():
    """Provide an in-memory database that is created and closed for the test."""
    from gateflow.audit import flush_audit
    from gateflow.db import close_db, init_db

    await init_db()
    yield
    await flush_audit()
    await close_db()


@pytest.fixture
async def seeded_data(redis_client, db_init):
    """Seed Redis with a route, a tier, and an API key for tests."""
    from gateflow.crypto import hash_api_key
    from gateflow.db import init_db
    from gateflow.models import APIKeyRecord, Route, TierConfig
    from gateflow.redis_client import RedisManager
    from gateflow.store import save_key_record, save_route, save_tier_config

    await init_db()

    key = "test-api-key"
    key_id = hash_api_key(key)
    record = APIKeyRecord(
        user_id="usr_test_123",
        tier="premium",
        active=1,
        expires_at=9999999999,
        rate_limit_custom=-1,
        request_count_lifetime=0,
    )
    await save_key_record(key_id, record)

    await save_tier_config(
        "premium",
        TierConfig(capacity=100, refill_rate=20.0, window_info="1s"),
        skip_redis_publish=True,
    )

    route = Route(
        prefix="users",
        target_url="http://localhost:9999",
        fallback_url=None,
        strip_prefix=True,
        requires_auth=True,
        allowed_methods={"GET", "POST"},
    )
    await save_route(route, skip_redis_publish=True)
    await RedisManager._refresh_routes()

    yield key

    # Cleanup
    await redis_client.delete(f"gateflow:auth:keys:{key_id}")
    await redis_client.delete("gateflow:tiers:premium")
    await redis_client.hdel("gateflow:routes", "users")
    await redis_client.delete(f"gateflow:rl:{key_id}:users")
