# 15 — Concurrency and resource lifecycle

**Scope:** `backend/` (FastAPI, workers, the Mouth runtime) and `Habibi/src` (authoring surface + operator console)
**Date:** 2026-09-02
**Method:** five parallel read-only analysts — Python async, frontend async, worker/queue, resource lifecycle, race conditions — then a verification pass in which every claim that reached this document was re-derived from the source, and several were corrected or rejected.

Vocabulary is `CONTEXT.md`: Mouth, Agent Card, Skill Pack, Locked Engine, Deployment, Tool Grant, Offer, Gate, Flow, Handoff, Reachability, Mission, Cadence, Outcome.

---

## Verdict

**The concurrency defects are not spread evenly. They cluster in exactly two places: code that runs on the API's single event loop, and code that performs a real-world side effect — a message to a borrower, a rupee waived, a published Deployment — without the guard the neighbouring code already establishes.**

Everything else is in good shape, and unusually so. Four job queues implement claim / lease / reclaim / dead-letter correctly. One SQLAlchemy Engine, no ORM sessions, every `connect()` inside a `with`. Per-session registries with real `release_*` functions. Generation counters and `AbortController` teardown across most of the frontend. This is a codebase that knows the patterns; the findings below are where specific call sites did not apply them.

Two measured facts set the severity of everything that follows.

**Fact 1 — the API is one process with one event loop.** `docker-compose.yml:103-113` runs `uvicorn main:app --workers 1`, and the comment at `:94` says the connection budget depends on it. So a blocking call inside an `async def` route does not slow one request; it stops the process — every other route, the Twilio TwiML endpoints, and the voice runner's calls back into the API.

**Fact 2 — the Mouth runs a turn's tool handlers concurrently, by default.** Measured inside `collections_voice`:

```
pipecat 1.6.0
273         run_in_parallel: bool = True,
1262        if self._run_in_parallel:
1263            await self._run_parallel_function_calls(runner_items)
```

`run_in_parallel` appears **nowhere in `backend/`**, so the default stands. Every tool call in one model turn is dispatched as a separate asyncio task, and `FlowManager._set_node` holds no transition lock. This converts a class of finding from "the model probably won't do that" into a property of the runtime. It is the single most consequential fact in this audit.

### If only five things are fixed

1. Get the synchronous DB round-trip out of the global authz dependency (**F1**).
2. Get Twilio REST calls off the event loop and out of open transactions (**F2**).
3. Give the `evaluate_authority` → `apply_goodwill` handshake something other than a shared mutable slot (**F3**).
4. Make the two borrower-contact queues idempotent across a crash (**F5**, **F6**).
5. Bump the generation counter on every Live-call teardown path, not just restart (**F7**).

---

## P0 — Critical

### F1. The global authz dependency does a synchronous DB checkout on the event loop, for every route

**Where:** `backend/main.py:507`, `:585`, `backend/authz.py:679` · **Verified**

```python
async def _authz_guard(conn: HTTPConnection) -> None:      # main.py:507
...
    dependencies=[Depends(_authz_guard)],                   # main.py:585
```

```python
def _load_grants(user_id: str) -> frozenset[str]:           # authz.py:673
    with db.engine.connect() as conn:                       # authz.py:679
```

**Mechanism.** `_authz_guard` is `async def` and registered app-wide, so it runs on the loop for all 314 routes. On a permission-cache miss (`_PERMS_TTL_S`, 30s) it calls `engine.connect()` inline. Measured live: the API pool is `5 + 5 = 10` (`docker-compose.yml:87-88`; the `db.py:115-119` default of 5+10 is overridden), and **`pool_timeout` is left at SQLAlchemy's default of 30.0s** — no `pool_timeout` is passed to `create_engine` at `db.py:138`.

**Failure scenario.** Most routes are sync `def` handlers running in anyio's threadpool, each holding a pooled connection. A burst occupies all 10. The next request's cache entry has just expired, so `engine.connect()` is called *from the loop*, finds the pool empty, and blocks **the entire event loop** for up to 30 seconds. Nothing is accepted, `/health` does not answer, and the liveness probe fails the container — while Postgres is perfectly healthy. `statement_timeout` is 15s on the API role (`db.py:123`) and bounds the query, not the pool wait.

**Blast radius:** deadlock / production-only failure.

The same shape exists in `ApiKeyMiddleware.dispatch` (`main.py:297`) → `actor_context._user_exists`.

### F2. The bounce webhook makes a carrier call on the event loop, inside an open transaction, then asks the pool for a second connection

**Where:** `backend/main.py:858` → `backend/payment_events.py:664`, `:882` · **Verified**

```python
@app.post("/webhooks/collections/payment-events")
async def payment_events_webhook(request: Request):        # main.py:858
    ...
    with db.engine.begin() as conn:
        return pe.ingest(conn, body)
```

**Mechanism.** Three compounding problems in one handler. It is `async def`, so `pe.ingest` runs on the loop. `ingest` → `_first_touch` reaches a synchronous Twilio REST send (`twilio_sms.py:79`, `TwilioHttpClient(timeout=10)`). And when digital channels are blocked, `_try_voice_now` (`payment_events.py:758`) calls `outbound.place(dbmod.engine, …)` at `:882`, which opens its **own** `engine.begin()` while the caller's transaction still holds a connection — as does `twilio_sms._record_sent` (`twilio_sms.py:113`).

**Failure scenario.** CBS posts a batch of NACH bounces. Ten concurrent handlers each hold one of ten pooled connections and each then asks for a second. The pool is exhausted, the wait happens on the loop, and the process stops answering for 30s before raising. `_record_sent` swallows its exception, so the SMS goes out with no receipt row, and `/twilio/sms/status` (`main.py:3714`) later 204s the delivery callback as an unknown SID — the delivery evidence for a regulated message is gone.

**Blast radius:** deadlock, then stale state.

### F3. The Locked Engine's goodwill verdict is passed between two tools through one mutable slot

**Where:** `backend/voice/tools.py:1462`, `:1517` · **Verified** (given Fact 2)

```python
state.authority_decision_id = payload.get("decisionId")     # tools.py:1462
cap = payload.get("approvedAmount") or payload.get("capAmount")
```
```python
decision_id = str(args.get("decision_id") or state.authority_decision_id or "")   # tools.py:1517
```

**Mechanism.** `evaluate_authority` writes the approved cap into shared session state *after* an `await asyncio.to_thread(...)`; `apply_goodwill` reads it. The prompt teaches the two as a pair, and Fact 2 means a turn emitting both runs them concurrently. Two evaluations in one turn leave whichever finished last in the slot.

**Failure scenario.** The caller asks to waive a late fee and a bounce fee. The model emits `evaluate_authority(late_fee)`, `evaluate_authority(bounce_fee)` and `apply_goodwill` together. Both evaluations run in parallel threads; `apply_goodwill` applies the amount approved for the **other** fee. The Locked Engine disposed correctly and the runtime reassigned its answer.

**Blast radius:** data corruption, on money, on a regulated channel.

This is the sharpest argument in the audit for the Tool Grant work: a grant that is fixed for the life of the card says nothing about two grants executing at the same instant.

### F4. Two parallel handlers can each hand `FlowManager` a next node

**Where:** `backend/voice/tools.py:462-469` · **Verified** (given Fact 2)

```python
if name in _TERMINAL_NODES:
    session.extra["ending"] = True
    session.extra["ending_reason"] = f"flow_node:{name}"
previous = state.current_node
state.current_node = name
session.extra["flow_node"] = name
```

**Mechanism.** `_node()` synchronously mutates `state.current_node` — which selects the KB corpus via `_current_product_keys` — and returns a config the Flow applies later. Two handlers calling `_node()` both reach `_set_node`, which interleaves at `await self._execute_actions(...)` and `await self._update_llm_context(...)` with no transition lock.

**Failure scenario.** One angry utterance produces `flag_dispute` + `escalate_to_human`, both returning `_node("escalate_close")`. Two transitions interleave: `LLMSetToolsFrame` pushed twice, pre-actions run twice, and the `end_conversation` post-action fires while the second transition is still building the context.

**Blast radius:** stale state / production-only failure.

### F5. Treatment enactment sends the SMS inside the claim transaction, with no idempotency

**Where:** `backend/agent_core/treatment/enact.py:908` → `:307` · **Verified**

```python
with engine.begin() as conn:                    # enact.py:908
    claimed = decisions.claim_due(conn, limit=1)
    if not claimed:
        return False
    acted, note = enact_one(conn, claimed[0])
```

`enact_one` → `_send_sms` reaches `twilio_sms.send(...)` at `:307` while that transaction is open. `decisions.claim_due` uses `FOR UPDATE SKIP LOCKED` — **the row lock is the only claim.** No `claimed_at`, no lease, no `attempts`, no backoff, no dead-letter. `decisions.mark_enacted` (`decisions.py:290-304`) wraps its UPDATE in `except Exception: logger.exception(...)`, so a swallowed write failure leaves `enacted=false`.

**Failure scenario.** The worker claims decision TD-x; Twilio returns a SID and the borrower has the dunning SMS; the container is then SIGKILLed, or the statement timeout fires. The transaction rolls back. `enacted` is still false and `scheduled_at` is still in the past, so the next poll 1.5s later re-sends **the same collections SMS**, repeatedly, until the row ages out of the 7-day window.

**Blast radius:** duplicate processing — regulated borrower contact, and a corrupted contact budget.

**The codebase already knows the fix.** `_dial_bot` at `enact.py:317` deliberately reserves its attempt on its own short transaction, and documents why in six lines. The voice path is correct; only the SMS path skipped it.

### F6. PTP reminders re-send on a crash, and a transient failure is permanent

**Where:** `backend/promise_fulfillment.py:1046` → `:1014`, `:1065`, `:1080` · **Verified**

```python
with engine.begin() as conn:                          # :1046
    row = conn.execute(text("""... FOR UPDATE SKIP LOCKED LIMIT 1"""))
    try:
        ok, err = _send_reminder_copy(conn, dict(row))
    except Exception as exc:                          # :1065
        ok, err = False, type(exc).__name__
```

**Mechanism.** `twilio_sms.send` at `:1014` runs with the `promise_reminders` row lock held, and `twilio_sms._record_sent` checks out a second pooled connection while the first is held. There is no attempt counter and no idempotency key on this queue at all.

Two distinct bugs. A crash after the POST and before COMMIT leaves `status='queued'` and the reminder is **re-sent**. And on the other side, both a `contact_policy.admit` refusal *and* a transient Twilio 500 land in the same `status='failed'` write at `:1080` — with no `run_after`, no retry, and no dead-letter reader. A borrower whose reminder happened to hit the daily contact cap simply never receives their PTP confirmation, and neither does one whose send hit a five-second carrier blip.

**Blast radius:** duplicate processing and lost work, in the same handler.

### F7. Ending a Live call mid-connect orphans the peer connection and leaves the microphone open

**Where:** `Habibi/src/components/sandbox/voice/useSandboxLiveCall.ts:174`, `:201`, `:264`, `:511`, `:536`, `:542` · **Verified**

```ts
const end = useCallback(async () => {          // :174
  stopBotAudio();
  if (clientRef.current) {
    await clientRef.current.disconnect();
    clientRef.current = null;
  }
```

**Mechanism.** `start()` guards every await with `gen !== startGenRef.current`, but **`startGenRef` is incremented in exactly one place — `:201`, inside `start()` itself.** `end()` (`:174`), the `!enabled` effect (`:614`) and the unmount teardown (`:623-627`) all null `clientRef.current` without bumping the generation.

Ordering matters: `clientRef.current = c` at `:264`, `c.initDevices()` takes the microphone at `:511`, `c.connect()` lands at `:536`. If `end()` runs in that window it disconnects a client that has not connected yet and nulls the ref. The in-flight `start()` still satisfies `gen === startGenRef.current` at `:542`, so it proceeds to connect `c` and sets `setStatus("live")` at `:548` — while `clientRef.current` is `null`. The now-connected `RTCPeerConnection` and the open microphone are unreachable by any code path.

**Failure scenario.** Sandbox → Live → **Start call** → click **End** while the chip still reads `connecting`. The UI says `ended`, then flips itself back to `live`. The browser's recording indicator stays lit until reload.

**Blast radius:** memory growth plus a hot microphone on a collections console after the operator believes the call ended.

The generation protocol is correct for the restart case and simply unimplemented for every other teardown path.

---

## P1 — High

### F8. `ending_reason` has three writers and two contradictory ownership policies

**Where:** `backend/voice/bot.py:916`, `backend/voice/tools.py:221`, `backend/voice/tools.py:466` · **Verified**

```python
session.extra.setdefault("ending_reason", reason)          # bot.py:916    first wins
session.extra.setdefault("ending_reason", "bot_farewell")  # tools.py:221  first wins
session.extra["ending_reason"] = f"flow_node:{name}"       # tools.py:466  last wins
```

The reversal is deliberate and commented at `tools.py:464-465`. One field, one reader (`on_pipeline_finished` → the Outcome), two rules. Most write tools carry `cancel_on_interruption=False` (`agent_core/tools/schema.py:95`), so a handler still running after a barge-in can reach `:466` and overwrite a reason already claimed.

**Scenario.** The caller goes silent; the idle ladder claims `ending_reason="idle_ladder_close"`. An in-flight `flag_dispute` returns `_node("escalate_close")` and overwrites it. The call is filed as an escalation, and the Cadence — which reads the Outcome — does not redial a borrower who merely went quiet.

**Blast radius:** data corruption, propagating into Cadence.

### F9. The Mouth admits 25 concurrent calls against a 5-connection pool

**Where:** `backend/voice/admission.py:50-53`, `backend/db.py:138` · **Verified by live measurement**

```
cap = 25
pool = 3 + 2
pool_timeout = 30.0
```

The constant's own comment cites the documented budget of "3+2 connections" and then sets 25. Every call does DB work on `asyncio.to_thread` threads (CRM sink, `persist.*`, `voice_session_store`), so past ~6 concurrent calls those threads queue for up to 30s and then raise.

**Scenario.** A Mission fires a Cadence burst and twelve calls connect. Calls 6-12 block in `bind_session_start`, blow the slow-setup window, and Twilio tears the media stream down — the borrower hears silence while every status callback reports success. Teardown then contends for the same five connections and eats the 20s finalize budget, so Outcomes go unrecorded.

**Blast radius:** production-only failure, then stale state.

### F10. Shutdown waits 10s for a teardown that is budgeted 20s, then disposes the engine underneath it

**Where:** `backend/voice/host.py:98` vs `backend/voice/bot.py:170`, `backend/main.py:504` · **Verified**

```python
await asyncio.wait_for(task, timeout=10)   # host.py:98
```
```python
_FINALIZE_BUDGET_SECS = 20.0               # bot.py:170
```

`main.py:487` states the intended ordering in a comment — "Before the DB engine goes away: live calls write CRM rows on teardown" — and the numbers contradict it. The host cancels at 10s, returns, and `main.py:504` disposes the engine while `_finalize_call` may still be inside its 20s budget, running `asyncio.to_thread(self._handle_sync, ...)` against a disposed pool.

**Scenario.** Deploy with two live calls. Both interactions stay `active` with no `ended_at`, no disposition, no transcript export. The Outcome that Cadence and post-call obligations read never exists.

**Blast radius:** data loss on every deploy that catches a live call.

Related, same file: `await runner.cancel()` at `host.py:93` is the one step in this chain with **no** timeout, so a hung STT/TTS websocket close blocks the lifespan `finally` forever and `usage_meter.shutdown()` never flushes.

### F11. An unguarded `process_one` starves everything below it in the worker loop

**Where:** `backend/bot_worker.py:93-146` · **Verified**

`call_closer`, `cadence`, `campaigns` and the clerk drain are each wrapped in `try/except`. `bot_jobs`, `whatsapp_outbound`, `promise_fulfillment`, `payment_events`, `treatment_enact`, `treatment_followthrough`, `treatment_sweep` and `webhooks_dispatch` are not. The order is fixed and the loop restarts from the top every iteration.

**Scenario.** `treatment_sweep.process_one` (`:139`) raises persistently — a missing column after a partial migration. The top-level handler logs and sleeps 1.5s, forever. `webhooks_dispatch.process_one` (`:145`) and the clerk drain (`:158`) sit below it and **never execute again**. Outbound webhook deliveries and clerk jobs stop silently while the log shows a healthy worker spinning.

**Blast radius:** stale state / production-only failure.

### F12. `'working'` is not a claim

**Where:** `backend/work_runtime/adapter_pg.py:164-186` · **Verified**

```sql
SELECT id FROM work_runtime_jobs
 WHERE tenant_id = :t AND status IN ('submitted','working')
 ORDER BY created_at
 FOR UPDATE SKIP LOCKED
 LIMIT 1
```

`'working'` is re-selectable with no `locked_at`, no lease cutoff, no attempt counter and no dead-letter. The instant the claim transaction commits, the row is eligible again. Mandate representment, EMI date changes and self-service plans re-run without bound if `finish` fails.

**Blast radius:** duplicate processing on financial instructions.

### F13. `escalate_to_human` sets a guard it never reads

**Where:** `backend/voice/tools.py:2617`, `:2696-2704` · **Likely**

`state.escalated = True` is written and never checked at the top of the handler. Every other write tool got an idempotency key scoped to `provider_call_id` (`tools.py:1297`, `:1381`, `:1571`); this one did not. Two concurrent invocations each open an Inbox conversation, each `record_handoff`, and each call `twilio_ops.warm_transfer_to_supervisor(call_sid)`. Two humans paged for one borrower. *(The double warm-transfer arm depends on Twilio redirect idempotency and is unproven.)*

### F14. Two paths present an Offer; neither excludes the other

**Where:** `backend/voice/tools.py:2028`, `:2168-2183` · **Verified** (given Fact 2)

`_prepare_close_probe` reads `offers_presented == 0`, yields for the whole recommendation engine round-trip, then increments at `:2198` — check-then-act across an await. `_recommend_next_offer_handler` increments at `:2028` and checks nothing at all. A turn emitting `recommend_next_offer` + `begin_wrap_up` presents two Offers, records two decision rows, and consumes two campaign quotas for one intended Offer. On a regulated channel this is a double pitch.

### F15. Publish stays clickable while the publish is in flight

**Where:** `Habibi/src/components/prompt-studio/PublishDialog.tsx:108`, `:304` · **Verified**

```tsx
const blocked = errors.length > 0 || compileFailed || compileBusy;   // :108
```

The dialog has **no prop for publish-in-flight at all** — `blocked` covers only the compiler. The parent closes the dialog after `await publishMutation.mutateAsync(...)` (`prompt-studio.lazy.tsx:945-962`), and `publishStudioDraft` carries no idempotency key. A double-click races two publish round-trips and can produce two published rows for one intended Deployment.

### F16. `voice.host.shutdown()` never touches the per-call session tasks

**Where:** `backend/voice/host.py:47-50`, `:84-103` · **Verified**

`shutdown()` cancels `_runner` and `_runner_task` only. The `_SESSION_TASKS` set — each entry running the whole of `bot()` — is never cancelled or awaited. A task still inside transport creation or the Flow build is not reachable by runner cancellation, so `bot()`'s `finally: admission.release(slot_token)` never runs.

### F17. Double-tapping push-to-talk leaks a `MediaStream`

**Where:** `Habibi/src/components/sandbox/ConversationPanel.tsx:149`, `:154` · **Likely**

The re-entrancy guard tests `recording`, which is only set `true` *after* `getUserMedia` resolves. Two presses inside the acquisition window both pass; the second re-sets `wantRecordingRef.current = true`, so the first continuation does not take its release path and assigns `streamRef.current = streamA`, which `streamB` then overwrites. Stream A's tracks are never stopped, including by the unmount cleanup at `:116`, which only stops `streamRef.current`.

### F18. A new Twilio client — and a new `requests.Session` — per REST call

**Where:** `backend/voice/twilio_ops.py:257-265`, `backend/twilio_sms.py:76-80` · **Verified**

`TwilioHttpClient.__init__` creates a `Session()` that nothing ever closes. Full DNS + TCP + TLS handshake per dial, per SMS, per status fetch — and on the dial path that handshake sits inside the caller's setup budget. Contrast `azure_speech.py:53-63` and `voice/llm_pool.py:70-81`, which share a client correctly.

---

## P2 — Medium

| # | Finding | Where | Confidence |
|---|---|---|---|
| F19 | MCP **HTTP** transport runs every tool call on its loop; the **stdio** transport offloads with `to_thread` (`mcp_server.py:72`) | `agent_core/mcp_http/http_app.py:55` | Verified |
| F20 | PSP payment webhook runs the whole ledger transaction on the loop | `main.py:842` | Verified |
| F21 | `/twilio/voice/outbound` offloads the attempt-backed dial with `to_thread` and not the ad-hoc one, eight lines apart | `main.py:3803` | Verified |
| F22 | Closer stamps `closed_at` in one transaction and writes the Outcome in the next; `_abandon` (`:1153`) covers the *handled* failure, so only a hard crash between them is silent — and no sweep finds `closed_at IS NOT NULL` with no Outcome | `call_closer.py:1120` | Partial |
| F23 | `campaign_targets` commits `'dialing'` before the dial with no reclaim; `sweep_stale` reaps the attempt, not the target | `campaigns.py:597-610` | Verified |
| F24 | `KbEnrichProcessor._enrich` locks the check and the set separately, dropping the lock across a 350-1900ms retrieval on the audio path | `kb_enrich.py:658-685` | Verified |
| F25 | IVR `STUCK` is the one termination path that bypasses `_claim_end`, so `ivr_stuck` is discarded for a generic `"bot_ended"` | `ivr.py:188-192` | Verified |
| F26 | `verify_identity` increments the attempt counter, then awaits, then writes three records, then checks the cap | `tools.py:810-826` | Likely |
| F27 | `autoMarkMissed` fires a serial PATCH burst on mount with no `AbortController` and `void …then()` with no `.catch` | `routes/callbacks.tsx:119` | Verified |
| F28 | `skipEnd` replays three scripted turns through a closure frozen at click time, sending the same `turnIndex` each time | `routes/sandbox.lazy.tsx:363` | Verified |
| F29 | Skill Pack import decompresses a zip on the loop; the 2MB cap bounds input, not output | `main.py:2347` | Likely |
| F30 | `ensureRun` has no in-flight guard; overlapping turns create two Sandbox runs | `routes/sandbox.lazy.tsx:229` | Likely |
| F31 | Provider-key binding and mesh state are registered before `_finalize_call` exists, so a Flow build error leaks both permanently | `voice/provider_bind.py:60-69` | Likely |
| F32 | Webhook dispatch classifies config errors (`http_status = 0`) as `server_err` and retries them to the cap | `webhooks_dispatch.py:349-354` | Verified |
| F33 | Column-resize listeners have no unmount cleanup; a drag held across a route change leaves `move` bound to `window` | `VoiceCatalogTable.tsx:168` | Verified |
| F34 | Poll loops have no jitter; single-replica is enforced accidentally by `container_name`, not by design | `bot_worker.py:171` | Likely |

---

## Rejected and corrected

Recorded so they are not re-filed.

- **Rejected — "the outbound fleet gate is off by one."** `outbound.py:569` documents the opposite and the code is right: *"Reserved rows count themselves, so the comparison is `>` not `>=`."* `reserve()` commits on its own short transaction before `place()` is called, so every concurrent dial is already inside the count. `>` yields exactly `max_in_flight` concurrent calls. The count-then-act window is closed by write ordering rather than by locking, deliberately.
- **Corrected — the treatment voice path.** The claim that `_dial_bot` calls `outbound.place` inside the claim transaction is wrong. `enact.py:317-325` reserves on its own transaction and explains why. Only `_send_sms` has the defect (F5).
- **Corrected — API pool size.** `db.py:115-119` defaults to `5 + 10 = 15`, but the API is deployed with `5 + 5 = 10` (`docker-compose.yml:87-88`). The smaller number makes F1 and F2 worse, not better.
- **Corrected — the Live call does not wedge the Start button.** `useSandboxLiveCall.ts:569` resets `startingRef` when the generation matches, which it does in this scenario. The orphaned peer connection (F7) is real; the wedged button is not.
- **Corrected — the Closer is not simply broken.** `_abandon` at `call_closer.py:1153` stamps `provider_error='closer_failed'`, so a handled failure is discoverable. Only a hard crash between the two transactions is silent (F22).
- **Noted — the connection budget comment is stale.** `docker-compose.yml:3-6` sums to ≈25; the real total is 28, because `voice_insurance` (2+1) was added after the comment. Against `max_connections = 100`, measured live, this is not a problem — it is a doc drift worth one line.

---

## What is healthy

This is most of the system, and it is why the findings above are call sites rather than a pattern.

**Four job queues get claim / lease / reclaim / dead-letter genuinely right.**

- **`kb_index_jobs`** (`kb_ingest.py:108-177`) is the best queue in the repo: `SKIP LOCKED` plus a `running` marker, a reclaim whose cutoff is computed **database-side** so a skewed worker clock cannot steal a healthy job, a real attempt cap with dead-lettering, the embedding call outside the claim transaction, and a `SELECT enabled … FOR UPDATE` so it loses the race to a concurrent disable.
- **`whatsapp_outbound_jobs`** (`whatsapp_outbound.py:181-216`) handles the genuinely hard case: `post_attempted_at` splits reclaim into *requeue* (never left the process) versus *dead-letter* (Meta may already have it), because the Cloud API has no idempotency key.
- **`bot_turn_jobs`** (`bot_jobs.py:140-293`) does single-flight per conversation with a two-step CTE plus `pg_try_advisory_xact_lock`, documents why the lock is not in the `WHERE` clause, coalesces bursts, and dead-letters at the attempt cap **while returning the dead rows so the conversation escalates to a human**.
- **`webhook_deliveries`** (`webhooks_dispatch.py:270-343`) holds a `locked_at` lease, POSTs strictly between two short transactions, and enqueues inside the caller's transaction so a webhook cannot fire for a rolled-back payment.

**The `call_attempts` state machine** (`outbound.py:836-937`) is order-insensitive and idempotent by construction — `_RANK` plus a first-terminal-wins guard — and `outbound.mark` refuses to reopen a terminal attempt. **`cadence._recover_stranded`** (`cadence.py:522-597`) is the one place that explicitly handles "claim committed, side effect threw, second transaction needed."

**Resource discipline is strong.** One `Engine`, module-level, with `pool_pre_ping` and `pool_recycle`; no SQLAlchemy ORM anywhere; every one of 262 `connect()`/`begin()` call sites inside a `with`. The RLS tenant travels as a libpq *startup* parameter, so a pool ROLLBACK cannot silently unset it. Every per-session registry has a `release_*` that `_finalize_call` calls. `drain_background_tasks(session_id)` takes the id precisely so one hangup cannot cancel a concurrent call's work. Streaming LLM responses are closed in `finally`; `_SPEECH_SEM.release()` is in a `finally`; the file lock uses an ownership token so a stale break cannot release another holder's lock.

**The async hygiene that does exist is real.** The FastAPI lifespan wraps all eight boot steps in `asyncio.to_thread`. There is no `create_task` without a strong reference anywhere in the non-voice backend, and every `asyncio.gather` in `voice/` passes `return_exceptions=True`. `agent_core/**` outside two files contains zero `async def`, so there is no sync/async confusion to find.

**The frontend already implements the patterns the three defects skipped.** `useVoicePreview` has a generation counter, revokes its object URL on both stop and unmount, and detaches the audio element. `useCopilotStream` aborts its `AbortController` in cleanup and checks `signal.aborted` before writing state. Every `setInterval` has a matching `clearInterval`; every `createObjectURL` is revoked; the Studio autosave has an in-flight guard with a re-entry queue. The inbox polls through a module-level counter *explicitly* to survive StrictMode remounts.

**In the Mouth:** `_claim_end` and the `finalized` latch are check-and-set with no await between, so single-flight holds. `_close_probe_node` latches *before* awaiting, and says so. The PTP, dispute and callback idempotency keys are correctly scoped to `provider_call_id` so they survive a media-stream reconnect. `mesh._states` and `admission._active` are both properly locked.

---

## Method appendix

Five read-only analysts ran in parallel over non-overlapping territories: non-voice Python async, `Habibi/src`, workers and queues, resource lifecycles, and `voice/` races. Their reports were treated as leads, not findings.

**What was verified first-hand for this document,** by reading the cited source or by measuring the running stack: F1 (both call sites and the app-wide registration), F2 (handler is `async def`), F5, F6, F11, F12, F22, and the fleet-gate rejection; F7 and F15 in the frontend; the `ending_reason` writers in F8; Fact 2 by introspecting the installed Pipecat 1.6.0 inside `collections_voice` and grepping `backend/` for `run_in_parallel`; and the F9 numbers by executing against the live voice process (`cap = 25`, `pool = 3 + 2`, `pool_timeout = 30.0`). Live Postgres was read directly: `max_connections = 100`, 11 connections at idle.

**Confidence labels** are the analysts' own where I did not re-derive the claim, and are marked *Likely* or *Partial* rather than promoted.

**Not claimed.** No load test was run, so no finding here has been observed firing in production — each is a mechanism plus a scenario, not an incident. No test suite was executed (a corpus simulator can hold Postgres locks and make failures look real). Twilio's redirect idempotency was not established, so the double warm-transfer arm of F13 stays unproven. Whether a given model turn emits two tool calls is the provider's behaviour and was not measured — only that the runtime executes them concurrently when it does. The frontend was read, not driven; F17 and F30 depend on interaction timing windows that were reasoned about rather than reproduced in a browser.
