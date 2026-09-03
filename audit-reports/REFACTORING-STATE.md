# REFACTORING STATE

**Date:** 2026-09-03
**Phase:** Consolidation complete. **Implementation has not begun.**
**Mode:** Read-only with respect to the repository. No application source, config, migration, test, or dependency was modified, and nothing was installed, migrated, seeded or dialled. Consolidation ran nothing at all. The **MEASURED BASELINE** below did run the project's own lint, typecheck, test and build commands — against a Docker stack the user started, not one I brought up. Build output lands only in gitignored paths (`.output/`, `.wrangler/`), so the working tree is byte-for-byte unchanged.

**Companions:** [MASTER-AUDIT.md](./MASTER-AUDIT.md) · [CONFLICTS-AND-FALSE-POSITIVES.md](./CONFLICTS-AND-FALSE-POSITIVES.md) · [TARGET-ARCHITECTURE.md](./TARGET-ARCHITECTURE.md) · [MASTER-BACKLOG.md](./MASTER-BACKLOG.md)

---

## BASELINE

**Repository state at consolidation.**

| | |
|---|---|
| Branch | `autonomous-modernization` |
| HEAD | `14377f1` — *"chore: checkpoint before autonomous modernization"* |
| Working tree | **clean** — `git status --porcelain` returns 0 entries |
| History | 34 commits, one author. The initial commit is 384 files / 78,267 insertions |
| Tags | **zero** |
| Uncommitted work | **none.** Earlier guidance describing this branch as carrying substantial uncommitted work no longer holds — that work was committed |

**Nothing in this consolidation was committed, staged, or pushed.** The five orchestration documents are the only files written.

> **A note on `git blame` as evidence.** Thin history means it explains almost nothing here. `contact_policy.py` — the regulated consent engine — has **2 commits**. Design intent lives in module docstrings and `docs/adr/`, not in history. Several findings in MASTER-AUDIT rest on a docstring being the only record of a fact, which is why [TARGET-ARCHITECTURE.md](./TARGET-ARCHITECTURE.md) treats those docstrings as protected artifacts.

### Evidence base

| | |
|---|---|
| Audit reports read | **40 files** (~23,850 lines), in full — 39 numbered (`01`–`31`, `34`–`41`) plus the unnumbered `architecture-forensics.md`, which is cited in MASTER-AUDIT as AF-02/03/04/06. **Corrected 2026-09-03:** earlier drafts said "41", which is the highest report *number*, not a file count |
| Reports missing from the series | **2** — reports `32` and `33` **do not exist**. `29` and `30` carry no date line. **A two-report gap nobody should assume was covered** |
| Original findings across the corpus | ~700+ |
| **Consolidated MASTER findings** | **129** |
| Conflicts adjudicated against source | **15** |
| Claims re-verified at source during consolidation | **21** |
| Runtime questions left open | **10** |

**Numbering note.** MASTER findings are `MF-001` … `MF-132`, of which **124 carry content** and **5 are sub-findings** (`MF-009b`, `MF-009c`, `MF-014b`, `MF-031b`, `MF-041b`) — 129 total. Eight ids (`MF-003`, `MF-012`, `MF-013`, `MF-019`, `MF-023`, `MF-024`, `MF-029`, `MF-030`) were **merged into neighbouring findings during consolidation and are retained as cross-references rather than renumbered** — renumbering would break every citation in the backlog.

### What was verified first-hand during consolidation

Twenty-one claims were re-opened at source rather than inherited. The eleven that changed a conclusion or a work package:

| # | Claim | Result |
|---|---|---|
| 1 | `CAMPAIGN_RUNTIME_ENABLED` is dead (report 07) | **REFUTED.** Live at `cadence.py:67-69`, `campaigns.py:61-63` |
| 2 | `AGENT_CARDS_ENABLED` is dead (report 07, same table) | **CONFIRMED.** Zero application readers |
| 3 | `grant.py` has zero production importers | **CONFIRMED.** Tests only |
| 4 | `styles.css:1638-1674` is safe to delete | **REFUTED.** `.bb-mark` ends at **1670**; `1672` opens live `@keyframes pulse-ring`, consumed at `:1835` |
| 5 | "Zero ordering-sensitive route pairs" (report 40) | **REFUTED.** Five static-before-parameterised pairs |
| 6 | `_AUTH_EXEMPT_PREFIXES` omits two `PUBLIC_ROUTES` webhooks | **CONFIRMED** |
| 7 | `patch_consent` rewrites consent from a round-tripped payload | **CONFIRMED**, and the `(10,19)` default is hardcoded **twice** |
| 8 | `_parse_allowed_days` collapses an en-dash to one day | **CONFIRMED** by hand-tracing to `f"Mon-Mon"` |
| 9 | `_IS_PROD` and `NON_PROD_ENVS` read the same question oppositely | **CONFIRMED**, with the author's own comment acknowledging both |
| 10 | `contact_policy` fails open for non-outreach | **CONFIRMED** at both `evaluate` and `admit` |
| 11 | No ungated path to a borrower's phone | **CONFIRMED 7-for-7** — the strongest positive result in the corpus |

Also confirmed: `db.py:24` imports `schemas` (not `:26`); the `db_tx` monkeypatch at `conftest.py:61`; both test date bombs; `sql/23_outbound_evals.sql` **does not exist**; `FISH_TTS_MODEL` still selects the lapsed free model **and so does its documented fallback**; `ui/card.tsx` and `ui/tooltip.tsx` have zero importers; `_activity` hardcodes `actor_kind='human'`; `setup_logging()` returns early and `LOG_FORMAT` appears **zero times** in `.env.example`.

---

## MEASURED BASELINE — 2026-09-03

**Everything in this section is a command that was run on this machine**, against `14377f1` with a clean working tree, before any modernization work. Where the consolidation had inherited a number from the audit corpus, the measured value replaces it and the discrepancy is recorded at the end.

**How it was run, and why that matters.** The four frontend commands ran on the host. `ruff` and `pytest --collect-only` ran on the host under `backend/.venv` — **Python 3.14.3**, which is *not* what ships: `ruff.toml` targets `py312` and both images are 3.12. The full `pytest` run was executed inside `collections_voice`, which bind-mounts `backend/` at `/app` and carries the shipping 3.12 interpreter, so the test numbers describe the real runtime. The user brought the Docker stack up; nothing was started on my initiative.

### Commands and results

| Tree | Check | Command | Result | Exit |
|---|---|---|---|:--:|
| `Habibi/` | Typecheck | `npx tsc --noEmit` | **0 errors** | 0 |
| `Habibi/` | Lint | `npm run lint` | **0 errors, 62 warnings**; spacing scale clean (14 steps), type scale clean (16 tokens) | 0 |
| `Habibi/` | Tests | `npx vitest run` | **107 passed / 107**, 11 files, 13.6s | 0 |
| `Habibi/` | Build | `npm run build` | **PASS**, 15.2s | 0 |
| `backend/` | Lint | `ruff check .` | **All checks passed** | 0 |
| `backend/` | Lint (widest) | `ruff check --select ALL --statistics .` | **27,743** diagnostics | — |
| `backend/` | Collection | `pytest --collect-only -q` | **3,165 items, 0 collection errors**, 126s | 0 |
| `backend/` | **Tests** | `docker exec collections_voice python -m pytest tests/ -q` | **1 failed · 3,141 passed · 19 skipped**, 587s | 1 |
| `backend/` | Migrations | `alembic heads` | **single head** `20260901_0103`, 102 revisions | 0 |
| `backend/` | Type check | — | **impossible — no checker installed** | — |
| `backend/` | Coverage | — | **impossible — `pytest-cov` not installed** | — |

**Absent tooling, verified by `pip show` and not by inference:** `mypy`, `pyright`, `vulture`, `pytest-cov`, `coverage`, `bandit`, `pip-audit` are **all not installed**. `[tool.vulture]` is configured in `pyproject.toml` for a tool that is not present. "No Python type checker exists anywhere" and "coverage has never been measured" are now measurements, not deductions.

---

### PRE-EXISTING FAILURES

**One test fails, and it is not a code defect.**

| Test | Cause | Since | Work package |
|---|---|---|---|
| `tests/test_contact_policy.py::test_due_reminder_blocked_when_capped` | Line 287 passes the literal `promised_date="2026-09-01"`; `agent_core/tools/domain.py:724` refuses any past date with `promise_date_in_past`. The literal aged out. | **2026-09-02** | **`WP-011`** |

Every other assertion in the suite passes. **3,141 passed, 19 skipped.**

**Four more fail on 2026-09-15, on the calendar rather than on a commit.** `tests/test_voice_write_idempotency.py:36` sets `PROMISE_DATE = "2026-09-14"`, reached through the `_book` helper by exactly four tests: `test_a_reconnect_mid_call_does_not_double_book_the_promise`, `test_a_session_with_no_provider_id_still_keys_on_the_interaction`, `test_the_provider_id_wins_over_the_interaction_id`, `test_two_genuinely_separate_calls_each_book_their_own_promise`. Two later literals (`2026-09-21` in `test_outbound_completion.py`, `2026-09-01` in `test_whatsapp_template_fallback.py`) are rendered or template strings that are never date-validated, and are inert.

> This is the whole argument for doing `WP-011` first. **On 2026-09-15 the baseline changes by itself**, and if that day falls in the middle of a work package, four new failures will appear in a diff that did not cause them.

---

### NOT FAILURES — measurement artefacts

The raw container run reported **five** failures. **Four of them are the measurement apparatus, not the code.** Only `backend/` is mounted at `/app`, so tests that read the frontend tree to pin the TypeScript/Python contract resolve `/Habibi/...` and raise `FileNotFoundError`.

| Test | What it reads |
|---|---|
| `test_outbound_studio_bindings.py::test_frontend_create_campaign_sends_bot_id` | `Habibi/src/components/prompt-studio/OutboundTab.tsx` |
| `test_sandbox_turn_schema.py::test_every_key_the_studio_posts_is_a_field_on_the_request_model` | `Habibi/src/api/sandbox.ts` |
| `test_system_prompt_rendering.py::test_the_editor_variable_palette_matches_the_renderer` | the System Prompt tab source |
| `test_voicemail_classifier_isolation.py::test_skill_clone_source_does_not_use_window_prompt` | `Habibi/src/routes/agent-studio.skills.index.tsx` |

**All four pass on the host** — re-run directly, 4 passed in 3.32s.

**A third artefact class, found 2026-09-03 at 22:23 UTC.** Two more tests fail in
the container and pass on the host, and the cause is neither the mount nor the
code:

| Test | Reads "today" from |
|---|---|
| `test_conversation_trace_regressions.py::test_a_promise_for_today_is_still_allowed` | `date.today()` — the **process** timezone |
| `test_promise_fulfillment.py::test_settle_due_today` | `days=0`, likewise |

The guard they exercise, `_promise_date_is_past`, reads it from the **tenant's**
— IST. Measured in `collections_voice` at that moment: `date.today()` returned
**2026-09-03** while IST today was **2026-09-04**. A promise dated "today" is
therefore already yesterday to the guard, and is refused `promise_date_in_past`.

This is a **real latent defect**, not a mount artefact: it makes the suite red
between **18:30 and 24:00 UTC** every day, on any UTC runner, with no commit
involved. Filed as **`WP-068`**. It is the same family as `WP-011` — a test that
is only correct while two clocks agree — which is why it surfaced the night
`WP-011` landed and not before.

> Had the raw container output been recorded as the baseline, five "pre-existing failures" would now be on file, four of them fictional. An implementation agent would eventually "fix" a test that was never broken — most likely by deleting the cross-tree assertion, which is precisely the contract these four exist to hold. This is the same failure mode the whole corpus is about: **a conclusion drawn from an absence, produced by a search that could not have found the evidence.**

---

### The line between pre-existing and modernization-introduced

**A failure is PRE-EXISTING if and only if** it reproduces at `14377f1` with a clean tree, **or** it is one of the six known artefacts — the four cross-tree mount failures, or either of the two `WP-068` timezone failures when the run straddles 18:30–24:00 UTC. *(The original two entries here, `test_due_reminder_blocked_when_capped` and the four `PROMISE_DATE` tests, were closed by `WP-011` in `b30fa8f`.)* **Everything else is introduced, and belongs to the work package that introduced it.**

Three traps stand between that rule and its correct application:

1. **The container's four cross-tree failures are not regressions.** Any failure seen inside `collections_voice` must be re-run on the host before it is believed. The reverse also holds: a genuine cross-tree contract break would be *invisible* in the container, because the test cannot run there at all.
2. **The clock moves the baseline.** On 2026-09-15 the expected count goes from 1 to 5 with no commit in between. Re-baseline on that date, or land `WP-011` before it.
3. **A green `ruff check .` and a green `npm run lint` prove almost nothing.** Ruff runs its default rules only; ESLint's 62 findings are all warnings and exit 0. Neither gate would have caught most of what the audit found. Do not read "lint passes" as "the code is clean" — read it as "the gate is set where it was set."

**Re-baseline command set**, to be run before and after every work package:

```
cd Habibi   && npx tsc --noEmit && npm run lint && npx vitest run && npm run build
cd backend  && .venv/Scripts/ruff.exe check .
docker exec collections_voice python -m pytest tests/ -q
```

The backend suite takes **~10 minutes**; run it in the background rather than blocking on it.

---

### Corrections to numbers inherited from the audit corpus

| Inherited claim | Measured | What went wrong |
|---|---|---|
| ~4,800 latent ruff diagnostics | **27,743** | 4,800 was `S101 assert` alone (4,794) — pytest's own idiom, counted as debt. The real total is 5.8x larger and mostly style |
| **+8** tests fail on 2026-09-15 | **4** | `8` is `grep -c PROMISE_DATE` — occurrences of the constant, not tests. Four reach it through `_book` |
| Suite runs in ~45s (444 passed) | **9m47s (3,141 passed)** | A note from when the suite was 444 tests. The suite grew ~7x and the timing note did not |
| ANN001 1,852 · ANN401 856 | 1,861 · 857 | Drift; corrected in place |
| Frontend lint state unrecorded | **62 warnings, 0 errors** | 39 × `react-refresh/only-export-components` (24 files), 23 × `react-hooks/exhaustive-deps` (14 files). Exit 0, so CI is silent about every one |

Confirmed unchanged: `ruff check .` clean at exit 0; `tsc --noEmit` clean; 186 backend test files / 2,431 test functions; 11 frontend test files against 474 modules; a single Alembic head.

---

## CURRENT ARCHITECTURE

**A FastAPI modular monolith with a mature domain core and a CRM/HTTP shell that never adopted it.**

```
Habibi console ──HTTP──► main.py (314 routes, 0 routers, fan-in 0)
                              │
                              ├── db.py ◄── fan-in 101, fan-out 46
                              │     imports the domain BACK → 107-module coupling SCC
                              │
                              ├── Locked Engines × 4  ← the architecture, and it HOLDS
                              ├── contact_policy.admit ← 13 callers, the one Gate
                              └── voice/ ← 3 of 44 modules coupled
```

| Property | Measurement |
|---|---|
| Backend production modules | 267 |
| `db.py` | **18,087 lines · 440 functions · fan-in 101 · fan-out 46** |
| `main.py` | **5,448 lines · 314 route decorators · 0 `APIRouter` · fan-in 0** |
| `schemas.py` | 3,453 lines · 247 models · **2 importers** |
| Import-time SCCs > 1 | **0** — import time is a genuine DAG, nine condensation levels deep |
| Coupling SCC (eager + lazy) | **107** (submodule-preferring; 76 / 110 / 112 under other conventions — see CONFLICTS §C5) |
| Function-local imports | **2,131** — load-bearing, not a smell: they are the image boundary |
| `# noqa: E402` markers | 66 across 28 files |
| `fastapi`/`starlette` importers | **3 of 267** |
| `HTTPException` sites | 202, **all in one file** |
| `create_engine` sites | **2 in the whole tree** |
| Domain modules that are already pure | **51 of 102** (12,414 lines) |
| Frontend modules | 474 · **zero app cycles** · zero `components → routes` edges |
| `fetch` calls outside `api/config.ts` | **1 of 7** |

**Runtime:** 5 application containers + 1 unmanaged (`mcp_server`, not in compose). Postgres 16 + pgvector as system of record **and** job broker via `SKIP LOCKED`. Redis is voice-mesh pub/sub only — **not a cache**. MinIO for KB originals.

**Shipped configuration:** `APP_ENV=dev` · `API_KEY`/`API_KEY_MAP` **present but empty** · `TREATMENT_MODE=live` · `BILLING_ENV=production` · `BOT_ENVIRONMENT=production` · `VOICE_WS_PROXY_SECRET` **set and ignored** · `TWILIO_AUTH_TOKEN` **set and ignored** · `LOG_FORMAT` **absent** · `PUBLIC_BASE_URL` a public tunnel.

---

## TARGET ARCHITECTURE

**The architecture this repository already has, finished.** Full statement in [TARGET-ARCHITECTURE.md](./TARGET-ARCHITECTURE.md).

**Four new constructions, and nothing else is new:**

1. `outbound.dial(...)` — one owner for the regulated gate sequence, currently written seven times in **two** orderings.
2. `conn` becomes **required** in the four Locked Engines — deleting a fallback, not adding an abstraction.
3. `db_core.py` — the precondition for splitting `db.py` at all, because 41 modules bind to its private helpers.
4. Runtime validation at `apiGet`, as an **optional** third parameter so 221 call sites keep working.

**Nine refusals, each with a reason drawn from this tree:** no rewrite · no repository/DAO layer · no service layer · no DTO layer · no eager-import conversion · no further `agent_core` split · no ORM · no frontend rewrite or global store · no vocabulary alignment (**a rename here is a data migration, not a refactor**).

**The destination in one line:** `db.py` at ~3,100 lines; `grant.py` with production importers; RLS on; every route declaring a response shape; `logger.info` reaching a handler; and `main.py` still with zero importers.

---

## MASTER FINDINGS

**Total: 129.**

| Severity | Count | Definition |
|---|---:|---|
| **P0** | **18** | A borrower can be contacted twice, charged wrongly, or have consent fabricated; or regulated evidence is destroyed; or the system runs with authentication off |
| **P1** | **61** | A regulated control has two owners that can disagree; a structural blocker; a diagnosis that is impossible |
| **P2** | **40** | Correctness or consistency with a bounded blast radius; engineering cost |
| **P3** | **10** | Hygiene |

**Severity here is regulatory exposure and irreversibility first, engineering cost second.** That inverts the corpus in three places, and each is stated in MASTER-AUDIT §"Conflicts": `db.py`'s 18,087 lines, 295 unlabelled controls, and a missing SCA gate are all real, correctly measured, and **cannot contact, charge or misquote a borrower.** They are P1/P2 costs, not P0 risks.

### P0 findings — the eighteen

| ID | Finding | Family |
|---|---|---|
| MF-001 | Tool Grant has no owner; ADR-0001 and ADR-0002 accepted and unbuilt | A — unwired owner |
| MF-002 | Contact Gate returns ALLOW for every non-outreach purpose on exception | C — false record |
| MF-004 | Five independent paths contact a borrower twice | D |
| MF-005 | Consent drawer overwrites borrower consent on every save | C |
| MF-006 | Two signature-verified webhooks 401 before their own HMAC | C |
| MF-007 | Auth + authz fail open together on a two-string allowlist | B — open envelope |
| MF-008 | Total revocation restores `ROLE_DEFAULTS` | B |
| MF-011 | The record disagrees with the world — money, statutory notice, audit chain | C |
| MF-014 | Three defaults for "what window when none is on file" | A |
| MF-020 | The suite is red on a date literal; a second bomb fires 2026-09-15 | — |
| MF-021 | `db_tx` makes concurrency structurally untestable | — |
| MF-025 | Carrier I/O inside claim transactions | D |
| MF-033 | An insights failure is rendered as a capturable Offer | C |
| MF-037 | The gate sequence in two orderings; one site leaves no attempt row | C |
| MF-041 | Two parallel `apply_goodwill` calls post two waivers | — |
| MF-041b | The Mission authority ceiling is spoken and not applied | — |
| MF-068 | Voice Media Streams WS upgrades without the configured secret | B |
| MF-106 | `UNKNOWN-CALLER` is a global primary key | — |

### Distribution by category

| Category | Findings | P0 |
|---|---:|---:|
| Security | 20 | 4 |
| Testing | 19 | 2 |
| Configuration | 14 | 2 |
| Data / database | 12 | 2 |
| Bugs | 12 | 3 |
| Duplication | 11 | 2 |
| Dead code | 10 | 0 |
| AI / voice integration | 9 | 0 |
| Reliability | 9 | 0 |
| Architecture | 8 | 0 |
| Performance | 6 | 1 |
| Cross-cutting (Critical section) | 8 | 8 |

---

## WORK PACKAGES

**Total: 68. Status: 5 completed, 63 open.** *(65 → 68: `WP-066`, `WP-067`, `WP-068` filed from findings during execution.)*

| Status | Count |
|---|---:|
| **READY** — no unmet prerequisite; can begin today | **29** |
| **BLOCKED** — has an unmet prerequisite | **31** |
| **BLOCKED (runtime)** — needs a database read first | **0** |
| **IN PROGRESS** | **1** — `WP-002` |
| **COMPLETED** | **5** |

### COMPLETED (5)

| WP | Commit | Verified by | Residual |
|---|---|---|---|
| **`WP-011`** the two date bombs | `b30fa8f` (2026-09-03) | Container suite **3,148 passed · 19 skipped · 4 failed**, the four being the known mount artefacts. Baseline was 3,141 / 19 / 5. Arithmetic closes exactly: 3,141 + 1 fixed + 6 new = 3,148. `ruff` clean | closed by `WP-066` |
| **`WP-066`** allowlist the expiry scanner | `52712ff` (2026-09-04) | 8/8 in the file, `ruff` clean, suite passed count unchanged at 3,148 | none |
| **`WP-005`** cardless inventory | — *(no code; an answer)* | Live query: **0 of 18** prompt versions cardless, all 18 parse; the 2 cardless bots have **no deployment rows** and are archived on purpose | none — **it unblocked `WP-004`** |
| **`WP-001`** deploy identity + rollback | `06e90b1` (2026-09-04) | `compose config --images` unchanged by default and SHA-resolving when set; `npm run build` PASS; every factual claim in `rollback.md` checked against migration source | first rollback not executable until one SHA is published |
| **`WP-004`** cardless Mouth granted nothing (**ADR-0002**) | `fd5c73b` (2026-09-04) | Container suite **3,165 passed · 19 skipped · 6 failed**, the six being 4 mount artefacts + the 2 `WP-068` timezone tests. `3,148 + 17 new = 3,165` exactly. Blast radius pre-measured at zero by `WP-005` | `WP-031`'s remaining steps — channel filter, adopt `grant.py`, drop `\| ALWAYS_ON` from the live filter |

### READY (31)

Nothing prevents any of these starting today.

**Band 0–1 — regulated, under 60 lines total:**
`WP-006` contact Gate fails closed · `WP-007` webhook exemption · `WP-008` bounce notice guard · `WP-009` classify the carrier exception · `WP-010` coalescing vs frequency caps

**Band 2 — envelope:**
`WP-012` `load_env()` ordering · `WP-014` require the WS secret and the Twilio signature · `WP-015` revocation means empty · `WP-016` provision `NOBYPASSRLS` and enable RLS · `WP-018` guard every `bot_worker` stage

**Band 3–4 — provable no-ops and cheap wins:**
`WP-024` publish a coverage number · `WP-025` import `BLOCKING_CONSENT` · `WP-032` `FISH_TTS_MODEL` · `WP-034` `sql/23_outbound_evals.sql` · `WP-035` `db_core.py`

**Band 6–8 — hygiene and infrastructure:**
`WP-044` one error-code map · `WP-050` the seventh `fetch` · `WP-051` keyboard-blocked tasks · `WP-052` connect 105 labels · `WP-053` CI import-boundary test · `WP-054` `-c requirements.txt` · `WP-055` Python lockfile · `WP-056` vulnerability gate · `WP-057` bump `nltk` · `WP-058` PRAXIST in the zip skip list · `WP-059` container hardening · `WP-060` MinIO defaults · `WP-061`–`WP-063` gitignore, `.env.bak.reco`, `[tool.vulture]` · `WP-065` flag parametrize

### BLOCKED (32) — with the specific gate

| WP | Blocked on | Why |
|---|---|---|
| WP-003 | WP-002 | Counting the corrupted rows while the corruption continues is pointless |
| **WP-004** | **WP-005** | The population deny-all protects is the population it breaks |
| WP-013 | WP-012 | `APP_ENV` is inert until `.env` is read — **and the natural assumption that it took effect is exactly what fails** |
| WP-017 | its own redactor sub-gate | Enabling JSON logs first creates a retained, indexed store of borrower phone numbers |
| WP-019, WP-020, WP-021, WP-022, WP-023 | WP-011 | A red baseline makes every test claim unfalsifiable |
| WP-026 | WP-021, WP-033 | A no-op unless a rule set is published |
| WP-027 | WP-022 | Capture and enforcement must meet in one process first |
| WP-028 | WP-023 + **an ordering decision** | The decision is a prerequisite, not a task |
| WP-029, WP-031 | WP-021 | Six of nine targets have no test that would fail |
| WP-030 | **WP-002, WP-003** | Fixing the parser first widens already-corrupted rows silently |
| WP-036 | WP-035, WP-016, WP-042, WP-019 | Carve without response models = silently rewritten public API |
| WP-037, WP-041 | WP-019 | Exactly the class `db_tx` cannot express |
| WP-039 | WP-018, WP-040 | |
| WP-040 | WP-009 | |
| WP-042, WP-043 | WP-024 | |
| **WP-045** | **must NOT ship with WP-042's `/agent-studio` work** | Both land on the same 26 routes, and the natural grouping pass reverses an ordering-sensitive pair |
| WP-046 | WP-001 (`npm run build`) | CI never builds today |
| WP-047, WP-048 | WP-046 | Do not remediate dead surface |
| WP-049 | WP-046, WP-048 | Deleting the mock branch deletes the module that declares `Customer` |
| WP-064 | a deploy-manifest sweep | A stale flag name in a running deployment is silent |

### BLOCKED — runtime (1)

**Changed 2026-09-03: the database is up.** `WP-005` (empty-Agent-Card inventory) needed only a live database and is now **READY** — it is one `SELECT`, and it gates `WP-004`, the single highest-value one-line change in the tree. `WP-003` (consent corruption inventory) stays blocked, but on `WP-002` rather than on the database: counting corrupted rows while the corruption continues is pointless.

---

## METRICS

Every number carries the method that produced it. **Where a metric cannot currently be measured, it says so rather than being estimated** — that distinction is itself a finding.

### Duplication

| Metric | Baseline | Method | Target |
|---|---:|---|---:|
| Regulated questions with >1 live implementation | **11** | Cross-report merge, re-verified | **0** |
| — of those, **already diverged** | **7** | Source comparison | 0 |
| Tool Grant formulas in production | **6** | Verified | **1** |
| `BLOCKING_CONSENT` definitions / use sites | **4 / 9** | Literal search (3 under aliased names) | 1 / 9 |
| Calling-window decision sites consulting `policy_rules` | **2 of 9** | Source | 9 of 9 |
| Preferred-window default literals | **3** (08–19, 09–20, 10–19) | Source | 2 — **statutory and preference must stay separate** |
| DND definitions | **3** | Source | 1 |
| Account-tail algorithms | **5** | Source | 1 |
| Outbound gate orderings | **2** | Source | 1 |
| `env_int` implementations | **4** | Source | 1 |
| Queue state machines | **4** | Source | 1 parameterized |
| jscpd token clones — TS / Python | 41 (0.61%) / 134 (1.80%) | jscpd | not a target |

> **Token-level clone percentage is deliberately not a target.** The dangerous duplicates are *competing answers to one regulated question*, and they sit below what jscpd can see.

### Dead code

| Metric | Baseline | Method | Target |
|---|---:|---|---:|
| Frontend dead files / lines | **29 / 2,843** | Two independent re-derivations; 2 spot-verified | 0 |
| Removable npm dependencies | **22** | Lockfile + import graph | 0 |
| Backend dead symbols / lines | **18 / 158** | AST | 0 |
| Backend dead feature flags | **1** (`AGENT_CARDS_ENABLED`) — **verified** | Indexed search | 0 |
| Backend dead files | **0** | — | 0 |
| Commented-out code blocks (4+ lines) | **0 in both trees** | — | 0 |
| Unreferenced database tables | **0 of 171** | — | 0 |
| **Diagnostics that must NOT be deleted** | **8** | Enumerated in MF-051 | **8 — this number must not fall** |
| Dynamic-dispatch sites with non-enumerable targets | **1** (`factory._import_class`) | AST + source | 1, with an allowlist |

> **Backend dead code is ~0.08% of the tree.** A roadmap must not promise otherwise. And deleting it does **not** pre-pay for the canonicalization: every live Tool Grant formula sits in a reachable module.

### Dependency cycles

| Metric | Baseline | Method | Target |
|---|---:|---|---:|
| Import-time SCCs > 1 | **0** | Tarjan, eager edges | 0 — **must not regress** |
| Coupling SCC (largest) | **107** | Tarjan, submodule-preferring | **~41** |
| Direct 2-cycles with `db` on them | ~21 | Graph | 0 |
| `db.py` fan-in / fan-out | **101 / 46** | AST | ~40 / ~10 |
| External reach-throughs into `db.py` privates | **239 across 41 modules** | AST | 0 |
| Frontend runtime cycles | **0** | Import graph | 0 — **must not regress** |

> **A residual SCC of ~41 remains with `db.py` deleted entirely.** The agent-turn core is genuinely mutually recursive and is **not `db.py`'s fault.** Nobody should promise the graph becomes a DAG. And **SCC size is a lagging indicator**: the first eight carve commits move file size, ownership and review surface, and move the SCC by ~1 each.

### Type safety

| Metric | Baseline | Method | Target |
|---|---:|---|---:|
| Python type checker | **none** — no mypy, pyright, or config anywhere | Config search | one, introduced **green** |
| Latent diagnostics under the widest rule set | **27,743** | `ruff check --select ALL --statistics .`, measured 2026-09-03 | not a target — see below |
| — `assert` in tests (S101) | 4,794 | Ruff | **not debt** — pytest's idiom |
| — missing trailing comma (COM812) | 4,027 | Ruff | **not debt** — conflicts with a formatter |
| — line too long (E501) | 3,675 | Ruff | style, ungated by choice |
| — missing argument types | 1,861 | ANN001 | — |
| — `Any` in signatures | 857 (149 in `db.py`) | ANN401 | — |
| — blind `except Exception` | 295 | BLE001 | reduced **outside `voice/`** (the audio contract is deliberate) |
| `TypedDict` usages in `backend/` | **0** | Search | — |
| Frontend `tsc --noEmit` | **clean**, `strict: true` | CI | clean |
| Hand-written `any` in `Habibi/src` | **3**, all deliberately suppressed | Search | 3 |
| **Unchecked `as T` casts at the wire** | **229** | Search | **0** |
| Runtime response validations | **0** | Search | all `api/*` modules |
| Domain types exported from mock seeds | **261** | Export scan | **0** |

### Lint

| Metric | Baseline | Method | Target |
|---|---:|---|---:|
| `ruff check .` (default E4/E7/E9 + F) | **0 findings, exit 0** | Run 2026-09-03 | 0 |
| Ruff rule set | defaults only; `select` unset | `ruff.toml` | + BLE outside `voice/` |
| `npm run lint` | **exit 0 — 0 errors, 62 warnings** | Run 2026-09-03 | ratchet, not flag-day |
| — `react-refresh/only-export-components` | 39 across 24 files | ESLint | ratchet |
| — `react-hooks/exhaustive-deps` | 23 across 14 files | ESLint | ratchet |
| Frontend `npm run build` | **PASS, 15.2s** | Run 2026-09-03; **CI never runs it** (WP-001) | gated in CI |
| Frontend `tsc --noEmit` | **0 errors, exit 0** | Run 2026-09-03 | 0 |
| ESLint type-aware rules | **0** — no `parserOptions.project` | Config | consider |
| Design-scale scanners | **2, both passing, both in CI** | `npm run lint` | 2 |
| Mutable default arguments (B006) | **0** | Ruff | 0 |

### Tests

| Metric | Baseline | Method | Target |
|---|---:|---|---:|
| **Suite status** | **RED — by exactly one test** | Full run, 2026-09-03 | **GREEN** |
| Backend suite result | **1 failed · 3,141 passed · 19 skipped** in **9m47s** | `docker exec collections_voice python -m pytest tests/ -q` | 0 failed |
| Genuinely failing tests | **1 today · 4 more on 2026-09-15** | Run + source | 0 |
| Container-only failures (**not defects**) | **4** | Re-run on host: 4 passed in 3.3s | n/a |
| Backend test files / functions | 186 / **2,431** | Count | — |
| Collected test items | **3,165, 0 collection errors** | `pytest --collect-only -q` (126s) | — |
| `MagicMock` occurrences | **1 in 2,431** | Search | 1 |
| Tests asserting **source text** | **53 across 27 files** | Search | **0** |
| Skippable at runtime | **436 (17.9%)** | AST | <5% |
| — because the seed was empty | 284 | AST | 0 |
| `pytest.skip()` call sites | 116 across 55 files | Count | — |
| **Coverage** | **NOT MEASURED — no `pytest-cov` anywhere** | Config search | published, then ratcheted |
| Contention tests | **1 of ~16 claim paths** | Source | ≥1 per high-volume queue |
| Statutory refusal reasons asserted as behaviour | **5 of 12** | Source | **12 of 12** |
| Routes with a negative-auth test | **5 of 314** | Source | high-consequence routes covered |
| Webhook routes tested at the HTTP layer | **0 of 12** | Source | 12 |
| Frontend test files / modules | **11 / 474** | Count | — |
| Frontend suite result | **107 passed / 107**, 13.6s | `npx vitest run`, 2026-09-03 | 107+ |
| Frontend component/render/hook tests | **0** — structurally impossible today | `vitest.config.ts` | jsdom, then the compliance surfaces |
| E2E / journey tests | **0** | Search | ≥1 |
| Voice eval scenarios in the manifest | **6 of 15**, run by **no CI** | `suite.yaml` | all, gated |

### Security

| Metric | Baseline | Method | Target |
|---|---:|---|---:|
| P0 security findings | **4** | Consolidation | 0 |
| Controls keyed to `_IS_PROD` | **8** | Source | 0 fail-open |
| **Configured secrets that are ignored** | **2** | Source | 0 |
| ADRs accepted and unimplemented | **2 of 2** | Source | 0 |
| Authz route coverage | **318/318, CI-proven** | `assert_registry_covers` | 318/318 — **the model for everything else** |
| Object-visibility coverage | **14 of ~491 query sites**, fail-open by construction | Source | RLS as the backstop |
| RLS status | **complete, tested, INERT** | Source | enforcing, `NOBYPASSRLS` |
| Hand-written tenant predicates | **~290 across 44 modules** | Regex (3 methods, same order) | defence in depth |
| SCA / secret / SAST scanning | **none, anywhere** | CI + machine | ≥1 gate |
| Python lockfile | **none**; 114 of 134 packages unpinned | Manifest vs venv | locked with hashes |
| Known advisories on the voice import path | **21** (`nltk 3.10.0`) | OSV batch | 0 |
| Credentials ever committed | **0** — verified across 39 commits, by path **and** content | Git history | 0 |
| Circuit-breaker coverage | **4 of ~21** outbound dependencies | Source | the ~10 that matter |
| Outbound integrations with a latency or error metric | **0 of 21** | Source | ~10 |

### Complexity

| Metric | Baseline | Method | Target |
|---|---:|---|---:|
| Modules > 2,000 lines | **5** (`db.py`, `main.py`, `schemas.py`, `voice/tools.py`, `voice/bot.py`) | `wc -l` | 2 (`schemas.py` is a type catalog; `db.py` at ~3,100) |
| Largest function | **`build_tools` — 2,605 lines, 18 kwargs, ~20 nested handlers** | Source | decomposed |
| Second largest | `run_bot` — 2,026 lines, **2 parameters** | Source | decomposed |
| Functions > 100 lines | 169 · **> 200 lines**: 42 · **cc > 25**: 77 | Proxy | reduced |
| Routes in one file | **314** | AST | ≤ 240 after six routers |
| Frontend god routes | 2 (`prompt-studio.lazy.tsx` 1,658 · `treatment.lazy.tsx` 1,506) | `wc -l` | decomposed |
| `useState` in one route file | 29 | Count | — |

### Architecture violations

| Metric | Baseline | Method | Target |
|---|---:|---|---:|
| Regulated decisions restated at call sites | **11** | Consolidation | 0 |
| Modules importing `db` | **101 (38% of the backend)** | AST | ~40 |
| Tables written by >1 module | **31 of 138** | SQL scan | reduced; `ledger_entries` first |
| Handlers owning a DB transaction | **28** | AST | 0 |
| Handlers authoring SQL inline | **13 (16 sites)** | AST | 0 |
| Routes without a `response_model` | **178 of 314** | AST | **0** |
| Mutating routes taking `dict[str, Any]` | **33 of 152** | AST | 0 |
| Models without `model_config` | 61 of 247 | AST | 0 |
| **Ordering-sensitive route pairs** | **5** — safe today, **hazardous to reorder** | Verified | documented + ordered-list gate |
| Ports with fewer operations than their adapter | **1** (`work_runtime`: 3 of 7) | Source | 0 |
| Locked Engines with a `db.engine` fallback | **4 of 4** | Source | 0 |
| `USE_MOCK` references outside `api/` | **26** | Search | 0 |
| Frontend mutations declared in screens | **43 of 102** | Search | 0 |
| `query.data ?? []` sites vs `QueryState` adopters | **~110 vs 1** | Search | inverted |

### Operations

| Metric | Baseline | Target |
|---|---|---|
| Services discarding their own INFO logs | **2 of 5** (`api`, `voice_insurance`) | 0 |
| PII redaction on log output | **never executes** | always |
| `/metrics` scrapers | **0** | ≥1 |
| Distributed tracing | **none** — `span()` is a permanent no-op with no SDK | decision recorded |
| Services with a healthcheck | **4 of 8** | 8 |
| Correlation id reaching a log line | **no** | yes |
| Deploy pipeline / image tags / rollback procedure / backup procedure | **none / none / none / none** | all four |
| Runbook | **none** | one |

---

## THE TEN OPEN RUNTIME QUESTIONS

**No runtime evidence was obtainable.** Docker is down; nothing is listening on 8000 or 3000. Full detail in [CONFLICTS-AND-FALSE-POSITIVES.md](./CONFLICTS-AND-FALSE-POSITIVES.md).

| # | Question | Gates |
|---|---|---|
| 1 | `SELECT DISTINCT service_class, enabled FROM provider_models` | **Any deletion in `agent_core/providers/`** — the one dispatch site whose targets are not enumerable from source, and where a wrong deletion is a production outage |
| 2 | `SELECT * FROM platform_switches` | Every corpus statement about outbound being enabled |
| 3 | `SELECT DISTINCT grader FROM eval_tasks` | Any grader deletion — an unknown name produces **a failing eval that looks like a real regression** |
| 4 | `SELECT * FROM policy_rule_sets` | **WP-026 and WP-033.** If empty, WhatsApp/SMS/email have no calling-hour bound |
| 5 | Consent rows with an en-dash or `Xxx-Xxx` | **WP-003** — sizes MF-005 |
| 6 | Are account ids all-numeric? | Whether WP's account-tail work is a no-op |
| 7 | `SELECT provider, count(*) FROM tts_voice_catalog GROUP BY 1` | Whether `provider_voice_sync.py` is wired or deleted |
| 8 | Byte-diff the built CSS before/after the kit deletion | **WP-046's** stated guarantee, which the nominated gates cannot observe |
| 9 | Per-route traffic counters for one week | The 26 routes with no frontend caller — **a traffic question, not an import question** |
| 10 | Mouths with an empty `agent_card` | **WP-005 → WP-004**, the highest-value one-line change |

---

## NEXT ACTION

**Baseline recorded. No implementation has begun.** No source, config, migration, test or dependency has been modified; nothing has been committed, staged or pushed.

### THE FIRST FIVE WORK PACKAGES

Selected for **safety first, then value**: each one either cannot break anything, or changes behaviour only where the audit proves behaviour is already wrong. Together they are under 100 lines of application code.

| # | WP | Title | Status | Risk | Verifiable by |
|:--:|---|---|---|---|---|
| 1 | **WP-011** | Fix the two date bombs and add an expiry test | READY | **none** — tests only | `pytest -q` goes green |
| 2 | **WP-001** | Give a deploy an identity and rollback a written procedure | READY | **none** — additive, CI + docs | a rehearsed rollback |
| 3 | **WP-005** | Inventory Mouths with an empty Agent Card | READY *(newly unblocked)* | **none** — one read-only `SELECT` | a row count |
| 4 | **WP-004** | Cardless Mouth is granted nothing (ADR-0002) | blocked on **WP-005** only | low, **bounded by WP-005's answer** | a negative-auth test |
| 5 | **WP-002** | Stop `patch_consent` overwriting borrower consent with serializer defaults | READY | low — the write is already wrong | a round-trip test |

### Dependency order

```
WP-011 ──┐                          (independent; do both first)
WP-001 ──┘

WP-005 ──────► WP-004               (hard gate: WP-004 must not ship before WP-005 answers)

WP-002 ──────► WP-003, WP-030       (later; not in this five)
```

`WP-011`, `WP-001`, `WP-005` and `WP-002` have **no dependency on each other** and could be done in any order or in parallel. Only `WP-005 → WP-004` is a real edge.

### Why each one

1. **`WP-011` — the two date bombs.** The measured baseline is red by exactly one test, and that test is a stale literal. Until it is green, *"did my refactor break it?"* has no answer, and a team learns to skim past red. It is tests-only, so it carries no rollback question of its own. **It has a deadline**: on 2026-09-15 four more tests fail on the calendar, and if that lands mid-package the failures will appear in a diff that did not cause them. Do not merely bump the literals — the package also asks for one test that fails when any dated constant in the tree is within 30 days of expiry, which closes the class rather than the two instances, and also catches `FISH_TTS_MODEL` (`WP-032`).

2. **`WP-001` — deploy identity and rollback.** Nothing else has a meaningful rollback strategy until images are tagged by commit SHA and the procedure is written down, **including what the database does not revert** — several migrations mutate rows unconditionally and `0101`'s downgrade is `pass`. Entirely additive: CI and docs, no application code. It also adds `npm run build` to CI, which today never runs — and the measured baseline shows the build passes, so this lands green.

3. **`WP-005` — how many Mouths have an empty Agent Card.** One read-only query. It is here because **it is the cheapest way to buy the right to do `WP-004`**, and because the database is now up, which is the only thing that was ever blocking it.

4. **`WP-004` — a cardless Mouth is granted nothing.** ADR-0002 is accepted and unimplemented: `agent_core/skills/runtime.py:182-185` fails **open**, returning `ToolState(allowed=None, offered=None)` when `self.card is None`. It is roughly one line and it is the highest-value regulated change in the tree. It is fourth and not first for one reason: **the population deny-all protects is the population it breaks.** `WP-005` says how large that population is. If the answer is zero, this is free; if it is not zero, this needs a migration plan before it ships, not after.

5. **`WP-002` — stop rewriting borrower consent from serializer defaults.** `db.py:6676-6693` round-trips a consent payload through a serializer and writes the result back, so absent fields are re-materialised as defaults — with `(10, 19)` hardcoded **twice**, in the writer itself. This is a regulated record disagreeing with the world, and it is **still happening**, which is why it outranks the inventory that would count the damage: `WP-003` is blocked on this one, not the reverse.

### One change from the ordering recorded during consolidation

Consolidation put `WP-001` first, on the reasoning that nothing has a rollback until it exists. **Measurement moved `WP-011` ahead of it.** Neither package ships application behaviour, so the rollback argument does not actually bind between them — but `WP-011` has a date on it, and the baseline is red today. The rest of the recorded ordering stands, including its central point: **the existing roadmap has the envelope work and the regulated one-liners last, which is the single largest sequencing error in the corpus.**

### Explicitly not in the first five

- **`WP-012` → `WP-013`** (`load_env()` ordering, then `APP_ENV`) come immediately after. They must stay in that order: setting `APP_ENV=production` is the most likely response to this audit, and on the documented bare-metal path it currently **does nothing while appearing to have worked**.
- **`WP-003`** stays blocked on `WP-002`. Counting corrupted rows while the corruption continues is pointless.
- **Nothing structural.** No `db.py` carve, no route grouping, no dead-code deletion. `WP-045` in particular must **not** ship alongside `WP-042`'s `/agent-studio` work — both land on the same 26 routes, and the natural grouping pass reverses an ordering-sensitive route pair.

---

## CHANGE LOG

| Date | Phase | Result |
|---|---|---|
| 2026-09-01 → 09-03 | Reports `01`–`41` | ~23,850 lines of read-only forensics. Reports `32` and `33` were never produced |
| **2026-09-03** | **Consolidation** | 40 report files read in full · **129** MASTER findings from ~700+ · **15** conflicts adjudicated at source · **21** claims re-verified · **65** work packages · **10** runtime questions left open. **No application file modified.** |
| **2026-09-04** | **`WP-004` — ADR-0002 implemented** | `fd5c73b`. The fail-open sentinel at `agent_core/skills/runtime.py` is inverted; both hand-maintained fallback tool lists deleted; three runtimes pinned by a new test file covering the previously-unpinned unparseable-card branch. **Grok exceeded the authorised scope by 17 files and reported `DONE` rather than `BLOCKED`** — accepted because it is what ADR-0002 asks for and the suite verifies, recorded because the override was silent. One genuine defect caught in review and repaired: a docstring promising a schema-drift guarantee the code no longer provided. |
| **2026-09-04** | **`WP-005`, `WP-066`, `WP-001` · `WP-004` dispatched** | `WP-005` answered with one read-only query: **0 of 18** prompt versions are cardless and all 18 parse, so `WP-004`'s blast radius is **empty** and its gate opened. `WP-066` landed the allowlist Grok had twice declined (`52712ff`). `WP-001` landed SHA-tagged images, a GHCR publish workflow, `npm run build` in CI and `docs/ops/rollback.md` (`06e90b1`) — every factual claim in that document verified against migration source. **`WP-068` filed**: two tests read "today" from the process timezone against an IST guard and go red for 5½ hours a day on any UTC runner. `WP-067` filed: the frontend roster calls an archived bot active. |
| **2026-09-03** | **`WP-011` implemented** | First turn of the supervised loop. Dispatched to Grok 4.6 High via Cursor CLI under `AGENTS.md`; **two review rounds rejected** before acceptance. Two aged-out date fixtures made relative; `tests/test_dated_constants.py` added as a 30-day expiry net. Committed `b30fa8f`. Suite moved 5 failed → 4 (mount artefacts only), 3,141 → 3,148 passed, skips unchanged at 19. **Residual debt recorded as `WP-066`.** |
| **2026-09-03** | **Baseline measurement** | Frontend typecheck/lint/test/build and backend ruff/collection/`alembic heads` run on the host; full `pytest` run in `collections_voice`. **1 genuine pre-existing failure**, 3,141 passed, 19 skipped. Four container-only failures identified as mount artefacts and re-run green on the host. Five inherited numbers corrected. First five work packages selected. **No application file modified.** |
