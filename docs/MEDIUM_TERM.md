# Medium-Term Roadmap (Quarter)

This document captures the longer-term direction for GateFlow and is a
companion to the production hardening already in place (Immediate and
Short-Term sprints).

## 1. Multi-Region / Dual-Zone Deployment

- Run one GateFlow stack per region (see `docker-compose.multi-region.yml`).
- Deploy behind regional load balancers with health checks on `/health` and
  `/ready`.
- Options for a global rate-limiting scheme:
  - **Redis Cross-Region replication**: keep `gateflow:auth:keys:*` and
    `gateflow:tiers:*` replicated, while accepting eventual consistency for
    hot `gateflow:rl:*` keys.
  - **Redis Global Datastore**: use a managed active-active Redis offering
    (ElastiCache Global, Redis Cloud Active-Active) so all regions observe the
    same token-bucket counters.
  - **Regional rate limits with global quota**: each region owns a local token
    bucket refreshed from a central quota service every few seconds.

## 2. Edge Caching / CDN

- Push cacheable responses closer to users using CloudFront / CloudFlare /
  Fastly.
- Route `/docs` and `/openapi.json` through the CDN for developer portal
  traffic.
- Cache only `GET` responses with explicit `Cache-Control` headers from the
  downstream service; do not cache authenticated mutating requests.
- Use the CDN as a first line of DDoS protection and WAF.

## 3. OpenAPI-Rendered Docs UI

- FastAPI docs are disabled in production (`docs_url=None`) for security.
- For the developer portal, expose a read-only, public OpenAPI UI at a
  separate path (`/portal/docs`) that is served by a static CDN and does not
  call the admin API.
- Alternatively, publish a `developer-portal` static site built from
  `openapi.json`.

## 4. Developer Portal

A self-service portal for API consumers to:

- View their own key quota and usage (`GET /api/me/quota`).
- Rotate their own key (if the admin allows self-rotation).
- Request a tier upgrade (workflow triggers an admin notification).

For now, the admin API is the contract; a front-end portal can be built on
`openapi.json` and `admin_read_keys`.

## 5. Anomaly Detection

`gateflow/anomaly.py` already provides real-time error-rate, latency, and
traffic anomaly detection on the `gateflow:metrics` stream.

Next steps:

- Consume `gateflow:anomalies` in a notification worker (email, Slack, PagerDuty).
- Add model-based forecasting (Prophet, ARIMA, or a small LSTM) for seasonal
  traffic patterns.
- Dashboard anomaly counts in a metrics exporter.
