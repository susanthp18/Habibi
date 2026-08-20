# Roadmap features — collections operations, not a voice demo

**Status:** research plan, not a committed sprint  
**Date:** 12 Aug 2026 (P2 and P6 marked done 13 Aug 2026)  
**Shipped:** P2 — written PTP + pay-link. P6 — cross-channel contact policy gate. P1 — bounce-to-contact. P3 — next-best-treatment engine (shadow). P5 — broken-PTP auto-next-action. P4 — live authority matrix (14 Aug 2026). P7 — 100% live QA → barge (14 Aug 2026; auto-barge shadow). Remaining ranked items: P8–P9.  
**Product:** BigBound AI (Habibi frontend + collections CRM backend)  
**Tenant shape:** HDFC-style loans **and** insurance (`BRAND.tenantLine`)  
**Companion canvas:** `.cursor/projects/d-Hackathon/canvases/collections-ops-research.canvas.tsx`

This file is the durable plan. Use it when adding features. Do not start from “we need a better voice agent.” Start from the chore, the delay, and the decision that must fire the same hour as the event.

---

## 1. One-line business

Indian lenders already know how to collect. Their problem is that the first 30 days of delinquency are a high-volume, high-attrition, tightly regulated factory — and most of that factory is still a human with a headset, a CRM, and a daily target.

The voice agent is the **mouth**. The P&L is everything around the call: who gets contacted, how fast, on which channel, with what authority, and whether a promise actually gets paid.

**The profit lever is delay, not dialogue.** A borrower who misses EMI on Day 1 and is contacted on Day 12 has already reclassified the debt. Every hour between bounce and structured intervention raises the chance of rolling into the next DPD bucket.

### How to talk about this product

Not: “we built an AI voice agent.”

Yes: we run a regulated Indian BFSI collections operation — the same work a telecaller, floor lead, QA analyst, DND desk, and clerk do every day — then put voice AI on the high-volume early buckets so humans only take hardship, disputes, and settlements, and so every material decision fires the same hour as the event.

### Buyer and scoreboard

The buyer is a **collections head** at a bank, NBFC, fintech lender, or insurer. Not a voice-AI enthusiast.

Their scoreboard:

| Metric | Why it is the scoreboard |
|---|---|
| Cost to collect | McKinsey: ≥15% down on digital-first; up to 40% opex with gen-AI |
| Recovery / roll-forward into NPA | McKinsey: ~10% recovery lift; Indian bank doubled digital payments |
| PTP **kept** % | Promises without keep-rate are vanity |
| Time-to-first-touch after bounce | Hours, not days. This is the early-bucket P&L |
| % of 1–30 DPD book contacted in 48h | Coverage is the 1–30 lift. Conversation quality is secondary |
| Compliance coverage | 100% scored calls. Sampling is not monitoring |
| Cost / resolved contact | Already the billing hero metric in this app. Keep it |

Published ranges (not our telemetry):

- McKinsey, Jun 2024, *The promise of generative AI for credit customer assistance*: up to **40% opex cut**, ~**10% recovery lift**, up to **30% CSAT**.
- McKinsey, *Holistic customer assistance*: Indian retail bank, **15% cost-to-collect** drop, ~15% more customers cured via self-service, digital payments doubled.
- RBI calling window: **8:00 a.m. – 7:00 p.m.** Lender is vicariously liable for recovery agents, including a voice bot.
- Human QA typically hears **2–5%** of calls.

Vendor claims (label as vendor until piloted): Caller Digital 25–40% recovery lift in 1–30 DPD from coverage; 40–60 pp on-time payment lift for pre-due vs SMS + selective human. Credgenics private-bank case: 40% higher engagement, 35% lower human calling cost, 25% faster collections.

---

## 2. Design constraints (do not break)

1. **Voice AI belongs in early buckets, not NPA.** Pre-due and 1–30 DPD are coverage problems. 61–90 is triage. 90+ is a specialist. Matches current product: bot for volume, handoff hub for exceptions.
2. **Reuse `agent_core/reco`, do not invent a new brain.** The model does not choose the product today; a gated engine does, then the model speaks. Collections **treatment** must be the same pipeline: features → veto → score → arbitrate → log. DND, calling hours, frequency, hardship, and authority are **vetoes that cannot be tuned away for conversion**.
3. **Policy corpus already forbids live settlement quotes and live waiver approval.** Features must encode that as an authority matrix, not as “the LLM may now approve.”
4. **RBI owns the agent.** A voice bot is still a recovery agent. After-hours dials, third-party contact, intimidation, and missing disclosures are product bugs, not ops issues.
5. **PTP made is vanity. PTP kept is the KPI.** Any capture path that does not write amount + date, confirm in writing, remind on the day, and react the hour it breaks is incomplete.
6. **Insurance is the same factory with a 13th-month clock.** A customer late on EMI and lapsing a policy is one cash-flow story, not two queues.

---

## 3. Who we replace — and who we keep

Six jobs. The product already has screens for most of them. The hole is instant decisioning, not more chrome.

| Role | Daily chore | Replace / keep | Profit if we win |
|---|---|---|---|
| **Tele-collection executive** | 100–150 dials/day, 60% contact target, ≥40% call-to-PTP, CRM notes after every hang-up. Identity check, amount, due date, pay-now vs pay-by-date. Language switch. DRA cert often required. | **Replace at volume** in pre-due and 1–30 DPD. Keep humans for hardship, settlement, rage. | Coverage: 100% of early book in 48h instead of a sampled list. Cost per contact collapses. |
| **Floor / team lead** | Morning huddle, allocate lists, watch RPC / PTP / roll-forward, coach objections, pull drowning agents, tune the dialer, file MIS. | **Augment.** Floor command + live flags replace the walk-around and the Excel pack. | Staff the exceptions, not the average. Occupancy goes into recovery, not firefighting. |
| **QA analyst** | Listen to 2–5% of calls. Score disclosure, hours, threats, third-party leak. Coach from a sample that will miss the complaint RBI pulls. | **Replace sampling** with 100% scorecards. Humans calibrate rubrics and coach the flags. | Inspection-ready evidence. Penalty avoidance. |
| **Compliance / DND desk** | Scrub NDND, enforce 8am–7pm, honour in-call opt-out, keep DPDP purpose-bound consent, prove TRAI transactional vs promo. | **Replace the spreadsheet.** Hard gates, not agent discipline. | Zero after-hours dials. Frequency cap across voice + WhatsApp + SMS so “persistent calling” is impossible. |
| **Back-office clerk** | Broken-PTP chase, callback diary, statement / NOC / pay-link fulfilment, dispute evidence, wrap-up notes the agent skipped. | **Replace the diary.** Promises, callbacks, documents, disputes already exist as queues. | PTP kept % is the real KPI. Clerks are why promises die overnight. |
| **Field / legal / hardship specialist** | Doorstep after ~30–60 DPD (₹800–1,500/visit, borrower absent 40–50%). SARFAESI / OTS / restructuring. Empathy on job-loss. | **Do not replace the judgment.** Feed them the same hour with transcript, PTP, and a legal clock. | Visits only when digital is exhausted. Same-day dispatch on a kept-intent PTP. |

Sources for the chores: AiXBFS telecaller JD (100–150 calls, 60% contact, 40% PTP); CarmaOne omnichannel (80–100 calls, 70% unanswered, 60%+ attrition, field visit cost); RBI Aug 2022 circular.

### A telecaller’s day — where the hours actually go

Talking is maybe half the shift. The rest is allocation, wrap-up, and chasing yesterday’s promises. McKinsey’s first gen-AI win in collections is not a better script — it is killing after-call work so the next attempt happens now.

| Block | Chore | Delay it creates | Instant equivalent |
|---|---|---|---|
| Before 9:00 | Login, take last night’s allocated list, skim broken PTPs and callbacks. | Accounts aged in a batch. First-time delinquents wait for a human to notice. | Event-driven queue: bounce at 00:12 → case at 00:13, not the 9am MIS. |
| Dialing | Progressive dialer. Verify identity, disclose purpose, state EMI + due date, ask pay-now / PTP / dispute / hardship. | Connect rate is scarce. ~70% unanswered on unknown numbers. | Bot never wraps. Preferred-language, preferred-window, DND-gated dial. |
| On the call | Hang-ups, “I’ll pay Saturday”, bounce-charge fights, “already paid”, waiver begging, language switch. | Agent cannot approve a waiver. Settlement is forbidden. The moment dies. | Authority matrix: auto-yes inside policy, specialist warm-transfer with transcript if not. |
| After each call | Notes, PTP amount/date, callback, dispute flag, CMS update. After-call work. | If it is not in the system, the next agent and the auditor have nothing. Attempts/hour collapse. | Structured disposition from the turn. Written PTP confirmation in minutes. |
| Afternoon | Retry RNRs, chase today’s PTPs, take inbound “you called me”. | PTP made ≠ PTP kept. No pay-link, no reminder, no field cue → breakage. | Pay-link on the call. Reminder on the promised date. Field sync the same hour. |
| End of shift | MIS: attempts, RPC, PTP, collected. Tomorrow’s huddle asks why roll-forward moved. | Nightly batch DPD. Intra-day truth is a rumour. | Live CE%, roll-forward, PTP kept, compliance flags. |

Industry waste ranges (directional, not our telemetry): ~70% unanswered; wrap-up often 20–40% of handle time; 95–98% of calls never QA’d; 40–50% field visits borrower not home.

---

## 4. DPD operating model — where the bot should (and must not) take the call

Indian retail books do not decay uniformly. A Day-1 miss is forgetfulness; Day-92 is distress and legal.

Recommended mix (Caller Digital 2026, vendor; midpoints):

| Bucket | AI share of outreach | Borrower state | The decision that must be instant |
|---|---|---|---|
| Pre-due | 100% | Not delinquent. Needs a reminder. | Pay-link now. Capture intent. No human. |
| 1–30 DPD | ~75% (70–80% first-touch) | Forgot / cash-flow wobble. Still reachable. | Contact 100% in 48h. Structured PTP. Written confirm. |
| 31–60 DPD | ~55% (50–60% first-touch) | Hesitation. Bureau reporting starts to matter. | Bot first-touch; human on broken PTP and complaints. |
| 61–90 DPD | ~30% (triage only) | Specialist recovery. Field / legal queued. | Triage: willing / distress / dispute — then route. |
| 90+ DPD | ~10% (logistics only) | NPA. Empathy + OTS + SARFAESI. | Human owns recovery. Bot only pings and confirms logistics. |

Finezza DPD trigger logic (ops, not vendor voice-AI):

- **DPD 0–1:** WhatsApp/SMS + pay-link, not a call, not a visit. Highest-ROI window.
- **DPD 1–30 (SMA-0):** Multi-channel. Telecalling auto-assign by value/risk around DPD-15. NACH retry against salary credit, not calendar.
- **DPD 31–60 (SMA-1):** Resolution (restructure / partial / deferral). Field for secured above ticket size. CIC reporting becomes material.
- **DPD 61–90 (SMA-2):** Field mandatory for secured. Legal notice queued. Co-lending books must not diverge on DPD class.
- **DPD 90+ (NPA):** SARFAESI / OTS / legal queue. Dedicated workflow, not a shared collections list.

NACH bounce is the start of collections, not the end of origination. Salary-credited accounts peak in balance within ~48 hours of credit. A retry scheduled next calendar cycle misses the liquidity window. RBI Digital Lending Directions (2025): repayment must flow borrower bank → RE account, no third-party pool.

---

## 5. Regulatory chores the bot cannot shrug off

Primary: [RBI DOR.ORG.REC.65/21.04.158/2022-23](https://rbi.org.in/Scripts/NotificationUser.aspx?Id=12378&Mode=0) (12 Aug 2022). Confirmed on rbi.org.in.

The circular tells regulated entities they own their recovery agents. A voice bot is still an agent.

| Rule | Daily implication | Product control |
|---|---|---|
| No calls before 8:00 a.m. or after 7:00 p.m. | Dialer must refuse the attempt, not rely on agent discipline. Time-zone aware (Northeast). Ongoing calls must conclude before cutoff. | Admission / calling-window guardrail; timestamp on every interaction. |
| No intimidation, public humiliation, family/friends contact, anonymous or persistent calling, false representations | Scripts, guardrails, and 100% QA — sampling will miss the complaint that reaches RBI. | Prompt guardrails, violation detection, audit trail, redaction. |
| Lender is liable for outsourced agents | Agency floors are a visibility problem. “Our BPO handled it” is not a defence. | Multi-tenant audit + QA by agent/bot + recording retention. |
| TRAI NDND / DLT; DPDP purpose-bound consent | Promotional vs transactional classification, category DND, in-call opt-out within hours. Collection calls are generally transactional but must be documented as such. | Consent / DND registry; opt-out capture; exportable logs. |
| Digital Lending Guidelines | Identify RE, loan ref, grievance mechanism. Written confirmation of any payment promise, typically within minutes. Hard separation of collection vs cross-sell. Consent captured at origination, not “press 1”. | Disclosure logging; PTP written confirm; reco already separates offer from collections. |
| Third-party / reference contact | Only if origination consent exists. Human warm-transfer must not then dial a guarantor at discretion. | Consent gate before any non-borrower number is offered to the dialer. |
| From 1 Jan 2027 directions (reported): ~6 month recovery-call retention; 1-day notice before field visit | Recording + identity of agency becomes an evidence pack. | Audit trail, media retention, customer 360 activity log. |

CarmaOne (vendor) comparison of audited Indian NBFC deployments — use as a **target**, not as our measured baseline:

| Dimension | Human floor (vendor) | AI platform target |
|---|---|---|
| Calling-hour violations | 3–7% | 0% hard block |
| Language violations | 8–12% flagged | 0% pre-approved |
| Frequency-limit breaches | 15–20% | 0% centralized cap |
| Call recording coverage | 70–85% | 100% |
| Disclosure compliance | 60–75% | 100% mandatory flow |
| Third-party contact | 5–8% unauthorized | 0% |

QA sampling of 2% is increasingly indefensible when 100% scoring is commercially available. Caller Digital: on a 500-agent floor (~25k calls/day) ~24k calls are never heard; the complained-about call is usually not in the sample.

Legal clocks (do not miss; they invalidate recovery):

- **NI Act s.138:** statutory demand within 30 days of bounce; borrower has 15 days to pay.
- **SARFAESI s.13(2):** 60-day demand notice after NPA; then s.13(4) possession path.
- **Legal hold:** typically at 90/120 DPD — long retention, tamper-evident hash, chain of custody to legal.

---

## 6. Insurance is the same factory

Tenant line is “HDFC · Loans & Insurance.” Persistency is collections with a 13th-month due date.

IRDAI FY24–25 (Rajya Sabha / Gyansurance from IRDAI handbook):

- ~**86 lakh** individual policies lapsed.
- ~**₹8.7 lakh crore** of cover wiped.
- 13th-month persistency by count often **60–83%**; 61st-month **22–59%**.
- Decay is steepest 13th → 25th month (~10.3 pp average drop).

Most of that leak is missed auto-debit and forgotten renewals — **pre-due work** — not specialist negotiation. Revival windows are often up to 5 years.

Implications:

- **Persistency desk:** remind, take payment, revive. Same chores as pre-due EMI: DND, disclosure, pay-link, no mis-sell on the renewal call.
- **IRDAI suitability:** upsell already has a gated recommender (eligibility veto before language). Insurance pitches need the same: no product the customer is not eligible for.
- **One customer:** a borrower late on EMI and lapsing a policy is one cash-flow story. Two queues cause over-contact and missed hardship.

---

## 7. What BigBound already covers

The codebase is already a CRM + compliance + QA + supervisor stack with a voice bot on top. The hole is not “more talking.” It is a **treatment brain** that fires without waiting for a person.

### Present (do not rebuild)

| Human job | Screen / system | Notes |
|---|---|---|
| Allocated list + shift stats | My workspace | Replace the paper list |
| Inbound “you called me” + WhatsApp | Conversation inbox | Replace the shared mailbox |
| Warm transfer on hardship / dispute | Handoff hub | Keep the human; give them a cockpit |
| Listen / whisper / barge | Floor command | Augment the supervisor |
| CE% / roll-forward MIS | Executive dashboard | Replace the Excel pack |
| Account lookup while talking | Customer 360 | Replace alt-tab into LMS |
| PTP diary + installment plans | Promise to pay | Written confirm + hosted pay-link on capture; keep/break from ledger (P2, 13 Aug 2026) |
| “Already paid” / bounce fights | Disputes queue | Keep specialists; structured queue |
| NOC, statement, pay-link fulfilment | Document desk | Present; generate/send/retry |
| “Call me after salary” | Callbacks | Replace the diary |
| Recording search for auditor | Audit trail | Replace tape-hunt |
| FPC / hours / threat sampling | Compliance risk + QA scorecards | Path to 100%; make gates hard |
| DND / opt-out spreadsheet | Consent / DND | Hard gate on every outbound; ledger counts, not a PATCH counter (P6, 13 Aug 2026) |
| PII before sharing a recording | Redaction & export | Replace manual beep-out |
| Script + DRA training | Prompt studio + sandbox + KB | Replace laminated scripts |
| Seat licences | Integrations / webhooks / billing | Cost / resolved call is the hero metric |
| Next-best **offer** (upsell) | `backend/agent_core/reco/` | Gated, logged, shadow-mode. Model does not pick the product |
| Next-best **treatment** (what/when/which channel) | `backend/agent_core/treatment/` | Gated, logged, shadow-mode. Scored in rupees; `wait` competes. Model does not pick the action (P3, 14 Aug 2026) |
| Broken-PTP / bounce chase ladder | `agent_core/treatment/followthrough.py` | Attributes each attempt, re-decides while the case is open, and **stops** — attempt cap, backoff, repeat penalty (P5, 14 Aug 2026) |
| Hardship / dispute / complaint / legal stop-work | `treatment_holds` | A row, not a routing label — binds the bot at 02:00 as it binds a supervisor (P3, 14 Aug 2026) |

Policy corpus already encodes: no live late-fee waiver, no live settlement %, hardship → callback/escalate, no same-day NOC, identity before account details, calls recorded.

### Explicit gaps (this roadmap)

- Live in-call UPI collect (pay-link after PTP is shipped; Razorpay checkout still stubbed)
- Delivery receipts and call dispositions — outcome attribution infers `reached` from an inbound reply or a call that lasted long enough, which is coarser than a provider's own read/answer signal
- Field GPS dispatch + same-day LMS sync (the engine recommends `field_visit`; nothing carries it out)
- Statutory legal clocks (s.138, SARFAESI) and legal-hold retention / chain of custody at 90 DPD — the *hold* exists (`treatment_holds.kind='legal'`), the clocks and the evidence pack do not
- Pre-delinquency signals (payment-timing drift, other-obligation bounce)
- Unified loan + policy contact budget
- Intra-day DPD (payment receipt updates status now, not nightly batch)
- Conference-from-start listen/whisper audio (P7 barge takes over the call; listen is still the transcript)

---

## 8. Ranked feature roadmap

Ranked by **(profit × speed of decision)**. Do not start with more persona prompts. Start with events that currently wait overnight.

Each item: chore it kills, decision it makes instantly, suggested shape, reuse, and what “done” means.

### P1 — Bounce-to-contact in minutes

**Chore it kills:** Morning MIS allocation.  
**Decision:** This account is live. Send pay-link. Dial inside window. Retry on salary credit, not next month.

**Context:** Finezza: at any book above ~10k loans, human coordination cannot keep intervention timing consistent. Bucket-assignment lag (DPD-15 treated like DPD-5) and NACH retry scheduled days later are the failure mode. A bounce that waits for 9am is already a Day-1 miss turning into Day-2 psychology.

**Shape:**

- First-class `payment_events` (or equivalent) for NACH/UPI/mandate bounce, with bounce reason, amount, salary-credit hint if known.
- On bounce: create/open work item immediately; enqueue WhatsApp/SMS pay-link; enqueue voice attempt only if inside 8am–7pm local and under frequency cap.
- Retry planner: 48–72h salary window preferred over next EMI cycle.
- Dashboard: time-to-first-touch after bounce (hours).

**Reuse:** `interactions`, `callbacks`, `followups`, WhatsApp outbound jobs, voice admission.  
**Done when:** a bounce at 00:12 produces a case at 00:13 and a first compliant touch inside the next legal window, with no human allocation step.

### P2 — In-call pay-link + written PTP

**Status:** done — 13 Aug 2026

**Chore it kills:** After-call notes and clerk confirmations.  
**Decision:** Promise is real: amount, date, channel, SMS/WhatsApp proof. Reminder scheduled.

**Context:** Digital Lending Guidelines: any payment promise on a call must be confirmed in writing, typically within minutes. PTP keep-rate is the floor KPI, not PTP capture. CarmaOne (vendor) claims 85%+ PTP-to-payment with omnichannel follow-up vs breakage when the promise lives only in CRM notes.

**Shape:**

- On PTP capture (bot or human): persist amount + date + channel; send SMS/WhatsApp/in-app confirm; attach pay-link; schedule reminder for the promised date.
- Disposition is structured from the turn — no free-text-only wrap-up as the source of truth.
- Broken vs kept computed from ledger, not agent honour system.

**Reuse:** `promises`, `promise_reminders`, `payment_intents`, WhatsApp outbound, `bot_worker` settle tick.  
**Done when:** every PTP has a written artefact timestamped within minutes of the call, and keep/break is automatic.

**Shipped:** capture (voice / bot / human) creates one `payment_intent`, queues WhatsApp (template outside the 24h window, freeform inside) or SMS fallback, schedules a due-date reminder, and speaks channel last-4 without reading the URL. Payment records to the ledger and marks kept/partial; after the promised IST day with no credit the promise auto-breaks. Agents cannot mark kept without a recorded payment.

**Still out of this item:** live in-call UPI collect; Razorpay checkout creation (hosted sandbox “mark paid” only); in-app confirm channel. Broken-PTP *next action* is P5, not this.

### P3 — Next-best-treatment engine

**Status:** done (shadow) — 14 Aug 2026

**Chore it kills:** Manager guessing channel / time / human vs bot.  
**Decision:** Same shape as reco: features → veto (DND, hours, frequency) → score → act. Shadow first.

**Context:** This is the collections analogue of `agent_core/reco`. Reco answers “which product, if any.” Treatment answers “which action, if any”: silence, SMS, WhatsApp, voice bot, human, field, legal. Credgenics/CarmaOne both sell “best channel, frequency, tonality, timing by risk.” We should own this as a gated engine, not as prompt text.

**Shape:**

- `recommend_treatment(customer_id, account_id, trigger)` → `{action, channel, suppress, reasons}` .
- Vetoes (non-negotiable): calling hours, DND/opt-out, origination consent, daily/weekly cross-channel cap, cooling-off, third-party contact, hardship hold, legal hold, collection-vs-upsell separation.
- Scorer may rank remaining actions; may not resurrect a vetoed action.
- Modes: `off` | `shadow` | `live`, default **shadow**. Log every invocation including suppressed.
- Do not let conversion weights dilute vetoes (same reason reco splits scoring from arbitration).

**Reuse:** `agent_core/reco` pipeline, `consent_records`, `channel_consents`, `routing_rules`, `offer_decisions`-style log table.  
**Done when:** shadow logs exist for two weeks of production-like traffic, with a suppression breakdown, before any live auto-act.

**Shipped:** `agent_core/treatment/` — `recommend_treatment()` returns `{action, channel, at, expectedValue, suppressed, reason, rationale}` over the ladder `wait | sms | whatsapp | voice_bot | human_call | field_visit | legal_notice`. Same pipeline shape as reco (features → candidates → veto → score → arbitrate → log), shadow by default, unrecognised mode degrades to shadow.

Three things worth naming:

- **The score is in rupees**, not a 0–1 opinion: `exposure × recovery_fraction × p(reach) × p(resolve|reach) × decay(delay) − cost − fatigue`. `wait` scores exactly 0, so every action has to beat silence. A collections head can argue with "an agent call is worth ₹68 here"; nobody can argue with "0.62".
- **Timing is part of the decision, not a follow-up question.** Each candidate is planned to an instant *before* it is vetoed — asking "may we dial?" at 02:00 answers no for every borrower alive. Digital nudges are timed to the salary credit when the bounce was for insufficient funds; dials prefer an hour the borrower has historically answered at; field visits take a day's notice and skip Sunday.
- **The channel vetoes are delegated to `contact_policy.evaluate()`**, not reimplemented. New: `treatment_holds` (hardship / dispute / complaint / bereavement / legal) gives the five "stop dunning this person" cases a row, so a bot at 02:00 is bound exactly as a supervisor is. `legal` still permits a statutory notice; `dispute` still permits a specialist call about the dispute itself.

Wired into: bounce ingest (decides the step after the statutory pay-link, inside the same transaction), the settle tick (a broken PTP's follow-up now carries the plan and its reasoning instead of "Broken promise follow-up"), voice escalation (`hardship` / `dispute` places a hold), and the offer engine (`reco.arbitration` reads the same holds — the Digital Lending Guidelines' collection-vs-upsell separation). API: `GET /treatment/next`, `GET /treatment/insights`, `GET|POST /treatment/holds`, `POST /treatment/holds/{id}/release`.

An LLM re-ranker (`TREATMENT_LLM_RERANK`, default off) may reorder the already-approved shortlist and draft one line of rationale. It cannot introduce an action, resurrect a vetoed one, change a channel or an instant, or put a figure on screen that is not in the payload it was given — the rationale is rejected outright if it contains an unknown number. Borrower speech reaches that context through the account summary, so those are enforced in code rather than requested in the prompt.

**Still out of this item:** `field_visit` and `legal_notice` are recommended and logged but have no executor — that is P8 and P9, and until then they are recorded as `cancelled` with the executor named rather than retrying forever. Deliberately so: the shadow log tells a collections head how much field work the ladder would generate *before* anyone builds the dispatcher. The unit-economics constants and reach/resolve priors are planning figures; replacing them with measured ones is what the shadow fortnight is for. No propensity model yet — `EVScorer` is the only scorer, with the seam (`Recommender`) and the logged feature vectors already in place.

### P4 — Live authority matrix

**Status:** done (shadow default) — 14 Aug 2026

**Chore it kills:** “I’ll escalate your waiver.”  
**Decision:** Yes / no / max rupees inside policy on this call. Else specialist with the packet ready.

**Context:** Policy corpus: agents must not invent or waive late fees; must not quote settlement %; hardship → specialist. Today that becomes a dead moment. McKinsey: agents with real-time negotiation support saw ~6% recovery lift. The matrix is policy-as-code, not LLM generosity.

**Shape:**

- Rules keyed by product, DPD, ticket, tenure, fee type: `auto_approve` | `cap_inr` | `escalate`.
- Bot/human UI shows the allowed move before speaking it.
- Escalation packet: transcript, asked amount, policy reason, customer 360, ability-to-pay signals.
- Never allow the model to invent a number outside the cap (`suggest_amount()` already has this discipline for upsell).

**Reuse:** routing `waiver_request` rule, prompt guardrails `neverPromiseWaiver`, disputes `fee_waiver`.  
**Done when:** in-policy fee goodwill can close on the call; out-of-policy always warm-transfers with a packet, never a quote.

**Shipped:** `agent_core/authority/` — `recommend_authority()` never raises. Shadow default. Floor / Handoff / 360 show the allowed move. `apply_goodwill` posts in live mode. `authority-cap-exceeded` is a live QA barge trigger.

### P5 — Broken-PTP auto-next-action

**Status:** done (shadow) — 14 Aug 2026

**Chore it kills:** Tomorrow’s huddle.  
**Decision:** Retry, human, or field — with transcript — the hour it breaks.

**Context:** ClearTouch: telecaller CRM and field app often do not share real-time PTP. Promise dies in the gap. Floor managers are paid on PTP kept %, not PTP made %.

**Shape:**

- On keep-by date with no matching ledger credit: mark broken, invoke treatment engine.
- Default ladder: reminder → bot retry in preferred window → human → field (only if digital exhausted and ticket/DPD warrant).
- Field packet includes full interaction history, last PTP, and geo if we have it.

**Reuse:** `promises.status`, `followups`, treatment engine (P3).  
**Done when:** a broken PTP does not wait for the next morning allocation.

**Shipped:** `agent_core/treatment/followthrough.py` closes the loop that turns P3's single verdict into a ladder.

- **Attribution.** Every enacted decision gets an `outcome`. Payment beats a promise beats a connection beats silence, and an attempt is only called unanswered after a grace period sized to the channel — a follow-up sitting in an agent's queue is not a no-answer an hour later. This is the training label the corpus has no other way to get.
- **Counterfactuals.** Shadow decisions are attributed too, and only ever as `paid` / `ptp` / `superseded` — never `no_answer`, because nobody asked. A plan the engine made, nobody carried out, on an account that paid anyway is the only evidence that would ever say the engine is reallocating spend rather than earning it.
- **The ladder climbs by itself.** Re-decision passes the same trigger back to the engine; the previous attempt is already in `contact_events`, which is what `policy.last_rung_used` reads. Nothing tells it to escalate.
- **It stops.** Attempt cap (5), retry backoff (12h), and a steep repeat-action penalty. That last one came out of running the ladder against real seed data: a pure expected-value ranker sends the cheapest channel forever, because ₹0.42 always beats ₹7.50 on a small balance — four identical unanswered WhatsApps, which is precisely the persistent-contact pattern the ladder exists to prevent.
- **A payment retires the plans.** The worst thing a collections system can do is ring somebody about a debt they have already paid, and a plan scheduled for 18:00 does not know about a payment at 15:00 unless something tells it.

`GET /treatment/cases` is the ladder view — one row per case with the rungs already walked.

**Still out of this item:** the loop *decides*; outside `TREATMENT_MODE=live` nothing is dispatched, which is the intended order. `field_visit` and `legal_notice` still have no executor (P8, P9). Outcome attribution reads the evidence this schema already has — ledger payments, promises, inbound messages, WhatsApp job failures; per-message delivery receipts and call dispositions would sharpen `reached` vs `no_answer` considerably.

### P6 — Cross-channel contact cap (hard gate)

**Status:** done — 13 Aug 2026

**Chore it kills:** DND spreadsheet + over-dial harassment.  
**Decision:** Block the 4th touch today across voice + WhatsApp + SMS. Persistent calling becomes impossible.

**Context:** RBI forbids persistent calling. Human floors (vendor) breach frequency 15–20% because agents, shifts, and channels are not one ledger. A borrower can be “in limit” on each channel and overwhelmed in aggregate.

**Shape:**

- Central `contact_events` across voice, SMS, WhatsApp, email, field.
- Before every outbound: check daily cap (typically 2–3), weekly cap, cooling-off, opt-out, hours.
- Fail closed. Campaign config cannot override system-level gates.
- Include bot and human and agency in the same cap.

**Reuse:** `consent_records`, `channel_consents`, `optout_events`, `contact_events`, `contact_policy.admit`.  
**Done when:** it is impossible to place a 4th same-day touch even if a campaign is misconfigured.

**Shipped:** `contact_policy.admit()` is fail-closed on voice outbound, WhatsApp drain, PTP confirm, due reminder, inbox send, bot reply, and document delivery. Daily budget is `contact_day_counters` locked `FOR UPDATE`. Statutory PTP confirms still send and still count. Consent UI `usedThisWeek` is the ledger, not a resettable PATCH field.

**Still out of this item:** field visits; inbound counting; campaign-level cap override (deliberately impossible); P1 bounce blast and P5 auto-retry as consumers of this gate.

### P7 — 100% live QA → barge

**Status:** done (auto-barge shadow) — 14 Aug 2026

**Chore it kills:** 2–5% sampling weeks later.  
**Decision:** After-hours, threats, third-party leak, skipped disclosure: flag and supervisor now.

**Context:** RBI inspectors do not pull from the QA sample. They pull the complained call. Sampling is hope. Product already has scorecards, calibration, live alerts, supervisor actions. Make them the path, not a report.

**Shape:**

- Score every interaction against FPC rubric: hours, identity/purpose in first seconds, grievance disclosure, banned phrases, third-party leak, DND honour.
- Live alert → floor command barge/whisper for high severity.
- QA humans become uncertainty adjudicators, not sample listeners.
- Export pack for examiner: any call, last 12 months, timestamped spans.

**Reuse:** `qa_scorecards`, `violations`, `live_alerts`, `supervisor_actions`, `interaction_disclosures`.  
**Done when:** coverage is 100% of calls, and a critical flag can barge within the same call.

**Shipped:** `agent_core/live_qa/` — `evaluate_live_qa()` never raises. Deterministic FPC on every voice/WhatsApp turn writes flags, violations, live alerts, and a scorecard on hangup. Critical cells are locked (`[live]`); the gated LLM autoscore cannot clobber them. Floor barge reuses `twilio_ops.warm_transfer_to_supervisor` via `voice_sessions.provider_call_id`; no CallSid → CRM takeover only. Whisper injects a coach note through the turn-critic developer-message path. Listen stays the live transcript. `GET /qa/coverage` is the hero metric; `GET /qa/interactions/{id}/pack` is the examiner zipper. `LIVE_QA_BARGE_MODE` defaults to shadow.

**Still out of this item:** conference-from-start listen/whisper audio (Media Stream as a conference participant); auto-LLM scoring of human agents; auto-barge on sentiment_drop / long_hold.

### P8 — Field same-day packet

**Chore it kills:** ₹800–1,500 visits to empty houses on 2-day-old notes.  
**Decision:** Visit only when digital exhausted; GPS proof; outcome in LMS before sundown.

**Context:** Field is the last escalation, not the primary channel. Dista / Finezza: proximity assignment, geo-tagged visit, outcome at point of visit, same-day LMS sync. Aaxonix gold-loan NBFC: paper receipts meant 2–3 day recon lag; digital receipts → 91% same-day recon.

**Shape:**

- Treatment engine may emit `field_visit` only after digital exhaustion + ticket/DPD rules.
- Packet: transcript, PTP, last touches, consent, 1-day prior notice artefact (2027 directions).
- Outcome capture: paid / PTP / not home / escalate — in the system, not a spreadsheet after base return.
- Out of scope for v1: full agency mobile app. v1 can be a dispatch queue + GPS check-in webhook.

**Reuse:** `callbacks`, `followups`, `work_items` view, activity log.  
**Done when:** a field case cannot be opened without a packet, and visit outcome updates DPD/next-action the same day.

### P9 — Statutory clocks + persistency

**Chore it kills:** Legal/ops calendars in Excel; 13th-month lapse.  
**Decision:** NI Act 30-day, SARFAESI 60-day, IRDAI renewal window — start on the event.

**Context:** Missed statutory notice invalidates recovery. Insurance persistency is the other P&L: 86 lakh lapses, ₹8.7 lakh crore cover. Pre-due reminder economics apply 1:1 to premium due.

**Shape:**

- Clock objects: start on bounce / NPA class / premium-due. Templates, dispatch, countdown, owner.
- Legal-hold bucket at 90/120 DPD: extended retention, hash, legal chain of custody.
- Persistency campaigns: 13th-month (and 25th) as first-class pre-due books, sharing treatment engine + contact cap with loans so one customer is not double-dialled.
- Unified customer contact budget across loan + policy.

**Reuse:** document templates/delivery, consent cap (P6), treatment (P3), bounce events (P1).  
**Done when:** a bounce starts a 30-day notice clock without a clerk, and a policy approaching 13th month enters the same pre-due machine as an EMI.

---

## 9. Suggested sequencing

Do not parallelize the brain. Sequence so each step has a veto the next step can trust.

```
P6 contact cap (hard gate)            [done 13 Aug 2026]
  → P1 bounce-to-contact              [done 13 Aug 2026]
    → P2 written PTP + pay-link       [done 13 Aug 2026; shipped ahead of P6/P1]
      → P3 treatment engine (shadow)  [done 14 Aug 2026]
        → P5 broken-PTP next action   [done 14 Aug 2026]
          → P4 authority matrix       [done 14 Aug 2026]
            → P7 live QA → barge      [done 14 Aug 2026; auto-barge shadow]
              → P8 field packet       [open — P3 emits field_visit; nothing carries it out]
                → P9 clocks + persistency [open — P3 emits legal_notice; nothing serves it]
```

P6 before P1 so the first automated blast cannot harass. P3 in shadow before P5 so we do not auto-dispatch field from an unmeasured scorer. P2 shipped first because the clerk gap (written confirm + keep/break) did not depend on bounce orchestration. P6 followed so PTP confirms and due reminders now share one borrower-frequency ledger.

---

## 10. Reco pattern — copy this, do not bypass it

From `backend/agent_core/reco/README.md`:

- Pipeline: features → candidates → eligibility veto → score → arbitrate → log.
- Scoring answers *which*; arbitration answers *whether*. Never fold a compliance rule into a score penalty.
- `recommend()` never raises. “No action” is always valid.
- Shadow default. Unrecognised mode degrades to shadow, not off.
- Unknown facts are absent, not zero.
- Every invocation logged, including suppressed — those are the counterfactuals.

Treatment engine must inherit all of the above. An LLM re-ranker may reorder already-approved actions and draft phrasing. It must not introduce an action that did not pass veto.

---

## 11. Sources

Opened or fetched 12 Aug 2026:

- RBI DOR.ORG.REC.65/21.04.158/2022-23 — [notification](https://rbi.org.in/Scripts/NotificationUser.aspx?Id=12378&Mode=0)
- McKinsey — [gen-AI credit customer assistance](https://www.mckinsey.com/capabilities/risk-and-resilience/our-insights/the-promise-of-generative-ai-for-credit-customer-assistance) (Jun 2024); [holistic digital-first collections](https://www.mckinsey.com/capabilities/risk-and-resilience/our-insights/holistic-customer-assistance-through-digital-first-collections)
- Caller Digital — [DPD bucket playbook](https://caller.digital/blog/ai-voice-bot-nbfc-collections-dpd-bucket-playbook); [100% QA](https://caller.digital/blog/voice-ai-call-qa-scoring-100-percent-audit-india-2026); [FPC for AI calls](https://caller.digital/blog/rbi-fair-practices-code-ai-collection-calls-india-2026)
- Finezza — [NACH, DPD triggers, field workflows](https://finezza.in/blog/nach-loan-collections-guide-2026/)
- Credgenics — [digital communications / Swara](https://credgenics.com/digital-communications-solutions) (private-bank case: 40% engagement, 35% calling-cost, 25% time-to-collect)
- CarmaOne — RBI-compliant AI collections; omnichannel playbook (40% recovery / 60% cost-per-rupee claims — vendor)
- AiXBFS telecaller JD; ClearTouch telecaller↔field gap; Gistly QA 2–5%; Gyansurance / IRDAI persistency FY24–25
- Product: `backend/DATA_MODEL.md`, `backend/agent_core/reco/README.md`, `source_db/policy/Collections_policy.md`, Habibi sidebar / brand

Vendor numbers are labelled. Do not put them in customer-facing decks as our results.
