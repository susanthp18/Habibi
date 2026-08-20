# Agent transformation plan

**Status:** research / product architecture — not a committed sprint  
**Date:** 15 Aug 2026  
**Product:** BigBound AI (Habibi frontend + collections CRM backend)  
**Companions:** `roadmap-features.md` · **Phasewise stack:** `agent_transformation_phases.md` · **Peak implementation spec:** `agent_transformation_implementation.md`

You already have more of an agentic platform than it looks like. The next leap is **not** “let anyone draw GPT boxes.” It is turning the one collections bot into a **governed agent factory**: people compose specialists, skills, and MCP connectors, while policy engines stay in charge of money, consent, and authority.

That is the only version of “most intelligent” that survives RBI, DPDP, and a collections head’s scoreboard.

---

## What you have today (honest map)

BigBound is already a **regulated collections OS** with a voice/WhatsApp mouth. The intelligence is split, on purpose:

| Layer | What it actually is | Where it lives |
|---|---|---|
| **Mouth** | One deployed bot: prompt + persona + voice + guardrails + conversation graph | Prompt Studio → `bot_deployments` |
| **Hands** | One tool catalog, rendered to voice, text, and MCP | `agent_core/tools/catalog.py` |
| **Veto brains** | Reco, treatment, authority — the model does **not** pick product, channel, or waiver | `agent_core/reco`, `treatment`, `authority` |
| **Critic** | Live QA on every turn, barge/whisper in shadow | `agent_core/live_qa` |
| **Router** | Rule engine for escalate / throttle / auto-action | `/routing` |
| **MCP (half)** | You **are** a server. Read-only CRM + KB. Stdio only. No network auth yet | `mcp_server.py` |
| **Mesh (stub)** | Hardcoded roles: `collections` / `insurance` / `supervisor_brief` | `voice/mesh.py` |

The important design already in the code:

> Reco: *the LLM does not choose the product — it receives a shortlist that has already passed every gate, and its remaining job is purely linguistic.*

That sentence is the north star. Custom agents that ignore it will look “agentic” in a demo and become a compliance incident in production.

**What is not true yet:** users cannot create agents. There is one bot, one prompt version, one flow graph of *conversation nodes* (`say` / `prompt` / tools / conditions). The flow canvas is a **call script**, not an agent graph. Mesh roles are Python constants. MCP cannot write, cannot verify identity, cannot expose resources/prompts, and cannot *consume* other MCP servers (CBS, payments, bureau, WhatsApp, Excel). Integrations are LLM/STT/TTS/telephony keys, not a tool marketplace.

So the product is “one very good recovery agent with a studio.” The demand is “an operating system where a collections head, an insurance ops lead, and a compliance officer each ship specialists — without forking the brain.”

---

## The trap (and the pattern that actually wins)

If you ship a blank LangGraph / n8n-for-LLMs canvas:

- Authors will put “approve settlement” in a prompt.
- They will wire `create_promise_to_pay` to a node with no identity gate.
- They will add 40 MCP tools and the model will pick the wrong one under latency.
- You will lose the thing that already makes this product serious: **features → veto → score → arbitrate → log**.

The 2026 consensus in enterprise / BFSI is a **three-layer stack**, and Anthropic’s finance agents (May 2026) made it concrete:

1. **Skills** — procedural knowledge. Folders of instructions, examples, scripts. Passive. Do not decide *when*. Teach *how*. Progressive disclosure (load metadata first, full skill only when relevant).
2. **Agents** — identity + workflow + allowed handoffs + allowed tools. They decide order and constraints.
3. **MCP connectors** — how agents touch systems. Tools, resources, prompts. Auth, audit, data minimization at the protocol, not in each prompt.

Plus a fourth layer you already invented and must not dilute:

4. **Policy engines** — reco / treatment / authority / live QA / consent / DND. Not skills. Not prompt text. Code with a log.

Google’s A2A sits beside MCP: MCP is agent→tool, A2A is agent→agent (handoff, task state, “input-required” for humans). OpenAI Agents SDK is the same idea with `Agent`, `handoff()`, `guardrails`, `mcp_servers`, tracing. You do not need to *adopt* those SDKs. You need those **primitives**, authored in Habibi, executed by `bot_runtime` / Pipecat.

Anthropic’s own line is useful here: *don’t build a new agent for every chore — build skills, and let a small number of agents load them.* For a bank, that is cheaper, safer, and actually customizable.

---

## The product to build: Agent Studio (Prompt Studio 2)

Keep Prompt Studio. Promote it from “edit the one bot” to **compose a fleet**.

### 1. Agent Card (the unit a user creates)

Every custom agent is a versioned card, not a prompt dump:

- **Identity:** name, purpose, channels (`voice` | `whatsapp` | `sms` | `internal` | `mcp`)
- **Persona / voice / languages** (you already have this)
- **Skills:** attach 1–N skill packs (`ptp-negotiate`, `hardship-intake`, `insurance-faq`, `kyc-screener`)
- **Tools:** subset of the catalog, plus MCP servers this agent may call
- **Handoffs:** allowlist of other agents (never “call anyone”)
- **Policy bindings:** which engines it must consult (`recommend_next_offer`, `recommend_treatment`, `evaluate_authority`) — not optional
- **Guardrails:** input + output, including the existing lexicon / live QA cells
- **Memory scope:** this call / this customer / this case / never
- **Human gates:** which writes require floor confirm
- **Eval suite:** sandbox scenarios that must pass before publish

Publish still goes through `bot_deployments`. Rollback still exists. `flowValid` actually blocks publish (it currently does not).

This is Salesforce Agentforce / Copilot Studio, but **collections-shaped**: the card cannot grant authority the matrix does not grant.

### 2. Skills, not 40 duplicate agents

A skill is `SKILL.md` + examples + optional scripts, stored next to the KB:

```text
skills/ptp-negotiate/
  SKILL.md          # when to use, script, objections, never-say
  examples.jsonl    # gold dialogues
  objections.md     # “salary delayed”, “already paid”
  scripts/          # optional: compute EMI remaining (deterministic)
```

The model sees only the skill’s **description** until the turn is about PTP. Then it loads the body. That is how you stay fast on voice (tight context) and still “intelligent.”

Skills the factory already needs, mapped to screens you have:

| Skill | Speaks on | Writes via tools | Engine it must obey |
|---|---|---|---|
| `verify-and-disclose` | Voice/WA | `verify_identity` | Consent / recording |
| `ptp-negotiate` | Voice/WA | `create_promise_to_pay` | Authority + DND |
| `hardship-intake` | Voice/WA | `add_customer_note`, escalate | Treatment hold |
| `dispute-capture` | Voice/WA | `flag_dispute` | Treatment `dispute` veto |
| `doc-fulfil` | Internal | `request_documents` | Identity |
| `broken-ptp-chase` | Internal + WA | treatment followthrough | Attempt cap |
| `upsell-pitch` | Voice (late) | `recommend_next_offer`, `capture_lead` | Reco suppression |
| `insurance-lapse` | Voice/WA | same catalog | Reco + consent (promo vs txn) |
| `qa-examiner` | Internal | scorecard pack | Live QA lock |
| `floor-coach` | Internal | whisper / barge | `LIVE_QA_BARGE_MODE` |
| `supervisor-brief` | Handoff | none | Mesh role you already named |

Users customize by **forking a skill** (tone, language, product line), not by rewriting the PTP tool.

### 3. Two different graphs (do not smash them)

You currently have one canvas that is a Pipecat conversation graph. Keep it. Add a second canvas:

**A. Conversation flow** (exists) — what the *mouth* says: greet → goal → verify → hub → wrap. Reserved keys (`verify_identity`, `negotiate_ptp`, …) stay. This is IVR-grade structure. Voice needs it.

**B. Agent graph** (new) — who is on the call:

```text
[Intake] ──verify──► [Collections]
                         ├─ hardship ──► [Hardship] ──► [Human]
                         ├─ dispute  ──► [Dispute]
                         ├─ gated_upsell ──► [Insurance]   ← mesh role you already have
                         └─ authority-cap ──► [Supervisor]
```

Handoffs are **typed**: payload schema, allowlist, shared `CallContext`, and a log row (`from_bot_id` / `to_bot_id` already exist on interactions). The model cannot hand off by quoting “transfer to legal” in a transcript — Anthropic’s finance orchestrator explicitly warns that pattern is injectable. Handoff is a **tool**, like OpenAI’s `handoff()`.

Routing rules (`/routing`) become the **non-LLM edges**: DPD ≥ 61 → never stay on bot; NDND → no voice; sentiment floor → no upsell. The agent graph is what the LLM may traverse *inside* those rails.

### 4. MCP as a two-way bus (this is the real “pluggable”)

You are only **MCP-out** today: Cursor/Claude can read customer context. That is the right start (mutating tools have no verification ceremony). To be the platform:

**Keep being a server (make it enterprise-grade)**

- Streamable HTTP + OAuth / mTLS, not only stdio (`MCP_API_KEY` is already the stated next step)
- **Resources**, not just tools: `customer://{id}`, `account://{id}/ledger`, `kb://snapshot/{id}`, `interaction://{id}/trace`, `policy://authority-matrix`
- **Prompts** as user-triggered playbooks: “prep this handoff”, “draft PTP SMS”
- **Elicitation** for writes: MCP client must complete identity (or a floor agent must confirm) before `create_promise_to_pay` is even listed
- Same `bot_tool_calls` audit, `channel='mcp'`
- Capability scopes per API key: `crm.read`, `kb.search`, `offers.read` — never “all tools”

**Become a client (this is how tenants plug their world in)**

Integrations today are Azure/Twilio keys. The 2026 version is an **MCP connector registry**:

| Connector | Why a collections OS needs it |
|---|---|
| Core banking / LMS | Live balance, bounce, payoff — stop trusting a stale CRM row |
| Payment gateway / UPI | Pay-link status, instant “paid already” |
| Bureau / CKYC | Eligibility without inventing KYC |
| WhatsApp Cloud / RCS | Same tools, new channel adapter |
| NDNC / DND registry | Veto, not a prompt reminder |
| Ticket / LOS | Disputes and docs leave the island |
| Spreadsheet / MIS | Floor lead’s morning pack (Anthropic’s Excel pattern) |

Each connector is: URL + auth + allowed tools + data-class (PII / money / marketing) + timeout + circuit breaker. An agent card **attaches** connectors. The runtime does what MCP clients already do: `list_tools()` across servers, merge into one registry, execute with tenant credentials.

**Progressive tool discovery** is mandatory on voice. Do not inject 80 MCP tools into a 400ms turn. Pattern: `search_tools` + `execute_tool`, or bind tools per node/skill. Your catalog already has `channels=` for this — extend it with `skill=` and `connector=`.

**Sampling** (MCP servers asking *your* LLM to complete) is how a CBS MCP could request a “explain this bounce in Hindi” without owning a model. You keep model access, spend, and redaction.

### 5. Internal agents — this is where “most intelligent” actually shows

The roadmap already says the P&L is delay, not dialogue. Custom agents should first eat **back-office**, where latency is seconds and HITL is natural:

1. **Clerk agent** — broken PTP, bounce, doc request, callback diary. Triggered by events (`treatment/followthrough` already re-decides). Speaks only to WhatsApp/SMS templates and the queue. Humans approve legal/field.
2. **Floor copilot** — sits on `/floor` and `/handoff`. Not another voice. Reads live QA flags, authority verdict, treatment recommendation, and drafts the whisper / wrap-up. You have the pack (`GET /qa/interactions/{id}/pack`).
3. **QA calibrator** — proposes rubric edits from locked `[live]` cells vs autoscore drift. Never overwrites live-locked scores.
4. **KB gardener** — unanswered table → draft FAQ skill → human publish. Prompt Studio already deep-links from gaps.
5. **Offer / treatment tuner** — suggests weight changes from `offer_decisions` / `treatment_decisions`. Apply only in shadow, then promote. The model never writes `RECO_W_*` live.

Customer-facing custom agents come **after** these, because a bad clerk agent emails the wrong NOC; a bad voice agent threatens a borrower after 7pm.

### 6. Memory that is not “dump the CRM in the prompt”

Intelligence here is **state machines + case memory**, not ChatGPT memory:

- **Turn memory:** already in the interaction
- **Case memory:** `(customer, trigger_kind, trigger_ref)` — treatment already groups this
- **Customer memory:** last PTP, last decline, hardship hold, preferred channel, language — structured, queryable
- **Skill memory:** “this objection worked on this cohort” — only after an eval, never raw weights in prod

Cross-channel: the WhatsApp bot and the voice bot must share `CallContext`-equivalent, or the “custom agent” is a goldfish. That is more valuable than a second persona slider.

### 7. Evals as the publish gate (or Agent Studio is a toy)

Sandbox already exists. Make it the CI for agents:

- Scenario packs per skill (you have rehearsal personas)
- Contract tests: “never names a product `recommend_next_offer` did not return”
- Compliance tests: after-hours, third-party disclosure, threat lexicon
- Voice tests: barge, interruption, Hindi/Hinglish via `understanding.py`
- Shadow traffic: new agent scores in parallel, live QA coverage is the hero metric you already track

Publish = prompt + flow + skills + connectors + **eval report**. Rollback is already there.

### 8. Observability: traces, not vibes

You have turn traces, tool calls, reco/treatment decision logs. Agent Studio needs one zipper:

`who (agent/skill) → why (engine verdict) → what tool → MCP server → human gate → outcome (PTP kept)`

That is OpenAI tracing + your `bot_tool_calls` + `treatment_decisions`. Without it, a tenant cannot debug “why did the insurance specialist talk on a hardship call?”

---

## How a tenant would actually “wire a use case”

Example: **HDFC-style insurance lapse + EMI bounce** (the tenant already spans loans and insurance).

1. Clone skill `broken-ptp-chase` → `premium-lapse-chase` (copy, 13th-month clock).
2. Attach MCP: policy admin system (read status) + payment link (write only after verify).
3. Create agent **Lapse Specialist**: tools = `{get_customer_context, request_documents, capture_lead, escalate}`; handoff allowlist = `{Collections, Human}`.
4. Agent graph: bounce event → treatment engine says `whatsapp` → Clerk agent sends template → if no pay in 4h → voice **Collections** → if “policy also lapsing” intent → handoff **Lapse Specialist** → reco may or may not allow a rider pitch.
5. Routing rule: DND or hardship hold → treatment `wait`. Not a prompt.
6. Sandbox: 12 scenarios. Live QA barge still fires on threat language.
7. Publish to `staging`, shadow 48h, then `production`.

The user never wrote a Python tool. They also never got to invent a waiver.

Second example: **external copilot**. A bank’s internal Claude/Cursor connects to *your* MCP server with `crm.read` + resources. Their credit ops agent preps the floor for tomorrow’s list. Writes still happen only inside BigBound after identity. That is how you become infrastructure, not a chatbot.

---

## What “most intelligent” means here (priority order)

Intelligence is not a bigger model on the greeting.

1. **The engines decide; the agent speaks.** Reco / treatment / authority stay gated. Custom agents *call* them, they do not replace them.
2. **Coverage and time-to-touch.** Clerk + treatment followthrough agents beat a wittier PTP script.
3. **100% scored, barge-capable critic.** You shipped this. Custom agents inherit it; they don’t opt out.
4. **Grounded tools.** CBS/payment MCP so “I already paid” is a lookup, not a vibe.
5. **Specialists with allowlisted handoffs.** Mesh roles become first-class Agent Cards.
6. **Skills with progressive disclosure.** Hindi hardship intake without stuffing the voice context.
7. **Evals + traces + Agent Cards** (purpose, data class, regulator). AFIX/FINOS-style metadata on every agent — BFSI buyers will ask.
8. **Only then:** fancier models, multi-agent debate, self-modifying skills.

Item 8 without 1–7 is a demo. Item 1–7 with a mid-size model is a product a collections head can buy.

---

## Suggested build sequence (so this doesn’t become a science project)

File-level schemas, APIs, compiler gates, UI, tests, and PR order live in `agent_transformation_implementation.md`. That spec is **peak, not demo**: no stub eval badges, no fake vault URLs, no UI-only publish gates.

**Phase 0 — honest seams**  
Publish is a compiler step: `flowValid` blocks UI **and** API; authored `flow` actually ships. Mesh roles load from JSON. MCP runbook. Trace field stubs. Vault inventory. Flag names.

**Phase 1 — Agent Cards as the fleet**  
Break the one-published-prompt-per-tenant monopoly. Four first-party cards, typed `handoff_to_agent`, compaction, OTel, regression + red-team **blocking** publish, Agent Studio fleet UI.

**Phase 2 — Skills as the knowledge plane**  
Full agentskills.io packs (not a textarea). Progressive disclosure, signed versions, per-skill **outcome** evals, sandboxed pure-function `scripts/`, KB gardener.

**Phase 3 — MCP both ways + gateway + vault**  
Stateless HTTP + mTLS + resources + prompts + Tasks. Pay-link then LMS connectors. LiteLLM/APIM gateway. Real Key Vault refs.

**Phase 4 — Internal agents that eat delay**  
Clerk, floor copilot, vision ingest, simulation twin, Temporal-shaped work runtime. This is the collections-head P&L phase.

**Phase 5 — Tenant-authored agents + A2A**  
Clone/fork, canary traffic with auto-rollback, partner mTLS A2A, MCP Apps, OPA export, Roles writable.

**Phase 6 — Self-improve under gates**  
Gateway model canaries. Twin + red-team on every upgrade. Shadow tuners. No unsupervised policy writes.

Do not start at Phase 5. That is how every “agent builder” ships an unregulated GPT. The hackathon-grade costume (Studio list + fake eval badges) is explicitly forbidden in the implementation spec.

---

## Non-goals (say these out loud in the pitch)

- Users cannot author a tool that posts to the ledger without going through `evaluate_authority` / identity / consent.
- Users cannot disable live QA or DND “to improve conversion.”
- The conversation canvas is not the place to draw CBS SOAP calls.
- Multi-agent debate on a live call is too slow and too leaky. Specialists hand off; they don’t committee.
- Do not wrap every Python engine in an LLM “for flexibility.” Reco exists because the LLM was a bad product picker.

---

## Bottom line

The demanding tech is not “custom GPTs.” It is **Skills + Agent Cards + MCP (server, client, Tasks, Apps) + allowlisted handoffs + A2A**, sitting on the policy engines you already built, with a **gateway, vault, eval/red-team compiler, and optional Temporal** around them.

**Habibi is the factory floor:** Agent Studio (fleet, locked policy, compiler-grade publish), Skills library, Integrations as connector/vault/MCP/A2A console, Sandbox as eval cockpit, Floor as copilot + approvals. Prompt Studio becomes the editor; Flow canvas stays the mouth; a second canvas is the org chart; Routing stays the law; Roles finally ship.

Highest-leverage next coding step: Phase 0 in `agent_transformation_implementation.md` (work packages 0.1–0.4). Frontend in that same step: disable Publish when the flow is invalid **and** reject invalid graphs on the API. Platform gaps and UI are in phases.md §1.5 / §7; the peak build spec is the implementation file.
