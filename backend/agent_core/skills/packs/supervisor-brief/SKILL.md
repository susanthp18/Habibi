---
name: supervisor-brief
description: Compact warm-transfer brief for the receiving human. No CRM writes. The handoff tool already fired; this card only briefs.
allowed-tools: []
metadata:
  version: 1.0.0
  data_class:
    - pii
    - internal
  eval_suite: skill.supervisor-brief
  mouth:
    - internal
---

# Supervisor brief

Summarise: who the caller is, why they transferred, last tool outcome, open promise/dispute, and the one question the human should ask first.

Do not call tools. Do not invent an account position.
