# GateFlow Runbook

## Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# edit .env with production secrets
docker run -d --name gateflow-redis -p 6379:6379 redis:7-alpine
python -m scripts.seed
python -m gateflow
```

## Health Checks

- `GET /health` — process alive.
- `GET /ready` — Redis ping succeeded.
- `GET /metrics` — Prometheus metrics.

## Failover / Redis Sentinel

Use `docker-compose.ha.yml` for a full Sentinel topology:

```bash
docker compose -f docker-compose.ha.yml up --build
```

Set in `.env`:

```
GATEFLOW_REDIS_SENTINELS=sentinel-1:26379,sentinel-2:26379,sentinel-3:26379
GATEFLOW_REDIS_SERVICE_NAME=mymaster
```

## Key Rotation

1. Generate a new `GATEFLOW_KEY_SECRET`.
2. Re-issue or regenerate all API keys (hashes are deterministic; old keys cannot be recovered).
3. Update `.env` and restart all GateFlow instances.

## Circuit Breaker Half-Open

If a downstream service is flapping, the breaker will be `HALF_OPEN` and allow one probe. A success closes it; a failure reopens it.

## Rate Limit Recovery

A client should back off using the `Retry-After` header on `429`.

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401` on proxy | Missing/invalid API key or key hash mismatch | Verify `X-API-KEY` and `GATEFLOW_KEY_SECRET` |
| `429` | Rate limit exhausted | Wait for `Retry-After` or increase tier capacity |
| `504` / `502` | Downstream down or circuit open | Check downstream health and circuit state |
| `413` | Body > `GATEFLOW_MAX_REQUEST_BODY_BYTES` | Reduce payload or raise limit |

## Remaining Limitations

- The gateway buffers the entire request body; streaming uploads >1 MiB are not supported.
- mTLS is configured in `__main__.py`; Nginx integration still requires extra client-cert config.
- API key hashing means the admin API cannot reveal the original key after creation.
- Sentinel failover is automatic but a split-brain Redis scenario may require manual intervention.
