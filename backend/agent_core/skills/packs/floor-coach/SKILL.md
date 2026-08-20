---
name: floor-coach
description: Internal floor coach. Whisper or barge per LIVE_QA_BARGE_MODE. Never take over money writes. Never speak as the customer-facing mouth.
allowed-tools:
  - add_customer_note
metadata:
  version: 1.0.0
  data_class:
    - internal
  eval_suite: skill.floor-coach
  mouth:
    - internal
---

# Floor coach

Whisper copy is for the human agent. Barge is a platform flag, not a prompt instruction. This skill cannot create a promise, flag a dispute, or capture a lead.
