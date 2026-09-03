# 09 — Canonical implementations

**Role:** principal refactoring architect, semantic consolidation.
**Scope:** `Habibi/src` and `backend/`. Guest tree `PRAXIST-main/` is out of scope.
**Date:** 2026-09-02
**Mode:** read-only. No product code was changed except this file.
**Companions:** `06-duplication.md` (clones and drifted copies), `02-domain-capability-map.md`, `03-frontend-architecture.md`, `04-backend-architecture.md`, `14-error-handling.md`.
**Vocabulary:** `CONTEXT.md`. Terms in **bold** are that glossary.

This report is not a clone hunt. Two functions that look alike are not the topic. Two modules that answer the **same domain question** and can disagree are.

---

## Verdict

The product already knows how to pick a canonical owner. `contact_window.py`, `money_inr.py`, `env_utils.py`, `pg_errors.py`, `agent_core/cards/schema.py`, and `GET /me` exist because a previous pair drifted and someone extracted a leaf. Production still runs the older copies beside those leaves.

Canonicalization here is not “newest file wins” and not “the seed file everything imports.” The owner is the module that **disposes** — the Locked Engine, the publish **Gate**, the ADR enforcement point, the fail-closed leaf with a pin test. Display, mocks, and process-local adapters are consumers.

Five analysts were spawned. The frontend pass returned a full inventory. The business-capability, API, backend, and terminology passes stalled on this tree; those lenses were completed from source in this document, cross-checked against `06-duplication.md` and the architecture series. Claims below were re-read from the files named.

The highest-blast pattern is always the same:

1. A regulated question has a named owner (`contact_policy.admit`, `agent_core/tools/grant.py`, `call_closer.BUSINESS_OUTCOMES`, `money_inr`).
2. Live traffic still uses a second formula.
3. The two have already diverged, or are held equal only by a characterization test that exists because they would.

Do not merge naming collisions. Four meanings of **Offer**, three of **Handoff**, and **Cadence** versus HTTP retry are different questions. Collapsing them would be a worse bug than leaving the copies.

---

## How a candidate was chosen

Not filename. Not git timestamp. Not “TypeScript because the UI imports it.”

| Criterion | Why it wins |
|-----------|-------------|
| ADR names it as the enforcement point | ADR-0001 / ADR-0002 already decided **Tool Grant** |
| It is the Locked Engine / Gate that other paths already treat as source of truth | `admit()`, authority `decide()`, compile G0–G15 |
| Fail-closed, with tests that pin the vocabulary | `call_closer.BUSINESS_OUTCOMES` ↔ SQL CHECK ↔ compile `OUTCOME_CODES` |
| Leaf module that already closed a copy-drift incident | `contact_window`, `money_inr`, `env_utils` |
| Wire DTO the other language already mirrors | `agent_core/cards/schema.py` → `Habibi/src/api/agent-card.ts` |

A seed file that happens to be the TypeScript import hub is a **fixture**, not an owner. `USE_MOCK` ports that recode a Python engine are **transport**, not a second policy.

---

## Canonicalization matrix

Two-column competitors where they exist. Where more than two implementations run, A/B are the pair that can disagree in production.

| Concept | Implementation A | Implementation B | Canonical candidate | Risk |
|---------|------------------|------------------|---------------------|------|
| **Tool Grant** (which tools this **Mouth** may execute) | Live: `skills/intersect.effective_tools` + `voice.tools.ALWAYS_ON` | ADR owner: `agent_core/tools/grant.py` (**no production import**) | `grant.py` `ToolGrant` after callers migrate; until then A is what runs | critical |
| Cardless **Mouth** tool set | `ToolState(allowed=None)` fail-open | ADR-0002 deny-all in `grant.py` | Deny-all. Delete cardless fallback lists last | critical |
| May we contact this borrower **now**? | `contact_policy.admit` | Consent/callback/inbox client verdicts | `admit` / `evaluate`. UI renders the API | critical |
| Blocking channel-consent statuses | `contact_policy.BLOCKING_CONSENT` | Same frozenset in `promise_fulfillment.py`, `payment_events.py` | Import from `contact_policy` | high |
| Is this party on DND? | `customers.dnd` | `consent_records.dnd_registry` (`admit` ORs them) | One column, or dual-write on every mutation | high |
| Allowed weekdays on a consent row | `contact_policy._parse_days` (empty → unrestricted; normalizes en-dash) | `db._parse_allowed_days` (empty → Mon–Fri; no en-dash) | Gate parser. Empty-handling stays at the call site if product requires it | high |
| Empty preferred-window **display** | `contact_window.DEFAULT_WINDOW` `09:00-20:00 IST` | `db.py` fallbacks still emit `10:00-19:00 IST` | `DEFAULT_WINDOW`. Insert NULL, do not stamp a stale literal | high |
| Account tail (last four) | `agent_core.context.account_tail` (digits only) | `db._account_tail` (slice, letters kept) | Digits-only. Desk and **Mouth** must speak the same four | high |
| Conversation **Outcome** | `call_closer.BUSINESS_OUTCOMES` + SQL CHECK + compile `OUTCOME_CODES` (pinned equal) | `interactions.disposition`, UI Disposition unions, `capture.disposition_from_flags` | Closer vocabulary. Do not unify treatment labels or connection axis | high |
| Authority goodwill cap | `agent_core/authority` Locked Engine | `api/authority.ts` `mockAuthorityNext` (+ `VITE_AUTHORITY_*`) | Engine. Mock is a recorded fixture, not a second `decide()` | high |
| Inbound routing `when` AST | `db._match_routing_rule` | `routing-seed.ts` `evalCondition` (always in the browser) | Backend matcher. Simulator calls an evaluate endpoint | medium |
| INR **grouped** display | `money_inr.inr` (`₹-500`, null `—`) | `customer360-seed.fmtMoney` (`-₹500`, null `₹0`) + locals | Python `inr` for account money; one TS twin | medium–high |
| INR **compact** display | `money_inr.inr_compact` | `billing-seed.ts` `inrCompact` (intentional mirror) | Keep the pair; do not merge with grouped | medium |
| Payment-plan status | `db.list_payment_plans` (due `< now` → slipped) | `promises-seed` (one-day grace) | Server derivation. Seed must not invent grace | medium |
| Promise status vocabulary | `PromiseResponse` omits `due_today` | `PromiseListResponse` includes it | List Literal + SQL CHECK. 360 nested promise is a projection | high |
| Staff write-error mapping | `main._handle_write` (KeyError → `exc.args[0]`; IntegrityError → 409) | `main._handoff_call` (`str(exc)`; no IntegrityError) | `_handle_write`. Delete the handoff wrapper | medium |
| List pagination | CRM lists: `limit`/`offset`, default 200, bare JSON **array** | Eval/A2A/change-log: `limit` only, different ceilings | `clamp_list_limit` + array until a cursor envelope exists. Do not mix | medium |
| Staff identity on a write | `GET /me` / `actor_context` | Seed `CURRENT_AGENT` / mock author `"You"` | `Me` + ContextVar. Seeds call `currentActor()` | high |
| Staff **authz** | `authz.ROUTE_PERMISSIONS` + `_authz_guard` | UI Roles screen with no client hide | Server registry. UI may hide; must not be the authority | — (correct split) |
| Environment class | `main._IS_PROD` / `actor_context._app_is_prod` (`APP_ENV` in `{prod,production}`) | `env_utils.env_name` also reads `ENV`; `env_allows_dev_key` uses an explicit laptop allow-list | Two questions, one module: `env_utils`. Delete private copies | high |
| `.env` load | `env_loader.load_env()` (publishes into `os.environ`) | `db._read_env_file` (no publish, by design) | Keep both **behaviours**; every other parser must pick one | high |
| Feature: “may this **deployment** dial at all?” | `platform_flags.campaign_runtime_enabled` (env, default off) | `platform_switches.outbound_enabled` (Postgres, absence = off) | **Both**, in sequence. Not duplicates — see collisions | — |
| Engine shadow/live | `AUTHORITY_MODE` / `TREATMENT_MODE` / `RECO_MODE` / `LIVE_QA_BARGE_MODE` | Frontend `VITE_AUTHORITY_*` | Python `*.config.mode()`. Vite knobs are mock-only | high |
| Offline UI switch | `USE_MOCK` (`VITE_USE_MOCK`, default true in dev) | Per-module mock ports that recode engines | Transport flag only. Ports are fixtures | high |
| Azure OpenAI client | `azure_openai.get_client` (20s / 2 / breaker) | `voice/llm_pool.py` (30s / 2 / **no breaker**); `get_analysis_client`; `llm_gateway` fail-open | Document three **profiles**. Share reasoning-model helper. Do not merge timeouts | high |
| Live TTS construction | `providers/factory.py` fail-closed unbound locale | `provider_bind.bind` fail-open to Azure | `factory.build` + explicit bind. Fail-open is an outage class, not a second factory | high |
| Twilio REST `Client` | `voice/twilio_ops._client` | `twilio_sms` per `send()` | One process-local factory + breaker. TwiML/Media Streams stay separate | medium |
| WhatsApp send | Adapter `whatsapp.py` (one HTTP) | Orchestrators: in-session `bot_runtime` vs queued `whatsapp_outbound` | Adapter = `whatsapp.py`. One retry/dead-letter helper; two queues stay | high |
| Job retry cap | `bot_jobs.max_attempts` (`BOT_JOB_MAX_ATTEMPTS`, 5) | `whatsapp_outbound.max_attempts` (`WHATSAPP_OUTBOUND_MAX_ATTEMPTS`, 5) + different backoff ceilings | Shared `mark_failed_or_retry` policy object. Caps may differ by queue | medium |
| Exception → HTTP | Domain types (`CompileError`, `CircuitOpenError`, `StorageUnavailable`, `OutboundDisabled`) | Ad-hoc `HTTPException` / `KeyError` → 404 | Keep typed errors. Map in one handler table. `_handle_write` for CRM KeyError | medium |
| Unique-violation detect | `pg_errors.is_unique_violation` | Any remaining `pgcode == "23505"` inline | `pg_errors` (already the leaf) | low |
| Customer TypeScript shape | `customer360-seed.Customer` (nested 360 graph) | `handoff.CustomerContext` / inbox `ThreadContext` | Live `CustomerResponse`. Board/handoff types are **projections** | high |
| Date display | 360 `fmtDate` (`en-IN` + `Asia/Kolkata`) | upsell/callbacks `undefined` locale; raw `toLocaleString()` | Extract 360 pair to `lib/`. Slot **math** is not a formatter | high |
| List query UI | `QueryState` (empty only after success) | `query.data ?? []` (dominant) | `QueryState` | high |
| Mutation home | `api/*` `useMutation` | Route-inline / leaf `busy` | Domain hooks in `api/` | medium |
| Mouth HTTP | `/prompt-versions` (prompt, persona, voice, flow) | `/agent-studio/cards` (compile, graph) | Two surfaces for two resources. Typed `AgentCard` on card JSON | medium |
| Voice authoring object | `VoiceConfig` (editor: Azure columns + `params`) | `AgentTuning.tts` (runtime JSON on `bot_deployments.tuning`) | Tuning is runtime; VoiceConfig is the editor projection that **folds into** tuning | medium |
| Viewport ≥ N px | `hooks/use-min-width.ts` | Local `useIsLg` in 360; unused `use-mobile.tsx` | `useMinWidth` only | low |
| Confirm destructive action | `confirm-gate` / `use-confirm` | Residual `window.confirm` comments (mostly already replaced) | `use-confirm` | low |
| Deep-link search | `parseDeepLinkSearch` `{id, new}` | Per-route `{callId}` / `{conversationId}` / duplicated `{unansweredId, note}` | Helper per key shape. Zod already used once on 360 `tab` | medium |
| Query-key identity | Prompt-studio `VERSIONS_KEY` constants | Inline tuples; dead `["customer", id]` | Per-module key factories | medium |

---

## P0 — Same question, two answers that can disagree on money, contact, or consent

### C-01 — Tool Grant

**Question:** which tools may this **Mouth** execute, and which subset is the **Offer** this turn?

**Implementations.** Live grant is `intersect.effective_tools` (unions connectors, no channel filter). Publish **Gate** G9 `allowed_scope` omits catalog intersect, connectors, and `VOICE_ALWAYS`. Voice unions `ALWAYS_ON`. Text/sandbox cardless fallbacks still contain write tools. `grant.py` is the ADR-0001 owner and still says “Nothing imports this yet.”

Cardless path in `MouthTurn.tools()` returns `ToolState(allowed=None)` — documented as **no filtering**. ADR-0002 requires deny-all.

**Why they exist.** Six formulas grew while the card was being invented. `grant.py` was added beside them so callers can migrate. Voice cannot import the API process’s pipecat-free grant leaf without a shared constants module; that is a real process constraint, not sloppiness.

**Canonical.** `agent_core/tools/grant.py` `ToolGrant.for_bundle` / `may_execute` / `static_grant`. G9 must call `static_grant` so publish is the union of runtime. One `VOICE_ALWAYS` leaf the API can import.

**Must not merge.** Staff `authz.ROUTE_PERMISSIONS` (may this **operator** hit this **route**?) with the **Tool Grant**. They are two permission systems on purpose (`04-backend-architecture.md`).

**Contradicts ADR-0001 and ADR-0002 until callers move.** Wiring `ToolGrant` without removing `| ALWAYS_ON` would hide a seventh formula.

---

### C-02 — Contact admission

**Question:** may we contact this borrower, on this channel, for this purpose, at this instant?

**Implementations.** Owner: `contact_policy.admit` / `_veto` (RBI voice 8–19, published `calling_window`, preferred ∩ consent hours, cooling-off, caps, `BLOCKING_CONSENT`). Customer 360 `ContactabilityPill` already asks `GET /customers/:id/contact-policy`. Consent board (`isContactableNow`), callback sheets (`isWithinDndWindow`), live QA `check_hours`, and treatment `_window_for` restate subsets. Inbox `contactableNow` is a baked seed boolean.

**Behaviour.** A 19:30 IST callback is inside `contact_window` 09–20 and blocked for voice outreach. Consent UI uses the operator’s local clock; `admit` uses borrower TZ / IST rules. Mock `mockVeto` skips cooling-off, caps, promotional purpose.

**Why they exist.** The pill was rewritten onto the engine. Consent and callbacks were not. Live QA is a detector, not a second **Gate**. Treatment planning hardcodes 8–19 then **enact** still calls `admit()` — the plan can propose a slot the Gate will refuse.

**Canonical.** `contact_policy.admit` / `evaluate`. Preferred-window *math* stays `contact_window` (borrower preference, not RBI). Live QA imports the published window or calls `evaluate(now=…)`.

**Must not merge.** Multi-channel “3 of 4 channels OK” with the voice-outreach veto. Preference window with statutory hours.

---

### C-03 — DND fact, allowed days, preferred-window display

Three stored/display rules that operators treat as one “when can we call” setting.

| Sub-question | Drift | Canonical |
|--------------|-------|-----------|
| Registry DND | Two columns; `admit` ORs; callback DND chip reads customer only | One store |
| Allowed days | Empty and en-dash already disagree between Gate and CRM write | `contact_policy._parse_days` |
| Empty window shown | Math uses 09–20; serializers still print 10–19 | `contact_window.DEFAULT_WINDOW` |

`contact_window.py` already closed the *math* copy-drift. Display literals in `db.py` (sites recorded in `06-duplication.md` DUP-06) did not follow. That is the same incident class, not a new concept.

---

### C-04 — Account tail

**Question:** last four of the account id, for `verify_identity` and desk cards.

`context.account_tail` keeps digits only. `db._account_tail` slices the raw string. Vanity id `AC-SUSANTH` → `"ANTH"` on the desk, `None` on the **Mouth**. Canonical is the digits function: it is what the borrower hears. Habibi seeds using `slice(-4)` are mock-only and must match.

---

### C-05 — Conversation Outcome versus every “disposition”

**Question:** what the conversation **settled**, as one code from a closed vocabulary.

The glossary **Outcome** is already canonical in three places, pinned equal: `call_closer.BUSINESS_OUTCOMES`, `sql/21_outbound.sql` CHECK, compile `OUTCOME_CODES`. Prior claims that those three differ are false.

Competing **other** vocabularies (do not collapse into Outcome):

| Vocabulary | Question it answers |
|------------|---------------------|
| Connection axis | Did the phone connect? **Cadence** retries on this |
| Treatment labels | Training/attribution coarsening |
| `capture.disposition_from_flags` | Legacy four-value mix of connection and business |
| `interactions.disposition` | Unconstrained TEXT |
| UI `Disposition` / handoff wrap-up / `CbDisposition` | Display / human wrap-up / **callback slot** reachability |

Canonical for post-call obligations and **Cadence** `stop_on`: closer codes. Map UI labels onto them. Stop writing `disposition_from_flags` into anything Cadence reads.

---

### C-06 — Authority matrix (Locked Engine vs browser)

Live panel uses `GET /authority/next`. `USE_MOCK` recodes the ladder in `mockAuthorityNext`. `lib/authority-policy.ts` is labels only. Canonical is `agent_core.authority`. Mock should seed a recorded `AuthorityNext`, not re-implement `decide()`. `VITE_AUTHORITY_LATE_FEE_*` must not be a production policy control.

Same shape: `lib/customerInsights.ts` / `mockOfferPolicy` versus treatment/reco snapshots. Insights are presentation; NBA that looks like a Locked Engine on a live borrower is a lie.

---

## P1 — Same concept, different contract

### C-07 — Promise as two resources

`PromiseResponse` (nested on Customer 360) omits `due_today` and board fields. `PromiseListResponse` is the desk row (`due_today`, `source`, `owner`, events, payment intent). TypeScript repeats the split: `customer360-seed.Promise` vs `promises-seed.Promise`.

These are **projections of one SQL entity**, not two products. Canonical status Literal is the list/CHECK vocabulary. The 360 nested object is a subset. Creating a PTP from 360 cannot populate board-only fields unless the API returns the list shape (or the client refetches `/promises`).

Payment-plan `on_track` / `slipped`: server uses `dueDate < now`; seed uses a one-day grace. Canonical is `list_payment_plans`.

---

### C-08 — Pagination

CRM list routes take `limit` (optional, Query ge=1 le=`MAX_LIST_LIMIT`) and `offset` (default 0). Omitting `limit` is **default page, not unbounded** (`clamp_list_limit`). Response is a **bare array** — documented in `db.py` as why bounding had to be additive.

Other lists (`/eval/*`, A2A tasks, agent change-log) take `limit` only with local defaults (50) and local ceilings (200–500). Frontend almost never sends `offset`; cadence uses `?limit=50` as a one-off.

There is no cursor type and no `{items, total}` envelope on the CRM spine. Canonical *helper* is `clamp_list_limit` / `clamp_offset`. Canonical *envelope* does not exist yet — do not invent a second one per feature. Adding `total` is a product change to every array consumer.

---

### C-09 — Write errors and HTTP exceptions

`_handle_write` maps KeyError → 404 with `exc.args[0]` (so the UI does not toast `'key'`), PermissionError → 403, ValueError → 409, IntegrityError → 409 `constraint_violation`. `_handoff_call` still uses `str(exc)` and drops IntegrityError (constraint → 500).

Typed failures already exist and should stay typed: `CompileError` / `FlowInvalidError` → 422, `CircuitOpenError` / `AzureBusyError` → 503, `StorageUnavailable`, `OutboundDisabled`, `NoBindingError`, `PermissionDenied`. Canonical mapping is one table next to `_handle_write`, not a new exception hierarchy that wraps everything in `HabibiError`.

Frontend `ApiError` (status + detail + path) is the one client type. Callers that still `catch (Error)` lose `isNotFound()`.

---

### C-10 — Actor, tenant, correlation

Three ContextVars on purpose (`actor_context`, `tenant_context`, `request_context`). A bug that leaked a log id into identity would be a security bug; they must not share a module.

Drift: `db._read_env_file("TENANT_ID")` vs `os.getenv` vs `tenant_context` defaulting through `db.TENANT_ID` — the modules’ comments already name a past empty-RLS incident. Canonical **read** is `db.current_tenant()` / `tenant_context.current_tenant()`. Canonical **actor** is `actor_context.get_actor_user_id()` after API-key middleware. UI chrome is `GET /me`. Seed `CURRENT_AGENT` and mock author `"You"` are the remaining liars.

`authz` answers route permission. `visibility.py` answers **which customers**. Neither is the **Tool Grant**.

---

### C-11 — Environment and flags (four systems, two real splits)

| System | Shape | Question |
|--------|-------|----------|
| `env_utils.env_name` / `env_allows_dev_key` | Process env | What environment is this, and may we use a committed secret? |
| `main._IS_PROD` / copies | `APP_ENV in {prod,production}` | Require API keys, disable docs? |
| `platform_flags` | Env bools, default **off** | Does this deployment have the feature at all? |
| `platform_switches` | Postgres, **absence = off** | Stop dialling **now**, without restart? |
| Engine `*_MODE` | `off` / `shadow` / `live` | Has this Locked Engine earned production dispose? |
| `USE_MOCK` | Vite, default true in **dev** | Is the browser talking to the API? |

`platform_switches.py` already explains why it sits next to `platform_flags`: env flags are the wrong shape for “stop dialling, now.” **Do not merge those two.** Drift risk is a **new dial path** that checks only one of: flag, switch, `admit()`.

`env_name()` reads `APP_ENV` **or** `ENV`. `_IS_PROD` reads only `APP_ENV` (default `dev`). `ENV=production` with unset `APP_ENV` makes `env_name` say production and `main` say not. Canonical: all copies import `env_utils`. Keep the **two questions** (prod vs laptop-allow-list) — `env_utils` docstring says a typo must not unlock committed vault keys.

Bool parsing: `platform_flags._TRUE = {1,true,yes,on}` vs `voice.config` similar helper vs `int(os.getenv(...))` in job modules vs `env_int` (malformed → default, never raise). Canonical parser for integers is `env_utils.env_int`. Canonical parser for feature booleans is `platform_flags._flag` or a leaf next to it — not a third `_TRUE` set.

`.env`: `load_env()` publishes; `db._read_env_file` must **not** (importing `db` must not mutate the process). That split is load-bearing. Callers that need TENANT_ID must not invent a third parser.

---

### C-12 — Retry is four concepts

| Name | Question | Canonical |
|------|----------|-----------|
| **Cadence** | When to attempt the same **Mission** again | `cadence.py`. Must not change the action |
| Job retry | `bot_turn_jobs` / WhatsApp outbound SKIP LOCKED | `mark_failed_or_retry`; caps per queue OK |
| HTTP client retry | React Query `retryUnlessClientError`; SDK `max_retries` | Keep per transport |
| Circuit breaker | Fail fast when Azure/Meta/MinIO are down | `circuit_breaker.py` — **Twilio never imports it** |

Do not “unify retry.” Cadence that started changing treatment would outvote the Locked Engine.

---

### C-13 — LLM / TTS / STT / Twilio

Not token clones. Competing **control planes** for one capability.

- **LLM:** sync Azure chat+embeddings (breaker), analysis client (8s, 0 retries), voice async pool (no breaker), gateway tried first then **fail-open to Azure**. Reasoning-model detection copied (`azure_openai` vs `llm_pool` vs `tuning_apply._is_reasoning_model`). Canonical helper: one `is_reasoning_model`. Canonical *clients*: keep profiles; document that voice bypasses the gateway.
- **TTS:** `factory.build` fail-closed vs bind fail-open vs REST preview (`provider_tts` / `azure_speech.synthesize`). Studio can audition a voice the call cannot use. Canonical live path: factory + bind. Do not merge REST preview into Pipecat.
- **Twilio REST:** two `Client()` factories, 10s timeout, no breaker. Canonical: one `rest_client()`. Media Streams / TwiML are a different API.
- **WhatsApp:** one Graph adapter, two orchestrators, two backoff ceilings, no idempotency key → double-send risk.

Payment HMAC (`payments.py` vs `payment_events.py`) is the same algorithm with two secret getters — extract `hmac_body`. **Do not** merge with Twilio `RequestValidator` or Meta `X-Hub-Signature-256`.

---

## P2 — Frontend concepts with multiple owners

The frontend analyst’s inventory is the type/formatter/query layer. Owners below; chrome clones (KPI strips) stay in `06-duplication.md` DUP-19 and are not re-opened here.

### C-14 — Seed files as the TypeScript domain model

Live `api/customers.ts` types `GET /customers` as `Customer` from `customer360-seed.ts`. A wire field missing on the seed is invisible; a seed-only field (`Contact.allowedDays`) is documented as absent from `CustomerResponse`.

Canonical per resource is the **Pydantic DTO** (`CustomerResponse`, `PromiseListResponse`, `AgentCard` in `schema.py` / `api/agent-card.ts`, `OfferPolicy` in `lib/offer-policy.ts`). Seeds remain fixtures.

**Must not merge.** Agent Card `Channel` (`internal|mcp|a2a`) with collections `Channel` (`chat|email`). `OfferPolicy` (Locked Engine DTO) with `LeadOffer` (pipeline ticket). `VoiceConfig` with `CardMouthRef` (pointers, not TTS knobs).

### C-15 — Money and dates

Grouped INR: extract 360 `fmtMoney` to `lib/` and match Python sign/null, **or** change Python to match the UI — pick one and pin. Compact: keep `inrCompact` ↔ `inr_compact`. Upsell `fmtMoney` is a compact/ticket formatter wearing the account name.

Dates: 360 pins `Asia/Kolkata`. Upsell/callbacks use the browser zone. Same UTC instant can be “today” on 360 and “yesterday” on a US laptop — which then disagrees with `admit()`. Canonical display is the IST pair. Callback **slot math** (`Date.getHours()` in the agent zone) is C-02, not a formatter.

### C-16 — QueryState, mutations, keys, 360 cache

`QueryState` exists because `data ?? []` told authors the catalog was empty during an outage. It has essentially one consumer. Canonical is `QueryState`.

Mutations: three homes. Canonical is `api/*` hooks (the `webhooks.ts` / `integrations.ts` pattern).

Keys: prompt-studio constants vs inline tuples vs dead `["customer", id]` vs `["documents"]` (CRM) colliding in English with `["kb","documents"]`. Canonical is per-module factories.

360 detail: loader → `useState` + imperative `fetchCustomer`, while insights is React Query. Canonical: `useQuery(["customers", id])` (loader as `initialData` if needed). `deriveCustomerInsights` on error is a silent second engine — starve it.

### C-17 — Mouth editor: two HTTP surfaces, one page

Prompt columns live on `prompt_versions`. The **Agent Card** is jsonb compiled by `schema.py` (`extra="forbid"`). The UI hosts both under `/agent-studio` after redirecting `/prompt-studio`. `AgentCardSummary.agentCard` is still `Record<string, unknown>` while `api/agent-card.ts` is the typed mirror. Canonical card JSON is the typed `AgentCard`. Canonical Mouth editor state is the live `/prompt-versions` payload. Do not squash the two HTTP resources: they are two persistence rows.

`VoiceConfig.params` exists because provider knobs used to live in component state and never published. Runtime authority is `AgentTuning` on `bot_deployments.tuning`, applied by `voice/tuning_apply.py`. Editor folds into that JSON; it is not a second TTS stack.

Compile `GateStatus` includes `"warn"` (`compile.py`). Glossary **Gate**: pass, block, or skip — never green for a check it did not run. `warn` is a fourth outcome the UI already types. Canonicalise the **name** against the glossary (block = fail) and decide whether warn is skip-with-note or a real product state; do not let it mean pass.

---

## Naming collisions — do not canonicalize across

| Word | Distinct concepts | Naive merge would |
|------|-------------------|-------------------|
| **Offer** | Tool **Offer** (subset of **Grant**); reco product offer; treatment next action; authority waiver | Let a prompt-cost narrowing become a money decision |
| **Handoff** | Card-named agent-to-agent **Handoff**; UI “Handoff hub” (human **transfer**); routing action `"handoff"` | Route a live call to the wrong card or a human queue |
| **Gate** | Publish compile G0–G15; `contact_policy.admit` | Skip a publish check because outreach was admitted |
| **Cadence** | Mechanical **Mission** retry | Become HTTP retry or change the treatment action |
| **Config** | Agent Card (avoid this word); `AgentTuning`; env/`platform_flags`; Vite `USE_MOCK` | Restart-required flags become operator switches or vice versa |
| **Channel** | Collections CRM vs Agent Card vs consent vs callback | Allow `mcp` on a PTP or drop `email` on a card |
| **User / actor** | Borrower (`customers`); operator (`users` / `Me`); **Mouth** (`bots`, kind `"bot"` on staff) | Attribute a write to the delinquent account |
| **Disposition / status / result** | Glossary **Outcome**; connection; promise status; presence; deployment status | Cadence stops on a UI label |
| **Transfer** | Reserved for reaching a human | Confused with **Handoff** |
| **Retry** | **Cadence** vs jobs vs HTTP vs breaker | See C-12 |
| **Mouth** | Glossary speaking surface; leftover `bot_id` / “Bot analytics” | Cosmetic until FKs move; do not rename tables in this pass |

---

## Already canonical — do not reopen

| Concern | Owner |
|---------|--------|
| Preferred-window *math* | `contact_window.py` |
| INR compact ladder (Python + billing TS) | `money_inr.inr_compact` / `inrCompact` |
| Unique-violation | `pg_errors.is_unique_violation` |
| Env int/float parse | `env_utils` |
| Agent Card wire schema | `agent_core/cards/schema.py` (TS mirror in `api/agent-card.ts`; pin `test_agent_card_schema_drift.py`) |
| Rollback-trigger vocabulary | `schema.ROLLBACK_TRIGGERS` (compile and canary import it) |
| Acting user chrome vs audit | `GET /me` / `MeResponse` |
| Assignee roster | `GET /staff` / `useStaff` |
| Confirm dialogs | `confirm-gate` (product surface, not `window.confirm`) |
| Product eligibility | `capture.evaluate_product_eligibility` (reco/tools wrap it) |

Remaining copies of these are wrappers, serializers, or documented mocks.

---

## Gaps the glossary does not name

Code has these as real concepts; `CONTEXT.md` does not. Do not invent product language here — flag only:

- **Connection** (vs business **Outcome**) — closer already splits the axes.
- **Reachability** of a card (entry / handoff / direct / unreachable) vs **admit()** of a borrower.
- **Deployment** vs published version vs draft (`AgentCardSummary.deploymentStatus`).
- **Platform switch** vs **platform flag** vs engine **mode**.
- Human **transfer** queue (Handoff hub) — glossary reserves the word; the UI does not.

---

## Consolidation sequence

Order is blast, then what the ADRs already require. Each step deletes copies; none adds an eighth formula.

1. **Tool Grant** — migrate to `grant.py`; G9 = `static_grant`; one `VOICE_ALWAYS`; cardless deny-all last (ADR-0001, ADR-0002).
2. **Contact** — delete live client verdicts; Consent/callbacks render `admit`/`evaluate`; one DND column; one days parser; display `DEFAULT_WINDOW`.
3. **Outcome** — stop writing legacy disposition into Cadence paths; map UI unions onto closer codes.
4. **Identity spoken** — `db` imports `context.account_tail`; TS mock matches digits.
5. **Money/dates** — one grouped TS twin of `money_inr.inr`; IST formatters in `lib/`; rename upsell compact.
6. **Authority/insights mocks** — fixtures, not engines; kill insights fallback-on-error.
7. **`_handoff_call` → `_handle_write`**; env reads → `env_utils`; job retry helper shared; Twilio REST singleton + breaker.
8. **Frontend types** — DTOs from `schemas.py`, seeds as fixtures; `QueryState`; query-key factories; 360 into React Query; `useMinWidth` only.

Do not start with KPI-strip extraction (DUP-19). It does not decide money, contact, or consent.

---

## Analyst coverage

| Lens | Result |
|------|--------|
| Frontend | Completed. Seed-as-model, money/dates, contactability, USE_MOCK ports, QueryState, mutation homes, Mouth dual HTTP, identity, 360 cache, routing sim, query keys, Outcome labels, AppShell/breakpoints, deep-links. |
| Business capability, API, backend, terminology | Spawned; stalled on this tree. Lenses filled from source + `02` / `04` / `06` / `14`, verified against the files cited above. |

No product code was changed.
