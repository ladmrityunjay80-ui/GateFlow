# GateFlow Observability

## Metrics

GateFlow exposes Prometheus metrics on `/metrics`:

- `gateflow_request_count_total` — total requests by route/method/status.
- `gateflow_request_latency_seconds` — request latency histogram.
- `gateflow_overhead_latency_seconds` — gateway overhead histogram.
- `gateflow_rate_limited_total` — rate-limited request counter.
- `gateflow_circuit_opened_total` — circuit breaker opened counter.
- `gateflow_errors_total` — internal error counter.

A `ServiceMonitor` is in `k8s/monitoring/servicemonitor.yaml` for the Prometheus operator. A Grafana dashboard is in `k8s/monitoring/grafana-dashboard-gateflow.json`.

## Logs

Logs are structured JSON. The `fluent-bit-daemonset.yaml` ships GateFlow container logs to Loki. Apply it after deploying Loki:

```bash
kubectl apply -f k8s/monitoring/fluent-bit-config.yaml
kubectl apply -f k8s/monitoring/fluent-bit-daemonset.yaml
```

Set `LOKI_HOST` and `LOKI_PORT` in the DaemonSet env to match your Loki endpoint.

## Tracing

OpenTelemetry tracing is optional. Set `GATEFLOW_TRACING_EXPORTER=otlp` and `GATEFLOW_OTLP_ENDPOINT` to send spans to a collector.

## Alerts

Prometheus rules are in `k8s/monitoring/prometheus-rules.yaml` for high 5xx rates, high p95 latency, and excessive rate limiting.
