---
title: API Reference
description: Interactive API reference for the RoutePass REST API.
---

The full interactive API reference is available at:

**[api.routepass.online/docs](https://api.routepass.online/docs)** — powered by [Scalar](https://scalar.com), with a built-in request runner.

The underlying OpenAPI 3.0 specification is at: **[api.routepass.online/openapi.json](https://api.routepass.online/openapi.json)**

---

## Import into Postman

1. Open Postman → **Import**
2. Select **Link**
3. Paste: `https://api.routepass.online/openapi.json`
4. Click **Continue** → **Import**

All endpoints, request bodies, and response schemas are imported automatically. Set the `Authorization` variable to your Bearer token or API key.

## Import into Insomnia

1. Open Insomnia → **Application → Import**
2. Select **From URL**
3. Paste: `https://api.routepass.online/openapi.json`

---

## Endpoint groups

| Group | Base path | Description |
|-------|-----------|-------------|
| Auth | `/api/v1/auth/` | Register, login, refresh, OAuth connections |
| Sync | `/api/v1/sync/` | Sync status, manual trigger, history rebuild |
| Activities | `/api/v1/activities/` | Paginated history, detail, GPX download |
| Rules | `/api/v1/rules/` | CRUD for sync rules (Pro: 5 rules) |
| API Keys | `/api/v1/api-keys/` | Create and revoke API keys (Pro) |
| Billing | `/api/v1/billing/` | Stripe checkout, portal, subscription status |
| Webhooks | `/api/v1/webhooks/` | Inbound webhooks from Strava and Stripe |

---

## Base URL

| Environment | Base URL |
|-------------|----------|
| Cloud production | `https://api.routepass.online` |
| Self-hosted (default) | `http://localhost:8000` |

---

## Response format

All responses are JSON. Errors follow this shape:

```json
{
  "detail": "Human-readable error message"
}
```

For validation errors (422):
```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "value is not a valid email address",
      "type": "value_error.email"
    }
  ]
}
```
