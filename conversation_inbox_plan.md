# Conversation Inbox — Make It Real

**Status today (Phase B core wired):** Inbox UI ↔ Postgres live. Susanth seeded (`cust-susanth` / `CV-SUSANTH-WA1`, phone `919655282324`). WhatsApp inbound webhook + take-over-gated Meta send implemented. RAG deferred to `KB_plan.md`.

| Layer | Status |
|--------|--------|
| UI (list / thread / composer / rail) | Built + live-wired (`api/inbox.ts`) |
| Postgres tables + seeded WA/SMS threads | Exist (+ Susanth WA thread) |
| Pre-A status/sender vocabulary | **Done** (Alembic `20260722_0011`) |
| API (`/conversations`, send, take-over, canned) | **Done** |
| Frontend `api/inbox.ts` | **Done** |
| WhatsApp webhook / send | **Wired** (`GET/POST /webhooks/whatsapp`, signature + idempotent `provider_ref`, 24h gate). Requires valid Meta send-capable token + ngrok→8000 + Meta webhook config for live phone round-trip |
| Azure OpenAI + RAG retrieval | Deferred (`KB_plan.md`); schema/HNSW may exist separately |

Docker today is basically **Postgres (pgvector)** — enough to start.

**Assets available:**
- Meta Developer account with WhatsApp
- Azure OpenAI LLM + embedding APIs
- RAG source: 5+ insurance product details
- Docker running (`collections_db`)

**Sequencing (locked):**

```
A (API + rewire) ✅  →  B (WhatsApp I/O)  →  C (RAG + sentiment)  →  D (realtime)
```

Same pattern as the other Phase 3B screens. Do **not** block A on Meta/RAG.

---

## Pre-A decisions (settle before any API or UI wiring) ✅

These are cheap now and expensive once the API + UI depend on them. Done as Alembic `20260722_0011` before Phase A endpoints.

### 1. `mine` is not a stored status

**Bug:** DB previously stored `status='mine'`. `"mine"` is viewer-relative — it only works for one hardcoded agent and breaks the moment a second agent opens the inbox.

**Fix (same “one identity, from `GET /me`” rule as `PHASE_3B_GUIDE`):**
- Take-over sets `assigned_user_id = currentUser.id` and stored status `assigned`.
- Column `assigned_user_id` already exists on `conversations` — use it.
- UI filter **"Mine"** is derived: `assigned_user_id === me.id` (from `GET /me`), never a DB status value.

### 2. Canonical conversation status vocabulary

**Canonical stored set:**

| Status | Meaning |
|--------|---------|
| `bot` | Bot is handling; composer locked until take-over |
| `needs_human` | Queued for an agent (unassigned or waiting) |
| `escalated` | Priority / supervisor path |
| `assigned` | An agent owns it (`assigned_user_id` set) |

- Dropped `mine` from the CHECK constraint.
- Migrated existing `status='mine'` rows → `assigned` (kept `assigned_user_id`).
- API exposes derived `isMine` when `assigned_user_id === me.id`.

### 3. Canonical message sender vocabulary

**Canonical set:** `customer | bot | agent | system`

- Migrated `human` → `agent` in data + CHECK.
- Map `system` → UI `SystemEvent`.
- Agent replies insert as `sender='agent'`.
- Take-over writes **`activity_events`** (`conversation_takeover`); chat UI merges that kind as a system divider.

### 4. Derived vs stored fields

| Field | Where |
|-------|--------|
| Status (`bot` / `needs_human` / `escalated` / `assigned`) | Stored |
| “Mine” chip / Mine filter | Derived from `assigned_user_id === me.id` |
| SLA (`ok` / `warn` / `breach`) | Derived (age since last customer inbound) |
| Unread count | Derived (trailing customer turns) |
| Sentiment | From linked interaction for now; Phase C stores computed |

---

## Phase A — Wire to Postgres ✅

**Goal:** Replace hardcoded seed with API data so the page behaves like Disputes/Handoff.

1. Backend CRUD (followed `PHASE_3B_GUIDE`)
   - `GET /conversations` — full Thread shape
   - `GET /conversations/{id}`
   - `POST /conversations/{id}/messages` — agent reply
   - `POST /conversations/{id}/takeover` — `assigned` + `activity_events`
   - `GET /canned-responses`
2. Map DB → UI `Thread` shape
3. Frontend `Habibi/src/api/inbox.ts` + React Query; rewired `inbox.tsx`
4. Context rail joins customer / disputes / promises / EMI

**Done when:** refreshing `/inbox` shows DB threads; take-over + send persist; Mine is viewer-relative. **Met.**

Set `Habibi/.env.local`:
```
VITE_USE_MOCK=false
VITE_API_BASE_URL=http://localhost:8000
```

---

## Phase B — WhatsApp (Meta Cloud API)

Use the existing Meta developer account.

> **Inbound vs outbound webhooks — keep separate.**  
> Existing `webhook_endpoints` / `webhook_deliveries` are **outbound** (app → external systems — Tier-3 Webhooks screen).  
> WhatsApp `GET/POST /webhooks/whatsapp` is **inbound** (Meta → app). Different subsystem; do not overload the outbound tables for Meta traffic.

### Env
`WHATSAPP_TOKEN`, `PHONE_NUMBER_ID`, `WABA_ID`, `VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`  
(plus public base URL / tunnel for local: **ngrok or equivalent** — Meta cannot reach `localhost`)

### Inbound webhook `GET/POST /webhooks/whatsapp`
1. **GET** — challenge verify with `VERIFY_TOKEN`.
2. **POST — mandatory security:**
   - Verify `X-Hub-Signature-256` against `WHATSAPP_APP_SECRET` (reject if missing/invalid).
   - **Idempotency:** Meta retries. Dedupe on WhatsApp message id → store in `messages.provider_ref` (unique/partial unique recommended); ignore duplicates.
3. On message: find/create customer + conversation → append message → update **last inbound timestamp** → bump status (`needs_human` on keywords / low bot confidence / negative sentiment later).
4. Delivery/read status callbacks → update `delivery_status` (ticks in UI).

### Outbound send (24-hour customer care window)
Meta only allows **free-form** replies within **24 hours of the customer’s last inbound** message. Outside that window, only **pre-approved template** messages succeed — free-form Send API calls fail (often silently from the product’s POV if errors aren’t surfaced).

**Required:**
1. Track `last_customer_inbound_at` on the conversation (or derive from latest `messages` where `sender='customer'`).
2. Gate free-form send: if outside window → do **not** call free-form Send; either block with a clear UI error or offer **template fallback**.
3. Template path: send approved template; still persist outbound row + `provider_ref`.
4. On agent `POST .../messages` inside window → Meta Send API → store `provider_ref` + `delivery_status`.

Start with **one test number**; keep SMS/email as DB-only until WA is solid.

**Done when:** phone ↔ Inbox round-trip works; take-over replies hit WhatsApp **when in-window**; out-of-window path uses template or explicit failure — never a silent no-op.

---

## Phase C — Azure OpenAI + RAG (insurance products)

1. Ingest product docs → chunk → embed (Azure embeddings) → `kb_chunks.embedding`.
2. **Add HNSW (or IVFFlat) index** on `kb_chunks.embedding` at ingest time — without it, top-k is a full scan. (`PLAN_NEXT_PHASE` already calls for HNSW.)
3. On thread open / new customer message (see cost note below):
   - Embed query (last N messages + account context)
   - Vector search top-k → `ai_response_suggestions`
   - LLM rewrite into agent-ready chips is **optional**, not required on every turn
4. Sentiment: classify last customer turn → store on conversation; drive red/amber dot + escalate rules.
5. Bot path (later): auto-reply while `status=bot`; escalate to `needs_human` on dispute/DND/low confidence.

### Cost / latency
Embedding + LLM on **every** message is slow and pricey.
- Debounce suggestion generation (e.g. on pause / thread open / explicit refresh).
- Cache embeddings for repeated queries / chunk texts.
- Keep LLM rewrite genuinely optional; retrieve-and-show snippets first.

**Done when:** RAG chips are live from the product KB, not hardcoded strings.

---

## Phase D — Live feel

- **v1:** short polling is fine for Inbox alone.
- **Do not invent an Inbox-only transport you’ll throw away.** Handoff + Floor also need realtime (`PLAN_NEXT_PHASE` Phase 4 = WebSocket). Prefer a **shared** realtime channel (or a polling helper designed to swap to WS) rather than a one-off Inbox poller.
- Assignment, unread, SLA remain derived as in Pre-A.
- Attachments via MinIO only if compose gains attach for real.

---

## Suggested order

```
Pre-A (status + sender migration) ✅
  → A (API + rewire) ✅
  → B (WhatsApp I/O + 24h window + signed idempotent webhook)
  → C (RAG + HNSW + debounced suggestions)
  → D (shared realtime)
```

| Phase | Unlocks |
|-------|---------|
| Pre-A | Correct multi-agent semantics |
| A | Page reads/writes Postgres |
| B | Real WhatsApp channel |
| C | Live RAG + sentiment |
| D | Live multi-agent floor feel |

---

## Prerequisites before Phase B/C

1. Put in `.env`: WhatsApp token / phone number ID / verify token / **app secret**, Azure OpenAI endpoint + keys, product doc paths.
2. Local WA inbound needs a **public tunnel** (ngrok).
3. Realtime: polling acceptable for Inbox v1, with shared WS as the Phase 4 target (not Inbox-specific).
