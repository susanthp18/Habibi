---
name: upsell-pitch
description: After the primary query is resolved, let the offer engine record what could be offered later on a consented channel. Never mention a product yourself; answer only a product the customer raises.
allowed-tools:
  - recommend_next_offer
  - check_product_eligibility
  - capture_lead
  - decline_offer
metadata:
  version: 1.0.0
  data_class:
    - marketing
    - pii
  eval_suite: skill.upsell-pitch
  mouth:
    - voice
  intents:
    - upsell_opportunity
---

# Upsell pitch

The offer engine chooses, and the offer is delivered later on a separate, consented message. The mouth never mentions a product on this call.

## Steps

1. Call `recommend_next_offer` once. It records the offer and returns nothing to say.
2. Only if the customer raises a product themselves: answer from the knowledge base, `check_product_eligibility` if they ask whether they qualify.
3. On their interest, `capture_lead`. On their refusal, `decline_offer`.

## Never

- Never name, hint at or describe a product the customer did not raise.
- Never pitch during hardship, dispute, or abuse.
