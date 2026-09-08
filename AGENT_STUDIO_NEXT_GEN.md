# Agent Studio — the honest state, and the architecture that makes it agentic

**Date:** 2026-09-06
**Status:** Read-only audit + architecture proposal. **No application code was changed to produce this.**
**Base commit:** `026cada` — *see [Working-tree caveat](#working-tree-caveat), the tree was not clean during the audit.*
**Companions:** [AGENT_STUDIO_BUG_HUNT.md](./AGENT_STUDIO_BUG_HUNT.md) (the 2026-08-25 pass, 61 of its 72 findings now fixed) · [agent_transformation_plan.md](./agent_transformation_plan.md) · [agent_transformation_phases.md](./agent_transformation_phases.md) · [audit-reports/TARGET-ARCHITECTURE.md](./audit-reports/TARGET-ARCHITECTURE.md) · [CONTEXT.md](./CONTEXT.md) · [docs/adr/0001](./docs/adr/0001-one-owner-for-the-tool-grant.md), [docs/adr/0002](./docs/adr/0002-cardless-agents-are-denied-every-tool.md)
**Complete findings:** [AGENT_STUDIO_FINDINGS.md](./AGENT_STUDIO_FINDINGS.md) — all 345 in full (mechanism, trigger, fix, files), the cross-cutting inventories, and the 33 gaps in this audit. **This document is the argument; that one is the reference.**
**Evidence:** [audit-reports/agent-studio-nextgen/](./audit-reports/agent-studio-nextgen/) — `backlog.json`, 24 per-slice reports and their verdicts in `raw/`.

This document does **not** supersede the plan documents. Those describe where the product is going; this one describes where it actually is, what is wrong with it in detail, and the one architecture that gets from here to the agentic system the product owner asked for.

---

## 0 · How this was produced, and what it cannot know

Twenty-four slices of the Agent Studio — every tab, both index screens, the tool catalog, the card→runtime binding, the type mirror, authorization, and code organization — were each read end to end by one agent, at the level of *UI control → API route → DB function → runtime consumer*. Every finding was then handed to a second agent whose only instruction was to **refute** it, with the standing rule that an undecidable finding is dropped rather than published.

| | |
|---|---|
| Slices audited | **24** |
| Raw findings | 349 |
| **Verified findings** | **345** — 337 CONFIRMED, 6 DOWNGRADED, 2 REFUTED and dropped, 2 duplicates of the prior audit |
| **MAJOR** | **81** |
| Prior audit (2026-08-25) | 72 findings re-checked: **61 FIXED**, 5 open, 3 partially fixed, 3 data-only |
| Agent-hours | 62 agents, ~8.5M tokens |

**What this method cannot see.** It was static: no database was queried, no test was run, no browser drove the UI. So it cannot distinguish an unenforced promise from an unused column in live data; it cannot confirm that a claimed test actually passes; and it has no runtime evidence for any latency, cache or cost claim. Those limits are recorded as work in [§6](#6--what-we-do-not-know) rather than papered over. A completeness critic re-read the audit against the source and found **33 gaps in the audit itself**, including four `checked_fine` entries whose line anchors were wrong — those are logged in `raw/completeness-critic.md` and folded into W6.

<a name="working-tree-caveat"></a>**Working-tree caveat.** `git status` moved from 8 entries at session start to **78** during the audit, because a separate "honest engines" workstream is active in the same tree (new `backend/db_inbox.py`, six new `agent_core/treatment/*` modules, migration `20260906_0107_honest_engines.py`). Those changes are **not** from this audit, which wrote only to `audit-reports/agent-studio-nextgen/`. Consequence: line numbers are accurate as read but the tree beneath them is moving. Every citation in [§4](#4--the-work) must be re-anchored at the moment it is picked up — which the fix-loop protocol in [§5](#5--the-fix-loop) makes step 1.

---

## 1 · What the Agent Studio actually is

One route (`Habibi/src/routes/prompt-studio.lazy.tsx`, 1,660 lines) renders **15 tabs** over a single editable object: a `prompt_versions` row (prompt, persona, voice, guardrails, flow, tuning) that carries an **Agent Card** in its `agent_card` column. Four screens surround it: the fleet index, the skills library, skill detail, and the sandbox. Twenty-six `/agent-studio/*` routes plus the `/prompt-versions`, `/flow`, `/eval`, `/connectors`, `/bot-deployments` and `/sandbox` families back them.

The intended pipeline is genuinely well conceived, and most of it is real:

> **author → autosave draft → compile (24 gates) → publish → one active deployment → runtime reads the bundle**

The compiler is the strongest thing in the codebase. `agent_core/cards/compile.py` runs G0–G15 plus G-OB1–9, and its gate vocabulary is honest by design — `pass`, `fail`, `warn`, `skipped`, with `CONTEXT.md` stating that *"a gate never reports green for a check it did not run"*. The Tool Grant has one owner (ADR-0001), a cardless agent is denied every tool (ADR-0002), the four locked policy engines cannot be unbound, and the outbound mission/cadence/post-call machinery is card-driven end to end.

**Where the design is real, this audit says so:** 24 slices produced 412 explicit `checked_fine` entries. The problem is not that the studio is fake. It is that the studio's *surface* has grown past its *substance*, and nothing in the system tells the operator where the edge is.

---

## 2 · The weaknesses

Nine patterns, each stated as a claim, each with finding ids you can look up in `backlog.json`.

### 2.1 The card is published as a contract and read as a suggestion

The field-by-field inventory (`raw/audit-runtime.json`) traced all **65 fields** of `AgentCard` to their runtime readers:

| Classification | Count | Meaning |
|---|---|---|
| **RUNTIME** | 36 | a real consumer reads it on a call |
| **COMPILE-ONLY** | 8 | a gate checks it; no runtime behaviour follows |
| **NONE** | **22** | **no reader anywhere** |

The 22 dead fields are not obscure corners. They include:

- **`human_gates[].tool_name` / `.require`** (`RUNTIME-01`) — the card's "require identity / floor / both before this tool" declaration. The field appears at `schema.py:389`, five times in `defaults.py`, and in the frontend type — **and nowhere else**. `ToolGrant.may_execute` (`grant.py:121-123`) is literally `return name in self.allowed`. Identity gating on voice is a hardcoded list at `voice/tools.py:516-523` and is card-independent; `floor` and `both` (supervisor approval) are implemented nowhere. The Intake card's seeded `HumanGate(handoff_to_agent, require='identity')` guarantees nothing.
- **All of `memory`** (`RUNTIME-02`) — including `scopes`, which describes what is retained about a borrower. `raw_last_n` is overridden by env `BOT_HISTORY_LIMIT`; `summarize_over_budget` has no flag to read because `compaction.py:35-50` always summarises.
- **`experiment.shadow`** (`RUNTIME-03`, `SHIP-01`) — stored in three tables, read by no router. The Ship tab's checkbox says *"log split, do not change customer treatment"*. A 25% shadow canary speaks to one borrower in four.
- **`objectives[].success` / `.partial`** (`RUNTIME-08`, `OUTBOUND-01`) — authored, gated by G-OB6, published, and then ignored: `call_closer.py:949` scores against the module-level `SUCCESS_BY_OBJECTIVE` table at `call_closer.py:102-112`.
- **`cadences[].escalate_to`** (`RUNTIME-09`) — gated by G-OB7, and `cadence.py:600 escalation_target` has no caller. An exhausted ladder escalates to no one.
- **`skills[].version` / `.pin`** (`SKILLS-01`) — `packs_for_slugs` resolves by slug only, always newest-signed. The pin is decorative.
- **`handoffs[].payload_schema`** and **`.when`** (`GRAPH-3`, `GRAPH-4`) — the `when` text sits under UI copy calling it *"guidance for the model"*; it is never rendered into any tool description or prompt.

An operator can author a retention policy, a supervisor-approval requirement, and a mission's definition of success, watch every gate go green, and change nothing.

### 2.2 Handoff is a defined word, not a mechanism

`CONTEXT.md` defines Handoff as *"transfer of a live conversation from one agent to another… **the receiving agent brings its own card, and therefore its own grant**."* The code does not do this on either channel (`GRAPH-1`).

`handoff_to_agent` (`agent_core/tools/domain.py:1009` → `db_inbox.py:1441`) updates `interactions.handler_bot_id`, writes an activity row, and instructs the model to say *"a specialist will continue"*. The voice handler returns `(result, None)` (`voice/tools.py:2773-2808`) — no node transition. The prompt, tools, flow and voice are unchanged. `handler_bot_id` is read only by analytics, QA, canary and compliance — never to load a bundle.

Worse, the allowlist that is supposed to bound it is **fail-open** (`GRAPH-2`, `RUNTIME-05`, `ORG-04`):

```python
# backend/voice/tools.py:2783-2788
allowlist: set[str] | None = None
if bot_id:
    try:
        allowlist = set(card_for(bot_id).handoff_targets())   # four Python constants
    except KeyError:
        allowlist = None                                      # → unrestricted
```

`card_for` resolves only the four first-party constants (`defaults.py:342-346`), so (a) a tenant's **published** edits to a first-party card's handoffs are ignored — voice enforces the shipped constant — and (b) any other `bot_id` yields `None`, which `domain.py:1027` (`if allowlist is not None and …`) reads as *no restriction*. The text channel was hardened and returns `set()` on a miss (`bot_tools.py:398-427`); the voice copy lost that hardening. Two implementations of one regulated control, and the weaker one guards the audio path.

### 2.3 The studio renders failure as absence

Thirty-seven `degradation-lie` findings. The pattern the repo's own audit corpus names as its #1 failure mode is still the most common defect in the newest code: an unreachable API and a correct empty state produce identical pixels, and the confident wrong answer is always the reassuring one.

- `CONNECTORS-1` — "Test" toasts **success** for a failed or SSRF-blocked connector probe.
- `OUTBOUND-06` — five live panes render a failed query as an authoritative zero.
- `FLOW-8` — a failed vocabulary fetch renders as *"No outbound missions available"* and hides the node's existing `entryFor` claims.
- `FLEET-4` — the roster's `evals: pass` lozenge is redteam-first-then-regression (`db_prompt_studio.py:478-481`), not worst-of: a card whose newest regression run **failed** shows green.
- `SKILLS-05` — the library's "signed" lozenge echoes a stored column and never verifies the signature it claims to represent.

### 2.4 Publish gates certify the wrong artifact

The compiler is rigorous about the things it checks and blind about which *version* it checked.

- `EVALS-1` — **G7/G8/G-OB9 certify a publish using the newest eval report for the `bot_id`, from any prompt version.** `eval_reports.prompt_version_id` exists (`sql/14_agent_factory.sql:46`) and the parameter exists (`db_inbox.py:1610`), but no production caller writes it and no reader filters on it. Rewrite the entire system prompt into an aggressive chase script, republish, and a report that never saw those words gates it green.
- `AUTHZ-2` — **deployment rollback re-publishes production on `BOT_WRITE` and never runs the compiler.** Every gate G0–G15, including G14 (`agent.publish`), is bypassed.
- `EVALS-3` — "Capability" is offered as a publish requirement and produces no gate at all, not even a skipped one.
- `EVALS-2` — the Twin requirement and the G11 twin gate read **different tables**; running the twin suite from the tab can never satisfy the gate that requires it.
- `AUTHZ-1` — approving a connector or refreshing its tool cache **silently widens the live Tool Grant of an already-published card**, with no republish and no gate.

### 2.5 Twenty duplicated vocabularies, eleven already drifted

The connectedness pass found 20 constants or vocabularies with two or more definitions. **Eleven have already drifted.** The pattern is exact and instructive:

> Every duplicated vocabulary that was given a cross-language drift test has held. Every one that was not has drifted.

`RollbackTrigger` has a drift test and agrees four ways. Without one: the agent tuning presets (browser copy vs `/sandbox/tuning/presets`, `SANDBOX-06`), the handoff allowlist (`ORG-04`), the reachability label vocabulary, the gate-verdict colour mapping, the seeded persona/prompt text (four copies, two repair migrations that touched only one of them), `card.experiment` vs `legacyShip`, and *"was the recording disclosure made"* — **four independent detectors** — have all separated.

### 2.6 The control surface is wider than the behaviour beneath it

Twenty-six controls were found that call nothing, or whose effect is observable nowhere. Sliders offer ranges no channel honours; selects offer modes nothing implements; toggles offer off-switches the runtime adds straight back.

- **Guardrails → "Max call duration", 120–900 s** (`GUARDRAILS-3`) — nothing ends a call on it. Voice uses a fixed `_MAX_CALL_DURATION_SECS = 10 * 60` watchdog (`voice/bot.py:164`); WhatsApp passes `elapsed=0`.
- **Guardrails → "Max turns per call", 4–40** (`GUARDRAILS-4`) — honest on no channel: sandbox hard-caps at 3, WhatsApp at 12, voice never enforces.
- **Ship → one-click rollback** — posts the **active** deployment's own id to a route that rejects exactly that id (`db_prompt_studio.py:2330`). The button always fails.
- **Tools → the "optional" toggles** for `verify_identity`, `capture_call_goal`, `load_skill`, `run_skill_script` — `VOICE_ALWAYS` adds all four back unconditionally.
- **Tools → Add** for nine flow-control verbs that are not catalog tools (`TOOLS-1`) — adding one makes G4 **fail** at publish while the tab's lozenge still shows G6 green.
- **Policy tab** — six rows, zero interactive elements, and `PolicyBinding` is `Literal["required"]`, so the only legal value is the one displayed. No runtime path reads `policy_bindings` at all; the engines take their mode from env (`reco/config.py:51-62`, `treatment/config.py:50-64`, `authority/config.py:23-36`, `live_qa/config.py:34-48`).

### 2.7 Everything an operator needs to change about routing is unauthorable

The inverse of §2.1: real behaviour that **no screen can author**, so changing it needs a code deploy.

- **Which card answers the phone** — `os.getenv("BOT_ID") or db.DEFAULT_BOT_ID` (`routing.py:34-45`, `.env.example:108`). Every inbound contact lands on Collections. Intake exists, is drawn on the fleet index, and receives nothing.
- **Which specialist a hop activates** — hardcoded to insurance in a flow action (`voice/bot.py:1518`), with the card holding only a veto.
- **Which intent loads which pack** — `INTENT_TO_SKILL`, a Python dict at `skills/runtime.py:27-35`.
- **What counts as mission success** — `SUCCESS_BY_OBJECTIVE` at `call_closer.py:102-112`.
- **The mesh role vocabulary** — `voice/mesh_roles.json`, a second tool list beside `card.tools` whose own docstring calls it *"the shape a future Agent Card subset uses"*. `active_role` is written by `activate_role` and read by nothing that changes tools or prompt.

### 2.8 The audit trail is the least trustworthy screen in the studio

- `CHANGELOG-1` — **the chain hashes the payload; the screen renders the unhashed columns.** Who, when and which agent are all forgeable without breaking the chain.
- `CHANGELOG-3` — canary rollback swaps the live deployment and writes **nothing** to the chain, including the auto-rollback the publish gates arranged.
- `CHANGELOG-2` — deleting the newest entries leaves the chain verifying clean; tail truncation is invisible.
- `CHANGELOG-4` — the chain head is read without a tenant-scoped lock; two concurrent publishes fork it.
- `AUTHZ-7` / `AUTHZ-9` — changing **who may publish an agent card** writes no audit record at all, and experiment rollback swaps live production with no entry and no actor.

### 2.9 "Test in Sandbox" does not test what "Publish" ships

`SANDBOX-01`: **the text sandbox executes zero tools.** The tool loop is gated on `_sandbox_tools_enabled(...) and customer_id`, and `customer_id` is read from a `SandboxContext` that — under `extra="forbid"` — has no field that can carry it (`schemas.py:2532`). `SANDBOX_TEXT_TOOLS` cannot turn it on. So the Tool Grant, the identity gate, connectors, always-on tools, `load_skill` and the tool audit are all unexercised.

Also different from production: the flow graph is not run at all (`flow` appears zero times in `sandbox_runtime.py`); every turn renders with the default context, not the scenario persona (`SANDBOX-02`); the prompt is assembled for channel `"text"`, which injects *"never state a call-recording disclosure even if an instruction above tells you to always disclose one"* — and then the sandbox flags the model for obeying (`GUARDRAILS-6`); and Promote from the sandbox ships a **different deployment** than Publish from the studio for the same version (`SANDBOX-08`).

The voice sandbox is much closer to production — it runs the real authored flow — but overwrites the version's authored tuning with a browser-built object (`SANDBOX-07`), and `/voice/sandbox/{id}/tune` persists nowhere but the session file.

### The four that are regulator-facing

Pulled out because they change who is contacted, what is said, or what evidence survives:

1. **`SHIP-02` — voice and outbound ignore the canary percentage entirely.** `voice/bot.py:427` calls `load_active_bundle("production", …)` with **no `customer_id`**; `deployment.py:40` forwards `customer_id=None`; `canary.py:71` reads `if pct >= 100 or not customer_id: return canary_id`. **A 5% canary sends 100% of voice calls to the candidate.** Outbound bypasses the canary in the other direction (`mission.py:516` calls `get_active_deployment` directly). `SHIP-06` compounds it: every auto-rollback trigger measures the whole bot, not the canary cohort.
2. **`GUARDRAILS-1` — WhatsApp files an RBI recording-disclosure violation on every bot turn**, while its own prompt correctly forbids the disclosure on a text thread.
3. **`SKILLS-03` / `SKILLS-04` — skill signing is decorative at the runtime boundary.** HMAC verification never reaches the runtime: an unverifiable pack still grants tools and injects its body. And importing a `.md`/`.zip` permanently overwrites a signed first-party pack — no slug guard, and boot-sync will not restore it.
4. **`GRAPH-2` — the voice handoff allowlist fails open** (§2.2).

---

## 3 · The proposed architecture — the Compiled Fleet

Three independent designs were produced and scored by three judges (voice-runtime, compliance, platform) against eight binding constraints. Two of three judges picked the same one; the full designs, scores and the synthesis are in `raw/`. What follows is the synthesis, condensed. **Every latency figure the three designs asserted was deleted**, because nothing in this tree has ever measured a prompt-cache hit — `crm_sink.py:1384` records Anthropic's field name against an Azure deployment.

### The answer to the actual question

> *"Specialized agent cards rather than the whole conversation in a generic card, agents communicating among themselves, no hardcoded flow — properly agent-studio driven."*

**Yes to the authoring model. No to a process per agent.** The authoring unit is many cards; the runtime unit is one compiled bundle with one deployment id.

**What you get.** You author as many specialist cards as you have real boundaries — Door, Collections, Insurance, Hardship, Lapse, Doc-verifier, Supervisor — each with its own persona brief, tool grant, skills, subgraph and eval fixtures, wired to each other as **typed edges** on a fleet canvas. The Door dispatches inbound by intent instead of every call landing on Collections because `BOT_ID` says so. A hop genuinely changes tools and brief: the receiving specialist brings its own grant, which is what `CONTEXT.md` already says Handoff means. `voice/flows.py`, `mesh_activate_insurance`, `INTENT_TO_SKILL`, `BOT_TO_MESH_ROLE`, `mesh_roles.json` and env `BOT_ID` are **deleted** and become card data the studio publishes. Genuine agent-to-agent consultation exists where it is honest: `consult_agent` puts a question on the existing Postgres task queue and a hardship-assessor answers it off the audio path.

**What it refuses, and why — each verified in this tree, not argued.**

1. `publish_prompt_version` (`db_prompt_studio.py:1820`) inserts a `bot_deployments` row and records a canary experiment in one transaction. If every specialist publishes itself, a regulator's *"which version said this"* resolves to a **set**.
2. A hop that changes the system prefix costs a prompt-cache miss on the one channel where sub-second turns bind. In the Compiled Fleet the system bytes do not change on a hop — the compiler emits `role_message` only on the fleet entry node, which is already how `flows_dynamic.py:363-369` behaves.
3. `TARGET-ARCHITECTURE.md:261` refuses microservices and an event bus outright. `mesh_bus.py`'s RedisBus is publish-only, `RedisBus.start()` is never called, and `BusBridgeProcessor` is not in this tree. A per-card-worker fleet bets the headline capability on unbuilt machinery.

**The honest trade, said once:** you cannot ship a fix to the Lapse specialist alone. Publishing a member promotes a version; deploying is a fleet act.

### The primitives

| Primitive | Owns | File |
|---|---|---|
| **Specialist Card** | identity, tools, skills, connectors, human gates, memory, eval, its own subgraph and its **brief** (a token-capped developer delta, not a system prompt) | `agent_core/cards/schema.py` — `AgentCard` plus `identity.kind: Literal['door','specialist','internal']` and `identity.pre_identity_safe` |
| **Handoff Edge** | the transition: `mode`, condition clauses, `carry`, `entry_node`, `return_to`, `bridge_line`, `refusal_line`, typed `payload_schema` | `schema.py` `CardHandoff`; compiles to a `go_to_<slug>.<node>` tool exactly like `flows_dynamic.py:235` |
| **Door** | greet/disclose, discover intent, verify identity, route, and the shared terminals | today's `intake-v1`, plus the door portion of `voice/flows.py` materialised through `voice/flow_export.py` |
| **Fleet** | door bot id, member closure, entry bindings (channel/number → door; objective → mission owner) | new `agent_core/fleet/schema.py` + `entry_bindings` table; replaces `runtime_entry_bot_id()` |
| **Bundle** | the compiled artifact: `prefix_text`, `prefix_hash`, namespaced graph, per-specialist grants and offers, missions, post-call, human gates, report | new `prompt_versions.compiled` jsonb on the **door's** published row; `bot_deployments.bundle_hash` pins it |
| **Carry Packet** | fact-only crossing. `PacketField` is a `Literal` with **no member for offer, waiver, amount or contact time** | `agent_core/context.py`, installed with `replace_developer('HANDOFF PACKET', …)` |
| **Human Gate enforcement** | the consumer that does not exist today | new `agent_core/tools/gates.py`, called from `voice/tools.py`'s `_traced` wrapper and `bot_tools.py` dispatch |
| **Hop ledger** | one row per hop | `interaction_handoffs` — **extended, not replaced** |

### What changes on a hop, and what it costs

- **Prompt: nothing.** The system message is `bundle.prefix_text` for the whole call. The `ACTIVE SPECIALIST` developer block is *replaced* — the same `replace_developer` path the skill runtime already survives a 30-turn call with.
- **Tools:** the target node's compiled offer; `ToolState.active_specialist` makes execution consult `grant_by_specialist`. The receiving specialist brings its own grant.
- **Flow:** an ordinary `set_node_from_config` into another namespace.
- **Voice: nothing.** No mid-call voice switching in v1 — `tts_pool.py` documents a 41-second deadlock from touching that connection mid-call.
- **Added inference: none.** One bridge line of TTS already being spoken, a pointer swap, ≤400 brief tokens, one queued DB write off the audio path.

The system-message half is true by construction and **testable in CI** by hashing the assembled system message before and after a hop. The provider-cache half is not asserted at all — see [§6](#6--what-we-do-not-know).

### The fleet gates

Numbered `G-F*` rather than continuing `G16+`, because the three source designs each assigned different meanings to G16–G21 and a gate-id collision is a support call.

`G-F1` closure · `G-F2` one door · `G-F3` identity-before-writes across every path · `G-F4` namespace + leaveability · `G-F5` prefix budget · `G-F6` door is read-only · `G-F7` **gate monotonicity** (fail an edge whose target lacks a human gate the source holds) · `G-F8` **boundary_distinct** (refuse a second member whose persona hash, authority profile, data class and regulator tags all match an existing one — *"this is a skill, not a card"*) · `G-F9` mission ownership · `G-F10` post-call merge · `G-F11` text-walkability · `G-F12` publish scope · `G-F13` hop cap · `G-F14` eval provenance.

`G-F8` is the brake. Cards are cheap to author in this design, and every extra one taxes the compiled prefix and the publish set — so a compliance officer gets a principled answer to *"I want a PTP specialist card"*, and the system can then say yes cheaply when the boundary is genuinely new.

### Migration

Seven phases, each shippable and reversible. **Phase 0 fixes what is broken today and contains no architecture and no flag** — it is the same work as W1 in [§4](#4--the-work). Phase 1 lands the bundle seam, namespacing and the human-gate consumer behind `FLEET_ENABLED=off`, and a one-member fleet must compile to today's behaviour byte for byte. Phase 2 is the real in-process hop on voice and deletes the mesh. Phase 3 splits publish from deploy and introduces the Door. Phase 4 gives WhatsApp the same compiled graph via a Pipecat-free walker. Phase 5 is eval economics and `consult_agent`. Phase 6 turns the Python-constant cards into rows. Phase 7 retires `voice/flows.py`.

Full phase-by-phase file lists, the deletion inventory, and the refusals are in `raw/synthesis-nextgen.md`.

---

## 4 · The work

Six workstreams. Each maps to one of the requests; each is independently shippable. All 345 findings are in `backlog.json` with `mechanism`, `trigger`, `fix` and `files` per item; the 81 MAJOR are tabulated in `majors-table.md`.

### W1 — Regulated correctness (ship first, alone, no architecture)

The findings that change who is contacted, what is said, or what evidence survives. **This is also Phase 0 of §3**, so it is not throwaway work.

| Do | Findings |
|---|---|
| Pass `customer_id` into the voice bundle load so the canary split is real; make outbound resolve through the canary; scope rollback triggers to the canary cohort | `SHIP-02`, `SHIP-06`, `SHIP-03` |
| Build the voice handoff allowlist from the **published card on the bundle**; delete the `KeyError → None` branch; make one implementation serve both channels | `GRAPH-2`, `RUNTIME-05`, `ORG-04` |
| Stop WhatsApp filing a recording-disclosure violation on every turn | `GUARDRAILS-1` |
| Verify skill HMAC at the runtime boundary; add a slug guard so an import cannot overwrite a signed first-party pack | `SKILLS-03`, `SKILLS-04` |
| Run the compiler on deployment rollback; align its permission with publish | `AUTHZ-2`, `SHELL-2`, `AUTHZ-3` |
| Write `eval_reports.prompt_version_id` and make G7/G8/G-OB9 filter on it | `EVALS-1` |
| Make connector approval and tool-cache refresh unable to widen a published card's grant without a republish | `AUTHZ-1` |
| Record actor + entry for permission changes and experiment rollback; hash the rendered columns, not just the payload; lock the chain head per tenant | `AUTHZ-7`, `AUTHZ-9`, `CHANGELOG-1`, `CHANGELOG-3`, `CHANGELOG-4`, `CHANGELOG-2` |

### W2 — Studio truthfulness (37 `degradation-lie` + 26 disconnected controls)

One rule, applied everywhere: **a control either works, is disabled with a reason, or is deleted; and a failed read never renders as a fact.** Every one of the 37 is a small, local diff. Start with the ones that give business advice on an error (`CONNECTORS-1`, `OUTBOUND-06`, `FLOW-8`), then the false-green lozenges (`FLEET-4`, `SKILLS-05`), then the sliders whose ranges no channel honours (`GUARDRAILS-3`, `GUARDRAILS-4`).

### W3 — Tool definitions, parameters, usage, attachment (the `catalog` slice, 15 findings)

`agent_core/tools/catalog.py` registers 26 `ToolSpec`s that three renderers fan out to Pipecat, OpenAI-strict and MCP. The audit checked every spec against every handler for arg-name drift, enum-vs-`CHECK`-constraint drift, channel-flag vs actual registration, and result-shape drift. Headline: `CATALOG-2` — **both `TEXT_ONLY` tools are unreachable, and the WhatsApp prompt instructs the model to call one of them.** Also `CATALOG-5`: the "read-only" MCP surface writes a commercial event, un-attributed. Fix the drift, then add the drift test — §2.5 shows a test is the only thing that has ever held a duplicated vocabulary together.

### W4 — Dead config: connect it or delete it (44 findings)

For each of the 22 dead card fields and the 26 disconnected controls, exactly one of:

- **Connect it** — `human_gates` gets `agent_core/tools/gates.py`; `objectives[].success` replaces `SUCCESS_BY_OBJECTIVE`; `cadences[].escalate_to` gets a caller; `experiment.shadow` gets a router branch; `guardrails.maxSeconds` replaces the fixed 10-minute watchdog.
- **Delete it** — from the schema, the TS type, the UI and the gate, in one commit.

Nothing stays in the middle. A field that is gated at publish and read by nobody is worse than an absent field, because the gate is what makes the operator believe it works.

### W5 — Code cleanup and organization (7 findings + the structural items)

`main.py`'s studio block → routers, with a consistent authz dependency. `AgentCardPanels.tsx` (1,047 lines, six tabs) and `prompt-studio.lazy.tsx` (1,660 lines) split by tab. One handoff-allowlist implementation. Collapse the 11 drifted vocabularies onto one owner each and **pin every one with a drift test**. Note that `TARGET-ARCHITECTURE.md §6.9` refuses a `bot`→`mouth` rename as a data migration, so naming is fixed only where a file is already being rewritten.

### W6 — Tests (8 findings + the 33 audit gaps)

The frontend has 19 test files and 3 touch the studio; there is no regression net under 42 unaudited hooks and 76 handlers. Add: the CI system-message-hash assertion, a drift test per collapsed vocabulary, one test per W1 fix, and the four cheap runtime checks in [§6](#6--what-we-do-not-know). Also re-anchor the four `checked_fine` entries the completeness critic found citing wrong lines (`raw/completeness-critic.md`).

---

## 5 · The fix loop

The page-by-page pass, as a protocol rather than a list. One tab per pass, in this order — **Ship, Evals, Skills, Connectors, Change log, Guardrails, Outbound, Flow, Tools, Agent graph, Sandbox, Fleet, Prompt, Persona, Voice, Bindings, Policy, Header** — ordered by regulated exposure, not by tab position.

For each tab:

1. **Re-anchor.** Pull its findings from `backlog.json` (`slice == <tab>`) and re-read every cited line. The tree is moving (see the [working-tree caveat](#working-tree-caveat)); a stale line number is the most likely cause of a wrong fix.
2. **Inventory the controls.** Every clickable, every field. For each: what it calls, what it invalidates, what it renders on pending/error/empty, and which runtime consumer reads what it writes.
3. **Decide W4 for each dead one** — connect or delete. Record the decision in the commit message.
4. **Fix W1 items first**, then W2, then the rest. One concern per commit.
5. **Add the test** that would have caught it. For a vocabulary, the test is a drift test.
6. **Update this document's tab section** with what was decided, so the next pass starts from the decision rather than re-deriving it.

**Definition of done for a tab:** no control on it can lie; every field it writes has a named runtime consumer or is gone; its vocabularies have one owner and a drift test; and its findings in `backlog.json` are closed with a commit sha.

---

## 6 · What we do not know

Every item here was asserted with confidence by at least one source design or audit slice, and none has evidence in this tree. Each is an instrument to build, not a claim to repeat.

1. **Has any Habibi voice call ever registered a prompt-cache hit?** No voice code reads a cached-token count. Until it does, every hit/miss latency delta — including this document's — is a projection. *Cheap check: add `usage.prompt_tokens_details.cached_tokens` to `crm_sink.py:1384`.*
2. **Does changing the tool-schema set per node invalidate the provider's cached prefix?** This is the load-bearing assumption under "a hop costs nothing". Every authored node already changes `NodeConfig.functions` and nothing measures it. *Measure across an ordinary transition inside one specialist before shipping any cross-member hop.*
3. **Does a replaced `ACTIVE SPECIALIST` developer block survive summarisation?** The mechanism is real; nothing asserts the block survives a context collapse.
4. **What does `LLMSummarizeContextFrame` actually cost?** Queued at `voice/bot.py:1506`; latency recorded nowhere. Until measured, `carry='summary'` is not an authorable option.
5. **Which "dead config" fields are dead in *data* as well as in code?** No database was queried. *Cheap check: `docker exec collections_db psql -U collections` and count non-default values per field before deleting any.*
6. **Do the tests this audit cites as pins actually pass?** The suite has known failures and six new untracked test files. *Cheap check: run it in the voice container.*
7. **Is any "zero readers" claim defeated by reflective access?** Established by name search. *Cheap check: grep for `agent_card.get(`, `card.get(` and `getattr(card`.*
8. **What happens under concurrency?** Two publishes of different bots racing the tenant-scoped hash chain (`CHANGELOG-4`), and two sandbox turns on one run, were never exercised.

---

## Appendix A — the 81 MAJOR findings

This is an index, not the findings. **Every finding in full — mechanism, trigger, proposed fix, files — is in [AGENT_STUDIO_FINDINGS.md](./AGENT_STUDIO_FINDINGS.md)**, which also carries the 206 MINOR and 58 trivial ones omitted here, the cross-cutting inventories (20 drift pairs, 38 writes with no reader, 16 behaviours no tab can author, 27 dead controls, 12 tab dependencies, 20 doc-vs-code contradictions), and the 33 gaps in this audit. It is generated from `backlog.json` by `render_findings.py` — edit the data, not the document.

The table below is the same 81 rows as `majors-table.md`, sorted by severity then slice.

| # | Slice | Category | Finding | Primary file |
|---|---|---|---|---|
| `AUTHZ-1` | Authorization | security | Approving a connector or refreshing its tool cache silently widens the live Tool Grant of an already-published card — INTEGRATIONS_WRITE, no publish gate, no change-log entry | `backend/agent_core/skills/intersect.py:117-123` |
| `AUTHZ-2` | Authorization | security | Deployment rollback re-publishes production on BOT_WRITE and never runs the compiler — every gate G0-G15, including G14 agent_publish, is skipped | `backend/db_prompt_studio.py:2292` |
| `AUTHZ-3` | Authorization | security | PATCH /prompt-versions/{id} accepts `agentCard` on BOT_WRITE, so AGENT_EDIT is unenforceable for card authoring | `backend/schemas.py:2388` |
| `AUTHZ-6` | Authorization | security | G13 (A2A mTLS) is satisfied by a self-asserted DN string that an INTEGRATIONS_WRITE holder types in, and it ignores the bot it is asked about | `backend/agent_core/a2a.py:222` |
| `AUTHZ-7` | Authorization | security | Changing who may publish an agent card writes no audit record at all | `backend/db.py:215` |
| `AUTHZ-9` | Authorization | security | Canary/experiment rollback swaps the live production deployment with no change-log entry and no actor recorded anywhere | `backend/agent_core/canary.py:136` |
| `BINDINGS-2` | Bindings | bug | Slot switch keeps the previous slot's modelId; nothing on any layer checks model.kind == binding.slot | `Habibi/src/components/prompt-studio/BindingsTab.tsx:49` |
| `BINDINGS-3` | Bindings | degradation-lie | The model picker offers unconfigured, preview-only and unconstructable models with no marking; binding one renders green and silently runs Azure | `Habibi/src/components/prompt-studio/BindingsTab.tsx:105` |
| `CATALOG-2` | Tool catalog | disconnected | Both TEXT_ONLY catalog tools are unreachable, and the WhatsApp prompt tells the model to call one of them | `backend/agent_core/tools/catalog.py:213-232` |
| `CHANGELOG-1` | Change log | security | The chain hashes the payload; the screen renders the unhashed columns — who, when and which agent are all forgeable under a green "Chain intact" | `backend/agent_core/change_log.py:150` |
| `CHANGELOG-2` | Change log | bug | Deleting the newest entries leaves the chain verifying clean — tail truncation is invisible, and verify_chain never checks seq contiguity | `backend/agent_core/change_log.py:349` |
| `CHANGELOG-3` | Change log | bug | Canary rollback swaps the live deployment and writes nothing to the chain — including the auto-rollback the publish entry promised | `backend/agent_core/canary.py:136` |
| `CHANGELOG-4` | Change log | bug | The chain head is read without a tenant-scoped lock — two concurrent publishes of different bots fork the chain into a permanent, unclearable "tampered with" banner | `backend/agent_core/change_log.py:120` |
| `CONNECTORS-1` | Connectors | degradation-lie | "Test" toasts success for a failed or SSRF-blocked health probe, and a blocked probe leaves health untouched | `Habibi/src/components/integrations/McpConsole.tsx:108` |
| `CONNECTORS-3` | Connectors | bug | Re-saving an existing connector through "Add connector" silently reverts approved → draft | `Habibi/src/components/integrations/McpConsole.tsx:148` |
| `CONNECTORS-4` | Connectors | bug | "Connect IdP" always writes the CIMD issuer to rows[0], not to a selected connector | `Habibi/src/components/integrations/McpConsole.tsx:192` |
| `CONNECTORS-5` | Connectors | disconnected | Bind/Unbind in the Connectors tab changes nothing any model can ever call — ext.* is in the Grant but in no Offer, and voice has no ext handler at all | `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:1003` |
| `CONNECTORS-6` | Connectors | bug | A binding to a connector that is no longer approved disappears from the tab, leaving no way to unbind it and a permanently unpublishable card | `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:925` |
| `EVALS-1` | Evals | bug | G7/G8/G-OB9 certify a publish with the newest report for the BOT, from any prompt version — prompt_version_id is written by nobody | `backend/db_prompt_studio.py:1914` |
| `EVALS-2` | Evals | disconnected | The Twin requirement and the G11 twin gate read different tables — running the twin suite from the tab can never satisfy the gate | `backend/agent_core/cards/compile.py:721` |
| `EVALS-3` | Evals | dead-config | "Capability" is offered as a publish requirement and gates nothing | `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:255` |
| `FLEET-1` | Fleet index | degradation-lie | Reachability chip is computed from the DRAFT card's handoffs, not the published one the runtime enforces | `backend/db_prompt_studio.py:429-430` |
| `FLEET-2` | Fleet index | disconnected | 'via handoff' on the voice channel is not backed by the card at all: voice allowlist is the Python default, and unrestricted for clones | `backend/voice/tools.py:2783-2788` |
| `FLEET-3` | Fleet index | bug | An archived card can be edited and published back into production; the fleet then shows 'archived · takes no traffic' beside 'deployed · 100%' | `Habibi/src/routes/agent-studio.index.tsx:673-686` |
| `FLEET-4` | Fleet index | degradation-lie | evalStatus lozenge reports 'pass' when the latest redteam passed even if the latest regression suite failed | `backend/db_prompt_studio.py:478-481` |
| `FLOW-1` | Flow | bug | GET /flow/built-in cannot run in the API container: import chain requires pipecat | `backend/main.py:2068-2081` |
| `FLOW-2` | Flow | bug | Built-in export marks only call_ended as endConversation — wrap_up, terminate_politely and escalate_close stop hanging up once reloaded and published | `backend/voice/flow_export.py:187` |
| `FLOW-3` | Flow | disconnected | Tool picker, /flow/validate and G1 accept any catalog tool; the card's Tool Grant silently drops it at runtime and the canvas still counts its hop as an exit | `Habibi/src/components/flow/FlowInspector.tsx:406-435` |
| `FLOW-4` | Flow | degradation-lie | A version flagged flowUnreadable is silently overwritten with the empty sentinel by the first autosave, while the tab says 'Nothing has been changed' | `backend/db_prompt_studio.py:155-174` |
| `FLOW-5` | Flow | bug | Captured yes/no variables serialise as 'True'/'False' while identity_verified is 'true'/'false' — an `equals true` expression edge on a captured boolean never fires | `backend/voice/flows_dynamic.py:246-256` |
| `GRAPH-1` | Agent graph | doc-vs-code | Doc vs code: a handoff never loads the receiving card's prompt, tools or flow on either channel | `CONTEXT.md:46-48` |
| `GRAPH-2` | Agent graph | security | Voice handoff allowlist reads the built-in card constants, not the published card, and disables itself on clone-card deployments | `backend/voice/tools.py:2781-2788` |
| `GRAPH-3` | Agent graph | dead-config | The `when` condition is stored but never reaches the model; the tab tells the author it is 'guidance for the model' | `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:669-673` |
| `GUARDRAILS-1` | Guardrails | bug | WhatsApp files an RBI recording-disclosure violation on every bot turn while its own prompt forbids the disclosure | `backend/agent_core/guardrails.py:240-243` |
| `GUARDRAILS-2` | Guardrails | degradation-lie | 'Hard-blocks' hints are true only in the sandbox; on voice and WhatsApp the rule is evaluated after the reply was spoken/sent | `Habibi/src/components/prompt-studio/GuardrailsPanel.tsx:28-45` |
| `GUARDRAILS-3` | Guardrails | dead-config | maxSeconds ('Max call duration') has no consumer that ends a call; voice uses a fixed 10-minute cap and WhatsApp passes elapsed=0 | `Habibi/src/components/prompt-studio/GuardrailsPanel.tsx:157-170` |
| `GUARDRAILS-4` | Guardrails | degradation-lie | maxTurns slider range 4-40 is honest on no channel: sandbox caps at 3, WhatsApp at 12, voice never enforces | `Habibi/src/components/prompt-studio/GuardrailsPanel.tsx:145-156` |
| `ORG-04` | Organization | code-organization | One handoff allowlist, two implementations: bot_tools' is hardened, voice/tools' is a copy that lost both hardenings | `backend/bot_tools.py:398-427` |
| `OUTBOUND-01` | Outbound | dead-config | 'Closes the case' and 'Partly worked' are authored, gated, published — and the Closer never reads them | `Habibi/src/components/prompt-studio/OutboundCardEditor.tsx:536-552` |
| `OUTBOUND-02` | Outbound | disconnected | Cadence retries dial as DEFAULT_BOT_ID, so every attempt after the first runs the wrong card | `backend/cadence.py:418` |
| `OUTBOUND-03` | Outbound | disconnected | The caller-ID pool the card names is honoured by campaigns only — engine dials and retries ignore it | `backend/campaigns.py:539` |
| `OUTBOUND-04` | Outbound | disconnected | `direction` is not a kill switch: a card switched to inbound keeps dialling, including mid-campaign | `Habibi/src/components/prompt-studio/OutboundTab.tsx:455` |
| `OUTBOUND-06` | Outbound | degradation-lie | Five live panes render a failed query as an authoritative zero or empty state | `Habibi/src/components/prompt-studio/OutboundTab.tsx:626` |
| `PERSONA-1` | Persona | degradation-lie | Persona language never binds the recogniser on a real call — every tuning reaching resolve_session_tuning is pre-normalised to stt.language='en-IN', which the function treats as an explicit override | `backend/voice/tuning_apply.py:417` |
| `PROMPT-1` | System Prompt | stale | The seeded prompt_versions rows still carry the CRM tokens and the duplicate disclosure; only persona_presets were ever repaired | `backend/alembic/versions/20260722_0018_prompt_studio_schema_seed.py:36` |
| `PROMPT-2` | System Prompt | bug | A spaceless flow token naming a CRM field silently deletes its line, while the lint and the editor both say the braces are read aloud — and the CRM warning is masked away | `backend/prompt_lint.py:65` |
| `PROMPT-3` | System Prompt | bug | A failed deterministic lint renders as a clean prompt: the prohibited-word ERROR and both recording-disclosure findings exist only server-side and have no error or pending surface | `Habibi/src/routes/prompt-studio.lazy.tsx:569` |
| `PROMPT-9` | System Prompt | disconnected | Nothing gates or even mentions the lint at publish — a prompt whose every CRM line will be deleted ships warn-only, and the publish dialog never sees the findings | `backend/main.py:3286` |
| `RUNTIME-01` | Card→runtime | dead-config | human_gates is enforced nowhere — the card's identity/floor requirement has no reader at all | `backend/agent_core/cards/schema.py:53` |
| `RUNTIME-02` | Card→runtime | dead-config | card.memory is dead in its entirety — including the scopes that describe what is retained about a borrower | `backend/agent_core/cards/schema.py:144-155` |
| `RUNTIME-03` | Card→runtime | degradation-lie | experiment.shadow never reaches routing — a shadow canary serves real callers | `backend/agent_core/canary.py:57-77` |
| `RUNTIME-05` | Card→runtime | bug | voice handoff_to_agent allowlists against the built-in card, not the live one — and denies nothing when the bot is not first-party | `backend/voice/tools.py:2773-2797` |
| `RUNTIME-06` | Card→runtime | security | a2a.expose and a2a.skill_ids are both dead: the well-known card is served for any bot to any authenticated partner, and lists card.skills instead | `backend/main.py:2711-2721` |
| `RUNTIME-07` | Card→runtime | bug | the A2A partner card is rendered from the DRAFT card, not the published one | `backend/agent_core/a2a.py:74-77` |
| `RUNTIME-08` | Card→runtime | stale | CardObjective.success does not decide whether a mission succeeded — the closer uses a hardcoded table, and both the comment and the Outbound tab say otherwise | `backend/call_closer.py:99-112` |
| `RUNTIME-09` | Card→runtime | dead-config | cadence.escalate_to is gated at publish and read by nobody — an exhausted ladder escalates to no one | `backend/cadence.py:600-604` |
| `RUNTIME-13` | Card→runtime | bug | outbound.direction never blocks a dial — an inbound-only card is dialled from, and the objective guard is skipped precisely when the card forbids dialling | `backend/agent_core/treatment/enact.py:358-370` |
| `RUNTIME-14` | Card→runtime | bug | cadence retries are always placed as the tenant default bot, so the ladder abandons the card that opened it | `backend/cadence.py:418-440` |
| `SANDBOX-01` | Sandbox | disconnected | Test in Sandbox executes zero tools — the Tool Grant is never exercised, and SANDBOX_TEXT_TOOLS cannot turn it on | `backend/sandbox_runtime.py:852` |
| `SANDBOX-02` | Sandbox | bug | Every sandbox turn renders the prompt with the default context, not the scenario persona | `backend/sandbox_runtime.py:529` |
| `SANDBOX-06` | Sandbox | stale | Tuning presets are a second, drifted copy in the browser; the server endpoint that exists to prevent this has no caller | `Habibi/src/components/sandbox/TuningStudio.tsx:112` |
| `SANDBOX-07` | Sandbox | bug | The voice sandbox overwrites the version's authored tuning with a tuning object the browser built | `backend/voice/bot.py:411` |
| `SANDBOX-08` | Sandbox | bug | Promote from the Sandbox ships a different deployment than Publish from Prompt Studio, for the same version | `Habibi/src/routes/sandbox.lazy.tsx:442` |
| `SHELL-2` | Editor shell | security | Rollback (a production re-publish) is gated by BOT_WRITE while publish needs AGENT_PUBLISH; card edits via the editor need only BOT_WRITE although the card route demands AGENT_EDIT | `backend/db_prompt_studio.py:2347-2404` |
| `SHIP-01` | Ship | dead-config | `shadow` is stored in three tables and read by no router — a "shadow" canary sends real customer calls to the candidate | `Habibi/src/components/prompt-studio/ShipTab.tsx:169` |
| `SHIP-02` | Ship | bug | Voice and outbound ignore the canary percentage entirely — 100% of calls hit the candidate | `backend/agent_core/canary.py:71` |
| `SHIP-03` | Ship | bug | The `slo_miss` trigger compares call length against a latency budget — enabling it rolls back every canary on the next sweep | `backend/agent_core/canary.py:292` |
| `SHIP-05` | Ship | bug | Manual deployment rollback does not stop a running canary — traffic keeps going to the rolled-back candidate, and no gate is re-run | `backend/db_prompt_studio.py:2292` |
| `SHIP-06` | Ship | bug | Every auto-rollback trigger measures the whole bot, not the canary cohort — the baseline's failures roll back the candidate and vice versa | `backend/agent_core/canary.py:206` |
| `SKILLS-01` | Skills | dead-config | The Agent Card's skill version pin is decorative — the runtime always loads the newest signed row | `backend/agent_core/cards/schema.py:102-107` |
| `SKILLS-02` | Skills | bug | "Revert to signed" / "Restore" changes the Studio display but not what the mouth loads | `backend/agent_core/skills/persist.py:445-471` |
| `SKILLS-03` | Skills | security | Skill HMAC verification never reaches the runtime — an unverifiable pack still grants tools and injects its body | `backend/agent_core/skills/persist.py:91-100` |
| `SKILLS-04` | Skills | security | Importing a .md/.zip permanently overwrites a signed first-party pack — no slug guard, and boot-sync will never restore it | `backend/main.py:2451-2481` |
| `SKILLS-05` | Skills | degradation-lie | The library's "signed" lozenge echoes a stored column and never verifies the signature it claims to represent | `backend/agent_core/skills/persist.py:60` |
| `SKILLS-06` | Skills | bug | API restart silently demotes an operator's signed edit of a first-party skill back to the platform version | `backend/agent_core/skills/persist.py:729-765` |
| `SKILLS-08` | Skills | dead-config | A pack's declared `mouth:` channels are parsed and never enforced — internal-only skills ride on a customer-facing card | `backend/agent_core/skills/pack.py:31` |
| `SKILLS-09` | Skills | shape-mismatch | load_skill tells the model it may call tools that are not in its grant or renderable on its channel | `backend/agent_core/skills/runtime.py:280-284` |
| `SKILLS-10` | Skills | degradation-lie | "Load in sandbox" always falls back to kaia-v2-4 for the only skills you can actually author, producing a run that exercises nothing | `Habibi/src/routes/agent-studio.skills.$skillId.tsx:192-206` |
| `TOOLS-1` | Tools | bug | Tools tab offers Add for nine flow-control verbs that are not catalog tools; Add makes G4 fail while the tab shows G6 green | `Habibi/src/components/prompt-studio/AgentCardPanels.tsx:154-181` |
| `VOICE-1` | Voice (TTS) | bug | Catalog Refresh is Azure-only but its soft-removal is not provider-scoped: it either marks every non-Azure voice removed (forcing runtime fallback to Aarti) or, as today, silently skips all removals while toasting 'Catalog refreshed' | `backend/tts_catalog_sync.py:212` |
| `VOICE-2` | Voice (TTS) | dead-config | Bindings-tab voiceRef is dead config and a provider/voice mismatch is never checked: the Voice tab's short name is force-fed to whatever TTS service is bound (or the Azure fallback) | `backend/agent_core/providers/factory.py:226-227` |

## Appendix B — evidence layout

```
AGENT_STUDIO_FINDINGS.md    all 345 in full + cross-cutting inventories + audit gaps (generated)
audit-reports/agent-studio-nextgen/
  backlog.json              all 345 verified findings, ranked — the source of truth
  majors-table.md           the 81 MAJOR, generated
  harvest.py                re-extract agent results from a workflow journal by run id
  merge.py                  re-merge audits + verdicts into backlog.json
  render_findings.py        regenerate AGENT_STUDIO_FINDINGS.md from backlog.json
  raw/
    audit-<slice>.json      x24  summary, endpoints, runtime consumers, findings, checked_fine
    verdicts-<slice>.json   x24  the adversarial verdict on every finding
    audit-runtime.json           the 65-field AgentCard → runtime inventory
    connectedness.json           20 double sources of truth, tab dependencies, 26 disconnected controls, 9 themes
    completeness-critic.md       33 gaps in the audit itself
    design-*.json           x3   the three candidate architectures
    judge-*.json            x3   scores against the eight constraints
    synthesis-nextgen.md         the Compiled Fleet proposal in full
    prior-*.json            x2   status of all 72 findings from the 2026-08-25 audit
```
