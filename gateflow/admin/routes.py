from __future__ import annotations

import os
import sys
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    __package__ = "gateflow.admin"

from ..audit import log_admin_async
from ..models import Route, normalise_prefix
from ..store import delete_route, get_route, list_routes, save_route
from .common import require_admin_read, require_admin_write

router = APIRouter(tags=["admin:routes"])


class RoutePayload(BaseModel):
    target_url: HttpUrl
    fallback_url: HttpUrl | None = None
    strip_prefix: bool = True
    requires_auth: bool = True
    allowed_methods: str = "*"


class RouteOut(BaseModel):
    prefix: str
    target_url: str
    fallback_url: str | None
    strip_prefix: bool
    requires_auth: bool
    allowed_methods: str


@router.get("/routes")
async def list_all_routes(admin_key: str = Depends(require_admin_read)) -> dict[str, Any]:
    routes = await list_routes()
    log_admin_async("list", "routes", admin_key, {"count": len(routes)})
    return {"routes": {prefix: _to_out(route) for prefix, route in routes.items()}}


@router.get("/routes/{prefix}")
async def get_existing_route(prefix: str, admin_key: str = Depends(require_admin_read)) -> RouteOut:
    try:
        prefix = normalise_prefix(prefix)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    route = await get_route(prefix)
    if not route:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
    log_admin_async("read", f"routes:{prefix}", admin_key)
    return _to_out(route)


@router.post("/routes/{prefix}", status_code=status.HTTP_201_CREATED)
async def create_route(prefix: str, payload: RoutePayload, admin_key: str = Depends(require_admin_write)) -> RouteOut:
    try:
        prefix = normalise_prefix(prefix)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    existing = await get_route(prefix)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Route already exists")
    route = Route(
        prefix=prefix,
        target_url=str(payload.target_url).rstrip("/"),
        fallback_url=str(payload.fallback_url).rstrip("/") if payload.fallback_url else None,
        strip_prefix=payload.strip_prefix,
        requires_auth=payload.requires_auth,
        allowed_methods=_parse_methods(payload.allowed_methods),
    )
    await save_route(route)
    log_admin_async("create", f"routes:{prefix}", admin_key, {"target_url": route.target_url})
    return _to_out(route)


@router.put("/routes/{prefix}")
async def update_route(prefix: str, payload: RoutePayload, admin_key: str = Depends(require_admin_write)) -> RouteOut:
    try:
        prefix = normalise_prefix(prefix)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not await get_route(prefix):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
    route = Route(
        prefix=prefix,
        target_url=str(payload.target_url).rstrip("/"),
        fallback_url=str(payload.fallback_url).rstrip("/") if payload.fallback_url else None,
        strip_prefix=payload.strip_prefix,
        requires_auth=payload.requires_auth,
        allowed_methods=_parse_methods(payload.allowed_methods),
    )
    await save_route(route)
    log_admin_async("update", f"routes:{prefix}", admin_key, {"target_url": route.target_url})
    return _to_out(route)


@router.delete("/routes/{prefix}")
async def remove_route(prefix: str, admin_key: str = Depends(require_admin_write)) -> dict:
    try:
        prefix = normalise_prefix(prefix)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not await delete_route(prefix):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
    log_admin_async("delete", f"routes:{prefix}", admin_key)
    return {"deleted": prefix}


def _parse_methods(methods: str) -> set[str]:
    if methods.strip() == "*":
        return set()
    return {m.strip().upper() for m in methods.split(",") if m.strip()}


def _to_out(route: Route) -> RouteOut:
    methods = "*" if not route.allowed_methods else ",".join(sorted(route.allowed_methods))
    return RouteOut(
        prefix=route.prefix,
        target_url=route.target_url,
        fallback_url=route.fallback_url,
        strip_prefix=route.strip_prefix,
        requires_auth=route.requires_auth,
        allowed_methods=methods,
    )
