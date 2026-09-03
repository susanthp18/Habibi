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
