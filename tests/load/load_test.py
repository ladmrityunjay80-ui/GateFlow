#!/usr/bin/env python3
"""Simple asyncio-based load test for the GateFlow proxy.

Usage:
    GATEWAY_URL=http://localhost:8000 API_KEY=gf_dev_free_001 \
        python -m tests.load.load_test --duration 10 --concurrency 50

Requires a running gateway and Redis.  This is intentionally dependency-light
(only uses httpx) so it can run in CI or on a developer laptop without Locust.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from dataclasses import dataclass

import httpx


@dataclass
class LoadStats:
    requests: int = 0
    successes: int = 0
    errors: int = 0
    status_429: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0


async def _worker(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    duration: float,
    delay: float,
    stats: LoadStats,
    lock: asyncio.Lock,
) -> None:
    end = time.monotonic() + duration
    while time.monotonic() < end:
        if delay:
            await asyncio.sleep(delay)
        start = time.perf_counter()
        try:
            response = await client.get(url, headers=headers, timeout=5.0)
            response.raise_for_status()
            ok = True
            status = response.status_code
        except Exception:
            ok = False
            status = 0
        elapsed = (time.perf_counter() - start) * 1000.0

        async with lock:
            stats.requests += 1
            if ok:
                stats.successes += 1
            else:
                stats.errors += 1
            if status == 429:
                stats.status_429 += 1
            stats.total_ms += elapsed
            stats.max_ms = max(stats.max_ms, elapsed)


async def main() -> None:
    parser = argparse.ArgumentParser(description="GateFlow load test")
    parser.add_argument("--gateway", default=os.environ.get("GATEWAY_URL", "http://localhost:8000"))
    parser.add_argument("--api-key", default=os.environ.get("API_KEY", "gf_dev_free_001"))
    parser.add_argument("--route", default="/users/profile")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--delay", type=float, default=0.0)
    args = parser.parse_args()

    url = f"{args.gateway.rstrip('/')}{args.route}"
    headers = {"X-API-KEY": args.api_key}

    stats = LoadStats()
    lock = asyncio.Lock()

    start = time.perf_counter()
    async with httpx.AsyncClient(
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    ) as client:
        workers = [
            _worker(client, url, headers, args.duration, args.delay, stats, lock)
            for _ in range(args.concurrency)
        ]
        await asyncio.gather(*workers)
    total_elapsed = (time.perf_counter() - start) * 1000.0

    avg = stats.total_ms / stats.requests if stats.requests else 0.0
    rps = (stats.requests / (total_elapsed / 1000.0)) if total_elapsed else 0.0

    print(f"Concurrency:    {args.concurrency}")
    print(f"Duration (s):   {args.duration:.1f}")
    print(f"Requests:       {stats.requests}")
    print(f"Successes:      {stats.successes}")
    print(f"Errors:         {stats.errors}")
    print(f"429s:           {stats.status_429}")
    print(f"Avg latency:    {avg:.2f} ms")
    print(f"Max latency:    {stats.max_ms:.2f} ms")
    print(f"Req/sec:        {rps:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
