from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import httpx

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .constants import RedisKeys
from .redis_client import RedisManager


async def build_merged_openapi() -> dict[str, Any]:
    client = RedisManager.client()
    routes = await client.hgetall(RedisKeys.ROUTES_HASH)

    merged: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": "GateFlow Consolidated API",
            "version": "1.0.0",
            "description": "Auto-merged OpenAPI specification from all registered downstream services.",
        },
        "paths": {},
        "components": {"schemas": {}},
    }

    async with httpx.AsyncClient(timeout=2.0) as http_client:
        tasks = []
        for prefix, raw in routes.items():
            try:
                route_data = _parse_route(raw)
                target = route_data["target_url"]
                tasks.append(_fetch_openapi(http_client, prefix, target))
            except (KeyError, ValueError):
                continue
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            continue
        prefix, spec = result
        if not spec:
            continue
        for path, methods in spec.get("paths", {}).items():
            prefixed_path = f"/{prefix}{path}"
            merged["paths"][prefixed_path] = methods
        for name, schema in spec.get("components", {}).get("schemas", {}).items():
            merged["components"]["schemas"][f"{prefix}_{name}"] = schema

    return merged


async def _fetch_openapi(
    client: httpx.AsyncClient, prefix: str, target_url: str
) -> tuple[str, dict[str, Any] | None]:
    url = target_url.rstrip("/") + "/openapi.json"
    try:
        response = await client.get(url)
        if response.status_code == 200:
            return prefix, response.json()
    except httpx.RequestError:
        pass
    return prefix, None


def _parse_route(raw: str) -> dict[str, Any]:
    import json

    data = json.loads(raw)
    if "target_url" not in data:
        raise KeyError("target_url missing")
    return data
