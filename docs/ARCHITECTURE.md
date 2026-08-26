# GateFlow Architecture Decisions

## ADR-001: Streaming Proxy with Bounded Bodies

- **Context**: The gateway sits between clients and microservices; buffering entire responses into memory would be a memory and latency risk at 10k RPS.
- **Decision**: Request bodies are fully read once to enforce the 1 MiB limit and to allow retries/fallbacks, but downstream responses are streamed via `httpx` + `StreamingResponse`.
- **Consequences**: Bounded memory usage on the gateway; request bodies are limited to small API payloads.

## ADR-002: Redis Sentinel for HA

- **Context**: Redis is a single point of failure for auth, rate limits, and routes.
- **Decision**: Support both standalone `REDIS_URL` and `GATEFLOW_REDIS_SENTINELS` configurations. A health check loop reconnects on failure.
- **Consequences**: Failover is automatic for Sentinel mode; standalone still works for dev.

## ADR-003: Token-Bucket Rate Limiting in Redis Lua

- **Context**: Rate limits must be correct under concurrency.
- **Decision**: Use a single Redis Lua script to atomically refill and debit tokens.
- **Consequences**: No race conditions on the token bucket; retry-after is calculated inside the script.

## ADR-004: Circuit Breaker with HALF_OPEN

- **Context**: Downstream failures should not flood the network and should recover automatically.
- **Decision**: Maintain state in Redis; after `OPEN` duration, allow a single probe (`HALF_OPEN`) to test recovery.
- **Consequences**: Fast failures on unhealthy targets and automatic recovery.

## ADR-005: One-Way Hashed API Keys

- **Context**: Plain API keys in Redis are a security risk.
- **Decision**: API keys are stored and looked up by HMAC-SHA256 using `GATEFLOW_KEY_SECRET`.
- **Consequences**: A key cannot be recovered from Redis. The secret must be backed up and rotated carefully.

## ADR-006: Prometheus Metrics and Structured Logs

- **Context**: Operating the gateway requires request-level and aggregate observability.
- **Decision**: Expose `/metrics` via `prometheus-client`, format all logs as JSON, and run a background worker on `gateflow:metrics`.
- **Consequences**: Easy scraping by Prometheus; logs are parseable by ELK/Loki.
