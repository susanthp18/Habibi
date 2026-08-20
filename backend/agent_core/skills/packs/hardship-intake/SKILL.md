---
name: hardship-intake
description: Capture hardship (job loss, medical, tenure). Write a note, hold treatment, do not pitch a product. Escalate if the caller asks for a waiver you cannot grant.
allowed-tools:
  - add_customer_note
  - escalate_to_human
  - request_callback
  - get_customer_context
metadata:
  version: 1.0.0
  data_class:
    - pii
    - money
  eval_suite: skill.hardship-intake
  mouth:
    - voice
    - whatsapp
---

# Hardship intake

Treatment holds collections. Reco stays quiet. The mouth does not freelance a product or a waiver.

## Steps

1. Acknowledge the situation in one sentence. Do not interrogate.
2. Call `add_customer_note` with the hardship kind (job_loss, medical, income_drop, other).
3. Offer a callback inside the calling window, or escalate when the caller asks for a concession beyond policy.
4. Do not call `recommend_next_offer` and do not name a product.

## Never

- Never capture a PTP on the same turn as a fresh hardship hold unless the caller clearly offers a date.
- Never quote a waiver amount.
