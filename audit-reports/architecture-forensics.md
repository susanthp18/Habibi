# Habibi Architecture Forensics Audit

**Product:** Habibi (regulated collections platform)  
**Date:** 2026-09-01  
**Mode:** Read-only. No source, config, git, or dependency changes.  
**Report file:** `audit-reports/architecture-forensics.md`  
**Assigned filename:** `architecture-forensics.md` (placeholder `REPORT_FILENAME` was not supplied in the prompt)

Legend used throughout:

- **Observed fact** — stated from repository evidence.
- **Strong inference** — supported by code + tests, with limited runtime uncertainty.
- **Weak inference** — plausible, needs runtime confirmation.
- **Recommendation** — future work only; nothing in this audit was fixed.

---

## 1. Executive Summary

Habibi is a **single-tenant-per-process** FastAPI CRM plus a TanStack operator console. Policy engines (authority, treatment, contact policy, live QA) are intended to own money, contact, and consent decisions; the language model is the mouth. That intent is written down in `CONTEXT.md`, two accepted ADRs, and a substantial test suite.

The architecture is **coherent at the seams and overloaded at the centers**.

What is already well designed: a unified tool catalog (`agent_core/tools/catalog.py`) with shared domain handlers; a total authz route registry with fail-closed unregistered routes; an explicit `USE_MOCK` production hard-error; SSRF guards on outbound webhooks; HMAC-signed webhook delivery; a boot-time production hardening gate; and characterization tests that *name* the remaining grant-migration work.

What is not done: the accepted Tool Grant ADRs are implemented as a **test-only module**. Production still uses seven live formulas, and **cardless mouths fail open** onto write tools including `create_promise_to_pay`. Mid-call **handoff does not refresh the grant**. The data plane’s last line of defence — Postgres RLS, PII column encryption, append-only audit — is **deferred**, with production boot allowed only via `ALLOW_UNHARDENED_PRODUCTION=1`. Two operator screens still compute collections policy in the browser on the live path: Customer 360 insights (loading + error fallback) and Consent contactability (agent-local clock).

This is not a rewrite candidate. It is an incremental-migration candidate: wire the grant owner that already exists, close the fail-open sentinels, extract `db.py` / `main.py` by domain, and treat the hardening gate as a real release constraint rather than a flag to set and forget.

**Overall:** the product has unusually strong *intent documentation* and *characterization tests* for a codebase of this size, and unusually large *god modules* plus *ADR-accepted-but-unwired* control planes. The highest-leverage work is connecting code that already exists, not inventing new abstractions.

---

## 2. Scope

**In scope**

| Tree | Role |
|------|------|
| `backend/` | FastAPI CRM, voice (Pipecat), WhatsApp bot worker, sandbox, MCP, schema, tests |
| `Habibi/` | Operator console (TanStack Start / React) |
| `docs/adr/`, `CONTEXT.md`, `backend/DATA_MODEL.md` | Intended architecture |
| `backend/docker-compose.yml`, Alembic, `backend/sql/` | Runtime and schema topology |

**Out of scope**

- `PRAXIST-main/` (separate research platform; not on the Habibi runtime path)
- `source_db/` corpus content
- `node_modules/`, `.venv/`, generated caches
- Live traffic, production cluster config, and secret values (not read)
- Implementation patches (forbidden by contract)

**Dynamic behavior explicitly considered:** plugin/string tool maps, FastAPI middleware vs authz registry, ContextVar tenancy, `MouthTurn` `None` sentinel, Vite env inlining, Alembic vs `sql/` dual install path, Docker service graph, lazy frontend routes.

---

## 3. Methodology

1. Read domain docs (`CONTEXT.md`, ADRs 0001–0002, `DATA_MODEL.md`) before treating folder names as architecture.
2. Inventory entry points: `main:app`, `bot_worker`, `worker`, `voice.bot`, `mcp_server`, Docker Compose services.
3. Measure module size, route shape, and import direction (file sizes, `@app` counts, `include_router`).
4. Launch five parallel read-only inspectors: Tool Grant vs ADR; auth/tenancy/PII/SSRF; runtime duplication; frontend mock/policy drift; dead/orphan modules.
5. Corroborate every P0/P1 claim against source line ranges in this session (not agent summary alone).
6. Classify duplication A–J only when two paths are functionally equivalent or fragment a single capability without a channel reason.
7. Record false positives where static “unused” or historical ops notes disagree with current code.

No packages were installed. No formatters, fixers, or git mutations were run.

---

## 4. Repository / System Context

### 4.1 Product intent (documented)

Habibi is a collections platform: autonomous agents speak on voice and WhatsApp; **locked engines**, not the model, dispose of money/contact/consent. Glossary (`CONTEXT.md`): Mouth, Agent Card, Skill Pack, Tool Grant, Offer, Gate, Flow, Handoff, Mission, Cadence, Outcome.

ADR-0001: one owner for the Tool Grant; that module *is* the gate; an Offer is never a safety mechanism.  
ADR-0002: a cardless mouth is granted **no** tools (deny-all).

### 4.2 Observed runtime topology (fact)

Docker Compose (`backend/docker-compose.yml`) runs:

| Service | Command | Role |
|---------|---------|------|
| `db` | Postgres 16 + pgvector | System of record |
| `redis` | Redis 7 | Queues / session adjunct |
| `minio` | S3-compatible | Media `storage_ref` |
| `api` | `uvicorn main:app` (1 worker) | CRM HTTP + optional embedded voice host |
| `worker` | `python -m worker` | KB index / scheduled jobs |
| `bot_worker` | `python -m bot_worker` | WhatsApp turns, outbound drain, treatment enact, webhook delivery |
| `voice` | Pipecat runner (`:7860`) | Production voice path |

Tenancy: **one process, one `TENANT_ID`** (`db.py:92`, default `hdfc.retail`). `tenant_context` holds a ContextVar and publishes `app.tenant_id` as a libpq startup GUC so RLS *could* compare against it. No request middleware binds tenant from `X-Tenant` or JWT.

### 4.3 Conversation surfaces (fact)

| Surface | Canonical code | Production? |
|---------|----------------|-------------|
| Voice | `voice/bot.py` + `voice/tools.py` + `voice/crm_sink.py` | Live |
| WhatsApp / text | `bot_runtime.py` + `bot_tools.py` + `bot_worker.py` | Live (`BOT_RUNTIME_ENABLED`) |
| Studio text sandbox | `sandbox_runtime.py` | Live (operator) |
| Studio live voice | `voice_sandbox.py` | Live (operator) |
| MCP | `mcp_server.py` / `agent_core/mcp_http/` | Separate process, read-oriented |
| Latency spike | `voice/spike.py` | CLI / diagnostic only |

Shared brain: `agent_core/` (cards, skills, tools catalog/domain, authority, treatment, live QA). Channel adapters are supposed to be thin; they are not yet uniformly thin.

### 4.4 Frontend

TanStack Start app (`Habibi/`). Data access is centralized behind `src/api/config.ts` `USE_MOCK`. Dev defaults mock **on**; production builds **throw** if mock is forced or `VITE_API_BASE_URL` is missing. ~42 route files, ~48 API modules, ~474 TS/TSX files under `src/`.

### 4.5 Schema

Fresh DB in CI: apply `backend/sql/*.sql` in name order, then `alembic stamp head`. Existing deployments: Alembic chain (~102 revisions). `DATA_MODEL.md` maps domains; `work_items` is a VIEW, not a table.

### 4.6 Size snapshot (fact, this session)

| Asset | Count / size |
|-------|----------------|
| `backend/*.py` (repo scan) | 582 files |
| `backend/tests/test_*.py` | 186 files |
| `backend/alembic/versions/` | 102 revisions |
| `backend/sql/*.sql` | 25 files |
| `backend/db.py` | **691.9 KB, 16,583 non-blank lines** (largest module) |
| `backend/main.py` | 211 KB, **100** `@app.(get\|post\|put\|patch\|delete)` handlers, **0** `include_router` |
| `backend/schemas.py` | 98 KB / ~2,633 lines |
| `voice/tools.py` | ~129 KB (largest voice module) |
| `Habibi/src` TS/TSX | 474 files |

---

## 5. Key Findings

| ID | Severity | Confidence | Finding | Location | Impact |
|----|----------|------------|---------|----------|--------|
| AF-01 | P0 | HIGH | Deferred data-plane controls (RLS, PII encryption, append-only audit). Production boot only via explicit ACK. | `backend/main.py:388–418`; `DATA_MODEL.md:298–304`; `backend/rls.py` | Real customer data on this build has Python-only tenant isolation. One missed predicate is a silent cross-tenant 200. |
| AF-02 | P1 | HIGH | Cardless / unparseable cards fail-open to default write tools (ADR-0002 unimplemented). | `agent_core/skills/runtime.py:127–145,216–224`; `bot_runtime.py:947–951`; `sandbox_runtime.py`; `voice/bot.py:1132–1154` | Unauthored mouths can be offered `create_promise_to_pay` and the rest of the skill-gated write surface. |
| AF-03 | P1 | HIGH | Handoff does not refresh Tool Grant (voice or text). | `voice/bot.py:1132–1156`; `voice/tools.py` `handoff_to_agent`; `bot_runtime.py:45–46,712–717` | Receiving agent's card is ignored; source grant/prompt persist. Permission bleed on a regulated channel. |
| AF-04 | P1 | HIGH | `ApiKeyMiddleware` exempt list omits paths that `authz.PUBLIC_ROUTES` treats as signature-auth. | `main.py:233–257` vs `authz.py:229–233`; `main.py:3669`, `857` | When `API_KEY` is set, Twilio SMS status and CBS payment-event ingest 401 before HMAC. Availability / automation break, not an auth bypass. |
| AF-05 | P1 | HIGH | Live Customer 360 insights use client-derived offer/NBA on loading and on API failure. | `Habibi/src/api/customers.ts:45–58`; `customers.$customerId.lazy.tsx:114`; `lib/customerInsights.ts:196–220` | Operators can see fabricated next-best-action / offer policy as if the engine produced it. |
| AF-06 | P2 | HIGH | Canonical `ToolGrant` is test-only; seven live formulas remain (ADR-0001). | `agent_core/tools/grant.py:26–31`; `tests/test_tool_grant_characterization.py` | Publish vs runtime vs channel can disagree; connectors (`ext.*`) already documented as G9 drift. |
| AF-07 | P2 | HIGH | Consent screen contactability uses browser-local clock, not `GET /contact-policy`. | `Habibi/src/components/consent/ContactablePill.tsx`; `data/consent-seed.ts:350–416` | Same customer can disagree with Customer 360 pill and the dialler veto. |
| AF-08 | P2 | HIGH | God modules: `db.py` ~16.5k lines; `main.py` 100 routes, no routers. | `backend/db.py`; `backend/main.py` | Change risk, merge conflict, and review cost on every CRM feature. |
| AF-09 | P2 | HIGH | Layer inversion: `agent_core` and WhatsApp runtime import `voice`. | `agent_core/live_qa/enact.py`; `bot_runtime.py` (~1271) | Core policy and text channel coupled to voice transport/persist. |
| AF-10 | P2 | HIGH | Call/interaction export writes stored transcript without `pii_redact`. | `voice/call_export.py`; `main.py:1030–1063` | Any `INTERACTIONS_READ` actor can download unmasked stored text. |
| AF-11 | P2 | HIGH | Dual schema sources (`sql/` vs Alembic) — intentional, reverse-drift is a prod breaker. | `backend/sql/`; `alembic/versions/`; `tests/test_schema_parity.py` | Column in SQL but no migration → existing deploys miss it. |
| AF-12 | P2 | HIGH | `POST /a2a` skips API key; trusts proxy client-cert headers. | `main.py` `/a2a`; `agent_core/a2a.py` | Direct exposure without a stripping ingress allows forged partner tasks. **Deployment-dependent.** |
| AF-13 | P2 | HIGH | `VITE_API_KEY` is inlined in the SPA; actor header is a first-class impersonation seam. | `Habibi/src/api/config.ts:37–54`; `actor_context.py` | Browser bundle holders can call the CRM as that key; non-prod can spoof `users.id`. |
| AF-14 | P3 | HIGH | `seed_first_party()` has zero callers; TTS `provider_voice_sync` is CLI-only. | `connectors/persist.py:405–421`; `provider_voice_sync.py` | Migrate-only / non-Azure catalog gaps. |
| AF-15 | P3 | HIGH | Triple `ALWAYS_ON` / flow-control literals (already pin-tested). | `voice/tools.py:80–94`; `grant.py`; `flow_graph.py:773–784` | Authoring catalog can omit tools the runtime keeps. |
| AF-16 | P3 | HIGH | Two transcript writers, different index allocation. | `voice/persist.py` vs `capture.insert_transcript_turn` | Trace / QA / billing attribution divergence under concurrency. |
| AF-17 | P3 | HIGH | `DATA_MODEL.md` still says AuthN/Z is deferred; `authz.py` is live. | `DATA_MODEL.md:303`; `authz.py`; `main.py` lifespan | Operators reading the data model will under-estimate current controls. |
| AF-18 | P3 | HIGH | Two of four “locked engines” are worker/post-turn hooks, not mouth tools. | `cards/schema.py:58–67`; characterization tests | Authors may believe the model can/must call treatment and live QA as tools. |

---

## 6. Detailed Findings

### AF-01 — Deferred data-plane hardening is the production last line of defence

**Severity:** P0  
**Confidence:** HIGH  
**Category:** Security boundary / data-loss (cross-tenant) / configuration discipline  
**Location:** `backend/main.py:388–418` (`_DEFERRED_HARDENING_CONTROLS`, `_assert_hardening_gate`); `backend/DATA_MODEL.md:298–304`; `backend/rls.py:1–29,417+`; `backend/tenant_context.py:1–13`

**Evidence:**

```388:418:backend/main.py
_DEFERRED_HARDENING_CONTROLS = (
    "RLS tenant isolation",
    "PII column encryption / Vault secret refs",
    "append-only enforcement on audit tables",
)
...
    if ack in {"1", "true", "yes", "on"}:
        logger.error(
            "Booting with APP_ENV=production while deferred controls are still "
            "inactive ... ALLOW_UNHARDENED_PRODUCTION is set. This deployment "
            "must not receive real customer data.",
        )
        return
    raise RuntimeError(...)
```

`rls.py` states the application currently connects as a role that **BYPASSRLS**, so enabling policies as that role “changes nothing at all while looking like it worked.” Tests (`tests/test_rls.py`) are opt-in via `RLS_DATABASE_URL`. Python `_assert_tenant_owns` / `_tenant()` predicates are the live isolation.

**Observed behavior:** Production without the ACK flag refuses to boot (good). Production *with* the ACK flag runs a full CRM against Postgres with owner/BYPASSRLS, unencrypted PII columns, and no trigger/revoke enforcement that audit tables are append-only.

**Why this matters:** In a collections system, a forgotten `tenant_id` predicate is not a 500. It is another bank’s borrowers, promises, and transcripts on a 200. The gate is honest; the architecture still has a single-process tenant model plus a flag that turns the honesty off.

**Dependencies / blast radius:** Every `db.py` query, every worker (`api`, `worker`, `bot_worker`, `voice`), exports, MCP reads, webhook payloads.

**Recommended action:** Treat `ALLOW_UNHARDENED_PRODUCTION=1` as incompatible with real customer data. Enable RLS with a non-BYPASSRLS app role (`rls.enable`), vault/column encryption as modeled, and append-only grants on audit tables. Then **remove the gate, not the flag**, as `DATA_MODEL.md` already specifies.

**Verification required:** Staging enablement of `rls.enable` against a copy of prod-shaped data; confirm `status()` reports non-BYPASSRLS; chaos test a deliberately unscoped query returns zero rows; confirm boot without ACK still fails.

---

### AF-02 — Cardless mouths fail-open (ADR-0002 accepted, not implemented)

**Severity:** P1  
**Confidence:** HIGH  
**Category:** ADR drift / fail-open / Tool Grant  
**Location:** `backend/agent_core/tools/grant.py:26–31`; `backend/agent_core/skills/runtime.py:127–145,182–185,216–224`; `backend/bot_runtime.py:947–951`; `backend/bot_tools.py:159–162,831–833`; `backend/voice/bot.py:1132–1154`; `backend/voice/tools.py:2911–2914`

**Evidence:**

`grant.py` documents deny-all for cardless mouths and states **“Nothing imports this yet.”** Production `rg` of `from agent_core.tools.grant` hits **only** `tests/test_tool_grant.py` and `tests/test_tool_grant_characterization.py`.

`ToolState.has_grant` interprets `allowed is None` as *no filtering*. `MouthTurn.tools()` returns that sentinel when `card is None`. Unparseable authored JSON takes the same path (`runtime.py:221–224`: “Reported as ungated, same as an absent card”).

Text: `bot_runtime.py` uses `bot_tools.TOOL_DEFINITIONS` when `not tool_state.has_grant`.  
Voice: `build_tools` applies the allow-set only `if allowed_tool_names is not None`; otherwise the **entire** registry remains.  
Sandbox: documented fallback `_SANDBOX_TOOL_NAMES` (inspector).

**Observed behavior:** A missing or unparseable Agent Card does not deny tools. It disables the filter. Characterization tests pin that the fallback list includes skill-gated writes such as `create_promise_to_pay`.

**Why this matters:** ADR-0002 exists because a previous sentinel inverted: empty packs + DB fault looked like “legacy allow everything.” The sentinel is still in production. The deny-all *module* is waiting beside it.

**Dependencies / blast radius:** WhatsApp deployments without a published card; corrupt `agentCard` JSON; voice sessions whose bundle has `{}`; sandbox rehearsals that mis-teach authors what production will allow.

**Recommended action:** Flip the sentinel last, as the module already plans (#14 in tests): cardless → empty grant; delete `TOOL_DEFINITIONS` / `_SANDBOX_TOOL_NAMES` fallbacks; treat voice `None` as empty + `ALWAYS_ON` floor *inside* `ToolGrant`, not as unfiltered registry.

**Verification required:** Integration: `{}` card on text, voice, sandbox → zero write tools offered and `execute_tool` / voice handler deny. Existing authored-card suites must stay green. Confirm no remaining `allowed is None` meaning “ungated.”

---

### AF-03 — Handoff does not refresh the Tool Grant

**Severity:** P1  
**Confidence:** HIGH  
**Category:** ADR drift / missing capability / permission bleed  
**Location:** ADR-0001 lines 17–19; `backend/voice/bot.py:1132–1156`; `backend/voice/tools.py` (`handoff_to_agent`, `build_tools` ~2911); `backend/bot_runtime.py:45–46,712–717`; `backend/bot_tools.py:165–169`

**Evidence:** ADR-0001: the voice runtime “filters its tool registry once at session start and would keep the handing-off agent's tools after the transfer.” That sentence still matches the code: `_mouth.tools()` and `build_collections_flow(..., allowed_tool_names=_allowed_tools)` run at session build. The handoff handler updates mesh/DB; it does not rebuild Pipecat functions from the receiving card.

Text: `load_active_bundle(..., bot_id=_bot_id())` where `_bot_id()` is `os.getenv("BOT_ID")`. Handoff may set `ctx.bot_id` and `ctx.agent_card` for the *allowlist*, but the next turn’s bundle/grant still comes from the process env bot.

**Observed behavior:** After `handoff_to_agent`, the call/chat continues under the source mouth’s grant (voice) or source deployment bundle (text). CONTEXT.md says the receiving agent “brings its own card, and therefore its own grant.” Runtime does not.

**Why this matters:** Handoff is the moment the grant *must* change. Leaving the source grant in place is the opposite of the ADR prerequisite.

**Dependencies / blast radius:** Multi-agent voice graphs; WhatsApp clone-card fleets; any write tool on the source card that the target card locked out (or vice versa: target tools never appear).

**Recommended action:** On successful handoff: resolve receiving `bot_deployments` row, `ToolGrant.for_bundle`, rebuild voice registry / text `allowed_tools` + prompt. Resolve text bundle from `interactions.handler_bot_id`, not `BOT_ID`.

**Verification required:** Extend `tests/test_handoff_to_agent.py`: narrow source → wide target (and reverse) on both channels; assert executable names and system prompt identity after the transfer.

---

### AF-04 — Auth middleware exempt list ≠ authz public routes (Twilio SMS + CBS events)

**Severity:** P1  
**Confidence:** HIGH  
**Category:** Configuration discipline / operational availability (not an auth bypass)  
**Location:** `backend/main.py:233–257` (`_AUTH_EXEMPT_PREFIXES`); `backend/authz.py:213–247` (`PUBLIC_ROUTES`); handlers `main.py:3669` (`POST /twilio/sms/status`), `main.py:857` (`POST /webhooks/collections/payment-events`)

**Evidence:** `PUBLIC_ROUTES` includes both POSTs and comments that Twilio SMS receipts carry no API key — “the signature check inside the handler is the authentication.” `_AUTH_EXEMPT_PREFIXES` lists WhatsApp, Twilio *voice* callbacks, `/pay`, `/webhooks/payments`, `/ws` — **not** `/twilio/sms/status` or `/webhooks/collections/payment-events`. `ApiKeyMiddleware` runs first. When `API_KEY` is set, those POSTs 401 before HMAC.

Voice Twilio paths *are* exempt and have a hardening test (`test_production_hardening.py` documents the outbound-not-exempt lesson). SMS/CBS do not share that exempt entry.

**Observed behavior:** Keyed deployments (including every `APP_ENV=production` boot that passed AUTH-002) reject provider callbacks that authz already classified as public.

**Why this matters:** SMS delivery receipts feed reachability; CBS payment-events feed bounce cases and statutory pay-links. Silent 401s look like “Twilio never called us.”

**Dependencies / blast radius:** `twilio_sms.py` status callback URL; `payment_events.ingest`; `bot_worker` bounce follow-up; operator dashboards that assume receipts exist.

**Recommended action:** Add both prefixes to `_AUTH_EXEMPT_PREFIXES` in the same style as other signature webhooks. Add a test next to the existing Twilio voice exempt assertions. Do **not** exempt `/twilio/voice/outbound`.

**Verification required:** With `API_KEY` set, POST both paths with valid signatures → handler 2xx; invalid signatures → 4xx from the handler, not 401 from middleware. Confirm `/twilio/voice/outbound` still requires the key.

---

### AF-05 — Live Customer 360 still derives offer / NBA in the browser

**Severity:** P1  
**Confidence:** HIGH  
**Category:** Duplicate business capability (E) / duplicate state (G) / single source of truth  
**Location:** `Habibi/src/api/customers.ts:45–58`; `Habibi/src/routes/customers.$customerId.lazy.tsx:114`; `Habibi/src/lib/customerInsights.ts:196–220`

**Evidence:**

```45:58:Habibi/src/api/customers.ts
  try {
    return await apiGet<CustomerInsights>(`/customers/${id}/insights`);
  } catch (err) {
    console.error(`[insights] /customers/${id}/insights failed, deriving offline`, err);
    ...
    return deriveCustomerInsights(c);
  }
```

```114:114:Habibi/src/routes/customers.$customerId.lazy.tsx
  const insights = insightsQuery.data ?? deriveCustomerInsights(customer);
```

`mockOfferPolicy` invents DND suppression or a ₹1,50,000 top-up from interaction flags — it is not the Python reco engine.

**Observed behavior:** Two live-mode paths feed client derivation:

1. **Loading:** `useQuery().data` is `undefined` until the request returns, so the page **always** paints `deriveCustomerInsights` first.
2. **Error:** 500, validation error, and offline are indistinguishable; all three call the same mock policy.

Customer 360 *authority* was already moved to `GET /authority/next` (cycle 7). Insights/offer were not given the same honesty.

**Why this matters:** CONTEXT.md: the model proposes, locked engines dispose. A UI that composes NBA/offer locally after a 500 (or during load) teaches operators a policy the engine did not emit.

**Dependencies / blast radius:** Overview tab, offer blocks, upsell capture, any component reading `insights.offerPolicy` / NBA.

**Recommended action:** While pending/error, show an explicit pending/unavailable state (the Authority panel already has this pattern). Never call `deriveCustomerInsights` when `!USE_MOCK`. Keep the function mock-only.

**Verification required:** `VITE_USE_MOCK=false`; throttle `/customers/:id/insights`; confirm UI does not flash a fabricated top-up. Force 500; confirm error chrome, not engine-looking copy.

---

### AF-06 — Seven live Tool Grant formulas; canonical owner unwired

**Severity:** P2  
**Confidence:** HIGH  
**Category:** ADR drift / duplicate capability (A–J)  
**Location:** `backend/agent_core/tools/grant.py`; `backend/tests/test_tool_grant_characterization.py:13–21`; `agent_core/skills/intersect.py`; `agent_core/cards/compile.py` G9; `bot_tools.TOOL_DEFINITIONS`; `voice.tools.ALWAYS_ON`; `sandbox_runtime._SANDBOX_TOOL_NAMES`; `flow_graph._FLOW_CONTROL_TOOLS`

**Evidence:** `grant.py:30–31`: “Nothing imports this yet. It is added beside the seven formulas so they can be migrated one at a time.” Characterization tests enumerate formulas A–G (intersect grant/offer, publish G9, text fallback, voice always-on, sandbox fallback) plus authoring flow-control and compile wrappers.

G9 publish scope is `include | locked | platform` and is tested as **omitting connectors** and **omitting the always-on floor** — the exact class of bug ADR-0001 records.

Voice still unions after the grant: `keep = set(allowed_tool_names) | ALWAYS_ON` (`voice/tools.py:2911–2913`). ADR-0001 forbids callers widening a returned set.

Text `load_skill` correctly widens **offer only** (`bot_runtime.py` ~1033–1038) — that part of ADR-0001 is implemented on WhatsApp.

**Observed behavior:** Publish can fail a pack the runtime would run (`ext.*`). Runtime can keep tools G9 never saw. Channels disagree about cardless. `ToolGrant.may_execute` is unused on the voice handler wrapper (registry filter only).

**Why this matters:** Six formulas already drifted once. The seventh (the intended owner) cannot prevent an eighth until callers go through it.

**Dependencies / blast radius:** Studio publish, connector tools, voice/text/sandbox permission surfaces, future handoff (AF-03).

**Recommended action:** Follow the sequence already in tests: wire `for_bundle` / `may_execute`; fold the floor into the grant module; replace G9 with `static_grant`; then delete characterization tests with the old formulas.

**Verification required:** `rg "from agent_core.tools.grant" backend --glob "!tests/**"` is empty today and must become non-empty per runtime. Keep `test_tool_grant.py` as the permanent ADR pin.

**Duplication class:** J (intended owner) vs A–I (live formulas). Not “copy-paste unused code” — they are competing control planes.

---

### AF-07 — Consent contactability is a live client policy, not the contact-policy engine

**Severity:** P2  
**Confidence:** HIGH  
**Category:** Duplicate business capability (E) / duplicate validation (H)  
**Location:** `Habibi/src/components/consent/ContactablePill.tsx:1–18`; `Habibi/src/data/consent-seed.ts:350–416`; contrast `Habibi/src/components/customer360/ContactabilityPill.tsx` → `useContactPolicy` → `GET /customers/:id/contact-policy`

**Evidence:** `ContactablePill` always calls `contactableSummary(record)`. `isWithinAllowedWindow` uses `at.getDay()` / `at.getHours()` on the default `new Date()` — **agent browser timezone**, inclusive of whatever DST/offset the operator laptop has. It does not call RBI 08:00–19:00 statutory logic in `contact_policy.py`. Customer 360 was migrated off this pattern (cycle 3); Consent was not.

**Observed behavior:** Consent registry pills can be green while the dialler and 360 pill veto (or the reverse) for the same borrower.

**Why this matters:** Contactability is a compliance display. Two verdicts train operators to distrust one of them — usually the honest backend.

**Dependencies / blast radius:** `/consent` board, filters that use `status === "contactable"`.

**Recommended action:** Drive the pill from `fetchContactPolicy` (or a server field on `GET /consent`). Keep `isContactableNow` as mock-only, with the same documented gaps as `contact-policy.ts` mock (caps).

**Verification required:** Same customer at 19:00 IST Sunday: Consent pill vs 360 pill vs JSON from `/contact-policy`. Compare DND and opted-out channel.

---

### AF-08 — `db.py` and `main.py` are god modules

**Severity:** P2  
**Confidence:** HIGH  
**Category:** Module ownership / cohesion / incremental migration  
**Location:** `backend/db.py` (691.9 KB, 16,583 non-blank lines); `backend/main.py` (100 HTTP handlers, **zero** `include_router`)

**Evidence:** `main.py` grep for `include_router` returns no matches. Voice is the exception that proves the pattern: `voice.host.register_routes(app)` (`main.py` ~667–672). Everything else — customers, billing, sandbox, Twilio, treatment, WhatsApp ingest — is inline.

`db.py` owns connection pooling, tenant helpers, customer/interaction/promise/dispute/bot-config/billing/WhatsApp ingest, and calls into policy engines. `voice/persist.py` exists specifically to keep voice writes off this mutation surface; transcript still splits with `capture.py` (AF-16).

**Observed behavior:** A one-line serializer change (historical dispute SLA) touches a 16k-line module. Route authz must be updated in a second 800-line registry. Reviewers cannot load a bounded diff.

**Why this matters:** This is not “the file is large so rewrite the app.” It is the primary maintainability risk for a codebase that otherwise has good tests. Every new screen currently has nowhere smaller to land.

**Dependencies / blast radius:** Entire CRM API and most tests that import `db` / `main.app`.

**Recommended action (incremental, not a rewrite):**

1. Extract routers: `routers/customers.py`, `twilio.py`, `sandbox.py`, `treatment.py`, `billing.py` — keep lifespan, middleware, and hardening in `main.py`.
2. Split `db.py` by write cluster first (`interactions`, `collections`, `bot_config`), shared `engine`.
3. Stop adding new endpoint bodies to `main.py` (precedent: `ops_screens.py`, `sandbox_runtime.py`).

**Verification required:** After any extract: `test_authz.py::test_registry_covers_every_route`; import-cycle tests; targeted route tests. Do not extract and rename in the same change.

---

### AF-09 — Dependency direction leak: core and WhatsApp import `voice`

**Severity:** P2  
**Confidence:** HIGH  
**Category:** Dependency direction / layering  
**Location:** `backend/agent_core/live_qa/enact.py` (lazy `from voice import twilio_ops`); `backend/bot_runtime.py` (~1271, `from voice import persist as voice_persist`)

**Evidence:** Voice → `agent_core` is the intended direction and is heavy (`voice/bot.py`, `voice/tools.py`, `voice/persist.py`). The reverse exists for barge (Twilio ops) and for WhatsApp live-QA flagging (`evaluate_and_flag_bot_turn` living on the voice persist module).

**Observed behavior:** Text-channel turns cannot evaluate live QA without importing the voice package. Core policy enactment cannot barge without a voice transport import.

**Why this matters:** Tests, packaging, and a future “text-only” deploy all drag Pipecat/Twilio. A bugfix in voice persist becomes a WhatsApp behavior change.

**Dependencies / blast radius:** `bot_runtime` live QA, Floor barge, any split of the voice extra (`requirements-voice.txt`).

**Recommended action:** Introduce a small transport/persist protocol in `agent_core` (or `capture.py`); register Twilio and voice-persist implementations at process start. Do not merge Pipecat session state into that protocol.

**Verification required:** WhatsApp turn with `voice` import blocked in a unit test still records live-QA decisions (after the split). Barge still enacts on Twilio.

---

### AF-10 — Export path skips transcript redaction

**Severity:** P2  
**Confidence:** HIGH  
**Category:** PII / security boundary  
**Location:** `backend/voice/persist.py` (`append_transcript_turn` redacts via `pii_redact.redact_text`); `backend/voice/call_export.py` (`build_bundle` exports `interaction_transcript.text`, retrieval queries, tool args); `backend/main.py:1030–1063` (`GET /interactions/{id}/export`); authz `INTERACTIONS_READ`

**Evidence:** Persist path redacts on write (cycle 28). Export reads stored columns and does not run `pii_redact`. Raw-PII viewing is a separate redaction-review concern (`_actor_can_view_raw_pii`), not applied to this export.

**Observed behavior:** An actor who can read interactions can download a call bundle containing whatever survived at rest (including pre-redaction historical rows, retrieval queries, tool previews).

**Why this matters:** Write-path redaction is necessary and insufficient if the operator export is a second, unredacted channel.

**Dependencies / blast radius:** Sandbox export UI (`sandbox.lazy.tsx`), compliance investigations, any script hitting `/export`.

**Recommended action:** Apply `pii_redact` on export unless the actor has an explicit raw-export permission. Do not overload `INTERACTIONS_READ`.

**Verification required:** Fixture with PAN/phone in transcript and retrieval query; export JSON must not contain raw digits unless the raw flag + role are present.

---

### AF-11 — Dual schema sources are managed, not accidental — reverse drift is still P2

**Severity:** P2  
**Confidence:** HIGH  
**Category:** Single source of truth / operational simplicity  
**Location:** `backend/sql/*.sql` (25 files); `backend/alembic/versions/` (102); `backend/DATA_MODEL.md:3`; `backend/tests/test_schema_parity.py`; CI comments in backend pytest workflow

**Evidence:** Fresh install applies SQL then stamps Alembic head (baseline revision is a no-op). Parity tests compare both directions when `SCHEMA_PARITY_DATABASE_URL` is set. Docs tell authors to edit **both** on every new column.

**Observed behavior:** This is a disciplined dual-write, not two competing ORMs. The dangerous direction is: column added to `sql/` and used by new Python, no Alembic revision, existing prod never sees it.

**Why this matters:** Silent INSERT/SELECT failures on upgraded code against old databases. Not a reason to generate SQL from migrations in this audit’s horizon — it is a reason to keep the parity job mandatory in CI.

**Dependencies / blast radius:** Every deploy that is not a from-scratch SQL apply.

**Recommended action:** Keep dual-write. Make schema parity non-optional in CI. Do not start a “migrations-only rewrite” until the god-module split lands.

**Verification required:** CI log shows parity job not skipped; a deliberate sql-only column fails CI.

---

### AF-12 — A2A mTLS trust is header-based

**Severity:** P2  
**Confidence:** HIGH (code) / MEDIUM (exploitability — depends on ingress)  
**Category:** Security boundary  
**Location:** `backend/main.py` (`POST /a2a` in `_AUTH_EXEMPT_PREFIXES` / `PUBLIC_ROUTES`); `backend/agent_core/a2a.py` (`require_partner` reads `X-SSL-Client-Verify` / `X-SSL-Client-DN`)

**Evidence:** API-key middleware skips `/a2a`. Partner identity is the proxy’s client-certificate headers. If the app is reachable without a terminator that **strips** client-supplied copies of those headers, they are spoofable.

**Observed behavior:** Correct behind a well-configured ingress. Unsafe on a raw port publish (`API_BIND=0.0.0.0` without mTLS).

**Why this matters:** Partner task creation is an unauthenticated CRM write from the API-key world’s point of view.

**Dependencies / blast radius:** A2A-enabled deployments only.

**Recommended action:** Document that A2A must sit behind stripping mTLS; disable the route if unused; never trust those headers on a public bind.

**Verification required:** Direct POST with forged DN vs POST through ingress that overwrites headers. Confirm default compose bind is loopback (`docker-compose.yml` `API_BIND` default `127.0.0.1`).

---

### AF-13 — Frontend API key is a public capability token

**Severity:** P2  
**Confidence:** HIGH  
**Category:** Security / configuration  
**Location:** `Habibi/src/api/config.ts:11–54`; `backend/actor_context.py` (`ALLOW_ACTOR_HEADER` defaults on in non-prod); `backend/main.py:431–433`

**Evidence:** `VITE_API_KEY` and `VITE_ACTOR_USER_ID` are compile-time env. Vite inlines them into JS. Every `apiGet`/`apiPost` sends `X-API-Key` and optional `X-Actor-User-Id`. Production backend refuses to boot without `API_KEY` or `API_KEY_MAP`. Production actor header defaults **off**.

**Observed behavior:** Anyone who can download the SPA can extract the shared key. That is acceptable only if the key is treated as a **capability** (and preferably mapped per user via `API_KEY_MAP`), not as a confidential secret. Non-prod impersonation is intentional.

**Why this matters:** Shared prod key + accidentally enabled `ALLOW_ACTOR_HEADER` = any user id. `DATA_MODEL.md` still says OIDC is future work; until then this *is* AuthN.

**Dependencies / blast radius:** All CRM routes in keyed deployments; audit attribution.

**Recommended action:** Production: `API_KEY_MAP` per operator, `ALLOW_ACTOR_HEADER` unset, no `VITE_ACTOR_USER_ID` in the prod build. Plan OIDC as modeled. Do not treat `VITE_API_KEY` as a vault secret.

**Verification required:** Prod bundle grep for key material; confirm header impersonation 401s in `APP_ENV=production`.

---

### AF-14 — Orphan connector seed and CLI-only voice catalog sync

**Severity:** P3  
**Confidence:** HIGH  
**Category:** Dead / duplicate seed capability  
**Location:** `backend/agent_core/connectors/persist.py:405–421` (`seed_first_party`); `backend/provider_voice_sync.py` (`__main__` only); contrast `seed_postgres.py` connector inserts; `main.py` TTS sync via `tts_catalog_sync`

**Evidence:** `seed_first_party()` upserts `paylink` / `lms` connectors. Repo-wide callers: **none**. Runtime startup uses `ensure_first_party_skills()` for packs, not this function. `provider_voice_sync.py` is not imported by `main.py` or `worker.py`.

**Observed behavior:** Demo seed can still create connectors. A migrate-only database that never runs `seed_postgres` may lack first-party connector rows. Non-Azure TTS catalogs do not refresh on the API “sync catalog” path.

**Why this matters:** Not safe to delete without proving migrate-only deploys. Not safe to assume production voice catalogs stay current for Cartesia/ElevenLabs/etc.

**Dependencies / blast radius:** `ext.paylink.*` / `ext.lms.*` tools; TTS picker in Agent Studio.

**Recommended action:** Either call `seed_first_party` from the same startup path as `ensure_first_party_skills`, or delete it after proving `seed_postgres` / migrations cover the rows. Document `provider_voice_sync` as manual or wire it into the existing catalog-sync route.

**Verification required:** Fresh `alembic upgrade` without seed → query `mcp_connectors`. Trace `POST /tts-voices/catalog/sync` and list which providers actually update.

---

### AF-15 — Triple always-on / flow-control tool lists

**Severity:** P3  
**Confidence:** HIGH  
**Category:** Duplicate capability (F/H/J) — pin-tested  
**Location:** `backend/voice/tools.py:80–94` (`ALWAYS_ON`); `backend/agent_core/tools/grant.py` (`VOICE_ALWAYS`); `backend/flow_graph.py:773–784` (`_FLOW_CONTROL_TOOLS`); `backend/tests/test_tool_grant.py:121–167`

**Evidence:** Comments in `ALWAYS_ON` and `grant.py` admit three copies, held together by tests. `_FLOW_CONTROL_TOOLS` is a shorter set (omits at least `capture_call_goal` relative to `ALWAYS_ON`).

**Observed behavior:** Authoring catalog and runtime keep-set can differ; tests fail if they drift too far, which is why this is P3 not P1.

**Why this matters:** The next person who adds a flow-control verb will update one list.

**Recommended action:** Single frozenset in `grant.py` (or catalog), imported by voice and `flow_graph`. Delete the pin test’s “three copies” section when only one remains.

**Verification required:** Existing pin tests stay green during consolidation.

---

### AF-16 — Parallel transcript writers

**Severity:** P3  
**Confidence:** HIGH  
**Category:** Duplicate state management (G) / structural duplication (C)  
**Location:** `backend/voice/persist.py` `append_transcript_turn` (explicit `turn_index`, PII redaction); `backend/capture.py` `insert_transcript_turn` (MAX+1 allocation, used from `bot_runtime.py`)

**Evidence:** Both write `interaction_transcript`. Voice pre-assigns indices in session state; WhatsApp allocates in SQL with retry. Redaction is on the voice persist path; capture’s contract is a different column/index story.

**Observed behavior:** Same table, two allocators, two redaction stories.

**Why this matters:** Concurrent writers, QA scorecards, and billing attribution share this table. A third writer will guess which function to call.

**Recommended action:** Make `capture.insert_transcript_turn` the single writer; voice persist delegates, passing voice-only columns as optional kwargs. Keep redaction in one function.

**Verification required:** `tests/test_voice_verify_reentry_and_transcript_pii.py` plus WhatsApp transcript tests; concurrent insert race.

---

### AF-17 — Data-model doc drift: AuthN/Z described as deferred

**Severity:** P3  
**Confidence:** HIGH  
**Category:** Documentation vs code  
**Location:** `backend/DATA_MODEL.md:298–304`; `backend/authz.py` (module docstring and `assert_registry_covers`); `backend/main.py` lifespan `authz.ensure_permission_catalog`; `backend/tests/test_authz.py`

**Evidence:** DATA_MODEL: “AuthN/Z (OIDC/Keycloak) — RBAC tables exist now; enforcement is added later.” `authz.py` implements a total per-route registry, fail-closed unregistered routes, and DB-backed grants with role-name defaults. Enforcement follows the same switch as API keys. OIDC is still absent — that half of the sentence is true.

**Observed behavior:** A reader of the data model will miss that keyed deployments already 403 on missing permissions.

**Why this matters:** Operators and future audits will under-specify the current control plane.

**Recommended action:** Update the “Scope of this build pass” bullet to: API-key + route registry live; OIDC still deferred. Do not weaken tests to match the old sentence.

**Verification required:** Doc review only.

---

### AF-18 — Locked engines on the card are not all mouth tools

**Severity:** P3  
**Confidence:** HIGH  
**Category:** Explicit contracts / authoring confusion  
**Location:** `backend/agent_core/cards/schema.py:58–67`; `backend/agent_core/cards/defaults.py`; `tests/test_tool_grant.py` (locked engines survive pack removal); invocation sites in `bot_worker.py` / `voice/persist.py` vs `bot_tools.py` / `voice/tools.py`

**Evidence:** `LOCKED_POLICY_ENGINES` = `recommend_next_offer`, `recommend_treatment`, `evaluate_authority`, `evaluate_live_qa`. `LOCKED_MOUTH_TOOLS` is only the first and third. Treatment runs on workers / `/treatment/next`. Live QA runs post-turn. Contact policy is **not** a locked engine — it is a dial/send gate (`contact_policy.py`), which is the correct separation.

**Observed behavior:** Cards claim four unbindable engines. The model can only call two of them as tools. Characterization tests already note treatment/live QA are not in the mouth catalog.

**Why this matters:** Authors may remove a skill expecting treatment to stop, or expect the model to `recommend_treatment` mid-call.

**Recommended action:** Document policy-binding vs mouth-tool in the card schema / studio UI. Optional compile warning when a locked name has neither a catalog spec nor a registered hook.

**Verification required:** Studio publish UX; `test_tool_grant.py` locked-engine invariants remain.

---

## 7. Positive Findings

These are observed facts, not recommendations.

1. **Tool catalog + domain handlers** (`agent_core/tools/catalog.py`, `domain.py`) — one wire contract for voice, text, and MCP. Channel modules are adapters, not second CRMs.
2. **ADR-quality characterization tests** (`test_tool_grant.py`, `test_tool_grant_characterization.py`) — the migration is specified before it is wired. Rare and valuable.
3. **Authz registry totality** (`authz.py`, `test_registry_covers_every_route`) — unregistered routes deny when enforcement is on. Policy is a table, not 180 scattered `Depends`.
4. **Production boot gates** — no API key in `APP_ENV=production` refuses to start; mock UI cannot ship; hardening controls are named rather than silently absent.
5. **`USE_MOCK` discipline** — production throws; billing/trace/cost refuse to invent numbers; offer-health documents that thresholds are server-side.
6. **Contact policy on Customer 360** — server verdict, borrower timezone, RBI window (cycle 3 completed).
7. **Authority on Customer 360** — `GET /authority/next` is live; client matrix deleted (cycle 7).
8. **Webhook SSRF + HMAC** — `webhooks_dispatch.resolve_public_host`, no redirect follow, secret stored as hash, plaintext shown once.
9. **Skill packs fail closed on DB outage** (`skills/runtime.py:83–91`) — contrary to an older ops note.
10. **Paylink tenant hygiene** — `first_party.py` filters `tenant_id`; regression in `test_connector_read_hygiene.py`. Historical bypass via `bot_tools` is gone (dispatch through registry).
11. **Off-audio `CrmSink`** — voice latency isolation is a real architectural boundary.
12. **`work_items` as a VIEW** — queue is a projection; domain tables remain source of truth (`DATA_MODEL.md` principle 11, implemented).
13. **Compose connection budget and loopback bind** — documented pool math; API not published on `0.0.0.0` by default.
14. **Prompt CRM token stripping** — untrusted CRM card cannot inject unrendered tokens (`prompt_render`).
15. **Handoff *allowlist* fail-closed** (distinct from AF-03 grant refresh) — empty set, not `None`.

---

## 8. False Positives / Ambiguous Findings

Do **not** treat these as deletion or “broken fail-open” tickets without the verification named here.

| Item | Why it looks bad | Why it should not be changed immediately |
|------|------------------|------------------------------------------|
| No API key → public CRM | Open by default | **Intentional local/demo.** Same switch as authz. Production boot fails without keys. |
| Non-prod voice WebSocket / Twilio signature lax | Unauthenticated media | **Intentional** for ngrok/dev. Prod WS fail-closed without `VOICE_WS_PROXY_SECRET`. |
| `assert_registry_covers` not in lifespan | New routes could ship | Runtime **denies** unregistered routes when keys exist. CI test is the compile-time gate. Adding startup assert is optional hardening, not a defect. |
| `voice/spike.py` “unused” | 300+ LOC, no prod import | **CLI diagnostic** (`python -m voice.spike`). `latency.py` *is* used by `voice/bot.py`. |
| `skills/runtime.py` “DB-fail fallback to disk” | Historical ops note | **Fail-closed** on exception (`return []`). Disk unsigned packs only when DB succeeds with empty packs. |
| `intersect.py` “bare except strips tools” | Historical ops note | `except Exception as exc` logs and records compile issues — not silent strip-without-trace. |
| Paylink “bypasses approval” | Historical ops note | `bot_tools.py:177–187` goes through `connectors.persist.dispatch`. |
| `seed_first_party` vs “delete connectors” | Zero callers | **Do not delete** until migrate-only deploys are proven to have rows (AF-14). |
| Package `__init__.py` with zero importers | AST orphans | Lazy imports of submodules (`agent_core.skills.runtime` from `bot_runtime`). |
| `rls.py` not imported by `main.py` | Looks dead | **Ops/enablement module**; enabling from the API process as BYPASSRLS would be the bug `rls.py` exists to prevent. |
| `GET /health`, `/metrics`, `/pay/{token}` unused by Habibi | Orphan routes | **By design** (probes, Prometheus, borrower browser). |
| MCP `DENIED` frozenset vs Tool Grant | Third formula | **Intentional separate boundary** — read-only external surface, no verification ceremony. |
| Locked treatment/live QA not in CATALOG | “Dead locked tools” | **Policy bindings** (AF-18), not unused strings. |
| Dual `foo.tsx` / `foo.lazy.tsx` | Duplicated routes | TanStack code-split convention; editor is shared via re-export. `/prompt-studio` redirect is the only weak extra. |
| `billing.ts` / `flow.ts` have no mock | Broken offline UI | **Intentional honesty** (no fake spend / fake graphs). Add a hard-error banner, not a mock ledger. |
| Python tenant predicates without RLS | “RLS is missing so Python is wrong” | Python predicates are the **current** isolation. RLS is defence in depth (AF-01), not a replacement to land by deleting `_tenant()`. |
| `DATA_MODEL.md` “X-Tenant unifies tenants” | Implies request switching | Inbound tenant switching **does not exist**. Seed uses `X-Tenant` as an *outbound webhook* header. |

---

## 9. Prioritized Recommendations

Nothing below was implemented in this audit.

### Immediate (correctness / safety on the current architecture)

1. **Do not put real borrower data** behind `ALLOW_UNHARDENED_PRODUCTION=1` (AF-01).
2. Add `/twilio/sms/status` and `/webhooks/collections/payment-events` to `_AUTH_EXEMPT_PREFIXES` (AF-04).
3. Stop live `deriveCustomerInsights` / `insightsQuery.data ?? derive…` (AF-05). Reuse Authority’s pending/unavailable states.
4. Plan the ADR-0002 deny-all flip as a dedicated change, last in the grant sequence already documented in tests (AF-02). Until then, treat unauthored cards as an incident, not a feature.

### Near-term (this quarter’s architecture)

1. Wire production runtimes to `ToolGrant` (AF-06); then refresh grant on handoff (AF-03).
2. Consent pill → server contact policy (AF-07).
3. Extract 3–5 FastAPI routers and the first `db.py` write cluster (AF-08). Stop growing `main.py`.
4. Move WhatsApp live-QA and barge off `voice.*` imports (AF-09).
5. Redact exports (AF-10). Production: `API_KEY_MAP`, no actor header, no `VITE_ACTOR_USER_ID` (AF-13).
6. Keep schema parity **mandatory** in CI (AF-11).
7. Fix DATA_MODEL AuthN/Z bullet (AF-17).

### Long-term (without a rewrite)

1. Enable RLS with a non-BYPASSRLS role; vault PII; append-only audit; then delete the hardening gate (AF-01).
2. OIDC as already modeled in RBAC tables — replace shared SPA keys.
3. Optional request-scoped tenant (JWT/host) using the existing `tenant_context` seam — only when multi-tenant-per-process is an actual product requirement. **Do not split microservices for tenancy.**
4. Collapse ALWAYS_ON literals (AF-15); single transcript writer (AF-16).
5. Card schema copy that distinguishes mouth tools vs worker-locked engines (AF-18).
6. Generate one schema source from the other only after `db.py` is split — not before.

**Do not:** rewrite the application; extract microservices; delete “unused” modules from a single static analyzer; use Offer as a safety control; add a seventh grant formula.

---

## 10. Metrics / Baseline

Counts from this session unless noted. Line counts for `db.py`/`main.py` are PowerShell non-blank `Measure-Object -Line`.

| Metric | Value |
|--------|------:|
| Backend Python files (scan) | 582 |
| Backend test modules `test_*.py` | 186 |
| Alembic revisions | 102 |
| Base SQL files | 25 |
| `db.py` size | 691.9 KB / 16,583 non-blank lines |
| `main.py` HTTP route decorators | 100 |
| `main.py` `include_router` | 0 |
| FastAPI WebSocket routes (reported) | 2 |
| `agent_core` Python files | 147 |
| Docker Compose app processes | api, worker, bot_worker, voice (+ db, redis, minio) |
| Habibi `src` TS/TSX files | 474 |
| Habibi `src/api/*.ts` modules | 48 |
| Habibi route files under `src/routes` | 43 |
| Production imports of `ToolGrant` | **0** (2 test files only) |
| Live Tool Grant formulas (characterization) | 7 + authoring copies |
| Locked policy engines on cards | 4 |
| Locked mouth tools in catalog | 2 |
| Auth middleware exempt prefixes (voice host off) | 13 tuples in `_AUTH_EXEMPT_PREFIXES` |
| `PUBLIC_ROUTES` entries including SMS/CBS | includes 2 paths **not** in middleware exempt list |
| Confirmed HIGH-confidence code orphans | `seed_first_party()`, `customer_insights._within_window`, `fetchTuningPresets`, CLI-only `provider_voice_sync` |
| ADRs in `docs/adr/` | 2 (tool grant; cardless deny-all) — both accepted, both partially implemented |
| Default process tenant | `hdfc.retail` |
| Default mock (dev) | ON (`VITE_USE_MOCK` unset) |
| Default mock (prod build) | Impossible (throws) |

**Test posture (from repo, not re-run in this audit):** backend pytest is the system of record (historical loop log: 2700+ passing). This forensics pass did **not** execute the suite (read-only; no env mutation). Treat current pass counts as unverified here.

---

## 11. Final Assessment

Habibi’s architecture is **policy-first on paper and adapter-heavy in production**.

The team has already done the hard conceptual work: one catalog, one domain handler module, locked engines, a total authz table, a mock seam that cannot ship, SSRF/HMAC on webhooks, and tests that describe the grant migration in advance. Those are the marks of a system that can be evolved.

The remaining risk is not “wrong folders.” It is **control planes that exist twice**:

| Intended owner | Live owner |
|----------------|------------|
| `ToolGrant` (`grant.py`) | `MouthTurn.tools()` + per-channel fallbacks |
| ADR-0002 deny-all | `allowed is None` → ungated |
| Handoff brings a new card | Session-start filter / `BOT_ID` env |
| Contact policy engine | Consent page `new Date()`; 360 already migrated |
| Reco / offer engine | Customer 360 `deriveCustomerInsights` on load/error |
| Postgres RLS | Python `_tenant()` + BYPASSRLS role |
| FastAPI routers | 100 handlers in `main.py` |
| Split persistence | 16k-line `db.py` plus a growing `voice/persist.py` / `capture.py` pair |

That pattern is **incremental-migration shaped**. The dangerous move would be a greenfield rewrite that throws away the catalog, the authz registry, and the characterization tests. The productive move is to **delete the extra formulas by pointing callers at the owners that already exist**, close the two live UI policy leaks, and treat the hardening gate as a release constraint.

**Verdict:** Architecturally ambitious, operationally still a modular monolith with two oversized cores (`db.py`, `main.py`) and an accepted-but-unwired permission model. Fit for continued feature work **if** AF-01’s data-plane constraint is respected and AF-02/AF-03/AF-04/AF-05 are scheduled as explicit migrations rather than left as comments in `grant.py`.

---

*End of report. No source files were modified.*
