# 04 — Backend architecture

**Scope:** `backend/` (Habibi collections platform)  
**Date:** 2026-09-01  
**Method:** six parallel reads — HTTP/router, application service, domain, persistence, integration, background workers — then a synthesised reconstruction of how work actually flows.

This is a description of the system as it runs, not of a hoped-for layering. Target architecture at the end is copied from the best patterns already in this tree, not from a textbook.

---

## Verdict

The backend is a **FastAPI monolith with two god modules and a growing island of well-bounded domain packages**.

- **HTTP** lives almost entirely in `main.py` (5,448 lines, **314** route decorators, **zero** `APIRouter`s).
- **Persistence + CRM orchestration + Pydantic serializers** live in `db.py` (18,087 lines, **440** functions).
- **Money, contact, and product selection** already follow a Locked Engine split (`engine` / `policy` / `enact` / `decisions`) that the rest of the system should copy.
- **Outbound dialling** already follows a correct application-service contract: reserve → Gate → place → Closer → Outcome.
- **Tool Grant** (ADR-0001) and **cardless deny-all** (ADR-0002) are written in `agent_core/tools/grant.py` and characterised in tests. **Nothing in production imports that module.** Seven formulas still compute the grant; a cardless Mouth still fail-opens onto a hand-maintained tool list.

Cross-cutting concerns that *are* in good shape: a global authz registry that tests prove is total over the route table; request/actor ContextVars; SKIP LOCKED queues with reclaim and dead-letter on the three formal job tables; “never raise on the audio path” as a real, documented contract.

The architecture problem is not absence of design. It is **two competing designs occupying the same process**: a mature domain core, and a CRM/HTTP shell that never adopted it.

---

## How work actually flows

There is no `services/` package and almost no FastAPI dependency injection below the authz guard. The live path is:

```
HTTP (main.py @app.*)
  → middleware (request id, metrics, API key → actor ContextVar)
  → global Depends(_authz_guard)  [staff permission, not Tool Grant]
  → Pydantic body  OR  dict[str, Any] + ad-hoc checks
  → one of:
        a) db.<fn>                 # CRM, inbox, Agent Studio, most reads/writes
        b) ops_screens / followups_db
        c) domain module (campaigns, contact_policy, copilot, treatment, …)
        d) provider adapter (azure_speech, twilio_ops, whatsapp, kb_retrieve)
        e) inline SQL on db.engine  # outbound list, Twilio SMS status, pay page
  → domain Locked Engine (sometimes, via db or a tool handler)
  → repository SQL (db.py, persist.py islands, or the caller’s own text())
  → Postgres  /  Twilio  /  Meta  /  Azure  /  MinIO
```

Workers skip HTTP and enter at (c): `bot_worker.process_one_any` round-robins module-level `process_one(engine)` functions that claim a row, drop the lock, then call the same domain modules the API uses.

Voice skips both HTTP orchestration and `bot_turn_jobs`. The Mouth (`voice/bot.py`) runs in its own process, writes CRM through `voice/persist.py`, and joins the collections world only after the call, when `call_closer` stamps an Outcome.

### Two permission systems, not one

| System | Owner | Question it answers |
|--------|--------|---------------------|
| Staff authz | `authz.ROUTE_PERMISSIONS` + `Depends(_authz_guard)` | May this **operator** hit this **route**? |
| Tool Grant | *Intended:* `agent_core/tools/grant.py`. *Actual:* `skills/intersect.py` + channel runtimes | May this **Mouth** execute this **tool**? |

They do not share a vocabulary. Mixing them is a design error; they are correctly separate. The defect is that the second system has two owners.

---

## Bounded contexts (as implemented)

| Context | Code | Cohesion |
|---------|------|----------|
| Agent Card / publish Gates | `agent_core/cards/` (`compile.py` G0–G12) | High |
| Skill Packs | `agent_core/skills/` | High; cycle with `cards` broken by lazy imports |
| Tool Grant / Offer | `agent_core/tools/grant.py` (unused) vs `intersect` + runtimes | **Split — ADR-0001 not landed** |
| Locked Engine: Authority | `agent_core/authority/` | Exemplar |
| Locked Engine: Treatment | `agent_core/treatment/` | Exemplar |
| Locked Engine: Reco | `agent_core/reco/` | High; veto lives in `capture.py` |
| Locked Engine: Live QA | `agent_core/live_qa/` | High; `enact` talks to Twilio |
| Reachability / contact Gate | `contact_policy.py`, `policy_rules.py`, `contact_window.py` | High — single `admit` |
| Flow / Mission | `flow_graph.py`, `mission` (used from outbound route) | High |
| Cadence | `cadence.py` | High — mechanical retry, must not change the Mission |
| Batch Mission metering | `campaigns.py` | High |
| Attempt ledger | `outbound.py` | High — reserve / Gate / place |
| Outcome | `call_closer.py`, `post_call_actions.py` | High |
| Promise fulfilment | `promise_fulfillment.py` | High |
| Payment / bounce | `payment_events.py`, `payments.py` | Medium — money split across four modules |
| CRM spine | `db.py` (customers, promises, disputes, leads, inbox, handoff, Agent Studio persist) | **God module** |
| Ops screens | `ops_screens.py` | Extracted from `db.py` on purpose |
| Coaching / routing / redaction | `followups_db.py` (re-exported through `db`) | Extracted |
| Voice Mouth | `voice/` | Large but bounded; `voice/tools.py` (2,914 lines) is a local god |
| WhatsApp Mouth | `bot_runtime.py` + `bot_jobs.py` | Cohesive |
| Staff HTTP | `main.py` | **God router** |
| Providers (live STT/TTS) | `agent_core/providers/` | High |
| Connectors | `agent_core/connectors/` | High; persist also dispatches HTTP |
| Work runtime / clerk | `work_runtime/`, `agent_core/clerk.py` | Early, Temporal-shaped |
| MCP HTTP | `agent_core/mcp_http/` | Separate Starlette process, not mounted |

---

## Representative request paths

### Thin CRM read — the common case

`GET /customers` (`main.py:941`) → Query ge/le clamp → `db.list_customers` → SQL + `CustomerResponse` assembled inside `db.py`.

This is most of the CRM surface. The handler is a one-liner. The application service, repository, and serializer are the same function.

### Promise write — application logic hiding in the repository

`POST /promises` (`main.py:1549`) → `_handle_write` (`main.py:720`) maps `KeyError→404`, `ValueError→409`, `IntegrityError→409` → `db.create_promise` opens `engine.begin()` → `_create_promise(conn, …)` inserts → **then calls `promise_fulfillment.fulfill(conn, …)` inside the same transaction**. Fulfilment failure is logged and swallowed; the promise row still commits.

Voice tools (`agent_core/tools/domain.py`) call the same `db.create_promise`. HTTP and Mouth share the write path. That is correct. The orchestration sitting in `db.py` is the layering violation.

### Handoff claim — domain rules in SQL

`POST /handoff/{id}/claim` → `_handoff_call` → `db.claim_handoff`: `FOR UPDATE`, visibility check, handler swap, participant upsert. Authorization and the state machine live next to the `UPDATE`.

### Publish — Gate at the right moment, draft-picking in the route

`POST /agent-studio/cards/{bot_id}/publish` (`main.py:2119`) **selects which draft to publish inside the handler** (list versions, filter drafts, resolve `versionId`), then `db.publish_prompt_version` runs compile Gates. `CompileError` and `FlowInvalidError` become HTTP 422. The Gate itself is in `agent_core/cards/compile.py`. The route is doing product policy.

### Outbound dial — application service in the route

`POST /twilio/voice/outbound` (`main.py:3731`):

1. `mission.build(conn, …)`
2. `outbound.reserve(conn, …)` — committed attempt row *before* the Gate
3. `contact_policy.admit(…)` — Reachability Gate
4. deny → `outbound.suppress`; allow → `outbound.place` (Twilio, outside the claim shape used by workers)

The **order is the documented contract** in `outbound.py`. Cadence, campaigns, and treatment/enact use the same three steps. This HTTP route inlines them instead of calling a single application function, so the fourth copy of the dial sequence lives in `main.py`.

### WhatsApp inbound — enqueue, don’t speak

`POST /webhooks/whatsapp` → HMAC in `whatsapp.verify_signature` → `db.process_whatsapp_webhook` (nested savepoint per message) → `bot_jobs.enqueue_bot_turn` **in the same transaction**. `bot_worker` later claims `bot_turn_jobs` and `bot_runtime.handle_turn` talks to Azure and Meta.

Human inbox sends enqueue `whatsapp_outbound_jobs` and return. Bot replies still call `whatsapp.send_text_message` **inline** from `bot_runtime` and block the worker on Graph latency.

### Floor copilot — domain engine from HTTP

`GET /floor/copilot/{id}/stream` → `agent_core.copilot.iter_events` → SSE. GZip is bypassed for `/stream` (`StreamingAwareGZipMiddleware`). This is the thin-adapter shape the rest of HTTP should look like.

### TTS preview — provider in the route

`POST /tts/preview` (~90 lines): branch on vendor, `provider_tts.synthesize` or `azure_speech.synthesize`, cache headers. Live calls go through `agent_core/providers/factory.py`. Preview does not.

---

## Dependency injection (actual)

| Mechanism | Where | Role |
|-----------|--------|------|
| `ApiKeyMiddleware` | `main.py` | Resolves actor, binds ContextVar |
| `RequestIdMiddleware` | `main.py` | `X-Request-Id` + ContextVar (db/voice/workers can log it) |
| `MetricsMiddleware` | outside the auth gate | Counts 401/403; labels by **route template** |
| `Depends(_authz_guard)` | on the `FastAPI` app | One table (`authz.ROUTE_PERMISSIONS`); tests fail if a route is missing |
| `Header(idempotency_key)` | five write routes | Passed into `db.create_*` |
| `Depends(require_admin)` | **one** route: TTS catalog sync | Legacy leftover; authz registry is the real gate |
| Constructor / protocol DI | almost none | Modules import `db`, `azure_openai`, … at top level |

FastAPI `Depends` is used as a **permission interceptor**, not as an application-service injector. That is a reasonable choice given the authz totality test. It does mean handlers cannot be unit-tested with a fake service graph; they import the world.

---

## God modules

Line counts of production Python (excluding tests, alembic, scripts):

| Lines | Module | What it mixes |
|------:|--------|----------------|
| 18,087 | `db.py` | Engine, tenant GUC, ~120 CRUD entrypoints, lead FSM, handoff claim, WhatsApp ingest, Agent Studio persist, KB admin, billing, serializers |
| 5,448 | `main.py` | 314 routes, middleware, lifespan, exception handlers, Twilio TwiML, inline SQL, provider calls |
| 3,453 | `schemas.py` | DTOs only — large, not a god *service* |
| 2,914 | `voice/tools.py` | Tool registry + ALWAYS_ON union onto the grant |
| 2,622 | `voice/bot.py` | Mouth runtime |
| 1,861 | `capture.py` | Post-call rollup + product eligibility veto used by Reco |
| 1,856 | `ops_screens.py` | Floor + webhook admin + provider config (already extracted) |
| 1,614 | `followups_db.py` | Coaching / routing / redaction (already extracted, re-exported as `db.*`) |
| 1,394 | `outbound.py` | Cohesive |
| 1,292 | `bot_runtime.py` | Cohesive WhatsApp Mouth |

`db.py` is the primary architectural debt. `main.py` is a god *router* — most handlers are thin, a minority are fat. `ops_screens.py` and `followups_db.py` prove the extraction pattern the team already trusts.

There are **no service classes** doing unrelated work. The anti-pattern is **module-level functions in a file that does unrelated work**.

---

## Violations

Severity: **P0** = contradicts an accepted ADR or fail-open on a safety boundary; **P1** = god module / scattered writes that will keep generating bugs; **P2** = inconsistency that slows change.

### P0 — Tool Grant is not the enforcement point

_Contradicts ADR-0001 (one owner for the Tool Grant)._  
`grant.py` says so itself: “Nothing imports this yet.” Production imports are tests only (`test_tool_grant.py`, `test_tool_grant_characterization.py`, `test_import_cycles.py`).

Seven live formulas:

| # | Formula | Location |
|---|---------|----------|
| 1 | Grant | `agent_core/skills/intersect.py` `effective_tools` |
| 2 | Idle Offer | `intersect.idle_offered_tools` |
| 3 | Active-skill Offer | `intersect.offered_tools` |
| 4 | Publish G9 scope | `agent_core/cards/compile.py` (`include ∪ locked ∪ platform`) — omits connectors, the original ADR bug |
| 5 | Text cardless fallback | `bot_runtime.py` falls back to `bot_tools.TOOL_DEFINITIONS` when `ToolState.allowed is None` |
| 6 | Voice ALWAYS_ON union | `voice/tools.py` `keep = allowed \| ALWAYS_ON` — **widens** after receiving a set |
| 7 | Sandbox cardless fallback | `sandbox_runtime.py` |

_Contradicts ADR-0002 (cardless Mouth is denied every tool)._  
`MouthTurn.tools()` returns `ToolState(allowed=None, offered=None)` when `card is None`. Callers treat `None` as “no filter” and load the full hand-maintained list. `grant.py` already implements deny-all; runtimes have not switched.

### P1 — Route handlers containing business logic

- Agent Card publish draft selection — `main.py:2134–2157`
- Handoff reachability graph assembly from `list_agent_studio_cards` — `main.py:2177–2203`
- TTS vendor routing — `main.py:2951–3048`
- Outbound Mission + Gate + dial — `main.py:3731–3818`
- Demo outbound waiver of contact-policy reasons — `main.py:3862+`
- KB reindex-all creating a snapshot as a handler side effect — `main.py:4406–4419`

### P1 — Direct database access scattered

~35 production modules open `db.engine` or run `text("SELECT…")` besides `db.py`. Notable HTTP leaks:

- Hosted `/pay/{token}` — `main.py` + `payments.*` on `engine.begin()`
- Twilio SMS status — raw SQL on `contact_delivery_events` (`main.py:3701`)
- `GET /outbound/attempts`, `/outbound/reasons`, `/outbound/campaigns` — JOIN SQL in the route
- Platform switches — `engine.connect/begin` in the route

Workers and Locked Engines opening their own connections is a **deliberate** pattern (claim/complete). HTTP doing the same is not.

### P1 — Direct provider calls from routes

- `azure_speech.synthesize` / `transcribe`
- `provider_tts.synthesize`
- `twilio.request_validator.RequestValidator` constructed in `main.py` (not in `twilio_ops`)
- `whatsapp.verify_signature` (acceptable at the webhook edge)
- FastAPI exception handlers typed on `azure_openai.AzureBusyError` and `circuit_breaker.CircuitOpenError`

### P1 — Repositories containing business logic

`db.py` is not a dump of SQL. It owns:

- Lead stage FSM (`_LEAD_STAGE_TRANSITIONS`, loss-reason required)
- Handoff claim + visibility
- Followup sweep (priority escalation)
- Promise create → fulfilment orchestration
- `compile_agent_studio_card` / publish pipeline
- `get_contact_policy` wrapping `contact_policy.evaluate`
- Bounce/write paths that trigger `recommend_treatment`

Skill delete guards live correctly in `agent_core/skills/persist.py`. Connector dispatch (circuit + SSRF) lives in `connectors/persist.py` — persist island acting as an HTTP client.

### P1 — God worker

`bot_worker.process_one_any` serialises 15+ unrelated drains on a 1.5s poll: WhatsApp outbound, bot turns, PTP reminders, bounce voice, treatment enact/followthrough/sweep, webhook deliveries, call closer, cadence, campaigns, clerk, canary, pool health. Only three queues (`bot_turn_jobs`, `whatsapp_outbound_jobs`, `kb_index_jobs`) have Prometheus depth. Horizontal replicas race `treatment_followthrough.open_cases` (no row lock).

### P2 — Inconsistent service patterns

| Area | Pattern |
|------|---------|
| Authority / treatment / reco / live QA | `engine` → `decisions` → `enact`; never raise on audio |
| Outbound | `process_one(engine) -> bool`; reserve/Gate/place |
| CRM (promise, dispute, lead, handoff) | `db.create_*` / `db.patch_*` |
| HTTP | Mix of one-liners, `_handle_write`, per-route try/except, fat orchestration |
| Request bodies | Pydantic `schemas.py` **or** `dict[str, Any]` (Agent Studio, campaigns, A2A, floor signals) |

### P2 — Duplicated integrations

| Duplicate | Copies |
|-----------|--------|
| Twilio `Client` | `twilio_sms.py` and `voice/twilio_ops.py` — no shared breaker |
| WhatsApp send | Queued (`whatsapp_outbound`) vs inline (`bot_runtime`) |
| LLM | `azure_openai.chat_with_tools` (optional gateway inside) vs `llm_gateway.client.chat` (retry, no breaker) |
| TTS | Live: `providers/factory.py`. Preview: `provider_tts.py` + `azure_speech` |
| Circuit breaker | In-process `circuit_breaker.py` vs DB-backed `connectors/circuit.py` |
| Flow-control tool set | `grant.VOICE_ALWAYS`, `voice.tools.ALWAYS_ON`, `flow_graph._FLOW_CONTROL_TOOLS` (tests pin equality; production has three sets) |

### P2 — Duplicated validation

Contact window was consolidated into `contact_window.py` (good). Remaining copies: Tool Grant (seven formulas), publish G9 vs runtime grant, product eligibility (`capture.evaluate_product_eligibility` plus direct `db.py` call sites), 42 untyped request dicts beside Pydantic models.

### P2 — Infrastructure leaking upward

- SQLAlchemy `text()` in `main.py`
- Adapter exception types on the FastAPI app
- `/ready` exposing `circuit_breaker.snapshots()`
- `db.py` calling `azure_openai.embed_texts` for FAQ vectors
- `agent_core/deployment.py` module-level `import db`

**Not observed:** ORM models acting as service objects. Persistence is SQLAlchemy Core + raw SQL. Database rows are not pretending to be engines.

### Circular dependencies

Managed, not eliminated. `tests/test_import_cycles.py` boots a **fresh interpreter** per module because pytest collection would hide the cycle.

- `agent_core.cards` ↔ `agent_core.skills` — lazy `__init__` and deferred imports
- `grant.py` sits on both halves; its imports are inside functions on purpose
- `db` ↔ `tenant_context`, `db` ↔ `followups_db`, `capture` ↔ `db` — lazy `import db`
- `money_inr.py`, `contact_window.py`, `visibility.py` exist as **leaf** modules specifically to break cycles

The graph is kept acyclic by discipline. It is not naturally acyclic.

---

## Evaluation

### Dependency direction

**Intended (and already true for Locked Engines):**

```
HTTP / worker / Mouth
        ↓
  engine (orchestrate, never raise)
        ↓
  policy / matrix / checks   ← pure
        ↓
  features / persist         ← SQL
        ↓
  enact                      ← Twilio, SMS, ledger posts
```

**Actual for CRM and most HTTP:**

```
main.py  ↔  db.py  ↔  promise_fulfillment / contact_policy / treatment / azure_openai
                ↕
         35 modules with their own SQL
```

Dependency arrows point **sideways** more often than down. `db.py` imports domain; domain imports `db`. That is the cycle the leaf modules were invented to puncture.

### Module cohesion

Highest: `outbound`, `cadence`, `campaigns`, `call_closer`, `contact_policy`, `authority/*`, `treatment/*`, `skills/persist`, `vault/persist`.  
Lowest: `db.py`, `main.py`, `bot_worker.py`, `voice/tools.py`.  
Transitional (extracted but still multi-surface): `ops_screens.py`, `followups_db.py`.

### Service boundaries

Application services exist as **module-level orchestrators**, not classes:

- Outbound stack is a real boundary.
- Locked Engines are a real boundary.
- `work_runtime.api` is a real (thin) boundary.
- CRM is not: HTTP, tools, and workers all call `db.create_*` which then calls other modules.

### Transaction boundaries

Default: **one `engine.begin()` per public `db.*` function**. Connection-scoped `_create_promise(conn, …)` exists so wrap-up can spawn a promise in the **same** transaction — documented because the double-begin bug already shipped once.

Workers that do it well (claim → commit → slow I/O → complete): `bot_jobs`, `whatsapp_outbound`, `webhooks_dispatch`, `call_closer`, `campaigns`, `cadence`, `kb_ingest`.

Workers that hold the lock through provider I/O: `promise_fulfillment.process_one_reminder`, some `payment_events` voice paths, `treatment_enact` when it dials inside the claim transaction.

Tenant: **three mechanisms** — libpq GUC `app.tenant_id`, explicit `tenant_id = :tenant_id` in SQL, optional RLS (`rls.py`, not assumed on). Visibility predicates are a fourth axis (assignment), reads only. Production still documents deferred hardening (RLS, PII encryption, append-only audit) and refuses to boot `APP_ENV=production` without `ALLOW_UNHARDENED_PRODUCTION`.

### Error boundaries

| Path | Contract |
|------|----------|
| CRM writes via `_handle_write` | `KeyError→404`, `PermissionError→403`, `ValueError→409`, `IntegrityError→409` |
| Publish | `CompileError` / `FlowInvalidError` → 422 |
| Audio / dial / authority engine / treatment enact | **Never raise**; degrade and log |
| Tools | `ToolResult(ok=False)` |
| Azure saturation / circuit open | 503, registered on the app |
| Fulfilment after promise insert | Swallowed — promise commits without pay-link |
| KB retrieve | catch-all 502 |
| Unhandled | Starlette 500; no global handler |

Error mapping is centralised for the `db.*` write club and ad hoc everywhere else.

### Testability

| What | How |
|------|-----|
| Authz totality | `test_authz.py` walks the live route table |
| Import cycles | subprocess per module |
| Locked Engines | `test_authority_engine.py` etc. — no HTTP, often no DB |
| CRM writes | `db_tx` fixture: outer transaction + savepoints; **requires Postgres** |
| SKIP LOCKED | `test_job_claim.py` (contends with a live `worker` if one is running) |
| Tool Grant | characterisation tests of the *seven formulas*; production not wired |

Cannot unit-test a CRM handler without importing `main` and a database. `db_tx` does not wrap modules that bound `engine` at import time instead of going through `db.engine`.

### Lifecycle management

| Process | `DB_PROCESS_ROLE` | Owns |
|---------|-------------------|------|
| `uvicorn main:app` | `api` (15s statement timeout) | HTTP, optional embedded voice host, `usage_meter` daemon thread |
| `python -m bot_worker` | `bot_worker` (60s) | God loop of collections drains |
| `python -m worker` | `worker` (60s) | `kb_index_jobs` + maintenance sweeps |
| `python -m voice.bot` | `voice` (60s) | Real-time Mouth |
| `python -m voice.workers.insurance` | `voice` | Redis mesh specialist |

FastAPI lifespan **does not start workers**. API-only deploy leaves WhatsApp agent sends queued; `whatsapp_outbound` logs a warning, nothing else does. Shutdown order is correct: voice host → `usage_meter.shutdown()` (stop flusher, then drain) → `db.dispose_engine()`. Boot seeds catalogs (permissions, TTS, skills, providers) without re-granting revoked permissions.

---

## Target architecture

Do not introduce a generic `app/services/` pyramid. Extend the three patterns that already work.

### Pattern A — Locked Engine (copy authority)

```
HTTP / tool / worker
        → engine.recommend / engine.decide     # never raises
            → features (SQL reads only)
            → matrix / policy / checks (pure)
            → decisions.log (append-only)
        → enact                                # side effects, Twilio, SMS
        → talk / narrate                       # model-facing copy
        → policy.snapshot                      # Floor / 360 read model
```

Apply next to: Promise (validation vs `fulfill`), Handoff (eligibility vs claim), contact-policy already *is* this (evaluate / admit / log).

### Pattern B — Outbound attempt (already correct)

Keep `outbound.reserve` → caller’s `contact_policy.admit` → `outbound.place` → `call_closer` → `post_call_actions`.  
**Delete the copy in `POST /twilio/voice/outbound`** by calling one application function the workers already use.

### Pattern C — Persist island + `db` facade (already started)

`agent_core/{skills,providers,connectors,vault}/persist.py`, `voice/persist.py`, `followups_db.py`, `ops_screens.py`.

Keep `import db` as a **re-export facade** during the move (same trick as `followups_db` at `db.py:18005`). Callers do not change on day one.

### Target package map

```
backend/
  api/                    # APIRouter per authz section; handlers stay thin
    deps.py               # _handle_write, _authz_guard stays on the app
    customers.py
    collections.py
    handoff.py
    agent_studio.py
    kb.py
    voice.py              # Twilio webhooks + WS
    outbound.py
    webhooks.py
    …
  db.py                   # shrinks to engine, GUC, _rows, facade re-exports
  repos/                  # or keep *_db.py / persist.py names
    customers.py
    collections.py
    interactions.py
    inbox.py
    agent_studio.py
    kb.py
    billing.py
    queues/               # claim/complete for the three formal job tables
  # existing — do not re-split
  outbound.py, cadence.py, campaigns.py, call_closer.py, contact_policy.py
  agent_core/{authority,treatment,reco,live_qa,cards,skills,tools,providers,connectors}
  voice/                  # Mouth process
```

### Target HTTP path

```
route (APIRouter)
  → Pydantic
  → app function (opens txn, or receives conn)
      → repo.insert(conn)
      → engine / fulfill / admit
  → _handle_write (single error map)
```

No SQL in routes. No Azure/Twilio SDK in routes. Webhook routes may call `adapter.verify_signature` then one ingest function.

### Target Tool Grant

`ToolGrant.for_bundle(bundle, channel=…)` is the only formula. Publish G9 calls `static_grant`. Voice `build_tools` **must not union** `ALWAYS_ON` — that set lives in the grant. Cardless → empty grant; delete `TOOL_DEFINITIONS` fallback. Offer is `grant.offer(…)` and cannot widen.

This is ADR-0001/0002 as written. The code is already in the tree.

### Target workers

Split `bot_worker` by SLO and table, not by inventing a broker:

| Process | Tables |
|---------|--------|
| `messaging_worker` | `bot_turn_jobs`, `whatsapp_outbound_jobs` |
| `dialer_worker` | closer, cadence, campaigns, bounce voice, `outbound.sweep_*` |
| `treatment_worker` | enact, followthrough (add SKIP LOCKED), sweep, clerk |
| `integration_worker` | `webhook_deliveries` |
| `worker` | keep — KB + maintenance |

Same `process_one(engine) -> bool` contract. Extend `_JOB_QUEUES` metrics. Move PTP send **outside** the claim transaction. Route **bot** WhatsApp sends through the outbound queue.

### Target integrations

- One Twilio client factory; signature check moves into `twilio_ops`.
- One messaging port: WhatsApp + SMS; all sends queued or behind the port.
- `azure_openai.chat_with_tools` / `embed_texts` as the only LLM surface; gateway stays inside it, one breaker.
- Preview TTS goes through `agent_core/providers`, same as live.
- Connector DB circuit appears on `/ready` with the same snapshot shape.

---

## Migration sequence (lowest risk first)

1. **Wire `ToolGrant`** in text runtime, voice `build_tools`, sandbox, and compile G9. Delete cardless fallbacks. This is an ADR completion, not a refactor.
2. **Extract APIRouters** keyed to `authz.ROUTE_PERMISSIONS` comment sections. Paths unchanged. `test_authz.py` is the gate. Start with health, webhooks, leads, handoff, KB.
3. **Peel `db.py`** in the `ops_screens` / `followups_db` style: Agent Studio persist, inbox, collections writes, KB admin. Facade re-exports so `main` still `import db`.
4. **Move outbound list SQL** out of `main.py` into `outbound.py` (it already owns the attempt ledger). Collapse `POST /twilio/voice/outbound` onto `outbound.place` after reserve+admit.
5. **Split `bot_worker`** by extracting branches; no schema change. Lock followthrough rows before a second replica exists.
6. **Unify Twilio client + WhatsApp send path** (bot replies join the queue).
7. **Single `map_domain_error`** used by `_handle_write`, publish, KB, campaigns.

Do not rewrite Locked Engines. Do not introduce an ORM. Do not mount the MCP Starlette app onto FastAPI. Do not start workers inside the API lifespan — they are a different SLO.

---

## What to copy, what to stop

**Copy**

- `authority/engine.py` docstring: never raise; amount never invented.
- `outbound.py` order of operations: reserve before Gate.
- `authz.py`: one registry + a test that the registry is total.
- `ops_screens.py` header: keep ops surfaces out of `db.py` on purpose.
- `grant.py`: one owner, Offer ⊆ Grant, cardless deny-all.
- `voice/persist.py` header: keep live-call writes off the contested `db.py` surface.
- `tests/test_import_cycles.py`: prove the cycle stays lazy.

**Stop**

- Adding routes to `main.py` instead of a router.
- Adding SQL accessors to `db.py` instead of a persist island.
- Computing a tool set and then unioning onto it.
- Treating `allowed is None` as “ungated”.
- Opening `engine.begin()` in a route when a module already owns the transaction.
- Sending WhatsApp from `bot_runtime` while the agent path already has a queue.
- Holding SKIP LOCKED rows across Meta/Twilio round-trips.
