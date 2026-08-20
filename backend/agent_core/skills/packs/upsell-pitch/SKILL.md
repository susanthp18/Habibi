---
name: upsell-pitch
description: After the primary query is resolved, speak one reco-engine product. Never invent a product id. capture_lead or decline_offer only. Reco suppression stays quiet.
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
---

# Upsell pitch

The reco engine chooses. The mouth speaks at most one product, late in the call, after the collections ask is handled.

## Steps

1. Call `recommend_next_offer`. If the engine stays quiet, do not freelance.
2. Optionally `check_product_eligibility` for the returned product id.
3. On interest, `capture_lead`. On refusal, `decline_offer`.

## Never

- Never name a product that was not in the reco payload.
- Never pitch during hardship, dispute, or abuse.
