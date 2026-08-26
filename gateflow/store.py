from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .cache import invalidate_key, invalidate_tier
from .constants import RedisKeys
from .crypto import hash_api_key
from .db import (
    APIKeyRecordDB,
    AuditEventDB,
    RouteDB,
    TierConfigDB,
    TierRequestDB,
    UsageDailyDB,
    _get_session_maker,
)
from .models import APIKeyRecord, Route, TierConfig
from .redis_client import RedisManager

logger = logging.getLogger("gateflow.store")


@asynccontextmanager
async def _session() -> AsyncIterator[AsyncSession]:
    maker = _get_session_maker()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _to_record(row: APIKeyRecordDB) -> APIKeyRecord:
    return APIKeyRecord(
        user_id=row.user_id,
        tier=row.tier,
        active=row.active,
        expires_at=row.expires_at,
        rate_limit_custom=row.rate_limit_custom,
        rate_limit_custom_refill=row.rate_limit_custom_refill,
        request_count_lifetime=row.request_count_lifetime,
        allowed_ips=row.allowed_ips or "",
    )


def _row_from_record(key_hash: str, record: APIKeyRecord) -> APIKeyRecordDB:
    return APIKeyRecordDB(
        key_hash=key_hash,
        user_id=record.user_id,
        tier=record.tier,
        active=record.active,
        expires_at=record.expires_at,
        rate_limit_custom=record.rate_limit_custom,
        rate_limit_custom_refill=record.rate_limit_custom_refill,
        request_count_lifetime=record.request_count_lifetime,
        allowed_ips=record.allowed_ips or "",
    )


async def _cache_key(client: Any, key_hash: str, record: APIKeyRecord) -> None:
    await client.hset(
        f"{RedisKeys.AUTH_KEY_PREFIX}{key_hash}",
        mapping=record.to_hash(),
    )


async def _cache_tier(client: Any, tier_name: str, tier: TierConfig) -> None:
    await client.hset(
        f"{RedisKeys.TIER_PREFIX}{tier_name}",
        mapping=tier.model_dump(mode="json"),
    )


async def get_key_record(key_hash: str) -> APIKeyRecord | None:
    """Return the API key record from the database, falling back to Redis cache."""
    async with _session() as session:
        result = await session.execute(select(APIKeyRecordDB).where(APIKeyRecordDB.key_hash == key_hash))
        row = result.scalar_one_or_none()
        if row is not None:
            return _to_record(row)

    # Fallback: if the record only exists in Redis (e.g. during migration),
    # backfill it into the database so the durable store becomes authoritative.
    try:
        client = RedisManager.client()
        raw = await client.hgetall(f"{RedisKeys.AUTH_KEY_PREFIX}{key_hash}")
    except Exception as exc:
        logger.debug("redis_key_lookup_failed", extra={"error": str(exc)})
        return None
    if not raw:
        return None
    record = APIKeyRecord.model_validate(raw)
    try:
        await save_key_record(key_hash, record)
    except Exception as exc:
        logger.warning("key_backfill_failed", extra={"error": str(exc)})
    return record


async def increment_request_count(key_hash: str, delta: int = 1) -> None:
    """Atomically increment the lifetime request counter and refresh the cache."""
    async with _session() as session:
        await session.execute(
            update(APIKeyRecordDB)
            .where(APIKeyRecordDB.key_hash == key_hash)
            .values(request_count_lifetime=APIKeyRecordDB.request_count_lifetime + delta)
        )

    try:
        client = RedisManager.client()
        await client.hincrby(f"{RedisKeys.AUTH_KEY_PREFIX}{key_hash}", "request_count_lifetime", delta)
        await invalidate_key(key_hash)
    except Exception as exc:
        logger.debug("increment_request_count_cache_failed", extra={"error": str(exc)})


async def get_key_record_with_fallback(key_hash: str) -> APIKeyRecord | None:
    """Return the API key record from the database, hydrating Redis cache if found."""
    record = await get_key_record(key_hash)
    if record is not None:
        client = RedisManager.client()
        await _cache_key(client, key_hash, record)
    return record


async def save_key_record(key_hash: str, record: APIKeyRecord) -> None:
    """Persist an API key record to the database and Redis cache."""
    async with _session() as session:
        result = await session.execute(select(APIKeyRecordDB).where(APIKeyRecordDB.key_hash == key_hash))
        existing = result.scalar_one_or_none()
        if existing:
            existing.user_id = record.user_id
            existing.tier = record.tier
            existing.active = record.active
            existing.expires_at = record.expires_at
            existing.rate_limit_custom = record.rate_limit_custom
            existing.rate_limit_custom_refill = record.rate_limit_custom_refill
            existing.request_count_lifetime = record.request_count_lifetime
            existing.allowed_ips = record.allowed_ips or ""
        else:
            session.add(_row_from_record(key_hash, record))

    client = RedisManager.client()
    await _cache_key(client, key_hash, record)
    try:
        await invalidate_key(key_hash)
    except Exception as exc:
        logger.debug("cache_invalidate_failed", extra={"error": str(exc)})


async def delete_key_record(key_hash: str) -> bool:
    """Delete an API key record from the database and Redis cache."""
    deleted = False
    async with _session() as session:
        result = await session.execute(select(APIKeyRecordDB).where(APIKeyRecordDB.key_hash == key_hash))
        row = result.scalar_one_or_none()
        if row is not None:
            await session.delete(row)
            deleted = True

    if deleted:
        client = RedisManager.client()
        await client.delete(f"{RedisKeys.AUTH_KEY_PREFIX}{key_hash}")
        try:
            await invalidate_key(key_hash)
        except Exception as exc:
            logger.debug("cache_invalidate_failed", extra={"error": str(exc)})
    return deleted


async def list_key_records() -> dict[str, APIKeyRecord]:
    """Return all API key records keyed by hash."""
    async with _session() as session:
        result = await session.execute(select(APIKeyRecordDB))
        rows = result.scalars().all()
        return {row.key_hash: _to_record(row) for row in rows}


def _to_route(row: RouteDB) -> Route:
    return Route(
        prefix=row.prefix,
        target_url=row.target_url,
        fallback_url=row.fallback_url,
        strip_prefix=row.strip_prefix,
        requires_auth=row.requires_auth,
        allowed_methods=set(row.allowed_methods) if row.allowed_methods else set(),
    )


def _row_from_route(route: Route) -> RouteDB:
    return RouteDB(
        prefix=route.prefix,
        target_url=route.target_url,
        fallback_url=route.fallback_url,
        strip_prefix=route.strip_prefix,
        requires_auth=route.requires_auth,
        allowed_methods=sorted(route.allowed_methods) if route.allowed_methods else [],
    )


async def get_route(prefix: str) -> Route | None:
    """Return a route from the database, falling back to Redis cache."""
    async with _session() as session:
        result = await session.execute(select(RouteDB).where(RouteDB.prefix == prefix))
        row = result.scalar_one_or_none()
        if row is not None:
            return _to_route(row)

    try:
        client = RedisManager.client()
        raw = await client.hget(RedisKeys.ROUTES_HASH, prefix)
    except Exception as exc:
        logger.debug("redis_route_lookup_failed", extra={"error": str(exc)})
        return None
    if not raw:
        return None
    try:
        route = Route.from_json(prefix, raw)
    except Exception:
        return None
    try:
        await save_route(route, skip_redis_publish=True)
    except Exception as exc:
        logger.warning("route_backfill_failed", extra={"error": str(exc)})
    return route


async def save_route(route: Route, skip_redis_publish: bool = False) -> None:
    """Persist a route to the database and Redis cache."""
    async with _session() as session:
        result = await session.execute(select(RouteDB).where(RouteDB.prefix == route.prefix))
        existing = result.scalar_one_or_none()
        if existing:
            existing.target_url = route.target_url
            existing.fallback_url = route.fallback_url
            existing.strip_prefix = route.strip_prefix
            existing.requires_auth = route.requires_auth
            existing.allowed_methods = sorted(route.allowed_methods) if route.allowed_methods else []
        else:
            session.add(_row_from_route(route))

    client = RedisManager.client()
    await client.hset(RedisKeys.ROUTES_HASH, route.prefix, route.to_json())
    if not skip_redis_publish:
        await RedisManager.reload_routes()


async def delete_route(prefix: str) -> bool:
    """Delete a route from the database and Redis cache."""
    deleted = False
    async with _session() as session:
        result = await session.execute(select(RouteDB).where(RouteDB.prefix == prefix))
        row = result.scalar_one_or_none()
        if row is not None:
            await session.delete(row)
            deleted = True

    client = RedisManager.client()
    await client.hdel(RedisKeys.ROUTES_HASH, prefix)
    await RedisManager.reload_routes()
    return deleted


async def list_routes() -> dict[str, Route]:
    """Return all routes keyed by prefix, falling back to Redis and backfilling."""
    async with _session() as session:
        result = await session.execute(select(RouteDB))
        rows = result.scalars().all()
        if rows:
            return {row.prefix: _to_route(row) for row in rows}

    try:
        client = RedisManager.client()
        raw_routes = await client.hgetall(RedisKeys.ROUTES_HASH)
    except Exception as exc:
        logger.debug("redis_routes_list_failed", extra={"error": str(exc)})
        raw_routes = {}

    routes: dict[str, Route] = {}
    for prefix, raw in raw_routes.items():
        try:
            routes[prefix] = Route.from_json(prefix, raw)
        except Exception:
            continue

    if routes:
        try:
            for route in routes.values():
                await save_route(route, skip_redis_publish=True)
        except Exception as exc:
            logger.warning("routes_backfill_failed", extra={"error": str(exc)})

    return routes


def _to_tier(row: TierConfigDB) -> TierConfig:
    return TierConfig(
        capacity=row.capacity,
        refill_rate=row.refill_rate,
        window_info=row.window_info,
        monthly_quota=row.monthly_quota,
    )


def _row_from_tier(tier_name: str, tier: TierConfig) -> TierConfigDB:
    return TierConfigDB(
        name=tier_name,
        capacity=tier.capacity,
        refill_rate=tier.refill_rate,
        window_info=tier.window_info,
        monthly_quota=tier.monthly_quota,
    )


async def get_tier_config(tier_name: str) -> TierConfig | None:
    """Return a tier from the database, falling back to Redis cache."""
    async with _session() as session:
        result = await session.execute(select(TierConfigDB).where(TierConfigDB.name == tier_name))
        row = result.scalar_one_or_none()
        if row is not None:
            return _to_tier(row)

    try:
        client = RedisManager.client()
        raw = await client.hgetall(f"{RedisKeys.TIER_PREFIX}{tier_name}")
    except Exception as exc:
        logger.debug("redis_tier_lookup_failed", extra={"error": str(exc)})
        return None
    if not raw:
        return None
    try:
        tier = TierConfig.model_validate(raw)
    except Exception:
        return None
    try:
        await save_tier_config(tier_name, tier, skip_redis_publish=True)
    except Exception as exc:
        logger.warning("tier_backfill_failed", extra={"error": str(exc)})
    return tier


async def save_tier_config(tier_name: str, tier: TierConfig, skip_redis_publish: bool = False) -> None:
    """Persist a tier to the database and Redis cache."""
    async with _session() as session:
        result = await session.execute(select(TierConfigDB).where(TierConfigDB.name == tier_name))
        existing = result.scalar_one_or_none()
        if existing:
            existing.capacity = tier.capacity
            existing.refill_rate = tier.refill_rate
            existing.window_info = tier.window_info
            existing.monthly_quota = tier.monthly_quota
        else:
            session.add(_row_from_tier(tier_name, tier))

    client = RedisManager.client()
    await _cache_tier(client, tier_name, tier)
    if not skip_redis_publish:
        try:
            await client.publish(RedisKeys.CACHE_INVALIDATE_CHANNEL, f"tier:{tier_name}")
            await invalidate_tier(tier_name)
        except Exception as exc:
            logger.debug("tier_cache_invalidate_failed", extra={"error": str(exc)})


async def delete_tier_config(tier_name: str) -> bool:
    """Delete a tier from the database and Redis cache."""
    deleted = False
    async with _session() as session:
        result = await session.execute(select(TierConfigDB).where(TierConfigDB.name == tier_name))
        row = result.scalar_one_or_none()
        if row is not None:
            await session.delete(row)
            deleted = True

    client = RedisManager.client()
    await client.delete(f"{RedisKeys.TIER_PREFIX}{tier_name}")
    try:
        await client.publish(RedisKeys.CACHE_INVALIDATE_CHANNEL, f"tier:{tier_name}")
        await invalidate_tier(tier_name)
    except Exception as exc:
        logger.debug("tier_cache_invalidate_failed", extra={"error": str(exc)})
    return deleted


async def list_tier_configs() -> dict[str, TierConfig]:
    """Return all tiers keyed by name, falling back to Redis and backfilling."""
    async with _session() as session:
        result = await session.execute(select(TierConfigDB))
        rows = result.scalars().all()
        if rows:
            return {row.name: _to_tier(row) for row in rows}

    try:
        client = RedisManager.client()
        cursor = 0
        raw_tiers: dict[str, dict] = {}
        while True:
            cursor, matches = await client.scan(cursor, match=f"{RedisKeys.TIER_PREFIX}*", count=100)
            for key in matches:
                tier_name = key.removeprefix(RedisKeys.TIER_PREFIX)
                raw = await client.hgetall(key)
                if raw:
                    raw_tiers[tier_name] = raw
            if cursor == 0:
                break
    except Exception as exc:
        logger.debug("redis_tiers_list_failed", extra={"error": str(exc)})
        raw_tiers = {}

    tiers: dict[str, TierConfig] = {}
    for tier_name, raw in raw_tiers.items():
        try:
            tiers[tier_name] = TierConfig.model_validate(raw)
        except Exception:
            continue

    if tiers:
        try:
            for tier_name, tier in tiers.items():
                await save_tier_config(tier_name, tier, skip_redis_publish=True)
        except Exception as exc:
            logger.warning("tiers_backfill_failed", extra={"error": str(exc)})

    return tiers


async def record_usage(
    user_id: str,
    route: str,
    day: date,
    bytes_in: int = 0,
    bytes_out: int = 0,
) -> None:
    """Increment daily usage counters for a user and route."""
    async with _session() as session:
        result = await session.execute(
            select(UsageDailyDB).where(
                UsageDailyDB.user_id == user_id,
                UsageDailyDB.route == route,
                UsageDailyDB.day == day,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.requests += 1
            row.bytes_in += bytes_in
            row.bytes_out += bytes_out
        else:
            session.add(
                UsageDailyDB(
                    user_id=user_id,
                    route=route,
                    day=day,
                    requests=1,
                    bytes_in=bytes_in,
                    bytes_out=bytes_out,
                )
            )


async def get_usage_summary(
    user_id: str,
    start: date,
    end: date,
) -> list[UsageDailyDB]:
    """Return daily usage rows for a user between two dates."""
    async with _session() as session:
        result = await session.execute(
            select(UsageDailyDB)
            .where(
                UsageDailyDB.user_id == user_id,
                UsageDailyDB.day >= start,
                UsageDailyDB.day <= end,
            )
            .order_by(UsageDailyDB.day)
        )
        return list(result.scalars().all())


async def log_audit_event(
    action: str,
    resource: str,
    x_admin_api_key: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Persist an audit event to the database and the Redis audit stream."""
    payload = dict(details) if details else {}
    actor_hash = hash_api_key(x_admin_api_key)
    async with _session() as session:
        session.add(
            AuditEventDB(
                action=action,
                resource=resource,
                admin_key_hash=actor_hash,
                payload=payload,
            )
        )

    try:
        client = RedisManager.client()
        await client.xadd(
            RedisKeys.AUDIT_ADMIN_STREAM,
            {
                "ts": str(time.time()),
                "action": action,
                "resource": resource,
                "actor_hash": actor_hash,
                **{k: str(v) for k, v in payload.items()},
            },
            maxlen=5000,
            approximate=True,
        )
    except Exception as exc:
        logger.warning("audit_redis_stream_push_failed", extra={"error": str(exc)})


async def create_tier_request(
    user_id: str,
    current_tier: str,
    requested_tier: str,
    reason: str,
) -> TierRequestDB:
    async with _session() as session:
        row = TierRequestDB(
            user_id=user_id,
            current_tier=current_tier,
            requested_tier=requested_tier,
            reason=reason,
            status="pending",
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)

    try:
        client = RedisManager.client()
        await client.xadd(
            RedisKeys.TIER_REQUESTS_STREAM,
            {
                "user_id": user_id,
                "current_tier": current_tier,
                "requested_tier": requested_tier,
                "reason": reason,
                "status": "pending",
                "id": str(row.id),
            },
            maxlen=1000,
            approximate=True,
        )
    except Exception as exc:
        logger.warning("tier_request_redis_stream_push_failed", extra={"error": str(exc)})

    return row


async def list_tier_requests(status: str | None = None, limit: int = 100) -> list[TierRequestDB]:
    async with _session() as session:
        stmt = select(TierRequestDB)
        if status:
            stmt = stmt.where(TierRequestDB.status == status)
        stmt = stmt.order_by(TierRequestDB.created_at.desc()).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def update_tier_request_status(request_id: int, status: str) -> TierRequestDB | None:
    async with _session() as session:
        result = await session.execute(select(TierRequestDB).where(TierRequestDB.id == request_id))
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.status = status
        return row
