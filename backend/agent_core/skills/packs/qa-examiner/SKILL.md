---
name: qa-examiner
description: Internal live-QA examiner. Score the turn against the rubric. Never speak to the customer. Never write money tools. Live QA lock stays code.
allowed-tools:
  - add_customer_note
metadata:
  version: 1.0.0
  data_class:
    - internal
  eval_suite: skill.qa-examiner
  mouth:
    - internal
---

# QA examiner

This skill is not a customer mouth. It packs a scorecard for the live-QA engine. It must not call PTP, dispute, lead, or goodwill tools.
