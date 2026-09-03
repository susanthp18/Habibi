# 22 — Testing and Quality

**Scope.** The whole test estate: `backend/tests/` (186 `test_*.py` + `conftest.py`), `Habibi/src/**/*.test.ts` (11 vitest suites), `backend/voice/evals/` (15 authored scenarios), and both CI workflows. Production surface measured for comparison: 143,586 LOC across 394 Python files in `backend/`, and 474 TypeScript files in `Habibi/src`.

**Method.** Six analysts (unit, integration, frontend, API, E2E, maintainability) plus a direct thread. Every metric in this report is AST-derived or `git ls-files`-derived, never estimated from a regex over a filename; the method is stated beside each number. Every Critical and High was re-verified by hand against the cited `file:line` before it was written down. Where two analysts disagreed, both numbers appear with their methods rather than one being silently chosen.

**The instruction not to judge by test count is load-bearing here,** and this report follows it literally: 2,431 test functions is a large suite, the naming is unusually good, and neither fact is evidence about risk. Coverage below is stated per business capability, and — the distinction that drives most of the findings — separates a test that asserts *the engine produces this outcome* from one that asserts *this constant is in the right list*.

---

## Verdict

**The suite protects the platform's mechanics well and its regulatory obligations poorly.** That is not a general weakness; it is a specific and repeated shape, and it has one cause.

Where a rule is expressed as **data** — a constant, a set, a registry, a schema — this codebase tests it thoroughly and inventively. Where a rule is expressed as **a decision the engine makes about a borrower**, the test usually stops at the data and never reaches the decision.

The clearest instance, verified by hand. `contact_policy.py` defines twelve refusal reasons. Of these, **five are ever asserted as an outcome the engine produces** (`daily_cap`, `outside_calling_hours`, `channel_opted_out`, `no_customer`, `no_promotional_consent`). The other seven — including `customer_dnd`, `channel_dnd`, `channel_expired`, `cooling_off`, `weekly_cap` — appear in tests *only as members of a policy set*:

```python
# tests/test_demo_call_waiver.py:44-56 — a good test of a different thing
@pytest.mark.parametrize("reason", [
    contact_policy.REASON_OPTED_OUT,
    contact_policy.REASON_CHANNEL_DND,
    contact_policy.REASON_CUSTOMER_DND,
    ...
])
def test_consent_refusals_are_never_waivable(reason: str) -> None:
    assert reason not in main._DEMO_WAIVABLE_REASONS
```

That asserts DND is *classified* as non-waivable. It does not assert that any borrower marked DND is ever refused. `contact_policy.py:505` is the line that returns `REASON_CUSTOMER_DND`, and **no test in the repository reaches it.** If that branch were deleted, the suite stays green.

The same shape recurs at every level, and it explains findings that otherwise look unrelated:

| The rule | Tested as data | Never tested as behaviour |
|---|---|---|
| DND / consent expiry / cooling-off / weekly cap | membership of `_DEMO_WAIVABLE_REASONS` | the engine emitting the refusal |
| Route authorization | `assert_registry_covers` proves the registry total over 314 routes | 5 of 314 routes have a negative-auth test |
| Opt-out capture | opted-out borrowers hand-built with raw SQL | `db.opt_out` — the production writer — is called by **no test** |
| Webhook signatures | `verify_webhook_signature` unit-tested | no test asserts a *route* rejects an unsigned body |
| Voice pipeline | stage list asserted by `ast.parse(inspect.getsource(...))` | no frame ever traverses two processors |

Two further findings are categorical rather than scattered — each is a property of the harness, so no amount of writing more tests of the current kind will close them.

**The fixture makes concurrency impossible to test.** `db_tx` (`conftest.py:47-60`) routes every `engine.begin()` into a SAVEPOINT on one shared connection. There is no second connection and no commit, so every `FOR UPDATE SKIP LOCKED` claim path, every advisory lock and every uniqueness race is verified by a test that structurally cannot exercise it. Production has ~16 such claim paths; **one** has a contention test. The advisory lock at `db.py:702-707` — added specifically because two requests once created *"two promises for one idempotent POST"* — could be deleted today with the suite still green (C8).

**Coverage is a function of the demo seed, and nothing asserts the seed has content.** 436 of 2,431 tests (17.9%) can disappear at runtime without failing anything — 284 because the seed did not contain the row they needed. CI closes most of this by running `scripts/seed_demo.py`, and `backend-pytest.yml:44-52` records that it was once wide open (*"Every test in this repository was decorative until this line existed"*). What remains is that a seed exiting 0 with no delinquent accounts turns 284 tests into skips and CI stays green. Fifty-six sit in compliance- and tenancy-named files (H1).

**One test is failing right now** for an unrelated reason — a `2026-09-01` date literal that aged out on 2026-09-02 (C7). That matters beyond the one test: it retires the assumption that a red run means you broke something.

### If only seven things are fixed

1. **Fix the stale date literal** at `test_contact_policy.py:289`. One line. Until it is fixed, the suite is red for a bogus reason, which is how teams learn to skim past red.
2. **Assert the seed floor.** One test that fails when `customers`, `accounts`, `interactions`, `products` or `leads` is empty converts 284 silent skips into one loud failure. Cheapest high-value change in this report.
3. **Test the seven unreached refusal branches** in `contact_policy.evaluate` — a DND borrower, an expired consent, a cooling-off window, a weekly-capped account. `_veto` takes a plain dict, so these are pure unit tests, not DB work. This is the regulatory core and it is roughly a day.
4. **Replace `assert len(DETECTORS) == 16`** with a cross-check against the seeded catalog, then decide whether the four checklist rules should be seeded or deleted. Right now the compliance screen reports clean on four rules that cannot fire (C6).
5. **Call `db.opt_out` in a test** and assert `contact_policy` then refuses. Capture and enforcement are never in the same process today.
6. **Add one contention test per high-volume queue**, starting with the dial queue and the reminder sender. `test_job_claim.py` is the working template — the team has already solved this once.
7. **Pin `PUBLIC_ROUTES` and `_AUTH_EXEMPT_PREFIXES` as exact sets**, and add one HTTP test per webhook asserting an unsigned body gets 401.

---

## Findings — Critical

### C1 · Seven of twelve statutory refusal reasons are never asserted as engine behaviour, including DND

`contact_policy.py` is 1,096 lines and defines twelve refusal reasons at `:42-56`. I resolved each against the whole test suite, distinguishing an assertion that the engine *emits* the reason from a mention of the constant:

| Reason | Emitted at | Behaviourally asserted? |
|---|---|---|
| `daily_cap` | `:589`, `:975` | yes — `test_contact_policy.py:129` |
| `outside_calling_hours` | — | yes — `test_contact_policy.py:176` |
| `channel_opted_out` | `:299` | yes — `test_contact_policy.py:211` |
| `no_customer` | — | yes — `test_contact_policy.py:251` |
| `no_promotional_consent` | — | yes — `test_outbound_completion.py:294` |
| **`customer_dnd`** | **`:505`** | **no — set membership only** |
| **`channel_dnd`** | **`:299`** | **no — set membership only** |
| **`channel_expired`** | **`:301`** | **no — set membership only** |
| **`cooling_off`** | **`:589`, `:975`** | **no — set membership only** |
| **`weekly_cap`** | **`:594`, `:978`** | **no — set membership only** |
| **`outside_allowed_window`** | — | **no — set membership only** |
| **`consent_unreadable`** | `:597-601` | **no — set membership only** |

The only tests naming the seven are `test_demo_call_waiver.py:44-56` and `test_outbound_kill_switch.py:342-356`, both asserting membership of `main._DEMO_WAIVABLE_REASONS`. Those are good tests of waiver policy. Neither constructs a borrower.

Corroborating the gap from the data side: the only test that ever writes a blocking consent status writes `opted_out` (`test_contact_policy.py:194`). No test writes `dnd` or `expired` into a consent row. The lone `dnd` assertions in the suite are `test_reco_engine.py:166` (`arbitration.SUPPRESS_DND` — a different module, different code path) and `test_call_context.py:129` (sets a display field on a card).

**Consequence.** A regression in the DND, consent-expiry, cooling-off or weekly-cap branch of `contact_policy.evaluate` ships green. These are not internal invariants; they are the RBI Fair Practices Code and DPDP controls this platform exists to honour. `customer_dnd` in particular is the check that stops the platform calling someone who has told the regulator not to be called.

### C2 · No test ever calls the production opt-out writer

`db.opt_out` (`db.py:6754`) is the function that records a borrower saying "stop contacting me"; `post_call_actions.py:290` is its caller from a live call. A search of all 186 test files for `db.opt_out`, `record_optout` or `optout_events` returns **nothing** — verified independently after the analyst reported it.

Every opted-out borrower in the suite is fabricated by raw SQL against the consent table (`test_contact_policy.py:190-200`, `test_payment_events.py:102-115`, `test_promise_fulfillment.py:39-52`).

**Consequence.** Capture and enforcement are never exercised in the same process. The enforcement tests assert against a hand-built imitation of what the writer is *believed* to produce. If `db.opt_out` wrote the wrong channel, the wrong purpose, or a mismatched composite id, every consent test in the repository would still pass while every subsequent contact to that borrower was permitted. This is the single highest-exposure seam in the codebase, and it is the one journey with a named regulatory duty attached to it.

### C3 · Suppression after payment is untested — and for the two main dialers, unimplemented

The recording half is well covered: `test_payment_events.py:392-428` asserts `payment_events.status == "cured"` and `emi_installments.status == "paid"` after `payments.record_payment`.

The suppression half does not exist to be tested. Verified directly:

- `contact_policy.py:42-56` — the complete refusal vocabulary — contains **no paid/settled reason**. The contact engine cannot refuse on the grounds that the debt is paid.
- `cadence.process_one` (`cadence.py:341-465`) checks kill-switch, pause, ceiling, phone, `admit`; no payment state. Its own docstring at `:344` describes the wait as time in which the borrower *"may have paid"*.
- `campaigns.py:557` — same.
- `payments.py:183-192` updates `outstanding` but never resets `accounts.dpd`, so `treatment/sweep.py:157`'s `WHERE a.dpd > 0` keeps selecting a fully-paid account.
- The one real defence, `treatment/enact.py:93 _resolved_since`, has **no test**.

**Consequence.** A borrower who pays at 15:00 can be called at 18:00. `followthrough.py:460` calls this "the single worst thing a collections system can do". No test would catch its return.

### C4 · `campaigns.process_one` — the dialer that runs the eligibility gate — is never executed

`campaigns.py:453` claims a run, selects a target, calls `contact_policy.admit` (`:557`) and `outbound.place` (`:610`). The entire head of the outbound journey.

Its only appearance in the test suite is `test_outbound_studio_bindings.py:107-111`, which calls `inspect.getsource(campaigns.process_one)` and substring-matches the result.

**Consequence.** The function deciding who gets called is verified by reading its own text. A logic inversion in the `REASON_OPTED_OUT` skip block at `campaigns.py:574-581` passes that check — the string is still present — and ships. A harmless reformat fails it. The test is inverted with respect to what matters.

### C5 · `POST /pay/{token}/complete` settles a debt behind an untested env-string comparison

`main.py:795`. Auth-exempt via the `/pay` prefix (`main.py:248`) and listed in `PUBLIC_ROUTES` (`authz.py:231`). The sole gate:

```python
# main.py:800
if payments.is_production() or payments.provider() != "hosted":
    raise HTTPException(status_code=403, detail="hosted_complete_disabled")
```

`is_production()` is `APP_ENV in {"prod","production"}` (`payments.py:43`); `provider()` defaults to `"hosted"` (`payments.py:34`). On success it runs the full `record_payment` → ledger insert → `outstanding - :paid` → intent marked paid → promise allocation.

**No test touches this route.** Delete line 800 and the suite stays green.

The amount is taken from the intent, not the caller, and the token is a 192-bit secret (`promise_fulfillment.py:271`) — so this is a borrower abusing a capability they legitimately hold, not an open endpoint. It still writes a false settlement into a regulated collections ledger in any deployment where `APP_ENV` is unset or non-production.

**This compounds a finding from report 20.** `payments.is_production()` reads `APP_ENV` through `_env()`, which calls `load_env()`; `main.py:204` computes `_IS_PROD` at import, *before* anything loads `.env`. The two therefore disagree about whether the same process is in production.

### C6 · Four compliance detectors can never fire in production, and the test that "covers" them counts a Python dict

The most complete instance of this report's central pattern, verified end to end.

`agent_core/compliance/scan.py:59-69` runs a detector only if its `rule_id` is an enabled row in `compliance_rules`:

```python
enabled = {r["id"] for r in conn.execute(
    text("SELECT id FROM compliance_rules WHERE tenant_id = :t AND enabled IS TRUE"), ...)}
for rule_id, detect in DETECTORS.items():
    if rule_id not in enabled:
        continue
```

`DETECTORS` holds 16 entries, four of them the checklist detectors registered at `detectors.py:194` — `rule-recording`, `rule-mini-miranda`, `rule-payment`, `rule-identity`.

The only INSERT sites for `compliance_rules` are `alembic/versions/20260722_0007:49-60` and `20260814_0071_live_qa.py:122`. I read the seeded list: `_SCREEN_RULES` (`0007:24-36`) contains **eleven** ids — `r-rec`, `r-mm`, `r-dnd-disc`, `r-disp`, `r-threat`, `r-abuse`, `r-false`, `r-guarantee`, `r-dnd-win`, `r-verify`, `r-distress` — plus `r-third` from the later migration. **Twelve.** None is a `rule-*` id. The same migration's `_LEGACY_RULE_MAP` (`:38-43`) explicitly retires all four checklist ids by mapping them onto screen rules.

So four registered detectors are permanently skipped. The test that should catch this, in full:

```python
# tests/test_compliance_detectors.py:86-88
def test_every_catalog_rule_has_a_detector():
    """The registry is the contract detector_coverage reports against."""
    assert len(DETECTORS) == 16
```

It counts a Python dictionary. It never reads the catalog. Sixteen detectors are registered; twelve can run; the assertion passes. `test_compliance_detectors.py:162-184` then proves all four work perfectly in isolation — which is true and irrelevant.

**Consequence.** The four rules that judge a *human* agent's handoff call — recording disclosure, mini-Miranda, payment terms, identity verification — are dead. The Compliance Risk screen reports them clean, permanently, which is exactly the failure `detectors.py:5-7` says the registry exists to prevent. Whether the fix is to seed them or delete them is a product decision; the test must assert against the seeded catalog either way.

### C7 · A hardcoded date makes a compliance test fail as of two days ago

`tests/test_contact_policy.py:289` passes `promised_date="2026-09-01"` and asserts `result.ok`. `agent_core/tools/domain.py:724-725` refuses any past date:

```python
if _promise_date_is_past(date_s):
    return ToolResult(ok=False, error="promise_date_in_past")
```

Today is 2026-09-03 IST. **`test_due_reminder_blocked_when_capped` is failing right now**, and began failing on 2026-09-02, for a reason unrelated to what it tests. Every other promise date in the suite is computed as `date.today() + timedelta(...)`; this one literal was missed.

**Consequence, and it is the reason this is Critical rather than Low.** A red suite that is red for a bogus reason is how a team learns to skim past red. It also invalidates the working assumption — recorded in this project's own notes — that the suite is green and therefore any failure is yours. Until this is fixed, that heuristic is actively misleading. One-line fix; disproportionate value.

### C8 · The DB fixture makes concurrency structurally impossible, so every concurrency guarantee in the product is tested by a test that cannot exercise it

This is the report's other categorical finding, and it is a property of the fixture rather than of any test.

`conftest.py:47-60` replaces `db.engine` with a proxy whose `begin()` returns `connection.begin_nested()` — a SAVEPOINT on one shared connection (`:24-31`) — and whose `connect()` hands back that same connection without closing it.

| Property | Production | Under `db_tx` |
|---|---|---|
| `engine.begin()` | new pooled connection, real COMMIT | SAVEPOINT on one shared connection |
| Two `begin()` blocks | two connections, cross-visible only after commit | same connection, always mutually visible |
| Advisory locks | released on commit | held for the whole test |
| Concurrency | possible | **structurally impossible** |

Production has ~16 distinct `FOR UPDATE SKIP LOCKED` claim paths — `outbound.py:1090` (dial queue), `whatsapp_outbound.py:231`, `promise_fulfillment.py:1056` (reminders), `payment_events.py:939`, `cadence.py:333`, `campaigns.py:443,493`, `webhooks_dispatch.py:309`, `treatment/sweep.py:162`, and seven more. **Exactly one has a contention test:** `test_job_claim.py:113-370` races two threads for a `kb_index_jobs` row, barrier-synchronised, with three-way forensics to distinguish a real defect from a live worker stealing the job. It is excellent.

The other fifteen are covered sequentially, and the sequential tests *look* like coverage. `test_webhooks_dispatch.py:440` — "a row waiting on its backoff is not claimed again" — runs both `process_one` calls on one connection through `db_tx`. **A sequential test of a concurrency guard is not a concurrency test.**

The sharpest instance is the idempotency advisory lock, which exists *because of a live double-write*. `db.py:686-716` documents it: *"two requests carrying the same key both saw no row, both performed the mutation… two promises for one idempotent POST."* The fix is `pg_advisory_xact_lock` at `:702-707`, and its correctness depends entirely on the second caller waiting for the first to **commit** — which cannot happen under `db_tx`. `test_idempotency.py` and `test_idempotency_tenant_scope.py` hold 26 good assertions between them and **removing the advisory lock entirely would leave all of them green.**

Same shape at `db.py:5745` (duplicate open lead — the comment names the racing parties: *"the voice tool and the WhatsApp worker are genuinely concurrent writers"*) and `db.py:14380`/`:14820` (single-active-deployment on publish/rollback).

**Consequence.** Two workers double-claiming a reminder or dial row contacts the same borrower twice for one queued touch — a contact-cap breach the ledger records as a single event. The team demonstrably knows how to test this: `test_job_claim.py` and `test_voice_session_store_contention.py` both escape the fixture to do it. The pattern simply has not been applied to the other fifteen queues.

### C9 · Both halves of the schema-drift defence are inert, and one of them cannot fail

I praised the CI schema check before verifying its reach; it is narrower than it looks, and the test beside it is vacuous.

**`test_schema_parity.py` compares `sql/*.sql` against itself in CI.** The fixture builds the "fresh" side by replaying `sql/*.sql` into a scratch database (`:110-131`) and takes the "migrated" side from `db.DATABASE_URL` (`:134`). But CI builds `DATABASE_URL` by *applying `sql/*.sql`* (`backend-pytest.yml:103`) and then `alembic stamp head` (`:126-127`) — **migrations are never executed.** Both sides of all three comparisons derive from the same source. The test cannot fail in CI. It has meaning only on a developer machine whose database was genuinely migrated, which the file's own docstring says is not what developers have.

**The CI inline check covers a minority of the schema.** It regex-scrapes `op.create_table` and `op.add_column` only. Measured across the 102 migration files:

| Mechanism | Visible to the check | Invisible |
|---|---|---|
| Table creation | 25 `op.create_table` | **41 raw `CREATE TABLE`** |
| Column addition | 71 `op.add_column` | **54 raw `ALTER TABLE … ADD COLUMN`** |

So it verifies 38% of table creations and 57% of column additions. `work_runtime_jobs` is in the invisible set (`20260815_0077_phase4.py:65`).

**And migrations are never executed anywhere.** `test_migrations.py:55`'s roundtrip is gated on `RUN_ALEMBIC_ROUNDTRIP`, which CI sets to `"0"` (`backend-pytest.yml:202`). The only unconditional migration test, `test_alembic_has_exactly_one_head` (`:34`), shells `alembic heads` — a static parse of the revision graph that touches no database.

**Consequence.** Nothing in the repository proves the migration chain applies to an existing deployment. The check's design is genuinely good — deriving expectations from the migrations rather than a hand-kept list is the right idea, and its comment records that `idempotency_keys` was caught this way. Its reach is the problem, and the correction is to parse raw DDL too rather than to abandon the approach.

---

## Findings — High

### H1 · 436 tests (17.9%) can vanish at runtime, and nothing asserts the seed has content

AST-derived, propagating skip sites through helper calls, fixture params and module-scope `importorskip`:

| Cause | Tests | Trigger |
|---|---|---|
| Empty seed — "no customers seeded", "seed has no early-bucket account" | **284** | a migrated database whose seed produced no rows of the needed kind |
| Missing optional dep (`pytest.importorskip("pipecat.*")`) | 118 | `requirements-voice.txt` not installed |
| Missing table — "contact_events missing — apply alembic 20260813_0066" | 75 | a database behind on migrations |
| Opt-in env var | 10 | `RLS_DATABASE_URL`, `SCHEMA_PARITY_DATABASE_URL`, `TEST_DATABASE_URL`, `RUN_ALEMBIC_ROUNDTRIP` |

116 `pytest.skip()` call sites; ~95 of them phrased as *"no X seeded"*. Because the guards live in shared helpers (`_a_customer`, `_customer`, `_require_table`), one empty table disarms whole files: `test_connector_governance.py` 10/10, `test_cadence_pause_and_strand.py` 9/9, `test_payment_events.py` 9/9, `test_voice_write_idempotency.py` 8/8.

**CI closes most of this**, and deliberately: `backend-pytest.yml` installs voice deps (`:82-84`), applies `sql/*.sql`, stamps Alembic, creates two scratch databases and runs `scripts/seed_demo.py` before `pytest -q`. The residual risk is precise and unguarded: **`test_seed_coherence.py` checks that the seed is *believable* — no interaction claiming a settled account the ledger shows overdue (`:46-66`) — but nothing checks that it is *adequate*.** Remove the last delinquent account with a phone number and five tests skip silently.

Fifty-six of the 284 are in compliance- and tenancy-named files.

### H2 · Cross-tenant isolation has no HTTP-level test, and RLS is dark outside CI

Not one of `test_cross_tenant_reads.py`, `test_tenant_scoping.py`, `test_rls.py`, `test_idempotency_tenant_scope.py`, `test_tenant_context.py` or `test_object_visibility.py` imports `TestClient` or `main`. **0 of 314 routes have a cross-tenant test.**

The Python-layer tests are better than the usual "assert the SQL mentions tenant_id" — they seed a real rival tenant into real Postgres and check the row does not come back (`test_cross_tenant_reads.py:131`, `:199`). But they bypass routing, so any route with inline SQL rather than a `db.*` accessor is invisible. `test_cross_tenant_reads.py:195` notes the `KeyError` "the API layer turns into 404" — **that translation is asserted nowhere.**

Real RLS enforcement exists (`test_rls.py:305-342`: non-bypassing role, GUC via libpq, bare `SELECT count(*)`) but is gated on `RLS_DATABASE_URL`, set only in CI (`backend-pytest.yml:204`), and probes 2 tables of ~112. The gate is a module-level alias (`test_rls.py:207 requires_scratch_db = pytest.mark.skipif(...)`), so it is invisible to a grep for `@pytest.mark.skipif`. Meanwhile `rls.enable` is imported in neither `main.py` nor `db.py`, `main.py:388-392` lists RLS as a **deferred** control, and the app connects as a superuser — which bypasses RLS unconditionally.

**Consequence.** Every developer's full-suite run reports green having never tested tenant isolation, and the aliasing makes that unsearchable.

### H3 · The two exemption lists disagree with each other, and neither is pinned

A route becomes public two ways, and `assert_registry_covers` (`authz.py:886-889`) is satisfied by either — it accepts a route if it is in `ROUTE_PERMISSIONS` **or** in `PUBLIC_ROUTES`. So the totality proof that makes this design good is equally satisfied by gating a route and by declaring it public.

Verified by reading both lists:

- `POST /twilio/sms/status` and `POST /webhooks/collections/payment-events` are in `PUBLIC_ROUTES` (`authz.py:228`, `:233`) but **not** matched by `_AUTH_EXEMPT_PREFIXES` — `"/webhooks/payments"` does not prefix-match `/webhooks/collections/...`. Twilio and the core banking system carry no API key, so in production both 401: SMS delivery receipts and CBS payment events silently drop. Neither path appears anywhere in the test suite.
- Conversely `/api/offer` and `/voice-rtc` are unconditionally public in `authz` but only conditionally exempt in the middleware (`main.py:256`).

`PUBLIC_ROUTES` (27 entries) is referenced in one test (`test_authz.py:57`) and only inside a union used to find stale rows — **no assertion on its membership or size.** Adding `("POST", "/consent/{customer_id}/opt-out")` to it makes that route unauthenticated and passes every test.

`_AUTH_EXEMPT_PREFIXES` is spot-checked, not pinned: `test_production_hardening.py:25-30` asserts four Twilio paths are in it and two are not. Appending `"/customers"` passes. There is also a 15th bypass the list does not describe — `main.py:278` returns early for `POST /a2a` before the prefix check runs.

### H4 · Not one webhook route is tested at the HTTP layer

Twelve inbound webhook routes. The signature helpers are correct and fail closed — `payments.py:69-82` returns `False` when the secret or header is missing, and uses `hmac.compare_digest` — and each has a unit test. **Nothing tests that the routes call them.** Deleting the `if not verify...: raise 401` at `main.py:830`, `:862` or `:4611` fails zero tests.

Worse, the four tests that do POST to webhook routes (`test_production_hardening.py:41-45`) assert `status_code != 401` — reachability. In that fixture's environment `_twilio_signature_ok` returns `True` at `main.py:3390`, so those unsigned POSTs are being *accepted*. The inline comment claims "signature validation rejects it, not auth"; the assertion checks no such thing.

Also unguarded inside the signed path: `record_payment` never compares the payload amount to the intent amount (`main.py:838-841`), and the signature covers the raw body with no timestamp or nonce, so a captured valid request is replayable. Neither has a test.

### H5 · Negative authorization is tested on 5 of 314 routes

| Metric | Count |
|---|---|
| Routes registered (all in `main.py`; no `APIRouter`) | 314 |
| State-mutating (POST/PATCH/DELETE) | 158 |
| Route templates touched by any test | ~37 (11.8%) |
| Mutating routes touched by any test | 13 of 158 (8.2%) |
| **Routes with a negative (401/403) authorization test** | **5 of 314 (1.6%)** |
| Test files constructing a `TestClient` | 17 of 188 (9%) |
| Total 4xx assertions in the suite | 31 |

The five: `GET /webhook-endpoints`, `POST /tts-voices/catalog/sync`, `GET /staff`, `POST /prompt-versions/{id}/publish` (`test_authz.py:297`, `:303`, `:313`, `:435`), `GET /metrics` (`test_observability.py:197`).

The policy itself is sound — all 148 registered mutating routes were checked for a too-weak permission and **none was mis-gated**; the five gated on a `*_READ` permission are genuinely read-only POSTs. The gap is verification, not design.

Untested and high-consequence: `PATCH /roles/{role_id}/permissions` (privilege escalation), `POST /consent/{customer_id}/opt-out`, `POST /conversations/{id}/messages` (sends to a borrower), `POST /outbound/campaigns` + `/targets`, `GET /customers`, the three PII-redaction PATCH routes, and the three credential-rotation routes.

### H6 · No frontend component is ever rendered, and two of the eleven "tests" are source greps

Hard numbers, from `git ls-files` and `package-lock.json`:

| Metric | Value |
|---|---|
| Source files (`.ts`/`.tsx`, excl. tests) | 463 (98 `.ts`, **365 `.tsx`**) |
| Source lines under `src/` | ~96,300 |
| Test files | 11 — **9 real**, 2 source greps |
| Test lines | 996 |
| Component render tests / snapshots / hook tests | **0 / 0 / 0** |
| File ratio | 11 / 474 = **2.3%** |

`Habibi/vitest.config.ts:19-24` sets `environment: "node"` with the comment *"Every suite here exercises a pure function. No jsdom, no DOM shims."* Verified against `package-lock.json`: `@testing-library/*` — **0 occurrences**; `jsdom`, `msw`, `playwright` appear only as vitest's own optional peer entries, none installed. **No component can be mounted in this repo without first changing the test infrastructure.**

Two files are not tests. `src/api/outbound.test.ts:1-24` and `src/routes/agent-studio.skills.index.test.ts:1-15` `readFileSync` their own source and assert substrings:

```ts
expect(src).not.toContain("window.prompt");
expect(src).toContain("clonePending");
```

They pass if the string sits in a comment, fail on a rename, and cannot fail when behaviour breaks while the identifier survives. Same defect as M1 on the backend side.

The nine real tests are genuinely good and document the bug each prevents — `src/api/contact-policy.test.ts:1-11` picks UTC instants so the *borrower's* local hour lands on the RBI boundary, *"because a test that says '19:00' in local time cannot distinguish the agent's clock from the borrower's"*. The codebase has a coherent strategy for the no-DOM constraint: extract the decision into a pure duck-typed function (`ContactabilityPill.test.ts:5-7` states it explicitly). That strategy is sound, and its limit is absolute — rendering, interaction, conditional visibility, disabled states and effect ordering are untested by construction.

**Consequence.** Every UI regression reaches a user first, in the console collections agents use to take compliance actions.

### H7 · A 345-line untested port of the Python money-authority matrix runs in the browser

`src/api/authority.ts:163-508` is a hand-written TypeScript re-implementation of the backend's goodwill/waiver engine. Its own header says so: *"A port of the Python authority matrix, not an approximation… `matrix.py :: decide()` — the ladder in its exact order, with all of its reason codes."* The rupee thresholds are in the bundle at `:216-220` — ₹500 late-fee cap, ₹250 mid-cap, ₹100,000 max outstanding, DPD 61, 6-month tenure.

**Zero tests cover any of it.** The contrast is internal to the codebase: `src/api/contact-policy.ts` is the same kind of port — the RBI contact veto — and it has 167 lines of boundary tests. **The team knows the pattern "port the policy, then pin the port." They applied it to the contact veto and not to the money matrix.**

Two adjacent untested pieces in the same subsystem: `authority-policy.ts:102 authorityStatusFor` ends `if (verdict) return "escalate"` — a fail-safe its docstring calls out as the property that stops *"a verdict this build does not recognise"* being rendered as an allowed move, and exactly the branch a refactor drops; and `authority-policy.ts:120 canApplyAuthority`, the client gate on the Apply-waiver button, including its double-apply guard.

**Calibration.** This is High rather than Critical because it is demo-path: `USE_MOCK` is `false` in the checked-in `.env`, and `src/api/config.ts:11-23` hard-errors on `VITE_USE_MOCK=true` in production builds. It is still 345 lines of unverified money policy rendered to operators in every demo and dev session, in a context where what was offered on a recorded call is evidence.

### H8 · The tested money formatter guards the less consequential number

Five competing INR formatters exist. Exactly one is tested — `inrCompact` (`billing-seed.ts:113-121`), with 87 lines of boundary tests — and it formats **token-billing** amounts.

`fmtOfferAmount` (`offer-policy.ts:62-65`) uses `Math.round` and is untested. It is re-exported as `fmtAuthorityAmount` (`authority-policy.ts:118`) and renders the **approved waiver and cap amounts** at `AuthorityPolicyBlock.tsx:40`, plus offer amounts at `OfferPolicyBlock.tsx:55`, `NeedsAttention.tsx:220` and `customerInsights.ts:227`.

The sharp point: `billing-seed.test.ts:6-7` records that flooring sub-rupee amounts to `"₹0"` was a **real shipped bug**. The identical `Math.round` defect is live and untested in the formatter that renders amounts owed and waived **to borrowers**.

### H9 · The whole network layer is untested, including three documented past bugs

`src/api/config.ts` is 317 lines, entirely pure or trivially fakeable, with zero tests — and testable *today* under the existing `environment: "node"` config with no new dependency. Its comments record the bugs it was written to fix:

- `:71-78 requestSignal` — `init?.signal ?? withTimeout()` once *"dropped the timeout entirely… so any request with a cancellation token could hang forever."*
- `:88-110 errorDetail` — reads the body once because `res.json()` then `res.text()` throws on a locked stream.
- `:127-146 isNotFound` — the docstring calls absence-vs-failure confusion *"the failure mode this codebase names as its #1"*.
- `:150-160 retryUnlessClientError` — the 408/429-vs-4xx policy, with a rationale about not resending settled verdicts.
- `:268-317 apiEventStream` — a hand-rolled SSE parser splitting on `"\n\n"` only; **it does not handle `\r\n\r\n` frame separators.**

This is the highest test-value-per-line target in the repository.

### H10 · Nothing validates that a backend response is the shape the frontend claims

`src/api/config.ts:170,175` is an unchecked cast — `JSON.parse(text) as T`. Every backend response enters the app through an assertion the compiler accepts on faith. `zod` is installed (`^3.24.2`) and used in exactly one place — a route search-param schema at `customers.$customerId.tsx:16` — validating **zero** API responses.

Behind that boundary sits a second implementation of the backend: **312 `USE_MOCK` branches across 41 of 44 files in `src/api/`**, 27 mock builders, and **14,604 lines of seed data** in `src/data/`.

Drift has already happened and was caught by hand: `billing-seed.test.ts:6-8` records that *"the backend printed '₹1.5 K' where this side printed '₹1.5k', and the backend floored every sub-rupee amount to '₹0'."* One formatter is now pinned. Nothing prevents the next one.

**Consequence.** A backend field rename compiles clean, passes `tsc --noEmit`, passes all 11 suites, passes CI, and surfaces as `undefined` — most likely a blank or `₹0` where a borrower's outstanding balance should be. This is the frontend half of H17's missing contract.

### H11 · Two suites each defer the contact gate to the other, and between them nobody tests it

This is the *mechanism* behind C1, and it is worth stating separately because the fix is different.

`tests/test_cadence_pause_and_strand.py:50-55` stubs the gate out for the entire 407-line file:

```python
@pytest.fixture(autouse=True)
def _contact_gate_allows(monkeypatch):
    """The gate has its own suite. Here it must not be the reason nothing dials."""
    monkeypatch.setattr(contact_policy, "admit",
                        lambda *a, **k: contact_policy.Decision(allowed=True))
```

That reasoning is correct in isolation — `cadence.py:445` is the real call site, and a retry-ladder test should not fail because of consent. But the gate's "own suite" then disables the very rules the ladder would hit: `test_contact_policy.py:56,66` sets `dnd = false`, `dnd_registry = false`, `allowed_days = NULL`, `allowed_hours = NULL`, `preferred_window = NULL` for every DB test in the file, and `:47-49` sets `CONTACT_COOLING_OFF_MINUTES=0` with a weekly cap of 8 against a daily cap of 3 — so the daily cap always trips first and the weekly one never can.

Each suite defers to the other. Between them, nothing proves the highest-volume outbound path respects the weekly cap, the cooling-off period, consent days, or channel-level DND.

**Consequence.** The gap in C1 is not an oversight in one file; it is produced by two individually-reasonable decisions meeting. Fixing C1 by adding tests to `test_contact_policy.py` alone will not close it — the setup that disables DND has to change too, and `test_cadence_pause_and_strand.py` needs at least one test that lets the real gate run.

### H12 · "DND" has three different definitions, and no test compares them

| Site | Definition |
|---|---|
| `contact_policy.py:504` (pre-dial veto) | `customers.dnd` **OR** `consent_records.dnd_registry` |
| `agent_core/compliance/context.py:113` (detector) | `COALESCE(c.dnd, FALSE)` **only** |
| `db.py:2313` (API/screen) | `dnd_registry OR customer_dnd` |

`load_context` (`context.py:120`) has **zero** references in the test suite.

**Consequence.** A borrower with `dnd_registry = true` and `customers.dnd = false` is blocked at dial time but, if a call reaches them by any other route, the retroactive `r-dnd-win` detector will not fire — so the breach is neither prevented nor recorded. This is the same "three copies drifted" defect that `lexicon.py:1-27` and `contact_window.py:1-21` were written to end, reintroduced one layer up.

### H13 · Three guardrail controls are enforced in production and detected by nothing in the suite

`agent_core/guardrails.py:159-161` (the tenant's prohibited-phrase list) and `:179-185` (`rate-quoted` — never quote an APR) have **no test that fires either detector**. What exists is only the flag→rule mapping:

```python
# test_guardrail_violations.py:56-61
assert persist.rule_for_flag("rate-quoted") == "r-false"
```

That maps a flag string nothing proves is ever produced. Separately, `max-turns` / `max-seconds` / `hard_max_turns` (`guardrails.py:221-229`, including `effective_max = min(ceiling, max_turns)`) have **zero** references anywhere in the suite.

**Consequence.** Break the prohibited-word regex or the APR regex and every guardrail test stays green. Break the turn ceiling and a call loops with nothing to catch it. Three assertions on `evaluate_guardrails` output would close all of it.

### H14 · The weekly cap is not concurrency-safe in the product, and neither cap is tested under contention

`contact_policy.py:816-852` (`_reserve_day`) takes `FOR UPDATE` on `contact_day_counters` so two dials cannot both take slot 3 — the module docstring makes this its headline safety claim (`:16-18`).

But in `admit()`, the **cooling-off check (`:972`), the weekly-cap check (`:976`) and session coalescing (`:965`) are plain unlocked SELECTs taken *before* that lock** (`:971-979`). Two concurrent outreach admissions can both pass the weekly cap and both proceed.

No test in `test_contact_policy.py` uses threads; `test_fourth_outreach_denied` (`:121`) loops four times on one connection.

**Consequence.** The daily cap holds under concurrency and is untested. The weekly cap does not hold under concurrency and is also untested — so this is a product defect that the test strategy has no way of surfacing. It is the one finding in this report where the missing test would fail today.

### H15 · No test asserts transactional atomicity of any business operation

`test_escalate_txn.py:31` is named `test_escalate_voice_interaction_one_txn` and asserts that a handoff, a conversation and an alert all exist after success (`:67-81`). It never fails the second or third write, so **it does not test the property its name claims.** `db.escalate_voice_interaction` writes at least four rows across three tables; a failure on the third leaves the first two behind and nothing would catch it.

The suite's only genuine partial-write check is `test_payment_events.py:430-448` — count before, `pytest.raises(ValueError)`, count after. One instance, and a good one.

This matters more here than in most codebases because of a known property of the shared fixture: one bad column name aborts the transaction and cascades failures across tests, so atomicity bugs are easy to misread as unrelated noise.

### H16 · The dispute SLA rule is implemented twice, tested twice, and compared never

`Habibi/src/data/dispute-sla.test.ts:1-3` states the problem outright: *"mockDisputeSla mirrors backend/db.py::_dispute_sla line for line, and the two have to agree."*

They do not. The backend suite uses a 48-hour window (`test_dispute_sla.py:36-85`); the frontend uses 40. Both suites pass. Nothing compares them.

This re-creates client-side the exact two-screens-disagree defect that `test_dispute_sla.py`'s own docstring says the shared contract was written to end.

### H17 · No response shape is pinned anywhere

No test in 188 files calls `app.openapi()`. Zero `.keys()` assertions. The five tests named "contract" pin something else:

| Test | What it actually pins |
|---|---|
| `test_agent_card_schema_drift.py:57-69` | Pydantic vs TS field sets — for `AgentCard`, a **config** model, never a `response_model`; skips if the frontend file is absent |
| `test_schema_parity.py:188` | DB-vs-DB column diff; **inert unless** `SCHEMA_PARITY_DATABASE_URL` is set |
| `test_inbox_channel_contract.py:56-76` | literal values of two fields against a SQL `CHECK` |
| `test_place_contract.py:206` | an internal dict from `outbound.place()`; no HTTP |
| `test_reco_contracts.py:145-149` | only the **intersection** of two dicts — cannot fail on a rename |
| `test_sandbox_turn_schema.py:116` | the handler is monkeypatched at `:81`; the assertion checks a value the test supplied |

Renameable today with zero failures: `CustomerResponse.assignedTo` and `.lastContact` (`schemas.py:160-161`, served by `GET /customers`), `NbaItemResponse.treatmentAction` (`customer_insights.py:226`).

No consumer-driven contract exists: no generated types in `Habibi`, no `openapi-typescript`/`orval`, and all 48 modules in `src/api/` carry hand-written interfaces.

### H18 · No test drives a voice turn through more than one processor

`backend/voice/bot.py` builds the pipeline inline inside a ~2,000-line entrypoint — stage list at `:1295-1327`, consumed at `:1328 pipeline = Pipeline(pipeline_stages)`. There is no `build_pipeline()` factory, and STT/TTS/LLM are constructed in place with real services (`:634`, `:650`, `:679`), so nothing between the signature and line 1328 is reachable without a live transport, database and Azure credentials.

The closest artefact is `test_voice_ivr_host.py:158` — a one-element pipeline of the bare `FrameProcessor` base class, with no frame ever queued. The pieces exist and are never joined: transcription→speculation, LLM→probe, tool→DB write, TTS settings all have tests; nothing links stage *n*'s output to stage *n+1*'s input.

Tellingly, `run_bot` is asserted against by parsing its own source: `test_voice_session_teardown.py:147,229,265,348,362` uses `ast.parse(inspect.getsource(bot.run_bot))`, as do `test_voice_flow_required.py:113,130` and `test_voice_crm_degraded.py:94`. That is an explicit admission that the entrypoint cannot be executed under test.

`test_understanding_voice_path.py` is not a voice-path test despite the name — its docstring says it asserts queue discipline in `CrmSink`.

### H19 · The only full-turn harness is in no CI and covers 6 of its own 15 scenarios

`backend/voice/evals/suite.yaml:13` spawns the real bot process and drives authored scenarios with tool-call and LLM-judge assertions — `promise_to_pay_happy.yaml` asserts `event: function_call, name: create_promise_to_pay`. It is the only artefact in the product that covers a complete turn.

It runs only via `scripts/run_voice_evals.py`, which needs the `pipecat eval` CLI and live Azure credentials. Neither workflow invokes it. **Only 6 of 15 scenarios are in the manifest** (`suite.yaml:20-25`) — the nine excluded include `upsell_blocked_by_dnd.yaml`, `no_unprompted_balance.yaml` and `goal_before_verify.yaml`.

`run_voice_evals.py:94 dry_validate` exists specifically so "CI still catches a malformed scenario without needing Azure credentials" (`:7-9`). **Nothing calls it.**

### H20 · `bot_runtime.py:159-161` fails open on the WhatsApp consent gate

The gate wraps `contact_policy.admit` in `except Exception: logger.exception(...)` and falls through to `return None` — allowed. This contradicts `contact_policy.evaluate`'s own fail-closed `REASON_UNREADABLE` path (`contact_policy.py:597-601`). No test covers the exception branch.

**Consequence.** A database blip lets the bot reply to a borrower it should be refusing. The fail-closed decision was made deliberately in one module and silently reversed in another.

---

## Findings — Medium

**M1 · Source-text assertions substitute for execution, on both sides of the stack.** `test_outbound_studio_bindings.py:110`, `test_outbound_card_switches.py:210`, the five `ast.parse(inspect.getsource(...))` sites in the voice tests, and on the frontend `Habibi/src/api/outbound.test.ts:9-13` (`readFileSync(...).toContain("botId?: string")`). These pass on a renamed variable and fail on a harmless reformat — the inverse of what a test should do — and they look like coverage in any file count.

**M2 · 33 files build their own borrower; 33 their own account; 20 both.** `conftest.py` is 171 lines and ships 5 fixtures, none producing domain data. Consequence: **531 raw `text(...)` SQL literals across 70 files** and **152 `INSERT INTO` statements across 45 files** covering 67 tables. `_a_customer` and `_customer` are the same query — `SELECT id, account_id FROM customers WHERE id <> 'UNKNOWN-CALLER' ORDER BY id LIMIT 1` — written 11 times, each with its own skip branch. Renaming a `customers` column costs ~28 file edits.

**M3 · The Alembic upgrade/downgrade roundtrip runs nowhere.** `test_migrations.py:50` skips unless `RUN_ALEMBIC_ROUNDTRIP` is truthy; CI sets it to `"0"` (`backend-pytest.yml:197`). The body skips again without `TEST_DATABASE_URL`. Both guards are well-reasoned — the test replays a destructive downgrade — but migration reversibility is asserted by no automated run, on a platform whose migrations touch `consent_records`, `contact_events` and `audit_log`.

**M4 · `/ready` leaks a raw exception string, and both its tests stub the leaking branch.** `storage.py:157` returns `{"ok": False, "detail": str(exc)}`; `main.py:775` folds it into the 503 body. `/ready` is unauthenticated. Both tests in `test_ready.py` monkeypatch `storage.ping` to a green literal (`:129-131`, `:161-163`), so the exception branch never executes. (Carried from report 20 H2; recorded here because the *test* is what allows it to persist.)

**M5 · One missing dependency is handled two ways.** `pipecat` is guarded by `importorskip` in 8 files (103 tests skip cleanly) and imported bare at module top in 5 files / 48 tests, which produces a collection error. Given CI installs it, the hard-error five are correct and the eight guards are the ones to remove.

**M6 · 69 monkeypatches of private module internals across 40 files.** `_IS_PROD` twice (`test_auth_cors_middleware.py:223`, `test_production_hardening.py:518`); beyond it `cache._CACHE_DIR`, `pool_mod._POOLS`, `enact._HANDLERS` and `bot_mod._bot_session` are the worst, because each is *the* seam for its module and there is no public one. Renaming any breaks tests with an `AttributeError` at patch time, naming the wrong thing.

**M7 · Input validation is spot-checked.** Four `422` assertions and four `404`s in the entire suite. Zero tests for oversized payloads, wrong scalar types on money fields, or missing required fields on any of the 158 mutating routes. `test_sandbox_turn_schema.py:218` checks the frontend's POST keys are a *subset* of the model — one-directional, so a field the studio stopped sending is invisible.

**M8 · `POST /a2a` is unauthenticated at the route level and untested at the route level.** `main.py:278` bypasses the API-key gate unconditionally. Its defence, `a2a_mod.require_partner`, has a function-level test (`test_phase5.py:137`) but no HTTP test, so nothing proves the route calls it.

**M9 · Two module globals are mutated and never restored.** `test_auth_cors_middleware.py:250,257` assign `azure_openai._azure_sem = None` outside any fixture. `test_voice_session_teardown.py:92` writes `os.environ[...]` directly. Two outliers against 316 correct `monkeypatch.setenv` calls — noted as leaks, not as a convention.

**M10 · `test_turn_enrichment_overlap.py` caches a wall-clock measurement in a module global.** `:207 global _MEASURED`; six tests assert against one memoised timing run built from 1.1 s of real sleep per turn. The one test group that cannot be run in isolation and mean the same thing, and the one most likely to flake on a loaded runner.

**M11 · `db_tx` silently disables the tenant GUC, so tests that look like RLS coverage are not.** `db.py:153` installs `@event.listens_for(engine, "begin")` to issue `SET LOCAL app.tenant_id`. `begin_nested()` fires SQLAlchemy's *savepoint* event, not *begin* — so inside `db_tx` that hook never runs. Tests combining `db_tx` with `tenant_context.bind()` (`test_connector_governance.py:265,306`, `test_connector_read_hygiene.py:145`) exercise only the Python-side `_tenant()` predicate; the GUC that RLS actually reads is never set. The transport itself is covered correctly by `test_tenant_context.py:78-110`, which deliberately does *not* use `db_tx` — so the seam is known, and the risk is that a future test assumes the fixture provides it.

**M12 · Pool exhaustion is tested by stubbing the reporter.** `test_ready.py:16-47` monkeypatches `db.pool_snapshot` to return `available: 0` and asserts `/ready` returns 503 — a test of the handler's arithmetic. No test checks out `pool_size + max_overflow` connections and observes an in-flight request when `QueuePool` times out. Relatedly, `pool_pre_ping` (`db.py:140`) and the statement timeout (`db.py:146`) are unverified, because every DB-unavailable test mocks at the SQLAlchemy boundary rather than severing a connection.

**M13 · RLS is well tested and never asserted to be *on*.** `test_rls.py` is the strongest file in the suite — the derivation half creates ~112 real policies against the real schema (`:82-101`), checks orphan rows (`:129`), alias collisions (`:174`), and refuses to enable when the role bypasses RLS (`:187`); the enforcement half (`:200-384`) builds a two-tenant scratch database with a non-superuser probe role and verifies read isolation, `WITH CHECK` write rejection and unknown-tenant blindness. But `rls.apply`/`rls.enable` are called only from `scripts/rls.py:140,158`, an ops script. No test asserts a deployed database has policies enforcing, and the app connects as a superuser. In practice tenant isolation rests on the SQL predicates of `test_cross_tenant_reads.py`, not on RLS.

**M14 · Eval suites are not journey tests, and should not be counted as any.** `agent_core/eval/harness.py:1` says so: *"Run a suite's tasks against fixtures. **No LLM on this path.**"* The graders are pure functions over hand-authored dicts. `test_eval_suites.py` is a regression test for the *graders*, not for the rules they describe. Two credits: `:69-76` is a real anti-vacuity ratchet (*"A task graded against `{}` is a task that cannot fail"*), and `:49-66` requires each grader to have a proven violating shape, because eight of nine open with a "not applicable" guard returning `passed: True` on an empty fixture. Someone understood the failure mode.

**M15 · Incident-driven regression tests are the healthiest habit here and have no mechanism behind them.** Three exist — `test_call_vs92cde3f088_regressions.py` (329 lines, pins one sandbox call: triple recording disclosure, 24 s of dead air, duplicated balance readout), `test_call_vs9bc3dd9725_regressions.py` (167 lines, four complaints from one trigger), and `test_conversation_trace_regressions.py` (335 lines, one WhatsApp thread). Two naming conventions already, no index, no tooling that turns an incident into a test. It depends entirely on someone choosing to do it again.

---

## Findings — Low

**L1 · 179 weak assertions**: 147 `is not None`, 32 `== 200`. Thirteen tests assert nothing stronger. `test_call_vs9bc3dd9725_regressions.py:23 test_an_outbound_call_after_hours_is_still_a_breach` asserts only `check_hours(...) is not None` — true for a breach *or* any non-`None` return — on a compliance path. (Several of the 32 `== 200`s are correctly minimal: in `test_authz.py:306,316,321` a 200 *is* the whole claim.)

**L2 · The 22 zero-assertion tests are almost all legitimate**, and are reported only because the raw number looks alarming. Every one read either delegates to an assert-bearing helper (`authz.assert_registry_covers` at `test_authz.py:40`, `db._assert_tenant_owns` at `test_cross_tenant_reads.py:215`) or is an explicit "must not raise" test. My own first scan mis-flagged these; see corrections.

**L3 · Four files are named for project history, not domain**: `test_phase4/5/6.py` and `test_decision_intelligence_p0–p3.py` (853–1,070 lines each). `test_phase4.py` mixes WhatsApp bounce handling, PTP re-entry and QA rubric selection. A reader cannot find a test by what it tests.

**L4 · Three tests swallow the exception they exist to observe** — `except: pass` inside the body at `test_production_hardening.py:508`, `test_turn_critic.py:313`, `test_voice_session_teardown.py:120`.

**L5 · One docstring claims more than the body checks.** `test_treatment_followthrough.py:618 test_closing_never_costs_the_payment` says "a payment must record even if the cleanup does not"; the body asserts only that no exception escaped.

**L6 · `PRAXIST-main/` is 4,518 tracked files of a vendored third-party project with its own test suite that runs in no CI** — root workflows filter `backend/**` and `Habibi/**`, and `PRAXIST-main/.github/` is ignored by Actions. It inflates any repo-wide test count and contributes nothing to this product.

**L7 · CI path filters mean some changes run nothing.** A commit touching only `docs/`, `tools/`, root scripts or `demo/` triggers neither workflow.

---

## Risk coverage by business capability

Ordered by regulatory exposure, not by test count. "Behaviour" means a test drives the production entry point and asserts the outcome.

| Capability | Tests exist | Rule verified as behaviour | Evidence | Residual risk |
|---|---|---|---|---|
| **Opt-out capture → cross-channel suppression** | fragments | **no** | `db.opt_out` called by no test; enforcement tested against SQL fakes | **Critical** — C2 |
| **DND / consent expiry / cooling-off / weekly cap** | membership only | **no** | `contact_policy.py:299,301,505,594` unreached | **Critical** — C1 |
| **Suppression after payment** | recording only | **no (not implemented)** | no paid reason in `contact_policy.py:42-56` | **Critical** — C3 |
| **Campaign eligibility gate** | source-text only | **no** | `test_outbound_studio_bindings.py:110` | **Critical** — C4 |
| **Payment capture via hosted link** | none | **no** | `main.py:795` untouched | **Critical** — C5 |
| Webhook authenticity (PSP, Twilio, Meta) | unit only | **no** | route-level untested; `test_production_hardening.py:41-45` asserts reachability | High — H4 |
| Route authorization | strong design, thin verification | 5 of 314 | `test_authz.py:297-435` | High — H5 |
| Tenant isolation / RLS | good Python-layer, no HTTP | partial, CI-only | `test_rls.py:305-342`, gated | High — H2 |
| Voice turn (regulated channel) | per-processor only | **no** | `bot.py:1328` unfactored | High — H18/H19 |
| Frontend behaviour (365 components) | 9 real pure-function suites | **no** | `vitest.config.ts:24` `environment: "node"` | High — H6 |
| Waiver/goodwill authority shown to operators (client port) | none | **no** | `src/api/authority.ts:163-508` | High — H7 (demo-path) |
| Money rendering to borrowers | tested formatter is the wrong one | **no** | `offer-policy.ts:62-65` untested | High — H8 |
| API response shape (frontend side) | none | **no** | `config.ts:170,175` unchecked cast | High — H10 |
| Daily cap / calling hours / channel opt-out | yes | **yes** | `test_contact_policy.py:129,176,211` | Low |
| Promise → fulfilment → broken → follow-up | yes | **yes** (best journey in the repo) | `test_voice_write_idempotency.py:16-19`, `test_promise_fulfillment.py:147-231` | Low |
| Outbound attempt ledger | yes | **yes** | `test_outbound_attempts.py:105-638` on real Postgres | Low |
| Identity verification before disclosure | yes | **yes** at three layers | `test_call_context.py:177-183`, `test_live_qa_engine.py:65` | Low–Medium (inbound leg never driven) |
| Authority / waiver limits | yes | **yes** | `test_authority_engine.py:89-184`, 10 distinct refusals asserted | Low |
| Schema drift (`sql/` vs Alembic) | yes | **partial — 38% of tables, 57% of columns** | `backend-pytest.yml:110-160` scrapes `op.*` only | Medium — C9 |
| Migration reversibility | exists | **no — runs nowhere** | `RUN_ALEMBIC_ROUNDTRIP=0` | Medium — M3 |
| **Concurrency — 16 job-claim queues** | 15 sequential, 1 real | **1 of 16** | `test_job_claim.py:113-370` | **Critical — C8** |
| **Idempotency under contention** | 26 sequential assertions | **no** | advisory lock `db.py:702-707` unreachable under `db_tx` | **Critical — C8** |
| **Compliance detectors (human handoff calls)** | unit-tested, prod-dead | **no** | `scan.py:59-69` vs 12 seeded ids | **Critical — C6** |
| Weekly cap under concurrency | none | **no — and unsafe in product** | `contact_policy.py:971-979` unlocked | High — H14 |
| Transactional atomicity | one instance | **essentially no** | `test_escalate_txn.py:31` names it without testing it | High — H15 |
| Prohibited language / APR quote / turn ceiling | flag→rule mapping only | **no** | `guardrails.py:159-161,179-185,221-229` | High — H13 |
| Schema parity (`sql/` ↔ migrations) | exists | **vacuous in CI** | both sides derive from `sql/*.sql` | Critical — C9 |

---

## What is done well

This is a better-engineered suite than its gaps suggest, and several practices should be protected rather than reformed:

- **The test names are the best documentation in the repository.** Mean 6.9 words; 31% carry an explicit behavioural verb; only ~1% read as mechanism. `test_an_opt_out_stops_the_ladder_immediately`, `test_inbound_calls_are_not_judged_for_mini_miranda`, `test_a_policy_that_wants_untried_actions_is_flagged_not_scored`. 52% have docstrings, and those docstrings routinely record the incident that caused the test.
- **`conftest.py` already diagnoses the vacuity failure mode — twice.** `:146` `assert packs, "... these tests would go vacuous"`; `:136-137` "without it, an environment that resolved nothing would still go green"; `:154-165` records modules that looked green locally and 401'd on CI's first run. **The pattern is understood. It is simply not applied at the seed level** — which is why H1's fix is one test, not a programme.
- **The CI schema-drift check (`backend-pytest.yml:110-160`) has the right design** — deriving expectations from the migrations themselves rather than a hand-kept list, with a comment recording that `idempotency_keys` was caught this way ("every idempotent write silently duplicated"). Its *reach* is the problem, not its idea; see C9.
- **The workflow comments are engineering documents.** The reasons for installing voice deps, for stamping rather than upgrading Alembic, and for not setting `--max-warnings 0` ("a gate introduced red is a gate people learn to ignore") are all recorded at the point of decision.
- **`test_eval_suites.py:69-76`** — the ratchet forbidding a task graded against `{}`.
- **`test_place_contract.py`** — a contract suite written specifically to make `outbound.place`'s "never raises" promise true, *because* `campaigns.process_one` calls it undefended. This is the model the other seams should follow.
- **`db_tx` (`conftest.py:11-65`)** — nested savepoints, rollback at teardown, no leftover rows.
- **One mocking convention**: 713 `monkeypatch` calls across 100 files against a single `unittest.mock` import. Zero `assert True`, zero `pass`-bodied tests, zero cross-test imports, zero `xfail`.
- **Zero `async def test_`** with 105 explicit `asyncio.run()` sites — deliberate, since `requirements.txt` pins no `pytest-asyncio` and a single `async def test_` would have been collected, never awaited, and silently passed.
- **The `_treatment_is_deterministic_unless_a_test_says_otherwise` fixture (`conftest.py:81-122`)** — 40 lines of rationale for pinning stochastic dials, written after exploration broke eleven tests "none of them wrong".
- **Frontend type discipline is excellent, and the usual "weak types plus no tests" compounding does not apply here.** `tsconfig.json:16-24` has `strict: true`, `noFallthroughCasesInSwitch` and `noUncheckedSideEffectImports`. Across ~96,300 lines there is **one** hand-written `as any` (`useSandboxLiveCall.ts:262`) and **zero** `@ts-ignore` — the 33 other `as any` occurrences are all in the generated `routeTree.gen.ts`. That is a rare result and it should be said plainly rather than talked around. What types cannot express is exactly the residue in H7–H10: that `Math.round` must not flatten ₹0.40 to ₹0, that `else escalate` must stay last, that `toISOString()` is the wrong clock for IST.
- **No access control is decided in the frontend, which is the right answer.** `src/api/me.ts:15-22` carries no `role` field and no permission list — there is nothing to gate on. The only `beforeLoad` in the route tree (`prompt-studio.tsx:13-21`) is a search-param redirect, not an auth check. `routes/roles.tsx` is an editor for server-side grants, not an enforcement point. The one client gate over a money action (`canApplyAuthority` → the Apply-waiver button) sits over a server-enforced rule, so bypassing it does not bypass the control — the correct shape, even though the gate itself is untested.
- **The frontend tests, where they exist, document the bug they prevent** — the same habit as the backend docstrings, and the reason several findings in this report could be stated so precisely.
- **`test_job_claim.py:113-370` is a model concurrency test** — two threads racing a real `SKIP LOCKED` claim, barrier-synchronised, with three-way forensics to distinguish a genuine defect from a live worker stealing the row. Together with `test_voice_session_store_contention.py` it proves the team knows exactly how to test contention; C8 is about reach, not capability.
- **`test_cross_tenant_reads.py:137` is a reflection test that fails when a new `list_*` accessor is added without cross-tenant coverage** — a coverage ratchet rather than a fixed list. The right shape, and the one that should be copied to the refusal reasons and the route table.
- **`test_tool_audit_is_redacted.py:69-127`** parameterises over all four executors and asserts card numbers are masked in arguments *and* in the result preview, with identity args withheld.
- **`test_outbound_attempts.py:105-297`** is strong real-DB coverage: an unplaced dial still leaves a row, a refusal leaves a row, out-of-order and repeated carrier callbacks stay monotonic (`:181,194`), and the borrower's number is not re-stored (`:128`).
- **`test_payment_events.py:394-398`** documents the frozen-`now()` hazard precisely — that `record_payment` compares intent expiry against the *Python* clock while the transaction clock is frozen, and that a hard-coded date "passed for a week and then failed forever". Four such comments are why the mixed-clock hazard is currently contained.
- **`test_place_contract.py:220-249`** asserts that when the state write fails *after* the carrier already dialled, the result reports `placed: False, reason: "state_write_failed"` and does not pretend the carrier was never called. Failure-path testing of a quality this report found rarely.

---

## Remediation

### Immediate — the compliance gaps

1. **`test_the_seed_is_not_empty`** — assert row counts in `customers`, `accounts`, `interactions`, `products`, `leads`. Converts 284 silent skips into one loud failure. Highest value per line in this report.
2. **Test the seven unreached refusal branches** in `contact_policy.evaluate`: DND borrower, expired consent, cooling-off window, weekly cap, unreadable consent, disallowed window, channel DND. Assert the reason emitted, not the constant's membership.
3. **Call `db.opt_out` in a test**, then assert `contact_policy.admit` refuses on the opted-out channel. Closes the capture↔enforcement seam.
4. **Decide and then test the cross-channel opt-out model.** `post_call_actions.py:290` defaults `record_optout` to `channel="voice"`, so a borrower saying "stop contacting me" on a call is not suppressed on WhatsApp. Today `test_contact_policy.py:221` asserts the opposite of suppression (`assert sms.allowed` after a WhatsApp opt-out). If channel-scoped is intended, that needs a comment and a compliance sign-off, not silence.
5. **Wire payment state into `cadence.process_one` and `campaigns.process_one`**, add a paid/settled refusal reason, and test it. C3 is a missing feature before it is a missing test.

6. **Fix `test_contact_policy.py:289`** to a relative date. One line, and it restores the meaning of a red run.
7. **Cross-check `DETECTORS` against the seeded `compliance_rules` catalog** instead of counting the dict, and resolve the four orphaned checklist rules either way.

### Near-term — the structural holes

8. Pin `PUBLIC_ROUTES` and `_AUTH_EXEMPT_PREFIXES` as exact sets; add a test asserting the two agree.
9. One HTTP test per webhook: unsigned body → 401. Fix `test_production_hardening.py:41-45`, which currently asserts the wrong thing.
10. Negative-auth tests for the mutating routes named in H5, starting with `PATCH /roles/{role_id}/permissions`.
11. Execute `campaigns.process_one` in a test; delete the `inspect.getsource` assertion.
12. Add `dry_validate` to CI, and put the nine orphaned voice-eval scenarios into `suite.yaml`.
13. Fix `bot_runtime.py:159-161` to fail closed, and test the exception branch.
14. Give the dispute SLA one implementation, or a test that compares the two.
15. Make `RUN_ALEMBIC_ROUNDTRIP` a nightly job rather than a flag nobody sets.

### Structural

16. **Give `db_tx` a sibling fixture that uses real connections and real commits**, so contention can be tested at all. `test_job_claim.py:38-50` and `test_voice_session_store_contention.py` already do this by hand; the pattern needs to be shared rather than re-derived. Then add contention tests to the dial queue, the reminder sender and the idempotency lock — the three whose failure contacts a borrower twice.

17. **Close the weekly-cap race in `contact_policy.admit`** by moving the cooling-off and weekly checks inside the `_reserve_day` lock, and add the contention test that would have caught it. This is the one finding here that is a product defect rather than a testing gap.

18. **Extend the CI schema check to parse raw DDL**, not just `op.create_table`/`op.add_column` — 41 tables and 54 columns are currently invisible to it. And point `test_schema_parity.py`'s "migrated" side at a database built by `alembic upgrade head`, or the comparison is against itself.


19. **Extract `build_pipeline()` from `bot.py:1295-1328`.** The single change that makes the voice runtime testable; it unlocks the whole missing tier and lets the five `inspect.getsource` tests be deleted rather than maintained.
20. Move `_a_customer`/`_customer`/`_require_table` into `conftest.py` as fixtures that fail loudly rather than skip. Removes 11 duplicate definitions and ~28 edit sites per schema change.
21. **Test `src/api/config.ts` and `src/lib/authority-policy.ts` first.** Both are pure, both run under the existing `environment: "node"` config with no new dependency, and between them they hold three documented past bugs and the waiver-apply gate. This is the cheapest real coverage available anywhere in this report — roughly 450 lines of target.
22. Pin the authority port (`src/api/authority.ts:163-508`) the way `contact-policy.ts` is already pinned. The pattern exists in the same directory.
23. Replace the two source-grep suites (`api/outbound.test.ts`, `routes/agent-studio.skills.index.test.ts`) with real assertions or delete them; they inflate the count and verify nothing.
24. Validate API responses at the boundary with the `zod` already installed, starting with the money-bearing shapes. `config.ts:170,175` is the single seam where the whole frontend trusts an unchecked cast.
25. Add a DOM environment and component tests for the role-gated and money-rendering paths, or state explicitly that the console is verified by hand.
26. Generate frontend API types from the OpenAPI schema; today all 48 modules in `src/api/` hand-write interfaces that drift silently, and drift has already happened once.
27. Adopt one convention for the `pipecat` guard — prefer the bare import, since CI installs it.
28. Give the incident-regression practice a naming convention and an index. It is the healthiest habit in the repo and currently depends on memory.

### One item for a different report

There is **no login flow in the frontend at all** (`src/api/me.ts:7` defers OIDC to "Phase 5"). `/roles` is reachable by anyone who can load the bundle, and toggling a permission fires a real `PATCH /roles/{id}/permissions`. Whether that is a privilege-escalation surface depends entirely on server-side enforcement — and per H5 that route has **no negative-authorization test**, so this audit cannot answer it either. It belongs to the authentication review, flagged here because the testing gap is what leaves the question open.

---

## Analyst disagreements, resolved

- **Frontend test count: 4 vs 11.** The API analyst reported 4 vitest files, the E2E analyst 11. **Eleven is correct** — `git ls-files` returns 11, and the CI comment at `frontend-typecheck.yml:65` independently says "11 vitest suites / 107 assertions". The API analyst appears to have searched only `src/api/`.
- **`_AUTH_EXEMPT_PREFIXES` untested vs spot-checked.** My brief to the analysts asserted it was untested; the API analyst corrected this and cited `test_production_hardening.py:21`. The correction is right, and H3 states the weaker true claim (membership spot-check, not an equality pin).
- **Skip severity.** The maintainability analyst rated the 436 skippable tests as Critical; the API analyst rated the same phenomenon Low. Both are carried: the mechanism is Critical (H1), while the *present-day* CI exposure is low because the workflow seeds the database. The finding is written around what is unguarded, not around what is currently broken.
- **Frontend suite size: 11 files or 9?** Both are true and the report uses both. Eleven files match `*.test.ts`; two of them (`api/outbound.test.ts`, `routes/agent-studio.skills.index.test.ts`) are `readFileSync` + substring assertions and verify nothing, so nine is the number that means anything. Stated as "11 — 9 real" rather than picking one.
- **What `PRAXIST-main/` is.** The E2E analyst read it as a vendored third-party project with a large test suite; the frontend analyst determined it contains zero `.tsx`/`.jsx`/`package.json` and is a Python package. Both conclusions agree on the only thing that matters — it is out of scope, runs in no CI, and inflates any repo-wide count. Recorded as L6 on that basis.
- **Severity of the untested authority port.** The frontend analyst rated `src/api/authority.ts` Critical. Downgraded to High (H7) here because `USE_MOCK` is `false` in the checked-in `.env` and `config.ts:11-23` hard-errors on it in production builds, so it is demo-path rather than the shipped decision path. The analyst noted that mitigation itself; the disagreement is only about weighting it.
- **Test-function count.** My AST scan and the maintainability analyst's independently produced 2,431 functions / 46,811 test LOC / 116 skip sites / 22 zero-assertion tests. No reconciliation needed — reported as corroborated.

## Corrections made during verification

- **My first scan reported "22 tests with zero assertions" as a defect.** It was wrong. Reading them showed nearly all delegate to an assert-bearing helper (`authz.assert_registry_covers`) or are deliberate "must not raise" tests, which is a legitimate form. Reclassified to L2 and explicitly labelled *not* a finding against the suite.
- **My first reading of the 116 skips assumed they were infrastructure-conditioned** and therefore vacuous in CI. Reading `backend-pytest.yml` refuted this — CI seeds the database, installs voice deps and creates both scratch databases. The finding was rewritten from "the suite skips its integration tests" to the narrower and true "nothing asserts the seed has content".
- **I initially recorded eight refusal reasons as "never asserted" based on string-literal search.** Checking for the constants showed they *are* referenced — in membership sets. The claim was narrowed from "never asserted" to "never asserted as behaviour", which is weaker, harder to dismiss, and what C1 now says.
- **I praised the CI schema-drift check in this report's own "done well" section before measuring its reach.** The integration analyst then showed it scrapes `op.create_table`/`op.add_column` only. I verified: 25 `op.create_table` against **41 raw `CREATE TABLE`**, and 71 `op.add_column` against **54 raw `ALTER TABLE … ADD COLUMN`**, across 102 migration files. The praise was rewritten to commend the design and state the coverage (C9). The check is still a good idea — it is just doing 38% of the job it appears to do.
- **My draft treated `test_schema_parity.py` as live coverage.** It is inert in CI: both sides of the comparison derive from `sql/*.sql`, because CI applies `sql/*.sql` and then `alembic stamp head` rather than running migrations. Recorded as C9 rather than left in the strengths list.
- The API analyst reported its own Grep tool returning silently incomplete results twice, and re-derived its numbers with backgrounded shell `grep`; it flagged that this nearly produced a false finding. Its final numbers are the re-derived ones.

## What could not be verified

- **Whether any of this passes.** No tests were run — the instruction was a static audit, and running pytest against a live corpus simulator produces failures that are not real. Every coverage claim is static: a cited test may currently be skipping or failing.
- **The runtime skip count.** 436 is a static upper bound on silent loss. Only `pytest -rs` in the CI environment gives the real number, and that is the single measurement that would most sharpen H1.
- **Whether `scripts/seed_demo.py` populates every table the 284 guards probe.** I read its entry point but did not run it. That uncertainty *is* H1 — the suite should not depend on anyone answering this by hand.
- **Whether either workflow is a required check.** Workflow files are readable; branch-protection settings are not.
- **Whether `voice/evals/` has ever been run.** `runs_dir: .cache/eval-runs` is gitignored and no result exists in the tree.
- **C6's production claim rests on static reading, not a query.** I verified that `_SCREEN_RULES` seeds eleven ids, `20260814_0071` adds `r-third`, and `_LEGACY_RULE_MAP` retires the four checklist ids — and found no other INSERT into `compliance_rules` anywhere in `backend/**/*.py`. I did not query a live database (instructed not to run migrations; the corpus simulator may hold locks). If some path outside `alembic/` and `seed_postgres.py` inserts them, C6 weakens from "dead in production" to "no test enforces that they are alive" — which is still a finding, and still the same fix.
- **C7 is derived from reading the guard against the calendar**, not from a test run. The mechanism is unambiguous (`domain.py:724-725` vs a `2026-09-01` literal) but I did not execute it.
- **Whether `test_schema_parity` is *entirely* vacuous in CI.** The structural claim — that the "migrated" side was never migrated — holds regardless. But `scripts/seed_demo.py` runs against `DATABASE_URL` before pytest, and I did not read it for DDL that might make the two sides diverge incidentally.
- **Whether the 16 `SKIP LOCKED` paths are individually unsafe.** C8 enumerates the claim sites and shows only one has a contention test. It is a coverage claim, not an assertion that each queue races — establishing that would need execution.
- **Line coverage.** No coverage tooling is configured for the backend, so all reachability claims here are call-graph-based, not line-based. Adding `pytest-cov` to CI would turn several "no test reaches this" claims from argued to measured — and is worth doing for that reason alone.
