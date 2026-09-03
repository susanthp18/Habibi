# 36 — Workflow & State Machines

**Role:** Workflow and state-machine architect.
**Question:** What implicit state machines exist, and where do they disagree, deadlock, or accept illegal moves?
**Scope:** `backend/` (SQL `backend/sql/*.sql` as ground truth + Python transitions), `Habibi/src/` (operator console), workers. `PRAXIST-main/` out of scope (no DB state). `source_db/` is RAG corpus only.
**Date:** 2026-09-03
**Mode:** Read-only. Five parallel analysts (status/enum, workflow, database-state, frontend-state, event-transition); claims verified against source cited.
**Companions:** `12-data-model.md` (CHECK inventory), `35-business-rule-consistency.md` (rule splits), `15-concurrency.md`, `23-e2e-workflows.md`, `31-runtime-wiring.md`.

**Method:** Grep for `status|state|enum|Literal\[|transition|lifecycle|queued|running|pending` + read of `backend/sql/*.sql`, `outbound.py`, `campaigns.py`, `cadence.py`, `bot_jobs.py`, `whatsapp_outbound.py`, `delivery_receipts.py`, `db.py`, `schemas.py`, `bot_worker.py`, `worker.py`, `a2a.py`, `work_runtime/adapter_pg.py`, `canary.py`, `Habibi/src/data/*-seed.ts`.

**Key fact:** There is no ORM and no state-machine library. Source of truth for *value domains* is `TEXT + CHECK` in `backend/sql/*.sql` (never native pg ENUM, per `backend/DATA_MODEL.md:306`). *Transitions* are raw Python in `db.py` / domain modules / workers. There is no XState/zustand/redux/useReducer on the frontend — only `useState` (680 sites) + TanStack Query + seed-file union types. Every diagram below is reconstructed, not declared.

---

## 1. Executive summary

~40 state-bearing entities. Three machines carry the product: **outbound dial (`call_attempts`, 16 states)**, **cadence retry ladder (`call_cadence_state`, 4 states)**, and **queue/retry jobs (`bot_turn_jobs`, `whatsapp_outbound_jobs`, `kb_index_jobs`, `mcp_tasks`)**. Around them orbit conversations, promises/payments, deployments/canaries, and config lifecycles.

The machines are individually reasonable. The system is not:

1. **DB enforces vocabularies, never transitions.** No transition-guard triggers exist (only `set_updated_at()`, `13_triggers.sql:1`). Only `leads.stage` has a real transition map (`db.py:5876-5933`). Everything else accepts any CHECK-listed value over any other — `patch_dispute`, `patch_callback`, `patch_document_request`, `followups`, `campaign_runs.set_status` have zero edge guards.
2. **Two spellings for the same states.** `canceled` (single-l, Twilio) vs `cancelled` everywhere else; `input-required` (hyphen, `a2a_tasks`) vs `input_required` (underscore, `work_runtime_jobs`). Cross-table analytics and shared constants cannot work.
3. **Resurrection is legal.** A2A `signal_task` has no source guard — `completed → submitted` accepted. `work_runtime finish/claim` accept `cancelled → working/completed`. `mark_cancelled` accepts `succeeded/dead → cancelled`. `gateway promoted` is not DB-tied to required gate columns.
4. **Dead / orphan states everywhere.** `bot_turn_jobs.failed` and `whatsapp_outbound_jobs.failed` are in CHECK but never written. `campaign_targets.failed` never written. `cadence.escalated` never written by cadence. `voice_sessions.starting/ending` never written. `conversations` re-escalation path diverges (`record_handoff` doesn't touch status).
5. **UI and backend run different machines.** Capitalised `ThreadContext.lastPromise.status` (`"Kept"` vs `"kept"`), `Sender` dropping `"system"`, phantom `"sending"` with no FE member, two `DeliveryStatus` types with the same name and 1 overlapping value, truncated `ReminderStatus` (3 of 6), untyped `confirmStatus==="suppressed"` that exists nowhere in backend, `on_call` presence state with no backend, `Record<string,…>` tone maps that swallow unknown states.
6. **Retry logic is copy-pasted 4× with different caps/backoffs**, and retryability itself is defined 3× (`outbound.RETRYABLE`, `cadence.retry_on`, `call_closer._CONNECTION_BY_STATE`). One edit diverges dial-vs-ladder behavior.
7. **Three overlapping session lifecycles with no owner** (`voice_sessions` × `interactions` × `call_attempts`) can strand `interaction=active` + `voice=ended` forever if the Closer never runs.

---

## 2. State catalog (condensed)

Full per-table inventory (defaults, nullability, CHECK) is in §2 of the database-state analysis; per-file seed mirrors in frontend-state analysis. Condensed owner map:

| # | Entity | Values | Owner / writer |
|---|---|---|---|
| M1 | `call_attempts.state` | 16: `reserved, suppressed, dialing, ringing, answered, live, completed, voicemail_left, voicemail_skipped, no_answer, busy, rejected, failed, invalid_number, canceled, transferred, abandoned` (`21_outbound.sql:47-51`, `outbound.py:71-87`) | `outbound.py` (only monotonic machine) |
| M2 | `call_outcomes.connection / business` | 10 conn + 15 business (`21:111-135`) | `call_closer.py:115-129` (lossy merge) |
| M3 | `agent_obligations.state` | `open,honoured,missed,cancelled` (`21:173-174`) | closer |
| M4 | `campaign_runs.status` | `draft,running,paused,finished,cancelled` (`22:30-31`, `campaigns.py:51-55`) | `set_status` — unguarded |
| M5 | `campaign_targets.state` | `pending,dialing,done,failed,skipped` (`22:62-63`) | `campaigns.process_one` (`failed` orphan) |
| M6 | `call_cadence_state.state` | `open,exhausted,stopped,escalated` (`22:101-102`, `cadence.py:54-57`) | `cadence.on_outcome` (`escalated` orphan) |
| M7 | `pool_numbers.state` | `active,cooling,retired` (`22:135-136`) | `refresh_pool_health` |
| M8 | `interactions.status` | `active,completed,abandoned,failed` (`04:12`, no DEFAULT) | `voice/persist.py` |
| M9 | `voice_sessions.status` | `starting,live,ending,ended,failed` (`12:216-217`) | `voice/persist.py` (`starting/ending` orphan) |
| M10 | `conversations.status` | `bot,needs_human,escalated,assigned` (`04:177`) | `db.py` + `bot_runtime.py` |
| M11 | `identity_verifications.status` | `pending,verified,failed` (`04:163`) | `capture.py:1719-1836` |
| M12 | `messages.delivery_status` | free TEXT: `sending,sent,delivered,read,failed,cancelled` + NULL, **no CHECK** (`04:190`) | `bot_runtime.py`, `db.py:10773-10847` |
| M13 | `contact_delivery_events.state` | `queued,sent,delivered,read,failed,undelivered` (`03:192-194`) | `delivery_receipts.py:34-53`, append-only |
| M14 | `promises.status / reminder_status` | 5 / 6 (`05:23-24,46`) | `db.py:5152`, `promise_fulfillment.py` |
| M15 | `payment_intents.status` | `created,sent,opened,paid,expired,failed,cancelled` (`05:71`) | `payments.py`, `promise_fulfillment.py` |
| M16 | `disputes.status` | `new,under_review,awaiting_customer,resolved,rejected` (`05:121`) | `patch_dispute` — unguarded |
| M17 | `document_requests / delivery_attempts` | `requested,generating,sent,failed` / `queued,sent,delivered,failed,bounced` (`05:169,205`) | `db.py:6382+` — unguarded |
| M18 | `callbacks.status` | `scheduled,reminded,in_progress,completed,missed,rescheduled,cancelled` (`05:223`) | `db.py:5539-5562` — status unguarded |
| M19 | `followups.status` | `open,in_progress,snoozed,done,cancelled` (`05:253`) | `db.py:6225` — free write |
| M20 | `mandates / presentations` | `pending,active,suspended,cancelled,expired` / `scheduled,submitted,success,returned,cancelled` (`05:438-440,480-482`) | mandate engine |
| M21 | `leads.stage` | `interested,contacted,qualified,won,lost` (`06:9`) | `db.py:5876-5933` — **only guarded machine** |
| M22 | `bot_turn_jobs.status` | `queued,running,succeeded,failed,dead,superseded,cancelled` (`12:80-82`) | `bot_jobs.py` (`failed` orphan) |
| M23 | `whatsapp_outbound_jobs.status` | `queued,running,succeeded,failed,dead` (`12:187-189`) | `whatsapp_outbound.py` (`failed` orphan) |
| M24 | `kb_index_jobs.status` | `queued,running,succeeded,failed,dead` (`09:66`) | `kb_ingest.py` |
| M25 | `mcp_tasks.status` | `queued,running,succeeded,failed` (`16:73`) | `mcp_http/tasks.py` (no `dead` — poison retries forever) |
| M26 | `work_runtime_jobs.status` | `submitted,working,input_required,completed,failed,cancelled` (`17:46-48`) | `adapter_pg.py` — weak guards |
| M27 | `a2a_tasks.status` | `submitted,working,input-required,completed,failed,cancelled` (`18:47-48`) | `a2a.py` — weakest guards |
| M28 | `webhook_deliveries.status` | `success,client_err,server_err,pending` (`10:190`) | `webhooks_dispatch.py` |
| M29 | `webhook_endpoints.status` | `active,paused,broken` (`10:140`) | ops screens |
| M30 | `violations.status` | `open,in_review,acknowledged,resolved` (`07:25-26`) | `append_violation` writes `open`; **no `open→*` writer found** |
| M31 | `qa_scorecards.status` | convention `unscored,ai_draft,final`, **no CHECK** (`07:80-82`) | code coercion only |
| M32 | `coaching / calibration` | `assigned,in_progress,done` / `active,closed` (`07:114,129`) | `followups_db.py` (read-coerces synonyms write rejects) |
| M33 | `kb_documents / prompt_versions / bot_deployments` | `draft,indexing,indexed,stale,failed` / `draft,published,archived` / `active,rolled_back,retired` (`09:10,113,246`) | singleton partial uniques |
| M34 | `deployment_experiments / gateway_canaries` | `running,rolled_back,promoted` / `(stage × status)` (`18:13`, `19:23-24`) | `canary.py` |
| M35 | `mcp_connectors.status × health` | `draft,approved,disabled` × `unknown,healthy,degraded,down` (`16:53-56`) | `persist.py` (creation bypass) |
| M36 | `channel_consents.status` | `opted_in,opted_out,dnd,expired` × purpose (`03:22`) | `capture.py:328-499` |
| M37 | `users.status / agent_presence.status` | `active,inactive` / `available,on_break,wrap_up,offline` (`01:40,60`) | `db.py:511-604` |
| M38 | Boolean-composite states | `products.is_active`, `*_bindings.enabled`, `holds.released_at IS NULL`, `bots.archived_at`, `mcp_keys.revoked_at`, `leads.closed_at` | flags, not statuses; no `deleted_at/is_deleted/is_archived` columns exist |

Frontend mirrors live in `Habibi/src/data/*-seed.ts` (not one place): `CbStatus`, `ThreadStatus`, `DeliveryStatus` (×2, divergent), `EndpointStatus`, `DisputeStatus` (×2 defs), `DocStatus` (×2 defs), `PromiseStatus`, `ReminderStatus` (truncated), `ConsentStatus`, `ViolationStatus`, `KbStatus`, `LeadStage`, `ScorecardStatus/CoachingStatus`, `AgentFloorStatus` vs `PresenceStatus`, `OfferPolicyStatus/AuthorityPolicyStatus/GateStatus`, `SaveStatus/ShipState`, `CopilotStreamState`, handoff derived state.

---

## 3. State diagrams

### M1 — `call_attempts` (the only monotonic machine)

```
∅ ──reserve()──▶ RESERVED
RESERVED ──suppress(gate deny / fleet busy / outbound disabled)──▶ SUPPRESSED (guarded: only if reserved)
    outbound.py:426-438,588,734
RESERVED ──_mark_dialing──▶ DIALING (guarded: only if reserved)
    outbound.py:796-814
RESERVED/DIALING/RINGING ──fail()──▶ FAILED
    outbound.py:817-828
DIALING ──carrier ringing──▶ RINGING ──carrier in-progress──▶ ANSWERED ──bind_interaction──▶ LIVE
    apply_provider_status rank-monotonic, outbound.py:871-937; bind outbound.py:965-971
ANSWERED/LIVE ──carrier terminal──▶ {COMPLETED, VOICEMAIL_LEFT/SKIPPED, NO_ANSWER, BUSY, REJECTED,
    FAILED/INVALID_NUMBER, CANCELED, TRANSFERRED, ABANDONED}
ANY non-terminal ──mark(state)──▶ arbitrary state (guarded NOT ANY(TERMINAL))
    outbound.py:1006-1024
ANY in-flight + stale 30m ──sweep_stale──▶ FAILED:no_carrier_callback
    outbound.py:1038-1050
```

Rank `_RANK` (`outbound.py:122-129`): `reserved:0 … live:4, terminal:9`. Late `ringing` cannot overwrite `completed`. Twilio map (`134-144`): `queued/initiated→dialing, ringing→ringing, in-progress→answered, completed→completed, busy→busy, no-answer→no_answer, failed→failed, canceled→canceled`. `transferred/abandoned/suppressed/invalid_number` are locally derived, never from Twilio. `RETRYABLE={no_answer,busy,voicemail_left,voicemail_skipped,rejected}` (`114-116`) feeds cadence.

### M4+M5 — `campaign_runs` + `campaign_targets`

```
∅ ──create──▶ runs:DRAFT ; ∅ ──add_targets──▶ targets:PENDING
    campaigns.py:121-131,163-172
DRAFT ──set_status──▶ RUNNING ──set_status──▶ {PAUSED ⇄ RUNNING, FINISHED, CANCELLED}
    campaigns.py:373-392 (ANY→ANY, zero edge guard; side-effects started/paused/finished_at)
RUNNING ──_finish_if_drained (no pending/dialing)──▶ FINISHED
    campaigns.py:659-669
PENDING ──process_one admit OK──▶ DIALING (attempts+1)
    campaigns.py:597-607
PENDING ──no phone / customer gone / permanent DND──▶ SKIPPED
    campaigns.py:523,554,583
PENDING ──transient deny / out-of-window──▶ PENDING + next_attempt_at+=2h/30m
    campaigns.py:585-594,509-518
DIALING ──place==False (fleet busy)──▶ PENDING +5m
    campaigns.py:611-625
DIALING ──on_attempt_closed──▶ DONE
    campaigns.py:679-688
```

### M6 — `call_cadence_state` retry ladder

```
∅ ──ensure_case──▶ OPEN
    cadence.py:130-142
OPEN ──on_outcome business ∈ stop_on──▶ STOPPED
OPEN ──on_outcome connection ∉ retry_on──▶ STOPPED
OPEN ──on_outcome attempts>=max──▶ EXHAUSTED
OPEN ──else──▶ OPEN + next_attempt_at=now+backoff([4,24,72]h, cap 168h)
    cadence.py:205-253,79,97
OPEN+due ──process_one attempts>=ceiling──▶ EXHAUSTED (pre-dial)
OPEN+due ──no phone / customer gone──▶ STOPPED
OPEN+due ──admit deny──▶ OPEN +2h (no attempt consumed)
OPEN+run paused──▶ held (no state change)
    cadence.py:374-474
```

Non-`open` short-circuits (`cadence.py:205-206`) — no reopen. `escalated` is written by treatment/followthrough, never by cadence itself.

### M22/M23 — queue jobs (`bot_turn_jobs` / `whatsapp_outbound_jobs`)

```
∅ ──enqueue──▶ QUEUED
    bot_jobs.py:100-106; whatsapp_outbound.py:85-93
QUEUED ──claim_next_job (SKIP LOCKED, single-flight)──▶ RUNNING (attempt+1)
QUEUED siblings ──coalesce on claim──▶ SUPERSEDED (bot_turn only)
    bot_jobs.py:250-293
RUNNING ──mark_succeeded──▶ SUCCEEDED (+messages sending→sent for WA)
RUNNING ──mark_cancelled──▶ CANCELLED (no source guard — ANY→cancelled)
RUNNING ──mark_failed_or_retry attempt<cap──▶ QUEUED + run_after=2^attempt (bot cap 300s/5 attempts;
    WA min(120,2^a); webhook min(120,2^a), max 3)
RUNNING ──attempt>=cap──▶ DEAD + escalate
RUNNING stale ──reclaim──▶ QUEUED / DEAD by attempt>=cap
    bot_jobs.py:158-184,300-368; whatsapp_outbound.py:183-216,261-392
WA special: post_attempted_at NOT NULL + stale ──▶ DEAD (no requeue, double-send risk)
    whatsapp_outbound.py:183-199
WA special: ambiguous transport (timeout/429/5xx) ──▶ DEAD immediate
    whatsapp_outbound.py:307-328
```

`BOT_JOB_MAX_ATTEMPTS=5`, `BOT_JOB_STALE_RUNNING_SEC=300` (`bot_jobs.py:43-54`).

### M8/M9/M10 — conversations / interactions / voice (three overlapping lifecycles)

```
∅ ──start_voice_call──▶ interactions:ACTIVE + voice_sessions:LIVE
    voice/persist.py:143-156,189-196
LIVE ──heartbeat──▶ LIVE (only if live)
    voice/persist.py:667-678
ACTIVE ──complete_voice_call──▶ COMPLETED/ABANDONED/FAILED (default completed)
LIVE ──complete_voice_call──▶ ENDED (or FAILED if interaction failed)
    voice/persist.py:681-764
∅ ──get-or-create chat──▶ conversations:BOT
ANY ──escalate_conversation_to_human──▶ NEEDS_HUMAN + bot_turn_jobs →CANCELLED
    db.py:10144-10169,10505
```

Only `completed,abandoned` are compliance-scannable (`scan.py:36`). `starting/ending` never written (insert is `live` directly).

### M26 vs M27 — `work_runtime_jobs` vs `a2a_tasks` (duplicated HITL machine, divergent vocab)

```
∅ ──start_workflow (idempotent)──▶ SUBMITTED
SUBMITTED/WORKING ──claim_next──▶ WORKING
ANY ──park_input_required──▶ INPUT_REQUIRED (underscore) / INPUT-REQUIRED (hyphen!)
INPUT_REQUIRED ──signal approve/reject──▶ SUBMITTED / CANCELLED
ANY ──finish(ok)──▶ COMPLETED / FAILED
    adapter_pg.py:46-220; a2a.py:108-206
```

### M34 — deploy / canary / gateway

```
∅ ──record_experiment──▶ RUNNING (+auto RUNNING→PROMOTED supersede old)
RUNNING ──rollback_experiment──▶ ROLLED_BACK
    agent_core/canary.py:96-184
∅ ──gateway.propose──▶ RUNNING(stage=analysis) ──_finish_stage──▶ PASS/FAIL
PASS ──gateway.promote──▶ RUNNING(next_stage) ──▶ PASS/FAIL/PROMOTED(voice+all gates)
    llm_gateway/canary.py:119-166,193
```

### M14/M15 — promises / intents (clock-driven)

```
∅ ──create──▶ promises:UPCOMING ; tick ──settle──▶ DUE_TODAY ──tick+unpaid──▶ BROKEN (+followup + dispatch)
    db.py:5152; promise_fulfillment.py:863-964
payment_intents: CREATED/SENT/OPENED ──expiry──▶ EXPIRED ; ──record_payment──▶ PAID
    payments.py:159,220-257; promise_fulfillment.py:882-892
promise_reminders: QUEUED/SCHEDULED+due ──process_one──▶ SENT/FAILED
    promise_fulfillment.py:1044-1094
```

### Event backbone (worker drain order, `bot_worker.py:64-164`)

`settle_promises → sweep_stale → bot_turn → whatsapp_outbound → reminders → payment_events voice → call_closer → cadence → campaigns → treatment enact → followthrough → sweep → webhooks → clerk`. KB worker (`worker.py:407-424`) drains `tts_catalog_sync, revalidate_open_leads, sweep_due_followups, compliance.sweep, autoscore, mcp_tasks` on separate cadences. No celery/arq/kafka/redis runtime — broker is Postgres `SKIP LOCKED`; `arq` appears only as future contract (`bot_jobs.py:3`); Redis token bucket explicitly rejected (`outbound.py:578-583`).

---

## 4. Findings

### F1. Impossible states (declared but unreachable) — MEDIUM

| # | State | Evidence |
|---|---|---|
| F1.1 | `bot_turn_jobs.failed` in CHECK, never written — only `dead` | `bot_jobs.py` writes `queued/running/succeeded/dead/superseded/cancelled` only |
| F1.2 | `whatsapp_outbound_jobs.failed` in CHECK, never written | `whatsapp_outbound.py:293-392` writes `queued/running/succeeded/dead` |
| F1.3 | `campaign_targets.failed` in CHECK, never written | `campaigns.py:523-688` writes `pending/dialing/done/skipped` |
| F1.4 | `call_cadence_state.escalated` never written by cadence; `escalation_target` advisory only | `cadence.py:600-604` |
| F1.5 | `voice_sessions.starting/ending` never written; insert is `live` directly | `voice/persist.py:143-196` |
| F1.6 | `conversations` re-escalation: `record_handoff` sets `disposition=escalated` without touching `conversations.status` — two escalation paths diverge | `db.py:1157-1225` vs `db.py:10144-10169` |

### F2. Missing transitions (workflow gaps) — HIGH where noted

| # | Gap | Impact |
|---|---|---|
| F2.1 | `campaign_runs.set_status` has zero edge guard; route allowlists values but not edges (`main.py:4975-5005`). `draft→finished`, `cancelled→running`, `finished→running` all accepted | **HIGH.** Corroborated `AGENT_STUDIO_BUG_HUNT.md:174` (Start enabled for cancelled runs) |
| F2.2 | `violations`: `append_violation ∅→open` exists; **no `open→*` writer found** — review workflow missing in code | HIGH (compliance queue fills, never drains) |
| F2.3 | Deployment canaries: no `running→promoted` graduation (only supersede); `gateway.blocked` never written; `gateway.fail` terminal with no restart (must `propose` anew); `pct>=100` in `record_experiment:107-108` promotes old but inserts nothing — silent no-op | MEDIUM |
| F2.4 | `clerk._run` `DOC_SLA`/`CALLBACK` return `{"noted":True}` and `finish(ok=True)` — `sweep_overdue` jobs complete with no state change to `document_requests`/`followups`. No-op drain | MEDIUM |
| F2.5 | Bounce voice chase silently dropped: `process_one_voice` NULLs `next_voice_at` when `_try_voice_now` returns `False`, which includes transient contact-policy denies that write no new time | MEDIUM (`payment_events.py:910-958,809-907`) |
| F2.6 | Campaigns crash between commit (`dialing`+`reserve`) and `place` leaves `target=dialing` + `attempt=reserved` stranded — no `_recover_stranded` equivalent (cadence has one). Closer skips `reserved`, so attempt never closes | MEDIUM (`campaigns.py:597-610`, `call_closer.py:206`, `cadence.py:522-597`) |
| F2.7 | `a2a_tasks`: nothing writes `working/completed/failed` for A2A rows; those CHECK values orphaned (only `clerk._finish_a2a_remote` writes `completed` for the remote path) | MEDIUM |
| F2.8 | `promise_reminders` `unsupported_channel` (e.g. `voice`) → `failed` with no retry/alternate; `due` PTP reminder lost | LOW (`promise_fulfillment.py:1041`) |

### F3. Illegal transitions accepted by code — HIGH

| # | Illegal move | Evidence |
|---|---|---|
| F3.1 | `mark_cancelled` has no `WHERE status=` guard — ANY→cancelled incl. `succeeded/dead/superseded`. Called 10×+ in `bot_runtime.py` | `bot_jobs.py:317-324` |
| F3.2 | A2A `signal_task`: `nxt = submitted if approve else cancelled` — any typo/other signal **cancels** the task; no source guard so `completed→submitted` resurrection accepted | `a2a.py:194-206` |
| F3.3 | `work_runtime finish/claim_next` have no terminal guard — `cancelled→working/completed`, `working→working` self-loop accepted. `signal` guards `input_required`, but `finish` does not | `adapter_pg.py:114,164-206` |
| F3.4 | `sandbox complete_sandbox_run` ANY→completed — no guard, no `failed` path | `sandbox_runtime.py:1133-1151` |
| F3.5 | Connectors: `upsert→draft` default but accepts `status=approved` directly — creation bypasses `approve()` gates (https + dataClass checks). `approve` ANY→approved, no source guard. No `reject/disable` writer — `disabled` only via `upsert` | `persist.py:185-206,222,262` |
| F3.6 | `gateway_canaries.status=promoted` not DB-enforced to require gate columns (`regression/redteam/twin_report_id NOT NULL + injection_closed`); code computes `ok` but constraint allows bypass via direct write | `canary.py:188-193`, `sql/19:19-35` |
| F3.7 | Escalate has no source guard — re-escalating `needs_human` rewrites + re-cancels jobs | `db.py:10144-10169` |
| F3.8 | `patch_dispute` any→any, no read of current; `patch_callback` status free write (only `disposition` validated); `patch_document_request` timestamps but no transition table; `followups` free write; `export_jobs`, `messages.delivery_status` free | `db.py:5333-5358,5539-5562,6225,6382+` |

### F4. Duplicated transition logic — MEDIUM (divergence risk)

| # | Duplication | Evidence |
|---|---|---|
| F4.1 | Retryability defined 3×: `outbound.RETRYABLE`, `cadence.retry_on` (+ card `cadence_for().retry_on`), `call_closer._CONNECTION_BY_STATE`. Adding e.g. `rejected` to one diverges dial-vs-ladder | `outbound.py:114`, `cadence.py:262`, `call_closer.py:120-130` |
| F4.2 | In-flight defined 3×: `outbound.IN_FLIGHT`, `outbound.in_flight_count`, `campaigns._live_for_run` (latter omits `reserved`) | `outbound.py:90-92,448-450`, `campaigns.py:419-432` |
| F4.3 | Queue machine copy-pasted 4× (`bot_turn` / `whatsapp_outbound` / `kb_index` / `mcp_tasks`) with different caps/backoffs and different terminal vocabs (`succeeded` vs `completed`, `dead` vs none) | §3 M22/M23, `kb_ingest.py:118-169`, `tasks.py:26-123` |
| F4.4 | Phone-slot death flagged 3× with different keys: `call_closer._retire_phone_slot` (`phoneSlotDead`), `post_call_actions._mark_phone_dead`, `_promote_alternate` (`preferSlot`) — same `context` patch | `call_closer.py:799-820`, `post_call_actions.py:386-428` |
| F4.5 | Delivery truth in 3 stores with 2 rank maps: `messages.delivery_status` (`db._DELIVERY_RANK`), `contact_delivery_events` (append-all), `whatsapp_outbound_jobs.status` — plus `outbound._RANK` for voice. Out-of-order handling synced manually | `db.py:10773,808-830`, `outbound.py:122-129` |
| F4.6 | Case-closed in 2 mechanisms: `followthrough.resolve_case` only clears `enacted IS FALSE`; enacted-but-unattributed plans rely on `_case_still_open` to stop re-decision — one incomplete | `followthrough.py:401-479` |
| F4.7 | Frontend tone/order tables re-implemented per domain (`STATUS_LABELS/TONE/ORDER/DOT/PILL` in callbacks, disputes, documents, promises, upsell, kb, webhooks) + inline magic comparisons (`cb.status==="scheduled"`, `v.status==="resolved"`) — N call sites per rename, no compiler error where `Record<string,…>` | `callbacks-seed.ts:66,76`, `CallbackList.tsx:28-48`, `documents-seed.ts:66-68`, `upsell/LeadTable.tsx:28` etc. |

### F5. Inconsistent status names — HIGH for F5.1–F5.2

| # | Inconsistency | Recommendation |
|---|---|---|
| F5.1 | `canceled` (single-l, Twilio spelling, `outbound.py:85`, `21:50`) vs `cancelled` in every other table (`campaign_runs`, `a2a`, `work_runtime`, `callbacks`, `followups`, `mandates`, `payment_intents`) | Alias + CHECK comment; normalize at analytics layer |
| F5.2 | `input-required` (hyphen, `a2a_tasks`, `18:48`) vs `input_required` (underscore, `work_runtime_jobs`, `17:46`) — same concept, two alphabets | Unify (migration + code const) |
| F5.3 | `skills.signature_status: unsigned` vs `skill_versions.status: draft` for same pre-sign stage (`15:9,24`) | Unify to `draft` |
| F5.4 | Dual closed-lead edge `won↔lost` bypasses pipeline (intentional mis-click correction, but invisible in funnel) | Ensure `lead_won/lost` events always emitted (they are, `db.py:5935-5941`); document |
| F5.5 | `rolled_back` on both `bot_deployments` and `deployment_experiments` with different meanings; canary `(stage × status)` allows `analysis/promoted` — require `promoted ⇒ stage='voice'` guard | Rename one; add guard |
| F5.6 | Offer/authority snapshots share `none,shadow` with different semantics | Always log namespaced (`offer:shadow` / `authority:shadow`) |

### F6. UI/backend state mismatch — HIGH for F6.1–F6.3

| # | Mismatch | Evidence |
|---|---|---|
| F6.1 | `ThreadContext.lastPromise.status` capitalised `"Kept"\|"Broken"\|"Pending"\|"Partial"` vs canonical lowercase + backend CHECK (`upcoming,due_today,kept,broken,partial`). Workaround `.toLowerCase()` in one place; any direct `=== "broken"` misses | `inbox-seed.ts:42`, `promises-seed.ts:10`, `05:23`, `CustomerContextPanel.tsx:29,111-113` |
| F6.2 | `Sender` drops `"system"` (`customer\|bot\|agent`) vs backend CHECK incl. `system`. Live `sender=system` rows fail FE union (`ThreadItem = Message\|SystemEvent` models separately) | `inbox-seed.ts:4`, `04:188` |
| F6.3 | `messages.delivery_status` phantom `"sending"`: backend writes `sending` with stuck-`sending` no-retry branch; FE `DeliveryStatus` has no `sending`. Column itself unconstrained (plain TEXT), so drift silent | `bot_runtime.py:415,1089,614-622`, `inbox-seed.ts:12`, `04:190` |
| F6.4 | Two `DeliveryStatus` types, same name: inbox `pending\|sent\|delivered\|read\|failed` vs webhooks `success\|client_err\|server_err\|pending`. Only `pending` overlaps — import confusion risk | `inbox-seed.ts:12`, `webhooks-seed.ts:3` |
| F6.5 | `ReminderStatus` truncated: FE 3 (`off\|scheduled\|sent`) vs backend 6 (`off\|queued\|scheduled\|sent\|acknowledged\|failed`). `queued\|acknowledged\|failed` unrenderable | `promises-seed.ts:13`, `05:24` |
| F6.6 | `confirmStatus?: string\|null` with magic `==="suppressed"` vs backend `promise_confirmations.status (created\|sent\|opened)` + `api/promises.ts:82` sets `"sent"`. `"suppressed"` exists nowhere in backend — dead branch or mock-only | `promises-seed.ts:39`, `PromiseSheet.tsx:305`, `05:71` |
| F6.7 | Presence aliasing: UI `break\|wrap` vs API `on_break\|wrap_up` needs `uiToPresence/presenceToUi`; floor adds 5th state `on_call` with no presence equivalent; `handoff.lazy.tsx:385` bypasses mapping with raw `"wrap_up"` | `presence.ts:7,70-84`, `floor-seed.ts:8`, `WorkforceStrip.tsx:5-16` |
| F6.8 | QA vocab wider in DB history: FE `unscored\|ai_draft\|final` vs migration mapping legacy `completed\|reviewed\|final→final`, `draft\|ai_draft\|in_review→ai_draft` — direct `=== "unscored"` misses legacy rows. Same for coaching legacy `open\|pending\|new\|active\|closed` | `qa-seed.ts:5-6`, `20260722_0010:192-193`, `20260722_0022:63-101`, `ScoringQueue.tsx:114` |
| F6.9 | `Record<string,…>` tone maps (`LIVE_QA/SERVING/MODEL/VERDICT/HOLD_TONE`) with `?? "neutral"` fallbacks hide unknown backend states instead of surfacing them | `floor-seed.ts:57`, `treatment.lazy.tsx:226-239` |
| F6.10 | API schema truncation: `schemas.py:110-111` `PromiseResponse.status` omits `due_today`, `reminderStatus` omits `scheduled/failed` that DB allows — API can never render what DB holds. `FollowupPatchRequest` (`schemas.py:1020`) exposes `open/done/cancelled` vs DB 5 incl. `in_progress/snoozed` | `schemas.py:110-111,1020`, `db.py:739-748` (+ presentation remaps `_ptp_status`, `_reminder_status`) |
| F6.11 | Doc-delivery vs message-delivery vocab: `document_notifications (queued\|sent\|delivered\|failed\|bounced)` ≠ inbox (`pending\|sent\|delivered\|read\|failed`) — `read` vs `bounced`, `pending` vs `queued`, no shared mapper | `05:205`, `inbox-seed.ts:12` |

### F7. Database enforcement gaps (no CHECK / no DEFAULT)

DB enforces *domains*, never *edges*. Worse, several status-ish columns have neither:

- **No CHECK:** `accounts.status` (`02:91`), `payment_plans.status` (`05:5`), `messages.delivery_status` (`04:190`), `interactions.disposition` (`04:13`), `qa_scorecards.status/band` (`07:80-82`), `export_jobs.status` (`08:59`), `invoices.status` (`10:249`), `integration_test_logs.status` (`10:51`), `provider_configs.health` (`10:26`), `live_alerts.severity` (`04:234`). Engine scans like `status='active'` silently skip typos.
- **NOT NULL with no DEFAULT** (one missing key = hard insert failure, not a safe state): `agent_presence.status`, `interactions.status`, `channel_consents.status`, `kb_*`.
- **Structurally enforced (good):** partial uniques for singleton states — one `published` prompt/bot (`09:139`), one `active` deployment/bot+env (`09:264`), one `champion` (`05:632`), one live hold (`05:302`), one open bounce/EMI (`02:178`), one open intent (`05:87-92`), one `running` experiment (`18:18`), one open canary (`19:37`); claim indexes paired with `FOR UPDATE SKIP LOCKED`.
- **History lesson:** `0063_status_checks_and_tenant_indexes` fixed "fresh DB has constraint, prod doesn't" drift; `0010` normalized QA vocab without adding the CHECK (gap persists); `0011` migrated `mine→assigned` (FE still derives `"mine"` — correct as derived, risky if persisted).

### F8. State-specific permissions (correct, but orthogonal)

Route RBAC (`authz.py:224-599`: `POST /outbound/campaigns/{id}/status → COLLECTIONS_WRITE`, `PATCH /consent/* → CONSENT_WRITE`, rollback experiment `AGENT_PUBLISH`, rollback deployment `BOT_WRITE`, archive card `AGENT_EDIT`, connector/canary/webhook `INTEGRATIONS_WRITE`) gates *who* may call. Status transitions themselves are enforced (or not) in domain code, not in `authz.py`. Status-dependent domain gates that do work: conversation ownership (`status='bot' AND assigned_user_id IS NULL`, `bot_runtime.py:131,957`); contact gate (denial still writes `suppressed`, `outbound.py:20-30`); cadence vetoes (`state≠open → no-op`, `paused` blocks retries); speak-vs-score (`offer/authority mode+status` suppress speech, keep scoring); A2A mTLS + `allowed_skills`.

Frontend enforces its own copy: `Composer.tsx:174-175` (`disabled=needsClaim||busy||sending`), `CallbackSheet` Start/Complete/Cancel gates, `ViolationCard` Acknowledge/Assign/Resolve disables, `AvailabilityToggle` guards. These mirror backend but share no constants — drift surface for F6.

---

## 5. Recommendations (no code changed)

| P | Rec | Addresses |
|---|---|---|
| P0 | Add edge guards to `campaign_runs.set_status` (allowed-edges map like `_LEAD_STAGE_TRANSITIONS`) + `patch_dispute/callback/document/followup`; add `WHERE status=` guards to `mark_cancelled`, `finish`, `signal_task`, `approve` | F2.1, F3 |
| P0 | Unify `canceled/cancelled` and `input-required/input_required` (single const, migration alias) | F5.1–F5.2 |
| P1 | Add CHECKs for `messages.delivery_status`, `qa_scorecards.status`, `accounts/payment_plans/export_jobs/invoices.status`; tie `gateway promoted` to gate columns; add `dead` to `mcp_tasks` or TTL | F1, F7, F3.6 |
| P1 | Single `RETRYABLE` + single `IN_FLIGHT` const; single delivery-rank map; single phone-slot-death key | F4.1–F4.5 |
| P1 | Fix FE mismatches F6.1–F6.6 (lowercase promise status, add `system` sender, add `sending`, split `DeliveryStatus` names, full `ReminderStatus`, kill `"suppressed"` branch); type tone maps as `Record<BackendUnion,…>` so renames fail loudly | F6 |
| P2 | Write the missing writers (`violations` review path, `campaign_targets.failed` or drop from CHECK, `cadence.escalated` or drop, `voice starting/ending` or drop, `bot_turn_whatsapp.failed` or drop from CHECK); add `_recover_stranded` to campaigns; fix bounce-voice NULL drop and `signal_task` typo-cancels | F1, F2.2–F2.8 |
| P2 | Reconcile the three session lifecycles: owner for `interaction=active + voice=ended` strand; monitor `call_attempts WHERE closed_at IS NULL AND state<>'reserved'` | §3 M8/M9/M10 |
| P2 | Deduplicate FE seed types (`DisputeStatus`, `DocStatus`, `DeliveryStatus` ×2) into one domain-types module; remove `Record<string,…>` fallbacks that mask unknown states | F4.7, F6.9 |

---

## 6. Appendix — evidence index

- Status/enum inventory: `backend/sql/21_outbound.sql`, `22_campaigns.sql`, `04_interactions.sql`, `05_collections.sql`, `12_crosscutting.sql`, `17_phase4.sql`, `18_phase5.sql`, `09_bot_config.sql`, `10_admin.sql`, `07_compliance_qa.sql`, `01_identity.sql`, `02_customer_account.sql`, `03_consent.sql`, `15/16/14/19` phase SQL; `backend/outbound.py:71-175`, `campaigns.py:51-55`, `cadence.py:54-57`, `bot_jobs.py:43-54`, `schemas.py:27-67,110-111,234-281,545-552,967-1020`, `db.py:511-604,739-748,5197-5207,5876-5941,7643-7652`.
- Workflows: `bot_jobs.py:100-368`, `whatsapp_outbound.py:49-600`, `campaigns.py:102-690`, `cadence.py:130-597`, `outbound.py:370-1054`, `voice/persist.py:143-764`, `work_runtime/adapter_pg.py:32-220`, `a2a.py:108-206`, `agent_core/canary.py:96-184`, `llm_gateway/canary.py:119-193`, `call_closer.py:200-1150`, `post_call_actions.py:77-563`, `clerk.py:36-260`, `treatment/enact.py`, `followthrough.py:95-505`.
- Events: `bot_worker.py:64-164`, `worker.py:407-424`, `main.py:825-898,3598-3666,4600-4618,4975-5005`, `db.py:10657-10974`, `payment_events.py:170-958`, `payments.py:220-394`, `promise_fulfillment.py:863-1094`, `webhooks_dispatch.py:208-463`, `voice/bot.py:1814-2307`, `voice/ws_proxy.py:39-156`.
- Frontend: `Habibi/src/data/{inbox,callbacks,disputes,documents,promises,consent,compliance,kb,floor,upsell,billing,qa,webhooks,customer360,consent}-seed.ts`, `api/{presence,inbox,floor,agent-studio}.ts`, `components/{inbox/meta,callbacks/CallbackSheet,compliance/ViolationCard,floor/*,upsell/*,webhooks/*,prompt-studio/*}`, `routes/{inbox,agent-studio.*,prompt-studio.lazy,treatment.lazy}.tsx`.
