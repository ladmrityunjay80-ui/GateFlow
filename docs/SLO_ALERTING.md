# SLO Alerting

GateFlow exposes Prometheus metrics that can be used for service-level objective (SLO) alerting.

## Metrics exposed

- `gateflow_request_count_total` — total requests by route, method and status code.
- `gateflow_request_latency_seconds_bucket` — request latency histogram.
- `gateflow_rate_limited_total` — rate-limited requests.
- `gateflow_circuit_breaker_opened_total` — circuit breaker openings.
- `gateflow_error_count_total` — gateway-level errors.

## SLOs

| SLO | Target | Alert expression |
|---|---|---|
| Availability | 99.9% over 30 days | `5xx rate > 1% for 2 minutes` |
| Latency p95 | < 500 ms | `p95 latency > 500 ms for 5 minutes` |
| Rate limiting | < 10 events/sec | `rate_limited_total > 10/sec for 1 minute` |

## PrometheusRule

`k8s/monitoring/prometheus-rules.yaml` contains the rule definitions. Apply it with:

```bash
kubectl apply -f k8s/monitoring/prometheus-rules.yaml
```

## Alert routing

Prometheus Alertmanager or a tool like PagerDuty/Opsgenie should be configured to route `severity: warning` alerts to the on-call channel.
