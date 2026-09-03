# 28 — Python correctness, maintainability, and type safety

**Scope:** `backend/` (API, workers, voice, `agent_core`). `PRAXIST-main/` excluded. Habibi is TypeScript and out of this report.
**Date:** 2026-09-02
**Mode:** Read-only. Ruff was run **check-only**. No `--fix`. `pyproject.toml` was not modified. No application file was changed except this report.
**Method:** five parallel analysts — Ruff/static, typing, async, exceptions, architecture — plus a parent verification pass. Tool counts below were produced this session. Claims that failed a second source check were dropped.

Companion reports: [04-backend-architecture.md](./04-backend-architecture.md) (god modules), [07-dead-code.md](./07-dead-code.md) (reachability; vulture configured but not installed), [10-complexity-smells.md](./10-complexity-smells.md) (size vs depth), [17-state-cache.md](./17-state-cache.md) (`_perms_cache` TTL).

This is a **quality** audit. “P0” here means a pattern that is already incorrect under load or that two live paths disagree about, not a CVE.

---

## Verdict

**Ruff is a real gate for pyflakes. It is not a quality system. There is no type checker.**

CI runs `ruff check .` before Postgres comes up (`.github/workflows/backend-pytest.yml:97-101`). Default Ruff (E4/E7/E9 + F, target `py312`) reports **zero** findings on application code. Unused imports are gone. There are **zero** B006 mutable defaults. That bar is held.

Everything else is optional documentation:

- No `[tool.mypy]`, no `[tool.pyright]`, no `[tool.pyrefly]`, no `mypy.ini`, no `pyrightconfig.json`. CI has no Python typecheck job (frontend has `frontend-typecheck.yml`; backend does not).
- Enabling ANN/BLE/UP/I on the same tree, check-only, yields **~4,800** diagnostics the current config cannot see: 1,852 missing argument types, 856 `Any` in signatures, 295 blind `except Exception`, 251 `datetime.timezone.utc` nits.
- Two Python dialects occupy one package. The CRM shell (`db.py`, most of `main.py`) speaks `dict[str, Any]`, lazy imports, and sync FastAPI. `agent_core/` speaks dataclasses, `ToolResult`, and a documented “stay sync, voice wraps `asyncio.to_thread`” contract. New work lands in whichever dialect the file already uses.

The async story is **intentional, not accidental** — and then inconsistently applied. CRM routes are correctly `def` (Starlette threadpool + sync SQLAlchemy). Voice tools correctly hop off the Pipecat loop. Several `async def` HTTP handlers still run sync DB or Azure on the event loop after `await request.body()` / `form()`.

Do not “asyncify `db.py`.” Do not enable ANN in CI. The useful moves are local: offload the mixed async routes, stop copying `env_int`, and treat `except Exception` on non-audio paths as a review question rather than a house style.

---

## What was measured

| Tool | How | Result |
|---|---|---|
| Ruff default (`ruff.toml`) | `ruff check . --exclude .venv --exclude alembic` | **0** findings, exit 0 |
| Ruff extra (check-only, not config) | `--select F,E4,E7,E9,BLE,B006,B008,B905,ASYNC,ANN,UP,I001 --statistics` | counts below |
| Type checker | config search | **none** |
| CI | `.github/workflows/backend-pytest.yml` | `ruff check .` then pytest; no mypy/pyright |
| Vulture | `[tool.vulture]` in `pyproject.toml` | configured; **not in `requirements.txt`**; not run (report 07) |

`ruff.toml` does not exclude `.venv`. A naive local `ruff check .` this session sat for **~7 minutes** (conda hook + venv walk) before returning empty. CI is fast because GitHub’s pip install is not a local `.venv` inside the lint root. That is a developer-experience defect, not a CI miss.

---

## Ruff configuration

```1:16:backend/ruff.toml
# Default rule set (E4/E7/E9 + F). Do not auto-fix unused names without
# checking whether they are re-exports or leftover after a refactor.
target-version = "py312"

[lint]
# `from module import name as name` is an explicit re-export (PEP 484).

[lint.per-file-ignores]
# These modules set DB_PROCESS_ROLE / sys.path / load_env() before importing
# db and friends. Moving those imports to the top binds config too early.
"bot_worker.py" = ["E402"]
"worker.py" = ["E402"]
"voice/bot.py" = ["E402"]
"voice/spike.py" = ["E402"]
"voice/workers/*.py" = ["E402"]
"scripts/*.py" = ["E402"]
```

Pinned in `requirements.txt:26-30` as `ruff==0.6.9` because the file existed for months as documentation with no package. That comment is still accurate about *scope*: E402 ignores are the only non-default policy.

### Extra-select census (not gated)

| Code | Count | Meaning |
|---|---|---|
| ANN001 | 1852 | missing argument type |
| ANN401 | 856 | `Any` in signature |
| ANN201 | 764 | public function missing return type |
| ANN202 | 297 | private function missing return type |
| **BLE001** | **295** | `except Exception` |
| UP017 | 251 | `datetime.timezone.utc` |
| I001 | 168 | unsorted imports |
| B905 | 46 | `zip` without `strict=` |
| B008 | 5 | `File()` in FastAPI defaults — **false positive** |
| B006 | **0** | mutable default argument |
| ASYNC109 | 2 | async def with `timeout` param — Pipecat-shaped, not a bug |
| F401 / F841 | **0** | unused import / unused variable |

ANN401 concentration: `db.py` 149, then `contact_policy.py` 29, `capture.py` 26, `call_closer.py` 23. The persistence magnet is the untyped core.

BLE001 concentration: `voice/bot.py` **57**, `db.py` 18, `voice/tools.py` 18, `voice/crm_sink.py` 15, `main.py` 13. Audio-path volume is the product contract (“never raise on the audio path”). CRM-path volume is not the same contract.

---

## Typing

**There is no type checker.** Public functions are annotated when a human felt like it. `from __future__ import annotations` is widespread. `X | None` is the modern form; `Optional[` / `List[` py2-era aliases are not the house style.

There is **no `TypedDict`** in `backend/` (search this session: zero hits). The three live type shapes are:

| Shape | Where | Job |
|---|---|---|
| Pydantic `BaseModel` | `schemas.py` (3,453 lines, **100** subclasses) | HTTP request/response for CRM screens that got models |
| `@dataclass` | `agent_core/` (treatment, reco, providers, `ToolResult`, `VoiceSession`) | domain objects with behaviour |
| `dict[str, Any]` | `db.py` (~18k lines), many `main.py` bodies | persistence DTO **and** HTTP payload |

`main.py` imports a large Pydantic catalog (`:49+`) and still has **32** handlers typed `payload: dict[str, Any]` (Agent Studio cards/skills, vault, A2A, gateway canary, floor approval, …). Neighbouring billing/consent/dispute routes take `BudgetRuleUpsertRequest` / `ConsentPatchRequest`. Same HTTP job, two contracts: FastAPI validates one and forwards the other as a bag.

`db.py` public functions typically return `dict[str, Any]` or `list[dict[str, Any]]` (`readiness` at `:330` is representative). `_rows` / `_one` are the serialization layer. Callers never see a typed row.

`agent_core.tools.domain.ToolResult` (`:33-40`) is the dialect the unification plan wanted: one dataclass, `field(default_factory=dict)` (not a mutable default), spoken summary + entity. Voice wraps those sync handlers in `asyncio.to_thread`. WhatsApp calls them on a worker thread. That boundary is **load-bearing and documented** (`domain.py:1-13`).

`# type: ignore[no-untyped-def]` appears on middleware (`main.py:598`). Without a checker it is a comment.

**Verdict:** types are documentation on the CRM spine and structure on the `agent_core` island. Enabling pyright in `strict` on `db.py` would be a multi-week rewrite, not a CI checkbox.

---

## Async / sync boundary

SQLAlchemy is **sync** (`db.py:138` `create_engine`, no `create_async_engine`). That decides the architecture.

### The intentional split

| Process | Loop | I/O style |
|---|---|---|
| API CRM routes | Starlette threadpool | `def` handlers, sync `engine.begin()` |
| API body/form/websocket | asyncio | `async def` because `await request.body()` / `form()` / WS |
| Voice / Pipecat | asyncio | handlers `async def`; **DB and Azure sync SDK** via `asyncio.to_thread` |
| `bot_worker` / `worker` | threads | sync throughout |
| Lifespan | asyncio | boot work in `to_thread` (`main.py:441-482`) |

`agent_core.tools.domain` states the rule explicitly: stay synchronous; the voice bot wraps. `voice/tools.py` has dozens of `await asyncio.to_thread(...)` call sites. `voice/llm_pool.py` uses `threading.Lock` around client construction because Pipecat constructors are not on one event-loop thread — documented, verified earlier (report 26).

Most of `main.py` is correctly `def` (health, customers, inbox, Agent Studio GETs, billing). FastAPI runs those in a threadpool. Mixing them into `async def` would be the bug.

### The accidental mix

Some handlers are `async def` **only** to read the body, then they block the loop on Postgres:

```825:850:backend/main.py
@app.post("/webhooks/payments/{provider}")
async def payment_provider_webhook(provider: str, request: Request):
    ...
    raw = await request.body()
    ...
    with db.engine.begin() as conn:
        try:
            return payments.record_payment(
```

Same shape: `twilio_voice_outbound` (`:3732-3757`) — `async def`, then `with db.engine.begin()`. Contrast siblings that got it right: `stt_transcribe` (`:3287`) and `whatsapp_webhook_receive` (`:4618`) use `asyncio.to_thread`.

B008 hits on `File(...)` defaults (`main.py:1649,2334,3271,4433,4470`) are FastAPI’s documented idiom, not mutable-default bugs. ASYNC109 on `voice/bot.py:231` and `voice/tools.py:113` is a `timeout` parameter name colliding with a Ruff heuristic.

**Verdict:** the boundary is designed. The defect is a small set of webhook/telephony routes that became `async` for Starlette reasons and never hopped the DB call.

---

## Exceptions

`_handle_write` (`main.py:720-738`) is the CRM write pattern done well: `KeyError` → 404, `PermissionError` → 403, `ValueError` → 409, `IntegrityError` → 409 without leaking psycopg. That is a typed hierarchy in practice, even if the functions still raise builtin exceptions with string codes (`"constraint_violation"`).

Elsewhere the house style is `except Exception`.

| Kind | Example | Judgement |
|---|---|---|
| Audio path, log + continue | `voice/bot.py` ×57 BLE001 | Product contract. Do not “fix” into raising. |
| Ready probe, log + degrade | `db.readiness` `:344-353` | Correct: never stringify DSN to LB. |
| Optional boot seed | lifespan `except Exception` + warning (`:454-484`) | Correct for catalog sync; prod still has the engine. |
| Fail-open identity | `db.py:425-430` `_actor_user_id`: any failure → process `ACTOR_USER_ID` | **Wrong dialect.** Import bugs look like “the default actor.” |
| Customer 360 degrade | `db.py:1273-1275` treatment snapshot → `None` | Documented degraded view; still a blind except. |
| Contact gate | `bot_runtime.py:158-160` gate failure → `None` (allow) | Logged; fail-open on the policy path. |
| Metrics | `main.py:383-385` | Correct: instrumentation must not fail the request. |

No bare `except:` turned up in the sampled application modules (agent_core, voice, main, db, azure_openai, bot_runtime, sandbox). BLE001 is the real class.

Exception *types* for LLM failures are stringy `RuntimeError("azure_chat_no_choices")` / `RuntimeError("llm_gateway_http_failed:…")` rather than a small hierarchy. Callers branch on message prefixes or treat all failures as “degrade.” Fine for capture-first; expensive to grep.

---

## Architecture / inconsistent patterns

### Same responsibility, N implementations

| Job | Implementations |
|---|---|
| Parse env int | `env_utils.env_int` (canonical, no log); `bot_runtime._env_int`; `agent_core.reco.config._env_int` (logs); `agent_core.treatment.policy._env_int` (no log, local `import os`) |
| HTTP write errors | `_handle_write` vs inline `except ValueError` in webhooks vs raw raise |
| HTTP body | Pydantic model vs `dict[str, Any]` vs `Request` + `json.loads` |
| Domain result | `ToolResult` dataclass vs `dict[str, Any]` from `db.*` vs Pydantic response |
| Provider/service client | module singleton + lock (`azure_openai`, `llm_pool`, `azure_speech._http`) |
| Authz | FastAPI `Depends(_authz_guard)` global — **the one real DI** |
| Actor / tenant | `ContextVar` (`actor_context`, `tenant_context`, `request_context`) — correct vs thread-local |
| Permission snapshot | process dict `_perms_cache` (report 17: 30s TTL, test-only invalidate) |

`env_utils.py:1-12` exists *because* a second copy drifted. Three copies remain. `reco.config._env_int` warns on garbage; `treatment.policy._env_int` does not. That is the bug `env_utils` was written to end.

### Import cycles

`db.py` is the cycle hub: **dozens** of function-local `from agent_core…` imports (cards, treatment, authority, tuning, change_log, canary, live_qa). `main.py` handlers similarly `import payments` / `from voice import twilio_ops` at call time. E402 per-file ignores on workers are the other half: `load_env()` / `DB_PROCESS_ROLE` must run before `import db`.

This is not sloppiness on the worker entrypoints. It **is** a maintainability tax on `db.py`: the persistence module knows every Locked Engine by name.

### God modules (re-verified line counts)

| File | Lines |
|---|---|
| `db.py` | 18,087 |
| `main.py` | 5,448 |
| `schemas.py` | 3,453 |
| `voice/tools.py` | 2,914 |
| `voice/bot.py` | 2,622 |

Zero `APIRouter`s. ~314 `@app` routes. Persistence, DTO mapping, and several engine snapshots live in `db.py`. Report 04/10 already named these; the typing and exception dialects follow the same cut.

### Global state (not automatically a bug)

Process-wide: `db.engine`, `azure_openai._client` / `_analysis_client`, `voice.llm_pool._client`, `azure_speech._http_client`, `authz._perms_cache`, `llm_gateway._spend_inr`, embed LRU. Request-scoped: ContextVars. The missing piece is a **named owner** for “how we construct a singleton,” not the singletons themselves. Voice vs API already have two Azure clients (report 26).

### Dataclass defaults

`ToolResult.data: dict[str, Any] = field(default_factory=dict)` — correct. Ruff B006 = 0 across the tree. Do not hunt mutable defaults; they were already cleaned.

---

## Confirmed findings

### P0 — incorrect under the stated async model

**F1. `async def` HTTP handlers that take the DB (or Azure) lock on the event loop.**
Verified siblings that already use `to_thread`: lifespan boot, STT, WhatsApp ingest, KB upload, Twilio *call* status. Verified siblings that still block the loop after `await body/form`:

| Route | File | What runs on the loop |
|---|---|---|
| Payment PSP webhook | `main.py:826-850` | `engine.begin` + `record_payment` |
| Payment-events webhook | `main.py:858+` | same pattern |
| Twilio SMS status | `main.py:3670-3723` | `engine.begin` + receipt insert |
| Twilio voice outbound | `main.py:3732-3757` | mission/contact_policy + DB; bare-number path also sync Twilio HTTP |
| Document ingest | `main.py:1645-1668` | `ingest_customer_document` → sync DB + `chat_with_tools` |
| Skill zip import | `main.py:2334+` | `upsert_skill_from_pack` after async read |

Floor SSE (`stream_floor_copilot`, sync generator with Azure polish) and `_authz_guard` DB on permission-cache miss are the same class, briefer. Compose runs **one** uvicorn worker (`--workers 1`), so these stalls are process-wide, not per-worker.

**Fix:** `await asyncio.to_thread(...)` the sync work, matching WhatsApp ingest. Do not migrate `db.py` to async SQLAlchemy.

### P1 — dialects that will bite the next change

**F2. No type checker; `dict[str, Any]` is the CRM schema.**
856 ANN401, 149 of them in `db.py`. `schemas.py` has 100 Pydantic models that do not cover Agent Studio writes. A field rename in SQL is a silent KeyError at the UI.

**F3. Ruff gates pyflakes, not the rules that describe this codebase.**
295 BLE001 and 1,852 ANN001 are invisible in CI. Expanding to ANN would red-build the repo for years. Expanding to BLE on `voice/` would fight the audio contract. The useful slice is BLE on `db.py` / `bot_runtime.py` / `agent_core/` excluding documented degrade paths.

**F4. Blind except fail-open on identity and outreach.**
- `db.py:425-430`: if `actor_context` raises for any reason, the process default actor is used.
- `db.py:8601-8606`: `contact_policy.evaluate` failure on outreach — if the customer is not DND, the helper **returns allowed** from preferred-window alone, **with no log**. That is fail-open on the contact Gate, not the audio contract.

Silent `pass` on ops hooks (`voice/bot.py` idle alert enqueue, `voice/bot_turn_state.py` first-speech callback) is the same class on the voice side: fail-open without the loud log the engines usually pair with it.

**F5. Three `env_int` helpers after a fourth was introduced to replace them.**
`env_utils.env_int` vs `bot_runtime.py:38` vs `reco/config.py:42` vs `treatment/policy.py:422`. Logging behaviour already disagrees.

**F6. HTTP mutating routes disagree on validation.**
32 `payload: dict[str, Any]` next to Pydantic siblings. FastAPI will not 422 a missing Agent Studio field that a Consent patch would catch.

**F7. `db.py` imports the domain it is supposed to serve.**
Function-local `agent_core` imports are cycle-breakers. They also mean a treatment bug can crash a customer GET unless wrapped in BLE001 (it is: `:1273`). Persistence should call engines through a narrow port, not through 40 inline imports.

**F7b. AgentTuning is a product name for a dict.**
`agent_core/tuning.py` `normalize_tuning(raw: dict[str, Any] | None) -> dict[str, Any]`. Agent Card is Pydantic; tuning is clamped JSONB. IDE/refactor cannot see a missing knob. `TypedDict` is unused in `backend/` (zero hits). Live Tool Grant remains the old formulas: `agent_core.tools.grant` is imported from **tests only**.

### P2 — hygiene

**F8. Local Ruff version drift.** CI and `backend/.venv` pin `ruff==0.6.9`. A PATH that hits conda Ruff (observed 0.8.6 this session) is a different tool. Ruff’s *default* excludes already skip `.venv`; a seven-minute local run is a wrong binary, not a missing exclude. Pin the command to `.venv\Scripts\ruff.exe`.

**F9. I001 / UP017 / B905 are noise relative to F1–F7.** 168 import sorts and 251 timezone aliases do not belong in the first quality PR.

**F10. B008 `File()` and ASYNC109 `timeout=` are false positives** if those rule codes are ever enabled. Per-file ignore, do not “fix” FastAPI signatures.

---

## What is already good (do not “fix”)

- Default Ruff **clean**. Do not auto-fix F401 re-exports (`ruff.toml` comment).
- **Zero mutable defaults** (B006).
- Sync FastAPI + sync SQLAlchemy for CRM. That is the correct Python pattern here.
- Voice `to_thread` + `ToolResult` + documented sync domain handlers.
- `_handle_write` exception mapping.
- ContextVars for actor / tenant / request id, not `threading.local`.
- E402 ignores on worker entrypoints — `load_env()` before `import db` is load-bearing.
- Lifespan boot in `to_thread`; engine dispose in `finally`.
- `from __future__ import annotations` and `py312` target.
- Audio-path `except Exception`: a product rule, not sloppiness.

---

## Prioritized consolidation

1. **Offload mixed async routes** (F1). Match `whatsapp_webhook_receive`. Payments, SMS status, outbound reserve, vision ingest, skill import.
2. **Log or fail-closed the contact-policy swallow** (F4). `db.py:8601` must not admit outreach on an exception.
3. **Delete duplicate `_env_int`** (F5). One import from `env_utils`.
4. **Stop adding `payload: dict[str, Any]`** on new mutating routes (F6). Use a Pydantic model or a shared `_handle_write` input type.
5. **If Ruff grows:** BLE on `agent_core` + `bot_runtime` with per-file ignores on `voice/`. Do **not** enable ANN. Do **not** enable I/UP as a quality program. Invoke the venv binary, not conda Ruff.
6. **Do not add mypy/pyright in CI** until `db.py` has a TypedDict or dataclass layer for the screens that still return bags. A red type job that everyone `--ignore`s is worse than none.

Do not rewrite `db.py` into async SQLAlchemy. Do not replace dataclasses with Pydantic in Locked Engines. Do not run `ruff check --fix` on ANN/UP in a drive-by.
