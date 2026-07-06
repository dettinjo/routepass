---
title: API Authentication
description: How to authenticate with the RoutePass REST API using JWT tokens and API keys.
---

The RoutePass API supports two authentication methods: **JWT Bearer tokens** (for user sessions) and **API keys** (for programmatic access, Pro only).

## JWT Bearer tokens

Obtain a token by logging in:

```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "you@example.com",
  "pass": "your-password-here"
}
```

Response:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.example",
  "token_type": "bearer"
}
```

Use the token in subsequent requests:

```http
GET /api/v1/sync/status
Authorization: Bearer <your-jwt-token>
```

### Token expiry and refresh

JWT tokens expire after **30 minutes**. Refresh before expiry:

```http
POST /api/v1/auth/refresh
Authorization: Bearer <current_token>
```

Returns a new `access_token`. The dashboard handles this automatically. If you're using the API directly, implement a refresh-on-401 pattern.

---

## API keys (Pro)

API keys are long-lived tokens for programmatic access. They don't expire unless you revoke them.

### Creating an API key

1. In the dashboard, go to **Settings → API Keys**.
2. Click **Create key**, give it a name.
3. **Copy the key immediately** — it is shown once and never retrievable again.

The key format is: `rp_live_<random-32-chars>`

### Using an API key

Send the key as a Bearer token:

```http
GET /api/v1/activities
Authorization: Bearer rp_live_abc123...
```

API keys have the same permissions as the user who created them. They respect tier limits — a Free user's API key cannot access Pro-only endpoints.

### Listing and revoking keys

```http
GET /api/v1/api-keys
Authorization: Bearer <jwt_or_api_key>
```

```http
DELETE /api/v1/api-keys/{key_id}
Authorization: Bearer <jwt_or_api_key>
```

Revocation is immediate. Revoked keys return `401`.

---

## Error responses

| Code | Meaning |
|------|---------|
| `401` | Missing, invalid, or expired token |
| `402` | Valid token, but your tier doesn't include this endpoint |
| `403` | Valid token, but you don't own the requested resource |

---

## Postman / API clients

Import the full API collection into Postman or Insomnia with one click:

- **Postman**: File → Import → Link → `https://api.routepass.online/openapi.json`
- **Insomnia**: Application → Import → URL → `https://api.routepass.online/openapi.json`

Or download the OpenAPI spec directly: [`/openapi.json`](https://api.routepass.online/openapi.json)
