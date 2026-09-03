# 23 — End-to-end workflows

**Role:** End-to-end system validation architect.  
**Scope:** Real user and carrier journeys across `Habibi/src` (TanStack CRM), `backend/main.py` (FastAPI), domain modules, Postgres, and providers (Twilio, Meta, Azure, MinIO, Redis mesh). Guest tree `PRAXIST-main/` is out of scope.  
**Date:** 2026-09-02  
**Mode:** Read-only. No source, config, git, or dependency changes. No live stack was running in this session; claims are from code, SQL, workers, and existing tests — not from a browser pass.  
**Companions:** [02-domain-capability-map.md](./02-domain-capability-map.md), [03-frontend-architecture.md](./03-frontend-architecture.md), [04-backend-architecture.md](./04-backend-architecture.md), [11-api-contracts.md](./11-api-contracts.md), [12-data-model.md](./12-data-model.md), [14-error-handling.md](./14-error-handling.md), [15-concurrency.md](./15-concurrency.md), [19-auth-authz.md](./19-auth-authz.md).  
**Vocabulary:** `CONTEXT.md`. Terms in **bold** are that glossary.

**Method:** six parallel lenses — UI journeys, API flows, backend workflows, persistence state, provider integrations, failure paths — then every headline hop re-read from source in this document. Known defects K1–K10 from report 14 were re-checked against current line ranges; each still holds, with one mechanism note on K6.

There is **no Playwright / Cypress / backend e2e suite**. Frontend vitest is 11 files, almost all formatters and contract helpers. Journey coverage is characterization tests at seams (`test_place_contract.py`, `test_inbox_channel_contract.py`, `test_promise_fulfillment.py`, `test_twilio_voice.py`), not operator-to-Postgres traces.

---

## Verdict

**The product has real journeys. It does not have an end-to-end owner for any of them.**

Each hop is locally competent. The CRM client is one module (`Habibi/src/api/config.ts`). Staff authz is a total registry. Outbound dialling has a real reserve → admit → place → Closer contract. WhatsApp outbound is the only adapter that reasons correctly about double-send. Publish is a compiler.

What fails is the *join*. Operator actions that look like telephone calls do not call. The one CRM button that *does* dial (`POST /demo/outbound-call`, hosted on Roles & access) turns off the frequency ledger via session coalescing. The audit field on a document request is fabricated on read. The wrap-up mutation sends an `Idempotency-Key` that includes `Date.now()`, which is the opposite of idempotency. Dev default `USE_MOCK=true` means most operators never exercise the live hops this report describes.

Three findings carry the report:

1. **The CRM has no click-to-call.** Customer 360 “Log call” writes `POST /interactions`. Callbacks “Start call” patches status to `in_progress`. The only operator-initiated PSTN path is the demo button, and that path is K1+K2. Campaigns and treatment enact dial from workers, not from the page the operator is looking at.
2. **K1–K10 still sit on live journeys.** Report 14 named two families — five ways to contact a borrower twice, five ways the record disagrees with what happened. Every one is still on a hop in this document. K6’s *inner* reserve now uses its own transaction; the outer `process_one` transaction still claims, dials, and marks-enacted together, so a rollback still replays the dial.
3. **There is no journey test.** 188 backend test files pin seams. Zero files drive START → UI. `QueryState` — the primitive that stops `query.data ?? []` from lying — is used in one component family. Customer 360 insights still fall through to `deriveCustomerInsights` on any API failure.

This is not a missing workflow engine. The workers already *are* the workflow engine (`bot_worker.process_one_any`, `worker`, `voice.bot`). The gap is that the operator console, the HTTP table, and those workers do not share a single picture of “what just happened.”

---

## 1. How to read a journey

Every journey below is scored on the same hop chain:

```text
START
  → USER ACTION          (click, webhook, SKIP LOCKED claim, Pipecat turn)
  → FRONTEND             (route + api/*.ts + USE_MOCK branch)
  → API                  (method + path + authz class)
  → SERVICE              (main.py handler → domain module)
  → DATABASE             (tables + state machine)
  → PROVIDER             (Twilio / Meta / Azure / MinIO / Redis / none)
  → RESPONSE             (HTTP / TwiML / job status)
  → UI                   (what the operator actually sees)
```

**Risk** is 1–10, also labelled P0–P3:

| Band | Score | Meaning |
|------|-------|---------|
| **P0** | 9–10 | Can contact a borrower twice, or the system of record lies about money / consent / contact. |
| **P1** | 7–8 | Live-path wrong state the operator will act on, or a UI that claims a call it did not place. |
| **P2** | 5–6 | Missing recovery, duplicated HTTP, provider bypass that is labelled. |
| **P3** | 3–4 | Naming, unused wrapper endpoints, mock/live cosmetic drift. |

Observed fact vs strong inference is marked on each hop that is not a straight line read.

---

## 2. Journey register

| ID | Journey | Start | Risk | Dominant defect |
|----|---------|-------|------|-----------------|
| J1 | Operator identity | Open any page | **7 / P1** | No login. `GET /me` + API key. Authz shipped off (`19`). |
| J2 | My workspace | `/` | **4 / P3** | Live `GET /work-items` + `/workspace/summary`. Mock stitches four seeds. |
| J3 | Customer 360 | `/customers/:id` | **8 / P1** | Insights fallback computes policy in the browser. |
| J4 | Contactability pill | Customer header | **8 / P1** | UI asks the engine (good). Engine `admit` fail-opens on non-outreach (K3). |
| J5 | Log call (360 rail) | Quick action | **8 / P1** | Writes an interaction. Does not dial. No attempt row. |
| J6 | Capture PTP (360 / promises) | Sheet submit | **7 / P1** | Live `POST /promises` with **no** `Idempotency-Key`. |
| J7 | Document request | 360 / desk | **8 / P1** | Write is correct; GET fabricates `requestedVia: "voice"` (`11` P0). |
| J8 | Conversation inbox | `/inbox` | **7 / P1** | Send enqueues WhatsApp; K5 on the worker hop. |
| J9 | Inbound WhatsApp | Meta POST | **7 / P1** | Signature verified. Voice-class tools run via `bot_turn_jobs`, not the Mouth. |
| J10 | Handoff hub | `/handoff` | **6 / P2** | Claim + 2s poll. Wrap-up idempotency key includes `Date.now()`. |
| J11 | Floor barge / whisper | `/floor` | **6 / P2** | `POST /supervisor-actions` → live QA enact. Mock returns `audioJoined: false`. |
| J12 | Callback “start call” | `/callbacks` | **8 / P1** | `PATCH` status `in_progress`. **No Twilio.** |
| J13 | Demo outbound | `/roles` panel | **10 / P0** | Only CRM PSTN button. K1+K2. |
| J14 | Campaign outbound | Agent studio Outbound tab | **10 / P0** | Worker dials. Ambiguous carrier → requeue (K4). |
| J15 | Inbound voice | Twilio webhook | **8 / P1** | Pipecat Mouth. Tool Grant module unused. Closer is async. |
| J16 | Treatment enact | Worker, not UI | **9 / P0** | Scoreboard is read-only. Live enact is K6. |
| J17 | Reco / upsell | `/upsell` + Mouth tool | **8 / P1** | Lead CRM is live. In-call refuse write can fail-open (K10). |
| J18 | Mouth publish | `/agent-studio/$botId` | **5 / P2** | Compiler is real. UI publishes via `/prompt-versions/:id/publish`; wrapper `/agent-studio/cards/:id/publish` is unused. |
| J19 | Call sandbox | `/sandbox` | **5 / P2** | Chat → Azure via API. Voice WebRTC bypasses FastAPI for media. Mock fabricates a WebRTC URL. |
| J20 | Knowledge base | `/knowledge-base` | **5 / P2** | Upload → `kb_index_jobs` → `worker`. UI polls jobs. |
| J21 | Consent / DND | `/consent` | **6 / P2** | Writes hit `/consent/:id`. Caps displayed here are the ledger K1 under-reports. |
| J22 | Pay-by-link | `GET /pay/{token}` | **9 / P0** | Public. Settlement is K8/K9. |
| J23 | Bounce first-touch | payment_events worker | **9 / P0** | `sent = True` outside the SMS configured guard (K7). |
| J24 | Billing | `/billing` | **8 / P1** | No mock branch. `tenantId` is a query param (`11`). |
| J25 | MCP / connectors | `/integrations` | **6 / P2** | CRM manages keys. Tool execution is a **separate process** with its own auth. |
| J26 | Roles + outbound switch | `/roles` | **6 / P2** | Real permission patches. Demo dialer lives on this page, not on Customer 360. |

---

## 3. Topology the journeys actually use

```text
Browser (Habibi :8080)
  │  apiGet/Post  (X-API-Key, X-Actor-User-Id)
  │  Pipecat SmallWebRTC ──► voice runner :7860  (/api/offer)
  ▼
FastAPI main:app :8000
  │  staff authz (ROUTE_PERMISSIONS) — Tool Grant is NOT this
  ├─ db.py / domain modules ──► Postgres
  ├─ twilio_ops / twilio_sms ──► Twilio
  ├─ whatsapp.py ──► Meta Cloud API
  ├─ azure_openai.py ──► Azure OpenAI (chat, embeddings)
  ├─ azure_speech / Pipecat AzureSTT/TTS ──► Azure Speech
  └─ MinIO (KB originals)

bot_worker          SKIP LOCKED: WA outbound, bot turns, PTP settle,
                    treatment enact, campaigns, cadence, closer, webhooks
worker              kb_index_jobs + nightly sweeps
voice.bot :7860     Pipecat; CRM via voice/persist.py (not bot_turn_jobs)
mcp_server :8081    separate process; not mounted on FastAPI
voice.workers.insurance   Redis mesh peer
```

**Two permission systems, two persistence spines, two Mouth runtimes.** Mixing them is how handoffs break:

| Pair | Intended split | Where journeys confuse them |
|------|----------------|------------------------------|
| Staff authz vs Tool Grant | Operator vs Mouth | Grant module imported only by tests. Voice/WhatsApp still compute tools locally. |
| `interactions` vs `call_attempts` | Connected media vs every dial | 360 “Log call” writes the first; audit `GET /calls` is the first; unanswered campaign dials live only on the second. |
| `voice.bot` vs `bot_turn_jobs` | Audio path vs WhatsApp/sandbox | Inbound PSTN never enters the bot-turn queue. A worker crash does not pause a live call; a live-call crash does not retry as a bot turn. |
| `/prompt-versions/:id/publish` vs `/agent-studio/cards/:id/publish` | Same `db.publish_prompt_version` | UI uses the former. The latter is an unused selector wrapper. |

---

## 4. Cross-cutting defects (before the journeys)

These are not journeys. They sit on almost every journey.

### 4.1 Dev default never leaves the building

`Habibi/src/api/config.ts:11-23` — `USE_MOCK` defaults **true** in development. Production throws if mock is forced. Every `api/*.ts` module except `billing.ts` has a seed branch. An operator following `npm run dev` without `VITE_USE_MOCK=false` exercises **none** of J8–J23.

### 4.2 The CRM almost never sends idempotency keys

Backend `_handle_write` accepts `Idempotency-Key` on create-interaction, wrap-up, create-promise, create-dispute, create-lead (`main.py:1540-1611`). Tests in `test_idempotency.py` prove the server side.

The frontend sends the header in **one** place: wrap-up (`handoff.ts:276-278`), and the value is ``wrap-${interactionId}-${Date.now()}``. A double-click or React Query retry is a new key. PTP, dispute, document, lead, and log-call creates send nothing.

### 4.3 `QueryState` is the product’s named #1 lie, used twice

`Habibi/src/components/ui/query-state.tsx:8-24` documents `query.data ?? []`. Adoption: `AgentCardPanels.tsx` only. Customer 360 insights uses the lie explicitly (`customers.$customerId.lazy.tsx:114`).

### 4.4 No login journey

`me.ts:7-8` — “Real authentication replaces the server side in Phase 5 (OIDC); this seam does not change when it does.” Identity is `GET /me` plus optional `VITE_API_KEY` / `VITE_ACTOR_USER_ID`. Report 19: shipped `API_KEY` empty, authz fail-open. J1 is therefore “open the app.”

### 4.5 Tool Grant is still test-only

`agent_core/tools/grant.py` is imported by `tests/test_tool_grant.py` and `tests/test_tool_grant_characterization.py` only. Production Mouths still assemble the grant in channel runtimes. ADR-0001/0002 are not on any live hop.

---

## 5. Journeys

### J1 — Operator identity  ·  risk 7 / P1

```text
START        Open Habibi (any nav item)
USER ACTION  None — there is no login form
FRONTEND     useMe() → fetchMe()                    api/me.ts:34-40
API          GET /me                                PUBLIC_ROUTES  authz.py:242
SERVICE      actor from API key / actor header
DATABASE     users row (or the seeded Priya Nair)
PROVIDER     none
RESPONSE     { id, name, kind, team, tenantId }
UI           TopBar name. Every write attributes this id.
```

**Broken handoff:** mock identity is `priya-nair` (`me.ts:25-32`). Live identity is whoever the server maps. If the header is missing and API_KEY is empty, report 19’s fail-open path applies. Presence (`GET/PATCH /me/presence`) is real; mock stores it in `localStorage`.

**Missing validation:** the client does not refuse to mutate when `useMe()` is in error. Mutations call `currentActor()` and will throw, or — if a cached `meCache` exists — write as a stale user.

---

### J2 — My workspace  ·  risk 4 / P3

```text
START        Nav “My workspace” → /
USER ACTION  View assigned queue, toggle availability
FRONTEND     useWorkspaceSummary, useWorkItems, usePresence
API          GET /work-items?assignee=me
             GET /workspace/summary
             GET/PATCH /me/presence
SERVICE      db work-item union (disputes, callbacks, docs, promises, followups, leads, bounces)
DATABASE     view over those tables, agent_presence
PROVIDER     none
UI           AssignedQueue buckets by entityType; NeedsAttention “start call” → J12
```

Live path is coherent. Mock omits followups/leads (`workspace.ts:73-79`). **NeedsAttention “start call” is J12** — a status patch — so the workspace’s most urgent button does not telephone anyone.

---

### J3 — Customer 360  ·  risk 8 / P1

```text
START        /customers → row click → /customers/$customerId
USER ACTION  Open overview, ledger, EMI, interactions, promises, disputes, documents, notes
FRONTEND     fetchCustomer GET /customers/:id
             fetchCustomerInsights GET /customers/:id/insights
             on failure: deriveCustomerInsights(customer)   customers.ts:45-59
             AND  insightsQuery.data ?? deriveCustomerInsights(customer)
                                                    customers.$customerId.lazy.tsx:114
API          GET /customers/:id
             GET /customers/:id/insights
             GET /customers/:id/contact-policy          (pill, J4)
             GET /authority/next                        (overview)
SERVICE      db customer aggregate; treatment/authority engines for insights
DATABASE     customers, accounts, ledger, emi, interactions, promises, disputes, documents, notes, consent
PROVIDER     none on the read path
UI           Header + tabs. NBA rail. Action sheets for PTP / dispute / document / log call.
```

**Broken handoff (policy in the browser):** `fetchCustomerInsights` catches **any** error — 500, 422, network — logs it, and derives offline. The lazy route *also* substitutes derived insights whenever `data` is undefined (pending **or** error). Report 03 named this. It is still the live render path.

`lib/customerInsights.ts` still contains a client NBA ladder. Comments say the engine owns contact; the fallback reintroduces the second opinion the comments exist to forbid.

**UI without backend (partial):** `logInteraction` → J5. `createPromise` from 360 posts `/promises` but 360’s mock PTP has no `ownerUserId` resolution (the promises screen does). Two create-PTP clients, different bodies.

---

### J4 — Contactability pill  ·  risk 8 / P1

```text
START        Customer header
USER ACTION  Look at the chip (no click)
FRONTEND     useContactPolicy → GET /customers/:id/contact-policy?channel=voice&purpose=outreach
             ContactabilityPill: pending / error / allowed / reason-code
             Fail-closed formatter: unknown reason is non-green   ContactabilityPill.tsx:36-39
API          GET …/contact-policy
SERVICE      contact_policy.admit (dry-run on this endpoint)
DATABASE     consent, contact_events, contact_day_counters
PROVIDER     none
UI           Green only when allowed === true
```

This is one of the better UI hops in the product. Tests in `ContactabilityPill.test.ts` pin fail-closed rendering.

**The engine behind the pill still fail-opens:** `contact_policy.py:1020-1024` — on exception, `purpose == "outreach"` denies; every other purpose returns `Decision(True)`. Statutory bounce (J23) and in-session tools use those purposes. K3 verified.

`admit` also skips cooling-off and both caps when `_session_coalesced` is true (`contact_policy.py:965-971`). The dial endpoints pass `session_key=customer_id` (J13). That is K1.

---

### J5 — Log call  ·  risk 8 / P1

```text
START        Customer 360 → QuickActionsRail “Log call”
USER ACTION  Pick a disposition, submit
FRONTEND     logInteraction → POST /interactions   customers.ts:159-196
API          POST /interactions                    COLLECTIONS_WRITE
SERVICE      db.create_interaction
DATABASE     interactions (connected-call spine). No call_attempts row.
PROVIDER     none
RESPONSE     interaction contract
UI           Interactions tab gains a voice outbound row that never rang.
```

**UI functionality without backend support for the thing the label means.** The rail icon is `PhoneCall`. The hop is a CRM note shaped like a call. Audit `GET /calls` (J-audit) will show it. Outbound stats (`/outbound/attempts`) will not. A collections head reconciling “calls today” against “attempts today” sees two numbers.

No `Idempotency-Key`. Double-submit → two rows.

---

### J6 — Promise to pay  ·  risk 7 / P1

```text
START        /promises  or  360 action sheet
USER ACTION  Create / move status / reschedule / resend confirm / build plan
FRONTEND     promises.ts  POST /promises, PATCH /promises/:id,
             POST /promises/:id/resend-confirm, POST /payment-plans
             360 createPromise also POST /promises (thinner body)
API          as above
SERVICE      db.create_promise → promise_fulfillment (reminders, auto-break)
DATABASE     promises, payment_intents (on confirm), activity_events
PROVIDER     WhatsApp/SMS confirm via bot_worker.promise_fulfillment
UI           Kanban. Mock mutates seeds in place; live invalidates.
```

**Missing validation:** CRM create sends no idempotency key (`promises.ts:50-63`). Voice PTP *does* key by call (`test_voice_write_idempotency.py`, `test_idempotency.py`). The operator path is the weaker one.

**Inconsistent state:** moving a promise to kept with `paidAmount` patches status. Actual money is J22. A kept PTP with no ledger payment is a legal CRM state and a lie about cash.

Settle/break is `promise_fulfillment.settle_promises`, run every 20th `bot_worker` iteration (`bot_worker.py:72-76`). If the worker is down, the board freezes at “upcoming” past due date. UI has no “worker stale” signal.

---

### J7 — Document desk  ·  risk 8 / P1

```text
START        /documents  or  360 “Send statement”
USER ACTION  Create request, assign, channel, template, retry delivery
FRONTEND     documents.ts  POST /document-requests  requestedVia: "agent"
             360 createDocumentRequest omits requestedVia
API          POST /document-requests
             PATCH /document-requests/:id
             POST /document-requests/:id/delivery-attempts
             inbox also POST /document-requests/ingest (multipart)
SERVICE      db.py writers
DATABASE     document_requests.requested_via CHECK includes bot_voice, agent, …
             Write path stores the real value (db.py:6268 in report 11)
PROVIDER     email / WhatsApp delivery (worker)
RESPONSE     list/detail
UI           Desk queue. 360 documents tab.
```

**Broken handoff (P0 from report 11, still live):** `_document_contracts` selects `requested_via` and then returns `"requestedVia": "voice"` (`db.py:1440-1455`). Every 360 document row tells the operator the Mouth asked for it. The desk list uses a different serializer (report 11); 360 is the fabricated one.

360 create omits `requestedVia`; server defaults to `"agent"` on write, then 360 read paints `"voice"`. Three values for one field across one journey.

---

### J8 — Inbox send  ·  risk 7 / P1

```text
START        /inbox
USER ACTION  Take over thread, type, send; optional RAG refresh
FRONTEND     GET /conversations (?updatedAfter= delta poll)
             POST /conversations/:id/takeover | /return-to-bot | /messages
             POST /conversations/:id/suggestions/refresh
API          as above
SERVICE      db message insert + enqueue whatsapp_outbound_jobs
DATABASE     conversations, messages (delivery_status sending→sent|failed),
             whatsapp_outbound_jobs
PROVIDER     Meta Cloud API via whatsapp_outbound.handle_job
UI           Thread. Deltas merge; compareThreads sorts by updatedAt then id
             (inbox.ts:74-79 — a real bug they already fixed)
```

**Provider hop is J8b / K5:** send succeeds, then a second transaction stamps `delivery_status='sent'` (`whatsapp_outbound.py:548-564`). If that write throws, `process_one` dead-letters only for ambiguous *transport* strings (`mark_failed_or_retry`, `:293-328`). A Postgres error string is not in that classifier → retry → second Meta send. The inbox will eventually show one failed or two sent; the handset got two.

**Missing error recovery:** mock send mutates the seed and returns; there is no delivery-failed state in the mock. Dev default mock teaches a 100% send rate.

---

### J9 — Inbound WhatsApp  ·  risk 7 / P1

```text
START        Borrower taps send in WhatsApp
USER ACTION  none in CRM
FRONTEND     none (inbox poll discovers it)
API          GET /webhooks/whatsapp  (verify)   PUBLIC
             POST /webhooks/whatsapp            PUBLIC, X-Hub-Signature-256
SERVICE      whatsapp.verify_signature → db.process_whatsapp_webhook
             savepoint per message   db.py:10925-10947
             enqueue bot_turn_jobs if BOT_RUNTIME_ENABLED
DATABASE     conversations, messages, bot_turn_jobs
PROVIDER     Meta (inbound). Azure OpenAI on the bot-turn hop (bot_runtime)
RESPONSE     200 to Meta even if a sibling message’s savepoint rolled back
UI           Inbox delta within ~poll interval. Bot reply appears after worker.
```

**Duplicated orchestration:** WhatsApp bot turns go through `bot_jobs` + `bot_runtime` (Azure `chat_with_tools`). Voice turns go through Pipecat + `voice/bot.py` (KeepAliveAzureLLMService). Same tool catalog, two runtimes, two grant formulas. A tool allowed on WhatsApp can be missing on voice (and vice versa) without a compile error.

If `BOT_RUNTIME_ENABLED` is off, inbound messages land and nobody replies. UI shows an unanswered thread with no “bot runtime off” banner.

---

### J10 — Handoff hub  ·  risk 6 / P2

```text
START        /handoff
USER ACTION  Claim pending transfer, read disclosures, accept suggestion, wrap up
FRONTEND     GET /handoff/queue, /handoff/active, /handoff/:id
             POST /handoff/:id/claim | /disclosures | /suggestions/:sid/accept
             POST /interactions/:id/wrap-up
API          as above
SERVICE      db handoff + wrap_up_interaction (may spawn PTP)
DATABASE     interactions.handler, handoff rows, promises if wrap-up includes PTP
PROVIDER     none on claim. Live audio stays on the voice runner.
UI           2s poll while claimed. Mock is a scripted seed.
```

**Missing error recovery:** wrap-up `Idempotency-Key` is `wrap-${id}-${Date.now()}` (`handoff.ts:277`). Retry creates a second wrap-up. If wrap-up also inserts a PTP, that is a second promise.

**Inconsistent state:** wrap-up `disposition` is the CRM word. Closer writes `call_outcomes.business`. Cadence keys off the latter. A human wrap-up does not run the Closer. Cadence may retry a call the human already settled, or not retry one they marked refused. Strong inference — wrap-up and Closer are different writers; no join test exists.

---

### J11 — Floor command  ·  risk 6 / P2

```text
START        /floor
USER ACTION  Watch live calls, ack alerts, listen / whisper / barge / force_handoff
FRONTEND     GET /floor (3s poll), EventStream copilot
             POST /supervisor-actions { interactionId, action, note }
             POST /floor/alerts/:id/ack
             GET /floor/copilot/:id[/stream]
API          as above
SERVICE      live_qa.enact.barge_audio / whisper; Twilio conference ops
DATABASE     live_qa decisions, floor alerts
PROVIDER     Twilio (barge audio). Azure (copilot draft).
UI           LiveTable + Inspector. Mock: audioJoined false, seed calls.
```

**Provider bypass (labelled):** barge goes through `agent_core/live_qa/enact.py`, not through `outbound.place`. That is correct — it is same-call, not a new dial — but contact_policy is not re-asked. A barge is a second voice on a session already admitted.

Auto-barge is `LIVE_QA_BARGE_MODE`. Shadow shows “Would barge”; the click still required. UI does not surface the mode; a floor supervisor cannot tell shadow from live without env.

---

### J12 — Callback start call  ·  risk 8 / P1

```text
START        /callbacks  or  workspace NeedsAttention
USER ACTION  “Start call”
FRONTEND     startCall() → PATCH /callbacks/:id { status: "in_progress" }
             api/callbacks.ts:143-149
API          PATCH /callbacks/:id
SERVICE      status update
DATABASE     callbacks.status
PROVIDER     none
UI           Row moves to in-progress. Phone does not ring.
```

**The most complete UI-without-backend in the console.** The mock seed function is also named `startCall`. Live copied the name and not the network. Compare J13, which actually calls Twilio, and is hidden on `/roles`.

---

### J13 — Demo outbound  ·  risk 10 / P0

```text
START        /roles  (not Customer 360)  OutboundControlPanel
USER ACTION  Toggle outbound.enabled / demo_ignores_window; click Place demo call
FRONTEND     GET /platform/switches
             PATCH /platform/switches/:key
             GET /demo/outbound-call     (dry-run target + policyReason)
             POST /demo/outbound-call
API          BOT_READ / VOICE_OPERATE    authz.py:600-602
SERVICE      mission.build → outbound.reserve → contact_policy.admit
             session_key=customer_id     main.py:4097-4105
             optional demo waiver for window/caps
             outbound.place → twilio_ops.start_outbound_call
DATABASE     call_attempts (reserved→dialing|suppressed), contact_events
PROVIDER     Twilio Programmable Voice → Media Streams → voice.bot
RESPONSE     { placed, attemptId, callSid }
UI           toast “Demo call placed”. Floor / 360 may show the call once media connects.
```

**K1 verified:** `session_key=customer_id` coalesces. Cooling-off, daily cap, weekly cap are not reserved or incremented on this endpoint (`contact_policy.py:965-971`). `POST /twilio/voice/outbound` (`main.py:3782`) is the same pattern. The CRM **does not call** `/twilio/voice/outbound` at all (`Habibi` grep: only `/demo/outbound-call` in `platform.ts`).

**K2 verified:** `outbound.reserve` has no idempotency key, no `ON CONFLICT`, no non-terminal-state check. Double-click Place demo call → two reserves → two Twilio calls. UI mutation has no client debounce beyond React Query’s default.

**Backend capability without UI:** `POST /twilio/voice/outbound` is the generic manual dial. No Habibi client calls it. There is no customer-360 “Ring this number” that uses the real pipeline.

---

### J14 — Campaign outbound  ·  risk 10 / P0

```text
START        Agent studio → Outbound tab (not a sidebar item)
USER ACTION  Preview cohort, create run, start/pause
FRONTEND     GET/POST /outbound/campaigns, /preview, /:id/status
             GET /outbound/attempts|stats|cadence|reasons|missions|number-pools
API          as above
SERVICE      campaigns.process_one (bot_worker)
             reserve + admit + outbound.place
DATABASE     campaign_runs, campaign_targets, call_attempts, call_cadence_state
PROVIDER     Twilio
UI           Campaign table + reach stats. Attempt ledger is the unanswered-dial spine.
```

**K4 verified:** `outbound.place` on any Twilio exception returns `{placed: false, state: failed, reason: dial_failed}` (`outbound.py:743-751`) — including timeouts where the INVITE may have left. `campaigns.py:610-625` then sets the target back to `pending` with `next_attempt_at + 5 minutes`. Ambiguous failure is retried as if it did not happen.

`fleet_busy` uses the same requeue. That one is correct. The code does not distinguish them.

Closer (`call_closer.process_one`) is a later hop: claims `call_attempts` where `closed_at IS NULL`. Cadence (`cadence.process_one`) must not change the Mission — it retries the same objective. UI cadence table is a read of that state, not a second orchestrator.

---

### J15 — Inbound / connected voice  ·  risk 8 / P1

```text
START        Borrower dials Twilio number  OR  outbound media connects
USER ACTION  Speak
FRONTEND     none (operator sees Floor / Handoff if escalated)
API          POST /twilio/voice/incoming     PUBLIC, Twilio signature
             WS /ws  or voice runner Media Stream
SERVICE      twilio_ops TwiML <Connect><Stream>
             voice.bot Pipecat pipeline
             STT/TTS via voice/provider_bind.py (registry, Azure fallback)
             tools via voice/tools.py (not grant.py)
             CRM writes via voice/persist.py + crm_sink (off audio path)
DATABASE     interactions, voice_sessions, transcript, tool traces
             call_attempts updated on status callbacks
PROVIDER     Twilio Media Streams, Azure STT/TTS (or bound Cartesia etc.),
             Azure OpenAI (KeepAliveAzureLLMService), Silero VAD,
             Redis mesh (optional insurance worker)
RESPONSE     audio. Never raise on the audio path (voice/bot.py contract)
UI           Floor tile once interaction exists. Handoff if escalate_to_human.
```

**Provider bypass (documented, still a bypass):** `provider_bind.py:13-20` — unbound slot falls back to Azure so registry rollout is not an outage. Operator can publish Cartesia in Agent Studio, hear preview (`POST /tts/preview`), and still talk to Azure on the real call until a binding exists. Provenance is written to `session.extra["providers"]`. UI does not show “this call used the fallback.”

**Grant unused:** tools available mid-call are the channel formula, not `ToolGrant`. Cardless Mouth fail-opens (ADR-0002 not wired). Mid-call handoff does not refresh the grant (architecture-forensics).

**Persistence split:** persist.py keeps writes off `db.py`’s contended surface. Closer runs later on `bot_worker`, after a grace so CrmSink can drain. If the worker is down, Floor shows a live call whose Outcome does not exist yet. Cadence waits on Closer. That delay is load-bearing and unsignalled.

Twilio status: `POST /twilio/voice/call-status` (PUBLIC). SMS status: `POST /twilio/sms/status` (PUBLIC). Signature check inside the handler.

---

### J16 — Treatment  ·  risk 9 / P0

```text
START        /treatment  (operator)     bot_worker  (enact)
USER ACTION  Inspect next/insights/metrics/holds; place or release a hold
FRONTEND     GET /treatment/next|insights|metrics|model-health|models|holds|cases
             POST /treatment/holds  POST /treatment/holds/:id/release
API          as above. next_treatment writes a decision even in shadow.
SERVICE      agent_core.treatment engine
             enact.process_one only if TREATMENT_MODE=live   enact.py:906-908
DATABASE     treatment_decisions, treatment_holds, then outbound/WhatsApp on enact
PROVIDER     Twilio or Meta, depending on chosen_action
UI           Scoreboard. Explicitly read-only for the caller
             (treatment.lazy.tsx copy: “outside live mode it enacts nothing”).
```

There is **no Enact button**. Live contact is a worker. That is the right split. The risk is the worker hop:

**K6 verified, mechanism updated.** `process_one` still `engine.begin()` → `claim_due` → `enact_one` (`enact.py:904-912`). `_dial_bot` now reserves on its **own** connection so `outbound.place` can see the row (`:317-384`), then `place` talks to Twilio, then `mark_enacted` runs on the outer `conn` (`:135-136`). If the outer transaction rolls back after Twilio accepted the call, the decision is unclaimed and the next `process_one` dials again. Report 14’s “one transaction” description is now “outer transaction still spans the dial.” Same outcome.

`admit` on enact uses `session_key=decision_id` (`:107`) — coalescing does not fire the K1 pattern here. Good.

---

### J17 — Reco / upsell  ·  risk 8 / P1

```text
START        /upsell  (operator)     Mouth tool decline_offer  (borrower)
USER ACTION  Move lead stage, revalidate, schedule follow-up
FRONTEND     GET/POST/PATCH /leads, /leads/metrics, /followups
API          as above
SERVICE      reco engine on capture; lead pipeline; nightly revalidate in worker
DATABASE     leads, followups, reco decisions
PROVIDER     none on CRM writes. Mouth path uses Azure + capture.record_offer_declined
UI           Lead kanban
```

**K10 verified:** `_tool_decline_offer` (`bot_tools.py:536-556`) returns `{"ok": true, "say": "…do not raise it again"}` even when `capture.record_offer_declined` throws. The Mouth will not mention the product; the next call will, because the refuse row is missing.

CRM lead revalidate is `POST /leads/:id/revalidate?channel=` — a real engine hop. Worker also revalidates open leads at 01:15 UTC (`worker.py:72-79`). Two schedulers, same flags; UI does not say which one last ran.

---

### J18 — Mouth compile / publish  ·  risk 5 / P2

```text
START        Nav “Agent studio” → /agent-studio  ( /prompt-studio redirects here )
USER ACTION  Edit card, compile preview (debounced 400ms), Publish
FRONTEND     PATCH /agent-studio/cards/:botId
             POST /agent-studio/cards/:botId/compile     (preview)
             publishStudioDraft:
               PATCH/POST /prompt-versions
               POST /prompt-versions/:id/publish          prompt-studio.ts:944-991
API          compile and publish both run compile_card G0–G15
SERVICE      db.publish_prompt_version  (advisory lock per bot+env)
             flow_graph validation → 422 flow_invalid
DATABASE     prompt_versions.status draft→published, bot_deployments swap
PROVIDER     none (eval suites may have run Azure earlier)
UI           PublishDialog + CompileReportList. Gates block the button.
```

**Duplicated orchestration (HTTP only):** `POST /agent-studio/cards/{bot_id}/publish` (`main.py:2119-2158`) picks a draft and calls the same `publish_prompt_version` handler. **No Habibi module calls it.** Not an orphan capability — an unused selector. The UI already knows `draftId`.

**Empty card skips G0:** `db.py:14384` comment: “Empty card is legacy (G0 skipped).” A bot with no authored card can still publish prompt text. That is the cardless Mouth that ADR-0002 wanted to grant nothing.

Outbound campaigns (J14) are a *tab on this editor*, not a nav item. Operators who do not open Agent studio never see campaign controls.

---

### J19 — Sandbox  ·  risk 5 / P2

```text
START        /sandbox
USER ACTION  Pick scenario, type a customer turn, or start a live WebRTC call
FRONTEND     POST /sandbox/runs  POST /sandbox/runs/:id/turns
             POST /voice/sandbox/start  → Pipecat SmallWebRTC to webrtcUrl
             GET /voice/status
API          sandbox_runtime uses azure_openai.chat_with_tools
             voice sandbox talks to the runner
SERVICE      retrieve + Azure chat (text). voice.bot (audio), tagged sandbox
DATABASE     sandbox_runs, sandbox_turns. Voice may also write persist rows.
PROVIDER     Azure OpenAI. Azure Speech. Browser WebRTC to :7860
             (Vite proxy /voice-rtc). Bypasses FastAPI for media.
UI           Transcript + tuning. Promote publishes via J18.
```

**Mock fabricates a live path:** `voice-sandbox.ts:34-40` returns `webrtcUrl: "/voice-rtc/api/offer"` even though `fetchVoiceStatus` in mock says `ok: false`. Start can look connected to a worker that is not there.

`fetchVoiceStatus` live catch returns `{ok:false}` instead of throwing (`:20-24`) — a failed GET looks like a healthy “worker down” status, which is the honest version. Rare in this codebase.

Text sandbox mock uses `generateBotReply` locally — no Azure, no retrieve. Dev default mock is a script, not the compiler.

---

### J20 — Knowledge base  ·  risk 5 / P2

```text
START        /knowledge-base
USER ACTION  Upload, reindex, edit FAQ, promote gap to skill
FRONTEND     apiUpload → POST /kb/documents (multipart)
             GET jobs, POST reindex, DELETE faqs, POST /kb/gaps/:id/promote-skill
API          as above
SERVICE      insert kb_index_jobs; worker.process_one → kb_ingest
DATABASE     kb_documents, chunks, faqs, kb_index_jobs, kb_gaps
PROVIDER     Azure embeddings (azure_openai). MinIO for originals.
UI           Job status poll. Gaps table.
```

If `worker` is down, uploads sit in `queued`. UI shows the job; there is no global “indexer stalled” banner. Nightly TTS catalog sync lives in the same process (`worker.py:40-64`) — a hung ingest loop delays voice-catalog refresh, which Agent studio voice pickers then show stale.

---

### J21 — Consent / DND  ·  risk 6 / P2

```text
START        /consent
USER ACTION  Save window, renew, opt-out, toggle DND
FRONTEND     GET /consent
             PATCH /consent/:customerId
             POST /consent/:customerId/opt-out
API          as above
SERVICE      consent writers; contact_events
DATABASE     consent, dnd flags, contact_day_counters (read for the list)
PROVIDER     none
UI           Registry. Caps/today counts from ledger_usage
```

The numbers on this screen are the evidence K1 makes wrong. An operator who just placed three demo calls sees one counted touch. The pill (J4) and this table disagree with the handset, and agree with each other.

---

### J22 — Pay-by-link  ·  risk 9 / P0

```text
START        Borrower opens GET /pay/{token}     PUBLIC
USER ACTION  Pay (demo complete POST /pay/{token}/complete)
             or bank POST /webhooks/payments/{provider}
FRONTEND     none (HTMLResponse, not Habibi)
API          public pay page + webhooks. Sandbox: POST /sandbox/payment-events (staff)
SERVICE      payments.record_payment
DATABASE     payment_intents, ledger_entries, promises allocation, payment_events cure
PROVIDER     payment aggregator (or mock complete)
RESPONSE     { ok, idempotent? }
UI           CRM sees kept PTP / ledger on next fetch. No push.
```

**K8 verified:** if `intent["status"] == "paid"`, return `{ok: true, idempotent: true}` (`payments.py:149-150`) **without comparing `provider_ref`**. A second real payment with a new provider_ref on a already-paid intent is discarded. Comment in report 14: `db.py` already keys a *text message* on provider_ref; money does not.

**K9 verified:** `cure_for_account` exception is logged and swallowed (`payments.py:238-239`); the function still returns `ok: true` with `curedEvents: []`. Bounce rows stay open. Treatment may still dial (J16) for a debt the ledger just closed.

---

### J23 — Bounce first-touch  ·  risk 9 / P0

```text
START        payment_events.process_one (bot_worker)
USER ACTION  none
FRONTEND     none (compliance / workspace may later show the bounce)
API          none
SERVICE      admit WhatsApp or SMS; send pay-link
DATABASE     payment_events.first_touch_at, payment_intents.status sent
PROVIDER     Meta or twilio_sms
UI           none at send time
```

**K7 verified:** `payment_events.py:664-675`

```python
if twilio_sms.configured():
    twilio_sms.send(...)
sent = True   # sibling of the if, not inside it
```

If SMS is the chosen channel and Twilio SMS is not configured, the event is marked first-touched. Statutory notice is a regulated artefact. The record says it was served.

`admit` here uses purpose that is not always `outreach`. Combined with K3, a consent-table exception can allow the send.

---

### J24 — Billing  ·  risk 8 / P1

```text
START        /billing
USER ACTION  Change period / tenant / env; export CSV; edit budget rules
FRONTEND     fetchBilling(period, tenantId, env)  — no USE_MOCK branch
             billing.ts:86-93
API          GET /billing?period&tenantId&env     BILLING_READ
             GET /billing/export.csv
             POST/PATCH/DELETE budget rules
SERVICE      db.billing_overview
DATABASE     usage / budgets / invoices
PROVIDER     none
UI           Charts. Empty API key + mock-off is the only way this page works in dev
             (because there is no seed path).
```

**Tenancy as client input:** `tenantId` query default `"all"` (`main.py:1017-1025`). Every other route uses `db.current_tenant()`. Report 11: IDOR-shaped; inert while one tenant is seeded. Still the hop.

---

### J25 — Integrations / MCP  ·  risk 6 / P2

```text
START        /integrations
USER ACTION  Toggle providers, approve connectors, mint MCP keys, vault rotate
FRONTEND     /providers, /connectors, /vault/refs, /mcp/keys|status|tasks,
             /gateway/status|canary, /a2a/partners
API          staff-authz
SERVICE      provider registry; mcp key table
DATABASE     provider bindings, connectors, vault refs, mcp_keys
PROVIDER     MCP server is `python -m mcp_server` — not mounted on FastAPI
             mcp_server.py:1-25 (auth would break SSE; mounting would skip API key)
UI           McpConsole
```

**Alternate API that bypasses FastAPI authz.** Stdio transport: process boundary is the auth boundary. Network transport requires `MCP_API_KEY`. Tools are the collections catalog (`mcp_tools.call_tool`). A minted key in the CRM is not the same check as `ROUTE_PERMISSIONS`.

Provider test buttons call `POST /providers/:id/test` — canonical. Voice runtime still constructs Azure STT/TTS via `provider_bind` fallback (J15). Studio preview (`POST /tts/preview`) is a third path (`apiPostBlob` in prompt-studio.ts). Three ways to hear a voice; only one is the call.

---

### J26 — Roles & outbound switch  ·  risk 6 / P2

```text
START        /roles
USER ACTION  Toggle permission chips; flip outbound.enabled; place demo call (J13)
FRONTEND     GET roles catalog, PATCH /roles/:id/permissions
             OutboundControlPanel
API          AGENT_EDIT-class role patches; platform switches; demo dial
SERVICE      authz grant rows; platform_switches
DATABASE     role_permissions, platform_switches
PROVIDER     Twilio on demo click
UI           Permission matrix + the only Ring button in the product
```

Report 19 P0-1: revoking a role’s access restores defaults. That is this screen’s mutation. Combined with J13 on the same page, a collections admin can both widen grants and dial the demo number without opening Customer 360.

---

## 6. Handoff map (the joins that fail)

| From hop | To hop | What should happen | What happens |
|----------|--------|--------------------|--------------|
| J12 Start call | J13/J15 | PSTN via reserve→place | Status patch only |
| J5 Log call | J14 attempt ledger | An attempt row | `interactions` only |
| J6 kept PTP | J22 ledger | Payment posted | Status can move without money |
| J10 wrap-up refused | Closer / cadence | Same Outcome vocabulary | Different writer, different table |
| J18 publish Cartesia | J15 runtime | Bound provider speaks | Azure fallback until binding exists |
| J8 send | Meta | Exactly-once | K5 retry after DB-post-send |
| J14 place fail | campaign_targets | Ambiguous → do not redial | Always requeue in 5 minutes |
| J16 claim | Twilio | Dial committed with decision | Outer rollback redials |
| J4 pill green | J13 dial | Caps incremented | Coalesced session skips caps |
| J7 write requested_via | J3 documents tab | Echo the column | Hardcoded `"voice"` |
| J17 decline_offer | next call reco | Product suppressed | Write can fail; tool still says ok |
| J23 SMS | payment_events | first_touch only if sent | first_touch if channel picked |
| J10 wrap-up retry | promises | One PTP | Date.now() key → N wrap-ups |

---

## 7. Orphans

### 7.1 API with no Habibi consumer (not unused — other callers)

These are journeys that start outside the CRM. They are not orphans.

| Route | Caller |
|-------|--------|
| `POST /twilio/voice/*` (incoming, fallback, stream-status, call-status) | Twilio |
| `POST /twilio/sms/status` | Twilio |
| `GET/POST /webhooks/whatsapp` | Meta |
| `GET/POST /pay/{token}` | Borrower browser |
| `POST /webhooks/payments/{provider}` | Bank |
| `WS /ws` | Media / signalling |
| `POST /api/offer` | Pipecat WebRTC (public) |

### 7.2 API the CRM could use and does not

| Route | Notes |
|-------|--------|
| `POST /twilio/voice/outbound` | Generic manual dial. UI uses only `/demo/outbound-call`. |
| `POST /agent-studio/cards/{bot_id}/publish` | Wrapper around the publish the UI already calls by version id. |
| `POST /sandbox/payment-events` | Staff injector for bounce/pay tests. No screen. |

### 7.3 UI with no live backend for the labelled action

| UI | What it calls | What the label implies |
|----|---------------|------------------------|
| Callbacks / workspace “Start call” | `PATCH` status | Ring the borrower |
| 360 “Log call” | `POST /interactions` | A telephone call |
| Insights NBA on API error | `deriveCustomerInsights` | Engine recommendation |
| Sandbox Start (mock) | fake `webrtcUrl` | Live Mouth |
| Billing in default `npm run dev` | live GET, no mock | Page errors unless mock is off **and** API is up |

### 7.4 Backend capability without a screen

| Capability | How it runs | Operator visibility |
|------------|-------------|---------------------|
| Treatment enact | `bot_worker` when `TREATMENT_MODE=live` | Scoreboard counts; no “enacted just now” toast |
| Call closer | `bot_worker` on `call_attempts` | Outcome appears later on attempt rows |
| Cadence retry | `bot_worker` | Cadence table in studio Outbound tab |
| Bounce voice last-resort | `payment_events.process_one_voice` | Weak |
| Insurance mesh specialist | Redis peer process | Floor may show a role change |
| MCP tool invoke | `mcp_server` | Task list only |
| Nightly lead revalidate, TTS sync, gardener, QA autoscore | `worker` | None |

---

## 8. Provider abstraction vs bypass

| Provider | Canonical adapter | Who bypasses it |
|----------|-------------------|-----------------|
| Azure OpenAI | `azure_openai.py` (semaphores, usage meter, analysis vs chat profiles) | Voice LLM is Pipecat `KeepAliveAzureLLMService` (`voice/latency.py`), not `azure_openai.chat_with_tools`. WhatsApp/sandbox/copilot use the canonical client. **Two Azure chat stacks.** |
| Azure Speech | `azure_speech.py` + Pipecat AzureSTT/TTS | `provider_bind` may substitute Cartesia/Deepgram; fallback reconstructs Azure directly. `/tts/preview` is a third client (`apiPostBlob`). |
| Twilio Voice | `voice/twilio_ops.py` + `outbound.place` | Floor barge (`live_qa.enact`). Demo and campaigns go through `place`. |
| Twilio SMS | `twilio_sms.py` | J23 sets `sent=True` even when `configured()` is false. |
| Meta WhatsApp | `whatsapp.py` + `whatsapp_outbound.py` | Inbox send does not call Meta from FastAPI; the worker does. Correct. |
| Redis | `voice/mesh_bus.py` | Optional. Without `REDIS_URL`, in-process bus. Insurance sidecar no-ops across processes. |
| MinIO | KB ingest | Not on operator hops except upload. |

Frontend talks to a provider **once**: Pipecat SmallWebRTC in `useSandboxLiveCall.ts` (and production voice if the operator is in sandbox). All other provider I/O is server-side. That is the right split.

---

## 9. Failure-path matrix

Rows are journeys. Columns are hops. Cell is what the operator / borrower / record sees. K-ids are report 14, re-verified.

| Journey | FE validation | API 4xx/5xx | DB fail | Provider timeout | Worker crash | Refresh mid-mutation |
|---------|---------------|-------------|---------|------------------|--------------|----------------------|
| J3 insights | n/a | **derived NBA (lie)** | derived | n/a | n/a | derived while pending |
| J4 pill | n/a | non-green (good) | K3 fail-open on non-outreach | n/a | n/a | refetch 60s |
| J5 log call | disposition required | toast | error toast | n/a | n/a | duplicate row (no idem) |
| J6 PTP | sheet | toast | error | n/a | reminders stall | duplicate PTP |
| J8 WA send | empty text | toast | K5 retry/double-send | dead-letter if ambiguous (good) | message stuck `sending` | duplicate job possible |
| J10 wrap-up | n/a | toast | error | n/a | n/a | **new idem key** |
| J12 start call | n/a | toast | status not moved | n/a | n/a | two PATCHes, still no dial |
| J13 demo dial | switches refetch | 409 policy / 502 twilio | attempt reserved | K2 no key; K1 caps off | attempt stuck reserved | **second call** |
| J14 campaign | n/a | n/a (worker) | target pending | **K4 requeue** | SKIP LOCKED reclaim | n/a |
| J15 voice | n/a | TwiML hangup | CrmSink degraded | never-raise audio; persist later | in-call drop; Closer missing | n/a |
| J16 enact | n/a | n/a | **K6 redial** | NoExecutor, plan cancelled | reclaim → redial | n/a |
| J17 refuse | n/a | tool ok | **K10 swallowed** | n/a | n/a | n/a |
| J22 payment | amount | 4xx | **K8/K9 ok:true** | webhook retry | n/a | second POST discarded or double |
| J23 bounce | n/a | n/a | n/a | **K7 sent without SMS** | event retries | n/a |
| J24 billing | n/a | page error (no mock) | error | n/a | n/a | n/a |

`retryUnlessClientError` (`config.ts:157-168`) stops RQ from retrying 4xx except 408/429. That is correct and under-adopted; many hooks still use defaults.

---

## 10. Test coverage vs journeys

| Layer | What exists | What is missing |
|-------|-------------|-----------------|
| Frontend vitest (11 files) | Contactability fail-closed; inbox merge; outbound types; sandbox; contact-policy mock port; confirm-gate | No test that `startCall` does not dial. No test that insights fallback is an error. No test that wrap-up keys are stable. No test that `/twilio/voice/outbound` is unused. |
| Backend seam tests | place contract, inbox channel Literal, agent-card schema drift, PTP idempotency (voice), Twilio signature, treatment engine, campaign, contact_policy, payments | No test that CRM `POST /promises` without a key double-inserts. No test that demo `session_key=customer_id` skips caps (K1 is described, not journey-tested from HTTP). |
| Browser e2e | **none** | Every J* |
| Contract triangle (report 11) | one column, one card | remaining vocabularies |

The cheapest journey tests, given what already exists:

1. HTTP: `POST /demo/outbound-call` twice → two `call_attempts` (K2) and `touch_counted` still 1 (K1).
2. HTTP: `PATCH /callbacks/:id` `{status:in_progress}` → zero Twilio client calls.
3. HTTP: GET customer documents → `requestedVia` equals the column.
4. Worker: WhatsApp send then raise on the status UPDATE → job not retried.
5. UI: wrap-up header does not contain a timestamp.

---

## 11. Nav → route → primary live API

Sidebar from `Sidebar.tsx:57-103`. `prompt-studio` key still names the Agent studio item; `/prompt-studio` redirects (`prompt-studio.tsx:13-21`).

| Nav | Route | Primary API modules |
|-----|-------|---------------------|
| My workspace | `/` | `workspace`, `presence`, `me` |
| Conversation inbox | `/inbox` | `inbox` |
| Handoff hub | `/handoff` | `handoff` |
| Floor command | `/floor` | `floor` |
| Executive dashboard | `/dashboard` | `dashboard` |
| Customer 360 | `/customers` | `customers`, `contact-policy`, `authority` |
| Promise to pay | `/promises` | `promises` |
| Disputes queue | `/disputes` | `disputes` |
| Document desk | `/documents` | `documents` |
| Callbacks | `/callbacks` | `callbacks` |
| Upsell & leads | `/upsell` | `upsell`, `products`, `teams` |
| Decision intelligence | `/treatment` | `treatment` |
| Audit trail | `/audit` | `audit` (`GET /calls`) |
| Compliance risk | `/compliance` | `compliance` |
| Consent / DND | `/consent` | `consent` |
| Redaction & export | `/redaction` | `redaction` |
| QA scorecards | `/qa` | `qa` |
| Bot analytics | `/bot-analytics` | `bot-analytics` |
| Knowledge base | `/knowledge-base` | `kb` |
| Agent studio | `/agent-studio` | `agent-studio`, `prompt-studio`, `outbound`, `flow` |
| Call sandbox | `/sandbox` | `sandbox`, `voice-sandbox` |
| Routing / logic | `/routing` | `routing` |
| Integrations | `/integrations` | `integrations`, `providers` |
| Webhooks | `/webhooks` | `webhooks` |
| Billing & usage | `/billing` | `billing` |
| Roles & access | `/roles` | `agent-studio` roles + `platform` |

Hidden routes: `/prompt-studio` (redirect), `/agent-studio/$botId`, `/agent-studio/skills/*`, `/customers/$customerId`.

---

## 12. Checked and cleared

| Hypothesis | Result |
|------------|--------|
| Prompt studio is a second Mouth editor | **Cleared.** Route redirects. Remaining `prompt-studio.ts` is the version/publish client the studio still uses. |
| Treatment UI can auto-dial from the scoreboard | **Cleared.** Holds only. Enact is the worker. |
| K6 “one transaction includes reserve” | **Updated, not cleared.** Reserve is on an inner connection; the dial still sits under the claim transaction. |
| Contactability still uses the agent’s clock | **Cleared for the happy path.** Pill consumes `admit`. Fallback NBA (J3) is the remaining client policy. |
| Frontend dead API paths | **None found** in this pass — agrees with report 11. The defects are wrong hops, not 404s. |
| Duplicate FastAPI routes | **None.** WhatsApp has an alias pair (`/webhook` vs `/webhooks`) on purpose. |
| Billing has a mock | **No.** Live-only. |

---

## 13. If only five journeys are fixed

1. **J12 + J5** — stop labelling CRM writes as calls, or wire them through `outbound.reserve` → `place` (the demo endpoint already knows how). Until then, every “start call” on workspace and 360 is a compliance incident waiting on a screenshot.
2. **J13 K1** — do not pass `customer_id` as `session_key` on dial endpoints (report 14 item 1). Two-line change, every demo and any future 360 dial inherits it.
3. **J7** — return `requested_via` from `_document_contracts` (`db.py:1455`).
4. **J10** — wrap-up idempotency key = `wrap-${interactionId}` (no clock). Send the same header from PTP/dispute/lead creates.
5. **J22 K8** — key payment idempotency on `provider_ref`, as message idempotency already does.

Do not start an e2e framework until (1) and (2) have a characterization test. A Playwright suite against `USE_MOCK=true` would certify the seeds.

---

## 14. Sources

Primary files, this session: `Habibi/src/components/shell/Sidebar.tsx`, `Habibi/src/api/{config,me,workspace,customers,contact-policy,promises,documents,inbox,handoff,callbacks,outbound,platform,treatment,billing,voice-sandbox,prompt-studio,agent-studio,floor,consent,upsell}.ts`, `Habibi/src/routes/customers.$customerId.lazy.tsx`, `Habibi/src/components/customer360/{ContactabilityPill,QuickActionsRail}.tsx`, `backend/{main.py,authz.py,contact_policy.py,outbound.py,campaigns.py,payments.py,payment_events.py,whatsapp_outbound.py,bot_worker.py,worker.py,bot_jobs.py,call_closer.py,db.py,mcp_server.py}`, `backend/agent_core/treatment/enact.py`, `backend/agent_core/tools/grant.py`, `backend/bot_tools.py`, `backend/voice/{bot.py,persist.py,provider_bind.py}`, `backend/tests/` inventory (188 files), `Habibi/src/**/*.{test,spec}.ts` (11 files).

K1–K10 line ranges re-read 2026-09-02; none had been removed.
