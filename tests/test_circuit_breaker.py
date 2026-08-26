from __future__ import annotations

import asyncio

import pytest

from gateflow.circuit_breaker import check_circuit, report_circuit
from gateflow.redis_client import RedisManager


@pytest.mark.anyio
async def test_circuit_starts_closed(redis_client):
    RedisManager._client = redis_client
    state = await check_circuit("http://users-service:8000")
    assert state.state == "CLOSED"


@pytest.mark.anyio
async def test_circuit_opens_after_failures(redis_client):
    RedisManager._client = redis_client
    target = "http://users-service:8000"
    for _i in range(6):
        await report_circuit(target, success=False)

    state = await check_circuit(target)
    assert state.state == "OPEN"
    assert state.retry_after > 0


@pytest.mark.anyio
async def test_circuit_half_open_recover(redis_client):
    RedisManager._client = redis_client
    target = "http://users-service:8000"

    for _ in range(6):
        await report_circuit(target, success=False)

    open_state = await check_circuit(target)
    assert open_state.state == "OPEN"

    await asyncio.sleep(0.15)

    half_open = await check_circuit(target)
    assert half_open.state == "HALF_OPEN"

    await report_circuit(target, success=True)
    closed = await check_circuit(target)
    assert closed.state == "CLOSED"
