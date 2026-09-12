# Identity is an assurance level, and a gate states its remedy

---
Status: accepted
---

`identity_verifications` had never received a single row from the text channel.
Every row in the live table came from a voice call, so on WhatsApp every gated
tool was refused, permanently. In one live thread three refusals landed in a row
— `recommend_next_offer`, `capture_nonpayment_reason`, `add_customer_note` — and
the bot responded by offering a callback, which is also gated.

The cause is one line in `capture.rebind_interaction_customer`:

```python
# Tail-only matches are never treated as full verification (schema: pending).
if method == "account_tail" and verification_status == "verified":
    verification_status = "pending"
```

`gates.interaction_identity_verified` required `status = 'verified'`. So the only
ceremony a customer can naturally perform in a chat thread — the last four digits
of their account — wrote a row that could never open the gate. The alternative,
`phone_match`, asks a customer to type back the number the bot is already
messaging them on. Meanwhile `voice/persist.record_identity_verification` has no
downgrade at all: on a phone call the same `account_tail` writes `verified`. Two
channels, one method, two meanings, and `gates.py`'s own docstring asserting the
opposite of what the code did.

The downgrade was not wrong about strength. A tail *is* weaker than a tail plus a
proven endpoint. What it got wrong is that strength is not binary, and that a
proven endpoint is worth something on its own.

## Decision

**Three levels, and tools declare which they need.**

| Level | Earned by | Opens |
|---|---|---|
| `none` | — | nothing gated |
| `endpoint` | the channel proved the customer controls the endpoint — on WhatsApp, Meta verified the number and we matched it to a CRM row | reads, and the reversible writes: a note, a callback, a contact preference, an offer |
| `challenge` | the customer supplied something only they know — account tail, DOB, OTP | money and regulated acts: promise to pay, dispute, goodwill, document requests, transfer to a human |

Caller ID on a voice call does **not** earn `endpoint` — ANI is spoofable, which
is why voice asks for spoken digits in the first place.

**And a blocked gate returns the remedy, not just the code.** `gate_failure`
returns `{error, tool, required, have, hint}`. Voice has done this since it was
written (`{"error": "need_digits", "hint": "ask_caller_for_last_4_of_account"}`);
text returned a bare `human_gate_identity`, which is how a model tried three
gated tools in a row and learned nothing from any of them.

## Considered options

**Flip the downgrade and keep the boolean.** Simplest, and it opens
`create_promise_to_pay` to anyone whose handset is unlocked. The whole reason the
downgrade existed was a real intuition about strength; deleting it without
replacing it throws that away.

**Treat an inbound WhatsApp from a known number as fully verified.** Rejected for
the same reason. Meta proves possession of a handset, not that the person holding
it is the borrower.

**Derive `endpoint` at gate time instead of writing a row.** Tempting — it is a
standing property of the thread, not an event, and it needs no write. Rejected on
two counts: a regulated collections product should be able to answer *when* a
customer was verified from a record rather than a recomputation, and
`db_bot_analytics`'s containment funnel reads this table, so a derived level would
leave the funnel reporting 0% verified for every WhatsApp interaction with every
later stage collapsing underneath it.

**A new column for the level.** Unnecessary. `identity_verifications.method` is
already stored, already constrained to the five methods, and already says exactly
this. No migration.

## Consequences

**`escalate_to_human` is still ungated**, for the reason already recorded in the
module: reaching a person must never require passing a ceremony the customer is
failing. `request_callback` moves to `endpoint` for a weaker version of the same
argument — it was gated at the strongest level while being the thing the model is
told to offer when it cannot help.

**`enforce_human_gate` survives as a shim, and reads `True` as `challenge`.** A
caller still speaking in booleans has not been taught about the weak level, and
reading its `True` as merely `endpoint` would silently open money tools to a phone
match — the opposite of what that caller believes it is asserting.

**The Sandbox rehearses levels too.** It tracked a `simulated_identity_verified`
flag, so an operator could not see that a promise-to-pay needs a challenge while a
callback does not. It now derives the level from the rehearsed `identify_customer`
arguments, the same way production does.

**One card-shaped thing is unchanged and deliberately so.** A card can still only
declare `human_gate: identity`; *how much* identity is this module's call, keyed
on the tool. A card authored before levels existed therefore gets the right
strength for whatever it is gating, and no author has to restate a risk judgment
the platform already owns.
