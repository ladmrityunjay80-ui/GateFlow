from __future__ import annotations

import pytest

from gateflow.auth import AuthError, _is_ip_allowed, authenticate


@pytest.mark.anyio
async def test_authenticate_valid_key(seeded_data):
    record, tier, key_id = await authenticate(seeded_data)
    assert record.user_id == "usr_test_123"
    assert record.tier == "premium"
    assert record.active == 1
    assert tier.capacity == 100
    assert tier.refill_rate == 20.0
    assert key_id


@pytest.mark.anyio
async def test_authenticate_invalid_key(redis_client, db_init):
    with pytest.raises(AuthError) as exc:
        await authenticate("nonexistent-key")
    assert exc.value.status_code == 401


@pytest.mark.anyio
async def test_authenticate_inactive_key(redis_client, db_init):
    from gateflow.crypto import hash_api_key

    key = "inactive-key"
    key_id = hash_api_key(key)
    await redis_client.hset(f"gateflow:auth:keys:{key_id}", mapping={
        "user_id": "usr_inactive",
        "tier": "free",
        "active": "0",
        "expires_at": "9999999999",
        "rate_limit_custom": "-1",
        "request_count_lifetime": "0",
    })
    with pytest.raises(AuthError) as exc:
        await authenticate(key)
    assert exc.value.status_code == 401
    await redis_client.delete(f"gateflow:auth:keys:{key_id}")


def test_is_ip_allowed():
    assert _is_ip_allowed("192.168.1.42", "") is True
    assert _is_ip_allowed("192.168.1.42", "*") is True
    assert _is_ip_allowed("192.168.1.42", "192.168.1.42") is True
    assert _is_ip_allowed("192.168.1.42", "192.168.1.0/24") is True
    assert _is_ip_allowed("10.0.0.1", "192.168.1.0/24,10.0.0.0/8") is True
    assert _is_ip_allowed("192.168.1.42", "10.0.0.0/8") is False
    assert _is_ip_allowed("not-an-ip", "192.168.1.0/24") is False


@pytest.mark.anyio
async def test_authenticate_ip_allow_list(redis_client, db_init):
    from gateflow.crypto import hash_api_key

    key = "ip-restricted-key"
    key_id = hash_api_key(key)
    await redis_client.hset(f"gateflow:auth:keys:{key_id}", mapping={
        "user_id": "usr_ip",
        "tier": "free",
        "active": "1",
        "expires_at": "9999999999",
        "rate_limit_custom": "-1",
        "request_count_lifetime": "0",
        "allowed_ips": "192.168.1.0/24",
    })

    record, tier, _ = await authenticate(key, "192.168.1.42")
    assert record.user_id == "usr_ip"

    with pytest.raises(AuthError) as exc:
        await authenticate(key, "10.0.0.1")
    assert exc.value.status_code == 403

    await redis_client.delete(f"gateflow:auth:keys:{key_id}")
