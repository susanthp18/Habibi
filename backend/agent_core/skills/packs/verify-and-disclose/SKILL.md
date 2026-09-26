---
name: verify-and-disclose
description: Verify the caller with the last four digits of their registered mobile before any account fact. The recording line is said once, in the opening, and never again. Never share dues with an unverified party.
allowed-tools:
  - verify_identity
  - get_customer_context
  - add_customer_note
  - set_contact_preference
metadata:
  version: 1.1.0
  data_class:
    - pii
    - money
  eval_suite: skill.verify-and-disclose
  mouth:
    - voice
    - whatsapp
  intents:
    - balance_query
---

# Verify and disclose

Identity is a ceremony, not a prompt line. Do not quote outstanding, DPD, or EMI until `verify_identity` has succeeded on this call.

## Steps

1. The recording line is spoken once, in the opening sentence. After that it is done for the whole call. Never say it again, including on the turn that first states a balance.
2. Ask only for the last four digits of the registered mobile. A first name is not verification, including on a call you placed.
3. Call `verify_identity` with the digits they spoke. On failure, retry once; then offer a callback or escalate.
4. Only after success, call `get_customer_context`. Account position, EMI, and PTP writes belong to later skills — this pack must not grant them.

## Never

- Never read the full account number back.
- Never continue collections with a third party (`not_account_holder` path).
- Never invent a verification match.

## When they tell you when to call

If the caller states a restriction on when we may ring them — "not before ten",
"don't call me at work in the afternoons", "evenings only" — call
`set_contact_preference` with the hours they named, at the moment they say it.
It is the only way that sentence survives the call: RBI's 08:00-19:00 window
moves for a borrower who asks, and the window we dial against is read from the
consent record, not from the transcript.

It can only make the window smaller. If they say we may call any time, say
thank you and call nothing — lifting a restriction they set earlier is a
person's decision, not the agent's, and the tool will refuse it anyway.

Never infer a preference from the hour they happened to pick up.
