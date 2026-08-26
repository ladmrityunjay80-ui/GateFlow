# GateFlow Disaster Recovery

## RPO / RTO targets

- **RPO**: 1 hour (AOF `appendfsync everysec` + scheduled point-in-time RDB backups).
- **RTO**: 5 minutes for single-zone failures by restoring the latest RDB and replaying AOF.

## What is protected

GateFlow stores all runtime state in Redis:

- API key records (`gateflow:auth:keys:*`)
- Tier configuration (`gateflow:tiers:*`)
- Route table (`gateflow:routes`)
- Rate limit / circuit-breaker state (`gateflow:rl:*`, `gateflow:cb:*`)
- Telemetry streams (`gateflow:metrics`, `gateflow:anomalies`, `gateflow:audit:admin`)

## Backups

### Kubernetes

- A StatefulSet with a persistent `redis-data` volume and AOF enabled.
- A daily CronJob `redis-backup` runs `redis-cli --rdb /backup/dump-<timestamp>.rdb`.
- Use Velero or CSI volume snapshots to back up both the `redis-data` and `redis-backup` PVCs off-cluster.

### Docker Compose

- AOF is enabled with `appendfsync everysec`.
- RDB snapshots are taken every 15 minutes under normal write load (`save 900 1 300 10 60 10000`).
- Mount a host volume on the Redis `/data` directory for persistence.

## Restore

1. Stop the GateFlow pods/Compose services.
2. Replace the Redis PVC `/data/appendonly.aof` and/or `dump.rdb` with the latest backup.
3. If only an RDB dump is available, start Redis with `redis-server --appendonly yes --dbfilename dump.rdb`.
4. Restart GateFlow; it will load scripts and refresh the route cache automatically.

## Failover

- For high availability, run Redis Sentinel or a managed service (ElastiCache, Redis Cloud).
- Update `GATEFLOW_REDIS_SENTINELS` / `GATEFLOW_REDIS_SERVICE_NAME` accordingly.
- Multi-region deployments should use a managed active-active Redis or per-region read replicas with regional routing.
