# 06 — Duplication forensics

**Scope:** `Habibi/src` and `backend/` (product). Guest tree `PRAXIST-main/` is out of scope.
**Date:** 2026-09-02
**Mode:** read-only. No source, config, or git was changed except this file.
**Companions:** `01-repository-xray.md`, `02-domain-capability-map.md`, `03-frontend-architecture.md`, `04-backend-architecture.md`, `architecture-forensics.md`

Vocabulary is `CONTEXT.md`: Mouth, Agent Card, Skill Pack, Locked Engine, Tool Grant, Offer, Gate, Flow, Handoff, Mission, Cadence, Outcome.

---

## Verdict

**The dangerous duplicates are not copy-pasted UI. They are competing answers to one regulated question.**

jscpd measured 41 TypeScript clones (602 lines, 0.61% of `Habibi/src`) and 134 Python clones (2709 lines, 1.80% of `backend/`). That is the token layer. The product's real duplication sits *below* jscpd: the same domain concept implemented under different names, in different languages, or behind a mock that still runs on a live screen.

The highest-blast clusters all share one shape:

1. A canonical owner already exists (`contact_policy.admit`, `agent_core/tools/grant.py`, `money_inr`, `call_closer.BUSINESS_OUTCOMES`).
2. Production still runs the older copies.
3. The copies have already drifted — or are pinned equal by a test that exists because they *would* drift.

Two accepted ADRs name the worst case. ADR-0001 requires one owner for the Tool Grant; `grant.py` still says “Nothing imports this yet.” ADR-0002 requires a cardless Mouth to be granted nothing; production still fail-opens onto `create_promise_to_pay`.

The healthy pattern is already in the tree: `contact_window.py` and `money_inr.py` are leaf modules that closed prior copy-drift. Consolidation should copy that move — wire the owner, delete the copies — not invent an eighth formula.

---

## Method

Six parallel read-only analysts, then a verification pass that re-read every P0/P1 claim from source. Several syntactic “exact” clones were downgraded to drifted-rule once both bodies were compared.

| Analyst | What it looked for |
|---------|--------------------|
| Syntactic clone detector | Exact / near / structural copies. `npx jscpd` on `Habibi/src` and `backend/` (tests, alembic, fixtures discounted as noise). |
| Semantic duplication analyst | Same domain concept under different names or languages. |
| Frontend duplication analyst | Copied components, hooks, API clients, query/mutation homes, mock policy. |
| Backend duplication analyst | Serializers, SQL, retry, auth layers, persist islands, `process_one`. |
| Business-rule duplication analyst | Locked Engine predicates, admit(), Outcome vocabularies, Cadence vs retry. |
| Integration/provider duplication analyst | TTS/STT/LLM, Twilio, WhatsApp, circuit breakers, webhook signatures. |

**In scope:** production Python and TypeScript. Tests cited as consumers or pins, not as clone sources.
**Out of scope:** `PRAXIST-main/`, `node_modules/`, `.venv/`, generated `routeTree.gen.ts` internals, seed JSON noise.

**Rule applied throughout:** two functions are not duplicates because they look similar. They are duplicates when they answer the same domain question and a patch to one would leave the other wrong. Naming collisions (four meanings of “Offer”) are recorded separately so they are not merged.

---

## Taxonomy

| Type | Meaning |
|------|---------|
| **exact** | Token-identical (or jscpd-identical) block. |
| **near** | Same algorithm, renamed identifiers or small edits. |
| **structural** | Same AST / UX shell; literals or domain actions differ. |
| **semantic** | Same domain concept, different names or languages. |
| **drifted-rule** | Intended to be the same rule; predicates or defaults already disagree. |
| **competing control plane** | Same provider or capability, two orchestrators (not the same function). |
| **naming collision** | Same English word, different questions. **Not a duplicate.** |

**Functional equivalence:** `yes` (safe to collapse) / `partial` (same job, different branches) / `no` (must not merge).

---

## Already consolidated — do not re-open

These were real duplicates and have a leaf owner now. Remaining copies are thin wrappers or documented mocks.

| Concern | Owner | What is left |
|---------|-------|----------------|
| Preferred-window *math* (IST hour vs HH:MM–HH:MM) | `backend/contact_window.py` | Display strings and a consent-hours parser still drift (DUP-06, DUP-05). |
| INR grouping / compact ladder (Python) | `backend/money_inr.py` | TypeScript still forks (DUP-12). |
| Customer 360 contactability | `GET /customers/:id/contact-policy` via `ContactabilityPill.tsx` | Consent screen and callback sheets still recompute in the browser (DUP-02). |
| Authority *live* panel | `GET /authority/next` | `USE_MOCK` still re-codes the matrix (DUP-10). |
| Product eligibility evaluator | `capture.evaluate_product_eligibility` | Reco and tools wrap it; they are not a second engine. |

---

## P0 — Competing answers to a regulated question

### DUP-01 — Tool Grant (seven live formulas; ADR owner unused)

**The question:** which tools may this Mouth execute, and which subset is the Offer this turn?

**Similarity:** semantic + drifted-rule. Three flow-control *literals* are near copies pinned by test.

**Implementations**

| # | Site | Role |
|---|------|------|
| 1 | `agent_core/skills/intersect.py` `effective_tools` | Live grant. Unions connectors. No channel filter. |
| 2 | same file `idle_offered_tools` | Idle Offer. |
| 3 | same file `offered_tools` | Active-skill Offer. |
| 4 | `agent_core/cards/compile.py` G9 `allowed_scope` (~734) | Publish Gate. `include \| locked \| PLATFORM_SKILL_TOOLS`. **No catalog intersect, no connectors, no `VOICE_ALWAYS`.** |
| 5 | `bot_tools.TOOL_DEFINITIONS` via `bot_runtime.py` | Text cardless fallback. |
| 6 | `voice/tools.py` `ALWAYS_ON` (80–94), applied ~2911 `keep = allowed \| ALWAYS_ON` | Voice keep-set union. |
| 7 | `sandbox_runtime.py` `_SANDBOX_TOOL_NAMES` | Sandbox cardless fallback. |
| owner | `agent_core/tools/grant.py` `ToolGrant` | ADR-0001. **No production import.** File still says “Nothing imports this yet.” |

Runtime path is `MouthTurn.tools()` (`agent_core/skills/runtime.py` 182–204) → `effective_tools`, not `ToolGrant`. Cardless:

```182:185:backend/agent_core/skills/runtime.py
    def tools(self, *, catalog_names: set[str] | None = None) -> ToolState:
        """What this turn may execute, and what to put in front of the model."""
        if self.card is None:
            return ToolState(allowed=None, offered=None)
```

`ToolState.has_grant` documents `None` as **no filtering** (fail-open). ADR-0002 requires deny-all.

**Flow-control floor (three statements of one set)**

| Literal | Members |
|---------|---------|
| `grant.VOICE_ALWAYS` | 9 flow verbs + `capture_call_goal` + `verify_identity` |
| `voice.tools.ALWAYS_ON` | Equal to `VOICE_ALWAYS` (pinned `tests/test_tool_grant.py`) |
| `flow_graph._FLOW_CONTROL_TOOLS` | 10 verbs; **omits `capture_call_goal`** |

The triple exists because the API process cannot import `voice.tools` (pipecat). That is a real constraint, not sloppiness. The pin must outlive the characterization suite.

**Functional equivalence:** **no.** Characterization (`tests/test_tool_grant_characterization.py`) records: G9 permits unreachable names (`evaluate_live_qa`, `recommend_treatment`); omits connectors the runtime would grant; cardless fallbacks still contain `create_promise_to_pay`.

**Divergence risk:** **critical.** Publish Gate can fail a pack the runtime would pass (`ext.*`). A cardless Mouth can write a PTP. Mid-call **Handoff** filters the tool registry once at session start (`voice/bot.py`) and would keep the handing-off agent's grant — ADR-0001 names this as a prerequisite for Handoff, not a cleanup.

**Canonical:** `agent_core/tools/grant.py` *after* call sites migrate. Until then the live grant is `intersect.effective_tools` + voice `ALWAYS_ON`.

**Consumers:** voice pipeline, WhatsApp `bot_runtime`, sandbox, compile G9, flow editor catalog.

**Migration risk:** **high.** Characterization lists a sequence (voice literal → channel filter → G9 → delete old formulas → deny-all last). Wiring `ToolGrant` without removing `| ALWAYS_ON` would hide a seventh formula.

**Consolidation:** migrate callers onto `ToolGrant.for_bundle` / `may_execute` / `static_grant`. Replace G9's private `allowed_scope` with `static_grant` (publish = union of runtime). Delete cardless fallbacks; branch on `is_cardless`. Keep one `VOICE_ALWAYS` leaf the API *can* import; voice and `flow_graph` consume it. Do not add an eighth formula.

---

### DUP-02 — “May we contact this borrower now?”

**The question:** `contact_policy.admit()` — purpose, blocking consent, customer DND, published-or-RBI voice hours, preferred window ∩ consent hours, cooling-off, daily/weekly cap.

**Similarity:** drifted-rule (same question, different predicates).

**Implementations**

| Site | What it actually tests |
|------|------------------------|
| `contact_policy.py` `admit` / `_veto` | Owner. `RBI_VOICE_START=8`, `END=19`. Can use a published `calling_window`. Intersects `allowed_hours` ∩ `preferred_window`. |
| `Habibi/src/api/contact-policy.ts` mock | Restates 8/19. Documents that it skips cooling-off, caps, `dnd_registry`, promotional purpose. |
| `Habibi/src/data/consent-seed.ts` `isContactableNow` / `contactableSummary` | **Live Consent screen** (`ConsentTable`, `ContactablePill`, `ConsentStatsStrip`). Operator-local `Date.getHours()`. **No RBI default.** Uses the record's window only. |
| `Habibi/src/data/callbacks-seed.ts` `isWithinDndWindow` | **Live** CallbackSheet / NewCallbackSheet. Browser-local clock; default 09–20. |
| `agent_core/live_qa/checks.py` `check_hours` | Imports RBI constants. Restates `START <= hour < END`. Outbound voice only; **ignores published windows**. |
| `agent_core/live_qa/scorecard.py` | Same constants; inbound/simulated skip **differs** from live check. |
| `agent_core/treatment/timing.py` `_window_for` | Plans voice as hardcoded 8–19 ∩ consent, not `rules.calling_window`. Enact still calls `admit()`. |

Customer 360 `ContactabilityPill.tsx` (9–21) already asks the owner. Consent and callbacks did not follow.

**Functional equivalence:** **partial** on the 8–19 bound when no published rule exists; **no** once a published window, cooling-off, caps, or timezone enters. Preferred window 09–20 (`contact_window`) is a *different* rule from RBI 8–19 — a 19:30 IST callback is in-window for preference and blocked for voice outreach.

**Divergence risk:** **critical (contact/consent).** Consent table can show green while the dialler vetoes, or the reverse. An agent outside IST reschedules a callback into quiet hours. Live QA can barge (or not) on a window admit would honour.

**Canonical:** `contact_policy.admit` / `evaluate`. Live QA is a detector, not a second Gate. `contact_window` owns *borrower preference* only.

**Consumers:** outbound, Cadence (re-checks admit at fire time), treatment enact, PTP confirms, bounce SMS, C360 pill, Consent UI, callback sheets.

**Migration risk:** **high** for Consent/callback UI (need a proposed-slot evaluate API). **Low** for live_qa/timing (import `calling_window` or call `evaluate(now=…)`).

**Consolidation:** delete client verdicts on live screens. Consent and callbacks render `admit`/`evaluate`. Point live QA and treatment timing at the same published window. Keep the mock only if it hits the API.

---

### DUP-03 — `BLOCKING_CONSENT` restated three times

**The question:** which channel-consent statuses forbid contact.

**Similarity:** exact (identical frozenset).

```37:37:backend/contact_policy.py
BLOCKING_CONSENT = frozenset({"opted_out", "dnd", "expired"})
```

Same literal: `promise_fulfillment.py:29`, `payment_events.py:28`.

**Functional equivalence:** **yes** today.

**Divergence risk:** **high.** Adding `withdrawn` to one set silently desyncs dials vs PTP confirms vs bounce receipts.

**Canonical:** `contact_policy.BLOCKING_CONSENT` (that module already owns `_consent_reason`).

**Consumers:** `_veto`; PTP confirm channel pick; payment-event SMS vs WhatsApp.

**Migration risk:** **low.**

**Consolidation:** import the frozenset; keep local `_channel_blocked` helpers. Pin with a test that all three effective sets stay identical. These helpers are **not** a second `admit()` — they pre-pick a channel; fulfillment still calls `admit` after.

---

### DUP-04 — Two columns for one DND fact

**The question:** is this party on DND?

**Similarity:** semantic (one fact, two stores).

**Implementations:** `customers.dnd` vs `consent_records.dnd_registry`. `admit` ORs them (`contact_policy.py` ~504). Treatment features do the same OR. `patch_consent` dual-writes when either field is present. `_callback_dnd_active` (`db.py` ~1826) reads **`customer_dnd` only**.

**Functional equivalence:** **partial.** Dual-write on the consent patch path; other mutations may not.

**Divergence risk:** **high.** A one-sided write produces a ghost DND or a missed block. Callbacks can disagree with outreach veto.

**Canonical:** one column, or dual-write on every mutation with a check that they match.

**Consumers:** `admit`, treatment features, consent roster, callback DND chip.

**Migration risk:** **high** (data repair).

**Consolidation:** pick one store; backfill; make `admit` and callback DND read the same field. Channel status `"dnd"` in `BLOCKING_CONSENT` is a **different axis** (per-channel consent vs registry flag) — do not merge those tokens.

---

### DUP-05 — Allowed-days parser (Gate vs consent write)

**The question:** which weekdays does this consent row allow.

**Similarity:** near (jscpd-shaped copy). **Not functionally equivalent.**

| | `contact_policy._parse_days` (~220–246) | `db._parse_allowed_days` (2038–2054) |
|--|----------------------------------------|--------------------------------------|
| Empty | `None` (no day restriction) | `[1,2,3,4,5]` (Mon–Fri default) |
| En-dash `Mon–Sat` | Normalizes `–`/`—` → `-`, then range | **Does not normalize**; `"mon–sat"` collapses to Monday only |

The contact_policy comment exists because this exact bug already happened on the Gate path.

**Functional equivalence:** **no.**

**Divergence risk:** **high.** Consent screen can persist a six-day window that the Gate reads as Monday, or a blank that the Gate treats as unrestricted and the CRM as weekdays.

**Canonical:** `contact_policy._parse_days` (Gate owner). Empty-handling must stay at the call site if consent “blank = unrestricted” is the product rule.

**Consumers:** consent patch/list in `db.py`; `contact_policy.evaluate`.

**Migration risk:** **high** (existing rows with en-dashes).

**Consolidation:** one parser in `contact_policy` (or a leaf next to `contact_window`). `db` imports it. Do not keep a second copy that “looks the same.”

---

### DUP-06 — Preferred-window *display* still ships 10:00–19:00

**The question:** what window do we show when `preferred_window` is empty.

**Similarity:** drifted-rule vs the leaf that already closed the *math* bug.

Enforcement: `contact_window.DEFAULT_WINDOW = "09:00-20:00 IST"` (`DEFAULT_START_HOUR=9`, `END=20`).
Display / insert fallbacks in `db.py`: **1058**, **1938**, **6631**, **8834**, **10476** still emit `"10:00-19:00 IST"` (one with an en-dash).

**Functional equivalence:** **no.** Empty preference: callable 09–20, shown as 10–19.

**Divergence risk:** **high.** Operators schedule inside a window the Gate does not use, or vice versa. This is the same class of bug `contact_window.py` was extracted to close (09:30 IST in one copy, out in the other).

**Canonical:** `contact_window.DEFAULT_WINDOW`.

**Consumers:** CRM serializers, new-consent INSERT, inbound-lead defaults.

**Migration risk:** **low** for strings; **medium** if stored rows already contain the stale default as data.

**Consolidation:** replace fallbacks with `DEFAULT_WINDOW`. New inserts should write NULL (meaning “use defaults”) rather than a stale literal.

---

### DUP-07 — Account tail (identity spoken vs identity shown)

**The question:** last four of the account id, for verify and desk cards.

**Similarity:** near (same name, different algorithm).

```411:412:backend/db.py
def _account_tail(account_id: str | None) -> str | None:
    return account_id[-4:] if account_id else None
```

```559:567:backend/agent_core/context.py
def account_tail(account_id: str | None) -> str | None:
    """Last 4 *digits* of an account id — never letters.
    ...
    """
    digits = "".join(ch for ch in (account_id or "") if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else None
```

`voice/tools.py` delegates to `context.account_tail`. Habibi seeds use `slice(-4)` / `tailOf` (letter-inclusive).

**Functional equivalence:** **no.** Vanity id `AC-SUSANTH` → `"ANTH"` on the desk, `None` on the Mouth (verify omits the phrase).

**Divergence risk:** **high.** Desk shows letters; verify_identity refuses or speaks a different tail.

**Canonical:** `agent_core.context.account_tail`.

**Consumers:** `db.list_promises` / disputes / callbacks / leads (`accountTail`); voice verify; Floor/desk cards; mock seeds.

**Migration risk:** **high** (every desk feed + verify copy).

**Consolidation:** delete `db._account_tail`; import `account_tail`. One TS `accountTail` mirroring the digits rule (mock only).

---

### DUP-08 — Payment webhook HMAC (money)

**The question:** is this payment webhook authentic.

**Similarity:** exact (jscpd 11-line pair).

`payments.py` `verify_webhook_signature` (69–82) and `payment_events.py` (56–64): HMAC-SHA256 of raw body, optional `sha256=` strip, `compare_digest`, fail-closed if secret or header missing. Different secret getters.

Related near-SQL: `promise_fulfillment.py` open-intent `SELECT … FOR UPDATE` duplicated for `promise_id` vs `payment_event_id`.

**Functional equivalence:** **yes** for HMAC; **partial** for intent lock (different FK).

**Divergence risk:** **high.** A timestamp/encoding patch on one path leaves the other forgeable. Razorpay checkout is still stubbed; if it goes live, both copies must match Razorpay's documented scheme.

**Canonical:** one `hmac_body(secret, raw, header)`; two secret getters. Parameterize `_lock_open_intent(where_col=…)`.

**Consumers:** `POST /webhooks/payments/{provider}`, `POST /webhooks/collections/payment-events`, PTP settle.

**Migration risk:** **medium** (tests + two secrets).

**Consolidation:** extract the leaf. Do **not** merge this HMAC with Twilio `RequestValidator` or Meta `X-Hub-Signature-256` (DUP rejected below).

---

## P1 — Same concept, or a word collision that will be merged by accident

### DUP-09 — Outcome vs disposition vs treatment label

**Similarity:** **naming collision** plus one real closed vocabulary copied three times on purpose.

**The conversation Outcome (glossary)** is one closed set, pinned equal:

- `call_closer.BUSINESS_OUTCOMES` (`call_closer.py` 66–84)
- SQL `call_outcomes.business` CHECK (`sql/21_outbound.sql`)
- compile `OUTCOME_CODES` (`compile.py` 123–141)

`tests/test_outbound_missions.py` asserts they match. Prior audits that said “compile vs closer vs SQL differ” are **false for this list**.

**Not the same concept**

| Vocabulary | What it is |
|------------|------------|
| Connection axis `_CONNECTION_BY_STATE` | How the call ended (`no_answer`, `busy`, `voicemail`…). Cadence retries on this. |
| Treatment `OUTCOMES` | Training/attribution (`reached`, `paid`, `ptp`, `unresolved`…). Coarser. |
| `capture.disposition_from_flags` | Legacy four-value: `ptp_captured` / `upsell_interest` / `query_handled` / `completed`. Last two **are not** in BUSINESS_OUTCOMES. `call_closer` exists because this field conflated connection and business. |
| `interactions.disposition` | Unconstrained `TEXT`. |
| UI: audit-seed, handoff wrap-up, `CB_DISPOSITIONS` | Display / human wrap-up. |

**Functional equivalence:** the three BUSINESS_OUTCOMES copies are **yes** (pinned). The others are **no**.

**Divergence risk:** **high** if Cadence or post-call obligations start reading `interactions.disposition` or treatment labels.

**Canonical:** `call_closer.BUSINESS_OUTCOMES` + connection axis. Treatment labels stay a different closed set — call them “treatment labels” in docs.

**Consumers:** Closer → `call_outcomes`; compile G-OB6; Cadence `stop_on` / `retry_on`; treatment `record_outcome`; live QA still reads `i.disposition`.

**Migration risk:** **medium** (legacy column still written).

**Consolidation:** stop writing `disposition_from_flags` into anything Cadence reads. Map UI labels onto closer codes. Do not “unify” treatment labels with conversation Outcome.

---

### DUP-10 — Authority fee-waiver matrix in the browser (mock)

**The question:** in-policy goodwill cap (₹500 DPD≤30 / ₹250 DPD 31–60, env-overridable).

**Similarity:** structural (same ladder, second language).

**Implementations:** owner `agent_core/authority/matrix.py` + `config.py`. Mock `Habibi/src/api/authority.ts` `mockAuthorityNext` (~216–367) re-implements the ladder with `VITE_*` defaults. Live panel uses `GET /authority/next`. `lib/authority-policy.ts` is **labels only** — not a cap.

**Functional equivalence:** **partial.** Mock aims to track defaults; live engine is the write path. Drift if ops tune `AUTHORITY_LATE_FEE_*` without matching Vite env.

**Divergence risk:** **high** on `USE_MOCK` / demo (quotes an amount live would refuse). **Low** on the live panel.

**Canonical:** `agent_core.authority` Locked Engine.

**Consumers:** Authority panel under `USE_MOCK`; live `GET /authority/next`.

**Migration risk:** **medium**.

**Consolidation:** mock should seed a recorded `AuthorityNext` (or hit the engine), not re-code `decide()`. Keep `authority-policy.ts` as display.

---

### DUP-11 — Routing DSL: live matcher vs Studio simulator

**The question:** does this inbound `when` AST fire.

**Similarity:** semantic (same operators: `= != > < >= <= in contains`, AND of nodes).

**Implementations:** live `db._routing_eval_condition` (~11583) / `_match_routing_rule` (~11731). Simulator `Habibi/src/data/routing-seed.ts` `evalCondition` / `evaluateRules`. Simulator always runs **in the browser**, including against live-fetched rules.

**Quoted drift**

| Op | Backend | Frontend |
|----|---------|----------|
| `=` / `!=` | coerce bool / float / **lowercased** string | numeric `Number()` else **raw `===`** |
| `in` | `str(raw)` vs list — **not** lowercased | `String` after coerce |
| `contains` | coerce then substring | **both** `.toLowerCase()` |

`"Angry" = "angry"` can match live and miss in the simulator.

**Functional equivalence:** **partial**.

**Divergence risk:** **medium.** Studio can show a fire the live matcher will not (or the reverse). This is inbound dispatch, not a Locked Engine, but operators will trust the sim.

**Canonical:** `db._match_routing_rule`.

**Consumers:** escalation / inbox routing; Studio `Simulator.tsx`.

**Migration risk:** **medium**.

**Consolidation:** simulator calls a backend evaluate endpoint. Do not let the TS DSL be the source of truth.

---

### DUP-12 — INR display (one true pair, several forks)

**Similarity:** mixed.

**True duplicate (intentionally mirrored):** `money_inr.inr_compact` ↔ `Habibi/src/data/billing-seed.ts` `inrCompact`. Same Cr/L/k/2dp/4dp ladder. Comments say change both.

**Same concept, different sign/null (grouped rupees)**

| Site | Negative | Null |
|------|----------|------|
| `money_inr.inr` | `₹-500` (sign inside) | `—` |
| `customer360-seed.ts` `fmtMoney` | `-₹500` (sign outside) | `0` → `₹0` |
| `offer-policy.ts` `fmtOfferAmount` | rounded `en-IN` | `""` |
| `customerInsights.ts` `inr` | numeral, no `₹` | `0` |
| `CustomerContextPanel` inline | `` `${currency}${n.toLocaleString("en-IN")}` `` | — |

**Related, not the same ladder:** `upsell-seed.ts` `fmtMoney` and dashboard compact Cr/L/k — pipeline ticket sizes, not metered spend.

**Functional equivalence:** compact pair **yes**; grouped formatters **no** across sign/null; upsell vs desks **no**.

**Divergence risk:** **medium–high.** Same Offer amount as `₹1.5 L` on Upsell and `₹1,50,000` on 360 is a display fork; spoken CRM card already went through this once (Western grouping) — that is why `money_inr` exists.

**Canonical:** `money_inr.inr` for grouped amounts; `inr_compact` / `inrCompact` for glanceable labels.

**Consumers:** context card, authority talk, treatment narration, db serializers, billing UI, C360, upsell.

**Migration risk:** **medium**.

**Consolidation:** one TS `fmtMoneyFull` matching `"₹" + n.toLocaleString("en-IN")` and Python's sign/null. Rename upsell to `fmtTicket`. Do not merge compact into grouped.

---

### DUP-13 — Twilio REST `Client` constructed twice, per call

**Similarity:** near adapter.

**Implementations:** `voice/twilio_ops.py` `_client()` (~257) — new `Client` per REST call, `TwilioHttpClient(timeout=10)`, no breaker. `twilio_sms.py` (~76) — same pattern per `send()`. Ops script `scripts/set_twilio_voice_webhook.py` has no timeout.

**Functional equivalence:** same SDK, same 10s timeout, **no shared pool or breaker**. Voice vs Messages products differ; the *factory* does not need to.

**Divergence risk:** **medium.** Process-wide Twilio outage still hammers REST; SMS and Voice cannot trip one breaker. Per-call `Client` repeats TLS (concurrency audit F18).

**Canonical:** one process-local `twilio_client.rest_client()` + breaker `twilio_rest`.

**Consumers:** `outbound.start_outbound_call`, warm transfer, PTP SMS fallback.

**Migration risk:** **low**.

**Consolidation:** extract the singleton. **Rejected merge:** Media Streams / TwiML vs REST dial — different APIs.

---

### DUP-14 — WhatsApp send: one adapter, two orchestrators

**Similarity:** competing control plane (exact HTTP adapter).

**Adapter (single):** `whatsapp.py` `send_text_message` / `send_template_message` — breaker `whatsapp_meta`, 30s timeout.

**Orchestrators:** inline on the Mouth turn (`bot_runtime.py` ~1127) vs queued `whatsapp_outbound.py` (SKIP LOCKED). Retry caps differ: outbound backoff **120s** vs `bot_jobs` **300s**. Outbound dead-letters after `post_attempted_at`; Mouth send is on the turn's critical path.

**Functional equivalence of HTTP:** **yes**. Of retry/durability: **no**.

**Divergence risk:** **high for double-send.** Two queues, one Graph API, no idempotency key. A crash after POST can retry one path and not the other.

**Canonical:** adapter = `whatsapp.py`. Keep two queues (in-session reply vs campaign/template) but **one** `mark_failed_or_retry` policy.

**Consumers:** `bot_worker.process_one_any` drains both.

**Migration risk:** **high** if Mouth replies are enqueued (latency). **Low** if only retry helpers are unified.

**Consolidation:** share dead-letter/backoff. Optional: enqueue Mouth replies. Do not merge Meta Cloud API with Twilio SMS.

---

### DUP-15 — LLM / TTS / STT wiring (competing control planes)

**Similarity:** competing control plane, not token clones.

**LLM — three clients, four *profiles* (x-ray overcounted constructors)**

| Client | Site | Timeout / retries / breaker |
|--------|------|------------------------------|
| Sync chat + embeddings | `azure_openai.get_client()` | 20s / 2 / `azure_openai` |
| Analysis | `get_analysis_client` | 8s / 0 / `azure_openai_analysis` |
| Async voice | `voice/llm_pool.py` | 30s / 2 / **none** |

Embeddings share client #1 (`AZURE_OPENAI_EMBEDDING_DEPLOYMENT`). Voice env can override (`AZURE_OPENAI_VOICE_*`). `chat_with_tools` tries `llm_gateway.client.maybe_chat` first and **fail-opens to Azure** on exception. Gateway: 20s, 2 retries on 5xx, **no breaker**, `reasoning_effort` accepted then ignored. Pipecat registry has `Kind="llm"` but **no LLM models are seeded**; `voice/bot.py` constructs Azure directly.

Reasoning-model detection is **copied** (`azure_openai.py` ~273 vs `llm_pool.py` ~91).

**TTS:** live `providers/factory.py` (Pipecat, fail-closed unbound locale) vs `provider_bind.py` (fail-open to Azure so the call survives) vs preview `provider_tts.py` + `azure_speech.synthesize` (REST, Azure excluded from `provider_tts` on purpose). Fish preview has OpenRouter fallback; live Fish does not. OpenRouter is `live_capable=False`.

**STT:** Pipecat streaming (Azure/Deepgram) vs `azure_speech.transcribe` REST for studio clips. REST has breaker+retries; Pipecat STT does not use `circuit_breaker.py`.

**Functional equivalence:** **no** across any of these pairs. They are different transports with different fail modes.

**Divergence risk:** **high** on the audio path. Studio binding can be Cartesia; a bind failure still speaks Azure. Operator can audition a Fish/OpenRouter voice the call cannot use. Voice LLM outage does not open the chat breaker; WhatsApp keeps calling a dead deployment.

**Canonical:** `factory.build` + `provider_bind.bind` for live calls; `chat_with_tools` for text/analysis; REST preview/transcribe for studio. Spike (`voice/spike.py`) is diagnostics — it constructs a different TTS class.

**Consumers:** voice runner, WhatsApp mouth, Agent Studio bindings, `/tts/preview`, `/stt/transcribe`. Habibi has **no** direct provider SDK calls (`src/api/speech.ts` → backend).

**Migration risk:** **medium–high** (removing Azure fallback is an outage for empty bindings).

**Consolidation:** shared reasoning-model helper. Document that voice LLM bypasses gateway and breaker. Align voice **ids** between preview and live; do not merge REST preview into Pipecat. Delete spike's parallel construction once it uses `provider_bind`. Do not make `factory` fail-open.

---

### DUP-16 — Customer 360 insights / NBA vs Locked Engines

**Similarity:** structural (TS “mirrors” Python `customer_insights`) plus a live fallback that invents policy.

**Implementations:** `backend/customer_insights.py` `derive_insights` / `_offer_nba` — live path loads reco + authority + treatment snapshots then prepends `_treatment_nba` when a row exists. `Habibi/src/lib/customerInsights.ts` `deriveCustomerInsights` / `mockOfferPolicy` — **no treatment**. `api/customers.ts` 45–58 and `customers.$customerId.lazy.tsx` fall back to derive on insights **loading and API error**.

Authority matrix was **removed** from insights (comments at `customerInsights.ts` 122–127). Contact ladder was removed from both copies. Dead Python `_within_window` is unused — do not revive it.

**Functional equivalence:** **partial** for heuristic NBA (dispute/PTP/statement); **no** for “what to do next” on a live borrower (that is treatment).

**Divergence risk:** **medium–high.** Operators see client NBA/offer as if a Locked Engine produced it.

**Canonical:** treatment / reco / authority snapshots. Insights are presentation plus heuristic fillers.

**Consumers:** `GET /customers/:id/insights`; C360 Overview; mock.

**Migration risk:** **medium**.

**Consolidation:** starve `mockOfferPolicy` toward empty/`none`. Surface insights errors instead of silent derive. Keep TS labelled as mock.

---

### DUP-17 — Promise status vs payment-plan derivation vs EMI/DPD

**Not three copies of one rule.** Three axes on a promise (`status`, `reminder_status`, `payment_intents.status`) plus a derived plan status.

| Defect that *is* duplication | Evidence |
|------------------------------|----------|
| Plan `on_track`/`slipped`/`completed` | `db.list_payment_plans` (~2585): unpaid ∧ `dueDate < now`. `promises-seed.ts` (~264): unpaid ∧ `dueDate < now - 86400000` (**one-day grace**). |
| `PromiseResponse.status` omits `due_today` | `schemas.py` vs `PromiseListResponse` vs SQL CHECK. |

**EMI / DPD:** no `computeEmi` / `calculateLoanPayment`. `get_emi_schedule` reads stored instalments. `accounts.dpd` is a stored column, bumped on bounce (`payment_events.py`). **Rejected as a duplicated ageing formula.** Risk is write-path incompleteness (no nightly ageing job found), a different defect class.

**Canonical:** `list_payment_plans` derivation; SQL CHECK for promise status.

**Consolidation:** seed must not invent a grace day. One response Literal matching the CHECK.

---

### DUP-18 — Write-error wrappers (Handoff vs CRM)

**Similarity:** near.

`main.py` `_handle_write` (720–738): KeyError → `exc.args[0]` (not `str(exc)`), IntegrityError → 409.
`_handoff_call` (1311–1319): still `str(exc)` for KeyError; no IntegrityError.

**Functional equivalence:** **no** for KeyError message shape.

**Divergence risk:** **medium.** Handoff toasts `'key'` with quotes; constraint failures → 500.

**Canonical:** `_handle_write`.

**Consumers:** Handoff queue/claim/disclosure vs all CRM writes.

**Migration risk:** **low**.

**Consolidation:** delete `_handoff_call`.

---

## P2 — Structural clones (real, lower blast)

These are maintenance cost. They do not decide money, contact, or consent unless noted.

### DUP-19 — Desk chrome cloned per feature

**Similarity:** exact / structural (jscpd's bulk).

| Cluster | Sites | Canonical move |
|---------|-------|----------------|
| MetricsStrip Tile | documents ≡ callbacks (icon tile); promises ≈ disputes ≈ upsell (filled card) | `components/ui/metrics-strip.tsx` |
| FiltersBar Chip | documents ≈ callbacks; disputes/upsell/promises local chips | `FilterChip` + shell |
| StatsStrips (~12) | ComplianceStatsStrip ≈ ConsentStatsStrip KpiCard; qa/redaction/floor/workspace/kb/… | `KpiCard` / `KpiStrip` |
| Entity sheets | Dispute/Lead/Callback/Promise/Request/Violation + New* | optional `EntitySheetShell` |
| Kanban cards | DisputeCard / PromiseCard / LeadCard | optional `BoardCard` |
| AppShell ×30+ | no pathless layout; remount per navigation | TanStack layout route |
| `query.data ?? []` | dozens of lists; `QueryState` used in essentially one file | adopt `QueryState` |
| Mutation homes | `api/*` hooks vs route-inline `useMutation` vs leaf `busy` | domain hooks; start with DUP-20 |
| Breakpoint hooks | unused `hooks/use-mobile.tsx`; inlined `useIsLg` vs `useMinWidth` | `useMinWidth` only |
| Staff assignee `USE_MOCK` | compliance/documents/disputes/callbacks/upsell/promises | `useAssigneeOptions` |

**Functional equivalence:** **partial** (same chrome, different KPIs/actions).

**Divergence risk:** **low–medium** (a11y/busy/error fix lands on one desk).

**Migration risk:** **low** per file, **high** volume.

**Consolidation:** extract primitives; leave domain config in feature folders. Rank below P0/P1.

---

### DUP-20 — Lead capture + authority apply copied between 360 and Handoff

**Similarity:** near / hook-clone.

`OverviewTab.tsx` 36–77 and `CustomerContextPanel.tsx` 32–70: same `captureLeadFromPolicy` / `applyAuthority`, different invalidation keys (`authority-next`+`customer-insights` vs `handoff`). Handoff always wires `onApply`; Overview gates on `decisionId`.

**Functional equivalence:** **partial**.

**Divergence risk:** **medium** (Handoff can skip cache the 360 path refreshes).

**Canonical:** `useCaptureLeadFromPolicy` / `useApplyAuthority` in `api/`.

**Migration risk:** **low–medium** (invalidate sets are intentional).

---

### DUP-21 — C360 loader + `useState` + insights dual path

**Similarity:** duplicate state (G).

Loader `fetchCustomer` → local `useState(initial)` + `refreshCustomer` in `customers.$customerId.lazy.tsx`. Insights query falls back to `deriveCustomerInsights` (DUP-16). Mouth editor `history` mirrors `usePromptVersions` (`prompt-studio.lazy.tsx`).

**Functional equivalence:** **partial** until a mutation races the mirror.

**Canonical:** React Query as sole cache; VersionHistory from `versionsQuery.data`.

**Migration risk:** **medium**.

---

### DUP-22 — Locked Engine scaffolding + A/B helpers

**Similarity:** exact (jscpd).

`authority/decisions.py` ↔ `live_qa/decisions.py` (`_writer`, snapshot SQL). `reco/config.py` A/B blake2b ↔ `treatment/config.py`. `reco/features._f` ↔ `treatment/features._f`.

**Functional equivalence:** helpers **yes**; domain `_from_row` **no**.

**Divergence risk:** **medium** (experiment assignment drifts between reco and treatment).

**Canonical:** shared `ab_split.py` / `decision_store` leaf; engines keep their tables.

**Migration risk:** **medium** (import cycles — same reason `money_inr` is a leaf).

---

### DUP-23 — Activity timeline SQL + lead SELECT

**Similarity:** exact / structural.

`db.py` `_dispute_events` / `_document_events` / `_callback_events` — same `activity_events` SELECT + user join; tone maps differ. Lead list SELECT duplicated (~2866 vs ~5030).

**Functional equivalence:** **partial**.

**Canonical:** `_activity_events_grouped(entity_type, tone_fn)`; `_LEAD_SELECT`.

**Migration risk:** **medium**.

---

### DUP-24 — Consent channel maps

**Similarity:** near.

`db._consent_channel` (897), `_consent_channel_db` / `_consent_channel_screen` (2024), `contact_policy.normalize_channel` (142; also maps `pstn`).

**Functional equivalence:** **partial**.

**Divergence risk:** **high (consent).** UI stores `call` while Gate expects `voice`.

**Canonical:** `contact_policy.normalize_channel`.

**Migration risk:** **medium**.

---

### DUP-25 — SKIP LOCKED / `process_one` (pattern, not one queue)

**Similarity:** structural.

Formal job tables: `bot_turn_jobs`, `whatsapp_outbound_jobs`, `kb_index_jobs`. Informal claims: treatment decisions, cadence, live QA enact, compliance scan, lead followups. `bot_worker.process_one_any` round-robins them. Stuck thresholds / attempt caps diverge.

**Functional equivalence:** pattern-equivalent; state machines differ.

**Canonical:** keep domain tables; optional shared claim helper.

**Migration risk:** **high** if forced into one generic queue.

**Consolidation:** document the pattern; align reclaim numbers where they mean the same thing. **Rejected:** merging Cadence backoff with job reclaim.

---

### DUP-26 — `db.py` / `main.py` / persist islands / untyped bodies

Not token clones. Competing *homes* for one job.

- `db.py` (~18k) vs `voice/persist.py` (no name overlap — voice spine) vs `followups_db.py` (re-exported at foot of db) vs `ops_screens.py` (called from main).
- `main.py`: 314 `@app` routes, zero `APIRouter`, `_handle_write` plus local try/except.
- `schemas.py` vs **~30+** `payload: dict[str, Any]` routes (studio, campaigns, A2A, floor).
- Schema triple: `sql/*.sql` + Alembic + `DATA_MODEL.md` (doc self-describes as map, not SoT).

**Canonical:** islands + thin `db` re-exports (followups pattern); `sql/` + Alembic for schema; `schemas.py` for CRM writes.

**Consolidation:** extract by domain; type campaign/studio next. This is architecture (report 04), listed here because it *produces* the copies above.

---

### DUP-27 — Worker loop twins + retry islands

**Similarity:** exact (`bot_worker.py` ↔ `worker.py` signal/loop); structural for retries.

Retry sites that share a *shape* but **not a policy:** Azure Speech (`_speech_call_with_retry`), Azure OpenAI SDK retries, WhatsApp outbound jobs, bot turn jobs, Cadence dial backoff, webhook deliveries (`ops_screens` / `webhooks_dispatch`).

**Canonical:** Cadence owns Mission retry. Job `mark_failed_or_retry` owns delivery. SDK retries own HTTP.

**Consolidation:** extract `run_until_signal` if wanted. Do not share Cadence's `(4, 24, 72)` hours with `max_retries=2`.

---

### DUP-28 — Circuit breakers (two domains, one metaphor)

**In-process** `circuit_breaker.py`: threshold 5, reset 60s, half-open probe. Named `azure_openai`, `azure_openai_analysis`, `azure_speech`, `whatsapp_meta`, `minio`.
**DB-backed MCP** `connectors/circuit.py`: OPEN_AFTER=3, COOLDOWN 30s, no half-open, shared via Postgres.

Twilio REST, Pipecat Azure LLM, LiteLLM HTTP, preview Cartesia/Deepgram: **not on a breaker**.

**Functional equivalence:** **no.**

**Verdict:** keep both. Align env names so operators are not surprised. Optional: add `twilio_rest` and a voice-named LLM breaker that does not share state with chat.

---

### DUP-29 — Reco promotional consent vs contact promotional admit

**Similarity:** related family, different fail mode — easy to “unify” wrongly.

`capture._promo_consent_flag`: missing promotional consent → **`unknown`, never blocks** eligibility.
`contact_policy._veto`: `data_purpose=="promotional"` and status ≠ `opted_in` → **`no_promotional_consent`**.

**Functional equivalence:** **no.** Product eligibility is not a contact Gate.

**Divergence risk:** Mouth can pitch (eligibility unknown-pass) while a marketing send is denied.

**Canonical:** keep both questions. Do not fold promotional admit into eligibility “unknown.”

---

## Rejected lookalikes

Do not consolidate these. They look adjacent and answer different questions.

| Pair | Why they are not duplicates |
|------|-----------------------------|
| Staff `authz.ROUTE_PERMISSIONS` vs Tool Grant | Operator vs Mouth. Different subjects. |
| Compile Gate G9 vs contact `admit()` | Publish vs dial. |
| Tool **Offer** vs reco product offer vs treatment action vs authority waiver | Glossary Offer is the turn subset of the Grant (cost, never safety). Three Locked Engines decide other objects. |
| Cadence vs `BOT_JOB_MAX_ATTEMPTS=5` vs Azure `max_retries` vs Meta 24h window | Mission retry vs job reclaim vs LLM transport vs WhatsApp session. Cadence must not change the action. |
| Preferred window 09–20 vs RBI voice 08–19 | Borrower preference vs statutory outreach hours. |
| Channel `"dnd"` vs `customers.dnd` | Per-channel consent vs registry/account DND. |
| Treatment `SILENCING_HOLDS` vs authority `SILENCING_HOLDS` | Next contact action vs waiver rupees. Treatment includes `dispute`; authority includes `legal` and **not** `dispute`. |
| `evaluate_product_eligibility` vs `check_product_eligibility` vs reco `_apply_eligibility` | One evaluator, wrappers. |
| `evaluate_authority` vs product eligibility | Waiver matrix vs product rules. |
| Insights NBA vs `recommend_treatment` | Heuristic UI vs Locked Engine. |
| `get_emi_schedule` vs any EMI calculator | CRM read; no formula in this repo. |
| UI “Handoff hub” vs agent **Handoff** | Human transfer vs card-to-card. |
| `contact_policy.evaluate` vs `admit` | Same veto; admit also counts the touch. |
| `_FLOW_CONTROL_TOOLS` vs `ALWAYS_ON` (authoring vs runtime) | Catalog omits tools that live in CATALOG; difference is by design **except** `capture_call_goal` (DUP-01). |
| `bot_tools` vs `voice/tools` handlers | Adapters over shared `domain.*` / CATALOG. Channel I/O differs. |
| `whatsapp.py` vs `whatsapp_outbound.py` | Transport vs job queue (DUP-14 is the *retry policy*, not the modules). |
| `voice/flows.py` vs `flows_dynamic.py` vs WhatsApp turn loop | Built-in graph vs authored Flow vs LLM+tools. Must differ. |
| `*.tsx` + `*.lazy.tsx` | TanStack code-split. `/prompt-studio` redirects to Agent studio; editor module is shared. |
| Seed `fmtMoney` re-exports in promises/disputes/documents | Aliases of C360, not clones. |
| `money_inr.inr` vs `inr_compact` | Grouped ledger vs glanceable billing. |
| In-process breaker vs MCP DB breaker | DUP-28. |
| Twilio signature vs Meta HMAC vs payment HMAC vs outbound `webhooks_dispatch.sign` vs skill-pack `sign.py` | Different protocols / directions. Payment HMAC copies *are* DUP-08. |
| `_dispute_sla` vs `_work_item_sla` | Same vocabulary (tone/label); different entities. |
| `kb_retrieve.retrieve` vs `tools/kb.search_knowledge_base` | Storage vs gated Mouth tool. |
| Gateway `chat` vs `azure_openai.chat_with_tools` | Layered kill-switch, not two peers (still DUP-15 for voice bypass). |

---

## Prior-audit claims, verified

| Claim | Now |
|-------|-----|
| Seven Tool Grant formulas; `grant.py` unused | **True.** No production import of `ToolGrant`. Cardless still fail-opens. |
| Publish G9 omitted connectors | **Still true.** |
| RBI window restated in contact_policy vs live_qa vs frontend | **Partial.** live_qa **imports** the constants but restates the hour test and ignores published windows. Mock restates `8`/`19`. Consent **live** UI omits RBI entirely. |
| Outcome lists differ compile vs closer vs SQL | **False** for `BUSINESS_OUTCOMES` (pinned). **True** that UI / `interactions.disposition` / callbacks / handoff / treatment-attribution are other vocabularies. |
| `contact_window` closed the Python copies | **True** for math. Display still 10–19 (DUP-06). Callbacks TS still recomputes (DUP-02). |
| ContactabilityPill client clone removed | **True** for C360. False for Consent `ContactablePill` and callback DND. |
| Product eligibility duplicated in `db.py` | **False** as a second evaluator. Reco/tools wrap `capture.evaluate_product_eligibility`. |
| Four Azure OpenAI constructors | **Three clients, four profiles.** Embeddings share the chat client. |
| Circuit breakers should be merged | **Rejected.** |

---

## Consolidation order

Wire owners that already exist. Do not invent engines.

1. **DUP-01** — `ToolGrant.may_execute` + cardless deny-all (ADR-0001 / 0002). Handoff is blocked on this.
2. **DUP-02 / DUP-05 / DUP-06 / DUP-04 / DUP-03 / DUP-24** — one contact/consent story: `admit()`, one day parser, one display default, one DND column, one `BLOCKING_CONSENT`, one channel map.
3. **DUP-07 / DUP-08 / DUP-10 / DUP-12** — identity tail, payment HMAC, mock waiver ladder, money formatters.
4. **DUP-09 / DUP-11 / DUP-16 / DUP-17** — Outcome vocabulary hygiene; routing sim → API; starve client NBA; plan-status grace.
5. **DUP-13 / DUP-14 / DUP-15 / DUP-18** — Twilio singleton, WhatsApp retry policy, LLM/TTS documentation + shared helpers, Handoff error wrapper.
6. **DUP-19–DUP-27** — chrome, sheets, persist islands, SKIP LOCKED numbers. Incremental.

`money_inr` and `contact_window` are the template: a leaf with no in-repo imports, so `db.py` and `agent_core` can both take it without closing a cycle.
)
