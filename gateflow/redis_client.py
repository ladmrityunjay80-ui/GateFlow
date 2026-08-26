from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from typing import TYPE_CHECKING, Any

import redis.asyncio as redis

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .cache import invalidate_key, invalidate_tier
from .config import get_settings
from .constants import RedisKeys
from .models import Route

if TYPE_CHECKING:
    from redis.asyncio.client import Redis


logger = logging.getLogger("gateflow.redis_client")


TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])

local bucket = redis.call('HMGET', key, 'tokens', 'last_time')
local tokens = tonumber(bucket[1])
local last_time = tonumber(bucket[2])
local time = redis.call('TIME')
local now = tonumber(time[1]) + tonumber(time[2]) / 1000000

if tokens == nil then
    tokens = capacity
    last_time = now
end

local delta = now - last_time
local new_tokens = math.min(capacity, tokens + delta * refill_rate)
local allowed = 0
local retry_after = 0

if new_tokens >= cost then
    new_tokens = new_tokens - cost
    allowed = 1
else
    retry_after = (cost - new_tokens) / refill_rate
end

redis.call('HSET', key, 'tokens', tostring(new_tokens), 'last_time', tostring(now))

local ttl = 86400
if refill_rate > 0 then
    ttl = math.ceil(capacity / refill_rate) + 60
end
redis.call('EXPIRE', key, ttl)

return {tostring(allowed), tostring(new_tokens), tostring(retry_after)}
"""

CIRCUIT_BREAKER_LUA = """
local key = KEYS[1]
local op = ARGV[1]
local result = ARGV[2]
local threshold = tonumber(ARGV[3])
local window = tonumber(ARGV[4])
local open_dur = tonumber(ARGV[5])

local time = redis.call('TIME')
local now = tonumber(time[1]) + tonumber(time[2]) / 1000000

local state_data = redis.call('HMGET', key, 'state', 'failure_count', 'last_failure')
local state = state_data[1]
local failure_count = tonumber(state_data[2]) or 0
local last_failure = tonumber(state_data[3]) or 0

local ttl = math.ceil(open_dur + window) + 60

if not state or state == '' then
    state = 'CLOSED'
end

if op == 'check' then
    if state == 'OPEN' then
        if now - last_failure >= open_dur then
            redis.call('HMSET', key, 'state', 'HALF_OPEN', 'failure_count', '0')
            redis.call('EXPIRE', key, ttl)
            return {'HALF_OPEN', '0'}
        else
            redis.call('EXPIRE', key, ttl)
            return {'OPEN', tostring(open_dur - (now - last_failure))}
        end
    end
    redis.call('EXPIRE', key, ttl)
    return {state, '0'}
end

if op == 'report' then
    if result == 'success' then
        redis.call('HMSET', key, 'state', 'CLOSED', 'failure_count', '0', 'last_success', tostring(now))
        redis.call('EXPIRE', key, ttl)
        return {'CLOSED'}
    end

    if state == 'HALF_OPEN' then
        redis.call('HMSET', key, 'state', 'OPEN', 'failure_count', '1', 'last_failure', tostring(now))
        redis.call('EXPIRE', key, ttl)
        return {'OPEN'}
    end

    if now - last_failure > window then
        failure_count = 1
    else
        failure_count = failure_count + 1
    end
    last_failure = now

    if failure_count >= threshold then
        state = 'OPEN'
    end

    redis.call(
        'HMSET', key, 'state', state,
        'failure_count', tostring(failure_count),
        'last_failure', tostring(last_failure)
    )
    redis.call('EXPIRE', key, ttl)
    return {state, tostring(failure_count)}
end
"""

ROTATE_KEY_LUA = """
local new_key = KEYS[1]
local old_key = KEYS[2]
local channel = KEYS[3]
local old_id = ARGV[1]

if redis.call('EXISTS', new_key) == 1 then
    return {0, 'exists'}
end

for i = 2, #ARGV, 2 do
    redis.call('HSET', new_key, ARGV[i], ARGV[i + 1])
end

redis.call('DEL', old_key)
redis.call('PUBLISH', channel, 'key:' .. old_id)

return {1, 'ok'}
"""

MONTHLY_QUOTA_RESERVE_LUA = """
local key = KEYS[1]
local quota = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])

local current = redis.call('GET', key)
if current and tonumber(current) >= quota then
    return {0, current}
end

local new = redis.call('INCR', key)
if new == 1 then
    redis.call('EXPIRE', key, ttl)
end

if new > quota then
    redis.call('DECR', key)
    return {0, tostring(new - 1)}
end

return {1, tostring(new)}
"""

MONTHLY_QUOTA_REFUND_LUA = """
local key = KEYS[1]
local new = redis.call('DECR', key)
if new < 0 then
    redis.call('SET', key, 0)
    return {0}
end
return {tostring(new)}
"""


def _parse_sentinels(value: str) -> list[tuple[str, int]]:
    if not value:
        return []
    nodes: list[tuple[str, int]] = []
    for part in value.split(","):
        host, _, port_str = part.strip().partition(":")
        if not host:
            continue
        port = int(port_str) if port_str else 26379
        nodes.append((host, port))
    return nodes


def _build_redis_client(settings) -> tuple[Redis, Any | None]:
    connection_kwargs: dict[str, Any] = {
        "decode_responses": True,
        "socket_connect_timeout": settings.redis_socket_connect_timeout,
        "socket_timeout": settings.redis_socket_timeout,
        "health_check_interval": settings.redis_health_check_interval,
        "socket_keepalive": settings.redis_socket_keepalive,
        "max_connections": 200,
    }

    if settings.redis_username:
        connection_kwargs["username"] = settings.redis_username
    if settings.redis_password:
        connection_kwargs["password"] = settings.redis_password

    if settings.redis_ssl:
        connection_kwargs["ssl"] = True
        if settings.redis_ssl_certfile:
            connection_kwargs["ssl_certfile"] = settings.redis_ssl_certfile
        if settings.redis_ssl_keyfile:
            connection_kwargs["ssl_keyfile"] = settings.redis_ssl_keyfile
        if settings.redis_ssl_ca_certs:
            connection_kwargs["ssl_ca_certs"] = settings.redis_ssl_ca_certs

    sentinel_nodes = _parse_sentinels(settings.redis_sentinels)
    if sentinel_nodes:
        sentinel = redis.sentinel.Sentinel(
            sentinel_nodes,
            sentinel_kwargs=connection_kwargs,
            **connection_kwargs,
        )
        master = sentinel.master_for(
            settings.redis_service_name,
            redis_class=redis.Redis,
            **connection_kwargs,
        )
        return master, sentinel

    client = redis.from_url(settings.redis_url, **connection_kwargs)
    return client, None


class RedisManager:
    _client: Redis | None = None
    _sentinel: Any | None = None
    _scripts: dict[str, str] = {}
    _route_cache: dict[str, Route] = {}
    _pubsub_task: asyncio.Task | None = None
    _health_task: asyncio.Task | None = None
    _closing: bool = False
    _reconnect_lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    async def connect(cls) -> None:
        cls._closing = False
        await cls._initialize_client()
        cls._pubsub_task = asyncio.create_task(cls._route_reload_listener())
        cls._health_task = asyncio.create_task(cls._health_check_loop())

    @classmethod
    async def _initialize_client(cls) -> None:
        settings = get_settings()
        cls._client, cls._sentinel = _build_redis_client(settings)
        await cls._client.ping()
        await cls._load_scripts()
        await cls._refresh_routes()

    @classmethod
    async def close(cls) -> None:
        cls._closing = True
        for task in (cls._pubsub_task, cls._health_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if cls._client:
            await cls._client.aclose()  # type: ignore[attr-defined]
            cls._client = None
        if cls._sentinel:
            for sentinel_client in cls._sentinel.sentinels:
                await sentinel_client.aclose()  # type: ignore[attr-defined]
            cls._sentinel = None

    @classmethod
    def client(cls) -> Redis:
        if cls._client is None:
            raise RuntimeError("Redis client is not connected")
        return cls._client

    @classmethod
    def scripts(cls) -> dict[str, str]:
        return cls._scripts

    @classmethod
    def routes(cls) -> dict[str, Route]:
        return cls._route_cache

    @classmethod
    async def _load_scripts(cls) -> None:
        client = cls.client()
        cls._scripts["token_bucket"] = await client.script_load(TOKEN_BUCKET_LUA)
        cls._scripts["circuit_breaker"] = await client.script_load(CIRCUIT_BREAKER_LUA)
        cls._scripts["rotate_key"] = await client.script_load(ROTATE_KEY_LUA)
        cls._scripts["monthly_quota_reserve"] = await client.script_load(MONTHLY_QUOTA_RESERVE_LUA)
        cls._scripts["monthly_quota_refund"] = await client.script_load(MONTHLY_QUOTA_REFUND_LUA)

    @classmethod
    async def _refresh_routes(cls) -> None:
        # The database is the source of truth; Redis is a hot cache.
        from .store import list_routes

        try:
            routes = await list_routes()
        except Exception as exc:
            logger.warning("refresh_routes_db_failed", extra={"error": str(exc)})
            client = cls.client()
            raw_routes = await client.hgetall(RedisKeys.ROUTES_HASH)
            routes = {}
            for prefix, raw in raw_routes.items():
                try:
                    routes[prefix] = Route.from_json(prefix, raw)
                except (json.JSONDecodeError, KeyError):
                    continue

        cls._route_cache = routes

    @classmethod
    async def reload_routes(cls) -> None:
        await cls._refresh_routes()
        client = cls.client()
        await client.publish(RedisKeys.RELOAD_CHANNEL, "refresh")

    @classmethod
    async def _route_reload_listener(cls) -> None:
        while not cls._closing:
            try:
                client = cls.client()
                async with client.pubsub() as pubsub:
                    await pubsub.subscribe(RedisKeys.RELOAD_CHANNEL, RedisKeys.CACHE_INVALIDATE_CHANNEL)
                    async for message in pubsub.listen():
                        if cls._closing:
                            break
                        if message["type"] != "message":
                            continue
                        channel = message.get("channel", "")
                        if isinstance(channel, bytes):
                            channel = channel.decode()
                        data = message.get("data", "")
                        if isinstance(data, bytes):
                            data = data.decode()
                        if channel == RedisKeys.RELOAD_CHANNEL:
                            await cls._refresh_routes()
                        elif channel == RedisKeys.CACHE_INVALIDATE_CHANNEL:
                            if data.startswith("key:"):
                                await invalidate_key(data[4:])
                            elif data.startswith("tier:"):
                                await invalidate_tier(data[5:])
            except redis.ConnectionError:
                if cls._closing:
                    break
                await cls._reconnect()
            except asyncio.CancelledError:
                raise
            except Exception:
                if cls._closing:
                    break
                await asyncio.sleep(1.0)

    @classmethod
    async def _health_check_loop(cls) -> None:
        while not cls._closing:
            try:
                await asyncio.sleep(get_settings().redis_health_check_interval / 2.0)
                client = cls.client()
                await client.ping()
            except asyncio.CancelledError:
                break
            except Exception:
                if cls._closing:
                    break
                await cls._reconnect()

    @classmethod
    async def _reconnect(cls) -> None:
        async with cls._reconnect_lock:
            if cls._closing:
                return
            old_client = cls._client
            try:
                await cls._initialize_client()
            except Exception:
                # Restore previous client so callers don't see None.
                cls._client = old_client
                raise
            if old_client and old_client is not cls._client:
                await old_client.aclose()  # type: ignore[attr-defined]
