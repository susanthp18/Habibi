# WhatsApp Reply Bot — Architecture Plan

> Status: **Decisions locked** (2026-07-22); revised with review feedback (single-flight coalesce, outbound send-before-persist fix, structural KB gate, return-to-bot)  
> Scope: Production-shaped text bot on Meta WhatsApp Cloud API, sharing one runtime with future Pipecat voice  
> Related: `conversation_inbox_plan.md`, `KB_plan.md`, `PROMPT_STUDIO_plan.md`, `PLAN_NEXT_PHASE.md`, `features.md`

---

## 1. Locked decisions

| # | Question | Decision |
|---|---|---|
| 1 | Channel | **WhatsApp text first**; architecture must share runtime with future **Pipecat voice** (adapter pattern). |
| 2 | Tool depth (v1) | **Read CRM + KB retrieve + safe writes** (PTP / dispute flag / callback / note) **+ escalate**. No payment collection. |
| 3 | Async model | **Best fit for this repo:** see §4. **v1 = Postgres `SKIP LOCKED` jobs** (same pattern as KB worker). **Scale path = Redis + Arq** (compose already anticipates Redis in `PLAN_NEXT_PHASE`). |
| 4 | Per-conversation concurrency | **Coalesce, not drop.** Many jobs may queue; **one runs at a time** via claim-time lock; running job uses **latest customer text + full history** and marks older queued jobs for that conversation `succeeded` / `superseded`. **No** partial unique index on `conversation_id`. |
| 5 | Outbound idempotency | **Persist outbound `messages` row before Graph Send** (`delivery_status=sending`, keyed by `bot_turn_job_id`). Retry must not call Send again if a sending/sent row exists for that job. |
| 6 | KB tool | **Structural gate** before BR-1 — not prompt-only. Intent allowlist and/or `kb_documents.type` filter and/or seed a small collections corpus. Insurance-only corpus must not answer late-fee/EMI. |
| 7 | Deployment authority | Loader follows Prompt Studio: **`bot_deployments` (active) is authoritative** for what runs; `prompt_versions.status='published'` is editor state kept in sync by publish/rollback — never load “published” alone and ignore deployments. |
| 8 | Tool traces | **`bot_tool_calls` required in BR-1** (not optional). |
| 9 | Escalation return | `needs_human` / take-over must have an explicit **return-to-bot** path so threads do not accumulate forever. |

### Why not Redis/Celery on day one

- Meta webhooks must return **200 fast**; work must be off the request path either way.
- This codebase **already** runs durable jobs via Postgres `FOR UPDATE SKIP LOCKED` (`backend/worker.py` + `kb_index_jobs`). Inventing Redis+Celery before multi-node load adds ops without unblocking capability.
- `PLAN_NEXT_PHASE` Phase 5 already names **Arq/Celery or SKIP LOCKED** and **`redis` in compose when Arq**. We design the **job contract** so the broker is swappable; we do not hard-wire business logic to Celery APIs.

**Choose Arq (not Celery) when graduating:** same language as FastAPI, asyncio-native, lighter than Celery for this service shape. Celery remains acceptable if the team already standardizes on it elsewhere.

---

## 2. Current state (grounded — no assumptions)

### Implemented

| Piece | Where | Notes |
|---|---|---|
| WA inbound webhook (verify + signature + idempotent ingest) | `main.py`, `whatsapp.py`, `db.process_whatsapp_webhook` | Persists customer message; **does not reply** |
| WA outbound send | `whatsapp.send_text_message`, gated in `send_conversation_message` | Agent-only today (take-over + 24h) |
| Conversation / interaction spine | `conversations`, `messages`, `interactions` | New WA thread creates both; `status='bot'` |
| Take-over | `takeover_conversation` | `assigned` + `assigned_user_id` + `activity_events` |
| Sandbox “brain” | `sandbox_runtime.py` | Prompt + `kb_retrieve` + Azure chat; **no tools**; not on WhatsApp |
| Azure client | `azure_openai.py` | Embed + chat; **no tool-call loop** |
| KB retrieve | `kb_retrieve.retrieve` | Shared; Inbox/Sandbox consumers exist |
| CRM reads/writes | `db.get_customer`, `create_promise`, `create_dispute`, callbacks, consent | Usable as tool backends |
| Bot config schema | `09_bot_config.sql` | `prompt_versions`, `bot_deployments`, `kb_snapshots`, `routing_rules`, `retrieval_logs` |
| KB job worker | `worker.py` | SKIP LOCKED claim loop |

### Missing (must build)

- Hook after inbound → enqueue bot turn  
- `get_active_deployment(bot_id, env)` (Prompt Studio contract; **not in code**)  
- `BotRuntime` (channel-agnostic agent loop + tools)  
- Azure **tool-calling** loop  
- Live **routing_rules** evaluation  
- Bot outbound path (consent/DND/24h + take-over race)  
- Job table + worker for bot turns  
- Multi-turn **slot/state** (`conversation_bot_state`)  
- **`bot_tool_calls`** table  
- **Return-to-bot** mutation + Inbox control  
- Outbound **persist-then-send** for bot  
- Unify Sandbox onto the same runtime  
- Structural KB gate / collections corpus for safe retrieve  

---

## 3. Target architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Channel adapters                                                         │
│  WhatsApp (Meta webhook)  ·  Sandbox HTTP  ·  Pipecat voice (later)      │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ enqueue BotTurnJob (idempotent)
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Queue transport                                                          │
│  v1: Postgres bot_turn_jobs + SKIP LOCKED                                │
│  scale: Redis + Arq (same job payload / handler)                         │
└───────────────────────────────┬──────────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ BotRuntime                                                               │
│  1. Load active bot_deployments (prompt + kb_snapshot + guardrails)      │
│  2. Policy gates (status=bot, consent, DND, 24h, rate limits)            │
│  3. Build session context (customer pack + recent messages + slots)      │
│  4. Agent loop: Azure chat + tools (bounded iterations)                  │
│  5. Routing rules → escalate or continue                                 │
│  6. Persist outbound message (sending) → Send API → update provider_ref  │
└───────┬─────────────────┬─────────────────┬──────────────────────────────┘
        ▼                 ▼                 ▼
   CRM tools (db.*)   kb_retrieve*     WhatsApp Send API
   bot_tool_calls     retrieval_logs   messages(sender=bot)
   activity_events                     interaction_sentiment
   routing_rule_executions

   * KB tool structurally gated (§6.2 / §6.4)
```

**Invariant:** adapters translate events ↔ channel I/O. **One** runtime owns policy, tools, RAG, escalation, writeback. Voice later = new adapter, same tools.

**Config authority (cross-plan):** This runtime is a **consumer** of Prompt Studio’s release unit. Load via `get_active_deployment(bot_id, env)` only — **active `bot_deployments` row is authoritative**. Do not resolve “whatever `prompt_versions.status='published'` is” independently, or this plan and Prompt Studio drift into split-brain. Publish/rollback in Studio must keep the invariant: active production deployment’s `prompt_version_id` equals the published prompt.

---

## 4. Queuing & async — best practices

### 4.1 Job contract (broker-agnostic)

```text
BotTurnJob {
  id                   # uuid
  conversation_id
  interaction_id
  customer_id
  trigger_message_id   # inbound messages.id
  trigger_provider_ref # WhatsApp wamid (inbound idempotency)
  channel              # whatsapp | sandbox | voice
  attempt
  status               # queued | running | succeeded | failed | dead | superseded
  superseded_by_job_id # set when coalesced away
  outbound_message_id  # messages.id reserved before Graph Send
  error
  locked_at / locked_by
  created_at / updated_at / run_after
}
```

**Inbound idempotency:** `UNIQUE (trigger_provider_ref)` (or `trigger_message_id`) so Meta retries never enqueue duplicate work for the same wamid.

**Do not** add `UNIQUE (conversation_id) WHERE status IN (queued, running)` — that drops rapid follow-up messages (see §4.5).

### 4.2 v1 — Postgres SKIP LOCKED

- Table: `bot_turn_jobs` (mirror `kb_index_jobs` semantics).
- Worker: extend `worker.py` **or** `python -m bot_worker` claiming with `FOR UPDATE SKIP LOCKED`.
- Enqueue **inside the same DB transaction** as inbound message insert when possible (atomic: message exists ⇒ job exists).
- **Backoff:** `run_after = now() + exponential(attempt)`; cap attempts (e.g. 5) then `dead`.
- **Reaper:** stuck `running` where `locked_at` older than N minutes → requeue (same as KB reaper pattern).
- **Pros:** no new infra; transactional with CRM; matches existing ops.
- **Cons:** weaker for multi-node fan-out, delayed/scheduled fan-out at high volume, pub/sub.

### 4.3 Scale path — Redis + Arq

When any of these become true, graduate:

- Multiple API/worker replicas contending heavily  
- Need delayed queues, rate-limit windows, or cross-service consumers  
- Job latency SLOs that need priority queues  

Then:

| Piece | Choice |
|---|---|
| Broker | **Redis** (compose service) |
| Worker lib | **Arq** (preferred) or Celery |
| Handler | Same `bot_runtime.handle_turn(job)` |
| Postgres job row | **Keep as durable outbox / audit** (optional write-through) or migrate to Arq job id + `bot_turn_runs` history table |

**Outbox pattern (recommended at scale):** webhook txn writes `bot_turn_jobs`; a tiny publisher moves `queued` → Redis; worker ack updates Postgres. Survives Redis blips without losing turns.

### 4.4 Webhook rules (Meta)

- Verify signature → parse → **persist + enqueue** → return **200** within seconds.  
- **Never** call Azure or Graph Send inside the webhook handler.  
- Deduplicate on `provider_ref` before enqueue.  
- On worker failure: retry with backoff; after max → `dead` + escalate conversation to `needs_human` + alert log.

### 4.5 Concurrency & ordering — coalesce (locked)

**Rejected:** partial unique index on `conversation_id` for queued|running. That makes the second enqueue **fail**, so rapid messages 2 and 3 are silently never processed — opposite of “queue extras.”

**Locked design:**

1. **Allow many queued jobs** per conversation (one per inbound message / trigger).  
2. **Claim-time single-flight:** before running, take a **per-conversation lock** (Postgres advisory lock, or `SKIP LOCKED` claim that also skips if another job for that `conversation_id` is already `running`). At most one job executes at a time.  
3. **Coalesce on run:** the running job:
   - Builds history from **all** messages (full transcript window).  
   - Treats the **latest customer message** as the primary user turn (not only its own `trigger_message_id` text if newer ones arrived).  
   - Marks other `queued` jobs for that conversation as **`succeeded` / `superseded`** (`superseded_by_job_id = running.id`) so they are not executed later as separate replies.  
4. Result: one coherent reply to a burst, **no dropped customer text**, **no N sequential “hi” / “hi” / “hi” replies**.

**Global:** rate-limit Azure calls (reuse/extend `kb_rate_limit` buckets: `bot_chat`, `bot_embed`).

### 4.6 What Redis is *for* (and not for)

| Use Redis | Do **not** put in Redis as source of truth |
|---|---|
| Job broker (Arq) | Conversation transcript |
| Short-lived rate-limit counters | Customer/account CRM state |
| Distributed locks at multi-node | Consent / DND / promises |

**Session truth stays in Postgres** (`messages` + optional slot state). Redis is transport/ephemeral only.

---

## 5. Multi-turn conversations — best practices

### 5.1 Session identity

- **Session = `conversations` row** (channel=whatsapp, linked `interaction_id`).  
- Do not create a parallel “chat session” store.  
- New inbound for known phone **reuses** open conversation (`_open_whatsapp_conversation` already does this).

### 5.2 Memory layers

| Layer | Store | Retention |
|---|---|---|
| **Transcript** | `messages` | Durable; source for LLM history |
| **Working slots** | `conversation_bot_state` jsonb (new) or columns on `interactions` | Intent, identity_verified, pending_ptp_amount, last_tool_errors, turn_count |
| **Long-term CRM** | customers/accounts/promises/disputes | Tools read/write; never only in LLM context |
| **Retrieval trace** | `retrieval_logs` | Debug / analytics |

**Working slots** exist so multi-turn flows (“yes, Friday” after “can you promise?”) don’t rely on the model re-inferring everything from a long transcript alone.

### 5.3 History window

- Send last **K messages** (e.g. 12–20 turns) to the model, truncated per turn.  
- Always inject a **compact customer pack** via tool or system preamble (balance, DPD, open PTP, DND) — refreshed each turn, not stale prompt vars only.  
- Prefer **tool calls** for dues/EMI over stuffing full ledgers into the prompt.

### 5.4 Turn lifecycle (happy path)

1. Inbound customer message persisted (`sender=customer`).  
2. Job enqueued (may sit behind other queued jobs for same conversation).  
3. Worker claims with per-conversation lock; coalesces superseded siblings (§4.5).  
4. Loads deployment + gates.  
5. Agent loop (tools) → final assistant text; every tool call → `bot_tool_calls`.  
6. **Outbound persist-then-send** (§5.7).  
7. Update slots, sentiment, routing execution, `conversations.updated_at`.  
8. If escalate → `status=needs_human`, stop auto-reply **until return-to-bot** (§8).

### 5.5 Take-over race

Before Send API (and again after LLM, immediately before Graph):

```text
IF conversation.status != 'bot' OR assigned_user_id IS NOT NULL:
  abort send; mark job cancelled; do not WhatsApp
```

Agent Inbox and bot must not interleave blindly.

### 5.6 Max turns & loops

- Honour `prompt_versions.guardrails.maxTurns` (Sandbox already reads this).  
- Hard ceiling env: `BOT_HARD_MAX_TURNS`.  
- Tool-loop ceiling: `BOT_MAX_TOOL_ITERATIONS` (e.g. 6).  
- Detect repeated tool failure → escalate, don’t spin.

### 5.7 Outbound idempotency — persist before Send (locked)

**Bug if we mirror today’s agent path (Send API → then INSERT):** send succeeds → DB commit fails → job retries → customer gets **two** WhatsApp messages. `UNIQUE(provider_ref)` cannot help: the wamid does not exist until after Graph responds.

**Required sequence for bot outbound:**

1. Insert `messages` row: `sender=bot`, `delivery_status='sending'`, body=final text, **`bot_turn_job_id` = job.id** (unique).  
2. Call WhatsApp Send API.  
3. Update row: `provider_ref=wamid`, `delivery_status='sent'` (or `failed` + error).  
4. On job **retry / reaper reclaim:** if a message already exists for this `bot_turn_job_id` with `delivery_status IN ('sending','sent')` → **do not call Graph again**; if `sent`, mark job succeeded; if `sending` stuck, reconcile (query status or mark failed and escalate — never blind re-send).

Agent `send_conversation_message` now follows the same persist-`sending`-first →
send → finalize order (aligned in `db.py`).

> **Design note (CodeRabbit review):** a crash *before* Graph submission is
> indistinguishable from a lost response *after* submission, and WhatsApp Cloud
> API has no client idempotency key. "Mark failed and escalate" can therefore drop
> a reply that was actually delivered. Implemented behaviour (`bot_runtime`) **fails
> safe**: a reused row still in `sending` is **not** auto-resent — the job is
> cancelled for manual reconciliation (`outbound_sending_unconfirmed`); only
> `failed` rows retry. A fully automatic resolution needs a durable reconciliation
> state machine or provider-side idempotency, which WhatsApp does not offer today.

**Success criterion:** worker retry after a successful Send produces **no second** WhatsApp message.

---

## 6. Agent loop & tools

### 6.1 LLM

- Extend `azure_openai.py` with `chat_with_tools(...)` (OpenAI-compatible tool calls on Azure deployment).  
- Temperature low (≤0.3) for collections.  
- System prompt from **active** `bot_deployments` → `prompt_versions` via `render_prompt` + real customer context (not Sandbox placeholders).

### 6.2 v1 tool catalog

| Tool | Backend | Notes |
|---|---|---|
| `get_customer_context` | `get_customer` + account/EMI summary | Always available; **authoritative for money** |
| `get_payment_history` | ledger accessors | Read |
| `get_emi_schedule` | `emi_installments` | Read |
| `search_knowledge_base` | `kb_retrieve.retrieve(source="bot")` | **Structurally gated** — see §6.4 |
| `create_promise_to_pay` | `create_promise` | Idempotency key = job id + tool name |
| `flag_dispute` | `create_dispute` | Capture only |
| `request_callback` | `create_callback` | Respect DND windows |
| `add_customer_note` | notes write | Audit |
| `escalate_to_human` | status `needs_human` + activity | Hard stop until return-to-bot |

**Guardrail:** informational payment **guidance** only — bot never executes payments (`features.md` / PLAN alignment).

### 6.3 Tool traces (required BR-1)

- Table **`bot_tool_calls`** (or equivalent): `job_id`, `conversation_id`, `tool_name`, `args` (jsonb), `result_ok`, `error`, `latency_ms`, `created_at`.  
- **Every** tool invocation in the agent loop writes a row — not optional, not logs-only.  
- Feeds debugging and Bot Analytics; missing traces make agent-loop failures unsupportable.

### 6.4 KB tool — structural gate (locked)

Today’s corpus is largely **HL Assurance insurance** products; the channel use case is **HDFC collections**. Prompt text (“CRM is authoritative for money”) is necessary but **not sufficient** — the model will still call `search_knowledge_base` and surface travel/fraud policy snippets for late-fee questions.

**Before BR-1 goes live, do at least one of:**

1. **Intent / topic allowlist** — tool returns empty / “unavailable” unless intent ∈ {product_faq, upsell_policy, benefits, …}; collections intents (balance, EMI, late fee, dispute process) never hit insurance chunks.  
2. **Document-type filter** — retrieve only `kb_documents.type IN ('sop','compliance', …)` once collections docs exist; exclude pure product marketing when intent is collections.  
3. **Seed a small collections corpus** (late fee, waiver SOP, dispute intake FAQ, payment guidance) and pin via `kb_snapshot_id` on the active deployment.

Recommended combo for BR-1: **(1) always** + **(3) if time** so the tool has something safe to return for policy questions. Until then, prefer CRM tools only for money and escalate when the customer asks policy the bot cannot ground.

Money facts: **CRM tools only** — structural (tool results / system blocks), not merely a sentence in the system prompt.

### 6.5 Other tool practices

- JSON-schema tool defs; validate args before DB writes.  
- All writes: existing mutation functions + `activity_events` + idempotency keys tied to `job_id`.  
---

## 7. Policy gates (before any Send)

1. `BOT_RUNTIME_ENABLED=true`  
2. Conversation still `status=bot` and unassigned  
3. WhatsApp channel consent opted-in; customer not DND (or rule says SMS-only follow-up — don’t WA blast)  
4. Inside **24h** customer-care window (else escalate or approved template — no silent fail)  
5. Per-conversation and global rate limits  
6. Guardrail / routing rule did not already force handoff  

---

## 8. Routing & escalation

- Implement evaluator over `routing_rules.conditions` + `action_key`.  
- On each turn: build context `{intent, sentiment, consent_dnd, channel, ...}` → match → `routing_rule_executions`.  
- Actions: `handoff` / `needs_human` / `suppress_reply` / template (later).  
- Align with Inbox: escalated threads appear under **Needs human**.

Intent/sentiment v1 may start from improved classifiers (replace Sandbox keyword-only over time); store on `interactions` / `interaction_sentiment`.

### 8.1 Return-to-bot (required)

Escalation / take-over **must** have a reverse path, or Inbox **Needs human** accumulates forever and the bot never resumes.

| Path | Behavior |
|---|---|
| Agent **Take over** | Already: `assigned` + `assigned_user_id`; bot jobs abort (§5.5). |
| Agent **Return to bot** (new) | Clear `assigned_user_id`, set `status='bot'`, write `activity_events` (`conversation_return_to_bot`), cancel pending human-only UI lock. Subsequent inbound enqueues bot jobs again. |
| Auto / supervisor | Optional later: routing action `return_to_bot` after idle SLA — not required for BR-1 if Inbox exposes the agent control. |

BR-1 must ship **API + Inbox control** (or at least API) for return-to-bot; do not treat escalate as a one-way door.

---

## 9. Infra & config

### Env (add)

```env
BOT_RUNTIME_ENABLED=true
BOT_ENVIRONMENT=production          # selects bot_deployments.environment
BOT_HARD_MAX_TURNS=12
BOT_MAX_TOOL_ITERATIONS=6
BOT_JOB_MAX_ATTEMPTS=5
BOT_JOB_STALE_RUNNING_SEC=300
# Scale path (later):
# REDIS_URL=redis://redis:6379/0
# BOT_QUEUE_BACKEND=postgres|arq
```

### Process topology

| Process | Role |
|---|---|
| `uvicorn` API | Webhooks, CRM, enqueue only |
| `worker` / `bot_worker` | Claim jobs + BotRuntime |
| Postgres | System of record + v1 queue |
| Redis | Later: Arq broker |
| ngrok (dev) | Public WA webhook |

Compose evolution (from `PLAN_NEXT_PHASE`): `api` + `worker` + `db` + `minio` + later `redis`.

---

## 10. Observability

- Structured logs: `conversation_id`, `job_id`, `wamid`, deployment id, Azure latency/tokens.  
- Persist: `bot_tool_calls` (required), `retrieval_logs`, `routing_rule_executions`, `activity_events`, message `provider_ref` / `bot_turn_job_id`.  
- Metrics (later OTel): queue depth, time-to-first-reply, tool error rate, escalate rate, coalesce/supersede rate.  
- Dead-letter inspection: admin query or Bot Analytics “failed turns”.

---

## 11. Phased delivery

### Phase BR-0 — Foundations
- [ ] `get_active_deployment(bot_id, env)` — **deployments authoritative** (see §3 / decision #7)  
- [ ] `bot_turn_jobs` migration + claim/reaper (**no** unique on conversation_id; statuses include `superseded`)  
- [ ] `azure_openai.chat_with_tools`  
- [ ] `BotRuntime` skeleton + tool registry (read-only CRM tools first)  
- [ ] `bot_tool_calls` schema  
- [ ] Enqueue from WhatsApp ingest (feature-flagged)  
- [ ] KB structural gate design (§6.4) — implement stub that refuses off-intent retrieve

### Phase BR-1 — Live WA auto-reply
- [ ] Full gates (status/consent/DND/24h/take-over race)  
- [ ] **Persist-then-send** outbound (§5.7) + retry-safe  
- [ ] Coalesce single-flight (§4.5)  
- [ ] Safe write tools + `escalate_to_human`  
- [ ] **Every tool call → `bot_tool_calls`**  
- [ ] Slot state (`conversation_bot_state` or equivalent)  
- [ ] **Return-to-bot** API (+ Inbox control)  
- [ ] KB gate live: intent allowlist and/or collections corpus seed before trusting retrieve

### Phase BR-2 — Routing + harden
- [ ] Live `routing_rules` evaluator  
- [ ] Dead-letter → `needs_human`  
- [ ] Rate limits + richer telemetry  
- [ ] Sandbox switched to `BotRuntime` (parity)

### Phase BR-3 — Scale queue (when needed)
- [ ] Redis in compose  
- [ ] Arq worker; keep durable outbox/history in Postgres  
- [ ] Priority / delayed jobs if required  

### Phase BR-4 — Voice adapter (existing Phase 4)
- [ ] Pipecat calls same tools + same deployment loader  
- [ ] Shared realtime bus for Handoff/Floor (Inbox Phase D)

---

## 12. Explicit non-goals (this plan)

- Pipecat for WhatsApp text  
- Payment execution / card capture by bot  
- Redis as transcript store  
- Blocking Meta webhook on LLM  
- Using unfiltered insurance KB as the collections answer engine (see §6.4 — gate or seed; do not “prompt harder”)  

---

## 13. Success criteria

1. Customer WhatsApp message while `status=bot` → bot reply on phone **and** in Inbox without agent take-over.  
2. Take-over mid-flight → **no** bot send.  
3. Duplicate Meta **inbound** delivery → **one** bot job / reply.  
4. Worker **retry after a successful Graph Send** → **no second** WhatsApp message (outbound idempotency).  
5. Rapid inbound burst → **one** coalesced reply covering latest text + history; superseded jobs not double-sent.  
6. Dispute / DND / max-turns / tool failure → `needs_human`; agent can **return to bot**.  
7. PTP/dispute/callback tools create real CRM rows + `activity_events` + `bot_tool_calls`.  
8. Collections money questions answered from **CRM tools**, not insurance chunks.  
9. Sandbox (after BR-2) exercises the **same** runtime as WhatsApp.  
10. Queue backend can move Postgres → Arq without rewriting tools/runtime.  

---

## 14. Immediate next step

Implement **BR-0** (deployment loader + job table + tool-capable Azure client + `bot_tool_calls` + enqueue stub behind `BOT_RUNTIME_ENABLED`), then **BR-1** end-to-end on Susanth’s WhatsApp thread with coalesce + persist-then-send + return-to-bot.

---

*Decisions locked: WA-first shared runtime; read+safe-write+escalate; Postgres SKIP LOCKED → Redis+Arq scale path; coalesce (not unique-index) single-flight; persist-then-send outbound; structural KB gate; deployments authoritative; `bot_tool_calls` required; return-to-bot required.*
