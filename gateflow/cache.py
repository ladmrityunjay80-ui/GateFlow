from __future__ import annotations

import asyncio
import os
import sys
import time
from collections import OrderedDict
from typing import Any, TypeVar

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .config import get_settings

T = TypeVar("T")


class TTLCache:
    """Bounded, TTL-backed in-memory cache with async-safe access."""

    def __init__(self, ttl: float, maxsize: int = 1000):
        self.ttl = ttl
        self.maxsize = maxsize
        self._data: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            value, expires = entry
            if time.monotonic() > expires:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return value

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            expires = time.monotonic() + self.ttl
            self._data[key] = (value, expires)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()


_api_key_cache: TTLCache | None = None
_tier_cache: TTLCache | None = None


def _init_caches() -> tuple[TTLCache, TTLCache]:
    global _api_key_cache, _tier_cache
    settings = get_settings()
    if _api_key_cache is None:
        _api_key_cache = TTLCache(ttl=settings.cache_ttl_seconds, maxsize=settings.cache_max_size)
    if _tier_cache is None:
        _tier_cache = TTLCache(ttl=settings.cache_ttl_seconds, maxsize=settings.cache_max_size)
    return _api_key_cache, _tier_cache


async def get_api_key_cache() -> TTLCache:
    cache, _ = _init_caches()
    return cache


async def get_tier_cache() -> TTLCache:
    _, cache = _init_caches()
    return cache


async def invalidate_key(key_id: str) -> None:
    await _init_caches()[0].delete(f"key:{key_id}")


async def invalidate_tier(tier: str) -> None:
    await _init_caches()[1].delete(f"tier:{tier}")


async def clear_caches() -> None:
    await _init_caches()[0].clear()
    await _init_caches()[1].clear()
