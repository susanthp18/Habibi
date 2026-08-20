---
name: insurance-lapse
description: Handle insurance lapse and eligibility. Reco picks the product. Capture a lead after consent. Do not quote premium from memory or skip recording disclosure.
allowed-tools:
  - recommend_next_offer
  - check_product_eligibility
  - capture_lead
  - request_documents
  - get_customer_context
metadata:
  version: 1.0.0
  data_class:
    - pii
    - marketing
  eval_suite: skill.insurance-lapse
  mouth:
    - voice
    - whatsapp
---

# Insurance lapse

Same catalog as collections upsell, different card. Consent and reco still bind.

Do not quote a premium, NCD, or coverage limit unless it came back from eligibility/reco. Document requests go through `request_documents`, never a invented portal.
