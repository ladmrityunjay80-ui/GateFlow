from __future__ import annotations

import os
import sys

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .models import Route
from .redis_client import RedisManager


def match_route(path: str) -> Route | None:
    cache = RedisManager.routes()
    if not cache:
        return None

    segments = path.strip("/").split("/")
    candidates = sorted(cache.keys(), key=lambda p: (-len(p.split("/")), p))

    for prefix in candidates:
        prefix_segments = prefix.split("/")
        if segments[: len(prefix_segments)] == prefix_segments:
            return cache[prefix]
    return None


def build_downstream_path(route: Route, original_path: str) -> str:
    if not route.strip_prefix:
        return original_path
    prefix = f"/{route.prefix}"
    if original_path.startswith(prefix + "/"):
        return original_path[len(prefix):]
    if original_path == prefix:
        return "/"
    return original_path
