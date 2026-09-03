# 20 — Configuration and Secret Management

**Audit date:** 2026-09-02
**Scope:** every configuration source and every secret-handling path — env files, config modules, container and CI descriptors, the frontend build surface, and the log/response/database sinks a secret can escape through.
**Redaction:** no secret value appears in this report. Credentials are named, located, and described by *shape* only, and marked `[REDACTED SECRET]` where a value would otherwise appear. One class of value is quoted verbatim and deliberately: the two `dev-*-not-for-prod` constants that are already committed to this repository in cleartext, because the whole point of the finding is that they are public.

**Method.** Four analysts ran in parallel — environment, configuration architecture, secret exposure, deployment — each required to cite `file:line` it had actually read. A fifth thread was run directly against the tree: git history, the `APP_ENV` chain, and an AST re-derivation of the config-spread metrics.

All four returned; the configuration-architecture analyst arrived last, after a first draft was written, and **changed the report's top recommendation** — see C4, which is why the fix for C1 is not the one-line change it first appeared to be.

Every Critical and every High was re-verified against source by hand. Five claims did not survive that check and are corrected under "Corrections made during verification" — including two of my own drafts. Counts are derived, not estimated, and where two analysts measured the same thing by different methods, both numbers and both methods are given rather than one being silently chosen.

---

## Verdict

**This audit has one root cause and it explains most of the report.**

`APP_ENV` is the master switch for every fail-closed path in the system. Its default is the *permissive* value:

```python
# backend/env_utils.py:38
return (os.getenv("APP_ENV") or os.getenv("ENV") or "dev").strip().lower()

# backend/main.py:204-205
_APP_ENV = (os.getenv("APP_ENV") or "dev").strip().lower()
_IS_PROD = _APP_ENV in {"prod", "production"}
```

Forgetting the variable, or setting it wrong, does not fail — it silently selects the development branch of **nine separate controls**. And the variable is read and re-interpreted in **eleven different files**, so there is no single place to fix it.

That would be a latent design problem in most repositories. Here it is live, because of what the deployment's own `.env` says:

| `backend/.env` | Value | What it means |
|---|---|---|
| `:145` `APP_ENV` | `dev` | every guard below is in its permissive branch |
| `:149` `API_KEY` | *(empty)* | authentication off |
| `:154` `API_KEY_MAP` | *(empty)* | authentication off |
| `:165` `CORS_ORIGINS` | *(empty)* | localhost regex + `allow_credentials` |
| `:64` `BILLING_ENV` | `production` | |
| `:75` `BOT_ENVIRONMENT` | `production` | |
| `:266` `TREATMENT_MODE` | `live` | the treatment engine is enacting real dials |
| `:25` `PUBLIC_BASE_URL` | a public HTTPS tunnel | reachable from the internet |
| `:207` `VOICE_WS_PROXY_SECRET` | `[REDACTED SECRET]` (set) | configured, and never enforced |

**One file declares this deployment to be a laptop in the only variable that gates security, and production in every variable that gates behaviour.** It is dialling real borrowers, billing as production, and running the treatment engine live, through a public URL, with authentication disabled.

### The two families

**Family A — the deployment is open.** C1, C2, C3. Anyone who learns the tunnel URL has unauthenticated read/write on a regulated debt-collections CRM, can choose which user their writes are attributed to, and can open the voice media-stream socket. These are live today, not hypothetical.

**And C4 is the reason Family A is hard to close:** on the documented bare-metal launch path the API decides whether it is in production *before it has read `.env`*. The obvious remedy for C1 — set `APP_ENV=production` — does nothing there, silently.

**Family B — the guards are real but reachable around.** H1, H2, H3, and the `NON_PROD_ENVS` design. This codebase has genuinely good defensive instincts — an explicit *allow*-list rather than a deny-list for non-production environments, a `/ready` DB path that refuses to stringify its own DSN, a MinIO fallback gated on an observable property rather than a variable. The failures are that the same care was not applied to the sibling path (`storage.ping` next to `db.readiness`), or that a shipped template walks around the guard from outside (H1).

### If only five things are fixed

1. **`.env:145` → `APP_ENV=production`, *and* make `main.py` load `.env` before it decides.** Setting the variable alone is not sufficient: on the documented non-container launch path `main.py` reads `APP_ENV` before `.env` has been loaded at all (**C4**), so the change is silently inert. Both halves, or neither works.
2. **`main.py:292`** — stop deriving `auth_required` from whether credentials happen to be configured. Absent credentials must be a refusal, not a mode. (one line)
3. **`main.py:3479`** — the voice WS gate's final `return True`. `VOICE_WS_PROXY_SECRET` is *already configured* at `.env:207`; require it unconditionally. (one line)
4. **`.env.example:326`** — comment out `SKILL_PLATFORM_KEY`, exactly as `VAULT_MASTER_KEY` is already commented out at `:290`. This is the one Family-B finding that survives fixing `APP_ENV`. (one character)
5. **`pii_redact.py:42-58`** — add credential detectors, and run them over `extra` fields and tracebacks in `observability.py:367-377`, not just `message`.

Four of these five are one-line changes. None needs a shadow period.

---

## Findings — Critical

### C1 · `APP_ENV` defaults to the permissive branch, and the live `.env` selects it

**Evidence:** `backend/env_utils.py:38`, `backend/main.py:204-205`, `backend/actor_context.py:55`, `backend/payments.py:40`, `backend/storage.py:46` — five independent re-implementations of the same default. `backend/.env:145` sets `APP_ENV=dev`. Neither compose file sets `APP_ENV` in any `environment:` block; it reaches containers only through `env_file: - .env` (`docker-compose.yml:80-81, 141-142, 170-171, 194-195, 228-229`), and the committed template also ships `APP_ENV=dev` (`.env.example:172`).

**What flips permissive:**

| # | Control | Evidence | Behaviour when not prod |
|---|---|---|---|
| 1 | Unhardened-deploy gate | `main.py:400-403` | `if not _IS_PROD: return` — the "RLS / PII encryption / append-only audit are inactive, refuse to boot" guard never fires |
| 2 | API-key requirement | `main.py:431-435` | the `RuntimeError` is inside `if _IS_PROD`; otherwise a `logger.warning` and boot continues |
| 3 | Actor-header spoofing | `actor_context.py:58-65` | `return not _app_is_prod()` — `X-Actor-User-Id` is honoured |
| 4 | Unauthenticated actor path | `actor_context.py:201-214` | prod returns `unauthorized`; non-prod accepts any existing `users.id` from the header |
| 5 | OpenAPI exposure | `main.py:588-590` | `/docs`, `/redoc`, `/openapi.json` published |
| 6 | Twilio webhook signature | `main.py:3387-3396` | missing signature → `return not _IS_PROD` — **fails open** |
| 7 | Voice media-stream WS gate | `main.py:3471-3479` | see C3 |
| 8 | Payment "mark paid" control | `payments.py:444-452` | renders a `POST /pay/{token}/complete` sandbox form on the public payment page |
| 9 | Sandbox payment-event ingest | `main.py:882-893` | `if payments.is_production(): raise 403` — otherwise arbitrary payment events enter the same `ingest()` the HMAC webhook uses |
| 10 | Actor-config validation | `main.py:444-448` | an invalid identity config is downgraded to a warning |
| 11 | Dev signing / vault keys | `sign.py:35-43`, `seal.py:42-52` | the committed `dev-*-not-for-prod` constants are accepted |

**Mechanism.** The failure trigger is *omission*, and the failure signal is a log line. A deployment that copies `.env.example` (the documented bootstrap at `docker-compose.yml:13-16`) inherits `APP_ENV=dev`; a deployment that forgets the variable entirely gets the same thing. In this repository's `.env` it is set explicitly to `dev` while seven sibling variables declare production.

**Why Critical:** eleven controls, one variable, silent, and currently selected on a deployment that is dialling real borrowers through a public tunnel.

---

### C2 · Empty `API_KEY` / `API_KEY_MAP` disables authentication, route permissions, and per-role visibility — and lets the caller pick their audit identity

**Evidence:**

```python
# backend/main.py:291-292
single = (os.getenv("API_KEY") or "").strip()
auth_required = bool(single or key_map)      # both unset ⇒ False
# main.py:294 — the 401 is guarded by `if auth_required and not provided`
```

`backend/.env:149` and `:154` are both empty — two of only five empty-valued entries in the entire 452-line file.

Three modules read the same two variables and each turns itself off:

- `main.py:291-294` — the auth middleware returns before any 401.
- `authz.py:631-639` — `enforcement_enabled()` falls through the same expression; route permission checks off.
- `visibility.py:92-100` — defers to `authz.enforcement_enabled()`; per-role customer scoping off, `resolve()` returns `ALL` with reason "enforcement disabled".
- `main.py:741-750` — `require_admin()` no-ops.

**The impersonation half.** `main.py:297-300` still calls `resolve_authenticated_actor()` with an empty key. At `actor_context.py:206`, `if actor_header and _allow_actor_header()` — and `_allow_actor_header()` (`actor_context.py:58-65`) defaults to `not _app_is_prod()`, which is `True` under C1. So an anonymous caller sends `X-Actor-User-Id: <any valid users.id>` and is authenticated as that user; `db._actor_user_id()` then writes the forged identity into the audit trail. With no header at all it falls to the hardcoded default actor at `actor_context.py:37`.

**Mechanism.** This is not "auth is off". It is attacker-chosen identity with genuine-looking audit attribution, on a system holding borrower PII, payment records, disputes, and DND/consent registers, reachable at the public URL in `.env:25`. Seed data supplies guessable ids (`priya-nair`, `role-agent`, `role-supervisor`, `role-admin`, `role-qa` — `seed_postgres.py:663`), so "any valid `users.id`" is not a meaningful barrier.

**The independent defect,** separable from C1: `auth_required` is derived from whether credentials *happen to be configured*. Absent credentials should be a refusal, not a mode. `main.py:432` gets this right but only in production; `Habibi/src/api/config.ts:11-35` gets it right unconditionally — the frontend throws in a production build if `VITE_USE_MOCK` is true or the base URL is unset. The backend has the weaker version of a rule its own frontend enforces properly.

**Why Critical:** unauthenticated read/write plus audit forgery on a regulated system, live now, single misconfiguration, no exploit chain.

---

### C3 · The Twilio media-stream WebSocket gate returns `True` for everything outside production — while the secret it should require is configured

**Evidence:** `backend/main.py:3455-3479`. A valid `VOICE_WS_PROXY_SECRET` returns `True` at `:3458`. Otherwise:

```python
# main.py:3471-3479
    if _IS_PROD:
        if not shared:  logger.error("... not configured in production")
        else:           logger.warning("... missing/invalid proxy secret")
        return False
    return True                      # ← :3479
```

`/ws` is in `_AUTH_EXEMPT_PREFIXES` (`main.py:249`), so nothing upstream stops the upgrade either.

**Mechanism.** With `APP_ENV=dev` (C1) and a public tunnel at `.env:25`/`:103`, any WebSocket upgrade from the internet is accepted onto the voice media stream. The particular sting: **`VOICE_WS_PROXY_SECRET` is set at `.env:207`.** The operator configured the control. The code does not consult it, because the environment says this is a laptop.

The comment at `main.py:3461-3470` is a careful, correct piece of reasoning about why a configured `TWILIO_AUTH_TOKEN` is not an authorization signal for this socket and why production must require the shared secret. It is right about all of it. The gap is that the environment opts out of the paragraph.

**Why Critical:** unauthenticated access to live borrower call audio, and the fix is deleting a fallback that a configured secret has already made unnecessary.

---

### C4 · `main.py` decides whether it is production *before* `.env` has been loaded — so setting `APP_ENV=production` is silently inert on the documented bare-metal path

**Evidence.** `main.py:204-205` computes `_APP_ENV` and `_IS_PROD` at module import. **`main.py` never calls `load_env()`** — the name does not appear anywhere in the file. Nor does anything it imports call it at import time: every `load_env()` call site in the API's import graph is *inside a function body*, verified by indentation and enclosing scope —

| Site | Enclosing scope |
|---|---|
| `storage.py:35` | `def _cfg()` |
| `storage.py:99` | `def is_configured()` |
| `whatsapp.py:20` | `def _read_env()` |
| `kb_rate_limit.py:40` | `def _limit()` |
| `azure_openai.py:167` | `def get_embedding_dims()` |
| `payments.py:30` | `def _env()` |
| `twilio_sms.py:20` | `def _env()` |
| `kb_ingest.py:30` | `def _stuck_after()` |

The configuration-architecture analyst confirmed this empirically by wrapping `os.getenv` and recording `env_loader._LOADED` at each first read during `import main`:

```
VAR                 env_loaded?   read at
APP_ENV             False         backend/main.py:204
MAX_UPLOAD_BYTES    False         backend/main.py:208
CORS_ORIGINS        True          backend/main.py:644
```

**Within a single file, configuration is half-applied.** By line 644 something in the module body has triggered a lazy `load_env()`; at line 204 nothing has.

**Mechanism.** On any launch where `APP_ENV` lives only in `backend/.env` — the path documented in `main.py:3` (`python -m uvicorn main:app`) and used by the repo's own `run_stack.ps1:43` — `os.getenv("APP_ENV")` returns `None` at line 204, `_IS_PROD` is `False`, and all four production gates stay open (`main.py:402` hardening gate, `:432` API-key requirement, `:446` actor-identity validation, `:588-590` OpenAPI). **An operator who sets `APP_ENV=production` in `.env` sees no error, no warning, and no change in behaviour.**

**Why it is masked in Docker.** `.dockerignore:12` excludes `.env` from the image, and `docker-compose.yml:80-81` injects it via `env_file:`, so the values arrive in the real process environment before Python starts and `load_env()` is a no-op. The bug is latent in the container and live on the documented bare-metal path.

**Why Critical.** It is not currently causing harm — `.env:145` says `dev`, which is what the code concludes anyway. It becomes Critical the moment someone acts on C1's remediation: the single most likely response to this audit is to set `APP_ENV=production`, and on the non-container path that change does nothing while appearing to have worked. **A control that silently ignores its own configuration is worse than one that has none**, because it converts a known gap into a believed-closed one.

**The same shape in two more entrypoints.** The same instrumented probe on `import voice.bot` shows `DATABASE_URL`, `TENANT_ID`, `ACTOR_USER_ID`, `DB_PROCESS_ROLE`, `BOT_ID` and `SANDBOX_HARD_MAX_TURNS` all read with `.env` unloaded; `voice/bot.py:28` sets `DB_PROCESS_ROLE` but never calls `load_env()`. And `voice_sandbox.py:33,35` read `VOICE_RUNNER_URL` / `VOICE_WEBRTC_PUBLIC_URL` pre-load, so the `.env` values are ignored and the hardcoded `http://127.0.0.1:7860` fallback wins. `voice/workers/insurance.py` calls `load_env()` only at `:186` and `:216`, inside functions.

**Per-entrypoint verdict:**

| Entrypoint | `load_env()` before app imports? | |
|---|---|---|
| `bot_worker.py:27-31` | yes | correct |
| `worker.py:20-24` | yes | correct |
| `mcp_server.py` | n/a — no import-time reads (`_transport()` at `:37` is call-time) | clean |
| `main.py` | **no** | **C4** |
| `voice/bot.py` | **no** | same defect |
| `voice/workers/insurance.py` | **no** at module level | same defect |

**The fix** is two lines at the top of each, in the shape `bot_worker.py:27-31` and `worker.py:20-24` already use: `from env_loader import load_env; load_env()` *above* the application imports. Three of six entrypoints already do it; the pattern exists and simply was not applied to the other three.

---

## Findings — High

### H1 · `.env.example` ships `SKILL_PLATFORM_KEY` set to the repo-published constant, defeating `sign.py`'s own production guard — *this one survives fixing `APP_ENV`*

`backend/agent_core/skills/sign.py:19` defines `DEV_PLATFORM_KEY = "dev-skill-platform-key-not-for-prod"` (35 characters). `backend/.env.example:326` sets `SKILL_PLATFORM_KEY` to a 35-character value beginning `dev-`. The guard:

```python
# sign.py:32-43
raw = (os.getenv("SKILL_PLATFORM_KEY") or "").strip()
if raw:
    return raw.encode("utf-8")        # ← returns here; the env check below is never reached
env = env_name()
if env not in NON_PROD_ENVS:
    raise RuntimeError("SKILL_PLATFORM_KEY is not set and APP_ENV=... is not a non-production environment ...")
```

Because the template *sets* the variable, `raw` is truthy and the `NON_PROD_ENVS` check at `:36` never runs — **even with `APP_ENV=production` correctly configured.** Every deployment that copied the template shares one HMAC key that anyone with repository access can read, so skill-pack signatures past the G9 publish gate (`sign.py:23-30`) are forgeable, silently, with no boot error.

The docstring at `sign.py:26-30` states the property the code is meant to have — *"Falling back to `DEV_PLATFORM_KEY` whenever `SKILL_PLATFORM_KEY` was unset meant an unconfigured production deploy verified against a public constant"* — and the fix correctly covers the *unset* case. The template then re-opens it from outside the module.

**Contrast, one line away:** `VAULT_MASTER_KEY` at `.env.example:290` is **commented out**, so `agent_core/vault/seal.py:42-52` does reach its guard and does raise outside `NON_PROD_ENVS`. Two sibling secrets, two templates, one uncommented line of difference.

**Current state:** `backend/.env` does **not** set `SKILL_PLATFORM_KEY` (verified — zero matches), so this deployment routes through the `NON_PROD_ENVS` fallback rather than the template bypass. The finding is about what the shipped template does to the next deployment.

**Rotation:** not applicable — these are intended-public constants, not leaked secrets. But any environment that has actually sealed `vault_refs.ciphertext` under `DEV_MASTER_KEY` must re-seal after setting a real `VAULT_MASTER_KEY`.

**High rather than Critical:** it needs repository access plus a deployment that copied the template. It is listed first among Highs because it is the only finding here that a correct `APP_ENV` does not fix.

### H2 · Unauthenticated `/ready` returns a raw storage exception string — while the DB path beside it deliberately refuses to

`/ready` is auth-exempt (`main.py:234`) and at `main.py:778` raises `HTTPException(503, detail=result)` where `result` is the whole dict, including `minio` and `circuits`. `storage.ping()` ends:

```python
# backend/storage.py:156-157
except Exception as exc:
    return {"ok": False, "configured": True, "detail": str(exc)}
```

A stringified MinIO/urllib3 exception carries the internal endpoint host:port; `storage.py:154` separately confirms bucket names via `bucket_missing:{bucket}`; `circuits` exposes internal dependency names and breaker state.

**The asymmetry is the finding.** Fifteen lines away, `db.readiness()` handles the identical case correctly and says why:

```python
# backend/db.py:345-347
# /ready is typically unauthenticated (load balancers poll it). A
# SQLAlchemy connection error stringifies the full DSN including the
# database user — log it, never return it.
```

…and returns `"detail": "db_unavailable"`. The reasoning was written down. It was not applied to the sibling function.

*Not fully verified:* whether the MinIO SDK's exception text can include an access-key id is provider-behaviour-dependent and was not confirmed by executing a failing auth call. The internal-topology disclosure is certain.

### H3 · The redaction layer covers borrower PII only — and skips `extra` fields and tracebacks entirely

`backend/pii_redact.py:42-58` defines exactly seven detectors: card, Aadhaar, PAN, phone, email, DOB, account number. **No** API-key, bearer-token, connection-string, or provider-key pattern.

Worse, only one of the three things in a log line goes through it:

- `observability.py:344-350` — `redact_text()` runs on `message` only.
- `observability.py:367-374` — every other `record.__dict__` field (everything passed as `extra=`) is copied into the payload with **no redaction**, falling back to `repr(value)`.
- `observability.py:376-377` — `payload["exception"] = self.formatException(...)`: **the full traceback is never redacted**, not even for PII.
- `observability.py:447-466` — the Sentry `before_send` scrubber uses the same PII-only detector set.

**Mechanism.** Any credential reaching a log message, an `extra=`, or a traceback is written cleartext to stdout and to Sentry. This is a latent gap rather than a confirmed leak: no key-in-query-string URL construction, no header-value logging (three sites log variable *names* only — `actor_context.py:92,95`, `main.py:3390`), and no `dict(os.environ)` dump was found anywhere. `voice/workers/insurance.py:198-199` redacts a Redis URL before logging and comments on why — the right instinct, applied in one place.

**Operational note:** `backend/` contains `api.err.log`, `api.out.log`, `botworker.*.log`, `ngrok.*.log`, `run_stack.*.log`. They are gitignored, so not a repository exposure, but given this finding they should be checked before this workstation's logs are archived or shared.

### H4 · Nineteen live-shaped provider credentials sit in one file that is mounted whole into five services

`backend/.env` holds, by shape (all values `[REDACTED SECRET]`): two 84-char Azure OpenAI keys (**identical value on `AZURE_OPENAI_API_KEY:34` and `AZURE_OPENAI_VOICE_API_KEY:40`**), one 84-char Azure Speech key (`:58`), a ~204-char Meta long-lived token (`:12`, `EAA…` shape), a 32-char WhatsApp app secret (`:11`), a Twilio Account SID (`:88`, `AC`+32hex) and 32-char auth token (`:89`), a MinIO pair (`:48-49`), a Postgres password (`:3`) also inline in `DATABASE_URL` (`:7`), a WS proxy secret (`:207`), and six comma-separated provider key pools — Cartesia `:334`, Deepgram `:342`, Groq `:350`, ElevenLabs `:356`, OpenRouter `:369`, Fish `:383`. None matches a placeholder pattern; all are format-consistent with real credentials.

`docker-compose.yml` mounts this entire file into **five** services — `api:80`, `worker:141`, `bot_worker:170`, `voice:194`, `voice_insurance:228`. A KB-indexing worker that needs `DATABASE_URL` and MinIO also receives Twilio and Meta credentials; a container escape in any one of five processes yields the whole set.

The compose file names its own problem at `:8-11`: *"worker, bot_worker, and voice_insurance mount the full backend/.env (including Azure/Meta/Twilio secrets). For production, prefer per-service env_file lists or Docker secrets."* Documented, not fixed.

**Repository exposure: none** — see "Git history" below. No rotation required *on these grounds*.

### H5 · There is no configuration schema, and all four startup checks are conditioned on `APP_ENV`

The lifespan hook (`main.py:426-448`) runs exactly four validations: `_assert_hardening_gate()` (returns immediately unless `_IS_PROD`), the `API_KEY`/`API_KEY_MAP` presence check (`if _IS_PROD and not has_auth`), `validate_configured_actors` (re-raises only `if _IS_PROD`), and `storage.ensure_bucket`. Everything else is read lazily at first use.

**Mechanism.** With `APP_ENV=dev` there is no boot-time signal for any missing or misspelt variable — the process starts and takes a default. There is no manifest of expected variables anywhere in the tree, which is also why H6's 83 undocumented reads went unnoticed.

### H6 · Eighty-three variables are read by code and documented in no env file — including the one that waives the production hardening gate

Derived by set arithmetic over parsed files against an enumeration of read sites. The security-relevant members:

`ALLOW_UNHARDENED_PRODUCTION` (`main.py:404` — the single variable that lets a production boot past `_assert_hardening_gate` while RLS, PII encryption and append-only audit are all still off), `AUTHZ_ENFORCE` (`authz.py:631`), `VISIBILITY_ENFORCE` (`visibility.py:92`), `VISIBILITY_UNASSIGNED_POOL` (`visibility.py:104`), `MAX_UPLOAD_BYTES` (`main.py:208`), `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` / `RAZORPAY_WEBHOOK_SECRET` (`payments.py:54,65`), `SENTRY_DSN` (`observability.py:425`), `TREATMENT_ALLOW_SIMULATED_MODELS` (`treatment/models.py:591`), `TREATMENT_MANDATE_RAIL_MODULE` (`treatment/enact.py:659`), and `OUTBOUND_TEST_ANY_HOUR` (`scripts/dial_test.py:191` — bypasses the calling-window guard, which in this jurisdiction is a statutory control).

None of `AUTHZ_ENFORCE`, `VISIBILITY_ENFORCE`, `ALLOW_ACTOR_HEADER`, `SKILL_PLATFORM_KEY` or `VAULT_MASTER_KEY` is set in `backend/.env` (verified: zero matches each). Every one of them therefore takes its `APP_ENV`-derived default.

### H7 · `ENV` is a valid alias for `APP_ENV` in exactly one module, producing a split brain on the most safety-relevant setting

`env_utils.py:38` accepts either: `(os.getenv("APP_ENV") or os.getenv("ENV") or "dev")`. **Every other production gate reads `APP_ENV` alone** — `main.py:204`, `actor_context.py:55`, `storage.py:46`, `payments.py:40`, `observability.py:433`, `seed_susanth.py:28`, `scripts/seed_demo.py:31`, `scripts/dial_test.py:46`.

**Mechanism.** On a host that sets `ENV=production` without `APP_ENV` — a common convention, and one this repo half-supports — the system splits: `env_allows_dev_key()` correctly returns `False`, so `vault/seal.py` and `skills/sign.py` refuse the committed dev keys and the process fails loudly on those paths, **while `main.py` runs fail-open and `storage.py:46-59` falls back to the `minioadmin` pair.** Half the system believes it is in production and half does not, and the halves that disagree are precisely the ones that matter.

Worse in combination with C4: the two variables are read at different times as well as in different modules.

### H8 · `AZURE_SPEECH_REGION` unset resolves four different ways, one of them a data-residency change

| Site | Behaviour when unset |
|---|---|
| `voice/config.py:77`, `azure_speech.py:84` | `_require` → raises |
| `agent_core/providers/factory.py:200` | **silently defaults to `"eastus2"`** |
| `tts_catalog_sync.py:101-103` | raises with a message |
| `ops_screens.py:1621` | `"centralindia" if for_env == "production" else "eastus"` |

**Mechanism.** For a platform processing Indian borrowers' voice under DPDP, `factory.py:200` routes speech traffic to a US region on an unset variable — while `ops_screens.py:1621` simultaneously *displays* `centralindia` to the operator. The screen asserts residency the runtime is not honouring. Four resolutions of one variable is a defect on its own; this particular pair is a compliance exposure with a misleading indicator on top.

The same shape, lower stakes, for `AZURE_OPENAI_API_VERSION`: `azure_openai.py:312` raises when unset, `voice/config.py:45` silently pins `"2025-04-01-preview"`.

### H9 · `Asia/Kolkata` is hardcoded in nine modules while `APP_TIMEZONE` exists — so the setting moves the model's clock but not the compliance clock

`agent_core/clock.py:30-31` is the intended single source and honours `APP_TIMEZONE`. **Nothing else calls it.** The literal is hardcoded at `campaigns.py:57`, `contact_policy.py:71`, `payments.py:25`, `payment_events.py:40`, `promise_fulfillment.py:28` (plus SQL literals at `:877, 878, 900, 901`), `schemas.py:40`, `db.py:1056, 1956, 2304, 8447`, `followups_db.py:17`, `outbound.py:1188`. `contact_window.py:29` hardcodes it as a fixed `+05:30` offset, which additionally cannot represent a DST-observing zone.

**Mechanism.** Setting `APP_TIMEZONE` changes what the agent is *told* the time is, but not calling-window enforcement, promise due-date rollover, or campaign scheduling — the half that is statutory. A configuration knob that moves the appearance of a compliance control without moving the control is a worse failure than not having the knob. It also means the compose comment at `.env.example:426` (*"Customers' local time. Containers run UTC"*) describes an intent the code only partly implements.

---

## Findings — Medium

**M1 · `backend/.env.bak.reco` is a second, unrotatable copy of the credential set.** 221 lines, 91 assignments, every name and every value identical to `backend/.env:1-221` — a byte-for-byte prefix taken before the RECO/TREATMENT/provider-pool blocks were appended. It carries the Meta token, the WhatsApp app secret, both Azure keys, the Twilio auth token, the MinIO pair, the WS proxy secret and the DSN. It is correctly ignored (by `backend/.gitignore:5`, `.env.*` — the root pattern `**/.env` alone would *not* have caught it) and has never been committed. The risk is rotation drift: rotating a key in `.env` leaves the old one here, under a filename no scanner keys on, in the same directory.

**M2 · The live `.env` uses the MinIO default credentials its own template forbids.** `.env:48-49` sets the well-known `minioadmin`/`minioadmin` pair, and `:51` sets `MINIO_SECURE=false`. `.env.example:116-117` says in terms: *"Generate UNIQUE credentials (e.g. `openssl rand -hex 24`) — do NOT reuse the well-known minioadmin/minioadmin defaults"*, and leaves both empty at `:119-120`. `docker-compose.yml:58-59` feeds these into `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`, so the object store's root account is the default pair. `storage.py:47-57` only objects when the endpoint is non-loopback or `APP_ENV` is prod — here it is `localhost:9000` and `dev`, so nothing complains.

**M3 · `.env.example` is deliberately baked into every image.** `backend/.dockerignore:12-14` is `.env` / `.env.*` / `!.env.example`, and `Dockerfile:23` is `COPY . .`. The 30 KB template — including H1's key at `:326` — is a readable file inside `collections-api:local` and `collections-voice:local`. The exclusion list is otherwise good: the real `.env`, `.git/` and `.venv/` are all correctly excluded.

**M4 · Weak Postgres defaults hardcoded in four committed files.** The `collections`/`collections` pair appears as a *default* in `docker-compose.yml:37-38` (and in every `DATABASE_URL` at `:83, 144, 173, 197, 231`), `alembic.ini:29` (a fully-formed credentialed DSN with no env indirection), `db.py:40` (`DEFAULT_DATABASE_URL`, used as the last fallback at `db.py:83`), and `seed_postgres.py:25`. The `:-collections` form means a missing `POSTGRES_PASSWORD` produces a working stack with a guessable password rather than an error. **MinIO in the same file gets this right** — `docker-compose.yml:58-59` uses `${MINIO_ACCESS_KEY:?set MINIO_ACCESS_KEY in backend/.env}`, the fail-fast form. Two of eleven compose variables use `:?`; nine use permissive `:-`.

**M5 · `VITE_API_KEY` would compile the shared backend key into the public browser bundle.** `Habibi/src/api/config.ts:38` reads it and `:52` sends it as `X-API-Key`; `:45`/`:53` do the same for `VITE_ACTOR_USER_ID` → `X-Actor-User-Id`, the exact header C2 turns into impersonation. **Currently unset** in `Habibi/.env`, `.env.local` and `.env.example` — nothing is leaking today — and `Habibi/.env.example:10-13` warns about precisely this and leaves it commented. The severity is structural: a browser SPA cannot hold a shared server secret, and fixing C2 without giving the SPA a real session mechanism makes reaching for this variable the obvious next move. `Habibi/vite.config.ts` has no `define:` block, so no non-`VITE_` value is injected at build time.

**M6 · Forty-three variables that `.env.example` presents as active defaults are absent from `.env`.** Including `CONTACT_DAILY_CAP`, `CONTACT_WEEKLY_CAP`, `CONTACT_COOLING_OFF_MINUTES`, `CONTACT_SESSION_WINDOW_MINUTES` (`.env.example:431-434` — the statutory contact-frequency gate) and `APP_TIMEZONE` (`:426`, whose own comment reads *"Customers' local time. Containers run UTC"*). The code defaults happen to match the example values (`contact_policy.py:98-119`), so nothing is broken today — but a compliance cap that is correct by coincidence rather than by declaration is not a control anyone can audit.

**M7 · Eight variables are live in `.env` and documented nowhere as active config.** Absent from `.env.example` entirely: `TREATMENT_GREEDINESS` (`.env:284`), `TREATMENT_MANDATE_EXECUTOR` (`:307`), `TREATMENT_SWEEP` (`:272`), `TURN_CRITIC_ENABLED` (`:221`). Present only as commented documentation: `TREATMENT_AB_SPLIT`, `TREATMENT_SCORER`, `VOICE_FLOW_GRAPH`, `VOICE_WS_PROXY_SECRET`. Three of these are the switches that turn the treatment engine from a logger into a dialler, and a fresh operator copying the template gets none of them with no line telling them they exist.

**M8 · Nine of `db.py`'s thirteen import-time settings are silently ignored by the API when it runs outside a container.**

`db.py` reads its entire configuration at module import — thirteen of thirteen sites: `DATABASE_URL:83`, `TENANT_ID:92`, `ACTOR_USER_ID:93`, `DB_POOL_SIZE:118`, `DB_MAX_OVERFLOW:119`, `DB_POOL_RECYCLE:120`, `DB_PROCESS_ROLE:122`, `DB_STATEMENT_TIMEOUT_MS:124`, and four list-limit defaults at `:180, 181, 184, 189`.

`db.py` handles the obvious hazard **deliberately and well**: it does not call `load_env()`, because *"importing `db` must not have the side effect of publishing the whole `.env` into the process, which would change what every later import sees"* (`db.py:64-66`). Instead `_read_env_file()` (`db.py:52-80`) reads `backend/.env` directly, without mutating `os.environ`, and `DATABASE_URL:83` and `TENANT_ID:92` each fall back through it. The docstring at `:55-62` records the bug that produced this: `usage_meter` called `load_env()` and `db` did not, so the two disagreed about `TENANT_ID`, and under row-level security that disagreement is not an error — every query simply returns nothing.

**The gap is that the other nine settings have no such fallback.** The pool, timeout and list-limit values go through `_env_int`, which reads `os.environ` only. And `ACTOR_USER_ID:93` is the sharpest case — **three adjacent lines, two different resolution strategies**:

```python
# db.py:83, :92 — fall back through _read_env_file()
DATABASE_URL = os.getenv("DATABASE_URL") or _read_env_file("DATABASE_URL") or DEFAULT_DATABASE_URL
TENANT_ID    = os.getenv("TENANT_ID")    or _read_env_file("TENANT_ID")    or "hdfc.retail"
# db.py:93 — does not
ACTOR_USER_ID = os.getenv("ACTOR_USER_ID", "priya-nair")
```

`.env` defines `ACTOR_USER_ID`. In an API process launched outside a container, that value is discarded and the hardcoded `priya-nair` is used instead — so every audit row written on the default path is attributed to a fixed identity the operator did not choose. It is also the value C2 hands out to an unauthenticated caller who sends no actor header.

Meanwhile `main.py` never calls `load_env()` (C4) and imports `db` at `main.py:38`. So:

- **In compose, this works by accident of the deployment descriptor.** `env_file: - .env` injects the whole file into the process environment before Python starts, so every variable is present at import.
- **Outside compose — a bare `uvicorn main:app`, which this repo's own run-stack scripts use — a value set only in `backend/.env` is invisible** to all nine. `DB_STATEMENT_TIMEOUT_MS`, `DB_POOL_RECYCLE`, `DEFAULT_LIST_LIMIT`, `MAX_LIST_LIMIT`, `DEFAULT_CALLS_LIMIT` and `DEFAULT_DETAIL_LIMIT` are not in any compose `environment:` block either, so they rely entirely on `env_file`.

And the asymmetry is the sharp end: `bot_worker.py:27-31` and `worker.py:20-24` both set `DB_PROCESS_ROLE` and call `load_env()` *above* the app imports, correctly. **The same line in the same `.env` therefore takes effect in the workers and not in a locally-run API** — with no error, and no way to tell from the outside except by observing a different statement timeout.

The voice runtime avoids all of this by calling `load_env()` at call time inside each accessor (`voice/config.py`, 11 call sites; `voice/host.py:54`; `voice/twilio_ops.py:41`; `voice/ws_proxy.py:21,34`), which is idempotent via `env_loader._LOADED`. That is the pattern that works regardless of import order.

**M9 · Eight numeric env reads parse at module import with no `try/except`.** `azure_speech.py:31, 36, 45, 374`; `tts_preview_cache.py:60, 63`; `sandbox_runtime.py:382`; `main.py:208` — all `int(os.getenv(...) or "<default>")` at module scope. A stray character makes this an import-time `ValueError` and the API never starts. This is an availability failure rather than a wrong-default one, so it is the safer direction — but note `sandbox_runtime.py:382` is the unguarded twin of `agent_core/guardrails.py:14`, which wraps the identical expression in `try/except ValueError` and comments on why. Everything routed through `env_utils.env_int`/`env_float` is correctly defaulted, including a `math.isfinite` guard (`env_utils.py:73-74`) against `nan`/`inf` reaching a timeout or breaker window.

**M10 · The vault master key is a bare unsalted SHA-256 of the env string.** `agent_core/vault/seal.py:53` — `hashlib.sha256(raw.encode("utf-8")).digest()`. No salt, no KDF, no iteration count. The envelope itself (`seal.py:66-89`) is a sound encrypt-then-MAC construction with per-nonce derived keys, but an attacker holding a database dump can brute-force a passphrase-style `VAULT_MASTER_KEY` offline at full hash speed. Requires a prior DB compromise, hence Medium.

**M11 · `GET /providers` returns the Twilio Account SID in cleartext.** `ops_screens.py:203` marks `accountSid` as `"secret": False`; `ops_screens.py:1518-1524` returns unflagged fields raw from the environment and masks only flagged ones. The SID is half of Twilio's basic-auth pair and a stable account identifier. Also returned raw: `AZURE_OPENAI_ENDPOINT`, `AZURE_SPEECH_REGION`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_WABA_ID`. This route is *not* auth-exempt, so it is behind authentication normally — and public under C2.

**M12 · No container hardening.** Grepping both compose files and the Dockerfile for `USER|mem_limit|cpus|deploy:|read_only|cap_drop|security_opt|privileged` returns **zero matches**: all four process types run as **root**, and no service of eight has a memory or CPU limit — despite the DB connection budget being carefully documented at `docker-compose.yml:2-6`. Healthchecks cover 4 of 8 services (`redis`, `db`, `minio`, `api`); the four workers have none, so `restart: unless-stopped` catches process exit but not a wedged worker.

**M13 · Four incompatible boolean truth sets, and `MINIO_SECURE=on` disables TLS.** `env_utils` exports `env_int` and `env_float` and **no `env_bool`**, so all 26 boolean sites are hand-rolled, in four different dialects:

| Truth set | Sites |
|---|---|
| `{"1","true","yes","on"}` | 20 — the dominant convention |
| `{"1","true","yes"}` — no `"on"` | 5 — `storage.py:62`, `voice/amd.py:139`, `voice/call_trace.py:108`, `scripts/dial_test.py:191` |
| `{"1","true","yes","y"}` | 1 — `db.py:11574` |
| `{"1","true","yes","on",""}` — **empty is true** | 1 — `voice/ws_proxy.py:36` |

The sharp edge is `storage.py:60-66`. `MINIO_SECURE` is non-empty, so it enters the branch — but `"on"` is not in *that* site's tuple, so `secure = False`. **An operator who writes `MINIO_SECURE=on` to enable TLS gets plaintext object storage**, and `on` is the spelling 20 of the 26 sites in this same codebase accept. The *unset* path is the safe one (`storage.py:64-66`: TLS for anything off loopback), so configuring the variable is more dangerous than leaving it alone. `voice/ws_proxy.py:36` is the mirror image: blanking `VOICE_WS_VIA_API=` to disable the proxy *enables* it.

**M14 · Sixteen private re-implementations of the shared env getters, one with a real semantic gap.** `env_utils`'s own docstring (`:1-13`) says it exists so that settings "can never disagree". Eighteen files import it (45 call sites) — and thirteen others define their own: `bot_runtime.py:38`, `agent_core/reco/config.py:31,42`, `agent_core/treatment/policy.py:422`, `agent_core/treatment/config.py:50`, `agent_core/platform_flags.py:14`, `agent_core/tools/kb_plan.py:78`, `agent_core/tools/kb_rerank.py:73`, `voice/config.py:106,111,159`, plus `_env` in `payments.py:29`, `payment_events.py:43`, `promise_fulfillment.py:33`, `twilio_sms.py:19`, `voice/twilio_ops.py:40`.

The drift is not cosmetic. `env_utils.env_float` rejects `nan`/`inf` (`:73-74`) with a comment explaining that NaN makes every comparison false and inf makes a bounded wait unbounded. `agent_core/reco/config.py:31-39` does not import `env_utils` and omits that guard — so `RECO_MIN_SCORE=nan` or `RECO_W_FATIGUE=inf` is accepted straight into the offer scorer.

**M15 · Two flags both claim to be the master dial gate.** `CAMPAIGN_RUNTIME_ENABLED` (`agent_core/platform_flags.py:79`, documented "Off means nothing dials") and `OUTBOUND_ENABLED` (`platform_switches.py:40`, the same claim). They are ANDed in practice, so there is no unsafe disagreement — the failure is diagnostic. An operator who flips `outbound.enabled` on from the screen and sees nothing dial gets no signal that an `.env` flag, on four separate processes, is also holding it shut. Given `platform_switches` exists precisely so dialling can be controlled without a restart, the env flag partly defeats its purpose.
---

## Findings — Low

**L1** · `Habibi/.env` and `Habibi/.env.local` are byte-identical (`VITE_USE_MOCK=false`, `VITE_API_BASE_URL=http://127.0.0.1:8000`). Vite's precedence gives `.env.local` the win, so `Habibi/.env` is inert — no conflict today, but a future edit to it will silently do nothing. `Habibi/.env.example:8-9` disagrees with both and its header says to copy to `.env.local`, so the `.env` copy is undocumented in the first place.

**L2** · Five variables set in *both* backend env files are read by nothing: `CARTESIA_MODEL`, `DEEPGRAM_STT_MODEL`, `DEEPGRAM_TTS_MODEL`, `GROQ_STT_MODEL`, `ELEVENLABS_TTS_MODEL`. The only related hit is a hardcoded constant at `provider_tts.py:118`. Their siblings *are* read (`FISH_TTS_MODEL`, `OPENROUTER_TTS_MODEL`), which is what makes the five look functional. Changing a Deepgram voice does nothing and reports nothing.

**L3** · `env_loader.py:23-25` does not strip inline comments and strips quote characters unconditionally: `API_KEY=abc  # rotated Tuesday` yields a value containing the comment. No current line trips it. The non-destructive precedence at `:26` (`if key and key not in os.environ`) is correct and matches its docstring — but it also means a stale shell export silently beats the file, with no warning.

**L6** · `bot_jobs.py:40` — `BOT_ENVIRONMENT` defaults to `production`, selecting the active `bot_deployments.environment` row. This is the one env discriminator in the codebase that defaults *conservative*; noted because it is the counter-example to C1.

**L7** · With `CORS_ORIGINS` empty (`.env:165`), `main.py:658-665` applies `allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+"` with `allow_credentials=True`. `allow_origins=["*"]` is never used and the invalid `*`+credentials combination does not appear. Narrow, but any process that can bind a localhost port on a user's machine becomes a same-credential origin, and the frontend sends `credentials: "include"` on every request.

**L8** · `Habibi/src/data/webhooks-seed.ts:257, 270, 293, 306, 326` ship five `whsec_`-shaped literals and internal hostnames into the browser bundle. These are demo fixtures — too short to be real signing secrets, per-system mnemonics — but the file is a static import path from source straight to the public bundle, imported by 11 UI components.

**L9** · `payments.py:48` — `base = _env("PUBLIC_BASE_URL") or "http://127.0.0.1:8000"` is the only localhost fallback on a path that produces a URL *sent to a customer*. Unset, every hosted payment link points at the recipient's own loopback and is silently dead. Every other `PUBLIC_BASE_URL` consumer either raises or declines (`voice/twilio_ops.py:111, 127, 340`).

**L10** · `Habibi/.gitignore` covers only `*.local`; the root `.gitignore:14-15` covers `**/.env` and `**/.env.local`. Nothing covers `Habibi/.env.production`, which would therefore be committed. `backend/.gitignore:5` has the general `.env.*` rule; the frontend does not. Asymmetric, and the backend comment at `:2-3` explains exactly why the general rule was needed.

**L11** · `agent_core/reco/config.py:79` and `:298-299` test `!= "false"`, so `0`, `no` and `off` all read as `True`. For `RECO_REQUIRE_COMMITMENT` this fails safe (the no-offer-without-a-promise guard stays on), but an operator writing `off` gets the opposite of what they typed, silently. These are the only two outliers — see "What is done well".

---

## The configuration surface — measured

Derived by AST walk over `backend/**/*.py`, excluding `.venv`, `__pycache__`, `alembic/`, and test files. Reads counted: `os.environ[...]`, `os.environ.get`, `os.getenv`, and the named helpers (`env_int`, `env_float`, `_env`, `_env_int`, `_env_bool`, `_flag`, `_read_env`, …). "Import-time" means a module-level statement, a class body, or a default argument evaluated at `def` time.

| Metric | This scan | Independent scan | Why they differ |
|---|---|---|---|
| Files with ≥1 env read | **94** | **107** | the other scan includes `tests/`, `scripts/` and `alembic/`; this one excludes them |
| Total env read sites | **396** | **275** | this scan counts calls through the wrapper helpers (`env_int`, `_env`, `_flag`, …); the other counts only literal `os.getenv` / `os.environ` |
| Distinct variable names | **270** | **283** | the other resolves names inside `_require`/`_optional`/`_read_env` helpers this scan attributes to the wrapper |
| Import-time reads | **32** sites | **23** module-level assignments in 20 files | this scan also counts bare module-level calls and `def`-time defaults |
| Names read in >1 file | **33** | **27** | scope difference as above |

The two agree on shape and disagree only on where to draw the boundary. Both were run because the headline — *configuration is spread across ~100 files with no schema* — should not rest on one method. Two further checks are worth recording as clean: **zero** class attributes and **zero** default arguments read the environment, so the import-time exposure is confined to plain module-level assignment.

**There is no settings object.** No pydantic `BaseSettings`, no config module — `env_loader.py` (29 lines) copies `.env` into `os.environ`, `env_utils.py` (~105 lines) offers four typed helpers, and every one of 94 files then reads the environment for itself.

**The spread is worst exactly where it matters.** `APP_ENV` — the variable behind C1 and eleven controls — is read in **11 distinct files**: `actor_context.py:55`, `env_utils.py:38`, `main.py:204`, `observability.py:433`, `payments.py:40`, `seed_postgres.py:36`, `seed_susanth.py:28`, `storage.py:46`, `usage_meter.py:292`, `scripts/dial_test.py:46`, `scripts/seed_demo.py:31`. Each re-implements the same `or "dev"` default. `env_utils.env_name()` exists to be the single source, and `env_allows_dev_key()` is exported for exactly this purpose — but its only two consumers (`sign.py:35`, `seal.py:44`) bypass the helper and re-derive the test from `env_name()` and `NON_PROD_ENVS` directly. The abstraction was built and then not used, including by the two modules it was built for.

Other multi-file names: `PUBLIC_BASE_URL` (6 files), `API_KEY` (3 files, 6 sites), `MCP_API_KEY` (3), `DATABASE_URL` (3), `AZURE_OPENAI_REASONING_MODEL` (3), `BOT_ID` (3), `RECO_SCORER` (3).

### There are two configuration systems, and the split is principled

Alongside the environment layer there is a second, DB-backed one: `platform_switches.py`, a small set of operator-flippable booleans in Postgres read by all four dialling processes. Its module docstring (`platform_switches.py:1-25`) draws the line explicitly, and draws it in the right place — environment flags are for *"does this deployment have the feature at all"*, fixed for the life of a process; DB switches are for *"stop dialling, now"*, flippable from a screen without a restart.

The two do not overlap and cannot disagree: `OUTBOUND_ENABLED` (`:40`) and `DEMO_IGNORES_WINDOW` (`:61`) have no environment-variable equivalent, and `agent_core/platform_flags.py`'s twelve gates have no DB equivalent. This is the one part of the configuration architecture that is deliberately designed rather than accumulated — see "What is done well" for its safety property.

**Env-file inventory:**

| File | Lines | Active `K=V` | Commented | Duplicate keys | Empty values |
|---|---|---|---|---|---|
| `backend/.env` | 452 | 126 | — | **0** | 5 |
| `backend/.env.example` | 638 | 161 | 89 | **0** | 42 |
| `backend/.env.bak.reco` | 221 | 91 | — | **0** | 5 |
| `Habibi/.env` | 2 | 2 | 0 | 0 | 0 |
| `Habibi/.env.local` | 2 | 2 | 0 | 0 | 0 |
| `Habibi/.env.example` | 11 | 2 | 2 | 0 | 0 |

**Zero duplicate keys in any env file** — no silent later-wins overwrite exists anywhere.

**Drift, by set arithmetic:** 8 variables live in `.env` but undocumented as active (M7) · 43 active in `.env.example` but absent from `.env` (M6) · **83** read by code and present in *neither* file, active or commented (H6) · 5 confirmed dead in both (L2, after clearing 13 false positives read via module constants or consumed by compose/CI rather than Python) · 42 values differing between `.env` and `.env.example`, which is the file's purpose — the interesting subset is C1's mode flags.

The second scan puts the undocumented count at **157**, measuring a different thing: production variables absent from `.env.example`, ignoring `.env` and ignoring commented-out entries there. Both are right about their own question, and both are worth knowing — 83 are documented *nowhere at all*, and 157 are missing from the file that `agent_core/platform_flags.py:4` names as the place they must be added: *"Do not invent a new name in a feature PR — add it here and in `.env.example`."* The rule is written down and is broken 157 times.

---

## Git history — verified clean

This is the one place the news is unambiguously good, and it is worth stating precisely because it determines whether a rotation is needed.

- **39 commits, all branches.** The only `.env`-named paths that have *ever* existed in history are `backend/.env.example` and `Habibi/.env.example`. `backend/.env`, `backend/.env.bak.reco`, `Habibi/.env` and `Habibi/.env.local` are untracked and have never been committed.
- **Content scan of every commit diff** for provider-token shapes — `sk-`+20, `AC`+32hex, `SK`+32hex, `EAA`+40, `xox[baprs]-`, `AKIA`+16, `ghp_`, `-----BEGIN … PRIVATE KEY`, `mongodb+srv://`, and credentialed `postgres`/`http(s)` URLs — returns **three classes only**: a `sk-abc…` test literal (9 occurrences), the `collections:collections` local default of M4 (7), and two `https://…@example.invalid/` fixtures. **No live credential has ever been committed.**
- **Ignore coverage is genuinely belt-and-braces.** Root `.gitignore:14-16` (`**/.env`, `**/.env.local`, `!**/.env.example`) plus `backend/.gitignore:4-6` (`.env`, `.env.*`, `!.env.example`). The `.env.*` rule is what catches `backend/.env.bak.reco`; the root pattern alone would not have.
- **No key material in the tree:** zero `.pem`, `.key`, `.crt`, `.p12`, `.pfx` or `.jks` files, and zero inline PEM blocks.
- **No TLS verification is disabled anywhere:** zero hits for `verify=False`, `rejectUnauthorized`, `NODE_TLS_REJECT_UNAUTHORIZED`, `ssl._create_unverified`, `check_hostname=False`.
- **Zero live credentials hardcoded in source.** Two independent scans: provider-literal patterns returned 2 hits (1 weak dev default, 1 source *comment* naming the risk); credential-named assignments to literals ≥8 chars returned 13 hits (5 demo fixtures, 5 test fixtures, 3 env-var *names* mistaken for values).

**No rotation is required on repository-exposure grounds.** The credentials in H4 are exposed by C2 and potentially by H3 — not by git.

---

## What is done well

Worth recording, because the remediation should preserve these rather than flatten them.

- **`NON_PROD_ENVS` is an allow-list, not a deny-list** (`env_utils.py:33`). `APP_ENV=staging`, or a typo, *raises* rather than silently weakening. The docstring at `:28-32` explains the reasoning. This is the correct shape; C1 is the observation that *unset* still lands inside the list.
- **`platform_switches` makes absence mean off, and says so.** *"A missing row, an empty table, a table that does not exist yet and a database the reader cannot reach all resolve to `False`. There is no input — including a broken one — that turns dialling on by accident"* (`platform_switches.py:15-24`). The docstring then names why this is deliberately the opposite of the usual degrade-gracefully instinct: *"the failure this guards against is placing a call to a real person who did not ask for one."* This is exactly the discipline C1 is missing — **it is the same codebase, applying the correct default rule to one subsystem and the inverted one to `APP_ENV`.** The `DEMO_IGNORES_WINDOW` documentation (`:42-60`) is likewise precise about a compliance override's reach: it waives timing and frequency vetoes for one endpoint dialling one operator-owned handset, and never waives consent, opt-out, DND, the registry, or the DPDP promotional basis.
- **`db.py` refuses to publish `.env` as a side effect of being imported** (`db.py:64-66`), reading the two values it needs directly instead. The docstring at `:55-62` records the tenant-divergence bug that produced the rule — and that under RLS such a divergence returns no error, just an empty application. See M8 for where the same care stops.
- **`db.readiness()` refuses to stringify its own DSN** (`db.py:345-347`) with the reasoning written down. H2 is a request to apply the same treatment fifteen lines away.
- **`storage.py:47-57` gates the MinIO fallback on an observable property of the deployment** — is the endpoint loopback? — and not only on `APP_ENV`. `storage.py:76-95` treats an unparseable endpoint as remote, the conservative direction. **This is the pattern every other guard in this report should follow**, and the comment at `:41-44` names the staging-box incident that produced it.
- **Secrets at rest are handled correctly.** Provider credentials are *not* stored in Postgres — `provider_configs` holds only `enabled`, `health`, `latency_ms` (`ops_screens.py:1547-1551`). The one credential store, `vault_refs`, is always sealed before insert (`vault/persist.py:74`), `_public()` returns `hasSecret: true` and never the ciphertext (`persist.py:45-52`), and `reveal()` (`persist.py:111`) has **zero callers anywhere in the backend**. Webhook secrets store a hash plus a ref and render as a fixed dot-string (`ops_screens.py:239-240`).
- **`VAULT_MASTER_KEY` no longer falls back to `SKILL_PLATFORM_KEY`.** The docstring at `seal.py:31-36` explains that one operator secret was doing two unrelated jobs, and that rotating it for a signing incident would have made the vault undecryptable. Two secrets, two variables — correctly separated.
- **Boolean parsing is case-robust.** Every hand-parsed boolean lower-cases and strips first, so `TRUE`, `Yes` and ` on ` never silently read as False — the usual typo hazard genuinely does not exist here. What *does* vary is which words count as true: see M13.
- **`env_utils.env_float` guards `nan`/`inf`** (`env_utils.py:73-74`) with a comment explaining that NaN makes every comparison false and inf makes a bounded wait unbounded — both feeding timeouts and breaker windows.
- **The frontend fails closed where the backend does not.** `Habibi/src/api/config.ts:11-35` throws in a production build if `VITE_USE_MOCK` is true or `VITE_API_BASE_URL` is unset — unconditionally, not gated on an env name.
- **Port bindings are right.** All six published compose ports are explicitly loopback; nothing binds `0.0.0.0` by default, and the API's binding carries a comment (`docker-compose.yml:115-117`) explaining exactly why.
- **CI is clean.** Two workflows, both read in full: zero uses of `${{ secrets.* }}` and zero need for them (every credential-shaped value is an explicit placeholder — `AZURE_OPENAI_API_KEY: "ci-not-a-real-key"`, endpoint `https://ci.invalid/`), zero `echo $ENV` steps, no inline real secrets. Worth noting for a different reason: CI runs with `APP_ENV: dev`, so **the permissive branch of every C1 control is the branch the test suite exercises** — the fail-closed production paths at `main.py:402, 432, 3473` have no coverage.
- **No migrations or seeding on the startup path.** `db.init_and_seed` (`main.py:441`) is now a bare `SELECT 1` connectivity probe (`db.py:365-367`); the name is a leftover. All three seed entry points refuse production, and `seed_postgres.py:32-36` reads `APP_ENV` from `.env` rather than only the process environment, with a comment explaining that a deployment setting it only in `.env` would otherwise look like dev while pointing at the production database. They create fixed actor *ids*, not passworded accounts — there is no admin backdoor.
- **No hardcoded tunnel URLs.** All 11 `ngrok` mentions in source are prose; every tunnel URL is read from `PUBLIC_BASE_URL`/`VOICE_PUBLIC_BASE_URL`, and `voice/twilio_ops.py:111-113` raises unless the base URL is HTTPS.
- **No build-time secret injection.** Zero `ARG` directives in the Dockerfile (so no `docker history` exposure), no `define:` block in `vite.config.ts`, and no `--reload` in any runnable path.

---

## Remediation

### Immediate — the deployment is currently open

1. **Add `load_env()` to the top of `main.py`, above the application imports** (C4) — the shape `bot_worker.py:27-31` already uses. **Do this first.** Every other change to `.env` is unverifiable until the API is actually reading the file on the bare-metal path.
2. **`.env:145` → `APP_ENV=production`.** Then fix what refuses to boot: `main.py:432` will demand `API_KEY`/`API_KEY_MAP`, and `main.py:400-418` will demand that RLS, PII encryption and append-only audit be active or that `ALLOW_UNHARDENED_PRODUCTION` be set deliberately. Both refusals are correct and both are currently being talked out of. Do **not** reach for `ALLOW_UNHARDENED_PRODUCTION` (H6) as the quick path. **Verify the change took effect** — under C4 the natural assumption that it did is exactly what fails.
3. **Set `API_KEY` or `API_KEY_MAP`** (`.env:149`/`:154`) — and independently, at `main.py:292`, stop deriving `auth_required` from whether credentials are configured. Absent credentials must refuse, not degrade.
4. **Delete the `return True` at `main.py:3479`** and require `VOICE_WS_PROXY_SECRET` unconditionally. It is already configured at `.env:207`.
5. **Set `ALLOW_ACTOR_HEADER=false` explicitly**, rather than inheriting it from `APP_ENV` (`actor_context.py:58-65`). Header-chosen identity should be an opt-in, never a default.
6. **Rotate the MinIO root credentials** (M2) as the template already instructs — and set `MINIO_SECURE` to `true`, **not `on`**, until M13 is fixed.
7. **Give `AZURE_SPEECH_REGION` one resolution.** `agent_core/providers/factory.py:200` must not silently default to a US region (H8); make it raise like its three siblings.

### Near-term — close the paths that survive steps 1-2

8. **Comment out `SKILL_PLATFORM_KEY` at `.env.example:326`**, matching `VAULT_MASTER_KEY` at `:290`. One character; it is the only Family-B finding a correct `APP_ENV` does not fix. Separately, restructure `sign.py:32-43` so the environment check runs *before* the early return, so a publicly-known key is refused in production even when it is set.
9. **`storage.py:157`** — return a stable token, not `str(exc)`; log the detail. Copy `db.py:345-353` verbatim.
10. **`pii_redact.py:42-58`** — add credential detectors (bearer tokens, `sk-`/`EAA`/`AC`+hex provider shapes, connection strings, `Authorization` values). Then run the redactor over `extra` fields and `formatException` output in `observability.py:367-377`, not just `message`.
11. **Delete `backend/.env.bak.reco`** (M1), or move it out of the tree. It is a rotation trap.
12. **Split the `env_file` lists per service** (H4) — the compose file already prescribes the fix at `:8-11`. A KB worker does not need Meta and Twilio credentials.
13. **`docker-compose.yml:37-38`** — change `${POSTGRES_PASSWORD:-collections}` to the `:?` fail-fast form that MinIO already uses at `:58-59`, and remove the inline DSNs from `alembic.ini:29` and `db.py:40`.
14. **`ops_screens.py:203`** — mark `accountSid` `"secret": True`.
15. **Add `.env.production` coverage to `Habibi/.gitignore`** (L10), matching `backend/.gitignore:5`.
16. **Add `env_bool` to `env_utils` and route all 26 sites through it** (M13). One truth set, including `"on"`. Then `db.py:93` should use `_read_env_file` like the two lines above it (M8).
17. **Route the nine hardcoded `Asia/Kolkata` sites through `agent_core/clock.py`** (H9), or delete `APP_TIMEZONE` — a knob that moves half a compliance control is worse than no knob.

### Structural

18. **Make `APP_ENV` unset a hard failure**, not a default. One `env_name()` that raises when neither variable is set, decide once whether `ENV` is an accepted alias (H7), and collapse the eleven call sites onto it. `env_allows_dev_key()` already exists for this and has zero real consumers — either use it or delete it.
19. **Introduce a settings object,** loaded once at startup, before anything reads configuration. That closes C4 structurally rather than by convention, gives H5's startup validation and a manifest for free, and is why H6's 83 undocumented variables, M14's sixteen private getters and L2's five dead ones all went unnoticed at ~100 files with no schema.
20. **Add a CI job that runs with `APP_ENV=production`.** Today the suite only exercises the permissive branch of every control in C1 — and, per A3's evidence, already works around the import-time freeze by reaching into private module globals (`monkeypatch.setattr(app_main, "_IS_PROD", True)` at `tests/test_auth_cors_middleware.py:223` and `tests/test_production_hardening.py:518`). **The tests know about C4.** They route around it rather than failing on it, which is why it survived to this audit.
21. **Add a `USER` directive and resource limits** (M12), and healthchecks for the four worker services.

---

## Analyst disagreements, resolved

- **`.env.example` hygiene — clean or a High finding?** The environment and secret-exposure analysts both graded it clean: every secret-named entry is an empty placeholder, `SKILL_PLATFORM_KEY` is a self-labelling `-not-for-prod` constant, and no rotation is warranted. The deployment analyst graded the same line High. **Both are right about different things, and the report carries both:** the *value* is not a leaked secret (so no rotation — recorded under "Git history"), but the *mechanism* is real and severe (so H1 stands), because setting the variable at all is what bypasses `sign.py`'s guard, in production, silently.
- **The dev key constants — Medium or High?** The secret analyst rated them Medium on the strength of the `NON_PROD_ENVS` guard, which is genuinely well built. That guard covers the *unset* case only; the template covers the *set* case in the wrong direction. Carried as H1 on the mechanism, with the guard credited under "What is done well".
- **`.env.example` assignment count.** Two independent parses agree on **161** active assignments; a third grep-based measure returned 155 by excluding empty values inconsistently. 161 is used.

## Corrections made during verification

- Two analysts cited `.gitignore:81-83`, `backend/.gitignore:111-112` and `.dockerignore:12-14` for the ignore rules. Direct reads: root `.gitignore` is **39 lines** with the env block at **:13-16**; `backend/.gitignore` is **10 lines** with `.env`/`.env.*`/`!.env.example` at **:4-6**. Only the `.dockerignore` reference was correct. All three are corrected above.
- One analyst placed `APP_ENV` at `.env:146`; `grep -n` puts it at **:145**. Corrected.
- `DEFAULT_DATABASE_URL` was cited at `db.py:39`; it is at **`:40`**. Corrected in M4.
- **A draft of M8 claimed `load_env()` must run before `db` is imported.** Reading `db.py:52-80` refuted it: `db.py` deliberately does *not* call `load_env()` and reads `.env` directly for the two values that matter. The finding was rewritten around what is actually exposed — the nine settings with no such fallback.
- **A draft of this report gave "set `APP_ENV=production`" as the single highest-value fix.** C4 shows that on the documented bare-metal path it does nothing. The recommendation now has two halves and the ordering is explicit. This is the correction that matters most: the earlier version would have produced a deployment believed to be hardened and not.
- **A draft claimed "boolean parsing is consistently robust" under *What is done well*.** It is consistently *case*-robust; it is not consistent about which words are true. Four truth sets, one of which turns TLS off — corrected, and moved to M13.
- Every other `file:line` in this report's Critical and High findings was re-read directly and matched.

---

## What could not be verified

- **Whether any credential in `backend/.env` is currently valid.** No vendor endpoint was called. "Live-shaped" means format-consistent with a real credential and inconsistent with a placeholder — not proof of validity. `.env:385` notes the Fish free model expired 2026-08-31, so at least one is likely already dead.
- **Whether the MinIO SDK's exception text can include an access-key id** (H2). The internal-topology disclosure is certain; the credential component was not confirmed by executing a failing auth call.
- **Whether H3's gap has already deposited a credential into the local log files.** They are gitignored and were not read.
- **Git history was scanned for added `.env` paths and for credential-shaped literals in commit diffs.** A secret pasted into an ordinary source file under an unusual name and later removed would evade both. A dedicated history scanner (`gitleaks`, `trufflehog`) is the right tool for a definitive answer.
- **How production is actually launched — and C4's severity depends on it.** No Kubernetes manifests, no Helm chart, no `docker-compose.prod.yml`, no deploy script, and no frontend Dockerfile or web-server config exist in the tree. The two candidate paths were inferred from `main.py:3`'s docstring, `run_stack.ps1:43`, `docker-compose.yml:80-81` and `.dockerignore:12`. **If production is always containerised, C4 is latent rather than live** — compose's `env_file` puts `.env` into the process environment before Python starts, so the ordering never bites. If anything runs `uvicorn main:app` directly, it is live. This is the single question whose answer would most change this report, and it cannot be settled from the repository. Every claim about container configuration is static; no container was built or run.
- **H6's 83 undocumented reads are a lower bound.** The sweep covers the enumerated read patterns and helpers; a read through an indirection not in that set, or a dynamically constructed name from a provider prefix not in the registry, would be missed.
- **`PRAXIST-main/`** is a vendored third-party tree inside this repository. It was included in the provider-literal scan and excluded from everything else.
