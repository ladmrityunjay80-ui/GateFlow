# GateFlow Security Notes

## API Key Storage

- API keys are **never stored in plain text**.
- Redis keys are `gateflow:auth:keys:{hmac_sha256(api_key)}`.
- HMAC uses `GATEFLOW_KEY_SECRET`. Rotate this secret only after understanding that existing keys cannot be recovered.

## Admin Authentication

- Admin endpoints require `X-Admin-API-Key`.
- The header is compared with `hmac.compare_digest` to resist timing attacks.
- Use a long, random `GATEFLOW_ADMIN_KEY` in production.

## Transport Security

- Set `GATEFLOW_SSL_CERTFILE` and `GATEFLOW_SSL_KEYFILE` to enable TLS.
- Enable `GATEFLOW_MTLS_ENABLED=true` plus `GATEFLOW_SSL_CA_CERTS` to require client certificates.
- In production, terminate at Nginx or an AWS/GCP load balancer and keep internal mTLS between load balancer and services.

## CORS

- `GATEFLOW_CORS_ORIGINS` is a comma-separated list of allowed origins.
- Empty value disables CORS middleware.

## Audit Log

- Admin actions are written to the Redis stream `gateflow:audit:admin`.
- The admin key is hashed before writing.
- Use `XRANGE gateflow:audit:admin - +` or `XREAD` to consume the stream.
