---
title: Webhooks
description: Receive activity events at your own URL via outbound webhooks.
---

Pro users can configure outbound webhooks — RoutePass will POST a signed JSON payload to a URL of your choice whenever an activity syncs. Use this to trigger downstream automations, log to your own database, or build custom dashboards.

## Setting up a webhook

1. Go to **Settings → Webhooks → Add webhook**.
2. Enter your endpoint URL (must be publicly reachable over HTTPS).
3. Enter a secret — a random string you choose. RoutePass uses it to sign payloads so you can verify authenticity.
4. Select which events to receive.
5. Click **Save**.

RoutePass immediately sends a test `ping` event to verify reachability.

---

## Events

| Event | Fired when |
|-------|-----------|
| `activity.synced` | An activity was successfully synced to a destination |
| `sync.failed` | A sync attempt failed (after retries) |
| `rule.skipped` | A sync rule's `skip` action fired for an activity |
| `ping` | Sent on webhook creation to verify reachability |

---

## Payload shape

All events share this envelope:

```json
{
  "event": "activity.synced",
  "timestamp": "2026-04-19T14:32:00Z",
  "data": { ... }
}
```

### `activity.synced`

```json
{
  "event": "activity.synced",
  "timestamp": "2026-04-19T14:32:00Z",
  "data": {
    "activity_id": "550e8400-e29b-41d4-a716-446655440000",
    "komoot_tour_id": "1234567890",
    "strava_activity_id": "9876543210",
    "name": "Morning Ride",
    "sport_type": "Ride",
    "distance_m": 48200,
    "elevation_up_m": 520,
    "started_at": "2026-04-19T07:00:00Z",
    "duration_seconds": 5400,
    "sync_direction": "komoot_to_strava"
  }
}
```

### `sync.failed`

```json
{
  "event": "sync.failed",
  "timestamp": "2026-04-19T14:32:00Z",
  "data": {
    "komoot_tour_id": "1234567890",
    "error": "Strava upload rejected: duplicate activity",
    "retries": 3
  }
}
```

### `rule.skipped`

```json
{
  "event": "rule.skipped",
  "timestamp": "2026-04-19T14:32:00Z",
  "data": {
    "komoot_tour_id": "1234567890",
    "name": "Indoor Yoga",
    "rule_id": "rule-uuid",
    "rule_name": "Skip indoor activities"
  }
}
```

---

## Signature verification

Every request includes a `X-RoutePass-Signature` header — an HMAC-SHA256 signature of the raw request body using your webhook secret.

**Verify in Python:**
```python
import hmac
import hashlib

def verify_signature(body: bytes, secret: str, signature: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

**Verify in Node.js:**
```js
const crypto = require('crypto')

function verifySignature(body, secret, signature) {
  const expected = 'sha256=' + crypto
    .createHmac('sha256', secret)
    .update(body)
    .digest('hex')
  return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(signature))
}
```

Always use a constant-time comparison to prevent timing attacks.

---

## Retries

If your endpoint returns a non-2xx status or times out (10 second timeout), RoutePass retries with exponential backoff:

| Attempt | Delay |
|---------|-------|
| 1st retry | 30 seconds |
| 2nd retry | 5 minutes |
| 3rd retry | 30 minutes |

After 3 failed retries, the delivery is marked as failed and the `failure_count` on the webhook is incremented. Webhooks with 10+ consecutive failures are automatically disabled.
