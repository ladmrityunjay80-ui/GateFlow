# Redis High Availability

GateFlow uses Redis as its primary state store. To avoid a single point of failure, the codebase already supports Redis Sentinel via `redis-py` and the environment variables `GATEFLOW_REDIS_SENTINELS` and `GATEFLOW_REDIS_SERVICE_NAME`.

## Local development with Sentinel

```bash
docker compose -f docker-compose.redis-sentinel.yml up -d
```

This starts one master, two replicas, and three Sentinels.

Configure GateFlow to use it:

```bash
export GATEFLOW_REDIS_SENTINELS="localhost:26379,localhost:26380,localhost:26381"
export GATEFLOW_REDIS_SERVICE_NAME="mymaster"
```

## Kubernetes deployment

Apply the HA Redis stack:

```bash
kubectl apply -f k8s/ha/redis-sentinel.yaml
```

Then configure the GateFlow ConfigMap/Secret:

```yaml
GATEFLOW_REDIS_SENTINELS: "redis-sentinel-0.gateflow.svc.cluster.local:26379,redis-sentinel-1.gateflow.svc.cluster.local:26379,redis-sentinel-2.gateflow.svc.cluster.local:26379"
GATEFLOW_REDIS_SERVICE_NAME: "mymaster"
```

`gateflow/redis_client.py` will automatically discover the current master and fail over when Sentinels promote a replica.

## Managed / cloud Redis

For production, a managed HA Redis (ElastiCache, Google Memorystore, Redis Cloud) is recommended. In that case set a single URL:

```yaml
GATEFLOW_REDIS_URL: "redis://<managed-endpoint>:6379/0"
```

## Failure handling

- The `RedisManager` health check pings the master every `GATEFLOW_REDIS_HEALTH_CHECK_INTERVAL` seconds.
- On connection failure it calls `_reconnect()`, which re-initialises the Sentinel master client.
- Lua scripts are re-loaded after a successful reconnect.
