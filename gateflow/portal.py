from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .auth import authenticate, get_client_ip
from .crypto import hash_api_key
from .governance import get_monthly_usage
from .store import create_tier_request, delete_key_record, get_key_record, save_key_record

router = APIRouter(tags=["developer-portal"])

_STATIC_DIR = Path(__file__).parent / "static"


@router.get("/api/me/quota")
async def get_my_quota(
    request: Request,
    x_api_key: str | None = Header(None, alias="X-API-KEY"),
) -> dict:
    """Return the calling key's quota and usage information."""
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-API-KEY")

    record, tier, _key_id = await authenticate(x_api_key, get_client_ip(request))
    if not record or not tier:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    monthly_used = await get_monthly_usage(record.user_id)
    return {
        "user_id": record.user_id,
        "tier": record.tier,
        "capacity": tier.capacity,
        "refill_rate": tier.refill_rate,
        "window_info": tier.window_info,
        "monthly_quota": tier.monthly_quota,
        "monthly_used": monthly_used,
        "request_count_lifetime": record.request_count_lifetime,
        "active": record.active,
        "expires_at": record.expires_at,
        "rate_limit_custom": record.rate_limit_custom,
        "rate_limit_custom_refill": record.rate_limit_custom_refill,
    }


@router.post("/api/me/keys/rotate")
async def rotate_api_key(
    request: Request,
    x_api_key: str | None = Header(None, alias="X-API-KEY"),
) -> dict:
    """Rotate the calling API key in-place and return the new key.

    The existing key record is preserved (user, tier, quotas) while the old
    hash is replaced with a new one. Consumers should update `X-API-KEY` to
    the new value immediately.
    """
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-API-KEY")

    record, _tier, old_id = await authenticate(x_api_key, get_client_ip(request))
    if not record:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    new_key = "gf_" + secrets.token_urlsafe(32)
    new_id = hash_api_key(new_key)

    if await get_key_record(new_id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Key collision, retry")

    await save_key_record(new_id, record)
    await delete_key_record(old_id)

    return {"api_key": new_key, "user_id": record.user_id, "tier": record.tier}


@router.post("/api/me/tier/request")
async def request_tier(
    request: Request,
    x_api_key: str | None = Header(None, alias="X-API-KEY"),
    requested_tier: str = "",
    reason: str = "",
) -> dict:
    """Submit a tier change request for admin review."""
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-API-KEY")

    record, _tier, _key_id = await authenticate(x_api_key, get_client_ip(request))
    if not record:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    row = await create_tier_request(
        record.user_id,
        record.tier,
        requested_tier,
        reason,
    )
    return {
        "status": "submitted",
        "request": {
            "id": row.id,
            "user_id": row.user_id,
            "current_tier": row.current_tier,
            "requested_tier": row.requested_tier,
            "reason": row.reason,
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        },
    }


@router.get("/api/me/openapi", response_class=HTMLResponse)
async def openapi_ui() -> str:
    """Serve a Swagger UI pointing at the merged OpenAPI specification."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>GateFlow API Docs</title>
  <link rel="stylesheet" href="/static/swagger-ui/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="/static/swagger-ui/swagger-ui-bundle.js"></script>
  <script src="/static/swagger-ui/swagger-ui-standalone-preset.js"></script>
  <script>
    window.ui = SwaggerUIBundle({
      url: '/openapi.json',
      dom_id: '#swagger-ui',
      deepLinking: true,
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
      plugins: [SwaggerUIBundle.plugins.DownloadUrl]
    });
  </script>
</body>
</html>"""


@router.get("/api/me/portal")
async def portal_index(x_api_key: str | None = Header(None, alias="X-API-KEY")) -> dict:
    """Developer portal discovery endpoint."""
    return {
        "message": "Developer portal is available",
        "endpoints": {
            "ui": "/portal",
            "quota": "/api/me/quota",
            "rotate_key": "/api/me/keys/rotate",
            "request_tier": "/api/me/tier/request",
            "openapi_ui": "/api/me/openapi",
        },
    }


@router.get("/portal", response_class=HTMLResponse)
async def portal_page() -> str:
    """Serve the developer portal static HTML page."""
    path = _STATIC_DIR / "portal" / "index.html"
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portal UI not found")
    return path.read_text(encoding="utf-8")
