# Demo script — Susanth, voice sandbox, Collections-clone

Recorded on the **Collections-clone** agent (`collections-clone-9ff4b6`, published
`v1.0` / `v1_0-c300e3`, active at 100% traffic). Every figure below is read from
the live CRM, and every step was checked against the published flow graph before
this was written.

---

## Before you hit record — two blockers

### 1. The upsell will not speak unless you turn the offer engine on

`RECO_MODE` is unset, which defaults to **shadow**: the engine scores and logs
every decision and presents nothing. Verified for `cust-susanth` — and for two
other customers, so it is not about Susanth:

```
suppressed: True   reason: shadow_mode   offers: 0
```

With `RECO_MODE=live` and a promise-to-pay already recorded on the call:

```
suppressed: False
OFFER  credit-card  Credit Card  ~₹1,10,000  reasons: comfortable_headroom, positive_sentiment
OFFER  gold-loan    Gold Loan    ~₹1,10,000
```

Add to `backend/.env`, then restart the voice runner:

```bash
RECO_MODE=live
```

### 2. Do NOT end the call before you show the Handoff hub

The hub's queue only lists handoffs whose interaction is still `active`:

```sql
WHERE i.status = 'active' AND h.to_user_id IS NULL AND h.accepted_at IS NULL
```

My earlier test escalation (`HO-86DEA58E9C`, unclaimed, reason `sentiment_drop`)
is invisible today for exactly one reason — the call ended, so the interaction
went `completed`. **Escalate, leave the sandbox tab open with the call still
connected, switch tabs to Handoff hub, then come back and hang up.**

`VOICE_HANDOFF_MODE=callback_queue`, so escalation opens an Inbox thread and
queues a callback. Nobody's phone rings mid-recording.

---

## Setup checklist

| | |
|---|---|
| Agent | Collections-clone → **Publish** |
| Voice | William (change in Agent Tuning → Voice & delivery; applies live, no Apply button) |
| Scenario | any — verification is what binds the account, not the persona label |
| Verification answer | **2324** (last 4 of Susanth's registered mobile) |
| Budget | maxTurns **20**, maxSeconds **480** — the script below is ~15 turns / ~5 min |

**Persona caveat for the camera:** the sandbox persona card may say a different
name (e.g. Rahul Sharma). That is the tester's role-play label. Once you verify
with 2324 the agent is working the **real CRM record — Susanth, AC-SUSANTH**.
Say so on camera; it is a feature (CRM is authoritative), not a glitch.

## Susanth's real data — what the bot should say back

| Field | Value |
|---|---|
| Customer | Susanth · `cust-susanth` |
| Account | **AC-SUSANTH** · Personal Loan |
| Outstanding | **₹62,400** |
| Minimum due | **₹4,800** |
| Days past due | **32** (bucket 31–60) |
| Mobile | 91965528**2324** |
| Open dispute | `D-SUSANTH-1` — fee_waiver, under_review |
| Open promise | `PTP-SUSANTH-1` — ₹4,800 due 22 Aug |

If the figures the bot reads back don't match this table, stop and re-record.

---

## The order is not negotiable

**PTP → Upsell → Dispute → Escalate.**

Measured, not assumed: with a dispute already open on the call the offer engine
returns

```
suppressed: True   reason: dispute_open_this_call
```

Raise the dispute before the upsell and the upsell silently vanishes. The engine
also cites `positive_sentiment` as a reason code — so stay pleasant until the
offer has been made, then turn.

---

## The script

Timings are the caller's turns. Speak naturally; these are intents, not lines to
read word-for-word.

### 1 · Open (bot speaks first)

> **Bot:** greeting + records disclosure + "what can I help you with?"

**Watch for:** the recording disclosure is said **once**, at the top, and never
again. It is also correctly absent from the WhatsApp channel now.

---

### 2 · State your goal

> **You:** "Hi — I got a message about my loan. I want to sort out the payment,
> and I've got a couple of questions as well."

*Captures the call goal, then moves to verification framed around your goal.*

---

### 3 · Verify

> **Bot:** asks for the last 4 digits of your registered mobile
> **You:** "**Two three two four.**"

**Watch for:** no account figure is spoken before this point. That is the
compliance gate doing its job.

---

### 4 · Hear the position

> **Bot:** states outstanding **₹62,400**, minimum due **₹4,800**, ~32 days past due.
> **You:** "Yes, I know. Things were tight last month."

**Watch for:** it says the figures **once**. Re-entering the hub later will not
make it recite them again.

---

### 5 · PTP — the money commitment

> **You:** "I can pay the minimum. Can I do four thousand eight hundred this Friday?"

> **Bot:** confirms amount and date, calls `create_promise_to_pay`, then confirms
> the amount, the date and the channel the written confirmation went to.

**Watch for:** it asks for the date **like a person** — it will not say
"YYYY-MM-DD" out loud any more. And it never reads a payment URL aloud.

**On screen:** Trace tab shows `create_promise_to_pay`. A statutory PTP
confirmation SMS is queued to the customer.

---

### 6 · Upsell — the engine decides, not the model

The PTP transitions the flow to the upsell step automatically.

> **Bot:** offers **one** product — expect the **Credit Card, around ₹1.1 lakh**.
> **You:** "What is it exactly?"
> **Bot:** one-line explanation, offers a specialist callback.

**Optional compliance beat — a good one to catch on camera:**

> **You:** "What's the interest rate on that?"

The guardrail `neverQuoteRate` is on, so it will decline to quote a rate and
offer to have a specialist confirm — even though the engine's own talk-track
carries "36% APR". The model is not allowed to say it.

> **You:** "Go on then, have someone call me."  → `capture_lead`
> *(or "not right now" → `decline_offer` — both are clean demos)*

**Watch for:** it names a product the **engine** returned. It cannot invent one.

---

### 7 · Knowledge base — grounded answer

> **You:** "One more thing — I have travel insurance with you. What's not
> covered on it?"

**Bot:** searches the KB and answers from **Travel Protect360 — Policy** (93
indexed chunks): professional racing or sport, wilful criminal acts, hazardous
activities — then offers to go deeper on medical, baggage or trip cancellation.

**Watch for:** it gives you the headline plus two or three items and asks if you
want the rest — it will not read a 15-item list at you for thirty seconds.

**On screen:** Retrieval tab shows the chunks and the answerability verdict.
Verified this question retrieves the travel policy from both the hub and the
upsell step, so it is safe to ask here.

---

### 8 · Dispute — now the tone turns

> **You:** "Actually, hang on. There's a charge on this account I never made.
> Around twelve hundred rupees. I want that raised."

> **Bot:** classifies it, calls `flag_dispute`, confirms it is logged for review.

Use **"a charge I never made"** — that classifies as `not_my_account` or
`fraud`, both of which open a **fresh** dispute. Susanth already has an open
`fee_waiver` dispute (`D-SUSANTH-1`), so asking for a fee waiver may dedupe
against it and look like nothing happened.

**Watch for:** it does **not** promise a reversal. `neverPromiseWaiver` is on —
it can log a review, not grant one.

---

### 9 · Escalate

> **You:** "Honestly this is the second time. I want to speak to a person about it."

> **Bot:** calls `escalate_to_human` (reason `customer_requested` or `dispute`),
> apologises once, and tells you a human will call back.

**Watch for:** it stops selling immediately. No offers after an escalation.

---

### 10 · Handoff hub — **keep the call connected**

Do not press End. Leave the sandbox tab live, open **Handoff hub** in a second
tab.

You should see Susanth queued — customer name, account, reason, queue and a
climbing wait timer. Claim it to show the agent-side view: the transcript, the
disclosures already read, and the suggested next actions.

Then return to the sandbox tab and end the call.

---

## Recovery lines, if something drifts

| If | Say |
|---|---|
| It won't leave verification | "Last four of my mobile — two, three, two, four." |
| It skips the PTP | "I want to make a promise to pay — four thousand eight hundred, Friday." |
| No offer is made | RECO_MODE is still shadow. Stop, fix, re-record. |
| It talks over you | Just pause — barge-in is on, it will yield. |
| It re-states the balance | Note it and continue; worth flagging to me afterwards. |

## What to say over the top

- **After verification:** "No account data is spoken before identity is proven."
- **After the PTP:** "That is a real CRM write — promise, reminder, and a
  statutory confirmation, not a transcript note."
- **After the offer:** "The recommendation engine chose that, applied
  eligibility and consent, and gated it behind a commitment. The model cannot
  invent a product."
- **After the KB answer:** "Grounded in the indexed policy document, and the
  system records whether those passages actually answered the question."
- **After the dispute:** "It logs the grievance. It is not permitted to promise
  the outcome."
- **In the Handoff hub:** "The human picks up with the full context — what was
  said, what was disclosed, and what was already committed."
