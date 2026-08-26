from __future__ import annotations

import os
import sys
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    __package__ = "gateflow.admin"

from ..audit import log_admin_async
from ..models import TierConfig
from ..store import delete_tier_config, get_tier_config, list_tier_configs, save_tier_config
from .common import require_admin_read, require_admin_write

router = APIRouter(tags=["admin:tiers"])


class TierPayload(BaseModel):
    capacity: int
    refill_rate: float
    window_info: str = "1s"
    monthly_quota: int = -1


class TierOut(TierPayload):
    tier: str


@router.get("/tiers")
async def list_all_tiers(admin_key: str = Depends(require_admin_read)) -> dict[str, Any]:
    tiers = await list_tier_configs()
    out = [{"tier": name, **config.model_dump()} for name, config in tiers.items()]
    log_admin_async("list", "tiers", admin_key, {"count": len(out)})
    return {"tiers": out, "count": len(out)}


@router.get("/tiers/{tier}")
async def get_existing_tier(tier: str, admin_key: str = Depends(require_admin_read)) -> TierOut:
    config = await get_tier_config(tier)
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found")
    log_admin_async("read", f"tiers:{tier}", admin_key)
    return TierOut(tier=tier, **config.model_dump())


@router.post("/tiers/{tier}", status_code=status.HTTP_201_CREATED)
async def create_tier(tier: str, payload: TierPayload, admin_key: str = Depends(require_admin_write)) -> TierOut:
    if await get_tier_config(tier):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tier already exists")
    config = TierConfig.model_validate(payload.model_dump())
    await save_tier_config(tier, config)
    log_admin_async("create", f"tiers:{tier}", admin_key, {"capacity": config.capacity})
    return TierOut(tier=tier, **config.model_dump())


@router.put("/tiers/{tier}")
async def update_tier(tier: str, payload: TierPayload, admin_key: str = Depends(require_admin_write)) -> TierOut:
    if not await get_tier_config(tier):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found")
    config = TierConfig.model_validate(payload.model_dump())
    await save_tier_config(tier, config)
    log_admin_async("update", f"tiers:{tier}", admin_key, {"capacity": config.capacity})
    return TierOut(tier=tier, **config.model_dump())


@router.delete("/tiers/{tier}")
async def remove_tier(tier: str, admin_key: str = Depends(require_admin_write)) -> dict:
    if not await delete_tier_config(tier):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found")
    log_admin_async("delete", f"tiers:{tier}", admin_key)
    return {"deleted": tier}


def _to_hash(config: TierConfig) -> dict[str, Any]:
    return {
        "capacity": str(config.capacity),
        "refill_rate": str(config.refill_rate),
        "window_info": config.window_info,
        "monthly_quota": str(config.monthly_quota),
    }
