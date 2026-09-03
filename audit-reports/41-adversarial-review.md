# 41 — Independent adversarial review

**Role:** External principal architect. Assumes the prior 40 reports contain false positives, over-engineering, and wrong conclusions until each is re-derived from source.
**Scope:** The `audit-reports/` corpus, tested against `backend/` and `Habibi/src`. Guest tree `PRAXIST-main/` out of scope.
**Date:** 2026-09-03
**Mode:** Read-only. No application file was modified, nothing was committed, no call was placed, no test or migration was run. `backend/.env` was inspected for key *presence* only — no value, no length.
**Method:** five adversarial lenses — false-positive, architecture, runtime, deletion-risk, business-impact — each briefed to ask, of every finding, **"what evidence would prove the opposite?"** Every claim reproduced below was re-opened at `file:line` by the lens that raised it, and the load-bearing ones were re-verified a second time by the author before publication. Disagreements between lenses were arbitrated against source, not averaged.

---

## Verdict

**The corpus is substantially more reliable than an adversarial brief assumes, and its two most actionable documents contain four errors that would each cause an incident if executed as written.**

Reports `08`, `25`, `35`, `06` and `09` were re-tested at source and held. The escape-hatch audit in `40-refactoring-roadmap.md` §1-0 — the analysis that licenses every deletion in the programme — was re-derived independently and is **correct and complete**, with one undercount. Its frontend deletion set was re-derived rather than checked, and is **exact to the line**. That is an unusual result and it should raise, not lower, confidence in the series.

The failures are concentrated and specific:

1. **`07-dead-code.md` declares a live regulated gate dead.** `CAMPAIGN_RUNTIME_ENABLED` is read by `cadence.py`, `campaigns.py` and `call_closer.py`. The roadmap silently corrects the count and never says report 07 was wrong — so a cleanup PR citing *the document titled "dead code"* deletes the switch that stops the platform auto-redialling borrowers on a timer.
2. **`40-refactoring-roadmap.md` states that no route-ordering hazard exists.** Five pairs exist, and `main.py:2216-2219` is a handler docstring warning about one of them. The roadmap's proposed validation compares a set where the defect is an order.
3. **The roadmap's Wave 5.1 prerequisite silently disarms the test suite's rollback fixture**, and nominates that same suite as its validation.
4. **A literal deletion range in a batch graded "blast radius: none" breaks the stylesheet.** `styles.css:1638-1674` overshoots the dead block by four lines and truncates a live `@keyframes`.

And one finding that is not a corpus correction at all, but a live defect no report raised: **the consent drawer overwrites borrower consent with serializer defaults on every save.**

Against that, the single most important thing this review found is a **positive** result the corpus never states plainly: **there is no ungated path to a borrower's phone.** All seven `outbound.place` sites are gated by `contact_policy.admit`, through one carrier chokepoint. Read without that, `06` DUP-02 and roadmap 3-3 imply a dial could escape. It cannot.

The corpus's own risk ranking is inverted at the top. Its Critical findings are dominated by file length, coupling graphs, dead UI kit and token drift — real engineering costs, but **no borrower is contacted, charged, or misquoted by any of them.** The changes that would actually reduce regulatory exposure total **under 50 lines** and appear in §5.

---

## 1. Findings I agree with

Re-derived from source this session. One line each; the corpus earned these.

| Finding | Where | Status |
|---|---|---|
| Escape-hatch inventory: 6 dynamic-import sites, all but one enumerable | roadmap §1-0 | **Confirmed by independent re-derivation.** `getattr(obj, var)` is exactly 9 in non-test code; `globals()[…]` exactly once; no module-level dispatch by string |
| `import.meta.glob` = 0; all 43 route files present in `routeTree.gen.ts` | roadmap §1-0 | **Confirmed exactly.** Zero orphans in either direction |
| Pipecat runs a turn's tool handlers concurrently by default | `15-concurrency.md` | **Confirmed.** `run_in_parallel` appears nowhere in tracked `backend/` source, so the `True` default stands. 15's "single most consequential fact" survives |
| The flow-control literal "drift" is not drift | roadmap, retracting `06` DUP-01 / `38` C3 | **Confirmed.** `flow_graph.py:773-784` is a `dict[str,str]` of editor descriptions; `voice/tools.py:80-94` is a `frozenset[str]` of 11 names. Different artifacts. `voice/tools.py:79`'s "the two still differ" is stale |
| The publish gate is channel-filtered; both runtimes are channel-blind | `intersect.py:65-68` vs `skills/runtime.py:191-199` | **Confirmed.** Two lines, real, correctly placed first in Wave 3 |
| `ui/card.tsx` and `ui/tooltip.tsx` are dead; report 07 missed both | roadmap §1-3 | **Confirmed twice, independently.** Zero references anywhere in `Habibi/` outside `node_modules` — checked against barrels (none exists), relative `./card` forms, `components.json` (`"registries": {}`), tsconfig paths, eslint, vite/vitest config, `Habibi/scripts/`, and root files. The only other `Tooltip` is `RechartsPrimitive.Tooltip` at `ui/chart.tsx:93` — a different symbol |
| 29 files / **2,843 lines** / 22 npm deps | roadmap §1-1 | **Confirmed exact**, by independent re-derivation rather than by checking the list. Every Radix package has exactly one importer (its wrapper). `liveline` is a genuine name collision — `charts/index.ts:4-5` exports hand-rolled `LivelineTrend`/`LivelineSpark` |
| `records/index.ts`, `AlertLane`, `CallTile`, `use-mobile`, `StatusPill`, `ScenarioList` are dead | roadmap §1-3 | **Confirmed.** Nothing depends on the `records` barrel existing — tsconfig maps only `@/*`, no `no-restricted-imports` rule, no codegen. No frontend feature-flag system gates a component, so there is no hatch reaching `AlertLane`/`CallTile` |
| DUP-08 — the two payment webhook HMACs are byte-identical after the secret lookup | `06`, roadmap §2A-2 | **Confirmed character by character**, line ranges exact. Only the first line differs, and the two getters resolve different env vars — which "keep the two secret getters" handles correctly. **Safe to ship as described** |
| DUP-13 — Twilio `Client` constructed per call in two places | `06` | **Confirmed.** No third site; every other `Client(` hit is `httpx.Client` or `TestClient`. `scripts/set_twilio_voice_webhook.py:37` has no timeout, as stated |
| `voice/node_contracts.py`, `voice/spike.py`, `grant.py` are orphaned-but-intentional | roadmap §1-3(c) | **Confirmed.** `grant.py` importers are exactly three test files, zero production — still true after the two recent `grant.py` commits on this branch. Line counts match the report exactly (247 / 633 / 51 / 329 / 364 / 592), so it was written against this tree |
| `test_alembic_upgrade_downgrade_roundtrip` never runs in CI | `07`, `22` | **Confirmed, and it is gated twice** — on `RUN_ALEMBIC_ROUNDTRIP` *and* on `TEST_DATABASE_URL`, which CI never sets. Flipping the flag to `1` would still skip |
| `backend/README.md:31` cannot work on a fresh volume | `12`, `39` | **Confirmed.** Baseline `20260721_0001` is `def upgrade(): pass`; the `db` service mounts no init dir; 0002+ then `add_column` against absent tables |
| `test_contact_policy.py:287` is permanently red on a date literal | `39` | **Confirmed at source.** `promised_date="2026-09-01"`, in the past on every run since 2026-09-02 |
| The refusals: no rewrite, no DAO/service/DTO layer, no `agent_core` split, `rls.py` is not dead | roadmap §6.1-§6.10 | **All correctly reasoned with source evidence.** Nothing in the corpus proposes removing an adapter, factory, barrel or facade — on that axis the series is already disciplined |
| `08-bug-hunter.md` BUG-1/2/3 and `25-resilience.md` R1-R6 | those reports | **All real at source, all correctly ranked.** Tested against the grain of this brief and they held |

### The strongest result in this review is a positive one, and the corpus never states it plainly

**There is no ungated path to a borrower's phone.** Every `outbound.place` call site is preceded by a `contact_policy.admit` in the same function — verified 7 for 7 by two independent scans:

| `place` | its `admit` | | `place` | its `admit` |
|---|---|---|---|---|
| `cadence.py:492` | `:445` | | `agent_core/treatment/enact.py:384` | `enact.py:102` |
| `campaigns.py:610` | `:557` | | `payment_events.py:882` | `:821` |
| `main.py:3811` | `:3777` | | `scripts/dial_test.py:215` *(script)* | `:176` |
| `main.py:4152` | `:4097` | | | |

And `voice/twilio_ops.start_outbound_call` is the sole function reaching the carrier — by its own design note at `:307-311` — with `outbound.place` its only production caller. **One chokepoint, universally gated.**

This matters because `06` DUP-02 and roadmap 3-3 frame the same fact as *"the sequence is written seven times,"* which reads as though a dial might escape the gate. **It cannot.** The real defects are in the *ordering* and in the *evidence left behind* — §5.1 item 4 — not in coverage. A risk committee reading the corpus without this correction would over-estimate the exposure, and that is its own kind of audit failure.

Two more the corpus deserves credit for, because they are the hardest kind of judgement to get right:

- **`platform_switches.py:60-66`** — renaming a switch key orphans a row an operator already enabled, so a rename is a data migration. The roadmap uses this to refuse a vocabulary-alignment wave. Correct.
- **Wave 3's "What must NOT be consolidated"**, particularly `contact_window` 09:00–20:00 preference versus the RBI 08:00–19:00 statute. Two numbers that look like drift and must never be merged.

---

## 2. Findings I challenge

### 2.1 `CAMPAIGN_RUNTIME_ENABLED` is live — `07-dead-code.md` is wrong, and the wrong document is the actionable one

Report 07 class **B** asserts: *"No hits in `main.py`, `worker.py`, `bot_worker.py`, `voice/`, `outbound.py`, `mission.py`."* True — and it never searched `cadence.py` or `campaigns.py`.

```
cadence.py:67-69      def enabled(): return campaign_runtime_enabled()
campaigns.py:61-63    def enabled(): return campaign_runtime_enabled()
call_closer.py:749    if not cadence.enabled(): return []
main.py:4994          409 campaign_runtime_disabled
sql/10_admin.sql:332  named as an outbound-engine gate
```

Delete it and hardcode `True`, and `call_closer.py:749` stops short-circuiting: every call outcome opens a retry ladder and the platform begins **auto-redialling borrowers on a timer**. `.env.example:592-594` describes "off" as *"nothing dials on a timer."* Detection is **L2 at best**, and **L4** if volume stays under the frequency cap — the only signal is a contact-frequency complaint months later.

**Two lenses reached this independently**, and the second explains *why* the search missed it: the flag is read through a **function-local import inside a differently-named wrapper**.

```python
# cadence.py:66-69  (character-identical twin at campaigns.py:60-63)
def enabled() -> bool:
    from agent_core.platform_flags import campaign_runtime_enabled
    return campaign_runtime_enabled()
```

Gated at `cadence.py:349` and `campaigns.py:461`. A grep for the flag name inside a fixed file list cannot see either. `31-runtime-wiring.md:157` lists the readers correctly — **the corpus already contained the disproof and nobody reconciled the two reports.**

The roadmap quietly counts one dead flag (`AGENT_CARDS_ENABLED` — independently confirmed genuinely dead) and never states that report 07 was wrong. **The correction must be written into report 07 itself**, because that is the document a cleanup PR will cite.

> **This is the archetype the brief was commissioned to find: a conclusion drawn from an absence, produced by a search that could not have found the evidence.** Every "no importer found" verdict in the corpus should be re-read with the search scope stated. Where the scope is a hand-listed set of files, the verdict is a hypothesis.

### 2.2 The same error class, three more times — and the taxonomy

| Report | Absence claimed | Why the method was blind |
|---|---|---|
| `07:119` | `CAMPAIGN_RUNTIME_ENABLED` unread | A **fixed file list** cannot find a reference in a file not on it |
| `06` DUP-03 | `BLOCKING_CONSENT` "restated three times" | Searching the **symbol name** cannot find a renamed private copy. There are **four** — `capture.py:331 _CONSENT_BLOCKING_STATUSES` is the same literal under a different name. Roadmap §2A-1 caught the fourth; report 06 still asserts three |
| roadmap §2A-1 | "3 definitions, 4 use sites" | Actual: **4 definitions, 9 use sites** — `contact_policy.py:491`, `promise_fulfillment.py:158`, `payment_events.py:528`, `written_followup.py:177`, and **five in `capture.py` alone**. A PR sized for four will be more than twice that. (The member-identity claim itself is confirmed byte-identical, and the consolidation is cycle-safe: `contact_policy` is a DAG leaf) |
| roadmap §1-4 Batch 1 | "the shipped bundle does not change" | True for JS. **False for CSS** — Tailwind v4 scans source files, and `ui/chart.tsx:51` alone carries a long `[&_.recharts-*]` arbitrary-variant string. The proposed gates (`tsc --noEmit`, `vitest`, `lint`) **cannot observe Tailwind output.** Benign in expectation; the guarantee as written is wrong. Settle it with a byte-diff of the built CSS |

**The general pattern: proving a negative with a name-scoped or file-scoped search, then reporting the scope's boundary as the codebase's boundary.**

### 2.3 The `styles.css` deletion range overshoots into a live keyframe · a build break

Roadmap §1-3(a) and §1-4 Batch 2 instruct: *"Delete `BigBoundMark.tsx` and `styles.css:1638-1674` together."* The `.bb-mark` block ends at **1670**. Verified at source:

```
1670   }              ← closes @keyframes bb-trend-draw — end of the dead block
1671   (blank)
1672   @keyframes pulse-ring {     ← a different, LIVE animation
1673     0% { box-shadow: 0 0 0 0 var(--background-success-bold); }
```

`pulse-ring` is consumed at `styles.css:1835`. Executing the range literally leaves a truncated `@keyframes` and a **syntactically broken stylesheet**. Correct range: **1638-1670**. Everything else in that finding is right — `BigBoundMark` has exactly one non-self hit, the explanatory comment at `EqualizerMark.tsx:23`.

This is the one error in the corpus that breaks the build rather than production, which makes it the cheapest to catch and the easiest to ship by accident: the instruction is a literal line range in a batch graded *"blast radius: none, behavioral risk: none."*

### 2.4 "Zero ordering-sensitive route pairs" is false — and the codebase says so

Roadmap §5.2: *"Every same-method, same-arity path pair was checked … **none**. Route registration order cannot affect matching."* Five pairs, each working today only because the static route is declared first:

| Static (declared first) | Parameterised |
|---|---|
| `main.py:1322` `GET /handoff/queue`, `:1327` `/handoff/active` | `:1335` `GET /handoff/{interaction_id}` |
| `main.py:1951` `GET /prompt-versions/published` | `:1960` `GET /prompt-versions/{version_id}` |
| `main.py:2213` `GET /agent-studio/skills/scripts` | `:2226` `GET /agent-studio/skills/{skill_id}` |
| `main.py:2915` `GET /tts-voices/catalog/sync-runs` | `:2921` `GET /tts-voices/catalog/{short_name}` |

`main.py:2216-2219`, in the handler itself:

> *"Declared above /skills/{skill_id} — FastAPI matches in definition order, and the parameterised route would otherwise swallow 'scripts'."*

Three compounding factors make this the corpus's most dangerous single sentence. `/agent-studio` is the roadmap's **first** router-extraction target *and* its first `response_model` target, so both changes land on the same 26 routes. Moving them invites a grouping pass — reads before writes, collections before items — which is the most natural thing to do and which reverses the pair. And the nominated validation, a route-table snapshot `[(r.methods, r.path) …]`, **compares a set where the defect is an order**, so it passes. `assert_registry_covers` passes too. The regression surfaces as the script picker returning `skill_not_found`, which nothing in CI exercises.

**Fix: the validation must be an ordered list, and Wave 4-2 must not ship in the same release as Wave 5's `/agent-studio` extraction.**

### 2.5 The `db.py` carve preserves the coupling it is sold to remove

Wave 5.1 rides seam **S4** and reads the `followups_db` carve as proof the manoeuvre is low-risk. But the working part of S4 is not the re-export block at `db.py:18005-18024`. It is:

```python
# followups_db.py:23-26
def _db():
    import db as d
    return d
```

Every one of the 19 transaction sites then does `with d.engine.begin() as conn:`. The carved module still imports `db`, at call time, on every call. The pair is a 2-cycle. **Repeating it 13 more times adds 13 more 2-cycles rather than removing a node.**

The roadmap's own peel simulation is the evidence: 112 → 111 → 110 → 86 → 83 → 82, and only *"remove all `db →` edges"* reaches 41. §5.1.3 calls this *"SCC size is a lagging indicator."* It is not lag, it is structural — the cycle survives until the shim is deleted, and deleting the shim means editing all 211 `db.*` call sites, which is the work the shim exists to avoid. Wave 5.1 never schedules that step and names no terminal state.

What the carve *does* deliver — file size, ownership, review surface, navigability — is real, and §5.1.3 says so honestly. **The framing is what fails.** Ordering constraint C1 declares the carve must precede every backend structural refactor, then schedules it last, after Waves 0–4. Both cannot be load-bearing. Nothing in Waves 0–4 is structural, so C1 constrains nothing in this document; it is a spine holding nothing up.

Credit where due: the prerequisite `db_core.py` module is correct and mandatory. **213 reach-throughs into `db.py`'s private helpers across 39 files** confirm `38` B2 independently, and the `_jsonb` / `_as_dict` hoist is new and correct.

### 2.6 Wave 2A-5 generalises a one-line finding to eleven sites, three of which are deliberate

`37-integration-boundaries.md` I2 asks for **one line**: `main.py` should import `env_utils.env_name()`, because `_IS_PROD` gates the Twilio signature check, the API-key requirement and `/docs`. The roadmap turns this into eleven adoption sites. Three of them re-derive on purpose:

- **`seed_postgres.py:29-40`** reads the `.env` **file**, and its docstring says why: *"a deployment that only sets APP_ENV in .env would otherwise be seen as `dev` while pointing at the production database."* `env_utils.env_name()` reads only the process environment. Adopting it re-opens that hole on a script that *"writes synthetic customers, calls and consent records over whatever is in the target database."*
- **`payments.py:29-40`** calls `load_env()` first — same class, smaller blast.
- **`storage.py:41-46`** gates the MinIO dev fallback on the **endpoint**, not `APP_ENV`, and documents the staging incident that caused it.

The roadmap's own "must NOT be consolidated" list catches only one of the three (`usage_meter`).

Worse, **2A-5 does not fix what D1 describes.** D1's divergence is between two *predicates* — `env_utils`'s allow-list reading versus `main.py:205`'s deny-list — but the allow-list lives in `env_allows_dev_key()`, a different function answering a different question. `env_name()` is a string normalizer, and eight of the eleven sites compute a boolean that would keep `in {"prod","production"}` verbatim after adoption. **2A-5 is close to a no-op on the divergence, not the regulated change it is graded as.** Getting D1's actual outcome requires adding `is_prod()` to `env_utils` — new construction, which the roadmap's Verdict says appears in exactly three places, and this is not one.

One unmeasured direction: `env_name()` also consults `ENV`, which **none** of the eleven sites do. On a box with `ENV=production` and `APP_ENV` unset, adoption flips eight fail-closed sites at once. That is the right direction and it is exactly `37` I2 — but the blast-radius column reads "11 modules, 1 line each."

### 2.7 The dependency-direction violation is real, trivial, and was mis-scored — including by me

`39-enterprise-readiness.md` scored Architecture **3** partly on *"the persistence layer depends on the API contract layer,"* citing `db.py:26`. Three problems, and the first two are mine:

1. **The citation is wrong** — it is `db.py:24`. Not re-read at source.
2. **The corpus contradicts itself.** `38-architecture-boundaries.md:152` lists `db.py:18-24` as *"the only clean part"* and `:550` files the same edge under **what is already right**. One report's asset is another's score deduction, and nobody reconciled them.
3. `db.py:1` is *"Postgres accessors plus API response serializers."* The module is declared as persistence **plus** serialization, so importing `*Response` types is its stated job, not a leak.

But the mislabelled-layer defence is only half right: the eight names `db.py` takes are all `*Response` — pure transport — and it **constructs** them at nine sites. So the violation exists; the remedy is nine function-local imports. **Scoring an architecture dimension down on a nine-call-site edge, while a sibling report calls that edge clean, is a corpus defect rather than a code defect.**

Related, and cheaper than the roadmap's plan: the cycle `db → schemas → flow_graph → agent_core.tools → …kb → db` has four breakable edges, and C1a picks the one that is a *deliberate, documented domain-model share* (`schemas.py:6-10`). The `kb` end already ships an injection seam at `kb.py:117-123`; threading `sink` at two call sites uses a seam that exists rather than deleting a re-export whose rationale is written above it.

### 2.8 Report 40 undercounts the graders by four

§1-0 says *"all 16 `grade_*` functions."* There are **20**, and the `GRADERS` dict at `:406-430` has 20 entries matching one-for-one. The four missed are in the outbound-conduct block — `no_debt_to_a_third_party`, `stops_after_opt_out`, `no_identifier_into_an_ivr`, `no_offer_after_hardship` and siblings. **A deletion pass working from "16 named" would be operating on a stale list of the highest-risk graders in the file.**

### 2.9 Accuracy notes — wrong as stated, sound as engineering

- **`rls.py` is not orphaned.** The roadmap calls it *"inert, not dead"* with zero importers. It has a real operator CLI importer — `backend/scripts/rls.py:34` `import rls`, driving `status` / `plan` / `apply` / `provision-role` / `enable` / `disable`. The ADOPT verdict is right; "orphaned" mischaracterises a wired-up admin tool. (`rls.py:327 weak_policies` **is** genuinely uncalled, including by that CLI — the carve-out in §4.6 stands.)
- **`record_offer_suppressed` is dead, and the finding is bigger than "clutter."** Its event kind is *registered* — `capture.py:1171` inside `COMMERCIAL_KINDS`, asserted by `tests/test_lead_eligibility.py:161`. So **no code path has ever emitted an `offer_suppressed` activity event**, while `agent_core/live_qa/scorecard.py:218-230` derives its own `offer_suppressed` from `offer_decisions.suppression_reason` — a second, unrelated record of the same fact, and the one that actually feeds the `ups-eligibility` rule at `:349`. **That duplication is in no report.** Deleting the function leaves an orphaned kind in a locked vocabulary.
- Roadmap §5.1.4: *"no importer anywhere uses `from db import X`"* is false by exactly one file (`tests/test_lead_eligibility.py:15`), which binds two head-section constants the carve keeps in place. The engineering conclusion survives; the absolute phrasing does not.
- §5.2's `http_errors.py` takes `fastapi` from 3 modules to ~10 and spreads `HTTPException` across 7 files — spending the "the framework does not leak" property that §6.1 uses as its #2 anti-rewrite argument, while grading the item "cosmetic."
- Wave 2A-4 names the wrong axis: **none** of the three `_env_int` copies raises. The one real difference is that `reco/config.py:42-49` **logs a warning** where the canonical swallows silently — and per the roadmap's own P2, WARNING is the level that survives the missing root handler. An observability deletion filed as cosmetic.

### 2.10 A method I tried and discarded

I attempted to rank the corpus's weakest reports by counting hedging language — "false positive", "unverified", "do not delete". Seven scored zero, including `15-concurrency`, `25-resilience` and `31-runtime-wiring`: exactly the domains where static analysis is least reliable. That looked like a finding.

It was not. Both 15 and 25 hedge continuously in prose rather than in the phrases I grepped; 15's method note says outright that claims were *"corrected or rejected"* in a verification pass. **A keyword-count proxy for analytical rigor produces a false signal, and I discarded it rather than ship it** — it is the same error class as §2.1, committed by the reviewer instead of the reviewed.

---

## 3. Findings requiring runtime verification

**No runtime evidence was obtainable this session.** The Docker daemon is down; nothing is listening on 8000 or 3000. Every item below is **unverified** and none was guessed at.

| # | The question | The exact check |
|---|---|---|
| **R1** | **The only dynamic-dispatch site whose targets are not enumerable from source.** `factory._import_class` (`factory.py:110-118`) has **no allowlist** — it imports whatever `provider_models.service_class` holds. `persist.sync_seed` is an **upsert, never a truncate** (documented at `persist.py:4-7`, because `provider_model_id` is `ON DELETE RESTRICT`). A model removed from `registry.py` keeps its row forever, stays enabled, stays bindable. **Deleting such a class is a production outage.** | `SELECT DISTINCT service_class, enabled FROM provider_models ORDER BY 1` — diff against the 13 literals in `registry.py` |
| **R2** | **Whether outbound dialing is on is a database row.** `platform_switches` absence = off, no row seeded, enforced at the carrier boundary (`twilio_ops.py:311-314`), 2.0s TTL cache. Every corpus statement about outbound being enabled is a guess | `SELECT tenant_id,key,enabled,updated_at FROM platform_switches` |
| **R3** | Graders are dispatched from a **DB column** (`eval/run.py:52` selects `grader` from `eval_tasks`), not only from fixtures. An unknown name returns `{"passed": False, "detail": "unknown_grader:…"}` — **a failing eval that looks like a real regression** | `SELECT DISTINCT grader FROM eval_tasks` — diff against the 20 keys |
| **R4** | Is the account-tail divergence a no-op? This is the one item that needs a production read before shipping | `SELECT count(*) FROM accounts WHERE right(id,4) IS DISTINCT FROM right(regexp_replace(id,'[^0-9]','','g'),4) OR length(regexp_replace(id,'[^0-9]','','g')) < 4;` Zero ⇒ ship in the 2A batch |
| **R5** | **How many consent rows are already corrupted** (§4.1). The second set is the re-consent population | `SELECT id, allowed_days FROM consent_records WHERE allowed_days ~ '[–—]' OR allowed_days IN ('Mon-Mon','Tue-Tue','Wed-Wed','Thu-Thu','Fri-Fri','Sat-Sat','Sun-Sun');` |
| **R6** | Has `provider_voice_sync.py` ever run? | `SELECT provider, count(*) FROM tts_voice_catalog GROUP BY 1` — Azure-only ⇒ never |
| **R7** | The 26 backend routes with no frontend caller. **A traffic question, not an import question** | A per-route counter for one week |
| **R8** | `voice_calls_slot_reaped` cannot fire — `admission.py:120` counts a metric `observability.py` does not define, and the `AttributeError` is swallowed to `logger.debug` at `:167`. The voice process has no `/metrics` route at all | `curl -s localhost:8000/metrics \| grep voice_calls` |

Two conclusions that runtime evidence would likely **contradict**, both environment-conditional:

- **`GET /providers/models` reports every pipecat-backed model `RUNTIME_UNAVAILABLE` in the `api` container.** `requirements.txt` has no pipecat line; `api` builds from target `base`; `runtime_status` imports by string and caches the failure for process life. The Agent Studio capability matrix answers *which container served the request*, not what the deployment supports.
- **`APP_ENV=staging` is a hole nothing in the corpus tests.** `main.py:205` treats anything not `prod|production` as dev; `env_utils.NON_PROD_ENVS` excludes `staging` deliberately. So on staging: signing keys **raise**, while auth, `/docs`, Twilio signature validation and the voice WS are all **fail-open**. Billing inverts it again — `usage_meter.py:292` reads `staging`, and silence, as **production**.

---

## 4. Dangerous changes that must not be automated blindly

**The governing rule.** A deletion is automatable when the thing deleted is a **capability**. It is not automatable when the thing deleted is a **statement about the world** — a diagnostic that would have reported something, a seam that would have made a test writable, a record that proves what happened, or a docstring that is the only place a fact is written down. `git revert` restores capabilities. It does not restore statements, because the restored text lands in a repository where nobody knows to go read it.

Detection latency, not blast radius, is the ranking axis. **L0** = CI red in seconds · **L1** = pytest red · **L2** = hours-to-days, a 500 or a ticket · **L3** = weeks, when someone needs the seam · **L4** = never.

### 4.1 The consent write-back — a live defect, not a corpus correction · L4 · **CRITICAL**

Not raised by any report in the series. Verified end to end this session.

```
db.py:2039-2040    _parse_allowed_days(NULL)  → [1,2,3,4,5]
db.py:2067-2068    _parse_allowed_hours(NULL) → (10, 19)
db.py:2306-2310    serialized into allowedWindow
ConsentDrawer.tsx:65,74 → api/consent.ts:38-49   sent back on ANY save
db.py:6676-6693    UPDATE consent_records SET allowed_days=…, allowed_hours=…
                   UPDATE customers   SET preferred_window=…
```

`api/consent.ts` always includes `allowedWindow` in the PATCH — including a save that only toggled a channel. Two irreversible outcomes:

- **`allowed_days = 'Mon–Sat'` (en-dash) → `'Mon-Mon'`.** The en-dash defeats the range branch at `db.py:2041`; the token split yields `["mon–sat"]`, key `"mon"`, days `[1]`; `_format_allowed_days([1])` returns `f"Mon-Mon"`. Six days of consent overwritten with one — and afterwards **both parsers agree on Monday**, so the bug becomes undiagnosable.
- **`NULL` → `'Mon-Fri'` and `'10:00-19:00 IST'`.** A record that said *no window captured* now asserts a window the borrower never stated, and `customers.preferred_window` is stamped with it too.

`db.py:6746` records the change as one contentless row: `kind='consent_updated'`, `label='Consent preferences updated.'` — no before, no after, no field list. There is no history table for `consent_records.allowed_days/allowed_hours`; `optout_events` covers withdrawals only.

**This inverts roadmap Wave 2B-4.** The roadmap says fixing the parser *"silently widens those consent windows from one day to six — a DPDP-relevant change,"* and uses that to argue for delay. The stored string **says `Mon–Sat`**; the borrower consented to six days. Reading it as Monday-only is the platform failing to use consent it holds — commercially expensive, regulatorily inert, and `contact_policy.py:227-231` says exactly that in its own comment. **The genuine hazard runs the other way**, and it is the write-back.

Correct sequence: **(1) stop the write-back** — omit `allowedWindow` unless the operator changed it, or preserve the stored string when the parsed value round-trips unchanged. **(2) inventory** (R5). **(3) then** consolidate the parser. **(4) re-confirm only the already-corrupted rows**, where the original consent is unrecoverable.

### 4.2 Two production webhooks 401 before their own HMAC checks · L2 in prod, invisible in dev and CI

`ApiKeyMiddleware.dispatch` (`main.py:272-292`) exempts a request only on a prefix match against `_AUTH_EXEMPT_PREFIXES` (`main.py:233-257`). Two routes declared public in `authz.py:229,233` are absent from it:

| Route | Declared public | Exempt? |
|---|---|---|
| `POST /twilio/sms/status` (`main.py:3669`) | `authz.py:229` | **No** |
| `POST /webhooks/collections/payment-events` (`main.py:857`) | `authz.py:233` | **No** — `/webhooks/payments` does not prefix-match it |

`auth_required = bool(single or key_map)`; Twilio and the payment provider send no `x-api-key`. So the handlers' own HMAC checks at `main.py:3686` and `:863` **never execute**. `authz.py:226-228` carries a comment asserting the opposite — that the in-handler signature check *is* the authentication. The middleware runs first.

The environment split is why it survived: dev has no `API_KEY` so it passes; CI sets one but no test calls either path (zero hits in `backend/tests/`); production **requires** `API_KEY` at `main.py:432-433`, so both return 401 permanently. `test_production_hardening.py:21-45` is exactly the right test applied to an incomplete list — it checks the four *voice* callbacks.

Consequence: SMS delivery receipts lost, and the collections payment-events ingest dead — which is the path `enact._hand_to_lms` says mandate settlement returns through, so the treatment follow-through loop cannot close.

### 4.3 The Wave 5.1 prerequisite silently disarms the rollback fixture · L4 · **blinds its own validation**

`tests/conftest.py:61`:

```python
monkeypatch.setattr(db, "engine", _EngineProxy(db.engine))
```

The fixture works because every production path resolves `engine` as an **attribute on the `db` module object at call time** — which is also why `followups_db` reaches back through `_db()` instead of importing `engine`. The prerequisite commit moves `engine` into `db_core.py` and grades it *"blast radius: zero call sites (attribute shim); validation: full pytest."*

True for production, false for the fixture. Any carved module binding `from db_core import engine` bypasses `_EngineProxy`; the savepoint wrapper stops wrapping; `outer.rollback()` at `:64` rolls back nothing those modules wrote. **The suite goes green while leaving committed rows behind** — and commit `fd855ca` ("Make the suite pass on a database nobody has touched by hand") shows this repo has already paid for that bug once.

**Required and absent:** every carved module must reach back through `_db().engine`, written into the prereq commit's acceptance criteria — not discovered on peel #3. The natural home for this decision is Wave 0-B's W0.4 ("a committing fixture"), not the highest-risk wave.

### 4.4 Deleting a `bots` row silently rewrites nine tables · L4

Wave 1 says *"no data changes, rollback is trivial."* True of file deletions, false of any DB cleanup that follows. Thirteen FKs to `bots(id)`, in three groups with three different failure modes:

- **Blocks the delete (loud):** `prompt_versions.bot_id` has **no `ON DELETE` clause** (`sql/09_bot_config.sql:111`).
- **Cascades (loud enough):** `bot_deployments`, `deployment_experiments`, `agent_provider_bindings`, `skill_attachments`.
- **`ON DELETE SET NULL` — the hazard. Thirteen tables.** Four are saved by a paired `CHECK` that aborts the delete (`interactions`, `interaction_participants`, `violations`, `promises`). **The other nine are silently nulled** — `qa_scorecards`, `coaching_actions`, `activity_events`, `interaction_handoffs`, `interaction_disclosures`, `supervisor_actions`, `eval_reports`, `campaign_runs`, and `call_attempts`, the last described at `sql/21_outbound.sql:37` as *"unredactable borrower PII whose retention nobody has argued about."*

`interaction_handoffs.from_kind='bot' AND from_bot_id IS NULL` is a legal row. **The CHECK constraints, not the foreign keys, are what make this survivable, and they cover four of thirteen.** `scripts/prune_probe_cards.py` reaches the right outcome for the wrong reason — its comment says the FK would block the delete anyway, which is false for the SET NULL tables; the `if counts["interactions"]: REFUSED` guard is doing all the work and it checks one table of thirteen. **Do not generalise that script without extending the guard.**

### 4.5 The audit chain: never delete an orphan row · L4 · a compliance question, not a tidiness one

`change_log.py:162` is the **only** `INSERT INTO audit_log` in the backend; `:57` sets `_ENTITY_TYPE = "bot"`; `sql/12_crosscutting.sql:20-30` gives `entity_id` **no foreign key**.

> Deleting a `bots` row leaves orphan `audit_log` entries naming a bot that no longer exists. **That is correct and must be left alone.** Deleting those orphans to tidy up breaks the hash chain from that entry forward and `verify_chain` reports broken permanently. There is no repair: the chain *is* the evidence, and a rebuilt chain is evidence of nothing.

`scripts/prune_probe_cards.py:24-30` is the only place in the tree that states this rule. **That docstring is itself a protected artifact** — a PR removing "an obsolete script" removes the rule with it.

And the guarantee is weaker than its docstring claims. `change_log.py:22-25` asserts tamper-evidence, but the `audit_log` DDL has **no `seq`, `prev_hash` or `entry_hash` columns** — the chain lives inside the `payload` jsonb; `sql/13_triggers.sql` adds only `updated_at` triggers; no `REVOKE` appears anywhere in `sql/*.sql`; and `verify_chain` is scheduled by nothing.

### 4.6 The hidden category — unused diagnostics that a sweep will reap

**An absent capability produces a missing feature. An absent diagnostic produces a false negative.** Every item below is flagged by knip / vulture / ruff `F401` / any "delete unused exports" codemod, and every one must survive. This is the allowlist.

| Symbol | Refs | What its absence causes | Latency |
|---|---|---|---|
| **`rls.py:327 weak_policies`** | **1** (its own def) | Returns the policies linked to the tenant through nullable columns — *"a table where a row with no parent is visible to every tenant."* Delete it and RLS reports green while those tables stay cross-tenant visible. **Nothing fails; the question no longer has a function name** | **L4** |
| `rls.py:294 orphan_rows` | def + `enable()` | The only check that catches a *semantically wrong* derivation — the count check compares a policy against itself, and *"a wrong policy agrees with itself perfectly"* | **L4** |
| `rls.py:342 role_bypasses_rls` | own module + script | Its own docstring: *"The single most important check here. RLS is invisible when it is not working"* | **L4** |
| **`authz.py:879 assert_registry_covers`** | **1 test** | Proves the authz registry is *total* over the FastAPI route table. Delete it and a new endpoint with no classification ships. `check()` denies it at runtime — **but only when `enforcement_enabled()` is true, and `AUTHZ_ENFORCE` is not in `.env.example`** (verified absent) | **L4** |
| **`authz.py:652 invalidate_permission_cache`** | **3 tests, zero production** | **Not a test seam.** Its docstring says *"call after a role change"*; `_PERMS_TTL_S` defaults to 30s. With no production caller, **a revoked permission stays honoured for up to 30 seconds.** The function is the already-written fix, and it clears `_roles_cache` alongside `_perms_cache` for a documented reason | **L3 / L4** |
| `voice/node_contracts.py` | module + 1 test | Encodes that a node whose exits were all dropped by the grant filter **hangs the call on a borrower who did nothing wrong.** Already fixed once — commit `5578cfd` | **L4** |
| `outbound.py:178 DialRefused` | **1** | Encodes a real state — *attempt recorded, no dial* — that callers currently cannot distinguish from success. The roadmap calls it "evidence of an unfinished thought" and puts it in the deletion batch anyway. Cost of keeping: 2 lines | **L4** |
| `capture.py:1635 record_offer_suppressed` | **1** | *"a silent suppression is indistinguishable from an engine that found nothing, and the two need very different fixes"* — a diagnostic, filed as clutter | **L4** |

**Intent-bearing docstrings, which no linter protects.** Each is the sole record of its fact: `rls.py:19-23` (the app connects as a BYPASSRLS role, so enabling RLS as-is is *a no-op that looks like it worked* — and there is no test that would catch it, because everything would pass); `rls.py:9-16` (an unset GUC is a total zero-row outage that looks like an empty database, hence a libpq **startup parameter** rather than `SET`); `grant.py:71-87` (why `verify_identity` is in the floor — a regulated post-mortem, and commit `767f1b4` shows it has already been removed once); `grant.py:81-87` (why the three always-on lists cannot be unified: the API process must not import Pipecat); `platform_switches.py:60-66`; `contact_policy.py:219-247`; `cadence.py:59-64`.

Four Alembic migrations already reason in terms of `rls.plan()`. **The migration history has taken a dependency on `rls.py`'s vocabulary** — deleting it leaves four dangling docstrings.

### 4.7 Deletion ordering

| Order | If reversed |
|---|---|
| `ui/toggle-group.tsx` with or before `ui/toggle.tsx` (closed two-node cluster) | L0 |
| Each `ui/*` wrapper **with** its exclusive npm dep, one commit | `npm ci` keeps pulling Radix packages nothing imports |
| `react-hook-form` **with** `@hookform/resolvers`; `date-fns` **not before** `react-day-picker` | `npm ci` ERESOLVE — verified in `package-lock.json` |
| `BigBoundMark.tsx` **with** `styles.css:1638-1674` | The CSS becomes an unattributable orphan nobody dares remove. L3 |
| Migrate all six live formulas → delete them → **then** the characterization suite. **Never** `grant.py` | `test_tool_grant_characterization.py:1` says *"delete this file in #13, with the formulas it pins."* Delete it first and the repo has **zero pin** on Tool Grant behaviour while six formulas migrate one at a time. Nothing goes red — that is the problem |
| Do **not** merge `test_tool_grant.py` into the characterization suite | `test_tool_grant.py:10-13` states the split *is* the safety mechanism: ticket #9 deletes the voice literal, #13 deletes the suite, and *"had the pin stayed in the scaffolding file, running #13 first would have unpinned the pair silently"* — and the pair contains `verify_identity` |
| Flip cardless deny-all **after** `SELECT`ing mouths with an empty `agent_card` | L2 |
| Bot-row deletes: `skill_attachments` → `deployment_experiments` → `bot_deployments` → `eval_reports` → `prompt_versions` → `bots`. Never `audit_log` | §4.4, §4.5 |
| Remove a flag from `platform_flags.py` only with `.env.example` + tests, **and after a deploy-manifest sweep** | `platform_flags.py:1-4` states the flag list is a contract. A stale name in a running deployment becomes an unrecognised variable — silent. And the L1 failure is a parametrized test the codemod will be tempted to edit |

**Four config-loaded npm deps a sweep will take, none catchable by `tsc --noEmit`:** `vite-tsconfig-paths` and `nitro` (peers of `@lovable.dev/vite-tanstack-config`; nitro is `optional: true`, so **npm installs silently** and only `vite build` fails), `tw-animate-css` (`styles.css:3`, a CSS `@import` by package name — animations stop with no JS error, **L2/L3**), and `sharp` (`scripts/gen-icons.mjs:25`, `await import()` inside a friendly `try` — **L3**).

**Backend dependencies: none proven unused, and do not go looking.** `requirements*.txt` are annotated line-by-line. Do not strip `redis`/`websockets`/`tiktoken`/`fastembed` because the API process does not import them — other images do.

**Also prohibited:** `ruff --fix` on `F401`. `ruff.toml:1-6` warns explicitly, and `db.py:18013` is `list_routing_audit as list_routing_audit` — the PEP 484 re-export idiom.

---

## 5. Missing investigations

### 5.1 The five cheapest high-value fixes — none of which needs a wave

If a risk committee funded no programme and demanded the smallest set that most reduces regulatory exposure. Total: **under 50 lines.**

| # | Change | Size | Consequence of not doing it |
|---|---|---|---|
| **1** | `db.py:6678-6693` — stop `patch_consent` rewriting `allowed_days`/`allowed_hours`/`preferred_window` from a round-tripped payload | one conditional | §4.1. Irreversible, undetectable, and it fabricates a consent artefact. **The highest value-per-line change in the tree** |
| **2** | `agent_core/skills/runtime.py:184` — return `ToolState(allowed=frozenset(), offered=())` instead of `allowed=None` | **one line** | Closes ADR-0002's fail-open at **all four** consumers at once, because each keys off the same sentinel (`has_grant` is `self.allowed is not None`). Today an unauthored card can take a PTP, post a goodwill waiver and flag a dispute on a live borrower |
| **3** | `db.py:649` — thread `actor_kind`/`actor_bot_id` through `_activity`, as `capture.py:1236-1242` already does | ~6 lines | Every activity row written by an autonomous agent — including `promise_created` at `db.py:5169`, in the same transaction that stores `owner_kind='bot'` — is attributed to a named human. On a conduct complaint the platform's own record says a person did it |
| **4** | `payment_events.py:866` — reserve before admit, and call `outbound.suppress` on refusal | ~10 lines | A refused bounce dial leaves **no `call_attempts` row** — the ledger proving a call was *not* placed. The invariant holds at six of seven sites. A hole in the evidence of a *correct* refusal is the worst kind |
| **5** | `outbound.py:743-751` — classify the carrier exception; a post-POST timeout is **ambiguous**, not `dial_failed` | ~15 lines | `twilio_ops.py` issues a non-idempotent `calls.create` with a 10s timeout and no idempotency key; `campaigns.py:611-625` re-queues in five minutes. **A double-contact is a compliance breach per occurrence, irreversible, and the ledger shows one attempt.** `cadence.py:224-228` already gets this right by stopping |

**On #2 specifically, against the roadmap:** it schedules ADR-0002 last, behind ~13 developer-days of Wave 0, on a stated blast radius that `voice/tools.py:80-94` contradicts — `ALWAYS_ON` is unioned back in *after* the filter, so a cardless mouth keeps `disclose_recording`, `verify_identity`, both refusals, the flow verbs and `end_call`. It still greets, discloses, verifies and hangs up. It simply cannot move money. **That is a safe degradation and it is what ADR-0002 asks for.** This is the largest sequencing error in the roadmap.

There is also a **ten-minute** Tool Grant win nobody costed. `grant.py:83-84` asserts the three always-on literals cannot be unified because `voice/tools.py` imports Pipecat. That is true in one direction only: `voice/tools.py:31-39` already imports four `agent_core.tools` modules, and `grant.py` is Pipecat-free. So `from agent_core.tools.grant import VOICE_ALWAYS as ALWAYS_ON` deletes one of the three literals with **no prerequisites** — it belongs in Wave 2A, not behind four steps of Wave 3-7.

### 5.2 What no report asked

- **Consent has no history, at all.** `consent_records.allowed_days/allowed_hours` and `channel_consents.status` are UPDATE-in-place; the sole trail is one contentless `activity_events` row. The corpus maps consent *rules* exhaustively (`35` §4, `06` DUP-02/03/04, `09` C-02/C-03) and never asks whether consent *changes* are recorded. A DPDP inquiry — or a borrower exercising a data-access right — opens with *"what did I agree to, and when did it change?"* The platform can answer neither.
- **`ledger_entries` (`sql/02_customer_account.sql:114-124`) has no `tenant_id`, no actor column, and no reference to the authority decision that authorised a waiver.** It is the money-movement record: it cannot be RLS-scoped, and it cannot be joined to *who* decided. This belongs in Wave 0-A P5's design and the "~290 hand-written predicates" framing does not surface it.
- **A fifth account-tail algorithm, in a borrower-facing SMS.** `enact.py:237` is `str(account_ref)[-4:]`, rendered at `:250` as *"on the account ending {tail}"*. The roadmap's 2B-3 counts four sites and misses the only one that reaches a borrower **in writing**, on a dunning notice.
- **Two live adapter defects the corpus found and the roadmap dropped from every wave.** `voice/tuning_apply.py:70` is `mapping.get(key, Language.EN_IN)` — the exact fail-open `providers/factory.py:3-7` was written to close; `37` I20 grades it *"the highest-consequence silent substitution left, because its failure mode is fluent words rather than an error."* An unmapped locale transcribes as English-India and every downstream layer scores the nonsense as the borrower's words. And `38` M7: the TTS factory is bypassed by its own consumers. **A regulated, borrower-facing silent substitution outranks the entire contents of Wave 5.**
- **`run_stack.ps1` and `dev-up.ps1` start four of the five compose services.** Neither starts `voice.workers.insurance` (a full compose service) or `mcp_server`. A developer who only uses the PowerShell launchers never exercises the insurance mesh worker.
- **Reports 32 and 33 do not exist**, and `29` / `30` carry no date line. A two-report gap nobody should assume was covered.

### 5.3 What the corpus over-ranks

Real engineering costs, correctly measured, wrongly graded as risk. **No borrower is contacted, charged, or misquoted by any of them.**

`38` C1 (`db.py` is 18,087 lines, fan-in 101, SCC 76–107) — Critical, and a genuine maintenance problem whose real cost is indirect: it is *why* Wave 4 must precede Wave 5. A cost item, not a risk item. `30` C1 (295 unlabelled controls) — excellent measurement, but these are **internal operator screens**; the exposure is employment-practice, not collections-conduct. `29` U11 (`cn()` drops two type tokens) — beautiful forensics, two font sizes render one step wrong. `21` S1/S2 (no vuln gate, no Python lockfile) — real, but against an on-prem bank deployment with no public write surface, a transitive CVE is a slower path to a regulatory event than any item in §5.1. `16` S1 (the inbox poll) — cost and latency.

And two retractions that must be **propagated back into the reports that still carry them as Critical**: the flow-control literal "drift" (`06` DUP-01, `38` C3), which the roadmap correctly retracts and those reports still assert; and `07`'s `CAMPAIGN_RUNTIME_ENABLED` verdict (§2.1).

---

## Unverified — stated plainly

- **No runtime evidence was obtained.** Docker is down; nothing on 8000 or 3000. R1–R8 are open, and **R1 is the one that matters most** — it is the only dynamic-dispatch site in the backend whose target set is not enumerable from source, and the only one where a wrong deletion is a production outage rather than a test failure.
- I did not run pytest, so `test_contact_policy.py:287`'s exact failing assertion is unconfirmed; the date literal is where the standing note says it is.
- The frontend deletion set was verified by reference extraction over `Habibi/src` plus config and lockfile inspection. It was not verified by a build.
- `backend/.env` was read for key presence only. No value or length was inspected or is reported.
- Whether `AlertLane`/`CallTile`/`ScenarioList` were superseded or are mid-redesign is inference from git history, not evidence. It needs one question to the Floor owner.
