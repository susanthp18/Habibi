# 35 — Business-rule consistency

**Role:** Domain rule consistency specialist.  
**Question:** Which business rules are implemented more than once, and which of those copies already disagree?  
**Scope:** `Habibi/` (operator console) and `backend/` (FastAPI, SQL, Locked Engines, workers). `PRAXIST-main/` is out of scope.  
**Date:** 2026-09-03  
**Mode:** Read-only. The only files written are this report and a companion canvas.  
**Companions:** `11-api-contracts.md` (the contract triangle — this report names the *rules* that live in that triangle), `12-data-model.md` (CHECK / UNIQUE inventory), `27-typescript-integrity.md` (seed files as de facto TS domain models), `09-canonical-implementations.md` (how this repo picks an owner), `14-error-handling.md` (K-defects that are also rule splits), `19-auth-authz.md` (authorization is one rule family; not re-litigated).  
**Vocabulary:** `CONTEXT.md`. **Mouth**, **Gate**, **Tool Grant**, **Offer**, **Cadence**, **Outcome**, **Locked Engine** are that glossary.

**Method:** five parallel analysts — frontend validation, backend validation, database constraints, API contract, business logic — then every headline claim re-read from source in this session. Prior reports were used as maps of where to look, not as evidence. Inference is labelled.

---

## 1. Executive summary

Habibi does not lack rules. It lacks a single layer that is allowed to *be* the rule.

The same question — “may we contact this borrower?”, “what is a promise’s status?”, “how much may we waive?”, “what vocabulary does `channel` take?” — is answered in SQL `CHECK`, Pydantic `Literal`, a `db.py` serializer that remaps for a screen, a worker that mutates rows, a Locked Engine, a mock seed that the live UI still types against, and an HTML form that does not share any of those lists.

Where the product has already picked an owner, the copies are honest about it. `contact_policy.admit` is the contact **Gate**. `promise_fulfillment.settle_promises` is the clock that moves `upcoming` → `due_today` → `broken`. `agent_core/authority` is the waiver matrix. `_dispute_sla` is the only SLA chip. `money_inr` is the rupee formatter. Those owners exist because a previous pair drifted.

The remaining splits are not style. They are two verdicts for the same borrower:

1. **A promise the board calls “due today” cannot be written through the PATCH contract**, which rejects `due_today`. Sending `upcoming` instead *writes* `due_today`. Customer 360 then maps `due_today` back to `upcoming`. Three screens, three machines, one row.
2. **A borrower with no window on file is callable 08:00–19:00 by the contact Gate, 09:00–20:00 by the callback/DND leaf, and 10:00–19:00 by the consent serializer.** The 19:00–20:00 hour is in-window to `contact_window.py` and out-of-window to RBI. That leaf exists *because* two copies had already drifted; the third copy was not deleted.
3. **`critical` risk is stored, returned on Customer 360, and displayed as `Medium` in the inbox context rail.** `_inbox_risk` title-cases and then drops anything that is not High/Medium/Low.
4. **Document provenance on Customer 360 is the literal `"voice"`**, discarding the column the desk screen and the database both know. That is report 11’s P0, restated here as a *rule* (who asked) with three implementations.
5. **The Tool Grant module that ADR-0001 named as the enforcement point is not imported by the runtime.** Its own docstring says so. Seven live formulas remain.

Frontend validation is not a second gate. Zod appears once (`customers.$customerId` search tab). Money, dates, caps, and status moves are `if (!amt || amt <= 0) return`, `<input type="date">` with no `min`, and seed unions. The live API is what rejects; the mock path often does not.

Canonicalization here is not “generate types from OpenAPI.” It is: **one owner per question, serializers that do not invent vocabulary, and a test that holds the other two legs of the triangle to that owner** — the pattern `test_inbox_channel_contract.py` already proved, for one column.

---

## 2. Scope

| In | Out |
|----|-----|
| `Habibi/src` forms, seeds, API modules, derived helpers | Rewriting, generating a shared package, enabling flags |
| `backend/schemas.py`, `main.py`, `db.py`, domain modules | Secret values, live cluster |
| `backend/sql/*.sql` CHECK / DEFAULT / UNIQUE | Alembic history except where it *adds* a CHECK `sql/` already has |
| Locked Engines (contact, authority, treatment, grant) | `PRAXIST-main/` |
| Workers that mutate status (`settle_promises`, cadence) | Product copy / i18n |

Legend: **Observed fact** — quoted from source. **Strong inference** — code + tests, limited runtime uncertainty. **Recommendation** — future work; nothing was fixed.

---

## 3. How a rule is actually stacked

There is no ORM. A business rule that survives a write has to live in at least one of:

```
HTML / if / seed union     (UX; compile-time at best)
        │
        ▼
Pydantic request Literal / Field(gt=0)     (HTTP 422)
        │
        ▼
db.py / engine / worker                    (ValueError → 400, or silent remap)
        │
        ▼
PostgreSQL CHECK / UNIQUE / DEFAULT        (IntegrityError → 500 unless mapped)
```

A *read* path has a fifth layer that the write path does not share:

```
row
  → db.py serializer (_ptp_status, _reminder_status_screen, _consent_channel, _inbox_risk, …)
  → Pydantic response Literal
  → Habibi interface imported from *-seed.ts
```

That serializer layer is where this codebase most often **lies in order to keep a screen’s TypeScript union happy**. It is also where two screens for the same entity acquire two vocabularies.

The contract triangle from report 11 is the enum special case of this stack. This report adds defaults, numeric limits, date windows, status *transitions*, and formulas.

```
   sql/*.sql  CHECK / DEFAULT          ← the only layer the database enforces
        │
        │  test_inbox_channel_contract.py — one column
        ▼
   schemas.py  Literal / Field         ← FastAPI 422
        │
        │  test_agent_card_schema_drift.py — one model
        ▼
   Habibi/src  TS union / seed         ← compile-time; live JSON is `as T`
```

---

## 4. Canonical ownership (target)

Use the same test as report 09: the owner is the module that **disposes**, not the file everything imports.

| Question | Canonical owner today | Should own | Notes |
|---|---|---|---|
| May we contact, right now? | `contact_policy.admit` / `evaluate` | same | 360 pill already defers. Inbox and consent-seed still have copies. |
| Statutory calling hours | `contact_policy.RBI_VOICE_*` (08–19) + published `policy_rules` | same | `contact_window.py` 09–20 is a *different question* that was allowed to use different defaults. |
| Borrower window | `consent_records.allowed_hours` ∩ `customers.preferred_window` via `_preferred_hours` | same | Serializer default 10–19 is a third number. |
| Promise clock (`due_today` / auto-break) | `promise_fulfillment.settle_promises` | same | PATCH and 360 serializers must stop inventing a second clock. |
| Promise amount that will be collected | `promise_fulfillment` (caps to outstanding) | same, at *create* too | `create_promise` stores the uncapped figure. |
| Kept / broken / partial | DB row + `kept_requires_payment` + settler | settle + PATCH guard | Mock marks kept without payment. |
| Waiver rupee cap | `agent_core/authority` matrix + env | same | CRM `valid_waive_fee` posts via `post_waiver_for_dispute`, bypassing the matrix amount. |
| Channel stored on a table | that table’s CHECK | same | Screen unions are projections. `"call"` is a screen spelling of `"voice"`. |
| Who requested a document | `document_requests.requested_via` | same | 360 response currently fabricates `"voice"`. |
| Tool Grant | `agent_core/tools/grant.py` (ADR-0001) | same, once imported | Docstring: “Nothing imports this yet.” |
| Route authorization | `authz.py` `ROUTE_PERMISSIONS` | same | Report 19. Frontend has no parallel policy. |
| Dispute SLA chip | `db._dispute_sla` | same | Mock `mockDisputeSla` is an explicit line-for-line port. |
| INR display | `money_inr` / `fmtMoney` (`en-IN`) | same | Backend leaf exists because seven formatters drifted. |
| DPD / bucket | **nobody** — stored columns | a writer that derives from EMI, or admit they are LMS imports | Unconstrained `bucket TEXT`; `dpd INTEGER`. |
| List page size | `db.clamp_list_limit` | same | Several routes use a private `Query(le=…)` instead. |

Do not canonicalize **Offer** (reco product vs tool Offer vs treatment action). Those are four questions. Do not merge **Outcome** (`call_outcomes`) with `interactions.disposition`. Do not put mock seed unions in charge of the wire.

---

## 5. Rule catalog

Each entry: **Rule → implementations → source of truth → divergences → affected workflows.**

Severity: **P0** wrong in the deployed book, no extra tenant required. **P1** wrong as soon as the UI path is used, or two live paths disagree. **P2** triangle open / defaults split; will bite on the next writer. **P3** unconstrained TEXT where a CHECK would document the rule.

---

### R1 — Promise status machine (`upcoming` / `due_today` / `kept` / `broken` / `partial`)

**P0.** The same row is three different state machines depending on which endpoint serializes it.

**Implementations**

| Layer | Constraint |
|---|---|
| SQL `promises.status` | `CHECK IN ('upcoming','due_today','kept','broken','partial')` (`sql/05_collections.sql:23`) |
| Worker | `settle_promises` sets `upcoming` → `due_today` when the promised *IST date* is today; then `upcoming`/`due_today` → `broken` after that date if `paid_amount < amount` (`promise_fulfillment.py:863-909`) |
| INSERT | `create_promise` always writes `'upcoming'` (`db.py:5152`) |
| PATCH writer | `params["status"] = "due_today" if next_status == "upcoming" else next_status` (`db.py:5207`) |
| PATCH schema | `Literal["upcoming","kept","broken","partial"]` — **no `due_today`** (`schemas.py:881`) |
| 360 response | `Literal["upcoming","kept","broken","partial"]`; serializer `_ptp_status` maps `due_today` → `upcoming` (`db.py:739-740`, `schemas.py:110`) |
| List response | `Literal` includes `due_today` (`schemas.py:584`) |
| Frontend board | `PromiseStatus` includes `due_today`; pipeline columns are `STATUS_ORDER` (`promises-seed.ts:10,576`); `movePromise` PATCHes the dragged status (`api/promises.ts:66-76`) |
| Mock create | computes `due_today` from the promised calendar day (`promises-seed.ts:454`) |

**Source of truth:** `settle_promises` (the clock) + the SQL CHECK (the vocabulary). `due_today` is a derived clock state, not an operator enum.

**Divergences**

- Dragging a card onto “Due today” sends `{ status: "due_today" }` → **422** (not in `PromisePatchRequest`).
- Dragging onto “Upcoming” sends `{ status: "upcoming" }` → writer stores **`due_today`**.
- Customer 360 will then show that row as **upcoming**.
- Mock path: create-today is `due_today` immediately; live path: stays `upcoming` until the worker runs.
- `kept` → `broken`/`partial` is rejected (`db.py:5197-5198`). `kept` requires `paid_amount >= amount` (`5200-5202`). Mock `movePromise` marks kept by setting `paidAmount = amount` with no payment (`promises-seed.ts:539-541`).

**Workflows:** Promises board, Customer 360 promises tab, work_items view (`status IN ('due_today','broken','partial')` — `sql/95_views.sql:41-52`), treatment features, campaigns (open PTP filter), payments (`OPEN_PROMISE_STATUSES`).

**Canonicalization:** PATCH must not accept operator `due_today`. PATCH must not map `upcoming` → `due_today`. 360 must not hide `due_today`. Either the 360 type grows the value, or the board stops treating it as a drag target and reads it as a clock.

---

### R2 — Promise reminder status

**P1.** Three vocabularies, two silent remaps.

**Implementations**

| Layer | Set |
|---|---|
| SQL `reminder_status` | `off, queued, scheduled, sent, acknowledged, failed` |
| Create request | same six, default `"queued"` (`schemas.py:877`) |
| 360 response | `queued, sent, acknowledged, off` — `_reminder_status` maps anything else to `"queued"` (`db.py:743-744`) |
| List / screen | `off, scheduled, sent` — `_reminder_status_screen`: queued→scheduled, acknowledged→sent, failed→off (`db.py:748-755`) |
| Frontend seed | `off, scheduled, sent` (`promises-seed.ts:13`) |
| Create form default | `"scheduled"` (`PromiseSheet.tsx:85`) |

**Source of truth:** SQL CHECK (what can be stored). Screen unions are projections.

**Divergences:** UI default `scheduled` vs API default `queued` (queued displays as scheduled on the board, as queued on 360). `failed` is stored, shown as `off` on the board, as `queued` on 360. Operator cannot see a failed reminder as failed on either screen.

**Workflows:** PTP create, 360 tab, board, `promise_reminders` drain.

---

### R3 — Promise amount vs outstanding

**P1.** The book can hold a PTP larger than the account. The pay-link cannot.

**Implementations**

- Create schema: `amount: float = Field(gt=0)` — no cap (`schemas.py:869`).
- `create_promise`: writes `payload["amount"]` (`db.py:5163`).
- Pipeline UI: default `"5000"`, `if (!amt \|\| amt <= 0) return` (`PromiseSheet.tsx:80,104-105`). No `max`, no outstanding check, no `min` on the date.
- 360 quick capture: default `"1000"`, `disabled={!amount \|\| !date}` — **no positive-amount check** (`ActionSheets.tsx:95,109-111`). `"0"` and `"-1"` are enabled.
- Pay-link: `amount = min(amount, outstanding)` when outstanding > 0 (`promise_fulfillment.py:349-352`).

**Source of truth (collection):** fulfillment cap. **Source of truth (commitment):** currently the uncapped insert.

**Divergences:** Board and 360 show ₹X. The hosted link charges min(X, outstanding). Partial-pay and `kept_requires_payment` compare against the *promise* amount, so a borrower who pays the link in full can still fail `kept`. Pipeline create silently no-ops `≤0`; 360 posts it and the API 422s. Two create surfaces also disagree on the default rupee figure (₹5,000 vs ₹1,000).

**Workflows:** PTP create (CRM, wrap-up, bot tool), pay-link, settlement worker.

---

### R4 — Promise source and channel defaults

**P2.**

| | UI create form | Live `POST /promises` | Live `POST /payment-plans` first PTP | Mock `createPlan` |
|---|---|---|---|---|
| Channel default | pipeline `whatsapp` (`PromiseSheet.tsx:82`); 360 `voice` (`ActionSheets.tsx:98`) | schema default `"voice"`; writer `payload.get("channel") or "voice"` | hardcoded `"voice"` (`db.py:5275`) | `"whatsapp"` (`promises-seed.ts:520`) |
| Source | select includes `"self"` | ignored; derived `bot` if `owner_kind==bot` else `agent` (`db.py:1558`) | n/a | `"agent"` |
| Reminder | `"scheduled"` | `"queued"` | `"queued"` | `"scheduled"` |

List response allows `source: Literal["bot","agent","self"]` (`schemas.py:581`). Nothing in `create_promise` writes `self`. Choosing Self-serve on the form is silently stored as agent.

360 PTP channel select is voice / whatsapp / chat only (`ActionSheets.tsx:130-132`). Pipeline and the API union also allow sms / email. The 360 form cannot express two legal channels; it can express `chat`, which is legal.

**Source of truth:** `owner_kind` (human/bot) is the book. `source` is a screen projection. `"self"` is a filter chip with no writer.

**Workflows:** Promises board filters, plans, bot wrap-up.

---

### R5 — Payment plan status, cadence, installment count

**P1.**

**Implementations**

- SQL `payment_plans.status` DEFAULT `'active'` — **no CHECK** (`sql/05_collections.sql:5`).
- Installment `paid_status` CHECK is the *promise* vocabulary (`upcoming/due_today/kept/broken/partial`) (`:105`).
- List serializer *computes* `on_track | slipped | completed` from installment dates (`db.py:2585-2589`) and *infers* cadence from the gap between the first two due dates (`≤8` weekly, `≤17` biweekly, else monthly) (`db.py:1581-1591`). Cadence is not stored.
- API response: `Literal["on_track","slipped","completed"]` and `Literal["weekly","biweekly","monthly"]` (`schemas.py:613-617`).
- UI builder: 2–12 installments (`PlanBuilderSheet.tsx:183-184`); `buildSchedule` rounds each to ₹100 (`promises-seed.ts:317`); cadence days 7 / 14 / 30 (`:282-283`).
- Create request: `installments: list[dict[str, Any]]` — no min length, no amount check per row (`schemas.py:890`).

**Source of truth:** there isn’t one for plan *status*. The column says `active`. The screen says `on_track`.

**Divergences:** A plan with one installment is `monthly` by inference. UI cannot create that (min 2); the API can. Rounding lives only in the browser; a bot caller posting raw rupees skips it. `paid` on the screen is `paid_status == "kept"` (`db.py:2578`) — `due_today`/`partial` installments render unpaid.

**Workflows:** Plans table, first-installment PTP spawn.

---

### R6 — Channel vocabulary (`voice` vs `call` vs `chat` vs `field`)

**P1.** One English word, five closed sets.

| Surface | Values |
|---|---|
| `schemas.Channel` | `voice, whatsapp, chat, email, sms` (`schemas.py:28`) |
| `channel_consents.channel` CHECK | `voice, whatsapp, sms, email, chat` (`sql/03_consent.sql:20`) |
| `contact_events.channel` CHECK | those **plus `field`** (`:55`) |
| Consent *screen* / `ConsentChannelPatch` | `call, whatsapp, sms, email` — **no chat, `call` not `voice`** (`schemas.py:1160`, `consent-seed.ts:5`) |
| `_CONSENT_CHANNEL_ORDER` | `call, whatsapp, sms, email` (`db.py:1981`) |
| Contact policy API | `voice, whatsapp, sms, email, chat, field` (`contact-policy.ts:31`) |
| Inbox / interactions / promises | `voice, whatsapp, sms, email, chat` |
| `agent_core.tools.grant.Channel` | `voice \| text` (`grant.py:52`) — a different question |

**Source of truth:** the CHECK on the table that stores the row. `"call"` is a screen alias: `_consent_channel` maps `voice`→`call` on read (`db.py:897-902`); `_consent_channel_db` maps `call`→`voice` on write (`:2024-2029`). `contact_policy._channel_status` also accepts `call` as `voice` (`contact_policy.py:325`).

**Divergences**

- SQL allows `chat` consent. The consent screen cannot display or PATCH it (`mapped is None` rows are dropped, `db.py:2114-2115`). A WhatsApp-adjacent chat opt-out is invisible.
- Inbox list **rewrites `chat` → `whatsapp`** (`_inbox_channel`, `db.py:8549-8552`) even though `ConversationListResponse.channel` and the SQL CHECK both allow `chat`. The inbox contract test pins the Literal to SQL; the serializer then collapses the value the test just allowed.
- `field` exists on the contact ledger and on `ContactChannel`, not on consent. Field visits have no consent row to read.
- Customer 360 `Consent.channel` is `call|whatsapp|sms|email` (`customer360-seed.ts:97`); 360 `Channel` for interactions is `voice|…`. Same customer JSON, two spellings.

**Workflows:** Consent desk, 360 consent, admit(), inbox, documents `requestedVia` (R7).

---

### R7 — Document `requestedVia` / who asked

**P0.** Restates report 11 with the rule framing: the audit field answering *who asked for this document* is fabricated on one read path and typed as a *contact channel* on another.

**Implementations**

| Layer | Values |
|---|---|
| SQL after `17_phase4.sql` | `bot_voice, bot_chat, agent, mcp, clerk, vision, inbox` (nullable) |
| SQL originally (`05_collections.sql:166`) | `bot_voice, bot_chat, agent` |
| Create request | `bot_voice, bot_chat, agent` \| None (`schemas.py:1082`) |
| Desk list response | seven-value Literal (`:1136`) |
| 360 `DocumentRequestResponse.requestedVia` | **`Channel`** = `voice, whatsapp, chat, email, sms` (`:136`) |
| 360 serializer | `"requestedVia": "voice"` hardcoded (`db.py:1455`) — column selected and discarded (`:1441`) |
| Desk UI | `RequestedVia` seven-value (`documents-seed.ts:15-16`) |
| 360 UI | `requestedVia: Channel`; seed rows use `"voice"` / `"whatsapp"` (`customer360-seed.ts:81,429`) |
| Live 360 create mock | `requestedVia: "voice"` (`api/customers.ts:145`) |
| Desk create | `requestedVia: "agent"` (`api/documents.ts:58`) |

**Source of truth:** `document_requests.requested_via` (the column).

**Divergences:** 360 type cannot hold the stored values. 360 JSON never holds them anyway. Desk is honest. Mock 360 paints `whatsapp` as a via, which is not in the CHECK.

360 *create* posts human labels (`"6-month account statement"`, `"No-dues certificate"`, `"Payment schedule"`, `"Restructuring quote"` — `ActionSheets.tsx:235-238`), not `DocType` slugs. Desk create posts the slug (`NewRequestSheet.tsx` / `api/documents.ts`). Writer `_doc_type_screen` (`db.py:807-833`) aliases three of the four labels onto slugs; `"Restructuring quote"` matches nothing and **becomes `account_statement`**. `doc_type` is unconstrained TEXT — the alias layer is the only vocabulary.

**Workflows:** Customer 360 documents tab, Document Fulfilment Desk, bot/MCP/clerk/vision writers, compliance export.

---

### R8 — Contact hours (statutory vs preference vs fallback)

**P0.** Three defaults for “no window on file,” and they do not nest.

**Implementations**

| Module | When | Hours | End exclusive? |
|---|---|---|---|
| `contact_policy.RBI_VOICE_*` | outreach + channel `voice` + no published rule | **08–19** (`contact_policy.py:69-70,512-517`) | yes (`hour >= end`) |
| `_preferred_hours` | always, if either column parses | intersection of `allowed_hours` and `preferred_window`; non-overlap falls back to consent (`:257-288`) | yes |
| `contact_window.py` | callback DND + skill scripts, empty/unparseable window | **09–20** (`DEFAULT_START_HOUR/END`, `:32-37`) | yes |
| `db._parse_allowed_hours` | consent screen serialization, empty | **10–19** (`db.py:2067-2068`) | n/a (returns bounds) |
| `ContactResponse.preferredWindow` | API default | `"10:00-19:00 IST"` (`schemas.py:42`) |
| Consent seed / form | typical row | 10–19; some seeds 9–20 (`consent-seed.ts:129,182`) |
| Mock `isContactableNow` | consent mock only | the record’s `allowedWindow` (`:354-356`) | yes |
| Mock contact-policy port | 360 mock | RBI 8–19 then preference (`contact-policy.ts:90-91`) | yes |

`contact_window.py` exists because two copies defaulted differently (09–20 vs 10–19). The docstring picks 09–20 as “what callback/DND always enforced.” It does not mention RBI 08–19. A 19:30 IST callback is in-window to `contact_window` and out-of-window to `admit()` for voice.

**Source of truth:** `contact_policy.evaluate` for *placing* contact. Borrower preference is the intersection. Statutory outer bound is RBI / published rules.

**Divergences:** Fallback 08–19 vs 09–20 vs 10–19. WhatsApp outreach is **not** RBI-bounded in `_veto` unless a published rule names the channel (`:507-513`). Campaign `window_end_hour <= 24` (`sql/22_campaigns.sql:47-49`) can schedule past 19:00; admit() is the only later veto, and only for voice.

**Workflows:** Dialler, WhatsApp send, callback DND flag, follow-up scheduling (`blocks_scheduling`), 360 ContactabilityPill, consent desk, G-OB3 cadence vs `dailyCap`.

---

### R9 — Contact caps (daily / weekly / `used_this_week`)

**P1.**

**Implementations**

- Daily: `CONTACT_DAILY_CAP` default **3**, `max(1, …)` (`contact_policy.py:98-100`).
- Weekly: `CONTACT_WEEKLY_CAP` default **8**, then min with per-channel `weekly_frequency_cap` (`:103-106,339-365`). A stored cap of 0 becomes **1** (`max(1, int(...))`).
- `used_this_week` is a **cache** of `contact_events`, refreshed after admit (`sql/03_consent.sql:47-48`, `_refresh_used_this_week`).
- Consent screen synthesizes missing channels as `frequencyCapPerWeek: 3` (`db.py:2216`) — that 3 is the *daily* default, shown as a *weekly* cap.
- UI editor: `min={0} max={20}` (`FrequencyCapsEditor.tsx:43-48`).
- Schema allows `usedThisWeek` on PATCH (`schemas.py:1164`). Writer **ignores** it and inserts `0`, updates only status/source/cap (`db.py:6721-2732`).
- Mock `isContactableNow` treats `usedThisWeek >= frequencyCapPerWeek` as a veto (`consent-seed.ts:404`) and does **not** implement cooling-off or daily ledger caps. Live consent screen does not call it (only defined in the seed). Live 360 uses `fetchContactPolicy`. Inbox uses `_inbox_contactable` → `evaluate(..., channel="whatsapp")` by default (`db.py:8589-8599`).

**Source of truth:** `admit()` + `contact_events` ledger. `used_this_week` is not editable. Weekly cap 0 is not “never”; it is 1. The week itself is **borrower-local last 7 calendar days** (`_week_counted`, `contact_policy.py:382-400`).

**Divergences:** Consent desk default chip 3/week vs Gate default 8/week. Cap 0 in the editor vs 1 at the Gate. Inbox contactable asks WhatsApp; 360 pill asks voice (`contact-policy.ts:43-48` vs `main.py:969` default `whatsapp` — the pill always sends both query params). Cooling-off default 120 minutes (`contact_policy.py:110`) is absent from every frontend formula. **The consent list does not use `_week_counted`.** `ledger_usage` counts `occurred_at >= now() - interval '7 days'` in UTC (`contact_policy.py:1048`) — a rolling 168 hours, not the borrower’s local week. Near a timezone boundary the desk chip and `admit()` can disagree on the same borrower.

**Workflows:** Every outbound path, consent desk, 360 pill, inbox rail, outbound card G-OB3 (`per_day > vocab.dailyCap`).

---

### R10 — Dispute type, transitions, SLA

**P1** (type + transitions), **cleared** (SLA chip — one owner, mock is a labelled port).

**Type**

- SQL CHECK: six values (`sql/05_collections.sql:118`).
- List response: same Literal (`schemas.py:646`).
- **Create request: `type: str`** (`:897`). Bot wrap-up or a malformed client gets 409 `constraint_violation` instead of 422.
- Frontend forms: `DisputeType` union + `TYPE_LABELS` (`disputes-seed.ts:17-18`, `NewDisputeSheet.tsx`, `ActionSheets.tsx`). Honest UX; not a gate.
- Create amount: Pydantic `amount: float | None` — **no `gt=0`** (`schemas.py:898`). SQL `disputed_amount` nullable, no CHECK. 360 / NewDispute default `"0"` and submit `Number(amount) \|\| 0`. Mock `createDispute` throws if `amount <= 0` (`disputes-seed.ts:610-611`). Live mock-off path stores ₹0.
- Assign: Habibi `api/disputes.ts:97-98` throws if the assignee is a bot. Backend `patch_dispute` writes any `users.id`. Same pattern on documents (`api/documents.ts:77-78`).

**Transitions**

- SQL: any of the five statuses. No transition table.
- `patch_dispute`: writes whatever `status` is in the payload (`db.py:5347-5356`). Resolved → new is allowed.
- UI: “Move to” omits resolved/rejected; those are dedicated buttons (`DisputeSheet.tsx:486-487`). Kanban can still PATCH any status the board columns expose.
- Resolve with `resolutionCode == "valid_waive_fee"` posts a goodwill ledger row (`db.py:5362-5366`) via `post_waiver_for_dispute` — not via the authority matrix amount.

**SLA**

- Insert: `now() + interval '2 days'` (`db.py:5312`).
- Chip: `_dispute_sla`, warn at 25% of filing→due remaining (`db.py:917,957`).
- Mock chip: `WARN_FRACTION = 0.25` (`dispute-sla.ts:27`) — comment says change both. **Cleared** as a labelled port.
- Mock *create*: `slaDueAt = capturedAt + 48h` (`disputes-seed.ts:631`) — **not** `+ 2 days`. The chip formula matches; the filing window on the mock mutator does not.
- Work-item SLA for disputes is a *different function* (`_work_item_sla`) with a 2-hour warn (`db.py:12294`), not 25% of window. Same dispute, two chips, if both screens render.

**Resolution codes:** list response Literal of five codes (`schemas.py:662-668`); column is unconstrained TEXT (`sql/05_collections.sql:123`); PATCH `resolutionCode: str | None`.

**Source of truth:** SQL for type vocabulary; `_dispute_sla` for the desk/360 chip; no owner for transitions.

**Workflows:** Disputes board, 360, wrap-up, authority enact, work_items.

---

### R11 — Waiver / authority cap vs CRM waive

**P1.**

**Implementations**

- Matrix fee types: `late_fee, bounce_charge, settlement, restructuring` (`sql/05_collections.sql:542-544`). Settlement / restructure / bounce reverse are *always escalate* in live (`matrix.py:126-131`).
- Caps: `AUTHORITY_LATE_FEE_CAP` default ₹500 (DPD 1–30), `AUTHORITY_LATE_FEE_MID_CAP` ₹250 (31–60), escalate at DPD ≥ 61 or outstanding > ₹100,000 or tenure < 6 months (`config.py:38-63`, `matrix.py:87-149`). Rounded to whole rupees (`_round_inr`).
- Mission profile ceilings can only *lower* (`config.py:75-80`).
- CRM path: dispute type `fee_waiver` + resolve `valid_waive_fee` → `post_waiver_for_dispute` posts `type='waiver'` on the ledger using the dispute amount (`enact.py`, `db.py:5362-5366`). Guard is `except Exception: log`. No matrix cap check on this path.
- Voice: `max_waiver_inr` on the session from `state.authority_cap`; live-QA barge if the model quotes above it (`guardrails.py`).

**Source of truth:** authority matrix for *in-call* goodwill. CRM specialist waive is a second, uncapped path by design (README: “specialist path”). That is a product decision — but the rupee number on the dispute is not validated against the same cap, so a clerk can post ₹50,000 the mouth could not quote.

**Workflows:** Voice, disputes desk, ledger, treatment holds.

---

### R12 — Risk level

**P0** on the inbox rail.

**Implementations**

- SQL `customers.risk` CHECK `critical, high, medium, low` (`sql/02_customer_account.sql:58`).
- `schemas.RiskLevel` same (`schemas.py:27`).
- 360 TS same (`customer360-seed.ts:7`).
- Inbox `ThreadContext.riskLevel`: `"High" \| "Medium" \| "Low"` (`inbox-seed.ts:32`).
- Serializer: `_inbox_risk` title-cases, then **anything not in {High, Medium, Low} becomes Medium** (`db.py:8530-8534`). `"critical"` → `"Critical"` → **`"Medium"`**.

**Source of truth:** `customers.risk`.

**Workflows:** Inbox context rail (wrong), 360 header (right), treatment features (raw).

---

### R13 — DPD and bucket

**P2.** Stored, not derived. No CHECK on bucket. Two UIs, two shapes.

**Implementations**

- `accounts.dpd INTEGER NOT NULL DEFAULT 0`, `bucket TEXT` unconstrained, `status TEXT NOT NULL DEFAULT 'active'` unconstrained (`sql/02_customer_account.sql:89-91`).
- 360 `AccountFacts.bucket`: `"0-30" | "31-60" | "61-90" | "91+"` (`customer360-seed.ts:125`). Treatment `bucket_for()` returns `"90+"` at DPD > 90 (`actions.py:290-307`). A 91-DPD account is `"90+"` to the engine and typed `"91+"` on 360.
- Authority matrix buckets DPD with `<= 30` vs else vs `>= 61` (`matrix.py:96-101`) — not by reading `accounts.bucket`. A third ladder.
- Inbox aging: `"{n} days overdue"` or `"Current"` (`db.py:8609-8613`) — not the bucket string.
- No writer in this repo was found that recomputes `dpd` from `emi_installments` (search for `UPDATE accounts SET dpd` empty). **Strong inference:** DPD is an LMS import / seed field.

**Source of truth:** none in-process. If EMI and `dpd` diverge, every engine that reads `a.dpd` is wrong together.

**Workflows:** 360, treatment, reco, authority, inbox, campaign selectors.

---

### R14 — Callback window, reason, disposition

**P2.**

| Field | SQL | Pydantic | Frontend |
|---|---|---|---|
| `window_mins` | `INTEGER NOT NULL DEFAULT 30`, no CHECK | `Literal[30, 60, 120]` (`schemas.py:958,993`) | sent through (`api/callbacks.ts:68`) |
| `reason` | `TEXT NOT NULL` | closed Literal of 6 (`:949-956`) | seed union |
| `disposition` | `TEXT` unconstrained | closed Literal of 5 (`:973`) | seed union |
| reminder status | CHECK six values (same as PTP reminders) | screen remap `_callback_reminder_status` (`db.py:1808`) | |

API 422 for `windowMins: 45` on the typed create model. If a writer reaches `_callback_window` with 45, it **snaps to 30** (`db.py:1783-1790`: `<=45 → 30`, `<=90 → 60`, else 120). Schema and snapper disagree on whether 45 is illegal or thirty.

**Source of truth:** should be SQL CHECK matching the Literal. Today the Literal is tighter than the table.

**Workflows:** Callbacks desk, work_items, wrap-up.

---

### R15 — Follow-up XOR and status

**P2** (status), **cleared** (XOR).

- `followups` CHECK: exactly one of `promise_id`, `lead_id` (`sql/05_collections.sql:260`).
- Status CHECK: `open, in_progress, snoozed, done, cancelled` (`:253`).
- Work_items projects `open, in_progress, snoozed` and **hides lead-linked rows** so the lead is not queued twice (`sql/95_views.sql:89-93`).
- Broken-PTP writer inserts `status='open', priority='high', due now()+1 day` (`db.py:5216-5225` and settler `:921-927`).
- PATCH schema `status: Literal["open","done","cancelled"]` (`schemas.py:1020`) — **cannot express `in_progress`/`snoozed`**, which the table and the view use.

**Source of truth:** SQL. PATCH is narrower than the table (safe for those two writes, blind to snooze).

---

### R16 — Call attempt state vs Outcome vs interaction disposition

**P2** as a language split; **cleared** as a CHECK (outbound is well constrained).

- `call_attempts.state`: 17 values (`sql/21_outbound.sql:47-51`).
- `call_outcomes.connection` / `.business` / `.nonpayment_reason`: closed CHECKs (`:111-128`). This is the glossary **Outcome**.
- `interactions.disposition`: **unconstrained TEXT** (`sql/04_interactions.sql:13`).
- Callback disposition (R14) is a third, CRM-shaped set (`reached, no_answer, ptp_captured, …`).
- Inbox maps interaction channel to `kind: "chat" \| "call"` (`db.py:8850`) — `sms`/`email` become `"chat"`.

**Source of truth:** `call_outcomes` for settlement. `disposition` is legacy prose. Do not canonicalize them into one enum; do constrain `interactions.disposition` or stop reading it as a machine.

**Workflows:** Closer, cadence, treatment connect_rate, CRM interaction tab.

---

### R17 — Tool Grant / Offer

**P1** (architecture). Restates report 02 / 09 with a current-file check.

`agent_core/tools/grant.py` documents seven formulas across eight call sites, names itself the ADR-0001 enforcement point, and says **“Nothing imports this yet”** (`grant.py:30-31`). `voice/tools.py` imports `catalog` and `domain`, not `grant`. `bot_runtime.py` still has `tool_state.allowed` / `has_grant` (local). Grant’s `Channel` is `voice|text`, not CRM channels.

**Source of truth (declared):** `grant.py`. **Source of truth (runtime):** the copies.

**Workflows:** Voice session, WhatsApp bot, publish **Gate** G-tools, skill packs.

---

### R18 — Pagination / numeric HTTP limits

**P3.**

- Canonical clamp: `DEFAULT_LIST_LIMIT=200`, `MAX_LIST_LIMIT=1000`, `DEFAULT_CALLS_LIMIT=100`, `DEFAULT_DETAIL_LIMIT=100` (`db.py:180-189`).
- Most list routes: `Query(..., ge=1, le=db.MAX_LIST_LIMIT)`.
- Exceptions: `limit: int = Query(200, ge=1, le=2000)` (`main.py:1722`) — **allows 2000, clamp still 1000** if the accessor uses `clamp_list_limit`. If it does not, 2000 rows. Either the OpenAPI lie or the unbounded read.
- Others: `le=500`, `le=200`, `le=100` on specialised lists.
- Frontend `fetchAttempts` default `limit=50` (`outbound.ts:217`).

**Source of truth:** `clamp_list_limit`. Query `le=` should equal `MAX_LIST_LIMIT` or the accessor’s tighter default.

---

### R19 — INR formatting

**P3** (cleared as a known extraction; remaining risk is TS-only).

`money_inr` exists because seven Python formatters drifted (Western grouping in the prompt). Frontend `fmtMoney` uses `toLocaleString("en-IN")` (`customer360-seed.ts:1140-1145`). Backend `inr()` is Indian grouping. Null: Python `"—"`, TS `₹0` for `null|undefined`. That last gap is real: a missing amount renders as rupees zero in the UI helper.

**Workflows:** Every money chip, agent prompt, authority talk track.

---

### R20 — Authorization

**P2** as duplication; the mechanism is report 19.

One backend policy table (`authz.py` `ROUTE_PERMISSIONS`), CI-total over routes. Frontend has **no** equivalent rule set: screens render from fetch success/failure. `roles.tsx` edits grants. Revoking every permission from a role restores `ROLE_DEFAULTS` (report 19 P0-1) — that is an authorization *rule* with two implementations (empty-set vs stripped). Not duplicated in the UI; the UI displays the empty set while enforcement uses defaults.

No second copy of “may this agent PATCH /promises” exists in TypeScript. That is the right shape. Do not add a frontend permission matrix that can disagree.

---

### R21 — Lead SLA, bounce SLA, campaign window

**P2** (unwritten rules with magic intervals).

- Leads with no follow-up: `captured_at + INTERVAL '3 days'` in `work_items` (`sql/95_views.sql:67`).
- Bounces: `occurred_at + interval '48 hours'` (`:102`).
- Disputes: 2 days at insert (R10).
- Campaign hours: `0 ≤ start < end ≤ 24` (`sql/22_campaigns.sql:47-49`) vs RBI 08–19.
- `max_concurrent BETWEEN 1 AND 100` (`:51`).

These intervals are the rule. They live only in SQL expressions / INSERT literals, not in schemas or UI.

---

### R22 — EMI uniqueness and account status

**P2** (assumed, not constrained). Report 12 noted this; re-read: `emi_installments` has **no UNIQUE (account_id, installment_index)** (`sql/02_customer_account.sql:128-140`). `accounts.status` has no CHECK despite writers treating `'active'` as the live book (`idx_accounts_delinquent` partial on `status = 'active' AND dpd > 0`).

A duplicate EMI index is a second due date for the same installment. DPD engines that count rows double-count.

---

### R23 — Promise uniqueness (one active PTP per account)

**P2.** Assumed in treatment/campaign SQL (`status IN ('upcoming','due_today')`) but **no partial unique index**. `create_promise` does not look for an open row. UI does not disable “New promise” when one is open. Two PTPs on one account is a book the rest of the product queries as if it were one.

Pay-link uniqueness *is* constrained: one open intent per promise (`uq_payment_intents_open_promise`).

---

### R24 — Installment / plan amount rounding

**P3.** `buildSchedule` rounds to ₹100 in the browser; the API stores what it is given. Authority rounds waivers to whole rupees. Ledger is `numeric(14,2)`. Three granularities.

---

### R25 — Lead stage transitions vs dispute / PTP

**P2** (inconsistency of *having* a matrix).

Leads are the one CRM entity with an explicit Python transition table (`_LEAD_STAGE_TRANSITIONS`, `db.py:5876-5884`): closed stages reopen only to `lost`/`interested` (won) or `won`/`interested` (lost). `lost` requires `lossReason`. Duplicate open lead per `(customerId, productId)` is **409** `duplicate_open_lead` unless `allowDuplicate=True` (`db.py:5739-5750`).

Disputes have no matrix (R10). Promises have two ad-hoc guards, not a table (R1). The product knows how to write a transition owner; it did it once.

SQL `leads.stage` CHECK matches the Literal. Schema PATCH still accepts any stage; the writer is the gate (**409**, not 422).

**Workflows:** Upsell / leads desk, wrap-up capture. Contrast PTP uniqueness (R23), which campaigns assume and create does not enforce.

---

### R26 — PTP keep-rate denominator

**P2.**

Dashboard settled count is `kept + broken + partial` (`db.py:3363`). Insights keep-rate uses `kept + broken` only (mirrors in `customer_insights.py` / `customerInsights.ts`). Partial is a success on one screen and a non-event on the other.

**Source of truth:** none named. Payments writer treats `new_paid >= promised → kept` else `partial` (`payments.py`).

---

### R27 — `UPSELL_BLOCKING_BUCKETS` is dead

**P2.**

`treatment/policy.py:498` defines `UPSELL_BLOCKING_BUCKETS = {61-90, 90+}`. The docstring says high-DPD accounts must not be cross-sold. `suppresses_upsell()` (`:501-531`) reads **holds only**. Reco arbitration calls that function. The bucket constant is unused. Documented intent ≠ gate.

---

### R28 — Write errors are 409, except when they are 400

**P2.**

`_handle_write` maps `ValueError` and `IntegrityError` to **409**, the latter as anonymous `"constraint_violation"` with no constraint name (`main.py:733-738`). Billing `tenantId` validation is the same `ValueError` type and returns **400**. Invalid dispute `type` is 409 from CHECK, not 422 from Pydantic (`type: str`). Clients cannot tell “bad input” from “conflict” from “unique index.”

---

## 6. Vocabulary triangle (closed sets that disagree)

Only the legs that already disagree. Matching triangles (risk SQL = Pydantic = 360 TS, before inbox) are omitted.

| Concept | SQL CHECK | Pydantic (write / 360 / list) | TypeScript |
|---|---|---|---|
| PTP status | 5 incl. `due_today` | PATCH 4; 360 4; list 5 | board 5; 360 seed 4 (`PtpStatus` drops `due_today`) |
| PTP reminder | 6 | create 6; 360 4; list 3 | board 3 |
| Consent channel | `voice`+chat | screen `call`, no chat | `call`, no chat |
| Contact event channel | +`field` | policy API includes `field` | `ContactChannel` includes `field` |
| Doc via | 7 after phase 4 | create 3; 360 **Channel**; list 7 | desk 7; 360 **Channel** |
| Doc delivery | whatsapp, email, sms | same | 360 seed **omits sms** (`customer360-seed.ts:83`) |
| Dispute type | 6 | create **`str`**; list 6 | 6 |
| Plan status | `active` (no CHECK) | `on_track/slipped/completed` | same as list |
| Callback window | any int | 30/60/120 | 30/60/120 |
| Interaction disposition | free TEXT | `str \| None` | `string` |
| Outcome business | 14 CHECK | closer / compile | — |
| Risk | 4 | 4 | 360: 4; inbox: 3 title-case |
| Handler | human/bot XOR | 360 `bot\|human` | same |

`test_inbox_channel_contract.py` holds **one** of these (inbox `channel`) to SQL. `test_agent_card_schema_drift.py` holds **one** model to TS. Everything else is open.

---

## 7. Frontend allows / backend rejects / database rejects

| Operator action | Frontend | API | Database | Result |
|---|---|---|---|---|
| Drag PTP to Due today | allowed | 422 (`due_today` not in PATCH) | would accept | toast / failed mutation |
| Drag PTP to Upcoming | allowed | 200, stores `due_today` | accept | board shows due today after refetch; 360 shows upcoming |
| Mark kept, unpaid (live) | allowed (mock auto-fills paid) | 400 `kept_requires_payment` | would accept `kept` with paid_amount 0 | live rejects; mock lies |
| PTP amount 0 / negative | pipeline silent no-op; 360 enabled | 422 `gt=0` | `numeric` allows 0 (no CHECK `> 0`) | 360 toast / failed mutation |
| PTP amount > outstanding | allowed | 200 | accept | pay-link silently smaller |
| Promised date in the past | `<input type="date">` no min | `str`, no validator | accept | settler may auto-break immediately |
| Source = self | select option | ignored | n/a | stored as agent |
| 360 PTP channel sms/email | not in the select | API allows | CHECK allows | cannot capture those channels from 360 |
| 360 document “Restructuring quote” | allowed | 200, stored as `account_statement` | unconstrained TEXT | operator asked for a quote; desk sees a statement |
| Dispute amount ₹0 | 360 / NewDispute default | 200 (`amount` optional) | accept NULL/0 | mock path throws; live stores 0 |
| Dispute type garbage | union in forms | **accepted** (`type: str`) | CHECK fail → 409 `constraint_violation` | |
| Dispute resolved → new | UI hides on closed sheet | allowed | accept | reopen without a rule |
| `windowMins: 45` | if a caller bypasses the select | 422 | accept | |
| Consent cap 0 | editor allows | stored 0 | accept | admit() treats as 1 |
| Consent `usedThisWeek` PATCH | sent as part of channel objects | accepted on model | **not written** | |
| Chat consent | cannot PATCH | `call` alias only | CHECK allows `chat` | invisible |
| Campaign window 21–23 | if editor offers it | depends | CHECK allows 0–24 | admit() vetoes voice, not WhatsApp |

---

## 8. Duplicated formulas (same question, two functions)

| Formula | Copies | Already diverged? |
|---|---|---|
| Contact now? | `admit`/`evaluate`; `_inbox_contactable` (calls evaluate, WhatsApp default, fallback to DND+`contact_window`); mock `mockVeto`; unused `isContactableNow` | **Yes** — channel default, fallback hours, cooling |
| Calling window fallback | RBI 8–19; `contact_window` 9–20; consent parse 10–19 | **Yes** |
| Hour parsing | `contact_policy._parse_hours`; `db._parse_allowed_hours`; TS `parseAllowedHours` | Ported; minutes discarded in all three (documented) |
| Day parsing | `_parse_days` / `_parse_allowed_days` / TS `parseAllowedDays` | Same algorithm, three homes |
| Dispute SLA | `_dispute_sla` / `mockDisputeSla` | Intentionally pinned; `_work_item_sla` is a **different** 2-hour rule |
| PTP due_today | `settle_promises` IST date; mock `setHours(0,0,0,0)` local; PATCH `upcoming`→`due_today` | **Yes** |
| Plan cadence | `buildSchedule` 7/14/30; `_plan_cadence` ≤8/≤17 | Compatible for those three; not for 10-day gaps |
| Weekly cap | env 8; per-row; synthesised 3; editor 0–20; **local 7 calendar days vs UTC 168h** | **Yes** |
| PTP keep-rate | dashboard includes `partial`; insights exclude it | **Yes** |
| DPD bucket key | treatment `"90+"`; 360 TS `"91+"`; matrix 1–30 / 31–60 / ≥61 | **Yes** |
| Upsell block | `UPSELL_BLOCKING_BUCKETS` unused; holds-only `suppresses_upsell` | documented ≠ live |
| Inbox channel | SQL+Literal allow `chat`; serializer → `whatsapp` | **Yes** |
| Waiver cap | matrix+env; profile ceiling; CRM dispute amount | **Yes** on CRM path |
| Tool grant | `grant.py` + seven runtime copies | Declared |
| INR | `money_inr` vs `fmtMoney` vs old Western copies | Leaf extracted; TS null→₹0 remains |
| Inbox risk | title-case subset | **Yes** vs `customers.risk` |
| Pay amount | promise.amount vs min(amount, outstanding) | **Yes** |

---

## 9. Defaults inventory (inconsistent)

| Thing | Value A | Value B | Value C |
|---|---|---|---|
| Daily contact cap | env 3 | synthesised weekly chip 3 | G-OB3 `vocab.dailyCap` from API |
| Weekly contact cap | env 8 | synthesised 3 | editor 0–20 |
| Cooling-off | 120 minutes | not in any UI | |
| Voice hours (no preference) | 08–19 | 09–20 | 10–19 |
| PTP channel | UI whatsapp | API voice | plan spawn voice / mock plan whatsapp |
| PTP reminder | UI scheduled | API queued | |
| PTP create amount | pipeline `"5000"` | 360 `"1000"` | schema `gt=0` only |
| PTP create status | worker clock | INSERT upcoming | mock due_today if today |
| Dispute SLA | insert +2 days | work-item 2 hours warn | mock create +48h; lead 3 days / bounce 48 hours |
| Consent expiry renew | UI +1 year (`consent.ts:57-58`) | SQL `expires_at` nullable, no default | |
| List limit | 200 / max 1000 | some Query le=2000 | attempts UI 50 |
| Authority late-fee | 500 / 250 | profile 0/250/500/1500 | |
| Plan installments | UI 2–12 | API unbounded | |

---

## 10. What is already consistent (do not “fix”)

These look like duplication and are not:

- **Handler XOR** on promises / interactions / violations — SQL CHECK matches writer (`provide either ownerUserId or ownerBotId, not both`).
- **Dispute SLA chip** on board vs 360 — one server function; mock is a labelled port. Do not recompute from `slaDueAt` in React.
- **360 contactability pill** — live path calls `GET /customers/:id/contact-policy`; comments forbid a client formula. Mock port documents the four points the old client got wrong.
- **`money_inr`** as the Python owner; `fmtMoney` as the TS owner. Do not add a third.
- **Pay-intent open uniqueness** and WhatsApp `provider_ref` / Twilio `provider_call_id` uniques — real uniqueness, not a second rule.
- **Authz registry totality** — one table. Do not mirror in TS.
- **`used_this_week` not writable** — schema field is vestigial; writer correctly ignores it. Delete from the PATCH model rather than implementing the write.
- **Offer / Handoff / Cadence** glossary collisions — different questions (report 02).

---

## 11. Prioritized canonicalization

Order is “stops two verdicts for one borrower,” not “tidy types.”

1. **Promise status (R1).** Stop PATCH `upcoming`→`due_today`. Add `due_today` to 360 or remove it as a drag target. Let `settle_promises` be the only clock. Pin with a test like `test_settle_due_today`.
2. **Contact window defaults (R8).** One fallback. Recommendation: empty preference → statutory (RBI 08–19 for voice), not 09–20 and not 10–19. `contact_window.DEFAULT_*` should equal `RBI_VOICE_*` or take them as arguments. Consent serializer default 10–19 should not be a third law.
3. **Inbox risk (R12).** Pass `critical` through. Change the TS union, not the data.
4. **Document via (R7).** 360 serializer returns `requested_via`. Change `DocumentRequestResponse.requestedVia` off `Channel`. Report 11’s fix.
5. **Promise amount (R3).** Cap at create, or store both committed and collectable. `kept_requires_payment` must use the same number as the link.
6. **Dispute create `type: str` (R10)** → the six-value Literal. Add a transition matrix or accept that reopen is a feature and test it.
7. **Consent weekly default (R9).** Synthesised chip 3 must not be the daily cap. Editor `min={1}` to match `max(1, cap)`. Show `evaluate()` remaining, not `used_this_week` alone.
8. **Channel alias (R6).** One wire spelling (`voice`). Map `call` only at the consent screen edge. Stop dropping `chat`. Stop `_inbox_channel` rewriting `chat` → `whatsapp` — the inbox contract test is otherwise a lie.
9. **Callback / plan CHECKs (R5, R14).** Put 30/60/120 and plan status on the table, or stop advertising them as closed in OpenAPI. Do not snap 45 → 30 in a writer the schema already 422s.
10. **Grant (R17).** Import `grant.py` at the runtime call sites; delete the copies. Already the ADR.
11. **Triangle tests.** Generalize `test_inbox_channel_contract.py` to: PTP status, reminder, consent channel, requested_via, dispute type, call_attempt state, outcome business, risk. SQL is the authority for stored enums. Pin the serializer, not only the Literal.
12. **DPD (R13).** Document “LMS-owned stored field” or compute from EMI. Add UNIQUE `(account_id, installment_index)`. Align `"90+"` / `"91+"`.
13. **Weekly window (R9).** `ledger_usage` must use `_week_counted`, not `now() - 7 days`.
14. **Leads already have a transition owner (R25).** Copy that pattern to disputes and PTP, or stop pretending those are state machines. Wire or delete `UPSELL_BLOCKING_BUCKETS` (R27).

Frontend Zod at `apiGet` is report 27. It does not replace this list. Parsing `due_today` as `upcoming` would *hide* R1.

---

## 12. Checked and cleared

| Hypothesis | Result |
|---|---|
| Frontend Zod is a parallel validation layer | **False.** One `z.enum` on a search tab. Forms are HTML + `if`. |
| `isContactableNow` still decides live contact | **False.** Only referenced inside `consent-seed.ts`. Live 360 uses the policy API; inbox uses `evaluate`. |
| Consent PATCH can overwrite `used_this_week` | **False** at the writer. Schema still *accepts* the field. |
| Dispute SLA board vs 360 still disagree | **False** for the desk/360 chip. True if work-item SLA is shown beside them. |
| One active PTP is unique in SQL | **False.** Pay-link-per-promise is unique; PTP-per-account is not. |
| `grant.py` is wired | **False.** Self-declared. |
| RBI applies to WhatsApp | **False** unless a published rule names the channel. Voice only in the fallback. |
| Payment plan `on_track` is stored | **False.** Computed. Column is `active`. |
| Leads have no transition matrix | **False.** `_LEAD_STAGE_TRANSITIONS` exists. Disputes and PTP do not. |
| High-DPD accounts cannot be upsold | **False in code.** `UPSELL_BLOCKING_BUCKETS` is unused; holds only. |
| Consent list `usedThisWeek` is the same count `admit()` uses | **False.** UTC 168h vs borrower-local 7 calendar days. |

---

## 13. What this report is not

It is not a recommendation to delete unused-looking columns. It is not an OpenAPI-codegen plan (report 11 / 27). It is not a re-audit of fail-open `APP_ENV` (report 19). It does not treat mock-vs-live as a defect when the live module documents the port (`contact-policy.ts`, `dispute-sla.ts`). It treats mock-vs-live as a defect when the mock **is** the type the live JSON is asserted into (`due_today`, `requestedVia: Channel`, reminder 3-vs-6).

---

## 14. Evidence index (session)

Re-read, not inherited: `sql/03_consent.sql`, `05_collections.sql`, `02_customer_account.sql`, `04_interactions.sql`, `17_phase4.sql`, `21_outbound.sql`, `22_campaigns.sql`, `95_views.sql`; `schemas.py` Channel / Promise* / Consent* / Document* / Dispute* / Callback*; `db.py` `_ptp_status`, `_reminder_status*`, `_consent_channel*`, `_document_contracts`, `_inbox_risk`, `_inbox_contactable`, `_inbox_channel`, `_callback_window`, `_LEAD_STAGE_TRANSITIONS`, `create_promise`, `patch_promise`, `create_dispute`, `patch_dispute`, `list_payment_plans`, `_parse_allowed_hours`; `contact_policy.py` RBI / caps / `_preferred_hours` / `_week_counted` / `ledger_usage`; `contact_window.py`; `promise_fulfillment.py` settle + outstanding cap; `agent_core/authority/{config,matrix}.py`; `agent_core/tools/grant.py`; `agent_core/treatment/{actions,policy}.py`; Habibi `promises-seed.ts`, `PromiseSheet.tsx`, `api/promises.ts`, `consent-seed.ts`, `FrequencyCapsEditor.tsx`, `contact-policy.ts`, `documents-seed.ts`, `customer360-seed.ts`, `inbox-seed.ts`, `dispute-sla.ts`.

Analyst follow-up (same session): [frontend](8324d3c0-a3f7-4af6-abf1-41b5b757dea6), [API](7975406f-3b56-4da3-b4ca-c1907ed2a6ad), [backend](39f4d609-39f3-4fd4-99b5-44aa6c99949f), [database](d1dfa715-bc3b-4c9b-bbc7-aed079ff5cf0), [formulas](2cb7e415-dd05-4e94-96c9-b5d66b8a8c29). Claims above were re-read from the files named, not copied from those inventories. Frontend-unique items folded after that analyst finished: 360 vs pipeline PTP amount/channel, 360 document labels vs `_doc_type_screen`, live dispute ₹0 vs mock throw, mock create SLA +48h vs insert +2 days, humans-only assign seams.
