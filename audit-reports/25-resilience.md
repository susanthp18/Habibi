# 25 — Resilience under partial failure

**Role:** Distributed systems resilience architect.  
**Scope:** Reliability of `backend/` and `Habibi/src` when a dependency is slow, down, or lies. Guest tree `PRAXIST-main/` is out of scope.  
**Date:** 2026-09-02  
**Mode:** Read-only. No source, config, git, or dependency changes. No live load was applied; claims are from code, workers, SQL, and existing tests.  
**Companions:** [14-error-handling.md](./14-error-handling.md) (K1–K10), [15-concurrency.md](./15-concurrency.md), [16-performance.md](./16-performance.md), [23-e2e-workflows.md](./23-e2e-workflows.md).  
**Vocabulary:** `CONTEXT.md`. Terms in **bold** are that glossary.

**Method:** five parallel lenses — retry, timeout, idempotency, external provider, transaction — then every headline claim re-read from source in this document. K1–K10 from report 14 were re-checked against current line ranges; each still holds. This report does not re-litigate their mechanisms. It asks a different question: *when a hop fails halfway, does the next hop retry, hang, or lie?*

---

## Verdict

**The adapters that were built as adapters are resilient. The paths that bypass them are not.**

Azure Speech REST (`azure_speech.py:373-457`) is the local gold standard: bounded retries, `Retry-After` + jitter, a circuit breaker that actually counts 429/5xx, a semaphore that sheds. WhatsApp outbound is the only send path that *reasons* about double-send (`whatsapp.py:201-244`, `whatsapp_outbound.py:293-328`). Postgres queues reclaim with `SKIP LOCKED` and attempt caps. The CRM client times out at 30s and does not retry mutations.

What fails under partial failure is the *join* between those primitives and the live contact paths:

1. **The live Mouth does not use them.** Voice LLM, STT and TTS go through Pipecat SDKs and `voice/llm_pool.py`. They share neither the Azure OpenAI breaker nor the Speech REST retry loop. A region outage is three SDK retries at 30s each, on every concurrent call, with no shed.
2. **Timeouts are missing where a hung TCP holds a worker.** MinIO, Redis mesh, and Postgres connect have no client-side deadline. Uvicorn has no request timeout. A stuck syscall is not a failed job — it is a slot that never comes back until the process is killed, and reclaim only fires after 180–900s of stale `locked_at`.
3. **Retry policy is per-file, not per-operation class.** Campaigns re-queue *any* `placed: false` in five minutes (K4). Cadence *refuses* to retry `failed`. WhatsApp Graph 5xx is dead-lettered (correct). The same class of error on the LLM gateway is retried three times with **zero backoff**, then swallowed into Azure (spend cap included).
4. **The outbox exists. SMS and the mandate rail do not use it.** Treatment WhatsApp enqueues. Treatment SMS calls Twilio inside the claim transaction. A rollback after a successful send is a second SMS (K6, SMS path). Voice splits the reserve, then still marks-enacted on the outer txn, so a crash after the ring still reclaims the plan.

This is not a missing circuit-breaker library. One already exists, it already closes two races, and five named breakers use it. The gap is that Twilio, the voice LLM pool, the LLM gateway, Fish/Cartesia/Deepgram, and Redis never enter it — and the connector breaker in Postgres is a *different* machine with no half-open probe.

---

## 1. How to read this report

Every dependency is scored on the same four controls:

| Control | Meaning |
|---------|---------|
| **Timeout** | Connect / read / total deadline on the client. Missing = hang until TCP or process death. |
| **Retry** | Bounded attempts, backoff, jitter, 4xx vs 5xx vs ambiguous. |
| **Breaker** | Fail-fast when the dependency is hard-down. Process-local vs shared. |
| **Idempotency** | Safe to retry the *operation* (not merely the HTTP GET). |

**Risk** is 1–10, also labelled P0–P3:

| Band | Score | Meaning |
|------|-------|---------|
| **P0** | 9–10 | Partial failure contacts a borrower twice, or the system of record lies about money / consent / contact. |
| **P1** | 7–8 | Hang, retry storm, or fallback that hides the failure the operator must see. |
| **P2** | 5–6 | Missing timeout/breaker on a non-contact path; bind-time-only failover. |
| **P3** | 3–4 | Two implementations of the same idea; cosmetic timeout drift. |

Observed vs inference is marked. Line numbers are current as of this date.

---

## 2. Dependency inventory

| Dependency | Client | Timeout | Retry | Breaker | Idempotent to retry? | Used by |
|------------|--------|---------|-------|---------|----------------------|---------|
| Postgres | SQLAlchemy + psycopg | **statement 15s API / 60s workers.** No `connect_timeout`. `pool_timeout` default **30s** (not set). | `pool_pre_ping` only | none | SQL txn | everything |
| Azure OpenAI (text) | OpenAI SDK via `_azure_call` | **20s** (`AZURE_OPENAI_TIMEOUT_S`); analysis **8s** | SDK `max_retries=2`; analysis **0** | `azure_openai` / `azure_openai_analysis` | yes (completion) | WhatsApp turns, KB embed, CRM |
| Azure OpenAI (voice) | `AsyncAzureOpenAI` in `llm_pool.py` | **30s** total, connect **10s** | SDK `max_retries=2` | **none** | yes | live Mouth |
| LLM gateway / LiteLLM | `httpx.post` per attempt | **20s** (or caller) | **3 attempts, no sleep**, 5xx only | **none** | yes | optional; kill-switch to Azure |
| Azure Speech REST | httpx | client 45s/connect 10s; TTS POST **30s**; STT **45s** | **2** + jitter + `Retry-After` | `azure_speech` | yes | studio preview, transcribe |
| Azure Speech live | Pipecat Speech SDK websocket | TTS pre-open **5s**; otherwise SDK | **none** at app layer | **none** | n/a (stream) | live Mouth |
| Meta WhatsApp | `urllib` 30s | **30s** (not split) | **1** HTTP; queue classifies | `whatsapp_meta` | **no** (Cloud API has no client key) | inbox + treatment WA |
| Twilio Voice REST | `TwilioHttpClient(10)` | **10s** | **1** | **none** | **no** | `outbound.place` |
| Twilio SMS | `TwilioHttpClient(10)` | **10s** | **1** | **none** | **no** | bounce, treatment SMS, PTP reminder |
| MinIO | `Minio(...)` | **none** | **1** | `minio` (ignores `ValueError`) | overwrite same key | KB originals |
| Redis mesh | `Redis.from_url` | **none** | n/a | **none** | n/a | Floor pub/sub only |
| MCP connectors | httpx | **`timeoutMs` default 2500** | **1**; breaker in DB | **DB** `OPEN_AFTER=3`, cooldown **30s**, **no probe** | per tool | Mouth ext tools |
| Tenant webhooks | httpx | **10s** | 5xx up to **3**, backoff `min(120, 2^n)` | **none** | delivery id header | `webhooks_dispatch` |
| Fish / OpenRouter TTS | httpx | **90s** | key-pool rotate on 401/402/403/429 | **none** | synthesis yes | bind-time / preview |
| CRM UI → API | `fetch` + `AbortSignal` | **30s** (blob 60s, upload 120s); SSE **none** | queries **1** global / some **2**; mutations **0** | n/a | only if `Idempotency-Key` sent | operator console |

Five named in-process breakers: `azure_openai`, `azure_openai_analysis`, `azure_speech`, `whatsapp_meta`, `minio`. Threshold **5**, reset **60s**, half-open **one probe** with generation stamp (`circuit_breaker.py:56-99`). They are **per process**. `UVICORN_WORKERS=1` plus `bot_worker` plus `voice` means three independent counters for the same Azure.

---

## 3. Findings

### R1 — P0 / 10 — Campaign treats every failed dial as “did not happen”

`outbound.place` maps any Twilio exception to `placed: false` / `dial_failed` (`outbound.py:743-751`). `campaigns.process_one` then sets the target back to `pending` with `next_attempt_at = now() + 5 minutes` (`campaigns.py:611-625`). There is no classification of “the REST call timed out after Twilio accepted the create.”

Cadence, on the same `failed` state, **stops** (`cadence.py:224-228`). Two schedulers, two answers to one carrier ambiguity. Report 14 K4. Still current.

A 10s Twilio HTTP timeout (`twilio_ops.py:265`) is exactly the window in which this happens.

### R2 — P0 / 10 — WhatsApp: send succeeded, persist failed, job retries

The classifier is correct: ambiguous transport is dead-lettered (`whatsapp_outbound.py:307-328`). The hole is *after* Meta accepted the message. Persist of `delivery_status='sent'` (`:548-564`) raises → `process_one` catch (`:582-585`) feeds `_persistable_error` → `whatsapp_send_failed:internal:OperationalError`. Neither `is_ambiguous_transport_error` nor `is_definite_client_error` parses `internal` as a status (`whatsapp.py:216-221`). The job is requeued. The message row is still `sending`. The next claim POSTs again.

`post_attempted_at` is set *before* the POST (`:488-499`) and `reclaim_stuck_jobs` dead-letters running jobs that already posted (`:183-198`). The crash/reclaim path is disciplined. The in-process exception path is not. Report 14 K5.

**Contrast (observed, same product):** `bot_runtime.handle_turn` refuses to re-POST a stuck `sending` row (`bot_runtime.py:614-627`). The Mouth’s WhatsApp turn already has the correct answer. The outbound worker does not use it.

### R3 — P0 / 9 — Side effect inside the claim transaction (K6, refined)

`treatment.process_one` is one `engine.begin()` around `claim_due` + `enact_one` (`enact.py:904-912`). Handlers are not equal:

| Handler | Carrier I/O | On rollback after success |
|---------|-------------|---------------------------|
| WhatsApp | enqueue only (outbox) | safe retry |
| **SMS** | `twilio_sms.send` on `conn` (`enact.py:307-313`) | **second SMS** |
| Voice | reserve on **own** txn (`:338-384`), then `place`, then `mark_enacted` on outer | **second dial** if claim rolls back |
| Mandate rail | `_submit_to_rail` **before** INSERT (`:589-597`) | **second presentment** |

The inner voice reserve is a real improvement since the first reading of K6. It does not close the hole: a crash after `place` and before outer commit leaves `enacted=false`, `sweep_stale` reaps the attempt, and `claim_due` hands the same plan to `_dial_bot` again.

The same SMS-in-txn shape exists on PTP reminders (`promise_fulfillment.py:1014-1019` inside `process_one_reminder` `:1044-1077`) and bounce first-touch (`payment_events.py:668-675` inside ingest).

### R4 — P0 / 9 — Money: false idempotent and swallowed cure (K8, K9)

`record_payment` returns `{"ok": true, "idempotent": true}` when the intent is already `paid` (`payments.py:149-150`) without looking at `provider_ref`. A second real settlement against the same intent is discarded. Inbound WhatsApp already keys uniqueness on `provider_ref` (`db.py:10674-10688`).

Bounce cure is `try/except` with no SAVEPOINT (`payments.py:218-239`). The payment commits. EMI rows may be half-written. The API still says ok.

### R5 — P0 / 9 — Bounce stamps `sent` when SMS was never configured (K7)

```664:675:backend/payment_events.py
            if twilio_sms.configured():
                twilio_sms.send(...)
            sent = True
```

`sent = True` is outside the guard. Downstream stamps `first_touch_at` from `sent`. Combined with R3 (SMS inside the ingest txn), a webhook retry after rollback can also double-SMS when Twilio *is* configured.

### R6 — P0 / 9 — Dial endpoints have no idempotency key (K2) and turn cooling-off off (K1)

`POST /demo/outbound-call` and `POST /twilio/voice/outbound` call `reserve` (plain INSERT, `outbound.py:370-405`) with `session_key=customer_id`. Coalescing then skips cooling-off and both frequency caps (`contact_policy.py:965-981`). No `Idempotency-Key`, no `ON CONFLICT`, no non-terminal-state check. A retried POST is a second ring, and the ledger under-counts it.

Frontend `useDemoOutboundCall` sends neither a key nor a mutation retry — double-click is two POSTs.

### R7 — P1 / 8 — LLM gateway: retry storm, then a kill-switch that bypasses the spend cap

```112:131:backend/llm_gateway/client.py
    retries = 2
    for attempt in range(retries + 1):
        ...
            if resp.status_code >= 500 and attempt < retries:
                continue   # no sleep
        except Exception as exc:
            ...
```

Three immediate POSTs on 5xx. 4xx (including 429) hits `raise_for_status` and is retried on the exception path — also with no sleep and no `Retry-After`. Then:

```618:634:backend/azure_openai.py
        routed = maybe_chat(...)
        if routed is not None:
            return routed
    except Exception:
        logger.exception("llm gateway routing failed; Azure kill-switch")
```

Bare `except Exception` swallows `llm_gateway_spend_cap` (`llm_gateway/client.py:55-56`) and every transport failure, and falls through to Azure. Worst case on a live WhatsApp turn: 3 × 20s gateway + Azure `max_retries=2` × 20s. The operator sees a slow bot. Finance sees two providers billed. The cap did not cap.

Voice never enters this path. It uses `llm_pool.py` directly.

### R8 — P1 / 8 — Live Mouth bypasses every in-process breaker

| Live slot | Client | Breaker |
|-----------|--------|---------|
| LLM | `voice/llm_pool.py:42-48` `AsyncAzureOpenAI` | none |
| STT | Pipecat `AzureSTTService` (`voice/bot.py:642`) | none |
| TTS | `KeepAliveAzureTTSService` (`tts_pool.py`) | none |
| Twilio | `twilio_ops._client` | none |

`azure_openai.prewarm()` also calls the SDK without `_azure_call` (`azure_openai.py:347-363`).

Bind-time failover exists (`provider_bind.py:40-97`, `factory.build_first_available:250-298`): unbound → Azure default; bound-but-broken → Azure + ERROR. That walk happens **once, at pipeline start**. Mid-call Fish `ErrorFrame` is silence (`fish_service.py`), not a switch. Key-pool rotation on 429 (`agent_core/providers/pool.py:85-86, 359-399`) is bind/preview, not a live utterance.

### R9 — P1 / 8 — Hung TCP has no deadline on MinIO, Redis, or Postgres connect

- `storage.py:113-118` — `Minio(...)` with no timeout. Breaker `minio` only sees a *returned* failure. A hung GET holds the thread until OS TCP timeout. `/ready` pings MinIO (`main.py:760-778`); compose healthcheck timeout is **5s** (`docker-compose.yml:127-129`). A hung MinIO makes the API look dead to the orchestrator while uvicorn is merely blocked.
- `voice/mesh_bus.py:45` — `Redis.from_url` with no `socket_connect_timeout` / `socket_timeout`. Init failure falls back to `_LocalBus` (call continues). A hang *during* `from_url` is not that path.
- `db.py:138-149` — `connect_args` set `statement_timeout` and the tenant GUC. No libpq `connect_timeout`. `pool_timeout` is SQLAlchemy’s **30s** default. Report 15 F1: that wait can run on the event loop inside `_authz_guard`.

Uvicorn is started with no `--timeout-keep-alive` and no request-timeout middleware (`docker-compose.yml:103-113`). Sync `def` routes are bounded by statement_timeout per query, not by a request budget.

### R10 — P1 / 7 — Two circuit breakers, neither covers Twilio, one has no probe

**In-process** (`circuit_breaker.py`): half-open, one probe, generation stamp, hung-probe expiry. Process-local. Speech routes catch `CircuitOpenError` as `RuntimeError` → **502** (`main.py:3035-3040`), not the global **503** handler (`:712-717`). An open speech circuit looks like “Azure is broken,” not “we are shedding.”

**Postgres connectors** (`agent_core/connectors/circuit.py`): `OPEN_AFTER=3`, `COOLDOWN_S=30`. After 30s `allow()` returns True for **every** concurrent call — no half-open slot. Thundering herd into a down MCP. Fail-closed on unparseable `circuit_opened_at` (correct). Recovery is `health_test` → `record_success`.

Twilio Voice, Twilio SMS, LLM gateway, Fish, Redis, voice LLM: no breaker of either kind.

### R11 — P1 / 7 — Media-stream reconnect recovers CRM writes, not the conversation

Twilio reconnecting the Media Stream mints a **new** interaction (`voice/persist.py` INSERT). Voice tools now key PTP / dispute / callback / documents on `session.provider_call_id` (CallSid) so a reconnect does not double-write money (`voice/tools.py:1277-1297`, `tests/test_voice_write_idempotency.py`). That fix is real.

What reconnect does **not** restore: LLM context, flow node, idle-ladder strikes, in-flight TTS. The borrower hears a new Mouth. Usage meters a new turn. `finalize_stt` is idempotent per session (`voice/usage.py:147-152`); a new session is a new meter.

Cancellation is otherwise careful: `_claim_end` is single-flight (`voice/bot.py:903-921`); idle after hangup does not speak into a dead socket (`:923-934`); background drain is 2s then cancel (`:231-247`); CRM sink drain is **15s** (`crm_sink.py:385`); max call **600s** (`bot.py:160`); worker idle **180s** (`:162`); WS proxy `open_timeout=10`, `ping_timeout=20` (`ws_proxy.py:55-57`).

### R12 — P1 / 7 — Operator writes that look idempotent are not

Backend `idempotency_keys` + `pg_advisory_xact_lock` (`db.py:686-736`) is the correct primitive. CRM `POST /promises` does not send the header (`Habibi/src/api/promises.ts:50-63`). Wrap-up sends `wrap-${id}-${Date.now()}` (`handoff.ts:277`) — a new key on every retry, which is the opposite of the store. Mutations globally `retry: 0` (`router.tsx:13-16`), so the UI will not auto-retry; the operator’s second click will.

WhatsApp tools key on `{job_id}:create_promise_to_pay` (`bot_tools.py:265`). Job retry is safe. `decline_offer` still returns `ok: true` after a swallowed write (K10, `bot_tools.py:544-556`).

### R13 — P1 / 7 — Azure OpenAI main client: 20s × 3 can occupy a live turn

Main client `timeout=20`, `max_retries=2` (`azure_openai.py:314-315`). Comments at `:664-667` record the measured cost: a 1s caller budget with retries still burned **26s**. Analysis and per-request `timeout=` force `max_retries=0`. The WhatsApp turn and the voice pool do not.

Voice pool: 30s × 3 on the call path, no breaker (R8). Bot-turn jobs then wrap that in `BOT_JOB_MAX_ATTEMPTS` default **5** with backoff `min(300, 2^min(attempt,6))` (`bot_jobs.py:45, 351`). Persistent Azure 5xx: ~15 completions per conversation, then dead-letter + escalate. Bounded. Still a retry storm against a struggling deployment because N workers share no breaker.

### R14 — P2 / 6 — Webhook and KB workers are the right shape; they are the template

Outbox: claim (SKIP LOCKED) → HTTP **outside** txn → settle. Used by `whatsapp_outbound` (except K5), `webhooks_dispatch` (`:412-463`, timeout 10s, 4xx terminal), `kb_ingest` (embed outside txn, atomic chunk replace), `bot_runtime` outbound. SMS treatment, SMS reminder, bounce SMS, and mandate rail have not been migrated onto it.

KB jobs dead-letter on first process failure and only auto-retry via stale reclaim (`kb_ingest.py:469-504`) — no transport retry ladder. Correct for a poison document.

### R15 — P2 / 5 — Fallback chains that hide failure

| Chain | Hides from |
|-------|------------|
| Gateway exception → Azure | Spend cap, gateway outage |
| `provider_bind` Azure fallback | Studio: operator bound Cartesia, call ran Azure (provenance is on `session.extra["providers"]` if anyone reads it) |
| `prewarm` swallow | First-turn latency only |
| Campaign `pending` on any `placed: false` | Second dial looks like a new attempt |
| SMS `_record_sent` swallow (`twilio_sms.py:134-135`) | Receipt corpus |
| Insights `deriveCustomerInsights` on API error (report 23 J3) | Operator |

Hiding a failure is a resilience defect when the hidden path still contacts the borrower or books money.

---

## 4. Retry policy matrix

No `tenacity`, no `urllib3.Retry`, no `aiohttp`. Retries are handwritten.

| Site | Max | Backoff | Jitter | 4xx | Safe? |
|------|-----|---------|--------|-----|-------|
| Azure Speech REST | 3 | exp, cap 10s, `Retry-After` | **yes** | 408/429/5xx only | yes |
| Azure OpenAI SDK (main) | 3 | SDK default | SDK | SDK (429/5xx) | completion yes |
| Azure OpenAI analysis | 1 | none | — | no | yes |
| LLM gateway | 3 | **none** | **no** | 5xx intended; 4xx retried via except | completion yes; storm |
| Voice LLM pool | 3 | SDK | SDK | SDK | completion yes; no breaker |
| WhatsApp HTTP | 1 | — | — | classified at queue | n/a |
| WA outbound queue | 5 | `min(120, 2^min(n,12))` | **no** | definite → dead; ambiguous → **dead** | intended; K5 bypass |
| Bot turn jobs | 5 | `min(300, 2^min(n,6))` | **no** | until cap | CRM writes keyed; usage may double |
| Twilio Voice/SMS | 1 | — | — | no | **no** (caller must not retry) |
| Cadence | card `max_attempts` default 3 | `[4,24,72]` h | n/a | `failed` **not** retried | by design |
| Campaign | unbounded while run live | **+5 min** any miss | **no** | n/a | **K4** |
| Webhooks out | 3 | same exp as WA | **no** | **terminal** | delivery id |
| KB index | 5 via reclaim only | none on fail | — | n/a | atomic replace |
| Connector MCP | 1 | cooldown 30s then all-in | — | n/a | herd |
| Fish TTS | `len(keys)` | key cooldown 900s | **no** | 401/402/403/429 rotate | synthesis |
| React Query | 1 global / 2 on some GETs | RQ | — | 408/429 only | GET; mutations 0 |
| Worker `while not stop` | infinite | poll 1.5s / 2s | — | n/a | sleep present |

**Retry storm formula (voice Azure outage):** `VOICE_MAX_CONCURRENT_CALLS` (default 25) × 3 SDK attempts × 30s, **plus** every WhatsApp worker × 5 job attempts × 3 SDK × 20s, **plus** no shared breaker. Speech REST would have opened. Voice will not.

---

## 5. Timeout matrix — missing vs present

**Present and load-bearing**

| Bound | Value | Where |
|-------|-------|-------|
| API `statement_timeout` | 15s | `db.py:123-124` |
| Worker/voice `statement_timeout` | 60s | same, `DB_PROCESS_ROLE` |
| Twilio REST | 10s | `twilio_ops.py:265`, `twilio_sms.py:79` |
| WhatsApp Graph | 30s | `whatsapp.py:112,191` |
| Azure chat | 20s / analysis 8s | `azure_openai.py` |
| Voice LLM | 30s / connect 10s | `llm_pool.py:48` |
| Speech REST | 45/10 client; 30 TTS; 45 STT | `azure_speech.py` |
| Connector MCP | 2.5s default | `connectors/persist.py:359` |
| Tenant webhook | 10s | `webhooks_dispatch.py:87-91` |
| CRM fetch | 30s (`AbortSignal.any`) | `Habibi/src/api/config.ts:47-74` |
| Voice max duration | 600s | `voice/bot.py:160` |
| CRM sink drain | 15s | `crm_sink.py:385` |
| TTS pre-open | 5s | `tts_pool.py:40` |
| WS upstream | open 10s, ping 20s | `ws_proxy.py:55-57` |
| WA stale reclaim | 180s; post-attempt → dead | `whatsapp_outbound.py:34-38,183-198` |
| Bot job stale | 300s | `bot_jobs.py:50-54` |
| Outbound attempt stale | 30 min | `outbound.py:198-206` |
| Voice admission slot | 3600s | `voice/admission.py` |

**Missing (hang risk)**

1. MinIO socket/connect timeout.  
2. Redis `socket_timeout`.  
3. Postgres `connect_timeout`.  
4. Uvicorn / FastAPI request timeout.  
5. SSE `apiEventStream` (intentional; caller must abort).  
6. WS proxy client-leg read (unbounded except ping on the *upstream* leg).  
7. Fish TTS **90s** on a preview path that can run in the API process.

A live hung MinIO/Redis/PG-connect call does **not** update `locked_at`. Reclaim waits for the stale window while the thread is still inside the syscall. That is the difference between “retry after 180s” and “worker permanently down one slot.”

---

## 6. Transactions that span side effects

| Flow | Open txn holds | Side effect | Pattern |
|------|----------------|-------------|---------|
| Treatment WhatsApp | claim + enqueue | none until worker | **outbox** |
| Treatment SMS | claim | Twilio HTTP | **unsafe** |
| Treatment voice | claim (lock) during `place` | Twilio after inner reserve commit | **split, still reclaim-unsafe** |
| Treatment mandate rail | claim | rail HTTP then INSERT | **unsafe** |
| Campaign | txn1 commit then `place` | Twilio | **better**; K4 on result |
| WA outbound | POST outside txn | Meta | **outbox**; K5 on persist |
| Bot turn | POST outside txn | Meta | **outbox + no re-POST if sending** |
| Bounce ingest | account `FOR UPDATE` | SMS HTTP | **unsafe** (R3+R5) |
| Bounce WA | enqueue | worker | **outbox** |
| PTP reminder SMS | reminder `FOR UPDATE` | SMS HTTP | **unsafe** |
| `record_payment` | intent `FOR UPDATE` | DB + webhook enqueue | **outbox for HTTP**; K8/K9 inside DB |
| KB ingest | none during embed | Azure then atomic replace | **correct** |
| Tenant webhooks | none during POST | HTTP then settle | **outbox** |

There is no saga. Compensation is `sweep_stale`, dead-letter, and an operator. That is acceptable for WhatsApp (reconciliation queue). It is not acceptable for a second PSTN ring.

---

## 7. Voice / AI workflows

### Duplicate call initiation

Five independent vectors (all still live): K1 coalescing, K2 no dial key, K4 campaign requeue, K6 reclaim after ring, operator double-click. Cadence is the one scheduler that *under*-retries (`failed` stops the ladder).

### Duplicate audio / writes

REST TTS/STT retries are idempotent and metered once (`azure_speech.py:519-521, 587-592`). Live reconnect: CRM writes CallSid-scoped (fixed). LLM/TTS usage is per new session (double-meter on reconnect, not double-contact). Bot-turn job retry can double-meter Azure; CRM tools keyed on `job_id` do not double-write.

### Provider switching

Bind-time chain is a failover list (`factory.py:16-19, 250-298`). Runtime is not. Unbound tenants fall back to Azure so deploying the registry is not an outage (`provider_bind.py:13-20`). Provenance is recorded; the Floor UI must read `session.extra["providers"]` or the screen still lies.

### Stream interruption

TTS `Connection.open` during synthesis deadlocks (~41s observed; `tts_pool.py:8-14`). Mitigated by opening **once** at `start()`, bounded by 5s. Barge-in is a tuning flag. Warm transfer tears the Media Stream (`twilio_ops.py:403-404`). Proxy logs frame counts so silence is attributable (`ws_proxy.py:63-69`).

### Session recovery

CallSid is now written onto `voice_sessions.provider_call_id` (`voice/bot.py:1898-1909`). Interaction row is still a new INSERT on reconnect. Pipeline state is not snapshotted. Recovery = new Mouth + idempotent CRM tools.

### Timeout / cancellation

Hard cap 10 minutes, spoken sign-off (`bot.py:1735-1759`). Idle ladder + dead-air watchdog share `_claim_end` and a re-fire guard. Finalize bookkeeping 20s (`:170`). Analysis stop 3s (`crm_sink.py:406`). These are real deadlines. They do not substitute for a breaker on the LLM websocket.

---

## 8. What already works

Do not “add resilience” by wrapping these again.

- **Azure Speech REST** — retry, jitter, `Retry-After`, breaker that counts HTTP 429, semaphore, express-as fallback documented.  
- **`circuit_breaker.py`** — probe generation, hung-probe expiry, ignore_exceptions release. Tests in `tests/test_circuit_breaker.py`.  
- **WhatsApp send classifier** — ambiguous vs definite; `post_attempted_at`; reclaim-after-post is dead.  
- **`bot_runtime` outbound** — stuck `sending` is cancel, not resend.  
- **Analysis LLM lane** — own semaphore, own breaker, `max_retries=0`, 8s, 1s acquire shed.  
- **Idempotency store** — advisory lock + unique `(tenant, endpoint, key)`. Voice CallSid keys. WA `{job_id}:…` keys.  
- **Inbound Meta `provider_ref` unique**; Twilio status callbacks order-insensitive (`outbound.py:836-889`).  
- **SKIP LOCKED queues** with attempt caps and stale reclaim (bot, WA, KB, webhooks, cadence).  
- **Frontend** — 30s timeout even when the caller passes a signal; mutations `retry: 0`; `retryUnlessClientError` does not retry 4xx except 408/429.  
- **Redis optional** — mesh down does not drop the PSTN call.  
- **Connector timeoutMs** default 2.5s — the one remote HTTP client that picked a collections-sane budget.

---

## 9. If only five things are fixed

1. **Stop retrying ambiguous dials.** Campaigns must not re-queue `dial_failed`. Classify Twilio timeouts like WhatsApp classifies Meta timeouts: dead-letter for reconciliation, not a 5-minute redial. Same function that already exists: `is_ambiguous_transport_error`.  
2. **Move SMS (and mandate rail) onto the outbox.** Treatment WhatsApp already did. PTP reminder and bounce first-touch are the same bug in two files. Split `claim` from `send` the way `call_closer.process_one` already splits.  
3. **Close K5 with one classifier arm.** Treat `whatsapp_send_failed:internal:*` after `post_attempted_at` as ambiguous — dead, not queued. `bot_runtime.py:614-627` is the patch.  
4. **Put a timeout on MinIO, Redis, and Postgres connect.** Then put the voice LLM client behind `get_breaker("azure_openai_voice")` (own name, so a studio preview 429 does not mute the Mouth — and vice versa).  
5. **Do not swallow the gateway.** `maybe_chat` raising `llm_gateway_spend_cap` must not fall through to Azure. Gateway 5xx retries need sleep + `Retry-After`, or `max_retries=0` and shed.

Four of five are under twenty lines. None requires a new workflow engine.

---

## 10. Circuit-breaker opportunities (do not add a sixth library)

| Candidate | Why | Pitfall |
|-----------|-----|---------|
| `azure_openai_voice` | Live pool bypasses `azure_openai` | Must not share counters with analysis or studio preview |
| Twilio REST | K4 is an unclassified timeout | Opening the breaker must **not** look like `placed: false` to campaigns |
| LLM gateway | Zero-backoff 5xx | Kill-switch currently hides the open circuit |
| MinIO | Hung PUT/GET | ValueError already ignored; add socket timeout *first* or the breaker never sees a failure |
| Connector (existing) | Add half-open probe | Do not copy the in-process class into Postgres; add a probe generation on `mcp_connectors` |

Do **not** put a breaker on Postgres. `statement_timeout` + pool_pre_ping + readiness is the shed.

---

## 11. Test gaps

Present: `test_circuit_breaker.py`, `test_connector_circuit.py`, `test_voice_write_idempotency.py`, `test_idempotency.py`, `test_place_contract.py`, WhatsApp classifier tests.

Absent:

- Campaign `placed: false` after a Twilio read timeout does not re-queue.  
- `whatsapp_outbound` persist failure after a successful send does not re-POST.  
- Treatment SMS rollback does not send twice.  
- Gateway spend-cap does not call Azure.  
- MinIO client actually times out (today it cannot fail that test).  
- Voice LLM path trips a breaker (today there is no breaker to trip).  
- Wrap-up with two different `Date.now()` keys does not create two promises.

There is still no journey test that drives START → UI → provider failure → UI (report 23).

---

## 12. Sub-agent register

Work in this document was produced through five parallel analysts, then re-read against source:

- Retry policy  
- Timeouts  
- Idempotency  
- External providers  
- Transactions / partial commits  

Where those lenses disagreed (K6 “one txn” vs “voice is split”; Redis “not used” vs mesh bus), this document takes the stricter, line-cited reading: K6 is **handler-dependent**; Redis is **optional mesh only**.
