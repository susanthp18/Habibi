# MASTER BACKLOG

**Date:** 2026-09-03
**Mode:** Read-only. **No work package below has been started.** This document proposes no code.
**Companions:** [MASTER-AUDIT.md](./MASTER-AUDIT.md) · [CONFLICTS-AND-FALSE-POSITIVES.md](./CONFLICTS-AND-FALSE-POSITIVES.md) · [TARGET-ARCHITECTURE.md](./TARGET-ARCHITECTURE.md) · [REFACTORING-STATE.md](./REFACTORING-STATE.md)

---

## How this backlog is ordered

The brief's default order is correctness → security → data integrity → architectural blockers → duplication → canonicalization → dead code → reliability → testing → performance → maintainability → cosmetic, **with repository evidence permitted to override it.** Evidence overrides it in three places, and each override is stated where it occurs:

1. **WP-001 comes before everything, including correctness fixes.** `git tag` returns zero, images are `:local`, and there is no registry and no backup procedure. **"Roll it back" is not currently an executable instruction**, so no other work package has a meaningful rollback strategy until this one lands.
2. **The regulated one-liners (WP-004…WP-010) come before the test baseline**, inverting the usual "make the ground safe first" rule. Each changes behaviour **only on a path that is already wrong**, each is under fifteen lines, and each closes a live regulatory hole. Waiting ~13 developer-days for a green suite to fix a one-line fail-open is a worse trade than shipping it with a targeted test.
3. **Dead-code removal is demoted for the backend and promoted for the frontend.** Verified: deleting dead code does **not** pre-pay for the backend canonicalization — every live Tool Grant formula sits in a reachable module. It pre-pays substantially for the frontend, where 22 dead `components/ui/*` files are in the remediation scope of three other reports.

**"Atomic" means a partial application is worse than none.** The classic case: deleting N−1 of N duplicate rule copies leaves the divergence *and* removes the evidence of it.

**Severity** is regulatory exposure and irreversibility first, engineering cost second.
**Confidence** — *Certain* = verified at source during consolidation · *High* = re-derived from source · *Medium* = source read, a runtime fact could change it.
**Risk** grades *behavioural* risk, not diff size: **none** (provably no-op) · **cosmetic** · **internal** (operators/logs only) · **user-visible** · **regulated** (could change who is contacted, when, or how much money moves).

---

# BAND 0 — Nothing else has a rollback until this lands

---

### WP-001 — Give a deploy an identity and rollback a written procedure

| | |
|---|---|
| **Category** | Deployability · **Severity** P0 · **Confidence** Certain |
| **Root cause** | `.github/workflows/` contains two files, both test-only. No deploy, no image build, no publish, no promotion. `git tag` returns **zero**. Images are `collections-api:local` / `collections-voice:local`. The frontend has **no Dockerfile anywhere in the tree**. |
| **Objective** | Make "roll it back" an instruction someone can execute at 3am. |
| **Affected files** | `.github/workflows/` (new), `backend/docker-compose.yml`, a new `docs/ops/rollback.md` |
| **Affected modules** | none (CI + docs only) |
| **Affected capabilities** | all — this is the precondition |
| **Dependencies** | none |
| **Prerequisites** | none. **Can start today.** |
| **Implementation strategy** | Tag images by commit SHA; push to a registry; write the two-command rollback **including the database-state caveat** — several migrations mutate real rows unconditionally and `0101`'s downgrade is `pass`. Add `npm run build` to the frontend workflow (CI never builds today, and `nitro` is pinned to a dated beta). Write the `pg_dump`-before-upgrade step down. |
| **Acceptance criteria** | A named engineer can roll a deploy back from the written procedure without asking anyone. The procedure states what the database does and does not revert. |
| **Required tests** | CI builds the frontend. One rehearsed rollback against a scratch environment. |
| **Risk** | **none** — all additive |
| **Rollback** | `git revert` (nothing persisted) |
| **Atomic?** | No |

---

# BAND 1 — The regulated holes that are live today

**Under 60 lines in total.** Every one changes behaviour only where behaviour is already wrong.

---

### WP-002 — Stop `patch_consent` overwriting borrower consent with serializer defaults

| | |
|---|---|
| **Category** | Correctness / data integrity · **Severity** **P0** · **Confidence** Certain (traced end to end and verified) |
| **Root cause** | A read-serializer default leaking into a write path through a round-tripped payload. `api/consent.ts` always includes `allowedWindow` in the PATCH — **including a save that only toggled a channel** — and `db.py:6676-6693` writes it straight back to `consent_records` **and** `customers.preferred_window`. The defaults are hardcoded twice: `_parse_allowed_hours` returns `(10,19)` on empty *and* the writer itself defaults `aw.get("startHour", 10)`. |
| **Objective** | A save that did not change the window must not rewrite the window. |
| **Affected files** | `backend/db.py:6676-6693` · `Habibi/src/api/consent.ts:38-49` · `Habibi/src/components/consent/ConsentDrawer.tsx:65,74` |
| **Affected modules** | `db`, consent UI |
| **Affected capabilities** | Consent · contact admission · **DPDP evidence** |
| **Dependencies** | none |
| **Prerequisites** | none |
| **Implementation strategy** | Omit `allowedWindow` from the PATCH unless the operator changed it; **or** preserve the stored string server-side when the parsed value round-trips unchanged. **Do not "fix the parser" first** — that is WP-030, and doing it first widens the already-corrupted rows silently. |
| **Acceptance criteria** | A PATCH that toggles only a channel leaves `allowed_days`, `allowed_hours` and `customers.preferred_window` **byte-identical**. `'Mon–Sat'` (en-dash) survives a channel toggle. `NULL` stays `NULL`. |
| **Required tests** | Round-trip test: seed `allowed_days='Mon–Sat'`, PATCH a channel status, assert the column is unchanged. Second test for `NULL`. |
| **Risk** | **regulated** — but in the safe direction: it stops a write, it does not start one |
| **Rollback** | `git revert`. **Rows already rewritten are not recoverable** — see WP-003 |
| **Atomic?** | **Yes** |

> **Verified mechanism.** `_parse_allowed_days` tests `if "-" in text_val`; an en-dash is not a hyphen, so the range branch is skipped, the token split yields `["mon–sat"]`, key `"mon"`, days `[1]`; `_format_allowed_days([1])` returns `f"Mon-Mon"`. **Six days of consent overwritten with one — and afterwards both parsers agree on Monday, so the bug becomes undiagnosable.**

---

### WP-003 — Inventory the consent rows already corrupted

| | |
|---|---|
| **Category** | Data integrity · **Severity** P0 · **Confidence** Certain (mechanism), **Unresolved** (population) |
| **Root cause** | WP-002, historically applied. There is **no history table** for `consent_records.allowed_days/allowed_hours`; the sole trail is one contentless `activity_events` row (`kind='consent_updated'`, no before, no after, no field list). `optout_events` covers withdrawals only. |
| **Objective** | Size the damage and identify the population whose original consent is unrecoverable. |
| **Affected files** | none — a query and a decision |
| **Affected capabilities** | Consent · DPDP |
| **Dependencies** | **WP-002 must land first**, or the population keeps growing while you count it |
| **Prerequisites** | Database access |
| **Implementation strategy** | `SELECT id, customer_id, allowed_days, allowed_hours FROM consent_records WHERE allowed_days ~ '[–—]' OR allowed_days IN ('Mon-Mon','Tue-Tue','Wed-Wed','Thu-Thu','Fri-Fri','Sat-Sat','Sun-Sun');` Then decide per row: re-confirm with the borrower, or restore from an external record if one exists. |
| **Acceptance criteria** | A written count, and a decision recorded for each affected row. |
| **Required tests** | n/a |
| **Risk** | **none** (read-only) |
| **Rollback** | n/a |
| **Atomic?** | No |

---

### WP-004 — Cardless Mouth is granted nothing (ADR-0002)

| | |
|---|---|
| **Category** | Correctness / security · **Severity** **P0** · **Confidence** Certain |
| **Root cause** | A `None` sentinel meaning *"no grant was derived"* to its author and *"do not filter"* to every caller. `agent_core/skills/runtime.py:184` returns `ToolState(allowed=None, offered=None)`; `bot_tools.py:831` is `if ctx.allowed_tools is not None and …`; `voice/tools.py:2911` is `if allowed_tool_names is not None:`. **A cardless Mouth is permitted to execute, not merely offered.** |
| **Objective** | An unauthored card cannot move money. |
| **Affected files** | `agent_core/skills/runtime.py:184` (**one line**); then `bot_runtime.py:947-951`, `bot_tools.py:59-85,831`, `voice/tools.py:2911`, `sandbox_runtime.py:230-244` |
| **Affected capabilities** | **Tool Grant · every write tool on both live channels** |
| **Dependencies** | none — `grant.py` is **not** required for this |
| **Prerequisites** | **WP-005 (the inventory query) must return a known population first.** The population this protects is the population it breaks. |
| **Implementation strategy** | Return `ToolState(allowed=frozenset(), offered=())`. Because `has_grant` is `self.allowed is not None`, **this closes the fail-open at all four consumers at once.** Then delete the `TOOL_DEFINITIONS` and `_SANDBOX_TOOL_NAMES` fallbacks and invert the two enforcement sentinels. |
| **Acceptance criteria** | A Deployment with `agent_card = '{}'` offers zero write tools on voice, WhatsApp and sandbox, and `execute_tool` refuses them. |
| **Required tests** | `test_tool_grant.py:99` already proves deny-all **in the module**; add the equivalent at each of the three runtimes. |
| **Risk** | **regulated**, and the degradation is **safe**: `voice/tools.py:80-94` unions `ALWAYS_ON` back after the filter, so a cardless mouth keeps `disclose_recording`, `verify_identity`, the flow verbs and `end_call`. **It still greets, discloses, verifies and hangs up. It simply cannot move money.** |
| **Rollback** | `git revert` |
| **Atomic?** | **Yes** for the sentinel; the three fallback deletions can follow |

> **This work package is scheduled last in the existing roadmap, behind ~13 developer-days of Wave 0, on a stated blast radius that the source contradicts.** That is the largest sequencing error in the corpus.

---

### WP-005 — Inventory Mouths with an empty Agent Card

| | |
|---|---|
| **Category** | Correctness · **Severity** P0 · **Confidence** Unresolved (needs runtime) · **Status** **READY** — unblocked 2026-09-03, the stack is up |
| **Root cause** | WP-004 cannot ship safely without knowing who it breaks. |
| **Objective** | Know the blast radius before inverting the sentinel. |
| **Affected files** | none |
| **Dependencies** | none · **Prerequisites** database access |
| **Implementation strategy** | `SELECT b.id, pv.id, pv.status FROM bots b LEFT JOIN prompt_versions pv ON pv.bot_id = b.id WHERE pv.agent_card IS NULL OR pv.agent_card = '{}'::jsonb;` Cross-check against `bot_deployments` for anything **active**. |
| **Acceptance criteria** | A list of affected Deployments, and an authoring plan for each, before WP-004 ships. |
| **Risk** | none · **Rollback** n/a · **Atomic?** No |

---

### WP-006 — Contact Gate fails closed for every purpose

| | |
|---|---|
| **Category** | Correctness · **Severity** **P0** · **Confidence** Certain |
| **Root cause** | A product preference (*never leave a customer on read because our DB blipped*) implemented as a blanket `True`, contradicting the module's own fail-closed contract. |
| **Objective** | An unreadable consent table refuses the send, on every purpose. |
| **Affected files** | `backend/contact_policy.py:596-600` and `:1020-1024` — **4 lines** |
| **Affected modules** | `contact_policy`, and every non-outreach caller: `bot_runtime.py:150`, `whatsapp_outbound.py:449`, `db.py:10280`, `payment_events.py:587/634/648`, `promise_fulfillment.py:599/995` |
| **Affected capabilities** | Contact admission · WhatsApp replies · statutory notices |
| **Dependencies** | none · **Prerequisites** none |
| **Implementation strategy** | Delete the `if purpose == "outreach"` discrimination in both exception paths. If product insists on answering an in-flight thread, require a **separately named purpose with an explicit, audited override** — not a blanket `True`. |
| **Acceptance criteria** | Fault-inject inside `_load_customer`: the WhatsApp reply is refused, and no `contact_events` row is written. |
| **Required tests** | One test per exception path. **Note `bot_runtime.py:158`'s own `except` is currently unreachable** because `admit` swallows first — it will start firing. |
| **Risk** | **regulated**, in the safe direction. Availability trade: during a DB incident, in-session replies stop |
| **Rollback** | `git revert` |
| **Atomic?** | **Yes** |

---

### WP-007 — The two signature-verified webhooks must reach their HMAC

| | |
|---|---|
| **Category** | Correctness / availability · **Severity** **P0** · **Confidence** Certain |
| **Root cause** | One policy written twice with no derivation. A real security fix replaced a `/twilio` prefix with an explicit enumeration, and the enumeration covered the four callbacks its author was looking at. `/twilio/sms/status` was added to `authz.py` later by someone with no reason to know a second list existed. **The security fix created the availability bug.** |
| **Objective** | Twilio SMS receipts and CBS bounce events reach their handlers in production. |
| **Affected files** | `backend/main.py:233-257` (2 lines) · `backend/authz.py:229,233` |
| **Affected capabilities** | SMS delivery evidence · **the treatment follow-through loop** (`enact._hand_to_lms` returns through the bounce path) |
| **Dependencies** | none · **Prerequisites** none |
| **Implementation strategy** | Add both paths to `_AUTH_EXEMPT_PREFIXES` — **noting `/webhooks/payments` does not prefix-match `/webhooks/collections/…`**, because matching is `path == p or path.startswith(p + "/")`. Then derive one list from the other, or add the test asserting they agree. |
| **Acceptance criteria** | With `API_KEY` set, an unsigned POST to each path returns 401/403 **from the signature check**, and a correctly signed POST returns 200. |
| **Required tests** | One HTTP test per webhook. **Neither path appears anywhere in `backend/tests/` today (zero hits).** And fix `test_production_hardening.py:41-45`, which asserts `status_code != 401` in a fixture where `_twilio_signature_ok` returns `True` — so those unsigned POSTs are currently being *accepted*. |
| **Risk** | **regulated** — it opens two routes that are currently closed. The HMAC is the gate and it is correct |
| **Rollback** | `git revert` |
| **Atomic?** | **Yes** |

---

### WP-008 — A statutory bounce notice is not recorded as served unless it was sent

| | |
|---|---|
| **Category** | Correctness · **Severity** **P0** · **Confidence** High |
| **Root cause** | `sent = True` sits at try-block level, **outside** `if twilio_sms.configured():`. |
| **Objective** | `first_touch_at` means a notice was sent. |
| **Affected files** | `backend/payment_events.py:668-675` — **one line** |
| **Affected capabilities** | Statutory bounce notice · a legal obligation with a clock |
| **Dependencies** | none · **Prerequisites** none |
| **Implementation strategy** | Move `sent = True` inside the guard. When SMS is unconfigured, set `suppression_reason` rather than nulling it — **today it is nulled, so no report will ever surface the gap.** |
| **Acceptance criteria** | With `TWILIO_SMS_FROM` unset, a bounce leaves `first_touch_at IS NULL` and a non-null `suppression_reason`. |
| **Required tests** | One test with SMS unconfigured. |
| **Risk** | **regulated**, in the safe direction |
| **Rollback** | `git revert` · **Atomic?** Yes |

---

### WP-009 — An ambiguous carrier failure is `ambiguous`, not `dial_failed`

| | |
|---|---|
| **Category** | Correctness · **Severity** **P0** · **Confidence** High |
| **Root cause** | `outbound.place` maps **any** Twilio exception to `{"placed": False}`. A 10 s read timeout *after* Twilio accepted the create is indistinguishable from a rejection — and `campaigns.process_one` returns the target to `pending` at +5 min while `cadence.py:224-228` makes the **opposite** decision on the same state. |
| **Objective** | A dial that may have connected is never automatically re-queued. |
| **Affected files** | `backend/outbound.py:743-751` (~15 lines) · `backend/campaigns.py:611-626` |
| **Affected capabilities** | **Outbound dialling · contact frequency · RBI Fair Practices** |
| **Dependencies** | none · **Prerequisites** none |
| **Implementation strategy** | **The correct answer is already in this repository, once.** Copy the shape of `whatsapp.py:201-244` — `is_definite_client_error` / `is_ambiguous_transport_error` — and give the voice path an `ambiguous_transport` bucket and a `parked` state for reconciliation, as `whatsapp_outbound.py:305-324` already has. Then reconcile cadence and campaigns on one answer. |
| **Acceptance criteria** | A simulated post-POST read timeout leaves the target **not** re-queued, and leaves a reconcilable row. |
| **Required tests** | *"A campaign must not re-queue after a Twilio read timeout."* Report 25 names this as the missing test; **it is the one that would fail today.** |
| **Risk** | **regulated**. Trade: some genuinely-failed dials will now need reconciliation rather than auto-retry. **A double-contact is a breach per occurrence and irreversible; a missed retry is not** |
| **Rollback** | `git revert` |
| **Atomic?** | **Yes** — a half-applied classifier is worse than none |

---

### WP-010 — Session coalescing must not disable the frequency caps

| | |
|---|---|
| **Category** | Correctness · **Severity** **P0** · **Confidence** High |
| **Root cause** | `admit` computes `coalesced` and then puts **cooling-off, the weekly cap and the daily-cap reservation all inside `if purpose == "outreach" and counts:`**. Both dial endpoints pass the **customer id** as `session_key`, and `related_id` is a fresh attempt id so `_already_counted_related` never matches. |
| **Objective** | The contact ledger records what actually happened. |
| **Affected files** | **Either** `backend/contact_policy.py:971-981` **or** `backend/main.py:3782` and `:4102`. **One of the two, not both.** |
| **Affected capabilities** | **Contact frequency · the RBI evidence artefact** |
| **Dependencies** | none · **Prerequisites** none |
| **Implementation strategy** | Move cooling-off and the cap reservation outside the `counts` branch, **or** stop passing `customer_id` as the session key on the dial endpoints. Coalescing exists for a reason — do not delete it; scope it. |
| **Acceptance criteria** | Two "Call now" clicks ten seconds apart produce **two** counted `contact_events` rows, and the fourth is refused with `daily_cap`. |
| **Required tests** | A repeat-dial test asserting the counter increments. |
| **Risk** | **regulated**. This is why it matters: today *"the daily cap of 3 records one touch for the whole burst"* — **the evidence is affirmatively wrong, not merely absent** |
| **Rollback** | `git revert` · **Atomic?** Yes |

---

### WP-011 — Fix the two date bombs and add an expiry test

| | |
|---|---|
| **Category** | Testing · **Severity** **P0** · **Confidence** Certain |
| **Root cause** | Stale fixtures. `test_contact_policy.py:287` passes `promised_date="2026-09-01"` against a wall-clock past-date guard — **failing since 2026-09-02**, taking a daily-cap enforcement test with it. `test_voice_write_idempotency.py:36` is `PROMISE_DATE = "2026-09-14"` — **4 tests start failing on 2026-09-15** — corrected 2026-09-03: the constant occurs 8 times, but only four tests reach it, through the `_book` helper. |
| **Objective** | Red means red. |
| **Affected files** | `tests/test_contact_policy.py:287` · `tests/test_voice_write_idempotency.py:36` · one new lint check |
| **Dependencies** | none · **Prerequisites** none · **Blocks:** every work package whose validation is "the suite passes" |
| **Implementation strategy** | Convert both to `date.today() + timedelta(...)`, the convention the rest of the suite already uses. **Then close the class**, not the two instances: one test that fails when any dated constant in the tree is within 30 days of expiry. That also catches `FISH_TTS_MODEL` (WP-032) and the `policy_rule_sets.effective_to` cliff. |
| **Acceptance criteria** | `pytest -q` green **on the host** — inside `collections_voice`, four cross-tree tests fail on a missing `/Habibi` path and always have (see REFACTORING-STATE → *NOT FAILURES*); a faked future clock does not re-break it. |
| **Risk** | **none** — tests only |
| **Rollback** | `git revert` · **Atomic?** No — two independent fixes |

> **With a red baseline, "did my refactor break it?" is unanswerable, and a team learns to skim past red.**

---

# BAND 2 — Shut the envelope

---

### WP-012 — `load_env()` before `_IS_PROD` is decided

| | |
|---|---|
| **Category** | Configuration / security · **Severity** **P0** · **Confidence** Certain |
| **Root cause** | `main.py:204-205` computes `_APP_ENV` and `_IS_PROD` at module import, and **`main.py` never calls `load_env()`** — verified by whole-file scan. On the documented bare-metal path (`main.py:3`, `run_stack.ps1:43`) `.env` has not been read yet. |
| **Objective** | Setting `APP_ENV=production` in `.env` actually does something. |
| **Affected files** | `backend/main.py` (2 lines at the top). Same defect in `voice/bot.py` and `voice/workers/insurance.py` |
| **Dependencies** | none · **Prerequisites** none · **Blocks WP-013.** |
| **Implementation strategy** | `from env_loader import load_env; load_env()` **above** the application imports — the shape `bot_worker.py:27-31` and `worker.py:20-24` already use. Three of six entrypoints already do it correctly. |
| **Acceptance criteria** | With `APP_ENV=production` only in `.env`, a bare `uvicorn main:app` refuses to boot without credentials. |
| **Required tests** | A test asserting `_IS_PROD` reflects `.env` on the non-container path. |
| **Risk** | **internal**, then **regulated** once WP-013 lands |
| **Rollback** | `git revert` |
| **Atomic?** | **Yes** |

> **Do this first. A control that silently ignores its own configuration is worse than one that has none**, because it converts a known gap into a believed-closed one — and setting `APP_ENV=production` is the single most likely response to this audit.

---

### WP-013 — Unrecognised `APP_ENV` is production; absent credentials refuse to boot

| | |
|---|---|
| **Category** | Security · **Severity** **P0** · **Confidence** Certain |
| **Root cause** | `_IS_PROD = _APP_ENV in {"prod","production"}` is a deny-list reading, while `env_utils.NON_PROD_ENVS` in the **same process** is an allow-list reading — and `env_utils.py:26-32`'s comment shows the author knew both existed and applied the safe one to keys only. `main.py:292`'s `auth_required = bool(single or key_map)` then makes absent credentials a *mode*. |
| **Objective** | `APP_ENV=staging` is safe, and a missing key is a refusal. |
| **Affected files** | `backend/main.py:205`, `:292` · `backend/actor_context.py:55,58-65` |
| **Affected capabilities** | Authentication · authorization · object visibility · OpenAPI · Twilio signature · voice WS · the hardening gate — **eight controls on one line** |
| **Dependencies** | **WP-012** · **Prerequisites** WP-012 verified in effect |
| **Implementation strategy** | `_IS_PROD = _APP_ENV not in {"dev","test","local"}`. Separately, stop deriving `auth_required` from whether credentials happen to be set. Set `ALLOW_ACTOR_HEADER=false` **explicitly** rather than inheriting it. |
| **Acceptance criteria** | `APP_ENV=staging` requires an API key, rejects an unsigned Twilio callback, refuses an unauthenticated WS upgrade, and does not publish `/docs`. |
| **Required tests** | **A CI job that runs with `APP_ENV=production`.** Today the suite exercises only the permissive branch — and two tests already route around the import-time freeze with `monkeypatch.setattr(app_main, "_IS_PROD", True)`. **The tests know about this bug and work around it.** |
| **Risk** | **regulated.** Expect things to refuse to boot. **Those refusals are correct** — do not reach for `ALLOW_UNHARDENED_PRODUCTION` |
| **Rollback** | `git revert` · **Atomic?** Yes |

---

### WP-014 — Require the voice WebSocket proxy secret; require the Twilio signature

| | |
|---|---|
| **Category** | Security · **Severity** **P0** · **Confidence** Certain |
| **Root cause** | Both gates end in a non-prod escape: `main.py:3479` `return True`; `:3396` `return not _IS_PROD`. **Both secrets are already configured in `.env`.** |
| **Objective** | A configured secret is enforced. |
| **Affected files** | `backend/main.py:3471-3479`, `:3387-3396` |
| **Affected capabilities** | **Live borrower call audio** · the `call_attempts` state machine (forged status callbacks feed treatment inputs) |
| **Dependencies** | WP-013 makes this redundant in production; do it anyway — **defence in depth is exactly what is missing** |
| **Implementation strategy** | If `VOICE_WS_PROXY_SECRET` is set, require it. If unset, refuse the upgrade. Same for the Twilio token. |
| **Acceptance criteria** | An upgrade without the secret is refused in every environment. |
| **Required tests** | Extend `tests/test_voice_ws_authz.py`, which already pins the route list so a third socket cannot inherit the carve-out silently. |
| **Risk** | **regulated** — local tooling that relied on the escape will break loudly |
| **Rollback** | `git revert` · **Atomic?** Yes |

---

### WP-015 — Total revocation must mean empty, and must take effect

| | |
|---|---|
| **Category** | Security · **Severity** **P0** · **Confidence** High |
| **Root cause** | Absence of a row used as a proxy for absence of intent. The `LEFT JOIN` yields `explicit == set()` for a stripped role, and the `else` branch unions `ROLE_DEFAULTS`. **The comment three lines above — "a revoked grant stays revoked" — is false in exactly this case.** |
| **Objective** | The Roles screen and the enforcer agree. |
| **Affected files** | `backend/authz.py:702-714` · `backend/db.py:473-508` · `backend/main.py:2828-2851` |
| **Affected capabilities** | RBAC · incident response |
| **Dependencies** | none · **Prerequisites** none |
| **Implementation strategy** | Distinguish "no rows" from "revoked to empty" — a sentinel row, or a `configured_at` column on `roles`. Make `GET /roles` report **resolved** grants, not raw rows. Call `invalidate_permission_cache` from `replace_role_permissions` — **it already exists, its docstring says "call after a role change", and it has zero production callers**, so a revocation currently lags 30 s per process. |
| **Acceptance criteria** | Revoke every permission from `role-supervisor`; a holder is denied `VOICE_OPERATE` within one request. |
| **Required tests** | The test that should have existed: **revoke *all*, assert empty.** `test_explicit_grant_beats_default_so_revocation_works` only ever exercised partial revocation. |
| **Risk** | **regulated** — it removes access that is currently granted |
| **Rollback** | `git revert` (a schema change needs its own migration) · **Atomic?** Yes |

---

### WP-016 — Provision a `NOBYPASSRLS` role and turn RLS on

| | |
|---|---|
| **Category** | Security / data integrity · **Severity** P1 · **Confidence** High |
| **Root cause** | `rls.py` is complete, tested and **self-protecting** — `enable()` refuses to install for a bypassing role. The application connects as exactly that role, and `db.py:39` hardcodes it as the default DSN, so **no configuration path in this repository connects as a non-bypassing role.** |
| **Objective** | Convert the most dangerous refactor error in this codebase from silent to loud. |
| **Affected files** | none in the application. `scripts/rls.py`, deployment config |
| **Affected capabilities** | **Tenant isolation** — and it gates every SQL-touching refactor |
| **Dependencies** | none · **Prerequisites** database access; a maintenance window |
| **Implementation strategy** | `provision-role` → `apply` → `enable`, in that order. **Do not enable before provisioning** — `rls.py:19-23` and `:446` refuse for exactly this reason, and enabling as a `BYPASSRLS` role *looks like it worked and changes nothing*. |
| **Acceptance criteria** | `rls.py status` reports policies installed and enforcing; `tests/test_rls.py`'s six enforcement tests pass against the live role. |
| **Required tests** | Already exist. **They probe 2 tables of ~112** — extend coverage. |
| **Risk** | **internal**, and **reversible** (`python scripts/rls.py disable`), which almost nothing else here is |
| **Rollback** | `disable` |
| **Atomic?** | **Yes** for enable/disable |

> **Why this is a prerequisite and not a nice-to-have.** Today, dropping one `WHERE tenant_id = :t` during a refactor of a ~290-site surface returns another tenant's borrower records **with a 200**. With RLS on, the identical mistake returns **zero rows** — a visible outage instead of an invisible breach. It does **not** make the API multi-tenant; the tenant still reaches Postgres as a libpq startup parameter baked from a process-level constant.

---

### WP-017 — Install a root log handler; make the redactor match bare digits

| | |
|---|---|
| **Category** | Operations · **Severity** P1 · **Confidence** Certain |
| **Root cause** | `setup_logging()` returns immediately unless `LOG_FORMAT=json` — and `LOG_FORMAT` appears **zero times** in a 638-line `.env.example`. In `api` and `voice_insurance` nothing configures the root logger, so **every `logger.info` is discarded** and WARNING+ falls to `logging.lastResort` unformatted. **`pii_redact.redact_text` therefore never executes on log output at all.** |
| **Objective** | A shadow run you cannot read is not a shadow run. |
| **Affected files** | `backend/observability.py:469-486` · `backend/voice/workers/insurance.py` · `backend/pii_redact.py:42-58` · `.env.example` |
| **Affected capabilities** | Every diagnosis, and **the validation of every later work package** |
| **Dependencies** | none · **Prerequisites** **the redactor fix must land first — see the blocking sub-gate** |
| **Implementation strategy** | Install a handler even when `LOG_FORMAT` is unset. Call `log_bridge.install()` in the insurance worker. Document `LOG_FORMAT`, `SENTRY_DSN`, `APP_RELEASE`. |
| **Acceptance criteria** | `docker logs collections_api` shows timestamped, levelled INFO with a request id. |
| **Required tests** | Extend `tests/test_observability.py`. |
| **Risk** | **internal** — **unless the sub-gate is skipped**, in which case regulated |
| **Rollback** | Unset and restart — **but purge what was already written** |
| **Atomic?** | No |

> **⚠ Blocking sub-gate.** `pii_redact.py:22-58` matches phone numbers only with a literal `+91` prefix, while `customers.phone_primary` stores **bare digits**. Turning on JSON logging first would create an indefinitely-retained, well-indexed store of borrower phone numbers. **Fix the redactor first**, run it over `extra` fields and `formatException` output (not just `message`), and note the scrubber currently **fails open**.

---

### WP-018 — Guard every stage in `bot_worker`, and log which one failed

| | |
|---|---|
| **Category** | Reliability · **Severity** P1 · **Confidence** Certain |
| **Root cause** | `process_one_any` guards four of twelve stages, and **five unguarded ones run above the guarded ones.** The loop logs `logger.exception("process_one crashed — backing off")` — no queue name, no row id — sleeps 1.5 s, and repeats forever. |
| **Objective** | One poison row cannot silently stop WhatsApp, reminders, treatment and webhooks. |
| **Affected files** | `backend/bot_worker.py:93-146` · `agent_core/treatment/followthrough.py:424-451,497-504` (~25 lines) |
| **Affected capabilities** | Every collections drain |
| **Dependencies** | none · **Prerequisites** WP-017 (or the failure stays invisible) |
| **Implementation strategy** | Wrap every stage; log queue name and row id; give `followthrough.advance` the savepoint its sibling `sweep.py:181-196` already documents. |
| **Acceptance criteria** | A deliberately-poisoned row in stage 1 does not prevent stage 12 from running, and the log names the queue. |
| **Required tests** | One test injecting a raise into an early stage. |
| **Risk** | **internal** · **Rollback** `git revert` · **Atomic?** No |

---

# BAND 3 — Make the ground safe

---

### WP-019 — A committing test fixture (`db_real`)

| | |
|---|---|
| **Category** | Testing · **Severity** P1 · **Confidence** Certain |
| **Root cause** | `db_tx` routes every `engine.begin()` into a SAVEPOINT on **one shared connection**; two blocks are always mutually visible; advisory locks are held for the whole test. **Concurrency is structurally untestable.** |
| **Objective** | The ~16 `SKIP LOCKED` claim paths become testable. |
| **Affected files** | `backend/tests/conftest.py` |
| **Dependencies** | WP-011 · **Blocks** WP-020 and every concurrency claim |
| **Implementation strategy** | Add `db_real` beside `db_tx` — real pooled connections, real commits, explicit cleanup. **`test_job_claim.py:38-50` and `test_voice_session_store_contention.py` already do this by hand; the pattern needs promoting, not inventing.** |
| **Acceptance criteria** | At least one contention test uses it and fails when its guard is removed. |
| **Required tests** | Mutation check: delete the advisory lock at `db.py:702-707` and confirm a test goes red. **Today all 26 idempotency assertions stay green** — and that lock exists *because* two requests once created *"two promises for one idempotent POST."* |
| **Risk** | **none** — test infrastructure |
| **Rollback** | `git revert` · **Atomic?** Yes |

---

### WP-020 — Assert the seed floor

| | |
|---|---|
| **Category** | Testing · **Severity** P1 · **Confidence** High |
| **Root cause** | 436 tests (17.9%) are conditioned on seeded rows and **nothing asserts the seed has content.** 56 sit in compliance- and tenancy-named files. |
| **Objective** | Convert 284 silent skips into one loud failure. |
| **Affected files** | one new test |
| **Implementation strategy** | Fail when `customers`, `accounts`, `interactions`, `products` or `leads` is empty. **The team already knows the pattern** — `conftest.py:146` reads `assert packs, "…these tests would go vacuous"`; it was simply never applied at the seed level. |
| **Acceptance criteria** | An empty seed fails one test loudly rather than skipping 284 quietly. |
| **Risk** | none · **Rollback** `git revert` · **Atomic?** Yes |

---

### WP-021 — Pin the seven unreached refusal branches, and un-disarm the fixture

| | |
|---|---|
| **Category** | Testing · **Severity** P1 (**gates the regulated canonicalizations**) · **Confidence** Certain |
| **Root cause** | Twelve refusal reasons; **five are asserted as engine behaviour and seven appear only as members of a policy set** — including `customer_dnd`, the check that stops the platform calling someone who told the regulator not to be called. **And the gate's own suite disarms them**: `_prep` nulls `dnd`, `dnd_registry`, `allowed_days` and `allowed_hours` for every DB test in the file, and sets weekly = 8 against daily = 3 so the weekly cap can never fire. |
| **Objective** | Deleting a statutory refusal branch turns the suite red. |
| **Affected files** | `tests/test_contact_policy.py` (+ a new pure-unit file) · `tests/test_cadence_pause_and_strand.py:50-55` |
| **Dependencies** | WP-011 · **Blocks** WP-025, WP-026, WP-027 |
| **Implementation strategy** | `_veto` takes a plain dict, so these are **pure unit tests**. Assert the *emitted reason* for DND, channel DND, expired consent, cooling-off, weekly cap, unreadable consent and disallowed window. **Then change `_prep` to stop nulling the columns** — otherwise the new tests sit beside a fixture that disarms them. And add one test to `test_cadence_pause_and_strand.py` that lets the real gate run: it currently monkeypatches `admit` to always allow **for the whole 407-line file**. |
| **Acceptance criteria** | Break each branch by hand; confirm **exactly one** new failure each. |
| **Risk** | **none** to production · **Rollback** `git revert` · **Atomic?** No — one branch per commit is better |

> **Two suites each defer the contact gate to the other, and between them nothing tests it.** Fixing this in one file will not close it.

---

### WP-022 — Close the capture↔enforcement seam

| | |
|---|---|
| **Category** | Testing · **Severity** P1 · **Confidence** Certain |
| **Root cause** | `db.opt_out` — the DPDP opt-out writer — **is called by no test.** Every opted-out borrower in the suite is fabricated by raw SQL. |
| **Objective** | Capture and enforcement meet in one process. |
| **Affected files** | one new test |
| **Dependencies** | WP-011 · **Unlocks** WP-027 (consolidating the three DND definitions) |
| **Implementation strategy** | One test: call `db.opt_out`, then assert `contact_policy.admit` refuses. |
| **Acceptance criteria** | If the writer wrote the wrong channel, purpose or composite id, this test fails. **Today every consent test would still pass.** |
| **Risk** | none · **Rollback** `git revert` · **Atomic?** Yes |

---

### WP-023 — A composition test for the outbound gate

| | |
|---|---|
| **Category** | Testing · **Severity** P1 (**unlocks WP-028**) · **Confidence** Certain |
| **Root cause** | Every *piece* is tested — `admit`, `suppress`, `place` (7 tests including *"database dies after the dial"*). **The composition is tested at zero sites.** And `campaigns.process_one` — the dialer that runs the eligibility gate — is verified only by an `inspect.getsource` substring match. |
| **Objective** | A change to the compliance ordering cannot land in six files out of seven. |
| **Affected files** | 3 test files + 1 new contract test |
| **Dependencies** | WP-011, WP-021 |
| **Implementation strategy** | Execute `campaigns.process_one` for real; delete the source-text assertion at `test_outbound_studio_bindings.py:110`. Then a parameterised contract test across all seven call sites: each must reserve, admit, suppress on refusal, and place only on allow. |
| **Acceptance criteria** | The test **fails** when a call site's order is deliberately swapped. |
| **Risk** | none · **Rollback** `git revert` · **Atomic?** No |

---

### WP-024 — Publish a coverage number and a skip count

| | |
|---|---|
| **Category** | Testing · **Severity** P2 · **Confidence** Certain |
| **Root cause** | **No coverage measurement exists anywhere.** Every "no test reaches this line" claim in 23,850 lines of forensics — including in MASTER-AUDIT — is call-graph-derived. |
| **Objective** | Convert an argued class of claim into a measured one. |
| **Affected files** | `.github/workflows/backend-pytest.yml` (one line) |
| **Implementation strategy** | Add `pytest-cov` and `--cov=. --cov-report=xml`. **Set no threshold** — publish the number. Run `pytest -rs` once and publish the real skip count. |
| **Acceptance criteria** | A number exists. |
| **Risk** | none · **Atomic?** Yes |

---

# BAND 4 — Canonicalize the regulated decisions

**Prerequisite for the whole band: WP-001, WP-011, WP-016, WP-017, WP-021, WP-023.** Six of nine targets have no test that would fail on a behaviour change, so consolidating them earlier would be **unfalsifiable** — you could not tell a successful consolidation from an incident.

---

### WP-025 — Import `BLOCKING_CONSENT` at its copy sites

| | |
|---|---|
| **Category** | Duplication · **Severity** P1 · **Confidence** High |
| **Root cause** | Four definitions under three names — `capture.py:331` is `_CONSENT_BLOCKING_STATUSES`, which is why a symbol-name search found only three. |
| **Objective** | One frozenset. |
| **Affected files** | `payment_events.py:28` · `promise_fulfillment.py:29` · `capture.py:331` · `agent_core/reco/arbitration.py:39` — **9 use sites, five in `capture.py` alone** |
| **Dependencies** | none. **Provable no-op; can start today.** |
| **Implementation strategy** | Import the canonical. Cycle-safe: `contact_policy` is a DAG leaf, and **two of the copying modules already import it for other reasons.** |
| **Acceptance criteria** | Zero local definitions; a pin test that all effective sets are identical. |
| **Risk** | **none** — verified member-identical |
| **Rollback** | `git revert` · **Atomic?** Yes — a half-migration leaves the divergence *and* removes the evidence |

---

### WP-026 — One calling-window decision: `policy_rules.calling_window()`

| | |
|---|---|
| **Category** | Canonicalization · **Severity** P1 · **Confidence** High |
| **Root cause** | The **constant** is shared correctly across six modules; the **decision** is not. `calling_window()` exists so a tenant can publish a narrower window — and has **two** production call sites, both inside `contact_policy.py`. |
| **Objective** | A published narrower window is honoured everywhere. |
| **Affected files** | `compliance/detectors.py:297-298` **first**, then `treatment/timing.py:88`, `live_qa/checks.py:171`, `live_qa/scorecard.py:292`, `treatment/metrics.py:345-365`, `payment_events.py:132-145`, `policy_export.py:53-59` |
| **Dependencies** | WP-021, WP-033 (`policy_rule_sets` must be seeded, or this is a no-op) |
| **Implementation strategy** | **Start with `detectors.py`** — one file, the numbers already match, and it is the **only unpinned restatement** (`RBI_CALL_START_HOUR` appears nowhere else in the repo), sitting *sixteen lines above* its own `from contact_policy import _zone  # one definition of the timezone fallback`. Then each site independently. **`treatment/metrics.py` re-implements the window in SQL** and needs the bounds parameterized into the query, not an import. **Use `agent_core/treatment/policy.py:12-16,463-484` as the reference — it already delegates and fails closed.** |
| **Acceptance criteria** | Publishing a narrower window changes the scheduler, the QA scorecard and the compliance sweep, not only the dialler. |
| **Risk** | **none** for any tenant that has not published a narrower window; **regulated** for any that has |
| **Rollback** | `git revert` · **Atomic?** No — one site per commit |

---

### WP-027 — One DND definition

| | |
|---|---|
| **Category** | Canonicalization · **Severity** P1 · **Confidence** High |
| **Root cause** | Three readings: `contact_policy.py:504` ORs both stores; `db.py:2313` ORs both; **`db.py:1826` reads `customer_dnd` only.** |
| **Objective** | A registry-flagged borrower is red everywhere. |
| **Affected files** | `db.py:1826-1827` (code fix) — then a column decision |
| **Dependencies** | WP-022 |
| **Implementation strategy** | Code fix first, fail-closed: `_callback_dnd_active` reads both. Column consolidation is a separate, later data migration. |
| **Acceptance criteria** | A borrower with `dnd_registry = true` and `customers.dnd = false` is blocked on the callback board. |
| **Risk** | **regulated**, in the safe direction |
| **Rollback** | `git revert` · **Atomic?** No |

---

### WP-028 — One owner for the outbound gate sequence

| | |
|---|---|
| **Category** | Architecture / canonicalization · **Severity** P1 · **Confidence** High |
| **Root cause** | Seven sites, **two orderings**, and `payment_events.py` calls **no `outbound.suppress` at all** — so the invariant *"every refused outbound leaves a suppressed attempt row"* holds at six of seven. |
| **Objective** | One function; one ordering; every refusal leaves evidence. |
| **Affected files** | new `outbound.dial(...)`; 7 call sites, ~400 lines. **Two are HTTP handlers taking `dict[str, Any]` bodies and opening their own transactions — moving the sequence out of them is the whole point** |
| **Dependencies** | WP-023 · **Prerequisites** **the ordering conflict must be resolved as a decision before the function is written** |
| **Implementation strategy** | Decide the order and whether every refusal must leave a `call_attempts` row. Introduce `outbound.dial(...)`; migrate the five ordering-A sites first (**no behaviour change**); then the two ordering-B sites separately. |
| **Acceptance criteria** | A test asserting every refusal path leaves exactly one suppressed `call_attempts` row. |
| **Risk** | **regulated.** Changing `payment_events` to reserve-then-admit **starts writing suppressed rows** — an audit-trail addition, and a change to attempt-ledger counts **which the fleet gate reads** |
| **Rollback** | `platform_switches`, not env |
| **Atomic?** | **Atomic for the shared function; strangleable per caller** |

---

### WP-029 — One preferred-window default

| | |
|---|---|
| **Category** | Canonicalization · **Severity** P1 · **Confidence** High |
| **Root cause** | `contact_window.DEFAULT_WINDOW` is `09:00-20:00 IST`; nine sites carry `10:00-19:00`. |
| **Objective** | One fallback. |
| **Affected files** | **(a)** display: `db.py:1058`, `:8834`, `schemas.py:42` · **(b)** the live verdict: `db.py:1938` · **(c)** writes: `db.py:6631`, `:10476`, `agent_core/skills/packs/ptp-negotiate/SKILL.md:32` |
| **Dependencies** | WP-021 |
| **Implementation strategy** | **Ship in three separate pieces, because their risk differs.** (a) cosmetic. (b) **`db.py:1938` is not a display literal** — it feeds `_callback_dnd_active` and changes a DND verdict, and it disagrees with `db.py:5468` in the same file; deleting the substitution flips callbacks in the 09:00–10:00 and 19:00–20:00 bands from DND to allowed. (c) INSERT `NULL`, not a literal; `SKILL.md` is **prompt text the model repeats to a borrower**, so a change there means re-running the eval suite. |
| **Acceptance criteria** | The callback list and the callback create path agree. |
| **Risk** | (a) cosmetic · **(b) user-visible + regulated** · (c) **regulated** (prompt) |
| **Verification before shipping (b)** | Count callbacks with `NULL preferred_window` scheduled in those two hour-bands. |
| **Rollback** | `git revert` · **Atomic?** Per piece |

> **⚠ The trap this band must not fall into.** RBI 08:00–19:00 (statutory) and `contact_window` 09:00–20:00 (borrower **preference**) are **different rules**. A 19:30 callback is in-preference and out-of-statute. **Merging them would be the worst single outcome of this exercise**, and a canonicalization pass that pattern-matches on "hour window" will do exactly that.

---

### WP-030 — One allowed-days parser

| | |
|---|---|
| **Category** | Canonicalization · **Severity** P1 · **Confidence** Certain |
| **Root cause** | `contact_policy._parse_days` returns `None` on empty and normalizes `–`/`—` → `-`, with a nine-line comment explaining that without it `"Mon–Sat"` collapses to Monday alone. `db._parse_allowed_days` returns `[1,2,3,4,5]` on empty and **does not normalize**. |
| **Objective** | One parser. |
| **Affected files** | `db.py:2038-2054` |
| **Dependencies** | **WP-002 must land first, and WP-003 must have run.** |
| **Implementation strategy** | `db` imports the Gate's parser. **Keep empty-handling at the call site** if consent "blank = unrestricted" is the product rule — that is a product decision, not a code one. |
| **Acceptance criteria** | `'Mon–Sat'` parses to six days on both paths. |
| **Risk** | **regulated.** This widens stored en-dash rows from one day to six — **which is reading the consent the borrower actually gave.** The dangerous direction was the write-back (WP-002), not this |
| **Rollback** | `git revert` · **Atomic?** Yes |

---

### WP-031 — Wire the Tool Grant (six steps)

| | |
|---|---|
| **Category** | Canonicalization / security · **Severity** P1 · **Confidence** Certain |
| **Root cause** | ADR-0001 names an owner with **zero production importers** (verified). Six live formulas remain. |
| **Objective** | One owner, and the publish Gate is the union of runtime. |
| **Affected files** | `skills/runtime.py:194,197` · `voice/tools.py:31-39,80-94,2911` · `bot_runtime.py:912-950` · `sandbox_runtime.py:230-244` · `cards/compile.py:630,734` |
| **Dependencies** | WP-004 is **step 6** and is scheduled in Band 1 — **do it early, not last** |
| **Implementation strategy** | **Six separately-reviewed steps:** (1) pass `channel_tools=` at `skills/runtime.py:194,197` — **two lines, needs none of `grant.py`**, closes the one *verified* divergence, where the publish gate is channel-filtered and both runtimes are channel-blind. (2) `from agent_core.tools.grant import VOICE_ALWAYS as ALWAYS_ON` in `voice/tools.py` — **ten minutes, no prerequisites**: `grant.py` is Pipecat-free and `voice/tools.py:31-39` already imports four `agent_core.tools` modules. (3) migrate `MouthTurn.tools()` → `ToolGrant.for_bundle`. (4) replace `allowed_scope` with `static_grant`. (5) remove `\| ALWAYS_ON` — **only after (3)**, or a seventh formula has been created. (6) = WP-004. |
| **Acceptance criteria** | `grant.py` has production importers and the old formulas are **deleted**, not left beside it. |
| **Required tests** | **Fix the pin's reach**: `test_tool_grant.py:131` opens with `pytest.importorskip("voice.tools")`, so the `VOICE_ALWAYS == ALWAYS_ON` assertion **silently skips in the API image and CI**. |
| **Risk** | (1) user-visible on voice · (2) **none** · (3)-(5) internal · (6) regulated |
| **Rollback** | `git revert` per step |
| **Atomic?** | Per step. **Never delete `test_tool_grant_characterization.py` before the formulas it pins** — its own header says *"delete this file in #13, with the formulas it pins."* Delete it first and the repo has **zero pin** on Tool Grant behaviour while six formulas migrate one at a time, and **nothing goes red — that is the problem** |

---

### WP-032 — Fix `FISH_TTS_MODEL`; close the latent-expiry class

| | |
|---|---|
| **Category** | Reliability · **Severity** P1 · **Confidence** Certain |
| **Root cause** | `fish_tts.py` documents *"Free through 2026-08-31"*; `DEFAULT_MODEL = "s2.1-pro-free"` and `.env.example:574` still select it. **Today is 2026-09-03.** Worse, `OPENROUTER_TTS_MODEL=fish-audio/s2.1-pro-free:free` — **the documented fallback points at the same expired promotion**, so it cannot rescue the primary. |
| **Objective** | Fish TTS works, and this class stops recurring. |
| **Affected files** | `.env`, `.env.example:554,574`, `agent_core/providers/fish_tts.py:60`, the registry seed |
| **Implementation strategy** | Set `FISH_TTS_MODEL=s2.1-pro` and fund API credit (a balance distinct from the platform wallet — the file documents a first-hand test of both ids). Point the OpenRouter fallback at something that is not the same promotion. **Then close the class** — the expiry test in WP-011. |
| **Acceptance criteria** | A Fish preview returns 200. |
| **Risk** | **user-visible** — it is failing now |
| **Rollback** | `git revert` · **Atomic?** Yes |

---

### WP-033 — Seed `policy_rule_sets`, or accept that policy-as-data is dead

| | |
|---|---|
| **Category** | Configuration · **Severity** P1 · **Confidence** High |
| **Root cause** | `INSERT INTO policy_rule_sets` appears in `scripts/seed_policy_rules.py:158` and a test. **The script is invoked from nowhere** — not CI, not `seed_demo.py`, not a migration, not `sql/`. |
| **Objective** | Statutory hours are bounded on every channel. |
| **Affected files** | seeding path, or `contact_policy.py:508-515` |
| **Dependencies** | **Blocks WP-026** (which is a no-op without it) |
| **Implementation strategy** | Either wire the seeding, or document the hardcoded fallback as the product **and fix the hole it leaves**: `contact_policy.py:508-515` reads *"Absent one, only voice is bounded."* **With no published rule set, WhatsApp, SMS and email have no calling-hour bound whatsoever.** Also handle `effective_to` — a rule set that expires with no successor **silently reverts the whole platform to those fallbacks**, and per WP-017 nothing logs it. |
| **Acceptance criteria** | Either `policy_rule_sets` is populated on a fresh install, or a WhatsApp send outside hours is refused by an explicit rule. |
| **Risk** | **regulated.** Publishing a statutory rule set **changes what the platform is allowed to do** — it goes through a shadow protocol, not an ordinary deploy |
| **Rollback** | `git revert` + delete the rows · **Atomic?** Yes |

---

### WP-034 — Create `sql/23_outbound_evals.sql`, or delete the reference

| | |
|---|---|
| **Category** | Data / configuration · **Severity** P1 · **Confidence** Certain |
| **Root cause** | `alembic/versions/20260822_0096:7` says it *"Mirrors sql/14_agent_factory.sql (the CHECK) and **sql/23_outbound_evals.sql**"* — **and that file does not exist** (verified: `sql/` jumps from `22_campaigns.sql` to `90_deferred_fks.sql`). |
| **Objective** | A fresh install can publish outbound. |
| **Affected files** | `backend/sql/` · `.env:405` |
| **Implementation strategy** | Create the file or delete the reference — **but decide.** `fixtures.py:207-211` states the consequence: on CI and on any pilot provisioned from `sql/`, the suite is absent entirely and `OUTBOUND_EVAL_GATE_ENABLED=true` **refuses every outbound publish.** And `.env:405` sets that flag **true** while `.env.example:606` ships **false**. |
| **Acceptance criteria** | A database built from `sql/` alone can satisfy compile gate G-OB9. |
| **Risk** | **internal** · **Rollback** `git revert` · **Atomic?** Yes |

---

# BAND 5 — Structural

---

### WP-035 — `db_core.py`

| | |
|---|---|
| **Category** | Architecture · **Severity** P1 · **Confidence** Certain · **Blocks WP-036** |
| **Root cause** | 41 production modules bind to `db.py`'s **private** helpers — 202 of 239 reach-throughs. A split breaks them all. |
| **Objective** | Make splitting `db.py` possible at all. |
| **Affected files** | one new file + the `db.py` head |
| **Dependencies** | none · **Prerequisites** WP-011, WP-019 |
| **Implementation strategy** | Move `engine` + the `@event.listens_for(engine,"begin")` hook + the DSN/tenant/pool constants + `current_tenant`/`_tenant`, `_rows`, `_one`, `_id`, `_dump`, `_sql`, `_vis_params`, `_activity`, `_actor_user_id`, `_assert_tenant_owns`, `clamp_list_limit`, `clamp_offset`, `_account_tail`, `_IST` — **plus `_jsonb` (from `:14068`) and `_as_dict` (from `:12703`)**, both defined inside upper sections and referenced across them. Explicit `__all__`. Re-export from `db.py`. |
| **Acceptance criteria** | Full pytest green; a smoke boot of `main:app`. **Zero call-site edits** — verified: no importer uses `from db import X`; all 211 use `import db`. |
| **Risk** | **internal, with one real hazard**: `create_engine` must execute **exactly once** and the `begin` listener must register against that same object |
| **Rollback** | Revert one commit |
| **Atomic?** | **Yes — mandatory.** Moving the engine and its listener in separate commits is the failure mode |

> **⚠ Acceptance criterion that must be written into this commit, not discovered on peel #3.** `tests/conftest.py:61` is `monkeypatch.setattr(db, "engine", _EngineProxy(db.engine))`. **Any carved module binding `from db_core import engine` bypasses the proxy**, the savepoint wrapper stops wrapping, and `outer.rollback()` rolls back nothing those modules wrote — **the suite goes green while leaving committed rows behind.** Commit `fd855ca` shows this repo has paid for that bug once. **Every carved module must reach back through `_db().engine`.**

---

### WP-036 — Carve `db.py` by section (13 peels)

| | |
|---|---|
| **Category** | Architecture · **Severity** P1 · **Confidence** High |
| **Root cause** | 18,087 lines, fan-in 101, and it imports the domain back. |
| **Objective** | ~3,100 lines: the CRM kernel plus re-exports. |
| **Affected files** | 13 new modules + `db.py` |
| **Dependencies** | **WP-035, WP-016, WP-042 (response models), WP-019** |
| **Implementation strategy** | **Order by inbound coupling, cheapest first:** Billing → Treatment holds → Dashboard → Workspace → Sandbox → Bot analytics → Routing → Redaction → KB-2+KB-3 → **Prompt Studio R+W as one unit** (17 internal W→R edges make splitting them a mistake; **this peel alone removes 43 of `db.py`'s domain import sites**) → QA → Inbox → Per-turn trace. Each peel is one commit: one new module plus a bottom-of-`db.py` re-export block in the exact shape of `db.py:18005-18024`. **Also remove the single eager edge `db.py:24 → schemas`** — without it the carve stops at SCC 50 instead of 17. |
| **Acceptance criteria** | Full pytest **run in the voice container** (a host run tests a different Python than ships), and **never while the corpus simulator holds locks** — a lock-contention failure looks exactly like a real regression. |
| **Risk** | **internal — with a silent-security-downgrade hazard.** A route or accessor leaving the global middleware loses auth and permission enforcement, and both are already off on this deployment, so the regression is undetectable in testing. **Do not touch any file carrying `# noqa: E402`** |
| **Rollback** | Each peel is one commit; `git revert` restores byte-identically |
| **Atomic?** | Each peel yes; the sequence no |

> **Say this out loud so nobody misreads progress.** SCC size is a **lagging indicator**: you get file size, ownership, review surface and navigability from commit 1, and the cycle only from the last. **Do not let anyone measure progress by SCC and conclude the first eight commits achieved nothing.** And one promise nobody should make: **an SCC of ~41 remains with `db.py` deleted entirely** — the agent-turn core is genuinely mutually recursive and is not `db.py`'s fault.
>
> **If only part of it is ever done:** WP-035 + Prompt Studio + Treatment holds. Three commits, ~2,700 lines moved, over half the domain fan-out removed.

---

### WP-037 — Make `conn` required in the four Locked Engines

| | |
|---|---|
| **Category** | Data integrity / architecture · **Severity** P1 · **Confidence** High |
| **Root cause** | All four fall back to `db.engine` when no connection is injected, so **a decision is read on one connection and its audit row written on another** — a caller's rollback cannot retract the log row. |
| **Objective** | A decision and the row recording it are atomic. |
| **Affected files** | `treatment/engine.py:258` · `authority/engine.py:224` · `reco/engine.py:138-158` (**needs a `conn` parameter added — it has none**) · `live_qa` |
| **Dependencies** | none · **Prerequisites** WP-019 |
| **Implementation strategy** | Delete the fallback; make `conn` required. **The seam exists in two of four**, and `treatment/decisions.py:41-61` already states the contract. |
| **Acceptance criteria** | A rolled-back caller leaves **no** decision row. |
| **Risk** | **internal.** ⚠ **`conn` is one of the four threaded arguments the pipeline invariant depends on — hoisting it to module state would break the invariant silently, with no import error and no failing test** |
| **Rollback** | `git revert` · **Atomic?** Yes per engine |

---

### WP-038 — Complete the `work_runtime` port and put a `Protocol` on it

| | |
|---|---|
| **Category** | Architecture · **Severity** P1 · **Confidence** Certain |
| **Root cause** | The port exposes 3 operations; `adapter_pg` exposes 7. `clerk.py:17,18` imports port and concrete on **consecutive lines**, and `treatment/enact.py:702` + `sweep.py:243` insert into `work_runtime_jobs` **directly**. There is **no `Protocol`** — the two adapters agree only because `adapter_temporal` is three `raise` statements. |
| **Objective** | The flag can be flipped without a split-brain job queue. |
| **Affected files** | `work_runtime/api.py` (42 lines) · `agent_core/clerk.py:18` · `treatment/enact.py:702` · `treatment/sweep.py:243` |
| **Implementation strategy** | Add `list_jobs`, `claim_next`, `finish`, `park_input_required` to the port; add a `Protocol`; delete the two raw INSERTs. |
| **Acceptance criteria** | No module imports `adapter_pg` directly. |
| **Risk** | **internal.** **Do not flip `TEMPORAL_ENABLED` until this lands** — the day it flips, `start_workflow` routes to Temporal while the drain loop raises and two treatment paths keep writing a Postgres table nobody drains, **on financial instructions** |
| **Rollback** | `git revert` · **Atomic?** Yes |

---

### WP-039 — Split `bot_worker` by SLO

| | |
|---|---|
| **Category** | Reliability / architecture · **Severity** P2 · **Confidence** High |
| **Root cause** | One process serialises 15+ unrelated drains on a 1.5 s poll. |
| **Objective** | A slow Twilio call does not stall every other queue. |
| **Affected files** | `bot_worker.py` → `messaging_worker`, `dialer_worker`, `treatment_worker`, `integration_worker` · `docker-compose.yml` |
| **Dependencies** | WP-018, WP-040 |
| **Implementation strategy** | Extract branches; **same `process_one(engine) -> bool` contract, no schema change, no new broker.** Extend `_JOB_QUEUES` metrics. **Lock `treatment_followthrough.open_cases` before a second replica exists** — it has no row lock today. |
| **Acceptance criteria** | Four processes; each drains its own tables; queue depth is exported per queue. |
| **Risk** | **internal** · **Rollback** revert compose + code · **Atomic?** No |

---

### WP-040 — Claim → commit → carrier I/O, everywhere

| | |
|---|---|
| **Category** | Reliability / correctness · **Severity** P1 · **Confidence** Certain |
| **Root cause** | A side effect inside the claim transaction. **`statement_timeout` cannot fire** — no statement is executing while Python waits on the carrier. |
| **Objective** | A rollback never un-records a send that already happened. |
| **Affected files** | `treatment/enact.py:904-912,295-314` · `promise_fulfillment.py:1044-1064` · `payment_events.py:664-693` · `main.py:857-877` |
| **Dependencies** | WP-009 |
| **Implementation strategy** | **The precedent is in the same tree, five times over**: `cadence.process_one`, `campaigns.process_one`, `whatsapp_outbound.process_one`, `call_closer.process_one`, `webhooks_dispatch` all commit the claim before the carrier call. Copy `call_closer`'s three-phase shape. `await asyncio.to_thread(...)` the blocking `async def` routes, following `whatsapp_webhook_receive`'s pattern in the same file. **And set `idle_in_transaction_session_timeout` and `lock_timeout` beside `statement_timeout`** — that does not fix the findings; it converts an unbounded stall into a bounded, loud failure. |
| **Acceptance criteria** | No carrier call executes with a transaction open N frames up. |
| **Required tests** | A lint or test for the pattern — **the other fixes do not prevent the class from recurring** |
| **Risk** | **regulated**, in the safe direction · **Rollback** `git revert` · **Atomic?** Per site |

---

### WP-041 — Serialise `apply_goodwill`; persist the Mission ceiling

| | |
|---|---|
| **Category** | Correctness / money · **Severity** P1 · **Confidence** High |
| **Root cause** | Check-then-act in Python instead of a transactional claim. `_run` `SELECT`s with no `FOR UPDATE`; `mark_enacted` does not inspect rowcount; a swallowed exception leaves `enacted` false. Separately, the Mission ceiling narrows only the **in-memory payload**, and `apply_goodwill` re-reads the un-narrowed `approved_amount` from the row. |
| **Objective** | One decision posts at most one waiver, at the amount that was spoken. |
| **Affected files** | `authority/enact.py:40-88,160-185` · `authority/decisions.py:105-134` · `voice/tools.py:1469-1528` |
| **Implementation strategy** | `SELECT … FOR UPDATE` in the same transaction as the ledger insert; require `mark_enacted` rowcount == 1 or raise and roll back; **do not swallow that exception.** Persist the narrowed cap onto `authority_decisions`. Prefer a unique partial index on enacted decisions. |
| **Acceptance criteria** | Two concurrent `apply_goodwill` calls on one `decision_id` yield **one** ledger row. |
| **Required tests** | Needs **WP-019** — this is exactly the class `db_tx` cannot express |
| **Risk** | **regulated** (money) · **Rollback** `git revert` · **Atomic?** Yes |

---

# BAND 6 — The wire contract

---

### WP-042 — `response_model` on the 33 low-risk routes

| | |
|---|---|
| **Category** | API contract · **Severity** P2 · **Confidence** High · **Blocks WP-036** |
| **Root cause** | 178 of 314 routes declare no response shape, so the wire format lives inside `db.py` — the file WP-036 splits. **Carve first and you silently rewrite the public API.** |
| **Affected files** | `main.py` (14 `db.*`-direct + 19 dict-literal returns) |
| **Implementation strategy** | Target `/agent-studio` first — **26 routes, 0 with a `response_model`**, and dense enough to also be WP-045's first extraction. Verify each declared model matches what already ships. |
| **Risk** | **none** where the model matches · **Rollback** `git revert` · **Atomic?** Per subsystem |

---

### WP-043 — Type the 42 unvalidated write routes, money and grants first

| | |
|---|---|
| **Category** | API contract / security · **Severity** P2 · **Confidence** High |
| **Root cause** | 33 handlers take `dict[str, Any]`, 9 take a raw `Request`. |
| **Affected files** | `main.py:2464,2476` (**vault secrets**), `:2490` (**tool grants**), `:2857` (**RBAC** — `[str(x) for x in ids]` straight into `replace_role_permissions`), `:3835` (kill switches), `:3731` (**contact windows + PSTN**), the four payment routes |
| **Implementation strategy** | **This is a wire change.** Land the model with `extra="ignore"`, log rejections for one release, **then** tighten to `extra="forbid"`. Separately: **61 of the 247 existing models carry no `model_config` at all**, including `PromiseCreateRequest` and `PaymentPlanCreateRequest`. |
| **Risk** | **user-visible → regulated** (the Twilio route dials real PSTN numbers) |
| **Rollback** | Revert the model · **Atomic?** Per route |

---

### WP-044 — One error-code map

| | |
|---|---|
| **Category** | API contract · **Severity** P2 · **Confidence** High |
| **Root cause** | `_handle_write` has 82 call sites and maps `ValueError → 409`. `db.py` raises `ValueError` **83 times across 48 distinct codes**, and they are not one kind of thing — `bot_id_required` means *bad input* (422), `publish_conflict` means *someone got there first* (409). **Eleven of the literals are English sentences, not codes**, and `detail=str(exc)` makes them the public contract. |
| **Affected files** | `main.py:720-738` · `main.py:1311-1319` (`_handoff_call`, a stale copy missing the `IntegrityError` branch, so a constraint violation escapes as a **500**) |
| **Implementation strategy** | A `dict[str, int]` code→status table inside `_handle_write`, **defaulting to 409 so every unmapped code keeps today's behaviour.** Delete `_handoff_call`. |
| **Risk** | **user-visible, bounded** — `retryUnlessClientError` already treats all non-408/429 4xx as terminal, so frontend retry behaviour is unchanged either way |
| **Rollback** | Empty the table · **Atomic?** Yes |

---

### WP-045 — Six routers out of `main.py`

| | |
|---|---|
| **Category** | Maintainability · **Severity** **P3** · **Confidence** Certain |
| **Root cause** | 314 routes, zero `APIRouter`. |
| **Objective** | Merge-conflict surface and navigability. **Nothing else.** |
| **Affected files** | `main.py` → `agent_studio`, `outbound`, `twilio`, `treatment`, `eval`, `demo` (~75 routes, ~1,700 lines) |
| **Dependencies** | **Must NOT ship in the same release as WP-042's `/agent-studio` work** — both land on the same 26 routes |
| **Implementation strategy** | Mount with **no `prefix=`** so full paths stay in the decorators, authz keys stay byte-identical, and the diff is a pure move. **Leave the other 72 prefixes alone.** |
| **Acceptance criteria** | **An ORDERED-LIST route snapshot, diffed before and after** — not a set. |
| **Risk** | **internal, with one specific hazard.** ⚠ Five static routes are declared before their parameterised siblings and work **only because of it**, and `main.py:2216-2219` is a handler docstring warning about one. **A grouping pass — reads before writes — reverses the pair, and a set-based snapshot passes, `assert_registry_covers` passes, and the regression surfaces as `skill_not_found`, which nothing in CI exercises** |
| **Rollback** | `git revert` |
| **Atomic?** | Per router · **If the programme has to drop something, drop this** |

---

# BAND 7 — Frontend

---

### WP-046 — Delete the dead frontend surface

| | |
|---|---|
| **Category** | Dead code · **Severity** P2 · **Confidence** Certain (2 files verified; 27 inherited from two independent re-derivations) |
| **Objective** | Remove 2,843 lines **and re-scope three prior reports' remediation surface.** |
| **Affected files** | 22 `components/ui/*` (incl. `card.tsx` and `tooltip.tsx` — **verified zero importers**, both missed by report 07) · `BigBoundMark.tsx` + `styles.css` · `documents/StatusPill.tsx` · `records/index.ts` · `floor/AlertLane.tsx`, `floor/CallTile.tsx` · `sandbox/ScenarioList.tsx` · `hooks/use-mobile.tsx` · 22 npm deps |
| **Dependencies** | **Blocks WP-049.** Reports 27, 29 and 30 scope remediation to `components/ui/` — and **22 of those files are dead, including `ui/form.tsx`, which report 30 names as a correct primitive awaiting adoption.** It is not; it is deletable |
| **Implementation strategy** | **Batch 1** — kit: each wrapper **with** its exclusive npm dep and the lockfile, in one commit, or `npm ci` keeps pulling Radix packages nothing imports. `toggle.tsx` ← `toggle-group.tsx` is a closed two-node cluster: delete together or `tsc` breaks. `react-hook-form` **with** `@hookform/resolvers`; `date-fns` **not before** `react-day-picker` (verified ERESOLVE in the lockfile). **Batch 2** — orphans: delete `BigBoundMark.tsx` **with** its CSS, or the CSS becomes an unattributable orphan nobody dares remove. |
| **Acceptance criteria** | `tsc --noEmit`, `vitest run`, `npm run lint`, **and `npm run build`** (WP-001). |
| **Risk** | **none** for JS. ⚠ **Not verified for CSS**: Tailwind v4 scans source files and `ui/chart.tsx:51` carries a long `[&_.recharts-*]` arbitrary-variant string. The nominated gates **cannot observe Tailwind output.** Benign in expectation — **settle with a byte-diff of the built CSS** |
| **Rollback** | `git revert` + `npm ci` |
| **Atomic?** | **Yes per wrapper+dep pair.** No across batches |

> **⚠ Four config-loaded deps a sweep will take, none catchable by `tsc --noEmit`:** `vite-tsconfig-paths` and `nitro` (peers of the Vite config; nitro is `optional: true`, so **npm installs silently** and only `vite build` fails), `tw-animate-css` (`styles.css:3`, a CSS `@import` by package name — animations stop with no JS error), and `sharp` (`scripts/gen-icons.mjs:25`, `await import()` inside a friendly `try`).
>
> **⚠ The `styles.css` range is wrong in the source roadmap.** It says `1638-1674`. **Verified: the `.bb-mark` block ends at 1670; line 1672 opens `@keyframes pulse-ring`, which is live and consumed at `:1835`.** Executing the range literally leaves a truncated keyframe and a **syntactically broken stylesheet**. **Correct range: 1638-1670.**

---

### WP-047 — `RecordsTable` and `FilterTable` gain an error state

| | |
|---|---|
| **Category** | Correctness (UX) · **Severity** P1 · **Confidence** Certain |
| **Root cause** | `RecordsTable` accepts `isLoading` and `emptyMessage` and **has no `isError` prop at all.** There is nowhere to put a failure. **The abstraction is the reason the fix does not generalise.** |
| **Objective** | A failed read stops rendering as a statement of fact. |
| **Affected files** | `records/RecordsTable.tsx` · `FilterTable.tsx` (**which lacks `isLoading` too**) · ~20 adopters |
| **Implementation strategy** | Add the prop; thread it from the adopters. **Fix the four compliance surfaces by hand first** — `consent.tsx:46`, `compliance.tsx:57`, `ApprovalsQueue.tsx:7`, `LedgerTab`/`EmiTab` — because those are the ones where "empty" is a factual claim about a borrower. |
| **Acceptance criteria** | Airplane-mode each list page; **none may show an empty-state lecture.** |
| **Risk** | **user-visible**, in the safe direction |
| **Rollback** | `git revert` · **Atomic?** Table components first, then per consumer |

> **The consent registry currently says *"No consent records match the current filters."* when the API failed — about the dataset that determines whether this company may lawfully telephone someone. `PaymentPlansTable` goes further and issues an instruction: create a plan. An agent who follows it may create a duplicate.**

---

### WP-048 — Move domain types out of `data/*-seed.ts`, then parse at `apiGet`

| | |
|---|---|
| **Category** | API contract · **Severity** P1 · **Confidence** Certain |
| **Root cause** | `src/types/` exports **zero** domain types; `src/data/*-seed.ts` exports **261**. `api/customers.ts:29` returns `apiGet<Customer[]>` where `Customer` is declared in the **mock fixture**. **229 unchecked casts, 0 runtime validations** — and the lie is already live: `InteractionResponse.summary` is `str | None` on the wire and `string` in TypeScript. |
| **Objective** | A backend field rename stops being invisible to `tsc`. |
| **Affected files** | 26 `src/data/*-seed.ts` · 31 `src/api/*` modules · `api/config.ts:183` |
| **Dependencies** | **Blocks WP-049** — deleting the mock branch deletes the module that declares `Customer` |
| **Implementation strategy** | **Types first** — a pure type-level move, so `tsc --noEmit` catches every mistake; **the lowest-risk frontend change available.** Then the **optional third parameter**: `apiGet<T>(path, init?, schema?)`, so 221 call sites keep working and one module migrates per commit. **Start with the six raw-row `/outbound` endpoints**, where `api/outbound.ts:301-307` has already documented in prose that the raw field names *are* the contract. |
| **Acceptance criteria** | No `api/*` module imports a type from `data/`. A deliberately-wrong payload fails closed. |
| **Risk** | **type move: none.** **Parse: real** — a schema stricter than reality turns a working screen into a thrown `ZodError`. Mitigate with `.safeParse` + `console.warn` + pass-through for one release, then flip |
| **Rollback** | Drop the argument at the call site · **Atomic?** Per module |

---

### WP-049 — `USE_MOCK` out of `components/` and `routes/`

| | |
|---|---|
| **Category** | Maintainability · **Severity** P2 · **Confidence** High |
| **Root cause** | 26 of 378 references sit outside `api/`. The sharpest is `routes/callbacks.tsx:83`, which asks *"are we mocked?"* when the real question is *"did `/staff` return rows?"* — so a live backend with an empty `/staff` renders an empty assignee dropdown with no error. |
| **Dependencies** | **WP-046, WP-048** |
| **Implementation strategy** | Return the capability from `api/`; let `USE_MOCK` stay in `api/config.ts`. **Screen by screen, and only for screens someone can eyeball** — near-zero test coverage. |
| **Risk** | **user-visible** · **Rollback** `git revert` · **Atomic?** Per screen |

---

### WP-050 — Route the seventh `fetch` through `authHeaders`

| | |
|---|---|
| **Category** | Correctness · **Severity** P2 · **Confidence** Certain |
| **Root cause** | `routes/sandbox.lazy.tsx:432` is a raw blob `fetch` with no auth headers, no `credentials`, and no timeout, while `apiGetBlob` already does all three. **It is the only network call outside `src/api/` in the entire frontend.** |
| **Implementation strategy** | One line. Restores the one-transport property. |
| **Risk** | **user-visible** — the export currently 401s in any keyed environment |
| **Atomic?** | Yes |

---

### WP-051 — Two keyboard-blocked tasks

| | |
|---|---|
| **Category** | Accessibility · **Severity** P2 · **Confidence** Certain |
| **Root cause** | A state transition whose only trigger is `onDrop`. |
| **Affected files** | `routing/RuleList.tsx:79` (**routing rule priority** — which rule wins) · `qa/CoachingBoard.tsx:52-57` (a coaching action; the click escape hatch only raises a toast) · `RecordsTable.tsx:234` + `floor/LiveTable.tsx` (**selecting a live call — the most-used action on the floor**) |
| **Implementation strategy** | Move up / move down in the overflow menu; a status control on the coaching card; a focusable control in the identity cell. **Of six drag surfaces, four already have a verified keyboard alternative** — this is two gaps, not a policy failure. |
| **Risk** | **user-visible** · **Atomic?** Per surface |

---

### WP-052 — Connect 105 labels that are already written

| | |
|---|---|
| **Category** | Accessibility · **Severity** P2 · **Confidence** Certain |
| **Root cause** | A `Field` helper cloned into six business forms: three render a real `<Label>` with **no `htmlFor`**, three use a plain `<div>`. |
| **Objective** | 295 controls have no accessible name; **105 of them have a visible label sitting right beside them.** The words are written; they are not connected. |
| **Affected files** | `PromiseSheet.tsx:240` · `PlanBuilderSheet.tsx:248` · `ActionSheets.tsx:305` · `DisputeSheet.tsx:509` · `NewRequestSheet.tsx:185` · `RequestSheet.tsx:366` |
| **Implementation strategy** | Fix the six `Field` helpers to generate an id and pair `htmlFor`. **Do not adopt `ui/form.tsx` — it is dead code (WP-046).** Build the pattern from `useConfirm`, which is adopted correctly at 7 of 7 call sites. |
| **Acceptance criteria** | Tabbing the promise sheet announces "Amount (₹)", not "edit, blank". |
| **Risk** | **none** · **Atomic?** Per helper |

---

# BAND 8 — Infrastructure and hygiene

---

### WP-053 — A CI import-boundary test

| | |
|---|---|
| **Category** | Architecture · **Severity** P2 · **Confidence** High |
| **Root cause** | The image boundary is **additive, not exclusive** — `requirements.txt` (with `fastapi`) is in the base layer of every image, so `voice/twilio_ops.py:93 → voice/ws_proxy → fastapi` costs nothing **only because packaging masks it**. |
| **Implementation strategy** | `python -c "import main"` and `python -c "import worker"` in the base image **with pipecat and fastembed absent**, asserting no `ImportError`. One CI step. |
| **Objective** | Convert "masked by packaging" into "caught by a test", with **no restructuring at all**. |
| **Risk** | none · **Atomic?** Yes |

---

### WP-054 — `-c requirements.txt` on the voice install

| | |
|---|---|
| **Category** | Supply chain · **Severity** P2 · **Confidence** Certain |
| **Root cause** | `Dockerfile:41` installs `requirements-voice.txt` on top of the base with no constraint file. **The api image and the voice image, built from one commit, do not have the same library versions, and nothing records what either got.** |
| **Implementation strategy** | Add the flag. **Expect it to fail on first application** (`ruff==0.6.9` vs pipecat's `cli` extra's `ruff>=0.12.1`) — **that failure is the finding.** |
| **Risk** | internal · **Atomic?** Yes |

---

### WP-055 — A Python lockfile from a 3.12 resolve

| | |
|---|---|
| **Category** | Supply chain · **Severity** P2 · **Confidence** Certain |
| **Root cause** | 21 declared dependencies, 134 installed — **114 (85%) constrained nowhere**, including `cryptography`, `pyopenssl`, `urllib3`, `requests`, `aiohttp`, `certifi`. And the venv the pins were taken from runs **Python 3.14** while the image and CI run 3.12, so environment markers resolve differently. |
| **Implementation strategy** | Generate a lockfile with hashes from a **3.12** resolve. Add `requires-python = ">=3.12,<3.13"` to `pyproject.toml` in the same change — **that makes the interpreter mismatch impossible to recreate**, and it is the cheapest mitigation for the largest finding. |
| **Risk** | internal · **Atomic?** Yes |

---

### WP-056 — One dependency-vulnerability gate

| | |
|---|---|
| **Category** | Supply chain · **Severity** P2 · **Confidence** Certain |
| **Root cause** | No `npm audit`, `pip-audit`, OSV, Trivy, Bandit, Semgrep, CodeQL or Dependabot anywhere. **A CVE disclosed tomorrow would be noticed by no mechanism in this repository, ever.** |
| **Implementation strategy** | `npm audit --audit-level=high` and `pip-audit`. Two steps. **Delete `Habibi/bun.lock` and add `packageManager` first** — it is 39 days stale, diverges on 206 packages, is missing the entire Pipecat voice stack, resolves *older* versions of the five packages `npm audit` flags, and **`npm audit` cannot read it**, so the gate would be blind to that tree. |
| **Risk** | none (introduce green) · **Atomic?** No |

---

### WP-057 — Bump `nltk` and pre-bake its data

| | |
|---|---|
| **Category** | Supply chain · **Severity** P2 · **Confidence** High |
| **Root cause** | `nltk 3.10.0` is a **core** requirement of `pipecat-ai==1.6.0` with **21 advisories**, essentially all fixed in 3.10.3 — and `pipecat/utils/string.py` calls `nltk.download("punkt_tab")` at **module scope**, on the sentence-boundary detector for bot speech. |
| **Implementation strategy** | `nltk>=3.10.3` (comfortably inside pipecat's `<4`), and `aiohttp>=3.14.3` in the same change. **Independently, pre-bake `nltk_data` or set `NLTK_DATA`** — no production container should perform a network download at process start, least of all behind a bank's egress proxy. |
| **Risk** | internal · **Atomic?** Yes |

---

### WP-058 — Add `PRAXIST-main` to the submission-zip skip list

| | |
|---|---|
| **Category** | Legal · **Severity** P2 · **Confidence** Certain |
| **Root cause** | `_make_submission_zip.py:100` walks `ROOT.rglob("*")` and `SKIP_DIR_NAMES` (`:11-31`) does not contain `PRAXIST-main`. Running it produces a zip containing all **4,518** files of a **revenue-gated Fair Source** licensed project and hands them to a third party — redistribution under §1.2.3. |
| **Implementation strategy** | One line. **The same script is already careful about secrets** (`SKIP_ENV_NAMES` under `# Never ship secrets`), so the pattern exists. |
| **Risk** | none · **Atomic?** Yes |

---

### WP-059 — Container hardening

| | |
|---|---|
| **Category** | Security · **Severity** P2 · **Confidence** Certain |
| **Root cause** | Zero matches for `USER|mem_limit|cpus|read_only|cap_drop|security_opt` in either compose file or the Dockerfile. **All four process types run as root**; no service of eight has a memory or CPU limit; healthchecks cover 4 of 8. |
| **Implementation strategy** | Non-root `USER`; resource limits; healthchecks on the four workers; drop `build-essential` to a builder stage (it survives into the **voice** image today, which is the container that terminates borrower calls); split the `env_file` per service; add `tests/` to `.dockerignore`. **The vendored `PRAXIST-main/services/product_usage/Dockerfile` already does the digest-pin and non-root user correctly — the pattern is in-tree.** |
| **Risk** | internal · **Atomic?** No |

---

### WP-060 — Rotate MinIO defaults; fix `MINIO_SECURE`

| | |
|---|---|
| **Category** | Security · **Severity** P2 · **Confidence** Certain |
| **Root cause** | `.env:48-49` uses `minioadmin`/`minioadmin`, which its own template forbids in terms. And **`MINIO_SECURE=on` disables TLS** — `"on"` is not in that site's truth set while it is in 20 of the other 26. |
| **Implementation strategy** | Rotate. Set `MINIO_SECURE=true`, **not `on`**, until `env_bool` exists. Then add `env_bool` to `env_utils` and route all 26 sites through it. |
| **Risk** | internal · **Atomic?** No |

---

### WP-061 — Add `Habibi/.env.production` to `.gitignore`

| | |
|---|---|
| **Category** | Security hygiene · **Severity** P3 · **Confidence** Certain |
| **Root cause** | `Habibi/.gitignore` covers only `*.local`; the root covers `**/.env` and `**/.env.local`. **Nothing covers `Habibi/.env.production`**, which would therefore be committed. `backend/.gitignore:5` has the general `.env.*` rule and a comment explaining why it was needed. |
| **Risk** | none · **Atomic?** Yes |

---

### WP-062 — Delete `backend/.env.bak.reco`

| | |
|---|---|
| **Category** | Security hygiene · **Severity** P3 · **Confidence** Certain |
| **Root cause** | A byte-for-byte prefix of `.env` holding the Meta token, the WhatsApp app secret, both Azure keys, the Twilio auth token, the MinIO pair, the WS proxy secret and the DSN. Correctly gitignored (by `backend/.gitignore:5`'s `.env.*` — the root pattern alone would **not** have caught it) and never committed. **The risk is rotation drift**: rotating a key in `.env` leaves the old one here, under a filename no scanner keys on, in the same directory. |
| **Risk** | none · **Atomic?** Yes |

---

### WP-063 — Delete the `[tool.vulture]` block

| | |
|---|---|
| **Category** | Hygiene · **Severity** P3 · **Confidence** Certain · Configures a tool that is in no requirements file. 19 lines. **Risk** none |

---

### WP-064 — Delete `AGENT_CARDS_ENABLED`

| | |
|---|---|
| **Category** | Dead code · **Severity** P3 · **Confidence** Certain (verified: definition + `.env.example:309` + 3 test references, **zero application readers**) |
| **Implementation strategy** | Remove from `platform_flags.py`, `.env.example` **and `tests/test_platform_flags.py`'s parametrize in the same commit** — `platform_flags.py:1-4` states the flag list is a contract. **Do this after a deploy-manifest sweep**: a stale name in a running deployment becomes an unrecognised variable, silently. |
| **Risk** | none — **but do not generalise this to `CAMPAIGN_RUNTIME_ENABLED`, which report 07 lists in the same table and which is LIVE.** See CONFLICTS §C1 |
| **Atomic?** | Yes |

---

### WP-067 — The frontend roster calls an archived bot active

| | |
|---|---|
| **Category** | Correctness (display) · **Severity** P3 · **Confidence** Certain |
| **Root cause** | Found while executing `WP-005`. `Habibi/src/api/staff.ts:62` hardcodes `{ id: "webchatbot", name: "WebChatBot", kind: "bot", team: null, status: "active" }`. In the database that bot holds **no prompt version and no deployment row**, and `backend/seed_postgres.py:637` archives it on purpose: *"they cannot take a call and never could."* The frontend asserts a liveness the backend denies. |
| **Objective** | The roster does not describe a bot as active when nothing can route to it. |
| **Affected files** | `Habibi/src/api/staff.ts:62` (and `collectionsbot-v2-4` if it appears in the same list) |
| **Dependencies** | none · **Prerequisites** none |
| **Implementation strategy** | Decide first whether this list should be hardcoded at all — the same seed comment records that *"shipping them onto the Agent Studio fleet index as live cards was the whole reason the page read as filler."* The minimum fix is to mark both archived. The better fix is to source the roster from the API that already knows. |
| **Acceptance criteria** | No bot renders as `active` unless it has a deployment. |
| **Risk** | **none** — display only · **Rollback** `git revert` · **Atomic?** Yes |

> A hardcoded status is a claim nobody re-checks. This one has already been wrong for as long as the bot has been archived.

---

### WP-068 — Two tests read "today" in the wrong timezone

| | |
|---|---|
| **Category** | Testing · **Severity** P1 · **Confidence** Certain (reproduced both ways) |
| **Root cause** | `tests/test_conversation_trace_regressions.py:252` asserts `_promise_date_is_past(date.today().isoformat()) is False`, and `tests/test_promise_fulfillment.py:240` creates a promise with `days=0`. Both take "today" from the **process** timezone. The guard they are testing, `agent_core/tools/domain.py::_promise_date_is_past`, takes it from the **tenant's** — IST. Between **18:30 and 24:00 UTC** the two disagree by one day, so a promise dated "today" is already yesterday to the guard and is refused with `promise_date_in_past`. |
| **Objective** | A test of an IST rule reckons the day in IST. |
| **Affected files** | `tests/test_conversation_trace_regressions.py:252` · `tests/test_promise_fulfillment.py:240` (the `days=0` case only) |
| **Dependencies** | none · **Prerequisites** none |
| **Implementation strategy** | Take today from the same clock the guard uses — `datetime.now(ZoneInfo("Asia/Kolkata")).date()`, the shape `test_contact_policy.py::_today_ist` already uses — rather than `date.today()`. Do **not** "fix" this by widening the guard: the guard is correct and the tests are wrong. |
| **Acceptance criteria** | Both pass inside `collections_voice` (UTC) at any hour, including between 18:30 and 24:00 UTC. |
| **Risk** | **none** — tests only · **Rollback** `git revert` · **Atomic?** Yes |

> **Measured 2026-09-03 at 22:23 UTC**, with the container reporting `date.today() = 2026-09-03` against an IST today of `2026-09-04`: both tests **fail in the container and pass on the host**, on identical code. This is the same family as `WP-011` — a test that is only correct while two clocks happen to agree — and it is why the baseline's *NOT FAILURES* section now has a third entry. CI running in UTC goes red for 5½ hours a day for no reason.

---

### WP-066 — Give the expiry scanner a named allowlist

| | |
|---|---|
| **Category** | Testing · **Severity** P2 · **Confidence** Certain |
| **Root cause** | Shipped with `WP-011` (`b30fa8f`). `tests/test_dated_constants.py` flags **already-past** ISO constants, and the only thing keeping `PROTOCOL_VERSION = "2025-11-25"` green is `_VERSION_NAME = re.compile(r"VERSION", re.I)` — a blanket, permanent, undocumented exemption for **every** constant whose name contains "VERSION", a real expiry named `LICENSE_VERSION_VALID_UNTIL` included. `_SKIP_ASSIGN_NAMES = {"NOW"}` is the same shape and is now dead: `NOW` is matched by `_ASSIGN_CTOR`, which is future-only. |
| **Objective** | An exception to the expiry net is a written, reviewed decision rather than a name that happens to match a regex. |
| **Affected files** | `backend/tests/test_dated_constants.py` only |
| **Dependencies** | none · **Prerequisites** none |
| **Implementation strategy** | Add `_ALLOWLIST` keyed by `(relative_path, identifier)` → a reason written as a sentence. Seed with exactly one entry: `agent_core/mcp_http/protocol.py` :: `PROTOCOL_VERSION`, an MCP specification revision that is shaped like a date and will never lapse. Delete `_SKIP_ASSIGN_NAMES`, `_VERSION_NAME` and `_skip_assign`. Give `hits_in` an optional `rel`, consulted only when supplied, so synthetic snippets in the pin tests are unaffected. Record **WP-032** in the file as the owner of the deliberately-unflagged lapsed Fish TTS date. |
| **Acceptance criteria** | The `PROTOCOL_VERSION` snippet is a hit **without** `rel` and clean **with** it — which is what proves the allowlist, not a name regex, is doing the work. |
| **Risk** | **none** — one test file |
| **Rollback** | `git revert` · **Atomic?** Yes |

> A legitimate historical marker — `MIGRATION_CUTOVER = "2026-01-15"` — now fails this scanner with no sanctioned way to record that a human reviewed it. The next engineer will delete the test or quietly append to `_SKIP_ASSIGN_NAMES`. **Both are the class reopening through the door the test was built to close.**

---

### WP-065 — Add the two newer flags to `test_platform_flags`

| | |
|---|---|
| **Category** | Hygiene · **Severity** P3 · `OUTBOUND_EVAL_GATE_ENABLED` and `CAMPAIGN_RUNTIME_ENABLED` are absent from the parametrize that locks the factory flag list. A cheap lock so the next name cannot land undocumented. **Risk** none |

---

## Sequencing summary

| Band | Gate to enter | Dominant risk | Parallel with |
|---|---|---|---|
| **0** — release identity | none | none | 1 |
| **1** — the regulated one-liners | WP-005 gates WP-004 only | **regulated**, all in the safe direction | 0, 2 |
| **2** — shut the envelope | WP-012 → WP-013 | **regulated** | 3 |
| **3** — make the ground safe | WP-011 | none (tests only) | 2 |
| **4** — canonicalize | **0, 1, 2, 3** | **regulated** | — (serialise) |
| **5** — structural | WP-035, WP-016, WP-042 | internal (**silent security downgrade**) | 6, 7, 8 |
| **6** — wire contract | WP-024 | user-visible → regulated | 5, 7 |
| **7** — frontend | **WP-046 first** | user-visible | 5, 6, 8 |
| **8** — infrastructure | none | none | 5, 6, 7 |

**Three "do not do this until X" gates, each measured:**

1. **Do not ship any refactor until WP-001.** Today "roll it back" is not an executable instruction.
2. **Do not refactor SQL-emitting code until WP-016.** A dropped predicate returns another tenant's borrower records **with a 200** — a reportable breach you cannot un-disclose, and per WP-017 nothing logs it.
3. **Do not move any indented import until someone has documented why it is where it is.** 2,131 function-local imports and 66 `# noqa: E402` markers, and `ruff.toml` explains why: *"These modules set `DB_PROCESS_ROLE` / `sys.path` / `load_env()` before importing db… Moving those imports to the top binds config too early."*

**And four things this backlog will not schedule**, each with a stated reason in [TARGET-ARCHITECTURE.md](./TARGET-ARCHITECTURE.md) §6: a repository/DAO layer, a service layer, an ORM, and a vocabulary alignment. **A rename here is a data migration, not a refactor.**
