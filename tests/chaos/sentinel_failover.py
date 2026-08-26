#!/usr/bin/env python3
"""Chaos test: kill the Redis master in a Sentinel topology and verify
that GateFlow reconnects and continues serving traffic.

Requires:
    - docker-compose -f docker-compose.ha.yml up -d
    - python -m scripts.seed
    - Locust or the load_test.py running in the background (optional)

Usage:
    python -m tests.chaos.sentinel_failover
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx

import docker as docker_sdk


def _gateway_url() -> str:
    return os.environ.get("GATEWAY_URL", "http://localhost:8080")


def _container_name() -> str:
    return os.environ.get("GATEFLOW_MASTER_CONTAINER", "gateflow_redis_master")


async def _request_until_ok(url: str, headers: dict[str, str], timeout: float = 120.0) -> bool:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=5.0) as client:
        while time.monotonic() < deadline:
            try:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
    return False


async def main() -> int:
    url = f"{_gateway_url()}/users/profile"
    headers = {"X-API-KEY": os.environ.get("API_KEY", "gf_dev_free_001")}

    client = docker_sdk.from_env()
    try:
        container = client.containers.get(_container_name())
    except docker_sdk.errors.NotFound:
        print(f"Container {_container_name()} not found. Is docker-compose.ha.yml up?")
        return 1

    print("Step 1: Verify traffic is healthy before chaos.")
    if not await _request_until_ok(url, headers, timeout=30.0):
        print("Pre-chaos traffic is not healthy.")
        return 1
    print("  OK")

    print(f"Step 2: Stop Redis master container {_container_name()}.")
    container.stop(timeout=5)
    print("  Stopped.")

    print("Step 3: Wait for Sentinel failover and GateFlow recovery.")
    recovered = await _request_until_ok(url, headers, timeout=120.0)
    if not recovered:
        print("FAIL: Traffic did not recover after master failure.")
        return 1
    print("  OK — traffic recovered")

    print(f"Step 4: Restart Redis master container {_container_name()}.")
    container.start()
    print("  Started.")

    print("Step 5: Verify traffic remains healthy after recovery.")
    if not await _request_until_ok(url, headers, timeout=60.0):
        print("FAIL: Traffic did not stay healthy after restart.")
        return 1
    print("  OK")

    print("Sentinel failover chaos test PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
