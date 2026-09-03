# 40 — Refactoring roadmap

**Role:** Principal software modernization architect.
**Question:** In what order can this repository be modernized without breaking a regulated collections platform that is already dialling borrowers?
**Scope:** `backend/` (FastAPI, workers, voice runtime, Locked Engines, SQL, Alembic) and `Habibi/src` (TanStack Start operator console). Guest tree `PRAXIST-main/` is out of scope — 4,518 vendored files with no import edge into the product.
**Date:** 2026-09-03
**Mode:** **Read-only. No code was modified.** No install, no build, no dev server, no migration, no `pytest` run, no write-mode linter, no state-changing git. The only file written is this report.
**Vocabulary:** `CONTEXT.md`. **Mouth**, **Agent Card**, **Skill Pack**, **Locked Engine**, **Tool Grant**, **Offer**, **Gate**, **Flow**, **Handoff**, **Mission**, **Cadence**, **Outcome** are that glossary.

**Method.** Six specialist analysts — dependency-order, duplication, dead-code, architecture, testing-risk, migration-risk — run in parallel against the tree, each briefed with first-hand ground truth and each required to cite `file:line` for anything that changes a wave assignment. Alongside them, a direct thread read the verdict of every one of the **38 prior reports in this audit series** (`01`–`39`, ~22,000 lines) and re-verified the load-bearing facts this roadmap is sequenced on. Prior reports are treated as **strong secondary evidence**: they are the accumulated, verified output of this series, but every claim that determines an ordering constraint was re-read from source in this session. Where an analyst and I disagreed, §11 records both readings and which survived.

**This report proposes no code.** It is a sequencing document. Every action below is a description of work to be done later, by someone with a green test suite and a deploy window.

---

## Verdict

**This repository does not need to be modernized so much as it needs to be *finished*. The dominant work item is adoption, not construction.**

That is the single most consequential finding for sequencing, it is not my inference, and it is not new. It is the independently-reached conclusion of at least eleven prior reports in this series, each looking at a different subsystem and each arriving at the same sentence:

> `06-duplication.md`: *"A canonical owner already exists… Production still runs the older copies."*
> `09-canonical-implementations.md`: *"The product already knows how to pick a canonical owner… Production still runs the older copies beside those leaves."*
> `11-api-contracts.md`: *"This codebase has a contract. It has no mechanism that keeps the contract true."*
> `14-error-handling.md`: *"The failure-handling primitives are better than the system that uses them."*
> `19-auth-authz.md`: *"Excellent mechanism, shipped switched off."*
> `25-resilience.md`: *"The adapters that were built as adapters are resilient. The paths that bypass them are not."*
> `29-ui-consistency.md`: *"The design layer is well built, well documented, and largely unused."*
> `30-accessibility.md`: *"Habibi's accessible primitives are well built, and the feature surfaces route around them."*
> `37-integration-boundaries.md`: *"In twelve separate places, the correct mechanism exists, is well built, is usually documented with the incident that motivated it — and stops at a boundary that has a neighbour on the other side."*
> `38-architecture-boundaries.md`: regulated decisions are *"restated at call sites rather than imported."*

Eleven independent lenses, one shape. `29-ui-consistency.md` named the mechanism behind it exactly: **"the quality in this codebase is concentrated exactly where an incident already happened, and absent everywhere else."** Each guard closed the hole it was written for and did not generalize by one inch.

That has three direct consequences for a roadmap, and they are why this document looks different from a normal modernization plan:

1. **The cheapest work is the highest-value work, which is unusual and should be exploited.** Wiring a module that already exists, is already correct, and is already unit-tested is a small diff with a large regulatory payoff. `backend/agent_core/tools/grant.py` is the emblem: 247 lines, an accepted ADR (ADR-0001) naming it the one owner of the **Tool Grant**, two dedicated test files — and, verified by hand in this session, **zero production importers**. Two commits this week refined it (`5560159`, `767f1b4`). Nothing calls it. Meanwhile four-to-seven live formulas still compute the grant, and at least one pair has already diverged.

2. **"Rewrite from scratch" is not merely unnecessary here — it would destroy the most valuable asset in the tree.** The good parts of this codebase are not its structure; they are its *institutional memory*. An unusual number of modules carry a docstring naming the specific incident they were written to close (`money_inr.py:10-23`, `env_utils.py:1-13`, `pg_errors.py:22-30`, `contact_policy.py:1-19`, `requirements-voice.txt:4-5`, `Habibi/src/api/config.ts:62-75`, `api/outbound.ts:301-307`). A rewrite discards the incident log and re-earns every one of those bugs. §6 states this position formally, as the instruction requires.

3. **The sequencing constraint is not mostly technical.** Very little in this tree is blocked by an import cycle or a type that must move first. What blocks the work is that **you cannot currently tell whether a behaviour-preserving change preserved behaviour** — the suite's regulatory coverage is thin exactly where the canonicalization targets are, and the shipped configuration turns the fail-closed controls off. That is why Wave 0 is not a formality here. It is the majority of the risk reduction in the entire programme.

**The one structural item that is genuinely large** is `backend/db.py`: 18,087 lines, 440 functions, fan-in ~101. It is the single article in this tree for which incremental strangling must be designed rather than merely scheduled, and it is deliberately placed *late* — it is the only wave whose prerequisites are nearly the whole rest of the roadmap.

**What this roadmap does not propose:** a repository/DAO layer, a service layer, a DTO layer, a Clean-Architecture re-layering, a rewrite of the 2,131 function-local imports, a further split of `agent_core/`, or a frontend rewrite. Each is declined with a stated reason in §6. The user's constraint — *do not create abstraction layers merely to satisfy a theoretical architecture diagram* — is honoured literally: **every wave below either deletes code, adopts a module that already exists, or moves a decision to an owner the repository has already named.** New construction appears in exactly three places, and each is justified individually.
---

## 1. What this roadmap is built on

### 1.1 The evidence base

This is report 40 in a series. Reports `01`–`39` are ~22,000 lines of read-only forensics over the same tree, each produced by parallel specialist analysts with a verification pass, and several explicitly recording claims that did not survive re-checking. That is a far stronger starting position than a modernization plan normally has, and this roadmap is mostly an act of **sequencing** what those reports already established rather than re-discovering it.

The reports that carry the most weight here, and what each contributes to the ordering:

| Report | What it contributes to the sequence |
|---|---|
| `05-dependency-graph.md` | The import graph and the ~110-module runtime SCC glued by `db.py`; frontend is acyclic |
| `38-architecture-boundaries.md` | The architecture that actually exists (gated decision pipeline); `db.py` cut experiments; boundary candidates |
| `06`, `09`, `35` | The canonicalization targets and, critically, **which copies have already diverged** |
| `07-dead-code.md` | The deletion candidates and the six dynamic-reference escape hatches that make static "dead" wrong here |
| `22-testing-quality.md` | What the safety net does and does not cover — the input to Wave 0 |
| `12`, `20`, `21`, `31` | Migration prerequisites: two sources of schema truth, `APP_ENV` as master switch, no backend lockfile, five processes with five answers to "am I live?" |
| `18`, `19`, `39` | The shipped configuration, and why it caps what can safely ship |
| `14`, `15`, `25` | The failure-mode families that a refactor must not disturb |
| `11`, `27` | The wire contract, and why frontend and backend work are coupled through it |
| `03`, `29`, `30` | The frontend's real debt: god routes and unadopted primitives, not missing state management |

### 1.2 What was re-verified first-hand in this session

Because a wrong ordering constraint is worse than a missing one, the following were re-read from source in this session rather than carried:

| Fact | Verified | Value |
|---|---|---|
| `backend/db.py` size | ✅ | **18,087** lines |
| `backend/main.py` size | ✅ | **5,448** lines |
| `backend/schemas.py` size | ✅ | 3,453 lines |
| `agent_core/tools/grant.py` production importers | ✅ | **zero** — only `tests/test_tool_grant.py`, `tests/test_tool_grant_characterization.py`, and the module-name list in `tests/test_import_cycles.py:35` |
| Backend test files | ✅ | **186** `test_*.py` |
| CI workflows | ✅ | exactly **two** — `backend-pytest.yml`, `frontend-typecheck.yml` |
| Branch state | ✅ | `autonomous-dev`, **25 commits** ahead of `main` |

The rest of this roadmap's per-action evidence is carried in the action tables, each citing the report and the `file:line` behind it.

### 1.3 Work already landed on this branch — and why the roadmap must account for it

`autonomous-dev` is 25 commits ahead of `main`, and the most recent five are remediation of exactly the kind this roadmap sequences:

```
5560159  Split the tool grant's guarantees out of its scaffolding
767f1b4  Put verify_identity back in the tool grant floor
ae480ed  Redact tool-call audit rows once, where the row is written
fd855ca  Make the suite pass on a database nobody has touched by hand
5578cfd  Stop a narrowed card from crashing the call it answers
a65c76a  Make CI run at all, and gate what was already written
```

Two things follow. First, `ae480ed` ("**once**, where the row is written") is a canonicalization move of exactly the shape Wave 2 prescribes — the pattern is already understood and practised here, which materially lowers the execution risk of this roadmap. Second, and more sharply: **two commits were spent improving `grant.py` and neither wired it.** That is the failure mode this roadmap exists to correct. Refining an unadopted owner feels like progress and moves no production behaviour. Wave 2's acceptance criterion is therefore *importers*, never *quality of the owner*.

### 1.4 How to read the action tables

Every action carries the seven fields the brief requires. Their meanings here are specific:

- **Prerequisites** — what must be *complete and verified*, not merely started. A prerequisite of "—" means the action can begin today.
- **Affected modules** — the files a reviewer will see in the diff.
- **Blast radius** — measured where possible (call sites, importers, routes), not adjectival. `S` = one module and its tests. `M` = a subsystem. `L` = crosses subsystems. `XL` = touches a live borrower-facing path.
- **Behavioral risk** — the axis that matters most in a regulated system, and it is *not* the same as blast radius. Graded: **none** (provably no-op) · **cosmetic** · **internal** (observable only to operators/logs) · **user-visible** · **regulated** (could change who is contacted, when, or how much money moves — RBI/DPDP exposure).
- **Rollback** — what actually restores the previous state. `git revert` is only a real answer when nothing persisted; where a schema or an external side effect is involved, the honest answer is stated instead.
- **Validation** — the specific check that would prove the change safe, not "run the tests".
- **Atomic?** — whether the change must land as one indivisible commit. **Yes** means a partial application is worse than no application (the classic case: deleting N-1 of N duplicate rule copies leaves the divergence and removes the evidence of it).

A note on the grading of **behavioral risk = regulated**. This platform operates under the RBI Fair Practices Code (08:00–19:00 calling window), the DPDP Act (consent, purpose limitation, opt-out), contact-frequency caps and DND. An action graded *regulated* is not necessarily dangerous; it means it cannot ship on an ordinary review. It needs the shipping protocol in §8.
---

## 2. Findings from the direct thread

### D1 — `env_utils` already owns the environment question; eleven modules re-derive it, in two opposite directions

`backend/env_utils.py:36-49` is a canonical owner, with `__all__` (`:25-26`), and its docstring states the reason it exists: *"A second copy of the allow-list would drift, and the two keys must agree on what counts as production."*

It is used by exactly two callers (`agent_core/vault/seal.py:47`, `agent_core/skills/sign.py:38`). Eleven other production modules re-derive `APP_ENV` inline:

| module | line | default when unset |
|---|---|---|
| `actor_context.py` | `:55` | dev |
| `main.py` | `:204-205` | dev |
| `observability.py` | `:433` | dev |
| `payments.py` | `:40` | dev |
| `seed_postgres.py` | `:36` | dev |
| `seed_susanth.py` | `:28` | dev |
| `storage.py` | `:46` | dev |
| `usage_meter.py` | `:292` | **production** |
| `scripts/dial_test.py` | `:46` | dev |
| `scripts/seed_demo.py` | `:31` | dev |
| `env_utils.py` | `:38` | dev (the owner) |

**Two things follow, and the second is the finding.**

First, `usage_meter.py:292` defaults to `"production"` where every other site defaults to `"dev"` — deliberately (`:284`: `BILLING_ENV` wins so a sandbox tenant can be metered separately) but it means one missing variable is read as *dev* by ten modules and *production* by billing.

Second, and more consequential: **the two readings are logically opposite and both are live in the same process.**

- `env_utils.py:28-33` reads it the *safe* way — only an explicitly-named non-production environment (`NON_PROD_ENVS`) earns a development key, so `APP_ENV=staging` or a typo **raises**.
- `main.py:204-205` reads it the *unsafe* way — `_IS_PROD = _APP_ENV in {"prod","production"}`, so anything unrecognised is dev, and `APP_ENV=staging` **silently disables** the fail-closed controls.

The comment at `env_utils.py:28-32` shows the author knew both readings existed and chose the safe one for keys. Nobody went back and applied it to the other nine. So a staging deployment today gets: no dev signing key (correct, fails loudly) *and* authentication off (incorrect, fails silently). That is the whole thesis of this roadmap in eight lines of one file.

**Roadmap placement:** Wave 1 (adopt an existing owner). Blast radius: 11 modules, single-line change each. Behavioral risk: **regulated** — it changes which controls are active under any non-canonical `APP_ENV`, which is the point, and is exactly why it must ship deliberately rather than as a tidy-up.

### D2 — `agent_core/tools/grant.py` still has zero production importers (re-verified 2026-09-03)

Full-tree scan of `backend/**/*.py` for `tools.grant`, `tools import grant`, `ToolGrant`, `may_execute`:
- `agent_core/tools/grant.py` itself (definition)
- `tests/test_tool_grant.py`
- `tests/test_tool_grant_characterization.py`
- `tests/test_import_cycles.py:35` (a module-name string in a list)

Zero production call sites. Two commits on 2026-09-01 (`767f1b4` 21:16, `5560159` 21:41) improved the module without wiring it. ADR-0001 names it the one owner.

### D3 — The CI gate is stronger than the corpus implies, and it is the model for Wave 0

`.github/workflows/backend-pytest.yml` (landed `a65c76a`, 2026-09-01 15:21) runs: `ruff check .` before Postgres (deliberately, to fail cheap), applies `sql/*.sql`, `alembic stamp head`, a **bidirectional schema-drift check** (derives expected tables/columns from `op.create_table`/`op.add_column`, then `tests/test_schema_parity.py` catches the reverse), two scratch databases (parity + RLS), `scripts/seed_demo.py`, then `pytest -q` — with `requirements-voice.txt` installed *because* 26 test files import pipecat at module scope and *"skipping them here would leave the highest-risk code in the product as the only code with no gate on it."*

`frontend-typecheck.yml` runs `tsc --noEmit`, `vitest run`, and `npm run lint` (eslint + two hand-written design-scale scanners).

Two properties make this the template for every gate this roadmap adds:
1. **The drift gate is bidirectional and has a named incident behind it** — `idempotency_keys` was migration-only, so *"every 'idempotent' write silently duplicated."*
2. **The lint gate was introduced green, on purpose.** The workflow comment: *"Deliberately NOT `--max-warnings 0`: gate what passes today, then drive the count down. A gate introduced red is a gate people learn to ignore."* Every new gate below follows that rule.

Caveat: both workflows are `paths:`-filtered, so a change outside `backend/**` or `Habibi/**` (a compose file, a Dockerfile, a root doc) is gated by nothing.
---

## 3. The dependency lattice — what actually blocks what

This section is the spine of the roadmap. Everything else is scheduled around it.

### 3.1 A measurement correction that the series needed

Reports `05-dependency-graph.md` and `38-architecture-boundaries.md` disagreed about the size of the backend coupling knot — 05 said ~108–111, 38 said 76 — and neither said why. The dependency-order analyst reproduced both and found the cause: **they resolved `from pkg import sub` differently.**

| Resolver for `from pkg import sub` | Nodes | Eager edges | Coupling edges | Largest coupling SCC |
|---|---|---|---|---|
| **A.** edge → `pkg` (report 38's) | 265 | 410 | 883 | **76** |
| **B.** edge → `pkg.sub` (**used here**) | 265 | 443 | 953 | **107** |
| **C.** both edges (what CPython executes) | 265 | 490 | 1055 | **110** |

Neither prior report was wrong; they measured different graphs. This roadmap uses **B**, because A undercounts real module-to-module coupling (`agent_core/clerk.py:16` `from agent_core.treatment import enact` couples to `enact`, not to the barrel) while C's extra cycles are almost entirely `pkg.__init__ ↔ pkg.sub` self-reference, which CPython resolves through the partially-initialised module in `sys.modules` and which carries no cross-module meaning.

**The two numbers that matter, and they are good news:**

- **443 eager edges, and zero eager SCCs greater than 1.** Import time is a genuine DAG, nine condensation levels deep. Nothing in this repository has an import-order bug waiting to happen; `tests/test_import_cycles.py` defends that property.
- **953 coupling edges (eager + 510 lazy + 6 `TYPE_CHECKING`), three coupling SCCs: 107, 2, 2.** The 107-node knot has 309 internal edges — mean degree 2.9, so it is **dense, not chain-like**. That density is the reason no incremental untangling works.

The knot is not evenly distributed: `agent_core` 69/146 modules (47%), top-level 30/67 (45%), **`voice` 3/44 (7%)**. The voice runtime — the regulated channel — is almost entirely outside it.

### 3.2 The decisive negative result: there is no incremental path through `db.py`

Cut experiments on the coupling graph (delete a node and all its edges):

| Cut | SCCs > 1 | Largest |
|---|---|---|
| **baseline** | 3 | **107** |
| `db` — outgoing only (52 edges) | 7 | **17** |
| `db` — incoming only (101 edges) | 7 | **17** |
| `db` — lazy-outgoing only (44 of 52) | 6 | **50** |
| `db` lazy-out **+ the one edge `db → schemas`** | — | **17** |
| `azure_openai` | 3 | 99 |
| `bot_jobs` | 3 | 95 |
| `contact_policy` | 3 | 104 |
| `schemas` alone | 3 | 106 |
| **all seven "shared kernel" candidates at once**, keeping `db` | 3 | **100** |
| `db` + `azure_openai` + `llm_gateway.{client,canary}` | 6 | **5** |

Then the sharpest measurement in this roadmap — a **single-edge** sweep. The best removable edge in the whole knot is `db → promise_fulfillment` (`backend/db.py:5113`, lazy), worth 107 → 94. A greedy minimum-feedback-arc search, removing the locally-best edge twelve times in succession, only reaches **36**:

```
1   db -> promise_fulfillment        db.py:5113                107 -> 94
2   bot_jobs -> bot_runtime          bot_jobs.py:457            94 -> 83
3   db -> agent_core.treatment       db.py:1265                 83 -> 75
4   flow_graph -> agent_core.tools   flow_graph.py:814          75 -> 68
5   db -> agent_core.reco.policy     db.py:1221                 68 -> 62
…
12  agent_core.authority -> engine   authority/__init__.py:17   38 -> 36
```

**Twelve surgical edge removals buy 66%. One node-level intervention on `db` buys 84%.** This is the quantitative form of report 38's "it has to be cut whole," and it is why Wave 5 carves `db.py` by domain slice behind a re-export shim rather than nibbling at its edges: a half-finished edge-by-edge campaign leaves the codebase strictly worse — two persistence homes, and the knot still there.

### 3.3 The one line that decides whether the carve works

**New, and it is the most actionable single fact in this report.** Cutting `db.py`'s 44 lazy callbacks into the domain is **not sufficient** — it stops at 50, not 17. The remaining glue is a single *eager* edge, `db.py:24 → schemas`, which closes the loop through a **type** module:

```
db.py:24                    import schemas
schemas.py:10               from flow_graph import FlowGraph, FlowIssue, FlowValidation  # noqa: F401
flow_graph.py:814           from agent_core.tools import CATALOG      (lazy)
agent_core/tools/kb.py:121,396   import db
```

So `db → schemas → flow_graph → agent_core.tools → agent_core.tools.kb → db`. Removing `db → schemas` **alongside** the lazy callbacks is what takes 107 → 17. `schemas.py:10` is a hard sequencing item and it is one line.

### 3.4 The ordering constraints, ranked

Stated as "X must precede Y **because** <mechanism>". Only the first four are true blockers; the rest are recorded so they are not mistaken for blockers.

**C1 — Carving `db.py` must precede every other backend structural refactor.**
Mechanism: it is the sole articulation point of the 107-module coupling SCC. Removing any other single node moves the knot by ≤12; removing all seven plausible shared-kernel candidates (`capture`, `schemas`, `tenant_context`, `authz`, `visibility`, `usage_meter`, `actor_context`) *at once* moves it 107 → 100. Removing `db` moves it 107 → 17.
Evidence: `backend/db.py` — 18,087 lines, 440 defs, fan-in **101**, 8 eager out-edges, **44 lazy out-edges into the domain** (`db.py:1221, 1222, 1265, 5113, 5364, 9419, 9420, 10614, 12741, 12942, 13066, 13290, 13382, 13414, 14407, 14637, 17907, 17923, 17933, 17947, 17970`, …).

**C1a — `schemas.py` must stop importing `flow_graph` in the same change as, or before, the callback extraction.** Mechanism: import cycle through a type module (§3.3). Without it the carve stops at 50 and delivers a fraction of its value.

**C2 — A persistence seam must precede moving the transaction boundary, and both must precede any claim that a decision and its audit row are atomic.**
Mechanism: **transaction owned at the wrong level, over shared mutable module state.** `db.py:138` creates `engine: Engine = create_engine(…)` at import; there are **269 references to `db.engine` across 67 files**. **85 modules call `engine.begin()`/`engine.connect()` at 520 sites; only 16 modules accept an injectable connection.** The engines take `conn: … | None = None` and fall back to the global — `treatment/features.py:433-437`, `treatment/policy.py:393`, `treatment/contract.py:166`, `connectors/persist.py:259`, `cards/compile.py:817` — and `treatment/engine.py:257` states the consequence in its own comment: *"One connection for the whole read phase, then the log writes on its own."* You cannot pass a connection down until there is a seam to pass it through, and you cannot delete the fallback until every caller passes one.

**C3 — `agent_core/__init__.py` must be made lazy before `agent_core` can be imported by anything that must not touch Postgres.**
Mechanism: eager barrel re-export. `agent_core/__init__.py:6` eagerly does `from agent_core.deployment import load_active_bundle`, and `agent_core/deployment.py:11` eagerly does `import db`. **Importing the barrel to call `estimate_sentiment` opens a database engine.** The technique to fix it already exists in this repo — `agent_core/cards/__init__.py` uses PEP 562 with the failing chain written into a 25-line comment.

**C4 — Decoupling `azure_openai`/`llm_gateway.client` from the eval harness must precede any LLM-provider abstraction work — and it is blocked by nothing, so it runs in parallel with C1.**
Mechanism: `llm_gateway/client.py:92` lazily imports `llm_gateway.canary`, which at `llm_gateway/canary.py:21-22` *eagerly* imports `agent_core.eval.harness` and `agent_core.eval.run`; the harness reaches back through `cards.compile → skills.intersect → connectors.persist → agent_core → turn → understanding → azure_openai`. **The LLM client transitively depends on the Agent-Card compiler.** This is the only other single-node lever in the codebase: cutting either `azure_openai` or `llm_gateway.client` dissolves all 17 residual nodes.

**C5 — Wiring `agent_core/tools/grant.py` is NOT blocked by C1.** Mechanism: not a cycle — an *absent* edge. `grant.py` is 247 lines with fan-out 0 into the knot, so it can be wired at any time. Same for `rls.py` (single importer, `tests/test_rls.py:26`). **This is the finding that lets the highest-value regulated work happen first rather than last**, and it is why Wave 2 precedes Wave 5 in this roadmap.

**C6 — Frontend: domain types must leave `data/*-seed.ts` before the mock switch can be removed, and both before any generated-client work.**
Mechanism: a type that must move first. `src/types/` exports **0** types; `src/data/` exports **261** across 26 files; `src/api/` 225. `data/customer360-seed.ts` has fan-in **25**. `USE_MOCK` appears **378 times across 67 files**, 26 of them outside `api/`. **Deleting the mock branch deletes the module that declares `Customer`.**

**C7 — The seven package-façade self-cycles block nothing.** `treatment` (9), `agent_core` core (4), `authority` (4), `mcp_http` (3), `reco` (3), `live_qa` (2), `providers` (2) — each is `pkg/__init__.py` importing its submodules while submodules import the barrel. These are the only cycles CPython actually navigates at import time and it survives them via partial modules. A genuine parallel workstream, one team per package, no shared files.

**Checked and rejected as blockers.** `capture`, `contact_policy`, `authz`, `visibility`, `usage_meter`, `tenant_context`, `actor_context`, `agent_core.deployment`, `agent_core.context` — each is a *passenger* in the knot, not a cause: cutting any one moves the knot by ≤3 nodes, and all seven together move it 107 → 100. **Extracting a "shared kernel" first is a preference, not an ordering constraint.** This roadmap therefore does not schedule one.

### 3.5 The frontend is independent — with one constraint pointing the other way

There is no import edge in either direction; the two graphs resolve entirely within their own trees. The coupling is the wire, and it is unusually well contained: **286 HTTP call sites across 42 files, 40 of them in `src/api/`**, with exactly **two leaks** — `components/sandbox/inspector/TwinTab.tsx:23,26` and `routes/compliance.tsx:146`. Fixing three call sites in two files makes `src/api/` the sole wire boundary. On the backend side the wire also has one owner: all 312 route decorators are in `main.py`.

But the contract is asserted in both directions and checked in neither: ~144 of 312 backend routes declare a `response_model`, and on the frontend **one** file imports a runtime validator against **356 `as Type` casts**.

**The ordering consequence is the non-obvious one, and it sets the position of Wave 4:**

> Because the wire is unvalidated, a backend change that alters a response shape has **zero** static protection. Today those response shapes are assembled **by hand inside `db.py`** — the very file Wave 5 splits. Therefore **`response_model` coverage must be raised before `db.py` is carved**, or the carve silently rewrites the public API.

That is why API-boundary work (Wave 4) precedes domain extraction (Wave 5) in this roadmap, matching the brief's example ordering — but for a measured reason rather than a conventional one.

### 3.6 Minimum wave count, and what is genuinely parallel

From dependency order alone the backend needs **three** ordered stages, not more:

- **Zero-blast-radius work**, unlimited parallelism: 55 backend and 49 frontend modules with coupling fan-out 0. Their internals can be changed with no import-graph risk; only their signatures matter. The high-fan-in members are exactly the shared leaves that should be adopted *more*, not refactored: `env_loader` (fan-in 20), `env_utils` (18), `agent_core.platform_flags` (17), `agent_core.cards.schema` (15), `agent_core.treatment.actions` (14), `agent_core.skills.pack` (11), `pii_redact` (9), `money_inr` (7), `pg_errors` (4). Also here: the seven façade self-cycles (C7), and wiring `grant.py`/`rls.py` (C5).
- **The two node-level levers, runnable by two teams simultaneously.** Team A owns `db.py`, `schemas.py` and the 44 callback sites (C1 + C1a + C2). Team B owns `azure_openai.py:619`, `llm_gateway/client.py:92`, `llm_gateway/canary.py:21-22` (C4). The file sets are disjoint, and the SCC math composes: measured together they give a largest SCC of **5**, exactly the union of the independent results. A frontend team can run C6 alongside both with no shared file at all.
- **The residual loops**, which are *invisible until `db` is cut* — they are subsumed inside the 107-knot, so their membership and feedback arcs cannot be identified beforehand. Once cut, they are small, fully enumerated, and four teams can take them in parallel: the money loop (5: `payments → payment_events → promise_fulfillment → agent_core.clerk → treatment.enact`), `treatment.{models,rerank,scoring}` (3), `reco.{models,scoring,vectorize}` (3), `bot_jobs ↔ bot_runtime ↔ voice.persist` (3), `observability ↔ voice.admission` (2), `voice.bot ↔ voice.host` (2).

### 3.7 Fan-in hazards — where any change is expensive by construction

Eager fan-in in brackets is the number that matters: those importers break at *import time* on a signature change.

| Module | fan-in | eager | fan-out | in knot |
|---|---|---|---|---|
| **`db`** | **101** | 25 | 52 | yes |
| `contact_policy` | 21 | 6 | 4 | yes |
| `env_loader` | 20 | 19 | 0 | no |
| `azure_openai` | 19 | 6 | 7 | yes |
| `env_utils` | 18 | 17 | 0 | no |
| `agent_core.platform_flags` | 17 | 10 | 0 | no |
| `capture` | 15 | 1 | 1 | yes |
| `agent_core.cards.schema` | 15 | 7 | 0 | no |
| `agent_core.tools.catalog` | 14 | 7 | 1 | no |
| `agent_core.treatment.features` | 11 | 11 | 4 | yes |

`db.py`'s 25 **eager** importers must be reworked first inside Wave 5, because they cannot be relocated while `db` exists: `main`, `worker`, `bot_worker`, `bot_runtime`, `bot_tools`, `sandbox_runtime`, `ops_screens`, `kb_retrieve`, `provider_voice_sync`, `voice.persist`, `voice.call_export`, `work_runtime.adapter_pg`, and 13 under `agent_core/**` (`deployment.py:11`, `a2a.py:16`, `canary.py:12`, `cards/clone.py:15`, `connectors/{circuit.py:31, first_party.py:9, persist.py:13}`, `mcp_http/{auth.py:14, tasks.py:10}`, `providers/{factory.py:33, persist.py:22}`, `skills/persist.py:12`, `vault/persist.py:12`). The other **76 importers are lazy-only** and are cheap to redirect.

Frontend: `lib/utils.ts` **213**, `components/ui/lozenge.tsx` **107**, `components/ui/button.tsx` **89**, `api/config.ts` **68**, `components/shell/AppShell.tsx` 30, `data/customer360-seed.ts` **25**. Two of those are hazards for the wrong reason — a design-system primitive carrying domain vocabulary (`lozenge`), and a mock fixture carrying the domain model (`customer360-seed`).

And the reassuring one: **`main.py` has fan-out 78 and fan-in 0.** Its 5,448 lines and 312 route decorators can be split with *zero* import-graph consequence.
---

## 4. The seams — what exists to strangle through

**A refactor without a seam is a big bang.** Every action in this roadmap rides one of six mechanisms already proven in this tree; anything that rides none of them is named as a big bang and refused. That constraint, not architectural taste, is what makes this plan incremental.

### 4.1 The six proven seams

**S1 — Protocol + `x or Default()`** — *live, complete, and never exercised.*
Five `Protocol` classes, zero `ABC`s, in the whole backend: `treatment/features.py:397`, `reco/features.py:193`, `authority/features.py:87` (each a `FeatureProvider` with one `build`), plus `Recommender` at `treatment/scoring.py:183` and `reco/scoring.py:68`. The wiring is complete end to end — `provider: FeatureProvider | None = None` at the public entry (`treatment/engine.py:163`), threaded through `:230` and `:285`, defaulted at the leaf (`treatment/features.py:1308` `(provider or SqlFeatureProvider()).build(...)`, `authority/features.py:207`, `reco/features.py:700`). **No production call site passes `provider=`.** That is exactly what a strangler seam should look like *before* you use it: swapping the implementation touches zero call sites.

**S2 — Named registry with graceful degradation.** `treatment/scoring.py:591` `build_scorer(name) -> Recommender` and `reco/scoring.py:404`, selected by config (`reco/config.py:68`). Its docstring is the template: *"Resolve a scorer by name, degrading to the EV scorer at every step. An unknown name must cost lift and never availability."* A live, config-driven, fail-safe swap — the best model in the repo for introducing a second implementation of anything.

**S3 — Flag-selected adapter port.** `work_runtime/api.py:10-17`, `_adapter()` selecting on `platform_flags.temporal_enabled()`. **Incomplete** — see §6.11 below.

**S4 — Bottom-of-file re-export block. This is the one that matters most.**

```python
# db.py:18005-18024
from followups_db import ( ... 18 names ... )   # noqa: E402
```
```python
# followups_db.py:23-26
def _db():
    import db as d
    return d
```
with the contract written at `followups_db.py:4`: *"Imported at the bottom of db.py so call sites stay `db.*`."*

**Someone has already carved 18 functions out of `db.py` this way, and it shipped.** That single fact converts Wave 5 from a design question into the repetition of an existing, reviewed manoeuvre — and it is why this roadmap can schedule an 18,000-line file split at moderate rather than extreme risk.

**S5 — PEP 562 lazy package façade.** `agent_core/cards/__init__.py:52-68` — an `_EXPORTS` dict plus `__getattr__`, with `TYPE_CHECKING` re-exports at `:38-50` so type checkers still resolve, and a 24-line comment naming the exact `ImportError` chain it closed. The tool for a carve that would create a cycle S4 cannot break.

**S6 — String-keyed `importlib` registry — the process-boundary seam.** `agent_core/providers/registry.py:550-552` resolves `model.service_class` by string. This is how `agent_core/providers/fish_service.py` — which has a **module-level `pipecat` import at `:39-41`** — lives inside `agent_core/` without breaking the API image: **it has zero Python importers.** It is referenced only as the string `"agent_core.providers.fish_service.FishTTSService"` at `registry.py:413`.

### 4.2 Where a seam is missing — so the refactor would be a big bang

| Wanted change | Seam status |
|---|---|
| Second persistence backend / repository | **None.** `conn`-as-parameter is a *convention* across 74 modules, not an interface. **Do not attempt** (§6.2). |
| Swap the job queue to Temporal | **S3 covers 3 of 7 operations.** Live hazard — §6.11. |
| One owner for the Tool Grant | **The seam is written and unimported.** Landing it is an *import*, not a design. |
| Second outbound channel | Half-present: `treatment/enact.py` raises `NoExecutor("no_phone_on_file")` — naming a type that does not exist. |
| Runtime response validation in the frontend | `apiGet<T>` has no schema parameter (`api/config.ts:171`); adding one touches 221 call sites unless optional. |

### 4.3 The pipeline invariant is holding — and is narrower than stated

Re-measured: `treatment` **26/26** intra-engine edges respect stage order, `reco` 16/17, `authority` 6/8, `live_qa` 2/2, `compliance` 3/3, and **all five package façades withhold `enact`** (every `__all__` read). The three apparent inversions are a ranking artefact — `matrix.py` is a pure decision table, not a late stage.

The refinement matters for every action below. The load-bearing invariant is not "ordering of gates" but **"the last stage cannot widen the permitted set."** Enforcement is by *data*, not by import path (`authority/enact.py:35-37` gates on `config.mode()` plus a required `decision_id`). The consequence for refactoring:

> The thing to protect is not the module boundary — it is the **argument threading**. `provider`, `conn`, `arm` and `mode` pass down through the stage functions. **A refactor that hoists any of them to module state breaks the invariant silently**, with no import error and no failing test.

That single sentence is the most important safety rule in this roadmap, because C2 (making `conn` required) and Wave 5 (the carve) both operate directly on it.

**Where the pipeline model *is* violated: nowhere inside the four engines — at their inputs.** `db.py` calls into `agent_core.treatment` and `agent_core.authority.enact` (9 import sites in the treatment-holds section alone, `db.py:17538+`). The ordering holds; what does not hold is that the pipeline sits *below* persistence in some places and *above* it in others.

---

---

# WAVE 0-A — Before any refactor: can we ship it, and can we undo it?

**This track was not in my original plan and it displaces the test work as the true first move.** The reason is a single measured fact:

> **There is no deployment pipeline, no release identity, and no rollback path.**
>
> - `.github/workflows/` contains exactly two files, both of which only *test*. No deploy, no image build, no publish, no environment promotion.
> - `git tag` returns **zero tags**. Images are `collections-api:local` and `collections-voice:local` (`docker-compose.yml:77,138,167,191,225`). No registry, no digest, no version.
> - The frontend has **no Dockerfile anywhere in the tree**. Its deploy path is undefined.
> - CI never runs `npm run build`, so a build-breaking frontend change is not caught.
>
> **Therefore `git revert` is not a rollback mechanism in this repository.** Rolling back today means `git checkout <sha>` + `docker compose build` + `up -d`, against a database that has already migrated forward.

Every risk grading in this roadmap is shaped by that. A refactor is only as safe as the ability to undo it, and right now that ability does not exist. **Wave 0-A precedes Wave 0-B.**

## P1 — Give a deploy an identity and rollback a procedure · low cost · **blocks everything**

Tag images by commit SHA, push to a registry, and write down the two-command rollback *including* the database-state caveat. Nothing else on this list is safe without it. Blast radius **S**, behavioral risk **none**, and it is the highest-leverage action in the entire document.

## P2 — Make behaviour visible before changing behaviour · **regulated sub-gate**

`observability.setup_logging()` (`observability.py:469-486`) **returns immediately unless `LOG_FORMAT=json`** (`:404-410`), and `backend/.env` contains no `LOG_FORMAT` line at all — verified in both `.env` and `.env.example`. `main.py:426` calls it, so in the **api** container the root logger gets **no handler**: INFO is discarded and WARNING+ falls to `logging.lastResort` with no timestamp, level, or logger name. **`voice_insurance`** is worse — `log_bridge.install()` is called in exactly one place in the tree (`voice/bot.py:2618`), and `voice/workers/insurance.py` never calls it. `worker.py:29` and `bot_worker.py:48` do call `basicConfig`, so the defect is scoped to those two services.

The codebase documents this against itself, at `voice/call_trace.py:112-122`: *"WARNING rather than INFO on purpose… on this deployment the root logger sits at WARNING — an INFO trace is a trace that is not there."*

Also: **only 6 Prometheus metrics exist** (`observability.py:76,83,91,97,104,110`), none covering `contact_policy.admit()` outcomes, consent changes, payment writes, or dial suppressions — and **nothing scrapes `/metrics`** (no prometheus service among the eight compose services).

> **A shadow run you cannot read is not a shadow run.** Wave 3's entire shipping protocol depends on this being fixed first.

**⚠️ Blocking sub-gate — do NOT simply set `LOG_FORMAT=json`.** `pii_redact.py:22-58` matches phone numbers only with a literal `+91` prefix, while `customers.phone_primary` stores bare digits. Turning on the JSON formatter would create an indefinitely-retained, well-indexed store of borrower phone numbers. **Fix the redactor first** — and note the scrubber currently *fails open* at `observability.py:349-350`.

## P3 — Decide which of the THREE schema sources is authoritative

Not two — three:

| Source | Status |
|---|---|
| `backend/sql/*.sql` (24 files) | Authoritative current shape; CI applies it then `alembic stamp head` |
| `alembic/versions/` (102 revisions) | Deltas for existing DBs only; baseline `20260721_0001` is `pass` |
| **Python** | Now authoritative for the outbound eval suite — `agent_core/eval/fixtures.py:195-215` |

**And there is a live, verified break.** `alembic/versions/20260822_0096_outbound_eval_suite.py:7` says it *"Mirrors sql/14_agent_factory.sql (the CHECK) and **sql/23_outbound_evals.sql**"* — **`sql/23_outbound_evals.sql` does not exist.** `fixtures.py:207-211` states the consequence: *"on CI, and on any pilot provisioned from sql/\*.sql, the suite is absent entirely and `OUTBOUND_EVAL_GATE_ENABLED=true` refuses every outbound publish."* And `backend/.env:405` sets that flag **true** (`.env.example:606` ships `false`).

**A fresh install provisioned from `sql/` cannot publish outbound at all.** Create the file or delete the reference — but decide.

## P4 — Seed `policy_rule_sets`, or accept that policy-as-data is dead · **regulated**

`INSERT INTO policy_rule_sets` appears in exactly two places: `scripts/seed_policy_rules.py:158` and a test. **The script is invoked from nothing** — not CI, not `seed_demo.py`, not a migration, not `sql/`.

So on every real install `policy_rules.resolve()` returns `EMPTY` and every regulated decision runs on hardcoded fallbacks — and one of those fallbacks is not a fallback at all:

> **`contact_policy.py:508-515` — *"Absent one, only voice is bounded."* With no published rule set, WhatsApp, SMS and email have no calling-hour bound whatsoever.**

Worse, `policy_rule_sets` has an `effective_to` column (`sql/03_consent.sql:112`) and `resolve()` filters on it (`policy_rules.py:343-344`). **A published rule set that expires with no successor silently reverts the entire platform to the hardcoded fallbacks** — and per P2, nothing logs it. This is the same failure mode as the expired Fish model below, aimed at a regulator.

## P5 — Provision a `NOBYPASSRLS` role and turn RLS on · **the cheapest high-value prerequisite in the repo**

It is nearly ready, and this corrects a pessimistic reading elsewhere in the series. `rls.py` derives policies from the FK graph and provides `apply()` (`:365`), `enable()` (`:417` — in-transaction with a row-count check and rollback), `disable()` (`:` leaves policies installed), `status()` (`:545`), and `provision_role` (`:620`, issuing `ALTER ROLE … NOSUPERUSER NOBYPASSRLS`). `tests/test_rls.py` has 9 derivation tests **plus 6 enforcement tests**, and CI already sets `RLS_DATABASE_URL`. That is real coverage on a real mechanism.

What is missing is only the switch: **`ENABLE ROW LEVEL SECURITY` appears in zero `sql/*.sql` files and zero migrations.** Meanwhile the hand-written tenant predicates number **290** (`db.py` 70, `followups_db.py` 28, `ops_screens.py` 18, `main.py` 13, long tail) — measured this session; prior work said ~248 with a different regex, same order of magnitude.

**Why this belongs in Wave 0 rather than Wave 7:**

> Today, dropping one `WHERE tenant_id = :t` during a refactor of a 290-site surface returns another tenant's borrower records **with a 200**. With RLS on, the identical mistake returns **zero rows** — a visible outage instead of an invisible breach.

It converts the single most dangerous class of refactor error in this codebase from silent to loud, and **it is reversible** (`python scripts/rls.py disable`), which almost nothing else here is.

**Sub-gates:** do not enable RLS until `provision-role` has run — `rls.py:19-23` and `:446` refuse for exactly this reason, and enabling as a BYPASSRLS role *looks like it worked and changes nothing*. And note that RLS-on makes the process correctly single-tenant; it does **not** make the API multi-tenant, because the tenant reaches Postgres as a **libpq startup parameter baked from the process-level `TENANT_ID`** (`db.py:138-149`, `.env:141 TENANT_ID=hdfc.retail`). The correct order is: provision role → `apply` → `enable` → per-request tenant binding → multi-tenant.

## P6 — Fix `APP_ENV` and config-load ordering together

Adds to finding D1 (§2). `main.py:204-205` reads `APP_ENV` at **module scope**, and **`main.py` never calls `load_env()`** — verified by a whole-tree scan of call sites; `db.py:64` explicitly documents *not* calling it at import. The hardening gate is a no-op outside prod (`main.py:400-403`, `if not _IS_PROD: return`). And config is read at **198 `os.getenv`/`os.environ` sites, 149 distinct variable names, across 78 files**. `env_utils.py` is a 75-line helper, not a config module — **there is no single place a refactor can move a config read to.**

**Why this gates Wave 5:** moving a function moves its `os.getenv` call, and with a lazy `load_env()` the *timing* of that read is load-bearing.

## P7 — Pin the Python dependency graph

- `requirements.txt` is mostly `==` but carries four ranges: `twilio>=9.0,<10` (`:13`), `redis>=5.0,<6` (`:14`), `websockets>=12.0,<16` (`:15`); `requirements-mcp.txt:6` is `mcp>=1.2.0`, fully unbounded.
- **`Dockerfile:41` installs `requirements-voice.txt` on top of the base install with no `-c requirements.txt`.** So pipecat's transitive graph can freely upgrade or downgrade `httpx`, `openai` and `websockets` **inside the voice image only**. **The api image and the voice image, built from one commit, do not have the same library versions — and nothing records what either got.**
- No lockfile, no hashes, no `requires-python`. `.venv` is 3.14.3; the image and CI are 3.12.

---

---

# WAVE 0-B — Make the ground safe: can we tell if we broke it?

**Duration: ~13 developer-days. Nothing in Waves 1–7 is safe until this lands.**

In most modernization plans Wave 0 is a formality. Here it is the majority of the risk reduction in the entire programme, for a reason that is measured rather than asserted: **of the nine canonicalization targets this roadmap schedules, only three have a test that would fail if their behaviour changed.** Consolidating the other six today would be *unfalsifiable* — you could not tell a successful consolidation from a regulatory incident.

## W0.0 The safety net, as it actually is

| Layer | Files | Test functions |
|---|---|---|
| Backend total | **186** `test_*.py` + `conftest.py` | **2,431** |
| — HTTP (constructs `TestClient`) | **16** (8.6%) | 282 |
| — DB-integration (`db_tx`) | 78 | 1,114 |
| — Pure, in-process | 101 | 1,214 |
| Frontend | **11** `*.test.ts` | 83 `it()` cases |
| Frontend component / hook / snapshot | **0** | 0 |
| E2E (Playwright / Cypress / backend journey) | **0** | 0 |
| Voice full-turn evals | 15 authored, **6 in the manifest**, run by **no CI** | — |

**The counter-intuitive result that should reorder anyone's instincts:** the backend has 186 test files and 2,431 test functions; the frontend has **11 test files for 474 modules**, no jsdom, no Testing Library, and no MSW. **Frontend refactoring in this repo is markedly less protected than backend refactoring** — the opposite of the usual assumption, and the reason Wave 6 sits late rather than early.

**53 "tests" are refactor-hostile.** Across 27 of 186 files, assertions are made against *source text* (`inspect.getsource`, `ast.parse`, `read_text().toContain`). They fail on a harmless reformat and pass on a behaviour break — the exact inverse of refactor protection. The worst concentration is 11 in `test_voice_session_teardown.py`, sitting on `voice/bot.py`, the file most in need of splitting. **Refactoring the voice runtime is actively punished today.**

## W0.1 — Make red mean red · 0.5 day · **blocks everything**

**The suite is red, and there is a second bomb on a timer that no prior report has found.**

1. **Already fired.** `tests/test_contact_policy.py:287` passes `promised_date="2026-09-01"` and asserts `result.ok` at `:292`. `agent_core/tools/domain.py:724-725` refuses any past date with `promise_date_in_past`. Today is 2026-09-03, so `test_due_reminder_blocked_when_capped` has been failing since **2026-09-02**.
2. **Fires in twelve days — new in this report.** `tests/test_voice_write_idempotency.py:36` defines `PROMISE_DATE = "2026-09-14"`, used at `:134, :147, :191, :249, :331-338`, reaching the same past-date guard through `voice/tools.py:1301`. **On 2026-09-15 that file — 508 lines, 8 tests — starts failing.** Report 22 calls promise→fulfilment *"the best journey in the repo"*. The repo's strongest coverage is on a timer.

Both are stale-fixture rot, not real defects. The consequence is what matters: **with a red baseline, "did my refactor break it?" is unanswerable**, and a team learns to skim past red.

**Action:** convert both to relative dates (`date.today() + timedelta(...)`, the convention the rest of the suite already uses), then add a check that fails on any literal date in `tests/` — otherwise this recurs every quarter.

| | |
|---|---|
| Prerequisites | — |
| Affected | `tests/test_contact_policy.py`, `tests/test_voice_write_idempotency.py`, one new lint check |
| Blast radius | **S** — tests only, zero production files |
| Behavioral risk | **none** |
| Rollback | `git revert` |
| Validation | the suite goes green; re-run with a faked future clock |
| Atomic? | No — two independent fixes |

## W0.2 — Measure before arguing · 1 day

There is **no coverage measurement anywhere**: no `pytest-cov`, no `.coveragerc`, no `--cov`. Every "no test reaches this line" claim in this roadmap and in report 22 is **call-graph-derived, not measured**.

**Action:** add `pytest-cov` and `--cov=. --cov-report=xml` to `backend-pytest.yml`. **Set no threshold yet** — publish the number. Run `pytest -rs` once and publish the real skip count (116 `pytest.skip()` sites across 55 files, ~95 phrased *"no X seeded"*; report 22 estimates 436 skippable tests, 17.9%).

This is one line of CI, and it converts the blast-radius ranking below from a well-supported estimate into a fact. Behavioral risk: **none**. Follows the repo's own rule — introduce the gate green, then ratchet.

## W0.3 — Assert the seed floor · 0.5 day

Up to 284 tests are conditioned on seeded rows, and **nothing asserts the seed has content**. One test that fails when `customers`, `accounts`, `interactions`, `products` or `leads` is empty converts that many silent skips into one loud failure. The team already knows the pattern — `conftest.py:146` reads `assert packs, "…these tests would go vacuous"`; it simply was never applied at the seed level.

**Unlocks:** trust in 1,114 of 2,431 test functions. Blast radius **S**, risk **none**.

## W0.4 — A committing fixture · 2 days · **unlocks every concurrency question**

`conftest.py:47-58`: `db_tx`'s `_EngineProxy.begin()` returns a SAVEPOINT on one shared connection (`:23-31`), and `connect()` hands back that same connection and refuses to close it (`:37-39`). Two `begin()` blocks are always mutually visible.

**Concurrency is therefore structurally untestable under the standard fixture.** Only two test files use `threading` at all, and both escape the fixture by hand. Consequences: the ~16 `SKIP LOCKED` claim paths, the idempotency advisory lock at `db.py:702-707`, and the weekly-cap race at `contact_policy.py:971-979` are all unreachable.

**Action:** add `db_real` beside `db_tx` — real pooled connections, real commits, explicit cleanup. `test_job_claim.py:38-50` and `test_voice_session_store_contention.py` already do this by hand; the pattern needs promoting, not inventing. Blast radius **S** (test infrastructure), risk **none**, but it gates every concurrency refactor in Waves 3 and 5.

## W0.5 — Pin the seven unreached refusal branches · 1.5 days · **regulated**

`contact_policy.py` defines twelve refusal reasons. **Five are asserted as an outcome the engine produces; seven appear only as members of a policy set** — including `customer_dnd`, `channel_dnd`, `channel_expired`, `cooling_off`, `weekly_cap`.

**And the gate's own suite disarms the rules it is testing.** `test_contact_policy.py:57-70` (`_prep`) sets `dnd = false`, `dnd_registry = false`, `allowed_days = NULL`, `allowed_hours = NULL` **for every DB test in the file** — verified. `_prep` also sets weekly = 8 against daily = 3, so the daily cap always trips first and **the weekly cap can never fire**.

> Today, **seven of twelve statutory refusal branches could be deleted with the suite green.**

**Action:** `contact_policy._veto` takes a plain dict, so these are pure unit tests. Assert the *emitted reason* for each: DND (`:504`), channel DND (`:299`), expired consent (`:301`), cooling-off (`:589`), weekly cap (`:594`), unreadable consent (`:597`), disallowed window. **And change `_prep` to stop nulling the DND and window columns** — otherwise the new tests sit beside a fixture that disarms them.

| | |
|---|---|
| Prerequisites | W0.1 |
| Affected | `tests/test_contact_policy.py` (+ new pure-unit file) |
| Blast radius | **S** — tests only |
| Behavioral risk | **none** to production; but this is the gate on **regulated** work in Wave 3 |
| Validation | mutation check — break each branch by hand, confirm exactly one new failure |
| Atomic? | No; one branch per commit is better |

## W0.6 — Close the capture↔enforcement seam · 1 day · **regulated**

`db.opt_out` (`db.py:6754`) — the DPDP opt-out writer — **is called by no test.** Every opted-out borrower in the suite is fabricated by raw SQL (`test_contact_policy.py:190-200`). So enforcement is tested against a hand-built *imitation* of what the writer is believed to produce, and capture and enforcement never meet in one process.

**Action:** one test that calls `db.opt_out` and then asserts `contact_policy.admit` refuses. **Unlocks** consolidating the three drifted DND definitions (`contact_policy.py:504`, `agent_core/compliance/context.py:113`, `db.py:2313`).

## W0.7 — A composition test for the outbound gate · 2 days · **unlocks the highest-value refactor**

The regulated ordering is `reserve → admit → suppress → place`. Every *piece* is tested — `admit` (`test_contact_policy.py:108`), `suppress` (`test_outbound_attempts.py:121,146,332,604`), `place` (`test_place_contract.py`, 7 tests including "database dies after the dial" and "a programming error is re-raised"). **The composition is tested at zero sites.**

And the two nearest suites are actively disarmed:
- `test_cadence_pause_and_strand.py:50-55` monkeypatches `contact_policy.admit` to **always allow**, for the whole 407-line file.
- `campaigns.process_one` is asserted only by an `inspect.getsource` substring match.

**Action:** execute `campaigns.process_one` for real (delete the source-text assertion at `test_outbound_studio_bindings.py:110`); add one test to `test_cadence_pause_and_strand.py` that lets the real gate run; then a parameterised contract test across the call sites — each must reserve, admit, suppress on refusal, and place only on allow.

| | |
|---|---|
| Prerequisites | W0.1, W0.5 |
| Affected | 3 test files + 1 new contract test |
| Blast radius | **S** — tests only |
| Behavioral risk | **none** to production; gates the **regulated** consolidation in Wave 3 |
| Validation | the contract test must fail when a call site's order is deliberately swapped |
| Atomic? | No |

## W0.8 — A backend type gate · 2 days to introduce, then ratchet

`backend/ruff.toml` sets **no `select`**, so CI's `ruff check .` runs ruff's defaults: E4/E7/E9 + F. **Pyflakes-grade.** It catches an undefined name; it does not catch a wrong type, an unused argument, or a dead branch. There is **no mypy and no pyright** — verified: no `mypy.ini`, no `pyrightconfig.json`, no `[tool.mypy]` (`backend/pyproject.toml` contains only a `[tool.vulture]` block), and neither is in `requirements.txt`.

Meanwhile `tsc --noEmit` with `strict: true` is the single strongest gate in the repository — **and it covers the frontend only.**

**Action:** add mypy (or pyright) at `--ignore-missing-imports`, **error-on-new-code only**, before the Postgres steps (ruff is already placed there deliberately, so a lint failure costs ten seconds instead of ninety). Report 28 measured ~4,800 diagnostics latent under a wider rule set — which is exactly why this must be introduced green and ratcheted, per the repo's own stated rule.

**Unlocks:** every signature change and every module split — i.e. all of Wave 5. Cheapest broad protection available on the backend.

## W0.9 — Frontend: the two free wins · 1.5 days

`src/api/config.ts` (317 lines) and `src/lib/authority-policy.ts` are pure and run under the existing `environment: "node"` vitest config **with no new dependency**. `config.ts` alone encodes three documented past bugs (`:71-78`, `:88-110`, `:127-146`) plus the SSE parser at `:268-317`, and has **no test**. Neither does `src/api/authority.ts` (508 lines) — the money surface.

**Action:** test `config.ts` and `authority-policy.ts`; pin `authority.ts` the way `contact-policy.ts` is already pinned in the same directory. Then replace or delete the two source-grep suites (`api/outbound.test.ts`, `routes/agent-studio.skills.index.test.ts`).

## W0.10 — Cross-language equivalence · 1 day · **regulated**

Several rules exist once in Python and once in TypeScript, with **nothing comparing them**:

- **RBI window:** `RBI_VOICE_START = 8` (`contact_policy.py:69`) and `const RBI_VOICE_START = 8` (`contact-policy.ts:90`). Both suites pin their own copy well — `test_contact_policy.py:160-184` and `src/api/contact-policy.test.ts:58-98` (which even chooses UTC instants so the *borrower's* hour lands on the boundary). **Both pass if one changes.**
- **Dispute SLA — already divergent, and both suites are green.** Backend uses **48 hours** (`test_dispute_sla.py:36-85`); frontend uses **40** (`src/data/dispute-sla.test.ts`).

**Action:** emit the backend's policy constants as a generated JSON fixture; have vitest assert the TS ports match. **Unlocks** every "one rule, two languages" consolidation in Wave 3.

---

### ⚠️ The trap that must be written into Wave 3's brief now

**The RBI calling window (08:00–19:00) and the preferred contact window (09:00–20:00) are DIFFERENT RULES.** `contact_window.py` pins `DEFAULT_START_HOUR == 9`, `DEFAULT_END_HOUR == 20`, `DEFAULT_WINDOW == "09:00-20:00 IST"` (`test_contact_window_shared.py:54-57`); `contact_policy.py:69-70` pins 8 and 19. They are not two copies of one rule and **merging them would be a regulatory defect introduced by a tidy-up.** A canonicalization pass that pattern-matches on "hour window" will do exactly this.

---

## Wave 0 exit criteria

Wave 1 may not begin until all of these are true:

1. `pytest -q` is **green** in CI, and a coverage number is published.
2. `pytest -rs` skip count is published and the seed floor is asserted.
3. `db_real` exists and at least one contention test uses it.
4. All twelve `contact_policy` refusal reasons have a behavioural assertion, and `_prep` no longer nulls the DND and window columns.
5. `db.opt_out → admit` is covered end to end.
6. The outbound gate composition has a contract test that fails on a deliberately swapped ordering.
7. A backend type gate runs in CI, green.
8. `api/config.ts`, `authority-policy.ts` and `authority.ts` have tests.
9. A cross-language constant fixture exists, and the dispute-SLA divergence (48 vs 40) has been *decided* — not silently unified.
---

# WAVE 1 — Dead-code verification and deletion

**Placed here, immediately after the baseline, for the reason the brief's example suggests — deleting code removes work from every later wave. That reasoning holds for the frontend and fails for the backend, and the difference matters enough to state up front.**

## 1-0 The escape-hatch audit, done first

Nothing may be called dead in this repository until the dynamic-reference hatches are enumerated, because a wrong deletion here is a production outage. They were enumerated exhaustively:

- **Six dynamic-import sites in the backend, all with enumerable targets**: `agent_core/cards/__init__.py:71-79` (PEP 562, fixed `_EXPORTS` dict at `:55-66`), `providers/factory.py:110-118` and `providers/registry.py:552` (`service_class` strings), `treatment/enact.py:657-665` (names an *external* module — no in-repo target), `voice/bot.py:2555-2570` (a literal tuple, all already reachable), and a `find_spec` probe in a script.
- **`getattr(obj, var)` appears 9 times in non-test backend code and every one is attribute-level.** `globals()[...]` appears exactly once, inside the cards memoization. **There is no module-level function dispatch by string.**
- **Frontend: `import.meta.glob` sites = 0.** `components.json` has `"registries": {}`. All **43** route files appear in `routeTree.gen.ts` — **no orphan route files**. The two Pipecat SDKs reach the graph through dynamic `import()`.

> **Conclusion: module-level static analysis is sound in this backend.** That is an unusual and valuable property, and it is what makes this wave safe to execute at all.

One correction to the corpus while here: the "~897 lazy imports" figure is an undercount. There are **2,131 function-local import statements**, and they are all real graph edges — which is *why* backend reachability is 255 of 266 modules rather than far lower.

## 1-1 The honest payoff — and the expectation to reset

| | Frontend | Backend |
|---|---|---|
| Provably dead files | **29** (2,843 lines) | 0 |
| Provably dead symbols | 32 exports | **18** (158 lines) |
| Removable dependencies | **22 npm** | **0 proven** |
| Dead feature flags | — | **1** (`AGENT_CARDS_ENABLED`) |
| Commented-out code blocks (4+ lines) | **0** | **0** |
| Unreferenced database tables | — | **0 of 171** |

That is **~2.9% of `Habibi/src`** and **~0.08% of the backend**. **The backend is genuinely lean; a roadmap must not promise otherwise.** And this codebase does not have a commented-out-code problem in either tree — worth stating so no later wave budgets for one.

## 1-2 The finding that corrects the brief's implied ordering

> **Deleting dead code does NOT pre-pay for the canonicalization wave in this repository.**
>
> Checked directly against the canonicalization targets: **all of the live Tool Grant formulas sit in reachable modules** — `skills/intersect.py`, `voice/tools.py:80-93`, `flow_graph.py:773`, `cards/compile.py`. The fifth copy, `grant.py`, is the intended *destination*, not a duplicate to reap. **Anyone hoping deletion shrinks Wave 3 should be told no.**

**Where deletion genuinely does eliminate later work — and it is substantial:**

1. **The shadcn deletion kills a whole wave's worth of frontend remediation.** Reports 27, 29 and 30 all take `components/ui/*` as in-scope surface. **22 of those files are dead**, including the six largest: `chart.tsx` (331), `carousel.tsx` (240), `menubar.tsx` (224), `context-menu.tsx` (186), `calendar.tsx` (177), `form.tsx` (171). Any accessibility remediation, token migration or variant codemod scoped to `components/ui/` **must be re-scoped after this deletion.** Note in particular that report 30 names `ui/form.tsx` as a correct primitive with **0 importers** — it is not an adoption candidate, it is dead.
2. **`recharts` removal deletes a charting decision from Wave 6 entirely.** The live charts are hand-rolled SVG; `recharts` exists only to satisfy the dead `ui/chart.tsx`. There is no "consolidate on one chart library" problem — there is one library and it is already gone.
3. **`hooks/use-mobile.tsx` turns a three-way reconciliation into a one-line inline.** Reports 06 and 09 both name three breakpoint implementations; one of the three is dead with zero consumers.

## 1-3 The four classifications

**(a) PROVABLY DEAD — safe to delete.** All frontend. 29 files, 2,843 lines, ~35 lines of CSS.

- **22 `components/ui/*.tsx`** — `aspect-ratio, avatar, breadcrumb, calendar, card, carousel, chart, context-menu, drawer, form, hover-card, input-otp, link, menubar, navigation-menu, pagination, progress, radio-group, scroll-area, toggle-group, toggle, tooltip`. `toggle.tsx` is imported only by `toggle-group.tsx:8`, which itself has zero importers — **a closed two-node dead cluster**. `card.tsx` and `tooltip.tsx` are new finds; report 07 missed both.
- `components/brand/BigBoundMark.tsx` + the `.bb-mark` rules at `styles.css:1638-1674`.
- `components/documents/StatusPill.tsx` — zero importers; `ExportAuditLog.tsx:95` defines and uses its own local `StatusPill`.
- `components/records/index.ts` — a barrel with **zero** matches for `"@/components/records"`, while its three members are deep-imported by 10+ consumers.
- `components/floor/AlertLane.tsx`, `components/floor/CallTile.tsx` — `routes/floor.tsx:5-11` imports 7 of the 9 other components in that directory; these two were superseded by `PriorityLane` and `LiveTable`.
- `components/sandbox/ScenarioList.tsx`, `hooks/use-mobile.tsx`.

**(b) DEAD-BUT-UNPROVABLE-STATICALLY — name the evidence that would settle it.**

| Unit | The check that decides it |
|---|---|
| `backend/provider_voice_sync.py` (364 lines) | It has an operator CLI at `:357-364` and nothing in the repo runs it. Ask operators; then `SELECT provider, count(*) FROM tts_voice_catalog GROUP BY 1` — **if only Azure rows exist, it has never been run, and the Voice tab's Cartesia/Deepgram/ElevenLabs/Fish chips are empty by construction** |
| The 26 backend routes with no matched frontend caller | Access logs or a per-route counter for one week. **This is a traffic question, not an import question** |
| `voice/flows.py` legacy/hub builders | Read the deployed `VOICE_FLOW_GRAPH` (default `auto`) and any sandbox `flowGraph` overrides |
| Anything named by a tenant DB row | One `SELECT DISTINCT service_class FROM provider_bindings`, and the equivalents for connectors and `prompt_versions.flow` node keys |

**(c) ORPHANED-BUT-INTENTIONAL — adopt or retire by decision; never silently reap.**

- **`agent_core/tools/grant.py`** (247) — the accepted-ADR-0001 owner. **Deleting it makes the modernization worse.** It is the *target* of Wave 3, not its subject. **ADOPT.**
- **`backend/rls.py`** (633) — inert, not dead. Its docstring at `:19-23` explains the app connects as a `BYPASSRLS` role and `enable()` refuses in that case. Deleting it deletes the only designed answer to ~290 hand-written tenant predicates. **ADOPT (Wave 0-A P5) or record an ADR accepting hand-written predicates forever.**
- **`voice/node_contracts.py`** (51) — referenced only by a test, but it encodes a live invariant (a node whose exits were all dropped by the grant filter hangs the call) and the test is what enforces it. **Test-only ≠ dead.** Keep.
- **`voice/spike.py`** (329) — a manual probe documented in `voice/SPIKE_NOTES.md:17-18` and granted an E402 exemption in `ruff.toml:14`. An explicitly-kept experiment; product decision.

**(d) NOT DEAD — false positives disproved.** `providers/fish_service.py` (string-loaded via `registry.py:413`); the three eager re-export barrels `agent_core/{eval,vault,skills}/__init__.py` (Python executes them on any submodule import — **live code with zero graph edges**); `worker.py`, `mcp_server.py`, `voice/workers/insurance.py` (compose commands); `treatment/ope.py` (592 lines, imported by a script and a test); all 16 `grade_*` functions in `agent_core/eval/graders.py` (registered in a dict at `:406` and dispatched by string); all 43 route files; `tailwindcss`/`tw-animate-css` (`@import` at `styles.css:1,3`); `src/server.ts` (`vite.config.ts:11`); and all 171 database tables.

## 1-4 Deletion mechanics

| Batch | Prerequisites | Blast radius | Behavioral risk | Rollback | Validation | Atomic? |
|---|---|---|---|---|---|---|
| **1 — shadcn kit** (22 files + 18 npm deps) | A product decision that "keep the kit for future components" is *not* the policy | **none** — zero importers, and `"sideEffects": false` already tree-shakes them, so **the shipped bundle does not change** | **none** | `git revert` + `npm ci` | the exact `frontend-typecheck.yml` matrix: `tsc --noEmit`, `vitest run`, `npm run lint` | **Yes** — wrapper + its exclusive dep + lockfile in one commit, or `npm ci` still pulls Radix packages nothing imports |
| **2 — orphan components** (7 files + CSS) | For `AlertLane`/`CallTile`/`ScenarioList`, one question to the feature owner: superseded, or is a redesign mid-flight? Git history favours superseded, but that is inference | none | none | trivial | same matrix | **Delete `BigBoundMark.tsx` and `styles.css:1638-1674` together** — separately, the CSS becomes an unattributable orphan nobody will dare remove |
| **3 — backend micro-deletions** (18 symbols, 158 lines) | For the flag only: `platform_flags.py:1-4` states the flag list is a contract, so removing a name edits `tests/test_platform_flags.py` and `.env.example:309` in the same commit | S | **Leave `rls.py:327 weak_policies` alone** — deleting an unused *safety diagnostic* on a currently-inert operator surface is a different decision from deleting an unused helper | trivial | `pytest -q` (note `ruff` at defaults will **not** catch a missed reference to a deleted public name) | **No** — one commit per module, so `git bisect` stays useful |

Among the 18 backend symbols, two are worth naming because they are evidence of an unfinished thought rather than clutter: **`outbound.py:178 DialRefused`** — an exception class that is **never raised and never caught** — and `capture.py:1635 record_offer_suppressed` (23 lines). A further 12 symbols are **test-only**, which is a distinct and mostly legitimate category (`providers/pool.py:423 reset_pools`, `voice/admission.py:263 reset_for_tests`, `authz.py:652 invalidate_permission_cache`) — test seams, not dead code.

Also removable: the `[tool.vulture]` block in `backend/pyproject.toml` (19 lines) configures a tool that **is in no requirements file** — dead configuration.

**Backend dependencies: none proven unused, and do not go looking.** `requirements*.txt` are annotated line-by-line with why each pin exists. **Do not strip `redis`/`websockets`/`tiktoken`/`fastembed` because the API process does not import them — other images do.**

**Rollback is trivial for everything in this wave** — no migrations, no data changes, no generated artefacts. The one place deletion rollback would *not* be trivial is `grant.py` and `rls.py`, and only because what is lost is the design intent recorded in ~880 lines of docstring that no `git revert` puts back into anyone's head. Which is the argument for adopting them rather than deleting them.
---

# WAVE 2 — Adopt the owners that already exist

**The cheapest work in the programme, and the highest value per line changed.** Nothing here needs designing: in every case a correct module already exists in the tree, and production runs an older copy beside it.

The wave splits by a single question that decides everything about how each item ships: **do the copies AGREE today, or do they DIVERGE?**

> **If the copies agree, consolidation is a provable no-op — ship it atomically, this week.
> If the copies diverge, consolidation is a BEHAVIOR CHANGE wearing a refactor's clothes.** It picks a winner, and in this codebase the loser is sometimes what a borrower currently hears.

That distinction was measured, not assumed. Most regulated copies in this repo **agree** — which is better news than the corpus implied.

## 2A — Pure no-op consolidations · all copies verified identical · one PR

| # | Change | Blast radius | Behavioral risk | Atomic? |
|---|---|---|---|---|
| **2A-1** | Import `contact_policy.BLOCKING_CONSENT` at `payment_events.py:28`, `promise_fulfillment.py:29`, **`capture.py:331`** | 3 definitions, 4 use sites | **none** — all four frozensets verified member-identical | yes, one commit |
| **2A-2** | Extract the payment webhook HMAC; keep the two secret getters | 2 definitions, 2 routes | **none** — `payments.py:69-82` and `payment_events.py:56-64` are byte-identical after the secret lookup | yes |
| **2A-3** | `whatsapp_outbound.py:115` → import `pg_errors.is_unique_violation` instead of reaching through `bot_jobs._is_unique_violation` | 1 line | **none** | yes |
| **2A-4** | Delete the three local `_env_int` copies (`bot_runtime.py:38`, `reco/config.py:42`, `treatment/policy.py:422`) | 3 definitions, ~12 uses | **cosmetic** — confirm each caller wants `env_utils.env_int`'s swallow-to-default rather than raising | yes |
| **2A-5** | Adopt `env_utils.env_name()` at the eleven `APP_ENV` re-derivation sites (finding D1, §2) | 11 modules, 1 line each | **regulated** — see D1; it changes which controls are active under a non-canonical `APP_ENV`, which is the point | **no** — ship the `main.py` reading separately and deliberately |
| **2A-6** | Delete dead `hooks/use-mobile.tsx` (**0 consumers**); point `useIsLg` and `routes/inbox.tsx:90` at `useMinWidth` | 3 sites | **none** | yes |

**Prerequisites for 2A-1 through 2A-4 and 2A-6: none.** These can begin today, before Wave 0 finishes, because they are provable no-ops. **Do them first and use them to establish the pin-test convention** the rest of the roadmap depends on.

`env_utils` is worth noting as a partial success already: **14 modules import `env_int`**. The pattern works here; it was just never finished. And `pg_errors` is a completed one — **zero raw `pgcode == "23505"` comparisons remain in production.**

## 2B — Adopt an existing correct module · small, provable behaviour change

**2B-1 — Rupee formatting → `money_inr.inr`.** `promise_fulfillment.py:105` `_fmt_inr` and `mission.py:368` `_inr` both emit Western grouping (`1,234,567`) where the canonical emits Indian (`₹12,34,567`). **Three cross-module reach-throughs into the private Western formatter, not two as previously reported** — `payment_events.py:158`, `payment_events.py:625`, and **`agent_core/treatment/enact.py:242`**.

| | |
|---|---|
| Prerequisites | W0.1 (the suite must be green); decide null rendering per site — `money_inr.inr(x, none=…)` already parameterizes it (`money_inr.py:63-68`) |
| Affected | `promise_fulfillment.py` (4), `mission.py` (3), plus the 3 reach-throughs |
| Blast radius | **10 call sites, 5 modules** |
| Behavioral risk | **REGULATED — borrower-facing output.** `1,234,567` becomes `₹12,34,567` in an SMS the borrower receives, in a WhatsApp template parameter, and **in a sentence the voice agent speaks aloud** (`promise_fulfillment.py:205` `_spoken`). It is the correct change and the entire reason `money_inr` exists — but it must ship as a deliberate, separately-reviewed change, never folded into a cleanup PR. WhatsApp template parameters may additionally be length- or format-validated by Meta |
| Rollback | `git revert` — no persisted state |
| Validation | extend `tests/test_money_formatting.py` (already the best characterization file in the repo) with the exact `_confirm_copy`, `_spoken` and `briefing()` strings; snapshot the four WhatsApp template payloads before and after |
| Atomic? | **Yes** — a half-migrated `_fmt_inr` is worse than either end state |

**2B-2 — `_handoff_call` → `_handle_write`.** `main.py:1311-1319` repeats three of `_handle_write`'s branches but uses `str(exc)` for `KeyError` (toasting `'key'` *with quotes* — the bug `main.py:722-724` documents) and **has no `IntegrityError` branch, so a constraint violation escapes as a 500**. 5 call sites; behavioral risk **user-visible**, both changes improvements.

**2B-3 — Account tail: four algorithms, not two.** Canonical is `agent_core/context.py:559` (digits only, `None` under 4 digits; `voice/tools.py:181-183` correctly delegates). Bypassed by `db.py:411` (raw `[-4:]`, letters kept, **7 call sites**), **`ops_screens.py:415/674`** (SQL `RIGHT(…,4)` plus a `"----"` sentinel), and **`voice/persist.py:939`** (inline re-implementation that happens to agree). Behavioral risk **user-visible**: a vanity id `AC-SUSANTH` renders `ANTH` on desk feeds and `None` on the mouth today. **This is the one item in the roadmap that needs a production database read before shipping** — if account ids are all-numeric it is a no-op.

**2B-4 — One day parser.** `contact_policy.py:219-247` `_parse_days` returns `None` on empty and normalizes `–`/`—` → `-`, with a nine-line comment explaining that without it `"Mon–Sat"` collapses to Monday alone. `db.py:2038-2054` returns `[1,2,3,4,5]` on empty and **does not normalize the dash**.

> **This is a data-repair problem, not just a code problem.** Existing rows containing `Mon–Sat` with an en-dash are read as Monday-only by the CRM today. Fixing the parser **silently widens those consent windows from one day to six** — a DPDP-relevant change requiring a migration plan: identify affected rows, then decide whether to re-confirm or re-normalize the stored strings.

Prerequisite: a *product* decision — does blank mean "unrestricted" (the gate's reading) or "Mon–Fri" (the CRM's)? Keep empty-handling at the call site; consolidate only the parse. **Atomic and separately reviewed. Do not bundle.**

---

# WAVE 3 — Canonicalize the regulated decisions

**Every item here changes what the platform is permitted to do.** Each ships alone, through the H2 shadow protocol, behind a `platform_switches` flag rather than an env var (an env flag needs four process restarts; the switch converges in ~2s).

**Prerequisites for the entire wave: Wave 0-A (P1, P2, P5) and Wave 0-B (W0.1, W0.5, W0.6, W0.7, W0.10).** Six of the nine targets here have no test that would fail on a behaviour change; consolidating them before Wave 0 would be unfalsifiable.

## 3-1 — The preferred-window default · **contains the highest-value one-line fix in the report**

`contact_window.DEFAULT_WINDOW = "09:00-20:00 IST"` is canonical. **Nine sites still carry `10:00-19:00 IST`**, and — correcting report 06 — two of them are not display literals and two more were never listed:

| Site | What it is |
|---|---|
| **`db.py:1938`** — `preferred = r["preferred_window"] or "10:00–19:00 IST"` (en-dash) | **NOT display.** Flows into `:1941 _callback_dnd_active → :1827 → :1823 → contact_window.outside_preferred_window`. **It overrides the 9–20 default and changes the DND verdict for every callback with a NULL `preferred_window`.** |
| **`db.py:5468`** — same function, passes `preferred_window` raw | **The same file returns two different verdicts**: the callback *list* endpoint says 10–19, the callback *create* path says 9–20, for the same customer |
| `db.py:2075-2076` | `_parse_allowed_hours` returns `(10, 19)` on empty — functional default |
| `db.py:6631`, `db.py:10476` | **writes the stale literal into the database as data** |
| **`schemas.py:42`** | `ContactResponse.preferredWindow` wire default — not previously listed |
| **`agent_core/skills/packs/ptp-negotiate/SKILL.md:32`** | **prompt text the model reads and repeats to a borrower** — not previously listed |
| `db.py:1058`, `db.py:8834` | genuine display |

**Ship in three separate pieces, because their risk differs:**

- **(a) Display only** — `db.py:1058, 8834`, `schemas.py:42`. Cosmetic, atomic, trivial.
- **(b) The live verdict** — `db.py:1938`. Deleting the `or "10:00–19:00 IST"` substitution makes the callback list agree with `db.py:5468` and with `contact_window`. **Risk: user-visible + regulated** — callbacks in the 09:00–10:00 and 19:00–20:00 bands flip from DND to allowed. **Validation: count callbacks with NULL `preferred_window` scheduled in those two hour-bands before shipping.**
- **(c) Writes** — `db.py:6631, 10476` should INSERT NULL, not a literal; `SKILL.md:32` should say 09:00–20:00 or defer to the CRM card (**a prompt change ⇒ re-run the eval suite**). Backfilling existing stale rows is a separate migration.

## 3-2 — The calling-window decision → `policy_rules.calling_window()`

The **constant** is shared correctly — `RBI_VOICE_START=8`/`RBI_VOICE_END=19` (`contact_policy.py:69-70`) is imported by six modules. **The decision is not.** `policy_rules.calling_window(channel)` — the whole point of which is that a tenant can publish a narrower window — has **exactly two production call sites, both inside `contact_policy.py` (`:511`, `:682`)**. Seven other sites decide the window without it: `treatment/timing.py:88`, `live_qa/checks.py:171`, `live_qa/scorecard.py:292`, `treatment/metrics.py:345-365` (re-implemented **in SQL**), `payment_events.py:132-145`, `policy_export.py:53-59` (the Rego export), and `agent_core/compliance/detectors.py:297-298`.

**Start with `detectors.py`.** It restates `RBI_CALL_START_HOUR = 8` / `RBI_CALL_END_HOUR = 19` sixteen lines above its own `from contact_policy import _zone  # one definition of the timezone fallback`, and **`RBI_CALL_START_HOUR` appears nowhere else in the repo — nothing pins those numbers.** Blast radius: one file. Behavioral risk: **none today** (the numbers match). It removes the only unpinned restatement in the set.

Then the rest, each independently. **`treatment/metrics.py:345-365` re-implements the window in SQL** — that one needs the bounds parameterized into the query, not an import. Behavioral risk across the group: **none for any tenant that has not published a narrower window; regulated for any that has** — and per Wave 0-A P4, *no tenant has published one, because the seeding script runs nowhere*. Check `policy_rule_sets` before shipping.

`agent_core/treatment/policy.py:12-16, 463-484` already does this correctly and fails closed. **Use it as the reference implementation.**

A tenth site, correct and worth preserving: `campaigns.py:94` gates on the campaign run's own `window_start_hour`/`window_end_hour` and *still* calls `admit` at `:557`. It narrows rather than replaces — which is right, but means "the calling window" is now decided by campaign row, policy rule, and constant, in three shapes.

## 3-3 — One owner for the outbound gate sequence · **the strongest single argument in this roadmap**

Report 38 said the sequence is written seven times and *"nothing would fail if it landed in six."* Measured, **it has already landed differently in two**, and the divergence is an audit-trail hole:

**Ordering A — `reserve → admit → suppress-on-refusal → place` (5 sites):** `main.py:3768/3777/3788/3811`, `main.py:4088/4097/4144/4152`, `cadence.py:429/445/460/492`, `campaigns.py:540/557/573/610`, `scripts/dial_test.py:152/176/197/215`.

**Ordering B — `admit → reserve → place` (2 sites):**
- **`payment_events.py:821 → :866 → :882`, with no `outbound.suppress` anywhere in the module.** A bounce dial refused by `admit` writes its reason to `payment_events.next_voice_at`/`suppression_reason` and **leaves no row on the `call_attempts` ledger at all.**
- `agent_core/treatment/enact.py:102 → :360 → :384`, with suppression handled out-of-band by `_record_suppressed_dial` (`:422/:434`) on its own transaction **that swallows exceptions**.

> **So the invariant "every refused outbound leaves a suppressed attempt row" holds at six of seven sites and is false at `payment_events`.** `call_attempts` is the only record that a call was *not* placed (§I3). This is a gap in the evidence of a regulated refusal — and it is exactly the failure ADR-0001 describes for the Tool Grant, in a different decision, without an ADR.

**Prerequisite: resolve the ordering conflict as a decision, before writing the shared function.** Pick one order, and decide whether every refusal must leave a `call_attempts` row.

| | |
|---|---|
| Prerequisites | W0.7 (the composition contract test), Wave 0-A P2, the ordering decision |
| Affected | 7 call sites, ~400 lines; two are HTTP handlers taking `dict[str, Any]` bodies and opening their own transactions — **moving the sequence out of them is the whole point** |
| Blast radius | **L** |
| Behavioral risk | **REGULATED.** Changing `payment_events` to reserve-then-admit starts writing suppressed attempt rows for refused bounce dials — an audit-trail *addition*, and a change to attempt-ledger counts, **which the fleet gate reads** |
| Rollback | `platform_switches`, not env |
| Validation | a test asserting every refusal path leaves exactly one suppressed `call_attempts` row; replay all 8 `test_outbound_*.py` files |
| Atomic? | **Atomic for the shared function; strangleable per caller.** Introduce `outbound.dial(...)`, migrate the five ordering-A sites first (no behaviour change), then the two ordering-B sites separately |

Note the gate itself is well-adopted — `contact_policy.admit` has **13 production call sites**. The duplication is the *sequence*, not the gate.

## 3-4 — "May we contact this borrower now?" in the browser

`useContactPolicy` (`api/contact-policy.ts:56`) has **exactly one consumer** (`ContactabilityPill.tsx:150`). Five live components compute their own verdict instead:

- `consent/ConsentTable.tsx:83,86`, `consent/ContactablePill.tsx:8`, `consent/ConsentStatsStrip.tsx:2` → `consent-seed.ts:419` → `:379 isContactableNow`. **No RBI 8–19 check at all**, and its window check (`:350`) uses **`at.getHours()` — the operator's browser clock, not IST**. No cooling-off, no daily cap, no promotional purpose.
- `callbacks/CallbackSheet.tsx:134`, `callbacks/NewCallbackSheet.tsx:80` → `callbacks-seed.ts:788 isWithinDndWindow` — browser clock again, regex-parsed window, **and a third default of 09–20 when unparseable** (`:797`). It feeds `:804 nextAllowedSlot`, **which books the slot.**

**This runs on live data, not mocks.** `api/consent.ts:29` and `api/callbacks.ts:41` fetch from the backend when `USE_MOCK` is false, and the components then run the seed-module verdict over those live rows.

**Winner: `contact_policy.admit`/`evaluate` behind an endpoint.** It is the only implementation that knows about borrower timezone, cooling-off, caps, published windows and DPDP purpose limitation.

## 3-5 — DND: one store · 3-6 — Consent channel vocabulary

**DND diverges three ways.** `contact_policy.py:504` ORs `customers.dnd | consent_records.dnd_registry`; `db.py:2313` ORs both for the consent screen; **`db.py:1826-1827` `_callback_dnd_active` reads `customer_dnd` only.** So a borrower on the registry but not flagged on `customers` is blocked by the gate, red on the consent screen, and **green on the callback board.** Code fix first (cheap, fail-closed); column consolidation later. **Not atomic.**

**Channel vocabulary diverges three ways.** `contact_policy.py:142 normalize_channel` maps `{call, voice, pstn} → voice`; `db.py:897 _consent_channel` maps `voice → call`, unknown → `None`, **no `pstn`**; `db.py:2024 _consent_channel_db` maps `call → voice`, **no `pstn`**. A `pstn` value survives unmapped through the CRM path and **matches no consent row**. Fail-closed → fail-correct.

## 3-7 — The Tool Grant · **a project, not a refactor** · ships last in this wave

Six live formulas compute the grant; the ADR-named owner has zero production importers. And the fail-open is real: `agent_core/skills/runtime.py:185` returns `ToolState(allowed=None, …)` for a cardless mouth, `bot_runtime.py:947-950` falls back to `bot_tools.TOOL_DEFINITIONS` — which contains all nine skill-gated writes including `create_promise_to_pay`, `apply_goodwill` and `flag_dispute` — and enforcement inverts the same way at `bot_tools.py:831` and `voice/tools.py:2911`. **A cardless mouth is permitted to execute, not merely offered.**

**Sequence, each step separately reviewed:**

1. **Fix the channel filter first — 2 lines, and it needs none of `grant.py`.** `intersect.py:65-68` `_apply_channel` returns names unchanged when `channel_tools is None`; `compile.py:630` passes it, `skills/runtime.py:194,197` does **not**. So the publish gate computes a channel-filtered grant and both runtimes compute a channel-blind one. **This is the one verified divergence, and this step closes it.** Risk: user-visible on voice — a card naming a text-only tool stops being granted on a call where no handler exists anyway.
2. Migrate `MouthTurn.tools()` → `ToolGrant.for_bundle`/`may_execute` across `voice/bot.py:1131`, `bot_runtime.py:912-950`, `sandbox_runtime.py:230-244`.
3. Replace `compile.py:734` `allowed_scope` with `ToolGrant.static_grant`, so publish is the union of runtime.
4. Remove `| ALWAYS_ON` at `voice/tools.py:2912` — **only after step 2**, or you have created a seventh formula.
5. **Delete the cardless fallbacks and invert the sentinels. This is ADR-0002 and it lands alone and last** — it turns a cardless mouth from *permitted to write a PTP* into *permitted nothing*, and it will break any deployment whose card read is failing, which is exactly the population it protects.

**And fix the pin's reach.** `tests/test_tool_grant.py:131` opens with `pytest.importorskip("voice.tools")`, so the `VOICE_ALWAYS == ALWAYS_ON` assertion **silently skips wherever pipecat is absent — the API image and CI.** The two agree today; nothing outside the voice container would notice if they stopped.

**ADR-0001 states the ordering constraint that makes this urgent rather than tidy:** *"This decision is therefore a prerequisite for handoff, not merely an improvement alongside it"* — because a session-start tool filter keeps the handing-off agent's tools after transfer. **Handoff is implemented** (25+ files, `voice/bot.py`, `tests/test_handoff_to_agent.py`). The prerequisite was never met.

---

## A correction that removes a Critical from the corpus

**`flow_graph._FLOW_CONTROL_TOOLS` (10 entries) vs `ALWAYS_ON` (11) is deliberate and pinned — not drift.** Verified member-by-member: `grant.VOICE_ALWAYS` (`grant.py:89`) and `voice/tools.py:80-94 ALWAYS_ON` are **identical, 11 members each**. `flow_graph.py:773-784` has 10, omitting `capture_call_goal` — and `tests/test_tool_grant.py:137-147` asserts exactly the permitted form of that difference, because both `capture_call_goal` and `verify_identity` are in `CATALOG` (`catalog.py:160, :190`) and the catalog supplies that half.

Both `06-duplication.md` DUP-01 and `38-architecture-boundaries.md` C3 present this as unmanaged divergence. **It is managed.** `voice/tools.py:79`'s comment *"the two still differ"* is stale. The real risk is narrower and is captured above: the pin does not execute in CI.

---

## What must NOT be consolidated

Re-verified as genuinely distinct questions:

- **`contact_window` 09–20 (borrower *preference*) vs RBI 08–19 (*statutory* voice hours).** A 19:30 callback is in-preference and out-of-statute. **Merging these would be the worst single outcome of this exercise.**
- `authz.ROUTE_PERMISSIONS` (may this *operator* hit this route) vs the Tool Grant (may this *mouth* execute this tool) — two permission systems on purpose.
- Compile Gate G0–G15 (publish) vs `contact_policy.admit` (dial).
- `bot_jobs.mark_failed_or_retry` vs `whatsapp_outbound.mark_failed_or_retry` — the WhatsApp dead-letter-on-ambiguous-error branch is a **double-send guard**, not an oversight, because Meta has no idempotency key. A parameterization candidate at best; the divergence is the correct part.
- `money_inr.inr` (grouped ledger) vs `inr_compact` (glanceable billing); and `billing-seed.ts:100-120 inrCompact` is a **deliberate documented mirror** — *"Mirrors `backend/money_inr.py::inr_compact` exactly. Change one, change both."*
- `usage_meter.py:277-292` deliberately does not use `env_utils.env_name`, with the reasoning written down.
- `env_loader.load_env()` (publishes into `os.environ`) vs `db._read_env_file` (must not, so importing `db` cannot mutate the process).
- `platform_flags` (does this deployment have the feature) vs `platform_switches` (stop dialling now, without a restart).
- **Cadence** vs job retry vs HTTP retry vs circuit breaker — four concepts, one English word.
- `rls.py`'s zero application importers is **correct**, not dead code — operator tooling driven by `scripts/rls.py:34`.

## Tenant isolation is not a canonicalization target

Measured: **168 hand-written `tenant_id = :tenant` SQL predicates and 312 `db._tenant()` call sites** in production, and `rls.py` — the designed backstop — has exactly one non-test importer. **There is no un-adopted canonical module here to wire.** This is a missing *mechanism*, not a duplicated one, which is why it sits in Wave 0-A as prerequisite P5 rather than in this wave.
---

# WAVE 4 — The API boundary

**Why this precedes the `db.py` carve**, restating the measured constraint from §3.5: today's response shapes are hand-assembled **inside `db.py`** — the file Wave 5 splits — and the wire has no runtime validation on either side (**356 `as Type` casts** in the frontend against **one** validator import; `api/config.ts:183` is literally `return JSON.parse(text) as T`, and `.safeParse(`/`Schema.parse(` return **zero** hits although `zod` is already a dependency). **Carve first and you silently rewrite the public API with nothing to catch it.**

**136 of 314 routes declare a `response_model`; 178 do not.** Classified by what they actually return:

| Return shape | count | Risk of adding a `response_model` |
|---|---|---|
| `return db.<fn>(...)` directly | 14 | **Low** — shape is one function away |
| Inline dict literal | 19 | **Low** — shape is visible in the handler |
| Delegates to another module | 26 | Medium — must read the callee |
| **Raw rows (`SELECT *` / `SELECT r.*`)** | **6** | **HIGH — breaking** |
| Mixed / multi-shape | 113 | Medium-to-high, per route |

**The mechanic that decides the ordering:** FastAPI's `response_model` **filters** undeclared fields. Adding one to a route that ships `SELECT *` **drops fields from the wire** — and `Habibi/src/api/outbound.ts:301-307` has already written down, in prose, that those raw field names *are* the frontend's contract. Those six routes are the ones that need frontend coordination, and they are also the ones leaking `tenant_id` to the browser.

### 4-1 — Error-code mapping first · one function · not a wire break

`_handle_write` (`main.py:720-738`) is a single funnel with **82 call sites**, mapping `KeyError→404`, `PermissionError→403`, `ValueError→409`, `IntegrityError→409`. `db.py` raises `ValueError` **83 times across 48 distinct codes**, and they are not one kind of thing: `bot_id_required`, `invalid_severity`, `empty_message` mean *the client sent garbage* (422); `publish_conflict`, `handoff_already_claimed`, `deployment_already_active` mean *someone got there first, refetch and retry* (409). **Eleven of the 59 string literals are English sentences, not codes** — `"answer cannot be empty"`, `"kept promise cannot move to broken/partial"` — and `detail=str(exc)` makes them the public contract.

Add a `dict[str, int]` code→status table consulted inside `_handle_write`, defaulting to 409 so every unmapped code keeps today's behaviour.

| Prereq | Affected | Blast | Risk | Rollback | Validation | Atomic? |
|---|---|---|---|---|---|---|
| — | `main.py:720-738` | **S** — one function; each mapping is opt-in per code | **user-visible, bounded**: a route returning 422 instead of 409. `api/config.ts:157-169 retryUnlessClientError` already treats all non-408/429 4xx as terminal, so frontend retry behaviour is unchanged either way | empty the table | backend tests; grep the frontend for `.status ===` | **Yes**, and cheap |

Fold in **2B-2** here (`_handoff_call` → `_handle_write`, 5 sites) — same function, same review.

### 4-2 — `response_model` on the 33 low-risk routes

The 14 `db.*`-direct plus the 19 dict-literal returns. Pure addition, no frontend coordination. `schemas.py` already holds 247 models with 186 carrying `extra="forbid"`. Blast radius **M**, behavioral risk **none** (the declared model matches what already ships — verify each), atomic per subsystem.

Target `/agent-studio` first: **26 routes, 265 lines, 0 with a `response_model`**, and dense enough (0.73 contiguity) that it is also Wave 5's first router extraction.

### 4-3 — Request bodies on the 42 unvalidated writes · **money and grants first**

`POST /vault/refs` and `/rotate` (`main.py:2464,2476`), `POST /mcp/keys` (`:2490` — **tool grants**), `PATCH /roles/{id}/permissions` (`:2857` — **RBAC**, `[str(x) for x in ids]` straight into `replace_role_permissions`), the four payment routes (`:795,825,857,882`), `POST /twilio/voice/outbound` (`:3731` — **contact windows and PSTN**, taking a `dict[str, Any]` and opening its own transaction).

**This is a wire change.** A Pydantic model with `extra="forbid"` starts 422-ing requests that used to 200. **Sequence: land the model with `extra="ignore"`, log rejections for one release, then tighten.** Separately, **61 of the 247 existing models carry no `model_config` at all**, so unknown fields are silently ignored rather than rejected — including `PromiseCreateRequest` and `PaymentPlanCreateRequest`.

Behavioral risk **user-visible → regulated** (the Twilio route dials real PSTN numbers). Rollback: revert the model. Validation: replay recorded request bodies against the new models before tightening.

### 4-4 — The six `SELECT *` routes · **last, with the frontend, in one PR**

`main.py:5008-5016` does `SELECT * FROM campaign_runs`; `main.py:4846` does `SELECT r.*`. `/outbound/number-pools` ships `tenant_id` to the browser. Generate the model from the live shape, land it **in the same PR** as the `outbound.ts` type change, and drop `tenant_id`.

**Before starting: diff the shipped columns against `outbound.ts`'s declared type.** That check was not performed by this audit and it decides the size of the change.

### 4-5 — Then, and only then, a route→contract registry

Enforce `response_model` coverage the way `authz.ROUTE_PERMISSIONS` is enforced — the mechanism is proven at 314/314 with a CI totality test. **But this test lands after 178 → 0, not before**, or the build is blocked on unfinished work. That is the repo's own rule: *"A gate introduced red is a gate people learn to ignore."*

---

# WAVE 5 — Carve `db.py`, and take six routers out of `main.py`

## 5.1 Carving `db.py` — the strangler path

### 5.1.1 `db.py` contains its own carve map

The file carries **15 banner-comment section headers**, and they are named. Function counts, spans, and external consumers beyond `main.py`:

| Line | Section | funcs | lines | External consumers besides `main.py` |
|---:|---|---:|---:|---|
| 1 | head / engine / row helpers | 110 | 3,057 | `ops_screens`, `voice/persist`, `agent_core/a2a`, `llm_gateway/canary`, `agent_core/skills/persist`, … |
| 3112 | Executive dashboard | 5 | 554 | **none** |
| 3700 | Per-turn trace | 79 | 3,407 | `agent_core/tools/domain` (6), `voice/tools`, `worker`, `bot_tools` |
| 7125 | Bot analytics | 5 | 445 | scripts only |
| 7636 | QA scorecards | 25 | 794 | `qa_autoscore` (5), `live_qa/scorecard` |
| 8443 | Conversation inbox | 54 | 2,524 | `bot_runtime` (4), `bot_tools`, `mission`, `sandbox_runtime` |
| 10977 | Redaction & export | 14 | 399 | `authz` (2) |
| 11399 | Routing builder | 16 | 768 | `voice/tools` |
| 12196 | My Workspace | 9 | 448 | **none** |
| 12671 | Prompt Studio — reads | 34 | 1,275 | `agent_core/cards/clone` (3), `agent_core/deployment` |
| 13981 | Prompt Studio — writes | 17 | 917 | `cards/clone`, `agent_core/canary`, `agent_core/deployment` |
| 14926 | KB-2 library admin | 21 | 841 | scripts only |
| 15777 | KB-3 FAQs / gaps | 14 | 540 | `worker` (2), `voice/crm_sink`, `agent_core/tools/kb` |
| 16325 | Sandbox | 7 | 291 | **none** |
| 16626 | Billing & usage | 16 | 896 | **none** |
| 17538 | Treatment holds | 14 | 535 | **none** |

**These sections are screen-shaped, not domain-shaped.** `db.py` is not one god repository; it is a CRM persistence kernel (lines 1–3111) with ~14 screen-backing query modules stacked on it. That is precisely why a DAO layer is the wrong answer (§6.2) and why the carve is by section rather than by entity.

### 5.1.2 The coupling profile says the carve is clean

Intra-file call graph over all 440 top-level functions:

- **~405 of ~440** calls point **down** into the head/helpers section (`_rows`, `_one`, `_tenant`, `_id`, `_activity`, `clamp_list_limit`, …).
- **Only ~35** run between the 15 upper sections, and they are one cluster: Prompt-Studio-writes → Prompt-Studio-reads (**17**), plus 4 studio→inbox, 3 QA→trace, 2 sandbox→studio, 2 studio→trace, and singletons.

Top internal fan-in: `_one` 113, `_rows` 103, `_actor_user_id` 43, `_activity` 37, `_id` 34, `_assert_tenant_owns` 23, `clamp_list_limit` 19, `clamp_offset` 18.

**Two hazards a naive carve will hit, not present in any prior report:**

- **`_as_dict` is defined at `db.py:12703`** — inside *Prompt Studio reads* — but has internal fan-in **18** across sections.
- **`_jsonb` is defined at `db.py:14068`** — inside *Prompt Studio writes* — and is referenced from **12 external modules**.

Both must move **down** into the core helper module *before* their sections are peeled, or the peel creates an upward dependency.

### 5.1.3 The honest bad news, and the honest good news

Peel simulations (this analyst's graph convention, baseline SCC 112):

| Cut | largest SCC |
|---|---:|
| baseline | **112** |
| peel Prompt Studio | 111 |
| peel Studio + Treatment-holds | 110 |
| peel Inbox + Per-turn-trace | 86 |
| peel Studio + Treatment + Inbox/Trace | 83 |
| + KB sections | 82 |
| remove all `db →` edges | 41 |

**The cycle collapses only at the end.** But the *work* is incremental, and the roadmap depends on saying this out loud:

> SCC size is a **lagging indicator**. You get file size, ownership, review surface and navigability from commit 1; you get the cycle from the last commit. **Do not let anyone measure progress by SCC and conclude the first eight commits achieved nothing.**

And one promise nobody should make: **an SCC of 41 remains with `db.py` deleted entirely.** The agent-turn core (`agent_core.turn`, `understanding`, `guardrails`, `prompt`, `tools.*`, `llm_gateway`, `azure_openai`) is a genuinely mutually-recursive cluster and is not `db.py`'s fault. Carving `db.py` will not make the import graph a DAG.

### 5.1.4 The sequence

**Prerequisite commit — `db_core.py`. The only thing that must happen first.**

Move into a new `db_core.py`: `engine` + the `@event.listens_for` begin hook + the `DATABASE_URL`/`TENANT_ID`/pool constants + `current_tenant`/`_tenant` + `_rows`, `_one`, `_id`, `_dump`, `_sql`, `_vis_params`, `_activity`, `_actor_user_id`, `_assert_tenant_owns`, `clamp_list_limit`, `clamp_offset`, `_account_tail`, `_IST`, **plus `_jsonb` and `_as_dict` moved down from `:14068` and `:12703`**. Give it an explicit `__all__` — `env_utils.py` and `pg_errors.py` are the in-repo models.

The shim is complete because of a verified fact: **no importer anywhere uses `from db import X`** — all 211 production import sites use `import db`, so attribute re-export from `db.py` keeps every call site resolving.

| | |
|---|---|
| **Prerequisites** | none |
| **Affected** | 1 new file + `db.py` head |
| **Blast radius** | **zero call sites** (attribute shim) |
| **Behavioral risk** | **internal, but one real hazard**: `create_engine` must execute exactly once and the `begin` listener must register against that same object |
| **Rollback** | revert one commit |
| **Validation** | full pytest + a smoke boot of `main:app` |
| **Atomic?** | **Yes — mandatory.** Moving the engine and its listener in separate commits is the failure mode |

**Then peel one section per commit**, each a new module plus a bottom-of-`db.py` re-export block in the exact shape of `db.py:18005-18024`:

| # | Section | Why here | Call-site edits |
|---:|---|---|---|
| 1 | **Billing** (16 fn / 896 ln) | 6 outbound calls all into core; zero inbound; `main.py` only | zero |
| 2 | **Treatment holds** (14 / 535) | `main.py` only; removes 4 of `db`'s domain fan-out targets | zero |
| 3 | Executive dashboard (5 / 554) | zero inbound | zero |
| 4 | My Workspace (9 / 448) | move `_as_utc@12220` to core first | zero |
| 5 | Sandbox (7 / 291) | needs `_as_dict` in core (prereq did it) | zero |
| 6 | Bot analytics (5 / 445) | scripts only | zero |
| 7 | Routing builder (16 / 768) | +1 consumer (`voice/tools`), still shimmed | zero |
| 8 | Redaction / export (14 / 399) | move `_speaker_screen` to core | zero |
| 9 | KB-2 + KB-3 (35 / 1,381) | removes the `kb_ingest`/`storage`/`azure_openai`/`pii_redact` fan-out (14 sites) | zero |
| 10 | **Prompt Studio R+W as ONE unit** (51 / 2,192) | 17 internal W→R edges make splitting them a mistake; **this peel alone removes 43 of `db.py`'s domain import sites** | watch `cards/clone.py:15` (eager `import db`) — S5 may be needed |
| 11 | QA scorecards (25 / 794) | `qa_autoscore` (5), `live_qa/scorecard` | zero |
| 12 | Conversation inbox (54 / 2,524) | owns the channel fan-out; 12 external consumers | moderate |
| 13 | Per-turn trace (79 / 3,407) | hardest: largest, 11 external consumers, `agent_core/tools/domain.py` binds 6 names | moderate |

Residual `db.py` ≈ 3,100 lines — the CRM kernel plus re-exports. A file a person can hold in their head, and the point at which the SCC finally moves.

**If only part of it is ever done**, the smallest carve that pays is **prereq + #10 + #2**: three commits, ~2,700 lines moved, over half of `db.py`'s domain fan-out removed. Steps 1, 3, 5, 6 are free wins that warm up the pattern but move little coupling.

**Validation for every peel:** full pytest, run *in the voice container* (a host run tests a different Python than ships), and never while the corpus simulator holds locks — a lock-contention failure looks exactly like a real regression. **Rollback:** each peel is one commit, one file created, one re-export block — `git revert` restores byte-identically. **Atomic:** each peel yes; the sequence no.

### 5.1.5 The two regions that must not be touched

`db.py:138-150` — `create_engine` passing the tenant as a **libpq startup parameter** — and `db.py:153-169`, the `@event.listens_for(engine, "begin")` `SET LOCAL` override. The rationale is written into the file at `:126-137`: a startup parameter cannot be un-set by the pool's return-to-pool ROLLBACK. **That is the strongest seam in the backend, it is the entire safety argument for enabling RLS later, and a casual "move the engine to a factory" during the carve would silently destroy it.**

---

## 5.2 `main.py` — what an `APIRouter` split honestly buys

The safety picture is unusually good, and it was measured rather than assumed:

- **334 top-level functions = 312 route handlers + 22 helpers.** Only one helper has meaningful fan-in: `_handle_write` (82 call sites). Seven helpers have fan-in 0. Only 20 module-level statements outside defs and imports.
- **Zero ordering-sensitive route pairs.** Every same-method, same-arity path pair was checked for parameterised-shadows-static conflicts across all 314 routes: none. **Route registration order cannot affect matching**, so `include_router` order cannot change behaviour.
- `_authz_guard` (`main.py:507-551`) reads `scope["route"].path` — the *mounted* template — so a router with `prefix=` still produces the same `(METHOD, path)` key, and `tests/test_authz.py::assert_registry_covers` turns any drift into a **build-time** failure.

So the split is about as safe as a 5,400-line refactor gets. **What it buys:** merge-conflict surface, navigability, and a place to hang per-subsystem `dependencies=[...]`. **What it does not buy, and this should be said plainly:** `main.py` has **zero importers**. Splitting it reduces no other module's coupling, breaks no cycle, and improves no dependency metric.

Prefix contiguity argues for a partial split. Measured as the fraction of each prefix's line span occupied by its own handlers:

- **Dense, worth extracting:** `/demo` (0.98), `/roles` (0.92), `/outbound` (0.87 — 14 routes, 430 lines), `/platform` (0.87), `/agent-studio` (0.73 — **26 routes, 265 lines, 0 with `response_model`**), `/treatment` (0.71), `/mcp` (0.65), `/eval` (0.62), `/twilio` (0.48).
- **Hopelessly interleaved:** `/providers` spans 3,920 lines for 144 of its own; `/customers` 3,901 for 31; `/tts-voices` 2,565 for 51; `/kb` 2,170 for 197.

**Recommendation:** extract **six routers** — `agent_studio`, `outbound`, `twilio`, `treatment`, `eval`, `demo` — covering ~75 routes and ~1,700 lines, mounted with **no `prefix=`** so full paths stay in the decorators, the authz keys stay byte-identical, and the diff is a pure move. Move `_handle_write`, `_json_charset` and `_read_upload_capped` into a ~40-line `http_errors.py`. **Leave the other 72 prefixes alone.** Validation is a route-table snapshot — `[(r.methods, r.path) for r in app.routes]` — diffed before and after, plus `tests/test_authz.py`.

**Priority: low.** If the roadmap has to drop something, drop this. It is cheap and safe and it is cosmetic.
# WAVE 6 — Frontend

**Placed late, against instinct, for a measured reason:** the backend has 186 test files and 2,431 test functions; the frontend has **11 test files for 474 modules**, no jsdom, no Testing Library, no MSW. **Frontend refactoring here is less protected than backend refactoring.** Wave 1 already deleted 29 files from this tree; do that first so nothing below is spent on dead surface.

**Do not regress the two things the corpus correctly calls exemplary:** `api/config.ts` holding 6 of the frontend's 7 `fetch` calls, and `components/ui` with **zero** edges to `api/`, `routes/` or feature code.

### 6-1 — Runtime validation at the transport, made opt-in

There are exactly three JSON→`T` sites: `apiGet` (`config.ts:183`), `apiSend` (`:211`), `apiUpload` (`:274`). But `apiGet<T>(path, init?)` has **no runtime schema parameter**, so adding zod changes the signature at **221 generically-typed call sites** across 48 api modules.

**The strangler form is an optional third parameter** — `apiGet<T>(path, init?, schema?: ZodType<T>)`. Unvalidated calls keep working unchanged; migrate one `api/*.ts` module per commit. `zod@^3.24.2` is already a dependency, used exactly once today. **Start with the six raw-row `/outbound` endpoints**, where the contract is provably fragile.

Behavioral risk **real**: a schema stricter than reality turns a working screen into a thrown `ZodError`. Mitigate with `.safeParse` + `console.warn` + pass-through for the first release, then flip to throw. Rollback: drop the argument at the call site. **Atomic per api module.**

**And fix the seventh fetch.** `routes/sandbox.lazy.tsx:432` is a blob-download `fetch` that **bypasses `authHeaders`** — so that export call carries no API key. One line, and it restores the "one transport" property.

### 6-2 — Move the 261 domain types out of `data/*-seed.ts`

`src/types/` contains **one file, 15 lines** (`view-transitions.d.ts`) and **zero domain types**. `src/data/` exports **261** across 26 files, and **31 production `api/*` modules import their response types from mock fixtures.** `api/customers.ts` returns `apiGet<Customer[]>` where `Customer` is declared in a seed file.

This is a pure type-level move — `tsc --noEmit` catches every mistake — making it the **lowest-risk frontend change in the repo**. Do it alongside 6-1, module by module: the zod schema and the inferred type land together, which is what makes 6-1 pay.

### 6-3 — One rupee formatter

Five named grouped formatters plus ~12 inline ones. The grouping is right almost everywhere (`toLocaleString("en-IN")`); the forks are **sign and null**. `data/customer360-seed.ts:1140 fmtMoney` renders `-₹500` (sign outside) and `₹0` for null — **diverging from `money_inr` on both** — and it is re-exported verbatim by `promises-seed.ts:80`, `disputes-seed.ts:11` and `documents-seed.ts:10`, making it the widest-blast TS formatter. `api/treatment.ts:1148 fmtInr` already agrees with the canonical on both. **Adopt that one.**

**Do not touch `billing-seed.ts:100-120 inrCompact`** — it carries an explicit contract: *"Mirrors `backend/money_inr.py::inr_compact` exactly. Change one, change both."* It is a deliberate mirror, not a duplicate.

### 6-4 — `USE_MOCK` out of `components/` and `routes/`

**384 references across `src`**, with 26 outside `api/` (10 components, 13 routes, 3 data files). The sharpest case is `routes/callbacks.tsx:83`, which asks *"are we mocked?"* when the real question is *"did `/staff` return rows?"*

Behaviour-changing, near-zero test coverage. **Do it last, screen by screen, and only for screens someone can eyeball.** Note the dependency from §3.5: deleting the mock branch deletes the module that declares `Customer`, so **6-2 must precede this.**

### 6-5 — The remaining structural work, in value order

`QueryState` across the **59** `query.data ?? []` sites (it has exactly one consumer today); query-key factories; the ~43 route-inline mutations of 102 total; the copy-paste chrome families (20 strip/KPI components, 9 filter bars, 16 entity sheets, 19 tables — and `components/ui/` contains **no** metrics-strip or kpi-card primitive, so this one is genuine *extraction*, not adoption); `AppShell` as a pathless layout route instead of **39 mount sites**; and the god routes `prompt-studio.lazy.tsx` (1,658) and `treatment.lazy.tsx` (1,506).

One item here is really Wave 3 and is listed only because the code lives in the frontend: **the consent and callback screens computing their own contact verdict** (§3-4). It runs on live data and it books slots.

---

# WAVE 7 — Infrastructure isolation

**Most of this is already achieved. The wave is small, and it is mostly about making an existing boundary *checkable* rather than building a new one.**

**Achieved — do not redo:** two images and five services with per-process `DB_PROCESS_ROLE` (which `db.py:122-124` reads to pick a 15s vs 60s statement timeout); a deliberate, documented dependency split (`requirements-voice.txt:4-5`); genuine provider containment — of 140 `pipecat` import lines every production one is under `voice/` except two, and both were checked (`agent_core/tools/schema.py:164` is lazy with a comment; `providers/fish_service.py:39-41` is module-level **but the module has zero Python importers**, being string-loaded); `storage.py:106` as the only `minio` import, with its breaker owned by the adapter and `CircuitOpenError → 503` mapped exactly once at `main.py:712-717`.

### 7-1 — A CI import-boundary test · **the cheapest honest improvement**

Run `python -c "import main"` and `python -c "import worker"` **in the base image with `pipecat` and `fastembed` absent**, asserting no `ImportError`. One CI step. It converts "the boundary is masked by packaging" into "the boundary is caught by a test", and requires no restructuring at all.

### 7-2 — `-c requirements.txt` at `Dockerfile:41`

Today the voice stage installs `requirements-voice.txt` on top of the base with no constraint file, so **the api image and the voice image, built from one commit, do not have the same library versions, and nothing records what either got.** Expect this to fail on first application (`ruff==0.6.9` vs pipecat's `ruff>=0.12.1`) — **that failure is the finding.**

### 7-3 — Two packaging facts to resolve

- **`requirements-mcp.txt` is installed by no Dockerfile stage and no compose service.** `mcp_server.py:43-46` imports `mcp` lazily inside `try/except ImportError`, so it degrades rather than crashing — but **the MCP stdio server cannot run in any image this repo builds.** Add a stage, or document it as host-only tooling.
- **`fastembed` is voice-image-only but is imported from `agent_core/`.** `agent_core/tools/kb_rerank.py:124` imports it lazily inside a `try` with a `_load_failed` latch, so **in the api and worker images the CPU reranker silently never loads.** The availability of a retrieval component differs by image with no signal anywhere.

Also: `pytest==9.1.1` and `ruff==0.6.9` ship in the base layer of every production image.

### 7-4 — What the process boundary must not become

The image boundary is **additive, not exclusive** — `Dockerfile:32` is `FROM base AS voice` and `Dockerfile:23` is `COPY . .`, so the whole source tree and all base pins are in every image. Five processes, four commands, **one** dependency boundary. **That is why `voice/twilio_ops.py:93 → voice/ws_proxy → fastapi` costs nothing today.** If a real dependency boundary is ever wanted, the seam that makes it incremental already exists: the string-keyed registry (S6). **Do not split the images speculatively** — add the test in 7-1 and let a real need drive the rest.
# The irreversibility register

`git revert` does not undo any of these.

## I1 — Migration downgrades that destroy regulatory evidence

The chain is healthy in shape: **102 revisions, single head `20260901_0103`, single root, strictly linear — no branches, no merges, no multiple heads** (verified by parsing every `revision`/`down_revision` pair). Every revision defines `downgrade()`; nine are `pass`.

Of the 93 real downgrades: **14 drop tables, 29 drop 69 columns in total, and 48 contain raw `DELETE`/`TRUNCATE`/`DROP`.** Three are regulatory rather than merely lossy:

| Revision | Downgrade does | Irreversible consequence |
|---|---|---|
| **`20260822_0098_consent_purpose.py:78`** | `DELETE FROM channel_consents WHERE purpose='promotional'` | **Every promotional DPDP consent basis ever captured is destroyed.** Under purpose limitation the row *is* the evidence that the borrower agreed. Restoring the schema does not restore the permission — you must re-collect consent from every borrower. |
| `20260813_0066_contact_events.py` | drops `contact_events` + `contact_day_counters` | That ledger *is* the evidence of RBI frequency-cap compliance; `channel_consents.used_this_week` is only a cache of it. Dropping it erases the audit trail for every contact made. |
| `20260822_0094_outbound_attempts.py` | drops `call_attempts`, `call_outcomes` | `call_attempts` is the only record of dials that did **not** connect, including suppressed ones. Dropping it erases the proof that a call was *not* placed. |

Plus `20260812_0059`, whose downgrade issues an unconditional `DELETE FROM idempotency_keys` — re-opening every replayed mutation as fresh.

> **And no downgrade in this repository has ever been executed by CI.** `backend-pytest.yml:198` sets `RUN_ALEMBIC_ROUNDTRIP: "0"`; `tests/test_migrations.py:50-53` skips unless it is `1`, and even then only runs `downgrade -1`. **These 93 downgrade functions are untested code that runs only in an emergency.**

## I2 — Migrations that mutate real rows unconditionally

`seed_guard.seed_demo_enabled()` gates *demo inserts* only. These mutate regardless: `0064` (stock role grants), `0073` (`DELETE FROM prompt_versions` + first-party bot inserts), **`0084` and `0101` (rewrite persona/prompt text — i.e. what the agent says to borrowers)**, `0103` (rewrite eval fixtures). **`0101`'s downgrade is `pass`** — the prior persona text is gone.

## I3 — Dialing: a wrong call is a regulatory event, not a bug

`voice/twilio_ops.py:371` is the only outbound voice boundary, gated at `:312-318` by `platform_switches.outbound_enabled()`; `:425` is a second `calls.create` on the warm-transfer path; `twilio_sms.py:85` sends SMS. Report 25's mechanisms apply: `outbound.place` maps any Twilio exception to `placed: false` and `campaigns.process_one` re-queues after five minutes, so a 10s client timeout *after* Twilio accepted the create produces a second real call; and `treatment/enact.py:307-313` sends SMS *inside* the enclosing transaction, so a rollback sends it twice. **There is no compensating action for a call the borrower has already received.**

## I4 — Money · I5 — Audit evidence · I6 — PII

`audit_log` (`sql/12_crosscutting.sql:20-30`) has **no immutability trigger, no REVOKE, nullable `tenant_id` with `ON DELETE SET NULL`**; `sql/13_triggers.sql` mentions audit nowhere. The only `INSERT INTO audit_log` in the Python tree is `agent_core/change_log.py:162` with `_ENTITY_TYPE = "bot"` — **the hash chain covers agent-card config publishes only.** Money, consent and contact carry no chain.

There is **no `pgcrypto` and no column encryption anywhere** — `sql/00_extensions.sql` is one line enabling `vector`. `policy_rules` defines a `recording_retention` in months, seeded by the script that runs nowhere (P4), and no sweep deletes recordings on that schedule. `sql/21_outbound.sql:37` describes `call_attempts` as *"unredactable borrower PII whose retention nobody has argued about."*

## I7 — Renaming anything an operator has already clicked

`platform_switches.py:60-66` says it outright: renaming a switch key *"would orphan the row an operator has already enabled, silently making the demo more restrictive at the moment they least expect it."* The same applies to every DB-keyed switch, every `policy_rules.kind` string, and every status literal backed by a `CHECK`. **A rename is a data migration, not a refactor** — which is why §6.13 declines the vocabulary-alignment work that `02-domain-capability-map.md` makes tempting.

---

# Latent expiry — a recurring class, four live instances

This class deserves its own heading because it has already fired twice and nothing detects it.

1. **`agent_core/providers/fish_tts.py:53-59`** — *"**Free through 2026-08-31**… When it lapses this will start failing."* `DEFAULT_MODEL = "s2.1-pro-free"`, and **`backend/.env:386` still sets `FISH_TTS_MODEL=s2.1-pro-free`.** Today is 2026-09-03. **Lapsed, never flipped.**
2. `provider_tts.py:113-115` — Cartesia `sonic-2` sunsetted, returning 400 for every non-English voice. Already remediated to `sonic-3.5`; the class recurs.
3. **`policy_rule_sets.effective_to`** — an expiring statutory rule set silently drops the platform to hardcoded fallbacks, with WhatsApp/SMS/email losing calling-hour bounds entirely (P4).
4. `tests/test_contact_policy.py:287` — a hardcoded date that expired on 2026-09-02 (W0.1), joined by a second on 2026-09-14.

**Roadmap action (Wave 1):** one test that fails when any dated constant in the tree is within 30 days of expiry. Cheap, and it closes a class rather than four instances.

---

# High-risk register — shipping protocol per refactor family

| # | Refactor family | Irreversible consequence | Shipping protocol | Rollback | Validation |
|---|---|---|---|---|---|
| **H1** | Any Alembic revision touching consent, contact, payments, dialing | The downgrade destroys the evidence (I1) | **Expand-migrate-contract, never one revision.** Additive half → code writing both, reading old → verify → contracting half in a *separate release*. Every new `downgrade()` must be non-destructive or documented one-way in the module docstring | **Do not rely on `downgrade`.** `pg_dump` immediately before; restore-from-dump is the rollback. **No backup procedure exists in this repo — write one first** | `RUN_ALEMBIC_ROUNDTRIP=1` in CI (currently `0`), plus `test_schema_parity.py`. Stop writing `op.execute("CREATE TABLE …")` — the drift regex only sees `op.create_table`/`op.add_column` |
| **H2** | Consolidating the five consent-blocking constant sets; anything in `contact_policy.py` | A widened gate places a call outside 08:00–19:00, to a DND number, or past a cap. **That call has happened.** | **Shadow first.** Run new alongside old, log both verdicts at WARNING (the only level that currently reaches a sink), require **zero divergences over a full book sweep** before the new path decides anything. Separate compliance review | Feature-flag through `platform_switches` (fail-closed by construction), **not** `os.getenv` — an env flag needs four process restarts | `test_contact_policy.py`, `test_outbound_kill_switch.py`, `test_outbound_conduct.py`, `test_demo_call_waiver.py`, `test_customer_timezone_is_untrusted.py`, **plus zero shadow divergence**. W0.1 first, or a new failure is indistinguishable from the old one |
| **H3** | `twilio_ops.py`, `outbound.py`, `campaigns.py`, `cadence.py`, `treatment/enact.py` | A duplicate dial or SMS to a real borrower | **Flip `outbound.enabled` off → deploy → replay a recorded campaign against a Twilio test credential → re-enable.** Never deploy a dialing change and enable dialing in one step | `platform_switches.set_enabled("outbound.enabled", False)` — but `_TTL_SECONDS = 2.0` (`platform_switches.py:88`) and `:230` invalidates only the calling process, so it converges across the four diallers in ~2s. **It is not instantaneous; do not advertise it as such** | The four outbound suites, plus the test report 25 says is missing: *a campaign must not re-queue after a Twilio read timeout*. Note `cadence.py:224-228` and `campaigns.py:611-625` make **opposite** decisions on the same ambiguous-failure state — a refactor that unifies them will silently pick one, and one is wrong |
| **H4** | Any data-access refactor **before** RLS is on | A dropped predicate returns another bank's borrower records with a 200 — a reportable DPDP breach you cannot un-disclose, and per P2 nothing logs it | **Gated behind P5. Do not start.** | **None.** The disclosure has occurred | `test_cross_tenant_reads.py` — which exists *because* seven list accessors historically had no tenant `WHERE`, and `list_callbacks` had none at all |
| **H5** | Moving imports; extracting modules; splitting `main.py`/`db.py` | Not data loss — **silent security downgrade.** A route leaving the global middleware loses auth and permission enforcement, and both are already off on this deployment, so the regression is undetectable in testing | One module per PR; assert the route inventory before and after; never combine an extraction with a behaviour change | `git revert` genuinely works here — *if you catch it*. That is the problem | Route-inventory diff test + `test_production_hardening.py`. **Do not touch any file carrying `# noqa: E402`** |
| **H6** | Enabling `LOG_FORMAT=json` | Borrower phone numbers, in the bare-digit form the redactor cannot match, written to a retained log store | Fix `pii_redact.py:22-58` for bare digits **and** run the redactor over `extra` fields and tracebacks (it fails open at `observability.py:349-350`); enable in one non-production environment; sample by hand; then roll forward | Unset and restart — **but purge what was already written** | Hand inspection of sampled output |
| **H7** | Upgrading Pipecat, or adding any extra to `requirements-voice.txt` | A rebuild silently changes the runtime that terminates borrower calls, with no code change and no review — and no image digest to compare against | Add `-c requirements.txt` to `Dockerfile:41` **first**; then pin; then one package per PR; then re-run `scripts/run_voice_evals.py` | Rebuild from the previous SHA — which requires P1 | The 26 voice test files CI installs voice deps specifically to collect |

---

# The "do not do this until X" gates

1. **Do not ship any refactor at all until images are versioned and a rollback procedure exists (P1).** Today "roll it back" is not an executable instruction.
2. **Do not ship a refactor whose correctness you want to observe until `api` and `voice_insurance` have a root log handler (P2)** — and do not enable JSON logs until `pii_redact` matches bare-digit phones.
3. **Do not move any indented import until someone has documented why it is where it is.** **2,177 local imports and 66 `# noqa: E402` markers across 28 files**, and `ruff.toml` explains why: *"These modules set `DB_PROCESS_ROLE` / `sys.path` / `load_env()` before importing db… Moving those imports to the top binds config too early."*
4. **Do not refactor SQL-emitting code in `db.py`, `ops_screens.py`, `followups_db.py` or `main.py` until RLS is on with a `NOBYPASSRLS` role (P5).**
5. **Do not enable RLS until `provision-role` has run** — enabling as a BYPASSRLS role looks like it worked and changes nothing.
6. **Do not make the API multi-tenant until per-request tenant binding replaces the process-level `TENANT_ID`** — and close the `UNKNOWN-CALLER` global PK first (`voice/persist.py:28-54`), or the second tenant in one database inherits the first tenant's sentinel customer.
7. **Do not write another `op.execute("CREATE TABLE …")`, or add a column to `sql/` without a mirroring migration.** And **create `sql/23_outbound_evals.sql` or delete the reference at `0096:7`** — today a fresh install cannot satisfy the outbound publish gate that `.env:405` turns on.
8. **Do not deploy a dialing change and enable `outbound.enabled` in the same step.**
9. **Do not run `alembic upgrade head` against a customer database without a `pg_dump` taken immediately before.** Several revisions mutate real rows unconditionally, and `0101`'s downgrade is `pass`.
10. **Do not seed `policy_rule_sets` in production as a "cheap win."** It is a prerequisite (P4), but publishing a statutory rule set *changes what the platform is allowed to do* — it goes through H2's shadow protocol, not an ordinary deploy.
11. **Do not run `_make_populate/submission` packaging scripts** — `_make_submission_zip.py:11-31` omits `PRAXIST-main` from `SKIP_DIR_NAMES`, and shipping that vendored tree to a third party breaches its licence.
---

## 6. What this roadmap recommends AGAINST, and why

A modernization plan is judged as much by what it refuses to schedule as by what it schedules. The brief's constraint is explicit — *do not create abstraction layers merely to satisfy a theoretical architecture diagram*, and *do not recommend rewrite-from-scratch unless overwhelming evidence proves incremental modernization is infeasible*. Each refusal below is a considered position, not an omission.

### 6.1 Rewrite from scratch — refused, and the evidence is overwhelming in the *opposite* direction

The brief permits a rewrite recommendation only on overwhelming evidence that incremental modernization is infeasible. The evidence points hard the other way, on five independent counts:

1. **The seams already exist.** Incremental migration requires places where old and new can coexist. This tree has them and they are documented: `FeatureProvider` Protocols in all three engines (`agent_core/treatment/features.py:397`, `reco/features.py:193`, `authority/features.py:87`), `Recommender` at `treatment/scoring.py:183`, the cursor-as-parameter pattern at `treatment/decisions.py:41-61`, a real port at `work_runtime/api.py:1-17`, one `create_engine` site, and PEP 562 lazy attributes on `agent_core/cards/__init__.py` with the failing import chain written into the comment. A codebase with no seams justifies a rewrite. This one is *made of* seams that were never fully used.

2. **`main.py` has zero importers.** For a 5,448-line, 314-route god file, that is a remarkable property: it is a pure sink. Nothing depends on the worst-shaped file in the tree, so nothing has to be rewritten to change it.

3. **The framework does not leak.** `fastapi`/`starlette` appear in 3 of 267 backend modules; `HTTPException` appears 202 times and all 202 are in `main.py`. The domain is already portable — which is exactly the property a rewrite is usually undertaken to obtain.

4. **Half the domain is already pure.** 51 of 102 domain-intent modules (12,414 lines) have no SQL, no `db` import, and no provider SDK. A rewrite would re-type code that is already in its target state.

5. **The institutional memory is the asset, and a rewrite burns it.** This repository documents its own incidents in-place: `money_inr.py:10-23` names the divergent copies it replaced; `env_utils.py:1-13` names the import cycle it was extracted to break; `pg_errors.py:22-30` names the psycopg2/psycopg3 SQLSTATE trap and the 42830 message hazard; `Habibi/src/api/config.ts:62-75` names the dropped-timeout bug; `api/outbound.ts:301-307` documents a wire-contract defect the frontend could not fix from its side; the CI workflow's own comments record that `idempotency_keys` was missing from `sql/*.sql` so *"every 'idempotent' write silently duplicated"*, and that a 1000px padding once shipped. That is years of hard-won knowledge encoded where the next engineer will read it. A rewrite discards it and re-earns every one of those bugs at full price. **This is the strongest argument against a rewrite in this repository and it is worth more than any structural argument.**

The one honest counter-argument — `db.py` at 18,087 lines — is a case for *strangling one file*, which Wave 5 sets out, not for replacing a platform.

### 6.2 A repository / DAO layer — refused

The reflex fix for "101 modules import `db`" is a repository layer. It is refused because the repository **already has** the pattern that solves this and uses it correctly in the engines: `FeatureProvider` is a domain-owned Protocol with a `SqlFeatureProvider` implementing it. That is a repository pattern applied exactly where it pays — one narrow interface per decision, defined by the consumer. Generalizing it into a `repositories/` package for all 440 `db.py` functions would produce ~440 pass-through methods, double the number of places a tenant predicate can be dropped, and add a hop to every read. **Extend the existing pattern to the specific call sites that need substitutability. Do not build the generic layer.**

### 6.3 A service / application layer — refused

There is no `services/` package and the roadmap does not add one. The work that a service layer would hold is already owned: `contact_policy.admit` is the contact Gate, `agent_core/authority` is the waiver matrix, `outbound` owns reserve/suppress/place, `promise_fulfillment.settle_promises` is the promise clock. What is missing is not a layer — it is that **28 HTTP handlers orchestrate those owners directly instead of calling one function that does**. The fix is to name the missing *functions* (Wave 3: the outbound gate sequence is one function, not a layer), not to erect a tier above the ones that work.

### 6.4 A DTO layer between `schemas.py` and the domain — refused

`schemas.py` has exactly two importers, `db` and `main`. 247 wire models and the domain never sees them. That is the outcome a DTO layer is built to achieve, already achieved. Adding DTOs would create a third representation of every payload.

### 6.5 Rewriting the 2,131 function-local imports as top-level — refused

They look like a code smell and they are load-bearing. `requirements-voice.txt` is deliberately kept out of `requirements.txt` so a CRM API upgrade is not coupled to Pipecat's transitive graph; the lazy imports are what let one codebase run in images with different dependency sets. `tests/test_import_cycles.py` defends the order. Converting them to eager imports would break the image split — a real, deployed property — to satisfy a style preference.

### 6.6 Further splitting `agent_core/` — refused

Four engines implementing the same gated pipeline is not accidental duplication; it is the same *shape* answering four different questions (treatment, reco, authority, live QA). `09-canonical-implementations.md` states the rule this roadmap follows: **do not merge naming collisions.** Four meanings of **Offer**, three of **Handoff**, and **Cadence** versus HTTP retry are different questions, and collapsing them would be a worse bug than leaving the copies. The one genuine over-abstraction here — three `FeatureProvider` Protocols each with exactly one SQL adapter, described by `34-ai-code-patterns.md` as a speculative seam — is *cheap and harmless*, and is where Wave 5's substitutability will actually be needed. Leave it.

### 6.7 A frontend rewrite, or introducing a global state manager — refused

`03-frontend-architecture.md` measured the thing a rewrite would be for and found it absent: there is **no god context**, global client state is small (theme, sidebar, notification-read set), the layering `routes → components → api/data/lib` is clean with **zero** `components → routes` edges, and the app graph has no cycles. `29` and `30` then found a well-built primitive layer that the feature surfaces route around. That is an adoption problem with a 44-route surface — precisely the thing incremental extraction fixes and a rewrite makes worse. The frontend needs `AppShell` extracted once, the god routes decomposed, and the existing primitives adopted. It does not need Redux and it does not need a new app.

### 6.8 Reporting `backend/rls.py` as dead code — refused

633 lines, zero importers, and it is the derivation of a row-level-security plan for a system whose RLS is currently off with tenant predicates hand-written at ~290 sites. Reaping it would delete the design for the control that closes the largest latent isolation risk in the platform. It is **orphaned-but-intentional**: it must be adopted or retired by an explicit decision, never silently deleted. The same classification protects `agent_core/tools/grant.py`.

### 6.9 A "big bang" `db.py` split — refused in favour of the strangler in Wave 5

Cut experiments show the coupling is one file, not diffuse: baseline SCC 76; removing `db.py`'s outgoing **or** incoming edges collapses it to 19, while partial cuts give 71/73/75. The tempting reading is "one big move fixes everything." The correct reading is the opposite — because partial cuts buy almost nothing, a half-finished split leaves the codebase strictly worse than before it started, with two persistence homes and no benefit. Wave 5 therefore carves by **domain slice with a re-export shim**, so every intermediate state is shippable, rather than by layer.

### 6.10 Adopting an ORM — refused

There is no ORM by deliberate choice (`alembic/env.py` sets `target_metadata = None`; `12-data-model.md` records the reasoning). Every query amplification in this tree is an explicit Python loop, which is why report 13 could enumerate them at all. Introducing SQLAlchemy ORM or SQLModel now would touch every one of the ~248 hand-written tenant predicates in the same change that introduces implicit lazy-loading. That is the single highest-risk change available in this repository and it buys ergonomics.

### 6.11 Do NOT flip `TEMPORAL_ENABLED`, or write anything new against `work_runtime`, until the port is complete

This is the one item in the roadmap where the **absence** of a seam is a live production hazard rather than a maintenance one. Verified: `work_runtime/api.py` exposes **3 operations**, `adapter_pg` exposes **7**, there is **no `Protocol`** anywhere in the package, `agent_core/clerk.py:17,18` imports the port and the concrete adapter on consecutive lines, and `treatment/enact.py:702` and `sweep.py:243` insert into `work_runtime_jobs` directly, bypassing both. Complete the port (Wave 5) before the flag is ever flipped.

### 6.12 Do NOT reorganise `main.py` by prefix wholesale

Measured: `/providers` spans 3,920 lines for 144 of its own; `/customers` spans 3,901 for 31; `/tts-voices` 2,565 for 51; `/kb` 2,170 for 197. A full 78-prefix reorganisation is a 5,400-line rewrite with **no importer to benefit**, and only `tests/test_authz.py` catching mistakes. **Six dense routers, or nothing** (§5.2).

### 6.13 Do NOT schedule a vocabulary alignment

`02-domain-capability-map.md` correctly documents that SQL, HTTP and the UI still carry pre-`CONTEXT.md` spellings — `bots`/`bot_id` where the glossary says **Mouth**, and so on. It is tempting and it is refused, because `platform_switches.py:60-66` states the governing constraint: renaming a key *"would orphan the row an operator has already enabled, silently making the demo more restrictive at the moment they least expect it."* Every DB-keyed switch, every `policy_rules.kind` string and every status literal backed by a `CHECK` has the same property. **A rename here is a data migration, not a refactor.** Fix names only where a file is already being rewritten for another reason.
---

## The wave summary

| Wave | Name | Gate to enter | Dominant risk | Parallel with |
|---|---|---|---|---|
| **0-A** | **Baseline — can we ship it and undo it?** | none | none (all additive) | 0-B |
| **0-B** | **Baseline — can we tell if we broke it?** | none | none (tests only) | 0-A |
| **1** | **Dead-code verification and deletion** | 0-B W0.1 (green suite) | none | 2A |
| **2** | **Adopt the owners that already exist** | 2A: none · 2B: 0-B | cosmetic → user-visible | 1 |
| **3** | **Canonicalize the regulated decisions** | **0-A P1,P2,P5 + 0-B W0.1,W0.5,W0.6,W0.7,W0.10** | **regulated** | — (serialise) |
| **4** | **The API boundary** | 0-B W0.2 | user-visible → regulated (4-3) | 6-1, 6-2 |
| **5** | **Carve `db.py`; six routers out of `main.py`** | **0-A P5,P6 + 0-B W0.4,W0.8 + Wave 4** | internal (silent security downgrade — H5) | 6, 7 |
| **6** | **Frontend** | Wave 1 (delete first) | user-visible | 4, 5, 7 |
| **7** | **Infrastructure isolation** | none | none | 5, 6 |

**Three ordering claims are load-bearing and each is measured, not conventional:**

1. **Wave 4 before Wave 5** — response shapes are hand-assembled inside the file Wave 5 splits, and the wire is unvalidated on both sides.
2. **Wave 1 before Wave 6** — 22 of the `components/ui/*` files that reports 27/29/30 scope their remediation to are dead.
3. **Wave 3 after all of Wave 0** — six of nine canonicalization targets have no test that would fail on a behaviour change.

And one claim the evidence **refuted**: the brief's example puts dead-code verification early partly so it shrinks later waves. It does that for the frontend and **not at all** for the backend — every live Tool Grant formula is in a reachable module.

---

## Quick wins — start here

Ordered by value ÷ risk. Everything in this table is **behavioral risk: none or cosmetic**, and every one can begin today.

| # | Action | Why it is a win | Wave |
|---|---|---|---|
| 1 | **Tag images by commit SHA; push to a registry; write the rollback down** | Turns "we'll roll it back" from a claim into an instruction. Blocks everything else | 0-A P1 |
| 2 | **Fix the two date-bomb fixtures** (`test_contact_policy.py:287`, `test_voice_write_idempotency.py:36`) | The suite goes green, so a failure starts meaning something. One fires 2026-09-15 | 0-B W0.1 |
| 3 | **Add `pytest-cov` with no threshold** | Converts every "no test reaches this" claim in this series from argued to measured. One CI line | 0-B W0.2 |
| 4 | **Delete the 22 dead shadcn wrappers + 18 npm deps** | Removes 2,221 lines and re-scopes three prior reports' remediation surface. The shipped bundle does not change | 1 |
| 5 | **Import `BLOCKING_CONSENT` at its 3 copy sites** | Four frozensets verified identical — a provable no-op that consolidates a DPDP rule | 2A-1 |
| 6 | **`detectors.py:297-298` → import the RBI constants** | Deletes the only *unpinned* restatement of the calling window. Numbers already match | 3-2 |
| 7 | **Pass `channel_tools=` at `skills/runtime.py:194,197`** | **Two lines.** Closes the one *verified* Tool Grant divergence, and needs none of `grant.py` | 3-7 |
| 8 | **`-c requirements.txt` at `Dockerfile:41`** | Makes the voice image's dependency set intentional. Expect it to fail first — that failure is the finding | 7-2 |
| 9 | **Delete `Habibi/bun.lock`; add `packageManager`** | One dependency truth. 41 days stale, unused by CI, nothing that ships changes | 7 |
| 10 | **Add `npm run build` to the frontend workflow** | CI never builds today; catches the Vite 8 / Tailwind 4 / nitro-beta class | 0-A |
| 11 | **Fix `FISH_TTS_MODEL`** | The free model lapsed 2026-08-31 and `.env:386` still selects it | 0-A |
| 12 | **Add an expiry test** — fail when any dated constant is within 30 days | Closes the *class* behind items 2 and 11, plus the `policy_rule_sets.effective_to` cliff | 1 |
| 13 | **CI import-boundary test** in the base image | Converts a packaging-masked boundary into a checked one. One CI step | 7-1 |
| 14 | **`routes/sandbox.lazy.tsx:432`** — route the 7th fetch through `authHeaders` | One line; restores the frontend's one-transport property | 6-1 |
| 15 | **Delete the `[tool.vulture]` block** | Configures a tool installed nowhere | 1 |

---

## Cross-cutting refactors

Four items cut across every wave and must be scheduled as programme-level constraints rather than tasks:

**X1 — Tenant isolation.** ~290 hand-written predicates (168 SQL literals + 312 `db._tenant()` call sites, by two different counting methods), RLS off, and no un-adopted canonical module to wire — this is a **missing mechanism**, not duplication. It is why P5 sits in Wave 0-A: it converts the most dangerous refactor error in this codebase from a silent 200-with-another-tenant's-rows into an empty result set.

**X2 — The `APP_ENV` master switch.** Read in 11 production modules in two logically opposite directions (finding D1), and part of a config surface of **198 `os.getenv` sites over 149 variables across 78 files**. Every wave that moves code moves a config read, and with a lazy `load_env()` the *timing* of that read is load-bearing.

**X3 — Observability.** Until `api` and `voice_insurance` have a root log handler and the redactor matches bare-digit phone numbers, **no shadow run in Wave 3 is readable and no silent regression in Wave 5 is detectable.**

**X4 — The vocabulary split.** `02-domain-capability-map.md` documents that SQL, HTTP and UI still carry pre-`CONTEXT.md` spellings (`bots`/`bot_id` for **Mouth**, and so on). **This roadmap deliberately does not schedule a vocabulary alignment**, because `platform_switches.py:60-66` states the governing constraint: renaming a key *"would orphan the row an operator has already enabled."* **A rename here is a data migration, not a refactor.** Fix names only where a file is already being rewritten for another reason.

---

## Analyst disagreements, resolved

Recorded with both methods rather than silently reconciled, per this series' convention.

**1. The size of the backend coupling knot: 76 vs 107 vs 110 vs 112.** Report 38 said 76; report 05 said ~108–111; the two analysts here measured 107 and 112 independently. **Resolved, and it is a resolver difference, not an error.** The dependency-order analyst reproduced all three by varying one rule — how `from pkg import sub` is attributed. Package-preferring gives 76; submodule-preferring gives 107; both-edges gives 110. The architecture analyst's 112 is a fourth convention (longest known module prefix, no synthetic parent edges). **This roadmap uses submodule-preferring (107)** because package-preferring undercounts real module-to-module coupling. **Every relative result — which cuts help, and by how much — reproduced identically across all conventions**, so no recommendation depends on the choice.

**2. Does cutting `db.py` dissolve the knot? 17 vs 41.** Same cause. Both analysts agree on the two things that matter: **no partial cut works**, and **the graph does not become a DAG.** The architecture analyst's residual of 41 names the surviving cluster — the agent-turn core (`agent_core.turn`, `understanding`, `guardrails`, `prompt`, `tools.*`, `llm_gateway`, `azure_openai`) — which is genuinely mutually recursive and **not `db.py`'s fault.** Stated in the roadmap as: carving `db.py` will not make the import graph acyclic, and nobody should promise it will.

**3. Is the `_FLOW_CONTROL_TOOLS` 10-vs-11 gap drift?** Reports 06 (DUP-01) and 38 (C3) say yes. **The duplication analyst disproved it** by reading all three literals member-by-member and finding the pin at `tests/test_tool_grant.py:137-147` that asserts the *permitted form* of the difference. **Resolution: not drift.** The roadmap carries the corrected finding — the real gap is that the pin sits behind `pytest.importorskip("voice.tools")` and therefore never runs in CI.

**4. How many outbound gate sites, and in what order?** Report 38 said seven sites in one order. The duplication analyst found **two distinct orderings** and that `payment_events.py` calls no `suppress` at all; the testing-risk analyst counted **11 `contact_policy.admit` call sites**. **All three are correct and answer different questions:** 38 counted sites where reserve+admit+place co-occur; the testing analyst counted every `admit` caller (including non-dialling purposes); the duplication analyst counted orderings. The roadmap uses seven for the sequence and 13 for `admit` adoption, and treats the ordering split as the finding.

**5. Tenant predicate count: 248 vs 290 vs 168+312.** Three regexes, three answers, same order of magnitude. Reported as a range with the methods attached; nothing depends on the exact figure.

**6. Lazy import count: 897 vs 2,131.** The dead-code analyst's AST walk found 2,131 function-local import statements against the corpus's ~897. The higher figure is the one this roadmap uses, because it was produced by the method that also had to resolve every one of them into a graph edge.

**7. `nltk`/`aiohttp` CVE attribution.** Report 39 could not reproduce report 21's attribution from the saved artifact. The migration-risk analyst weights 21 higher (it names package, version, advisory and reachability) but flags the disagreement. **Unresolved; not load-bearing for any sequencing decision.**

---

## Corrections this roadmap makes to the prior reports

1. **`_FLOW_CONTROL_TOOLS` is not drift** — it is pinned. Reports 06 and 38 are wrong; `voice/tools.py:79`'s "the two still differ" comment is stale.
2. **`db.py:1938`'s `"10:00–19:00 IST"` is not a display literal** — it feeds `_callback_dnd_active` and changes a DND verdict, and it disagrees with `db.py:5468` in the same file.
3. **The outbound gate is written in two orderings, not one order seven times**, and `payment_events` writes no suppressed attempt row at all.
4. **`BLOCKING_CONSENT` has four definitions, not three** — `capture.py:331` `_CONSENT_BLOCKING_STATUSES` is a fourth under a different name.
5. **`_fmt_inr` has three cross-module reach-throughs, not two** — `agent_core/treatment/enact.py:242` was missed.
6. **Two more stale-window sites** than report 06 listed: `schemas.py:42` (wire default) and `agent_core/skills/packs/ptp-negotiate/SKILL.md:32` (**prompt text the model repeats to a borrower**).
7. **Account tail has four algorithms, not two** — add `ops_screens.py:415/674` and `voice/persist.py:939`.
8. **`api/config.ts` holds 6 of 7 fetches — and the 7th bypasses `authHeaders`** (`routes/sandbox.lazy.tsx:432`).
9. **`ui/card.tsx` and `ui/tooltip.tsx` are dead** — report 07 missed both.
10. **`ui/form.tsx` is dead, not merely unadopted** — report 30 lists it as a correct primitive with 0 importers awaiting adoption; it is 171 lines of deletable code.
11. **A second date bomb exists** (`test_voice_write_idempotency.py:36`, fires 2026-09-15) — not in any prior report.
12. **`sql/23_outbound_evals.sql` is referenced by `alembic/…0096:7` and does not exist**, while `.env:405` turns the gate that depends on it **on**.

---

## What could not be verified

- **Nothing was executed.** No build, no server, no test run, no database, no migration, no container. Every number in this roadmap is static. In particular **nobody in this audit has seen the suite pass or fail** — W0.1's "the suite is red" is derived from reading a date literal against a guard, and W0.2 exists precisely to convert this whole class of claim into measurement.
- **Coverage is call-graph-derived, never measured.** No `pytest-cov` exists. Every "no test reaches this line" statement is an inference from imports and call sites.
- **Anything driven by a tenant database row** — `service_class` bindings, MCP connectors, published card rows, `prompt_versions.flow` node keys, whether `policy_rule_sets` has ever been populated in a real deployment, whether account ids are all-numeric (which decides 2B-3's risk). The read-only constraint forbade a `psql` session.
- **HTTP route reachability** for the 26 routes with no matched frontend caller. That is a traffic question.
- **Whether `provider_voice_sync.py` is ever run by a human.**
- **Column-level dead data.** All 171 tables are referenced; columns were not analysed.
- **Whether the six `SELECT *` routes' extra columns are actually read by the frontend** — this decides the size of 4-4 and was not checked.
- **Whether either CI workflow is a required check** on the branch.
- **No scanner ran.** Knip, vulture (configured but installed nowhere), mypy, pyright, pip-audit, Trivy, Semgrep — none is present on this machine or in CI. Every count here comes from purpose-written scripts, so treat them as **one independent method, not as several agreeing tools.**
- **Effort estimates** appear only for Wave 0 (~13 developer-days), where the work is enumerable. **No estimate is offered for Waves 1–7**, because the honest inputs — team size, deploy cadence, how much of Wave 0 reveals — do not exist yet.
