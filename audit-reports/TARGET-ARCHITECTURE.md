# TARGET ARCHITECTURE

**Date:** 2026-09-03
**Mode:** Read-only. No application file was modified. This document describes a destination; it proposes no code.
**Companions:** [MASTER-AUDIT.md](./MASTER-AUDIT.md) · [CONFLICTS-AND-FALSE-POSITIVES.md](./CONFLICTS-AND-FALSE-POSITIVES.md) · [MASTER-BACKLOG.md](./MASTER-BACKLOG.md) · [REFACTORING-STATE.md](./REFACTORING-STATE.md)

---

## The governing principle

**The target architecture is the architecture this repository already has, finished.**

That is not a stylistic preference. It follows from a measured fact: of everything this consolidation would change, **the overwhelming majority is adoption of a module that already exists, is already correct, and is already unit-tested.** New construction appears in exactly **four** places, and each is justified individually below.

Three consequences shape every decision in this document:

1. **Every new boundary must name the concrete failure it prevents.** A boundary that exists to satisfy a layer diagram is refused. Nine such refusals are recorded in §6, each with a reason drawn from this tree rather than from a book.
2. **A refactor without a seam is a big bang.** Six strangler seams are already proven *in this repository* — one of them by an 18-function carve out of `db.py` that shipped. Every move below rides one of them, and anything that rides none is named as a big bang and refused.
3. **The institutional memory is the asset.** An unusual number of modules carry a docstring naming the specific incident they were written to close — `money_inr.py:10-23`, `env_utils.py:1-13`, `pg_errors.py:22-30`, `contact_policy.py:1-19`, `rls.py:19-23`, `requirements-voice.txt:4-5`, `api/config.ts:62-75`, `api/outbound.ts:301-307`, `platform_switches.py:15-24`. **A rewrite discards the incident log and re-earns every one of those bugs at full price.** The target preserves them; where a docstring is the *only* record of a fact, it is a protected artifact.

---

## 1 · What the architecture already is, and stays

Do not read the folder structure as the architecture. The shape below was reconstructed from imports, call graphs, routes and runtime wiring — and **it is largely correct.**

### 1.1 The gated decision pipeline — keep exactly as is

Four Locked Engines implement one documented shape:

```
features → candidates → veto → score → arbitrate → explore → log → [enact]
```

`agent_core/treatment/README.md:33` states the invariant: *"Exploration is last, and that is the architectural boundary. It sees only actions that already cleared every gate."* Measured: **49 of 56 intra-engine edges respect stage order**, and all seven apparent inversions are ranking artefacts, not control inversions. Every package façade deliberately withholds `enact`.

**The refinement that matters for every change below.** The load-bearing invariant is not *"ordering of gates"* — it is **"the last stage cannot widen the permitted set,"** and it is enforced by **data**, not by import path (`authority/enact.py:35-37` gates on `config.mode()` plus a required `decision_id`). Therefore:

> **The thing to protect is not the module boundary — it is the argument threading.** `provider`, `conn`, `arm` and `mode` pass down through the stage functions. **A refactor that hoists any of them to module state breaks the invariant silently**, with no import error and no failing test.

That single sentence is the most important safety rule in this document, because two of the four new constructions operate directly on it.

### 1.2 Boundaries that already hold — do not regress them

| Property | Measurement | Why it must survive |
|---|---|---|
| **Nothing imports `main.py`** | zero edges, 267 modules | The worst-shaped file in the tree is a pure sink. Nothing has to be rewritten to change it |
| **The web framework does not leak** | `fastapi`/`starlette` in 3 of 267 modules; `HTTPException` in exactly one file | Every policy engine is reusable by the voice worker, the WhatsApp worker and the sweeps, because none can raise a web error |
| **Wire schemas do not leak inward** | `schemas.py` has exactly 2 importers | The outcome a DTO layer is built to achieve, already achieved |
| **Authorization is total and provable** | `Depends(_authz_guard)` on the `FastAPI(...)` constructor; unregistered routes **denied**; CI proof at **318/318** | Coverage by construction, not by discipline. **This is the mechanism every missing boundary below should copy** |
| **One `create_engine`, tenant as a libpq startup parameter** | 2 sites in the whole tree | A pool ROLLBACK cannot un-set it. **This is the entire safety argument for enabling RLS**, and a casual "move the engine to a factory" during a carve would silently destroy it |
| **Half the domain is already pure** | 51 of 102 domain modules, 12,414 lines, no SQL, no `db`, no provider SDK | A rewrite would re-type code already in its target state |
| **Frontend layering** | `routes → components → api/data/lib`, **zero** `components → routes`, zero app cycles, `components/ui` with zero edges to `api/` or feature code | The frontend does not need a rewrite or a store |
| **One frontend transport** | `api/config.ts` holds 6 of 7 `fetch` calls; zero `axios`/`XMLHttpRequest`/`EventSource`/`WebSocket` elsewhere | The single strongest seam in the repository |
| **Process split** | two images, five services, per-process `DB_PROCESS_ROLE` selecting a 15 s vs 60 s statement timeout | Deliberate and documented; the lazy imports that look like a smell are what make it work |

### 1.3 The six proven seams — every move rides one

| # | Seam | Where it is proven | What it unlocks |
|---|---|---|---|
| **S1** | `Protocol` + `x or Default()` | `FeatureProvider` in all three engines; `Recommender` ×2. Wired end to end, **defaulted at the leaf**, and **no production call site passes `provider=`** | Swapping an implementation touches **zero** call sites. This is what a strangler seam looks like *before* you use it |
| **S2** | Named registry with graceful degradation | `treatment/scoring.py:591 build_scorer(name)` — *"degrading to the EV scorer at every step. An unknown name must cost lift and never availability"* | The best model in the repo for introducing a second implementation of anything |
| **S3** | Flag-selected adapter port | `work_runtime/api.py:10-17` | **Incomplete — 3 of 7 operations. See §4.3** |
| **S4** | Bottom-of-file re-export | `db.py:18005-18024` ← `followups_db.py` | **Someone has already carved 18 functions out of `db.py` this way, and it shipped.** That converts the carve from a design question into a repetition |
| **S5** | PEP 562 lazy package façade | `agent_core/cards/__init__.py:52-68`, with the failing `ImportError` chain in a 24-line comment | A carve that would create a cycle S4 cannot break |
| **S6** | String-keyed `importlib` registry | `providers/registry.py:550-552` | How `fish_service.py` — with a module-level `pipecat` import — lives inside `agent_core/` without breaking the API image, by having **zero Python importers** |

---

## 2 · The target, stated as a diagram

```
┌─ OPERATOR CONSOLE (Habibi) ───────────────────────────────────────────┐
│  routes → features → api/*  →  ONE transport (api/config.ts)          │
│                                  └─ parses at the boundary (NEW #4)   │
│  types live in api/, NOT in data/*-seed.ts                            │
│  seeds are fixtures. USE_MOCK lives in api/config.ts and nowhere else │
└──────────────────────────────── HTTP ─────────────────────────────────┘
                                    │
┌─ API PROCESS ─────────────────────▼───────────────────────────────────┐
│  main.py  — routes only, thin handlers, one error map                 │
│     · six dense routers extracted; 72 prefixes left alone             │
│     · every route declares a response_model, enforced like authz      │
│     · Depends(_authz_guard) stays on the constructor                  │
│                                                                        │
│  ── application functions ────────────────────────────────────────────│
│     outbound.dial(...)          ← NEW #1: the one gate sequence       │
│     db.<domain>.* via re-export ← S4 carve, 13 sections               │
│                                                                        │
│  ── LOCKED ENGINES (unchanged shape) ─────────────────────────────────│
│     treatment · reco · authority · live_qa                            │
│        conn is REQUIRED (NEW #2) — no db.engine fallback              │
│        façades still withhold enact                                   │
│                                                                        │
│  ── REGULATED OWNERS (one each, imported not restated) ───────────────│
│     contact_policy.admit      ← the contact Gate, 13 callers          │
│     policy_rules.calling_window()  ← statutory hours, 9 callers       │
│     agent_core.tools.grant.ToolGrant ← ADR-0001, ALL runtimes         │
│     money_inr · contact_window · env_utils · pg_errors · context      │
│                                                                        │
│  ── PERSISTENCE ──────────────────────────────────────────────────────│
│     db_core.py   ← NEW #3: engine, begin-listener, row helpers, tenant│
│     db.py        ← ~3,100 lines: CRM kernel + re-exports              │
│     db_<section>.py × 13                                              │
│     RLS ON, NOBYPASSRLS role  ← the backstop, not the only line       │
└───────────────────────────────────────────────────────────────────────┘
        │                    │                      │
   bot_worker            worker              voice.bot / insurance
   (split by SLO)     (KB + sweeps)     Pipecat — 3 of 44 modules coupled
        │                                          │
        └─ claim → COMMIT → carrier I/O ───────────┘   ← the invariant
```

**Four new constructions. Everything else is an import, a deletion, or a move.**

---

## 3 · The four new constructions

Each is justified on its own, and each names the failure it prevents.

### NEW #1 · `outbound.dial(...)` — one owner for the gate sequence

**The failure it prevents.** The regulated ordering `mission.build → reserve → admit → suppress-on-refusal → place` is written at **seven sites in two different orderings**, two of them inside HTTP handlers ~320 lines apart that also take `dict[str, Any]` bodies and open their own transactions. And it has **already landed differently**: `payment_events.py` runs `admit → reserve → place` with **no `outbound.suppress` anywhere in the module**, so the invariant *"every refused outbound leaves a suppressed attempt row"* holds at six of seven and is false at the seventh. `call_attempts` is the only record that a call was *not* placed — **this is a gap in the evidence of a correct refusal.**

**Why a function and not a layer.** `outbound.py` already owns `reserve`, `suppress` and `place`, and `contact_policy` already owns `admit`. Nothing owns the **sequence**, and the sequence is where the compliance lives. This is a missing *function*, not a missing tier — which is exactly why §6.2 refuses a service layer.

**Prerequisite that is a decision, not code.** Pick one ordering, and decide whether every refusal must leave a `call_attempts` row. **Do not average the two.**

**Seam:** none needed — the five ordering-A sites migrate with no behaviour change; the two ordering-B sites migrate separately and deliberately.

---

### NEW #2 · `conn` becomes required in the four Locked Engines

**The failure it prevents.** All four engines accept an injected connection and **fall back to opening their own** from the `db.engine` global (64 modules, 262 references). `treatment/engine.py:259` states the cost in its own comment: *"One connection for the whole read phase, then the log writes on its own."* When the fallback fires, the decision is read on one connection and the decision-log row is written on another — **so a caller that rolls back cannot retract the log row.** In a regulated collections product that is an audit record asserting a treatment decision was taken for a borrower when it was not, and the audit trail is the artefact an inspection reads.

**Why this is a subtraction, not an abstraction.** The injection path already exists in two of the four engines, and `treatment/decisions.py:41-61` (`_writer`/`_reader` — *"use the caller's transaction, or open one"*) already expresses the intended contract. The work is deleting a fallback and threading one argument. `reco/engine.py:_recommend` is the exception — it takes no `conn` at all, so there is no seam to inject through and one must be added.

**The safety rule from §1.1 applies directly here.** `conn` is one of the four threaded arguments. Hoisting it to module state during this change would break the pipeline invariant silently.

---

### NEW #3 · `db_core.py` — the precondition for splitting `db.py` at all

**The failure it prevents.** `db.py` cannot be split today, because 41 production modules bind to its **private** helpers: `db._tenant()` at 80 external sites, `_rows()` at 57, `_one()` at 54, `_jsonb()` at 22 — **202 of 239 reach-throughs**. A split breaks all of them, plus the 101 modules bound to the name.

**What moves.** `engine` + the `@event.listens_for(engine, "begin")` hook + the `DATABASE_URL`/`TENANT_ID`/pool constants + `current_tenant`/`_tenant` + `_rows`, `_one`, `_id`, `_dump`, `_sql`, `_vis_params`, `_activity`, `_actor_user_id`, `_assert_tenant_owns`, `clamp_list_limit`, `clamp_offset`, `_account_tail`, `_IST` — **plus `_jsonb` and `_as_dict`, hoisted down from `:14068` and `:12703`**, because both are defined inside upper sections and referenced across them, so a naive peel would create an upward dependency. Give it an explicit `__all__`; `env_utils.py` and `pg_errors.py` are the in-repo models.

**Why the shim works.** Verified: **no importer anywhere uses `from db import X`** — all 211 production import sites use `import db`, so attribute re-export from `db.py` keeps every call site resolving. Blast radius: zero call sites.

> **One hazard that must be written into this commit's acceptance criteria, not discovered later.** `tests/conftest.py:61` is `monkeypatch.setattr(db, "engine", _EngineProxy(db.engine))`. The fixture works because every production path resolves `engine` as an **attribute on the `db` module object at call time** — which is also why `followups_db` reaches back through `_db()` instead of importing `engine`. **Any carved module that binds `from db_core import engine` bypasses `_EngineProxy`**: the savepoint wrapper stops wrapping, and `outer.rollback()` rolls back nothing those modules wrote. **The suite goes green while leaving committed rows behind** — and commit `fd855ca` ("Make the suite pass on a database nobody has touched by hand") shows this repository has already paid for that bug once. **Every carved module must reach back through `_db().engine`.**

**Seam:** S4, then S5 where a carve would create a cycle S4 cannot break.

---

### NEW #4 · Runtime validation at the frontend transport

**The failure it prevents.** `api/config.ts:183` is literally `return JSON.parse(text) as T`, and `T` is chosen by the caller — usually an interface declared in `src/data/*-seed.ts`, the **mock factory**. **229 unchecked casts, zero runtime validations.** This is not a style complaint; it is a **false safety property**, and it is already false in production: `InteractionResponse.summary` is `str | None` on the wire and `string` in TypeScript. `tsc` is green while the wire type is optional; `customerInsights.ts` already wraps with `str()` as runtime compensation for a type that still says `string`.

**Why an optional third parameter and not a generated client.** `apiGet<T>(path, init?)` has no schema parameter, so adding one unconditionally changes the signature at **221 generically-typed call sites**. The strangler form is `apiGet<T>(path, init?, schema?)`: unvalidated calls keep working, and one `api/*.ts` module migrates per commit. `zod@^3.24.2` is already a dependency, used exactly once.

**Order matters and is not obvious.** The 261 domain types must leave `data/*-seed.ts` **first** — that move is pure type-level, so `tsc --noEmit` catches every mistake, making it the lowest-risk frontend change available. Then the zod schema and the inferred type land together, which is what makes the parse pay. **And deleting the mock branch deletes the module that declares `Customer`**, so the `USE_MOCK` cleanup comes last.

---

## 4 · What changes without new construction

### 4.1 Adopt the owners that exist

Nine regulated questions have a named owner and a live copy running beside it. **In every case the work is an import.**

| Question | Owner | What changes |
|---|---|---|
| Which tools may this Mouth execute? | `agent_core/tools/grant.py` | 6 steps, ending in `allowed=frozenset()` for a cardless card. **Step 1 is two lines and needs none of `grant.py`**: pass `channel_tools=` at `skills/runtime.py:194,197`, closing the one *verified* divergence |
| Which consent statuses forbid contact? | `contact_policy.BLOCKING_CONSENT` | 4 definitions → 1. Provable no-op; cycle-safe (`contact_policy` is a DAG leaf) |
| What are the statutory calling hours? | `policy_rules.calling_window()` | 9 decision sites, 2 consult it. Start with `compliance/detectors.py:297-298` — one file, numbers already match, and it is the only **unpinned** restatement in the set |
| What window when none is on file? | `contact_window.DEFAULT_WINDOW` | Ship in three pieces by risk: display / **the live DND verdict at `db.py:1938`** / the writes |
| Is this party on DND? | `contact_policy` (ORs both stores) | `db.py:1826` reads one column. Code fix first, fail-closed; column consolidation later |
| How do we format rupees? | `money_inr.inr` | Regulated — it changes an SMS the borrower reads and **a sentence the agent speaks aloud** |
| What are the last four of the account? | `agent_core.context.account_tail` | 5 algorithms → 1, **after** a production read proves it is a no-op |
| Which environment is this? | `env_utils` + a new `is_prod()` | **`main.py` only.** Three of the eleven sites re-derive on purpose — see CONFLICTS §C13 |
| How is a failed read rendered? | `QueryState` | **Fix `RecordsTable` first** — it has no `isError` prop, so the abstraction is *the reason* the fix does not generalise |

### 4.2 Enforce the wire contract the way authorization is enforced

`authz.ROUTE_PERMISSIONS` is the model: **one reviewable table, applied by construction, unregistered entries denied, coverage provable by a test at 318/318.** The wire needs the same shape — a route→`response_model` registry with a CI totality test.

**But the test lands after 178 → 0, not before.** That is this repository's own stated rule, from the CI workflow's comment: *"Deliberately NOT `--max-warnings 0`: gate what passes today, then drive the count down. **A gate introduced red is a gate people learn to ignore.**"*

**Two mechanics decide the order:**
- `response_model` **filters** undeclared fields. Adding one to a route that ships `SELECT *` **drops fields from the wire** — and `api/outbound.ts:301-307` has already written down, in prose, that those raw field names *are* the frontend's contract. Six routes need frontend coordination and are also the ones leaking `tenant_id` to the browser.
- **Response shapes are hand-assembled inside `db.py`** — the file NEW #3 splits. **Raise coverage before the carve, or the carve silently rewrites the public API.**

### 4.3 Complete the `work_runtime` port

`work_runtime/api.py:1` states the intention correctly — *"Adapter is chosen here, not at call sites"* — and `adapter_temporal.py` fails **closed** rather than silently falling back. The whole port is 42 lines. **But it exposes 3 operations and the Postgres adapter exposes 7**, so callers reach around it: `agent_core/clerk.py:17,18` imports the port and the concrete on consecutive lines, and `treatment/enact.py:702` and `sweep.py:243` insert into `work_runtime_jobs` directly.

**Add `list_jobs`, `claim_next`, `finish`, `park_input_required` to the port and put a `Protocol` on it.** There is none today; the two adapters agree only because `adapter_temporal` is three `raise` statements. **Do not flip `TEMPORAL_ENABLED` until this is done** — the day it flips, `start_workflow` routes to Temporal while the drain loop raises and two treatment paths keep writing a Postgres table nobody drains. That is a split-brain job queue on **financial instructions**, and it is the exact swap the package was built to make safe.

### 4.4 Split `bot_worker` by SLO, not by inventing a broker

One process serialises 15+ unrelated drains on a 1.5 s poll, and **only four of twelve stages are individually guarded — with five unguarded ones running above them.** A persistently-raising row aborts the tick before the guarded stages are reached, and the loop logs `logger.exception("process_one crashed — backing off")` with **no queue name and no row id**, forever.

Target: `messaging_worker` (bot turns, WhatsApp outbound) · `dialer_worker` (closer, cadence, campaigns, bounce voice, sweeps) · `treatment_worker` (enact, followthrough, sweep, clerk) · `integration_worker` (webhook deliveries) · `worker` (KB + maintenance, unchanged). **Same `process_one(engine) -> bool` contract, no schema change, no new broker.** Postgres `SKIP LOCKED` is the broker and stays the broker.

**And the invariant that must hold in all of them:** *claim → COMMIT → carrier I/O → record.* `cadence.process_one`, `campaigns.process_one`, `whatsapp_outbound.process_one`, `call_closer.process_one` and `webhooks_dispatch` already do this correctly. Treatment SMS, PTP reminders and bounce first-touch do not.

### 4.5 Six routers out of `main.py` — and this is the item to drop

Extract `agent_studio`, `outbound`, `twilio`, `treatment`, `eval`, `demo` — ~75 routes, ~1,700 lines, mounted with **no `prefix=`** so full paths stay in the decorators, authz keys stay byte-identical, and the diff is a pure move. **Leave the other 72 prefixes alone**: `/providers` spans 3,920 lines for 144 of its own, `/customers` 3,901 for 31.

**Say plainly what it buys and does not buy.** It buys merge-conflict surface, navigability, and a place to hang per-subsystem dependencies. **`main.py` has zero importers**, so it reduces no other module's coupling, breaks no cycle, and improves no dependency metric. **Priority: low. If the programme has to drop something, drop this.**

> **And one hard constraint, which the corpus got wrong.** Route registration order **does** affect matching, in five places, and `main.py:2216-2219` is a handler docstring warning about one. The validation must be an **ordered list**, not a set — and this extraction must not ship in the same release as the `/agent-studio` `response_model` work, because both land on the same 26 routes and the natural grouping pass reverses the pair. See CONFLICTS §C3.

---

## 5 · The operational target

Structure is not the binding constraint here; the envelope is. These belong in the target because **no structural work is safe without them.**

| Property | Target | Today |
|---|---|---|
| **Release identity** | Images tagged by commit SHA, pushed to a registry, rollback written down **including the database-state caveat** | `collections-api:local`. `git tag` returns zero. **`git revert` is not a rollback mechanism in this repository** |
| **Environment** | `_IS_PROD = _APP_ENV not in {"dev","test","local"}`, decided **after** `load_env()`, absent credentials a **refusal** not a mode | Two-string allowlist, computed before `.env` is read, credentials optional |
| **Tenant isolation** | RLS on, `NOBYPASSRLS` role provisioned, hand-written predicates as defence in depth | RLS complete, tested, and **inert**; ~290 predicates are the only line |
| **Logs** | Root handler installed unconditionally; redactor matches **bare-digit** phones and runs over `extra` and tracebacks | `logger.info` discarded in `api` and `voice_insurance`; the redactor never executes |
| **Metrics** | `/metrics` scraped from both API and voice; one `outbound_latency`/`outbound_errors` pair at the ~10 adapter entry points | Well-built, cardinality-disciplined, **scraped by nothing** |
| **Correlation** | `X-Request-Id` reaches the log line and joins to the interaction id; job rows carry it across the queue | Generated, sanitised, echoed, CORS-exposed, **written to no log**; the browser shows a reference id transmitted nowhere |
| **Health** | Healthchecks on all five app services | Four workers have none |
| **Schema truth** | One source. `sql/23_outbound_evals.sql` created or the reference deleted | Three sources, one referenced file **missing**, and a fresh install **cannot publish outbound at all** |
| **Policy as data** | `policy_rule_sets` seeded, or the fallback documented as the product | Seeded by nothing, so **WhatsApp, SMS and email have no calling-hour bound** |
| **Dependency floor** | A lockfile from a 3.12 resolve with hashes; `requires-python`; `-c requirements.txt` on the voice install; one SCA gate | 114 of 134 packages unpinned; two images from one commit have different libraries and **nothing records what either got** |

---

## 6 · What this target refuses, and why

A target architecture is judged as much by what it declines. Each refusal is a position, not an omission.

**6.1 · A rewrite.** The evidence points hard the other way on five counts: the seams already exist and are documented; `main.py` has zero importers; the framework does not leak; half the domain is already pure; and **the institutional memory is the asset a rewrite burns.** The one honest counter-argument — `db.py` at 18,087 lines — is a case for strangling one file, not replacing a platform.

**6.2 · A repository / DAO layer.** The reflex fix for "101 modules import `db`" is refused because **the repository already has the pattern that solves this and uses it correctly**: `FeatureProvider` is a domain-owned Protocol with a SQL implementation — a repository pattern applied exactly where it pays, one narrow interface per decision, defined by the consumer. Generalizing it to 440 functions produces ~440 pass-throughs, **doubles the number of places a tenant predicate can be dropped**, and adds a hop to every read. And it would break something load-bearing: `contact_policy` needs `SELECT … FOR UPDATE` **inside the caller's transaction** to enforce the frequency cap at all. **Extend the pattern to the call sites that need substitutability. Do not build the generic layer.**

**6.3 · A service / application layer.** The work a service layer would hold is already owned — `contact_policy.admit` is the contact Gate, `agent_core/authority` is the waiver matrix, `outbound` owns reserve/suppress/place, `promise_fulfillment.settle_promises` is the promise clock. **What is missing is not a layer — it is that 28 HTTP handlers orchestrate those owners directly instead of calling one function that does.** Name the missing functions (NEW #1). Do not erect a tier above the ones that work.

**6.4 · A DTO layer.** `schemas.py` has exactly two importers and the domain never sees its 247 models. That is the outcome a DTO layer is built to achieve, already achieved. Adding one creates a third representation of every payload.

**6.5 · Rewriting the 2,131 function-local imports as top-level.** They look like a smell and they are **load-bearing**: `requirements-voice.txt` is deliberately kept out of `requirements.txt`, and the lazy imports are what let one codebase run in images with different dependency sets. `tests/test_import_cycles.py` defends the order. Converting them would break a real, deployed property to satisfy a style preference. **They are a symptom of `db.py`, and they will resolve when it is split — not before, and not by being rewritten.**

**6.6 · Splitting `agent_core/` further.** Four engines implementing one shape is not accidental duplication; it is the same shape answering four different questions. **Do not merge naming collisions** — four meanings of **Offer**, three of **Handoff**, and **Cadence** versus HTTP retry are different questions, and collapsing them would be a worse bug than leaving the copies. The one genuine over-abstraction (three `FeatureProvider` Protocols with one adapter each) is cheap, harmless, and is exactly where NEW #2's substitutability will be needed.

**6.7 · An ORM.** There is no ORM by deliberate choice (`alembic/env.py` sets `target_metadata = None`). Every query amplification in this tree is an explicit Python loop, which is why they could be enumerated at all. Introducing one now would touch every hand-written tenant predicate **in the same change that introduces implicit lazy-loading**. That is the single highest-risk change available in this repository and it buys ergonomics.

**6.8 · A frontend rewrite, or a global state manager.** There is **no god context**; global client state is theme, sidebar collapse and a notification-read set; layering is clean with zero `components → routes` edges; the app graph has no cycles. What `29` and `30` found is a well-built primitive layer the feature surfaces route around — an **adoption** problem, which is precisely what incremental extraction fixes and a rewrite makes worse.

**6.9 · A vocabulary alignment.** SQL, HTTP and the UI still carry pre-`CONTEXT.md` spellings (`bots`/`bot_id` where the glossary says **Mouth**). It is tempting and it is refused, because `platform_switches.py:60-66` states the governing constraint: renaming a key *"would orphan the row an operator has already enabled, silently making the demo more restrictive at the moment they least expect it."* Every DB-keyed switch, every `policy_rules.kind` string and every status literal backed by a `CHECK` has that property. **A rename here is a data migration, not a refactor.** Fix names only where a file is already being rewritten for another reason.

**Also refused:** microservices (the process split already exists and is correct); an event bus (Postgres `SKIP LOCKED` is the broker and four queues get claim/lease/reclaim/dead-letter genuinely right); a workflow engine (the workers *are* the workflow engine); a second circuit-breaker library (one exists, closes two real races, and the DB-backed connector breaker is a justified second **kind**, not a duplicate); and merging `contact_window` 09:00–20:00 with RBI 08:00–19:00 — **borrower preference and statutory hours are different rules, and merging them would be the worst single outcome of this exercise.**

---

## 7 · How the target is enforced

Structure decays unless something fails the build. Every enforcement mechanism below is **already proven in this repository**; none is new machinery.

| Invariant | Mechanism | Precedent in-tree |
|---|---|---|
| Every route is classified | `assert_registry_covers` | **Already at 318/318.** The model for the rest |
| Every route declares a response shape | The same table shape, added **after** 178 → 0 | `authz` |
| The two exempt lists agree | A three-line test | `tests/test_env_name_shared_helper.py` does exactly this for a different pair |
| Route order is preserved across a router split | An **ordered-list** snapshot, not a set | New — and the reason C3 exists |
| A regulated constant is stated once | A pin test comparing the copy to the owner | `tests/test_outbound_missions.py` pins the Outcome vocabulary across three homes |
| Cross-language rules agree | Emit backend constants as a generated JSON fixture; vitest asserts the TS port | New, cheap. The dispute SLA is **already divergent — 48 h vs 40 h — with both suites green** |
| A dated constant has not expired | One test failing when any dated constant is within 30 days | New. Closes a **class** that has already fired twice |
| The image boundary is real | `python -c "import main"` in the base image with pipecat and fastembed absent | New, one CI step. Converts "masked by packaging" into "caught by a test" |
| No carrier call inside an open transaction | A lint or a test for the pattern | New. **The other fixes do not prevent the class from recurring** |
| The seed has content | One test failing when `customers`, `accounts`, `interactions`, `products` or `leads` is empty | `conftest.py:146` already does this for skill packs — *"these tests would go vacuous"* |
| Concurrency is testable at all | A `db_real` fixture beside `db_tx` | `test_job_claim.py` and `test_voice_session_store_contention.py` **already escape the fixture by hand.** The pattern needs promoting, not inventing |

---

## 8 · Migration order, and the three claims it rests on

**Order:** shut the envelope and give a deploy an identity → make red mean red → adopt the owners that are provable no-ops → close the four regulated holes → raise the wire contract → carve `db.py` → frontend → infrastructure.

Three ordering claims are load-bearing, and each is measured rather than conventional:

1. **The wire contract before the `db.py` carve.** Response shapes are hand-assembled *inside* the file being split, and the wire is unvalidated on both sides. Carve first and you silently rewrite the public API with nothing to catch it.
2. **Delete the dead frontend before the frontend wave.** 22 of the `components/ui/*` files that reports 27, 29 and 30 scope their remediation to are **dead** — including `ui/form.tsx`, which report 30 names as *"a correct primitive with 0 importers awaiting adoption."* It is not an adoption candidate.
3. **The test baseline before the regulated canonicalizations.** Six of nine targets have no test that would fail on a behaviour change, so consolidating them today would be **unfalsifiable** — you could not tell a successful consolidation from an incident.

**And one claim the evidence refutes.** Deleting dead code does **not** pre-pay for the canonicalization work in this repository: every live Tool Grant formula sits in a reachable module, and `grant.py` is the *destination*, not a duplicate to reap. It pre-pays substantially for the **frontend** and not at all for the backend.

**One ordering correction to the existing roadmap, and it is the largest sequencing error in the corpus.** ADR-0002's one-line deny-all is scheduled **last**, behind ~13 developer-days, on a stated blast radius that `voice/tools.py:80-94` contradicts: `ALWAYS_ON` is unioned back *after* the filter, so a cardless mouth keeps `disclose_recording`, `verify_identity`, the flow verbs and `end_call`. **It still greets, discloses, verifies and hangs up. It simply cannot move money.** That is a safe degradation and it is exactly what the ADR asks for. It belongs near the front, gated only on `SELECT bot_id FROM prompt_versions WHERE agent_card IS NULL OR agent_card = '{}'::jsonb`.

---

## 9 · What "done" looks like

The target is reached when all of the following are true. Not one requires a new abstraction.

- [ ] `agent_core/tools/grant.py` has **production importers**, and the old formulas are deleted — not left beside it.
- [ ] A cardless Mouth is granted `frozenset()`, and `bot_tools.TOOL_DEFINITIONS` no longer exists as a fallback.
- [ ] `contact_policy.admit` fails **closed** for every purpose, and `patch_consent` cannot overwrite a window the operator did not change.
- [ ] Every refused outbound leaves exactly one suppressed `call_attempts` row, at all seven sites.
- [ ] An ambiguous carrier failure is `ambiguous`, not `dial_failed`, and no scheduler re-queues it.
- [ ] `_AUTH_EXEMPT_PREFIXES` is derived from `authz.PUBLIC_ROUTES`, or a test asserts they agree.
- [ ] Absent credentials refuse to boot; unrecognised `APP_ENV` is treated as production; `load_env()` runs before `_IS_PROD`.
- [ ] RLS is on with a `NOBYPASSRLS` role, and the hand-written predicates are defence in depth.
- [ ] `logger.info` reaches a handler in all five services, and the redactor runs over `extra` and tracebacks.
- [ ] Every route declares a `response_model`, enforced by a test that was introduced **green**.
- [ ] `db.py` is ~3,100 lines: the CRM kernel plus re-exports. **`db_core.py` exists and every carved module reaches back through `_db().engine`.**
- [ ] `apiGet` parses, and no domain type is exported from a `*-seed.ts` file.
- [ ] `pytest -q` is green, a coverage number is published, and `db_real` exists with at least one contention test using it.
- [ ] All twelve `contact_policy` refusal reasons have a behavioural assertion — and `_prep` no longer nulls the DND and window columns.
- [ ] Images are tagged by commit SHA and the rollback procedure is written down.

**And the things that must look exactly as they do now:** `main.py` still has zero importers · `schemas.py` still has two · `fastapi` still appears in three modules · `create_engine` still appears twice, still passing the tenant as a libpq startup parameter · the Locked Engine façades still withhold `enact` · `contact_window` 09:00–20:00 and RBI 08:00–19:00 are still two different rules.
