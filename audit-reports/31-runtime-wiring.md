# 31 — Runtime configuration and feature wiring

**Scope:** `backend/` processes (API, `worker`, `bot_worker`, `voice.bot`, `voice.workers.insurance`, `mcp_server`), `backend/docker-compose.yml`, `Habibi/src` only where it gates the same capability. `PRAXIST-main/` excluded.
**Date:** 2026-09-03
**Mode:** Read-only. No application file was modified except this report.
**Method:** five parallel analysts — feature-flag, environment, dependency-injection, provider-selection, runtime-wiring — plus a parent verification pass. Every finding below was re-derived from source. Specialist claims that survived a second source check were folded in (F4 half-apply, F5 example/code polarity, F7 `ToolGrant`, F2 UI copy). Claims that failed that check were dropped.

Companion reports: [20-config-secrets.md](./20-config-secrets.md) (`APP_ENV` as the security master switch; this report is the *behaviour* half of the same split), [26-ai-integration-architecture.md](./26-ai-integration-architecture.md) (provider clients; this report is who *selects* them on which path), [04-backend-architecture.md](./04-backend-architecture.md) (process map).

This is a wiring audit. “P0” here means **two live paths that claim to be one capability and honour different configuration**, or a Studio/status surface that asserts a process that is not running. Exploitability is out of scope except where a flag’s default is the thing that decides whether a real person is dialled.

---

## Verdict

**There is no single runtime. There are five application processes and five different answers to “am I live?”, and they do not share a configuration object.**

`load_active_bundle` is the intended seam for Mouth config. The callers do not agree which environment string to pass it. WhatsApp uses `BOT_ENVIRONMENT` (default **production**). Sandbox HTTP hardcodes `"sandbox"`. Voice hardcodes `"production"`. The insurance mesh worker does not load a bundle at all — it constructs `KeepAliveAzureLLMService` from `default_tuning()`. The same spoken product is four wiring graphs.

Outbound is the opposite problem: **too many real gates, stacked, and one of them is misnamed.** `platform_switches.outbound.enabled` is a genuine kill switch at the carrier. In front of it sit `TREATMENT_MODE`, `CAMPAIGN_RUNTIME_ENABLED` (which also gates cadence *retries*, not just campaigns), `BOUNCE_VOICE_ENABLED`, and the demo button. All four can be “on” in different combinations. An operator who flips the Postgres switch off is safe. An operator who flips `CAMPAIGN_RUNTIME_ENABLED` thinking they stopped the treatment engine is not — `enact` does not read that flag.

What is already disciplined:

- Two flag *systems*, documented as different shapes: env flags in `agent_core.platform_flags` (process-lifetime, default **off**) and Postgres `platform_switches` (operator-flippable, **absence is off**, 2-second cache).
- One carrier boundary for PSTN (`voice.twilio_ops.start_outbound_call`).
- One permission table (`authz.ROUTE_PERMISSIONS`) instead of 180 `Depends` arguments.
- STT/TTS on a live call go through `voice.provider_bind` → `factory.build_first_available` with Azure fallback and provenance (report 26).
- `KNOWN_KEYS` so a typo in a switch URL cannot mint a flag nothing reads.

What is not:

- `main.py` never calls `load_env()` itself. Importing `voice.host.embedded_host_enabled` at `main.py:223-226` may publish `.env` **after** `_APP_ENV` is frozen at `:204`. `CORS_ORIGINS` at `:644` can therefore see `.env` in the same file that decided production with the OS env only. Workers `load_env()` before `import db`. Compose hides this because `env_file:` injects first.
- `AGENT_CARDS_ENABLED` is in the flag module, `.env.example`, and the default-off unit test. **Zero application readers.**
- FastAPI `Depends` is not a DI system. It is authz plus `require_admin`. Clients are module singletons and function-local `import db`.
- The frontend’s `VITE_USE_MOCK` defaults **on** in dev, so the Roles & access switch screen can be a local fiction while `bot_worker` is live.

The useful moves are local: **one environment string for Deployment selection**, **put WhatsApp sampling knobs through `AgentTuning` like sandbox already does**, **split or rename `CAMPAIGN_RUNTIME_ENABLED`**, **delete or wire `AGENT_CARDS_ENABLED`**, **call `load_env()` at the top of `main.py`**. Do not introduce a DI framework. Do not collapse the outbound gates into one boolean — they are different capabilities. Make the stack readable.

---

## Wiring map

```
Habibi UI (VITE_USE_MOCK? mock data : API_KEY + X-Actor-User-Id)
        │
        ▼
Entry points (separate OS processes unless noted)
        │
        ├─ uvicorn main:app          load_env: side-effect of embedded-host probe, AFTER APP_ENV freeze
        │     APP_ENV read at import (default "dev")
        │     db.engine created at import via _read_env_file
        │     lifespan: observability, hardening gate, init_and_seed
        │
        ├─ python -m bot_worker      load_env() before import db
        │     DB_PROCESS_ROLE=bot_worker
        │
        ├─ python -m worker          load_env() before import db
        │     DB_PROCESS_ROLE=worker
        │
        ├─ python -m voice.bot       setdefault DB_PROCESS_ROLE=voice
        │     load_env via voice.config helpers (first Azure read)
        │
        ├─ python -m voice.workers.insurance
        │     load_env inside worker boot; default_tuning() not bundle
        │
        └─ python -m mcp_server      NOT in docker-compose
              MCP_TRANSPORT=stdio|http; HTTP also needs MCP_HTTP_ENABLED

Configuration (no single object — pick a family)
        │
        ├─ APP_ENV / ENV             security + docs + actor header   default "dev"
        ├─ BOT_ENVIRONMENT           which bot_deployments row        default "production"
        ├─ BILLING_ENV               usage_events bucket              unset → "production"
        ├─ TREATMENT_MODE            engine enact                     default "shadow"
        ├─ AUTHORITY_MODE            fee matrix apply                 default "shadow"
        ├─ platform_flags.*          env, process lifetime, default off
        └─ platform_switches.*       Postgres, 2s TTL, absence = off

Provider
        │
        ├─ LLM text     azure_openai.chat_with_tools → maybe llm_gateway
        ├─ LLM voice    KeepAliveAzureLLMService (AZURE_OPENAI_VOICE_*)
        ├─ STT/TTS live factory.resolve_chain → provider_bind → Azure fallback
        ├─ STT batch    azure_speech.transcribe (always Azure)
        ├─ TTS preview  provider_tts HTTP adapters (parallel stack)
        ├─ Storage      MinIO (loopback may invent minioadmin)
        ├─ Payments     PAYMENT_PROVIDER env; webhook {provider} in URL
        └─ Telephony    Twilio only

Service → feature (same product, different graph — see table below)
```

There is no “AI orchestration” module and no DI container. A feature is whatever the entry point imported.

---

## Entry points

Compose (`backend/docker-compose.yml`) runs eight containers; five of them are application processes. `mcp_server` is a sixth entry that compose does not start.

| Process | Command | When `.env` lands in `os.environ` | `DB_PROCESS_ROLE` | `db.engine` |
|---|---|---|---|---|
| API | `uvicorn main:app` | Compose `env_file:` before exec. Bare-metal: **never via `load_env()`** — `db._read_env_file` for `DATABASE_URL` / `TENANT_ID` only | `api` (compose) or unset → `"api"` | Import-time `create_engine` |
| KB worker | `python -m worker` | `load_env()` at line 24, **before** `import db` | `worker` setdefault | Same module, after env |
| Bot worker | `python -m bot_worker` | `load_env()` at line 31, **before** `import db` | `bot_worker` | Same |
| Voice | `python -m voice.bot` | `voice.config` helpers call `load_env()` on first Azure/Speech read | `voice` setdefault | When `agent_core` imports `db` |
| Insurance mesh | `python -m voice.workers.insurance` | `load_env()` in boot | `voice` | Same |
| MCP | `python -m mcp_server` | Not composed. Stdio default. | n/a | Tools may import `db` |
| Alembic | `alembic upgrade` | Own `_database_url()` reads `DATABASE_URL` or parses `.env` | n/a | Separate engine |
| Embedded voice | opt-in inside API | `VOICE_EMBEDDED_HOST` — same process as uvicorn | `api` | Shared with API |

The E402 club in `ruff.toml` (`bot_worker.py`, `worker.py`, `voice/bot.py`, `voice/spike.py`, `voice/workers/*.py`, `scripts/*.py`) is the documented init-order dependency: **`DB_PROCESS_ROLE` and `load_env()` must run before `import db`**, because `db.py` binds `statement_timeout` and `app.tenant_id` at `create_engine`. Importing `db` first freezes the wrong timeout for that process. The API is the exception that proves the rule: it never calls `load_env()`, and it reads `_APP_ENV` at import (`main.py:204-205`) from whatever the OS already had.

`load_env()` itself is once-only (`env_loader.py:9-14`) and **non-destructive** (existing `os.environ` wins). The first caller in a process decides whether `.env` is published. A module that `import db`s first and `load_env()`s later cannot change `DATABASE_URL` or `TENANT_ID` already captured at import.

---

## Five answers to “am I live?”

These are not aliases. They default in opposite directions and select different rows.

| Question | Variable | Default if unset | Who honours it |
|---|---|---|---|
| Is this production *security*? | `APP_ENV` (also `ENV` in `env_utils.env_name`) | `"dev"` — permissive | Hardening gate, API-key requirement, actor header, OpenAPI docs, MinIO credential fallback, payments sandbox “Mark paid” button |
| Which Deployment row? | `BOT_ENVIRONMENT` | `"production"` | WhatsApp `bot_runtime` via `load_active_bundle(bot_jobs.bot_environment())` |
| Which usage invoice? | `BILLING_ENV` then `APP_ENV` | `"production"` | `usage_meter._billing_env` — opposite default to `env_name()` on purpose (`usage_meter.py:274-293`) |
| May the treatment engine *act*? | `TREATMENT_MODE` | `"shadow"` | `treatment.enact` no-ops unless `"live"` |
| May the fee matrix *post*? | `AUTHORITY_MODE` | `"shadow"` | `agent_core.authority.config.mode` |

Voice does not read `BOT_ENVIRONMENT`. It passes the literal `"production"` (`voice/bot.py:423`). Sandbox HTTP passes the literal `"sandbox"` (`sandbox_runtime.py:528-530`). The frontend in a Vite dev build does not read any of these: `VITE_USE_MOCK` defaults **true** (`Habibi/src/api/config.ts:21-22`), so the screen is a third environment that never reaches Postgres.

`BOT_ENVIRONMENT=production` next to `APP_ENV=dev` is the committed template (`.env.example:101` and `:172` in report 20). A laptop that turns `BOT_RUNTIME_ENABLED` on loads the production prompt.

---

## Feature-flag inventory

### System A — `agent_core.platform_flags` (env, process lifetime, default off)

Contract: `platform_flags.py:1-7`. “Do not invent a new name in a feature PR — add it here and in `.env.example`.” Truth test: `_flag` is empty → `False`. Changing a flag requires restarting **every** process that imported the module.

| Flag | Readers (application) | Owner | Live? |
|---|---|---|---|
| `AGENT_CARDS_ENABLED` | **none** (definition + `tests/test_platform_flags.py` only) | none | **Stale.** `.env.example:309` still documents it |
| `MCP_HTTP_ENABLED` | `mcp_server.py:87-90`, `mcp_http/http_app.py:104`, `main.py:2540` (status) | MCP process, not compose | Default off. Status can say `httpEnabled: true` with no listener |
| `MCP_CLIENT_ENABLED` | `connectors/persist.py`, `cards/compile.py`, `skills/intersect.py` | connectors | Default off |
| `MCP_TASKS_ENABLED` | `mcp_http/tasks.py`, `mcp_http/protocol.py`, `worker.py:363` | worker drain + protocol | Default off |
| `MCP_APPS_ENABLED` | `mcp_http/protocol.py`, `main.py:2543` | protocol | Default off |
| `A2A_ENABLED` | `agent_core/a2a.py`, `cards/compile.py:902` | A2A surface | Default off |
| `EVAL_GATE_ENABLED` | `cards/compile.py:716` | card publish | Default off — gate is a no-op until flipped |
| `REDTEAM_GATE_ENABLED` | `cards/compile.py:718` | card publish | Default off |
| `LLM_GATEWAY_ENABLED` | `llm_gateway/client.py:188`, `azure_openai.py:619-634`, `main.py:2576` | text client only | Default off. Voice does not call `maybe_chat` |
| `VISION_INGEST_ENABLED` | `agent_core/vision.py:34` | ingest route | Default off |
| `TEMPORAL_ENABLED` | `work_runtime/api.py:11` | workflow adapter | Default off → `adapter_pg` |
| `POLICY_EXPORT_ENABLED` | `agent_core/policy_export.py:16` | export | Default off |
| `OUTBOUND_EVAL_GATE_ENABLED` | `cards/compile.py:461-464` | card publish G-OB9 | Default off. **Missing from `test_platform_flags` parametrize** |
| `CAMPAIGN_RUNTIME_ENABLED` | `campaigns.enabled`, `cadence.enabled` | bot_worker loops | Default off. **Also missing from that parametrize.** Name does not mention cadence |

`tests/test_platform_flags.py:10-25` locks the original factory list. Two flags added later (`OUTBOUND_EVAL_GATE_ENABLED`, `CAMPAIGN_RUNTIME_ENABLED`) are not in it. The module’s own comment is the owner; the test did not keep up.

### System B — `platform_switches` (Postgres, fail closed)

| Key | Readers | Writers | Default |
|---|---|---|---|
| `outbound.enabled` | `voice.twilio_ops.start_outbound_call:314` (carrier), `main.py` demo + status | `set_enabled` via Roles & access; `KNOWN_KEYS` 404s unknown keys | Absence / error → **off** |
| `outbound.demo_ignores_window` | Demo target + POST only | Same | Absence → **off**. Does not waive consent/DND |

Cache TTL is 2 seconds (`platform_switches.py:88`). Writes invalidate in-process; the other three processes converge within the TTL. That is a stated property of the control, not a bug.

### System C — env booleans that never joined `platform_flags`

| Name | Default | Readers | Notes |
|---|---|---|---|
| `BOT_RUNTIME_ENABLED` | off | `bot_jobs.bot_runtime_enabled` — enqueue + `bot_worker` drain | WhatsApp **outbound jobs still drain** when this is off (`.env.example:107-108`) |
| `BOUNCE_VOICE_ENABLED` | off | `payment_events.bounce_voice_enabled` | Third outbound on-ramp. Called out in the switches migration as a thing the DB switch was meant to sit *in front of*, not replace |
| `VOICE_EMBEDDED_HOST` | off | `voice.host.embedded_host_enabled` | In-process Pipecat vs `:7860` |
| `VOICE_WS_VIA_API` | **on** | `voice.ws_proxy`, `twilio_ops` | Compose sets `true` on the API. Unset means proxy, not direct |
| `VOICE_MULTI_AGENT_ENABLED` | off | `voice.config`; compose **forces `true`** on `voice` and `voice_insurance` | Compose disagrees with `.env.example` |
| `VOICE_LATENCY_OBSERVER` | **on** (`_flag_default_on`) | `voice.config` | Opposite polarity to platform_flags |
| `VOICE_TURN_AUDIO` | sandbox-dependent | `voice.config.voice_turn_audio` | Unset → on for sandbox, off for production calls |
| `TREATMENT_SWEEP` | off | `treatment/sweep.py` | Book sweep; independent of `TREATMENT_MODE=live` except `MODE_OFF` |
| `ALLOW_UNHARDENED_PRODUCTION` | off | `main.py:_assert_hardening_gate` | Only meaningful when `APP_ENV` is already prod |
| `ALLOW_ACTOR_HEADER` | derived from `APP_ENV` | `actor_context._allow_actor_header` | Unset is not off — it is “non-prod allows spoofing” |

Three boolean parsers disagree about the empty string: `_flag` (off), `_flag_default_on` (on), `ALLOW_ACTOR_HEADER` (follow `APP_ENV`). A fourth, `VOICE_TURN_AUDIO`, is a function of the session kind.

### Frontend flags that do not share identifiers

| Frontend | Backend | Agreement |
|---|---|---|
| `VITE_USE_MOCK` (dev default **true**) | none | Parallel fake API. Platform switch mutations in mock never reach `platform_switches` |
| `VITE_API_KEY` / `VITE_ACTOR_USER_ID` | `API_KEY` / `X-Actor-User-Id` | Wired only when mock is off |
| `VITE_AUTHORITY_*` | `AUTHORITY_*` env | `Habibi/src/api/authority.ts:6-18` documents that a browser copy goes stale; the verdict is the server’s. The Vite bindings still exist for the mock matrix |
| `OUTBOUND_ENABLED` constant in `platform.ts` | `platform_switches.OUTBOUND_ENABLED` | Same string when mock is off |

---

## Same capability, different wiring

### Mouth turn (LLM + prompt + knobs)

| Path | Entry | Init | Config | Provider | Knobs |
|---|---|---|---|---|---|
| WhatsApp bot reply | `bot_worker` | `load_env()` then `db` | `load_active_bundle(bot_jobs.bot_environment())` default **production** | `azure_openai.chat_with_tools` → optional LiteLLM | **Hardcoded** `temperature=0.2`, `max_completion_tokens=500` (`bot_runtime.py:965-969`) |
| Sandbox text | API `POST /sandbox/runs/.../turns` | no `load_env` | `load_active_bundle("sandbox")` | same `chat_with_tools` | `AgentTuning.llm.temperature` (`sandbox_runtime.py:783-784`) |
| Voice call | `voice.bot` (or embedded host) | `voice.config.load_env` on first credential | Live: `load_active_bundle("production")`. Sandbox session: `resolve_prompt_bundle(..., environment="sandbox")` | `KeepAliveAzureLLMService` from `AZURE_OPENAI_VOICE_*` | `AgentTuning` via `tuning_apply` |
| Insurance mesh | `voice.workers.insurance` | `load_env` in boot | **`default_tuning()` — no bundle** | same KeepAlive Azure constructor | Defaults, not the published card |

Report 26 already said WhatsApp ignores `AgentTuning.llm`. Re-verified: `bot_runtime.py:968` still passes `temperature=0.2`. Sandbox does not. Voice does, through a different object (`tuning_apply.build_llm_settings_kwargs`). The insurance sidecar is a fourth answer: no card at all.

LiteLLM (`LLM_GATEWAY_ENABLED`) wraps `chat_with_tools` only (`azure_openai.py:617-634`). `maybe_chat` returns `None` unless the flag is on **and** `LITELLM_BASE_URL` or `LLM_GATEWAY_URL` is set (`llm_gateway/client.py:186-189`). Voice never enters that function. `/mcp/status`-style `/llm` status on the API can show the gateway “enabled” in a process that does not serve voice.

### Outbound PSTN

```
demo button ─────────────┐
bounce voice (env) ──────┤
cadence retry (CAMPAIGN_RUNTIME_ENABLED) ─┐
campaign run (same flag) ─┤
treatment enact (TREATMENT_MODE=live) ────┤
                                          ▼
                         outbound.place → contact_policy.admit
                                          ▼
                         twilio_ops.start_outbound_call
                                          ▼
                         platform_switches.outbound.enabled   ← only carrier gate
                                          ▼
                         Twilio REST
```

| On-ramp | Gate in front of `place` | Still needs DB switch? |
|---|---|---|
| Treatment executor | `TREATMENT_MODE == live` (`enact.py:60`, `:906`) | yes |
| Campaign runner | `CAMPAIGN_RUNTIME_ENABLED` (`campaigns.py:461`) | yes |
| Cadence retry | **same** `CAMPAIGN_RUNTIME_ENABLED` (`cadence.py:349`) | yes |
| Bounce last-resort voice | `BOUNCE_VOICE_ENABLED` (`payment_events.py:48-49`, `:924`) | yes |
| Demo button | none of the env flags; `outbound_enabled()` then contact-policy with optional window waiver (`main.py:4046-4107`) | yes |

`.env.example:592-593` states the campaign/cadence sharing on purpose: “the treatment engine’s own executor is still gated by `TREATMENT_MODE`.” That is honest. The flag *name* is not: turning “campaign runtime” off also stops retries on missions already in flight. An operator debugging a stuck second attempt will not look at a campaign flag.

The demo path is the one that is *not* an env flag, by design (`platform_switches.py:41-55`). It still cannot outrun the carrier switch.

The Roles UI overstates the DB switch. Confirm copy at `Habibi/src/components/platform/OutboundControlPanel.tsx:87` says turning it on “authorises the treatment executor, the campaign runner and the bounce autodial.” Necessary, not sufficient: those three paths still need their own env flags. `.env.example:584-590` is the accurate text. Under `VITE_USE_MOCK` the mock payload lists only `outbound.enabled` (`platform.ts:74-83`) — `demo_ignores_window` is missing from the fiction.

### Voice hosting (same `voice.bot.bot`)

| Mode | How Twilio / browser reaches the pipeline | Compose default |
|---|---|---|
| Standalone runner | `:7860` | `voice` service command |
| API proxy | `VOICE_WS_VIA_API=true` (default) — Twilio hits API `/ws`, proxied | API env sets `"true"` |
| Embedded host | `VOICE_EMBEDDED_HOST=true` — API serves `/ws` and `/voice-rtc` in-process | **off** in `.env.example:336` |

`voice/host.py:3-20` exists to close the dual-port footgun. Compose still runs the dual-port layout. Both funnel into the same `bot()`; transport construction cannot drift. Session store can: API and voice share a named volume only so the *filesystem fallback* of `voice_session_store` still works (`docker-compose.yml:98-102`). The happy path is Postgres.

### Storage

`storage._cfg` (`storage.py:34-73`): MinIO is the only object store. There is no filesystem provider for KB originals — upload raises `StorageUnavailable` if unset. Voice recordings are a second selector: MinIO if configured, else `local://recordings/...` on disk (`voice/recording.py`). KB hard-requires MinIO; audio does not. Unset credentials fall back to `minioadmin` **only** when the endpoint is loopback and `APP_ENV` is not prod.

### Payments

Two selection mechanisms:

1. Env `PAYMENT_PROVIDER` (`hosted` | `razorpay`, default hosted) — `payments.provider()`.
2. URL `POST /webhooks/payments/{provider}` — the path segment chooses the HMAC secret (`payments.webhook_secret`).

`checkout_url` with `PAYMENT_PROVIDER=razorpay` **still returns the hosted `/pay/{token}` URL** and logs that order creation is stubbed (`payments.py:54-59`). The intent may record `provider='razorpay'` so webhooks can match. The operator-visible “we are on Razorpay” and the URL the borrower opens disagree.

Sandbox “Mark paid” is gated on `not is_production() and provider() == "hosted"` (`payments.py:445`), and `is_production()` calls `load_env()` then `APP_ENV`. The API process’s `_IS_PROD` does **not** call `load_env()`. On bare metal those two can disagree.

### Work runtime

`work_runtime.api._adapter` (`work_runtime/api.py:10-17`): `TEMPORAL_ENABLED` → Temporal adapter, else Postgres. Call sites do not know. Default is Postgres. There is no Temporal service in compose. The flag is a future seam, not a running path.

---

## Findings

### F1 · P0 · Four Mouth wirings for one Deployment

**Evidence:** `bot_runtime.py:712-717, 965-969`; `sandbox_runtime.py:528-531, 783-784`; `voice/bot.py:402-423`; `voice/workers/insurance.py:36-50`; `agent_core/deployment.py:1-4`.

`load_active_bundle`’s docstring says sandbox / WhatsApp / voice “cannot drift.” They drift on the *argument*. WhatsApp sampling knobs never reach Azure. The insurance sidecar never reaches the card. LiteLLM is a fifth, text-only, default-off overlay. Gateway canary “promote to voice” writes `LLM_GATEWAY_VOICE_MODEL` (`llm_gateway/canary.py`); the voice process has no `llm_gateway` import.

If `LLM_GATEWAY_ENABLED` is on but `maybe_chat` returns `None` or throws, Azure still serves the turn and metering labels it `llm_gateway.*` because `_gw_on()` is read after the kill-switch (`azure_openai.py:617-725`). The flag being on is not the same as the gateway having served.

**Fix shape:** One helper `active_environment() -> str` used by all three Mouth loaders. Pass `AgentTuning.llm` into `bot_runtime` the way sandbox already does. Either load the bundle in the insurance worker or stop calling it a Mouth peer. Meter the client that actually answered.

### F2 · P0 · Outbound on-ramps share a carrier and not a name

**Evidence:** `voice/twilio_ops.py:307-318`; `campaigns.py:60-63, 453-461`; `cadence.py:66-69, 341-349`; `agent_core/treatment/enact.py:60, 904-906`; `payment_events.py:48-49`; `main.py:4046`; `.env.example:584-593`.

The DB switch is the right last gate. The env flags in front of it are capability-shaped and should stay separate. `CAMPAIGN_RUNTIME_ENABLED` gating cadence is the inconsistency: same flag, different feature, easy to disable retries while debugging “campaigns.” The UI confirm (F2 paragraph above) sells the last gate as the only gate.

**Fix shape:** Rename to something that says “timer dials” or split `CADENCE_RUNTIME_ENABLED`. Do not teach the treatment engine to read the campaign flag. Fix the confirm copy to match `.env.example:584-590`.

### F3 · P0 · Opposite defaults for “environment”

**Evidence:** `env_utils.py:36-38` (`APP_ENV`/`ENV` → `dev`); `bot_jobs.py:39-40` (`BOT_ENVIRONMENT` → `production`); `usage_meter.py:291-293` (unset → `production`); `treatment/config.py:64` (shadow); `authority/config.py:29` (shadow); `Habibi/src/api/config.ts:21-22` (mock on).

This is not accidental on billing — the comment at `usage_meter.py:283-289` explains the opposite default. It *is* accidental that WhatsApp’s Deployment selector defaults to production on the same laptop whose security posture defaults to dev.

**Fix shape:** `BOT_ENVIRONMENT` should default to `APP_ENV` (or to `sandbox` when `APP_ENV` is in `NON_PROD_ENVS`). Leave billing’s opposite default; it is tested (`tests/test_usage_meter_billing_env.py`).

### F4 · P1 · `load_env` is not an initialization path; it is a per-module habit

**Evidence:** `env_loader.py`; `main.py:204-226, 644`; `bot_worker.py:29-31`; `worker.py:22-24`; `db.py:52-93, 138-150`; `voice_sandbox.py:33-35`; `alembic/env.py:24-34`; `ruff.toml` E402 list.

Workers publish `.env` then import `db`. The API imports `db` at the top, freezes `_APP_ENV` / `_MAX_UPLOAD_BYTES`, then may call `load_env()` as a side effect of `embedded_host_enabled()` (`main.py:223-226`). After that, `CORS_ORIGINS` at `:644` sees `.env`; `_IS_PROD` does not. That is half-applied configuration in one module.

`db._read_env_file` covers `DATABASE_URL` and `TENANT_ID`. `ACTOR_USER_ID` at `db.py:93` is import-time `getenv` only — no file peek. `actor_context.default_actor_user_id` is call-time. If the actor is only in `.env`, `db.ACTOR_USER_ID` and the ContextVar fallback can disagree. `voice_sandbox.py:33-35` freezes `VOICE_RUNNER_URL` at import with no `load_env`; compose overrides it, bare-metal `.env` does not.

Four grammars parse the same file: `env_loader`, `db._read_env_file`, `seed_postgres.read_env`, `alembic/env.py`. Report 20 called the APP_ENV half C4. Here it is also why CORS, actor, and runner URL can disagree with the security gate inside one API process.

### F5 · P1 · Stale and unowned flags

**Evidence:** `agent_cards_enabled` — only `platform_flags.py:18-19` and the default-off test. `test_platform_flags.py` omits `campaign_runtime_enabled` and `outbound_eval_gate_enabled`. `.env.example:309` still ships `AGENT_CARDS_ENABLED=false`.

A flag with no reader is worse than no flag: the template claims a kill switch for Agent Cards that does not exist. Cards compile and serve regardless.

Three live flags have the opposite polarity problem — `.env.example` says `true`, code treats unset as **off**:

| Flag | Example | Unset in code |
|---|---|---|
| `UNDERSTANDING_LLM_ENABLED` | `:237` true | `understanding.py:220` false |
| `KB_GAP_CAPTURE_ENABLED` | `:141` true | `agent_core/tools/kb.py:58` false |
| `VOICE_MULTI_AGENT_ENABLED` | `:379` true | `voice/config.py:136-137` false (compose forces true) |

A deploy that omits those keys, or a process that never loaded `.env`, silently disables features the template says are on. `TREATMENT_SWEEP` and `TURN_CRITIC_ENABLED` are live worker gates and are **absent** from `.env.example`. `RECO_MODE` is a sixth shadow/live axis (`reco/config.py`), sibling of `TREATMENT_MODE` / `AUTHORITY_MODE`, not listed in the “am I live?” table because it does not dial — it still decides whether recommendations enact.

### F6 · P1 · Voice is one function and three hosts

**Evidence:** `voice/host.py:1-30`; `docker-compose.yml:82-91, 186-218`; `VOICE_WS_VIA_API` default true (`voice/ws_proxy.py:35`); compose **and** `.env.example:379` set `VOICE_MULTI_AGENT_ENABLED=true` while code unset is off.

The dual-port layout is documented as the thing embedded host replaces. Production compose still is the dual-port layout. That is an operator-wiring trap (two healthchecks, two logs, one named volume for a degraded session store), not a logic bug in `bot()`.

### F7 · P1 · There is no dependency-injection system

**Evidence:** `Depends(` appears twice in application code — `main.py:585` (`_authz_guard` on the app) and `main.py:2940` (`require_admin` on TTS catalog sync). No `app.dependency_overrides` in tests. `db.engine` is a module global (`db.py:138`). Azure clients: sync singleton `azure_openai.py:23-36` **and** a second async singleton `voice/llm_pool.py:30`. `storage._cached_client` similarly. `platform_switches._cache` is a process-local dict. Agent-core tools `import db` inside functions to break cycles.

`_authz_guard` is the one piece of DI that is doing real work: one registry, websocket-safe `HTTPConnection`, tests that fail if a route is missing (`main.py:508-532`). Everything else is imports. Tests patch whatever name the test file imported. Patching `azure_openai.get_client` does not move a voice turn — that process uses `voice.llm_pool`.

`agent_core.tools.grant.ToolGrant` documents “Nothing imports this yet” (`grant.py:30-31`). Live tool dispatch is three handler maps: `bot_tools.HANDLERS` (WhatsApp/sandbox), `voice/tools.py` (Pipecat), `mcp_tools.HANDLERS` (MCP). Same catalog schema, three implementations. “Current deployment” is also two APIs: `load_active_bundle` (prompt+tuning+card) vs `db.get_active_deployment` (row) on CRM routes.

Do not add a container. Do add constructors that go through one function per capability (the STT/TTS factory is the model; the LLM path and `ToolGrant` are not).

### F8 · P2 · MCP status is on the API; the server is not in compose

**Evidence:** `mcp_server.py:1-24, 82-98`; `docker-compose.yml` (no `mcp` service); `main.py:2532-2543`.

`GET /mcp/status` reports `httpEnabled` from the API process’s env. The HTTP listener is a different process that must be started by hand, and only if `MCP_TRANSPORT=http` **and** `MCP_HTTP_ENABLED` **and** `MCP_API_KEY`. Two flags plus a transport enum for one socket. The status payload can describe a URL nothing binds.

### F9 · P2 · Razorpay is selected twice and honoured once

**Evidence:** `payments.py:34-59`; `main.py:825-838`.

Env selects checkout (then stubs it). The webhook URL selects HMAC. The borrower still opens `/pay/{token}`.

### F10 · P2 · Observability is an API lifespan concern

**Evidence:** `main.py:422-428` (`observability.setup_logging` first in lifespan). `bot_worker.py:48-51` and `worker.py:29-32` use `logging.basicConfig`. Voice uses loguru. Metering still runs in workers via `usage_meter` lazy `load_env()`, so spend is recorded; the *shape* of logs is not shared. Request-id ContextVar is an HTTP middleware (`main.py:321-344`) and does not exist on a `bot_worker` turn unless something else binds it.

---

## Import-time side effects (hidden dependencies)

| Module | Runs at import | Depends on happening first |
|---|---|---|
| `main.py` | `_APP_ENV`, `_IS_PROD`, `_MAX_UPLOAD_BYTES`; then maybe `load_env` via embedded host; then `_cors_origins` | Compose env, or the probe’s later `load_env` for CORS only |
| `db.py` | `create_engine` with GUC + statement_timeout from `DB_PROCESS_ROLE`; `ACTOR_USER_ID` getenv-only | `DB_PROCESS_ROLE` setdefault in workers; `DATABASE_URL`/`TENANT_ID` via getenv or `_read_env_file` |
| `voice_sandbox.py` | `_RUNNER_URL` / `_WEBRTC_PUBLIC` | Compose `VOICE_RUNNER_URL`; not `.env` on bare metal |
| `azure_openai.py` | locks, not the client | Client on first `get_client()`; that calls `load_env()` |
| `actor_context.py` | ContextVar default; `API_KEY_MAP` cache lazy | `APP_ENV` at call time for header spoofing |
| `platform_switches` | empty cache | First `is_enabled` imports `db` |
| `voice/bot.py` | `sys.path` insert, `DB_PROCESS_ROLE` setdefault | Must precede `import db` through `agent_core` |

`db.py:64-66` is explicit: importing `db` must not publish the whole `.env`. That is why the API’s `APP_ENV` can stay unset while `DATABASE_URL` is correct. It is a carefully drawn hole.

---

## What not to do

- Do not “asyncify” or wrap `db.engine` in a DI container.
- Do not merge `TREATMENT_MODE`, `CAMPAIGN_RUNTIME_ENABLED`, and `BOUNCE_VOICE_ENABLED` into one env var. The Postgres switch is already the one operator-facing master.
- Do not enable `AGENT_CARDS_ENABLED` in compose thinking it gates Studio. It gates nothing.
- Do not point the Bindings tab’s LLM slot at `LLM_GATEWAY_ENABLED` and call it done (report 26). Gateway is text-only and default off.
- Do not set `BOT_ENVIRONMENT=dev` without a matching `bot_deployments` row — `load_active_bundle` raises `active_deployment_not_found` and the WhatsApp job fails. The default is production because that row exists.

---

## Prioritized consolidation

1. **`load_env()` at the top of `main.py` before `_APP_ENV`.** Same fix as report 20 C4. Makes the API honour `.env` the way workers already do. One line, process-agreement.
2. **Deployment environment helper.** WhatsApp, voice, and sandbox pass one function’s result into `load_active_bundle`. Stop hardcoding `"production"` in `voice/bot.py:423` and stop defaulting `BOT_ENVIRONMENT` to production on a `dev` laptop.
3. **WhatsApp `chat_with_tools` reads `AgentTuning.llm`.** Copy the sandbox lines. Delete the `0.2` / `500` literals.
4. **Rename or split `CAMPAIGN_RUNTIME_ENABLED`.** Cadence retries are not a campaign. Keep the DB outbound switch where it is.
5. **Delete `AGENT_CARDS_ENABLED` from `platform_flags`, `.env.example`, and the test parametrize — or give it a reader that actually skips card compile.** A documented no-op is a lie on the operator template.
6. **Add the two newer flags to `test_platform_flags`.** Cheap lock so the next name cannot land undocumented.
7. **Align `.env.example` polarity with code.** `UNDERSTANDING_LLM_ENABLED`, `KB_GAP_CAPTURE_ENABLED`, and `VOICE_MULTI_AGENT_ENABLED` say `true` in the template and `false` when unset. Document `TREATMENT_SWEEP` and `TURN_CRITIC_ENABLED` or delete the gates.
8. **Meter the client that answered.** `azure_openai.py:718-725` must not label Azure traffic `llm_gateway.*` because the flag is on.
9. **Compose: either start `mcp_server` or stop reporting `httpUrl` from the API.** Status without a process is Studio-class fiction (report 26’s LLM binding).
10. **Leave STT/TTS bind, `KNOWN_KEYS`, `authz.ROUTE_PERMISSIONS`, and billing’s opposite default alone.** Those seams hold.

---

## Appendix — compose vs laptop

| Setting | `.env.example` | `docker-compose.yml` `environment:` |
|---|---|---|
| `APP_ENV` | `dev` (file) | not set — file wins |
| `BOT_ENVIRONMENT` | `production` | not set |
| `CAMPAIGN_RUNTIME_ENABLED` | `false` | not set |
| `VOICE_EMBEDDED_HOST` | `false` | not set |
| `VOICE_WS_VIA_API` | (default true in code) | API: `"true"` |
| `VOICE_MULTI_AGENT_ENABLED` | `true` (`:379`; code unset = off) | voice + insurance: `"true"` |
| `VOICE_RUNNER_URL` | — | API: `http://voice:7860` |
| MCP | documented, not a service | **no service** |

Compose is the source of truth for “which processes exist.” `.env.example` is the source of truth for flag polarity. They disagree on multi-agent and they both omit MCP. A laptop `uvicorn` plus a laptop `python -m voice.bot` is a third topology (no `VOICE_RUNNER_URL` override unless the operator sets it). Three topologies, one `bot()` function — that part is the success. The configuration that *finds* that function is the drift.
