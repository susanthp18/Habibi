# 10 — Complexity and maintainability smells

**Role:** code quality and maintainability forensics.
**Scope:** `backend/` and `Habibi/src`. Guest tree `PRAXIST-main/` is out of scope.
**Date:** 2026-09-02
**Mode:** read-only. No product code was changed except this file.
**Companions:** `03-frontend-architecture.md`, `04-backend-architecture.md`, `05-dependency-graph.md`, `09-canonical-implementations.md`.
**Vocabulary:** `CONTEXT.md`. Terms in **bold** are that glossary.

Five analysts were spawned (complexity, class/module, function-level, coupling, readability). Claims below were re-checked from the files named. Cyclomatic numbers are branch-keyword proxies (`if`/`elif`/`except`/`for`/`while`/`and`/`or`/`match`/`case`, plus `&&`/`||` in TS), not McCabe AST.

This report does not treat size as a defect. A **Locked Engine** with a small `admit()` / `decide()` / `compile_card()` interface can be a thousand lines and still cheap to change. Complexity is harmful here when a future edit has to hold several unrelated jobs, several vocabularies, or several live formulas for one domain question.

---

## Verdict

The product already knows how to hide complexity. `contact_policy.admit`, `agent_core/authority`, `cadence.on_outcome`, and `compile_card` are deep: callers learn one name, the body holds the hard parts. Maintenance cost is concentrated in **three unnamed magnets** and in **formulas that the magnets never adopted**.

1. **`db.py`** (~18,088 lines, **440** `def`s, fan-in ≥75) is persistence, screen DTOs, **Gate** orchestration, WhatsApp ingest, billing, and Customer 360 in one blame graph.
2. **`main.py`** (5,448 lines, **314** `@app` routes, **zero** `APIRouter`s) is every HTTP resource in one switch.
3. **`voice/tools.build_tools`** (2,605-line factory, ~18 kwargs, ~20 nested handlers) plus **`voice/bot.run_bot`** (2,026 lines) are the voice **Mouth** as two functions.

Frontend mirrors the same shape: `PromptStudioPage` (~1,488 lines) is the whole **Mouth** editor; `treatment.lazy.tsx` (1,506) is Decision Intelligence as one route. Customer 360 and inbox already extracted. These two did not.

There is **no** `*Manager` / `*Service` / `*Handler` class explosion. A name hunt under-reports the problem. The gods are anonymous modules. The speculative layer is small and named: a Temporal adapter that only raises, three `FeatureProvider` Protocols with one SQL adapter each, and `grant.py` — a real **Locked Engine** that **nothing in production imports**.

The highest-cost pattern is always the same as in `09-canonical-implementations.md`: a regulated question has a deep owner, live traffic still uses a second formula, and a change to **Outcome**, channel, consent, or tool is shotgun surgery by construction.

| Lens | Verdict |
|------|---------|
| Size vs depth | Giants that are one job (`compile_card`, `admit`, `authz` registry, seed dumps) are cheap. Giants that mix jobs are not. |
| God modules | `db.py`, `main.py`, `voice/tools.py`, `schemas.py`. `followups_db` / `ops_screens` split the file, not the interface. |
| God functions | `build_tools`, `run_bot`, `PromptStudioPage`, `_handle_turn`, `retrieve`. |
| Coupling | High fan-in on `admit` is healthy. High fan-out from `db.py` is the magnet. `grant.py` fan-in is **0**. |
| Abstraction | Few pass-through wrappers. The unused **Tool Grant** and the Temporal stub are the speculative ones. |
| Readability | Four `Channel` types, **Gate** jammed into `bool \| None`, **Outcome** as string soup outside the closer, INR still `float` beside `money_inr`. |

**Overall:** shippable as a dense collections platform; expensive to extend on money, contact, consent, and tools. Refactor is extraction of already-named engines into the live path, not a rewrite and not a layer of managers.

---

## How complexity was judged

A module is **deep** when a large body sits behind a small interface and deleting it would scatter complexity into N callers (Ousterhout depth-as-leverage, not line-count ratio).

A module is a **god** when it has many unrelated reasons to change (divergent change), or when a reader cannot name one job. Length is evidence only when it comes with mixed jobs, high branch density, or a surface callers cannot hold in their head.

A function is a **god** when flags fork it into several products, when nesting hides the happy path, or when the parameter list is a row that wants a type.

**Not flagged:** `seed_postgres.py`, `Habibi/src/data/*-seed.ts`, `styles.css`, wide Pydantic/TS type catalogs with near-zero branches, sequential **Gate** procedures whose callers only see `CompileReport`.

---

## Method

| Analyst | What it measured |
|---------|------------------|
| Complexity | File LOC, hottest function ranges, branch-keyword density, route/class counts |
| Class/module | Public surface, reasons-to-change, `*Factory`/`*Manager` hunt, deletion test |
| Function-level | Longest defs/components/hooks, flag args, param clumps, nest, switch/if-cascades |
| Coupling | Fan-in/fan-out, ContextVars, process globals, temporal call-order, shotgun scenarios |
| Readability | Primitive obsession, boolean blindness, glossary drift, mixed abstraction |

Parent pass verified: `@app.*` count **314** in `main.py`; **zero** `APIRouter` / `include_router`; **440** `^def ` in `db.py`; `grant.py` imported only by `tests/test_tool_grant.py` and `tests/test_tool_grant_characterization.py`; `run_bot` 297–2322; `build_tools` 310–2914; `PromptStudioPage` starts at 171 in a 1,658-line file.

Full-tree `Get-ChildItem` / grep under `backend/` hangs on `.venv`. Counts were taken on named files.

---

## Metrics

### Backend files (physical lines)

| File | LOC | Surface | Hottest unit | Fan notes |
|------|-----|---------|--------------|-----------|
| `backend/db.py` | ~18,088 | **440** defs, 1 class, **+19** re-exports from `followups_db` | `get_dashboard` ~503; `billing_overview` ~470; `bot_analytics` ~412; `publish_prompt_version` ~338 | Fan-out ~53 internal imports; fan-in ≥75 production modules |
| `backend/main.py` | 5,448 | **314** `@app` routes, **0** routers, 308 defs | `_authz_guard` 507–685 (docstring-heavy); `demo_outbound_call` ~144 | Fan-out ~65; fan-in 1 (process entry) |
| `backend/schemas.py` | 3,454 | ~220–247 `BaseModel`s | types only (low CC) | Every HTTP contract |
| `backend/voice/tools.py` | 2,915 | `ToolState` + `build_tools` closing ~20 handlers | `build_tools` **310–2914 (2,605)** | Voice **Mouth** tool bag; unions `ALWAYS_ON` |
| `backend/voice/bot.py` | 2,623 | 11–13 defs | `run_bot` **297–2322 (2,026)** | Pipeline assembler |
| `backend/voice/crm_sink.py` | 1,661 | `CrmSink` **101–1617 (~1,517)**, ~40 methods | `_handle_sync`, `record_bot_turn` | Transcript, QA, barge-in, memory, escalate |
| `backend/capture.py` | 1,861 | ~40–55 defs | `evaluate_product_eligibility`; `rebind_interaction_customer` | Eligibility + event log |
| `backend/ops_screens.py` | 1,856 | ~37 defs | `get_floor_snapshot` ~375 | Floor + webhooks + provider health |
| `backend/followups_db.py` | 1,614 | ~35 defs, **re-exported as `db.*`** | coaching / redaction / routing / workspace | Split file, same public name |
| `backend/outbound.py` | 1,394 | ~25 defs | `place` ~253 | **Mission** dial; never raises |
| `backend/bot_runtime.py` | 1,293 | ~24 defs | `_handle_turn` **598–1292 (~695)** | WhatsApp/text turn |
| `backend/call_closer.py` | 1,161 | ~25 defs | `close_one` ~180 | **Outcome** + **Cadence** trigger |
| `backend/sandbox_runtime.py` | 1,151 | 8 defs | `append_sandbox_turn` ~469 | Sandbox **Mouth** turn |
| `backend/contact_policy.py` | 1,096 | `evaluate` 533; `admit` 887 | Locked Engine | Fan-out 1; fan-in **16** |
| `backend/agent_core/cards/compile.py` | 980 | `compile_card` 519–954 (~436) | G0–G15 + G-OB | Small interface, sequential **Gates** |
| `backend/authz.py` | 895 | registry + `check` | staff permission table | Totality tested; not **Tool Grant** |
| `backend/agent_core/tools/grant.py` | 248 | `ToolGrant` | ADR-0001 owner | **Fan-in 0** in production |

Branch-keyword file totals (proxy): `db.py` ~1,871; `voice/tools.py` ~460; `voice/bot.py` ~405; `voice/crm_sink.py` ~289; `bot_runtime.py` ~166; `compile.py` ~159.

### Hottest functions

| Function | Location | LOC | Params | CC proxy | Nest | Job a reader can name? |
|----------|----------|-----|--------|----------|------|------------------------|
| `build_tools` | `voice/tools.py:310–2914` | 2,605 | 18 | ~392 | 7 | No — entire voice **Tool Grant** + nested handlers |
| `run_bot` | `voice/bot.py:297–2322` | 2,026 | 2 | ~285 | 4 | No — transport, VAD, Flow, STT/TTS, observers |
| `PromptStudioPage` | `prompt-studio.lazy.tsx:171–1658` | ~1,488 | 3 | ~164 | high | No — prompt, **Flow**, **Agent Card**, **Gate**, **Deployment** |
| `FlowCanvasInner` | `FlowCanvas.tsx:407–1365` | ~959 | 4 | ~51 | high | Graph editor + layout + validation |
| `CrmSink` (class) | `crm_sink.py:101–1617` | ~1,517 | — | ~289 | — | CRM writer for one call — many event kinds |
| `KnowledgeBasePage` | `knowledge-base.lazy.tsx:75–920` | ~846 | 0 | ~97 | ~7 | Docs + FAQs + gaps + purge |
| `build_collections_flow` | `voice/flows.py:108–944` | 837 | 17 | 24 | 1 | Built-in **Flow** constructor (data clump, low density) |
| `_handle_turn` | `bot_runtime.py:598–1292` | 695 | 2 | ~111 | 5 | WhatsApp retrieve + LLM + tools + send |
| `VoicePanel` | `VoicePanel.tsx:170–852` | 683 | 3 | ~71 | ~9 | Catalog + preview + G15 locale |
| `retrieve` | `kb_retrieve.py:493–1088` | 596 | 11 | ~104 | 3 | Three products behind bool flags |
| `useSandboxLiveCall` | `useSandboxLiveCall.ts:111–649` | 539 | 1 object / 8 fields | ~71 | ~7 | WS + mic + insights + metrics |
| `get_dashboard` | `db.py:3195–3697` | ~503 | 3 | ~73 | 3 | One screen, one SQL god |
| `append_sandbox_turn` | `sandbox_runtime.py:662–1130` | 469 | 2 | ~80 | 4 | Preflight → retrieve → LLM → persist |
| `compile_card` | `compile.py:519–954` | 436 | **18** | ~114 | 5 | Sixteen **Gates** — deep *if* the kwargs were a context object |
| `bot_analytics` | `db.py:7222–7633` | 412 | 2 | ~65 | 3 | Aggregation dump |
| `build_authored_flow` | `voice/flows_dynamic.py:127–534` | 408 | **20** | ~64 | 2 | Same 17-arg clump as `build_collections_flow` |

### Frontend files

| File | LOC | Surface |
|------|-----|---------|
| `Habibi/src/styles.css` | 1,849 | tokens — not logic |
| `routes/prompt-studio.lazy.tsx` | 1,658 | `PromptStudioPage` + helpers |
| `routes/treatment.lazy.tsx` | 1,506 | Insights / Models / Cases / Holds tabs in one file |
| `components/flow/FlowCanvas.tsx` | 1,365 | `FlowCanvasInner` ~959 |
| `api/treatment.ts` | 1,202 | type catalog + thin hooks |
| `data/customer360-seed.ts` | 1,181 | seed + types + `fmtMoney` |
| `api/prompt-studio.ts` | 1,141 | fetch + React Query + `_mockVersions` |
| `prompt-studio/OutboundCardEditor.tsx` | 1,126 | **Mission** / **Cadence** panels |
| `api/agent-studio.ts` | 1,104 | ~40 hooks: **Agent Card**, **Skill Pack**, eval, roles |
| `prompt-studio/AgentCardPanels.tsx` | 1,047 | six **Card** concerns |
| `components/flow/FlowInspector.tsx` | 1,004 | form dump, **~12** branch keywords |
| `prompt-studio/VoicePanel.tsx` | 990 | catalog + preview |
| `routes/knowledge-base.lazy.tsx` | 920 | three KB products |

`Habibi/src/api/config.ts` `USE_MOCK` is imported by ~68 modules. Dev default is **true** (`config.ts:21–22`).

---

## Ranked findings

Severity is maintenance cost on money, contact, consent, or tools — not “lines of code.”

### S-01 — `db.py` is the shotgun magnet

**Smell:** god module / divergent change / feature envy.
**Where:** `backend/db.py` entire file; re-export façade at `18005`.
**Numbers:** ~18,088 LOC, 440 defs, ~1,871 branch keywords, fan-out ~53, fan-in ≥75.

Persistence, `_*_screen` serializers, tenant checks, **Handoff** session, **Mouth** publish (`publish_prompt_version` ~14342), **Gate** `compile_card` orchestration, WhatsApp webhook (`process_whatsapp_webhook` nest 7 at ~10886), billing, KB MinIO, treatment/authority screen adapters, and Customer 360 that **calls three Locked Engines and can write a treatment decision on page open** (`get_customer_insights` ~1230).

`ops_screens.py` and `followups_db.py` already exist because the file hurt. Nineteen `followups_db` names are still imported as `db.*`. The split did not create a seam.

**Why it is harmful:** a **Cadence** column on promises, a **Gate** on publish, and a billing forecast all merge-conflict in one file. Reviewers cannot hold 440 names. Changing `publish_prompt_version` requires loading inbox/WhatsApp/QA into working memory. `db` already imports `compile` / contact policy / treatment while owning the same tables — cycle risk, not just size.

**Not the fix:** wrapping `db` in a `DbService`. The extraction that already started (`followups_db`) only works if callers stop importing `db`.

**Severity:** critical. **Confidence:** observed (counts, re-export, mixed names).

---

### S-02 — `main.py` is every HTTP resource

**Smell:** god module / switch explosion.
**Where:** `backend/main.py` `@app.*` from ~754 to end.
**Numbers:** 5,448 LOC, **314** routes, **0** `APIRouter`, ~81 `return db.*` thunks.

Auth middleware, CRM CRUD, Twilio/WhatsApp webhooks, sandbox/voice WS, TTS preview, Agent Studio compile/publish, KB ingest, treatment next, A2A, eval, MCP/vault share one module. Many handlers are five-line pass-throughs (shallow, cheap individually). The cost is the *index*: there is no subtree to grep, and a **Mission** route lands beside webhook signature checks.

**Why it is harmful:** every feature PR conflicts here. Middleware/auth changes and “add a list endpoint” share a 5.4k file. Route ownership is unsearchable. This is not high fan-in of a Locked Engine — it is high fan-out of a process entry.

**Severity:** critical. **Confidence:** observed (`@app` count, no `APIRouter`).

---

### S-03 — `build_tools` is the voice Mouth as one closure

**Smell:** god factory / nested handlers / parameter explosion.
**Where:** `backend/voice/tools.py:310–2914`.
**Numbers:** 2,605 LOC, 18 kwargs, CC proxy ~392, nest 7, ~20 inner defs. File also exports `ALWAYS_ON` (`:80–94`) which **unions onto** the card’s allowed set at `:2912` (`keep = set(allowed_tool_names) | ALWAYS_ON`).

Identity (`_verify_identity_handler` ~721–975), PTP, **Offer**, KB, escalate (`_escalate_to_human_handler` ~2595–2762, nest 7), and **Handoff** share one closure over `session`. `hub_node` / `upsell_node` forks legacy **Flow** vs hub **Flow** inside the same factory. `_FLOW_CONTROL_TOOLS` in `flow_graph.py:773` still **omits** `capture_call_goal` that `ALWAYS_ON` includes — the comment at `tools.py:79` says they still differ.

**Why it is harmful:** a **Tool Grant** change means editing a 2.6k-line closure. Nested handlers are not modules; they are not independently testable. A PTP schema change re-parses identity. Runtime grant is this union, not `grant.py`. Publish **Gate** G9 can disagree with the floor.

**Severity:** critical. **Confidence:** observed (range, union, drifted set).

---

### S-04 — `run_bot` is the voice runtime as two parameters

**Smell:** god function.
**Where:** `backend/voice/bot.py:297–2322`.
**Numbers:** 2,026 LOC, 2 params (`transport`, `runner_args`), CC proxy ~285.

Inline nested `_spawn_bg`, sandbox session load, Twilio vs WebRTC, Pipecat pipeline, FlowManager, STT/TTS, observers, lazy `db` import. Nested `on_client_connected` is hundreds of lines inside the same function.

**Why it is harmful:** a VAD timeout and a **Handoff** wiring change are the same function. Pipeline assembly cannot be unit-tested without the whole call. Two parameters hide the entire voice product.

**Severity:** critical. **Confidence:** observed (range). Nesting inside callbacks: inference from structure.

---

### S-05 — Tool Grant exists; production does not call it

**Smell:** speculative abstraction that is *not* speculative as design — it is an unwired Locked Engine. Live path is still seven formulas.
**Where:** `backend/agent_core/tools/grant.py:30` (“Nothing imports this yet.”). Live: `skills/intersect.effective_tools`, `voice/tools.ALWAYS_ON`, `flow_graph._FLOW_CONTROL_TOOLS`, `compile.effective_tools` (`compile.py:494–510`, pass-through to intersect).

**Numbers:** `grant.py` 248 LOC, production fan-in **0**. Adding a tool is **12+ files** (catalog, domain, voice `build_tools`, flow-control set, unused `VOICE_ALWAYS`, intersect, runtime, G6, skill defaults, WhatsApp `bot_tools`, Studio ToolsTab, pin tests).

**Why it is harmful:** every new tool is shotgun surgery *by construction*. Publish **Gate** and runtime can disagree: a card publishes, then the voice floor unions tools the compiler never granted — the failure `grant.py:71–79` describes. Deleting `grant.py` today vanishes from production (characterization tests fail; no caller breaks). That is the deletion test for “not yet a module.” Wiring it without deleting `| ALWAYS_ON` would hide a seventh formula.

**Contradicts ADR-0001 until callers move.** Staff `authz` (G14 `perm-agent-publish`) is a different permission system and must stay separate — mixing them would be a worse bug.

**Severity:** critical. **Confidence:** observed (imports, `ALWAYS_ON` union).

---

### S-06 — `PromptStudioPage` is the Mouth editor as one state machine

**Smell:** giant component / temporal coupling.
**Where:** `Habibi/src/routes/prompt-studio.lazy.tsx:171`.
**Numbers:** file 1,658 LOC; component ~1,488; 15 queries/mutations; ~25 `useState`; ~7–8 effects. Owns prompt, persona, voice, guardrails, **Flow**, **Agent Card**, lint, compile, canary, publish, presets.

`fingerprint()` exists because JSON key-order already caused a PATCH loop (`:144–158`, `:214–220`). Autosave is a handshake: `hydrated`, `skipAutosave`, `savingRef`, `resaveRef`, `lastSavedFp`. The `$botId` route remounts by `key` because this state cannot be reset field-by-field.

**Why it is harmful:** a **Flow** validation bug and a **Gate** banner share one hydration effect. A tab-local save or a third lint input looks local and rebreaks autosave or orphans a card-only edit. Customer 360 already extracted; this page did not. The 21-line remount wrapper around it earns its keep; the page does not.

**Severity:** high. **Confidence:** observed.

---

### S-07 — Channel is four types; consent is a fifth spelling

**Smell:** primitive obsession / shotgun surgery.
**Where:**

| Vocabulary | Values | File |
|------------|--------|------|
| **Agent Card** identity | `voice, whatsapp, sms, internal, mcp, a2a` | `cards/schema.py:16` |
| **Tool Grant** | `voice \| text` | `grant.py:52` |
| HTTP CRM | `voice, whatsapp, chat, email, sms` | `schemas.py:28` |
| Consent | **`call`**, whatsapp, sms, email | `consent-seed.ts:6`; `ConsentResponse` |

Contact policy uses `voice, whatsapp, sms, email, chat, field`. Catalog uses `CHANNEL_VOICE/TEXT/MCP`.

**Why it is harmful:** a new channel cannot be added in one type. Consent UI can mark `call` opted-out while the dialler admits `voice`. Grant `text` vs catalog `whatsapp` is how a voice-only tool appears on WhatsApp. Mapping `card.identity.channels` into `ToolGrant.for_card(..., channel=)` can silently drop WhatsApp or grant the voice catalog on text. **At least 11 files** for a new channel.

**Severity:** high. **Confidence:** observed (literals).

---

### S-08 — Outcome, Gate, and money leak as primitives

**Smell:** primitive obsession / boolean blindness / repeated switches.

**Outcome.** Closer owns `BUSINESS_OUTCOMES` + SQL CHECK + compile `OUTCOME_CODES` (pinned). Analytics in `db.py:7177–7185` regexes free text (`no answer|voicemail|…`). Hub chips use display labels (`"PTP captured"`). API `disposition: str`. UI search treats it as a substring. Treatment has a **different** closed set (`reached`, `ptp`, …). Adding `settled_in_full` is **8 files minimum** (closer, SQL, compile restatement, schema defaults, Studio `OutboundCardEditor` hardcoded `stop_on`, pin test, plus callbacks union if the UI must show it). Miss the editor and **Cadence** cannot author `stop_on`. Miss SQL and Postgres rejects after the call.

**Gate.** Glossary is pass / block / skip. Code: `GateStatus = Literal["pass","fail","warn","skipped"]` (`compile.py:45`). `CompileReport.ok` is `not self.blocking` (`:88–90`) — **warn and skipped are green**. G14 skipped on dry-run with no actor (`compile.py:932–934`). `has_publish: bool | None` (`compile.py:534`) is skip / pass / fail jammed into a tri-state bool. KB `gate_allows(...) -> tuple[bool, str]` has no skip.

**Why it is harmful:** `if report.ok: publish` ships a card that never ran G14. Treating `gate_allows` False as “skip retrieval” vs “block collections from the insurance corpus” is the opposite safety polarity.

**Money.** `money_inr` exists because Western grouping was spoken to borrowers. `PromiseResponse.amount: float`, `AuthorityResult.approved_amount: float`, hosted pay HTML `f"{float(...):,.2f}"`, cohort `Number(raw)`. UI still has `fmtMoney` / `inrCompact` in seed files.

**Why it is harmful:** the next “just format the rupees” reintroduces the audit disagreement `money_inr` was written to kill.

**Severity:** high. **Confidence:** observed.

---

### S-09 — `USE_MOCK` makes every API two programs

**Smell:** flag argument at process scale / mutable shared state / hidden second persistence.
**Where:** `Habibi/src/api/config.ts:11–23`, default true in dev. In-memory DBs: `_mockVersions` (`prompt-studio.ts:141`), `_mockRules` (routing, redaction), `_mockCoaching`, plus consent-seed `isContactableNow` (`consent-seed.ts:379`) and `mockEvaluateContactPolicy`.

**Why it is harmful:** every feature is implemented twice. Shotgun includes both branches. `VITE_AUTHORITY_*` lets the mock engine’s caps diverge from `AUTHORITY_MODE` on the server — operators learn a ceiling the Locked Engine will not honour. Consent screen can show green while `admit` vetoes (Customer 360 was fixed to ask the API; Consent was not). This is not “too many React Query hooks”; it is a second database.

**Severity:** high. **Confidence:** observed.

---

### S-10 — Temporal coupling that callers can get wrong

**Smell:** temporal coupling / hidden protocol.

| Sequence | Required order | If skipped |
|----------|----------------|------------|
| Outbound | `reserve` → `admit` → `place` → Closer → `cadence.on_outcome` | Skip `reserve`: `KeyError`. `place` throws before `fail()`: row stuck `reserved` — “the one state the Closer skips.” Skip Closer: **Cadence** never moves. Skip `admit` at fire time: contact after opt-out / outside RBI window. |
| Publish | compile **inside** `publish_prompt_version` then `assert_publishable` | Preview-then-edit-then-publish: stale **Gate** report. G14 dry-run with no actor **skips** (green compile, unpublished). |
| Env | `db.py` freezes `TENANT_ID` at import via `_read_env_file`; later `load_env()` publishes into `os.environ` | Workers that import `db` before `.env` query the wrong tenant. RLS makes this look like “no data.” Documented at `db.py:53–66`. |
| `close_one` | claim → gather (txn 1) → enrich with **no** txn → write (txn 2). `enrichment is _UNSET` vs `None` vs dict | Call without `evidence` and it re-gathers inside the write txn (LLM in a lock — the comment says not to). |
| `build_tools` | “registry is populated by the caller after this returns” (`state.nodes`) | Handlers close over a session that is not fully wired yet. |
| `admit(conn)` vs `evaluate(conn)` | live connection; `admit` writes counters `FOR UPDATE` | `evaluate` is dry-run: UI can show allowed while a concurrent dial takes the last cap slot. |

**Why it is harmful:** the order is the invariant. It lives in comments and in call-site discipline, not in a type. A new outbound path that copies `place` without `reserve` produces a row the Closer will never see.

**Severity:** high. **Confidence:** observed (docstrings + call sites).

---

### S-11 — Flag-forked functions and parameter clumps

**Smell:** flag arguments / parameter explosion / boolean blindness.

| Signature | What the flags fork |
|-----------|---------------------|
| `retrieve(..., include_draft_answer, prefer_policy, scope_from_query)` | Draft answer vs passages; policy-first vs recall |
| `search_knowledge_base` **20 params**, 3 bools | Gate on/off, query expansion, **Offer** telemetry; `confidence_threshold` accepted and ignored |
| `compile_card` **18 kwargs**, `has_publish: bool \| None` | Sixteen **Gates**; dry-run is a bool |
| `recommend_authority(..., identity_verified=True)` | Default **True** hides unverified callers |
| `publish_prompt_version(..., shadow=False)` | **Deployment** mode is not a bool |
| `VoiceCatalogBrowser({ mode: "full" \| "compact", ... 12 props })` | Two layouts, one component |
| `decisions.record` **25** fields; `_stage_timings` **22**; flow builders **17–20** | These are rows/DTOs travelling as kwargs |
| `build_tools` / `build_collections_flow` / `build_authored_flow` | Same session-wiring clump copied three times |

**Why it is harmful:** a reader cannot name one job. Call sites cannot be reviewed. A new clock or decision field is another kwarg. `identity_verified=True` inverts the exceptional **Gate**.

**Severity:** high (retrieve / compile / authority default); medium (UI `mode`). **Confidence:** observed (signatures).

---

### S-12 — God pages and a giant hook on the operator console

**Smell:** huge components / giant hook.

- `treatment.lazy.tsx` (1,506): Insights / Models / Cases / Holds. `TreatmentPage` is a thin tab shell; heat is `InsightsTab` (~264) and `ModelsTab` (~306). No `components/treatment/` folder.
- `FlowCanvasInner` (~959) + `FlowInspector` (1,004, **low** CC — form dump, not a god).
- `KnowledgeBasePage` (~846): three products.
- `SandboxPage` (~634) + `useSandboxLiveCall` (539 LOC, CC ~71, inner `switch (msg.type)` duplicating `asServerMessage`).
- `LeadSheet` nest ~10; `VoicePanel` nest ~9.

**Why it is harmful:** Decision Intelligence, KB, and sandbox rehearsal cannot be tested except as one component. The hook mixes session lifecycle, mic, RTVI, CRM/RAG insights, and metrics. Inbox and customer 360 prove the tree already knows how to extract.

**Severity:** medium–high. **Confidence:** observed.

---

### S-13 — `CrmSink`, `_handle_turn`, leftover dumps

**Smell:** god class / god function / leftover dump.

- `CrmSink` (~1,517 lines, ~40 methods): transcript, sentiment, live QA, whisper, latency, barge-in, customer memory, escalate, RTVI observer. A latency histogram change can break **Handoff** alerts.
- `_handle_turn` (~695, CC ~111, nest 5): WhatsApp idempotency, retrieve, tools, Graph send. A **Tool Grant** miss and a delivery idempotency fix are the same path.
- `followups_db.py`: coaching, redaction, routing, workspace.
- `ops_screens.py`: floor snapshot + webhook CRUD + provider health.
- `capture.py`: `reco` correctly reuses `evaluate_product_eligibility`; the same module also emits commercial events and identity outcomes.
- `schemas.py` (~247 models, near-zero CC): a field rename is still `schemas` + `db` serializer + `main` + frontend type.

**Why it is harmful:** unrelated screen backends share a blame graph. Eligibility rule changes share a file with wrap-up telemetry. Wide DTO dumps are cheap to *read* and expensive to *change together*.

**Severity:** high (`CrmSink`, `_handle_turn`); medium (dumps, `schemas`). **Confidence:** observed.

---

### S-14 — Speculative seams and stacked policies

**Smell:** abstraction without value / wrapper chain / needless factory (partial).

There is **no** manager/handler/service explosion. Named factories that **earn keep:** `agent_core/providers/factory.py` (fail-closed unbound locale — deletion would re-create the Azure-default bug), `KeepAliveAzure*` wrappers (process keepalive invariant), Fish TTS HTTP vs Pipecat PCM (two products).

**Do not earn keep yet:**

| Site | Deletion test |
|------|----------------|
| `work_runtime/adapter_temporal.py:12–21` | Only `raise RuntimeError("temporal_adapter_not_promoted")`. `api.py` switches on `temporal_enabled()`. One live adapter (`adapter_pg`). Flag-on is an outage, not a failover. **One adapter = hypothetical seam.** |
| `FeatureProvider` ×3 (`authority/features.py:87`, `reco/features.py:193`, `treatment/features.py:397`) | Same essay, different signatures, one SQL adapter each. No second in-repo adapter. Hypothetical seam copied per Locked Engine. The **vectors** are deep; the Protocol is the speculative part. |
| `compile.effective_tools` (`compile.py:494`) | Forwards to `skills.intersect.effective_tools` after `_resolve_attached`. Extra import at the call site if deleted. |
| `db.py:18005` followups re-export | Zero logic; preserves the god interface. |
| `voice/provider_bind.bind` vs `factory.build` | Not empty wrapping: factory **raises** `NoBindingError`; bind **catches** and Azure-falls-back (`provider_bind.py:70–79`). Two answers to “nothing bound.” Fail-open is an outage class (see `09`). |

**Why it is harmful:** readers learn a seam that does not vary; tests mock Protocols production never swaps. `TEMPORAL_ENABLED=true` is a crash. Stacked STT/TTS policy means “what happens when nothing is bound?” depends on which function you call.

**Severity:** medium. **Confidence:** observed.

---

### S-15 — Process-global mutable state

**Smell:** hidden global state / mutable shared state.

Appropriate: request `ContextVar`s (`actor_context`, `request_context`, `tenant_context`) with `db` `begin` listener setting RLS. Sandbox copies context into the thread pool.

Costly:

| Location | Risk |
|----------|------|
| `db.py:83–93, 138–150` | `TENANT_ID`, `engine` snapshotted at import |
| `env_loader.load_env` vs `db._read_env_file` | Two parsers, different side effects |
| `authz.py` `_perms_cache` TTL 30s | Revoke `agent.publish` and G14 can still pass; per-worker |
| `kb_rate_limit.py` process-local deque fallback | N replicas → N× Azure spend when Postgres counter write fails |
| `voice/tools.py:55–56` `_session_tasks` | live call side-effects |
| `circuit_breaker._breakers`, Azure client singletons, provider key pool | process-local; fine if documented, surprising if not |
| `agent_core/__init__.py` → `deployment.py` → `import db` | `from agent_core import classify_intent` constructs the Postgres engine — why `money_inr` / `env_utils` exist as leaves |

**Why it is harmful:** import order and TTL are not in any function signature. Multi-worker caches disagree. RLS empty-result is the failure mode, not a crash.

**Severity:** medium. **Confidence:** observed.

---

### S-16 — Vocabulary drift that causes the wrong edit

**Smell:** mysterious names vs glossary (readability, not style).

| Glossary | Code still says | Wrong edit this invites |
|----------|-----------------|-------------------------|
| **Mouth** | `bot_id`, `/agent-studio/$botId`, `bots` table, `bot_tools.py` | Rename without a column/route plan |
| **Handoff** | `transferred_from_bot_id`; docs “transfer”; allowlist in `domain.handoff_to_agent`; `allowlist is None` = **unrestricted** (`domain.py:1024`) | Skip the middle layer “to go straight to db” and bypass the grant. Pass `None` for “no card” and open every **Mouth**. |
| **Mission** | `campaigns.py`, `/outbound/campaigns` | Collapse the batch layer into **Mission** and delete the thing `campaigns.py` exists to hold |
| **Offer** | **Tool Grant** subset *and* product rupees (`offer_amount`, `recommend_next_offer`) | Merge the two Offers |
| **Outcome** | `disposition` | Unify treatment labels with closer codes |
| **Tool Grant** | Handoff **allowlist** | Treat allowlist as the grant |

Identifier leftovers (`botId`) are naming debt. The hazard is a synonym collapse, not the leftover itself.

**Severity:** medium (navigation); high if someone “fixes” `allowlist is None` or `campaign` → **Mission** as a rename. **Confidence:** observed.

---

## Shotgun-surgery scenarios (concrete)

These are coupling findings with file counts, not hypotheticals.

| Change | Files (minimum) | Why N>1 |
|--------|-----------------|---------|
| New conversation **Outcome** code | **8** | closer vocabulary, SQL CHECK, compile restatement (avoids importing closer’s Azure client), schema defaults, Studio `stop_on`, pin test |
| New channel (e.g. `rcs`) | **11** | four `Channel` types + policy + catalog + grant `text` + consent `call` + serializers + adapters + Studio |
| New consent status | **10** | `BLOCKING_CONSENT`, `_veto`, `db.py` unknown→`opted_out` collapse, SQL CHECK, seed union, `isContactableNow`, chips/filters, mock API |
| New tool | **12+** | catalog + domain + two channel bags + three always-on lists + intersect + G6 + UI + tests |

Healthy contrast: a contact-rule change that only goes through `admit` is **one module**. Do not “reduce” that fan-in.

---

## NOT a smell (large and earning it)

| Module | Why size is not the cost |
|--------|--------------------------|
| `contact_policy.py` `evaluate` / `admit` | Fail-closed **Gate**. Never raises. Fan-out 1, fan-in 16. SQL and caps stay inside. |
| `compile_card` G0–G15 | Sequential **Gates** behind `CompileReport`. Callers learn pass/fail/skip (when they do not use `.ok`). The smell is the 18 kwargs and `bool \| None`, not the length. |
| `authz.py` | One table + `assert_registry_covers`. 895 LOC is policy data. Staff permission, correctly separate from **Tool Grant**. |
| `agent_core/{authority,treatment,reco,live_qa}` | `recommend_*` / `evaluate_live_qa` / `matrix.decide()`. Shadow vs live is one path. |
| `treatment/features.py` `SqlFeatureProvider` (~878 body) | Fat adapter behind `FeatureProvider.build`. Reachability/promises stay off the engine interface. The copied Protocol is the speculative part. |
| `cadence.py`, `outbound.place`, `mission.build` | Mechanical retry; reserve→gate→dial; Action Contract assembly. Would reappear in the dialler if deleted. |
| `flow_graph.validate_graph` | **Flow** reachability/tool checks behind `FlowValidation`. |
| `money_inr.py`, `contact_window.py`, `env_utils.py` | Leaves that closed copy-drift incidents. Under-adoption is the UI’s problem, not their size. |
| `providers/factory.py` | Fail-closed locale bind. Deletion test: complexity returns to every STT/TTS ctor. |
| `agent_core/turn.assemble_turn_messages` | One **Mouth** turn assembler for sandbox/text. |
| `seed_postgres.py`, `*-seed.ts`, `styles.css` | Data/CSS, not mixed behaviour. |
| `api/treatment.ts` types 1–875 | Type catalog; CC lives in the Locked Engine. |
| `FlowInspector.tsx` (1,004 LOC, ~12 branches) | Form dump, low cyclomatic density. |
| `_authz_guard` | Long docstring; thin adapter onto `authz.check`. |
| `campaigns.py` header | States what a run is *not*. Keep the batch object. |
| Frontend `customers.$customerId.lazy.tsx`, `inbox.tsx`, `agent-studio.$botId.lazy.tsx` | Orchestrators over feature folders. Proof extraction works. |

`call_closer.close_one` / `promise_fulfillment.fulfill` / `outbound.place` are large and closer to deep **Outcome**/**Cadence**/**Mission** modules than to `db.py`. Watch them if SQL and policy keep mixing.

---

## What “reduce complexity” must not mean

- Do not split `db.py` by moving functions into `followups_db` and re-exporting them. That already happened. Move the **import path**.
- Do not add `DbManager` / `VoiceService` / `PromptStudioController`. The tree does not have a manager explosion; naming the gods would not shrink their reasons-to-change.
- Do not collapse staff `authz` with **Tool Grant**. Two permission systems on purpose (`04-backend-architecture.md`).
- Do not merge treatment **Outcome** codes with closer **Outcome** codes. Different questions (`09`).
- Do not rename `bot_id` → **Mouth** or `campaign` → **Mission** as a cleanup. Those are identifier leftovers and a batch layer, respectively.
- Do not treat `grant.py` as dead (`07-dead-code.md`) and delete it, and do not wire it beside `ALWAYS_ON`.
- Do not “reduce” `contact_policy` fan-in. That fan-in is the healthy shape.

The cheap deepening already in the tree: extract a screen’s SQL+DTO into a module that callers import by that name; make runtimes call `ToolGrant.may_execute`; put new money through `money_inr`; put new contact checks through `admit`; group FastAPI routers behind the packages that already exist (`outbound`, `ops_screens`, `contact_policy`).

---

**Confidence legend.** LOC, def/route counts, `APIRouter` absence, `grant.py` import set, function line ranges, `ALWAYS_ON` union, `Channel` literals, `USE_MOCK` default — **observed**. Per-function CC and exact nest inside `run_bot` / `get_dashboard` — **proxy / inference**. “Reasons-to-change” — **inference** from mixed domain names in one module.
