# Developer Portal

A developer portal lets API consumers manage their keys and quotas without
needing full admin access.  GateFlow supports this through `admin_read_keys`
and read-only admin endpoints.

## Self-Service Endpoints

| Capability | Method | Admin route | Notes |
|------------|--------|-------------|-------|
| List own key usage | `GET` | `/api/admin/keys/{api_key}` | Requires an `admin_read_keys` key or the consumer's own key + audit log review. |
| List tiers | `GET` | `/api/admin/tiers` | Public-facing tier definitions; use an `admin_read_keys` key. |
| Request key rotation | `PUT` | `/api/admin/keys/{api_key}` | Requires an admin write key; a portal can proxy this from an internal workflow. |

## Suggested Portal Architecture

1. **AuthN/AuthZ**: Portal uses `GATEFLOW_ADMIN_READ_KEYS` for read access and
   an internal service account with write access for approved mutations.
2. **Caching**: Cache tier metadata and openapi spec at the CDN edge for 60s.
3. **Rate limiting**: The portal itself should be rate-limited through the
   same `gateflow` instance or a dedicated `/portal` route.
4. **OpenAPI UI**: Mount the rendered OpenAPI docs at `/portal/docs` from a
   static CDN copy of `openapi.json`.

## Implementation Checklist

- [ ] Build a small React/Vue front-end that calls `/api/admin/keys` and
      `/api/admin/tiers`.
- [ ] Add a `/api/admin/keys/{api_key}/rotate` convenience endpoint.
- [ ] Add a request-a-tier-upgrade workflow that writes to a queue.
- [ ] Add a `/portal` route in the Ingress and CDN to serve the static UI.
