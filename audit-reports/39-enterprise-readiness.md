# 39 — Enterprise production readiness

**Scope:** `backend/` and `Habibi/src`. `PRAXIST-main/` excluded (vendored; 4,518 of 5,879 tracked files, not in the backend image).
**Date:** 2026-09-03
**Mode:** Read-only. No application file was modified. No service was started or restarted. No migration, `pytest`, or scanner was run. No request was sent at a live target. No secret value was read or recorded — credential variables are reported as present/empty only.
**Question:** would a regulated collections operator put live borrowers, live money, and live PSTN on this tree as it stands — and still be able to explain a 3am incident?

**Method.** Six specialist lenses, each run as an independent reviewer with instructions to treat prior reports 01–37 as *hypotheses only* and to re-derive every claim from source with a `file:line` citation: architecture, security, reliability, testing, maintainability, operational-readiness. A seventh (docs/ADR accuracy) was delegated by the maintainability lens to close its own open item. The parent independently measured file sizes, route counts, test counts, CI content, and the shipped non-secret environment flags, and reconciled every disagreement between lenses before scoring.

**Supersedes** the 11:30 draft of this report (preserved at `.39-superseded-1130.md.bak`), whose own method note records that its security lens was never independently run. That lens has now been run, and it is the one that moved most. A reconciliation table appears at the end.

**Scoring rule.** 10 = fail-closed, scanned, operable, and the documented owner is the live path. 6 = sound with a named, bounded gap. 3–4 = a path that can contact a borrower twice, misreport money, or run with authentication off. **No score is an average.** A family score is capped by its weakest production-blocking member, and the composite is capped the same way — averaging a go-live blocker against a strength hides the blocker, which is the failure mode this report exists to prevent.

---

## Verdict

**Not enterprise production-ready. Composite 4 / 10.**

Two findings must be read together, because neither is alarming alone and together they are the whole assessment:

> The shipped `backend/.env` sets **`APP_ENV=dev`** with `API_KEY` and `API_KEY_MAP` **present but empty** — which turns authentication *and* authorization off together — while **`TREATMENT_MODE=live`**, `BILLING_ENV=production`, and `BOT_ENVIRONMENT=production`.

Verified directly by the parent, without reading any secret value. The treatment executor is authorised to place real calls and send real messages to real borrowers, on a process whose front door is open. `VOICE_WS_PROXY_SECRET` and `TWILIO_AUTH_TOKEN` are both **set and both ignored**, because each check short-circuits on `not _IS_PROD` (`main.py:3479`, `:3396`).

That is the envelope. Inside it is a genuinely well-engineered product, and this report is emphatic about that: a permission registry with a CI totality proof, Locked Engines for contact/authority/treatment/cadence, `numeric(14,2)` money throughout, tamper-evident audit hashing with a test that mutates a stored row to prove it, 2,431 backend test functions with `MagicMock` appearing exactly once, a Prometheus registry with bounded cardinality written by someone who has carried a pager, and a per-call export bundle for incident response. The interior is not the problem.

The problem is that **the controls are libraries the live path may skip.** Both accepted ADRs are unimplemented — `agent_core/tools/grant.py` (ADR-0001) has zero production importers, and ADR-0002's deny-all fails open on three separate runtimes. RLS is fully implemented in `rls.py` and called by nothing at boot. The JSON log formatter with PII redaction exists and never installs. The Prometheus endpoint is real and nothing scrapes it. The DB-backed kill switch was built for exactly this problem and `TREATMENT_MODE` was never migrated into it.

**This is not a rewrite. It is a wiring job on a system that already contains most of its own answers.**

---

## Scorecard

| Dimension | Score / 10 | Confidence | Evidence | Main risks |
|---|---|---|---|---|
| **Architecture** | **3** | High | `db.py` 18,087 LOC / 451 defs / 101 tables / 200 importers; `main.py` 5,448 LOC / **314 route decorators / 0 `APIRouter`**; `db.py:26` imports `schemas` | No unit of ownership to hand a second team. Persistence depends on the API contract layer. |
| **Code quality** | **5** | High | `voice/tools.py:310` `build_tools` = 2,605 LOC, cc≈424; `voice/bot.py:297` `run_bot` = 2,026 LOC; 169 functions >100 LOC, 77 with cc>25; **no mypy/pyright config exists anywhere**; `ruff.toml` = default `E`+`F` only | The two hottest live-call paths are the two least testable functions. A green ruff run proves almost nothing. |
| **Security** | **3** | High | `main.py:292` (`auth_required = bool(single or key_map)`); `authz.py:624-639`, `:704-709`; `bot_tools.py:831`; `db.py:8994-9010` | Tunnel URL = unauthenticated regulated CRM. Revoking a role's permissions *grants* them. Prompt injection reaches live CRM write tools. |
| **Reliability** | **5** | High | `voice/llm_pool.py:48` (30s × 3, no breaker); `outbound.py:743-751` → `campaigns.py:611-625`; `bot_worker.py:93` unguarded ahead of `:95-163` | Five independent paths to a second ring on a real borrower. One poison row silently starves every downstream queue. |
| **Data** | **6** | High | Money `numeric(14,2)` throughout (`sql/02_customer_account.sql:86-158`); `sql/05_collections.sql:12-37` (promises, no natural key); `agent_core/change_log.py:110-134`, `:57` | Duplicate promise-to-pay on retry. Audit hash chain covers **bot config only** — money and consent events are unchained. |
| **Testing** | **6** | High | 186 files / **2,431** test functions; `MagicMock` ×1; `test_agent_change_log.py:155`; **144 of 275 routes untouched**; `Habibi/vitest.config.ts:22` `environment: "node"` | Deep unit coverage, near-zero HTTP-layer coverage. Component tests are structurally impossible. |
| **Operations** | **5** | High | `observability.py:476` (returns unless `LOG_FORMAT=json`, which is unset); `/metrics` real and **unscraped**; `agent_core/telemetry.py:13-18` span is a permanent no-op; `worker`/`bot_worker`/`voice` have no healthcheck | `logger.info` is discarded in the `api` process on both launch paths. No distributed tracing exists. |
| **Configuration** | **4** | High | `main.py:204`, `usage_meter.py:292`, `bot_jobs.py:40`, `agent_core/treatment/config.py:64` | **Four independent "am I live?" switches that disagree in the shipped file.** `TREATMENT_MODE=live` has no operator kill switch. |
| *(Deployability)* | **2** | High | `.github/workflows/` = pytest + typecheck only; no runbook; `PUBLIC_BASE_URL` is an ngrok host | No deploy pipeline, no rollback, no Postgres backup/restore procedure. Production ingress is a free-tier tunnel. |
| *(Documentation)* | **5** | Med-High | `backend/README.md:31`; `decision-intelligence-engine.md:3` | The documented first-run command **cannot work on a fresh volume**. One doc says "not yet built" about 24 shipped modules. |

**Composite: 4 / 10** (confidence High). The unweighted mean of the eight primary families is 4.6. The composite is **4** because security, configuration, and deployability each independently block a regulated go-live, and reliability's duplicate-contact paths are a regulatory exposure in this specific domain.

---

## Sub-dimension detail

### Architecture — 3

| Sub-dimension | Score | Evidence |
|---|---|---|
| Modularity | **2** | `db.py` 18,087 LOC, 451 defs, **1 class**, SQL against 101 distinct tables (~60% of the 169 referenced anywhere). `main.py` 5,448 LOC, 314 route decorators, **zero `APIRouter` in the entire repo**. |
| Ownership | **4** | Genuinely good in `agent_core`: Agent Card has one owner (`cards/schema.py:376,409`), Tool Grant has one (`tools/grant.py:224`). Fails on Flow: `voice/bot.py:37` builds the hardcoded flow and `:1166` conditionally builds the authored one, and the comment at `:1158-1161` confirms it is "built after the hardcoded flow rather than instead of it" — both exist, both must be maintained. |
| Coupling | **2** | `db` fan-in = **200 files**. `main` fan-out = 85. Corroborated by **1,143 function-local imports** across backend production code (115 inside `db.py` alone) — modules defer importing `db` because importing it at the top does not work. |
| Cohesion | **3** | `db.py:1` docstring concedes two jobs: "Postgres accessors plus API response serializers". `db.py:26` imports `schemas` — **the persistence layer depends on the API contract layer.** 242 functions return untyped `dict[str, Any]`. |
| Dependency direction | **4** | Corrected during review. Top-level-only SCC analysis: largest true import cycle is **9 modules**, all conventional package-facade re-exports in `agent_core`. The 112-module SCC found on the all-imports pass is a *logical* cycle held apart by those 1,143 deferred imports and 66 `# noqa: E402` markers. Managed, not chaotic — but undocumented, so "tidying" a deferred import to the top of a file breaks the build. |

**Counterweight the architecture lens insisted on: the frontend is not the problem, and would score ~7.** `Habibi/tsconfig.json` sets `strict: true`; the only `@ts-ignore` in `Habibi/src` is in generated `routeTree.gen.ts`; across 474 files and 1,646 internal edges the only cycle is the generated router bootstrap; 43 of 48 `api/*.ts` modules route through one HTTP seam at `api/config.ts`, which throws on production builds if mocks are enabled (`config.ts:16`).

### Code quality — 5

| Sub-dimension | Score | Evidence |
|---|---|---|
| Duplication | **6** | Verbatim duplication is *low* — an AST-normalised body hash found 4 groups, ~58 redundant LOC. The cost is semantic: **35 module-level constant values redeclared across files.** Worst: `frozenset({'opted_out','dnd','expired'})` in 5 modules under 4 different names (`contact_policy.py:37`, `payment_events.py:28`, `promise_fulfillment.py:29`, `capture.py:331`, `agent_core/reco/arbitration.py:39`); `'Asia/Kolkata'` in 6 under 4 names; a PII regex in 4. **A regulated consent rule can be fixed in one of five places.** |
| Complexity | **3** | `build_tools` (`voice/tools.py:310`) is a single **2,605-line function**, cc≈424, 89% of its file. `run_bot` (`voice/bot.py:297`) is 2,026 lines. 169 functions >100 LOC, 42 >200, 77 with cc>25. Nesting is *not* the problem (max ~4–6; the depth outliers are flat `elif` dispatch) — length and branching are. |
| Dead code | **8** | ≈2.4% (5,350 of 221,931 production LOC). No commented-out code anywhere across 682 comment runs. No `_old`/`.bak` files. The concentration: 1,333 LOC behind 12 permanently-false flags in `agent_core/platform_flags.py:18-62`, which makes two publish gates unable to fail (`cards/compile.py:716-718`). |
| Consistency | **5** | Plumbing is canonical (one HTTP seam, one error helper). Vocabulary is not: **96% `bot` / 4% `Mouth`** (3,598 tokens vs 145), with both appearing four lines apart inside one function (`bot_runtime.py:912` and `:931`). Two competing error paths in `main.py`: `_handle_write` at `:719` used 83 times, versus 113 hand-rolled `except`→`HTTPException`. |
| *Type safety* | **6** | Python: **no mypy or pyright configuration exists anywhere**; `pyproject.toml` holds only `[tool.vulture]`, for a tool that is in neither requirements nor CI. 43 `# type: ignore[...]` markers for a checker that has never run. Annotation coverage is 88.3% overall but **96% excluding `main.py`, which is 5.3%**. 2,714 `Any` (488 in `db.py`). TypeScript is the opposite: `strict: true`, 3 `any` in all of `Habibi/src`, all deliberately suppressed — though 61 non-null assertions are gated by neither tsc nor ESLint, and ESLint has no `parserOptions.project`, so zero type-aware rules run. |

### Security — 3

| Sub-dimension | Score | Evidence |
|---|---|---|
| Authentication | **2** | `main.py:292` — `auth_required = bool(single or key_map)`. **Absent credentials is a mode, not a refusal.** `_IS_PROD` is decided at import from the process env (`main.py:204-205`) and is a two-string allowlist, so `APP_ENV=staging` opens every gate. The prod boot refusal at `:431-433` is skipped because `APP_ENV=dev`. WebSockets: `/ws` is auth-exempt (`:233,250`) and `_voice_ws_upgrade_authorized` ends `return True` when not prod (`:3479`) — with `VOICE_WS_PROXY_SECRET` set and unused. Twilio: `:3396` returns `not _IS_PROD` on a missing signature, with `TWILIO_AUTH_TOKEN` set. A2A skips the middleware entirely (`:278`); identity is the request headers `X-SSL-Client-Verify`/`X-SSL-Client-DN` (`agent_core/a2a.py:23-32`), and no ingress config in this repo strips them. |
| Authorization | **3** | `authz.py:624-639` — enforcement follows whether credentials exist, so one missing variable disables both layers. No defence in depth. **Both report-18 claims confirmed at source:** (a) `authz.py:704-709` — a role with zero `role_permissions` rows yields `explicit == set()`, takes the `else` branch, and is handed its full `ROLE_DEFAULTS`; the UI shows `[]` while the resolver grants everything, and `:713` makes any role *named* `admin` un-revocable. (b) `agent_core/skills/runtime.py:184-185` returns `allowed=None` for a cardless mouth and `bot_tools.py:831` skips filtering on `None`. **Tenant isolation: effectively neither mechanism.** `rls.py` is complete (`apply:365`, `enable:417`, `status:545`) and reachable only from an operator script; nothing calls it at boot, and `main.py:393-396` lists RLS as deferred. Explicit assertions are partial — `db._assert_tenant_owns` (`:282-293`) is correct, but `_conversation_base_rows` (`db.py:8994-9010`), the **primary Inbox read**, filters on conversation id and `updated_after` only: no `tenant_id`, no visibility predicate. |
| Secrets | **5** | Nothing committed — `git log --all` over `backend/.env` and `Habibi/.env` returns nothing, `.gitignore` covers `**/.env`, `.dockerignore:12-14` keeps `.env` out of the image. Credit where due: tool-call audit redaction is *structural*, not remembered — `bot_jobs.record_tool_call` is the sole writer, redaction happens inside it (`bot_jobs.py:414-415`), and all four agent channels route through it (`voice/persist.py:401`, `bot_runtime.py:1005`, `mcp_tools.py:253`, `sandbox_runtime.py:329`), with idempotence pinned by `tests/test_tool_audit_is_redacted.py:153-155`. Two real gaps: `VITE_API_KEY` is baked into the browser bundle (`Habibi/src/api/config.ts:38,45`), and only `message` passes through `redact_text` (`observability.py:344-348`) — log `extra` fields and tracebacks are unredacted (`:370-379`), and `PII_DETECTORS` (`pii_redact.py:41-56`) carries no credential patterns. All five compose app services mount the full `.env`; the file says so itself at `docker-compose.yml:8-11`. |
| Injection | **5** | **Classic injection is clean, and verified as such** — no `shell=True`, `os.system`, `pickle`, `yaml.load`, `eval`, `exec`, or `verify=False` anywhere in backend application code. All 56 f-string SQL sites sampled interpolate fixed column maps or allowlisted identifiers with bound values. Both `dangerouslySetInnerHTML` sites take compile-time constants, not user data. The score is 5 because the real surface is **prompt injection**: a borrower's speech drives a tool loop whose catalog includes `create_promise_to_pay`, `flag_dispute`, `apply_goodwill`, `set_contact_preference` (`agent_core/tools/catalog.py:240-535`), and with a cardless mouth the grant filter is absent. Locked Engines still cap waiver *amounts*, so the hole is "run the catalog", not "raise the cap". SSRF egress is well defended (HTTPS-only, private-IP reject, no redirects) but resolves DNS then reconnects by hostname (`webhooks_dispatch.py:132-173`) — rebinding TOCTOU. `main.py:4595` compares the WhatsApp verify token with `==` (timing oracle). |
| Dependencies | **3** | Confidence Medium. **No pip-audit, npm audit, OSV, Trivy, Bandit, Semgrep, CodeQL, or Dependabot anywhere in CI.** No Python lockfile and no hashes; `requirements.txt:13` is a floating `twilio>=9.0,<10`. The frontend has a lockfile with integrity hashes but ships a *second* one (`bun.lock` alongside `package-lock.json`). npm findings are 4 high / 1 moderate, all indirect dev/build dependencies, none on a borrower-reachable path. The Starlette/FastAPI form-parsing CVE is already patched while `request.form()` is live on the Twilio path — that would otherwise be P1. |

### Reliability — 5

| Sub-dimension | Score | Evidence |
|---|---|---|
| Timeouts | **6** | 15 external client surfaces; 11 bounded. Four are not: `db.py:144-150` sets `statement_timeout` but **no `connect_timeout`**, so a Postgres that accepts TCP and stalls the handshake blocks the calling thread forever (`statement_timeout` never applies — no statement was sent); `voice/mesh_bus.py:45` Redis has no socket timeouts; `storage.py:166-168` MinIO has none, and `circuit_breaker.py:81-90` ages probe slots out to compensate — a workaround for the missing timeout, not a fix. The voice LLM is bounded but badly: `voice/llm_pool.py:48` is `Timeout(30.0, connect=10.0)` with `max_retries=2` and **no breaker** — a 90-second worst case of dead air, on every concurrent call, with no shed. Frontend is the strongest area: 6 of 7 `fetch` sites compose caller signal *and* default timeout (`api/config.ts:68-73`); one bypass at `routes/sandbox.lazy.tsx:432`. |
| Retries | **5** | `circuit_breaker.py` is **not** dead — it is wired into five real callers (`azure_openai.py:148,161`, `azure_speech.py:424`, `whatsapp.py:72,132`, `storage.py:168`) and surfaced on `/health` and Prometheus. It is absent from Twilio, the voice LLM pool, the LLM gateway, and Redis. `llm_gateway/client.py:114-130` retries 3× on 5xx with **no sleep at all**. `webhooks_dispatch.py:378` backs off correctly but with **no jitter**, so a recovering tenant endpoint takes every queued delivery in lockstep. The gold standard is in the same tree: `azure_speech.py:379-455` honours `Retry-After` with full jitter behind a semaphore. |
| Idempotency | **4** | `outbound.py:743-751` maps *any* Twilio exception to `{"placed": False}`. A read timeout at `voice/twilio_ops.py:265` (10s — a routine carrier latency) **after Twilio accepted the create** is indistinguishable from a rejection, and `campaigns.py:611-625` then re-queues the target. **The borrower is called twice.** Twilio's Calls API takes no idempotency key and none is sent. `cadence.py:224-228` makes the *opposite* choice on the same state — two schedulers, two answers. `payments.py:149-150` returns `{"ok": True, "idempotent": True}` on `status == "paid"` **without comparing `provider_ref`**, so a second genuine settlement is discarded as success. Webhook redelivery is handled **correctly** for delivery receipts (`sql/03_consent.sql:202-203` backs the `ON CONFLICT DO NOTHING` at `delivery_receipts.py:97`) and **incorrectly** for promises (`db.py:5144-5167`, no conflict clause, against a table with no natural-key constraint). The gap is not a missing pattern — it is one table having the index and the other not. |
| Failure isolation | **5** | The process split is real and correct. `bot_worker.py:218-223` has a top-level catch, so one bad row does not kill the worker — but `process_one_any` runs stages in fixed priority and only *some* are individually guarded. A permanently-raising row at `:93` means `:95-163` never execute, turning it into a 1.5s poison-pill loop: **WhatsApp, reminders, treatment, and webhooks all stop while the worker reports healthy.** Fire-and-forget tasks retain strong refs correctly, but done-callbacks only `discard` and never read `.exception()`; `voice/bot.py:1852-1853` (the max-duration and dead-air watchdogs) have **no done-callback at all** — if the dead-air watchdog raises, the call goes mute with nothing watching, and in the `api`/`voice_insurance` processes that exception is invisible. |

### Data — 6

| Sub-dimension | Score | Evidence |
|---|---|---|
| Integrity | **8** | **Money is `numeric(14,2)` throughout** — no float anywhere in the money path. Partial unique indexes for "exactly one current X" are excellent (`payment_intents`, `sql/05_collections.sql:85-90`). FKs and CHECKs are broadly present. Two gaps: `promises` (`sql/05_collections.sql:12-37`) has **no unique constraint on any natural key**, and `audit_log` (`sql/12_crosscutting.sql:20-29`) has only `id` as PK. |
| Transactions | **4** | `agent_core/treatment/enact.py:904-912` wraps `claim_due` **and** `enact_one` in one `engine.begin()`, and the SMS handler calls Twilio on that same connection — a rollback after a successful send is a second SMS. Same shape in `promise_fulfillment.py:~1014` and `payment_events.py:~668`. `payments.py:218-239` runs the bounce cure in `try/except Exception: logger.exception` with **no SAVEPOINT**, so the payment commits with the EMI cure silently skipped and the API returns `{ok: true}`; `db.py:5170-5176` repeats the shape, so it reads as a habit. The audit chain writes with the change it records (good) but `_chain_head` reads `MAX(seq)` with **no lock** and no unique constraint on `(tenant_id, entity_type, seq)` — two concurrent publishes both write `seq+1` with the same `prevHash`, forking the chain, and `verify_chain` walks one branch and reports ok. |
| Migrations | **7** | 102 revisions, **every one defines `downgrade`** (5 are `pass`). CI enforces schema drift in **both** directions — `.github/workflows/backend-pytest.yml:113` derives expectations from `op.create_table`/`op.add_column`, and `tests/test_schema_parity.py` catches the reverse case (a column in `sql/*.sql` that no migration creates, which every fresh database has and every existing deployment lacks). That is rare and genuinely strong. Deductions: dual schema truth (`sql/*.sql` authoritative, baseline migration is `pass`), the parity check needs a scratch DB and is opt-in, and CI disables the Alembic round-trip (`RUN_ALEMBIC_ROUNDTRIP: "0"`). |

**Framing correction, and it matters for an auditor.** `agent_core/change_log.py:57` sets `_ENTITY_TYPE = "bot"`, and `:162` is the **only** `INSERT INTO audit_log` in the Python tree. The hash chain is therefore tamper-evident **for agent-card configuration publishes only**. Money movements, consent changes, and contact events carry no chain and no `prevHash`, and `verify_chain` only ever walks the `bot` entity. State this capability as *"hash-chained for bot configuration; unchained for financial and consent events"* — not as a property of the audit log.

### Testing — 6

| Sub-dimension | Score | Evidence |
|---|---|---|
| Capability coverage | **7** | **This overturns prior report 22.** All eleven high-risk capabilities checked have real behaviour-asserting tests: audit hash chaining (`test_agent_change_log.py:155` mutates a stored payload directly in Postgres and asserts `entry_hash_mismatch`; `:180` catches deletion), contact windows (`test_contact_policy.py:156` admits 10:00 IST, denies 19:01 and 07:59 with `outside_calling_hours`), webhook SSRF (`test_webhooks_dispatch.py:270`), tool grant (`test_tool_grant.py:99` proves cardless deny-all *in the module*, `:59` proves offer ⊆ grant), plus publish gates, flow transitions, handoffs, cadence, outcome recording, PTP idempotency and tenant isolation. The deduction is entirely about **layer**: 144 of 275 routes untouched by any test, and only 17 files use `TestClient`. |
| Regression protection | **5** | Near-zero over-mocking — `MagicMock`/`AsyncMock` appears **once in 2,431 tests**; seams are drawn at network and clock edges and the real handler is called. Status-code-only assertions are ~1.5% and sit where the status *is* the contract. Against that: **43 of 186 files inspect source text rather than run it** (`inspect.getsource` ×45, `read_text` ×40), worst at `test_outbound_studio_bindings.py:72-76`, which slices `main.py` with `src[start : start + 1800]` and asserts substrings — that survives inverted logic and breaks on a rename. **116 `pytest.skip()` across 55 files**, mostly guarded on seed presence, so a thin seed turns tenancy and compliance tests green silently. And the date rot is confirmed: `test_contact_policy.py:287` passes `promised_date="2026-09-01"` against a wall-clock rejection at `agent_core/tools/domain.py:724` — **permanently red as of two days ago**, not flaky, taking a daily-cap enforcement test with it. |
| *Infrastructure* | **6** | `tests/conftest.py:12-65` is the best asset in the estate — `db_tx` monkeypatches `db.engine` so handler-owned `engine.begin()` becomes `begin_nested()`, rolled back at teardown, used by 74 files; two autouse fixtures close real non-determinism. But it routes everything through **one shared connection**, so every `FOR UPDATE SKIP LOCKED` claim, advisory lock and uniqueness race is verified by a harness that structurally cannot produce contention. No `freezegun`, no `random.seed`. `pyproject.toml` has **no `[tool.pytest.ini_options]` at all**, so no `--strict-markers` and a typo'd marker is a silent no-op. |
| *Frontend* | **2** | `Habibi/vitest.config.ts:22` sets `environment: "node"` with an explicit comment: no jsdom. **No component, render, event-handler or accessibility test is possible in this repository.** 11 test files / 83 tests against 463 source files, 365 of them `.tsx` with zero behavioural coverage of any kind. What exists is good (`api/sandbox.test.ts:43-46` pins all four branches of a real past incident); two of the eleven are source-text greps. |

**What CI actually enforces** — better than prior reports claimed, and worth knowing precisely. Enforced: `ruff check .`; full `pytest -q` against real Postgres (pgvector pg16) **with voice dependencies installed**, so the 26 voice test files that import pipecat at module scope actually run; bidirectional schema-drift checking; `tsc --noEmit`; `vitest run`; and `npm run lint` — **which includes both design-token scanners** (`check-spacing-scale.mjs`, `check-type-scale.mjs`). The hypothesis that those scanners are ungated is **wrong**. Not enforced by anything: coverage (never measured), dependency audit, security scan, secret scanning, Dependabot, eslint warnings (62 react-hooks warnings pass; `--max-warnings 0` deliberately omitted with a rationale), and the Alembic round-trip. Both workflows are path-filtered, so a change touching neither `backend/**` nor `Habibi/**` gates nothing. Branch protection is not in the repo, so whether these are *required* to merge is unverifiable from the filesystem.

### Operations — 5

| Sub-dimension | Score | Evidence |
|---|---|---|
| Logs | **6** | Two corrections to prior hypotheses first: this is **not** a `print()`-debugging codebase (zero `print(` in `agent_core/`, `llm_gateway/`, `work_runtime/`), and the "root logger unconfigured" claim holds **only for `api` and `voice_insurance`** — `voice/bot.py:2617`, `worker.py:29` and `bot_worker.py:48` all configure logging correctly. But for those two processes it is true on **both** launch paths (`run_stack.ps1:43` and `Dockerfile:28` pass no `--log-config`), so uvicorn configures only its own loggers, `setup_logging()` returns at `observability.py:476` because `LOG_FORMAT` is unset, and the `basicConfig` fallback at `:481` is never reached. **Every `logger.info` from `main`, `db`, `authz`, `agent_core.*` in the api process is discarded**; warnings and above reach stderr via `logging.lastResort`, unformatted and without the request id. `agent_core.*` reasoning logs are dropped entirely in `voice_insurance` because `voice/workers/insurance.py:228` never calls `log_bridge.install()`. PII handling is good where logging works: JSON formatter redacts, transcripts redacted at write (`voice/persist.py:239`), phones truncated to last-4. |
| Metrics | **7** | A real, well-designed Prometheus registry with bounded cardinality, scrape-time collectors and authz gating (`authz.py:100,140,581`). **Nothing scrapes it** — no Prometheus in any compose file. Missing from it: LLM/ASR/TTS latency, tokens, cost, call-setup latency, failed calls, compliance-gate blocks. Do not confuse `/treatment/metrics` and `/leads/metrics` with this: those are per-request Postgres queries feeding operator screens, gated by business-analytics permissions, with no time series, no scraper and no retention. An SRE cannot alert on them. |
| Tracing | **2** | `agent_core/telemetry.py:13-18` — `span()` is a permanent no-op; the OpenTelemetry SDK is not in `requirements.txt` and no exporter is configured. There is no distributed tracing. Cross-process correlation is manual, via `voice/call_trace.py`. |
| Health checks | **7** | `/ready` (`main.py:759-777`) genuinely checks DB ping, pool headroom, MinIO and breaker states, and compose uses it. `/health` (`:753-756`) returns `{"status":"ok"}` unconditionally and is auth-exempt — a liveness probe that cannot fail. `worker`, `bot_worker`, `voice` and `voice_insurance` have **no healthcheck at all**, and the Dockerfile sets none. |

**"It is 3am and a borrower says the agent said something wrong."** What an on-call engineer can actually do — and it is better than the logging story implies, because someone built for this deliberately:

1. **The transcript is in Postgres**, redacted at write — `voice/persist.py:254` (turns), `:368` (tool calls), `:420` (per-turn understanding), `:618` (violations).
2. **A one-shot bundle exists**: `voice/call_export.py:50` `build_bundle(interaction_id)` assembles turns, tool calls, and latency p50/p95 for a single call. This is the first command to run.
3. **Cross-process correlation works**: `voice/call_trace.py:100-109` stamps `attempt`/`sid`/`session`/`interaction` at every hop, and logs at **WARNING on purpose** (`:112-122`) precisely so it survives the unconfigured root logger.
4. **Cost and tokens are attributable per interaction** (`usage_meter.py:232,372`).

What they **cannot** do: join the HTTP `X-Request-Id` to the call — the two id spaces never meet. See LLM latency on any dashboard. Search logs at all, because logs go to container stdout with no aggregation, no JSON, and the `api` process silently drops everything below WARNING.

### Configuration — 4

| Sub-dimension | Score | Evidence |
|---|---|---|
| Environment isolation | **3** | Four independent "am I live?" switches, disagreeing in the shipped file (table below). Boot validation exists and is good — `main.py:399-418` refuses to start on `APP_ENV=production` with deferred controls off, `:431-433` requires `API_KEY` — but **all of it is keyed on `APP_ENV`, which ships as `dev`, so none of it fires.** |
| Secret handling | **4** | `.env` correctly out of git and out of the image, but **all five app services mount the full file** (compose flags this itself at `docker-compose.yml:8-11`), there are no Docker secrets, and `VITE_API_KEY` is baked into the browser bundle at build time. |
| Feature flags | **6** | A genuine DB-backed, fail-closed **kill switch for outbound dialling** with an audit trail and `KNOWN_KEYS` so typos 404 (`platform_switches.py:39-140`). Against that: 15+ env flags read by scattered `os.getenv`, untyped, with no boot validation, and all 12 flags in `platform_flags.py:18-62` are absent from `.env` and therefore permanently off. |

**Shipped environment switches** (non-secret values only; credentials reported as presence/emptiness):

| Switch | file:line | Shipped | What it changes |
|---|---|---|---|
| `APP_ENV` | `main.py:204`, `env_utils.py:38` | **`dev`** | Fail-closed auth, OpenAPI exposure, hardening gate, dev vault/signing keys, WS gate, Twilio signature check |
| `TREATMENT_MODE` | `agent_core/treatment/config.py:64` | **`live`** | **Lets the executor actually send messages and dial borrowers** |
| `BILLING_ENV` | `usage_meter.py:292` | **`production`** | Which side of the money column usage lands on |
| `BOT_ENVIRONMENT` | `bot_jobs.py:40` | **`production`** | Environment stamp on bot job rows |
| `API_KEY` / `API_KEY_MAP` | `main.py:292,431-438` | **present, EMPTY** | CRM routes are public; boot refusal only fires if `APP_ENV=production` |
| `VOICE_WS_PROXY_SECRET` | `main.py:3479` | **set, IGNORED** | Gate returns `True` when not prod |
| `TWILIO_AUTH_TOKEN` | `main.py:3396` | **set, IGNORED** | Signature check returns `not _IS_PROD` |
| `LOG_FORMAT` | `observability.py:410,476` | **absent** | The entire JSON logging + redaction path |
| `SENTRY_DSN` | `observability.py:425` | **absent** | Error tracking (inert) |
| `outbound.enabled` (DB) | `platform_switches.py:39,133` | DB row, **fail-closed** | Master kill switch on every dial |

The migration that introduced the DB-backed kill switch (`alembic/versions/20260826_0102_platform_switches.py:3`) opens by stating that every gate on the dialler used to be an environment variable, and **names `TREATMENT_MODE` among them**. Only two keys were ever migrated. The one switch that authorises acting on real borrowers is still a process-restart-only env var with no operator kill switch.

---

## Go-live blockers, ranked

Each is cited to current source. 1–3 are regulatory or financial; 4–5 are the ability to know what happened.

**1 — Shut the envelope.** Decide `_IS_PROD` *after* `load_env()`; treat unrecognised `APP_ENV` as production rather than allowlisting two strings; make absent `API_KEY`/`API_KEY_MAP` a refusal to boot in every environment, not a mode (`main.py:204,292,431`). Delete the non-prod `return True` on the voice WS gate (`:3479`) and the `not _IS_PROD` on the Twilio signature check (`:3396`) — both secrets are already configured. Fix `authz.py:704-709` so an empty explicit grant means empty, not `ROLE_DEFAULTS`, and call `invalidate_permission_cache` from `replace_role_permissions`. Strip `X-SSL-Client-*` at ingress or stop trusting it (`main.py:278`, `agent_core/a2a.py:23-32`).

**2 — Implement ADR-0002, which is accepted and unbuilt on three runtimes.** `allowed is None` must deny, not skip the filter — voice (`voice/tools.py:2911-2913`), text/WhatsApp (`bot_tools.py:831` + the `TOOL_DEFINITIONS` fallback at `bot_runtime.py:947-951`), and sandbox (`sandbox_runtime.py:233`). The module that does this correctly already exists and is tested (`tools/grant.py`, `test_tool_grant.py:99`); it has zero production importers. This one survives locking the envelope, and it is the difference between "a borrower's words can run the CRM catalog" and not. GitHub issue #14 is open and labelled ready.

**3 — Stop double-contacting and stop misreporting money.** Send an idempotency key on the dial path or stop treating an ambiguous Twilio failure as "not placed" (`outbound.py:743-751` → `campaigns.py:611-625`); reconcile with the opposite decision `cadence.py:224-228` already makes. Key payment settlement on `provider_ref`, not intent status (`payments.py:149-150`). Add a natural-key unique index and `ON CONFLICT` to `promises`, copying `contact_delivery_events` (`sql/03_consent.sql:202-203`). Move carrier I/O outside the claim transaction (`enact.py:904-912`). Put the bounce cure on a SAVEPOINT or fail the payment (`payments.py:218-239`). Add a unique index on `(tenant_id, entity_type, seq)` and take a lock in `_chain_head`.

**4 — Make 3am possible.** Set `LOG_FORMAT=json` in compose and `.env.example`, or install a root handler even when it is unset (`observability.py:476`). Call `log_bridge.install()` in `voice/workers/insurance.py`. Scrape `/metrics` from both the API and the voice process. Healthcheck `worker`, `bot_worker`, `voice`, `voice_insurance`. Join `X-Request-Id` to the interaction id.

**5 — Fix the tests that are lying, and the doc that will break a new hire.** `test_contact_policy.py:287` is permanently red on a hardcoded date. Assert the demo seed is non-empty so the 116 seed-guarded skips cannot silently pass. Add a CI dependency audit — there is none of any kind. And fix `backend/README.md:31`: `alembic upgrade head` on a fresh volume **cannot work**, because the baseline is a deliberate no-op and migrations 0002+ collide; CI already documents the correct order (`sql/*.sql`, then `alembic stamp head`) at `.github/workflows/backend-pytest.yml:104-127`.

---

## What already holds — do not re-open

Copy these patterns rather than inventing alternatives.

| Seam | Evidence |
|---|---|
| Staff authz registry with CI totality proof | `authz.ROUTE_PERMISSIONS` + `assert_registry_covers` (`tests/test_authz.py:38-40`) |
| Fail-closed grant lookup on DB error | `authz.py:730-735` |
| Money as `numeric(14,2)`, no floats | `sql/02_customer_account.sql:86-158` |
| Tamper-evident audit hashing (bot config) | `agent_core/change_log.py:349`; proven by `tests/test_agent_change_log.py:155,180` |
| Tool-call audit redaction at the single writer | `bot_jobs.py:414-415`, all four channels; idempotence pinned |
| Webhook redelivery dedupe done right | `sql/03_consent.sql:202-203` + `delivery_receipts.py:97` |
| Retry with `Retry-After` and full jitter | `azure_speech.py:379-455` |
| Circuit breaker, where wired | `azure_openai.py:148,161`, `whatsapp.py:72,132`, `storage.py:168` |
| SSRF egress defence | `webhooks_dispatch.py:132-173` (HTTPS-only, private-IP reject, no redirects) |
| Bidirectional schema-drift enforcement | `.github/workflows/backend-pytest.yml:113` + `tests/test_schema_parity.py` |
| Transactional test fixture | `tests/conftest.py:12-65` |
| Fail-closed DB kill switch with audit trail | `platform_switches.py:39-140` (`KNOWN_KEYS`, absence = off) |
| Per-call incident bundle | `voice/call_export.py:50` |
| Call trace at WARNING, deliberately | `voice/call_trace.py:112-122` |
| `/ready` that actually checks dependencies | `main.py:759-777` |
| Frontend HTTP seam that throws on prod mocks | `Habibi/src/api/config.ts:16,68-73` |
| Reachability vocabulary matching CONTEXT.md exactly | `agent_core/cards/routing.py:84-90` |

---

## Reconciliation with the 11:30 draft

Same headline (composite 4), materially different shape. Where this pass disagrees, it is because a lens was actually run.

| Dimension | 11:30 draft | This report | Why |
|---|---|---|---|
| Architecture | 5 | **3** | Draft did not measure the import graph. `db` fan-in 200, `main` fan-out 85, 1,143 deferred imports, `db.py:26` imports `schemas`. |
| Security | 4 | **3** | Draft's security lens was **never independently run** — it says so. Auth is 2, not 4: four separate `_IS_PROD` short-circuits with the secrets already configured. Injection is 5, not 8 — classic injection is clean, but prompt injection reaching live CRM writes belongs in this row. Two new findings: no tenant filter on the primary Inbox read (`db.py:8994-9010`), A2A identity from spoofable headers (`main.py:278`). |
| Data | 4 | **6** | Draft understated. Money is `numeric(14,2)` throughout; partial uniques are strong. New finding it missed: the audit chain covers `entity_type='bot'` **only**. |
| Testing | 5 | **6** | Draft (and report 22) understated capability coverage. All 11 high-risk capabilities have behavioural tests; `MagicMock` appears once in 2,431 tests. The real gap is layer, not capability. |
| Migrations | 5 | **7** | All 102 revisions define `downgrade`; CI enforces drift bidirectionally. |
| Operations | 4 | **5** | Draft over-generalised: the root-logger defect affects `api` and `voice_insurance` only, and this is not a `print()` codebase. Tracing is 2, worse than the draft's 4 — `telemetry.span()` is a permanent no-op with no SDK dependency. |
| Configuration | 4 | **4** | Same score, one correction: shipped `TREATMENT_MODE` is **`live`**, not `shadow`. And it has no kill switch, though the kill-switch migration names it. |
| Deployability | not scored | **2** | No pipeline, no rollback, no backup/restore, no runbook, ngrok ingress. |

---

## Unverified — stated plainly

- **Nothing was executed.** No pytest, no vitest, no migration, no service start, no container exec, no scanner, no request at any target. Every finding is static, from source and committed configuration. The "permanently red test" claim is derived from a date literal plus a wall-clock rejection, not observed.
- **Runtime state is inferred.** Which flow actually serves a live call, whether the ngrok tunnel is currently reachable, whether `USE_MOCK` is off in the deployed bundle, and the true logger state inside a running container were not observed.
- **Route coverage is an upper bound.** 131 of 275 "touched" counts any string mention anywhere in the test corpus; only 17 files use `TestClient`, so real HTTP-exercised coverage is lower and could not be computed without running the suite.
- **Dependency scanning is inconclusive by absence, not by scan.** No SCA tool is installed here or in CI. `artifacts/osv-batch.json` (2026-09-02) is **unusable** — advisory IDs with no package names and no saved query input, so no Python CVE can be attributed from it. The npm data is usable and is summarised above. The Dependencies score rests on manifest inspection and the absence of any CI gate.
- **Infrastructure outside this repo is unknown.** Whether a reverse proxy strips `X-SSL-Client-*` or adds security headers; whether any external log or metric collector exists; whether branch protection makes the two workflows required. None of it is in the tree.
- **Not individually re-verified:** the specific findings of reports 06, 09, 26, 31 and `architecture-forensics.md`, and 11 of the 12 root-level planning documents. Vendored `PRAXIST-main/` and container OS layers were out of scope.
- **Audit-chain fork frequency is unknown.** The missing lock and missing unique constraint are certain; how often concurrent same-tenant publishes occur is not.
- **A note on repo state:** the working tree is effectively clean. `git status --porcelain` shows **44 entries: 43 untracked files that are this audit's own output** (`artifacts/`, `audit-reports/`, one scratch script) **and one pre-existing modification to `.cursor/settings.json`** that this pass did not make. Earlier guidance describing this branch as carrying substantial uncommitted work no longer holds — that work was committed. Nothing here was modified, staged, committed, or pushed.
- **Git history is thin for a system this size:** 34 commits, one author, and the initial commit is 384 files / 78,267 insertions. `contact_policy.py` — the regulated consent engine — has 2 commits. `git blame` and `git log` will not explain intent to a new team; the module docstrings and `docs/adr/` are the only design record.
