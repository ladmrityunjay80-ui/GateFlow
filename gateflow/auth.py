from __future__ import annotations

import ipaddress
import os
import sys
import time
from typing import Any

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .crypto import _key_secrets, hash_api_key
from .models import APIKeyRecord, TierConfig
from .store import get_key_record, get_tier_config


def _is_trusted_proxy_ip(ip: str, allowed: str) -> bool:
    """Check whether an IP address is in the trusted-proxy allow list."""
    if not allowed:
        return False
    if allowed.strip() == "*":
        return True
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for cidr in allowed.split(","):
        cidr = cidr.strip()
        if not cidr:
            continue
        try:
            if address in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def _resolve_forwarded_for(forwarded: str, allowed: str) -> str | None:
    """Walk X-Forwarded-For from right to left and return the first untrusted IP.

    This mirrors Uvicorn's trusted-proxy logic: every entry after the client
    belongs to a trusted proxy, so the rightmost untrusted IP is the client.
    """
    if not allowed:
        return None
    ips = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
    if not ips:
        return None
    # Wildcard means trust all; the leftmost value is the original client.
    if allowed.strip() == "*":
        return ips[0]
    for ip in reversed(ips):
        if not _is_trusted_proxy_ip(ip, allowed):
            return ip
    # All entries are trusted proxies; fall back to the leftmost.
    return ips[0]


def get_client_ip(request) -> str | None:
    """Return the client IP, respecting trusted proxies if configured.

    Uvicorn may already resolve the real client into request.client.host.  If
    request.client is a trusted proxy (or no proxy resolution is configured),
    we inspect X-Forwarded-For and choose the rightmost untrusted hop to
    prevent header spoofing.
    """
    from .config import get_settings

    settings = get_settings()
    peer = request.client.host if request.client and request.client.host else None
    if not peer or not settings.forwarded_allow_ips:
        return peer

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded and _is_trusted_proxy_ip(peer, settings.forwarded_allow_ips):
        resolved = _resolve_forwarded_for(forwarded, settings.forwarded_allow_ips)
        if resolved:
            return resolved
    return peer


def _is_ip_allowed(client_ip: str, allowed_ips: str) -> bool:
    """Check a client IP against a comma-separated list of IPs or CIDRs."""
    rules = [r.strip() for r in allowed_ips.split(",") if r.strip()]
    if not rules or rules == ["*"]:
        return True
    try:
        address = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for rule in rules:
        try:
            if address in ipaddress.ip_network(rule, strict=False):
                return True
        except ValueError:
            continue
    return False


class AuthError(Exception):
    def __init__(self, status_code: int, detail: str, extra: dict[str, Any] | None = None):
        self.status_code = status_code
        self.detail = detail
        self.extra = extra or {}
        super().__init__(detail)


async def resolve_key_id(api_key: str) -> tuple[str, int] | None:
    """Find the stored key id for an API key across all active secrets.

    Returns the matched key id and the index of the secret that produced it,
    or None if no stored record matches any secret version. The durable
    database is authoritative, with a Redis cache fallback for migrations.
    """
    secrets = _key_secrets()
    for i, s in enumerate(secrets):
        key_id = hash_api_key(api_key, s)
        record = await get_key_record(key_id)
        if record is not None:
            return key_id, i
    return None


async def authenticate(api_key: str, client_ip: str | None = None) -> tuple[APIKeyRecord, TierConfig, str]:
    from .cache import get_api_key_cache, get_tier_cache
    from .config import get_settings

    resolved = await resolve_key_id(api_key)
    if resolved is None:
        raise AuthError(401, "Invalid or missing API key")
    key_id, _ = resolved
    key_cache_key = f"key:{key_id}"

    api_cache = await get_api_key_cache()
    cached = await api_cache.get(key_cache_key)
    if cached:
        record, tier = cached
    else:
        record = await get_key_record(key_id)
        if record is None:
            raise AuthError(401, "Invalid or missing API key")

        tier_name = record.tier
        tier_cache = await get_tier_cache()
        tier_cache_key = f"tier:{tier_name}"
        cached_tier = await tier_cache.get(tier_cache_key)
        if cached_tier:
            tier = cached_tier
        else:
            tier = await get_tier_config(tier_name)
            if tier is None:
                settings = get_settings()
                tier = TierConfig(
                    capacity=settings.default_tier_capacity,
                    refill_rate=settings.default_tier_refill_rate,
                    window_info="1s",
                )
            await tier_cache.set(tier_cache_key, tier)
        await api_cache.set(key_cache_key, (record, tier))

    if not record.active:
        raise AuthError(401, "API key is inactive")

    if record.expires_at and int(time.time()) >= record.expires_at:
        raise AuthError(401, "API key has expired")

    if record.allowed_ips and not _is_ip_allowed(client_ip or "", record.allowed_ips):
        raise AuthError(403, "API key not allowed from this IP address")

    return record, tier, key_id


def resolve_rate_limits(record: APIKeyRecord, tier: TierConfig) -> tuple[int, float]:
    if record.rate_limit_custom > 0:
        refill = record.rate_limit_custom_refill or record.rate_limit_custom
        return record.rate_limit_custom, float(refill)
    return tier.capacity, tier.refill_rate


def verify_mtls(request) -> None:
    """Enforce mutual TLS when a terminating proxy forwards certificate headers.

    If mtls_enabled is set, the request must contain the configured header
    (default X-Client-Verify) with the required value (default SUCCESS).
    """
    from .config import get_settings

    settings = get_settings()
    if not settings.mtls_enabled:
        return
    value = request.headers.get(settings.mtls_header, "")
    if value != settings.mtls_required_value:
        raise AuthError(403, "Client certificate verification failed")
