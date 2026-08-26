from __future__ import annotations


class RedisKeys:
    """Central Redis key and stream names for GateFlow."""

    AUTH_KEY_PREFIX = "gateflow:auth:keys:"
    TIER_PREFIX = "gateflow:tiers:"
    ROUTES_HASH = "gateflow:routes"
    RATE_LIMIT_PREFIX = "gateflow:rl:"
    CIRCUIT_PREFIX = "gateflow:cb:"

    METRICS_STREAM = "gateflow:metrics"
    ANOMALIES_STREAM = "gateflow:anomalies"
    ANOMALIES_DEAD_LETTER = "gateflow:anomalies:dead_letter"
    AUDIT_ADMIN_STREAM = "gateflow:audit:admin"
    TIER_REQUESTS_STREAM = "gateflow:tier_requests"

    CACHE_INVALIDATE_CHANNEL = "gateflow:cache:invalidate"
    RELOAD_CHANNEL = "gateflow:reload"

    MONTHLY_PREFIX = "gateflow:governance:monthly:"
    IDEMPOTENCY_PREFIX = "gateflow:idempotency:"

    NOTIFICATION_CONSUMER_GROUP = "gateflow-notifiers"
