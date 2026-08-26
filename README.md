# GateFlow — Developer-Focused API Gateway & Rate-Limiter

A FastAPI + Redis API gateway that authenticates opaque API keys, performs path-prefix routing, and enforces token-bucket rate limits with atomic Lua scripts. It is designed to sit in front of microservices and handle multi-instance production deployments behind Nginx.

## Features

- **API key authentication** with one-way HMAC-SHA256 hashes at rest.
- **Constant-time admin key comparison** to resist timing attacks.
- **Audit log** for all admin operations (Redis stream `gateflow:audit:admin`).
- **Tier-based token-bucket rate limiting** via atomic Redis Lua scripts.
- **Stateful circuit breaker** with CLOSED/OPEN/HALF_OPEN state and automatic fallback.
- **Hot-reloadable route table** stored in Redis and cached in memory with pub/sub invalidation.
- **Streaming proxy** with 1 MiB max request body limits and response streaming.
- **Redis Sentinel / HA support** with health checks and transparent reconnect.
- **Telemetry** pushed asynchronously to a Redis stream (`gateflow:metrics`).
- **Structured JSON logging** and a Prometheus `/metrics` endpoint.
- **Consolidated OpenAPI** endpoint (`/openapi.json`) that merges downstream specs.
- **Admin REST API** protected by a master admin key.
- **CORS and optional mTLS/TLS** for the gateway listener.

## Architecture

```
                ┌──────────┐
Client ────────▶│  Nginx   │──┬──▶ gateflow_proxy_alpha
                └──────────┘  ├──▶ gateflow_proxy_beta
                              │
                              ▼
                        ┌──────────┐
                        │  Redis   │
                        └──────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
  users-service          orders-service       gateflow:metrics
```

## Redis Data Schemas

### `gateflow:auth:keys:{hmac_sha256(api_key)}` (Hash)

API keys are **hashed at rest** with HMAC-SHA256 using `GATEFLOW_KEY_SECRET`. Only the hash is stored.

| Field                | Type       | Example       |
|----------------------|------------|---------------|
| `user_id`            | string     | `usr_uuid4`   |
| `tier`               | string     | `free`        |
| `active`             | int        | `1`           |
| `expires_at`         | int        | `1787184000`  |
| `rate_limit_custom`  | int        | `150` or `-1` |
| `request_count_lifetime` | int    | `48590`       |

### `gateflow:tiers:{tier}` (Hash)

| Field         | Type  | Example |
|---------------|-------|---------|
| `capacity`    | int   | `15`    |
| `refill_rate` | float | `2.0`   |
| `window_info` | str   | `1s`    |

### `gateflow:routes` (Hash)

The hash key is a path prefix, e.g. `users`. The value is a JSON string:

```json
{
  "target_url": "http://users-service:8000",
  "fallback_url": null,
  "strip_prefix": true,
  "requires_auth": true,
  "allowed_methods": "GET,POST"
}
```

`allowed_methods` may be a comma-separated list or `*` for all methods.

### `gateflow:rl:{api_key}:{route}` (Hash)

Token-bucket state maintained by the Lua rate-limiter.

### `gateflow:cb:{sha256(target_url)}` (Hash)

Circuit-breaker state for a downstream target.

### `gateflow:metrics` (Stream)

Telemetry events with the following fields:

- `request_id`
- `api_key` (masked)
- `user_id`
- `route`
- `duration_ms`
- `status_code`
- `bytes_in`
- `bytes_out`

## Standard Headers

### Inbound
- `X-API-KEY` — opaque API key.

### Injected downstream
- `X-User-Id`
- `X-User-Tier`
- `X-Request-ID`

### Response
- `X-Request-ID`
- `X-Gateway-Overhead-MS` — internal gateway processing time.
- `X-Response-Time-MS` — total round-trip time.
- `X-RateLimit-Remaining`
- `Retry-After` — returned with `429` responses.

## Gateway Endpoints

- `GET /health` — liveness probe.
- `GET /ready` — readiness probe (Redis ping).
- `GET /metrics` — Prometheus metrics.
- `GET /docs` — docs pointer.
- `GET /openapi.json` — consolidated downstream OpenAPI spec.
- `/api/admin/*` — route/key/tier management (requires `X-Admin-API-Key`).

## Quick Start

### 1. Install locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

### 2. Start Redis

```bash
docker run -d --name gateflow-redis -p 6379:6379 redis:7-alpine
```

### 3. Seed sample data

```bash
python -m scripts.seed
```

### 4. Run the gateway

```bash
python -m gateflow
```

The gateway will be on `http://localhost:8000`.

## Docker Compose (multi-instance)

```bash
docker compose up --build
```

This starts:
- `redis` on port `6379`
- `users-service` and `orders-service`
- `gateflow_proxy_alpha` and `gateflow_proxy_beta`
- `nginx` on port `8080` as the edge load balancer

Seed the data after the stack is up:

```bash
python -m scripts.seed
```

Then send requests through Nginx:

```bash
curl -H "X-API-KEY: gf_dev_free_001" http://localhost:8080/users/profile
curl -H "X-API-KEY: gf_dev_premium_001" http://localhost:8080/orders/orders
```

## Admin API

All admin endpoints require the `X-Admin-API-Key` header (default: `gateflow-admin-dev`, set via `GATEFLOW_ADMIN_KEY`).

```bash
curl -H "X-Admin-API-Key: gateflow-admin-dev" http://localhost:8000/api/admin/routes
curl -H "X-Admin-API-Key: gateflow-admin-dev" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"target_url":"http://users-service:8000","fallback_url":null,"strip_prefix":true,"requires_auth":true,"allowed_methods":"GET,POST"}' \
  http://localhost:8000/api/admin/routes/users
```

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — architecture decisions.
- [`docs/SECURITY.md`](docs/SECURITY.md) — key hashing, TLS/mTLS, audit log.
- [`docs/RUNBOOK.md`](docs/RUNBOOK.md) — operations, failover, and troubleshooting.

## Production Checklist

- Change `GATEFLOW_ADMIN_KEY` and `GATEFLOW_KEY_SECRET` from defaults.
- Run Redis in Sentinel or managed mode (AWS ElastiCache, etc.).
- Enable TLS/mTLS or terminate TLS at the edge load balancer.
- Restrict `GATEFLOW_CORS_ORIGINS` to known front-end domains.
- Point `/metrics` to your Prometheus scrape config.
- Set `GATEFLOW_MAX_REQUEST_BODY_BYTES` to a value appropriate for your API.

## Tests

Tests assume a real Redis instance on `localhost:6379/15` by default. If none is running, the test harness attempts to start one in a Docker container on `127.0.0.1:6379`.

```bash
docker run -d --rm --name gateflow-test-redis -p 127.0.0.1:6379:6379 redis:7-alpine
pytest
```

## License

MIT
