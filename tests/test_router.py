from __future__ import annotations

import pytest

from gateflow.models import Route
from gateflow.redis_client import RedisManager
from gateflow.router import build_downstream_path, match_route


@pytest.fixture
async def route_cache(redis_client):
    RedisManager._client = redis_client
    RedisManager._route_cache = {}

    routes = [
        Route(
            prefix="users",
            target_url="http://users-service:8000",
            fallback_url=None,
            strip_prefix=True,
            requires_auth=True,
            allowed_methods={"GET", "POST"},
        ),
        Route(
            prefix="v1/users",
            target_url="http://users-v1:8000",
            fallback_url=None,
            strip_prefix=True,
            requires_auth=True,
            allowed_methods={"GET"},
        ),
    ]
    for route in routes:
        RedisManager._route_cache[route.prefix] = route

    yield

    RedisManager._route_cache = {}


@pytest.mark.anyio
async def test_match_longest_prefix(route_cache):
    route = match_route("/v1/users/123")
    assert route is not None
    assert route.prefix == "v1/users"


@pytest.mark.anyio
async def test_build_downstream_path_strip(route_cache):
    route = match_route("/users/profile")
    assert route is not None
    path = build_downstream_path(route, "/users/profile")
    assert path == "/profile"
