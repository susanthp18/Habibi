# 14 — Error handling and failure modes

**Scope:** `backend/` (~143k LOC Python, 393 non-test files) and `Habibi/src` (~98k LOC TypeScript)
**Date:** 2026-09-02 — **revision 2**
**Method:** five parallel analysts — backend exceptions, frontend errors, integration failures, retry/idempotency, API error contract — plus a sixth thread on the correlation spine. This revision re-derived every claim in revision 1 against the source rather than carrying it forward. Twenty-three claims were corrected or refuted; those are recorded in full at the end, because a wrong entry in an audit outlives the audit.

---

## What changed in this revision, and why it matters

Revision 1 reported **three Criticals** and a tidy thesis: good primitives, under-adopted. Verification kept the thesis and broke the count. There are **ten Criticals**, and the increase is not the result of a wider net — every new one was found by pulling on a claim revision 1 had already made, and finding the mechanism was different from the one described.

Three examples of that shape, because they set the confidence level for everything below:

- Revision 1's Critical C2 said the WhatsApp compliance gate fails open when Postgres is unreachable. **The stated mechanism is wrong** — `_whatsapp_opted_in` opens its own connection *above* the `try`, so a total outage fails closed. But `contact_policy.admit` keeps its "never raises" promise by returning **`allowed=True` for every non-outreach purpose** on any internal exception. The gate does fail open; it does so on a consent-table read error rather than an outage, on more paths than C2 named, and the guard C2 proposed fixing would never have fired.
- Revision 1's Critical C1 said the dial endpoints have no idempotency key. True, and understated: the one control that *would* have caught a double dial — contact-policy cooling-off — **is switched off on exactly those two endpoints** by session coalescing, which also stops the daily and weekly caps from being evaluated or incremented. The frequency ledger under-reports the burst it exists to detect.
- Revision 1 reported "90 Azure calls per customer message." The tool loop is not a retry loop; a persistent blip costs **~15**. The 25-minute figure belongs to the worker-crash path, not the exception path.

The pattern: revision 1 identified the right *seams* and guessed the *mechanisms*. Where a guess was wrong it was usually optimistic.

---

## Verdict

**The failure-handling primitives are better than the system that uses them.** That finding survives verification intact, and the evidence for it is stronger than revision 1 had: `azure_speech.py:373-457` could not be faulted under adversarial reading, `whatsapp_outbound.py:293-341` is the only adapter in the repository that reasons correctly about double-send, `circuit_breaker.py` closes two real races, and `pg_errors.py` chooses SQLSTATE over message text with the 42830 hazard named in a comment. Someone did the work.

What verification added is a sharper statement of what is wrong. The ten Criticals are not ten separate problems. They are **two**:

### Family A — five independent paths to contacting a borrower twice

| # | Mechanism | Where |
|---|---|---|
| **K1** | Session coalescing disables cooling-off and both frequency caps on the manual-dial endpoints | `contact_policy.py:965-981`, `main.py:3782`, `:4102` |
| **K2** | No idempotency key, no `ON CONFLICT`, no non-terminal-state check on `reserve` | `main.py:3731`, `:4029`, `outbound.py:309` |
| **K4** | An ambiguous carrier failure is recorded as "did not happen", and the campaign driver re-queues the target | `outbound.py:747-751` → `campaigns.py:611-626` |
| **K5** | A DB failure *after* a successful WhatsApp send produces an error string neither classifier can parse, so the job is retried | `whatsapp_outbound.py:545-560` |
| **K6** | The treatment executor claims, dials and marks-enacted in one transaction; a rollback replays the dial | `agent_core/treatment/enact.py:908-912` |

Five mechanisms, five files, one outcome. Under the RBI Fair Practices Code contact *frequency* is the regulated quantity, and `contact_day_counters` is the system's evidence that it was respected. K1 makes that evidence affirmatively wrong rather than merely absent: a regulator pulling `contact_events` for a borrower sees **one counted touch on a day the handset rang eight times**.

The repository already contains the correct answer to this class of bug, once, on the messaging channel: `whatsapp.py:201-244`'s `is_definite_client_error` / `is_ambiguous_transport_error`, with a docstring explaining that the Cloud API accepts no client-supplied idempotency key so an ambiguous error must never be retried. Voice never got it. K5 shows the discipline can be routed around even where it exists.

### Family B — five ways the record disagrees with what happened

| # | The record says | Reality |
|---|---|---|
| **K3** | consent, DND, cooling-off and caps were checked | the read failed and `admit` returned allow (`contact_policy.py:1020-1024`, `:596-600`) |
| **K7** | statutory bounce notice served, `first_touch_at` stamped | SMS was never configured; nothing was sent (`payment_events.py:668-675`) |
| **K8** | `{"ok":true,"idempotent":true}` — a duplicate | a second real ₹5,000 payment, discarded, absent from the ledger (`payments.py:147-148`) |
| **K9** | `{"ok":true}`, payment posted | the bounce is uncured and EMI rows are half-written (`payments.py:219-257`) |
| **K10** | the customer's refusal is recorded, "do not raise it again" | the write failed; the next call pitches the same product (`bot_tools.py:544-556`) |

Family B is the more serious of the two. A duplicate call is a breach you can find in the logs. A false record is a breach you cannot, and in a regulated pilot the artefact *is* the compliance position.

### If only five things are fixed

1. **K1** — move cooling-off and the cap reservation outside the `coalesced` branch, or stop passing `customer_id` as the session key on the dial endpoints. One of the two, not both; the second is a two-line change.
2. **K3** — `admit`'s exception path returns deny for every purpose, not just `outreach`.
3. **K7** — move `sent = True` inside the `if twilio_sms.configured():` guard. One line.
4. **K8** — key payment idempotency on `provider_ref`, as `db.py:10673-10688` already does for a *text message*.
5. **K10** and its two siblings — return the write's actual outcome.

Four of the five are under ten lines. None needs a shadow period, because all four change behaviour only on a path that is currently wrong.

---

## The end-to-end map

Provider failure → adapter → service → API → frontend → user, for every provider. Markers: `✗LOST` context destroyed · `✗LEAK` internal detail reaches a user · `✗AMBIG` "may have happened" collapsed to "failed" · `✗ID` identity dropped.

### Azure OpenAI

```
Azure 429/500
  └─ openai SDK, max_retries=2                          azure_openai.py:315
      └─ circuit_breaker "azure_openai"                  azure_openai.py:148
          └─ chat_with_tools                             azure_openai.py:597
              └─ BUT FIRST: llm_gateway try/except       azure_openai.py:618-632
                 ✗LOST bare `except Exception` swallows EVERY gateway outcome
                       INCLUDING the spend cap, then falls through to Azure
              └─ raises a RAW openai.* exception         azure_openai.py:678
                 ✗LOST no typed vocabulary; callers each guessed `except Exception`
  └─ job fails → bot_turn_jobs retries the whole turn    bot_jobs.py:330-366
     CORRECTED: ~15 Azure calls (3 SDK × 5 job), not 90. The tool loop at
     bot_runtime.py:954 iterates on tool calls, not on failure.
  └─ dead-letter → escalate_conversation_to_human        db.py:10132-10182
     ✗ the borrower receives NOTHING. No fallback message exists on this path.
```

### Azure Speech / TTS

```
REST path (studio preview, transcribe)
  └─ _speech_call_with_retry — the best retry in the repo  azure_speech.py:429-455
  └─ express-as fallback re-enters the whole loop          azure_speech.py:534-544
     ✗ up to 6 HTTP requests for one preview
  └─ RuntimeError(f"azure_speech_tts_failed:{status}:{detail[:300]}")  :555
     ✗LOST untyped RuntimeError
  └─ main.py:3039 → HTTPException(502, detail=str(exc))
     ✗LEAK 300 chars of raw Azure body → VoicePanel.tsx:464-467 toast
     ✗ CircuitOpenError IS a RuntimeError (circuit_breaker.py:22), so this route
       catches it first and returns 502; the registered 503 handler at
       main.py:712 never runs. The breaker's "shed load" signal reads "broken".

LIVE CALL path — different, and behind no breaker at all
  └─ pipecat websocket AzureSTT/TTS                        voice/bot.py:642,665
     ✗ the azure_speech breaker wraps only _speech_call (:411). The regulated
       path is unprotected; the demo path fast-fails correctly.
  └─ bound TTS dies mid-turn → yield ErrorFrame(...)       fish_service.py:171,188
     ✗LOST no ErrorFrame handler exists anywhere in backend/. The turn produces
           NO AUDIO. There is no runtime Azure fallback — only a bind-time one.
  └─ session.extra["providers"]["tts"] still reads source:"binding"
     ✗LOST provenance is stamped at BIND time and never revised, so it asserts a
           provider spoke that did not — in exactly the case it exists to catch.
  └─ VoicePanel.tsx:824-828 renders the intended providerName regardless
  └─ CallCostPanel.tsx:148-151 hardcodes "Azure bills continuous recognition"
     ✗ the cost view does not read the binding table either. On a bound-Cartesia
       call it is right by accident when the fallback fires, wrong otherwise.
```

### Twilio voice — the K4 path

```
TwilioRestException | read timeout | 21211 | 21610 | 429
  └─ start_outbound_call: event("dial.failed"), bare raise   twilio_ops.py:372-381
     ✗LOST raw SDK exception; the only typed error is OutboundDisabled
     ✗ no circuit breaker anywhere in this file
  └─ outbound.place  except Exception                        outbound.py:747-751
     ✗AMBIG a read timeout where Twilio DID create the call is indistinguishable
            from a connection refusal. Both → {"placed":False,"state":"failed"}
     ✗LEAK _fail_quietly writes str(exc)[:400] to call_attempts.provider_error
           (:749 → :822). The webhook path writes the SAME column as a ≤64-char
           numeric code (:908-910). Two vocabularies, one column.
  ├─ cadence path: `failed` is in no retry_on → not_retryable:failed
  │  ✗ under-retry: a call that may have connected closes the case
  └─ campaign path: placed:False → state='pending', +5 min   campaigns.py:611-626
     ✗ OVER-retry: the borrower is dialled again. Revision 1 called this
       "under-retry rather than double-dial." It is both, on different drivers.
  └─ OutboundControlPanel.tsx:296-299 paints the failure as WARNING, the same
     colour as "blocked by calling hours", and never updates after success.
     The second dial is invisible from the only screen that reports dialling.
```

### WhatsApp / Meta

```
OUTBOUND — the exemplar. No defects in the classification itself.
  └─ _classify_send_error → stable code, parsed fields only  whatsapp.py:247-256
  └─ mark_failed_or_retry                              whatsapp_outbound.py:293
     ├─ ambiguous → dead + "ambiguous_transport: …" for reconciliation  :305-324
     ├─ definite  → dead                                                :326-341
     └─ else      → capped backoff, exponent bounded at 12              :359-372

  ✗ BUT the guard is routed around (K5): a DB failure AFTER a successful send
    produces "whatsapp_send_failed:internal:OperationalError" (:283-285), which
    both classifiers fail to parse (whatsapp.py:231-245 raises ValueError on
    parts[1]), so the job is REQUEUED. delivery_status is still 'sending'
    because that write is the one that rolled back, so the pre-send guard at
    :418-423 does not short-circuit. post_attempted_at is set but
    claim_next_job never consults it (:218-232). The borrower gets the dunning
    message twice, ninety seconds apart.

INBOUND — the hole
  └─ per-message savepoint, correct, comment explains why  db.py:10925-10946
  └─ return {"ok": True, "results": results}               db.py:10974
     ✗LOST no scan of results for status=="error"
  └─ main.py:4618 returns it through unread
     ✗ Meta gets HTTP 200 → never redelivers → the borrower's reply is gone.
       Inbound messages are regulatory evidence.
```

### MinIO

```
S3 timeout — with NO client timeout at all               storage.py:113-118
  ✗ every other HTTP client in backend/ sets one. Full sweep confirms MinIO is
    the sole exception, and it is the one socket that can black-hole.
  └─ StorageUnavailable(f"minio_put_failed: {exc}")        storage.py:252
     ✗LOST the SDK type is gone; "bucket missing" vs "credentials wrong" vs
           "network" are now one string
  └─ main.py:4460 → HTTPException(503, detail=str(exc))
     ✗LEAK breaks the file's own convention, applied correctly 60 lines away
           at main.py:4399-4403, 4464-4466
  └─ config.ts:101-102 passes `detail` through; :136 builds the message
  └─ knowledge-base.lazy.tsx:413-416 toast:
     "POST /kb/documents failed: S3 operation failed; code:
      XMinioServerNotInitialized, …"
     ✗ the operator reads raw S3 internals. UploadWizard has no inline error
       region at all (:135-137) and stays on step 3 reading "Uploading to
       MinIO and waiting for API acknowledgement…" (:333)
```

### LLM gateway

```
400 | 401 | 429 | 500 | connect error
  └─ for attempt in range(3)                       llm_gateway/client.py:112-130
     ✗ bare except retries a PERMANENT 401/400 three times, with NO delay
       (time.sleep is never called in the file)
  └─ RuntimeError(f"llm_gateway_http_failed:{type(last_exc).__name__}")  :131
     ✗LOST status, Retry-After and body all discarded
  └─ _over_cap raises RuntimeError("llm_gateway_spend_cap:…")             :53-54
  └─ azure_openai.py:618-632 bare except swallows ALL of it, incl. the cap,
     and proceeds to Azure
     ✗ a hard spend control reports itself enforced and is not
     ✗ _spend_inr is a process-local dict (:22) — with N uvicorn workers the
       cap is N× what the operator configured
     ✗ amplification: 3 gateway attempts (3×20s) THEN a full Azure call with
       max_retries=2 — and on a live voice turn this defeats the caller-supplied
       timeout BEFORE the code that enforces it runs (azure_openai.py:660-663
       documents that budget: "a budget the caller cannot enforce is not a budget")
```

### Payment / pay-link

```
PSP webhook POST /webhooks/payments/{provider}              main.py:825
  └─ inside db.engine.begin()                               main.py:843
      └─ payments.record_payment                            payments.py:117
          ├─ intent.status == 'paid' → {"idempotent": True}  payments.py:147-148
          │  ✗ K8: keyed on INTENT STATUS, not provider_ref. A genuine SECOND
          │    payment (different provider_ref) is swallowed and never posted.
          │    db.py:10673-10688 deduplicates a TEXT MESSAGE on provider_ref
          │    with a unique index and a SQLSTATE check.
          ├─ cure_for_account, no savepoint, caller's conn   payments.py:219-239
          │  ✗ K9: a mid-loop failure leaves some EMI rows paid, cured==[],
          │    _close_treatment_cases closes nothing, the webhook publishes
          │    "curedEvents":[] — then the transaction COMMITS and the API
          │    returns {"ok": True} at :257
          └─ ValueError("intent_expired") → main.py:851 → 409 str(exc)
             ✗ a 409 stops PSP retries. Money taken, no ledger row, and no
               park-for-reconciliation exists for MONEY — while
               whatsapp_outbound.py:305 has one for a text message.

CBS bounce webhook                                          main.py:857
  └─ pe.ingest → _first_touch → twilio_sms.send()      payment_events.py:669
     ✗ a live carrier call inside an HTTP webhook's open transaction
     ✗ K7: `sent = True` sits OUTSIDE `if twilio_sms.configured():` (:668-675)
```

### Remote MCP connectors — core-banking tools on a live call

```
remote timeout | 500 | JSON-RPC business error
  └─ RuntimeError(payload["error"]["message"])   agent_core/connectors/persist.py:378
  └─ dispatch except Exception                                        :275-287
     ✗LOST a remote's legitimate business answer ("mandate already presented")
           is indistinguishable from a socket timeout — both become
           {"ok": False, "error": "connector_call_failed"}
     ✗ AND circuit.record_failure is called for the business error (:286), so a
       remote correctly REFUSING requests opens the breaker on a healthy
       connector. OPEN_AFTER=3, and recovery needs an operator health probe.
     ✗AMBIG a side-effecting connector tool that timed out is reported to the
            model as a flat failure; the bot then tells a borrower on a live
            regulated call that it did not work, while the CBS may have applied it
  └─ bot_tools.py:843-850 wraps it in a SECOND identical collapse
  └─ bot_tools.py:880-887 → {"error": f"tool_failed:{type(exc).__name__}"}
     ✗ the LLM improvises what the borrower hears from a Python class name
```

### A genuine unhandled 500

```
uncaught non-HTTPException
  └─ passes ExceptionMiddleware, CORSMiddleware            main.py:614-617,647
  └─ passes RequestIdMiddleware — the header is set on the line AFTER
     call_next, outside the try/finally                    main.py:337-344
     ✓ the ContextVar IS reset, so the id reaches the LOG
     ✗ the id never reaches the RESPONSE
  └─ caught by Starlette's ServerErrorMiddleware, outside all user middleware
     ✗ no CORS headers. No @app.exception_handler(Exception) exists repo-wide;
       only four handlers, at main.py:693, :698, :704, :712.
  └─ fetch rejects with TypeError BEFORE a Response exists, so apiGet
     (config.ts:168-181) never constructs an ApiError
     ✗ isNotFound() is false; retryUnlessClientError falls to
       `return failureCount < 2` — every 500 is RETRIED, then rendered as
       "Failed to fetch"
  └─ the operator cannot distinguish a bug that dropped a payment write from
     their own Wi-Fi, and has no id to quote.
```

---

## Where context is lost — summary

| Boundary | What is lost | Consequence |
|---|---|---|
| Provider SDK → adapter | Error *class* for Azure OpenAI, Twilio voice, Twilio SMS, the LLM gateway, MinIO | Callers cannot decide retry vs abandon; each guesses with `except Exception` |
| Adapter → service | "May have already happened" for Twilio dials | K4: under-retry on cadence, **double-dial on campaigns** |
| Adapter → service | Twilio 21610 (carrier-level opt-out) collapsed to `reason="failed"` | A consent signal becomes a transient error and is retried forever |
| Connector → model | Business refusal vs transport failure | The bot tells a borrower an action failed that may have applied; the breaker opens on a healthy connector |
| Service → API | Which constraint fired (`IntegrityError` → static code) | **Deliberate and correct.** The one place the codebase gets leak-prevention right |
| API → frontend | Error *shape* — 0 of 312 routes declare `responses={...}` | Six distinct body shapes, none documented |
| API → frontend | 404-ness for 7 real not-found conditions raised as `ValueError` | `isNotFound()` — the console's only absence-vs-failure predicate — cannot fire |
| API → frontend | `X-Request-Id` on a true 500, and CORS headers | The incident is unattributable and reads as a network outage |
| Frontend query → render | Failure vs emptiness | The consent register says "no consent records"; the compliance dashboard says "0 critical" |
| Runtime → CRM/audit | Which provider actually spoke | Written at bind time, never revised, read by nobody |
| Worker → logs | Which queue and which row failed | `logger.exception("process_one crashed — backing off")` and nothing else |

---

## Findings by severity

**The bar.** *Critical* — a regulated action completes, or regulated evidence is written, without the check or record that authorises it; or borrower money or contact is duplicated or lost. *High* — a failure is invisible or misattributed on a surface someone relies on to act. *Medium* — a correctness or consistency defect with a bounded blast radius. *Low* — hygiene.

### Critical

**K1 — Session coalescing disables cooling-off and both frequency caps on the two manual-dial endpoints.**
`contact_policy.py:965-981`. `admit` computes `coalesced = _session_coalesced(...)` at `:965`, then `counts = purpose in {...} and not coalesced and not related_done` at `:969`, and puts **cooling-off, the weekly cap and the daily-cap reservation all inside `if purpose == "outreach" and counts:`** at `:971-981`. `_session_coalesced` (`:403-428`) returns True whenever a prior allowed `contact_events` row shares the `session_key` inside `session_window()` — 30 minutes (`:118-119`). Both dial endpoints pass the **customer id** as the session key (`main.py:3782`, `:4102`), and `related_id` is a fresh attempt id so `_already_counted_related` (`:430-452`) never matches.

*Scenario.* An operator clicks "Call now". The call is admitted, a `contact_events` row is written with `session_key = CUS-123` and `touch_counted = true`. Ten seconds later they click again. `admit` finds the first event, sets `coalesced = True`, so **cooling-off is never evaluated, the daily counter is never incremented, and the weekly cap is never read**. The call is admitted. This repeats, unbounded, for thirty minutes, and **the daily cap of 3 records one touch for the whole burst**.

What still binds: `_veto` (`:477-532`) runs unconditionally, so consent, DND, opt-out and the RBI 08:00–19:00 window hold. What does not bind: every frequency rule.

**K2 — An HTTP retry places two live calls to one borrower.**
`main.py:3731` and `:4029` call `outbound.reserve()` with no idempotency key. `reserve` (`outbound.py:309-425`) has no `idempotency_key` parameter, a plain `INSERT` at `:372-412` with no `ON CONFLICT`, no advisory lock, and no `SELECT … WHERE state IN ('reserved','dialing')` guard. The only unique index on `call_attempts` is `ux_call_attempts_provider_call` (partial, `provider_call_id IS NOT NULL`) — `sql/21_outbound.sql:91-93`, confirmed unchanged in `alembic/versions/20260822_0094_outbound_attempts.py:246-248`. `provider_call_id` is written only in `_mark_dialing`, *after* `calls.create` returns (`outbound.py:753-755`), so two reservations never collide; that index exists to dedupe Twilio's own status callbacks, which it does correctly.

Upstream guards checked and found absent: no rate-limit middleware (`main.py:607-617`; the only limiter is `kb_rate_limit`, KB-only); the fleet gate (`outbound.py:585-596`) is an unlocked `count(*)`, a capacity cap and not a dedupe. And the one guard that would have caught it is K1.

The machinery exists in the same file: `_handle_write` (`main.py:720`) threads an `Idempotency-Key` for creating an interaction, promise, dispute and lead, backed by `idempotency_keys` with a transaction-scoped advisory lock (`db.py:686-717`) added to close a past duplicate-promise race. It is applied to writing a promise and not to dialling a person.

**K3 — `contact_policy.admit` returns ALLOW for every non-outreach purpose when it cannot read the database.**
`contact_policy.py:1020-1024`, identically at `evaluate` `:596-600`:

```python
except Exception:
    logger.exception("contact_policy.admit failed customer=%s", cid)
    if purpose == "outreach":
        return Decision(False, REASON_UNREADABLE, daily_cap=cap)
    return Decision(True, daily_cap=cap)
```

Inside that same `try` sit `_channel_status` (`:321-325`, the opt-out/consent read), `_veto` (DND, calling window, statutory window), the cooling-off check and the cap reservation. A lock timeout, an RLS mis-grant, a migration in flight or a bad column **admits the send**. Non-outreach callers: `bot_runtime.py:150` (every bot WhatsApp reply), `whatsapp_outbound.py:449`, `db.py:10280`, and `purpose="statutory"` at `payment_events.py:587/634/648` and `promise_fulfillment.py:599/995`.

This is why `bot_runtime.py:158`'s own `except` never fires — `admit` swallowed the exception first — and it is presumably why nobody noticed. Revision 1's C2 proposed hardening that unreachable handler.

**K4 — An ambiguous Twilio failure is re-dialled by the campaign driver.** `outbound.py:747-751` → `campaigns.py:611-626`. Twilio accepts `calls.create`; the response times out at 10s (`twilio_ops.py:265`); the borrower's phone rings and the bot is answered. We record `state='failed'`, the campaign driver reads `placed:False` as "did not happen", returns the target to `pending` with `next_attempt_at = now() + 5 min`, and dials the same borrower again. Only K1's cooling-off would have stopped it, and on this path cooling-off is evaluated — but the second dial is five minutes later and unattributable, because the first attempt has no `provider_call_id`.

**K5 — A database failure after a successful WhatsApp send re-sends the message.** `whatsapp_outbound.py:545-560`. Traced in the map above. The module's own docstring at `:290-299` says a retry after a possible acceptance "double-sends to the customer". The guard was built and then routed around by an error string it cannot parse.

**K6 — The treatment executor replays the dial or SMS on a rollback.** `agent_core/treatment/enact.py:908-912`. `process_one` opens `engine.begin()`, calls `decisions.claim_due` (`FOR UPDATE SKIP LOCKED`), then calls `enact_one` **in the same transaction**. `enact_one` fires `twilio_sms.send` (`:307`) or `outbound.place` (`:384`) and only afterwards calls `mark_enacted` (`:135`) on that connection. On a rollback, `enacted` reverts to false and the plan matches `claim_due` again — as does the `contact_events` row `admit` wrote, so the daily counter never moved either. `bot_worker.py:127` does not guard `treatment_enact.process_one`, so the exception reaches the main-loop catch-all (`bot_worker.py:219-224`), which sleeps 1.5s and continues. **The borrower is dialled a second time while the first call is still ringing.** `treatment_decisions` has no attempt counter for this loop.

The correct pattern is in the same dispatch table: `_dial_bot`'s docstring (`enact.py:326-334`) explicitly commits on its own transaction so a crash "leaves evidence rather than a spent contact budget with no cause". Three handlers under `_HANDLERS` (`:894-896`), three different disciplines.

**K7 — A statutory bounce notice is recorded as served when no SMS was sent.**
`payment_events.py:668-675`. `sent = True` is at try-block level, **outside** `if twilio_sms.configured():`. With `TWILIO_SMS_FROM` unset on a tenant, a bounce arrives, WhatsApp is outside the 24h window, the path falls to SMS, nothing is sent — and the record reads `status='in_progress'`, `first_touch_at=now()`, `first_touch_channel='sms'`, `suppression_reason=NULL` (`:680-700`). Because `suppression_reason` is nulled, no report will ever surface it. The statutory bounce notice is a legal obligation with a clock; the system's own evidence says it was served on a date when nothing happened.

**K8 — A second real payment is discarded as a replay.** `payments.py:147-148`. Idempotency is keyed on `payment_intents.status == 'paid'`, not on `provider_ref`. Borrower pays ₹5,000, the page hangs, they pay ₹5,000 again — two distinct PSP webhooks with two distinct `provider_ref`s. Only the first posts a `ledger_entries` row. ₹5,000 of the borrower's money exists at the PSP and not in the ledger, `accounts.outstanding` is overstated, and collections continues against them for money already paid.

**K9 — A posted payment returns `{"ok": True}` with the bounce uncured.** `payments.py:219-257`. `record_payment` writes the ledger entry and allocates to promises, then wraps `pe.cure_for_account` (`payment_events.py:961`) in `try/except Exception` on the **caller's connection with no savepoint**. `cure_for_account` loops `UPDATE emi_installments` per instalment. A mid-loop failure leaves some instalments marked paid, `cured == []`, `_close_treatment_cases(conn, bounce_ids=[])` closing nothing, the `payment.updated` webhook publishing `"curedEvents": []` — and then the transaction **commits** and the API returns `{"ok": True, …}` at `:257`. The borrower has paid, the money is booked, and the delinquency record stays open, so the treatment ladder keeps escalating against someone who is current.

**K10 — A declined offer reports success when the write failed.** `bot_tools.py:544-556`. `_tool_decline_offer` wraps `capture.record_offer_declined(...)` and unconditionally returns `{"ok": True, "say": "acknowledge briefly and move on; do not raise it again"}`. On a write failure the refusal is never recorded, the bot promises not to raise it again, and the next call pitches the same product with no audit trail that a refusal happened. Two siblings share the shape: `bot_tools.py:520-533` (`mark_upsell_presented`, silently undercounting the funnel) and `agent_core/tools/domain.py:767-770` (the PTP-captured flag — the promise row survives, the interaction marker does not, and call-outcome reporting, the treatment ladder's PTP signal and agent QA all read that flag).

### High

**Compliance and consent surfaces that fail open or fail silent**

- **H1 — `contact_policy.narrow_window` writes a consent record and its audit row unguarded on the caller's connection.** `contact_policy.py:675-735`. The `try` spans `INSERT INTO consent_records … ON CONFLICT DO UPDATE SET allowed_hours` (`:704-716`) and `record_activity` (`:719-727`), with no savepoint; the handler at `:732-735` returns `{"ok": False, "reason": "failed"}`. Two failure modes: the consent row lands but the activity row does not, so the dialler's window is narrowed with no audit trail of who narrowed it; or the caller's transaction is now aborted while it sees an ordinary `ok: False` and carries on. Callers: `bot_tools.py:405-416`, `voice/tools.py:1754`. This is the write for "don't call me before 10am."
- **H2 — `db.py:8592-8605` falls back to a weaker compliance check with zero logging.** On a `contact_policy.evaluate` failure, `_inbox_contactable` consults only DND and the preferred window — **ignoring opt-out, cooling-off, daily cap and weekly cap** — and the result is surfaced to a human agent as `"contactableNow"` (`db.py:8833`). A collector reads a green badge on a borrower who has opted out. There is no log line anywhere to reconstruct why.
- **H3 — `agent_core/treatment/features.py:486-489` records a failed consent read as "no consent on any channel."** `consent = {}` on failure, stored on the feature snapshot (`:519`) and serialised as `"consentByChannel": {}` (`:375`) into the treatment decision record — the "why did the model do that" artefact. `agent_core/reco/arbitration.py:75-77` shows what an empty map means downstream: `.get(channel)` → `None` → not in `_CONSENT_BLOCKING` → **the suppression does not fire**. The sibling at `agent_core/reco/features.py:395` has no try and correctly raises.
- **H4 — The consent register renders a 500 as "No consent records match the current filters."** `Habibi/src/routes/consent.tsx:46` → `ConsentTable.tsx:176`. All four mutations in the file toast on error (`:70,79,93,102`); the read that shows current state does not. An agent checking whether a borrower has withdrawn consent is told, in a sentence, that no such record exists — the direct input to a decision to place a call.
- **H5 — The compliance dashboard renders a 500 as measured zeroes.** `compliance.tsx:57,201,220` → `ComplianceStatsStrip.tsx:44-52` computes `openCritical`, `openTotal`, `mtd` by filtering an empty array. A supervisor's daily glance at "0 critical violations" is a network error. This is precisely the failure `Habibi/src/components/ui/query-state.tsx:16-21` was written to stop, in its own words: "a false statement about the system, in numbers, which read exactly like a measured one."

**Failure indistinguishable from emptiness, elsewhere**

- **H6 — `RecordsTable` structurally cannot show an error state.** `RecordsTable.tsx:24-45` declares `isLoading?` and `emptyMessage?` and no error prop; `:284` renders `emptyMessage` whenever `!isLoading && visibleRows.length === 0`. **19 files, 24 render sites** (corrected from 22). Only `customers.index.tsx` and `AssignedQueue.tsx` read `isError` in the same file. `McpConsole.tsx:35,166-171` tells the operator *"No connectors. Seed creates pay-link and LMS."* when the request 500s.
- **H7 — `FilterTable` has no error prop AND no `isLoading` prop.** `FilterTable.tsx:21-33,155-160`. The borrower's payment ledger renders "No entries in this window." (`LedgerTab.tsx:152-158`) and the instalment schedule renders "No installments on this account." (`EmiTab.tsx:181-187`) — during the load as well as on failure. An agent on a live call reads a borrower their own payment history; "no entries" is a factual assertion about a debt record produced by a slow read. 6 consumer files.
- **H8 — `ApprovalsQueue` renders `null` on a failed read.** `ApprovalsQueue.tsx:7,9` — `const { data = [] }` then `if (USE_MOCK || data.length === 0) return null;`. The pending-approvals banner **disappears entirely** on a 500. A workflow is blocked waiting on a supervisor decision and the supervisor's screen shows nothing to approve. No reviewer found this because its failure mode is rendering nothing at all.
- **H9 — `fetchCustomerInsights` fabricates data on backend failure.** `Habibi/src/api/customers.ts:36-60`. Catches any error, logs at `:55`, returns a client-derived object at `:58`, so `isError` is never true. *Corrected:* it is not fully silent — the derived object carries a rank-1 marker "Recommendation unavailable" (`customerInsights.ts:269-278`) — but that attaches only to `nba`; `summary` and `metrics` (`customerInsights.ts:114-119`) still render as if server-computed. **No other function in `src/api/**` does this**; all 17 catch sites were read.

**Writes that silently no-op**

- **H10 — `McpConsole` has 12 mutate sites and zero `onError`.** `McpConsole.tsx:104, 262, 269, 361, 464, 485, 570, 599`; only 3 `.catch`. Clicking **Revoke** on an MCP API key that 500s does nothing, shows nothing, and leaves the row — the operator believes a live credential is dead. Same for connector Approve, vault secret store/rotate (the `.then` that clears the field and toasts "Stored — secret is not shown again" never fires, so the field stays populated with no explanation), and canary promote. With `retry: 0` there is no second attempt.
- **H11 — Campaign pause has no error handling.** `OutboundTab.tsx:594` — `setStatus.mutate({runId, status})`, no `onError`, no `isError`, while siblings at `:327` and `:362` do check. On failure the button re-enables and the row's lozenge still reads `running`, which looks identical to a pending refetch. The operator believes a campaign stopped dialling and it has not.
- **H12 — Floor-alert acknowledgement has none either.** `HandoffQueue.tsx:9-14,36`. A supervisor acknowledging a live escalation gets no feedback if the write failed, and the row stays — which is also what success looks like before the invalidate lands.
- **H13 — Automatic presence transitions are unguarded.** `presence.ts:59-67` has `onSuccess` only; `handoff.lazy.tsx:385` fires `presenceMut.mutate("wrap_up")` and discards the result. The agent believes they are in wrap-up; routing still sees them `available` and can push the next escalation onto them mid-wrap. The *manual* toggle at `AvailabilityToggle.tsx:66` does have an `onError`.

**Integration and operability**

- **H14 — `session.extra["providers"]` has no reader, and asserts a false fact when it matters.** Written at `voice/bot.py:649,673`; the only readers repo-wide are its own tests. Zero occurrences of `session.extra` in `Habibi/src`. Worse (**N6**): provenance is stamped at **bind** time (`provider_bind.py:106-113`) and never revised, so a provider that builds fine and dies mid-call still reads `source:"binding"` — false in exactly the case the field exists to catch. And no `ErrorFrame` handler exists in `backend/`, so a mid-turn TTS death is dead air with no Azure fallback; the bind-time fallback the docstring promises does not exist at runtime.
- **H15 — Twilio has no circuit breaker, and neither does the live speech path.** Five in-process breakers exist (`azure_openai.py:148,161`, `azure_speech.py:424`, `storage.py:168`, `whatsapp.py:72,132`), plus a **second, independent DB-backed one** at `agent_core/connectors/circuit.py` that shares no state or snapshot with them. `voice/twilio_ops.py` imports neither; nor does `twilio_sms.py`, `llm_gateway/client.py` (which retries), or `provider_tts.py`. And the `azure_speech` breaker wraps only `_speech_call` (`:411`) — the REST preview path — while the live call uses pipecat websockets (`bot.py:642,665`) behind nothing. **The breaker protects the demo path and not the regulated one.**
- **H16 — The WhatsApp webhook returns 200 when every message in the batch failed.** `db.py:10974`, `main.py:4618`. Safe to fix precisely: ingest is idempotent on `messages.provider_ref` with conflicts detected by SQLSTATE 23505 (`pg_errors.py:12,16-31`), so returning 500 when all items errored makes Meta redeliver and the already-ingested messages are correctly treated as duplicates.
- **H17 — Carrier calls inside open transactions, one holding a row lock.** `enact.py:307`, `payment_events.py:669`, `promise_fulfillment.py:1014` — and the last holds `FOR UPDATE SKIP LOCKED` (`:1046,1057`) across the 10s Twilio timeout while `twilio_sms._record_sent` (`:110`) acquires a *second* pool connection. Under any concurrency the pool exhausts and `/ready` starts 503-ing on pool headroom.
- **H18 — `promise_fulfillment.process_one_reminder` retries a non-idempotent SMS without bound or accounting.** `:1044-1093`. No attempt column exists on this loop; the only terminal states are `sent` and `failed`, both written after the send. If the commit fails after delivery, `status` stays `queued` and the borrower gets the same PTP-confirm SMS every poll. Separately, a policy denial is written as `failed` (`:1010-1012`), so an `outside_calling_hours` refusal at 19:05 permanently kills a statutory notice that would have been fine at 08:00.
- **H19 — Contact-policy denials are fed into the transient-error retry ladder.** `whatsapp_outbound.py:436-466`. `outside_calling_hours`, `daily_cap` and `cooling_off` match neither classifier, so the job burns all 5 attempts in **under four minutes** and dead-letters — a message blocked at 19:05 is dead by 19:09. And each attempt writes a `contact_events` denial row (`contact_policy.py:945-958`), so **one blocked message produces five denial events**, inflating the denial-rate metric the table exists to make queryable.
- **H20 — `twilio_sms`'s stated contract is not kept, and 21610 is collapsed to "failed".** `twilio_sms.py:52` promises "Raises ValueError on config/API errors"; only config errors do (`:66,68`). All four call sites need `except Exception`, and `written_followup.py:339-341` collapses to `reason="failed"`. Twilio 21610 means the recipient opted out **at the carrier** — a consent signal, now indistinguishable from a network blip and retried forever.

**API contract**

- **H21 — A true 500 reaches the browser with no CORS headers and no request id, and is then retried and rendered as a network outage.** Traced above. Every link verified; no global exception handler exists.
- **H22 — Seven genuine not-found conditions can never return 404.** Raised as `ValueError`, so they land on the ValueError arm and map to 400/409: `db.py:5737`, `:5970` (`product_not_found` → **409**), `db.py:14499` (`kb_snapshot_not_found` → **409**), `db.py:15863`, `:15976` (**400**), `kb_retrieve.py:678`, `sandbox_runtime.py:584`. `isNotFound()` (`config.ts:145-147`) tests `status === 404` and is the console's only absence-vs-failure predicate. An operator publishing a prompt version against a deleted KB snapshot gets a 409, which reads as a concurrency conflict and invites a retry that can never succeed.
- **H23 — Raw provider text is rendered to the operator.** `config.ts:101-102` passes `detail` through unmodified; `:136` builds `` `${method} ${path} failed: ${detail}` ``; ~135 sites toast `err.message`. Confirmed rendered: MinIO S3 internals (`storage.py:252` → `main.py:4460` → `knowledge-base.lazy.tsx:413-416`), 300 chars of raw Azure Speech body (`azure_speech.py:555` → `main.py:3039` → `VoicePanel.tsx:464-467`), 200 chars of raw TTS vendor body (`provider_tts.py:107` → `main.py:2990`). The file's own correct convention is 60 lines away at `main.py:4399-4403`.
- **H24 — Borrower PII is rendered into toasts on every routine 422.** `main.py:698-700` uses FastAPI's default handler, whose `errors()` includes an `input` field echoing the submitted value; `config.ts:104-107` `JSON.stringify`s the whole array into `ApiError.message`. A 422 on a customer-create form renders the submitted PAN, phone and name into a toast — and the console ships `lib/lovable-error-reporting.ts`, third-party error telemetry. This is the highest-volume leak, because 422s are routine.
- **H25 — Unauthenticated internal-topology disclosure on `/ready`.** `main.py:777` returns `detail = result`, the whole readiness object, including `minio.detail = str(exc)` (`storage.py:157`) and `circuit_breaker.snapshots()`. `/ready` is in `_AUTH_EXEMPT_PREFIXES` (`main.py:235`). Anyone reaching the LB endpoint during a MinIO blip reads the internal hostname and port plus a live map of which providers are failing. `db.readiness()` (`db.py:344-354`) gets this exactly right, and says why in a comment. *Severity note: the integration analyst rated this Low (not rendered), the API analyst Critical (unauthenticated). Recorded as High — it is a real disclosure on an unauthenticated endpoint, and not a borrower-harm path.*
- **H26 — Cross-tenant read on `GET /customers/{id}/outbound/hours`.** `outbound.py:1177-1199` via `main.py:4833-4843` — `hourly_reach` filters on `WHERE a.customer_id = :cid` and joins `customers` with **no `c.tenant_id` predicate**, unlike the query 15 lines above it (`main.py:4823`). A caller with another tenant's `customer_id` reads that borrower's per-hour contact-attempt and answer history, with a 200. `call_attempts` is not in `_CUSTOMER_SCOPED_TABLES` (`db.py:217-232`), and `rls.py:19-23` says `enable()` refuses while the app connects as a superuser, so the backstop may be inert. *Out of this audit's scope; recorded because it was found while tracing the 200-with-empty-list finding, and it belongs to the tenancy workstream.*
- **H27 — The dial-failure banner paints a compliance refusal and a carrier outage the same colour.** `OutboundControlPanel.tsx:296-299` styles it `text-text-warning-bolder`; `friendlyOutboundError` (`platform.ts:150-179`) substring-matches ~8 reasons and otherwise `return raw`. A Twilio 5xx (an incident) and "blocked by calling hours" (correct, expected) are visually identical to the operator on duty.
- **H28 — A stranded campaign target reads as a completed one.** `OutboundTab.tsx:561-580` renders only `targets_done/targets_total`; per-target state is never fetched and no stuck indicator exists anywhere. A target stranded in `dialing` never increments the counter, so a run with a strand looks slow; `stale_after()` later resolves it to `done` with `outcome = NULL`, the counter jumps, and the run reads **complete**. A borrower who was never dialled is counted as a finished target.
- **H29 — One poison row starves every queue below it.** `bot_worker.process_one_any` guards `call_closer` (`:109`), `cadence` (`:117`), `campaigns` (`:122`) and `clerk` (`:156`), and leaves **`bot_jobs` (`:93`), `whatsapp_outbound` (`:95`), `promise_fulfillment` (`:97`), `payment_events` (`:99`), `webhooks_dispatch` (`:145`) and the three treatment jobs (`:127,132,139`) unguarded** — and five of those run *above* the guarded ones. An exception in `whatsapp_outbound` aborts the tick before `call_closer` is ever reached. The main loop (`:219-224`) logs `logger.exception("process_one crashed — backing off")` — no queue name, no row id — sleeps 1.5s, and repeats forever with no attempt accounting. `followthrough.advance` (`:424-451`) is likewise unguarded and its caller (`:497-504`) runs it in a plain `engine.begin()` with no savepoint, while its sibling `sweep.py:181-196` documents the savepoint it uses to prevent exactly this.
- **H30 — The handoff screen 500s and names the wrong query.** `db.py:4457-4502` — three policy loaders each `except Exception: return policy.empty()` on one shared `engine.connect()` (SQLAlchemy 2.0.44, so autobegin means a real transaction). A genuine Postgres error aborts it; `_handoff_compliance_items` at `db.py:4254` then runs unguarded and raises `InFailedSqlTransaction`. The error names the disclosures query; the fault was three functions earlier. This is what a human agent reads before taking over a live call, including the compliance checklist — and it fails whole rather than degrading.

### Medium

| # | Finding | Refs |
|---|---|---|
| M1 | `llm_gateway/client.py` retries every exception, including permanent 400/401, with **no delay** — `time.sleep` is never called in the file | `:112-131` |
| M2 | Transient Postgres errors are handled **nowhere**. No 40001/40P01 anywhere in `backend/`; `pg_errors.py:13` classifies only 23505. In a request path this is an unhandled 500; in the worker it is the uncapped 1.5s loop of H29 | repo-wide |
| M3 | `bot_jobs.py:351` caps the **exponent** at 6 against a 300s ceiling, so backoff plateaus at 64s and the cap is dead code. Its two siblings cap the exponent at 12 *with a comment* saying they do so because an earlier version had this bug | `:351` vs `whatsapp_outbound.py:369-374` |
| M4 | Reclaim never sets `run_after` (`bot_jobs.py:140-184`) while `claim_next_job` filters on it (`:217`), so a worker-crashing poison job is instantly re-claimable; the only pacing is `stale_running_seconds()` — 300s × 5 ≈ 25 min to dead-letter with the borrower unanswered | `:140-184` |
| M5 | No jitter in three job queues; `azure_speech.py:378-395` adds it deliberately and explains why | `bot_jobs.py:351`, `whatsapp_outbound.py:375`, `webhooks_dispatch.py:378` |
| M6 | `retry_on`/`stop_on` are validated by no compile gate — G-OB1..G-OB8 (`compile.py:167-176`) plus G-OB9 (`:453-465`) never touch them, and the strings appear nowhere in `compile.py`. An author can publish `retry_on: ["not_a_real_code"]`, or a value in both lists. Compounding: `main.py:5170` offers `sorted(outbound_mod.RETRYABLE)`, which **includes `rejected`** — which both cadence defaults omit and which `outbound.py:111-115` says should retire a number | `compile.py`, `main.py:5170` |
| M7 | `db.py:419-430` `_actor_user_id()` swaps in the process-wide `ACTOR_USER_ID` default — `"priya-nair"`, a **named human's id** (`db.py:93`) — on any exception, **with no log call at all**. `actor_context`'s docstring says its purpose is that every CRM write attributes the real caller and not a process-wide env spoof | `db.py:419-430` |
| M8 | 400 vs 422 for a missing required field is split 9/8 with no rule; `to_required` is 400 and `connector_id_required` is 422 | `main.py:841,3747` vs `:2167,2861` |
| M9 | Webhook signature rejection is **401** for payments and **403** for Twilio/WhatsApp — and the detail also splits (`invalid_signature` vs `invalid_twilio_signature`). A SIEM rule matching `status=401 AND detail=invalid_signature` catches 2 of 8 forgery signals | `:833,868` vs `:3489,3556,3578,3620,3687,4612` |
| M10 | `outbound_disabled` — the compliance kill switch — is a **502** on one dial route and a **503** on the other, and 5xx is wrong for a deliberate local switch in both. An operator sees "bad gateway" and escalates to the wrong team | `:3813-3818` vs `:4158-4163` |
| M11 | `CircuitOpenError` subclasses `RuntimeError`, so route-level `except RuntimeError` intercepts it and returns 502; the registered 503 handler never runs. Same for `AzureBusyError`. The breaker's "shed load" signal reads "we are broken" | `circuit_breaker.py:22`, `main.py:3039,3298` vs `:704-717` |
| M12 | No `Retry-After` header is set anywhere in the codebase, on either 429 or either load-shed 503 — while `config.ts:164` explicitly opts 429 *into* retry with no delay guidance | `main.py:706,714,4307,4579` |
| M13 | A connector's legitimate business error is collapsed to `connector_call_failed` **and scored against the circuit**, so a remote correctly refusing three requests opens the breaker on a healthy integration | `persist.py:275-287,378` |
| M14 | `GET /voice/status` returns **200** with `{"ok":false,"detail":"<raw httpx exception>"}` — a 200 carrying an error payload and an internal host:port, which defeats `ApiError` entirely | `main.py:3349-3352`, `voice_sandbox.py:126` |
| M15 | `except Exception` around `twilio_ops.start_outbound_call` reports a local `TypeError` to the operator and to metrics as a **502 Twilio failure**, so the SLO dashboard shows "Twilio degraded" while the real defect goes unlogged | `main.py:3805-3808` |
| M16 | The best-designed error body in the codebase is destroyed in transit. `CompileError.http_detail()` (`compile.py:107-112`) returns a per-gate structured verdict; **no frontend code handles the shape**, so `config.ts:104-107` stringifies it and clips at 400 chars — consumed by the serialised card before the failing gate's detail is reached | `compile.py:107-112` |
| M17 | Authorization denial is consistent in *status* (403) but not in *shape*: `{"detail":"forbidden:agent.publish"}` from the app-wide guard vs `{"detail":{"code":"compile_failed",…}}` from G14. A monitor matching `^forbidden:` misses every publish denial | `main.py:551` vs `:3130` |
| M18 | Idempotency is plumbed and unused on two CRM writes: `db.create_callback` (`db.py:5429`) and `db.create_document_request` (`db.py:6233`) both accept `idempotency_key`; `main.py:1592` and `:1639` never pass one, while five siblings on the same path do. `db.py:5714-5718` records that `capture_lead` was previously the one write without replay protection and "put two identical leads in the pipeline and two reps on the phone" | `main.py:1592,1639` |
| M19 | The fleet gate is a read, not a lock — a bare `count(*)` with no `FOR UPDATE`, so N concurrent dialers can all observe `cap - 1`. The effective ceiling is `cap + concurrency` | `outbound.py:441-458,585-596` |
| M20 | Supervisor barge returns `{"ok": True}` after three independently swallowed failures, so the `supervisor_actions.audio_joined` column can disagree with reality and a failed `mark_enacted` lets the auto-barge decision re-fire | `ops_screens.py:885,899,907` |
| M21 | Staff enumeration: `KeyError(f"user_not_found: {assignee}")` echoes a caller-supplied id, and the 404/200 split distinguishes "this staff user exists" from "it does not". `_assert_tenant_owns` (`db.py:271-280`) argues this case correctly for borrower rows; assignment paths do not follow it | `db.py:5141,5344,5460,5529,6260,6355,7078` |
| M22 | `EvalCockpit.tsx:64` renders any non-`pass` report as `danger`, painting `warn` and `skipped` red on the screen an auditor reads. `gate-status.ts:13-14` documents this bug; `gateTone`/`GATE_TONE` are imported nowhere. (The *first* documented bug **is** fixed — `ChangeLogTab.tsx:116` uses `partitionGates()`.) | `EvalCockpit.tsx:64` |
| M23 | `azure_speech`'s express-as fallback re-enters the whole retry loop, so one preview can cost 6 HTTP requests | `azure_speech.py:534-544` |
| M24 | `_spend_inr` is a process-local dict, so the LLM spend cap is N× the configured value with N workers | `llm_gateway/client.py:22` |
| M25 | Six distinct error body shapes live under `{"detail": …}` — bare code, colon-compound, free prose with ids, raw exception text, `{code, …}` object, and FastAPI's error array — plus a seventh at `main.py:777` (the whole readiness object). A generic client must branch on `typeof detail` | see the API analyst's shape table |
| M26 | ~30 production `assert` statements, dominated by a "write, re-`SELECT`, `assert row is not None`" idiom (db.py **15**, followups_db 4, ops_screens 3, adapter_pg 2, +6). These assert *runtime state*, not invariants. *Corrected:* `-O`/`PYTHONOPTIMIZE` is used **nowhere** in the repo, so the strip risk is hypothetical today | `payment_events.py:402` et al. |

### Low

- **L1** `azure_speech.py:71-74` and `storage.py:229,236,262` leak internal env var names to the caller.
- **L2** Two id-scoped GETs return 200 with an empty list for a nonexistent parent where four comparable routes 404 (`main.py:1535-1537`, `:4833-4843`).
- **L3** `main.py:4397-4398` returns `str(FileNotFoundError)` — the container's absolute filesystem layout — three lines above a comment warning that the underlying exception carries paths that must not reach a client.
- **L4** `main.py:2149-2156` is the only prose `detail` in 100+ error bodies; any client switching on `detail` breaks there.
- **L5** `db.py:286-289` — `_assert_tenant_owns` has an `if table == "customers"` branch that is unreachable because `"customers"` is not in `_CUSTOMER_SCOPED_TABLES`; a future addition raises a 409 leaking the internal function name.
- **L6** `delivery_receipts.record` never raises, so a failed insert returns 204 and Twilio never retries. **Accepted risk, not a defect** — `delivery_receipts.py:9-15` argues the trade. Named only because the sibling voice callback (`main.py:3657-3661`) chose the *opposite* trade for the same failure class, and neither call site says so.
- **L7** `storage.delete_object` swallows everything and returns False (`:283-286`), so orphaned objects accumulate silently.
- **L8** `promise_fulfillment.py:1073` writes an exception class name into a `provider_delivery_id` column — and on success `err` is None, so the real SID is never stored at all.
- **L9** Synchronised wake-ups: every queue is drained by one loop on a fixed 1.5s poll with no jitter. Harmless with one worker; with N replicas — the shape `SKIP LOCKED` anticipates — all N wake in lockstep and all N jitterless retry ladders re-fire together.
- **L10** `apiGet`/`apiSend` return `undefined as T` for a 204 **and** for a 200 with an empty body (`config.ts:177,182,208,210`), so `200 ""` is read as absence — e.g. `customers.$customerId.tsx:23-24` turns it into `throw notFound()`.
- **L11** `TurnTraceView.tsx:23,27,33,36` renders a failed trace load and an empty trace in the same `<Empty>` component, differing only in text — and the text is a raw `ApiError` string. Call-trace review is an evidence surface.

---

## The backend exception surface — re-measured

All figures below were re-derived by AST parse (`ast.ExceptHandler`), not regex, over 393 non-test files, and the scripts are reproducible. Where revision 1's number was scripted differently, both are shown.

| Metric | Rev 1 | **Rev 2** | |
|---|---|---|---|
| broad `except Exception`/`BaseException` | 656 | **657** | confirmed |
| bare `except:` | 0 | **0** | confirmed |
| total except handlers, all types | — | 1116 | |
| broad handlers that log something | 534 | **534** | exact match |
| broad handlers with **no log at all** | — | **123** | new |
| logged, but with **no identifying context** | 207 | **306–323** | **understated** |
| `.exception()` calls in broad handlers | 360 | **366** | confirmed |
| broad handlers on `.warning()`/`.error()` only | 65 | **65** | exact match |
| — of those, passing `exc_info=True` | 63 | **49** | corrected |
| — **losing the traceback outright** | 2 | **14** | **refuted** |
| "silently empty" catches | 16 | **39** | **refuted** (19 bare `pass`/`continue`/`return`, 20 `return <empty value>`) |
| broad handlers whose **only** log is `logger.debug` | — | **105** | **new — a fifth of all logged catches, invisible at production log level** |
| custom exception classes | 14 | **33** | **corrected** |
| production `assert` | ~30 | **30** | confirmed (db.py 15, not 17) |

The 105 debug-only handlers are the most consequential new number. Compliance-adjacent examples: `compliance_copy.py:72` ("tenant contacts unreadable"), `contact_policy.py:334` (promotional consent), `voice/tools.py:644` ("disclosure note injection failed"). These are not silent in the source — they are silent in production.

**No shared exception taxonomy.** 33 custom classes; base histogram `RuntimeError` 22, `Exception` 6, `ValueError` 3, `KeyError` 1, `FileNotFoundError` 1. **Zero inherit from a project-local exception**, so nothing can be caught by category. The consequence is concrete: `main.py` has **36** `except ValueError as exc` sites, of which 33 do `detail=str(exc)`, distributed 19×400 / 8×409 / 6×422 — the same exception type mapped to three statuses by call site. And `main.py:806-816` and `:843-854` wrap the **same call** (`payments.record_payment`) in the same two-arm handler, so whether a duplicate webhook is a **409 or a 404** is decided by which exception type the callee happened to reach.

*Corrected:* revision 1 called "not found" a four-idiom problem including 233 `ValueError` sites. Only **7** non-test ValueErrors encode not-found (the other ~225 are validation/conflict codes), and 171 of ~180 `raise KeyError` sites mean not-found — a coherent convention, not a competing idiom. The real landscape is `HTTPException(404)` (77), `KeyError` (171), bare-`None`, and those 7 misfiled ValueErrors, which is H22.

---

## The correlation spine

`request_context` is a correct, well-documented ContextVar read by the log formatter (`observability.py:385-399`). Its total reference surface in `backend/` is **`main.py` (the two middlewares) and `observability.py`** — nothing else, and nothing in `voice/`, `agent_core/`, `db.py` or any worker. `set_request_id`/`set_actor` are called only from HTTP middleware.

So the spine covers exactly the surface that already had correlation, and nothing binds an equivalent in the two surfaces that lack it. Measured by AST over the full call expression (a generous anchor regex — `session|call_id|call_sid|interaction|customer|tenant|conversation|sid`):

| Surface | log calls | carry an anchor | do not |
|---|---|---|---|
| `voice/` | 361 | 95 (26%) | **266 (74%)** |
| `agent_core/` | 205 | 40 (20%) | 165 (80%) |
| top-level `*.py` | 392 | 60 (15%) | 332 (85%) |

*Corrected:* revision 1 reported "23 of 361, 94% unattributable" from a same-line grep. The honest figure is 74%, and the true value sits between the strict 23 and the generous 95 — the regex matches the word "customer" anywhere in a call, message strings included.

The more useful reading is that top-level modules score *worst* (15%) but are largely fine, because HTTP requests carry the id through the formatter. The gap is not voice-specific; it is **process-specific**. Voice and the workers have no request, bind nothing, and are where the exemplar already lives:

> `voice/crm_sink.py:300-306` — `"crm_persistence_degraded · minimal interaction could NOT be filed · session=%s · this call is unrecorded"`

and where the anti-exemplar lives, in the same tree:

> `bot_worker.py:220` — `logger.exception("process_one crashed — backing off")`, for eleven different queues.

---

## What is done well

These are the templates the fixes should copy, and each survived adversarial reading.

- **`azure_speech.py:373-457`** — the retry the analyst could not fault. `Retry-After` honoured with positive jitter, full-jitter decorrelation otherwise, bounded attempts, a 10s per-sleep ceiling, status-based classification so 4xx is never retried, and a semaphore *and* breaker wrapping **each attempt**. `_SpeechRetryable` (`:398-408`) exists because httpx returns 429/5xx as ordinary responses, which made the breaker score every throttled attempt as a success.
- **`whatsapp.py` + `whatsapp_outbound.py`** — the only adapter in the repository that reasons about double-send, and it says why (`:294-302`: the Cloud API accepts no client idempotency key). `_classify_send_error` carries parsed fields only, because the raw Graph body echoes the recipient number and token fragments.
- **`circuit_breaker.py`** — generation-stamped half-open probes (`:57-59`, `:100-102`) and an aged-out probe slot (`:85-94`) close two real races.
- **`agent_core/providers/pool.py:86-101`** — `KEY_FAULT_STATUSES = {401,402,403,429}`, with the discrimination stated exactly: "A 400 means our payload is malformed, and every key in the pool will refuse it identically; treating that as a key fault would burn the whole pool to learn nothing."
- **`azure_openai.py:64-255`** — full chat/analysis isolation: separate deployments, clients, timeouts, semaphores, acquire timeouts, retry policies and breakers, with the motivating bug recorded (`:220-227`: analysis silently inherited a 20s timeout and burned 51s enriching a 1.8s reply). The semaphore is acquired *outside* the breaker so `AzureBusyError` is not scored as a dependency failure.
- **`pg_errors.py`** — SQLSTATE first, with the message fallback narrowed to `"duplicate key"` specifically because `"unique constraint"` also matches 42830. The comment says so.
- **`IntegrityError` → static `constraint_violation`** (`main.py:733-738`, `:3135-3137`) with `exc.orig` logged only — and **no site anywhere leaks raw constraint text**. This is the reference implementation the rest of `main.py` should copy.
- **`webhooks_dispatch.py`** — SSRF re-resolution at connect time, HMAC over `{timestamp}.{body}`, retry only on `server_err`, capped delay with a bounded exponent, per-endpoint policy, stuck-delivery reclaim, and the POST issued outside any transaction. Only defect is the missing jitter.
- **`POST /twilio/voice/call-status`** (`main.py:3598-3665`) — idempotent by rank-monotonic state machine, order-insensitive, silent 204 on unknown SIDs, and a deliberate 500 on DB failure to *earn* a Twilio retry. All three docstring properties are actually implemented.
- **`call_closer.process_one`** (`:1098-1150`) — claim, read and `closed_at` committed in a short transaction *before* the LLM call and any post-call action. A phase-three failure is absorbed by `_abandon` and leaves a visible gap rather than a replay. **This is the pattern K6 and H18 need.**
- **`bot_jobs.claim_next_job`** (`:186-290`) — two-step CTE plus `pg_try_advisory_xact_lock` with a bounded skip-list, and comments describing the two real bugs it fixed.
- **Frontend: no optimistic UI anywhere.** Every `setQueryData` applies a server response, not a guess — and `integrations.tsx:60-63` records that local overrides were *removed* for exactly this reason. Nothing needs rollback because nothing is written ahead of the server.
- **Frontend: the fetch layer's timeout composition** (`config.ts:61-74`) — `AbortSignal.any` composes the caller's signal with the timeout, with a note recording that the earlier `init?.signal ?? withTimeout()` dropped the timeout whenever a caller passed a token.
- **`ContactabilityPill.tsx:104-125`** — the fail-closed exemplar: treats `isError` **and** "settled with no data" as unknown and returns "Cannot confirm — treat as do-not-contact". `contact-policy.ts:1-11` refuses to recompute the verdict client-side.
- **`OutboundControlPanel.tsx:20-33`** — "Never render an unknown state as off", `readFailed = switches.isError`, both controls confirm, all three handlers map through `friendlyOutboundError`. The best-handled surface in the app (H27 is about its *colour*, not its logic).
- **`compliance.ts:63-79`** — the only compensating write in the frontend: when the note fails after a status update it attempts a revert and, if that also fails, says exactly what state the user is in.
- **The root error boundary** (`__root.tsx:41-88`) — user-safe copy, no stack, correlation id shown and reported, sidebar preference reset so a bad render cannot brick every refresh.
- **Mutations default to `retry: 0`** (`router.tsx:13-15`), and **nothing overrides it** — all 8 `retry:` code sites are inside `useQuery`. No double-POST anywhere.

---

## The frontend: failure is indistinguishable from emptiness

| Metric | Rev 1 | **Rev 2** |
|---|---|---|
| `query.data ?? []` sites | 68 / 20 files | **67 / 19 files** |
| destructured `const { data: x = [] }` | 41 / 24 files | **43 / 21 files** (incl. the bare `{ data = [] }` variant at `ApprovalsQueue.tsx:7`) |
| — of those, that also read `isError` | 3 | **4** |
| `<QueryState>` usages | 2, one file | **2, one file** |
| `scripts/check-query-state.mjs` | absent | **absent** — while `check-spacing-scale.mjs` and `check-type-scale.mjs` both exist |
| mutation call sites | 118 | **118 / 35 files** |
| files with mutations and zero `onError` | 12 | **12** |
| — of those, also zero `catch` | 3 | **3** — `HandoffQueue`, `EvalCockpit`, `OutboundTab` |
| error boundaries | 1 | **1** (root only) |
| seed modules | 25 | **28 files** (24 `*-seed.ts`) |
| — that simulate a network or 5xx failure | 0 | **0** |

*Corrected:* the "zero `onError`" figure overstates the problem. Nine of those twelve files handle errors via `.catch(err => toast.error(...))`; `OutboundControlPanel.tsx` is the best-handled file in the repo. `McpConsole.tsx` is the genuine exception (H10).

The last row still explains the rest. `USE_MOCK` defaults true in dev (`config.ts:22`) and of 24 seed modules only two throw, both business-rule validations. Two seeds emit failure-shaped *data* (`integrations-seed.ts:531`, `webhooks-seed.ts:343-356`) without ever rejecting a promise. **Every `isError` branch, every `QueryState` error branch and every `onError` toast in the application is unexecuted code under the default development configuration.** No developer has ever seen this app fail, which is a complete explanation for the other frontend findings.

**And no operator can see a breaker.** Grep across all of `Habibi/src` for `circuit`, `circuitBreaker`, `/ready`, `healthz` returns **zero matches**. The five breakers' state and failure counts are computed, exported to Prometheus, and shown to nobody in this product. When a breaker opens on a regulated channel the operator's only signal is that things feel slow — and the one screen that reports a dial refusal paints the outage the same colour as a policy refusal (H27).

### The single structural gap

`query-state.tsx:6-24` already diagnoses this failure mode by name and cites two shipped instances of it; `:48-63` already renders the correct three-way answer; `scripts/` already holds two `check-*.mjs` conventions. A `check-query-state.mjs` flagging `data ?? []` / `{ data: x = [] }` in any file that never reads `isError` would catch all 110 sites mechanically — **including `ApprovalsQueue.tsx:7`, which no human reviewer found because its failure mode is rendering nothing at all.**

---

## Remediation

Ordered by risk-adjusted value. ◆ marks an existing plan item that gains evidence here rather than new scope.

### Immediate — safety, small, independently shippable

| # | Change | Files | Size |
|---|---|---|---|
| 1 | **`admit`/`evaluate` fail closed for every purpose.** Delete the `if purpose == "outreach"` discrimination in both exception paths. | `contact_policy.py:1020-1024`, `:596-600` | 4 lines |
| 2 | **Stop coalescing from disabling the frequency rules.** Move cooling-off and the cap reservation outside the `counts` branch — *or* stop passing `customer_id` as `session_key` on the two dial endpoints. Do one, not both. | `contact_policy.py:971-981` **or** `main.py:3782`, `:4102` | 2–8 lines |
| 3 | **`sent = True` moves inside the `configured()` guard.** | `payment_events.py:668-675` | 1 line |
| 4 | **Key payment idempotency on `provider_ref`**, copying the unique-index + SQLSTATE pattern already used for inbound WhatsApp. | `payments.py:147-148`, `db.py:10673-10688` as template, new migration | ~20 lines |
| 5 | **`cure_for_account` gets a savepoint, and `record_payment` returns its real outcome.** | `payments.py:219-239` | ~8 lines |
| 6 | **The three tool handlers return the write's outcome**, with a say-string that does not promise silence. | `bot_tools.py:520-556`, `agent_core/tools/domain.py:767-774` | ~14 lines |
| 7 | **Guard every queue in `process_one_any`**, and give `followthrough.advance` the savepoint its sibling has. Log the queue name and row id on failure. | `bot_worker.py:93-145`, `followthrough.py:424-451,497-504` | ~25 lines |
| 8 | **One catch-all exception handler**, restoring CORS headers and `X-Request-Id` on true 500s. | `main.py`, beside `:693-715` | ~12 lines |
| 9 | **WhatsApp webhook returns 500 when every item errored.** Safe because ingest is idempotent on `provider_ref`. | `db.py:10974`, `main.py:4618` | ~6 lines |
| 10 | **Static details on the six leaking routes**, logging the real error — the convention already used at `main.py:4399-4403`. Covers MinIO, Azure Speech, provider TTS, `FileNotFoundError`, `/ready`, and `voice_sandbox`. | `main.py:777,2990,3039,3298,4397,4460,4482` | ~20 lines |
| 11 | **Log the degrade in `_actor_user_id`.** | `db.py:419-430` | 1 line |
| 12 | **Twilio gets a circuit breaker**, matching the five adapters that have one. | `voice/twilio_ops.py`, `twilio_sms.py` | ~12 lines |

Items 1, 3, 5, 6, 7, 9 and 11 change behaviour in the safe direction under failure only, and need no shadow period. Item 2 needs one release of conflict logging before enforcement. Item 4 is a migration and belongs with a reconciliation query for intents already double-paid.

### Near-term — the seams

- **A typed error vocabulary for Twilio voice, Twilio SMS and the LLM gateway**, copying `whatsapp.py:201-244`. This is the single highest-leverage structural fix: it is what lets K4, H20, M1 and operator messaging all stop guessing. Give the voice path an `ambiguous_transport` bucket and a `parked` state, as `whatsapp_outbound.py:305-324` already has.
- **Idempotency on the dial endpoints** (K2) — thread the existing `Idempotency-Key` path, and add a partial unique index on `(customer_id, objective)` for non-terminal states as the durable guard. Land the key first, log conflicts for one release, then enforce.
- **`claim_next_job` refuses rows with `post_attempted_at IS NOT NULL`** (K5), or classify `whatsapp_send_failed:internal:*` after a post attempt as ambiguous.
- **Split the treatment executor's claim from its side effect** (K6), copying `call_closer.process_one`'s three-phase shape and `_dial_bot`'s own docstring.
- ◆ **`RecordsTable` and `FilterTable` gain an error prop**, then `QueryState` behind a `scripts/check-query-state.mjs` ratchet. Plan item **B6**; this audit adds that the *table components* must change first, or the 110 sites cannot be fixed, and that `FilterTable` needs `isLoading` too.
- **Fix the four compliance-surface reads by hand first** — `consent.tsx:46`, `compliance.tsx:57`, `ApprovalsQueue.tsx:7`, `LedgerTab`/`EmiTab` — ahead of the ratchet. These are the ones where "empty" is a factual claim about a borrower.
- **Delete `fetchCustomerInsights`'s catch** so the failure reaches react-query.
- **Simulate failure in the seed layer.** Until one seed module rejects, every error branch in the frontend is unexecuted code. This is cheap, and it is the *cause* of the other frontend findings.
- ◆ **G-OB10 validates `retry_on`/`stop_on`**, and `main.py:5170` stops offering `rejected`. Plan item **S2c**.
- **Move the three carrier calls out of open transactions** (H17), starting with `promise_fulfillment`, which holds a row lock across a 10s timeout.
- **Route policy denials away from the retry ladder** (H19) — a denial is a schedule, not a failure.
- **Surface breaker state and per-target campaign state to operators** (H15, H27, H28). The data is already computed and exported.

### Structural — sequence behind the existing plan

- **A shared exception base with an HTTP mapping**, collapsing 36 hand-written translations to one handler and fixing H22 as a side effect. This belongs with **B4**'s router split — moving 312 routes and changing their error contract in one pass is not reviewable.
- **A correlation ContextVar bound per voice session and per worker job**, so 361 voice and 392 top-level log calls become attributable without editing them. This pairs with **C1**, which already requires running `bot()` inside `tenant_context.bind(...)` — same seam, same commit.
- ◆ **Read `session.extra["providers"]`** — and fix N6 first, so the field is revised at *use* rather than stamped at bind, or the strip will display a false provenance on the one call that matters.
- **Add SQLSTATE handling for 40001/40P01** in `pg_errors.py` and a bounded retry at the two seams that need it.
- **`responses={...}` per router during B4**, not as a 312-route sweep.
- **Replace the `assert`/re-`SELECT` idiom** with a raised domain error, starting with `payment_events.py:402`.

---

## Corrections carried forward

Recorded because a wrong entry in an audit outlives the audit. Twenty-three of revision 1's claims changed.

**Mechanism was wrong**

| Rev 1 claim | Correction |
|---|---|
| C2: the WhatsApp gate fails open when **Postgres is unreachable**, at `bot_runtime.py:158` | **Refuted as stated.** `_whatsapp_opted_in` opens its own connection *above* the `try` (`bot_runtime.py:96`), so a total outage propagates and fails closed. The real fail-open is inside `admit` itself (K3), on more paths, and `bot_runtime.py:158`'s handler is unreachable because `admit` swallows first. |
| M3: **90 Azure calls** per customer message, ~25 min to dead-letter | **~15 calls** (3 SDK × 5 job). The tool loop at `bot_runtime.py:954` iterates on tool calls, not on failure — an exception propagates straight out. The ~25 min belongs to the *reclaim* path (300s × 5), i.e. a worker crash, not an exception; the exception path is ~5–6 min. The customer-receives-nothing finding stands and is the worst part. |
| H6: `outbound.place` is called **unguarded** and **nothing reclaims `dialing`** | **Three of four parts refuted.** `place` implements its never-raises contract (guarded at `:597,615,650,735,756`). `campaigns.py:611-626` *does* reset to `pending` on `placed:False`. `outbound.sweep_stale` → `call_closer.claim_one` → `campaigns.on_attempt_closed` *does* reclaim. **What survives:** the release is to `done`, never `pending`, so the borrower is still never re-dialled — and the run reads *complete* (H28). |
| M9: Twilio ambiguity causes **under-retry rather than double-dial** | **Both.** Under-retry on the cadence driver; **double-dial on the campaign driver** (K4). |
| "Not found" has **four competing idioms** including 233 `ValueError` sites | Only **7** non-test ValueErrors encode not-found; the other ~225 are validation/conflict codes. `KeyError` (171 of ~180) is a coherent convention. The real defect is narrower and sharper: those 7 can never return 404 (H22). |

**Counts were wrong**

| Metric | Rev 1 | Rev 2 |
|---|---|---|
| logged catches with no identifying context | 207 | **306–323** |
| catches losing the traceback outright | 2 | **14** |
| "silently empty" catches | 16 | **39** |
| custom exception classes | 14 | **33** |
| `db.py` production asserts | 17 | **15** |
| voice log calls carrying an anchor | 23 of 361 (6%) | **95 of 361 (26%)**; 74% unanchored, not 94% |
| `RecordsTable` consumers | 22 files | **19 files, 24 sites** |
| destructured `{ data: x = [] }` | 41 / 24 files, 3 read `isError` | **43 / 21 files, 4 read `isError`** |
| `query.data ?? []` | 68 / 20 files | **67 / 19 files** |
| seed modules | 25 | **28 files** (24 seeds) |
| routes | 314 | **312 HTTP + 2 WebSocket** |

**Line references corrected**

`_handle_write` is `main.py:720` (1540–1611 is the endpoint block that threads the header) · `outbound.py`'s catch-all is `:743-751`, not 735–742 (735–742 is the `OutboundDisabled` branch, which correctly resolves to `suppressed`) · the `rejected`-retires-a-number comment is `outbound.py:111-115`, not 52–54 · `azure_speech`'s retry loop ends at `:457` · `bot_tools` decline is `:544-556` · `gate-status.ts` documents its two bugs at `:9-12` and `:13-14` · the outbound gates are G-OB1..G-OB8 plus G-OB9 appended at `compile.py:453-465` · `db.py:8592-8605`, `:4457-4502`, `:4254`, `:10974`.

**Confirmed exactly, and worth saying so**

0 of 312 routes declare `responses={...}`; 136 declare `response_model` · 534 of 657 broad handlers log · 65 `.warning()`/`.error()`-only handlers · zero bare `except:` · 118 mutation call sites in 35 files · 2 `QueryState` usages in 1 file · `scripts/check-query-state.mjs` still absent · 0 seed modules simulate a failure · 1 error boundary · `USE_MOCK` dev default and prod build error · the 401/403 signature split across all 8 sites · `IntegrityError` handling correct at both sites, with no raw-constraint leak anywhere.

**Severity disagreements between analysts, resolved**

- `/ready` disclosure: rated Low by the integration analyst (not rendered) and Critical by the API analyst (unauthenticated). **Recorded as High (H25)** — a real disclosure on an unauthenticated endpoint, but not a borrower-harm path.
- `provider_error` leaking a Twilio Account SID: rated High, then **downgraded to Medium** by the same analyst after the frontend sweep found `Habibi/src/api/outbound.ts:43-44` is dead code with no importer. Exposed on the API to any key holder; never rendered.
- `payments.record_payment`: the retry analyst marked it **PROTECTED** (it does short-circuit replays, correctly) and the integration analyst marked it **broken** (it keys on intent status, so a genuine second payment is swallowed). Both are true; recorded as K8 with that nuance, because the protection is real and the key is wrong.

**Also corrected**

`ApiError.isNotFound()` is a standalone exported function (`config.ts:145-147`), not a method · `-O`/`PYTHONOPTIMIZE` is used nowhere, so the assert-stripping risk is hypothetical · the "12 files with zero `onError`" figure overstates the problem, since 9 of them use `.catch(toast.error)` · `fetchCustomerInsights` is not fully silent — it marks `nba` but not `summary`/`metrics` · `CompileError.report.model_dump()` is **SAFE** (no paths or DSNs; it serialises the author's own card) but is destroyed in transit (M16).

**Still open from revision 1's own correction list, unchanged:** `idempotency_keys` is present and correct at `sql/12_crosscutting.sql:44-52` · the system *does* have retry classification, in two places, and the defect is that voice and Azure OpenAI lack it · `[object Object]` does not happen · a 403 does not log the operator out · unhandled 500s do not leak tracebacks (FastAPI is built without `debug=True`; the gap is headers only).

**One item not verified:** whether `features.py`'s `consentByChannel` snapshot reaches a `treatment_decisions` column. It was traced to the serialisation at `:375` but not to the INSERT, so H3's audit-record impact is inferred from that serialisation rather than confirmed at the write site.

---

## What this means for the plan

Nothing here reorders the existing waves, but two things changed.

**The Critical count moved from 3 to 10, and the reason is the finding.** Revision 1 found the right seams by inspection and guessed the mechanisms; seven of ten Criticals only became visible when someone opened the file and followed the call. That is an argument about method, not about this codebase: **an audit that stops at the seam will systematically under-report, because the seam is where the *primitive* lives and the defect is one layer inside it.**

**S9's argument generalises further than revision 1 said.** The tool-audit redaction fix worked because it moved the control to `record_tool_call` — the one function every channel already goes through. Family A is five instances of the same shape: duplicate-contact prevention living at five call sites instead of the one seam they share (`admit`, which every path already calls, and which is currently the thing that fails open). Family B is four instances of a second shape: a write's outcome discarded at the boundary that reports it. Both argue for the plan's core bet — enforce once at a shared seam — and both now name the seam.

The one genuinely new observation for sequencing: **four of the five highest-value fixes are under ten lines**, and none needs a shadow period, because each changes behaviour only on a path that is already wrong. They do not need to wait for B4, C1 or the router split. They should ship first, precisely because everything structural in this report will take a quarter and the frequency ledger is wrong today.
