## Thesis

Start from **Ensemble** (highest scoring, best on C1 and C2, and the only design two of three judges picked), absorb the grafts the judges named, and fix the three fatal flaws. The result is the **Compiled Fleet**.

**What you get, exactly as you asked for it.** You author as many specialist cards as you have real boundaries — Door, Collections, Insurance, Hardship, Lapse, Doc-verifier, Supervisor — each with its own persona brief, its own tool grant, its own skills, its own subgraph, its own eval fixtures. You wire them to each other on a fleet canvas as typed edges. The Door dispatches inbound contacts by intent instead of every call landing on Collections because `BOT_ID` says so. A hop really does change the tools and the brief: the receiving specialist brings its own grant, which is what `CONTEXT.md` says Handoff means and what the code does not do today. Nothing about inbound or outbound routing stays hardcoded — `voice/flows.py`, `mesh_activate_insurance` (`voice/bot.py:1519`), `INTENT_TO_SKILL` (`agent_core/skills/runtime.py:28-36`), `BOT_TO_MESH_ROLE`, `voice/mesh_roles.json` and env `BOT_ID` are all deleted and become card data the studio publishes. And you get genuine agent-to-agent communication where it is honest: `consult_agent` puts a question on the existing task queue and a hardship-assessor or doc-verifier answers it off the audio path.

**What it refuses, and why.** A specialist is not a separately deployed runtime agent. **The authoring unit is many cards; the runtime unit is one compiled bundle with one deployment id.** Three reasons, all verified in this tree rather than argued:

1. `db_prompt_studio.publish_prompt_version` (line 1820) inserts a `bot_deployments` row with `environment='production', status='active'` and calls `canary.record_experiment` in the same transaction. If every specialist publishes itself, every specialist gets its own release id and its own canary — and a regulator's "which version said this" resolves to a *set*. That is the audit fragmentation C2 forbids.
2. A hop that changes the system prefix costs a prompt-cache miss on the one channel where sub-second turns bind. In the Compiled Fleet the system message bytes do not change on a hop, because `flows_dynamic.py:363-369` emits `role_message` only on the entry node and the compiler emits it only on the *fleet* entry node.
3. `audit-reports/TARGET-ARCHITECTURE.md:261` refuses microservices and an event bus outright. `voice/mesh_bus.py`'s RedisBus is publish-only and `RedisBus.start()` is never called; `BusBridgeProcessor` is not in this tree. A per-card-worker fleet is a bet on machinery that does not exist.

Also refused: parallel specialists reasoning concurrently on a live call; mid-call voice switching (v1); free-text negotiation between agents on the audio path; and a blank canvas — `agent_transformation_plan.md` names that the trap and this design agrees.

The honest trade, said once: **you cannot ship a fix to the Lapse specialist alone.** Publishing a member promotes a version; deploying is a fleet act. That is the price of one release id, and it is the price the eval cache and the fleet canary are built to make cheap.

---

## Primitives (what each noun owns, and the file that owns it)

| Primitive | Owns | File |
|---|---|---|
| **Specialist Card** | identity, `tools.include`/`locked`, `skills[]`, `connectors[]`, `human_gates[]`, `memory`, `eval`, its own subgraph (`prompt_versions.flow`) and its **brief** (`prompt_versions.prompt`, now a token-capped developer delta, not a system prompt) | `backend/agent_core/cards/schema.py` — `AgentCard` unchanged in shape, plus `identity.kind: Literal['door','specialist','internal']` and `identity.pre_identity_safe: bool` |
| **Handoff Edge** | the transition: `mode: Literal['model','expression','always']`, `clauses[]` over `flows_dynamic.SESSION_VARIABLES`, `carry: Literal['brief','full']`, `entry_node`, `return_to`, `bridge_line`, `refusal_line`, typed `payload_schema` | `schema.py` `CardHandoff`; compiles to a `go_to_<slug>.<node>` schema exactly like `flows_dynamic.py:235 _transition_tool` |
| **Door** | greet/disclose, discover_intent, verify_identity, the `route` node, and the shared terminals (`pre_close`, `call_ended`, `terminate_politely`, `escalate_close`) | today's `intake-v1` (`agent_core/cards/defaults.py:158-174`), plus the door portion of `voice/flows.py` materialised through `voice/flow_export.py` |
| **Fleet** | door bot id, member closure, entry bindings (channel/number → door; objective → mission owner), publish lifecycle | new `backend/agent_core/fleet/schema.py`; new `entry_bindings` table; replaces `agent_core/cards/routing.py:34-45 runtime_entry_bot_id()` and `.env.example:108` |
| **Bundle** | `{schema_version, prefix_text, prefix_hash, graph (nodes keyed <slug>/<key>), specialists{slug:{bot_id, prompt_version_id, card_hash, flow_hash, prompt_content_hash, brief, skills[]}}, grant_by_specialist{}, offer_by_node{}, missions{objective→node}, post_call{}, human_gates{tool→require}, report}` | new column `prompt_versions.compiled jsonb` on the **door's** published row; `bot_deployments.bundle_hash` pins it; `agent_core/deployment.py load_active_bundle` returns it |
| **Fleet Compiler** | the fleet gates, run *after* `cards/compile.py` per member and once on the synthesised union card | new `backend/agent_core/fleet/compile.py`, wrapping `agent_core/cards/compile.py` (G0–G15, G-OB1–9) |
| **Active Grant** | which tools the *speaking* specialist may execute | `agent_core/tools/grant.py` gains `for_specialist(bundle, slug, channel)`; `voice/tools.py` `ToolState.active_specialist`; the one-shot `keep = set(allowed_tool_names) | ALWAYS_ON` at `voice/tools.py:2918` becomes a per-turn lookup into `grant_by_specialist` |
| **Human Gate enforcement** | the consumer that **does not exist today** | new `backend/agent_core/tools/gates.py`, called from `voice/tools.py`'s `_traced` wrapper and from `bot_tools.py` dispatch. Verified: `human_gates` appears only at `schema.py:389` and `defaults.py:131/150/171/312/328`; `ToolGrant.may_execute` (`grant.py:121-123`) is literally `return name in self.allowed`. Until this file exists, `card.human_gates` is a comment that reads as a control |
| **Carry Packet** | fact-only crossing: `identity_verified`, `disclosure_done`, `call_goal`, `call_goal_intent`, `language`, `sentiment`, `commitments[]` copied **from rows the tools wrote**, mission envelope refs, `open_questions[]`, `last_n_turns`. `PacketField` is a `Literal` with **no member for offer, waiver, amount or contact time** | `backend/agent_core/context.py` `handoff_packet_message()`, installed with `replace_developer('HANDOFF PACKET', …)` so a second hop evicts the first |
| **Namespaced node key** | that two members may both own `wrap_up` | `flow_graph.py` (key grammar accepts `<slug>/<key>`), `voice/flows_dynamic.py build_authored_flow(namespace=…)`, and `voice/tools.py:426 _node(name)` resolving `f"{state.active_specialist}/{name}"` first, then the door namespace |
| **Text Walker** | the Pipecat-free interpreter of the same compiled graph | new `backend/flow_walker.py`, state in `conversations.bot_state`, reusing `voice/flow_vars.evaluate_condition` |
| **Consult** | agent-to-agent, off the audio path | `agent_core/mcp_http/tasks.py` — `ALLOWED_KINDS` gains `'agent_consult'`; result delivered via `inject_developer` (`voice/bot.py:824`) |
| **Hop ledger** | one row per hop | `interaction_handoffs` (`sql/04_interactions.sql:61-77`), **not** a new table — extended with `turn_index`, `deployment_id`, `carry`, `packet jsonb` and widened `reason` CHECK |
| **Prefix Warmer** | per-worker periodic keep-warm | new `backend/voice/prefix_warm.py`. This is **new code, not an extension** — `_warm_llm_service` (`voice/bot.py:2586`) sends no request; it pays a measured 2.46 s class init. `llm_pool.prewarm_shared_client` (`llm_pool.py:174`) sends `"Reply with: ok"` and warms TLS. Use `max_output_tokens=16`; `llm_pool.py:137-141` documents that `1` returns a 400 on gpt-5.x |
| **Hop metrics** | whether the amortisation worked | new `backend/voice/hop_metrics.py`: `hop.ttfb_ms` p50/p95, `hop.cached_tokens` ratio, `hop.cover_ms` (bridge-line audio duration minus first-token latency; positive means the miss was hidden), `hops_per_call`, `misroute_rate` |

---

## Runtime model

### Inbound voice — door → specialist → handoff → close

1. **Entry.** `voice/bot.py run_bot` calls `fleet.routing.resolve_entry(channel='voice', address=to_number)` → the door bot id, then `load_active_bundle(bot_id=door, customer_id=…)`. Today `bot.py:427` loads `'production'` before it knows who is calling, which falls through to `db.DEFAULT_BOT_ID = kaia-v2-4` — that is why Intake receives nothing. Canary is decided **once** here by `canary.pick_deployment_id` hashing the door DEP and the customer id; there is exactly one active deployment per (door, environment) by `uq_bot_deployments_bot_env_active` (`sql/09_bot_config.sql:264`), so the whole call is on one side of the split by construction.
2. **Prefix.** `prefix_text` = door prompt + door persona + **the union of every member's guardrail rules** + the sorted skill description block. The guardrail union is load-bearing: `voice/natural.py:182-184` puts `guardrail_rules(guardrails, channel='voice')` verbatim into the system message, and a door-only prefix would silently demote a specialist's compliance text to an evictable developer block. Because the prefix is compiled once at publish, the union is byte-identical per deployment and costs nothing at runtime.
3. **Graph.** `build_authored_flow(session, compiled.graph, objective='inbound')` — same engine, bigger graph; entry is the door's `isStart` node. The compiler emits `role_message` **only** on that node.
4. **Door.** `greet_disclose` → `discover_intent` (`capture_call_goal` writes `session.call_goal_intent`) → `verify_identity` → `route`. The route node's outgoing edges are the door's `handoffs[]`: expression edges on `call_goal_intent` fire deterministically through the existing `_advance_action`; model-chosen `go_to_<slug>` transitions cover the ambiguous case. The door can hold no write tool (G-F6).
5. **Specialist.** Its subgraph runs. Each node offers `node.data.tools ∩ grant_by_specialist[slug]` plus its transitions. Skills load as today (`load_skill` → `replace_developer(SKILL_BODY_PREFIX, …)`, `voice/tools.py:2827`). Locked engines are on every member's grant by G3.
6. **Hop.** An edge fires → `pre_actions = [tts_say(bridge_line), render_carry, specialist_enter(slug)]` → `replace_developer('ACTIVE SPECIALIST', brief + persona_delta)`, `ToolState.active_specialist = slug`, RTVI emits `flow.specialist`, and `CrmSink` queues one `interaction_handoffs` row off the audio path.
7. **Close.** Every specialist exit edges to a door-owned terminal (G-F2). `end_call` → close probe → `_node('call_ended')` → `CrmSink complete` → `call_closer.py`. Inbound reserves a `call_attempts` row with `purpose='in_session'` (already a legal value, `sql/21_outbound.sql:34`) so both directions close through one queue. `post_call_actions` runs the merged `bundle.post_call`.

### Outbound mission → dial → specialist → close

`treatment/enact.py enact_one` → `outbound.place` runs the fixed sequence `reserve → contact_policy.admit → suppress-on-refusal → place`; `mission.build` resolves the mission owner through `entry_bindings(objective)` (G-F9: exactly one member per objective). `call_attempts.deployment_id` is **pinned at dial**, so a publish mid-campaign cannot change a live attempt's version. On answer, `bot.py` reads `attempt_id/objective/treatment_decision_id` from the stream params, loads the bundle by the pinned DEP, sets `session.extra['entry_node'] = compiled.missions[objective]`, and enters the mission owner's subgraph at `confirm_identity`. **Outbound never enters through the Door** — the dialler already knows the objective; the compiler refuses an outbound entry binding that resolves to a `kind='door'` card. Mission latches (`upsell_blocked='mission_forbids_offers'`, `max_duration_sec`, `expected_customer_name`) live on `VoiceSession`, which every subgraph closes over, so no hop can widen them. Hops are the same mechanism as inbound.

### WhatsApp turn

`bot_runtime.handle_turn` today is prompt+tools with no flow (`bot_runtime.py:712` loads by env `_bot_id()`). Under the Compiled Fleet it loads the same bundle via `resolve_entry('whatsapp', address)`, then `flow_walker.step(state, compiled.graph, understanding)`: render the current node's developer task message and the ACTIVE SPECIALIST block, offer `node tools ∩ Active Grant ∩ CATALOG.for_channel(TEXT)` plus `go_to_*`, run the existing `chat_with_tools` loop, evaluate expression edges after each tool result, persist `{node_key, variables, active_specialist}`, write `bot_tool_calls.agent_id`. A handoff is the same edge, the same `interaction_handoffs` row, the same grant swap; the target answers in the same job (one extra LLM call, off audio).

This is also the only path that closes a verified hole: `bot_tools.py:300` passes `identity_verified=True` **unconditionally** into `evaluate_authority`, and `:627` derives it from `customer_id != 'UNKNOWN-CALLER'` rather than from a verification event. G-F3 walks the same compiled graph the walker runs, so identity-before-writes becomes mechanical on text for the first time. Phase 0 fixes the two call sites directly, before any of that ships.

---

## Handoff mechanics and the latency budget

**What changes on a hop:**

- **Prompt: nothing.** The system message is `bundle.prefix_text` for the whole call. The compiler emits `role_message` only on the fleet entry node — verified as the current behaviour at `flows_dynamic.py:363-369`, which sets it on `entry.key` alone. The `ACTIVE SPECIALIST` developer block is *replaced*, not appended, through the same `replace_developer` path the skill runtime already uses on a 30-turn call.
- **Tools:** the target node's compiled offer plus its transitions; `ToolState.active_specialist` makes execution consult `grant_by_specialist`. The receiving specialist brings its own grant — ADR-0001's requirement, met without a second process.
- **Flow:** an ordinary `set_node_from_config` into a node of another namespace.
- **Voice: nothing.** There is no `voice_change` field in v1 (see refusals).
- **Context:** `carry='brief'` renders a deterministic developer block from `VoiceSession`, the flow variable bag and the typed payload — zero inference. `carry='full'` folds nothing.

**The budget, stated honestly.** Per hop the added cost is: one bridge line of TTS (already speaking), a dict pointer swap, ≤ ~400 brief tokens plus the target node's task message, and one queued DB write off the audio path. **No added inference.** The system-message half of "the cache survives" is true by construction and testable in CI by hashing the assembled system message before and after a hop.

**What I will not assert.** Nothing in this tree has ever observed a prompt-cache hit. `voice/crm_sink.py:1384` records `usage.cache_read_input_tokens` — Anthropic's field name; Azure's `usage.prompt_tokens_details.cached_tokens` is read nowhere. `voice/tts_pool.py` records the only LLM latency figure in the repo: "the LLM turn (p50 ~1.6s) dominates the turn budget," against `VOICE_SLO_MS = 800` (`canary.py:27`). So: **every millisecond figure in all three source designs is deleted from this one.** Phase 0 adds the Azure cached-token field to the usage capture; Phase 2 ships `hop.cover_ms` and `hop.cached_tokens`; the canary's `slo_miss` trigger is evaluated on hop turns specifically, so a badly authored fleet rolls itself back rather than degrading quietly.

**Amortisation** is a per-worker periodic keep-warm (`voice/prefix_warm.py`), not a per-call one. Ensemble's prefix is byte-identical per deployment, so it is warmable once per worker every ~4 minutes rather than N−1 times per call — which is what Sealed Fleet proposed and what would have put N−1 extra prefills per call onto the same scheduler serving the audio path. On-prem, vLLM prefix caching is process-local, so the warm and the serve must be the same engine worker; the swap is in-process, so they are.

**One present-tense latency win, independent of hops.** `voice/bot.py:525-577` appends `mission_mod.briefing(_mission)` to the system instruction and then string-replaces `"inbound collections voice agent"` with `"outbound collections voice agent"`. Every outbound call therefore has a per-borrower system prefix and no cross-call cache at all. Phase 0 moves both into a developer block. That is a fix, not a neutral refactor, and it is a precondition for the warmer being worth running.

**Ping-pong** is capped by `card.memory.max_hops_per_call` (default 2) with an authored `refusal_line` on the edge, so a refused hop is a sentence the borrower hears rather than a silent stall.

---

## One version number per call

**The id is the door's `bot_deployments.id`.** No new `fleet_releases` table. `bot_deployments` already enforces one active row per (bot, environment); `prompt_versions.compiled` on the door's published row pins every member as `{bot_id, prompt_version_id, card_hash, flow_hash, prompt_content_hash}` and carries `prefix_hash` and the full compile report — so the compiler artifact stops being thrown away. `bot_deployments.bundle_hash = sha256(compiled)` and `change_log.py`'s COMPONENTS gains `'compiled'`, extending the existing tamper-evident chain over the flattened graph.

**The fix that makes this true — publish is not deploy.** Today `db_prompt_studio.publish_prompt_version` (1820) archives the published row, promotes the draft, **inserts a `bot_deployments` row with `environment='production', status='active'`**, and calls `canary.record_experiment(bot_id=…)`, all in one transaction. Phase 3 splits it:

- Publishing a **member** promotes its `prompt_versions` row to `status='published'` and writes **no** `bot_deployments` row and **no** `deployment_experiments` row. `load_active_bundle(bot_id=member)` then resolves nothing, and the studio's `'direct'` reachability state genuinely disappears.
- Publishing a **fleet** (new `POST /agent-studio/fleets/{door}/publish`) compiles, writes one `bot_deployments` row for the door with `bundle_hash`, and records one experiment.
- `POST /agent-studio/cards/{bot_id}/publish` (`main.py:2214`) survives for doors and standalone cards; on a fleet member it returns `409 fleet_publish_required`. **G-F12** enforces this at compile so it cannot be routed around.

**Per-turn attribution.** `bot_tool_calls.agent_id` and `.skill_id` already exist (`sql/12_crosscutting.sql:148-149`) — no new columns for "which specialist, which skill, which tool." For a sentence with no tool call, `interaction_transcript` has **no** `bot_id` and no `prompt_version_id` (`sql/04_interactions.sql:80-104`), so Phase 2 adds one nullable `speaker_bot_id` column rather than leaving attribution to a turn-range join.

**`interactions.handler_bot_id` stays the door.** It is read by `canary._live_qa_burn` (`canary.py:194-208`, joining `i.handler_bot_id = :b`) and by `db_bot_analytics.py:332`. Flipping it per hop — which `db_inbox.handoff_to_agent` does today at `db_inbox.py:1441` — would make a post-hop call's *pre-hop* live_qa failures count against the wrong deployment's canary. The accountable mouth is the door; the specialist is a row.

**The metric fix that must ship in Phase 0.** `interaction_handoffs` today means "escalated to a human": it is written only with `to_kind='human'`, and three analytics queries read `EXISTS (SELECT 1 FROM interaction_handoffs h WHERE h.interaction_id = i.id)` as the escalated flag — `db_bot_analytics.py:152`, `:209`, `:339`. Its `reason` CHECK admits only eight human-escalation values (`sql/04_interactions.sql:71`), so an insert of `'specialist_route'` fails outright. Phase 0 widens the CHECK **and adds `AND h.to_kind = 'human'` to all three predicates in the same commit.** Without both halves, the first specialist hop inflates the escalation and containment rates a grievance MIS report is built on.

**Regulator's three questions, one join each.** *Why this sentence:* interaction → DEP → `compiled` → `interaction_handoffs` (turn_index ≤ turn) → the speaking member and its prompt version. *Why this offer:* `offer_decisions` keyed from the `recommend_next_offer` call, which the `product_in_reco` grader already pins. *Why this call at this time:* `call_attempts.decision_id` → `treatment_decisions` + `policy_version`, plus the `contact_events` row.

---

## Policy engines and human gates across hops

Nothing an author or a hop can do widens what the engines decide.

- **Locked engines.** G3 runs per member (`LOCKED_POLICY_ENGINES`, all six `PolicyBindings` `'required'`), and the fleet compiler additionally asserts every `grant_by_specialist` entry contains the locked mouth tools. `recommend_next_offer` and `evaluate_authority` remain the only speakers of product and rupee amount on every subgraph. The treatment engine still decides whether a call happens; `contact_policy.admit` still gates every dial.
- **Grants are pre-gated sets.** `grant_by_specialist[slug]` is compiled statically from the target card ∪ its signed packs ∪ its connectors ∪ `VOICE_ALWAYS`. A hop moves to a set that was gated at publish; it can never union onto the source's.
- **Identity before writes is a graph property.** G-F3 walks every path from the door's start to any node whose offer contains a non-read tool and requires `verify_identity` on it. A member entered before verification must be flagged `pre_identity_safe` and may offer only read/KB tools. On voice this is belt-and-braces — `session.identity_verified` lives on `VoiceSession`, not the card, so a specialist swap cannot clear it and every write tool re-checks it. On text it is the only thing that closes `bot_tools.py:300`.
- **Human gates get a consumer.** This is the single largest correction to all three source designs. A repo-wide search finds `human_gates` at `schema.py:389`, five sites in `defaults.py`, and the frontend type — **and nowhere else**. `ToolGrant.may_execute` is `return name in self.allowed`. So the Door's seeded `HumanGate(handoff_to_agent, require='identity')` (`defaults.py:171`) guarantees nothing today, and any design that rests its C3 story on that field is asserting a control it does not have. Phase 1 ships `agent_core/tools/gates.py` and wires it into both dispatch paths, in the same phase that first relies on it.
- **Gate monotonicity across a hop.** G-F7 **fails** a handoff edge whose target lacks a human gate the source holds for the same tool, and merges strictest-wins (`'both' > 'floor'|'identity'`) where both hold one. Strictest-wins alone would let a gated write be laundered through a laxer card; the refusal catches it explicitly.
- **The packet cannot carry a decision.** `PacketField` is a `Literal` with no member for offer, waiver, amount or contact time. Commitments are copied from rows the tools wrote, never from the transcript, with a grader that fails loudly if a number appears that no row contains.
- **Prose cannot hand off.** Model-chosen edges are typed tools with `payload_schema` properties; the `no_prose_handoff` grader stays. The free-target `handoff_to_agent(target_bot_id)` is deleted — a model picking an arbitrary bot id is exactly what compiled edges make impossible.
- **The live fail-open, fixed on day one.** `voice/tools.py:2773-2788` builds the handoff allowlist from `agent_core.cards.defaults.card_for(bot_id)` and sets `allowlist = None` on `KeyError`; `agent_core/tools/domain.py:1029` reads `if allowlist is not None and target not in allowlist`. So **any tenant card that is not a first-party constant can hand off anywhere today.** `bot_runtime.py:947` already does it correctly from `bundle['agentCard']`. This is a live ADR-0002 deny-all violation, not a design decision, and it ships alone in Phase 0 with one test.

---

## Studio model

**Fleet index** (`Habibi/src/routes/agent-studio.index.tsx`) groups cards by fleet — "Inbound servicing (door: Intake)", "Outbound collections (owner: Collections)", "Internal (Supervisor brief, Doc verifier)". Reachability collapses to entry / member / unbound.

**Card editor** keeps its 15 tabs (`prompt-studio.lazy.tsx:1109-1132`), re-scoped by `identity.kind`: *System Prompt* becomes **Brief** on a member (a developer delta, linted to a token cap, with the message "this is not the system prompt; the door owns it"); *Voice* reads "inherits fleet voice"; *Outbound* is enabled only on the member that owns missions; *Bindings* and *Ship* move to the fleet.

**Fleet canvas** — `FleetCanvas.tsx` replaces the body of `AgentGraphTab`. Nodes are member cards drawn as collapsed subgraphs, fed by a new `GET /agent-studio/fleets/{door}/graph` returning the compiled closure instead of `main.py:2272-2298`'s "all cards + this card's handoffs". Edges are Handoff Edges with an inspector for condition, carry, payload fields, entry node and return. Double-click opens the member's Flow tab in the existing `FlowCanvas`/`FlowInspector`. A **Flattened view** toggle renders the compiled graph read-only in the same component — a compliance officer reviews the exact path the borrower traverses, not a picture of intent. A **"Who answers this?"** simulator resolves a pasted customer id or feature set to a rule and a member.

**Adding a specialist** (an insurance ops lead, no code): New card from template (`agent_core/cards/templates.py` `clone_card`) → Flow tab: author an entry node and an exit node → Skills tab: attach signed packs → Tools: include stays inside catalog → Brief tab: write the persona delta → **Mark publishable** runs the member gates (G0/G1/G3/G4/G5/G9/G10 + the member's LLM-free contract suite, seconds) → open the fleet canvas, drag an edge from `collections/negotiate_ptp` to `lapse/entry`, set the condition, carry, bridge line and refusal line → **Compile**, which paints per-edge and per-member gate status → **Ship** at 10% with auto-rollback. Publishing writes one `prompt_versions.compiled` and one `bot_deployments` row.

**What the compiler checks.** Per member: G0–G15 and G-OB1–9 unchanged. Then the fleet gates — deliberately numbered `G-F*` rather than continuing `G16+`, because all three source designs assigned different meanings to G16–G21 and a collision in gate ids is a support call:

| Gate | Check |
|---|---|
| **G-F1** closure | every member reachable from the door; no orphan; **no member holds a production deployment** |
| **G-F2** one door | exactly one `kind='door'`; door owns the terminals; every member exits to a terminal or a return |
| **G-F3** identity_before_writes | every path from door start to a non-read tool passes `verify_identity`, unless `pre_identity_safe` |
| **G-F4** namespace + leaveability | keys compile to `<slug>/<key>`; each member may own its own `wrap_up`/`negotiate_ptp`; the handoff entry node satisfies `voice/node_contracts.py NODE_REQUIRED` so an authored specialist is never unleaveable |
| **G-F5** prefix budget | skill catalog portion ≤ `CATALOG_PREFIX_TOKEN_CAP` (800, `skills/lint.py:10`); guardrail union counted and reported |
| **G-F6** door_readonly | a door card may hold no tool outside `{verify_identity, get_customer_context, capture_call_goal, search_knowledge_base, set_contact_preference, add_customer_note, escalate_to_human}` + transitions; its flow reaches `greet_disclose` before any node exposing a route edge |
| **G-F7** gate_monotonicity | fail an edge whose target lacks a gate the source holds for the same tool; strictest-wins otherwise |
| **G-F8** boundary_distinct | refuse a second member whose persona hash, `authority_profile`, `data_class` and `regulator_tags` all match an existing one — *"this is a skill, not a card"*, with **Promote to card** offered when the boundary is real |
| **G-F9** mission ownership | one member per Objective; G-OB2 re-run on the flattened graph; outbound entry may not resolve to a door |
| **G-F10** post_call merge | no contradictory verbs for one outcome |
| **G-F11** text-walkability | whatsapp-reachable nodes depend on no voice-only affordance |
| **G-F12** publish_scope | a member publish deploys nothing; a per-card publish on a member fails `fleet_publish_required` |
| **G-F13** hop cap | `max_hops_per_call` (default 2); a cycle needs a return edge and a `refusal_line` |
| **G-F14** eval provenance | see below |

G-F8 is the brake the Ensemble design lacked. Cards are cheap to author here, and every extra one is a permanent tax on the compiled prefix and the publish set — so a compliance officer needs a principled, legible answer to "I want a PTP specialist card," and this design is the one that can then say yes cheaply when the boundary is genuinely new. Paired with it, authored skill activation (pack frontmatter: intents from the understanding vocabulary, objectives from `flow_graph.OBJECTIVES`, host node keys, variables over `SESSION_VARIABLES`) replaces `INTENT_TO_SKILL` and keeps skills — not edges — the default specialisation inside a boundary.

---

## Eval and canary at fleet scale

**Three tiers; only the top costs LLM time; only the changed slice runs by default.**

1. **Member static gates**, on every save: milliseconds, already implemented.
2. **Member contract suite**: code graders only, run by `run_suite_fixtures` over the member's fixtures against its compiled offer table — `verify_before_ptp`, `no_prose_handoff`, `product_in_reco`, `crm_card_injection`, plus new **`grant_respected`** (every tool call in a fixture ∈ `grant_by_specialist[slug]`) and **`handoff_via_edge_only`** (no `interaction_handoffs` row without a typed transition call). Seconds, no model. Required green before a member can join a fleet.
3. **Fleet regression + redteam + outbound** on the synthesised union card, plus closure graders: `disclosure_once_per_call`, `identity_before_write_across_hops`, `packet_carries_no_decision`, `hop_count_within_cap`, `misroute_returns`. A suite that only tests Collections in isolation would pass a broken Door, so fleet fixtures must traverse the door and at least one hop.

**The cache is the sub-linearity mechanism, and its key is fixed.** `eval_reports.content_key = sha256(card_hash, flow_hash, prompt_content_hash, sorted skill_version_ids, grader_version)` — where `prompt_content_hash` covers `prompt_versions.prompt`, `.persona`, `.guardrails`, `.voice` and `.tuning`. **Both Bounded's G20 and Sealed's G19 omitted the words**: the card is a column on the `prompt_versions` row (`sql/09_bot_config.sql:110-125`), so a key built from `card_hash` and `flow_hash` alone lets the single most common operator edit — rewriting the system prompt or the persona into an aggressive chase script — republish with regression and red-team passing on a report that never saw the new words. That is precisely the RBI fair-practices vector the rung-3 gate exists for. **G-F14** lets G7/G8 pass on a stored passing report with the same key and reports it as `pass · cached r-… unchanged since 2026-08-30` — never as "skipped", and never without the report id. Two acceptance criteria, as tests rather than comments: `grader_version` is inside the key, and fixtures grade tool calls and CRM rows, not transcripts.

**Delta red-teaming is a supplement, not a gate.** A clone whose only change is its words has an empty tool/skill/edge delta and would be honestly "skipped" — which is the wrong answer. The delta selects *additional* cases; the cached-or-run regression on the content key is what actually gates.

**Canary.** One `deployment_experiments` row per door. Adding a specialist adds no experiment. The six rollback triggers keep their vocabulary and their `handler_bot_id` keying, which works precisely because the door stays the handler. `slo_miss` is additionally evaluated on hop turns. `live_qa_burn` is attributable per member through `bot_tool_calls.agent_id` and `interaction_handoffs`, so the Ship tab can say which member burned.

**What does not get cheaper, said plainly:** a new handoff edge is a new injection surface and needs genuinely new red-team cases; the nightly full run still scales with total fixtures; and a publish between nightlies is verified on a slice.

**What this design does not do:** it does not touch `agent_core/eval/run.py:14-34`. That docstring argues, correctly, that a suite is one-to-many across cards (nine cards name `eval-regression-collections`), that NULL is the truthful owner, and that the Evals-tab misreading was already fixed in the tab. Two of the three source designs proposed "fixing" a symptom that is already fixed. We add `eval_reports.content_key` and `eval_reports.scope jsonb`; we leave `bot_id_for_suite` alone.

---

## Migration

Each phase ships alone, is reversible, and names its tests.

**Phase 0 — fix what is broken today. No architecture, no flag.**
- `backend/voice/tools.py:2773-2788` — allowlist from the published card on the bundle, delete the `KeyError → None` branch. → `test_handoff_allowlist_reads_published_card`
- `backend/bot_tools.py:300` and `:627` — pass the real identity flag into `evaluate_authority`; derive from a verification event, not from `customer_id != 'UNKNOWN-CALLER'`.
- `backend/sql/25_fleet.sql` — widen `interaction_handoffs.reason` CHECK with `specialist_route`, `specialist_return`, `mission_entry`; `ADD COLUMN turn_index, deployment_id, carry, packet`.
- `backend/db_bot_analytics.py:152, 209, 339` — `AND h.to_kind = 'human'` on all three EXISTS predicates, **same commit**. → `test_bot_hop_does_not_count_as_escalation`
- `backend/voice/crm_sink.py:1384` — also capture `usage.prompt_tokens_details.cached_tokens`.
- `backend/voice/bot.py:525-577` — mission briefing and the `inbound→outbound` string replace move to a developer block. → `test_outbound_system_prefix_is_per_deployment_not_per_borrower`
- `backend/api` / `bot_worker` root logger gets a handler (per repo memory it has none, so text-path regressions are invisible today). Prerequisite for Phase 4.

**Phase 1 — bundle seam, namespacing, and the human-gate consumer. Flag `FLEET_ENABLED` off.**
Files: new `agent_core/fleet/{schema,compile,routing}.py`; new `agent_core/tools/gates.py`; migration adding `prompt_versions.compiled`, `bot_deployments.bundle_hash`, `entry_bindings`, `eval_reports.content_key/scope`, `interaction_transcript.speaker_bot_id`; `agent_core/deployment.py`; `flow_graph.py` (key grammar + new `ENTRY_ROLES` constant and `FlowNodeData.entryRoles` — **`OBJECTIVES` is left untouched**, because it is the 13-entry mission vocabulary that `card.outbound.objectives[].key`, G-OB1/G-OB2 and `PROMOTIONAL_OBJECTIVES` all read); `voice/flows_dynamic.py build_authored_flow(namespace=…)`; `voice/tools.py:426 _node`. Gates G-F1–G-F5, G-F12 informational. A one-member fleet compiles to today's behaviour byte for byte.
Tests: `test_fleet_compile_is_deterministic`, `test_two_members_may_both_own_wrap_up`, `test_human_gate_blocks_execution`, `test_single_member_fleet_is_byte_identical`.
**This is the highest-value reordering available.** Ensemble put namespacing in Phase 5; until it lands, `voice/tools.py` transitions by literal name (`_node('negotiate_ptp')`), only one member may own each `RESERVED_NODE_KEY`, and the fleet you can actually ship holds exactly one collections-shaped specialist. Doing it first is what turns "twelve specialists" from a roadmap item into a Phase 2 capability.

**Phase 2 — real in-process hop on voice. Flag `VOICE_HANDOFF=swap`.**
Files: `voice/flows_dynamic.py` (edge → pre_actions), `voice/tools.py` (`ToolState.active_specialist`, per-turn grant lookup replacing the `keep` filter at `:2918`), `agent_core/tools/grant.py for_specialist`, `agent_core/context.py handoff_packet_message`, new `voice/hop_metrics.py`, new `voice/prefix_warm.py`, `agent_core/canary.py` (slo_miss on hop turns). Gates G-F4, G-F7, G-F13 blocking.
Deletes here: `voice/mesh.py`, `voice/mesh_bus.py`, `voice/mesh_roles.json`, `BOT_TO_MESH_ROLE` (`defaults.py:46-51`), `agent_core/cards/handoff_policy.py`, `mesh_activate_insurance` (`bot.py:1519-1544`), the mesh call in `_on_upsell_engaged` (`bot.py:1102-1132`), `voice/workers/insurance.py` and the `voice_insurance` compose service.
Tests: `test_hop_swaps_brief_and_grant_not_system_prompt`, `test_system_message_hash_is_stable_across_a_hop`, `test_hop_keeps_identity_and_upsell_latch`, `test_second_hop_evicts_first_packet`.
Reversible by flag; the mesh deletion is git-reversible and safe, because `mesh.active_role` is written and read by nothing that changes tools or prompt today.

**Phase 3 — publish/deploy split, the Door, fleet routing. Flag `DOOR_ENABLED`.**
Files: `db_prompt_studio.py:1820` (deploy scope), `main.py:2214` (409 on members) plus new `/agent-studio/fleets/{door}/graph|compile|publish`, `agent_core/cards/routing.py` (entry_bindings first, `BOT_ID` second, logged deprecated), `agent_core/canary.py` (canary decided once per call), `voice/flow_export.py` (materialise the door portion of `voice/flows.py`), `FleetCanvas.tsx`, `ShipTab.tsx`, Door simulator. Gates G-F6, G-F8, G-F12 blocking.
Tests: `test_member_publish_creates_no_deployment`, `test_per_card_publish_rejects_a_fleet_member`, `test_door_cannot_hold_write_tools`, `test_outbound_skips_the_door`.
Reversible: empty `entry_bindings` → `BOT_ID` → Phase 2 behaviour, and every inbound call lands on Collections exactly as today.

**Phase 4 — WhatsApp walks the graph. Flag `TEXT_FLOW_WALKER`.**
Files: new `backend/flow_walker.py`, `bot_runtime.py handle_turn`, `agent_core/skills/runtime.py` (`INTENT_TO_SKILL` retired behind door expression edges). Gate G-F11. Conformance suite runs the same `flow_graph` fixtures through `flows_dynamic` (voice container) and `flow_walker` (API image) and asserts identical node paths and tool sequences.

**Phase 5 — eval economics and consult.**
Files: `agent_core/eval/{harness,graders}.py` (five closure graders + `grant_respected`, `handoff_via_edge_only`), `agent_core/fleet/compile.py` (G-F14, changed-member diff), `agent_core/mcp_http/tasks.py` (`ALLOWED_KINDS` gains `agent_consult`), `agent_core/tools/{catalog,domain}.py` (`consult_agent`), Ship-tab provenance rendering. `escalate_to_human` becomes the first consult caller, with `supervisor-brief` the first internal card.
Tests: `test_cached_report_is_invalidated_by_a_persona_edit`, `test_cached_pass_reports_its_report_id`, `test_consult_never_blocks_the_turn`.

**Phase 6 — outbound ownership; constants become rows.**
`_collections_outbound()` (`defaults.py:190-276`) becomes authored `outbound` on the Collections row; `entry_bindings(objective)` resolves the mission owner; `call_attempts.deployment_id` pinned at dial; inbound reserves `purpose='in_session'`. `defaults.py` builders become an idempotent, hashed boot seed; every `card_for()` caller reads the DB. Gate G-F9.

**Phase 7 — legacy retirement, one deletion per PR with its parity report id.**
`voice/flows.py` deleted once materialised; `VOICE_FLOW_GRAPH` retires **`legacy` and `hub` only** — not `auto`, which is today's default when the variable is unset (`voice/config.py:271-272`), so retiring it would change behaviour on upgrade for every environment that never set it. The free-target `handoff_to_agent` is deleted last.

---

## What gets deleted

- `backend/voice/mesh.py`, `backend/voice/mesh_bus.py`, `backend/voice/mesh_roles.json` — a second tool vocabulary and a per-session `active_role` that nothing reads to change tools or prompt.
- `BOT_TO_MESH_ROLE` in `backend/agent_core/cards/defaults.py:46-51`, and the `voice_mesh.activate_role` calls in `backend/voice/tools.py` (inside `_handoff_to_agent_handler`) and `backend/voice/bot.py:1102-1132`.
- `backend/voice/bot.py:1519-1544` — the `mesh_activate_insurance` flow action and its registration.
- `backend/agent_core/cards/handoff_policy.py` — `insurance_handoff_allowed`; the veto becomes the presence or absence of a compiled edge.
- `backend/voice/workers/insurance.py` and the `voice_insurance` compose service — a Redis-dependent sidecar whose job an in-process namespace does.
- `VOICE_MULTI_AGENT_ENABLED` in `backend/voice/config.py`.
- `runtime_entry_bot_id()` in `backend/agent_core/cards/routing.py:34-45`, `BOT_ID` at `.env.example:108`, and `db.DEFAULT_BOT_ID` as a routing default.
- `INTENT_TO_SKILL` in `backend/agent_core/skills/runtime.py:28-36`.
- The `handoff_to_agent` catalog tool's free `target_bot_id` (`agent_core/tools/domain.py:1009`, `voice/tools.py:2773`), and `db_inbox.handoff_to_agent`'s `UPDATE interactions.handler_bot_id` (`db_inbox.py:1441`); `interactions.transferred_from_bot_id` deprecated.
- `backend/voice/flows.py` and the `legacy`/`hub` values of `VOICE_FLOW_GRAPH`.
- The four card constants in `backend/agent_core/cards/defaults.py` as runtime authorities — they become seed data; `card_for()` leaves every request path.
- The mission-briefing append and the `"inbound collections voice agent"` string replace at `backend/voice/bot.py:566-577`.
- The read-only "Agent graph" tab body in `Habibi/src/components/prompt-studio/` — replaced by `FleetCanvas`.

---

## What we are deliberately NOT building, and why

- **A process or LLMWorker per specialist, and any event bus.** `TARGET-ARCHITECTURE.md:261` refuses microservices ("the process split already exists and is correct") and an event bus ("Postgres `SKIP LOCKED` is the broker"). Concretely: `BusBridgeProcessor` is not in this tree, `voice/mesh_bus.py`'s RedisBus is publish-only and `RedisBus.start()` is deliberately never called, and `voice/workers/insurance.py`'s own docstring says the bridge does not exist yet. Building the fleet on it would be betting the headline capability on unbuilt machinery.
- **Mid-call voice switching.** `TTSUpdateSettingsFrame` appears nowhere in this codebase. `voice/tts_pool.py` documents that the Azure synthesizer is constructed once in `start()` with the websocket pre-opened exactly once, that touching that connection mid-call already produced a **41-second deadlock after a barge-in**, and that a cold re-handshake costs ~1.5 s. There is no `voice_change` field in v1 — the fleet speaks in one voice and a specialist introduces itself in words. Revisit only with a measurement.
- **Parallel consultation on the audio path.** Specialists are sequential in one context. "Agents communicate among themselves" is realised as typed edges with carried payloads *plus* `consult_agent` off the audio path — which is the honest form, and costs the live turn nothing.
- **A new `handoff_events` table.** `interaction_handoffs` exists, is the table the current handoff path already feeds, and `TARGET-ARCHITECTURE §6.6` refuses exactly this class of collision. We extend it and fix its readers.
- **A new `fleet_releases` table.** The door's `bot_deployments` row plus `prompt_versions.compiled` is already one id with a hash chain through `change_log.py`. A second ledger is a second thing to keep in sync.
- **Renaming `mesh_bus.py` to `fleet_events.py`.** `§6.9` classifies renames of operator-visible keys as data migrations; and the bus is deleted rather than renamed.
- **Adding `'handoff'` to `flow_graph.OBJECTIVES`.** That tuple is the 13-entry mission vocabulary and the domain of `card.outbound.objectives[].key`, iterated by G-OB1/G-OB2 and `PROMOTIONAL_OBJECTIVES`. A new `ENTRY_ROLES` constant costs nothing and pollutes nothing.
- **Retiring `VOICE_FLOW_GRAPH='auto'`.** It is today's default when the variable is unset; retiring it changes behaviour on upgrade for environments that never set it.
- **Changing `eval/run.py bot_id_for_suite`.** The relation is genuinely one-to-many; NULL is truthful; the downstream misreading was already fixed in the Evals tab.
- **Per-card models (`model_profile`).** Splits the live-QA and tuning surfaces for no capability the fleet needs in v1.
- **A blank LangGraph canvas.** `agent_transformation_plan.md` names it the trap and it stays named.

---

## Open questions that need a runtime measurement

Every one of these was asserted with a number by at least one of the three designs. None has evidence in this tree, so each is an instrument to build, not a claim to repeat to a customer.

1. **Has any Habibi voice call ever registered a prompt-cache hit?** No voice code reads a cached-token count: `voice/crm_sink.py:1384` records `usage.cache_read_input_tokens` (Anthropic's field); Azure's `usage.prompt_tokens_details.cached_tokens` is read nowhere. Phase 0 adds the field. **Until it reports, every hit/miss latency delta in every design — including this one — is a projection.**
2. **Does changing the tool-schema set per node invalidate the provider's cached prefix?** This is the load-bearing assumption under "a hop costs nothing." Today every authored node already changes `NodeConfig.functions` (`flows_dynamic.py:415-435`) and nothing measures it. Measure `hop.cached_tokens` across an ordinary node transition *inside one specialist* before shipping any cross-member hop.
3. **What does `LLMSummarizeContextFrame` actually cost?** It is queued at `voice/bot.py:1506-1512` and its latency is recorded nowhere. Until it is measured, `carry='summary'` is not an authorable option — only `brief` and `full` ship.
4. **Does a replaced `ACTIVE SPECIALIST` developer block survive summarisation?** The mechanism is real (`load_skill` → `replace_developer(SKILL_BODY_PREFIX, …)`, `voice/tools.py:2827`), but nothing asserts that a replaced block survives a context collapse — the VS-0D653BF9C3 stale-fact class. Needs a conformance test before a multi-hop call passes canary.
5. **Does per-worker periodic prefix warming actually keep the prefix hot?** Azure eviction is provider behaviour and vLLM's prefix cache is process-local. `hop.cover_ms` (bridge audio duration minus first-token latency; positive means the miss was hidden) is the only metric that can falsify the amortisation, and it does not exist yet.
6. **What does a full eval suite cost, in wall time and LLM calls?** Nothing in the repo records it, so "sub-linear" is a structural argument. Instrument `run_suite_fixtures` in Phase 5 before quoting any arithmetic.
7. **Does the compiled prefix stay inside budget as members grow?** `CATALOG_PREFIX_TOKEN_CAP = 800` (`skills/lint.py:10`) caps one card's skill catalog today; whether a fleet union plus a guardrail union fits inside the same number is asserted, not shown. G-F5 reports the real count on the first compile.
8. **What is the Door's misroute rate?** A Tier-0 rule that sends a product question to Collections turns a zero-hop call into a one-hop call. `misroute_rate` (target hands back within two turns) is measured from the first canary; set the threshold from what it shows, do not pre-declare it.