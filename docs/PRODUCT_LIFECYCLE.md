# Product Lifecycle

## API Versioning

GateFlow exposes a single API version. New endpoints are added under
`/api/` prefixes. Breaking changes are introduced behind a new version prefix
or by requiring clients to opt-in via request headers.

## Deprecation

1. Endpoints that are planned for removal are tagged `deprecated` in OpenAPI.
2. A `Sunset` HTTP header is returned for every request to deprecated
   endpoints with a target removal date.
3. Admins can configure a `deprecation_deadline` on tier settings.
4. Webhook notifications are sent to consumers 30 and 7 days before removal.

## Tiers

- `free`: minimal capacity, no SLA, self-service only.
- `premium`: increased quotas, webhook alerts, e-mail support.
- `enterprise`: dedicated limits, custom routing, priority support.

Tiers are defined in `gateflow/admin/tiers.py` and stored in Redis. Customers
request tier changes via `/api/me/tier/request` or the portal at `/portal`.

## Key Lifecycle

- Customers can rotate keys at any time via `/api/me/keys/rotate` or the portal.
- Old keys are invalidated atomically using a Lua script.
- Key `allowed_ips` and `expires_at` can be managed by admins.

## Portal

The self-service developer portal is at `/portal` and supports quota viewing,
key rotation, and tier requests without admin intervention.
