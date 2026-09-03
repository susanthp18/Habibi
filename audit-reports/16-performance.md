# 16 — Performance architecture

**Scope:** `backend/` HTTP, workers, voice process; `Habibi/src` operator UI. `PRAXIST-main/` excluded.
**Date:** 2026-09-02
**Mode:** Read-only. No application file was modified, no migration run, no write issued.
**Method:** five parallel analysts — frontend, backend, database, network/API, caching — plus a parent verification pass. Every finding below was re-derived from source. Claims that failed a second source check were dropped or corrected (see the last section). Companion SQL-local audit: `13-query-performance.md`. This document restates only the items that show up as **system** cost (polls, process topology, payload shape, cache boundaries, event-loop blocking). Predicate-shape indexes and handler-local transaction poisoning stay in 13.

Vocabulary is `CONTEXT.md`: Mouth, Agent Card, Locked Engine, Mission, Cadence, Outcome, Reachability. The Inbox sidebar flag `contactableNow` is the **contact Gate** (`contact_policy.evaluate`), not Agent Card Reachability (`agent_core.cards.routing.reachability`). Those two words are not interchangeable here.

---

## The measurement caveat

This pass could not attach a profiler, a Lighthouse run, or a live catalog. `docker` on the host hung with no output, so there is no `EXPLAIN`, no `pg_stat_statements`, no Chrome Performance trace, and no bundle analyzer. A previous session against `collections_db` described a demo book. That is **not** reused as evidence.

Three rules that constrain every claim:

1. **A sequential scan over a demo table is the correct plan, not a defect.** Where a finding names query fan-out, that is a statement about the access path as written, not about current latency.
2. **Cost arguments are structural.** They name the scaling variable (open Inbox threads, transcript length, ledger age, idle worker ticks, operator navigations) and the code that multiplies it.
3. **Correctness hazards are volume-independent.** A `FOR UPDATE` held across a Twilio HTTPS call can duplicate a borrower-facing send on rollback at any table size. That is also a performance finding: the held pool slot and the stalled worker are the cost, not the SQL.

Findings are **Confirmed** (code-cited structural certainty) or **Opportunity** (would help; not shown to be hot). Nothing below is labelled slow from a stopwatch.

---

## Verdict

The performance architecture is **disciplined on the voice Mouth and outbound Mission paths, and self-inflicted on the operator CRM shell.**

The discipline is real. WhatsApp inbound is offloaded with `asyncio.to_thread`. Cadence and campaigns **commit the claim before they dial**. The call closer runs LLM enrichment **outside** the DB transaction. KB retrieval has a bounded LRU+TTL result cache shared by inbox, voice, and WhatsApp. Voice tool handlers wrap DB work in `asyncio.to_thread`. React Query’s global `staleTime` is 15 seconds, not zero. Inbox already delta-polls with `updatedAfter` and merges on write.

Against that, three things are true:

- **The dominant *steady-state* cost is one operator leaving Inbox open.** `useConversations` refetches every **4 s** (1.5 s while a Mouth is typing). `list_conversations` has no `clamp_list_limit()`, loads **all messages** for returned threads, then runs **4 context SELECTs + a full contact-Gate `evaluate()` per thread**. Messages are already batched with `ANY(:ids)`; the sidebar is not. This is poll-amplified N+1, not a missing index.
- **The dominant *liveness* cost is one mistake repeated.** A leaf send/dial is often locally correct. A caller several frames up still holds `FOR UPDATE`. With `UVICORN_WORKERS=1` and a single `bot_worker`, that mistake stalls the API event loop (bounce webhook) or every outbound queue (treatment enact, PTP reminder) for the length of a Twilio HTTPS call. `statement_timeout` does not apply while Python waits on the carrier.
- **The cache map is inverted relative to cost.** Embeddings, KB hits, authz grants, and policy rules are cached. The things operators hit every few seconds — Inbox sidebar context, contact Gate, dashboard aggregates, compiled Agent Card / Tool Grant, WhatsApp `load_active_bundle` — are not. Customer 360 even *intends* to persist a treatment decision on card-open (`db.py:1259-1262`) and then uses `engine.connect()` with no `commit()`, so SQLAlchemy 2.0.51 **rolls the INSERT back**.

That last point is the most actionable: nearly every fix already has a worked example in this tree.

---

## Census

### Process topology (compose + `db.py`, not live `SHOW`)

| Process | Source | Pool + overflow | Capacity | `statement_timeout` |
|---|---|---|---|---|
| `api` (`UVICORN_WORKERS=1`) | `docker-compose.yml:87-88,95,111` | 5+5 | **10** | 15,000 ms |
| `worker` | compose `:148-149` | 3+2 | 5 | 60,000 ms |
| `bot_worker` | compose `:177-178` | 3+2 | **5** | 60,000 ms |
| `voice` | compose `:201-202` | 3+2 | 5 | 60,000 ms |
| `voice_insurance` | compose `:235-236` | 2+1 | 3 | 60,000 ms |

Compose comment at `:3-6` budgets ≈25 app connections against `max_connections` 100. **Do not raise uvicorn workers without re-budgeting.** `pool_timeout` is not passed (`db.py:138-150`) — SQLAlchemy default 30 s. `lock_timeout` and `idle_in_transaction_session_timeout` are unset (Postgres default 0 = wait forever). Redis exists and is **voice-mesh only** (`REDIS_URL` → Pipecat `RedisBus`); it is not a CRM/KB cache.

### Frontend

| Surface | Count / note |
|---|---|
| QueryClient defaults | `staleTime: 15_000`, `refetchOnWindowFocus: true`, `retry: 1` (`Habibi/src/router.tsx:6-16`) |
| Router preload | `defaultPreload: "intent"`, **`defaultPreloadStaleTime: 0`** (`router.tsx:23-24`) |
| `refetchInterval` hooks | Inbox 4 s / 1.5 s; Floor 3 s + approvals 5 s; Handoff queue/active 5 s + session 2 s; contact-policy 60 s; outbound 60 s; providers 30 s |
| Lazy route modules (`*.lazy.tsx`) | **9** (Mouth editor, treatment, KB, sandbox, handoff, audit, bot-analytics, customer detail, Agent Studio `$botId`) |
| Eager CRM pages | Inbox, Dashboard, Floor, Customers index, most list screens |
| `React.memo` | **0** |
| `@tanstack/react-virtual` | Voice catalog only (2 files) |
| `useInfiniteQuery` | 1 (TTS voice catalog) |
| `prefetchQuery` / `ensureQueryData` | **0** |
| AppShell | Copied into **30+** routes; **not** a pathless layout. `__root.tsx` is `QueryClientProvider` + `<Outlet />` |

### Backend

| Surface | Count / note |
|---|---|
| HTTP handlers | ~314 `@app.*` in `main.py`; CRM majority are **sync `def`** (Starlette threadpool). ~15 **async** HTTP routes (webhooks, uploads, STT, voice WS, WhatsApp) |
| Data access | SQLAlchemy **Core** only. No ORM. One process-wide `Engine` (`db.py:138-150`) |
| `clamp_list_limit()` | Exists (`db.py:172-204`, default 200 / max 1000). **Not** applied to `list_conversations`, `list_violations`, `list_scorecards` |
| `asyncio.to_thread` on API | WhatsApp webhook, STT, KB upload, outbound dial place, lifespan. **Missing** on payment-events webhook and document ingest |
| Worker idle tick | `bot_worker --poll 1.5` (`bot_worker.py:171,234`); KB `worker` sleeps 2.0 s |

### Caches that exist (in-process unless noted)

| Cache | Bound | TTL |
|---|---|---|
| KB result (`kb_retrieve.py:348-428`) | 256 | 120 s (`KB_RESULT_CACHE_TTL_S`) |
| Azure embed (`azure_openai.py:377-471`) | 256 | until LRU eviction |
| Policy rules (`policy_rules.py`) | 512 | 60 s |
| Authz grants (`authz.py:646-774`) | 512 | 30 s |
| Platform switches | per-key | 2 s |
| Voice KB enrich | 32 | 180 s |
| TTS preview | disk | age + size sweep |
| Redis | — | **not** used for these |

---

## Confirmed findings

### S1 — P0 — Inbox poll is the system’s hottest path

**Layers:** frontend poll + unbounded list + per-thread query fan-out + unvirtualized render + no server memoization.

**Evidence**

- Frontend: `useConversations` (`Habibi/src/api/inbox.ts:102-137`) — `queryKey: ["conversations"]`, `staleTime: 2_000`, `refetchInterval` 1.5 s when any thread has `botTyping` or `pendingOutbound`, else 4 s; pauses when the tab is hidden; **invalidates on `visibilitychange`** (`:139-148`). Full list on first fetch and every 15th poll (~60 s). Delta polls still return **full message history for changed threads** (`inbox.ts:49-57` merge).
- Backend route: sync `GET /conversations` (`main.py:4256-4259`) → `list_conversations` (`db.py:9059-9110`). **No `clamp_list_limit()`.** `_conversation_base_rows` has no `LIMIT` (`db.py:8994-9056`).
- Messages: `_conversation_messages` selects all messages for `ANY(:ids)` with **no per-thread cap and no watermark** (`db.py:8616-8629`). A single new message re-fetches that thread’s entire history.
- Per-thread loop: `_serialize_conversation` → `_thread_context` runs **four extra SELECTs** (latest promise, open disputes, last 3 interactions, next EMI) (`db.py:8756-8813`) plus `_inbox_contactable` → `contact_policy.evaluate` (`db.py:8584-8600`, `contact_policy.py:533-595`). Evaluate itself loads customer, rules, channel status, today’s count, session coalesce, last counted, weekly count — **~6–8 reads** on the outreach path.
- UI: `ConversationList` maps every filtered thread in a plain `<ul>` (`ConversationList.tsx:157-218`). `ChatThread` maps every `thread.messages` (`ChatThread.tsx:210`). **Zero** `React.memo` in the tree. Parent holds the polled array, so every tick reconciles list + transcript.

**Cost model**

```
per full poll ≈ 4 batched queries (rows, messages, suggestions, typing)
              + N × (4 context SELECTs + 6–8 contact-Gate SELECTs)
              + JSON of all messages for those N threads
              + React work O(N + messages_in_active_thread)
```

`N` is every open thread on a full refresh, or every delta thread otherwise. At 4 s idle that is 15 full-shape requests/minute per open tab, doubling to 40/minute while a Mouth is typing.

**Workflow:** Conversation Inbox — the primary text/WhatsApp operator screen, designed to stay open all shift.

**Why this is structural:** Fixed interval × unbounded list × explicit per-row Python loop. Not a missing `EXPLAIN`. Sibling lists already use `clamp_list_limit()`; messages are already batched — the sidebar was not given the same treatment.

**Not claimed:** Measured p99. Demo books will look fine. The defect is the multiplier, not today’s wall clock.

---

### S2 — P0 — Bounce webhook: async route, row lock, Twilio, event loop

**Evidence:** `POST /webhooks/collections/payment-events` is `async def` (`main.py:857-877`) and opens `db.engine.begin()` **on the event loop**. `pe.ingest` locks the account `FOR UPDATE OF a` (`payment_events.py:188-201`). First-touch SMS calls `twilio_sms.send()` (`:669`, `TwilioHttpClient(timeout=10)` at `twilio_sms.py:79`) **before** writing `first_touch_at` (`:680-693`). Contrast: WhatsApp inbound uses `await asyncio.to_thread(...)` (`main.py:4617-4618`).

**Cost model:** `UVICORN_WORKERS=1` → one EOD bounce burst serializes **the entire API event loop** for up to 10 s per event, plus **1 of 10 API pool slots**, plus the account row lock, while **no SQL is running**. `statement_timeout` cannot fire. Rollback after `sent=True` (`payment_events.py:675`) can **duplicate SMS** on webhook retry — correctness and performance are the same bug.

**Workflow:** CBS bounce ingest → statutory pay-link SMS.

---

### S3 — P0 — Treatment enact and PTP reminders hold the worker across carrier I/O

**Evidence**

- Treatment enact: `process_one` opens `engine.begin()`, `decisions.claim_due`, then `enact_one` (`agent_core/treatment/enact.py:904-920`). `_send_sms` calls `twilio_sms.send` on that connection (`:295-314`). `_dial_bot` comments that the executor’s transaction is **still open** and opens a *second* connection for the attempt (`:317-338`) — so this path can occupy **2 of 5 `bot_worker` slots** during `outbound.place`.
- PTP reminders: `promise_fulfillment` sends SMS on the same `conn` that holds the reminder lock (`promise_fulfillment.py` around the send at `:1014` with lock at `:1046-1064` — see report 13 F7).
- Contrast (the convention that already exists): cadence records the attempt, **ends the transaction**, then calls `outbound.place` (`cadence.py:478-492`). Campaigns dial after commit (`campaigns.py:610`). WhatsApp outbound claims, **exits `begin()`**, then `handle_job` (`whatsapp_outbound.py:573-581`).

**Cost model:** One process owns WhatsApp outbound, PTP, bounce voice, cadence, campaigns, treatment enact/sweep/followthrough, and webhooks (`bot_worker.py:64-140`). A 10 s Twilio call inside an open transaction is a **10 s stall of every other queue**, plus pool occupancy. `bot_worker` pool capacity is **5**.

**Workflow:** Live Locked Engine dispatch; promise-to-pay reminder Cadence.

---

### S4 — P1 — Customer 360: unbounded ledger, double hydration, rolled-back treatment write

**Evidence**

- Detail: `GET /customers/{id}` → `get_customer` → `_customer_contract(..., include_detail=True)` (`db.py:1174-1179`, `1081-1158`). **Ledger has no `LIMIT`** (`:1112-1124`). EMI schedule is the full installment table (`:1136-1148`). Interactions are capped at 25 but each ships **full transcript text** (`:1154`, `1324-1337`). Promises/disputes/docs/notes use `DEFAULT_DETAIL_LIMIT` (100) (`db.py:180-189`).
- Insights: `GET /customers/{id}/insights` calls **`get_customer` again** (`db.py:1225`), then opens a **second** `engine.connect()` (`:1228`) for activity + offer snapshot + authority snapshot + `_treatment_snapshot`. `_treatment_snapshot` calls `recommend_treatment(..., trigger=Trigger(kind="manual"))` (`:1264-1271`). The docstring says the INSERT is deliberate (`:1259-1262`). `connect()` autobegins; there is **no `commit()`**; SQLAlchemy 2.0.51 **rolls it back** on context exit.
- Frontend: route loader fetches the customer (`customers.$customerId.tsx:22-25`); the lazy page copies it into `useState` and fires `["customer-insights", id]` in parallel (`customers.$customerId.lazy.tsx:92-112`). Mutations call `refreshCustomer`, which invalidates list + insights and **fetches the full aggregate again** outside the Query cache (`:116-121`). Overview tab then adds `useAuthorityNext` after insights resolve (one extra round-trip).

**Cost model:** Opening the card pays **2× full 360 assembly + treatment engine (~50–60 queries) + a discarded INSERT**. Ledger bytes scale with account age. Tabs switch in memory (good); the initial payload is the whole card (bad).

**Workflow:** Customer 360 — ledger, EMI, interactions, promises, disputes.

**Correction vs frontend analyst:** `GET /customers` (the **index**) uses `include_detail=False` (`db.py:1163-1171`, route `main.py:941-947`) and **is bounded**. Nested collections are not fetched on the list. The shared `CustomerResponse` schema (`schemas.py:151-171`) still *serializes empty arrays* for those fields; that is payload noise, not N+1.

---

### S5 — P1 — Idle `bot_worker` is a query generator; `settle_promises` locks without `SKIP LOCKED`

**Evidence**

- Default poll 1.5 s (`bot_worker.py:171`). When `process_one_any()` returns False, it sleeps (`:225-234`). Every tick still walks the queue ladder (`:64-140`): WhatsApp (which **reclaims inside the claim transaction even when empty** — `whatsapp_outbound.py:573-578`), PTP, bounce voice, closer, cadence, campaigns, treatment enact/followthrough/sweep, webhooks.
- Every 20th tick (`SETTLE_EVERY`) runs `settle_promises` (`bot_worker.py:72-74`). That issues `FOR UPDATE` on all open overdue promises with **no `LIMIT` and no `SKIP LOCKED`** (`promise_fulfillment.py:893-905`), then per row may call `recommend_treatment`. Sibling claim queues all use `SKIP LOCKED LIMIT 1`.

**Cost model:** Idle ticks still issue a claim/reclaim round-trip per enabled queue — structurally **~8–16 statements every 1.5 s** on a 5-connection pool, regardless of queue depth. `settle_promises` holds every matching promise row for the length of the treatment loop.

**Workflow:** Background drain; promise breakage; everything that shares `bot_worker`.

---

### S6 — P1 — Inbox RAG sits on the HTTP critical path, then invalidates the list

**Evidence:** Debounced 500 ms `POST /conversations/{id}/suggestions/refresh` (`inbox.tsx:234-248`, `main.py:4558-4573`). Handler calls `kb_retrieve.retrieve` synchronously (`db.py:9461-9467`) — embed + pgvector ANN + optional draft LLM (`kb_retrieve.py:576,659-818,966-978`). After retrieval it **reloads the full thread** (`get_conversation`). Frontend `void invalidate()` of `["conversations"]` after the POST (`inbox.tsx:223`), stacking a list refetch on top of a response that already carries the thread. Takeover/send/return similarly `mergeThread` **and** `invalidate()` (`inbox.tsx:186-192, 288, 304, 318`).

**Cost model:** Uncached miss = embed API + ANN + optional chat **on the API threadpool**, plus a full Inbox refetch. Mitigated by the 256-entry KB result cache (`kb_retrieve.py:348-428`) for identical queries — not for unique borrower turns.

**Workflow:** Inbox suggestion chips; “Suggest reply”.

---

### S7 — P1 — AppShell remounts on every navigation; Inbox (and most lists) are unvirtualized

**Evidence:** `AppShell` wraps page content in 30+ route files (`inbox.tsx:339`, `dashboard.tsx`, `customers.$customerId.lazy.tsx:301`, …). It is **not** a router layout: `__root.tsx` renders `<Outlet />` only. Nested `customers.tsx` / `agent-studio.tsx` also only outlet. Each navigation tears down Sidebar (lucide catalog + `useRouterState`), TopBar, `SidebarUiProvider`, Toaster (`AppShell.tsx:7-19`) and rebuilds them. Query cache survives (`QueryClientProvider` lives in `__root.tsx:155-161`); chrome and default `refetchOnMount` do not get that mercy once `staleTime` has elapsed.

Virtualization exists (`@tanstack/react-virtual` in `package.json`) and is used for the TTS voice catalog only. Inbox, Customers index, Floor live table, Handoff queue, workspace AssignedQueue, Audit, Treatment tables, KB tables — plain `.map()`.

**Cost model:** O(navigations) chrome remount + O(rows) DOM on every poll/filter. Query cache hit still pays React commit for the shell.

**Workflow:** Every operator page; worst on Inbox because of S1’s poll.

---

### S8 — P1 — Mouth editor: six parallel GETs, eager Flow graph, keystroke API

**Evidence:** `prompt-studio.lazy.tsx:182-187` mounts `usePromptVersions`, `usePersonaPresets`, `useActiveProdDeployment`, `useProdDeployments`, `useDeploymentExperiments`, `useAgentStudioCard` unconditionally. Active production deployment is a subset of the prod deployments list (duplicate round-trip). Default prompt tab then debounces lint (400 ms), token estimate (250 ms), and `POST /flow/validate` even off the Flow tab (`:710-731`). Autosave PATCH at 1.2 s (`:613-679`). `FlowCanvas` is a **static import** (`:21`) of `@xyflow/react` (`FlowCanvas.tsx:2-17`) — the lazy route splits the *page*, not the graph library. `agent-studio.$botId.lazy.tsx` remounts the editor with `key={botId}`.

**Cost model:** O(6 GETs + 2–3 POSTs) per Mouth open; xyflow parse cost on first visit even if the operator never opens Flow; keystroke bursts become debounced writes.

**Workflow:** Agent Studio → edit Agent Card / Mouth.

---

### S9 — P1 — Connection budget is tight; timeouts are one-sided

**Evidence:** API capacity 10, `bot_worker` 5 (`docker-compose.yml:3-6,87-88,177-178`). `connect_args` set `statement_timeout` only (`db.py:144-149`). During S2/S3, the connection is **idle in transaction** — `statement_timeout` is inactive. Competing checkouts wait up to `pool_timeout` 30 s, then fail. `/ready` healthcheck is a 5 s curl (`docker-compose.yml:127-129`). An event-loop stall from S2 can make liveness look like a dead process.

**Cost model:** Inbox polls occupy API slots (S1). Bounce webhook occupies loop + slot (S2). Treatment enact can occupy 2–3 of 5 worker slots (S3). Headroom is not proportional to those overlapping modes.

**Workflow:** Any concurrent operator + outbound + webhook moment.

---

### S10 — P1 — Floor and Handoff stack overlapping polls

**Evidence:** `useFloor(refetchIntervalMs = 3_000)` (`floor.ts:75-81`); `useFloorApprovals` at 5 s (`floor.ts:289-294`); page copies `snapshot.calls/alerts` into `useState` on every tick (`floor.tsx:64-68`). Handoff page always runs `useHandoffQueue` + `useHandoffActive` at 5 s (`handoff.ts:170,190`; `handoff.lazy.tsx:43-44`) and, when a session is active, `useHandoffSession(..., { poll: true })` at 2 s (`handoff.ts:194-205`). Parent hooks stay mounted when `interactionId` is set.

**Cost model:** Up to **3 concurrent polling queries** on an active Handoff; Floor is 3 s + 5 s on a live-ops screen. Mock Floor also runs a 1 s local updater (`floor.tsx:72-88`) — irrelevant in live mode.

**Workflow:** Floor command; live Handoff / call takeover.

---

### S11 — P1 — Compiled Agent Card and WhatsApp bundle are not cached

**Evidence**

- `compile_agent_studio_card` runs `compile_card` and returns `report.model_dump()` (`db.py:13372-13443`). Publish re-runs the full compile + gates. Stored artifact is raw `agent_card` JSONB, **not** a compiled Tool Grant / effective-tools snapshot. Frontend compile preview is debounced 400 ms with 30 s `staleTime` (good for the editor, does not persist).
- Fleet index `list_agent_studio_cards` loads every card, then `reachability(...)` over the handoff graph (`db.py:12935-12989`). Each `_agent_studio_card_summary` also hits versions + active deployment per Mouth. This **is** Agent Card Reachability (correct use of the word).
- WhatsApp/text Mouth: `bot_runtime.py:712-717` calls `load_active_bundle` **every bot-turn job** (`agent_core/deployment.py:15-61` — deployment row + prompt version, no memo). Voice loads the bundle **once per session connect** (`voice/bot.py:423`).

**Cost model:** Compile = G0–G15 walk + skill pack + connector lookups per preview/publish. Fleet list = O(cards × DB). WhatsApp = 2+ DB round-trips per inbound turn on top of the turn itself.

**Workflow:** Agent Studio fleet and editor; WhatsApp Mouth runtime.

---

### S12 — P1 — Document ingest and copilot run Azure on the serving process

**Evidence**

- `POST /document-requests/ingest` is `async def` (`main.py:1644-1662`). After reading the upload it calls `ingest_customer_document` **inline**. Classification hits `azure_openai.chat_with_tools` (`agent_core/vision.py:92-110`). The call is filename+mime, not image bytes — cheaper than a vision pass, still a **sync Azure round-trip on the event loop** of the only uvicorn worker.
- Floor copilot: sync route `main.py:1364-1371` → `copilot.py:227-247` `_maybe_polish` → Azure analysis profile. Stream route materializes events synchronously (`main.py:1374-1390`).

**Cost model:** One supervisor copilot or one receipt upload competes with Inbox polls and Twilio webhooks for the same process.

**Workflow:** Inbox document upload; live-call Floor whisper.

---

### S13 — P2 — Unbounded compliance/QA lists; dashboard is a multi-scan bundle with no server cache

**Evidence:** `list_violations` (`db.py:7025-7045`) and `list_scorecards` (`db.py:8050-8072`) — no `clamp_list_limit()`, no SQL `LIMIT`. `get_dashboard` (`db.py:3195+`) runs **10+ sequential aggregates** on one connection (interactions, prior window, volume, recovery, outstanding, promises, leads, at-risk, leaderboard with correlated subqueries, TTFT). Frontend `useDashboard` has 30 s `staleTime` (`dashboard.ts:113-118`) and **no `refetchInterval`** — good. There is no backend cache or materialized snapshot. Dashboard route **eager-imports six Recharts surfaces** (`dashboard.tsx:8-13`, `createFileRoute` `:18`) via `components/ui/chart.tsx`.

**Cost model:** Violations/scorecards scale with table growth. Dashboard is bounded by time window, not row limit; cost is “every open dashboard tab, every 30 s of staleness + window focus”, not a 4 s poll.

**Workflow:** Compliance Risk; QA scorecards; executive dashboard.

---

### S14 — P2 — HTTP cache headers almost absent; intent-preload treats data as immediately stale

**Evidence:** `Cache-Control: private, max-age=3600` on TTS preview (`main.py:3042-3047`); `no-cache` on SSE (`main.py:1396`). No `ETag` / `If-None-Match` on list endpoints. Router `defaultPreloadStaleTime: 0` (`Habibi/src/router.tsx:23-24`) vs QueryClient `staleTime: 15_000` — hovering a link refetches even with a warm cache. Global `refetchOnWindowFocus: true`.

**Cost model:** Extra JSON bodies on tab focus and link hover. CORS preflight is **not** the issue: `ApiKeyMiddleware` passes OPTIONS (`main.py:274-275`); custom headers cause one preflight per origin, not per poll (`Habibi/src/api/config.ts:172-175`).

**Workflow:** Any navigated route; tab-switching operators.

---

### S15 — P2 — Authz cache miss is a sync DB checkout from an async dependency

**Evidence:** Global `Depends(_authz_guard)` (`main.py:507,585`). Guard is `async def` and calls `authz.check` inline (`:543-544`). On a 30 s TTL miss, `_load_grants` / role lookup does `db.engine.connect()` (`authz.py:673-790`). Hits are in-process and cheap. Misses on **async** routes (webhooks, ingest) block the event loop for a pool checkout.

**Cost model:** Per-user, at most once per 30 s in the steady state. Becomes dangerous only when the API pool is already saturated (S1+S2) — checkout waits `pool_timeout` 30 s on the loop.

**Workflow:** Every authenticated HTTP request, felt on the async subset.

---

### S16 — P2 — Inbound caller match cannot use an expression index; `work_items` view cannot be indexed

**Evidence:** Hot inbound path matches `regexp_replace(...phone...)` (`db.py:10366-10367`). `customers` has no expression index on digit-stripped phones (`sql/02_customer_account.sql:64-66`); `accounts` already grew tail indexes in Alembic 0040 — the asymmetry is the finding. `work_items` view (`sql/95_views.sql`) `LEFT JOIN LATERAL` on `followups.lead_id`; `followups` indexes `customer_id` and `promise_id` but **not** `lead_id` (`sql/05_collections.sql:262-263`). `list_work_items` clamps (`db.py:12584`) then `ORDER BY CASE` (`:12617-12623`).

**Cost model:** Phone lookup is O(customers) by predicate, not O(log n), on every inbound WhatsApp/voice match. Work-items LATERAL is O(open followups per lead) per workspace row. Both change asymptotics; neither is the Inbox poll.

**Workflow:** Inbound Mouth; My Workspace.

---

### S17 — P2 — Treatment book sweep holds 50 account locks; follow-through is O(backlog) per tick

**Evidence:** `BATCH = 50` (`agent_core/treatment/sweep.py:63`). One `engine.begin()`, `_claim` with `FOR UPDATE OF a SKIP LOCKED` (`:162`), then `_decide_account` → `recommend_treatment` per account inside that transaction (`:87-109`). Off unless `TREATMENT_SWEEP` is set (`:112-128`). Returning `True` when `decided > 0` means `bot_worker` **does not sleep** (`bot_worker.py:220-225`), starving WhatsApp/PTP/cadence until the slice finishes. Follow-through `BATCH = 25` every tick unless `TREATMENT_MODE=off`.

**Cost model:** Sweep-window cost = 50 × treatment pipeline, locks held for the whole batch. Not the daily default; catastrophic when enabled on a large delinquent book sharing S3’s worker.

**Workflow:** Nightly / flagged delinquent-book sweep.

---

### S18 — P2 — KB/embed caches are per-process; cold miss is a stampede across the fleet

**Evidence:** `_result_cache` is a process-local `OrderedDict` (`kb_retrieve.py:360-428`). Embed cache is process-local (`azure_openai.py:458+`). API is one uvicorn worker (one cache). `bot_worker` and `voice` keep **separate** copies. Redis is not on this path.

**Cost model:** After deploy/restart, identical queries pay N × (embed + ANN) until each process warms. Mitigated by `bot_worker` Azure prewarm (`bot_worker.py:198-233`) for *chat*, not for every embed.

**Workflow:** First WhatsApp/voice/inbox retrievals after a bounce.

---

## Critical-path waterfalls (network)

### Inbox

```
Mount (parallel)
├─ GET /conversations                 [poll 4s / 1.5s; full every ~60s]
└─ GET /canned-responses              [staleTime 5 min]

Thread selected (+500ms debounce)
└─ POST /conversations/:id/suggestions/refresh   [embed ± LLM, then get_conversation]

Write (takeover / send / return)
├─ POST … → Thread
├─ mergeThread (cache patch)
└─ GET /conversations                 [background invalidate]
```

List + canned are parallel. RAG is serial after selection. Poll runs beside everything else.

### Customer 360

```
Loader (blocks first paint)
└─ GET /customers/:id                 [full CustomerResponse]

Mount (parallel with loader data)
└─ GET /customers/:id/insights        [re-fetches customer + treatment]

Overview tab
└─ GET authority-next                 [after insights]

Tab switch
└─ (no HTTP)

Mutation
└─ POST … → invalidate list+insights → GET /customers/:id again
```

### Dashboard

```
Mount / filter change
└─ GET /dashboard?range=&segment=&team=    [one payload, staleTime 30s]
```

Single-endpoint aggregation. This is the pattern Inbox and Customer 360 should copy for *orchestration*, not for payload size.

### Mouth editor

```
Mount (6 parallel GETs)
├─ /prompt-versions
├─ /persona-presets
├─ /bot-deployments/active
├─ /bot-deployments?environment=production
├─ /bot-deployments/experiments
└─ /agent-studio/cards/:botId

Then (debounced, even off-tab for flow)
├─ POST /prompt-versions/lint
├─ POST /prompt-versions/estimate-tokens
└─ POST /flow/validate
```

---

## Opportunities (not proven bottlenecks)

These would reduce structural cost. They are not labelled hot without a trace.

| ID | Opportunity | Why it is only an opportunity |
|---|---|---|
| O1 | Pathless `_authenticated` layout: one `AppShell` + `<Outlet />` | Chrome remount is confirmed (S7); its share of session time vs Inbox poll is unmeasured |
| O2 | Split Inbox API: list projection vs `GET /conversations/:id` for messages/context; SSE/WS for ticks (Floor already has SSE in `floor.ts`) | Delta poll already exists; transport change is a product decision |
| O3 | Batch `_thread_context` with `customer_id = ANY(:ids)`; memoize `contact_policy.evaluate` per `(customer_id, channel, minute)` | S1’s fan-out is confirmed; in-request memo is the cheap fix, a new table is not required to start |
| O4 | Customer 360 `?include=` / tab-scoped fetches; `LIMIT` on ledger; transcripts only on Interactions tab | Unbounded ledger is confirmed; typical row counts are not |
| O5 | `GET /agent-studio/cards/:id/bootstrap` collapsing S8’s six GETs; lazy-load FlowCanvas | Parallelism already hides much of the RTT; xyflow weight needs a bundle report |
| O6 | Persist compiled Tool Grant at publish; cache `load_active_bundle` keyed by `(bot_id, deployment_id, prompt_version_id)` | WhatsApp turn DB cost is confirmed small relative to the LLM turn; still wasted |
| O7 | Dashboard materialized snapshot / short TTL keyed by `(range, segment, team)` | 30 s client staleTime already bounds this; backend cache helps many tabs, not one |
| O8 | ETag on `/teams`, `/canned-responses`, `/me`, fleet index | Cheap 304s; bandwidth unmeasured |
| O9 | `React.memo` on `MessageBubble` / conversation row; virtualize `RecordsTable` consumers | Zero memo is a fact; benefit needs a profiler |
| O10 | Shared Redis for KB result cache | Stampede (S18) is real after restart; complexity vs `UVICORN_WORKERS=1` may not pay |
| O11 | Raise `defaultPreloadStaleTime` to match QueryClient `staleTime`; `refetchOnWindowFocus: false` on dashboard/treatment | Extra fetches are confirmed; user-visible delay is not |
| O12 | Lint: no carrier HTTP with an open transaction N frames up | Recurring defect class (S2, S3); a test, not a runtime cache |

---

## What is already good

The system is not undifferentiatedly slow. These are the patterns to copy, not replace:

| Pattern | Where |
|---|---|
| **Commit-then-dial / commit-then-send** | Cadence (`cadence.py:478-492`), campaigns (`campaigns.py:610`), WhatsApp outbound (`whatsapp_outbound.py:575-581`), Inbox WhatsApp reply enqueue (`db.py:10315-10324`) |
| **LLM off the DB transaction** | Call closer (`call_closer.py:1107-1133`) |
| **Event-loop offload** | WhatsApp webhook, STT, KB upload (`main.py:4618, 3287, 4447`); voice tools (`voice/tools.py`, dozens of `to_thread`) |
| **SKIP LOCKED claim queues** | Bot turns, cadence, campaigns, closer, treatment due-queue. (`settle_promises` is the omission, S5) |
| **KB result cache + buffered analytics** | `kb_retrieve.py:25-204, 348-428` |
| **Inbox delta poll + mergeThread** | `inbox.ts:91-118`; mutations patch cache then invalidate in the background |
| **Dashboard is one GET** | `dashboard.ts:105-118` / `main.py:978-980` |
| **Customer *list* is bounded and `include_detail=False`** | `db.py:1163-1171`, `main.py:941-947` |
| **Global React Query `staleTime: 15s`** | `router.tsx:10` — no project-wide `staleTime: 0` |
| **Canned responses 5 min staleTime** | `inbox.ts:159-164` |
| **Treatment hooks disable window-focus refetch** | `treatment.ts:1057-1058` (avoids accidental decision writes) |
| **Compile preview debounce + 30 s staleTime** | `agent-studio.ts:248-280` |
| **Pipecat dynamically imported** | `useSandboxLiveCall.ts:251-252` — the pattern FlowCanvas should copy |
| **GZip with SSE exception** | `StreamingAwareGZipMiddleware` (`main.py:593-614`) |
| **Authz 30 s TTL + invalidate on role change** | `authz.py:646-666` |
| **Azure prewarm on idle bot_worker** | `bot_worker.py:198-233` — cold-start is a named, measured problem this already treats |
| **`clamp_list_limit` convention** | 18+ list accessors; S1/S13 are the holdouts |

---

## Ranked remediation

If only five things are fixed, in this order:

1. **Inbox list shape (S1).** `clamp_list_limit()` on `list_conversations`. Cap messages (last N, or watermark). Batch `_thread_context` with `ANY(:ids)`. Compute `contactableNow` once per distinct `customer_id` per request (or denormalize a minute-bucket). Stop invalidating the full list after RAG/send when `mergeThread` already applied the response. Optionally drop poll to 10–15 s idle once the payload is a projection. *Precedent:* message batching in the same function; `clamp_list_limit` on `list_customers`.
2. **Claim → commit → send (S2, S3).** Payment webhook: `await asyncio.to_thread(pe.ingest)` **and** do not call Twilio inside `FOR UPDATE`. Treatment enact / PTP: copy cadence. Add `idle_in_transaction_session_timeout` and `lock_timeout` beside `statement_timeout` (`db.py:144-149`) so a missed call site fails bounded. *Precedent:* cadence, campaigns, WhatsApp outbound, WhatsApp webhook `to_thread`.
3. **Customer 360 / insights (S4).** `LIMIT` on ledger. Do not call `get_customer` inside insights. Either `engine.begin()`/`commit()` if the shadow write is still wanted, or drop `conn=` so `recommend_treatment` is not a discarded ~50-query write. Drive the page from `useQuery(["customer", id])` with loader `initialData`; delete the `useState` mirror.
4. **Worker idle + `settle_promises` (S5).** Heartbeat / `LISTEN` / exponential backoff after empty ticks; skip reclaim UPDATE when queue depth is zero. `FOR UPDATE OF p SKIP LOCKED` + `LIMIT` on settle; hoist `recommend_treatment` out of the lock. Shrink treatment sweep `BATCH` or commit per account (S17).
5. **Mouth editor bootstrap + Flow split (S8, S11).** One bootstrap GET. `import()` FlowCanvas on Flow-tab select (copy Pipecat). Persist compiled grant at publish. Cache `load_active_bundle` with publish invalidation.

Honourable mentions, already cheap: `asyncio.to_thread` on document ingest (S12); `clamp_list_limit` on violations/scorecards (S13); phone expression indexes (S16); pathless AppShell (S7, O1).

SQL-local indexes and predicate rewrites remain in `13-query-performance.md` and should land as migrations, not as a third copy of that list.

---

## What we could not verify

- p50/p99 of `/conversations`, `/customers/{id}`, copilot, or webhooks.
- JSON byte sizes at production thread/ledger counts.
- Bundle composition (`vite build` / visualizer not run; no `.output/` artifacts). Recharts, `@xyflow/react`, `@pipecat-ai/*` weight is inferred from **static imports**.
- Pool wait times, idle-in-transaction counts, `pg_stat_statements`.
- N4/S4 rollback via `SELECT … trigger_kind = 'manual'` against a live catalog.
- Whether Radix Tabs `forceMount` treatment panels (assumed unmounted; default).
- Production `REDIS_URL` adoption; voice-mesh only in source.
- End-to-end voice turn latency (STT → LLM → TTS on Pipecat) beyond “webhook returns TwiML quickly” (`main.py:3482-3546`).
- Exact `useQuery` hook census (ripgrep counts include tests/re-exports).

---

## Corrections to analyst notes

These were caught on the parent pass and **must not** be reused:

| Claim | Reality |
|---|---|
| Inbox runs Agent Card **Reachability** `evaluate()` per thread | It runs **`contact_policy.evaluate`** (contact Gate) (`db.py:8584-8599`). Card Reachability is `list_agent_studio_cards` (`db.py:12977`) |
| `GET /customers` hydrates nested ledger/interactions for every row | **`include_detail=False`**, bounded (`db.py:1163-1171`). Detail is the unbounded path |
| Floor polls every 5 s | Snapshot is **3 s** (`floor.ts:75-81`); approvals 5 s |
| Document ingest runs Azure vision on image bytes | Classifier sends **filename + mime** (`vision.py:92-110`). Still blocks the loop; not a vision payload |
| Payment webhooks as a class are all “inline and fine” | `payment_events_webhook` is the severe one (S2). Provider webhook is sync-route DB work without Twilio in the same lock — heavy, not the same class |
| `engine.connect()` commits writes on exit | SQLAlchemy 2.0.51 **rolls back** unless `commit()` is called. This is the S4 insights INSERT |

---

## SQL-local items left in report 13

Do not restate in this document. Fix them as migrations / handler-local patches:

- Index/predicate: I3–I8, S1, S2, S4, S5, S7, S8, S10–S12 in report 13
- Handler-local transaction poisoning P1–P5
- Connection-churn counts C1–C4
- Dataset-bounded N5–N7
- Dormant rail path F10 mandate presentment

Cross-walk of **system** items that *are* restated here: 13’s N0/S3 → **S1**; F1 → **S2**; F6/F7/F8 → **S3**; N4 → **S4**; N1/F11 → **S5**; N2 → **S17**; I1 → **S16**; pool/timeout baseline → **S9**.
