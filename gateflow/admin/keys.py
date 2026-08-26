from __future__ import annotations

import os
import sys
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    __package__ = "gateflow.admin"

from ..audit import log_admin_async
from ..auth import resolve_key_id
from ..crypto import hash_api_key
from ..models import APIKeyRecord
from ..store import delete_key_record, get_key_record, list_key_records, save_key_record
from .common import require_admin_read, require_admin_write

router = APIRouter(tags=["admin:keys"])


class KeyPayload(BaseModel):
    user_id: str
    tier: str
    active: int = Field(..., ge=0, le=1)
    expires_at: int | None = None
    rate_limit_custom: int = -1
    rate_limit_custom_refill: int | None = None
    request_count_lifetime: int = 0
    # Comma-separated list of allowed IPs or CIDRs. Empty or "*" allows all.
    allowed_ips: str = ""


class KeyOut(KeyPayload):
    api_key: str


@router.get("/keys")
async def list_keys(admin_key: str = Depends(require_admin_read)) -> dict[str, Any]:
    records = await list_key_records()
    items = [{"api_key": key, **record.model_dump()} for key, record in records.items()]
    log_admin_async("list", "keys", admin_key, {"count": len(items)})
    return {"keys": items, "count": len(items)}


async def _resolve_or_404(api_key: str) -> str:
    resolved = await resolve_key_id(api_key)
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    return resolved[0]


@router.get("/keys/{api_key}")
async def get_key(api_key: str, admin_key: str = Depends(require_admin_read)) -> dict[str, Any]:
    key_id = await _resolve_or_404(api_key)
    record = await get_key_record(key_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    log_admin_async("read", f"keys:{key_id}", admin_key, {"user_id": record.user_id, "tier": record.tier})
    return {"api_key": key_id, **record.model_dump()}


@router.post("/keys/{api_key}", status_code=status.HTTP_201_CREATED)
async def create_key(
    api_key: str, payload: KeyPayload, admin_key: str = Depends(require_admin_write)
) -> dict[str, Any]:
    # Prevent creating a key whose string already matches an existing record
    # under any secret version.
    existing = await resolve_key_id(api_key)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="API key already exists")
    key_id = hash_api_key(api_key)
    record = APIKeyRecord.model_validate(payload.model_dump())
    await save_key_record(key_id, record)
    log_admin_async("create", f"keys:{key_id}", admin_key, {"user_id": record.user_id, "tier": record.tier})
    return {"api_key": key_id, **record.model_dump()}


@router.put("/keys/{api_key}")
async def update_key(
    api_key: str, payload: KeyPayload, admin_key: str = Depends(require_admin_write)
) -> dict[str, Any]:
    key_id = await _resolve_or_404(api_key)
    record = APIKeyRecord.model_validate(payload.model_dump())
    await save_key_record(key_id, record)
    log_admin_async("update", f"keys:{key_id}", admin_key, {"user_id": record.user_id, "tier": record.tier})
    return {"api_key": key_id, **record.model_dump()}


@router.delete("/keys/{api_key}")
async def delete_key(api_key: str, admin_key: str = Depends(require_admin_write)) -> dict:
    key_id = await _resolve_or_404(api_key)
    await delete_key_record(key_id)
    log_admin_async("delete", f"keys:{key_id}", admin_key)
    return {"deleted": key_id}
