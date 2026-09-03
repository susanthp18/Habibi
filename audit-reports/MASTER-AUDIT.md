# MASTER AUDIT

**Repo:** [susanthp18/Habibi](https://github.com/susanthp18/Habibi) at `D:\Hackathon`
**Date:** 2026-09-03
**Role:** Principal Software Architect — consolidation phase
**Mode:** Read-only. **No application source, config, migration, test, or dependency was modified.** Nothing was built, started, installed, migrated, seeded or dialled. The only files written are the five orchestration documents named in the brief.

**Inputs:** all 41 Markdown reports in `audit-reports/` (~23,850 lines), read in full, plus first-hand inspection of the repository.
**Companions:** [CONFLICTS-AND-FALSE-POSITIVES.md](./CONFLICTS-AND-FALSE-POSITIVES.md) · [TARGET-ARCHITECTURE.md](./TARGET-ARCHITECTURE.md) · [MASTER-BACKLOG.md](./MASTER-BACKLOG.md) · [REFACTORING-STATE.md](./REFACTORING-STATE.md)

**Vocabulary:** `CONTEXT.md`. **Mouth**, **Agent Card**, **Skill Pack**, **Locked Engine**, **Tool Grant**, **Offer**, **Gate**, **Flow**, **Handoff**, **Mission**, **Cadence**, **Outcome** are that glossary.

---

## Executive Summary

**This system does not need to be modernized. It needs to be *finished*, and then it needs its envelope shut.**

Forty-one independent forensic reports, produced over three days by different analysts against the same tree, converged on one sentence without coordinating: **the correct mechanism exists, is well built, is usually documented with the incident that motivated it — and nothing imports it.** Eleven reports say this in their own words about eleven different subsystems. It is the single most consequential structural fact in this repository, and it is unusual in a good way: the dominant work item is *adoption*, not construction, and adoption is cheap.

The evidence, in one table:

| The control | Built? | Tested? | Wired? |
|---|---|---|---|
| `agent_core/tools/grant.py` — ADR-0001's named Tool Grant owner | yes, 247 lines | yes, 2 dedicated files | **zero production importers** (verified) |
| ADR-0002 cardless deny-all | yes, inside `grant.py` | yes | **no**, three runtimes fail open |
| `rls.py` — row-level security, 633 lines | yes | yes, 6 enforcement tests | **no**, app connects as a `BYPASSRLS` role |
| `observability.JsonFormatter` + PII redaction | yes | yes | **no**, `LOG_FORMAT` absent from a 638-line `.env.example` |
| `/metrics` Prometheus registry | yes, exemplary cardinality discipline | yes | **no scraper anywhere in the tree** |
| `policy_rules.calling_window()` — tenant-publishable statutory hours | yes | yes | **2 of 9 decision sites** consult it |
| `ui/form.tsx` — the a11y form layer | yes, correct | — | **zero importers**; 295 controls have no accessible name |
| `QueryState` — stops "failed read renders as fact" | yes, with the incident in its docstring | yes | **1 importer** against ~110 sites doing the thing it forbids |
| `money_inr` — the Indian-grouping formatter | yes | yes | bypassed by the SMS the borrower reads and the sentence the agent speaks |

Against that, three things are true and they set the risk posture:

**1. The envelope is open, and the interior controls are keyed to it.** The shipped `backend/.env` sets `APP_ENV=dev` with `API_KEY` and `API_KEY_MAP` present but empty — which turns authentication *and* authorization off on the same switch — while `TREATMENT_MODE=live`, `BILLING_ENV=production` and `BOT_ENVIRONMENT=production`. `VOICE_WS_PROXY_SECRET` and `TWILIO_AUTH_TOKEN` are both **set and both ignored**, because each gate short-circuits on `not _IS_PROD`. And `_IS_PROD` is a two-string allowlist (`{"prod","production"}`) computed at import — while `env_utils.NON_PROD_ENVS` reads the *same question the opposite way*. Both are in one process. `APP_ENV=staging` therefore refuses the committed dev signing keys (correct, loud) **and** disables authentication, the Twilio signature check and the voice WebSocket gate (incorrect, silent). Verified at source.

**2. The corpus's own risk ranking is inverted at the top.** Its Critical findings are dominated by file length, coupling graphs, dead UI kit and token drift — real engineering costs, correctly measured, but **no borrower is contacted, charged, or misquoted by any of them.** The changes that most reduce regulatory exposure total **under 60 lines** and need no wave, no green suite, and no shadow period. They are listed in §"If only six things are fixed" below.

**3. The strongest single result in the whole corpus is a positive one that no report states plainly.** Verified 7-for-7 this session: **there is no ungated path to a borrower's phone.** Every `outbound.place` call site is preceded by a `contact_policy.admit` in the same function, and `voice/twilio_ops.start_outbound_call` is the sole function reaching the carrier. One chokepoint, universally gated. `06` DUP-02 and roadmap 3-3 frame the same fact as *"the sequence is written seven times,"* which reads as though a dial might escape the gate. **It cannot.** The real defects are in the *ordering* and in the *evidence left behind*, not in coverage — and a risk committee reading the corpus without this correction would materially over-estimate the exposure.

### The four families

Every finding of consequence in 23,850 lines of forensics reduces to four shapes:

| Family | Shape | Master findings |
|---|---|---|
| **A — The unwired owner** | A canonical module exists, is correct, is tested, and production runs an older copy beside it | MF-001, MF-014, MF-016, MF-017, MF-018, MF-029, MF-030 |
| **B — The open envelope** | A fail-closed control keyed to one unvalidated string that ships permissive | MF-007, MF-008, MF-006, MF-039 |
| **C — The record disagrees with the world** | The system writes evidence for something that did not happen, or destroys evidence that did | MF-005, MF-011, MF-013, MF-020, MF-037 |
| **D — The borrower is contacted twice** | Ambiguity resolved as "did not happen", or a side effect inside a claim transaction | MF-003, MF-004, MF-025, MF-026 |

Families C and D are regulatory. Families A and B are the mechanism that produced them.

### If only six things are fixed

Under 60 lines total. None needs a wave, a shadow period, or a green suite, because every one changes behaviour **only on a path that is already wrong**.

| # | Change | Size | If not done |
|---|---|---|---|
| 1 | `db.py:6676-6693` — stop `patch_consent` rewriting `allowed_days`/`allowed_hours`/`preferred_window` from a round-tripped payload | one conditional | **MF-005.** Irreversible, undetectable, and it fabricates a consent artefact on every save |
| 2 | `agent_core/skills/runtime.py:184` — return `ToolState(allowed=frozenset(), offered=())` instead of `allowed=None` | **one line** | **MF-001.** Closes ADR-0002's fail-open at all four consumers at once. Today an unauthored card can take a PTP and post a goodwill waiver on a live borrower |
| 3 | Add `/twilio/sms/status` and `/webhooks/collections/payment-events` to `_AUTH_EXEMPT_PREFIXES` | 2 lines | **MF-006.** In production both return 401 before their own HMAC runs. SMS delivery receipts lost; CBS bounce ingest dead |
| 4 | `contact_policy.py:596` and `:1020` — fail closed for **every** purpose, not only `outreach` | 4 lines | **MF-002.** A consent-table read error admits the send, and no cap slot is reserved |
| 5 | `payment_events.py:668-675` — move `sent = True` inside the `if twilio_sms.configured():` guard | **one line** | **MF-011.** A statutory bounce notice is recorded as served on a day nothing was sent |
| 6 | `outbound.py:743-751` — classify the carrier exception; a post-POST timeout is *ambiguous*, not `dial_failed` | ~15 lines | **MF-004.** `campaigns.py:611-625` re-queues in five minutes. A double-contact is a breach per occurrence, irreversible, and the ledger shows one attempt |

Item 2 is scheduled **last** in the existing roadmap, behind ~13 developer-days of Wave 0, on a stated blast radius that `voice/tools.py:80-94` contradicts — `ALWAYS_ON` is unioned back *after* the filter, so a cardless mouth keeps `disclose_recording`, `verify_identity`, the flow verbs and `end_call`. It still greets, discloses, verifies and hangs up. It simply cannot move money. **That is a safe degradation and it is exactly what ADR-0002 asks for.**

---

## Repository Overview

One git repository, one product, one guest tree, several scratch trees.

| Tree | Files (tracked) | Role |
|---|---:|---|
| `PRAXIST-main/` | 4,518 | **Guest.** A complete unrelated research platform (Sapient), Fair Source licensed. No import edge into the product, cannot reach any image (every compose build context is rooted at `backend/`). **Out of scope.** |
| `backend/` | 671 | The whole server side: FastAPI API, two job workers, two voice runners, MCP process, SQL, Alembic, seeds, tests, operator scripts |
| `Habibi/` | 504 | The operator console only. TanStack Start / React 19 / Tailwind v4 |
| `source_db/` | 30 | Static RAG corpus (FAQ / policy / benefits). Not a database |
| `docs/` | 7 | 2 ADRs, 3 agent docs, MCP + vault ops. No runbook |
| `artifacts/`, `.loop/`, `_conv_trace/` | 155 | Analysis residue. Not runtime |

**Languages:** Python 3.12 (image and CI; the dev `.venv` is 3.14 — MF-023), TypeScript/TSX, SQL, YAML, Jinja2 (Praxist only), PowerShell, Rust (Praxist only).

**Processes (five application containers plus one unmanaged):**

| Process | Command | Port | Drains / serves |
|---|---|---|---|
| `api` | `uvicorn main:app --workers 1` | 8000 | 314 routes, optional embedded voice host, `usage_meter` thread |
| `worker` | `python -m worker` | — | `kb_index_jobs` + eight unrelated nightly sweeps |
| `bot_worker` | `python -m bot_worker` | — | 15+ collections drains on a 1.5 s poll |
| `voice` | `python -m voice.bot` | 7860 | Pipecat SmallWebRTC + Twilio Media Streams |
| `voice_insurance` | `python -m voice.workers.insurance` | — | Redis mesh specialist |
| `mcp_server` | `python -m mcp_server` | 8081 | **Not a compose service.** Started by hand, or not at all |

**Data plane:** PostgreSQL 16 + pgvector (system of record and job broker), Redis 7 (voice mesh pub/sub only — not a cache), MinIO (KB originals).

**Scale:** `db.py` 18,087 lines / 440 functions / fan-in 101. `main.py` 5,448 lines / 314 route decorators / **zero `APIRouter`**. `schemas.py` 3,453 lines / 247 Pydantic models. 171 tables + 1 view. 102 Alembic revisions, single linear head. 186 backend test files / 2,431 test functions. 474 frontend modules / 11 test files.

**CI:** exactly two workflows, both path-filtered, both test-only. No deploy, no image build, no publish, no tag. `git tag` returns zero.

---

## Current Architecture

**Do not read the folder structure as the architecture.** The reconstructed shape, from imports, call graphs, routes and runtime wiring:

```
Habibi (operator console)                    ← HTTP only. No import edge either way.
   │  routes → components → api/data/lib     ← clean layering, zero cycles
   │  api/config.ts holds 6 of 7 fetch calls ← the strongest single seam in the repo
   ▼
FastAPI main:app  ── 314 routes, 0 routers, fan-in 0 ──┐
   │                                                   │
   ├── db.py ◄──────────────────────────────────────────┤  fan-in 101, fan-out 46
   │     persistence + screen serializers + Gate         │  imports the domain BACK
   │     orchestration + WhatsApp ingest + billing       │  → 107-module coupling SCC
   │                                                     │
   ├── Locked Engines  (agent_core/{treatment,reco,authority,live_qa})
   │     features → candidates → veto → score → arbitrate → log → [enact]
   │     49 of 56 intra-engine edges respect stage order. THE ARCHITECTURE HOLDS HERE.
   │     Package façades deliberately withhold `enact`.
   │
   ├── contact_policy.admit  ── the one Gate every outbound path calls (13 sites)
   ├── outbound.reserve/suppress/place ── the attempt ledger
   └── voice/  ── Pipecat Mouth, 3 of 44 modules in the knot. Almost entirely clean.
```

**The architecture that is documented and holding:** a *gated decision pipeline*, implemented four times over, whose invariant is an **ordering of gates** rather than a layering of abstractions. `agent_core/treatment/README.md:33` states it: *"Exploration is last, and that is the architectural boundary."* Measured: it holds. All seven apparent inversions were re-checked and are ranking artefacts, not control inversions.

**Three boundaries are enforced better than most codebases of this size:**

- **HTTP does not leak inward.** `fastapi`/`starlette` in 3 of 267 backend modules. `HTTPException` in exactly one file (202 uses, all `main.py`). **Nothing imports `main.py`** — zero edges, for a 5,448-line god router.
- **Wire schemas do not leak inward.** `schemas.py` has exactly two importers.
- **Authorization is total and provable.** A global `Depends(_authz_guard)` on the `FastAPI(...)` constructor, two reviewable tables, unregistered routes *denied*, coverage proven by a CI test at **318/318**.

**The boundary that is failing is the one nobody named: `db.py`.** It is not a shared kernel — a shared kernel has fan-out 0. This one imports the Locked Engines, `contact_policy`, the channel adapters and the job queue back. Cutting *either* direction of its edges collapses the coupling SCC from 107 to 17; twelve surgical single-edge removals only reach 36. **The coupling is one file and it has to be cut whole.**

**Two permission systems, correctly separate:** staff `authz.ROUTE_PERMISSIONS` (may this *operator* hit this *route*) and the **Tool Grant** (may this *Mouth* execute this *tool*). The first is exemplary. The second has two owners and one of them is unimported.

**Two persistence spines, correctly separate:** `interactions` (a connected session) and `call_attempts` (every dial, including suppressed and unanswered). Treating either as "the" session entity is a modelling error.

---

## Major Business Capabilities

Nine domains hold together under load. Three more are real but weak.

| Capability | Owner today | Health |
|---|---|---|
| **Contact policy / consent admission** | `contact_policy.admit` + `policy_rules` + `contact_events` ledger | **Strongest seam in the codebase.** `_veto` is a pure function of 8 arguments — no connection, no I/O, no clock. Defects are at the edges (MF-002, MF-005, MF-014) |
| **Mouth publish** (Card → Gates G0–G15 → Deployment) | `agent_core/cards/compile.py`, `db.publish_prompt_version` | Compile is real and sequential. `CompileReport.ok` counts `warn` and `skipped` as green (MF-038) |
| **Tool Grant / Offer** | *split* — `intersect` + `ALWAYS_ON` live; `grant.py` is the ADR owner and unimported | **MF-001.** Highest-value single fix in the tree |
| **Outbound attempt / Mission / Cadence / Outcome** | `outbound.py`, `mission.py`, `cadence.py`, `call_closer.py` | Best-isolated pipeline. `call_attempts` state machine is monotonic and order-insensitive. MF-004 and MF-037 are at its edges |
| **Treatment** (locked) | `agent_core/treatment/*` | Exemplar package shape. Enact dials and SMSes inside the claim transaction (MF-025) |
| **Reco / NBO** (locked) | `agent_core/reco/*` | Parallel to treatment. `_recommend` takes no `conn` at all (MF-011) |
| **Authority** (locked) | `agent_core/authority/*` — ₹ waiver matrix | Narrow, correct matrix. `apply_goodwill` is not serialised (MF-041) |
| **Live QA** (locked) | `agent_core/live_qa/*` | Turn-hooked, pure checks over a value object. 15/15 pure functions |
| **Collections resolution** (PTP, dispute, callback, document, follow-up) | `db.py` — **no application service** | Cohesive *entities*, no cohesive *module*. Status machines have no transition guards (MF-038) |
| **Book** (customer, account, ledger, EMI) | `db.py` + SQL | `numeric(14,2)` money throughout. `accounts.outstanding` vs `ledger_entries.balance` is a dead-column trap |
| **Human ops** (inbox, floor, handoff hub) | `db.py`, `ops_screens.py` | Three channel-specific queues sharing one English word |
| **Inbound routing rules** | `db._match_routing_rule` — a fifth decision engine, inside persistence | The clearest "business rules in the repository" finding |

**Present in the backend, absent as a nav item:** hosted pay page, mandates, agent Handoff graph, campaigns, twins, work-runtime jobs, grievance-officer copy.

---

## Critical Findings

Format per the brief: **ID · Severity · Confidence · Location · Evidence · Impact · Root Cause · Recommended Action · Verification Required.**

Severity is **regulatory exposure and irreversibility first**, engineering cost second. A finding that costs a quarter of developer time but cannot contact, charge or misquote a borrower is not Critical here, however large.

---

### MF-001 · Tool Grant has no owner; ADR-0001 and ADR-0002 are accepted and unbuilt

**Severity:** P0 (regulated) · **Confidence:** Certain — verified at source this session
**Merges:** `02` §4.8 · `04` P0 · `05` §7.3 · `06` DUP-01 · `07` B/C · `08` BUG-1, BUG-5, BUG-10 · `09` C-01 · `10` S-05 · `18` X7 · `19` · `22` · `23` §4.5 · `26` · `31` F7 · `34` F10/F21/F24 · `35` R17 · `38` C3/C4 · `39` · `40` 3-7 · `41` §5.1 · `architecture-forensics` AF-02/AF-03/AF-06

**Location.** Owner: `agent_core/tools/grant.py` (247 lines). Live formulas: `agent_core/skills/runtime.py:182-185` (`MouthTurn.tools()`), `agent_core/skills/intersect.py:65-68` (`_apply_channel`), `agent_core/cards/compile.py:494-510, 630`, `voice/tools.py:80-94, 2911-2913`, `bot_runtime.py:947-951`, `bot_tools.py:59-85, 831`, `sandbox_runtime.py:230-244`, `flow_graph.py:773-785`.

**Evidence.** Verified by indexed search over `backend/**/*.py`: the only references to `ToolGrant`, `may_execute`, `static_grant`, `for_bundle` outside `grant.py` itself are `tests/test_tool_grant.py`, `tests/test_tool_grant_characterization.py`, and a module-name string at `tests/test_import_cycles.py:35`. **Zero production importers.** The module's own docstring concedes it. Two commits on this branch (`5560159`, `767f1b4`) refined the module without wiring it.

Verified at `agent_core/skills/runtime.py:182-185`:
```python
def tools(self, *, catalog_names: set[str] | None = None) -> ToolState:
    """What this turn may execute, and what to put in front of the model."""
    if self.card is None:
        return ToolState(allowed=None, offered=None)
```
Every caller reads `None` as *no filtering*. `bot_tools.py:831` is `if ctx.allowed_tools is not None and …`; `voice/tools.py:2911` is `if allowed_tool_names is not None:`. So a cardless Mouth is not merely *offered* the write catalog — it is **permitted to execute** it, including `create_promise_to_pay`, `apply_goodwill` and `flag_dispute`.

**One divergence is verified, not hypothetical.** `intersect._apply_channel` returns names unchanged when `channel_tools is None`. `compile.py:630` passes `channel_tools=`; `skills/runtime.py:194,197` does not. **The publish gate computes a channel-filtered grant and both runtimes compute a channel-blind one.** A card naming a text-only tool is granted it on a voice call where no handler exists, and the Gate that validated the card applied a different rule than the runtime that enforces it — which is precisely the failure ADR-0001's opening paragraph describes.

**Impact.** Prompt injection from borrower speech or a WhatsApp message can drive live CRM write tools on any Mouth whose card is missing, unauthored, or fails `parse_card`. Locked Engines still cap waiver *amounts*, so the hole is *"run the catalog"*, not *"raise the cap"* — but the catalog includes taking a promise to pay. Separately, **agent-to-agent Handoff cannot be correct until the grant is recomputed from the receiving card** (MF-040): voice filters the registry once at session start and then unions `ALWAYS_ON` back on top.

**Root cause.** A `None` sentinel that meant *"no grant was derived"* to its author and *"do not filter"* to every caller. `grant.py` was correctly written beside the old formulas so they could be migrated; the deny-all ticket was scheduled last and never landed.

**Recommended action.** In order, each separately reviewed:
1. Pass `channel_tools=` at `skills/runtime.py:194,197`. **Two lines, needs none of `grant.py`,** closes the one verified divergence.
2. `import VOICE_ALWAYS as ALWAYS_ON` from `grant.py` into `voice/tools.py` — deletes one of the three always-on literals with **no prerequisites** (`voice/tools.py:31-39` already imports four `agent_core.tools` modules and `grant.py` is Pipecat-free).
3. Migrate `MouthTurn.tools()` → `ToolGrant.for_bundle` across voice, text and sandbox.
4. Replace `compile.py` `allowed_scope` with `ToolGrant.static_grant`.
5. Remove `| ALWAYS_ON` at `voice/tools.py:2912` — **only after step 3**, or a seventh formula has been created.
6. **Return `allowed=frozenset()` for a cardless card. Lands alone and last** — but see the Executive Summary: this is one line, and the degradation is safe.

**Verification required.** `SELECT bot_id FROM prompt_versions WHERE agent_card IS NULL OR agent_card = '{}'::jsonb` before flipping the sentinel — the population it protects is the population it breaks. And **fix the pin's reach**: `tests/test_tool_grant.py:131` opens with `pytest.importorskip("voice.tools")`, so the `VOICE_ALWAYS == ALWAYS_ON` assertion silently skips wherever pipecat is absent — the API image and CI.

---

### MF-005 · The consent drawer overwrites borrower consent with serializer defaults on every save

**Severity:** P0 (regulated, irreversible, undetectable) · **Confidence:** Certain — traced end to end and verified this session
**Merges:** raised only by `41` §4.1. **No other report in the corpus asks whether consent *changes* are recorded.**

**Location.** `db.py:2038-2054` (`_parse_allowed_days`), `db.py:2066-2072` (`_parse_allowed_hours`), `db.py:2306-2310` (serialization), `Habibi/src/api/consent.ts:38-49`, `db.py:6676-6693` (`patch_consent`).

**Evidence.** Verified at `db.py:6676-6693`:
```python
if "allowedWindow" in payload and payload["allowedWindow"] is not None:
    aw = payload["allowedWindow"]
    days_str  = _format_allowed_days(list(aw.get("days") or []))
    hours_str = _format_allowed_hours(int(aw.get("startHour", 10)), int(aw.get("endHour", 19)))
    UPDATE consent_records SET allowed_days = :days, allowed_hours = :hours WHERE id = :id
    UPDATE customers        SET preferred_window = :hours WHERE id = :id
```
`api/consent.ts` always includes `allowedWindow` in the PATCH — **including a save that only toggled a channel.** Two irreversible outcomes, both verified by hand-tracing the parser:

- **`allowed_days = 'Mon–Sat'` (en-dash) → `'Mon-Mon'`.** `_parse_allowed_days` tests `if "-" in text_val` — an en-dash is not a hyphen, so the range branch is skipped; `re.split(r"[,\s]+", "mon–sat")` yields one token, key `"mon"`, days `[1]`; `_format_allowed_days([1])` returns `f"Mon-Mon"`. **Six days of consent overwritten with one — and afterwards both parsers agree on Monday, so the bug becomes undiagnosable.**
- **`NULL` → `'Mon-Fri'` and `'10:00-19:00 IST'`.** Note the defaults are hardcoded **twice**: `_parse_allowed_hours` returns `(10, 19)` on empty, *and* the writer itself defaults `aw.get("startHour", 10)`. A record that said *no window captured* now asserts a window the borrower never stated, and `customers.preferred_window` is stamped with it too.

`db.py:6746` records the change as one contentless row: `kind='consent_updated'`, `label='Consent preferences updated.'` — no before, no after, no field list. There is **no history table** for `consent_records.allowed_days/allowed_hours`; `optout_events` covers withdrawals only.

**Impact.** The platform silently manufactures a consent artefact and destroys the real one. A DPDP inquiry, or a borrower exercising a data-access right, opens with *"what did I agree to, and when did it change?"* **The platform can answer neither.**

**Root cause.** A read-serializer default leaking into a write path through a round-tripped payload, plus a display parser used as a storage parser.

**Recommended action.** Sequence matters:
1. **Stop the write-back** — omit `allowedWindow` unless the operator changed it, or preserve the stored string when the parsed value round-trips unchanged.
2. **Inventory** the damage (below).
3. **Then** consolidate the parser onto `contact_policy._parse_days`.
4. **Re-confirm only the already-corrupted rows**, where the original consent is unrecoverable.

**This inverts roadmap Wave 2B-4.** The roadmap argues for delay because fixing the parser *"silently widens those consent windows from one day to six — a DPDP-relevant change."* The stored string **says `Mon–Sat`**; the borrower consented to six days. Reading it as Monday-only is the platform failing to use consent it holds — commercially expensive, regulatorily inert, and `contact_policy.py:227-231` says exactly that in its own comment. **The genuine hazard runs the other way, and it is the write-back.**

**Verification required.**
```sql
SELECT id, allowed_days FROM consent_records
 WHERE allowed_days ~ '[–—]'
    OR allowed_days IN ('Mon-Mon','Tue-Tue','Wed-Wed','Thu-Thu','Fri-Fri','Sat-Sat','Sun-Sun');
```
The second set is the re-consent population.

---

### MF-007 · Authentication and authorization fail open together, on a two-string allowlist, in a deployment that is dialling live borrowers

**Severity:** P0 · **Confidence:** Certain — verified at source
**Merges:** `18` X1/X2/X4 · `19` P0-2 · `20` C1/C2/C3/C4/H7 · `31` F3 · `37` I2 · `39` (Security 3, Configuration 4)

**Location.** `main.py:204-205`, `:292`, `:431-438`, `:3392`, `:3396`, `:3479`; `authz.py:624-639`; `actor_context.py:55, 58-65, 203-226`; `visibility.py:92-100`; `env_utils.py:33, 38`.

**Evidence.** Verified verbatim:
```python
# main.py:204-205
_APP_ENV = (os.getenv("APP_ENV") or "dev").strip().lower()
_IS_PROD = _APP_ENV in {"prod", "production"}
```
```python
# env_utils.py:26-33 — the SAME question, read the other way, in the same process
# "...only an *explicitly* non-production name earns a built-in development
#  key, so a deployment with APP_ENV=staging (or a typo) raises rather than
#  trusting a constant that is committed to this repository."
NON_PROD_ENVS = frozenset({"dev","development","local","test","testing","sandbox","ci"})
```
The comment proves the author knew both readings existed and chose the safe one **for keys only**. Nobody applied it to the other nine sites.

`main.py:292` — `auth_required = bool(single or key_map)`. **Absent credentials is a mode, not a refusal.** `authz.enforcement_enabled()` follows the same expression, and `visibility.resolve()` defers to `authz`, so **one missing variable disables three layers with no defence in depth.** `actor_context._allow_actor_header()` then defaults to `not _is_prod()`, so an anonymous caller sends `X-Actor-User-Id: priya-nair` — the seeded administrator, whose id is public in this repository — and every write is attributed to them.

Eight independent controls key off `_IS_PROD`: the hardening gate, the API-key requirement, actor-header spoofing, the unauthenticated-actor refusal, OpenAPI publication, the Twilio signature check, the voice WS proxy secret, and actor-config validation. `APP_ENV=staging` disables all eight **silently**, while `env_allows_dev_key()` correctly refuses the committed keys **loudly**. Half the process believes it is in production.

**And the ordering makes the obvious remedy inert.** `main.py` **never calls `load_env()`** — verified by whole-file scan. On the documented bare-metal launch path (`main.py:3`, `run_stack.ps1:43`), `os.getenv("APP_ENV")` at line 204 returns `None` because `.env` has not been read yet. **An operator who sets `APP_ENV=production` in `.env` sees no error, no warning, and no change in behaviour.** Compose masks this because `env_file:` injects before Python starts.

**Impact.** Unauthenticated read/write of a regulated collections CRM on any host that can reach the process — with attacker-chosen audit attribution — while `TREATMENT_MODE=live` authorises the executor to place real calls and send real messages, through a public tunnel URL.

**Root cause.** A boolean derived from *whether credentials happen to be configured*, gated on a string equality test whose default is the unsafe value, computed before the file that would set it has been read.

**Recommended action.** All four halves, in this order:
1. `load_env()` at the top of `main.py`, above the application imports — the shape `bot_worker.py:27-31` already uses. **Do this first**; every other change is unverifiable until the API actually reads the file.
2. `_IS_PROD = _APP_ENV not in {"dev","test","local"}` — one line, inverts the failure direction of all eight controls at once.
3. `main.py:292` — absent `API_KEY`/`API_KEY_MAP` must **refuse to boot in every environment**, not select a mode.
4. Delete the non-prod `return True` at `main.py:3479` and the `not _IS_PROD` at `:3396`. **Both secrets are already configured in `.env`.**

**Verification required.** After (2), confirm the change took effect — under the C4 ordering bug the natural assumption that it did is exactly what fails. Add a CI job that runs with `APP_ENV=production`; today the suite exercises only the permissive branch, and two tests already route around the import-time freeze with `monkeypatch.setattr(app_main, "_IS_PROD", True)`.

---

### MF-006 · Two signature-verified production webhooks return 401 before their own HMAC runs

**Severity:** P0 (regulated evidence loss; invisible in dev and CI) · **Confidence:** Certain — verified at source
**Merges:** `18` X17 · `19` H5 · `22` H3 · `37` I5 · `41` §4.2 · `architecture-forensics` AF-04

**Location.** `authz.py:229, 233` vs `main.py:233-257`; handlers at `main.py:3669` and `main.py:857`.

**Evidence.** Verified: both routes are declared public in `authz.PUBLIC_ROUTES` with a comment stating *"the signature check inside the handler is the authentication"*. Neither is in `_AUTH_EXEMPT_PREFIXES` — and `/webhooks/payments` does **not** prefix-match `/webhooks/collections/payment-events`, because matching is `path == p or path.startswith(p + "/")`. `ApiKeyMiddleware` runs first. So with `API_KEY` set — which `main.py:432` makes mandatory in production — both return 401 and the handlers never execute.

**Why it survived is visible in the code.** The comment above `_AUTH_EXEMPT_PREFIXES` records a real incident: exempting all of `/twilio` left `POST /twilio/voice/outbound` open to the internet. The fix replaced a prefix with an explicit enumeration — and the enumeration covered the four voice callbacks its author was looking at. `/twilio/sms/status` was added to `authz.py` later, by someone reading the authorization policy, who had no reason to know a second list existed. **The security fix created the availability bug**, and neither list references the other.

**Impact.** SMS delivery receipts are lost — and SMS is the fallback channel used when WhatsApp is outside its 24-hour window, so **the channel of last resort is the one with no delivery evidence.** The CBS bounce-ingest path is dead, which is the path `enact._hand_to_lms` says mandate settlement returns through, so the treatment follow-through loop cannot close.

**Root cause.** One policy written twice, in two files, with no derivation and no test asserting they agree.

**Recommended action.** Derive `_AUTH_EXEMPT_PREFIXES` from `authz.PUBLIC_ROUTES`, or add the three-line test asserting the two agree — the same shape as the guard `tests/test_env_name_shared_helper.py` already applies to a different pair of lists.

**Verification required.** Neither path appears anywhere in `backend/tests/` (zero hits). Add one HTTP test per webhook asserting an unsigned body gets 401 **from the signature check**, not from the middleware — and note `test_production_hardening.py:41-45` currently asserts `status_code != 401` on four voice paths in a fixture where `_twilio_signature_ok` returns `True`, so those unsigned POSTs are being *accepted*.

---

### MF-004 · Five independent paths contact a borrower twice

**Severity:** P0 (regulated, irreversible per occurrence) · **Confidence:** High
**Merges:** `08` · `14` K1/K2/K4/K5/K6 · `15` F5/F6 · `16` S2/S3 · `25` R1/R2/R3/R6 · `39` · `40` H3

**Location.** `contact_policy.py:965-981` · `main.py:3782`, `:4102` · `outbound.py:309-425`, `:743-751` · `campaigns.py:611-626` · `whatsapp_outbound.py:545-560` · `agent_core/treatment/enact.py:904-912`, `:295-314`.

**Evidence.** Five mechanisms, five files, one outcome:

| # | Mechanism |
|---|---|
| **K1** | `admit` computes `coalesced` and puts **cooling-off, the weekly cap and the daily-cap reservation all inside `if purpose == "outreach" and counts:`**. Both dial endpoints pass the **customer id** as `session_key`, so a second click within 30 minutes is coalesced: the call is admitted, **and the daily cap of 3 records one touch for the whole burst.** `_veto` still runs, so consent, DND and RBI hours hold. Every *frequency* rule does not. |
| **K2** | `outbound.reserve` has no idempotency key, no `ON CONFLICT`, no advisory lock, and no non-terminal-state check. The only unique index on `call_attempts` is on `provider_call_id`, which is written *after* `calls.create` returns. `_handle_write` threads `Idempotency-Key` for creating a promise and not for dialling a person. |
| **K4** | `outbound.place` maps **any** Twilio exception to `{"placed": False}`. A 10 s read timeout *after* Twilio accepted the create is indistinguishable from a rejection, and `campaigns.process_one` returns the target to `pending` at +5 min. `cadence.py:224-228` makes the **opposite** decision on the same state. |
| **K5** | A DB failure *after* a successful WhatsApp send produces `whatsapp_send_failed:internal:OperationalError`, which **neither classifier can parse**, so the job is requeued — while `delivery_status` is still `sending` because that write is the one that rolled back. |
| **K6** | `treatment.process_one` wraps `claim_due` **and** `enact_one` in one `engine.begin()`; `_send_sms` calls Twilio on that connection. A rollback after a successful send re-sends. |

**Impact.** Under the RBI Fair Practices Code contact *frequency* is the regulated quantity, and `contact_day_counters` is the system's evidence it was respected. **K1 makes that evidence affirmatively wrong** rather than merely absent: a regulator pulling `contact_events` sees one counted touch on a day the handset rang eight times.

**Root cause.** Duplicate-contact prevention lives at five call sites instead of the one seam they all share. And the repository already contains the correct answer, once, on the messaging channel — `whatsapp.py:201-244`'s `is_definite_client_error` / `is_ambiguous_transport_error`, with a docstring explaining that the Cloud API accepts no client idempotency key so an ambiguous error must **never** be retried. Voice never got it.

**Recommended action.** In value order: classify the Twilio exception (K4 — the only one that is a pure win with no schema change); move cooling-off and the cap reservation outside the `counts` branch **or** stop passing `customer_id` as `session_key` (K1 — *one* of the two, not both); thread `Idempotency-Key` on the dial endpoints and add a partial unique index on non-terminal `(customer_id, objective)` (K2); split the treatment claim from its side effect, copying `call_closer.process_one`'s three-phase shape (K6); classify `whatsapp_send_failed:internal:*` after `post_attempted_at` as ambiguous (K5).

**Verification required.** A test that a campaign does **not** re-queue after a Twilio read timeout — report 25 names it as missing and it is the one test that would fail today.

---

### MF-002 · The contact Gate returns ALLOW for every non-outreach purpose when it cannot read the database

**Severity:** P0 (regulated) · **Confidence:** Certain — verified at source
**Merges:** `08` BUG-6 · `14` K3 · `22` H20 · `25` · `28` F4 · `39`

**Location.** `contact_policy.py:596-600` (`evaluate`) and `:1020-1024` (`admit`), verified identical.

**Evidence.**
```python
except Exception:
    logger.exception("contact_policy.admit failed customer=%s", cid)
    if purpose == "outreach":
        return Decision(False, REASON_UNREADABLE, daily_cap=cap)
    return Decision(True, daily_cap=cap)
```
Inside that same `try` sit `_channel_status` (the opt-out/consent read), `_veto` (DND, calling window), the cooling-off check and the cap reservation. A lock timeout, an RLS mis-grant, a migration in flight or a bad column **admits the send**, and no cap slot is reserved. Non-outreach callers include `bot_runtime.py:150` (every bot WhatsApp reply), `whatsapp_outbound.py:449`, `db.py:10280`, and `purpose="statutory"` at `payment_events.py:587/634/648` and `promise_fulfillment.py:599/995`.

**This is also why `bot_runtime.py:158`'s own `except` never fires** — `admit` swallowed the exception first — and is presumably why nobody noticed. An earlier revision of report 14 proposed hardening that unreachable handler.

**Impact.** During a database blip: opt-out, DND, expired consent and cooling-off are not applied to WhatsApp replies or statutory notices, and `contact_events` has no counted row.

**Root cause.** A product preference (*never leave a customer on read because our DB blipped*) implemented as a blanket `True`, contradicting the module's own fail-closed contract.

**Recommended action.** Return `Decision(False, REASON_UNREADABLE)` for **every** purpose. If product insists on answering an in-flight thread, require a separately named purpose with an explicit, audited override.

**Verification required.** Fault-inject in `_load_customer`; assert the reply is refused and no `contact_events` row is written.

---

### MF-008 · Revoking every permission from a role restores that role's full defaults

**Severity:** P0 (survives locking the envelope) · **Confidence:** High
**Merges:** `18` X3 · `19` P0-1 · `35` R20 · `39`

**Location.** `authz.py:702-714`; `db.py:473-508`; `main.py:2828-2862`; `Habibi/src/routes/roles.tsx:26-34`.

**Evidence.** The resolver cannot distinguish *"stripped of everything"* from *"never configured"*. The `LEFT JOIN` at `authz.py:686` yields one row with `permission_id IS NULL` for a role with zero grants; `explicit` is the empty set; the `else` branch unions `ROLE_DEFAULTS`. **The comment three lines above — "a revoked grant stays revoked" — is false in exactly this case.** `GET /roles` reads raw rows, so the screen shows `[]` while the enforcer grants everything. For `supervisor` that is 23 permissions including `VOICE_OPERATE` — the right to telephone real borrowers. And `authz.py:713` short-circuits on the role *name*, so `admin` cannot be de-privileged at all.

**Why it survived review.** A test is named for exactly this property — `test_explicit_grant_beats_default_so_revocation_works` — and it only ever exercises *partial* revocation. `db.replace_role_permissions` has no test at all.

**Impact.** The one action an operator takes in an incident to lock a role down does the opposite, and the screen confirms the opposite of what is enforced.

**Root cause.** Absence of a row used as a proxy for absence of intent.

**Recommended action.** Distinguish "no rows" from "revoked to empty" (a sentinel row, or a `configured_at` column). Make `GET /roles` report **resolved** grants. Call `invalidate_permission_cache` from `replace_role_permissions` — it exists, its docstring says *"call after a role change"*, and it has zero production callers, so a revocation currently lags 30 s per process.

**Verification required.** The test that should have existed: revoke *all*, assert empty.

---

### MF-011 · The record disagrees with what happened — money, statutory notice, and audit chain

**Severity:** P0 (regulated evidence) · **Confidence:** High
**Merges:** `12` · `14` K7/K8/K9/K10 · `15` F5 · `25` R4/R5 · `38` C2 · `39` (Data 6) · `41`

**Location.** `payment_events.py:668-675` · `payments.py:147-148`, `:219-257` · `bot_tools.py:544-556` · `agent_core/change_log.py:57, 110-134, 162` · `agent_core/treatment/engine.py:241-259`, `authority/engine.py:220-229`, `reco/engine.py:138-158`.

**Evidence.** Five distinct instances of one shape:

| The record says | Reality |
|---|---|
| Statutory bounce notice served, `first_touch_at` stamped | `sent = True` sits **outside** `if twilio_sms.configured():`. With `TWILIO_SMS_FROM` unset nothing was sent — and `suppression_reason` is nulled, so no report will ever surface it |
| `{"ok":true,"idempotent":true}` — a duplicate | Idempotency is keyed on `payment_intents.status == 'paid'`, **not on `provider_ref`**. A second genuine ₹5,000 settlement is discarded, absent from the ledger, and collections continues against a borrower who has paid |
| `{"ok":true}`, payment posted | `cure_for_account` runs in `try/except` on the caller's connection with **no SAVEPOINT**. Mid-loop failure leaves EMI rows half-written, `cured == []`, the webhook publishing `"curedEvents":[]` — and the transaction commits |
| The customer's refusal is recorded, "do not raise it again" | `_tool_decline_offer` sets the session flag *before* the write, swallows the exception, and returns `ok=True` |
| The audit log is tamper-evident | `change_log.py:57` sets `_ENTITY_TYPE = "bot"` and `:162` is the **only** `INSERT INTO audit_log`. **The hash chain covers agent-card configuration publishes only.** Money movements, consent changes and contact events carry no chain, and `verify_chain` only ever walks the `bot` entity |

**And the chain itself is weaker than its docstring.** `audit_log` has no `seq`/`prev_hash`/`entry_hash` columns — the chain lives inside a `payload` jsonb; `_chain_head` reads `MAX(seq)` with no lock and no unique constraint on `(tenant_id, entity_type, seq)`, so two concurrent publishes fork the chain and `verify_chain` walks one branch and reports ok. No immutability trigger, no `REVOKE`, and `verify_chain` is scheduled by nothing.

**Separately, the Locked Engines can write an audit row for a rolled-back action.** All four accept an injected connection and **fall back to opening their own** from the `db.engine` global (64 modules, 262 references). `treatment/engine.py:259` states the cost in its own comment: *"One connection for the whole read phase, then the log writes on its own."* `reco/engine.py:_recommend` takes no `conn` parameter at all — there is no seam to inject through.

**Impact.** In a regulated pilot the artefact *is* the compliance position. A duplicate call is a breach you can find in the logs; a false record is a breach you cannot.

**Root cause.** A best-effort write sharing a transaction with the record that authorises it, and a status flag set before the write it describes.

**Recommended action.** One line for the bounce guard. Key payment idempotency on `provider_ref`, copying the unique-index + SQLSTATE pattern `db.py:10673-10688` already uses for a *text message*. SAVEPOINT the cure. Return the write's real outcome from the three tool handlers. Delete the `db.engine.connect()` fallback in the engines and make `conn` required — the seam already exists in two of four, and `treatment/decisions.py:41-61` already states the contract. Add a unique index on `(tenant_id, entity_type, seq)` and take a lock in `_chain_head`. **State the audit capability honestly:** *"hash-chained for bot configuration; unchained for financial and consent events."*

**Verification required.** `SELECT count(*) FROM payment_intents pi JOIN payment_events pe ON … WHERE pi.status='paid'` against distinct `provider_ref` values, to size the discarded-settlement population.

---

## Duplication Findings

The dangerous duplicates are not copy-pasted UI. They are **competing answers to one regulated question**. jscpd measured 41 TypeScript clones (0.61%) and 134 Python clones (1.80%) — that is the token layer, and it is not where the risk is.

| ID | Sev | The question | Owner | Copies | Diverged? |
|---|---|---|---|---|---|
| **MF-014** | **P0** | What window may we contact in when none is on file? | `contact_policy` RBI 08–19 (statute) + `contact_window` 09–20 (preference) | **three defaults**: 08–19, 09–20, **10–19** (`db.py` ×5, `schemas.py:42`, and a **Skill Pack prompt the model repeats to a borrower**) | **Yes.** `db.py:1938` is not display — it feeds `_callback_dnd_active` and changes a DND verdict, disagreeing with `db.py:5468` in the same file |
| **MF-014b** | P1 | Which hours does the *statute* allow? | `policy_rules.calling_window()` | **9 decision sites, 2 consult it.** `compliance/detectors.py:297-298` restates `8` and `19` **sixteen lines above** `from contact_policy import _zone  # one definition of the timezone fallback`, and nothing pins those numbers | Latent — fires for any tenant that publishes a narrower window |
| **MF-015** | P1 | Is this party on DND? | — | `contact_policy.py:504` ORs `customers.dnd \| dnd_registry`; `db.py:2313` ORs both; **`db.py:1826` reads `customer_dnd` only** | **Yes.** Registry-flagged but not customer-flagged: blocked by the Gate, red on consent, **green on the callback board** |
| **MF-016** | P1 | Which consent statuses forbid contact? | `contact_policy.BLOCKING_CONSENT` | **four definitions under three names**, `capture.py:331` is `_CONSENT_BLOCKING_STATUSES`; **9 use sites, five in `capture.py` alone** | No — member-identical today. Two of the copying modules already import `contact_policy` for other reasons |
| **MF-037** | **P0** | The outbound gate *sequence* | nobody | **7 sites, two orderings.** `payment_events.py` runs `admit → reserve → place` with **no `outbound.suppress` anywhere in the module** | **Yes.** The invariant *"every refused outbound leaves a suppressed attempt row"* holds at six of seven and is **false at `payment_events`** — a hole in the evidence of a *correct* refusal |
| MF-042 | P1 | Last four of the account id | `agent_core.context.account_tail` (digits only) | **five algorithms**: `db.py:411` raw slice (7 sites), `ops_screens.py:415/674` SQL `RIGHT()`, `voice/persist.py:939`, and **`enact.py:237` — the only one that reaches a borrower in writing, on a dunning SMS** | **Yes.** `AC-SUSANTH` → `ANTH` on the desk, `None` on the Mouth |
| MF-043 | P1 | Rupee formatting | `money_inr.inr` | `promise_fulfillment._fmt_inr` and `mission._inr` emit Western grouping, plus **three cross-module reach-throughs into the private one** | **Yes** — and it lands in the SMS the borrower reads and **the sentence the agent speaks aloud** |
| MF-044 | P1 | Payment webhook HMAC | — | `payments.py:69-82` and `payment_events.py:56-64`, **byte-identical after the secret lookup** | No |
| MF-045 | P2 | Twilio REST client | — | **three** independently constructed `Client()` from one credential pair; new client + new `requests.Session` **per call**, no breaker, no pool | No |
| MF-046 | P2 | `env_int` | `env_utils.env_int` | three local copies; `reco/config.py:42` **logs a warning** where the canonical swallows silently — and WARNING is the level that survives the missing root handler | Behaviourally, yes: an observability deletion filed as cosmetic |
| MF-047 | P2 | The queue machine | — | copy-pasted **4×** with different caps, backoffs and terminal vocabularies (`succeeded` vs `completed`, `dead` vs none) | Yes, deliberately in one case (WhatsApp dead-letters ambiguous errors — that divergence is the *correct* part) |

**Rejected lookalikes — do not consolidate.** `contact_window` 09–20 (borrower *preference*) vs RBI 08–19 (*statutory*) — **merging these would be the worst single outcome of this exercise.** Staff `authz` vs Tool Grant. Compile Gate vs `admit`. Four meanings of **Offer**. Three of **Handoff**. Cadence vs job retry vs HTTP retry vs breaker. `money_inr.inr` vs `inr_compact`. `env_loader.load_env` (publishes) vs `db._read_env_file` (must not). `platform_flags` vs `platform_switches`. In-process breaker vs DB-backed connector breaker.

---

## Dead Code Findings

**The backend is genuinely lean and a roadmap must not promise otherwise.** ~0.08% provably dead. The frontend is ~2.9%.

| ID | Sev | Finding |
|---|---|---|
| **MF-031** | P2 | **29 frontend files / 2,843 lines / 22 npm deps are provably dead**, verified twice by independent re-derivation. 22 `components/ui/*` wrappers — including `card.tsx` and `tooltip.tsx`, which report 07 missed and I confirmed have **zero importers** anywhere in `Habibi/` — plus `BigBoundMark`, `records/index.ts`, `AlertLane`, `CallTile`, `StatusPill`, `ScenarioList`, `use-mobile`. `toggle.tsx` ← `toggle-group.tsx` is a **closed two-node dead cluster** |
| MF-031b | P2 | **This re-scopes three prior reports.** Reports 27, 29 and 30 all take `components/ui/` as in-scope remediation surface, and 22 of those files are dead — including `ui/form.tsx` (171 lines), which report 30 names as *"a correct primitive with 0 importers awaiting adoption."* It is not an adoption candidate; it is deletable |
| MF-048 | P3 | `AGENT_CARDS_ENABLED` is the **one** genuinely dead backend flag — verified: definition, `.env.example:309` and a default-off test, **zero application readers**. The template claims a kill switch for Agent Cards that does not exist |
| MF-049 | P3 | `[tool.vulture]` in `pyproject.toml` configures a tool that is in no requirements file |
| MF-050 | P2 | `provider_voice_sync.py` (364 lines) is implemented, has an operator CLI, and is called by nothing in the tree. The Studio's "Refresh catalog" button calls `tts_catalog_sync.run_sync` — **Azure only** |
| **MF-051** | **P1** | **Deletion is not automatable when the thing deleted is a *statement about the world*.** `git revert` restores capabilities; it does not restore diagnostics, because the restored text lands where nobody knows to read it. **The allowlist** — every item flagged by knip/vulture/`F401`/any "delete unused exports" codemod, every one of which must survive: `rls.py:327 weak_policies` (1 ref, its own def — *"a table where a row with no parent is visible to every tenant"*; delete it and RLS reports green while those tables stay cross-tenant visible), `rls.py:294 orphan_rows`, `rls.py:342 role_bypasses_rls`, `authz.py:879 assert_registry_covers` (1 test — the totality proof), `authz.py:652 invalidate_permission_cache` (**not a test seam** — it is the already-written fix for MF-008), `voice/node_contracts.py`, `outbound.py:178 DialRefused`, `capture.py:1635 record_offer_suppressed` |
| MF-052 | P2 | **`record_offer_suppressed` is dead and the finding is bigger than "clutter."** Its event kind is *registered* in `COMMERCIAL_KINDS` and asserted by a test — so **no code path has ever emitted an `offer_suppressed` activity event**, while `live_qa/scorecard.py:218-230` derives its own `offer_suppressed` from `offer_decisions.suppression_reason`. **That duplication is in no report.** Deleting the function leaves an orphaned kind in a locked vocabulary |

**Do not delete from a scanner.** Six dynamic-reference hatches were enumerated exhaustively and **all but one have enumerable targets**: `getattr(obj, var)` is 9 in non-test code and all attribute-level; `globals()[…]` exactly once; **no module-level dispatch by string**; frontend `import.meta.glob` = 0; all 43 route files present in `routeTree.gen.ts`. That makes module-level static analysis sound in this backend — an unusual and valuable property. **The exception is MF-053.**

**MF-053 · P1 · `factory._import_class` is the one dynamic-dispatch site whose targets are not enumerable from source.** `agent_core/providers/factory.py:110-118` imports whatever `provider_models.service_class` holds, with **no allowlist**, and `persist.sync_seed` is an **upsert, never a truncate** (documented, because `provider_model_id` is `ON DELETE RESTRICT`). A model removed from `registry.py` keeps its row forever, stays enabled, stays bindable. **Deleting such a class is a production outage, not a test failure.** Settle with `SELECT DISTINCT service_class, enabled FROM provider_models` before touching `agent_core/providers/`.

**MF-054 · P1 · Deleting a `bots` row silently rewrites nine tables.** Thirteen FKs to `bots(id)` in three groups: `prompt_versions.bot_id` has **no `ON DELETE`** (blocks, loud); four cascade (loud enough); and **nine are `ON DELETE SET NULL`** — `qa_scorecards`, `coaching_actions`, `activity_events`, `interaction_handoffs`, `interaction_disclosures`, `supervisor_actions`, `eval_reports`, `campaign_runs`, and `call_attempts`, the last described at `sql/21_outbound.sql:37` as *"unredactable borrower PII whose retention nobody has argued about."* **The CHECK constraints, not the foreign keys, are what make this survivable, and they cover four of thirteen.** `scripts/prune_probe_cards.py` reaches the right outcome for the wrong reason — its guard checks one table of thirteen. Do not generalise it.

**MF-055 · P1 · Never delete an orphan `audit_log` row.** `entity_id` has no FK, so deleting a `bots` row leaves orphans naming a bot that no longer exists. **That is correct and must be left alone.** Deleting them to tidy up breaks the hash chain from that entry forward, permanently, with no repair — the chain *is* the evidence, and a rebuilt chain is evidence of nothing. `scripts/prune_probe_cards.py:24-30` is the **only** place in the tree that states this rule, which makes that docstring itself a protected artifact.

---

## Bug Findings

| ID | Sev | Finding | Location |
|---|---|---|---|
| **MF-041** | **P0** | **Two parallel `apply_goodwill` calls can post two waivers for one decision.** `_run` `SELECT`s with **no `FOR UPDATE`**; `mark_enacted` runs `UPDATE … WHERE enacted IS FALSE` and **does not inspect rowcount**, so a writer that lost the race still returns `ok=True` with its own `ledgerId`; and if `mark_enacted` raises, the exception is swallowed, `enacted` stays false, and a retry posts again. Amplified by Pipecat `run_in_parallel=True` — **verified absent from all of `backend/`, so the default stands** | `authority/enact.py:40-88`, `decisions.py:105-134` |
| **MF-041b** | P0 | **The Mission authority ceiling is spoken and not applied.** `voice/tools.py:1477-1490` narrows `payload` and `state.authority_cap` only; the `authority_decisions` row is unchanged; `apply_goodwill` with `amount=None` posts the **un-narrowed matrix figure**. A pre-due courtesy Mission can concede what a broken-promise chase would — the thing the handler's own comment exists to stop | `voice/tools.py:1469-1528` |
| **MF-033** | **P0** | **An insights API failure is rendered as a successful Offer the operator can capture.** `fetchCustomerInsights` catches **every** error and returns `deriveCustomerInsights(customer)`, which invents a Top-up Loan of ₹1,50,000 with a talk track. React Query therefore never sets `isError`. `OverviewTab` offers **Capture** against it and writes a real lead. The same derivation runs during *pending* | `api/customers.ts:45-58`, `lib/customerInsights.ts:196-218`, `customers.$customerId.lazy.tsx:108-114` |
| MF-040 | P1 | **Handoff tells the borrower a specialist will continue; the same Mouth keeps the grant.** The handler writes a CRM row, may activate a mesh role, speaks *"a specialist will continue"* — and returns **no node transition**. The Pipecat session keeps the originating Mouth's tool map, captured at connect. The receiving Agent Card is never loaded | `voice/tools.py:2768-2803`, `domain.py:1006-1077` |
| MF-056 | P1 | **WhatsApp Live QA treats "has a `customer_id`" as identity verified**, so `check_identity_before_dues` never fires on the text channel. Inbound threads bind the customer from the sender number with no ceremony | `bot_runtime.py:1282` → `live_qa/checks.py:219-232` |
| MF-057 | P1 | **`evaluate_authority` hardcodes `identity_verified=True` on WhatsApp**, removing one of the matrix's vetoes. Voice guards with `_require_customer()` first; the copy did not take the guard. Document ingest in the *same file* uses the stricter check | `bot_tools.py:321-328` |
| MF-058 | P1 | **Promise date parsing drops the timezone**, then stores a bare date into `timestamptz`. `due_today` and pay-link expiry flip at UTC midnight, not IST midnight | `agent_core/tools/domain.py:122-151`, `db.py:5164` |
| MF-059 | P2 | Dispute waiver idempotency is `WHERE description LIKE '%{dispute_id}%'` — collision skips a real waiver, a description-format change double-posts | `authority/enact.py:91-110` |
| MF-060 | P2 | `apply_goodwill` compares rupees as **float with a 0.009 slop** against `numeric(14,2)` columns, while `voice/session.py:11-17` keeps `Decimal` | `authority/enact.py:58-66` |
| MF-061 | P2 | **PTP row commits even when fulfilment fails.** The Mouth reports `ok=True` and confirms amount and date aloud; the borrower has no pay link, and cadence may treat `ptp_captured` as terminal | `db.py:5170-5181` |
| MF-062 | P1 | **`_activity` hardcodes `actor_kind` to the literal `'human'`** — verified. There is no `actor_kind='system'` path anywhere. An unattended sweep, a bot's own WhatsApp reply and a payment callback are each recorded as *a named person* performing them, and `visibility.params()` resolves those paths to scope `ALL` | `db.py:642-659` |
| MF-063 | P1 | **Ending a Live call mid-connect orphans the peer connection and leaves the microphone open.** `startGenRef` is incremented in exactly one place — inside `start()` — so `end()`, the `!enabled` effect and unmount all null the ref without bumping the generation. The UI reads `ended`, flips back to `live`, and the recording indicator stays lit until reload | `useSandboxLiveCall.ts:174-201, 264, 511-548` |

---

## Architecture Findings

| ID | Sev | Finding |
|---|---|---|
| **MF-009** | **P1** | **`db.py` is the boundary that does not exist and must be cut whole.** 18,087 lines, 440 functions, fan-in 101 (38% of the backend), fan-out 46. It imports the Locked Engines, `contact_policy`, the channel adapters, the card compiler and the job queue **back**. Removing its outgoing **or** incoming edges collapses the coupling SCC 107 → 17; twelve surgical single-edge removals reach only 36; removing all seven plausible "shared kernel" candidates *at once* moves it 107 → 100. **Partial cuts buy nothing.** And one *eager* edge decides whether the carve works: `db.py:24 → schemas → flow_graph → agent_core.tools → …kb → db` — removing it alongside the lazy callbacks is what takes 107 → 17 |
| MF-009b | P1 | **The real persistence API is four private helpers, and that is what blocks the split.** `db._tenant()` 80 external sites, `_rows()` 57, `_one()` 54, `_jsonb()` 22 — 202 of 239 production reach-throughs. **Not one importer uses `from db import X`**; all 211 use `import db`, which is why an attribute shim works. Two hazards no prior report named: `_as_dict` is defined at `:12703` inside *Prompt Studio reads* with internal fan-in 18, and `_jsonb` at `:14068` inside *Prompt Studio writes* with 12 external consumers — **both must move down before their sections are peeled** |
| MF-009c | P2 | **`db.py` contains its own carve map.** Fifteen named banner sections; ~405 of ~440 internal calls point **down** into the head helpers and only ~35 run *between* the upper sections. The sections are **screen-shaped, not domain-shaped** — which is exactly why a DAO layer is the wrong answer and the carve is by section |
| MF-010 | P2 | **`main.py`: 314 routes, zero `APIRouter`, fan-in 0.** Splitting it reduces no other module's coupling and breaks no cycle. It is cheap, safe, and **cosmetic** — and it is the item to drop if anything must be dropped |
| MF-064 | P1 | **`work_runtime` is a port with 3 of 7 operations, so callers reach around it.** `agent_core/clerk.py:17,18` imports the port and the concrete adapter on **consecutive lines**; `treatment/enact.py:702` and `sweep.py:243` insert into `work_runtime_jobs` **directly**. There is no `Protocol` — the contract is duck-typed, and the two adapters agree today only because `adapter_temporal` is three `raise` statements. **The day `TEMPORAL_ENABLED` flips: `start_workflow` routes to Temporal while the drain loop raises and two treatment paths keep writing a Postgres table nobody drains** |
| MF-065 | P2 | **Thirty-one tables are written by more than one module, including the regulated ones** — `ledger_entries` (3 writers), `consent_records` (2), `violations` (3), `call_attempts` (4), `followups` (4), `messages` (5). **Two modules writing one table are coupled with no import edge at all**, so the import graph is blind to it |
| MF-066 | P2 | **The decision layer imports the channel adapters.** `treatment/enact.py:296 → twilio_sms`; `promise_fulfillment.py:23 → webhooks_dispatch` (eager); `payments.py:20 → webhooks_dispatch` (eager). Adding a channel means editing the enactment engine, and the engine cannot be exercised without Twilio configuration |
| MF-067 | P2 | **`agent_core/__init__.py` eagerly re-exports `deployment`, which eagerly imports `db`.** Importing the barrel to call `estimate_sentiment` opens a Postgres engine — and is how `voice/persist.py` joins the WhatsApp worker knot |

**What must not be regressed.** `main.py` has **zero importers**. `fastapi`/`starlette` in 3 of 267 modules. `HTTPException` in exactly one file. `schemas.py` has two importers. `create_engine` appears **twice in the tree**, and `db.py:138-183` passes the tenant as a **libpq startup parameter** so a pool ROLLBACK cannot un-set it — that is the strongest seam in the backend and the entire safety argument for enabling RLS. Half the domain (51 of 102 modules, 12,414 lines) is already pure. `contact_policy._veto` is the best-shaped regulated function in the repo.

---

## Security Findings

Classic injection was hunted and is **clean**: no `shell=True`, `os.system`, `pickle`, `yaml.load`, `eval`, `exec`, or `verify=False` in backend application code; all f-string SQL interpolates fixed column maps or allowlisted identifiers with bound values; both `dangerouslySetInnerHTML` sites take compile-time constants. The findings are elsewhere.

| ID | Sev | Finding |
|---|---|---|
| **MF-007** | P0 | Auth + authz + object visibility fail open together — see Critical |
| **MF-008** | P0 | Total revocation restores defaults — see Critical |
| **MF-001** | P0 | Cardless Tool Grant fail-open. **The real injection surface here is prompt injection**: a borrower's speech drives a tool loop whose catalog includes `create_promise_to_pay`, `flag_dispute`, `apply_goodwill`, `set_contact_preference` |
| MF-068 | P0 | **The voice Media Streams WebSocket upgrades without the proxy secret.** `_voice_ws_upgrade_authorized` ends `return True` when not prod — with `VOICE_WS_PROXY_SECRET` **set and unused**. `/ws` is auth-exempt. Anyone who can open `wss://{public-host}/ws` joins the media-stream proxy: live call audio, and injection into the voice runner |
| MF-069 | P1 | **`POST /a2a` skips both auth layers and authenticates on request headers.** An early return at `main.py:278-279` *and* an entry in `PUBLIC_ROUTES`. Identity is `X-SSL-Client-Verify`/`X-SSL-Client-DN`, and **no ingress config in this repository strips them**. Correct only if a proxy terminates mTLS — a security boundary that lives in infrastructure nobody can see from the repo is not reviewable |
| MF-070 | P1 | **Twilio callbacks accept a missing signature outside prod** — with the token set. `POST /twilio/voice/call-status` drives the `call_attempts` state machine, so forged answer rates and durations flow into treatment inputs |
| **MF-018** | **P1** | **RLS is complete, correct, self-protecting, and switched off.** `rls.py` derives ~90 policies from the FK graph, applies `FORCE ROW LEVEL SECURITY`, verifies row counts in-transaction, and **refuses to install for a `BYPASSRLS` role**. The application connects as exactly that role — `db.py:39` hardcodes it as the default DSN, so **no configuration path in this repository connects as a non-bypassing role.** Tenant isolation therefore rests on ~290 hand-written predicates across 44 modules, and read scoping (`visibility.py`) is **fail-open by construction** — a query that forgets the `/*VISIBILITY*/` marker keeps it as an inert SQL comment — reaching **14 of ~491 query sites**, all of them lists |
| MF-071 | P1 | **Conversations, exports and several by-id reads ignore visibility and often tenant.** `_conversation_base_rows` — the **primary Inbox read** — filters on `cv.id` and `updated_after` only. `GET /interactions/{id}/export` is existence-only, and it is the richest PII bundle in the product. Writes stop at `_assert_tenant_owns` (tenant granularity), which is **documented rather than accidental** |
| MF-072 | P1 | **Outbound SSRF: the guard resolves an address, discards it, and connects by name.** `resolve_public_host` is good security code with 13 tests — and both call sites throw the answer away, so `httpx` re-resolves. Classic rebinding TOCTOU. **The specification for the fix is in the same repository**: `ops_screens.py:73-77` states *"the delivery worker must re-check the resolved address immediately before connecting and pin it for the request."* The worker does the re-check; it does not do the pin |
| MF-073 | P1 | **No dependency-vulnerability gate exists on any path** — see MF-023 |
| MF-074 | P1 | **The sandbox tool loop writes the live ledger.** Pinning a real `customerId` with tools enabled runs the same handlers as production. Rehearsal that creates a real PTP on a borrower |
| MF-075 | P2 | **Log redaction covers borrower PII in `message` only** — `extra` fields and full tracebacks are unredacted, and `PII_DETECTORS` carries **no credential patterns**. Compounded by MF-017: the redactor never runs at all today |
| MF-076 | P2 | 19 live-shaped provider credentials in one `.env` **mounted whole into five services**; the compose file names its own problem at `:8-11`. **Repository exposure: none** — verified across 39 commits, all branches, by path and by content scan. No rotation is required on git grounds |
| MF-077 | P2 | `/ready` echoes raw MinIO exception text to an unauthenticated caller — **while `db.readiness()` fifteen lines away deliberately refuses to**, with the reasoning written down |
| MF-078 | P2 | `VITE_API_KEY` would compile the shared backend key into the public browser bundle. Currently unset; the severity is structural — fixing MF-007 without giving the SPA a session mechanism makes reaching for it the obvious next move |
| MF-079 | P2 | Permission cache is not busted on grant write; WhatsApp verify GET uses `==` (timing oracle); `GET /pay/{token}` does not enforce `expires_at`; no HTTP security headers in the API or SSR |
| MF-080 | P2 | **Four independent definitions of "privileged"**, two of which ignore permissions entirely. `_actor_can_view_raw_pii` and `visibility._UNSCOPED_ROLES` key on **role name**, so a role named `dpo` stripped of every grant still reads raw PII and still resolves to scope `ALL` — **permission revocation cannot remove raw-PII access** |

---

## Performance Findings

Nothing here is Critical. All are cost, and the ranking is deliberate.

| ID | Sev | Finding |
|---|---|---|
| **MF-032** | P1 | **The Inbox poll is the system's hottest path.** `useConversations` refetches every **4 s** (1.5 s while a Mouth is typing). `list_conversations` has **no `clamp_list_limit`**, loads **all messages** for returned threads with no watermark, then runs **4 context SELECTs + a full `contact_policy.evaluate()` per thread**. Messages are already batched; the sidebar was not given the same treatment. `conversations` has no `tenant_id` and no index on `updated_at`, and the sort is on a `COALESCE` expression |
| MF-025 | P0 | **Carrier I/O inside open transactions** — the same finding as MF-004's K6, ranked here for its resource cost: the bounce webhook is `async def` and calls Twilio on the event loop inside `FOR UPDATE` on a **single-worker** uvicorn; PTP reminders hold a `SKIP LOCKED` row across a 10 s Twilio timeout while `_record_sent` checks out a **second** pooled connection. `statement_timeout` cannot fire — no statement is executing |
| MF-026 | P1 | **One poison row starves every queue below it.** `bot_worker.process_one_any` guards four of twelve stages; five unguarded ones run *above* the guarded ones. A persistently-raising `whatsapp_outbound` aborts the tick before `call_closer` is reached. The loop logs `logger.exception("process_one crashed — backing off")` — **no queue name, no row id** — sleeps 1.5 s, and repeats forever |
| MF-081 | P1 | **Customer 360 pays for the engine twice and throws the result away.** `/insights` calls `get_customer` **again**, then `_treatment_snapshot` runs a full `recommend_treatment` (~50–60 round-trips) whose `decisions.record` INSERT is **rolled back**, because the caller used `engine.connect()` with no `commit()`. The docstring says the write is deliberate. The payload can still carry a `decisionId` for a row that never committed. Ledger has no `LIMIT` |
| MF-082 | P1 | **Idle `bot_worker` issues ~8–16 statements every 1.5 s with nothing to do** — on the order of 0.7–1.0 M statements/day — because `process_one_any` evaluates every branch with no upfront work check |
| MF-083 | P2 | `settle_promises` `FOR UPDATE`s **every** due promise with no `LIMIT` and **no `SKIP LOCKED`**, then runs `recommend_treatment` per row inside the lock |
| MF-084 | P2 | Missing access paths: no expression index on digit-stripped `customers.phone_primary` (**the hot inbound-identity path** — `accounts` already grew the equivalent in Alembic 0040); no `followups (status, due_at)` or `(lead_id)`; no `ledger_entries (account_id, type, posted_at)`; no `routing_rule_executions (rule_id)` |
| MF-085 | P2 | `AppShell` remounts on every navigation (30+ mount sites, not a layout route); zero `React.memo`; virtualization used only for the TTS catalog |

---

## Reliability Findings

| ID | Sev | Finding |
|---|---|---|
| **MF-027** | P1 | **The live Mouth bypasses every breaker, the gateway, the spend cap and the meter.** Voice LLM, STT and TTS go through Pipecat and `voice/llm_pool.py`, which share neither the `azure_openai` breaker nor the Speech REST retry loop. A region outage is 3 SDK retries × 30 s **on every concurrent call, with no shed**. Bind-time failover is real; **runtime failover does not exist** — a mid-call Fish `ErrorFrame` is silence, and there is no `ErrorFrame` handler anywhere in `backend/` |
| **MF-028** | P1 | **The LLM spend cap reroutes around itself when it engages.** `maybe_chat` has **one caller**; a cap breach raises `RuntimeError`, and that caller catches **every** exception and falls through to uncapped direct-Azure. Two of four declared profiles are unreachable, so `LLM_GATEWAY_CAP_VOICE_INR` is a documented key no code path can consult. `_spend_inr` is a per-process dict, so the ceiling is a multiple of the number. **And the meter labels the fallback as gateway spend**, because the condition is whether the *flag* is on, not whether the gateway *served* |
| MF-086 | P1 | **Hung TCP has no deadline on MinIO, Redis, or Postgres connect**, and uvicorn has no request timeout. A hung syscall does not update `locked_at`, so reclaim waits out its window while the thread is still inside the call — the difference between "retry after 180 s" and "worker permanently down one slot" |
| MF-087 | P1 | **The circuit breaker covers 4 of ~21 outbound dependencies**, and none has a latency or error metric. Absent from both Twilio clients, the voice LLM pool, the LLM gateway, Fish/Cartesia/Deepgram/ElevenLabs/OpenRouter, Key Vault, MCP connectors, Redis and outbound tenant webhooks. `CircuitOpenError` subclasses `RuntimeError`, so route-level `except RuntimeError` intercepts it and returns **502** — the breaker's "shed load" signal reads "we are broken" |
| MF-088 | P1 | `llm_gateway/client.py:112-131` retries **3× with no sleep at all** — `time.sleep` is never called in the file — including on permanent 400/401 |
| MF-089 | P2 | Shutdown waits 10 s for a teardown budgeted 20 s, then disposes the engine underneath it. `await runner.cancel()` has **no timeout**, so a hung STT/TTS close blocks the lifespan `finally` forever |
| MF-090 | P2 | Voice admits **25 concurrent calls against a 5-connection pool**, with the constant's own comment citing the 3+2 budget |
| MF-091 | P2 | `'working'` is not a claim in `work_runtime` — re-selectable with no `locked_at`, no lease, no attempt counter, no dead-letter, on **financial instructions** |
| MF-092 | P2 | Transaction poisoning: a "non-fatal" `try/except` sharing a transaction with the record it protects. Five sites; `kb_retrieve._try_set_local` already uses the `begin_nested()` idiom that fixes it |

**Do not re-wrap what already works.** `azure_speech.py:373-457` is the retry the adversarial pass could not fault — bounded attempts, `Retry-After` honoured with a cap, **full jitter**, status-based classification, and `_SpeechRetryable` converting a retryable *response* into an *exception* so the breaker can count it. `whatsapp.py` + `whatsapp_outbound.py` is the only adapter that reasons about double-send. `circuit_breaker.py` closes two real races with a probe-generation stamp. Four job queues get claim/lease/reclaim/dead-letter genuinely right, and `kb_index_jobs` computes its reclaim cutoff **database-side** so a skewed worker clock cannot steal a healthy job.

---

## Testing Findings

**2,431 test functions is a large suite, and it is not evidence about risk.** The shape is specific: **where a rule is expressed as *data* — a constant, a set, a registry — this codebase tests it thoroughly and inventively. Where a rule is expressed as *a decision the engine makes about a borrower*, the test usually stops at the data.**

| ID | Sev | Finding |
|---|---|---|
| **MF-020** | P0 | **The suite is red, for a reason unrelated to what it tests, and a second bomb is on a timer.** `test_contact_policy.py:287` passes `promised_date="2026-09-01"` against a wall-clock past-date guard — **failing since 2026-09-02**, taking a daily-cap enforcement test with it. `test_voice_write_idempotency.py:36` is `PROMISE_DATE = "2026-09-14"` — **508 lines and 8 tests start failing on 2026-09-15**, on the journey report 22 calls *"the best in the repo."* Both verified. **A red baseline makes "did my refactor break it?" unanswerable, and teaches a team to skim past red** |
| **MF-021** | P0 | **The `db_tx` fixture makes concurrency structurally impossible to test.** Every `engine.begin()` becomes a SAVEPOINT on **one shared connection**; two blocks are always mutually visible; advisory locks are held for the whole test. Production has ~16 `SKIP LOCKED` claim paths and **one** has a contention test. The idempotency advisory lock — added *because* two requests once created *"two promises for one idempotent POST"* — **could be deleted today with all 26 idempotency assertions still green** |
| **MF-022** | P1 | **Seven of twelve statutory refusal reasons are never asserted as engine behaviour**, including `customer_dnd` — the check that stops the platform calling someone who told the regulator not to be called. They appear only as *members of a policy set*. `contact_policy.py:505` is reachable by no test; delete the branch and the suite stays green. **And the gate's own suite disarms the rules it is testing**: `_prep` nulls `dnd`, `dnd_registry`, `allowed_days` and `allowed_hours` for every DB test in the file, and sets weekly = 8 against daily = 3 so the weekly cap can never fire |
| MF-093 | P1 | **Two suites each defer the contact gate to the other.** `test_cadence_pause_and_strand.py:50-55` monkeypatches `admit` to always allow **for the whole 407-line file** — correct in isolation — and the gate's "own suite" then disables the rules the ladder would hit. **Fixing MF-022 in one file will not close it** |
| MF-094 | P1 | **No test ever calls `db.opt_out`** — the DPDP opt-out writer. Every opted-out borrower is fabricated by raw SQL. **Capture and enforcement are never exercised in the same process** |
| MF-095 | P1 | **`campaigns.process_one` — the dialer that runs the eligibility gate — is never executed.** Its only appearance is an `inspect.getsource` substring match. A logic inversion passes; a reformat fails |
| MF-096 | P1 | **Four compliance detectors can never fire, and the test that "covers" them counts a Python dict.** `assert len(DETECTORS) == 16` — sixteen registered, twelve seeded, four permanently skipped. The four that judge a *human* agent's handoff call — recording disclosure, mini-Miranda, payment terms, identity verification — are dead, and the Compliance screen reports them clean, permanently |
| MF-097 | P1 | **Negative authorization is tested on 5 of 314 routes.** 16 files construct a `TestClient`. Untested and high-consequence: `PATCH /roles/{id}/permissions`, `POST /consent/{id}/opt-out`, `POST /conversations/{id}/messages`, the outbound campaign routes, the three PII-redaction PATCH routes |
| MF-098 | P1 | **Not one webhook route is tested at the HTTP layer.** Deleting `if not verify…: raise 401` at three sites fails zero tests |
| MF-099 | P1 | **Both halves of the schema-drift defence are inert.** `test_schema_parity.py` compares `sql/*.sql` **against itself** in CI, because CI builds `DATABASE_URL` from `sql/` and then *stamps* — migrations are never executed. The inline check regex-scrapes `op.create_table`/`op.add_column` only, covering **38% of table creations and 57% of column additions**; 41 raw `CREATE TABLE` and 54 raw `ALTER TABLE … ADD COLUMN` are invisible |
| MF-100 | P1 | **No frontend component is ever rendered.** `environment: "node"`, no jsdom, no Testing Library, no MSW: **11 test files for 474 modules**, zero render/hook/snapshot tests. **Frontend refactoring here is markedly less protected than backend refactoring** — the opposite of the usual assumption |
| MF-101 | P1 | **A 345-line untested port of the Python money-authority matrix runs in the browser**, with the rupee thresholds in the bundle. The sibling port of the RBI contact veto **has 167 lines of boundary tests**. The team knows the pattern and applied it to one of the two |
| MF-102 | P2 | **53 "tests" assert against source text** (`inspect.getsource`, `ast.parse`, `readFileSync`) — they fail on a reformat and pass on a behaviour break. The worst concentration is 11 in `test_voice_session_teardown.py`, sitting on the file most in need of splitting. **Refactoring the voice runtime is actively punished today** |
| MF-103 | P2 | 436 tests (17.9%) can vanish at runtime; **nothing asserts the seed has content.** 56 of them sit in compliance- and tenancy-named files |
| MF-104 | P2 | Cross-tenant isolation has **no HTTP-level test**; real RLS enforcement exists but probes 2 tables of ~112 and is gated behind a module-level alias invisible to a grep for `@pytest.mark.skipif` |
| MF-105 | P2 | **No coverage measurement exists anywhere.** Every "no test reaches this line" claim in 23,850 lines of forensics — including in this document — is call-graph-derived, not measured |

**What CI genuinely enforces**, better than parts of the corpus claimed: `ruff check .`; full `pytest -q` against real Postgres **with voice dependencies installed**, so the 26 pipecat-importing test files actually run; bidirectional schema-drift checking; `tsc --noEmit`; `vitest run`; and `npm run lint` **including both design-token scanners**. `MagicMock` appears **once in 2,431 tests** — near-zero over-mocking, seams drawn at network and clock edges.

---

## Data / Database Findings

| ID | Sev | Finding |
|---|---|---|
| MF-106 | P0 | **`UNKNOWN-CALLER` is a global primary key.** `voice/persist.py:28-54` upserts a sentinel customer with `ON CONFLICT (id) DO NOTHING`, which does not retarget `tenant_id`. The first tenant to connect owns the row; later tenants reuse it, and interactions then store one tenant's id against another tenant's customer. Silent today because one tenant is seeded |
| **MF-018** | P1 | RLS off; child tables without `tenant_id`; no CHECK that child.tenant = parent.tenant — see Security |
| MF-107 | P1 | **Uniqueness the writers assume and the database does not enforce**: one conversation per customer+channel (concurrent first messages split a thread), one conversation per interaction, one active PTP per account, `emi_installments (account_id, installment_index)`, one `agent_presence` row per user |
| MF-108 | P1 | **`accounts.status`, `payment_plans.status`, `messages.delivery_status`, `interactions.disposition`, `qa_scorecards.status`, `export_jobs.status`, `invoices.status` have no CHECK** — while partial indexes and the treatment sweep predicate depend on the literal `'active'`. Garbage in, missed delinquents |
| MF-109 | P1 | **Three migrations' downgrades destroy regulatory evidence**, and **no downgrade in this repository has ever been executed by CI**: `0098` `DELETE FROM channel_consents WHERE purpose='promotional'` (**every promotional DPDP consent basis ever captured** — restoring the schema does not restore the permission); `0066` drops `contact_events` + `contact_day_counters` (the RBI frequency-cap evidence); `0094` drops `call_attempts` + `call_outcomes` (the proof a call was **not** placed). 93 real downgrades are untested code that runs only in an emergency |
| MF-110 | P2 | **Migrations mutate real rows unconditionally** — `0064` role grants, `0073` `DELETE FROM prompt_versions`, **`0084` and `0101` rewrite persona/prompt text (what the agent says to borrowers)**, `0103` eval fixtures. **`0101`'s downgrade is `pass`** — the prior persona text is gone |
| **MF-034** | P1 | **`sql/23_outbound_evals.sql` is referenced by `alembic/…0096:7` and does not exist** — verified: `sql/` jumps from `22_campaigns.sql` to `90_deferred_fks.sql`. `fixtures.py:207-211` states the consequence: on CI and on any pilot provisioned from `sql/`, the suite is absent and `OUTBOUND_EVAL_GATE_ENABLED=true` **refuses every outbound publish**. And `.env:405` sets that flag true while `.env.example:606` ships false. **A fresh install cannot publish outbound at all** |
| MF-111 | P2 | `backend/README.md:31` documents `alembic upgrade head` as the first-run command. **It cannot work on a fresh volume**: baseline `0001` is `def upgrade(): pass`, so 0002+ run against missing tables. CI already documents the correct order |
| MF-112 | P2 | `ledger_entries` has **no `tenant_id`, no actor column, and no reference to the authority decision that authorised a waiver.** It is the money-movement record: it cannot be RLS-scoped and cannot be joined to *who* decided |
| MF-113 | P2 | `ledger_entries.balance` is a documented running total that **every writer leaves NULL**, beside `accounts.outstanding` which they do maintain. A future reader summing `balance` disagrees with outstanding with no runtime bug |
| **MF-038** | P1 | **The database enforces vocabularies and never transitions.** No transition-guard triggers exist. **Only `leads.stage` has a real transition map.** `campaign_runs.set_status` accepts ANY→ANY (`cancelled → running`, `finished → running`); `mark_cancelled` has no source guard; A2A `signal_task` accepts `completed → submitted` **and any unrecognised signal cancels the task**; `work_runtime finish/claim` accept `cancelled → completed`. Two spellings for one state (`canceled` vs `cancelled`; `input-required` vs `input_required`) make cross-table analytics impossible. Dead states are declared and never written in six places |
| MF-114 | P2 | `supervisor_actions.supervisor_user_id` is `ON DELETE CASCADE` — **deleting a supervisor removes the audit of every barge and whisper they performed** |

**What is strong and should be copied:** partial unique indexes for every "one current X" (active deployment, published prompt, open bounce per EMI, open pay-link per promise, live hold, champion model); idempotency keyed `(tenant_id, endpoint, key)` **after a documented cross-tenant leak**; handler XOR CHECKs; `work_items` as a **VIEW** so domain tables stay authoritative; `contact_events` + `contact_day_counters` as the Gate's ledger with `used_this_week` explicitly labelled a cache; money as `numeric(14,2)` throughout with **no float anywhere in the money path**; 102 revisions, single linear head, **every one defining `downgrade`**.

---

## AI / Voice Integration Findings

| ID | Sev | Finding |
|---|---|---|
| **MF-115** | P1 | **LLM binding is a UI contract with no runtime.** `Kind` includes `"llm"`, `BindingsTab` offers slot `llm`, `GET /providers/models?kind=llm` is valid — and the seed defines **zero** `kind="llm"` models while `voice/bot.py:679` constructs Azure from env. `provider_bind.bind` is never called with `"llm"`. **This is the exact failure `provider_bind.py:1-8` was written to end for STT/TTS**: *"an operator could pick Cartesia in the Agent Studio, hear the preview, publish it, and every real call still ran Azure."* |
| MF-116 | P1 | **Four Mouth wirings for one Deployment.** `load_active_bundle`'s docstring says sandbox/WhatsApp/voice cannot drift. They drift on the **argument**: WhatsApp passes `BOT_ENVIRONMENT` (default **production**), sandbox hardcodes `"sandbox"`, voice hardcodes `"production"`, and **the insurance mesh worker loads no bundle at all** — it builds Azure LLM with a hardcoded HDFC specialist prompt and `default_tuning()`. Handoff onto that worker leaves the card's grant *and* the card's prompt behind |
| MF-117 | P1 | **WhatsApp ignores `AgentTuning.llm`** — `temperature=0.2`, `max_completion_tokens=500` hardcoded — while sandbox and voice honour it. Publishing a preset changes the phone and the sandbox, not WhatsApp. **A Mouth published once does not speak with one sampling policy**: temperature 0.2 / 0.2 / 0.4 and max tokens 500 / 320 / 220 / 800 across four channels |
| MF-118 | P2 | **`SpokenTextFilter` destroys Fish emotion tags on every provider.** It strips `[]` because Azure word-boundary events duplicated parentheticals — and Fish S2 steers delivery with `[happy]`/`[whispering]`. Azure-shaped content policy leaking into a provider that needs the brackets |
| MF-119 | P2 | **Provider provenance is written on every bind and read by nobody.** `session.extra["providers"]` has zero readers outside its own tests, is stamped at **bind time and never revised** — so a provider that builds fine and dies mid-call still reads `source:"binding"`, **false in exactly the case the field exists to catch** |
| MF-120 | P1 | **`tuning_apply.py:70` is `mapping.get(key, Language.EN_IN)`** — the exact fail-open `providers/factory.py:3-7` was written to close. An unmapped locale transcribes as English-India and **every downstream layer scores the nonsense as the borrower's words.** Its failure mode is fluent words rather than an error |
| **MF-035** | P1 | **Latent expiry is a recurring class with four live instances, and it has already fired twice.** `fish_tts.py` documents *"Free through 2026-08-31"*; `DEFAULT_MODEL = "s2.1-pro-free"` and `.env.example:574` still selects it — **verified, lapsed, never flipped.** Worse, the documented Fish→OpenRouter fallback is `fish-audio/s2.1-pro-free:free` — **the same expired promotion**, so the fallback cannot rescue the primary. Plus Cartesia `sonic-2` (already remediated), `policy_rule_sets.effective_to`, and the two test date bombs |
| MF-121 | P2 | Two TTS abstractions (Pipecat live vs HTTP preview) with the model id hardcoded in the preview path; two STT stacks; three copies of "is this a reasoning deployment?"; two "provider" screens with **incompatible identifier schemes** (`azure_openai` vs `azure`) |
| MF-122 | P2 | `voice/tools.build_tools` is a **2,605-line function** with 18 kwargs closing over ~20 nested handlers; `voice/bot.run_bot` is 2,026 lines with 2 parameters. Both are the two hottest live-call paths and the two least testable functions |

**What is genuinely right here:** one Deployment loader; one authored prompt store rendered through `prompt_render` so CRM tokens cannot land in the system role; a capability matrix whose `service_class` paths were read off installed Pipecat rather than guessed; session-sticky key rotation so free-tier failover does not seam a caller mid-turn; `OpenRouterTTSService` **raising on construct** rather than yielding silence; and the factory/binder split — fail-closed on *locale*, fail-open on *unbound tenant* — which is layered policy, not inconsistency.

---

## Configuration Findings

| ID | Sev | Finding |
|---|---|---|
| **MF-039** | P1 | **There is no settings object, and `APP_ENV` — the master switch — is read in 11 production modules in two logically opposite directions.** 198–396 env read sites over 149–270 distinct names across 78–94 files, depending on method. `env_utils` is a 75-line helper, not a config module: **there is no single place a refactor can move a config read to**, and with a lazy `load_env()` the *timing* of that read is load-bearing |
| MF-123 | P1 | **Five different answers to "am I live?", defaulting in opposite directions**: `APP_ENV` → dev, `BOT_ENVIRONMENT` → **production**, `BILLING_ENV` → **production** (deliberately, and tested), `TREATMENT_MODE` → shadow, `AUTHORITY_MODE` → shadow, plus `RECO_MODE` and `LIVE_QA_BARGE_MODE`. A laptop that turns `BOT_RUNTIME_ENABLED` on **loads the production prompt** |
| **MF-036** | P1 | **`policy_rule_sets` is seeded by nothing.** `INSERT INTO policy_rule_sets` appears in `scripts/seed_policy_rules.py:158` and a test; **the script is invoked from nowhere** — not CI, not `seed_demo.py`, not a migration, not `sql/`. So `policy_rules.resolve()` returns `EMPTY` on every real install and every regulated decision runs on hardcoded fallbacks — and one is not a fallback at all: `contact_policy.py:508-515` reads *"Absent one, only voice is bounded."* **With no published rule set, WhatsApp, SMS and email have no calling-hour bound whatsoever.** Worse, `effective_to` means a rule set that expires with no successor **silently reverts the whole platform to those fallbacks** |
| MF-124 | P1 | **`TREATMENT_MODE=live` has no operator kill switch.** The migration that introduced the DB-backed switch names `TREATMENT_MODE` among the env gates it was meant to replace. Only two keys were migrated. The one switch that authorises acting on real borrowers is still process-restart-only |
| MF-125 | P1 | **`.env.example` ships `SKILL_PLATFORM_KEY` set to the repo-published constant**, which defeats `sign.py`'s own production guard **even with `APP_ENV=production` correctly configured** — because the guard's env check sits *after* an early return on a non-empty value. `VAULT_MASTER_KEY` at `:290` is **commented out** and therefore does reach its guard. Two sibling secrets, one uncommented line of difference. **This is the only Family-B finding a correct `APP_ENV` does not fix** |
| MF-126 | P2 | **83 variables are read by code and documented in no env file**, including `ALLOW_UNHARDENED_PRODUCTION` (the one that waives the production hardening gate), `AUTHZ_ENFORCE`, `VISIBILITY_ENFORCE`, and `OUTBOUND_TEST_ANY_HOUR` (bypasses a statutory control). `platform_flags.py:4` states the rule — *"add it here and in `.env.example`"* — and it is broken 157 times |
| MF-127 | P2 | **Four incompatible boolean truth sets.** `MINIO_SECURE=on` **disables TLS**, because `"on"` is not in *that* site's tuple while it is in 20 of the 26 others. The *unset* path is the safe one — configuring the variable is more dangerous than leaving it alone. `VOICE_WS_VIA_API=` (blank) *enables* the proxy |
| MF-128 | P2 | `AZURE_SPEECH_REGION` unset resolves **four different ways**, one of which silently routes Indian borrowers' speech to `eastus2` — **while `ops_screens.py:1621` simultaneously displays `centralindia` to the operator.** The screen asserts a residency the runtime is not honouring |
| MF-129 | P2 | `Asia/Kolkata` is hardcoded in **nine modules** while `APP_TIMEZONE` exists and only `clock.py` honours it. **The setting moves the model's clock and not the compliance clock** — a knob that moves the appearance of a control without moving the control |
| MF-130 | P2 | `backend/.env.bak.reco` is a second, unrotatable copy of the credential set under a filename no scanner keys on, in the same directory. Correctly gitignored; the risk is rotation drift |
| MF-131 | P2 | No container hardening: **all four process types run as root**, no memory or CPU limit on any of eight services despite a carefully documented connection budget, and healthchecks on 4 of 8 — none on the four workers |
| **MF-017** | P1 | **Observability is built to a high standard and switched off.** `setup_logging()` **returns immediately unless `LOG_FORMAT=json`** — verified — and `LOG_FORMAT` appears **zero times** in a 638-line `.env.example`. In the `api` and `voice_insurance` containers nothing configures the root logger, so **every `logger.info` is discarded** and WARNING+ falls to `logging.lastResort` with no timestamp, level, or request id. **`pii_redact.redact_text` therefore never executes on log output at all**, because the only place it runs is inside the formatter that was never installed. `/metrics` is real, well-designed, and **scraped by nothing**. `telemetry.span()` is a permanent no-op with no SDK dependency. The team already found, measured and wrote down this exact bug — `log_bridge.py:8-14` names the call — and the fix is called in **one** place, guarded by `if __name__ == "__main__"` |
| MF-132 | P2 | **The correlation id is generated, sanitised, echoed, CORS-exposed, and written to no log** — its only consumer is the formatter that is off. Meanwhile the browser shows every user a `Reference:` id minted by `crypto.randomUUID()` at render time and **transmitted nowhere.** Both halves of a working scheme exist and have never been connected at either end |

---

## Canonicalization Opportunities

The owner is the module that **disposes** — the Locked Engine, the publish Gate, the ADR enforcement point, the fail-closed leaf with a pin test. Display, mocks and process-local adapters are consumers. A seed file that happens to be the TypeScript import hub is a **fixture**, not an owner.

| Concept | Canonical owner | Competing implementations | Verdict |
|---|---|---|---|
| **Tool Grant / Offer** | `agent_core/tools/grant.py` (ADR-0001) | `intersect.effective_tools` + `voice.tools.ALWAYS_ON` + compile G9 + 3 cardless fallbacks | **Adopt.** One verified divergence; wire in 6 steps (MF-001) |
| **Contact admission** | `contact_policy.admit` / `evaluate` | consent-seed `isContactableNow`, callbacks-seed `isWithinDndWindow`, `mockVeto`, `_inbox_contactable` fallback | **Adopt.** The two callback/consent copies run **on live data** and one of them **books the slot** |
| **Statutory calling hours** | `policy_rules.calling_window()` | 7 sites decide without it, incl. one re-implemented **in SQL** and one with its own unpinned literals | **Adopt.** Start with `detectors.py:297-298` — one file, numbers already match, removes the only unpinned restatement |
| **Preferred window default** | `contact_window.DEFAULT_WINDOW` (09:00–20:00) | 9 sites carry `10:00-19:00`, two of which are **not display** | **Adopt in three pieces** by risk: display / the live DND verdict / the writes |
| **Blocking consent set** | `contact_policy.BLOCKING_CONSENT` | 4 definitions under 3 names, 9 use sites | **Adopt.** Provable no-op; cycle-safe (`contact_policy` is a DAG leaf) |
| **Rupee formatting (Python)** | `money_inr.inr` | `_fmt_inr`, `_inr`, + 3 cross-module reach-throughs | **Adopt.** Regulated — it changes the SMS and the spoken sentence |
| **Rupee formatting (TS)** | `api/treatment.ts fmtInr` (already agrees on sign and null) | `customer360-seed fmtMoney` (re-exported by 3 more), `upsell-seed fmtMoney`, ~12 inline | **Adopt.** **Do not touch `billing-seed inrCompact`** — a deliberate documented mirror |
| **Account tail** | `agent_core.context.account_tail` | `db._account_tail`, `ops_screens` SQL, `voice/persist`, **`enact.py:237`** | **Adopt** — after `SELECT count(*) FROM accounts WHERE …` proves it is a no-op |
| **Payment webhook HMAC** | one `hmac_body(secret, raw, header)` | 2 byte-identical copies, 2 secret getters | **Extract.** Keep the two getters |
| **Environment name** | `env_utils.env_name()` / a new `is_prod()` | 11 re-derivations in two opposite directions | **Adopt at `main.py` first** — and **not** at `seed_postgres.py`, `payments.py` or `storage.py`, each of which re-derives on purpose (see CONFLICTS) |
| **Row helpers** | a new `db_core.py` | `db._rows/_one/_tenant/_jsonb/_actor_user_id` reached from 41 modules | **Extract.** The precondition for splitting `db.py` at all |
| **The outbound gate sequence** | a new `outbound.dial(...)` | 7 sites, **2 orderings**, one with no `suppress` | **Extract** — after the ordering is *decided*, not averaged |
| **Wire response shape** | `schemas.py` + `response_model` | 178 routes declare none; shapes hand-assembled in `db.py` | **Enforce**, the way `authz.ROUTE_PERMISSIONS` already is at 318/318 |
| **Frontend wire types** | `backend/schemas.py`, mirrored | 261 domain types exported from `src/data/*-seed.ts`; **229 unchecked casts, 0 runtime validations** | **Move types out, then parse at `apiGet`.** `zod` is already a dependency, used once |
| **Job retry policy** | one `mark_failed_or_retry` shape | 4 copies with different caps and vocabularies | **Parameterize.** The WhatsApp divergence is the **correct** part |
| **Failed-read rendering** | `QueryState` | ~110 sites doing `data ?? []`; `RecordsTable` **has no `isError` prop at all** | **Fix the table first** — the abstraction is the reason the fix does not generalise |
| **Form accessibility** | `ui/form.tsx` — **but it is dead code** (MF-031b) | 6 cloned `Field` helpers; 295 controls with no accessible name | **Delete it and build the pattern from `useConfirm`**, which is adopted correctly at 7 of 7 call sites |

**Do not canonicalize across.** Four meanings of **Offer**. Three of **Handoff**. Two of **Gate**. **Cadence** vs job retry vs HTTP retry vs breaker. `contact_window` 09–20 vs RBI 08–19. Staff `authz` vs Tool Grant. `platform_flags` vs `platform_switches`. `env_loader.load_env` vs `db._read_env_file`. Treatment labels vs closer Outcome codes. Two circuit breakers (in-process vs DB-backed, per-tenant, survives restart).

---

## Conflicts and False Positives

Fifteen conflicts between reports were adjudicated against source. Full evidence and resolutions are in **[CONFLICTS-AND-FALSE-POSITIVES.md](./CONFLICTS-AND-FALSE-POSITIVES.md)**. The four that change what a cleanup PR may do:

| # | Conflict | Resolution |
|---|---|---|
| 1 | `07-dead-code.md` classifies `CAMPAIGN_RUNTIME_ENABLED` as **B — highly likely dead**. `31-runtime-wiring.md:157` and `34` list it as live | **Report 07 is WRONG — verified.** Read at `cadence.py:67-69` and `campaigns.py:61-63`, through a function-local import inside a differently-named `enabled()` wrapper. Delete it and the platform begins **auto-redialling borrowers on a timer**. **The correction must be written into report 07**, because that is the document a cleanup PR will cite |
| 2 | `06` DUP-01 and `38` C3 present the flow-control literal gap as unmanaged drift; `40` retracts it | **The roadmap is right — not drift.** `flow_graph._FLOW_CONTROL_TOOLS` is a `dict[str,str]` of editor descriptions; `voice/tools.ALWAYS_ON` is a `frozenset[str]` of 11 names. Different artifacts. `voice/tools.py:79`'s *"the two still differ"* is stale. **The retraction must be propagated back into 06 and 38, which still carry it as Critical** |
| 3 | `40` §5.2: *"Zero ordering-sensitive route pairs… route registration order cannot affect matching."* `11` §6 checked the same thing and found the ordering **correct** | **Both measured, one mis-stated.** Verified: five static routes are declared before their parameterised siblings and work **only because of it** — and `main.py:2216-2219` is a handler docstring warning about one. Report 11 is right that nothing is broken *today*; the roadmap is wrong that reordering is safe. **The nominated validation compares a set where the defect is an order** |
| 4 | `39` scored Architecture 3 partly on *"persistence depends on the API contract layer"* (`db.py:26`); `38:152` lists the same edge as *"the only clean part"* | **Both partly wrong.** The citation is `db.py:24` (verified). `db.py:1` declares the module as *"Postgres accessors plus API response serializers"*, so importing `*Response` types is its stated job. **The violation is real and trivial** — nine construction sites, remediable with function-local imports. Scoring an architecture dimension down on it while a sibling report calls the edge clean is a corpus defect, not a code defect |

**Two retractions must be propagated back into the reports that still carry them as Critical:** the flow-control literal "drift" (`06` DUP-01, `38` C3) and `07`'s `CAMPAIGN_RUNTIME_ENABLED` verdict.

**And a gap nobody should assume was covered: reports 32 and 33 do not exist.**

---

## Overall Risk Assessment

**Composite: 4 / 10. Not enterprise production-ready — and the gap is a wiring job, not a rewrite.**

No score is an average. A family score is capped by its weakest production-blocking member, and the composite the same way: averaging a go-live blocker against a strength hides the blocker, which is the failure mode this document exists to prevent.

| Dimension | Score | Capped by |
|---|---:|---|
| Architecture | **4** | MF-009 (`db.py`), MF-010. Raised from the corpus's 3 — the Locked Engine pipeline measurably holds, HTTP does not leak, and the frontend would score ~7 alone |
| Code quality | **5** | MF-122 (2,605-line `build_tools`), no type checker, 4,800 latent diagnostics under a wider rule set |
| **Security** | **3** | MF-007, MF-008, MF-001, MF-068. **Tunnel URL = unauthenticated regulated CRM with attacker-chosen audit identity** |
| **Reliability** | **4** | MF-004 (five paths to a second ring), MF-026, MF-027. Lowered from 5: the duplicate-contact paths are a *regulatory* exposure in this domain, not merely an availability one |
| Data | **6** | Strong partial uniques and `numeric(14,2)` money, against MF-018, MF-109, MF-011's audit-chain scope |
| Testing | **5** | MF-020 (red today), MF-021 (concurrency untestable), MF-022. Lowered from 6: a suite that is red for a bogus reason is worth less than its coverage suggests |
| Operations | **4** | MF-017. `logger.info` is discarded in `api`; nothing scrapes `/metrics`; no tracing; no runbook; four workers with no healthcheck |
| **Configuration** | **3** | MF-039, MF-007, MF-036, MF-124. Lowered from 4: `policy_rule_sets` seeded by nothing means **WhatsApp, SMS and email have no calling-hour bound at all** |
| Deployability | **2** | MF-019. No pipeline, no image tags, no registry, no rollback, no backup/restore procedure, ngrok ingress |
| Documentation | **5** | MF-111, plus one doc calling 24 shipped modules "not yet built" |

**The three facts that set this number:**

1. **The shipped configuration is dialling live borrowers through a public URL with authentication off.** `APP_ENV=dev` + empty `API_KEY` + `TREATMENT_MODE=live` + `BILLING_ENV=production`. Two configured secrets are ignored because each gate short-circuits on `not _IS_PROD`.
2. **Both accepted ADRs are unimplemented**, and the module that implements them correctly has zero production importers.
3. **`git revert` is not a rollback mechanism in this repository.** There is no deploy pipeline, no release identity, and no backup procedure. Rolling back today means `git checkout <sha>` + rebuild + `up -d`, against a database that has already migrated forward — and three migrations' downgrades destroy regulatory evidence.

**What raises it fastest.** The six changes in the Executive Summary total under 60 lines and move Security and Reliability materially, because they close the four regulated holes that are live *today*. Everything structural — `db.py`, the routers, the frontend — is a quarter of work that moves the composite by one point. **The ordering in the existing roadmap has these reversed**, and that is the single largest sequencing error in the corpus.

**What this assessment explicitly does not claim.** Nothing was executed: no build, no server, no migration, no test run, no database, no container, no scanner, no request at any target. Every number is static. Coverage is call-graph-derived, never measured. Anything driven by a tenant database row — `provider_models.service_class`, `policy_rule_sets` contents, whether account ids are all-numeric, whether `platform_switches.outbound.enabled` is on — is **unknown**, and the eight runtime questions that would settle it are enumerated in [REFACTORING-STATE.md](./REFACTORING-STATE.md).
