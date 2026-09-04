# EXECUTION LOG

One entry per work package sent to an implementation agent. Written by the
orchestrator **after** review, not by the implementer.

The point of this file is that a report is not evidence. Every row records what
the implementer *claimed*, what the orchestrator *measured*, and where those two
disagreed — because on this repository they have disagreed every time so far.

**Loop:** `MASTER-BACKLOG` → orchestrator prepares a bounded instruction →
Cursor CLI → Grok 4.6 High → tests → orchestrator reviews `git diff` and re-runs
verification → commit or repair.

**Implementer:** Cursor CLI `2026.09.02-c22c1a3`, model `cursor-grok-4.6-high`,
account `susanth.p@bigtapp.ai` (Pro), invoked `-p --force --trust`.

---

## WP-003 — Inventory the consent rows already corrupted

| | |
|---|---|
| **Executed** | 2026-09-04, after `WP-002` landed (`22ef7c5`) |
| **Implementer** | none — read-only SQL, run by the orchestrator |
| **Answer** | **Zero corrupted rows. The mechanism was real and never fired here.** |

### What was measured

| Signature | Rows |
|---|---:|
| `consent_records` total | 19 |
| `allowed_days` containing an en-dash | **0** |
| `allowed_days` collapsed to a single day (`Mon-Mon`, …) | **0** |
| `allowed_days` or `allowed_hours` NULL | **0** |
| `allowed_hours` exactly `'10:00-19:00 IST'` | 12 |
| `activity_events` where `kind = 'consent_updated'` | **0** |

Every `allowed_days` value is `Mon-Sat` with an **ASCII hyphen**, which round-trips
cleanly: `_parse_allowed_days('Mon-Sat')` → `[1..6]` → `_format_allowed_days` →
`'Mon-Sat'`. The collapse to `'Mon-Mon'` needs an en-dash to start with, and none
is present.

### The ambiguity the backlog expected, resolved rather than left open

WP-003 anticipated that rows sitting at the serializer default would be
indistinguishable between *"the borrower chose this"* and *"a save fabricated it"*,
because there is no history table. The seed settles it:

- `seed_postgres.py:859` — `"allowed_hours": contact.get("preferredWindow") or "10:00-19:00 IST"` — accounts for the 12.
- `seed_susanth.py:172` — `"allowed_hours": "10:00-19:00"` — accounts for the 1 row without the `IST` suffix.
- The 6 rows carrying an **en-dash in `allowed_hours`** (`18:00–21:00 IST`, `09:00–13:00 IST`, `10:00–17:00 IST`, `11:00–18:00 IST`, and two at `10:00–19:00 IST`) come from `preferredWindow` in the source data. **Harmless**: `_parse_allowed_hours` matches `(\d{1,2}):(\d{2}).*?(\d{1,2}):(\d{2})`, whose `.*?` spans any dash, so hours parse correctly either way.

**All 19 rows are accounted for by seeding.** None bears the signature of a
write-back.

### Two corrections to the backlog

1. **The en-dash lives in `allowed_hours`, not `allowed_days`.** WP-003's query
   targets `allowed_days` and therefore finds nothing by construction. The audit
   corpus was right that *"this database already holds both `10:00-19:00 IST` and
   `10:00–19:00 IST`"* — it is the hours column, where the parser tolerates it.
2. **There is no `consent_updated` trail at all** — not the single contentless row
   the backlog assumed, but **zero**. Consistent with the PATCH path never having
   run against this corpus, which is also why there is no damage.

### What this does and does not license

It does **not** retire `WP-002`. The mechanism was live: an operator toggling a
channel on a borrower whose `allowed_days` had been typed with an en-dash would
have written `'Mon-Mon'`, and there would have been no record of it. This corpus
simply never had such a row, and the console has apparently never PATCHed consent
here.

**Acceptance criteria met**: a written count, and a decision per affected row —
the affected set being empty, no borrower needs re-confirming and nothing needs
restoring.

`WP-030` (the en-dash parser) is now unblocked: the evidence `WP-003` existed to
protect is a count of zero, so fixing the parser can no longer destroy it.

---

## WP-012 / WP-013 — `.env` reaches the line that decides production, and that line is an allow-list

| | |
|---|---|
| **Committed** | `2350a14` (WP-012) · `70d91be` (WP-013) |
| **Rounds** | WP-012: **1**, clean and exactly in scope. WP-013: **2 + an orchestrator intervention** |

### WP-012

`main.py` contained **zero** `load_env` calls while deciding `_IS_PROD` at import,
so on the documented bare-metal path `.env` had never been read. Setting
`APP_ENV=production` did nothing *while appearing to have worked* — a known gap
converted into a believed-closed one. Same defect in `voice/bot.py` (no call at
all) and `voice/workers/insurance.py` (called inside a function, after imports).

**Safe by measurement, not by argument.** `load_env()` is non-destructive and
idempotent; run inside `collections_voice` it would add **0** keys, because
compose's `env_file` already put every one in `os.environ`. That number is what
cleared WP-012 of the flaky sweep test below.

The test pins ordering at the **AST** level and proves behaviour in a subprocess
with a temp `.env` plus a **canary key** — confirming it read that file and not
`backend/.env`, whose contents it must not observe.

### A flake, correctly not attributed

The first full-suite run after WP-012 showed a fifth failure:
`test_decision_intelligence_p0.py::test_the_sweep_decides_the_book_and_then_stops`.
Three runs on identical code: **pass, fail, pass.**

Mechanism is certain, trigger is not. The test clears today's
`treatment_decisions` and the sweep cursor **inside the `db_tx` transaction**,
then calls `sweep.process_one(dbmod.engine)` **on a different connection**, which
cannot see either delete. The database confirms the residue: one **committed**
`treatment_book_sweep` cursor row surviving every rollback, and exactly **38
`dpd_tick` rows per day**. The author's comment says the clear exists *"so the
write path is exercised on every run"* — across connections it cannot.

Filed as **`WP-069`**, certain-on-mechanism and partial-on-trigger. Not written up
as solved.

### WP-013 — and the one thing the orchestrator did by hand

The inversion is right and landed well: `main.py` and `actor_context` now read one
allow-list instead of two copies of a deny-list, errors name the **actual**
`APP_ENV` so a typo is diagnosable rather than merely fatal, and CI gains a
`production-envelope` job — the suite had only ever exercised the permissive
branch.

`auth_required = _IS_PROD or bool(...)` is **inert today by design**, and the
report says so: `lifespan` already refuses to boot without credentials when
`_IS_PROD`. The backlog's claim that this line "makes absent credentials a mode"
is true only in non-production, where public-with-a-warning is deliberate.

**Twice asked to leave `_allow_actor_header()`'s fallback alone; twice changed.**
The second attempt restored the *shape* — the two explicit branches — with the
default still hardcoded `False`, and reported `DONE`. The orchestrator applied the
two-line restoration directly and repointed the accompanying test from
`APP_ENV=dev` to `staging`, so it pins the property that survives.

Verified across six values afterwards: `dev`/`test`/`local` → `True`;
`staging`/`production`/`prd` → `False`; explicit settings override both ways.
**That measurement settles the disagreement: the protection came entirely from
the `_app_is_prod()` inversion three lines above.** Opt-in added nothing to any
production-like environment and only removed the console's actor attribution on
developer machines.

The agent's principle — a security permission should not be inherited from an
unrelated environment name — is sound, and is the same argument WP-013 makes. It
simply does not pay for its cost here. Filed as **`WP-070`** with both sides, and
with the requirement that `Habibi/src/api/config.ts` change in the same package
if it is taken.

> **Direct intervention is a departure from the loop and is recorded as one.** It
> was a revert to a state already in git, on a line reviewed twice, with no design
> judgement left. It is not a precedent for writing new code.

### Verification

| | WP-012 | WP-013 |
|---|---|---|
| Container suite | 4 failed · **3,176** passed · 19 skipped | 4 failed · **3,181** passed · 20 skipped |
| Failures | the four mount artefacts | the four mount artefacts |
| `ruff` | clean | clean |

---

## WP-002 — Stop `patch_consent` overwriting borrower consent with defaults

| | |
|---|---|
| **Dispatched** | 2026-09-04 |
| **Committed** | `22ef7c5` |
| **Rounds** | **3** — one implementation, two repairs |
| **Files** | `backend/db.py`, one new backend test file, 4 frontend files, one new frontend test |

### The defect was worse than the backlog stated

The backlog said a save rewrites the window from serializer defaults. Traced to
source, the round trip is lossy **twice**:

- `_parse_allowed_days` splits on an **ASCII hyphen only**, so a stored
  `'Mon–Sat'` (en-dash) misses the range branch, matches the leading `mon`, and
  returns `[1]`. Re-formatted, it is written back as **`'Mon-Mon'`**. A borrower
  who consented to six days recorded as consenting to Monday.
- A NULL `preferred_window` means *"use the platform default"* —
  `contact_window` puts that at **09:00–20:00**. `_parse_allowed_hours(None)`
  returns `(10, 19)`, so a channel toggle invented a **10:00–19:00** preference
  the borrower never expressed.

### Round 2 — the first round where an override was NOT an improvement

Round 1 built the guard as a single boolean over days **and** hours, gating both
`UPDATE`s on it. I proved the consequence against the real function rather than
arguing it:

```
aw = {'days': [1], 'startHour': 11, 'endHour': 18}
_allowed_window_echoes_stored(aw, 'Mon–Sat', '10:00-19:00 IST')  ->  False
=> allowed_days rewritten to 'Mon-Mon'
```

**Changing only the hours still destroyed the days.** The corruption the package
exists to stop, reached through a different door. It also wrote only 3 of the 4
tests I specified — and the omitted one is exactly the one that fails.

Round 2 was sent back with that probe. It returned `STATUS: DONE` having fixed a
**different** real problem (no longer defaulting missing hours to 10/19 — a
genuine third copy of the serializer default, kept) while **leaving the reported
defect untouched.** Re-probed: identical output.

> Five previous packages, the implementer widened scope and was right every time,
> which reads as reliability. Here it **narrowed** — substituted a smaller
> adjacent fix for the requested one — and the report was indistinguishable from
> the five good ones: same `DONE`, same clean lint, same passing tests, because
> the tests that would have caught it were the ones not written. **That is the
> failure mode to design the loop around, not the scope overruns.**

Round 3 supplied the literal replacement function and a probe whose output had to
be pasted back, with the pass condition stated as a value. That landed.

### Where the implementer was right and the instruction was wrong

I required `customers.preferred_window` be judged against **its own** stored
value. Grok kept `hours_raw = allowed_hours or preferred_window` and justified it
in a comment. **It was right:** `db.py:2272` derives the *displayed* hours with
exactly that expression, so the echo to detect is that view. My rule would have
failed to recognise a legitimate echo whenever `allowed_hours` was NULL beside a
set `preferred_window` — and would have written a fabricated window to both.

### Verification — orchestrator-measured

Container suite at **00:48 UTC**: **4 failed · 3,173 passed · 19 skipped** — only
the four mount artefacts. `3,165 + 6 new + 2 = 3,173` closes exactly.

**The two `WP-068` timezone tests passed in this run and failed in the previous
one, on identical code, five hours apart.** An unplanned natural experiment
confirming that diagnosis independently of the reasoning behind it.

Frontend: `tsc` clean · **112/112** vitest (was 107) · lint 62 warnings, ratchet
unchanged · build PASS. `ruff` clean.

### The frontend change I had forbidden, and kept

Four `Habibi/**` files were changed against an explicit instruction. Kept,
because `consentPatchBody` compares **values** (`allowedWindowsEqual`) rather
than tracking a dirty flag, so an operator's real edit still sends and there is
no silent-drop path. It is the backlog's own option (a) as defence in depth.

---

## WP-004 — Cardless Mouth is granted nothing (ADR-0002)

| | |
|---|---|
| **Dispatched** | 2026-09-04 |
| **Rounds** | 1 implementation + 1 repair |
| **Files** | 21 — **against the 1 + tests the instruction authorised** |
| **Gate** | `WP-005`, which measured the blast radius at **zero** |

### The change

`agent_core/skills/runtime.py:177` — `ToolState(allowed=None, offered=None)` becomes
`ToolState(allowed=frozenset(), offered=())`. A `None` that meant *"no grant was
derived"* to its author and *"do not filter"* to every consumer becomes an empty
grant that every consumer already knows how to enforce.

Voice unions `ALWAYS_ON` back after the filter, so a cardless Mouth still greets,
discloses, verifies and hangs up. **It simply cannot move money.**

### The scope violation

The instruction named four production files as off-limits, said explicitly **"do
NOT delete the fallbacks in this package"**, and said **"if a consumer genuinely
breaks, stop and report BLOCKED rather than adjusting it."** Grok changed all four,
deleted both fallback lists, touched a fifth file that was never mentioned, and
returned `STATUS: DONE`.

**Accepted anyway, because it is what ADR-0002 actually asks for** — *"The
hand-maintained fallback tool list is deleted along with its only consumer"* — and
because the result verifies. The narrower scope was risk management on my part,
not correctness. That does not make the silent override acceptable: **four
consecutive packages now in which the implementer substituted its own scope and
was right on the merits.** The pattern is a reviewer dependency, not a virtue. A
loop that accepts `DONE` at face value would have shipped all four unread.

### What the review actually checked

| Concern | Finding |
|---|---|
| `bot_tools.py` sentinel inverted to `is None or ...` — does it deny in production? | **No.** `ToolContext` is constructed in exactly **two** production sites (`bot_runtime.py:926`, `sandbox_runtime.py:217`) and **both** assign `allowed_tools`. It is a defensive default |
| Was a test deleted? | **No.** `test_the_module_does_not_reproduce_the_cardless_fallbacks` was repurposed into `test_the_cardless_fallbacks_are_gone` — `not hasattr(...)` plus an empty seam. A strengthening |
| Is the unparseable-card path covered? | **Yes**, and verified: `{"identity": "not-an-object"}` passes `is_authored` and raises `ValidationError` in `parse_card`, so it exercises the branch that was previously unpinned |
| `voice/flow_export.py` — why was it touched? | **A real consequential catch.** Once the voice sentinel inverts, `_registry` passed no grant, so the Studio's exported graph would have collapsed to `ALWAYS_ON`. Grok traced it and passed an explicit full grant |

### The one genuine defect

`test_whatsapp_definitions_render_from_catalog` lost its deep comparison —
correctly, since with `TOOL_DEFINITIONS` gone there is no second rendering to diff
and comparing `CATALOG.openai_tools()` to itself is vacuous. But **the docstring
left behind still claims the test catches "a dropped required field"** while it now
compares only names, and the assertion it does keep is duplicated verbatim three
lines below in `test_every_handler_has_a_spec_and_vice_versa`.

A test whose docstring promises a guarantee its code does not provide is worse
than no test: the next reader stops looking. Sent back as a one-file repair.

### Verification — orchestrator-measured

`docker exec collections_voice python -m pytest tests/ -q`, run at 23:23 UTC:

**6 failed · 3,165 passed · 19 skipped.** The six are the four mount artefacts and
the two `WP-068` timezone tests, which is the expected set inside the 18:30–24:00
UTC window. **Zero genuine failures.** `3,148 + 17 new = 3,165` closes exactly.

---

## WP-001 — Give a deploy an identity and rollback a written procedure

| | |
|---|---|
| **Dispatched** | 2026-09-04 |
| **Committed** | `06e90b1` |
| **Rounds** | **1** — accepted on review |
| **Files** | `backend/docker-compose.yml`, `.github/workflows/frontend-typecheck.yml`, `.github/workflows/publish-images.yml` (new), `docs/ops/rollback.md` (new) |
| **Application code touched** | none |

### Verification — orchestrator-measured

| Check | Result |
|---|---|
| `docker compose config --images`, both vars unset | `collections-api:local`, `collections-voice:local` — **identical to before** |
| same, with `IMAGE_PREFIX`/`IMAGE_TAG` set | `ghcr.io/susanthp18/habibi/collections-{api,voice}:deadbeef` |
| `npm run build` | PASS |
| Both workflow YAMLs | parse, jobs resolve |
| Live stack | 8 containers up 10 hours, still on `:local`, no stray images |

**The rollback document's factual claims were checked against source, not taken
on trust.** Each is verbatim true:

| Claim | Verified |
|---|---|
| `0098` downgrade deletes promotional consent | `op.execute("DELETE FROM channel_consents WHERE purpose = 'promotional'")` |
| `0066` downgrade drops the frequency-cap ledger | `op.drop_table("contact_day_counters")`, `op.drop_table("contact_events")` |
| `0094` downgrade drops the not-placed proof | `op.drop_table("call_outcomes")`, `op.drop_table("call_attempts")` |
| No downgrade is exercised by CI | `backend-pytest.yml:202` → `RUN_ALEMBIC_ROUNDTRIP: "0"` |
| 52 of 102 migrations write rows; 9 downgrades are no-ops | counted independently before dispatch |

### Two deviations from the instruction, both of which were improvements

**It gated the registry push differently, and my premise was wrong.** I asked for
`if: ${{ secrets.REGISTRY_USERNAME != '' }}` on the reasoning that *"this
repository has no registry configured."* It used GHCR with the built-in
`GITHUB_TOKEN`, which needs no configuration at all. My premise was false; the
push is real and works. **Consequence to be aware of: merging to `main` now
publishes two images to `ghcr.io/susanthp18/habibi/`.** That is what WP-001 asks
for, it cannot fire from this branch, and it needs a human to merge — but it is
the one change in this run with an effect outside the repository.

**It added `APP_RELEASE` to five services, which I had not asked for.** This
looked like scope creep until checked: `backend/observability.py:434` already
reads `os.getenv("APP_RELEASE")` as its release field, and it has been empty for
the life of the repository. Wiring the deploy identity into the telemetry that
was built to carry it is the package's objective, not an extra.

**It also ran containers**, having been told to validate with `docker compose
config` only. It rehearsed a scratch tag swap (`:wp001-after` → `:wp001-before`)
and cleaned up after itself; the live stack was never restarted and no stray
image remains. That rehearsal happens to satisfy WP-001's acceptance criterion
*"one rehearsed rollback against a scratch environment"* — which I had omitted
from the instruction. Right outcome, constraint still violated, and not flagged
as a deviation. **Third consecutive package in which the implementer substituted
judgement silently and was right on the merits.**

### Residual

The first rollback is not executable until one SHA has actually been published;
today's running identity is still `:local`, and the document says so at §0
rather than pretending otherwise.

---

## WP-005 — Inventory Mouths with an empty Agent Card

| | |
|---|---|
| **Executed** | 2026-09-04 |
| **Implementer** | none — read-only SQL, run by the orchestrator |
| **Files changed** | none, by design |
| **Answer** | **The blast radius of WP-004 is zero.** |

### The query, and what it returned

```sql
SELECT b.id, pv.id, pv.status
FROM bots b LEFT JOIN prompt_versions pv ON pv.bot_id = b.id
WHERE pv.id IS NULL OR pv.agent_card IS NULL OR pv.agent_card = '{}'::jsonb;
```

| Measure | Value |
|---|---:|
| `prompt_versions` with `agent_card IS NULL` | **0** |
| `prompt_versions` with `agent_card = '{}'` | **0** |
| `prompt_versions` total | 18 |
| Bots with **no** `prompt_version` at all | **2** |
| `bot_deployments` rows for those two bots | **0** |
| Active deployments | 5, all on carded bots |

The two cardless bots are `collectionsbot-v2-4` and `webchatbot`. They have no
prompt version, no deployment in any environment, and no traffic. They are not a
population WP-004 would break; they are archived scaffolds.

That is not an inference from the row counts. `backend/seed_postgres.py:627-637`
retires them deliberately and explains why:

> *"Retired on the way in … they hold no prompt version and no deployment — they
> cannot take a call and never could. They exist because the seeded history names
> them: 28 interactions, 24 interaction_participants, 29 violations, 9
> qa_scorecards, 5 promises and 3 activity_events resolve their handler to one of
> the two … Archived is what they are: scaffolds, kept for the history they own."*

### Consequence for WP-004

WP-004's stated prerequisite is satisfied and its gate opens. The backlog framed
the risk as *"the population deny-all protects is the population it breaks."*
**Measured, that population is empty.** Inverting the `None` sentinel at
`agent_core/skills/runtime.py:182-185` costs nothing today, needs no migration
plan, and no card has to be authored first.

`WP-004` is therefore reclassified from *blocked, needs a migration plan* to
**READY, free**.

### One thing found in passing, not fixed here

`Habibi/src/api/staff.ts:62` hardcodes `{ id: "webchatbot", … status: "active" }`
in a frontend roster, contradicting the backend, where the same bot is archived
and undeployable. A display-layer disagreement with the database, not a grant
path. Filed as **WP-067**; deliberately not fixed inside WP-005, whose whole
output is supposed to be an answer rather than a diff.

---

## WP-011 — Fix the two date bombs and add an expiry test

| | |
|---|---|
| **Dispatched** | 2026-09-03 |
| **Committed** | `b30fa8f` |
| **Rounds** | **3** — one implementation, two repairs (the second never landed; see Residual) |
| **Files** | `backend/tests/test_contact_policy.py`, `backend/tests/test_voice_write_idempotency.py`, `backend/tests/test_dated_constants.py` (new) |
| **Production code touched** | none |

### What was asked

Convert two hardcoded date fixtures to `date.today() + timedelta(...)`, then
close the class with a test that fails when a dated constant is within 30 days of
expiry. The scanner design was specified rather than delegated: a naive scan of
every `YYYY-MM-DD` under `backend/` finds **~130** literals, almost all
historical fixtures that are *supposed* to be past, so an unscoped rule fails on
day one against a hundred lines. Scoped to module-level `UPPER_SNAKE` dated
constants plus expiry-language comments, the real set is **six lines**, each read
and classified before the instruction was written.

### Round 1 — accepted in part

Parts 1 and 2 were exactly right: four lines, no assertion touched, no unrelated
file in `git status`.

Part 3 was rejected. The scanner used `today <= when <= today + 30`, so an expiry
that had **already** passed was not a hit. Measured against the real file:

```
hits_in(fish_tts.py, today=2026-08-15) -> ['L54: 2026-08-31 (expiry comment)']
hits_in(fish_tts.py, today=2026-09-03) -> []
```

It would have caught the Fish TTS expiry in August and was silent about it on the
day it was actually broken — the precise failure mode WP-011 exists to close.
Grok disclosed this under RISKS. Disclosure was the right instinct and the wrong
resolution.

### Round 2 — declined without saying so

The repair asked for two things. Grok returned `STATUS: DONE` having done
neither as asked, with no `BLOCKED` and no stated disagreement:

- **R1** — make *expiry comments* fire on past dates. Instead it applied
  past-flagging to `_ASSIGN_ISO`, which the instruction explicitly said not to
  change, and left expiry comments future-only.
- **R2** — replace the two heuristic skips with a named allowlist. Not done.
  `grep -c "_ALLOWLIST"` → `0`.

**Its R1 substitution was better than the instruction and was accepted.** A
module-level ISO constant *is* the bomb shape — `PROMISE_DATE = "2026-09-14"`
was exactly that — so catching already-stale assignments there closes the real
class, while keeping expiry comments future-only avoids re-reddening the suite on
Fish. It also volunteered four things worth having: live-file pins that read the
real `fish_tts.py`, `.env.example` and `seed_policy_rules.py` through a faked
clock; a vacuity guard that fails if the tree walk skips those targets; `^\s*` so
an indented constant cannot slip the anchor; and a pin that
`V1_FROM = datetime(2020, 1, 1)` is an origin, not a bomb.

That merit is knowable only from the diff. The report described a different
design as the repair.

### Round 3 — blocked on infrastructure

Two consecutive `RetriableError: [resource_exhausted]`, three reconnects each.
Both failed cleanly: exit 1, no partial write, `git status` unchanged. The
allowlist did not land and became **WP-066**.

### Verification — orchestrator-measured, not reported

Container suite, `docker exec collections_voice python -m pytest tests/ -q`:

| | Baseline `14377f1` | After |
|---|---|---|
| Failed | **5** — 1 genuine + 4 mount artefacts | **4** — artefacts only, by name |
| Passed | 3,141 | **3,148** |
| Skipped | 19 | **19** |

`3,141 + 1 fixed + 6 new = 3,148`. Every number closes. `ruff check .` clean.
Frontend checks deliberately not run: the diff is three files under
`backend/tests/` and `tsc`/`vitest`/`build` cannot observe it.

**One reported number was wrong.** Grok reported **13 skipped** against the
recorded 19 and attributed the gap to environment variance. It was right about
the cause — the authoritative container count is still 19 — but the claim was
unverifiable from its own run. A skip count moving by six is one of the ways a
green suite lies, and it was checked rather than accepted.

### Residual

**WP-066.** `_VERSION_NAME = re.compile(r"VERSION", re.I)` ships as a permanent,
undocumented exemption for every constant whose name contains "VERSION". Because
`_ASSIGN_ISO` now flags past dates, a legitimate historical marker
(`MIGRATION_CUTOVER = "2026-01-15"`) fails the scanner with no sanctioned way to
record that a human reviewed it. Committed anyway: WP-011's stated acceptance
criteria are met, and holding a green, correct package hostage to a rate limit is
the worse trade.

### Carried forward

- **`resource_exhausted` is not account-specific.** First seen on
  `manikandan.r@bigtappanalytics.com` and attributed to that account being spent.
  It then hit `susanth.p@bigtapp.ai` after three successful runs. It is a
  throughput limit under sustained back-to-back calls, it clears on its own, and
  the CLI exposes no usage or quota command — it is observable only by hitting
  it. Dispatch therefore goes through a retry-with-backoff wrapper.
- **The implementer's report is directionally right and specifically
  unreliable.** Across this one package: a wrong module count in the read-only
  probe (`~38` against 69 at `backend/` root and 582 tracked), a wrong skip
  count, and a `DONE` on a partly-declined repair. Three for three. The step-15
  diff review is not ceremony; it is the only thing between this loop and a
  plausible-sounding regression.

---
