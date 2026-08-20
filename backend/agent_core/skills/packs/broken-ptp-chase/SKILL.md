---
name: broken-ptp-chase
description: Follow up a broken promise. Respect attempt caps and DND. Offer a new date or a callback. Do not threaten. Treatment followthrough owns the cadence.
allowed-tools:
  - request_callback
  - add_customer_note
  - get_customer_context
metadata:
  version: 1.0.0
  data_class:
    - money
    - pii
  eval_suite: skill.broken-ptp-chase
  mouth:
    - internal
    - whatsapp
---

# Broken PTP chase

Treatment followthrough decides whether this account is due a chase. The mouth does not invent a fourth attempt.

## Steps

1. Read open promises from the CRM card. If none are broken, do not chase.
2. Acknowledge the missed date without blame.
3. Offer `request_callback` inside the window. A new Promise-to-Pay is `ptp-negotiate` — this chase pack must not write money.
4. Stop when attempt cap or DND says stop.

## Never

- Never mention police, legal action, or family members paying.
- Never call outside the preferred window.
