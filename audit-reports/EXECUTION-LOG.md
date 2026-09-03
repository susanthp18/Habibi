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
