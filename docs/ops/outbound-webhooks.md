# Outbound customer event webhooks

The Webhooks page manages outbound PayInt events sent to customer systems. It does not configure inbound payment or WhatsApp callbacks, or Voice Studio workflow webhook nodes. The Integrations console page is retired; its backend APIs remain because other live paths still use them.

## Release and activation

Apply the reviewed Alembic migrations through `20260928_0172` before starting code that reads the new columns. The fresh-install mirror is `backend/sql/77_webhook_subscription_review.sql`. Do not apply the SQL mirror and Alembic migration to the same installation independently.

The migration sets neither `subscriptions_confirmed_at` nor `destination_tested_at` on existing endpoints. No old subscription will emit new customer data automatically. An authorized operator must:

1. Inspect the receiver URL, custom headers, signing secret, retry policy and selected events. Replace legacy event names as appropriate; `document.sent` has no confirmed carrier-send producer.
2. Ensure the receiver accepts a signed `webhook.test` event containing no borrower data. Use **Send live probe**, then refresh the delivery log and verify a real 2xx response. The separate **Simulation** control only records a simulated delivery.
3. Select only supported event names, then use **Review & activate**. This records the actor and event list in the audit chain and starts egress for future transitions. Historical pending business deliveries are closed as `subscription_review_required` rather than released as a backlog.

Only public HTTPS receivers can pass the current outbound DNS/IP policy. A private bank endpoint needs an approved network path and a separate reviewed exception before it can be activated; do not disable the SSRF check to make a probe pass.

Editing the URL, headers, signing algorithm or event list suspends the subscription. Rotating the secret also suspends it. Repeat the live probe and review. Pausing an endpoint blocks delivery; resuming does not bypass an outstanding review. An edit may finish a request already in flight; coordinate changes with the receiver if a hard cutoff is needed. The delivery header allows receiver-side deduplication.

The review request includes the configuration version shown to the operator. If another operator changes the destination, headers, events or retry policy meanwhile, the server rejects the stale approval and requires refresh. Retry-policy edits require renewed review; destination edits and secret rotations require a new probe.

## Supported events

Only event names marked **Supported** in the catalog can be selected for a new subscription or activated. Each is queued in the same database transaction as its business transition:

| Event | Source |
| --- | --- |
| `call.completed` | A voice interaction first reaches a terminal status |
| `promise.created` | A promise is created |
| `promise.kept`, `promise.broken` | Existing promise fulfillment transitions |
| `dispute.raised`, `dispute.resolved` | A dispute is created or resolved |
| `payment.updated` | Existing verified payment ingest transition |
| `lead.created` | A lead is created |

Other catalog names remain visible so historical subscriptions can be recognized and removed. They are not presented as working producers. In particular, legacy `interaction.completed` maps conceptually to `call.completed`, and `dispute.created` to `dispute.raised`; neither is silently renamed on an existing customer endpoint. `document.sent` requires a confirmed carrier-send state before it can be implemented safely.

## Receiver contract

The JSON envelope has `schemaVersion: 1`, `event`, `tenant`, `at` and `data`. The event catalog displays the field shape. Business payloads contain identifiers and bounded status fields; they do not contain phone numbers, transcripts or message bodies. A receiver must treat the identifiers as customer data and apply its own access controls and retention policy.

The sender includes `X-BigBound-Event`, `X-BigBound-Delivery`, `X-BigBound-Timestamp` (Unix seconds), and `X-BigBound-Signature` (lowercase hex HMAC-SHA256). Verification uses the raw request bytes and the one-time secret shown on endpoint creation or rotation:

Custom headers are for non-secret routing metadata. Common authentication and token header names are rejected because values would otherwise be stored as endpoint configuration. Operators must not enter credentials under another header name. Receivers should authenticate the signed request instead.

```
key = sha256(secret_utf8).hexdigest().encode("ascii")
expected = HMAC_SHA256(key, timestamp_ascii + b"." + raw_body).hexdigest()
```

Compare the signature in constant time and reject timestamps older than five minutes. Deduplicate on `X-BigBound-Delivery`; deliveries are at least once. Return any 2xx only after durable acceptance. 3xx and 4xx are terminal; 5xx and transport failures retry according to the endpoint policy, up to its attempt and event-age limits. Redirects are not followed. Delivery response bodies are truncated to 2,000 bytes in the operator log, so receivers should not put secrets in responses.

## Operations and rollback

Inspect the delivery log for `live` versus `simulated`, HTTP status, attempts and latency. A manual retry requeues the original payload only when the endpoint remains approved and subscribed. To stop egress, pause the endpoint. A code rollback to a version that does not enforce `subscriptions_confirmed_at` could bypass the review gate, so pause endpoints before such a rollback and keep the additive columns. This change does not send a probe, customer event, call or message during local implementation.
