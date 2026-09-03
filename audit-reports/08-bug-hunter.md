# 08 — Bug hunter

**Scope:** `backend/` (FastAPI, workers, Mouth runtime, locked engines) and `Habibi/src` (operator console). Guest tree `PRAXIST-main/` excluded.
**Date:** 2026-09-02
**Mode:** Read-only. Nothing was fixed.
**Method:** Seven specialist analysts were spawned (static, business-logic, async/concurrency, frontend behavior, API edge-case, data integrity, test-gap). Several stalled on repo-wide search. Every finding that reached this document was re-derived from source in the parent session; claims that could not be cited to a line were dropped. Prior audits (`14-error-handling.md`, `15-concurrency.md`, `architecture-forensics.md`) were treated as leads, not as evidence.

Vocabulary is `CONTEXT.md`: Mouth, Agent Card, Skill Pack, Locked Engine, Deployment, Tool Grant, Offer, Gate, Flow, Handoff, Reachability, Mission, Cadence, Outcome.

Legend:

- **Actual bug** — a reachable path whose current behaviour disagrees with the domain rule, an ADR, or the surrounding code's own contract.
- **Code smell** — messy, duplicated, or incomplete, but not shown to misbehave.
- **Cleared** — looked like a bug, then the surrounding code explained it.

---

## Verdict

**The defects that matter are not scattered typos. They cluster where a locked engine already decided, and a later step forgets to honour that decision — or never asks the engine at all.**

Three shapes repeat:

1. **A safety sentinel of `None` still means "do not filter".** ADR-0002 is accepted; the live Mouth still fail-opens. The replacement module (`agent_core/tools/grant.py`) is deny-all and unwired. Characterization tests pin the discrepancy so the migration does not silently absorb it — and so the production hole stays green.
2. **A rupee figure is authorised in one place and spent in another, with no row lock between them.** Mission profile ceilings mutate the model's payload and never the `authority_decisions` row. `apply_goodwill` re-reads the un-narrowed cap, does not `SELECT FOR UPDATE`, and treats a no-op `mark_enacted` as success. Combined with Pipecat's default `run_in_parallel`, two tool calls in one turn can post two waivers.
3. **Failure is converted into a plausible success.** Insights 5xx becomes a client-derived Top-up Loan. `decline_offer` returns `ok: true` after a failed write. Contact-policy exceptions on `in_session` / `statutory` admit the touch. The operator and the Mouth both speak as if the system did the thing it did not do.
4. **Zero is treated as missing on rupee fields.** A known-zero posted fee becomes `None` and unlocks the full policy cap against principal. An asked ₹0 auto-approves that cap. `approved_amount or cap_amount` then posts it.

Money, contact, and consent are the blast radius. Cosmetic UI and unused helpers are listed as smells or cleared.

### If only five things are fixed

1. Wire `ToolGrant.may_execute` on both live channels and delete the `allowed is None` fail-open (**BUG-1**).
2. Stop treating rupee `0` as missing in features, matrix, and enact (**BUG-15**, **BUG-16**, **BUG-17**).
3. Make `apply_goodwill` lock the decision row, persist mission ceilings onto it, and refuse when `mark_enacted` matches zero rows (**BUG-2**, **BUG-3**).
4. Stop converting insights API failures into a successful mock Offer (**BUG-4**).
5. Fail closed on contact-policy exceptions for every purpose, not only outreach (**BUG-6**).

---

## P0 — Critical

### BUG-1. A cardless Mouth is granted the full write catalog

- **Where:** `backend/agent_core/skills/runtime.py:182-185`, `backend/bot_runtime.py:947-950`, `backend/bot_tools.py:159-162,831`, `backend/voice/bot.py:1132-1136`, `backend/voice/tools.py:2911-2913`. The replacement owner `backend/agent_core/tools/grant.py:26-28,202-205` is deny-all and, by its own docstring, imported by nothing on the live path.
- **Trigger:** A Deployment whose Agent Card is missing, unauthored (`is_authored` false), or fails `parse_card`. WhatsApp and voice both take this branch today.
- **Current behavior:** `MouthTurn.tools()` returns `ToolState(allowed=None, offered=None)`. `has_grant` is therefore false. WhatsApp offers `bot_tools.TOOL_DEFINITIONS` (includes `create_promise_to_pay`, `apply_goodwill`, `flag_dispute`, …). Voice skips the keep-filter (`if allowed_tool_names is not None`) and registers every handler. `execute_tool` only enforces a grant when `allowed_tools is not None`.
- **Expected behavior:** ADR-0002 and `CONTEXT.md`: a cardless Mouth is granted no tools. `ToolGrant.for_card(None, …).allowed` is already `frozenset()`.
- **Evidence:**

```182:185:backend/agent_core/skills/runtime.py
    def tools(self, *, catalog_names: set[str] | None = None) -> ToolState:
        """What this turn may execute, and what to put in front of the model."""
        if self.card is None:
            return ToolState(allowed=None, offered=None)
```

```947:950:backend/bot_runtime.py
        turn_tools = (
            CATALOG.openai_tools(list(tool_state.offered))
            if tool_state.has_grant
            else bot_tools.TOOL_DEFINITIONS
        )
```

```2911:2913:backend/voice/tools.py
    if allowed_tool_names is not None:
        keep = set(allowed_tool_names) | ALWAYS_ON
        tools = {k: v for k, v in tools.items() if k in keep}
```

- **Likely root cause:** The `None` sentinel was defined as "no grant derived" and every caller read it as "no filtering". `ToolGrant` was added beside the seven live formulas so they could be migrated; the deny-all ticket is explicitly last and has not landed.
- **Blast radius:** An unpublished or broken card on a live Deployment can take a Promise, post goodwill, flag a dispute, or capture a lead. Money and contact, on both channels.
- **Reproduction path:** Deploy a Mouth with no Agent Card (or a card that fails parse). Place a WhatsApp turn or a voice call. The model is offered `create_promise_to_pay`. Call it.
- **Confidence:** high
- **Recommended fix direction:** Make `MouthTurn.tools()` return `allowed=frozenset()` when `card is None`. Pass that set into both runtimes. Delete the `TOOL_DEFINITIONS` / unfiltered-registry fallbacks. Enforcement stays in `may_execute` / `allowed_tools is not None and name not in allowed` inverted to "deny unless in grant".

Related: the live grant also ignores catalog channel. `MouthTurn.tools()` calls `effective_tools` without `channel_tools`, so a card that names `get_account_position` (VOICE_ONLY, `catalog.py:145`) is offered on WhatsApp, where no handler exists. That is a contract mismatch on the same unwired-owner path; it is P1 on its own (**BUG-10**).

---

### BUG-2. Two parallel `apply_goodwill` calls can post two waivers for one decision

- **Where:** `backend/agent_core/authority/enact.py:40-88,160-185`, `backend/agent_core/authority/decisions.py:105-134`. Amplified by Pipecat `run_in_parallel: True` (default; not overridden in `backend/`). Independently consistent with report 15's F3 (shared `authority_decision_id` slot) but this is a distinct integrity hole: even a *single* decision id is not serialised.
- **Trigger:** Two `apply_goodwill` invocations on the same `decision_id` before either commits `enacted=true` — same-turn parallel tool calls, a retried WhatsApp job after a post-write Azure failure, or an operator Apply overlapping the Mouth.
- **Current behavior:** `_run` `SELECT`s the row with no `FOR UPDATE`. If `enacted` is false, it inserts a `ledger_entries` waiver and subtracts `accounts.outstanding`. `mark_enacted` then `UPDATE … WHERE id = :id AND enacted IS FALSE` and **does not inspect rowcount**. A second writer that lost the update still returns `ok=True` with its own `ledgerId`. If `mark_enacted` itself raises, the exception is logged and swallowed (`decisions.py:8,133-134`), `enacted` stays false, and a retry posts again.
- **Expected behavior:** One decision posts at most one waiver. A lost race or a failed mark is a refused apply, and the ledger insert rolls back with it.
- **Evidence:**

```54:66:backend/agent_core/authority/enact.py
        if row["enacted"]:
            raise AuthorityError("already_applied")
        …
        asked = float(amount) if amount is not None else cap
        if asked > cap + 0.009:
            raise AuthorityError("amount_above_cap")
```

```119:125:backend/agent_core/authority/decisions.py
                    UPDATE authority_decisions
                    SET enacted = true, …
                    WHERE id = :id AND enacted IS FALSE
```

No unique constraint on "one enacted waiver per decision" exists on `authority_decisions` (`sql/05_collections.sql:519-549`). `ledger_entries` has none tying `description` / `decision_id` either.

- **Likely root cause:** The enacted flag was added as a check-then-act in Python, not as a transactional claim. `mark_enacted` was written under "nothing here fails loudly" — correct for the *log* path, fatal for the *money* path that reuses it.
- **Blast radius:** Duplicate rupee waivers; outstanding driven below the authorised cap; audit log shows one decision, two `LED-` rows. Regulated money.
- **Reproduction path:** With `AUTHORITY_MODE=live`, evaluate once, then invoke `apply_goodwill` twice concurrently on that `decisionId` (or one voice turn with both tool calls in parallel). Inspect `ledger_entries` for two `waiver` rows and `accounts.outstanding` dropped twice.
- **Confidence:** high
- **Recommended fix direction:** `SELECT … FOR UPDATE` the decision in the same transaction as the ledger insert. Require `mark_enacted` rowcount == 1 or raise `already_applied` and roll back. Do not swallow that exception. Prefer a unique partial index on enacted decisions and a ledger unique on the decision ref.

---

### BUG-3. Mission authority ceiling is shown to the model and not applied at post time

- **Where:** `backend/voice/tools.py:1469-1499` (narrows `payload` / `state.authority_cap` only), `backend/agent_core/authority/enact.py:58-66` (re-reads `approved_amount` from the DB).
- **Trigger:** A Mission whose `authorityProfile` has a ceiling below the matrix cap. The Mouth calls `evaluate_authority`, is told the narrowed figure, then calls `apply_goodwill` with no `amount` (or with the original matrix cap still sitting in context from an earlier evaluate).
- **Current behavior:** The profile "can only ever lower" the cap in the in-memory payload. The `authority_decisions` row is unchanged. `apply_goodwill` with `amount is None` posts `approved_amount` from that row — the un-narrowed matrix figure.
- **Expected behavior:** A Mission profile is a Locked Engine bound, not a prompt hint. The posted waiver cannot exceed the ceiling that was spoken.
- **Evidence:**

```1477:1490:backend/voice/tools.py
        if _profile and state.authority_cap is not None:
            …
            if ceiling is not None and ceiling < state.authority_cap:
                …
                state.authority_cap = ceiling
                payload["approvedAmount"] = ceiling
                payload["capAmount"] = ceiling
                payload["narrowedBy"] = _profile
```

```1516:1528:backend/voice/tools.py
        decision_id = str(args.get("decision_id") or state.authority_decision_id or "")
        …
                domain.apply_goodwill,
                decision_id=decision_id,
                amount=args.get("amount"),
```

- **Likely root cause:** The narrowing was added on the speech path (what the model may quote) and never written back onto the decision the enact path trusts.
- **Blast radius:** A pre-due courtesy Mission can concede what a broken-promise chase would. The comment in this same handler names that as the thing it exists to stop.
- **Reproduction path:** Attach a Mission profile with a low ceiling. `evaluate_authority` → observe `narrowedBy` in the tool result. `apply_goodwill` with no amount. Ledger amount equals the original matrix cap.
- **Confidence:** high
- **Recommended fix direction:** Persist the narrowed cap on `authority_decisions` (new write, same transaction as evaluate, or a dedicated "bind profile" update). `apply_goodwill` should also `min(asked, state.authority_cap)` only if that cap is durable; in-memory session state is not enough under parallel tools.

---

### BUG-4. An insights API failure is rendered as a successful Offer the operator can capture

- **Where:** `Habibi/src/api/customers.ts:45-58`, `Habibi/src/routes/customers.$customerId.lazy.tsx:108-114`, `Habibi/src/lib/customerInsights.ts:196-218,491-506`, `Habibi/src/components/customer360/OverviewTab.tsx:36-56,91-97`.
- **Trigger:** `GET /customers/:id/insights` returns 5xx, times out, or fails schema validation. Also the first paint while the query has no `data` yet.
- **Current behavior:** `fetchCustomerInsights` catches **every** error, logs it, and returns `deriveCustomerInsights(customer)`. That function invents `mockOfferPolicy`: if any interaction has `upsellPresented`, a Top-up Loan of ₹1,50,000 with a talk track. The query is therefore **successful**. `insightsQuery.data ?? deriveCustomerInsights(customer)` applies the same derivation while pending. `OverviewTab` offers **Capture** against `insights.offerPolicy` and `captureLeadFromPolicy` writes a real lead.
- **Expected behavior:** Engine-unavailable is an error state. No Offer, no Capture. The NBA already has a "Recommendation unavailable" row for the offline copy; the Offer must not be a second, quieter engine.
- **Evidence:**

```45:58:Habibi/src/api/customers.ts
  try {
    return await apiGet<CustomerInsights>(`/customers/${id}/insights`);
  } catch (err) {
    console.error(`[insights] /customers/${id}/insights failed, deriving offline`, err);
    const c = customer ?? (await fetchCustomer(id));
    if (!c) throw new Error("Customer not found");
    return deriveCustomerInsights(c);
  }
```

```196:218:Habibi/src/lib/customerInsights.ts
function mockOfferPolicy(customer: Customer): OfferPolicy {
  …
  const presented = customer.interactions.some((i) => i.intents?.upsellPresented);
  if (presented) {
    return {
      …
      productId: "topup-loan",
      productName: "Top-up Loan",
      suggestedAmount: 150000,
```

The catch comment admits a 500 used to ship because it was indistinguishable from offline. The fallback still returns a full `CustomerInsights` object, so React Query never sets `isError`.

- **Likely root cause:** Offline/mock derivation was left on the live path as a convenience, then the Offer block was wired to the same object the engine is supposed to own.
- **Blast radius:** Operators capture leads the reco engine never approved. Funnel and specialist queues fill with invented product. During loading, a flash of fake NBA/Offer is possible even when the API would have succeeded.
- **Reproduction path:** With `VITE_USE_MOCK=false`, break `/customers/:id/insights` (or inspect Network 500). Open Customer 360 for a borrower with `upsellPresented`. Overview shows a Top-up Loan. Click Capture. A lead exists.
- **Confidence:** high
- **Recommended fix direction:** Let insights failures throw (`ApiError` already distinguishes 404 from 5xx). Render the existing "Recommendation unavailable" NBA without `offerPolicy`. Disable Capture unless the payload came from the engine (`decisionId` present and query `isSuccess`). Remove the `?? deriveCustomerInsights` coalescing on the live route.

---

## P1 — High

### BUG-5. Handoff tells the borrower a specialist will continue; the same Mouth keeps the grant

- **Where:** `backend/voice/tools.py:2768-2803`, `backend/agent_core/tools/domain.py:1006-1077`.
- **Trigger:** Model calls `handoff_to_agent` with an allowlisted target during a live call.
- **Current behavior:** A CRM row is written. Mesh role may activate. Spoken summary: "one short sentence that a specialist will continue, then stop". The handler returns no node transition (`None`). The Pipecat session keeps the originating Mouth's tool map (`allowed_tool_names` captured at connect in `voice/bot.py:1132-1154`). The receiving Agent Card is never loaded.
- **Expected behavior:** `CONTEXT.md` Handoff: the receiving agent brings its own card and therefore its own Tool Grant. Either the live session swaps grant + Flow, or the originating Mouth actually stops (transfer / end_call) after the sentence.
- **Evidence:** `_handoff_to_agent_handler` ends `return result.to_llm(), None`. No `resolve_mouth` / `ToolGrant.for_bundle` on `target`. Connect-time grant is not rebuilt.
- **Likely root cause:** Handoff was implemented as an audit + mesh event, then given borrower-facing copy that implies a transfer the runtime does not perform.
- **Blast radius:** Borrower believes they have left collections; the same grant (including write tools) remains. Specialist queue may also open — duplicated handling.
- **Reproduction path:** On a live/sandbox call, call `handoff_to_agent`. Confirm the next turn still has `create_promise_to_pay` / `apply_goodwill` and the same persona.
- **Confidence:** high
- **Recommended fix direction:** After a successful handoff, either (a) rebuild the session from the target Deployment bundle (grant, Flow, prompt) or (b) transition to a terminal node and do not speak further. Do not advertise a transfer the runtime cannot complete.

---

### BUG-6. Contact policy fail-opens for `in_session` and `statutory` when evaluation throws

- **Where:** `backend/contact_policy.py:596-600` (`evaluate`), `:1020-1024` (`admit`).
- **Trigger:** Database error, unexpected type, missing zoneinfo, or any exception inside the `try` after the customer id is known. Purpose is `in_session` (WhatsApp reply) or `statutory` (PTP confirm / receipt).
- **Current behavior:** Outreach returns `Decision(False, REASON_UNREADABLE)`. Every other purpose returns `Decision(True)`. No frequency-cap slot is reserved (`admit`'s success path is skipped). The send proceeds.
- **Expected behavior:** The module docstring: fail-closed. "no contact" is always valid. Unreadable consent is a refusal (`REASON_UNREADABLE` is already a first-class reason; the pill treats it as blocked).
- **Evidence:**

```596:600:backend/contact_policy.py
    except Exception:
        logger.exception("contact_policy.evaluate failed customer=%s", cid)
        if purpose == "outreach":
            return Decision(False, REASON_UNREADABLE, daily_cap=cap)
        return Decision(True, daily_cap=cap)
```

- **Likely root cause:** In-session replies were given a "never leave the customer on read because our DB blipped" exception. That is a product preference that contradicts the fail-closed contract and DPDP purpose limitation for statutory sends that still *count*.
- **Blast radius:** WhatsApp replies and statutory notices during an outage: opted-out / DND / expired / cooling-off not applied; caps not incremented. Report 14 named the WhatsApp compliance gate; these are the exact branches.
- **Reproduction path:** Raise in `_load_customer` / consent read (fault injection). Send an in-session WhatsApp reply. Message goes out; `contact_events` has no counted row.
- **Confidence:** high (independently confirmed; first published in report 14)
- **Recommended fix direction:** Return `Decision(False, REASON_UNREADABLE)` for every purpose on exception. If product insists on answering an in-flight customer thread, require a separately named purpose with an explicit, audited override — not a blanket `True`.

---

### BUG-7. `decline_offer` reports the refusal recorded when the write failed

- **Where:** `backend/bot_tools.py:536-556`. Voice equivalent should be checked on the same `record_offer_declined` pattern.
- **Trigger:** `capture.record_offer_declined` raises (DB down, missing interaction).
- **Current behavior:** `ctx.offer_declined = True` is set **before** the write. The `except` logs and falls through to `return {"ok": True, "say": "acknowledge briefly and move on; do not raise it again"}`. The model promises not to raise the product; the funnel has no decline row; a later turn / channel can pitch again.
- **Expected behavior:** `ok=False`, spoken "do not claim the refusal was noted". Session flag only after a durable write.
- **Evidence:**

```536:556:backend/bot_tools.py
def _tool_decline_offer(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    ctx.offer_declined = True
    …
    try:
        with db.engine.begin() as conn:
            capture.record_offer_declined(…)
    except Exception:
        logger.exception("record_offer_declined failed")
    return {"ok": True, "say": "acknowledge briefly and move on; do not raise it again"}
```

- **Likely root cause:** Same incident-shaped fix as report 14's Critical #3. Still live.
- **Blast radius:** Borrower-visible promise; reco suppression skipped; compliance "do not re-pitch after refusal" is unenforceable.
- **Reproduction path:** Break `record_offer_declined`. Call `decline_offer` on WhatsApp. Tool result `ok: true`. Table empty. Next turn `recommend_next_offer` may still present.
- **Confidence:** high
- **Recommended fix direction:** Write first. Set `ctx.offer_declined` only on success. Return `ok=False` / `crm_write_failed` on exception, with a spoken line that does not claim the note landed.

---

### BUG-8. WhatsApp Live QA treats "has a customer_id" as identity verified

- **Where:** `backend/bot_runtime.py:1282`, consumed by `backend/agent_core/live_qa/checks.py:219-232`.
- **Trigger:** Any WhatsApp turn on a bound conversation. Inbound threads bind the customer from the sender number (`bot_tools.py:665-668`); there is no verification ceremony.
- **Current behavior:** `evaluate_and_flag_bot_turn(…, identity_verified=bool(fresh.get("customer_id")))`. `check_identity_before_dues` returns `None` (no finding) whenever `identity_verified` is true. Dues spoken on WhatsApp before any Mini-Miranda / identity step do not raise `identity-before-verify`.
- **Expected behavior:** Either WhatsApp's phone-bind *is* the ceremony (then the check should be a different rule, and Mini-Miranda must still fire — `check_miranda` does not look at `identity_verified`), or QA must score WhatsApp as unverified until `identify_customer` succeeds. Today's code does neither honestly: it reuses the voice predicate with a different meaning.
- **Evidence:** `checks.py:220` `if facts.identity_verified or facts.third_party: return None`. WhatsApp caller at `:1282`.
- **Likely root cause:** Voice facts were copied onto the WhatsApp capture path; `customer_id` was the only available proxy.
- **Blast radius:** Compliance scoring under-reports identity-before-dues on the text channel. Inbox "all clear" on turns that disclosed outstanding to a bound-but-unverified peer (shared handset, wrong bind).
- **Reproduction path:** WhatsApp turn that mentions outstanding before any identify/disclose. Live QA finding list has no `identity-before-verify`.
- **Confidence:** medium-high (the phone-bind-as-verify design is arguable; silently disabling the check is not)
- **Recommended fix direction:** Pass a channel-specific fact (`identity_basis: "voice_ceremony" | "whatsapp_msisdn"`). Do not set `identity_verified=True` solely from `customer_id`. Keep Mini-Miranda independent.

---

### BUG-9. Promise date parsing drops the timezone, then stores a date into `timestamptz`

- **Where:** `backend/agent_core/tools/domain.py:122-133` (`_parse_promise_date` splits on `T`), `:136-151` (compares to `clock.now_local().date()`), `backend/db.py:5164` (`promised_at: payload["promisedDate"]` into `promises.promised_at timestamptz`).
- **Trigger:** Model emits an ISO datetime (`2026-09-02T22:00:00Z`) or a bare `YYYY-MM-DD`. Session/DB timezone is UTC (containers).
- **Current behavior:** `2026-09-02T22:00:00Z` becomes calendar date `2026-09-02` even though that instant is `2026-09-03` 03:30 in `Asia/Kolkata`. A bare `2026-09-03` inserted into `timestamptz` is typically midnight UTC = 05:30 IST on the 3rd. `due_today` / pay-link expiry (comment: promised day + 1, 23:59 IST) therefore flip at UTC midnight, not IST midnight. `_promise_date_is_past` can accept a date that is already over in IST or reject one that is not.
- **Expected behavior:** Promise days are tenant-local dates (`agent_core.clock`). Instants convert to `Asia/Kolkata` before taking `.date()`. Storage is either `date` or a clearly defined IST midnight instant.
- **Evidence:** `_parse_promise_date` lines 127-133; `_create_promise` INSERT binds `:promised_at` to the string date; schema `sql/05_collections.sql:22`.
- **Likely root cause:** The clock module was introduced to fix callback offsets (`clock.py:1-12`) and applied to `_promise_date_is_past`, but the parse step still strips the time rather than converting it.
- **Blast radius:** Same-day PTP around midnight IST; pay links already expired when sent; "due today" work items wrong for several hours each night.
- **Reproduction path:** At 01:00 IST, emit `promised_date` as yesterday 19:30Z. Observe accepted vs rejected. Inspect stored `promised_at`.
- **Confidence:** medium-high
- **Recommended fix direction:** Parse datetimes through `clock.to_instant` then `clock.to_local(…).date()`. Store `date` or IST midnight. Drive due-today off `(promised_at AT TIME ZONE 'Asia/Kolkata')::date`.

---

### BUG-10. Live Tool Grant is not channel-filtered; WhatsApp is offered voice-only tools

- **Where:** `backend/agent_core/skills/runtime.py:192-203` vs `backend/agent_core/tools/grant.py:92-103,212-214`. Catalog: `get_account_position`, `capture_call_goal`, `verify_identity` are `VOICE_ONLY` (`catalog.py:145,180,210`). `identify_customer` is `TEXT_ONLY` (`catalog.py:231`).
- **Trigger:** Any WhatsApp turn with a usable card (the granted path, not only cardless).
- **Current behavior:** `effective_tools(…)` is called without `channel_tools`, so `_apply_channel` is a no-op. Voice-only names that appear on `tools.include` are offered on WhatsApp. `bot_tools.HANDLERS` has no `get_account_position` / `verify_identity`; the model gets `unknown_tool` or skips. Conversely, voice connect uses this same unchannelled set unioned with `ALWAYS_ON`, so text-only `identify_customer` can appear in the voice keep-set if the card named it.
- **Expected behavior:** Grant is derived per channel. Offer ⊂ grant ⊂ catalog-for-channel. `ToolGrant.for_card` already does this; live callers use `MouthTurn.tools()`.
- **Evidence:** `grant.py:95-99` documents the exact bug as the reason the module exists. Live `MouthTurn.tools()` still does not pass `channel_tools`.
- **Likely root cause:** Same unfinished migration as BUG-1.
- **Blast radius:** Prompt cost and confused tool calls on WhatsApp; on voice, a card that listed `identify_customer` could expose a text-only identity write if the handler is reachable through some other registry. Safety of writes is still mostly `identity_verified` on voice (`_require_customer`).
- **Reproduction path:** Author a card including `get_account_position`. Inspect WhatsApp `turn_tools` names.
- **Confidence:** high
- **Recommended fix direction:** Replace `MouthTurn.tools()` with `ToolGrant.for_card(…, channel=…)`. Delete the unchannelled formula.

---

## P2 — Medium

### BUG-11. Specialist dispute waiver idempotency is a `LIKE '%id%'`

- **Where:** `backend/agent_core/authority/enact.py:91-110`.
- **Trigger:** `post_waiver_for_dispute` on a dispute whose id is a substring of another dispute's id already mentioned in `ledger_entries.description`, or a retry after a waiver whose description omitted the id.
- **Current behavior:** `WHERE description LIKE :pat` with `pat = f"%{dispute_id}%"`. Collision skips a real waiver (`return None`). Miss after a description-format change double-posts.
- **Expected behavior:** Idempotency on a real key (`dispute_id` column, unique index).
- **Evidence:** Lines 99-110. `_post` does write `dispute_id` onto the dispute row, not onto `ledger_entries`.
- **Likely root cause:** Ledger has no `decision_id` / `dispute_id` column; description was used as a side channel.
- **Blast radius:** Wrong skip or double fee waiver on the specialist desk — lower volume than live goodwill, still money.
- **Reproduction path:** Two dispute ids `DSP-ABC` and `DSP-ABCDEF`; waive the shorter after the longer exists in a description.
- **Confidence:** medium
- **Recommended fix direction:** Add `ledger_entries.ref_dispute_id` (unique) or consult `authority_decisions.enacted_ref` / disputes.resolution. Never `LIKE`.

---

### BUG-12. `apply_goodwill` compares rupees as float with a 0.009 slop, against `numeric(14,2)` columns

- **Where:** `backend/agent_core/authority/enact.py:58-66,171,184`; schema `accounts.outstanding` / `ledger_entries.amount` / `authority_decisions.approved_amount` are `numeric(14,2)` (`sql/02_customer_account.sql:87,119`, `sql/05_collections.sql:527-533`). Voice session already refuses this: `voice/session.py:11-17` `to_money` keeps Decimal.
- **Trigger:** Any live goodwill post, especially amounts that are not dyadic in binary float (e.g. 0.10, 299.99) or large outstanding.
- **Current behavior:** Cap check is `asked > cap + 0.009`. Posted amount is `float(-abs(amount))`. Outstanding update uses the same float. A value 0.005 above cap posts; float drift can disagree with the numeric column Postgres stores.
- **Expected behavior:** Integer paise or `Decimal("0.01")` end-to-end, matching `to_money`.
- **Evidence:** `enact.py:64-66`; contrast `voice/session.py:11-17`.
- **Likely root cause:** Engine features were modelled as `float` (`authority/features.py:43-51,62`) and enact copied them.
- **Blast radius:** Usually paise; the epsilon is an explicit hole in the cap. Combined with BUG-2, drift is the smaller problem.
- **Reproduction path:** Approve 100.00, apply 100.005. Observe accept vs reject.
- **Confidence:** medium
- **Recommended fix direction:** Quantize to paise at the engine boundary. Compare integers. Bind `Decimal` into SQL.

---

### BUG-13. PTP row commits even when fulfilment (pay link / confirm send) fails

- **Where:** `backend/db.py:5170-5181` inside `_create_promise`.
- **Trigger:** `promise_fulfillment.fulfill` raises after the INSERT (Twilio/WhatsApp down, pay-link provider error).
- **Current behavior:** Exception is logged; `fulfillment = None`; the function still returns the promise row and stores the idempotent response **without** `_fulfillment`. The Mouth's `create_promise_to_pay` reports `ok=True` with `payLinkSent: false` (domain.py:783-786) and still instructs the model to confirm amount and date (`spoken_summary` falls back). Borrower hears a confirmed PTP; no link, confirm channel possibly unset. Idempotent replay will retry fulfill (`:5110-5122`), which is good, but the first spoken confirmation already happened.
- **Expected behavior:** Either the whole transaction fails (`ok=False`, "could not send the confirm — do not treat this as a promise yet") or the spoken line is mandatory-conditional on `payLinkSent` / `suppressed`.
- **Evidence:** `db.py:5170-5181`; `domain.py:773-786`.
- **Likely root cause:** Fulfilment was treated as best-effort inside a transaction that already considers the Promise the source of truth.
- **Blast radius:** Unkeepable promises; cadence/outcome may treat `ptp_captured` as terminal (`cadence.py:264`) and stop retries on a borrower who never got a link.
- **Reproduction path:** Fault `fulfill`. Capture PTP on voice. Hear confirmation. No pay link; cadence stopped if outcome maps to `ptp_captured`.
- **Confidence:** medium
- **Recommended fix direction:** Distinguish "promise persisted, confirm suppressed" (already a fulfilment flag) from "confirm failed". Do not emit Outcome `ptp_captured` until confirm is sent or explicitly suppressed by policy.

---

### BUG-14. WhatsApp `evaluate_authority` hardcodes `identity_verified=True`

- **Where:** `backend/bot_tools.py:321-328`. Contrast voice: `_require_customer()` checks `session.identity_verified` *before* the same `True` is passed (`voice/tools.py:548-551,1443-1451`).
- **Trigger:** WhatsApp tool call `evaluate_authority` on any bound conversation, including mis-bound `customer_id`.
- **Current behavior:** The matrix never sees `IDENTITY` escalate from this caller (`matrix.py:119-120`). A live-mode Mouth can be told `apply: true` without a ceremony analogous to voice.
- **Expected behavior:** If MSISDN bind is the ceremony, pass a dedicated basis into features and keep Mini-Miranda. If it is not, pass `False` unless `identify_customer` succeeded this thread.
- **Evidence:** `identity_verified=True` literal at `bot_tools.py:327`. Document ingest on the same file uses the stricter `bool(ctx.customer_id) and ctx.customer_id != "UNKNOWN-CALLER"` (`:652`) — two policies, one module.
- **Likely root cause:** Voice handler was copied; the voice guard was not.
- **Blast radius:** Live goodwill evaluation on WhatsApp with no identity step. Enact still needs `AUTHORITY_MODE=live` and a non-escalate verdict; this removes one of the matrix's vetoes.
- **Reproduction path:** WhatsApp turn, `evaluate_authority` for an in-policy late fee. Payload `apply: true` without any identify tool call.
- **Confidence:** medium (depends on whether phone bind is accepted as KYC for this product)
- **Recommended fix direction:** Share `_require_customer` semantics. Pass the real verification flag. Do not default `True` on `recommend_authority` / `AccountAuthority` (`engine.py:120`, `features.py:69`) either — those defaults fail open if any future caller omits the argument.

---

## Independently reconfirmed (already in prior audits)

These are still present. They are not re-litigated at full length.

| Prior | Finding | Still at |
|---|---|---|
| Architecture forensics / ADR-0002 | Cardless fail-open | **BUG-1** (this report, with live call sites) |
| Report 14 Critical | WhatsApp compliance fail-open | **BUG-6** |
| Report 14 Critical | Declined offer reported recorded | **BUG-7** |
| Report 14 Critical | `POST /twilio/voice/outbound` lacks idempotency | not re-opened; not re-read end-to-end this pass |
| Report 15 F1 | Sync DB checkout in async `_authz_guard` | not re-measured |
| Report 15 F2 | Bounce webhook Twilio call on the loop inside a transaction | not re-measured |
| Report 15 F3 | `authority_decision_id` shared mutable slot | still assigned at `bot_tools.py:329` and `voice/tools.py:1462`; compounds **BUG-2** |
| Report 15 | Pipecat `run_in_parallel` default | still unset in `backend/` |

---

## Code smells (not filed as bugs)

- **`money_inr.inr` uses `int(round(float(amount)))`.** Display-only; paise disappear in speech. Wrong for a spoken "₹500.50", not a posting bug.
- **`customerInsights.inr` maps null to 0.** Offline bullets can say "₹0 outstanding" when the field is missing. Live path should not use this once BUG-4 is closed.
- **Empty `card.skills` skips skill-gating** (`intersect.py:6-8,107-108`). Documented migration hatch: unmigrated cards keep PTP. Intentional until the deny-all ticket, but it means a published card with an include list and no packs is ungated on writes. Treat as accepted risk, not a silent defect.
- **`evaluate_authority` always returns `ok=True`** (`domain.py:886`). By design: the tool succeeded at asking the matrix. `apply: false` is in the payload. Not a status-code bug.
- **`patch_promise` maps client `upcoming` → DB `due_today`** (`db.py:739-740,5207`). API vocabulary aliases an internal status. Confusing, consistent, not inverted.
- **Cadence `ON CONFLICT` overwrites `max_attempts`.** Drain path already guards extra dials (`cadence.py:385-410`). Residual smell: a lowered ceiling can exhaust on the next outcome rather than immediately, but the extra-dial hole they named is closed.
- **`_promotional_status` swallows exceptions to `None`.** Absence of promotional consent is a refusal (`REASON_NO_PROMO_CONSENT`) when `data_purpose=="promotional"`. Fail-closed. Cleared as a bug; noisy `debug` log is a smell.

---

## Checked and cleared

- **Contactability pill uses the agent's clock.** Fixed. `ContactabilityPill.tsx:9-21,104-114` asks `contact_policy` and fail-closes on error. Architecture forensics is stale on this point.
- **Customer 360 authority matrix computed in the browser.** Fixed. `OverviewTab.tsx:23-27` uses `GET /authority/next`. The *insights* Offer fallback (**BUG-4**) is the remaining live-path derivation.
- **Voice `evaluate_authority(identity_verified=True)`.** Safe: `_require_customer()` ran first. WhatsApp copy is **BUG-14**.
- **Twilio signature fail-open in production.** `_twilio_signature_ok` rejects missing token/signature when `_IS_PROD` (`main.py:3388-3396,3409-3411`). WS upgrade similarly fails closed in prod (`:3471-3478`). Non-prod allow is explicit.
- **Bot-turn retries creating duplicate PTPs.** Same `job_id` is re-queued (`bot_jobs.py:351-367`); attempt increments on claim (`:252`). WhatsApp PTP idempotency key is `{job_id}:create_promise_to_pay` (`bot_tools.py:265`). Same-job retry is safe. New job = new key; that is the remaining gap if a caller enqueues a second job.
- **`_ptp_status` rewriting `due_today`.** Alias, see smells.
- **`has_grant` inverted?** `allowed is not None` matches the docstring. The bug is what callers do when it is false, not the property itself.

---

## Test gaps (that let the bugs above ship)

| Gap | What it fails to catch |
|---|---|
| `tests/test_tool_grant_characterization.py:167-182` | **Encodes BUG-1.** Asserts production fallbacks still contain `create_promise_to_pay` and that `ToolGrant` does not. Green while the Mouth fail-opens. |
| No test that `apply_goodwill` concurrent on one `decision_id` yields one ledger row | **BUG-2** |
| No test that a Mission `authorityProfile` ceiling is the posted amount when `amount` is omitted | **BUG-3** |
| Frontend insights tests do not assert `isError` / absence of `offerPolicy` on 500 | **BUG-4** |
| No test that `handoff_to_agent` changes `allowed_tool_names` or ends the call | **BUG-5** |
| Contact-policy tests likely cover outreach fail-closed only | **BUG-6** |
| `decline_offer` happy-path only | **BUG-7** |
| Live QA fixtures default `identity_verified=False` (`checks.py:69`) but WhatsApp capture overrides it | **BUG-8** |
| Promise-date tests if any use naive `YYYY-MM-DD` only | **BUG-9** |

A characterization test that pins a fail-open as "today's answer" is useful for a migration **if** the deny-all ticket is scheduled. It is also how a regulated write path stays untested for the behaviour ADR-0002 already forbids.

---

## Analyst coverage

| Analyst | Status | Contribution |
|---|---|---|
| Static | Relaunched after stall; parent verified | Conditions, defaults, float money, None sentinels |
| Business-logic | Still in flight at synthesis; parent verified | Authority, Mission ceiling, Handoff, Cadence, Offer |
| Async/concurrency | Stalled then relaunched; parent verified | Double-enact race, parallel tools, job retry idempotency |
| Frontend | Stalled then relaunched; parent verified | Insights fallback, Capture, Contactability cleared |
| API edge-case | In flight / resumed; parent sampled webhooks | Twilio prod fail-closed cleared; outbound idempotency deferred to report 14 |
| Data integrity | Stalled then relaunched; parent verified | Ledger/outstanding, LIKE idempotency, date/timestamptz, numeric vs float |
| Test-gap | Stalled then relaunched; parent verified | Characterization tests encoding BUG-1 |

No runtime traffic was exercised. Reproduction paths are inferred from control flow, not executed.

---

## Counts

| Class | Count |
|---|---|
| P0 actual bugs | 4 |
| P1 actual bugs | 6 |
| P2 actual bugs | 4 |
| Prior-audit still live (not re-opened as new ids) | 4 additional from reports 14–15 |
| Smells | 7 |
| Cleared | 6 |
