# CONFLICTS AND FALSE POSITIVES

**Date:** 2026-09-03
**Mode:** Read-only. No application file was modified.
**Purpose:** Where two or more of the 41 audit reports disagree about the same code, this document states both claims, records the evidence I examined, and says which reading survived contact with the source.

**Method.** Every conflict below was resolved by opening the file, not by preferring the newer report, the more confident report, or the one with more citations. Where a claim could be settled by an indexed search over `backend/**/*.py` or `Habibi/src/**`, it was. Where it needs a running database it is marked **UNRESOLVED — needs runtime** and carries the exact query.

**Confidence** is one of: **Certain** (read at source this session, quoted below) · **High** (re-derived from source, mechanism traced) · **Medium** (source read, but a runtime fact could still change the conclusion) · **Unresolved**.

---

## Why this document exists

Three of the fifteen conflicts below share one shape, and it is worth naming before the table, because it governs how the rest of the corpus should be read:

> **A conclusion drawn from an absence, produced by a search that could not have found the evidence.**

`07-dead-code.md` states its own scope honestly — *"No hits in `main.py`, `worker.py`, `bot_worker.py`, `voice/`, `outbound.py`, `mission.py`"* — and that scope is a hand-listed set of files. A reference in a file not on the list is invisible to it. That is not carelessness; it is the documented method. The defect is that the **verdict** was then written as though the scope were the codebase.

**Every "no importer found" claim in this corpus should be re-read with its search scope stated. Where the scope is a hand-listed file set or a symbol name, the verdict is a hypothesis, not a finding.**

I committed the same error class myself while preparing this consolidation and it is recorded in §16.

---

## C1 · `CAMPAIGN_RUNTIME_ENABLED` — dead or live?

**Confidence: Certain. Report 07 is wrong.**

| Report | Claim |
|---|---|
| `07-dead-code.md:119` | Class **B — highly likely dead**. *"Documented in `.env.example` as cadence/campaign dialer. No hits in `main.py`, `worker.py`, `bot_worker.py`, `voice/`, `outbound.py`, `mission.py`. Master outbound switch is Postgres `outbound.enabled`. Not even in `test_platform_flags.py`'s parametrize list."* |
| `31-runtime-wiring.md:157` | Lists it as **live**, readers `campaigns.enabled`, `cadence.enabled` |
| `34-ai-code-patterns.md` §5 | *"Live: `cadence.py` and `campaigns.py` call it. `07` listed it as unread; that is stale."* |
| `41-adversarial-review.md` §2.1 | Live; report 07 is wrong |

**Evidence examined.** Indexed search over `backend/**/*.py`:

```
backend/cadence.py:67:    from agent_core.platform_flags import campaign_runtime_enabled
backend/cadence.py:69:    return campaign_runtime_enabled()
backend/campaigns.py:61:    from agent_core.platform_flags import campaign_runtime_enabled
backend/campaigns.py:63:    return campaign_runtime_enabled()
backend/agent_core/platform_flags.py:77-79:  def campaign_runtime_enabled() -> bool: ... _flag("CAMPAIGN_RUNTIME_ENABLED")
backend/alembic/versions/20260826_0102_platform_switches.py:4:  names it as an outbound-engine gate
```

**Resolution.** The flag is **live and load-bearing**. It is read through a **function-local import inside a differently-named `enabled()` wrapper** — which is exactly why a name-scoped grep over a fixed file list could not see it. `cadence.py:349` and `campaigns.py:461` gate on it; `call_closer.py:749` short-circuits on `cadence.enabled()`; `main.py:4994` returns `409 campaign_runtime_disabled`.

**Consequence of acting on report 07.** Delete the flag and hardcode `True`, and `call_closer.py:749` stops short-circuiting: every call outcome opens a retry ladder and **the platform begins auto-redialling borrowers on a timer.** `.env.example:592-594` describes "off" as *"nothing dials on a timer."* Detection latency is **L2 at best, L4 if volume stays under the frequency cap** — the only signal is a contact-frequency complaint months later.

**Action required.** The correction must be written **into report 07 itself**, not left standing in reports 31, 34 and 41. Report 07 is the document titled "dead code"; it is the one a cleanup PR will cite.

**The crisp contrast, which makes the method failure legible.** Report 07 lists `AGENT_CARDS_ENABLED` in the *same class B table*, one row above. I verified that one too:

```
.env.example:309 · platform_flags.py:18-19 · tests/test_platform_flags.py (3 sites)
```

**Zero application readers. `AGENT_CARDS_ENABLED` is genuinely dead.** Two flags, one table, one verdict, and only one of them is right. The report had no way to tell them apart because its method could not see through a function-local import inside a renamed wrapper.

---

## C2 · Is the flow-control literal gap drift?

**Confidence: Certain. The roadmap's retraction is correct.**

| Report | Claim |
|---|---|
| `06-duplication.md` DUP-01 | Three statements of one set; `flow_graph._FLOW_CONTROL_TOOLS` has 10 and **omits `capture_call_goal`**; presented as divergence risk **critical** |
| `38-architecture-boundaries.md` C3 | Same, as a **Critical**: *"`ALWAYS_ON` holds 11 names; `_FLOW_CONTROL_TOOLS` holds 10 — no `capture_call_goal`. `voice/tools.py:79` says so outright: 'the two still differ.'"* |
| `40-refactoring-roadmap.md` | **Retracts it.** Verified member-by-member; `tests/test_tool_grant.py:137-147` asserts the *permitted form* of the difference |
| `41-adversarial-review.md` | Confirms the retraction |

**Evidence examined.** `grant.VOICE_ALWAYS` is a `frozenset[str]` of 11 names. `voice/tools.ALWAYS_ON` is the same frozenset, pinned equal by `tests/test_tool_grant.py:133`. `flow_graph.py:773-784` is a **`dict[str, str]` of editor descriptions** — a different artifact answering a different question (what the Flow authoring catalog offers), not a third copy of the runtime floor. Both `capture_call_goal` and `verify_identity` are in `CATALOG`, and the catalog supplies that half.

**Resolution.** **Not drift.** The difference is managed and pinned. `voice/tools.py:79`'s comment *"the two still differ"* is stale and should be corrected in place.

**But one real defect survives the retraction, and it is narrower and sharper.** `tests/test_tool_grant.py:131` opens with `pytest.importorskip("voice.tools")`. So the `VOICE_ALWAYS == ALWAYS_ON` assertion **silently skips wherever pipecat is absent — the API image and CI.** The two agree today; nothing outside the voice container would notice if they stopped.

**Action required.** Propagate the retraction back into `06` DUP-01 and `38` C3, both of which still carry it as Critical. Then fix the pin's reach.

---

## C3 · "Zero ordering-sensitive route pairs"

**Confidence: Certain. The roadmap's claim is false; report 11's is true and was mis-generalised.**

| Report | Claim |
|---|---|
| `11-api-contracts.md` §6 | *"Checked and cleared — path shadowing. All 314 routes were checked… **Zero occurrences.** Every literal precedes its parameterized sibling."* |
| `40-refactoring-roadmap.md` §5.2 | *"**Zero ordering-sensitive route pairs.** Every same-method, same-arity path pair was checked… none. **Route registration order cannot affect matching**, so `include_router` order cannot change behaviour."* |
| `41-adversarial-review.md` §2.4 | Five pairs exist and work **only because** the static route is declared first |

**Evidence examined.** Verified in `main.py`:

```
1322  GET /handoff/queue              1327  GET /handoff/active
1335  GET /handoff/{interaction_id}                       ← both shadowed if reordered
1951  GET /prompt-versions/published
1960  GET /prompt-versions/{version_id}
2213  GET /agent-studio/skills/scripts
2226  GET /agent-studio/skills/{skill_id}
2915  GET /tts-voices/catalog/sync-runs
2921  GET /tts-voices/catalog/{short_name}
```

And `main.py:2216-2219`, in the handler itself:

> *"Declared above /skills/{skill_id} — FastAPI matches in definition order, and the parameterised route would otherwise swallow 'scripts'."*

**Resolution.** **Both reports measured correctly and one drew the wrong conclusion.** Report 11 asked *"is anything shadowed today?"* — answer, correctly, **no**. The roadmap asked the same question and answered a different one: *"can registration order affect matching?"* — answer **yes, in five places**, and the codebase says so in a docstring.

**Why this is the corpus's most dangerous single sentence.** Three factors compound:

1. `/agent-studio` is the roadmap's **first** router-extraction target *and* its first `response_model` target, so both changes land on the same 26 routes.
2. Moving them invites a grouping pass — reads before writes, collections before items — which is the most natural thing to do and which **reverses the pair**.
3. The nominated validation is a route-table snapshot, `[(r.methods, r.path) for r in app.routes]`, diffed before and after. **That compares a set where the defect is an order**, so it passes. `assert_registry_covers` passes too. The regression surfaces as the script picker returning `skill_not_found`, which nothing in CI exercises.

**Action required.** The validation must be an **ordered list**, and Wave 4-2 must not ship in the same release as the `/agent-studio` router extraction.

---

## C4 · Does persistence depend on the API contract layer?

**Confidence: Certain. Both reports are partly wrong, and the disagreement is a corpus defect.**

| Report | Claim |
|---|---|
| `39-enterprise-readiness.md` | Architecture scored **3**, partly on *"`db.py:26` imports `schemas` — **the persistence layer depends on the API contract layer**"* |
| `38-architecture-boundaries.md:152` | Lists `db.py:18-24` as *"**the only clean part**"* of `db.py`'s imports |
| `38:550` | Files the same edge under *"**What is already right**"*: *"Wire schemas do not leak inward. `schemas.py` has exactly 2 importers."* |

**Evidence examined.** Verified — the import is at **`db.py:24`**, not `:26`:

```python
# db.py:18-24
import contact_window
import money_inr
import tenant_context
import visibility
from env_utils import env_int as _env_int
from pg_errors import is_unique_violation as _is_unique_violation
from schemas import (CallResponse, CustomerResponse, DashboardResponse, HandoffQueueItem, …)
```

And `db.py:1` is the module docstring: **`"""Postgres accessors plus API response serializers."""`**

**Resolution.** Three findings, in order:

1. **The citation is wrong** — `:24`, not `:26`. Report 39 did not re-read at source.
2. **`db.py` is declared as persistence *plus* serialization.** Importing `*Response` types is its stated job, not a leak. Report 38 is right that it is the clean part of a dirty file.
3. **But the violation is real and trivial.** The eight names taken are all `*Response` — pure transport — and `db.py` **constructs** them at nine sites. The remedy is nine function-local imports.

**Scoring an architecture dimension down on a nine-call-site edge, while a sibling report files the same edge under "what is already right", is a corpus defect rather than a code defect.** MASTER-AUDIT raises Architecture to 4 partly on this.

**One consequential detail neither report drew out.** This edge is not merely a layering opinion — it is the **single eager edge that decides whether the `db.py` carve works.** `db → schemas → flow_graph → agent_core.tools → …kb → db` closes the loop through a *type* module, and removing it alongside the lazy callbacks is what takes the coupling SCC from 107 to 17. Cutting the lazy callbacks alone stops at 50. It is one line, and it is a hard sequencing item.

---

## C5 · How big is the backend coupling SCC?

**Confidence: Certain. All four numbers are correct; they measure different graphs.**

| Report | Number |
|---|---|
| `05-dependency-graph.md` | ~108–111 |
| `38-architecture-boundaries.md` | 76 |
| `40-refactoring-roadmap.md` (dependency-order analyst) | 107 |
| `40` (architecture analyst) | 112 |

**Evidence examined.** The roadmap reproduced all of them by varying **one rule** — how `from pkg import sub` is attributed:

| Resolver | Nodes | Coupling edges | Largest SCC |
|---|---:|---:|---:|
| edge → `pkg` (report 38's) | 265 | 883 | **76** |
| edge → `pkg.sub` | 265 | 953 | **107** |
| both edges (what CPython executes) | 265 | 1055 | **110** |
| longest known module prefix, no synthetic parent edges | — | — | **112** |

**Resolution.** **Not an error in any report.** Package-preferring undercounts real module-to-module coupling (`from agent_core.treatment import enact` couples to `enact`, not to the barrel); both-edges adds cycles that are almost entirely `pkg.__init__ ↔ pkg.sub` self-reference, which CPython resolves through the partially-initialised module and which carries no cross-module meaning.

**Critically: every *relative* result reproduced identically across all conventions.** Which cuts help, and by how much, does not depend on the choice. **No recommendation in this consolidation rests on the absolute number**, and MASTER-AUDIT quotes 107 with the convention named.

**A second disagreement inside this one, also resolved:** does cutting `db.py` dissolve the knot — 17 or 41? Same cause. Both analysts agree on the two things that matter: **no partial cut works**, and **the graph does not become a DAG.** The residual of 41 names the surviving cluster — `agent_core.turn`, `understanding`, `guardrails`, `prompt`, `tools.*`, `llm_gateway`, `azure_openai` — which is genuinely mutually recursive and **not `db.py`'s fault.** Nobody should promise that carving `db.py` makes the import graph acyclic.

---

## C6 · Is `agent_core/tools/grant.py` dead code?

**Confidence: Certain. It is orphaned-but-intentional, and deleting it would make the modernization worse.**

| Report | Claim |
|---|---|
| `07-dead-code.md` | Class **B** — *"Docstring: 'Nothing imports this yet.' In-progress migration (ADR-0001), **not abandoned. Do not delete.**"* |
| `10-complexity-smells.md` S-05 | *"Deleting `grant.py` today vanishes from production… That is the deletion test for 'not yet a module.'"* — and then: *"Do not treat `grant.py` as dead and delete it"* |
| `40`, `41` | **ADOPT.** It is the *target* of the canonicalization, not its subject |

**Evidence examined.** Indexed search confirms **zero production importers** — only `tests/test_tool_grant.py`, `tests/test_tool_grant_characterization.py`, and a module-name string at `tests/test_import_cycles.py:35`.

**Resolution.** **There is no real conflict here** — every report reaches the same operational verdict by different reasoning, and report 07 explicitly says *"Do not delete."* It is listed because a reader skimming report 07's class-B table, or report 10's "deletion test", could mistake the classification for a deletion mandate. It is not.

**The reason deleting it would be worse than leaving it** is not the 247 lines of code. It is the ~880 lines of docstring, which are the only record of several facts: why `verify_identity` is in the floor (a regulated post-mortem — and commit `767f1b4` shows it has already been removed once); why the three always-on lists cannot be unified (the API process must not import Pipecat); and why an Offer may never widen a Grant. **`git revert` restores the text; it does not restore the text landing in a repository where somebody knows to go read it.**

---

## C7 · Is `rls.py` dead code?

**Confidence: Certain. No — and two of the reports that called it orphaned are wrong about that specific word.**

| Report | Claim |
|---|---|
| `05-dependency-graph.md` | Orphan; *"Runtime tenant isolation is libpq GUC inside `db`, not this module. Tests/scripts only"* |
| `19-auth-authz.md` §8 | *"**Nothing calls it.** `rls.apply`/`rls.enable` are invoked only from `scripts/rls.py` (a manual CLI) and `tests/test_rls.py`"* |
| `38-architecture-boundaries.md` H5 | *"Its application importer count is **zero**, which is **correct**: it is operator tooling… Flagging it as dead code would be wrong"* |
| `40-refactoring-roadmap.md` | *"inert, not dead"*, with **zero importers** |
| `41-adversarial-review.md` §2.9 | *"**`rls.py` is not orphaned.** It has a real operator CLI importer — `backend/scripts/rls.py:34` `import rls`"* |

**Resolution.** The **verdict** is unanimous and correct: **ADOPT or retire by explicit decision; never silently reap.** The disagreement is about the word *orphaned*, and report 41 is right on the narrow point — `scripts/rls.py:34` is a real importer driving `status` / `plan` / `apply` / `provision-role` / `enable` / `disable`. "Zero **application** importers" is the accurate phrasing, and report 38 gets it exactly right.

**One carve-out inside the carve-out, and it survives.** `rls.py:327 weak_policies` has exactly **one** reference — its own definition. It is genuinely uncalled, **including by that CLI**, and it must still not be deleted: it returns the policies linked to the tenant through nullable columns — *"a table where a row with no parent is visible to every tenant."* Delete it and RLS reports green while those tables stay cross-tenant visible. **Nothing fails; the question simply no longer has a function name.**

That is the general rule this document ends on: **an absent capability produces a missing feature; an absent diagnostic produces a false negative.**

---

## C8 · Do the four consent-blocking constant sets number three, four, or five?

**Confidence: High. Four definitions, nine use sites. Reports 06 and 40 both undercount.**

| Report | Claim |
|---|---|
| `06-duplication.md` DUP-03 | *"restated **three** times"* — `contact_policy.py:37`, `promise_fulfillment.py:29`, `payment_events.py:28` |
| `39-enterprise-readiness.md` | **five** modules under **four** names, adding `capture.py:331` and `agent_core/reco/arbitration.py:39` |
| `38-architecture-boundaries.md` M1 | **five** — same list as 39 |
| `40-refactoring-roadmap.md` §2A-1 | **four** definitions; *"3 definitions, 4 use sites"* in the action table |
| `41-adversarial-review.md` | **4 definitions, 9 use sites** |

**Evidence examined.** The canonical is `contact_policy.BLOCKING_CONSENT = frozenset({"opted_out","dnd","expired"})`. The copies: `payment_events.py:28`, `promise_fulfillment.py:29`, `capture.py:331` (`_CONSENT_BLOCKING_STATUSES` — the same literal under a **different name**, which is why a symbol-name search missed it), and `reco/arbitration.py:39` (`_CONSENT_BLOCKING`).

**Resolution.** Report 06's "three" is an undercount caused by searching the **symbol name** rather than the literal. The roadmap caught the fourth in its prose and then sized the PR from the older count. **A PR scoped for four use sites will be more than twice that** — five of the nine are in `capture.py` alone.

**The member-identity claim itself is confirmed** — all four frozensets are member-identical today, so the consolidation is a provable no-op, and it is cycle-safe because `contact_policy` is a DAG leaf. **Two of the copying modules already import `contact_policy` for other reasons**, so the copy buys nothing at all.

---

## C9 · Is the outbound gate one order written seven times?

**Confidence: High. Two orderings, and one site writes no attempt row at all.**

| Report | Claim |
|---|---|
| `38-architecture-boundaries.md` C7 | Seven sites, one order; *"nothing would fail if it landed in six"* |
| `22-testing-quality.md` | **11** `contact_policy.admit` call sites |
| `40-refactoring-roadmap.md` §3-3 | **Two distinct orderings**, and `payment_events.py` calls no `suppress` at all. **13** `admit` call sites |
| `41-adversarial-review.md` | 7 `place` sites, all gated; `admit` has many more callers |

**Evidence examined.** Verified by indexed search — `outbound.place` has exactly 7 call sites (`cadence.py:492`, `campaigns.py:610`, `main.py` ×2, `treatment/enact.py:384`, `payment_events.py:882`, `scripts/dial_test.py:215`), and `contact_policy.admit` has 13+ callers including non-dialling purposes (`bot_runtime`, `whatsapp_outbound`, `promise_fulfillment`, `written_followup`, `db.py` ×3).

**Resolution.** **All three counts are correct and answer different questions.** 38 counted sites where reserve+admit+place co-occur; the testing report counted every `admit` caller; the roadmap counted orderings. Use **7** for the sequence and **13** for `admit` adoption.

**The roadmap's addition is the real finding and it is not in report 38.** Two orderings exist:

- **A — `reserve → admit → suppress-on-refusal → place`** (5 sites)
- **B — `admit → reserve → place`** (2 sites), and at `payment_events.py:821 → :866 → :882` **there is no `outbound.suppress` anywhere in the module.**

So the invariant *"every refused outbound leaves a suppressed attempt row"* holds at six of seven and is **false at `payment_events`**. `call_attempts` is the only record that a call was *not* placed. **That is a gap in the evidence of a regulated refusal**, which is a materially different finding from "the sequence is duplicated."

---

## C10 · Does a dial escape the contact Gate?

**Confidence: Certain. No — and the corpus never states it plainly, which is its own failure.**

| Report | Framing |
|---|---|
| `06-duplication.md` DUP-02, `40` §3-3 | *"the sequence is written seven times"* — reads as though a dial might escape |
| `41-adversarial-review.md` | **All seven `place` sites are gated.** One chokepoint |

**Evidence examined.** Verified 7-for-7 by indexed search this session: every `outbound.place` call site is preceded by a `contact_policy.admit` **in the same function**:

| `place` | its `admit` | | `place` | its `admit` |
|---|---|---|---|---|
| `cadence.py:492` | `:445` | | `treatment/enact.py:384` | `enact.py:102` |
| `campaigns.py:610` | `:557` | | `payment_events.py:882` | `:821` |
| `main.py:3811` | `:3777` | | `scripts/dial_test.py:215` | `:176` |
| `main.py:4152` | `:4097` | | | |

And `voice/twilio_ops.start_outbound_call` is the sole function reaching the carrier, by its own design note at `:307-311`, with `outbound.place` its only production caller.

**Resolution.** **There is no ungated path to a borrower's phone.** This is the strongest single result in the corpus and no report states it as a headline. It is recorded here as a **false-positive risk in the reader**, not in the reports: a risk committee reading `06` DUP-02 without this correction would materially over-estimate the exposure, **and that is its own kind of audit failure.**

The real defects are in the *ordering* (C9) and in the *evidence left behind* — not in coverage.

---

## C11 · Is the frontend better or worse protected than the backend?

**Confidence: Certain. Worse — and this reverses the usual instinct.**

| Report | Claim |
|---|---|
| `03-frontend-architecture.md` | *"Readiness for feature-oriented migration: **high**"* |
| `27-typescript-integrity.md` | `strict: true`, CI `tsc --noEmit`, essentially no `any` — *"a strong interior lock"* |
| `22`, `30`, `40` | **11 test files for 474 modules**, `environment: "node"`, no jsdom, no Testing Library, no MSW, **zero** component/render/hook/snapshot tests |

**Evidence examined.** `Habibi/vitest.config.ts:22` sets `environment: "node"` with an explicit comment: *"Every suite here exercises a pure function. No jsdom, no DOM shims."* Verified against `package-lock.json`: `@testing-library/*` — **0 occurrences**. **No component can be mounted in this repo without first changing the test infrastructure.** Two of the eleven "tests" are `readFileSync` source greps.

**Resolution.** **Both are true and they are about different things.** The *interior* type lock is genuinely strong; the *behavioural* net is close to absent. `tsc --noEmit` catches a renamed prop and catches nothing about rendering, interaction, conditional visibility, disabled states or effect ordering.

**The sequencing consequence, which is the reason this conflict matters:** the backend has 186 test files and 2,431 test functions; the frontend has 11 for 474 modules. **Frontend refactoring in this repository is markedly less protected than backend refactoring**, which is why the frontend wave sits late rather than early — against instinct, and correctly.

---

## C12 · Is `db.py`'s size a Critical risk?

**Confidence: High. It is a Critical *cost*, correctly measured, wrongly graded as risk.**

| Report | Grade |
|---|---|
| `38-architecture-boundaries.md` C1 | **Critical** |
| `10-complexity-smells.md` S-01 | **critical** |
| `39-enterprise-readiness.md` | Architecture **3**, capped partly by it |
| `41-adversarial-review.md` §5.3 | *"a genuine maintenance problem whose real cost is indirect… **A cost item, not a risk item**"* |

**Resolution.** **No borrower is contacted, charged, or misquoted by `db.py` being 18,087 lines.** The finding is entirely real and the measurement is excellent — fan-in 101, the cut experiments, the section map, the 202-of-239 private reach-throughs. Its consequence is developer velocity, merge conflict, review cost, and the fact that a signature change in `agent_core/treatment/` can break the file 101 modules import.

**MASTER-AUDIT files it as P1 architecture, not P0 regulatory**, and the same demotion applies to three siblings the corpus over-ranks:

- `30` C1 (295 unlabelled controls) — excellent measurement, but these are **internal operator screens**; the exposure is employment-practice, not collections-conduct.
- `29` U11 (`cn()` drops two type tokens) — beautiful forensics; two font sizes render one step wrong.
- `21` S1/S2 (no vuln gate, no Python lockfile) — real, but against an on-prem bank deployment with no public write surface, a transitive CVE is a slower path to a regulatory event than any of the six changes in MASTER-AUDIT's Executive Summary.

**This is not a criticism of those reports.** Each measured its own dimension correctly. The consolidation's job is to rank *across* dimensions, and across dimensions a 2,843-line dead UI kit and a contact-frequency ledger that under-reports a burst are not the same kind of finding.

---

## C13 · Should eleven `APP_ENV` sites adopt `env_utils.env_name()`?

**Confidence: High. No — three of the eleven re-derive on purpose, and the change does not fix what it claims to.**

| Report | Claim |
|---|---|
| `37-integration-boundaries.md` I2 | **One line.** `main.py` should import `env_utils`, because `_IS_PROD` gates the Twilio signature check, the API-key requirement and `/docs` |
| `40-refactoring-roadmap.md` 2A-5 | **Eleven adoption sites**, graded *regulated*, blast radius *"11 modules, 1 line each"* |
| `41-adversarial-review.md` §2.6 | Three of the eleven are deliberate; and 2A-5 does not fix the divergence it names |

**Evidence examined.** Three sites re-derive with a stated reason:

- **`seed_postgres.py:29-40`** reads the `.env` **file**, and its docstring says why: *"a deployment that only sets APP_ENV in .env would otherwise be seen as `dev` while pointing at the production database."* `env_utils.env_name()` reads only the process environment. Adopting it **re-opens that hole** on a script that writes synthetic customers, calls and consent records over whatever is in the target database.
- **`payments.py:29-40`** calls `load_env()` first — same class, smaller blast.
- **`storage.py:41-46`** gates the MinIO dev fallback on the **endpoint** (is it loopback?), not on `APP_ENV`, and documents the staging incident that produced it. **This is the pattern every other guard in the corpus should follow.**

The roadmap's own "must NOT be consolidated" list catches only one of the three (`usage_meter`).

**And the deeper point: 2A-5 does not fix the divergence it is named for.** The divergence is between two *predicates* — `env_utils`'s allow-list reading versus `main.py:205`'s deny-list — but the allow-list lives in `env_allows_dev_key()`, a **different function answering a different question**. `env_name()` is a string normalizer, and eight of the eleven sites compute a boolean that would keep `in {"prod","production"}` verbatim after adoption. **2A-5 is close to a no-op on the divergence, not the regulated change it is graded as.**

**Resolution.** Adopt at **`main.py` only** (report 37's original one-line finding), and separately add an `is_prod()` to `env_utils` that inverts the default. Leave the three deliberate sites alone and record why.

**One unmeasured direction, which is the right one:** `env_name()` also consults `ENV`, which **none** of the eleven sites do. On a box with `ENV=production` and `APP_ENV` unset, adoption flips eight fail-closed sites at once — the correct outcome, and exactly report 37's point.

---

## C14 · How many graders are there?

**Confidence: High. Twenty, not sixteen.**

| Report | Claim |
|---|---|
| `40-refactoring-roadmap.md` §1-0 | *"all **16** `grade_*` functions in `agent_core/eval/graders.py` (registered in a dict at `:406` and dispatched by string)"* |
| `41-adversarial-review.md` §2.8 | **20**, and the `GRADERS` dict at `:406-430` has 20 entries matching one-for-one |

**Resolution.** The four missed are in the **outbound-conduct block** — `no_debt_to_a_third_party`, `stops_after_opt_out`, `no_identifier_into_an_ivr`, `no_offer_after_hardship` and siblings. **A deletion pass working from "16 named" would be operating on a stale list of the highest-risk graders in the file.**

**And the dispatch is wider than either report's framing.** `eval/run.py:52` selects `grader` from the `eval_tasks` **database column**, not only from fixtures. An unknown name returns `{"passed": False, "detail": "unknown_grader:…"}` — **a failing eval that looks like a real regression.** See UNRESOLVED-3.

---

## C15 · Is `test_schema_parity.py` a working drift gate?

**Confidence: High. Not in CI — it compares `sql/*.sql` against itself.**

| Report | Claim |
|---|---|
| `12-data-model.md` §9.2 | Describes it as a real bidirectional control with a named incident |
| `39-enterprise-readiness.md` | Migrations **7**; *"CI enforces schema drift in **both** directions… That is rare and genuinely strong"* |
| `40` D3 | *"a **bidirectional schema-drift check**… `idempotency_keys` was migration-only, so 'every idempotent write silently duplicated'"* |
| `22-testing-quality.md` C9 | **Both halves are inert**, and one cannot fail |

**Evidence examined.** Report 22's mechanism, which the others did not trace: the fixture builds the "fresh" side by replaying `sql/*.sql` into a scratch database and takes the "migrated" side from `db.DATABASE_URL` — **but CI builds `DATABASE_URL` by applying `sql/*.sql` and then `alembic stamp head`. Migrations are never executed.** Both sides of all three comparisons derive from the same source.

Separately, the inline CI check regex-scrapes `op.create_table` / `op.add_column` only. Measured across 102 migration files: **25 `op.create_table` vs 41 raw `CREATE TABLE`; 71 `op.add_column` vs 54 raw `ALTER TABLE … ADD COLUMN`.** It verifies 38% of table creations and 57% of column additions.

**Resolution.** **Report 22 is right and the others over-credit the gate.** The *design* is genuinely good — deriving expectations from the migrations rather than a hand-kept list is the right idea, and its comment records a real caught incident. Its **reach** is the problem, and the correction is to parse raw DDL too, not to abandon the approach. `RUN_ALEMBIC_ROUNDTRIP` is `"0"` in CI and gated twice besides, so **nothing in this repository proves the migration chain applies to an existing deployment.**

---

## §16 · Corrections to my own work in this consolidation

Recorded because a wrong entry in an audit outlives the audit, and because the method failure in C1 is one I reproduced myself.

**1. I ran a recursive `grep -rn` from `backend/` twice and both timed out at 120 s on `.venv`.** The standing note in this workspace says exactly this and I ignored it. Both commands were re-run with the indexed search tool, which is what produced the C1 and C6 verifications. **Every "no importer found" claim in this document comes from the indexed tool, not from a shell grep** — and where a claim rests on a scope, the scope is stated.

**2. My first pass accepted report 07's `AGENT_CARDS_ENABLED` and `CAMPAIGN_RUNTIME_ENABLED` verdicts as a pair.** They are in the same class-B table, one row apart, with the same evidence shape. Verifying them separately is what produced the contrast in C1 — one dead, one live, one method blind to both. Had I checked only the one report 41 flagged, I would have propagated the other unexamined.

**3. I have not independently re-derived the frontend deletion set.** MASTER-AUDIT reports 29 files / 2,843 lines / 22 npm deps on the strength of two independent derivations in reports 40 and 41. I verified only the two files report 07 missed (`ui/card.tsx`, `ui/tooltip.tsx` — both confirmed at zero importers). **The rest is inherited, and it is inherited from a claim that was verified by *re-derivation* rather than by *checking the list*, which is the stronger method — but it is not mine.**

**4. Report 41 is a document I wrote earlier in this same session.** I have treated it as evidence with the same suspicion as the other forty — every one of its load-bearing claims cited above (C1, C2, C3, C9, C10, C13, C14) was re-opened at source here, and §2.7 of that report is itself a correction of an error I made in report 39. Where 41 and another report disagree and I could not re-verify, the disagreement is left open rather than resolved in 41's favour. **One such case:** 41 §2.2 asserts roadmap Batch 1's *"the shipped bundle does not change"* is false for CSS because Tailwind v4 scans source files. I did not test this, and it is recorded as UNRESOLVED-8.

---

## UNRESOLVED — needs runtime evidence

**No runtime evidence was obtainable in this session.** The Docker daemon is down; nothing is listening on 8000 or 3000. No pytest, no migration, no scanner, no request at any target. Each item below carries the exact check.

| # | The question | Why it matters | The check |
|---|---|---|---|
| **1** | **What is in `provider_models.service_class`?** | `factory._import_class` is the **only** dynamic-dispatch site in the backend whose targets are not enumerable from source. No allowlist; `sync_seed` is an upsert, never a truncate, so a model removed from `registry.py` keeps its row forever, enabled and bindable. **Deleting such a class is a production outage, not a test failure** | `SELECT DISTINCT service_class, enabled FROM provider_models ORDER BY 1` — diff against the 13 literals in `registry.py` |
| **2** | **Is outbound dialling actually on?** | `platform_switches` absence = off, no row seeded, enforced at the carrier boundary with a 2 s TTL cache. **Every corpus statement about outbound being enabled is a guess** | `SELECT tenant_id,key,enabled,updated_at FROM platform_switches` |
| **3** | **What grader names are in `eval_tasks`?** | Graders are dispatched from a **DB column**, not only from fixtures. An unknown name returns `{"passed": False, "detail": "unknown_grader:…"}` — **a failing eval that looks like a real regression** (C14) | `SELECT DISTINCT grader FROM eval_tasks` — diff against the 20 keys |
| **4** | **Has `policy_rule_sets` ever been populated?** | If not, every regulated decision runs on hardcoded fallbacks and **WhatsApp, SMS and email have no calling-hour bound at all** (MF-036). It also decides whether the calling-window consolidation is a no-op or regulated | `SELECT tenant_id, kind, effective_from, effective_to FROM policy_rule_sets` |
| **5** | **How many consent rows are already corrupted?** | Sizes MF-005 and identifies the re-consent population, where the original consent is unrecoverable | `SELECT id, allowed_days FROM consent_records WHERE allowed_days ~ '[–—]' OR allowed_days IN ('Mon-Mon','Tue-Tue','Wed-Wed','Thu-Thu','Fri-Fri','Sat-Sat','Sun-Sun')` |
| **6** | **Are account ids all-numeric?** | Decides whether the account-tail consolidation (MF-042) is a no-op or a user-visible change on desk feeds and spoken verification | `SELECT count(*) FROM accounts WHERE right(id,4) IS DISTINCT FROM right(regexp_replace(id,'[^0-9]','','g'),4) OR length(regexp_replace(id,'[^0-9]','','g')) < 4` |
| **7** | **Has `provider_voice_sync.py` ever run?** | Decides whether it is wired or deleted (MF-050), and whether the Voice tab's non-Azure chips are empty by construction | `SELECT provider, count(*) FROM tts_voice_catalog GROUP BY 1` — Azure-only ⇒ never |
| **8** | **Does deleting the dead shadcn kit change the built CSS?** | The roadmap grades Batch 1 *"the shipped bundle does not change"* and nominates `tsc`/`vitest`/`lint` as the gates. **None of those can observe Tailwind output**, and Tailwind v4 scans source files; `ui/chart.tsx:51` alone carries a long `[&_.recharts-*]` arbitrary-variant string. Benign in expectation; the guarantee as written is unverified | Byte-diff the built CSS before and after |
| **9** | **Are the 26 backend routes with no frontend caller actually dead?** | **A traffic question, not an import question.** Report 38's own method could not resolve them and says so | A per-route counter for one week |
| **10** | **Which mouths have an empty `agent_card`?** | The population MF-001's deny-all flip protects is the population it breaks. This must be answered **before** the sentinel is inverted | `SELECT bot_id, id FROM prompt_versions WHERE agent_card IS NULL OR agent_card = '{}'::jsonb` |

**Two conclusions that runtime evidence would likely contradict**, both environment-conditional and both worth stating so they are not mistaken for findings:

- **`GET /providers/models` probably reports every pipecat-backed model `RUNTIME_UNAVAILABLE` in the `api` container.** `requirements.txt` has no pipecat line; `api` builds from target `base`; `runtime_status` imports by string and caches the failure for process life. **The Agent Studio capability matrix answers *which container served the request*, not what the deployment supports.**
- **`APP_ENV=staging` is a hole nothing in the corpus tests.** Verified statically (MF-007): signing and vault keys **raise**, while auth, `/docs`, the Twilio signature check and the voice WS are all **fail-open** — and billing inverts it again, reading `staging`, and silence, as **production**.
