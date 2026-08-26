from __future__ import annotations

import hashlib
import os
import sys

from fastapi import Header, HTTPException, status

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    __package__ = "gateflow.admin"

from ..config import get_settings
from ..crypto import constant_time_compare
from ..rate_limiter import check_rate_limit


def _admin_authorized(key: str | None, allowed: list[str]) -> bool:
    if not key:
        return False
    return any(constant_time_compare(key, k) for k in allowed if k)


def _read_keys(settings) -> list[str]:
    extra = [k.strip() for k in settings.admin_read_keys.split(",") if k.strip()]
    return [settings.admin_key, *extra]


async def _check_admin_rate_limit(admin_key: str) -> None:
    settings = get_settings()
    if not settings.admin_rate_limit_enabled or not admin_key:
        return
    key_id = hashlib.sha256(admin_key.encode()).hexdigest()
    result = await check_rate_limit(
        key_id,
        "admin",
        settings.admin_rate_limit_capacity,
        settings.admin_rate_limit_refill_rate,
    )
    if not result.allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Admin rate limit exceeded")


async def require_admin_write(x_admin_api_key: str | None = Header(None, alias="X-Admin-API-Key")) -> str:
    settings = get_settings()
    if x_admin_api_key:
        await _check_admin_rate_limit(x_admin_api_key)
    if not _admin_authorized(x_admin_api_key, [settings.admin_key]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing admin key")
    assert x_admin_api_key is not None
    return x_admin_api_key


async def require_admin_read(x_admin_api_key: str | None = Header(None, alias="X-Admin-API-Key")) -> str:
    settings = get_settings()
    if x_admin_api_key:
        await _check_admin_rate_limit(x_admin_api_key)
    if not _admin_authorized(x_admin_api_key, _read_keys(settings)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing admin key")
    assert x_admin_api_key is not None
    return x_admin_api_key

