# 13 — Query performance

**Scope:** `backend/` database access patterns — SQL text, data-access layer, query amplification, indexing, transactions. `Habibi/src` only where it drives poll frequency. `PRAXIST-main/` excluded.
**Date:** 2026-09-02
**Mode:** Read-only. No application file was modified, no migration run, no write issued.
**Method:** five parallel analysts (SQL/query, ORM/data-access, N+1, indexing, transaction) plus a parent verification pass, then a merge of extras that survived a second source check. Every finding in this document was re-derived from source. Claims that could not be cited to a line were dropped.

Vocabulary is `CONTEXT.md`: Mouth, Agent Card, Locked Engine, Mission, Cadence, Outcome, Reachability.

---

## The measurement caveat

This pass could not attach to a live catalog. `docker` on the host exited without listing containers, so there is no `EXPLAIN`, no `pg_stat_user_tables`, and no row-count census here. A previous session against `collections_db` described a demo book (tens of customers, hundreds of ledger rows). That is consistent with a seed database; it is **not** reused as evidence.

Three rules that constrain every claim:

1. **A sequential scan over a demo table is the correct plan, not a defect.** Where a finding says the access path cannot use an index, that is a statement about the predicate as written, not about current latency.
2. **Cost arguments are structural.** They name the scaling variable (tenant event log, transcript length, open Inbox threads, idle worker ticks) and the code that multiplies it.
3. **Correctness hazards are volume-independent.** A `FOR UPDATE` held across a Twilio HTTPS call can duplicate a borrower-facing send on rollback at any table size.

Findings are **Confirmed** (code-cited structural certainty) or **Suspected** (with the check that would settle them). Nothing below is labelled slow from a stopwatch.

---

## Verdict

The data layer is **disciplined in the large and breached in a specific, nameable way in the small.**

The discipline is real: there is no ORM; every amplification is an explicit Python loop. `clamp_list_limit()` already bounds most CRM lists. Cadence, campaigns, the call closer, WhatsApp outbound, and webhook dispatch all commit the claim **before** they touch a carrier or an LLM. The Mouth's tool handlers wrap DB work in `asyncio.to_thread`. Partial indexes already exist for the outbound fleet gate, campaign target claim, treatment due-queue, and cadence due-queue.

Against that, three things are true:

- **The severe findings are one mistake repeated.** A function that dials or texts is locally correct — it commits its own receipt after the send. A caller several frames up still holds `FOR UPDATE`. Rollback un-records a send that already happened. Nothing in the type system or tests asks "is a transaction open N frames above this HTTP call?"
- **The worst *query* amplification is the Inbox poll, not a once-a-day batch.** `GET /conversations` already batches messages with `ANY(:ids)`, then pays 4–8 extra queries *per thread* to build sidebar context, including a full Reachability `evaluate()`, every 4 seconds (1.5s while a Mouth is typing).
- **The gaps are omissions from conventions that already exist.** `list_conversations` / `list_violations` / `list_scorecards` skip `clamp_list_limit()`. `customers` never got the expression index `accounts` already has. `followups` never got the partial index three sibling queues already have. Customer 360 *intends* to persist a treatment decision on card-open (`db.py:1259-1262`) but uses `engine.connect()` with no `commit()`, so SQLAlchemy 2.0.51 **rolls that INSERT back** — wasted engine work, not a live plan.

That last point is the most actionable: nearly every fix already has a worked example in this tree.

---

## Baseline facts

### Connection pools (from compose + `db.py`, not live `SHOW`)

| Process | Source | `DB_POOL_SIZE` | overflow | capacity | `statement_timeout` |
|---|---|---|---|---|---|
| `api` (`UVICORN_WORKERS=1`) | `docker-compose.yml:87-88,95,111` | 5 | 5 | **10** | 15,000 ms (`db.py:123-124`) |
| `worker` | compose `:148` | 3 | 2 (compose) | 5 | 60,000 ms |
| `bot_worker` | compose `:177` | 3 | 2 | **5** | 60,000 ms |
| `voice` | compose `:201` | 3 | 2 | **5** | 60,000 ms |
| `voice_insurance` | compose `:235` | 2 | 1 | **3** | 60,000 ms |

`create_engine` (`db.py:138-150`): `pool_pre_ping=True`, `pool_recycle=1800s`. **`pool_timeout` is not passed** — SQLAlchemy default 30s. Compose comment at `:3-6` budgets ≈25 app connections against `max_connections` 100; do not raise uvicorn workers without re-budgeting.

### Timeouts — why transaction findings are severe rather than untidy

Confirmed by reading `db.py:144-149` and grepping `lock_timeout` / `idle_in_transaction_session_timeout` in `db.py` (absent):

```
statement_timeout                   -> set per-connection in connect_args
lock_timeout                        -> unset (Postgres default 0 = wait forever)
idle_in_transaction_session_timeout -> unset (default 0 = wait forever)
```

**`statement_timeout` bounds one SQL statement. It does not bound time spent in Python between statements while a connection is checked out.** During a Twilio HTTP call inside an open transaction, no statement is executing — there is nothing for it to time out. A hung carrier call holds its pool slot until the process dies. Anything waiting on the locked row waits indefinitely.

### Data-access layer — established by reading, not assumed

**There is no ORM.** `db.py` has no `declarative_base`, `sessionmaker`, `Mapped[`, `relationship(`, `SQLModel`, or `scoped_session`. `backend/models/` is not a SQLAlchemy model package. Access is SQLAlchemy **Core**: `text()` strings on a sync psycopg driver, one process-wide `Engine` at `db.py:138-150`.

This changes what "N+1" means: there is no lazy-load to misconfigure. Every amplification below is an **explicit Python loop calling a DB function per iteration**, or a helper invoked once per row of a list the caller already had in memory.

Serialization is Pydantic `CustomerResponse` plus `_dump(...)` (`db.py:391-392`). Over-fetching here is "hydrate the whole aggregate then slice in Python," not an ORM `joinedload` mistake.

### Census (from this pass)

| Surface | Count / note |
|---|---|
| `main.py` `@app.` decorators | **314** |
| `async def` HTTP/WS handlers in `main.py` | 15-ish routes + websockets + `_authz_guard`; 295-ish plain `def` (Starlette runs those in the threadpool) |
| `list_*` in `db.py` | 43 functions. **Growing-data lists without `LIMIT`:** `list_violations`, `list_scorecards`, `list_conversations`, `list_routing_rules`. Catalog lists (`teams`, `products`, `canned_responses`, …) are seed-bounded and not re-flagged. |
| `clamp_list_limit()` | defined `db.py:172-211`; used by 18 list functions. Eight more have their own cap (handoff 50, eval reports ≤200, …). |
| `sqlalchemy.text(` (production `.py`) | ~500 call sites; `db.py` alone ~101 `text(` + 18 `_sql()` wrappers |
| `FOR UPDATE SKIP LOCKED` | present on bot jobs, WhatsApp outbound, webhook deliveries, work-runtime jobs, treatment decisions, followups escalation, bounce voice, promise reminders, cadence, campaign targets, campaign runs, MCP tasks, treatment sweep accounts |
| Engine construction | one `Engine` (SQLAlchemy **2.0.51**). `connect()` autobegins and **rolls back on context exit unless `conn.commit()`**. `begin()` commits on success. The previous draft of this file stated the opposite. |

This pass did not recount `text()` sites repo-wide; that number is not load-bearing.

---

## Class 1 — Transactions held across external calls

**Most serious class. One mistake, several live instances.** Each is a correctness hazard at any data volume: the send/dial happens, `mark_enacted` / `first_touch_at` / reminder status commit *after*, and a rollback releases the lock **and un-records the send**. The next claim re-selects the same row.

Every leaf that talks to Twilio is locally careful. `outbound.place()` (`outbound.py:533-596`) checks the fleet gate in its own transaction **before** the carrier call, and says so in the docstring. `twilio_sms.send()` (`twilio_sms.py:76-95`) sends, then `_record_sent` opens a *new* `engine.begin()`. **The hazard is introduced entirely by callers that wrap the chain in an outer transaction.**

### F1 — Severe — Twilio SMS inside a `FOR UPDATE` transaction, on the API event loop

`main.py:857-877` → `payment_events.py:188-201,664-693` → `twilio_sms.py:76-95`

```python
@app.post("/webhooks/collections/payment-events")
async def payment_events_webhook(request: Request):
    ...
    with db.engine.begin() as conn:
        return pe.ingest(conn, body)
```

`ingest()` takes `SELECT ... FROM accounts ... FOR UPDATE OF a`. The first-touch SMS branch calls `twilio_sms.send()` (`payment_events.py:669`) — blocking `client.messages.create` with `TwilioHttpClient(timeout=10)` — **then** writes `first_touch_at` (`:680-693`), which is the idempotency guard checked at `:218`.

Three defects compound:

- The account row lock is held for up to 10s of carrier HTTPS, unprotected by `statement_timeout`.
- The handler is `async def` with the work inline. `UVICORN_WORKERS=1` — the process's event loop stalls. Every other route, including Twilio TwiML, queues behind it.
- **Rollback duplicates the SMS.** `sent = True` is set at `:675`; the guard write commits after. CBS/PSP webhooks retry. `_record_sent` (`twilio_sms.py:113`) opens a **second** pooled transaction while the caller's lock is still held.

**Affected workflow:** inbound bounce-event webhook → statutory pay-link SMS. Bounce files arrive in EOD bursts.

**Runtime cost:** 1 of 10 API pool slots + the event loop for up to 10s per event, plus lock wait for any other worker touching that account. Not a big SQL cost; a concurrency and duplicate-contact cost.

### F6 — Severe — treatment voice enactment can dial the same borrower twice

`agent_core/treatment/enact.py:904-919` → `:317-390` → `outbound.py:533`

```python
with engine.begin() as conn:                    # outer tx, held throughout
    claimed = decisions.claim_due(conn, limit=1) # FOR UPDATE SKIP LOCKED
    acted, note = enact_one(conn, claimed[0])
```

`enact_one` (`:124-135`) runs the handler, **then** `decisions.mark_enacted(...)` on the same `conn`. `_dial_bot` opens a nested `engine.begin()` for `reserve` (`:338-380`) — necessary so `outbound.place` can see the attempt — then calls `outbound.place` **while the outer claim transaction is still open** (`:384`).

At the moment the dial is in flight: outer SKIP LOCKED connection (idle in transaction) + `place`'s own connection(s). Up to **3 of `bot_worker`'s 5 slots** for one decision.

Rollback after a successful dial releases the claim without `enacted`. The next `claim_due` picks the same decision and **dials again**.

`outbound.place`'s docstring reasons carefully about not leaving stray `dialing` rows. That reasoning does not cover an outer transaction held two frames up.

**Contrast (audited this pass, previously listed as a gap):** `cadence.process_one` (`cadence.py:357-492`) and `campaigns.process_one` (`campaigns.py:470-610`) **commit the claim, then call `place`**. Same `outbound.place`. The treatment executor did not copy that split.

### F10 — High (live SMS) / Severe (dormant rail) — same outer-tx shape on SMS and mandate presentment

Same `enact_one(conn, ...)` dispatch, same still-locked outer transaction.

- **`_send_sms` (`enact.py:295-314`)** — live whenever `TREATMENT_MODE=live` (this checkout's `.env:266`). Rollback → re-send. F6's hazard on SMS.
- **`_represent_mandate` (`:503-638`)** — takes a **second** row lock (`FOR UPDATE OF m` on `mandates`, `:547`) on top of the outer claim. If `TREATMENT_MANDATE_EXECUTOR=rail`, `_submit_to_rail` (`:589-596`) runs **before** the `INSERT INTO mandate_presentations` (`:609-638`). A debit can leave the building with no presentation row.

  **Verified dormant today:** `mandate_executor()` defaults to `lms` (`config.py:128`). `_submit_to_rail` raises `NoExecutor` unless `TREATMENT_MANDATE_RAIL_MODULE` is set (`enact.py:659-661`) — it is not in `.env.example`. The `_hand_to_lms` path is DB-only. This is a landmine for when the rail adapter is wired. The docstring at `:508-514` already names the stakes.

`_send_whatsapp`, `_queue_human`, `_change_emi_date`, `_open_self_service_plan` are DB-only or enqueue-only — safe.

### F7 — High — PTP reminder SMS stalls every other `bot_worker` queue

`promise_fulfillment.py:1044-1064` → `:1014`

`process_one_reminder` opens `engine.begin()`, `SELECT ... FROM promise_reminders ... FOR UPDATE SKIP LOCKED`, then `_send_reminder_copy` which calls `twilio_sms.send` on that same `conn` for `channel == "sms"`. WhatsApp reminders enqueue (`:1030-1039`) — correct.

`SKIP LOCKED` means other reminder *rows* are not blocked. `bot_worker.py:64-166` is a **strictly sequential single-threaded loop**. WhatsApp sends, PTP reminders, bounce-voice, call closing, cadence, campaigns, and treatment all run in series in one process. A slow Twilio call here does not merely hold 1 of 5 connections; it **stalls every queue the process owns** until it returns.

Same rollback/resend gap as F1.

### F8 — High — bounce autodial holds 2 of 5 worker connections per dial

`payment_events.py:910-958` → `:809-879`

`_try_voice_now` reserves on a *separate* connection (`:856`) — the comment at `:847-850` correctly explains this is so the reservation is visible to the fleet gate. That reasoning is sound. It does not change the fact that the outer `conn` from `process_one_voice` sits **idle-in-transaction** for the whole duration, including `outbound.place`. Combined with F7's serialization, Twilio latency across a modest backlog stalls the worker.

### F11 — High — `settle_promises` `FOR UPDATE`s every due promise, no `SKIP LOCKED`, then treatment per row

`promise_fulfillment.py:863-917`. One `engine.begin()`:

1. `UPDATE promises SET status = 'due_today'` with an IST date-cast that cannot use `idx_promises_status`.
2. `SELECT … FROM promises WHERE status IN ('upcoming','due_today') AND paid_amount < amount AND (promised_at AT TIME ZONE 'Asia/Kolkata')::date < … FOR UPDATE` — **no `LIMIT`, no `SKIP LOCKED`**.
3. Per row: status → broken, `_next_action` → `recommend_treatment` (~50–60 round-trips), INSERT followup.

Two workers block rather than split work. Locks are held for the whole recommend loop. Cadence of `SETTLE_EVERY = 20` ticks (`bot_worker.py:60,72`).

**Workflow:** Promise-break worker. Sibling claim queues already use `OF alias SKIP LOCKED LIMIT 1`.

### F12 — Medium — Inbox send holds `FOR UPDATE OF cv` across admit + enqueue (not the Graph call)

`send_conversation_message` (`db.py:10185-10325`). Lock taken inside `engine.begin()`, held through `contact_policy.require_admit` and `whatsapp_outbound.enqueue_agent_send`. The carrier send is the worker's job after commit — this is **not** F1. Concurrent Inbox replies/takeovers on the same thread serialize behind the conversation row.

### Cross-cutting root cause

F1, F6, F7, F8, F10 are not five unrelated bugs. Lint, tests, and type signatures do not catch "a transaction is still open N frames up when this HTTP call fires." That is the gap to close. F11 is the same class without an HTTP call: a bulk lock around per-row engine work. F12 is lock scope, not a carrier call.

---

## Class 2 — Event-loop blocking

### EL-1 — High — several `async def` routes do blocking psycopg3 work on the single event loop

`main.py` has **314** `@app.` decorators. FastAPI/Starlette runs plain `def` in the threadpool, so the vast majority of the route table is safe by construction. The finding lives in the `async def` routes, and they are mixed.

**Correct (to_thread, or no DB):**

| Route | Evidence |
|---|---|
| `twilio_voice_call_status` | `main.py:3656` `await asyncio.to_thread(_apply)` |
| `whatsapp_webhook_receive` | `:4618` `await asyncio.to_thread(db.process_whatsapp_webhook, ...)` — comment at the call site states the rule |
| `kb_upload_document` / `kb_new_version` | `:4447`, `:4473` `to_thread` |
| `stt_transcribe` | `:3287` `to_thread` |
| `demo_outbound_call` **carrier call** | `:4151` `to_thread(outbound.place, ...)` after the `begin()` block exits |
| `twilio_voice_outbound` **carrier call when an attempt exists** | `:3810` `to_thread(outbound.place, ...)` |

**Confirmed blocking on the loop:**

| Route | Line | What blocks |
|---|---|---|
| `payment_events_webhook` | `:875-877` | F1 — DB **plus** live Twilio SMS |
| `payment_provider_webhook` | `:842` | `engine.begin()` + `payments.record_payment` (FOR UPDATE + writes). Outbox insert only for webhooks — no HTTP inside this tx — but the DB work is still sync on the loop |
| `twilio_sms_status` | `:3701` | delivery-receipt lookups/updates |
| `twilio_voice_outbound` | `:3757` | mission/reserve/admit **inline**; bare-number path `:3805` calls `twilio_ops.start_outbound_call` **on the loop** |
| `demo_outbound_call` | `:4054` | SELECTs, `mission.build`, `reserve`, `admit` inline (Twilio itself is off-loop) |
| `ingest_document_request` | `:1654` | `ingest_customer_document(...)` sync; DB two frames down |
| `import_agent_studio_skill` | `:2359` | `upsert_skill_from_pack` sync |

**Why this is a regression rather than a missing design:** the convention exists, is commented, and is followed by the WhatsApp webhook and call-status callback in the same file.

### EL-2 — High — global authz dependency does a sync pool checkout on the loop

`main.py:507` `async def _authz_guard` is registered app-wide (`:585`). On a permission-cache miss (`authz.py:646`, TTL 30s) `_load_grants` (`:679`) does `with db.engine.connect()`.

**Failure shape, not observed live:** a burst of sync `def` handlers occupies the API's 10 connections. The next request's cache expires. `engine.connect()` from the loop waits up to `pool_timeout` (default **30s**, not set in `db.py`). `/health` does not answer; the liveness probe can kill a process whose database is healthy. `statement_timeout` bounds the query, not the pool wait.

Same shape: `ApiKeyMiddleware` → `actor_context._user_exists` (see `15-concurrency.md`).

**Query cost itself is a small join** (`user_roles ⋈ roles ⋈ role_permissions`). The performance issue is *where* it runs, not the SQL.

---

## Class 3 — Query amplification

### N0 — High — Inbox poll: batched messages, then 4–8 queries per thread including Reachability

**This is the highest-frequency amplification in the audit.** The prior architecture notes flagged unbounded `list_conversations`; they did not spell out the per-thread fan-out.

`Habibi/src/api/inbox.ts:102-136`: live Inbox refetches every **4s**, or **1.5s** while `botTyping` / `pendingOutbound`. Full list on first fetch and every 15th poll (~60s); otherwise `?updatedAfter=`.

Server path: `db.list_conversations` (`db.py:9059-9110`).

**What is already batched (do not "fix"):**

- `_conversation_messages` — `WHERE conversation_id = ANY(:ids)` (`:8616-8629`)
- conversation-level activity events — `entity_id = ANY(:ids)` (`:8632-8648`)
- suggestions — `ANY(:cids)` (`:8727`)
- bot-typing — batched (`:8866`)

**What is per conversation, in a Python loop:**

`_serialize_conversation` (`:8981-8990`) calls `_thread_context` (`:8756-8833`) for **every** returned thread:

| Query | Site |
|---|---|
| latest promise | `:8761-8769` |
| open disputes `LIMIT 5` | `:8771-8784` |
| last 3 interactions | `:8786-8798` |
| next EMI | `:8800-8813` |
| `contact_policy.evaluate(...)` | `:8584-8599` → `_load_customer`, `_rules_for`, `_channel_status`, `_today_count`, and on the allow path `_last_counted_at` + `_week_counted` + `_weekly_cap_for` (`contact_policy.py:554-594`) |

**Cost formula (structural):**

```
per poll ≈ 4 batched list queries
         + N × (4 context SELECTs + 3–6 Reachability SELECTs)
         + full message history for those N threads
```

`N` is every conversation on a full poll, or every thread touched since the watermark on a delta. One new message on a long thread still re-fetches **that thread's entire `messages` table**, not the delta (`_conversation_messages` has no `sent_at > :watermark`).

**Affected workflow:** operator Inbox, left open all shift. One tab at 4s is the baseline; a typing Mouth raises it to 1.5s. This is idle *operator* load, not idle *worker* load.

**Confirmed** from source + the frontend poll. Not timed.

### N1 — Medium/High — idle `bot_worker` issues a claim query for every queue, every 1.5s

`bot_worker.py:64-166`, `main()` sleeps `args.poll` default **1.5s** (`:171,218-234`).

`process_one_any` is a chain of `if <module>.process_one(...): return True`. When nothing is queued, **every branch is evaluated**. There is no upfront "is there any work" check.

Gates read from this checkout's `backend/.env` (flags only):

| Flag | Value | Consequence |
|---|---|---|
| `BOT_RUNTIME_ENABLED` | `true` (`:74`) | `bot_jobs.process_one` most ticks (reclaim + claim) |
| `CAMPAIGN_RUNTIME_ENABLED` | `true` (`:401`) | `cadence` + `campaigns` every tick |
| `BOUNCE_VOICE_ENABLED` | `true` (`:409`) | `payment_events.process_one_voice` every tick |
| `TREATMENT_MODE` | `live` (`:266`) | `treatment_enact` + `treatment_followthrough` every tick |
| `TREATMENT_SWEEP` | `1` (`:272`) | `treatment_sweep` every tick |

Always-on (no flag): `whatsapp_outbound` (reclaim + claim), `promise_fulfillment.process_one_reminder`, `call_closer`, `webhooks_dispatch`, clerk drain.

Always-on WhatsApp reclaim (`whatsapp_outbound.py:573-576`) is an extra `UPDATE` even when the queue is empty.

**Idle arithmetic (structural, not measured):** ~12–16 round-trips every 1.5s ≈ **8–11 queries/s sustained with nothing to do**, on the order of **0.7–1.0 million statements/day**. Every subsystem's *real* claim then queues behind that self-inflicted chatter. Nothing here needs 1.5s freshness across a dozen independent tables.

Every 20 ticks (`SETTLE_EVERY`, `:60`) additionally: `settle_promises`, `outbound.sweep_stale`, `outbound.sweep_pool_health`, clerk overdue, canary rollbacks.

### N2 — High — treatment sweep: one transaction, 50 account locks, `recommend_treatment` is ~50–60 round-trips not ~25

`agent_core/treatment/sweep.py:75-107`, `BATCH = 50` (`:63`).

`_claim` takes up to 50 delinquent accounts (`FOR UPDATE OF a SKIP LOCKED`, `:162`). Each `_decide_account` first hits `_decided_today` (`:201-214`, 1 SELECT). Already-decided accounts skip the engine; idle-with-sweep-on is therefore **~50 existence checks per tick**, not 50 full recommends. Undecided accounts enter a **savepoint** (`:181`) then `recommend_treatment`.

`recommend_treatment` cost is higher than “~25 feature SELECTs”:

- `SqlFeatureProvider._build` (`features.py:442` onward) is a sequence of independent `conn.execute` calls (customer/account, holds, promises, ledger, attempts, voice, inbound, disputes, legal, …) — on the order of **25 SELECTs**.
- `_generate` then calls `policy.veto` per action. Contacting specs (`sms`, `whatsapp`, `voice_bot`, `human_call`, `field_visit`) that reach the channel gate each call `contact_policy.evaluate` (`policy.py:216-229`, `:463-475`) — another **~5 queries per channel**, up to five times.
- Plus `last_rung_used`, `planned_actions`, `_rules`, and `decisions.record` INSERT (`engine.py:377`).

Worst case **~50–60 round-trips per undecided account**, not 25. Scoring is in-process (no LLM on this path unless `TREATMENT_LLM_RERANK` is on; default off).

The whole batch is still one `engine.begin()`, holding those 50 account locks. `process_one` returns `True` when any account was decided (`:109`), so `bot_worker` **does not sleep** until the day’s remaining undecided slice reports empty (`bot_worker.py:220-225`). Follow-through returning True (`:132-133`) is **intentional** starvation of the sweep when unattributed outcomes remain (`:134-137`).

**Cost:** peak ~50 × ~60 sequential queries in one transaction per tick while the book is still being logged. After the day’s cursor catches up, cost collapses to claim + `_decided_today` probes. Today's demo book is much smaller than `BATCH`; the code path is not.

### N3 — Medium — follow-through attribution: up to 25 rows × several probes, every tick, in one transaction

`agent_core/treatment/followthrough.py:95-156,487-505`, `BATCH = 25`.

Runs unless `TREATMENT_MODE=off` (`:496`). Default in code is **shadow** (`config.py:64`); this checkout is **live**. Attribution is intentional in shadow — the docstring says so (`:490-494`).

Each `_outcome_for` may hit ledger (`:263-266`, `type = 'payment'`), payment intents, later decisions, call outcomes, … then `record_outcome` or stamp `outcome_checked_at`.

**Cost:** O(backlog) probes per tick, one transaction. Scales with unattributed decisions, not with accounts.

`_case_still_open` (`followthrough.py:401-421`) only knows `bounce` / `broken_ptp` / `pre_due`. Sweep decisions use `trigger_kind = 'dpd_tick'` (`sweep.py:72`). Those fall through to `return False` **with no query** — they never re-enter the ladder. That is a behaviour cut, not extra SQL.

### N4 — High — Customer 360 runs a full `recommend_treatment` whose INSERT is rolled back

`main.py` insights route → `db.get_customer_insights` (`db.py:1220-1243`) → `_treatment_snapshot` (`:1246-1275`) → `recommend_treatment(..., trigger=Trigger(kind="manual"), conn=conn)`.

Two facts, both cited:

1. **The docstring wants a write.** `:1259-1262` says persisting a decision row from a card open is deliberate (shadow corpus from questions people actually ask). `decisions.record` INSERTs (`decisions.py:92-128`) on the caller’s connection (`_writer` yields `conn` when one is lent, `:42-46`).
2. **The write does not survive.** `get_customer_insights` uses `engine.connect()` (`:1228`) and never calls `conn.commit()`. SQLAlchemy 2.0.51 rolls back an autobegun transaction when the `connect()` context exits. The JSON can still carry a `decisionId` for a row that never committed.

This is **not** “a live plan that enact will send because someone opened 360.” Sweep and bounce ingest use `engine.begin()`; those writes persist. Insights pays the engine cost and then throws the row away.

Fan-out on the same request:

```
get_customer                 ~8 queries, full aggregate, own connect()
_customer_activity_preview   1  (second connection — see S1)
policy.snapshot              several
authority_policy.snapshot    several
recommend_treatment          ~50–60 round-trips + INSERT that is rolled back
```

**Affected workflow:** operator Customer 360 insights card. Inbox → Customer → back → Customer re-runs the engine for an answer that usually did not change, and the corpus the docstring wanted is empty.

Frontend: `Habibi/src/api/customers.ts:36-46` `GET /customers/${id}/insights` (no poll interval — cost is per navigation, not per second).

**Settle:** open 360 on a customer, then `SELECT id FROM treatment_decisions WHERE trigger_kind = 'manual' ORDER BY created_at DESC LIMIT 5`. If the table is empty of `manual` rows, the rollback claim is proven. If rows appear, some other commit path exists and this finding is wrong.

### N5 — Medium — `campaigns.add_targets`: one INSERT per customer in a held API transaction

`campaigns.py:153-190`. Python loop, one `INSERT ... SELECT` with a correlated subquery against `accounts` per id. Bound: selector cap default **500** (`:322`), `SELECTOR_MAX = 5000` (`:215`), or a client-supplied `customerIds` list. Held by `main.py:4898` / `:4964` `engine.begin()` against the API's 10-connection pool.

`INSERT ... SELECT ... FROM unnest(:ids)` would be one statement. Dataset-bounded today; the path is not.

### N6 — Low/Medium — KB index: sequential INSERT per chunk after a connection held across Azure embed

`kb_ingest.process_one` (`:469-475`) correctly commits the claim **before** embedding. `_prepare_embedded_chunks` is then called with `engine.connect()` still open (`:480-481`) and `azure_openai.embed_texts` runs at `:322` — **pool slot held across Azure**, not a row lock. `_atomic_replace_chunks` (`:373-387`) then INSERTs chunks in a Python loop inside one transaction.

Single-threaded `worker` today. Matters if that process is scaled or documents are large.

### N7 — Medium — voice/WhatsApp tools hydrate the whole customer aggregate for one field

`bot_tools.py:195-210`:

```python
def _tool_get_payment_history(ctx, args):
    customer = db.get_customer(ctx.customer_id)     # include_detail=True, 8 queries
    ledger = list(customer.get("ledger") or [])[:limit]
```

Same for EMI (`:204-210`). `get_customer` (`db.py:1174-1179`) has no partial-fetch mode. `_customer_contract(..., include_detail=True)` always loads consent, **unbounded ledger** (`:1112-1124` — no `LIMIT`), full EMI schedule, 25 interactions **plus every transcript turn for those 25** (`_interaction_contracts`, batched with `ANY(:ids)` — the N+1 there was already fixed, `:1320`), promises, disputes, documents, notes.

Voice wrappers put this in `asyncio.to_thread` (`voice/tools.py:1123` and siblings) — it does not stall Pipecat's loop, but it **does** occupy a voice-pool slot and sits on the Mouth's TTFB path after "let me check that."

`list_customers` already uses `include_detail=False` (`db.py:1163-1171`) and says so in the docstring. The tool path did not get that switch.

---

## Class 4 — Unbounded queries and missing pagination

### S1 — Confirmed access-path — Customer 360 activity preview cannot use `(entity_type, entity_id)`

`db.py:1182-1202` (`_customer_activity_preview`)

```sql
WHERE ae.tenant_id = :tenant_id
  AND ( (ae.entity_type = 'customer' AND ae.entity_id = :customer_id)
     OR ae.entity_id IN (SELECT id FROM interactions WHERE customer_id = :customer_id)
     OR ae.entity_id IN (SELECT id FROM promises ...)
     OR ... 4 more OR'd IN subqueries ... )
ORDER BY ae.at DESC LIMIT 8
```

`idx_activity_events_entity` is `(entity_type, entity_id)` (`sql/12_crosscutting.sql:17`). **Five of the six OR branches supply no `entity_type`**, so the composite cannot serve them. There is also `idx_activity_events_tenant_id` (`:18`) — a tenant-leading index still has to evaluate the OR filter over that tenant's log.

The query does not resolve this customer's event ids and probe by PK. It scans (at least) the tenant's `activity_events`, hashes six subplans, then `LIMIT 8`.

**Cost:** O(tenant event log) **per Customer 360 open**, on a table written by almost every notable action. `LIMIT 8` does not make the filter indexable.

Live `EXPLAIN` was not captured this pass. The structural argument does not need it: a btree on `(entity_type, entity_id)` cannot match `entity_id IN (...)` with `entity_type` unconstrained.

### S2 — `list_violations()` unbounded, then refetches entire transcripts for a 3-turn snippet

`db.py:7025` / `_transcripts_by_interaction` `:6899` / `_build_violation_evidence` `:6921-6964` (docstring: "Offending turn + neighbours"). Route `main.py` list-violations handler takes **no query params**.

No `LIMIT`. Then every turn and the full `text` column of every implicated call is pulled; the builder keeps the closest turn ±1. The fetch is batched (`ANY(:ids)`), not N+1 — the waste is **width × history**, not round-trips.

**Cost:** O(violations in tenant history × average transcript length). Neither factor is bounded.

### S3 — `list_conversations()` unbounded + full history per returned thread

Covered under N0. Listed here because the list function itself has **no `limit`/`offset`** (`db.py:9059`), unlike 13+ siblings. Initial load is "every conversation in the tenant, each with complete history, plus per-thread context."

`conversations` (`sql/04_interactions.sql:172-183`) has **no `tenant_id`** and **no index on `updated_at`**. First Inbox poll (no `updated_after`) is `ORDER BY COALESCE(cv.updated_at, cv.created_at)` — that expression cannot use a btree on either column. Messages are indexed only on `conversation_id`. Combined with N0 this is `O(conversations × (messages + ~8–10 round-trips))`.

### S4 — `list_scorecards()` unbounded

`db.py:8050-8072`. 7-way join plus per-row `EXISTS` on `interaction_handoffs` (`_SCORECARD_LIST_SQL`, `:7979-8001`). Join shape is fine; missing bound is the finding. `_scorecard_rows_to_screen` then loads rubric trees and QA entries for the whole result.

### S5 — Lead search: 5-column leading-wildcard `ILIKE`, unindexable by construction

`db.py:2807-2832` (`_LEAD_FILTER_SQL`)

```sql
l.id ILIKE '%' || :q || '%'
OR c.name ILIKE '%' || :q || '%'
OR COALESCE(l.account_id, '') ILIKE '%' || :q || '%'
OR COALESCE(p.name, '') ILIKE '%' || :q || '%'
OR COALESCE(l.transcript_snippet, '') ILIKE '%' || :q || '%'
```

Pagination exists (`list_leads` uses `clamp_list_limit`, `:2862`). The page is applied **after** the join filter. No `pg_trgm` / GIN index appears in `sql/` or the alembic grep for these columns. A leading `%` cannot use a btree regardless.

**Cost:** O(leads ⋈ customers ⋈ products) per keystroke-filter, then `LIMIT`. Fine at demo size; the access path has no index future.

### S6 — `get_customer` ledger query has no `LIMIT`; siblings in the same function do

`db.py:1112-1124` vs interactions `clamp_list_limit(..., DEFAULT_CALLS_LIMIT)` at `:1289`. Ledger is append-only and grows with account age × payment frequency. Tools then slice in Python (N7).

### Pattern behind S2–S4

`clamp_list_limit()` is the convention (`db.py:172-204`). `list_violations`, `list_scorecards`, and `list_conversations` are the `list_*` functions on **growing operational tables** with no `limit` parameter at all. Roster/catalog lists (`list_staff`, `list_teams`, `list_canned_responses`, …) are omitted from this finding — they are bounded by configuration, not by calendar time.

`list_handoff_queue` **does** `LIMIT 50` (`db.py:4032`) and filters to open handoffs on active interactions — correctly not flagged.

### S7 — `list_routing_rules` LATERAL-aggregates the entire execution log per rule

`_ROUTING_RULE_SELECT` (`db.py:11473-11500`). `LEFT JOIN LATERAL (SELECT count(*) FILTER … FROM routing_rule_executions e WHERE e.rule_id = r.id)`. Table is indexed on `interaction_id` only (`sql/09_bot_config.sql:355`) — **no `rule_id` index**. `list_routing_rules` has no `LIMIT`. Each LATERAL is a seq scan of an append-only eval log.

**Workflow:** Routing builder screen.

### S8 — `bot_analytics`: no tenant filter; correlated transcript `count(*)` three times

`_bot_analytics_window` (`db.py:7188-7197`) is only `i.started_at >= (now() - make_interval(days => :days))`. Abandoned uses regex on `disposition`. Daily CTE, intent CTE, and turn histogram each pay `EXISTS` on `interaction_handoffs` and `count(*)` on `interaction_transcript` per interaction in the window.

**Workflow:** Conversation & Bot Analytics (default 30d).

### S9 — `work_items` view: UNION ALL + LATERAL on unindexed `followups.lead_id`, then `ORDER BY CASE`

View `sql/95_views.sql:1-106`; `list_work_items` `db.py:12568-12626`. Lead arm is `LEFT JOIN LATERAL (SELECT MIN(due_at) FROM followups WHERE lead_id = l.id …)`. `followups` has indexes on `customer_id` and `promise_id` only (`sql/05_collections.sql:262-263`) — **no `lead_id` index** even though `lead_id` is an FK. Views cannot carry indexes. `LIMIT` applies after the union + CASE sort.

**Workflow:** My Workspace / assigned queue.

### S10 — Billing KPI wraps `started_at` in a timezone cast

`db.py:16827-16856`: `(started_at AT TIME ZONE 'UTC')::date >= :start`. That expression cannot use `idx_interactions_started_at`. Same class as the promise date-cast in F11.

### S11 — Inbox suggestions: `OR` of two `ANY()` arrays

`_conversation_suggestions` (`db.py:8717`). `WHERE conversation_id = ANY(:cids) OR interaction_id = ANY(:iids)`. Index exists only on `interaction_id` (`sql/04_interactions.sql`). Fired on every Inbox poll.

### S12 — Repeated primary-account LATERAL: `ORDER BY CASE WHEN id LIKE 'AC-%'`

Same LATERAL at customer list (`db.py:1019-1028`), consent, inbox, work items, dashboard, `bot_runtime.py:81-85`. Prefix `LIKE 'AC-%'` is sargable on the PK; the **CASE sort** is not. `SELECT *` over-fetches.

---

## Class 5 — Indexing

Index evidence in this pass is **schema files + query predicates**, not `pg_stat`. `idx_scan = 0` is not used. Drop recommendations are only for indexes that are a **strict column-prefix** of another index on the same table (provable from `CREATE INDEX` text).

### I1 — Highest-value gap — `customers` phone lookup has no expression index; `accounts` already does

Hot identity path:

- `db.py:10364-10420` (`_find_customer_by_phone`) — inbound PSTN and new WhatsApp (`find_customer_by_phone`, `:10449`)
- `voice/persist.py:988-1005` (`lookup_customer_for_verify`) — in-call last-4
- `main.py:4058-4061` demo outbound — same `regexp_replace` on `phone_primary`

```sql
regexp_replace(COALESCE(c.phone_primary, ''), '[^0-9]', '', 'g') = :phone
OR regexp_replace(COALESCE(c.phone_alt, ''), '[^0-9]', '', 'g') = :phone
```

`sql/02_customer_account.sql:64-66` lists `customers_pkey`, `idx_customers_tenant_id`, `idx_customers_assigned_user_id`, `idx_customers_risk`. No expression index on the digit-stripped phones.

A btree cannot serve a function-wrapped equality without a matching expression index. Seq scan is the only plan at any size until one exists.

**The identical problem was already fixed on `accounts`:** `alembic/versions/20260725_0040_production_hardening_invariants.py:118-124` added `idx_accounts_digit_tail4` and `idx_accounts_id_tail4`. Those exist in Alembic; they are **not** in `sql/02_customer_account.sql`. `customers.phone_primary` is the hotter path and never got the mirror.

**Affected workflow:** every inbound call and every new WhatsApp identity resolution.

### I2 — `followups` escalation sweep has no supporting index

`db.py:6096-6116` — `FOR UPDATE OF f SKIP LOCKED` filtering `status IN ('open','in_progress') AND priority <> 'high' AND due_at <= now()`, `ORDER BY due_at`, join `leads`.

`sql/05_collections.sql:262-263`: `followups_pkey`, `idx_followups_customer_id`, `idx_followups_promise_id`. **No index touches `status` or `due_at`.**

Worker cadence: `worker.py:111-128`, every 600s — not the 1.5s bot loop. Still a claim query with no supporting index, unlike three siblings:

| Index | Definition |
|---|---|
| `idx_call_cadence_due` | `call_cadence_state (next_attempt_at)` (alembic 0095) |
| `idx_campaign_targets_claim` | `(run_id, next_attempt_at) WHERE state = 'pending'` (`sql/22_campaigns.sql:75-76`) |
| `idx_treatment_decisions_due` | `(scheduled_at) WHERE enacted IS FALSE AND chosen_action IS NOT NULL AND chosen_action <> 'wait'` (alembic 0069) |

### I3 — `ledger_entries` access shapes

Current indexes (`sql/02_customer_account.sql:125-126`): `(account_id)`, `(posted_at)`.

Hot predicates that want `(account_id, type, posted_at)`:

- `authority/features.py:155-161` — `account_id = :aid AND type = 'fee' AND posted_at >= :since`
- `authority/features.py:172-177` — `type = 'waiver'`
- `treatment/followthrough.py:263-266` — `account_id AND type = 'payment' AND posted_at > :since`

**Confirmed gap, scaling-based cost.** Cheap at hundreds of rows; this table is append-only and will not stay small. These run per Authority snapshot and per follow-through check.

**Also:** `authority/enact.py:99-108` — `WHERE description LIKE :pat` with `pat = f"%{dispute_id}%"`. Leading wildcard, unindexable by btree. The root cause is storing a foreign reference inside free text; the missing index is a symptom. Idempotency of goodwill waivers depends on this scan.

### I4 — Unindexed FK columns with confirmed query sites

Postgres does not auto-index the referencing side. From `sql/21_outbound.sql`, `call_attempts.bot_id` and `call_attempts.campaign_run_id` are columns without their own indexes. Query sites:

| Column | Query |
|---|---|
| `call_attempts.bot_id` | `agent_core/canary.py:235-238` — `WHERE bot_id = :b AND state = 'abandoned' AND updated_at > now() - interval '15 minutes'` (canary sweep) |
| `call_attempts.campaign_run_id` | `campaigns.py:424-427` — in-flight count **per campaign tick**, `state IN ('reserved','dialing',...)` |

The in-flight **fleet** gate uses partial `idx_call_attempts_in_flight (tenant_id, reserved_at) WHERE state IN (...)` (`sql/21_outbound.sql:83-85`) — that one is correct. It does not serve `WHERE campaign_run_id = :run AND state IN (...)`.

Do not index every FK. The rest were not grepped to exhaustion this pass.

### I5 — Prefix-redundant indexes (definition-provable; the only drop list)

Each is a strict column-prefix of a longer index on the same table, so it adds write cost and nothing a planner cannot get from the longer one:

| Redundant | Covered by |
|---|---|
| `idx_leads_customer_id` (`sql/06_sales.sql:28`) | `idx_leads_customer_product_stage (customer_id, product_id, stage)` (`:38-39`) |
| `idx_webhook_deliveries_status` (`sql/10_admin.sql:209`) | `idx_webhook_deliveries_claim (status, next_retry_at)` (`:210-211`) |
| `idx_kb_chunks_document_id` (`sql/09_bot_config.sql:51`) | `uq_kb_chunks_document_id_chunk_index (document_id, chunk_index)` (`:55-56`) |
| `idx_interaction_transcript_interaction_id` (`sql/04_interactions.sql:105`) | `UNIQUE (interaction_id, turn_index)` (`:103`) |

Drop only after a `pg_stat_user_indexes` check against representative traffic. This list is **not** "every index with idx_scan = 0."

### I6 — SKIP LOCKED coverage (claim queries vs indexes)

| Claim | Index match |
|---|---|
| `bot_turn_jobs` | `ix_bot_turn_jobs_status_run_after (status, run_after, created_at)` — **match** |
| `whatsapp_outbound_jobs` | `ix_whatsapp_outbound_jobs_status_run_after` — **match** |
| `webhook_deliveries` | `idx_webhook_deliveries_claim (status, next_retry_at)` — **match** |
| `work_runtime_jobs` | `idx_work_runtime_jobs_tenant_status` — **match** (`adapter_pg.py:170-174`) |
| `treatment_decisions` due | `idx_treatment_decisions_due` partial — **match** |
| `campaign_targets` | `idx_campaign_targets_claim` partial — **match** |
| `call_cadence_state` | `idx_call_cadence_due (next_attempt_at)` — **usable**; claim also filters `state = 'open'` and orders paused runs last (`cadence.py:328-333`), so not a perfect partial match |
| `followups` escalation | **no status/due_at index** (I2) |
| `campaign_runs` `_claim_run` | `WHERE status = 'running' ORDER BY started_at` (`campaigns.py:440-443`); index is `(tenant_id, status)` — **suspected mismatch**, tiny table, check row count before acting |
| `mcp_tasks` | `idx_mcp_tasks_tenant_status` — **match** |
| `payment_events` bounce voice | filter on `kind`, `status`, `next_voice_at` — **suspected**, not verified against live indexes this pass |
| `promise_reminders` | **`idx_promise_reminders_due_drain (status, scheduled_at) WHERE kind IN ('confirm','due') AND status IN ('queued','scheduled')`** — exists in `sql/05_collections.sql:55-57`. A previous draft of this file marked this suspected. |
| `kb_index_jobs` claim | `WHERE status = 'queued' ORDER BY created_at FOR UPDATE SKIP LOCKED` (`kb_ingest.py:156-159`). Table `sql/09_bot_config.sql:63-76` has **no secondary index**. Tiny queue today; claim has no supporting index. |
| `call_qa_whispers` live-QA claim | indexed on `interaction_id` in the snapshot; claim predicate is status/due — **suspected mismatch** |

### I7 — Tenant-scoping test does not require `tenant_id` to *lead*

`tests/test_tenant_scoping.py:113-126`. Docstring: "Every scoped read and every future RLS policy filters on this first." Assertion:

```sql
SELECT count(*) FROM pg_indexes WHERE ... indexdef LIKE '%tenant_id%'
```

This passes if `tenant_id` appears **anywhere** in the index, including trailing, where it provides none of the claimed benefit. Spot-checks of `sql/*.sql` found many indexes that do lead with `tenant_id` and some that do not. **Latent test-coverage gap, not a proven production regression.** Anchoring the pattern to `'(tenant_id'` (or `pg_index.indkey`) would close it.

### I8 — `sql/*.sql` is a stale baseline relative to Alembic

Concrete instance: `idx_accounts_digit_tail4` / `idx_accounts_id_tail4` exist in Alembic 0040 and not in `sql/02_customer_account.sql`. TTS catalog search GIN/btree from Alembic 0034 is **missing from `sql/09_bot_config.sql`** — `list_tts_voice_catalog` still uses leading-wildcard `ILIKE` (`db.py:13683-13690`) which cannot use a btree even if the Alembic index is live. Treat Alembic + the live catalog as authoritative.

### I9 — Unindexed `followups.lead_id` (board + work_items LATERAL)

Confirmed FK, no index in `sql/05_collections.sql`. Used by the work_items lead arm (S9). Same table as I2; a `(lead_id, status, due_at)` index would serve both the LATERAL and the escalation claim if status/due_at were included — do not add two overlapping indexes without checking both predicates.

---

## Class 6 — Transaction poisoning

A write recording a real-world outcome shares a transaction with a second DB call wrapped in `try/except` intended to be non-fatal. A DB-level error in that second call aborts the *shared* transaction. Python catches the exception but cannot un-abort the connection — later statements, including COMMIT, fail with "current transaction is aborted," rolling back the record the `try/except` was meant to protect.

**Not reproduced live.** Structural: what happens *if* the wrapped call raises a DB error.

| ID | Site | Consequence |
|---|---|---|
| P1 | `voice/persist.py:696-764` (`complete_voice_call`) | Failure in `capture.rollup_interaction` (`:742-749`) rolls back the `UPDATE interactions` that recorded call end, duration, disposition. Media is already gone; DB can show pre-teardown status. |
| P2 | `voice/persist.py:137-182` (`start_voice_call`) | Failure in `db._activity` (`:171-182`) aborts COMMIT of `INSERT INTO interactions`. Defeats the function's own documented intent (`:122-126`): interaction committed first so CRM tools still work if `voice_sessions` fails. (The `voice_sessions` insert is already a *second* `begin()` — that split is correct. The activity write is still inside the first.) |
| P3 | `bot_runtime.py:445-480` (`_finalize_outbound`) | Failure in `db.record_activity` loses `delivery_status='sent'` for a WhatsApp message that already left. Adjacent code (`:614-627` in prior reading of this file) treats `'sending'` as ambiguous and does not auto-resend — no double-send, but the row stays wrong until a human intervenes. |
| P4 | `payment_events.py:361-396` (`IntegrityError` race recovery) | After `IntegrityError` the connection is aborted. The `except` block runs more SQL on **the same conn** with no savepoint / rollback. Recovery cannot succeed; the webhook returns 500 and F1's outer `begin()` rolls back. |
| P5 | `payments.record_payment` (`payments.py:219-239`) and `_create_promise` (`db.py:5170-5177`) | `try/except Exception` around `cure_for_account` / `fulfill` on the caller's transaction. A DB error in the "non-fatal" call aborts COMMIT of the payment / promise the handler already inserted. Same class as P1; `_promise_by_id` after a poisoned `fulfill` will fail too. |

The repo has been bitten by the *adjacent* nested-`begin()` bug and documented it — `db.py:5100-5107` (orphan promise from a second pooled commit). `kb_retrieve._try_set_local` already uses `conn.begin_nested()` for the savepoint idiom.

**Check:** force a failure in `capture.rollup_interaction` (rename a column it references), then observe whether `interactions.status` and `voice_sessions.status` disagree.

---

## Class 7 — Connection churn

Not hold time — checkout count. Against pools of 3–10.

| ID | Site | Cost |
|---|---|---|
| C1 | `voice/persist.py:103-185` (`start_voice_call`) | `ensure_unknown_caller()` (own tx) + interactions `begin()` + `voice_sessions` `begin()` = **3 sequential checkouts per connect**. Two splits are for durability (documented). `ensure_unknown_caller` is an idempotent upsert. |
| C2 | `bot_runtime.py:954-1004` | `_load_conversation` reopens a connection **once per tool-loop iteration** (up to `BOT_MAX_TOOL_ITERATIONS`) for a takeover race check; `record_tool_call` reopens per tool. Short-lived, but on the WhatsApp turn path competing with the 5-connection bot_worker pool. |
| C3 | `db.backfill_kb_sources_to_minio` (`db.py:15712-15750`) | `limit` defaults to `None`; one transaction across N × (disk read + MinIO PUT). Savepoint per row (`:15750`) prevents one bad insert from aborting the rest — good — but the outer tx and the PUTs still span. Admin path. |
| C4 | WhatsApp `_handle_turn` / bot helpers | Each helper that opens its own `engine.connect()`/`begin()` is a checkout. Against `bot_worker`'s pool of **5**, a turn that fans out identity + conversation + transcript + tools + activity can take **many sequential checkouts**. Not measured this pass; the shape is connection-per-helper rather than one conn for the turn. Voice CRM sink is the same class on the voice pool. |

`get_customer_insights` opening a second connection after `get_customer` already used one (N4) is the same class, smaller. The insights `connect()` is also the rollback that discards the treatment INSERT.

---

## What is already right

This matters as much as the findings: the defects above are **deviations from a standard this codebase already holds**.

- **Cadence and campaigns commit before they dial.** `cadence.py:480-492` and `campaigns.py:608-610`. This pass audited them; they were listed as gaps in an earlier note. They are the pattern treatment enactment should copy.
- **`outbound.place()`** (`outbound.py:533-596`) fleet-gate then dial, documented at `:540-562`. F6/F8 are caller-side.
- **`webhooks_dispatch`** — POST between two short transactions; module docstring states the rule. Claim uses `FOR UPDATE OF d SKIP LOCKED` (`webhooks_dispatch.py:309`).
- **`call_closer.process_one()`** (`call_closer.py:1098-1133`) — claim/read → LLM with **no** transaction → write. Docstring names the exact hazard.
- **`whatsapp_outbound.process_one`** (`:573-581`) — claim commits, then `handle_job`. Graph latency does not hold the SKIP LOCKED row.
- **`payments.record_payment` webhook dispatch is an outbox** — `dispatch()` inserts `webhook_deliveries`; the POST is later.
- **KB ingest claim/embed split** — claim transaction ends before Azure (`kb_ingest.py:471-475`). Remaining issue is the leftover `connect()` around embed (N6), not the claim.
- **`_interaction_contracts` batches transcripts** with `ANY(:ids)` and a comment that this was a conscious N+1 fix (`db.py:1320`).
- **Floor snapshot is batched and bounded by live calls.** `ops_screens.get_floor_snapshot` (`:395-514`) filters `i.status = 'active'`, then `ANY(:ids)` for flags, sentiment, last turns. Polled every 3s (`Habibi/src/api/floor.ts:75-79`) — that interval is acceptable *because* the query is bounded by concurrent calls, not history.
- **Dashboard is not polled.** `useDashboard` (`Habibi/src/api/dashboard.ts:113-118`) has `staleTime: 30_000` and **no** `refetchInterval`. `get_dashboard`'s ~12-query fan-out (`db.py:3195-3354`) is per page view, not per second. Previously suspected; **settled**.
- **`list_customers` is `include_detail=False`** — one indexed read (`db.py:1163-1171`).
- **Voice tool handlers** wrap DB in `asyncio.to_thread` (`voice/tools.py`, many sites). The Mouth path does not hold a connection across Azure STT/TTS.
- **Advisory locks are transaction-scoped** (`pg_advisory_xact_lock` at `db.py:704,5745,14380,14820`).
- **`SET LOCAL` is inside transactions:** `db.py:153-169` on the SQLAlchemy `"begin"` event; `kb_retrieve.py:332` savepoint-guarded; `rls.py:483` with an open transaction.
- **Partial indexes that match their queries:** `idx_call_attempts_in_flight`, `idx_campaign_targets_claim`, `idx_treatment_decisions_due`, `idx_promise_reminders_due_drain`.
- **Nested-begin scar tissue** is documented at `db.py:5100-5107`.

---

## Ranked remediation

Ordered by (severity × how cheap the fix is), with the in-repo precedent.

**Correctness first — wrong at any data volume**

1. **Move the carrier call outside the lock in F1, F6, F7, F10-SMS.** Persist-then-send or claim → commit → send → record. Precedent: `outbound.place`, `cadence.process_one`, `campaigns.process_one`, `webhooks_dispatch`, `call_closer`, `whatsapp_outbound`.
2. **Set `idle_in_transaction_session_timeout` and `lock_timeout`** in `connect_args` beside `statement_timeout`. Does not fix the findings; converts an unbounded stall into a bounded, loud failure.
3. **`asyncio.to_thread` the blocking `async def` routes**, following `twilio_voice_call_status`'s `_apply()` pattern. Put `_authz_guard`'s DB load on a thread too, or keep the 30s cache always warm from a sync path.
4. **Split poisoned transactions (P1/P2/P4/P5)** so the non-fatal call is its own transaction, or `conn.begin_nested()` — the idiom `kb_retrieve._try_set_local` already uses. P4 needs a savepoint *before* the INSERT that can race, or a rollback in the `IntegrityError` handler before the recovery SELECT.
5. **If/when the mandate rail is wired:** insert the presentation row and commit **before** `present()`, or accept that a crash after presentment is an ops incident with a row to reconcile. Do not keep FOR UPDATE across the rail call.
6. **`settle_promises` (F11):** `FOR UPDATE OF p SKIP LOCKED` plus a batch cap; hoist `recommend_treatment` out of the lock, matching cadence.

**Then load — self-inflicted and cheap**

7. **Stop running Reachability + four context queries per Inbox thread per poll (N0).** Batch promises/disputes/interactions/EMI with `WHERE customer_id = ANY(:ids)`, and compute `contactableNow` from columns already on the conversation join (or a single batched evaluate). Delta-fetch messages after the watermark. Add `clamp_list_limit()` and an index that can serve `ORDER BY updated_at DESC` (S3).
8. **Gate the worker poll loop (N1).** One "is there work" check, `LISTEN/NOTIFY`, or back off the 1.5s interval after successive empty ticks.
9. **Make `_treatment_snapshot` actually match its docstring (N4).** Either `conn.commit()` after a deliberate write, or stop calling `recommend_treatment` on card-open and read the last decision. Today it pays ~50–60 queries and persists nothing.
10. **Hoist `recommend_treatment` out of the sweep's single transaction (N2),** or shrink `BATCH`. Commit per account, like cadence already commits per dial.
11. **Batch `campaigns.add_targets`** into one `INSERT ... SELECT ... FROM unnest(:ids)`.
12. **Release the `connect()` around KB embed (N6)**; `executemany` / `unnest` the chunk inserts.

**Then indexes — each has a worked precedent**

13. **Expression indexes on `customers.phone_primary` / `phone_alt`**, mirroring Alembic 0040's `accounts` tail indexes. Also last-4 if verify-by-OTP stays on `RIGHT(regexp_replace(...), 4)`.
14. **Partial index on `followups (due_at) WHERE status IN ('open','in_progress')`**, mirroring `idx_call_cadence_due` / `idx_campaign_targets_claim`. Add `followups (lead_id)` (or include it in that partial) for S9.
15. **Composite on `ledger_entries (account_id, type, posted_at)`.** Put `dispute_id` on goodwill rows instead of `LIKE '%DSP-...'`.
16. **Index `call_attempts (bot_id, updated_at)` and `(campaign_run_id)`** (or a partial in-flight index on `campaign_run_id`).
17. **`routing_rule_executions (rule_id)`** for S7. **`kb_index_jobs (status, created_at)`** for the claim in I6.
18. **Drop the four prefix-covered indexes in I5** after a live `pg_stat_user_indexes` check.

**Then bounds**

19. **Apply `clamp_list_limit()` to `list_violations`, `list_scorecards`, `list_conversations`, `list_routing_rules`.**
20. **Fetch only the 3 turns `_build_violation_evidence` keeps (S2).**
21. **Restructure `_customer_activity_preview` (S1)** to resolve candidate ids first and probe `(entity_type, entity_id)`, or UNION 6 indexable legs each with `entity_type`.
22. **Give `get_customer` a partial-fetch mode** so voice tools stop hydrating the full aggregate (N7), and `LIMIT` the ledger query at `db.py:1112`.
23. **Rewrite billing date predicates (S10)** as `started_at >= :start::timestamptz AND started_at < :end + 1 day`.
24. **Replace the work_items CASE sort (S9)** with a sargable key, or materialize overdue first.

**Structural**

25. **Sync `sql/*.sql` forward from Alembic, or stop treating it as the schema.**
26. **Anchor `test_tenant_scoping.py` to a leading `tenant_id`.**
27. **Lint "external call with a transaction open N frames up."** The other fixes do not prevent the class from recurring. Cadence/campaigns prove the split is already the house style.

---

## What we could not verify

- **No live catalog this pass.** Docker CLI failed (`exit_code: 1` after hanging). No `EXPLAIN`, no `n_live_tup`, no `idx_scan`, no `pg_stat_activity` sample. Scaling claims are structural. Do not read "seq scan" as "slow today."
- **Nothing was caught red-handed idle-in-transaction.** Every transaction hazard is reasoned from code.
- **Poisoning cascade (P1–P5) was not reproduced.** Injection check specified above. P4 is the most mechanical: raise a unique-violation on ingest and watch whether the except-block SELECT succeeds.
- **Unindexed FKs beyond I4** were not exhaustively joined to query sites. Do not add 100 indexes from a catalog self-join without a `WHERE`/`JOIN` hit.
- **`main.py`'s ~295 plain-`def` routes were not individually audited.** Threadpool placement is a structural argument, not a review of each handler.
- **Open thread:** not every caller of `outbound.place(` was traced. F6 and F8 are the two that enclose it. Cadence and campaigns were traced and are clean. `grep -n "outbound.place(" --include=*.py backend` settles the rest.
- **`followups_db.py`, `sandbox_runtime.py`, `tts_catalog_sync.py`, `agent_core/eval/*`, `agent_core/reco/decisions.py`** were not fully walked. Known SKIP LOCKED / `FOR UPDATE` sites outside this document should not be read as clean.
- **Feature-query count in `_build` is "on the order of 25,"** from counting `conn.execute` sites, not from a tracer. The ~50–60 round-trip figure for `recommend_treatment` adds veto/`evaluate` theoretically; it was not traced.
- **Idle-query arithmetic is ticks × branches, not `pg_stat`.** Confirm with `pg_stat_statements` on a quiet worker if that extension is available.
- **The Mouth-path "no connection across STT/TTS" result is durable only as written today.** A newly added `db.py` helper that opens its own transaction, called from inside a persist transaction, would reintroduce the hazard silently.
- **WhatsApp / voice checkout-per-turn (C4) was not counted on a live turn.**
- **N4 rollback** was not proven with a SELECT against `treatment_decisions`; it follows from SQLAlchemy 2.0.51 `connect()` semantics. The settle query is in the N4 section.

---

## Corrections to earlier notes in this folder

- `04-backend-architecture.md` describes SKIP LOCKED as living on "the three formal job tables." It is present across bot jobs, WhatsApp outbound, webhooks, work-runtime, treatment, followups, bounce voice, promise reminders, cadence, campaigns, and MCP tasks.
- Cadence and campaigns were previously listed as unaudited transaction shapes. They **commit before `outbound.place`**. Treatment enactment is the one that did not copy them.
- Dashboard poll interval was previously "suspected." It is **not polled**.
- `sql/*.sql` is not the authoritative current schema for indexes added in Alembic after the snapshot (I1/I8). `idx_promise_reminders_due_drain` **does** exist in `sql/05_collections.sql`; an earlier draft of this file marked it suspected.
- An earlier coarse pass counting `async def` routes as "26 of 314" does not match this file's decorator count (**314**) plus the mixed async set above. Use the table in EL-1, not a single headline fraction.
- SQLAlchemy 2 `engine.connect()` **does not commit on exit.** An earlier draft of this file, and the first N4 write-up, claimed insights persists a `treatment_decisions` row. It does not, unless some other `commit()` path exists (settle query in N4).
- `TREATMENT_MODE=live` on this checkout does **not** mean opening Customer 360 will enqueue a live SMS. Sweep and bounce ingest use `begin()`; insights uses `connect()`.
