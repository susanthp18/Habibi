# Agent transformation — end-to-end implementation plan (peak)

**Status:** engineering implementation plan — the *how*  
**Date:** 15 Aug 2026  
**Product:** BigBound AI (Habibi + collections CRM + Pipecat voice)  
**Companions:** `agent_transformation_plan.md` (why) · `agent_transformation_phases.md` (stack / what) · `roadmap-features.md` (collections P&L)

This document is the **build spec**. Phases.md decides technology. This file decides schemas, APIs, files, compiler gates, UI, tests, and what “done” means when the bar is **production-grade, not a demo**.

Do not start Phase 5 until 0–4 hold. Inside each phase, ship the **complete** capability for that layer — not a stub to “upgrade later.”

---

## 0. How to read this

| If you want… | Go to |
|---|---|
| What “peak” forbids | §1 |
| Decisions that are no longer open | §2 |
| Agent Card / Skill / Connector / Eval schemas | §3 |
| The publish compiler | §3.5 |
| Phase-by-phase build | §5–§11 |
| PR sequence | §13 |
| Program done | §14 |

**Runtime north star (unchanged):** reco / treatment / authority / live QA / DND remain **code with a log**. Agents speak. Engines decide. Customization is composition.

**Implementation north star:** Publish is a **compiler**. An invalid graph, a failed red-team, a missing policy binding, or a hallucinated product is a **failed compile**, not a warning toast.

---

## 1. The peak bar

Every workstream is judged against this table. If a PR matches the left column, it is not mergeable.

| Surface | Demo (forbidden) | Peak (required) |
|---|---|---|
| Agent Studio | Extra tabs on Prompt Studio, three hardcoded cards | Fleet of versioned Agent Cards, clone/fork, compiler report, canary, rollback |
| Skills | A markdown textarea named “skill” | agentskills.io packs: frontmatter form, `allowed-tools` ∩ catalog, progressive disclosure, signed versions, per-skill outcome evals, sandboxed `scripts/` |
| Handoffs | Model says “transfer to insurance” | Typed `handoff_to_agent` tool, allowlist, payload schema, interaction log, graph simulator |
| MCP server | Stdio + “HTTP coming soon” | Stateless streamable HTTP + mTLS + stdio, resources, prompts, Tasks, scoped keys, same `bot_tool_calls` audit |
| MCP client | URL paste box that echoes | Vault-backed connector registry, CIMD/OAuth, circuit breaker, compile-time bind, schema-strip, health tests |
| Evals | “Looks good” on the transcript | Outcome graders hit CRM rows; regression + capability + red-team + twin; pass@k; publish blocked |
| Floor copilot | Static suggested lines | Streams from QA pack + authority + treatment; approvals queue with resume; never offers a product reco did not return |
| Clerk | Cron that sends one SMS | Event-driven, idempotent, treatment-logged (`enacted_by`), HITL that survives deploys, twin-tested ladders |
| Gateway | App still calls Azure SDK URLs | All four profiles through one gateway: retries, spend caps, deployment canary, billing grain |
| Secrets | `vault://` string in a form | Azure Key Vault refs, rotation in UI, no connector tokens in `.env` |
| Identity | `MCP_API_KEY` forever | Key bootstrap → mTLS → Azure Workload Identity / partner certs |
| Canary | Number in a form, unused | `traffic_pct` on `bot_deployments`, auto-rollback on SLO / live-QA / eval burn |
| Roles | Sidebar `soon: true` | `authz.py` catalog extended; `/roles` live before tenant authoring |
| Voice SLO | “We’ll measure later” | 500–800 ms user-stop → first audio; fail **short** on context; measured every mouth-touching phase |

**Hard schema fact today that a demo would ignore:** `prompt_versions` allows **one published row per tenant** (`ux_prompt_versions_one_published`). A fleet is impossible until that constraint becomes **one published per bot**. `DEFAULT_BOT_ID` (`kaia-v2-4`) is the whole mouth. Phase 1 must break that monopoly or Agent Studio is a costume.

---

## 2. Locked implementation decisions

Open questions in `agent_transformation_phases.md` §11 are **closed here** so engineering does not re-litigate them mid-build.

| # | Decision | Lock |
|---|---|---|
| 1 | Card storage | JSON column `agent_card jsonb` on `prompt_versions` + `bot_id`. One publish lifecycle. Extract `agent_cards` table only if the JSON hurts (indexes, partial updates). |
| 2 | Durable HITL | Phase 4 ships a **Temporal-shaped** work API (`start` / `signal` / `query`) on `worker.py`. Promote to Temporal by swapping the adapter, not rewriting clerks. Mouth never waits. |
| 3 | LLM gateway | **LiteLLM in-cluster first** (same client interface). Azure APIM is the bank-facing option when procurement exists. App code talks only to the gateway client. |
| 4 | Workload identity | **Azure Workload Identity** first. SPIFFE/SPIRE only if a named A2A partner requires it. |
| 5 | Policy export | **OPA/Rego first** (Indian bank GRC familiarity). Cedar as a second exporter. Python engines remain live. Import is review + eval, never hot-reload. |
| 6 | MCP HTTP | **Stateless from day one of Phase 3.** No sticky `Mcp-Session-Id` for reads. MRTR when writes are allowed. Tasks in Phase 3. Apps in Phase 5. |
| 7 | A2A skills | A2A Agent Card `skills[]` = **our skill names + descriptions**, never a dump of MCP tools. |
| 8 | Skill signing | Platform key signs first-party packs. Tenant key signs forks. Unsigned = draft only, cannot attach to a production card. |
| 9 | Code-mode | In-process **allowlisted pure functions** with JSON schema. WASM only if tenants author scripts (Phase 5+, off the mouth). |
| 10 | Studio URL | Phase 1: `/prompt-studio` **redirects** to `/agent-studio`. Keep components under `components/prompt-studio` until they move. |
| 11 | AG-UI | Default **no**. RTVI + existing Floor/Handoff. Revisit only if approval forms cannot stream. |
| 12 | Unique published prompt | Phase 1 migration: drop tenant-global unique; add `bot_id` + unique published **per bot**. |
| 13 | Authored flow default | Phase 0: if published `flow` is a non-empty graph, runtime uses `VOICE_FLOW_GRAPH=db` path. Legacy hardcoded graph is fallback only. |
| 14 | Sampling | MCP sampling is **not adopted** (deprecated). Connectors that need a model call our `analysis` profile via our API. |
| 15 | Roles | Extend existing `backend/authz.py` `PERMISSION_CATALOG` + `permissions` table. Do not invent a second ACL. `/roles` ships in Phase 1 (read) and is writable in Phase 5. |

---

## 3. Canonical contracts

Every phase compiles into these. Do not invent a parallel schema per feature.

### 3.1 Agent Card (`prompt_versions.agent_card`)

Pydantic: `backend/agent_core/cards/schema.py` → `AgentCard`. TypeScript: `Habibi/src/api/agent-studio.ts`.

```text
schema_version: "1"
identity:
  bot_id, slug, display_name, purpose, owner_user_id
  channels: [voice | whatsapp | sms | internal | mcp | a2a]
  data_class: [pii | money | marketing | internal]
  regulator_tags: [rbi-fair-practices | dpdp | ...]
mouth:                 # already on prompt_versions columns — card references, does not duplicate
  persona, voice, languages, guardrails, flow_ref
skills: [{ skill_id, version, pin: exact|caret }]
tools:
  include: [tool_name...]          # subset of catalog
  locked: [recommend_next_offer, recommend_treatment, evaluate_authority, evaluate_live_qa]
  max_voice_tools: int             # compile warning above cap
handoffs: [{ to_bot_id, payload_schema, when }]
connectors: [{ connector_id, allow_prefixes: [ext.paylink.*] }]
policy_bindings:                   # not optional, not togglable
  reco: required
  treatment: required
  authority: required
  live_qa: required
  routing: required
  dnd: required
memory:
  scopes: [turn | call | case | customer]
  compaction: { raw_last_n, summarize_over_budget }
human_gates: [{ tool_name, require: identity | floor | both }]
eval:
  suite_id
  require: [regression, redteam]   # capability/twin added as they exist
experiment:
  traffic_pct: 0-100
  shadow: bool
  auto_rollback: [slo_miss, live_qa_burn, eval_fail]
a2a: null | { expose: bool, skill_ids: [] }
```

**Compile-time tool set (the only set the mouth sees):**

```text
effective_tools =
    card.tools.include
  ∩ catalog.by_channel(card.channels)
  ∩ ∪ skill.allowed_tools
  ∩ connector.scopes
  ∪ card.tools.locked          # always, even if author omitted them
```

A skill may *request* tools. The intersection is what executes. A skill cannot widen the card.

### 3.2 Skill pack (`skills` / `skill_versions`)

On disk / object store, agentskills.io layout:

```text
skills/{slug}/
  SKILL.md              # YAML frontmatter + body
  examples.jsonl        # gold dialogues (scrubbed)
  references/           # lazy-load
  scripts/              # JSON-in / JSON-out pure functions
```

Frontmatter (form in Habibi, never free-text tool names that can grant `apply_goodwill`):

```yaml
name: ptp-negotiate
description: ~100 tokens the model always sees
allowed-tools:
  - create_promise_to_pay
  - evaluate_authority
  - get_account_position
metadata:
  version: 1.4.0
  data_class: [money, pii]
  eval_suite: skill.ptp-negotiate
```

Tables:

| Table | Purpose |
|---|---|
| `skills` | `id`, `tenant_id`, `slug`, `latest_version_id`, `signature_status` |
| `skill_versions` | pack bytes / object-store ref, frontmatter jsonb, `allowed_tools`, `content_hash`, `signed_by`, `status` (`draft\|signed\|retired`) |
| `skill_attachments` | `prompt_version_id`, `skill_version_id` |

### 3.3 Connector (`mcp_connectors`)

| Column | Rule |
|---|---|
| `url` | HTTPS only |
| `auth_ref` | `vault_refs.id` — never the secret |
| `scopes` | tool name prefixes |
| `data_class` | pii / money / marketing |
| `ttl_ms` | `tools/list` cache |
| `timeout_ms`, `circuit` | fail closed |
| `allowed_env` | sandbox / production |

Prefixed into the catalog as `ext.{connector_slug}.{tool}` so names never clash with native `ToolSpec`.

### 3.4 Eval report (`eval_suites` / `eval_tasks` / `eval_trials`)

Anthropic shape, wired to CRM:

| Kind | Pass bar | Examples |
|---|---|---|
| **Regression** | near-100% | verify-before-PTP, no product outside reco shortlist, DND, after-hours, no prose handoff |
| **Capability** | hill to climb | Hinglish hardship, “already paid” with live bounce, code-switch |
| **Red-team** | 100% fail-closed | prompt-waiver, tool-result injection, skill jailbreak, confused deputy, CRM-card injection |
| **Twin** | outcome SQL | bounce → chase ladder → fake ledger; PTP-kept stochastic |

A **trial** records: card+skill+connector fingerprint, transcript, **tool calls**, **CRM outcome rows**, grader verdicts, pass@k (k≥3 on flaky tasks).

Sandbox today (`sandbox_runs`) becomes the **harness process**. These tables become the **compiler artifact** attached to `bot_deployments.eval_report_id`.

### 3.5 The compiler (publish)

Replace “type PUBLISH” with a compile report. Backend module: `backend/agent_core/cards/compile.py`. API: `POST /agent-studio/{botId}/compile` (dry-run) and `POST /agent-studio/{botId}/publish` (compile + deploy).

**Gates, in order. First red stops the rest of the mutating steps but the report still lists all static failures.**

| # | Gate | Phase it becomes blocking | Failure |
|---|---|---|---|
| G0 | Schema valid (`AgentCard`) | 1 | 422 |
| G1 | `flowValid` (existing `flow_graph.parse_graph`) | **0** | Publish disabled |
| G2 | Flow included in the published version (not dropped by patch) | **0** | 422 |
| G3 | Policy bindings present and locked | 1 | 422 |
| G4 | Effective tool set ⊆ catalog; locked engines included | 1 | 422 |
| G5 | Handoff targets exist and are allowlisted | 1 | 422 |
| G6 | Latency estimate: voice tool count ≤ cap; skill description tokens ≤ budget | 1 (warn) / 2 (block if over) | 422 |
| G7 | Regression suite green | 1 | 409 eval_fail |
| G8 | Red-team suite green | 1 | 409 eval_fail |
| G9 | Skill signatures valid; `allowed-tools` ⊆ card | 2 | 422 |
| G10 | Connector health + data-class review | 3 | 422 |
| G11 | Twin capability suite (clerk ladders) | 4 | 409 |
| G12 | Canary + auto-rollback configured | 5 | 422 |
| G13 | A2A cert / mTLS if `a2a.expose` | 5 | 422 |
| G14 | `authz`: `agent.publish` | 1 (check) / 5 (Roles UI) | 403 |

Frontend: `PublishDialog` becomes `CompileReportDialog` — gate list, diff (existing `DiffModal` extended), token/SLO estimate, eval pass@k, type-PUBLISH only if all required gates are green.

---

## 4. What we compile into (do not rebuild)

| Primitive | Existing home |
|---|---|
| Mouth | `bot_runtime.py`, `voice/bot.py`, `voice/flows_dynamic.py` |
| Tools | `agent_core/tools/catalog.py` → `bot_tools.py` / `voice/tools.py` / `mcp_tools.py` |
| Policy | `agent_core/reco`, `treatment`, `authority`, `live_qa` |
| Deploy | `bot_deployments`, `load_active_bundle()` |
| Flow | `prompt_versions.flow`, `flow_graph.py`, `FlowCanvas.tsx` |
| Mesh | `voice/mesh.py` + `mesh_bus.py` — becomes data |
| MCP out | `mcp_server.py` (stdio, out-of-process — **keep out of FastAPI**) |
| Work | `worker.py`, `bot_worker.py`, treatment `followthrough.py` |
| Audit | `bot_tool_calls`, `get_turn_trace` |
| Authz | `authz.py` + `roles` / `permissions` / `user_roles` |
| Sandbox | `sandbox_runtime.py`, `voice_sandbox.py`, `voice/evals/` |
| Studio | `prompt-studio.lazy.tsx`, `PublishDialog`, `DiffModal` |

---

## 5. Phase 0 — Honest seams (1–2 weeks)

**Peak goal:** The one-bot path is a compiler, not a text box. Mesh is data. MCP is a documented product. Traces and flags have the columns later phases need. **No new product surface yet — but nothing is a lie.**

### Forbidden demo

- Disable Publish in the UI but still allow the API.
- Mesh JSON that the runtime ignores (Python `ROLES` still authoritative).
- Flag names in a markdown file only, not in `.env.example` + config loaders.
- Trace fields added as comments.

### Backend

| Work | Files |
|---|---|
| Publish must persist `flow` | `Habibi/src/api/prompt-studio.ts` `publishStudioDraft` includes `flow`. Backend publish/patch: omitted key = untouched; explicit `flow` = saved. Tests: authored graph survives publish. |
| Server-side `flowValid` | `POST /prompt-studio/publish` (or existing publish) calls `flow_graph.parse_graph`. Invalid → 422 `flow_invalid` with node errors. UI disable is not enough. |
| Authored flow default | `voice/config.py`: if active deployment’s `flow` is a real graph, compile via `flows_dynamic.py` even when env is `legacy`. Env `VOICE_FLOW_GRAPH=legacy` remains an explicit kill-switch. |
| Mesh as data | `backend/voice/mesh_roles.json` (shape ⊂ Agent Card: `name`, `description`, `tools[]`). `mesh.py` loads it; `ROLES` constant deleted. Test: JSON round-trip; unknown role still `unknown_mesh_role`. |
| Trace stubs | `bot_tool_calls` + `get_turn_trace` rows gain nullable `agent_id`, `skill_id`, `connector_id` (json extra or columns). Floor/Audit ignore nulls. |
| Flags | `.env.example` + loaders: `AGENT_CARDS_ENABLED`, `MCP_HTTP_ENABLED`, `MCP_CLIENT_ENABLED`, `MCP_TASKS_ENABLED`, `MCP_APPS_ENABLED`, `A2A_ENABLED`, `EVAL_GATE_ENABLED`, `REDTEAM_GATE_ENABLED`, `LLM_GATEWAY_ENABLED`, `VISION_INGEST_ENABLED`, `TEMPORAL_ENABLED`, `POLICY_EXPORT_ENABLED`. All default **off**. |
| Vault inventory | `docs/ops/vault-inventory.md`: every secret still in env (`AZURE_*`, `TWILIO_*`, `WHATSAPP_*`, `MCP_API_KEY`). No vault yet — the list is the ticket. |
| MCP runbook | `docs/ops/mcp.md`: stdio only, deny-list, `python -m mcp_server`, why not on FastAPI. Identity story for writes (MRTR or floor) as a ticket, not code. |
| Bot analytics SLO | Label 800 ms voice budget on existing latency charts (`bot-analytics`). |

### Frontend

| Work | Files |
|---|---|
| Publish disabled when `flowValid === false` | `prompt-studio.lazy.tsx` — `flowValid` is set today and **never read**. Wire it. |
| Error list | Header + `PublishDialog`: node/edge errors from `FlowCanvas.onValidation`. |
| Confirm still requires `PUBLISH` | Keep the type-in. Add the gate list above it. |

### Tests (blocking)

- `test_flow_graph_authoring.py`: publish with invalid graph → 422.
- New `test_publish_persists_flow.py`: patch without flow does not wipe; publish with flow stores it; voice compile sees it when kill-switch off.
- `test_mesh_roles_json.py`: load, unknown role, session isolation (already a concern in `mesh.py`).
- `test_mcp_catalog.py` still green (mutating tools impossible).

### Accept

Invalid flow cannot publish (UI **and** API). Mesh JSON is what `activate_role` uses. Trace payload accepts `agentId`. Flags exist. MCP mutating tools still 403.

### Not

Agent Studio rename, HTTP MCP, LiteLLM, Temporal, tenant cards.

---

## 6. Phase 1 — Agent Cards as the fleet (3–4 weeks)

**Peak goal:** Four first-party cards (Intake, Collections, Insurance, Supervisor-brief) share one catalog. Habibi is a **fleet console**. Handoff is a tool. Context does not grow unbounded. Red-team and regression **block publish**. The tenant-global published-prompt monopoly is gone.

### Forbidden demo

- UI list of four names that all load `DEFAULT_BOT_ID`.
- Handoff parsed from transcript text.
- Red-team as a markdown checklist.
- Compaction that re-summarizes every turn on the voice path.
- Experiment columns that nothing reads.

### Schema (the load-bearing migration)

Alembic + `sql/09_bot_config.sql`:

1. `prompt_versions.bot_id TEXT NOT NULL REFERENCES bots(id)`.
2. **Drop** `ux_prompt_versions_one_published` (per tenant). **Add** unique `(bot_id) WHERE status = 'published'`.
3. `prompt_versions.agent_card jsonb NOT NULL DEFAULT '{}'::jsonb`.
4. Seed four `bots` rows from today’s mesh JSON (Intake, Collections=`kaia-v2-4` renamed/aliased, Insurance, Supervisor-brief). Existing deployments attach to Collections.
5. `bot_deployments`: `traffic_pct int NOT NULL DEFAULT 100`, `shadow boolean NOT NULL DEFAULT false`, `eval_report_id TEXT`.
6. `eval_suites`, `eval_tasks`, `eval_trials`, `eval_redteam_cases`.
7. `context_summaries` (`interaction_id`, `summary`, `upto_turn`, `model_profile`).
8. `agent_handoffs` optional if `interactions.transferred_from_bot_id` / `handler_bot_id` are enough — **prefer existing columns**; add table only for payload hash + schema version.

`load_active_bundle(bot_id=…)` already exists. Stop defaulting every path to `DEFAULT_BOT_ID` without an explicit card.

### Backend

| Work | Files |
|---|---|
| Card schema + compiler G0–G8 | `agent_core/cards/schema.py`, `compile.py`, `defaults.py` (four first-party cards) |
| Typed handoff | New catalog tool `handoff_to_agent(target_bot_id, reason, payload)`. Allowlist from card. Writes `handler_bot_id` / `transferred_from_bot_id`. **Not** activated by “transfer to legal” in user text. |
| Mesh compile | Card → `mesh.activate_role` + Flows node tool lists. Insurance off on the card ⇒ `gated_upsell` never activates. |
| Compaction | `assemble_turn_messages` / voice context: last N raw; older → `context_summaries` via **analysis** profile (off audio path); fail short. Prefix-cache static prompt. |
| OTel | `gen_ai.invoke_agent`, `execute_tool`, `chat` spans. Content capture **off**. Postgres remains the audit. |
| Eval harness | Graduate `voice/evals/` + sandbox scenarios into `eval_*` tables. Code graders: product id ∈ reco payload; no money tool before `verify_identity`; no `handoff_to_agent` unless tool fired; DND. |
| Red-team pack | Fixtures in `eval_redteam_cases`: ignore-policy waiver, prose handoff, CRM-card injection (`format_untrusted_crm_card` already exists — assert it holds), fake tool-call in KB snippet. |
| Authz | Add `agent.publish`, `agent.edit`, `eval.run`, `redteam.run` to `PERMISSION_CATALOG`. Enforce on compile/publish. |
| Routing | Rule inspector data: which `bot_id`s a rule allows. Runtime already vetoes; expose it. |

### APIs

```
GET    /agent-studio/cards
GET    /agent-studio/cards/{botId}
PATCH  /agent-studio/cards/{botId}          # draft agent_card + mouth columns
POST   /agent-studio/cards/{botId}/compile  # dry-run report
POST   /agent-studio/cards/{botId}/publish
GET    /agent-studio/cards/{botId}/graph
POST   /eval/suites/{id}/run
GET    /eval/reports/{id}
GET    /flow/tools                          # already exists; add locked[] 
```

### Frontend — Agent Studio (peak, not a rename)

**IA:** `/agent-studio` index · `/agent-studio/$botId` editor. `/prompt-studio` redirect. Sidebar + command palette: “Agent studio”, “New agent card” (disabled for tenants this phase — four cards only), “Open active card”, “Run red-team”.

**Index (fleet):**

- Table/grid: name, channels, skills (0 this phase), eval status, traffic %, last publish, owner.
- Mini agent graph (React Flow, same renderer as editor): Intake → Collections → Insurance → Human. Click node → editor.
- Cannot delete a card with an active production deployment.
- Empty state never shown for us — we seed four. Tenant empty state in Phase 5: “Start from Collections template.”

**Editor tabs:** Prompt · Conversation flow · **Agent graph** · Persona · Voice · Guardrails · **Tools** · **Policy** (read-only locked engines) · **Evals**.

**Tools tab:** catalog picker, channel badges, MCP vs native, **locked engines visible and disabled** with “required by policy” copy. Hover = schema. Search. Hard cap + “this will miss 800 ms” warning (warn this phase, block in Phase 2).

**Agent graph:** edges = handoff allowlist. **Simulator:** pick a twin intent (hardship / dispute / upsell / authority-cap) and highlight the legal walk. Illegal walk is red, not a toast.

**Compile report dialog:** G0–G8. Diff includes tools + graph + card JSON, not only prompt/persona/voice/guardrails (`DiffModal` extension).

**Sandbox:** card picker. Red-team pack one-click. Inspector shows `agentId` on `TurnTraceView`. Promote blocked unless evals green.

**Floor:** chip = active card/role (`mesh.status()` already has `activeRole`).

**Trace / Audit:** zipper starts: `agentId → engine verdict → tool`.

**Roles page (read-only):** `/roles` leaves `soon`. Lists `authz` catalog + who has `agent.publish`. Writable in Phase 5.

### Tests

- Insurance detached ⇒ `gated_upsell` never fires (`test_flows_dynamic.py` extension).
- Prose “transfer to legal” ⇒ no handoff row.
- Verify-before-PTP regression + red-team waiver case.
- 20-turn call: `context_summaries` used; voice token budget bounded.
- Two published cards in one tenant (the unique-constraint proof).
- `test_authz.py`: user without `agent.publish` → 403.

### Accept

Four cards load independently. Handoff is a tool with a log. Invalid/red-team-fail cannot publish. Voice context bounded. Floor shows the active card.

### Not

Tenant-created fifth card. MCP client. Traffic split (schema ready, `traffic_pct=100` only). A2A. Skills files.

---

## 7. Phase 2 — Skills as the knowledge plane (3–4 weeks)

**Peak goal:** The mega-prompt is gone. Voice sees ~100 tokens of descriptions until a skill activates. First-party skills are signed, eval’d, and attachable. Code-mode is real math, not `exec`. KB gaps promote to skills.

### Forbidden demo

- Pasting PTP instructions into a “skill” field that is concatenated into the system prompt every turn.
- `allowed-tools` as a comma-separated text box that can name `apply_goodwill`.
- Scripts that shell out.
- Marketplace storefront.

### First-party skills (all shipped this phase, not a sample)

| Skill | Mouth | Writes | Engine |
|---|---|---|---|
| `verify-and-disclose` | voice/WA | `verify_identity` | consent / recording |
| `ptp-negotiate` | voice/WA | `create_promise_to_pay` | authority + DND |
| `hardship-intake` | voice/WA | notes + escalate | treatment hold |
| `dispute-capture` | voice/WA | `flag_dispute` | treatment dispute veto |
| `doc-fulfil` | internal | `request_documents` | identity |
| `broken-ptp-chase` | internal + WA | treatment followthrough | attempt cap |
| `upsell-pitch` | voice (late) | `recommend_next_offer`, `capture_lead` | reco suppression |
| `insurance-lapse` | voice/WA | same catalog | reco + consent |
| `qa-examiner` | internal | scorecard pack | live QA lock |
| `floor-coach` | internal | whisper / barge | `LIVE_QA_BARGE_MODE` |
| `supervisor-brief` | handoff | none | mesh role |

### Backend

| Work | Files |
|---|---|
| Store + linter | `skills` / `skill_versions`; validate with `skills-ref`; YAML frontmatter schema |
| Runtime load | Descriptions always in static prefix (stable order for prefix cache). Body on activation (`understanding.py` intent **or** `load_skill` tool). Drop previous body on switch. `references/` on demand. |
| Intersection | `allowed-tools` ∩ card. Collections with PTP skill removed **cannot** call `create_promise_to_pay` even if catalog has it. |
| Code-mode | `agent_core/skills/scripts.py`: registry of pure functions (EMI remaining, promise date inside calling window). JSON schema in/out. No `subprocess`, no network, no ledger writes. |
| KB gardener | Unanswered table → draft `SKILL.md` (status `draft`, unsigned). Human signs + publishes. Worker cron. |
| Signing | Platform key; unsigned cannot attach to production card (G9). |
| Evals | Per-skill suites. PTP **outcome** = `promises` row + amount + date. Hardship = treatment hold kind, **no** reco product. Red-team: `references/` cannot grant extra tools. |
| Compaction | G6 becomes blocking if description tokens + tools blow the voice budget. |

### Frontend

- `/agent-studio/skills` list: description (the actual prefix tokens), `allowed-tools` chips from catalog multi-select, attached cards, signature status.
- Editor: **form** for frontmatter (tools = multi-select from catalog, not free text). Markdown body + preview. File tree for `references/` and `scripts/` (MinIO, same as KB).
- Import/export zip (agentskills.io). Unsigned import = draft.
- Card **Skills** tab: attach/detach, progressive-disclosure preview (rest vs activated vs references), token counts.
- Playground: “load this skill on Collections in sandbox.”
- KB unanswered: **Promote to skill** (gap banner already deep-links Prompt Studio — land on skill editor).
- Code-mode: JSON in/out form, **no terminal**.

### Accept

PTP skill detached ⇒ no `create_promise_to_pay`. Voice TTFB regresses **≤10%** vs Phase 1 (prefix cache). 30-turn call stays inside voice token budget. Skill jailbreak red-team fails closed. Gardener draft requires human sign.

### Not

Public marketplace. General interpreter on the mouth. Tenant-authored scripts.

---

## 8. Phase 3 — MCP both ways + gateway + vault (4–6 weeks)

**Peak goal:** We are a load-balancable MCP **server** and a **client** of tenant systems. Secrets live in a vault. Every LLM call goes through a gateway. Long work is a Task, never a blocked voice turn.

### Forbidden demo

- HTTP MCP mounted on FastAPI “to make it simpler.”
- API key in the Agent Card URL field.
- Connector that dumps 80 tools into the voice completion.
- Gateway as a config comment while `azure_openai` still uses the SDK URL.
- `vault://` placeholder strings.

### Server (us) — still a **separate process**

`mcp_server.py` stays out of FastAPI (gzip + auth — already documented).

| Capability | Spec |
|---|---|
| Transports | stdio **and** streamable HTTP. `MCP_HTTP_ENABLED`. |
| Auth | `MCP_API_KEY` **and** mTLS. Scopes per key: `crm.read`, `kb.search`, `offers.read`. Never “all tools.” |
| Stateless | Design headers for `2026-07-28`: `Mcp-Method`, `Mcp-Name`. No sticky session for reads. |
| Tools | Same five read-only + deny-list. Writes: still denied **or** MRTR `input_required` to floor. Prefer deny until elicitation UX is real. |
| Resources | `customer://{id}`, `account://{id}/ledger`, `kb://snapshot/{id}`, `interaction://{id}/trace`, `policy://authority-matrix` |
| Prompts | User-triggered: “prep handoff”, “draft PTP SMS” |
| Tasks | `io.modelcontextprotocol/tasks` for statement generate / bureau-class work. Voice/WA get a ticket id + spoken “we’ll send it.” Clerk polls. Table `mcp_tasks`. |
| Cache | `ttlMs` on `tools/list` |
| Apps | Schema + `MCP_APPS_ENABLED` flag only. UI in Phase 5. |
| Audit | `bot_tool_calls.channel='mcp'` (already). |

### Client (tenants)

First connectors, **real systems**, not mocks: **pay-link status**, then **LMS balance**.

- `mcp_connectors` + `vault_refs`.
- Merge as `ext.paylink.*` / `ext.lms.*`.
- Compile-time bind on the card (G10). Progressive discovery on voice: **never** inject unbound connector tools.
- Prefetch after `verify_identity`.
- Circuit breaker, timeout, schema-strip extra fields (red-team confused deputy).
- Health test: one read tool, same as provider Test today.

### Vault

Azure Key Vault (or tenant equivalent). `provider_configs` credential references become `vault_refs`. LLM, Twilio, WhatsApp, MCP OAuth (CIMD — DCR is deprecated). Rotation is an Integrations action. No connector refresh tokens in `.env`.

### LLM gateway

`backend/llm_gateway/` client. All four profiles (`voice`, `text`, `analysis`, `internal`) through LiteLLM (or APIM). Retries, spend caps, deployment canary (`analysis` → `text` → `voice`). Billing reads gateway usage. `LLM_GATEWAY_ENABLED` on; old SDK path is the kill-switch, not the default.

### Frontend — Integrations becomes a console

Keep Azure/Twilio/WhatsApp provider cards. Add:

| Surface | Peak UX |
|---|---|
| Connectors | Catalog: status, last `tools/list`, cache age, data-class, bound cards. Test = one read. |
| Add connector | Drawer: URL, **vault ref picker** (never token), scopes, timeout, circuit. CIMD “Connect” opens bank IdP. |
| Our MCP | Copy stdio command / HTTP URL / rotate key / mTLS cert download. Resource browser. Task list. |
| Vault | Refs, rotation age, last used. Ops lock stays (`credentialsLocked`). |
| Gateway | Profile → Azure deployment. Canary analysis first. Spend cap. |
| Card Connectors tab | Bind **approved** servers only. SLO warning on tool count. |

Billing: gateway tokens by profile + connector call grain.

### Accept

Cursor/Claude `get_customer_context` over HTTP with a scoped key; mutators 403. Collections + pay-link connector can say “UPI success” from a **tool result** in sandbox. Statement request returns a task id without blocking the call. Secret rotation does not require a deploy. Mouth LLM calls visible in the gateway. Voice SLO still held.

### Not

A2A. MCP Apps UI. Arbitrary MCP URL on a voice card without data-class review. Temporal cluster.

---

## 9. Phase 4 — Internal agents that eat delay (4–6 weeks)

**Peak goal:** This is the collections-head phase. Clerks close the hour a bounce happens. Floor gets a copilot that knows the engines. Receipts become documents. Chase ladders are proven on a twin before they touch a borrower.

### Forbidden demo

- A script that SMS-es everyone in `promises` at 9am.
- Copilot that paraphrases the transcript and ignores authority.
- Vision on the live STT/LLM path.
- Twin that dials.
- Temporal on the mouth.

### Agents (all shipped, first-party cards, `internal` channel)

| Agent | Trigger | Enact | HITL |
|---|---|---|---|
| **Clerk** | bounce ingest, broken PTP, doc SLA, callback diary | same domain handlers as today; `enacted_by=clerk_agent` | legal/field/goodwill |
| **Floor copilot** | live call / handoff | whisper draft, wrap-up, next action from QA pack | barge already exists |
| **KB gardener** | unanswered cron | draft skill | human sign (Phase 2) |
| **Tuner** | decision logs | suggested `RECO_W_*` in **shadow** | human copies to env |

### Work runtime

- Keep `worker.py` as the process.
- Introduce `backend/work_runtime/` with Temporal-shaped API: `start_workflow`, `signal`, `query`, `idempotency_key`.
- Adapter v1 = Postgres + worker drain (survives process restart via job rows). Adapter v2 = Temporal (go/no-go at phase start: promote if HITL must pause **days** across deploys).
- Mouth **never** awaits a workflow. It speaks “I’ve raised this” and enqueues.

### Multimodal

`ingest_customer_document` on **analysis** profile. WhatsApp image / bounce screenshot → documents/disputes. Identity-gated. Existing redaction pipeline. `source: vision`. Not in the voice completion.

### Simulation twin

Not a canned sandbox persona:

- State: DPD, bounce, open PTP, hardship, language, DND, fake UPI ledger.
- Stochastic: PTP-kept, rage, code-switch, injection strings.
- Outcome graders hit the **fake ledger + queues**.
- Clerk ladders run here before live treatment mode.
- Never a dialer.

### Frontend

| Screen | Peak |
|---|---|
| Floor | Copilot rail: whisper draft streamed (RTVI), authority verdict, treatment next action (`GET /qa/interactions/{id}/pack` already). **Approvals** queue (MRTR / work-runtime `input-required`). Chip: card + skill. |
| Handoff | From-card → to-card. Supervisor-brief from the card. Suggested responses engine-gated. |
| Inbox | Image drop → ingest. Card badge on thread. |
| Workspace | Clerk items in Needs Attention with `enacted_by`. |
| Documents / Disputes | `source: vision` flag. |
| Sandbox | Twin runner + outcome panel (**CRM rows**, not the reply). |
| QA | Channel-appropriate rubric (voice vs clerk SMS). Live-locked cells stay locked. |

Optional 4b: AG-UI only if RTVI cannot stream the approval form.

### Accept

Bounce → WhatsApp in the same hour in live treatment mode. Broken PTP re-enters without a human opening the diary. No double SMS (idempotency). Receipt photo → document row. Twin replays a bounce ladder. Work-runtime resumes an approval after API restart. Live QA does not score clerk SMS with a voice rubric.

### Not

Tenant-authored voice agents. Multi-agent debate. Vision on audio. Using the twin as a dialer.

---

## 10. Phase 5 — Tenant-authored agents + A2A (6–8 weeks)

**Peak goal:** A collections head clones **Lapse Specialist**, attaches pay-link + LMS, eval-gates, canaries 10%, publishes — without a Python deploy. A bank fraud agent can `input-required` us over A2A with mTLS. GRC diffs an OPA bundle. Roles are a product.

### Forbidden demo

- “Create agent” that copies the Collections prompt into a new row with no compiler.
- Canary slider that does not split traffic.
- A2A as a JSON download of the card with a bearer token.
- Hot-import OPA that bypasses Python authority.
- Wrapping Collections as a stateless MCP tool for a partner (throws away multi-turn PTP). They talk **A2A**.

### Backend

| Work | Detail |
|---|---|
| Clone/fork | Card + skill. Marketplace = **first-party skills only** until tenant signing exists. |
| Canaries | `bot_deployments.traffic_pct` actually splits. Auto-rollback on SLO miss / live-QA burn / eval fail. Table `deployment_experiments`. |
| A2A 1.0 | Serve Agent Card at `/.well-known/agent-card.json` (authz-gated). Skills = our skill names. Tasks in `a2a_tasks` (`submitted`/`working`/`input-required`/`completed`/`failed`). Consume partners in **work runtime only**. Partner mTLS. Our side: Azure Workload Identity. |
| MCP Apps | First app: handoff prep / PTP confirm inside Cursor/Claude. Read-mostly. |
| Policy export | Generate OPA (and optionally Cedar) bundle from DND + hours + authority caps. Download on Compliance. Live path still Python. |
| Compiler | G12–G14 blocking. Full report in publish dialog. |

### Frontend

- Index: **Clone card**. Templates: Collections, Lapse, Hardship, Clerk.
- **Ship** tab: canary 0–100%, shadow, auto-rollback conditions, compare live-QA burn vs previous. One-click rollback (mutation exists).
- Integrations: **A2A partners** (card URL, cert, allowed skills, recent tasks). `input-required` deep-links Floor.
- MCP Apps status (read-only in Habibi).
- Compliance: policy export download; “this card cannot disable DND” audit.
- **Roles** writable: `agent.publish`, `connector.attach`, `policy.export`, `redteam.run`.
- Routing inspector: which cards a rule allows.
- Publish = full compiler report (all gates).

### Walkthrough that must work without a deploy

HDFC-style insurance lapse + EMI bounce from `agent_transformation_plan.md`: clone `broken-ptp-chase` → `premium-lapse-chase`; attach policy-admin + pay-link connectors; Lapse Specialist card; graph bounce → clerk WA → voice Collections → intent handoff Lapse; routing DND/hardship → wait; 12-scenario suite + red-team; staging → 10% canary → production.

### Accept

That walkthrough. Partner A2A task in audit with a **client cert**. 10% canary rolls back when red-team fails in sampling. Voice SLO held (A2A never on audio). GRC diffs a bundle without reading Python.

### Not

Unregulated GPT canvas. Mega-graph mixing conversation, handoffs, and CBS SOAP. Hot OPA import.

---

## 11. Phase 6 — Self-improve under gates (ongoing)

**Peak goal:** Model upgrades are a days-not-weeks event. Skills improve from **outcomes** (PTP kept), not from the model editing itself. Tuners suggest; humans promote.

### Forbidden demo

- Agent rewrites production `SKILL.md`.
- Fine-tune on raw call audio.
- Skip red-team because “the new model is smarter.”
- Auto-write `RECO_W_*` live.

### Loops (allowed)

| Loop | Input | Output | Promote |
|---|---|---|---|
| KB gardener | unanswered | draft skill | human sign |
| Skill critique | failed eval transcripts | objection-line diff | human merge |
| Reco/treatment tuner | decision logs | shadow weights | human copies env |
| Judge calibration | disagreement vs `[live]` QA | rubric tweak | QA lead |
| Model upgrade | full suite vs new Azure deployment | go/no-go | gateway canary `analysis` → `text` → `voice` |
| Twin corpus | production **outcomes** (not raw audio) | harder capability tasks | eval owners |

Optional: DSPy **in sandbox only** for skill drafts.

### Frontend

Eval cockpit history; twin corpus browser; gateway canary on Integrations; tuner suggestions on offer-health / treatment insights (read-only until copy). Bot analytics per-card / per-skill (containment, handoff rate, SLO, skill activation histogram).

### Accept

New Azure model: suite (regression + red-team + twin) + voice SLO + compliance graders → switch `voice` profile via gateway. Injection fixtures still fail closed. Tuner visible, not auto-applied.

---

## 12. Cross-cutting implementation (every phase)

### 12.1 Latency

Instrument per stage (you already store `latency_ms`): TTFB STT, LLM, TTS, tool, skill-load, handoff. OTel `gen_ai.client.operation.duration`. Voice fail-short order: drop `references/` → drop extra skill bodies → drop summaries last. A2A, Temporal, eval judges, marketplace downloads are **forbidden** on the audio path.

### 12.2 Security

- Untrusted: CRM card (already), skill bodies, MCP results, vision OCR — all ride the developer-untrusted channel. Never executed as tools.
- Handoff is a tool. Period.
- Confused deputy: per-connector creds, `Mcp-Name` allow, schema-strip.
- PII: traces redacted (`_trace_redact`); OTel content off; skill examples scrubbed.
- Multi-tenancy: every new table `tenant_id`. MCP keys and vault refs scoped. A2A tasks namespaced.

### 12.3 Idempotency

Mutating tools already have `idempotency_keys`. Clerk, Temporal activities, MCP Task retries, and canary replays **must** use them. Double-PTP is a release blocker.

### 12.4 Feature flags

Shadow-first, same as reco/treatment/live QA. Mouth-touching flags default off until eval + SLO pass. `ALLOW_UNHARDENED_PRODUCTION` already gates deferred controls — new flags join that list until green.

### 12.5 Billing grain

Hero metric stays cost per resolved contact. Add: gateway tokens by profile, connector calls, MCP Task runtime, eval/red-team suite cost, vision jobs.

---

## 13. Work packages / PR sequence

Do not open a Phase N PR until the previous phase’s **Accept** is green on CI + a voice SLO check if the mouth moved.

| ID | Phase | PR theme | Primary paths |
|---|---|---|---|
| 0.1 | 0 | `flowValid` UI + API + persist flow | `prompt-studio.lazy.tsx`, `api/prompt-studio.ts`, publish handler, `flow_graph.py` |
| 0.2 | 0 | Mesh JSON | `voice/mesh.py`, `voice/mesh_roles.json`, tests |
| 0.3 | 0 | Trace stubs + flags + `.env.example` | `db.py` / SQL, config, `bot-analytics` SLO label |
| 0.4 | 0 | MCP runbook + vault inventory (docs) | `docs/ops/` |
| 1.1 | 1 | `bot_id` on `prompt_versions`; unique per bot; seed four bots | Alembic, `sql/09_bot_config.sql`, `deployment.py` |
| 1.2 | 1 | Agent Card schema + compiler G0–G8 | `agent_core/cards/` |
| 1.3 | 1 | `handoff_to_agent` + mesh compile | `catalog.py`, `mesh.py`, `flows_dynamic.py` |
| 1.4 | 1 | Eval tables + regression/red-team harness | `eval_*`, `voice/evals/`, sandbox |
| 1.5 | 1 | Compaction + OTel | context assembler, `context_summaries` |
| 1.6 | 1 | Agent Studio UI + redirect + Floor chip + Roles read | Habibi routes/components |
| 1.7 | 1 | Authz permissions | `authz.py` |
| 2.1 | 2 | Skill tables + linter + signing | SQL, `agent_core/skills/` |
| 2.2 | 2 | Runtime progressive disclosure + intersection | `prompt.py`, `bot_runtime.py`, voice context |
| 2.3 | 2 | Code-mode registry | `skills/scripts.py` |
| 2.4 | 2 | Per-skill evals + gardener | worker, KB gaps |
| 2.5 | 2 | Skills UI + card tab + KB promote | Habibi |
| 3.1 | 3 | HTTP MCP + mTLS + resources + prompts | `mcp_server.py` (still separate) |
| 3.2 | 3 | MCP Tasks | `mcp_tasks`, worker poll |
| 3.3 | 3 | Connector registry + vault + CIMD | `mcp_connectors`, `vault_refs` |
| 3.4 | 3 | LiteLLM gateway client | `llm_gateway/`, billing |
| 3.5 | 3 | Integrations console + card Connectors tab | Habibi |
| 4.1 | 4 | Work-runtime adapter | `work_runtime/` |
| 4.2 | 4 | Clerk agent + idempotent enact | followthrough, queues |
| 4.3 | 4 | Floor copilot + approvals | Floor/Handoff |
| 4.4 | 4 | Vision ingest | analysis profile, Inbox |
| 4.5 | 4 | Twin + outcome graders | sandbox / `simulation_twins` |
| 5.1 | 5 | Clone/fork + canary split + auto-rollback | deployments |
| 5.2 | 5 | A2A server + mTLS + tasks | `a2a_*` |
| 5.3 | 5 | MCP Apps + OPA export | protocol edge, Compliance |
| 5.4 | 5 | Ship tab + Roles write + A2A partners | Habibi |
| 6.x | 6 | Continuous suites, tuners, gateway model canary | eval cockpit, offer-health |

Each PR: tests first for the gate it adds; no “UI only” publish control without the API twin.

---

## 14. Program definition of done

The transformation is done when **all** of the following are true in production, not in a slide:

1. A collections head can compose a specialist from skills + connectors + allowlisted handoffs, and **cannot** unbind reco / treatment / authority / live QA / DND.
2. Publish is a compiler: flow, policy, tools, skills, connectors, regression, red-team, (from 4) twin, (from 5) canary — all green or it does not ship.
3. Cursor can read CRM over HTTP MCP with a scoped key; it cannot create a PTP without identity/floor.
4. A bounce is chased the same hour by a clerk agent, idempotently, with a treatment log.
5. Floor sees which card/skill is live, gets an engine-grounded whisper, and can approve a waiting write after an API restart.
6. Voice stays inside 500–800 ms; A2A, Tasks, Temporal, vision, and eval judges never sit on the audio path.
7. A 10% canary rolls itself back when red-team or SLO burns.
8. A partner talks A2A with mTLS; they do not receive our internal tools.
9. GRC downloads an OPA bundle that matches live Python vetoes.
10. A new Azure model reaches the mouth only after the full suite, including attacks, is green.

Until then, we still have one very good recovery agent with a studio. That is a product. It is not yet a governed agent factory.

---

## 15. Explicit non-goals (repeat in every design review)

Same as `agent_transformation_phases.md` §10, plus:

- No “v0” UI that pretends a gate exists.
- No second tool catalog (LangChain, n8n, CopilotKit tools).
- No mega-canvas that mixes conversation flow, agent handoffs, and CBS connectors.
- No mounting MCP on FastAPI.
- No skipping Phase 0–4 to “show custom agents” in a hackathon demo.

The hackathon-grade version of this plan is Phase 0 + 1.6 (Agent Studio list) with fake eval badges. **Do not build that.** Build the compiler, then put a UI on it.
