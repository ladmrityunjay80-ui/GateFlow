# Multi-Region Deployment Topology

This document describes how to run GateFlow across multiple regions with a shared Redis global datastore.

## Reference topology

```
                    ┌──────────────┐
                    │  Global DNS  │
                    │  (GeoRoute)  │
                    └──────┬───────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
      ┌─────────┐     ┌─────────┐     ┌─────────┐
      │ GateFlow│     │ GateFlow│     │ GateFlow│
      │  US-East│     │  EU-West│     │  APAC   │
      └────┬────┘     └────┬────┘     └────┬────┘
           │               │               │
           └───────────────┼───────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌─────────┐  ┌─────────┐  ┌─────────┐
        │ Redis   │  │ Redis   │  │ Redis   │
        │ Primary │──│ Replica │──│ Replica │
        │  US-East│  │  EU-West│  │  APAC   │
        └─────────┘  └─────────┘  └─────────┘
```

## Local reference

`docker-compose.multi-region.yml` spins up a three-region Redis replication setup and a single GateFlow instance for local testing.

```bash
docker compose -f docker-compose.multi-region.yml up
```

## Redis configuration

- One active primary per shard. Writes always go to the primary.
- Read replicas in secondary regions for hot cache and route lookups.
- Sentinel or a managed Redis service (e.g. AWS ElastiCache, GCP Memorystore, Azure Cache) for automatic failover.
- Configure `GATEFLOW_REDIS_SENTINELS` and `GATEFLOW_REDIS_SERVICE_NAME` to point to Sentinel.

## Consistency model

- Routes and key/tier metadata are written to the primary and propagated through Redis pub/sub to invalidate local caches.
- Telemetry streams (`gateflow:metrics`, `gateflow:audit`) are regional and can be aggregated centrally.
- Idempotency keys are region-local by default; for cross-region idempotency a shared Redis prefix should be used.

## Next steps

- Add cross-region health checks in `GATEFLOW_READY_DOWNSTREAM`.
- Deploy regional rate limiter counters with Redis replication.
- Use a global load balancer with health-based geo-routing.
