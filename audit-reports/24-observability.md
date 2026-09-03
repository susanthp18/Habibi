# 24 — Production observability

**Question this report answers:** if this system fails in production at 3am, can anyone find out why from its logs, metrics, traces and error reports?

**Scope.** `backend/` (582 tracked `.py` files, 8 compose services) and `Habibi/` (the React console). `PRAXIST-main/` is a vendored 4,518-file third-party tree and is excluded throughout, as are `.venv/` and `node_modules/`.

**Method.** Read-only. Nothing was installed, no container was started, no test or migration was run, and the only file written is this one. Five analysts were briefed with ground truth I had verified myself, then every load-bearing claim they returned was re-verified against primary sources before it was allowed into this report — including reading the installed `uvicorn`, `starlette` and `anyio` sources in `backend/.venv` to settle framework-semantics questions rather than asserting them from memory. Where an analyst was wrong, the disagreement is adjudicated in §18 rather than quietly dropped.

**Relationship to the other reports.** Report 14 (`14-error-handling.md`) covers how errors are *handled*; this report covers whether the resulting failures can be *diagnosed*. Report 14's "correlation spine" section credits `request_context` as "a correct, well-documented ContextVar read by the log formatter". That is accurate as far as it goes. This report establishes the part that changes the conclusion: **the formatter that reads it is never installed.** Report 23 maps end-to-end journeys; §15 here maps those flows specifically to observability coverage and cost-of-blindness.

---

## Verdict

Somebody on this team knows exactly what they are doing. `backend/observability.py` is 486 lines of genuinely expert work — a private Prometheus registry so library registrations cannot make tests order-dependent, latency buckets chosen for this workload rather than copied from the library, a hard and stated rule against unbounded label cardinality, scrape-time collectors that read existing snapshots so a metric and `/ready` can never disagree, explicit zero-emission so a missing series and a zero are distinguishable in an alert, and a JSON formatter that runs messages through PII redaction because "log aggregation is exactly the kind of place a card number spoken into a transcript ends up". `voice/call_trace.py` is a purpose-built call-tracing module written after a real incident. `voice/log_bridge.py` fixes a subtle stdlib-into-loguru gap and documents the exact call it was measured on. The voice pipeline captures Pipecat's TTFB and usage metrics into per-turn database columns. The `_authz_guard` both logs and meters every denial.

And almost none of it is switched on.

The structured-log formatter is gated behind `LOG_FORMAT=json`. That variable is set in no Dockerfile, no compose service, no CI workflow, and — decisively — nowhere in the **638-line `backend/.env.example`**, a configuration template so thorough it documents retrieval margins and shadow-mode semantics. The same is true of `SENTRY_DSN`. So on any deployment an operator builds by following this repository's own documentation, three things are simultaneously true: logs are not structured, the request id is written to no log line, and **`pii_redact.redact_text` never executes on log output at all** — because the only place it runs is inside the formatter that was never installed.

It is worse than unstructured. In the `api` container nothing ever calls `logging.basicConfig`, and uvicorn's default config — which I read from the installed source — configures only the `uvicorn`, `uvicorn.error` and `uvicorn.access` loggers, never the root. So the root logger keeps its stock state: no handlers, level `WARNING`. Every `logger.info(...)` in `main.py`, `db.py`, `azure_openai.py`, `bot_runtime.py` and `agent_core/*` is **discarded before it reaches a handler**, and `WARNING`/`ERROR` fall through to `logging.lastResort`, a bare stderr handler with no formatter — no timestamp, no level, no logger name, no request id.

This is not an inference. The team already found this bug, measured it, and wrote it down. `voice/log_bridge.py:8-14` records that on call `VS-6B252E0479` "the whole five-minute call produced **zero** log lines from `agent_core.understanding`, `agent_core.turn_critic` or `voice.crm_sink`", and explains precisely why: "`WARNING` is the root logger's default level and anything below it was discarded before it reached a handler." They wrote `install()` to fix it. It is called in exactly one place — `voice/bot.py:2618`, inside `if __name__ == "__main__"`. The `voice` container is fixed. The `api` container and the `voice_insurance` container have the identical, still-unfixed bug.

The metrics have a different problem: nothing reads them. There is no Prometheus service in the compose file, no scrape config, no alert rule, no Grafana provisioning, and no runbook anywhere in the repository. The sixteen files matching "dashboard" are all the customer-facing collections KPI screen. `/metrics` is a well-built endpoint that, as committed, no process on earth is configured to poll — and two of its six pushed metrics could not report anything useful even if one were, because `voice_calls_admitted_total` increments inside the `voice` container while `/metrics` is served by the `api` container, and `VOICE_EMBEDDED_HOST=false` is the documented default.

Meanwhile the browser shows users a "Reference:" id on every crash. It is `crypto.randomUUID()`, minted in the browser at render time, never transmitted anywhere. The backend generates a real `X-Request-Id`, binds it to a ContextVar, echoes it on the response, and even adds it to `_CORS_EXPOSE_HEADERS` so the browser is explicitly permitted to read it. The frontend never does. So a user reads out a reference number that exists in no log, no database row, and no server anywhere.

And where the platform-level instrumentation runs out, the flow-level picture (§15) is worse than the module-level one suggests. Un-muting a redacted audio segment containing spoken PII — the most compliance-sensitive single action in the product — writes no audit row and no log line, while the function immediately above it in the same file audits correctly. Thirteen asynchronous business processes, including promise-breach detection, treatment enactment and every WhatsApp send, run inside one `bot_worker` loop that has no healthcheck and no liveness metric. A voice bot that crashes mid-call leaves `interactions.status='active'` forever, because `last_heartbeat_at` is written and never read. Payment webhooks log nothing on success and nothing on signature rejection. For seven of seventeen mapped flows the first signal of failure is a customer complaint; for three it is nothing at all.

The honest summary is that this system's observability was designed by someone who understood the problem, built to a high standard, and then left unwired — and the single most damaging gap is not a missing feature but a default: three environment variables that nobody is told to set. The second most damaging is that the coverage runs inverse to the stakes. The best-instrumented flows are config publishing, authorization denial and outbound dialing; the worst are PII removal, the hardship veto, consent detection and cash. The instrumentation that exists is the instrumentation a past incident paid for — which is precisely why the flows that have not failed yet are the ones nobody will see fail.

---

## 1. The observability surface, as built

| Component | File | State |
|---|---|---|
| Prometheus metrics + registry | `backend/observability.py:64-311` | Built, well-designed, **unscraped** |
| JSON structured logging | `backend/observability.py:318-392` | Built, **never installed** (`LOG_FORMAT` unset) |
| PII redaction of log output | `backend/observability.py:344-350` | Built, **never executes** (inside the formatter above) |
| Sentry error tracking | `backend/observability.py:413-444` | Built with PII scrubbing, **never initialised** (`SENTRY_DSN` unset) |
| Request-id ContextVar | `backend/request_context.py` (52 lines) | Built, correct, **one consumer — the formatter that is off** |
| `RequestIdMiddleware` | `backend/main.py:321-343` | Working; generates, sanitises, binds, echoes |
| `MetricsMiddleware` | `backend/main.py:347-385` | Working; route-template labels, counts 401/403 |
| `/health`, `/ready` | `backend/main.py:753`, `:759` | Working; `/ready` checks DB + pool + MinIO + breakers |
| `/metrics` | `backend/main.py:927` | Working, auth-gated by design |
| OpenTelemetry spans | `backend/agent_core/telemetry.py` | Called from 2 real paths, **tracer never installed** |
| Voice call tracing | `backend/voice/call_trace.py` | **Working and good** — logs at WARNING deliberately |
| Voice turn latency capture | `backend/voice/crm_sink.py:1204-1393` | **Working and good** — persisted per turn |
| stdlib→loguru bridge | `backend/voice/log_bridge.py` | **Working**, applied to 1 of 3 affected processes |
| Frontend error reporting | `Habibi/src/lib/lovable-error-reporting.ts` | **No-op outside the Lovable editor** |
| Alerting / dashboards / runbook | — | **None exist** |

### How each process actually logs

This table is the core of the report. It was assembled by reading each entrypoint and each compose `command:`.

| Service | Command | Logging configured by | Result |
|---|---|---|---|
| `api` | `uvicorn main:app --workers 1` | `observability.setup_logging()` (`main.py:426`) — **no-ops** | **Root logger has no handler.** All `INFO` discarded; `WARNING`+ via `logging.lastResort`: bare message, no timestamp, no level, no request id |
| `worker` | `python -m worker` | `worker.py:29` unconditional `basicConfig(level=INFO, format=…)` | Plain text, timestamped, INFO+ ✓ |
| `bot_worker` | `python -m bot_worker` | `bot_worker.py:48` unconditional `basicConfig` | Plain text, timestamped, INFO+ ✓ |
| `voice` | `python -m voice.bot` | `log_bridge.install()` (`voice/bot.py:2618`) | stdlib bridged into loguru, root level INFO ✓ |
| `voice_insurance` | `python -m voice.workers.insurance` | **nothing** | **Same bug as `api`.** All INFO from `agent_core`, `db`, `azure_openai`, `voice.crm_sink` discarded |

Five services, four different logging behaviours, two of them silently dropping most of what they log.

---

## 2. O1 — The `api` and `voice_insurance` processes discard their own logs (P0)

**Claim.** In the `api` and `voice_insurance` containers, no handler is ever attached to the root logger, so every `logger.info(...)` in the application is dropped before reaching a handler, and `WARNING`/`ERROR` are emitted unformatted.

**Evidence, in the order I verified it.**

1. `observability.setup_logging()` (`observability.py:469-486`) is the only code path in the `api` process that could call `basicConfig`, and it returns immediately unless `LOG_FORMAT=json`:
   ```python
   def setup_logging() -> None:
       if not json_logs_enabled():
           return
       formatter = JsonFormatter()
       root = logging.getLogger()
       if not root.handlers:
           logging.basicConfig(level=logging.INFO)
   ```
   Note the irony: **line 480-481 is exactly the fix**, and it sits behind the flag nobody sets.

2. A repository-wide grep for `basicConfig|dictConfig|addHandler|setLevel` finds it configured only in `worker.py:29`, `bot_worker.py:48`, `voice/log_bridge.py:62-64`, `mcp_server.py:83`, `provider_voice_sync.py:361` and `scripts/*`. **Nothing in `main.py`.**

3. uvicorn does not configure the root logger. Read from the installed source at `backend/.venv/Lib/site-packages/uvicorn/config.py`:
   ```python
   "loggers": {
       "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
       "uvicorn.error": {"level": "INFO"},
       "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
   },
   ```
   There is no `""` (root) entry. Application loggers such as `logging.getLogger("main")` and `logging.getLogger("db")` are not descendants of `uvicorn.*`, so they inherit nothing from this.

4. Therefore, by CPython `logging` semantics: the root logger keeps its default level `WARNING` and its empty handler list. `logger.info(...)` fails `isEnabledFor` and returns. `logger.warning(...)` and above find no handler in the ancestor chain and fall through to `logging.lastResort` — a `_StderrHandler` at level `WARNING` with no formatter, so the output is the bare `%(message)s` (plus a traceback for `.exception()`).

5. **The team already measured this exact failure.** `voice/log_bridge.py:8-14`:
   > "The consequence, measured on call `VS-6B252E0479`: the whole five-minute call produced **zero** log lines from `agent_core.understanding`, `agent_core.turn_critic` or `voice.crm_sink`. The only product line that surfaced at all was a bare `WARNING:agent_core.tools.kb:…`, in stdlib's default format, because `WARNING` is the root logger's default level and anything below it was discarded before it reached a handler. Diagnosing an agent whose analysis layer logs nothing is guesswork."

6. The fix, `log_bridge.install()`, is called in exactly one place in the repository — `voice/bot.py:2618` — and it is inside `if __name__ == "__main__":`, so it runs only for `python -m voice.bot`. The `voice_insurance` container runs `python -m voice.workers.insurance` and never calls it. The `api` container never calls it. Note the corollary: in embedded mode (`VOICE_EMBEDDED_HOST=true`), the API *imports* `voice.bot` rather than executing it, so the `__main__` guard does not fire and embedded voice inherits the API's broken logging too.

**Why this is the top finding.** Every other logging finding in this report is downstream of it. Context-free log messages do not matter much if the messages are discarded anyway. This is the difference between "our logs are hard to search" and "our logs are not being written."

**What it costs.** `docker logs collections_api` during an incident shows a sparse trickle of unformatted `WARNING`/`ERROR` lines with no timestamps and no correlation, and nothing at all from the INFO-level lines the code was written to emit.

---

## 3. O2 — Structured logging, and with it PII redaction, is off everywhere (P0)

`LOG_FORMAT` appears in exactly two tracked files — `observability.py:405,410` and `tests/test_observability.py:301,307`. It is absent from `backend/Dockerfile`, every service in `backend/docker-compose.yml`, `docker-compose.dev.yml`, both CI workflows, all of `docs/`, and from `backend/.env.example`.

That last one is what makes this a P0 rather than a deployment note. `backend/.env.example` is **638 lines** and tracked. It is an unusually conscientious document — it explains retrieval margins, MCP exposure, shadow-mode semantics for three separate engines, and the reason `customers.phone_primary` holds bare digits. An operator configuring this system reads that file. It does not mention `LOG_FORMAT`, `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE` or `APP_RELEASE`. The six matches for logging-ish words in it are incidental uses of the word "log" in unrelated comments.

Two consequences follow, and the second is the serious one.

**Logs are not machine-parseable.** No `requestId`, no `actor`, no structured fields, no consistent shape across five services.

**PII redaction never runs on log output.** `pii_redact.redact_text()` is called from exactly one place in the logging path — `JsonFormatter.format()` at `observability.py:344-350` — and `JsonFormatter` is only ever installed by `setup_logging()`. The module docstring justifies redaction on the grounds that "log aggregation is exactly the kind of place a card number spoken into a transcript ends up and is retained indefinitely". That reasoning is correct and the safeguard is real code; it simply does not execute. Redaction *does* still run where it is called directly — on `bot_tool_calls` rows via `pii_redact.audit_args`/`audit_preview` — so the database audit path is protected. The log path is not.

For a collections platform holding borrower PII, intended for deployment inside a bank, a redaction control that is present in code, described in a docstring, covered by tests, and inert at runtime is worse than one that was never written: it reads as a discharged obligation.

---

## 4. O3 — Nothing scrapes `/metrics` (P0)

`backend/docker-compose.yml` defines eight services: `redis`, `db`, `minio`, `api`, `worker`, `bot_worker`, `voice`, `voice_insurance`. There is no `prometheus` and no `grafana`. There is no `prometheus.yml`, no `alertmanager` config, no `*.rules.yml`, no Grafana provisioning directory, and no scrape configuration of any kind tracked anywhere in the repository. `docs/` contains seven files — two ADRs, three agent docs, `ops/mcp.md`, `ops/vault-inventory.md` — and no runbook, alerting doc or on-call guide.

To be precise about a claim that is easy to get wrong: sixteen tracked files match `dashboard`. All sixteen are the customer-facing collections KPI screen (`Habibi/src/routes/dashboard.tsx`, `Habibi/src/components/dashboard/*`, `backend/seed/dashboard.json`). They are business analytics for users of the product, not operational telemetry. The same applies to the six `MetricsStrip.tsx` components. **There is no operational dashboard.**

The endpoint is well-built and its cardinality discipline is exemplary. As committed, it has no consumer. Every other metrics finding below is conditional on this one being fixed first — a broken metric and a perfect metric are worth the same amount when nothing is scraping either.

---

## 5. O4 — The correlation id is generated, bound, echoed, CORS-exposed, and never written to a log (P1)

The server side of this is complete and careful:

- `RequestIdMiddleware` (`main.py:321-343`) accepts an inbound `X-Request-Id`, sanitises it against `[^A-Za-z0-9-]` and truncates to 64 characters before echoing it — correctly treating a client-supplied id as untrusted — or generates `uuid4().hex`.
- It binds a ContextVar (`request_context.py`) precisely because `request.state` "is reachable only by code holding the `Request` object — that is, almost nothing".
- It echoes `X-Request-Id` on the response.
- `main.py:635-641` adds `"X-Request-Id"` to `_CORS_EXPOSE_HEADERS` in **both** the production and development CORS branches — the browser is explicitly permitted to read it.

And then:

- The only consumer of `request_context.get_request_id()` in the entire repository is `JsonFormatter` (`observability.py:360,363`), which is never installed (§3). **The id reaches no log line.**
- `Habibi/src/api/config.ts:51-57` is the single central fetch wrapper; `authHeaders()` sets only `Accept`, `X-API-Key` and `X-Actor-User-Id`. It never sends `X-Request-Id` and never reads the echoed one — `ApiError` (`config.ts:135-149`) carries `method`, `path`, `status`, `detail` and no headers.
- The root error boundary (`Habibi/src/routes/__root.tsx:41`, registered at `:135` as TanStack Router's `errorComponent`) displays `Reference: {correlationId}` where:
  ```js
  const correlationId =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `err-${Date.now()}`;
  ```
  This is minted in the browser during render and transmitted nowhere.

So the user is shown an authoritative-looking reference number that corresponds to nothing on any server, while the real id — which the backend went to the trouble of generating, sanitising, echoing and CORS-exposing — is discarded by the client and written to no log by the server. Both halves of a working correlation scheme exist; they have simply never been connected at either end.

A secondary defect in the same component: `correlationId` is computed during render rather than memoised, and it appears in the `useEffect` dependency array (`__root.tsx:56`). Any re-render of the boundary therefore produces a new id and re-fires `reportLovableError` under a different reference. Minor today only because the report target is itself a no-op (§9).

---

## 6. O5 — Job rows carry no correlation id, so work loses its identity at the queue (P1)

Three SKIP LOCKED queues cross a process boundary. None of them can carry a correlation id, because none has a column for one:

| Table | Schema | Correlation column |
|---|---|---|
| `bot_turn_jobs` | `sql/12_crosscutting.sql:59-84` | none |
| `whatsapp_outbound_jobs` | `sql/12_crosscutting.sql:164-190` | none |
| `kb_index_jobs` | `sql/09_bot_config.sql:63-76` | none |

The enqueue functions (`bot_jobs.enqueue_bot_turn`, `whatsapp_outbound.enqueue_agent_send`, `kb_ingest.enqueue_index_job`) neither accept nor insert one. On the consuming side, `worker.py` and `bot_worker.py` do not import `observability` at all — so even a deployment that set `LOG_FORMAT=json` for the API would leave both workers on the plain formatter permanently — and their loop-level logging is bare counters: `logger.info("processed=%s", did)` (`bot_worker.py:187`), `logger.info("drained=%s", n)` (`:195`).

A ContextVar cannot cross a process boundary by any mechanism; here Postgres *is* the broker, so the row is the only available carrier and it has no field. The practical consequence: when a borrower says the bot never replied, you can find the inbound webhook's request id and you can find the job row by `conversation_id`, but nothing joins "this HTTP request" to "this job the worker picked up" except timestamp adjacency.

---

## 7. O6 — Voice admission metrics increment in a process nobody scrapes (P1)

`voice/admission.py` counts admitted and rejected calls through a helper (`:156-168`):

```python
def _count(metric: str) -> None:
    try:
        import observability
        getattr(observability, metric).inc()
    except Exception:
        logger.debug("metric %s unavailable", metric, exc_info=True)
```

`observability.py` builds a **private, per-process** `CollectorRegistry`. So `_count` increments a counter in whichever process executes it. `admission.acquire()` is called from two places: `main.py:3504` (guarded by `if _EMBEDDED_VOICE_HOST:`) and `voice/bot.py:2334` (the Pipecat pipeline, run by the `voice`/`voice_insurance` containers).

`backend/.env.example:336` sets `VOICE_EMBEDDED_HOST=false` as the documented default, and compose runs `voice` as a separate container. So in the shipped topology, admission happens in the `voice` container — which serves no `/metrics` endpoint — while `/metrics` is served by `api`, whose own counters for these two series never move.

The codebase says so itself, twice. `main.py:3501-3503`: *"Only meaningful when the pipeline runs in THIS process: with a separate `voice` container the counter here is always zero."* And `voice/admission.py:34-36`: *"The counter is **per process**. Each voice worker caps itself; there is no deployment-wide total."*

The same applies to the three scrape-time gauges `voice_calls_active`, `voice_calls_max_concurrent` and `voice_calls_high_water_mark` (`observability.py:195-201`), which call `admission.snapshot()` inside the `api` process — where `_active` is permanently empty in the default topology. **All six voice-admission series read zero on the shipped configuration regardless of call volume.**

Note this is a *deployment* mismatch, not sloppiness: the per-process limitation is deliberate and documented, and `--workers 1` (compose `:95`, `:111-112`) correctly avoids an intra-container split, so `PROMETHEUS_MULTIPROC_DIR` is rightly unused. The defect is that metrics defined in the API's registry are fed from a different container.

---

## 8. O13 — A metric that does not exist, incremented on a resource-leak path (P2)

`voice/admission.py:120` calls `_count("voice_calls_slot_reaped")`. `observability.py` defines exactly six metric objects — `http_requests`, `http_latency`, `http_in_flight`, `authz_denials`, `voice_calls_admitted`, `voice_calls_rejected`. There is no `voice_calls_slot_reaped`, and `git grep` finds the string in that one call site and nowhere else.

So `getattr(observability, "voice_calls_slot_reaped")` raises `AttributeError`, which `_count`'s broad `except Exception` swallows to `logger.debug` — a level that, per §2, is discarded outright in every process.

What it was counting matters. From `:114-120`:

```python
logger.error(
    "voice admission reclaimed an abandoned %s slot after %.0fs (token=%s) — "
    "its session never released it; teardown is leaking",
    label, age, tok,
)
_count("voice_calls_slot_reaped")
```

This is a leaked concurrency slot — a bug that progressively reduces call capacity until real callers are refused. The `logger.error` does survive (it is above `WARNING`), so the signal is not lost entirely; but the metric intended to make the leak *countable and alertable* silently does nothing, and the swallow means nobody will ever discover the name is wrong. This is the precise hazard of `getattr` plus a broad `except` on an instrumentation path.

---

## 9. O8 — Error tracking is dark on both sides (P1)

**Backend.** `setup_error_tracking()` (`observability.py:413-444`) is well-built: opt-in by DSN, `send_default_pii=False` with a comment explaining that it is load-bearing for a process handling collections transcripts, and a `before_send=_scrub_event` hook that runs `pii_redact.redact_text` over the message and exception values. `SENTRY_DSN` appears in the tracked repo only in `observability.py`, a comment in `requirements.txt:21`, and the test file. It is absent from `.env.example`'s 638 lines. So the safety net is never deployed, and unhandled exceptions are logged (badly, per §2) and lost.

**Frontend.** `Habibi/src/routes/__root.tsx:49` calls `reportLovableError`, which (`Habibi/src/lib/lovable-error-reporting.ts:26-56`) forwards only to `window.__lovableEvents?.captureException` and `window.__lovableReportRuntimeError`. Both are optional-chained globals, and the file's own comment (`:41-43`) states they are "present only inside the editor preview". In a production build neither exists, so both calls are no-ops.

To be fair to the code: this means there is **no** third-party exfiltration of borrower data from the browser, which for an on-premises bank deployment is the right outcome and worth stating plainly. But it also means a client-side crash reaches `console.error` in one user's browser and nowhere else. No Sentry, no web-vitals, no RUM, and no `fetch` anywhere in `Habibi/src` that posts to a logging endpoint. Frontend failures in production are discoverable only if a user opens devtools and reports what they see.

---

## 10. O12 — `gen_ai` spans are written to a tracer that is never installed (P2)

`backend/agent_core/telemetry.py` (37 lines) wraps OpenTelemetry:

```python
try:
    from opentelemetry import trace as _otel_trace
    _TRACER = _otel_trace.get_tracer("bigbound.agent")
except Exception:  # pragma: no cover - optional dependency
    _TRACER = None
```

`opentelemetry` is not a dependency in `requirements.txt`, `requirements-voice.txt` or `requirements-mcp.txt`; the only match in any of them is a comment at `requirements.txt:17-18` explaining that Prometheus was chosen over the OTel SDK. So `_TRACER` is `None` in every deployment and `span()` is an empty context manager.

It has two real callers, both on live paths:

- `bot_runtime.py:963` — `with _span("gen_ai.chat", gen_ai_operation_name="chat")` around the Azure OpenAI call that generates every WhatsApp/text bot reply, and a second span around each CRM tool call in the same loop.
- `sandbox_runtime.py:888` — `_span("gen_ai.invoke_agent", …)` with a nested `gen_ai.chat`.

The span names follow OTel's GenAI semantic conventions, and `telemetry.py:31-32` deliberately drops `content`, `input`, `output`, `transcript` and `arguments` from span attributes — this was written by someone who knew both the specification and the privacy constraint. It is dormant scaffolding, not a live gap; the reason it is a finding at all is that the code asserts instrumentation which does not exist, and the next engineer to read `bot_runtime.py` will reasonably assume `gen_ai.chat` spans are available.

The apparent contradiction with `observability.py`'s "traces are deliberately not attempted here" resolves cleanly: that docstring describes deployment reality and is the load-bearing statement; `telemetry.py` is call-site intent waiting on a collector.

---

## 11. External calls: what is timed and what is not

| Dependency | Timeout | Retry | Breaker | Duration measured |
|---|---|---|---|---|
| Azure OpenAI chat (`azure_openai.py:606-679`) | ✓ | deliberate no ✓ | ✓ | ✓ `latency_ms` |
| Azure OpenAI analysis (`:208-252`) | ✓ | — | ✓ | ✓ |
| Azure OpenAI embeddings (`:494-528`) | ✓ | — | ✓ | ✓ |
| Azure Speech TTS (`azure_speech.py:470-601`) | ✓ 30s | ✓ `Retry-After` + jitter | ✓ | ✓ |
| Azure Speech STT (`:639-720`) | ✓ 45s | ✓ | ✓ | ✓ |
| KB retrieval (`kb_retrieve.py`) | ✓ | ✓ | ✓ | ✓ persisted to `retrieval_logs.latency_ms` |
| Outbound webhooks (`webhooks_dispatch.py:412-460`) | ✓ | ✓ backoff + dead-letter | ✗ | ✓ `latency_ms` persisted |
| **Twilio Voice** (`voice/twilio_ops.py:257-280`) | ✓ 10s | ✗ | **✗** | **✗** |
| **Twilio SMS** (`twilio_sms.py:79`) | ✓ 10s | ✗ | **✗** | **✗** |
| **WhatsApp / Meta Graph** (`whatsapp.py:70-132`) | ✓ 30s | ✓ (job ladder) | ✓ | **✗** |
| **MinIO / S3** (`storage.py:104-291`) | **✗ none** | ✗ | ✓ | **✗** |
| Postgres (`db.py`) | ✓ `statement_timeout` | — | — | ✗ per-query; pool occupancy only |
| Redis mesh bus (`voice/mesh_bus.py:39-156`) | ✗ | ✗ | ✗ | ✗ |
| TTS provider previews (`provider_tts.py`) | ✓ 60s | key rotation only | ✗ | ✗ |

The Azure and KB paths are genuinely well instrumented. The gaps that matter:

- **Twilio has no timing and no circuit breaker**, on the highest-value flow in the product. When a dial takes twenty seconds to fail, nothing records whether Twilio was slow to accept or the network was slow to Twilio.
- **The MinIO client has no timeout configured at all** — only a breaker. A hung connection has nothing bounding it, so it can occupy a worker thread indefinitely rather than failing into the breaker that was built to catch it. This is the most concerning single line in the table.
- **WhatsApp send latency is never measured**, though the retry ladder around it is good.

Correctly cleared: `payments.py` has no outbound provider call to time — Razorpay checkout creation is explicitly stubbed (`:52-58`) and confirmation arrives by inbound webhook. That is N/A, not a gap.

---

## 12. Metrics: what is missing

Beyond §4 (nothing scrapes) and §7 (voice series are dead), the following failure modes have **no metric at all**. None of `azure_openai.py`, `azure_speech.py`, `payments.py`, `payment_events.py`, `webhooks_dispatch.py`, `whatsapp_outbound.py` or `contact_policy.py` imports `observability`:

- LLM token spend and cost — for a product whose unit economics are per-call LLM tokens
- LLM, STT and TTS error rates and latency distributions
- Payment intent creation/completion failure rate
- Webhook delivery success/failure rate (recorded as DB rows only, queryable by hand, not alertable)
- WhatsApp send failure rate
- **Consent / opt-out enforcement violations** — a legal exposure in a collections platform, with a whole subsystem (`contact_policy.py`, `sql/03_consent.sql`) and no counter
- Per-query database latency (only pool occupancy is exposed)

Partial indirect coverage does exist and deserves credit: circuit breakers wrap Azure OpenAI, Azure Speech, WhatsApp and MinIO, and breaker state and failure counts *are* exported by the `circuit_breakers` collector. That gives a binary "is this dependency broken" signal, but no latency distribution and no way to distinguish a rate-limit storm from a hard outage.

Two smaller metrics-path defects:

- **`kb_index_jobs` has no index** (`sql/09_bot_config.sql:63-76` defines only a PK on `id`; no index on it exists in `sql/` or `alembic/`). `_job_queue_samples()` runs `GROUP BY status` across it on every scrape, so each scrape is a full sequential scan that degrades linearly as the table grows. The other two queues are correctly indexed (`ix_bot_turn_jobs_status_run_after`, `ix_whatsapp_outbound_jobs_status_run_after`). P2.
- **The scrape shares the pool it measures.** `_job_queue_samples()` checks a connection out of the same `db.engine` QueuePool (`pool_size=5`, `max_overflow=5` in compose) that `/ready` monitors for exhaustion. Under saturation, scraping competes with live traffic for the ten slots. An accepted trade-off rather than an oversight — the module notes this is "the only collector that touches the database" — but it means `/ready` and `/metrics` share fate under pool pressure. P3.

---

## 13. O7 — Four of eight services have no liveness signal (P1)

| Service | Healthcheck |
|---|---|
| `redis` | ✓ `redis-cli ping` |
| `db` | ✓ `pg_isready` |
| `minio` | ✓ `mc ready local` |
| `api` | ✓ `curl -fsS http://127.0.0.1:8000/ready` |
| `worker` | **none** |
| `bot_worker` | **none** |
| `voice` | **none** |
| `voice_insurance` | **none** |

All four undefended services carry `restart: unless-stopped`, which only acts when a process *exits*. A deadlocked event loop, a stuck socket read, or a worker blocked on a lock leaves the container in `Up` state indefinitely with no signal to Docker, compose, or any orchestrator. These are the four processes that do the actual outbound work — draining job queues and placing calls.

The `api` healthcheck correctly targets `/ready` rather than `/health`, and `/health` is not misused anywhere as a dependency check. That part is right.

### A related gap: `/ready` does not reflect boot-seed failure

The lifespan (`main.py:445-484`) performs seven boot-time seed operations — permission catalog, price book, TTS catalog, first-party skills, provider registry — each wrapped in `try/except` that logs `logger.warning(..., exc_info=True)` and continues. Continuing is a defensible choice. But `/ready` (`main.py:759`) checks only DB, pool headroom, MinIO and breakers. A container that failed *every* boot seed reports ready and serves traffic with a stale price book and an unsynced provider registry, having announced it only through a warning that — per §2 — is emitted unformatted and collected nowhere. P2.

---

## 14. Error and exception diagnostics

**Unhandled exceptions.** Handlers are registered for `StarletteHTTPException` (`main.py:693`), `RequestValidationError` (`:698`), `AzureBusyError` (`:704`) and `CircuitOpenError` (`:712`). There is no generic `Exception` handler, so an unexpected exception propagates to Starlette's `ServerErrorMiddleware`, which returns a bare 500 and re-raises for the ASGI server to log. `MetricsMiddleware` correctly records it as a 500 before re-raising (`main.py:355-377`). The app is not constructed with `debug=True`, so no stack trace is returned to the client — correct. The traceback is logged by uvicorn's own `uvicorn.error` logger, which *is* configured, so unhandled 500s are one of the few things that do reliably reach stdout in the `api` container — but through uvicorn's plain formatter, so with no request id, no actor and no PII redaction.

There is a second-order effect worth stating. Starlette's `ServerErrorMiddleware` is its outermost wrapper — outside `CORSMiddleware` and outside `RequestIdMiddleware`, which sets the response header only *after* `call_next` returns normally and has no `except`. So an unhandled 500 goes back to the browser with **neither CORS headers nor `X-Request-Id`**, as `PlainTextResponse("Internal Server Error")`. A browser client therefore experiences the system's least-diagnosable failure as a CORS or network error rather than a legible 500 — the one case where the user most needs a reference id is the one case where the id is guaranteed absent. **O29, P2.**

**Circuit breaker transitions are half-observable.** `circuit_breaker.py:140-145` logs `logger.warning("circuit OPEN name=%s failures=%s reset_s=%s")` exactly once per transition — good. But `_on_success` (`:105-119`) resets the breaker **silently**, and the exported metrics are scrape-time *gauges* (`circuit_breaker_state`, `circuit_breaker_failures`) with no `circuit_breaker_trips_total` counter. A breaker that opens and closes between two scrapes leaves **no trace in Prometheus at all** — only the log line, which per §2 is unformatted and uncollected. Flapping, the most diagnostic breaker behaviour, is the case the instrumentation cannot see. **O28, P2.**

**Retry visibility is inconsistent.** `azure_speech.py:429-455` logs every retry with delay and attempt count. `llm_gateway/client.py:112-131`'s retry loop logs **nothing on any attempt** — only the final failure surfaces. An LLM gateway quietly needing two or three attempts per call would appear only as unexplained latency. **O31, P3.**

**Context-free failure logs.** Verified samples, each checked against the file:

| Site | Log line | Identifier in scope but omitted |
|---|---|---|
| `main.py:4311` | `logger.exception("kb_retrieve_failed")` | the query |
| `main.py:3807` | `logger.exception("Twilio outbound failed")` | `to`, `custom["customer_id"]` |
| `bot_worker.py:110` | `logger.exception("call closer failed")` | job / interaction id |
| `agent_core/tools/domain.py:751` | `logger.exception("create_promise failed")` | customer / promise id |
| `agent_core/tools/domain.py:834,919,974` | `create_dispute` / `apply_goodwill` / `create_callback` failed | customer / case id |
| `azure_openai.py:529,728` | `"chat usage metering failed"` | call / interaction id |

`domain.py:751` is the sharpest: a promise-to-pay — a commitment from a borrower, the core artifact of a collections product — fails to persist, and the log records neither who made it nor for how much. Report 14 measured this pattern more broadly: 74% of `voice/` log calls and 80% of `agent_core/` calls carry no identifier at all.

**Dead-letter reasons are persisted** — `kb_index_jobs`, `bot_turn_jobs` and `whatsapp_outbound_jobs` all carry an `error TEXT` column, so a job in status `dead` retains its cause. Good, and better than the metric-only view suggests.

**Redaction coverage, for the counterfactual where §3 is fixed.** `pii_redact.redact_text` (`pii_redact.py:22-58`) matches 16-digit cards, space-grouped Aadhaar, uppercase PAN, and phone numbers **only with a literal `+91` prefix**. `backend/.env.example:622-625` documents that `customers.phone_primary` "holds bare digits" because that is what the WhatsApp Graph API requires. So the stored phone format does not match the redaction regex: turning on JSON logging today would produce structured logs that still leak borrower phone numbers. It also has no detector for API keys, bearer tokens, connection strings or DSNs, and `JsonFormatter` copies `extra=` fields into the payload without redacting them (latent — no current call site passes PII via `extra`). P2, and it must be fixed *before* §3, not after.

---

## 15. Critical business flows mapped to observability coverage

Ranked by cost of blindness: highest is where money moves or a regulatory obligation is discharged with no durable trace. "First signal" answers the only question that matters operationally — *if this silently breaks, how does anyone find out?* Read every row against §2: on the `api` and `voice_insurance` containers, any log line below `WARNING` in this table is discarded before it reaches a handler.

| # | Flow | Entry point | Log on failure | Metric | Audit row | **First signal if it silently breaks** |
|---|---|---|---|---|---|---|
| 1 | **Redaction audio-mute** | `followups_db.py:585-616` | **none — no logger in the module at all** | none | **none** | **Never.** Only by re-listening to the call |
| 2 | **Bulk campaign dial vs. treatment hold** | `campaigns.py:274-278` | none naming the hold | none | `contact_events` row, but nothing joins it to `treatment_holds` | **Never**, absent a manual retrospective join |
| 3 | **Consent / opt-out enforcement** | `contact_policy.py:1021`, `:597` | `logger.exception(… customer=%s)` — carries the id ✓. But a failed consent *read* is `logger.debug` (`:335`) — **discarded everywhere** | **none** | `optout_events` + `contact_events` on every attempt ✓ | **A regulator or a complaint.** The audit trail is strong; the *detection* is absent |
| 4 | **Payment webhook confirmation** | `main.py:825`, `:857` | **no success log at all**; signature rejection raises 401/403 **unlogged** | none | none for the payment itself | Hours — a borrower who paid and is still being chased |
| 5 | **Promise-to-pay creation and breach** | `domain.py:751`; `promise_fulfillment.py:963` | `logger.exception("create_promise failed")` — **no customer, no amount**; breach logs aggregate counts only, no per-customer id | none | `activity_events` | Days. Depends entirely on `bot_worker` being alive (see below) |
| 6 | **Voice bot crash mid-call** | `voice/bot.py:2361-2367` | `try/finally` with **no `except`** — an escaping exception skips `_finalize_call` | none | interaction row + per-turn transcript **survive** ✓; **audio recording is lost** | **Never for the zombie row.** `interactions.status` stays `active`, `voice_sessions.status` stays `live`, and no reaper exists — `last_heartbeat_at` is written but never read |
| 7 | **Outbound voice call** | `outbound.py:533`, `main.py:3731` | `call_attempts` row written **before** the policy gate, so a refusal still leaves a trace ✓; rich per-outcome logging with `attempt_id`/`call_sid` ✓ | admission counters **read zero** (§7); Twilio call itself **untimed, no breaker** | `call_attempts` ✓ | **≤30 min** via `outbound.sweep_stale()`, wired at `bot_worker.py:81`. The best bound in the system |
| 8 | **Inbound voice call** | `main.py:3504` `/twilio/voice/incoming` | `call_trace` ✓, but `ws.arrived`/`ws.authorized` precede any call id (O18) | as above | none until the WS connects | If the webhook never arrives at all: **no row, no log, no metric** — visible only in Twilio's console, which nothing reconciles against |
| 9 | **WhatsApp inbound → bot turn** | `bot_jobs.enqueue_bot_turn` → `bot_worker.py` | `bot_worker.py:110` `logger.exception("call closer failed")` — **no job id**; loop logs `processed=%s` | `job_queue_depth{queue="bot_turn_jobs"}` ✓ (unscraped) | `bot_tool_calls` ✓ redacted | The dead-letter count — **if anything were scraping it.** Otherwise the borrower |
| 10 | **WhatsApp outbound send** | `whatsapp_outbound.enqueue_agent_send` | retry/dead-letter ladder is good ✓; `error` column persisted ✓ | depth metric ✓ (unscraped); **no send-failure counter, no latency** | none | The borrower never replies, because they never received anything |
| 11 | **Dispute / callback / goodwill** | `domain.py:834`, `:919`, `:974` | `logger.exception("… failed")` — **no case or customer id** | none | `bot_tool_calls` | A customer chases a dispute the system has no failure record of |
| 12 | **LLM turn generation** | `bot_runtime.py:963` | Azure call itself is timed and breakered ✓ | breaker state ✓; **no token spend, no error rate** | — | A cost spike on the monthly bill |
| 13 | **KB / RAG retrieval** | `kb_retrieve.py` | timed and persisted to `retrieval_logs.latency_ms` ✓ | `kb_result_cache` hits/misses ✓, `rate_limit_throttled` ✓ | `retrieval_logs` ✓ | **Good.** This flow is genuinely observable |
| 14 | **KB indexing** | `kb_ingest.enqueue_index_job` | `error` column persisted ✓; `main.py:4465,4487` log without document id ✗ | depth metric ✓, but the table is **unindexed** so each scrape scans it (O16) | none | A search returns nothing and someone notices |
| 15 | **Agent config publish / rollback** | `agent_core/change_log.py:137-178` | — | none | **`audit_log`, hash-chained with `actor_user_id`** ✓ | **Best-covered flow in the system.** `verify_chain()` proves tamper-evidence |
| 16 | **Authorization denial** | `main.py:546-551` | `logger.warning(… actor, method, route, permission)` ✓ survives | `authz_denials_total{route,permission}` ✓ | none | Fast, and correctly designed — both halves present |
| 17 | **Boot-time seeding** | `main.py:445-484` | seven `logger.warning(exc_info=True)` — survive, but unformatted and uncollected | none | none | **Never.** `/ready` returns 200 regardless (O14) |

### The cross-cutting fact behind half the table: `bot_worker` is a single point of failure with no liveness signal

`bot_worker.py:64-149` (`process_one_any`) is one polling loop that drives, in order: WhatsApp bot replies, WhatsApp outbound sends, promise breach detection, stale-outbound sweeping, pool health, voice payment events, call closing, cadence, campaigns, treatment enactment, treatment follow-through, treatment sweeps, webhook dispatch, and the agent clerk. **Thirteen business processes in one process.**

If it stops, promises never breach, campaigns never advance, treatment decisions never enact, webhooks never dispatch and WhatsApp never sends — and per O7 that container has **no healthcheck**, so it stays `Up`. There is no "is `bot_worker` alive" metric. The only downstream symptom is queue depth climbing on three tables, which nothing alerts on (§4). This single fact is why "days, when a customer complains" recurs across so much of the table above, and it is why O7 is ranked P1 rather than a routine ops nit.

### Four observations

**The coverage is inverse to the stakes.** The best-instrumented flows are agent config publish (row 15, hash-chained and tamper-evident), authz denial (row 16, logged *and* metered) and outbound calling (row 7, bounded at 30 minutes). All three are well built. None of them moves money. The four worst — redaction mute, campaign-vs-hold, consent detection and payment confirmation — are respectively the PII-removal proof, the hardship veto, the regulatory obligation and the cash. **The instrumentation that exists is the instrumentation a past incident paid for**, which is why voice is well covered and payments are not: nobody has been burned by payments yet.

**Row 1 is the sharpest single result in the audit.** `patch_audio_segment_mute` is a tenant-scoped `SELECT` followed by a bare `UPDATE redaction_audio_segments SET muted = :m`. No audit row, no log line — and `followups_db.py` has no module-level logger at all. Its immediate sibling `patch_pii_finding` (`:548`) *does* write `_activity` at `:574`, so this is an inconsistency within one file rather than a blanket omission. Un-muting a segment containing spoken PII is the single most compliance-sensitive action in the product, and it leaves no record of who did it or when.

**Row 2 needs its scope stated honestly.** Whether a bulk campaign *should* dial a customer under an active treatment hold is a correctness question that belongs to the authorization and workflow reports, not this one. What belongs here is that **nothing would tell you it happened**: `excludeOnHold` appears in exactly two places in the backend, both in `campaigns.py` (`:206` declaring the selector field, `:274` applying it), so it is opt-in rather than default; and `contact_policy.admit()` — the shared gate every other channel calls — never consults `treatment_holds`. A `contact_events` row is still written, so the contact is recorded; what is missing is any log, counter or join that distinguishes it from a legitimate one. The violation and the ordinary call look identical.

**"A customer complains" is the first signal for seven of the seventeen flows, and "never" for four** — the redaction mute, the campaign-vs-hold contact, the zombie call row, and boot-seed failure. That is the honest answer, and it is what operationally blind means in practice.

**Voice is the exception that proves the rule.** Rows 4–5 are well covered — and they are well covered precisely because someone was burned once and wrote `call_trace.py` afterwards, deliberately logging at `WARNING` because they knew the root logger sits there. The instrumentation that exists in this codebase is the instrumentation that a past incident paid for.

**Every "✓ (unscraped)" in the metric column is currently worth nothing.** Rows 6, 7 and 11 have correctly-built queue metrics including dead-letter depth and backlog age. Until §4 is fixed they are text on an endpoint nobody polls.

---

## 16. What is genuinely well built

Listing these is not politeness; they are the templates the fixes should copy, and each survived adversarial reading.

- **`observability.py`'s cardinality discipline.** Route templates only, never raw paths; `<unmatched>` for unrouted requests so a 404 scan cannot mint unbounded series; an explicit module-level rule that "a metric labelled by a user id is an outage waiting for a busy day". Exactly right.
- **The private `CollectorRegistry`** rather than the process-global default, with the reason stated: the global one is shared with any library that registers something and makes tests order-dependent.
- **Scrape-time collectors that read existing snapshots** instead of mirroring state into pushed gauges, so a metric and `/ready` cannot disagree about the same number.
- **Explicit zero emission** for absent `(queue, status)` pairs, because "a missing series and a zero look identical in a graph and behave very differently in an alert".
- **`_breaker_samples()`'s comment** recording that reading `snapshots()` as a mapping "silently produced no breaker metrics at all, which is the worst possible failure for a signal whose entire job is to tell you a dependency is down."
- **Instrumentation that can never fail a request** — `MetricsMiddleware` swallows its own errors, `_SnapshotCollector.collect` degrades to missing series rather than a broken scrape, `admission._count` never blocks a call. These deliberate swallows are correct.
- **`MetricsMiddleware` placed outside `ApiKeyMiddleware`** so 401s and 403s are counted — "an auth failure spike is exactly the thing worth alerting on".
- **`voice/call_trace.py`** — a purpose-built call tracer logging `dial.requested → dial.placed → ws.arrived → ws.authorized → ws.upstream_open → pipeline.ready → ws.closed`, each with its own timing and the three ids needed to join a Twilio SID, an attempt id and a session id. It logs at WARNING **deliberately**, because the author knew the root logger sits at WARNING — which means it is one of the few product signals that survives the §2 bug. Written after an incident where "a call that answered and played silence" took most of a day to debug.
- **Voice turn telemetry is captured, not dropped.** `crm_sink.py:1204-1393` reads Pipecat's `TTFBMetricsData`, `LLMUsageMetricsData` and `TTSUsageMetricsData` off the pipeline and persists `stt_ttfb_ms`, `llm_ttfb_ms`, `tts_ttfb_ms`, `user_turn_ms`, `tool_ms` and `aggregation_ms` per turn (migration `20260727_0049_turn_latency_breakdown.py`), with a comment noting Pipecat 1.6.0 has no `STTUsageMetricsData` so STT is derived. Barge-in is recorded as `interrupted` on the turn row.
- **Migration `20260801_0055_turn_trace_keys.py`** adds `transcript_turn_id` foreign keys to `bot_tool_calls` and `retrieval_logs` specifically because "show me what the bot did on turn 4" was previously unanswerable. That is an observability fix made at the schema level, which is the right level.
- **`log_bridge.py`** — correct depth-walking so loguru reports the true call site, idempotent installation, and third-party loggers pinned to WARNING so the conversation is not buried.
- **ContextVar propagation is correct everywhere it is used.** `asyncio.to_thread` copies context (~90 call sites); `sandbox_runtime.py:123-139` explicitly does `copy_context()` + `ctx.run` for its `ThreadPoolExecutor` with a comment explaining why; `usage_meter.py` resolves attribution *before* crossing into its flush thread. There is a dedicated test, `test_attribution_survives_asyncio_to_thread`. No propagation bug was found.
- **`telemetry.py`'s span-attribute blocklist** — `content`, `input`, `output`, `transcript`, `arguments` are dropped before `set_attribute`, so transcripts cannot leak into spans even once a collector exists.
- **`_authz_guard`** logs *and* meters every denial, and the docstring records a real incident: annotating the parameter as `Request` rather than `HTTPConnection` broke websocket upgrades so that "Twilio's Media Stream never connected, the customer heard silence, and every status callback still reported a healthy call." That sentence is the best one-line argument for this entire report.
- **`/metrics` is authenticated**, deliberately, because it publishes pool occupancy, breaker state and call volume — "reconnaissance for an attacker and commercially sensitive besides". Most teams get this wrong in the other direction.
- **`bot_tool_calls` redaction is centralised at the single writer** (`bot_jobs.record_tool_call`), which is why it actually holds.

---

## 17. What to do, in order

The ordering matters more than usual here, because several of these fixes are worthless or actively harmful out of sequence.

1. **Fix the phone redaction regex first** (`pii_redact.py`, the `+91`-prefixed pattern vs. the bare-digit storage format documented at `.env.example:622-625`), and extend `JsonFormatter` to redact `extra=` values. Do this *before* step 3 — turning on structured logging while redaction cannot match the stored phone format would produce a well-indexed, aggregated, indefinitely-retained store of borrower phone numbers.
2. **Install a root log handler unconditionally in the `api` and `voice_insurance` processes.** The mechanism already exists and is proven: call `log_bridge.install()` for `voice_insurance` (which already imports loguru), and for `api` move the `if not root.handlers: logging.basicConfig(level=logging.INFO)` out from behind the `LOG_FORMAT` gate. This alone restores every INFO line the application already writes.
3. **Set `LOG_FORMAT=json` in the compose `environment:` block for all five app services, and document it in `.env.example`** alongside `SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE` and `APP_RELEASE`. Steps 2 and 3 together make the request id appear in a log line for the first time.
4. **Read the echoed `X-Request-Id` in `Habibi/src/api/config.ts`**, attach it to `ApiError`, and display *that* in the error boundary instead of `crypto.randomUUID()`. The backend already exposes the header via CORS; this is a few lines, and it converts every support ticket from "it broke" into a greppable id. Also send a client-generated id on the way in, so a request stays correlatable even when the response never arrives.
5. **Stand up a scrape.** Add a `prometheus` service to compose pointing at `/metrics` with an observability service key, and write four alert rules to begin with: `job_queue_depth{status="dead"} > 0`, `job_queue_oldest_seconds > 900`, `circuit_breaker_state{state="open"} == 1`, and `db_pool_available == 0`. Every one of those series already exists and is correctly built.
6. **Add healthchecks to `worker`, `bot_worker`, `voice` and `voice_insurance`.** For the two job workers, a liveness file touched each loop iteration and checked for staleness is sufficient and cheap; for `voice`, the existing `:7860` runner port already answers.
7. **Decide where voice metrics live.** Either expose a small `/metrics` endpoint from the voice process and scrape it separately, or push the six admission series through a shared store. Until then, delete or clearly comment the series that cannot report, so nobody builds a panel on a permanently-zero metric.
8. **Fix `_count("voice_calls_slot_reaped")`** — define the counter, and have `_count` log at WARNING rather than DEBUG so a future missing metric name is discoverable instead of silent.
9. **Add a correlation column to the three job tables** — `request_id TEXT` on `bot_turn_jobs`, `whatsapp_outbound_jobs` and `kb_index_jobs`, populated at enqueue from `request_context.get_request_id()` and re-bound in the worker loop.
10. **Time the Twilio and WhatsApp calls, and set a MinIO client timeout.** The MinIO timeout is the smallest and most urgent item in this list: an unbounded connection can hold a worker thread indefinitely, which the breaker around it cannot help with.
11. **Add counters for the six unmetered business failures** in §12. The consent counter matters most: it is the one whose absence is a regulatory exposure rather than an operational one.
12. **Either install `opentelemetry-api` or delete `agent_core/telemetry.py`.** Dormant instrumentation that reads as live is a trap for the next engineer.

Four more, added after the flow map landed. Two of them outrank most of the list above:

- **Write an audit row in `patch_audio_segment_mute`** (O23). Copy the `_activity` call its sibling `patch_pii_finding` already makes at `followups_db.py:574`. This is a handful of lines on the most compliance-sensitive action in the product, and it should go first.
- **Give `bot_worker` a liveness signal** (O25) — a heartbeat row or file touched each loop iteration, a `bot_worker_loop_iterations_total` counter, and the healthcheck from step 6. Thirteen business processes currently share one unobserved process.
- **Add a reaper for zombie calls** (O26). `last_heartbeat_at` is already written on `voice_sessions`; nothing reads it. `outbound.sweep_stale()` is the working pattern to copy, and it is already wired into the same worker loop.
- **Log payment webhook outcomes** (O27) — one line on success with the payment id and amount, one on signature rejection with the provider and source. A rotated PSP secret and an attacker probing signatures must not look identical.

---

## Findings index

| ID | Sev | Finding |
|---|---|---|
| O1 | P0 | `api` and `voice_insurance` never attach a root log handler: all INFO discarded, WARNING+ emitted bare via `lastResort` (`main.py:426`, `observability.py:476-481`, uvicorn `config.py`) |
| O2 | P0 | `LOG_FORMAT` set nowhere, including the 638-line `.env.example` — JSON logging off, request id in no log line, **and `pii_redact` never runs on log output** |
| O3 | P0 | Nothing scrapes `/metrics`: no Prometheus service, scrape config, alert rule, operational dashboard or runbook anywhere in the repo |
| O4 | P1 | Request id generated, sanitised, echoed and CORS-exposed, but written to no log and read by no client; the UI shows a browser-minted UUID instead (`__root.tsx:45-48`) |
| O5 | P1 | The three job queues have no correlation column; workers log bare counters and never import `observability` |
| O6 | P1 | Voice admission counters increment in the `voice` container, which serves no `/metrics`; `VOICE_EMBEDDED_HOST=false` is the default — all six voice series read zero |
| O7 | P1 | `worker`, `bot_worker`, `voice`, `voice_insurance` have no healthcheck; a hung worker stays `Up` forever |
| O8 | P1 | `SENTRY_DSN` never set; frontend `reportLovableError` is an editor-only no-op — no error tracking on either side |
| O9 | P1 | Twilio voice and SMS have no timing and no breaker; **the MinIO client has no timeout at all** |
| O10 | P1 | Failure logs on money and CRM paths omit the identifier that was in scope (`domain.py:751`, `main.py:3807`, `bot_worker.py:110`, …) |
| O11 | P1 | No metric for LLM spend, STT/TTS errors, payment failures, webhook delivery, WhatsApp sends, or consent violations |
| O12 | P2 | `gen_ai.chat` / `gen_ai.execute_tool` / `gen_ai.invoke_agent` spans call a tracer that is never installed (`opentelemetry` is not a dependency) |
| O13 | P2 | `_count("voice_calls_slot_reaped")` targets a metric that does not exist; the `AttributeError` is swallowed to DEBUG, on a resource-leak path |
| O14 | P2 | `/ready` ignores boot-seed failure: a container that failed all seven seeds reports ready |
| O15 | P2 | `pii_redact`'s phone regex requires a `+91` prefix; stored phones are bare digits — redaction would miss them even once enabled |
| O16 | P2 | `kb_index_jobs` has no index; every scrape sequentially scans it |
| O17 | P2 | `JsonFormatter` copies `extra=` fields into the payload without redacting them (latent: no current call site passes PII) |
| O18 | P2 | `ws.arrived` / `ws.authorized` precede any call id, and `ws_proxy.py` bridge logs carry no session id — the socket phase is correlatable only by timestamp |
| O19 | P2 | `bot_tool_calls` has no actor column, so it cannot answer whether a human triggered a tool call |
| O20 | P3 | The metrics scrape checks out a connection from the same pool `/ready` guards for exhaustion |
| O21 | P3 | `CORSMiddleware` is added after the ordered block and is therefore outermost, contradicting the middleware-order comment at `main.py:607-613` (no behavioural effect) |
| O22 | P3 | `voice/host.py:161-163` freezes the offer request's id into a call-lifetime task; inert today because voice never reads `request_context`, but a trap if it ever does |
| O23 | P0 | `patch_audio_segment_mute` (`followups_db.py:585-616`) writes no audit row and no log — un-muting spoken PII is untraceable, while its sibling `patch_pii_finding:574` does audit |
| O24 | P1 | Nothing distinguishes a campaign dial to a treatment-held customer from a legitimate one: `excludeOnHold` is opt-in (`campaigns.py:206,274`) and `contact_policy.admit()` never consults `treatment_holds` |
| O25 | P1 | `bot_worker.py:64-149` drives thirteen business processes in one loop with no liveness metric and (per O7) no healthcheck |
| O26 | P1 | No reaper for `interactions.status='active'` / `voice_sessions.status='live'` after a voice crash; `last_heartbeat_at` is written but never read. Audio recording is lost; transcript survives |
| O27 | P1 | Payment webhooks have no success log at all, and signature rejections raise 401/403 unlogged — a rotated PSP secret and an attacker probing signatures look identical |
| O28 | P2 | Circuit breakers log OPEN but not CLOSE, and export gauges rather than a trips counter — open/close between two scrapes leaves no trace |
| O29 | P2 | An unhandled 500 carries neither CORS headers nor `X-Request-Id`, so the least-diagnosable failure reaches the browser as a CORS error |
| O30 | P2 | `observability.py:349-350` swallows a redaction failure and logs the **unredacted** message — the PII-scrubbing step fails open |
| O31 | P3 | `llm_gateway/client.py:112-131` retries without logging any attempt |
| O32 | P2 | A `failed` `kb_index_jobs` row is a permanent silent bucket: `claim_next_job` selects only `queued`, so it is never retried and never reaches `dead` |

---

## Checked and cleared

Verified negatives. These are worth as much as the findings.

- **`main.py:1012`'s duplicate module name is not a bug.** `import observability` at `:39` and a function-local `from agent_core.reco import observability` at `:1012` are two distinct modules, one legitimately shadowing the other inside a single function. I checked this specifically because it is the shape of error I made in report 21.
- **Middleware ordering is correct and deliberate.** `MetricsMiddleware` sits outside `ApiKeyMiddleware`, so 401s and 403s are counted.
- **ContextVar propagation has no bug.** `asyncio.to_thread` copies context (~90 call sites); the one production `ThreadPoolExecutor` explicitly does `copy_context()` + `ctx.run`; `usage_meter` resolves attribution before crossing into its flush thread; sync `def` endpoints inherit correctly via anyio. Verified against the installed `anyio` and `starlette` sources rather than assumed. `run_in_executor` is used nowhere.
- **The websocket middleware bypass is framework behaviour, not a local defect.** `BaseHTTPMiddleware`, `GZipMiddleware` and `CORSMiddleware` all pass non-`http` scopes straight through — read from the installed Starlette source. The auth consequence is deliberate and test-pinned (`test_voice_ws_authz.py`).
- **`--workers 1`** is set in both the compose environment and the command, so there is no intra-container counter split and `PROMETHEUS_MULTIPROC_DIR` is correctly unused.
- **`print()` is confined to CLI scripts, seeds and tests** — none in the request-serving path.
- **No duplicate request logging.** `MetricsMiddleware` does not emit a log line alongside uvicorn's access log.
- **No secrets found interpolated into log messages** in the sampled Azure, Twilio and DB call sites. `db.py:10424,10444` deliberately logs only the last four digits of a phone number — good discipline where it was applied.
- **`payments.py` has no outbound provider call to time.** Razorpay checkout is explicitly stubbed and confirmation arrives by inbound webhook. N/A, not a gap.
- **Dead-letter causes are persisted** — all three job tables carry an `error TEXT` column, so a `dead` job retains its reason.
- **The frontend does not exfiltrate borrower data to a vendor.** `reportLovableError`'s two targets are editor-only globals; in production both calls are no-ops. Wrong for diagnosis, right for data residency.
- **`bot_turn_jobs` and `whatsapp_outbound_jobs` are correctly indexed** for the exact `GROUP BY status` shape the scrape uses.
- **No k8s or helm manifests exist**, so there is no unexamined deployment surface that might set the missing variables — with one caveat, recorded below.

---

## 18. Corrections to my own framing

Recorded rather than quietly fixed, because a brief that seeds a wrong hypothesis is a way to manufacture a false finding, and because the reliability of the rest of this report depends on being able to see where it was wrong.

1. **I assumed there were no dashboard or alerting artifacts, and the literal grep proved me wrong.** Sixteen tracked files match "dashboard". All sixteen are the customer-facing collections KPI screen. The conclusion survived, but only because I checked before writing it.
2. **I told the tracing analyst that no OpenTelemetry code existed anywhere.** `backend/agent_core/telemetry.py` does exist and is called from two live paths. I corrected the brief mid-flight.
3. **I then told the same analyst that nothing else in the repo mentioned "telemetry", on the strength of a truncated grep.** Seven files do. I retracted it in a second message and told the analyst to treat the question as open and verify independently — which it did, and the resulting finding (O12) is sharper than either of my versions.
4. **I expected the multi-process metrics question to be either a scandal or a non-issue.** It is neither. The per-process limitation is deliberate and documented in the codebase twice; the actual defect is narrower and more specific — a deployment topology in which metrics defined in one container are fed from another.
5. **I nearly reported the frontend's vendor error reporter as data exfiltration.** Reading it showed the opposite: both targets are optional-chained editor-only globals, so nothing leaves the browser in production. The finding is a diagnosis gap, not a privacy breach, and stating it the other way would have been alarmist and wrong.
6. **The correlation analyst reported that no React error boundary exists in the app.** That is incorrect: it searched for the class-component idiom (`ErrorBoundary`, `componentDidCatch`) and missed TanStack Router's convention. `Habibi/src/routes/__root.tsx:41` defines `ErrorComponent` and `:135` registers it as `errorComponent`. I verified this directly and did not propagate the claim. The substance of that analyst's finding survives — the frontend still neither sends nor reads a correlation id — but the specific assertion was false, and it is the same anchored-pattern failure that produced my own error in report 21.
7. **Report 14 credits `request_context` as "a correct, well-documented ContextVar read by the log formatter."** Every word of that is true and I am not contradicting it. What this report adds is the fact that changes its meaning: the formatter is installed only under an environment variable that no tracked artifact sets. This is an escalation of a sibling report's finding, not a disagreement with it.
8. **I wrote §15 myself, then the fifth analyst returned and I rewrote it.** The failure-diagnostics analyst had not reported when the rest of the report was finished, so I built the flow map from the four returned reports plus my own reading, and recorded that it was narrower than a dedicated pass. It then landed, with material I had missed entirely: the `bot_worker` single-point-of-failure across thirteen business processes, the unaudited redaction mute (now O23, a P0 and arguably the sharpest finding here), the opt-in treatment-hold filter (O24), the missing zombie-call reaper (O26), the unlogged payment webhooks (O27), and the breaker close/flap blind spot (O28). §15 and §14 are rewritten around it. I verified both P0-grade claims directly before publishing — reading `campaigns.py:264-285` and `followups_db.py:585-616` in full, and confirming by grep that `excludeOnHold` occurs in exactly two places and that `patch_pii_finding` audits where `patch_audio_segment_mute` does not.
9. **I softened two of that analyst's claims on scope grounds.** It reported the treatment-hold gap as "zero trace"; a `contact_events` row *is* written for every attempt, so the accurate statement is that nothing distinguishes the violating contact from a legitimate one. And it reported `patch_export_job` as unaudited alongside `patch_audio_segment_mute`; I could confirm the latter by reading the whole function but not the former, whose boundaries I did not establish, so only the verified one is asserted. It also framed the treatment-hold issue as this report's P0 — it is primarily an enforcement-correctness finding belonging to the authorization and workflow reports, and §15 says so rather than claiming it.
10. **One thing I could not verify.** `backend/.env` is untracked and holds live secrets; I did not read it. It is therefore possible that an operator's local `.env` sets `LOG_FORMAT=json` or `SENTRY_DSN`. What I can state is that nothing in the repository would tell them to: the 638-line `.env.example` that documents nearly every other knob in this system mentions neither. If a deployment does set them, O2 and O8 reduce to documentation defects — but **O1 survives regardless**, because the root-handler bug is independent of `LOG_FORMAT` for `voice_insurance`, and is only incidentally repaired for `api`.

---

## Sources

Read in full or in the cited ranges: `backend/observability.py`, `backend/request_context.py`, `backend/voice/admission.py`, `backend/voice/log_bridge.py`, `backend/agent_core/telemetry.py`, `backend/main.py` (middleware, lifespan, authz guard, health/ready/metrics, CORS, exception handlers, cited log sites), `backend/docker-compose.yml`, `backend/Dockerfile`, `backend/.env.example`, `backend/bot_runtime.py`, `backend/sql/12_crosscutting.sql`, `backend/sql/09_bot_config.sql`, `Habibi/src/routes/__root.tsx`, `Habibi/src/lib/lovable-error-reporting.ts`, `Habibi/src/api/config.ts`.

Framework semantics verified against installed sources in `backend/.venv`: `uvicorn/config.py` (`LOGGING_CONFIG`), `starlette/middleware/base.py`, `starlette/middleware/cors.py`, `starlette/middleware/gzip.py`, `anyio/_backends/_asyncio.py`.

Sibling reports cross-referenced: `14-error-handling.md` (correlation spine, log-attribution percentages), `23-e2e-workflows.md` (journey register), `21-dependency-supply-chain.md` (the absence of `opentelemetry` from requirements).
