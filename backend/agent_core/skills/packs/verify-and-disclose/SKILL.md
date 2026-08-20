---
name: verify-and-disclose
description: Verify the caller and disclose recording before any account fact. Call verify_identity, then read context. Never skip disclosure or share dues with an unverified party.
allowed-tools:
  - verify_identity
  - get_customer_context
  - add_customer_note
metadata:
  version: 1.0.0
  data_class:
    - pii
    - money
  eval_suite: skill.verify-and-disclose
  mouth:
    - voice
    - whatsapp
---

# Verify and disclose

Identity is a ceremony, not a prompt line. Do not quote outstanding, DPD, or EMI until `verify_identity` has succeeded on this call.

## Steps

1. Disclose that the call is recorded for quality and compliance.
2. Ask for a verification factor the CRM already holds (DOB, last four, registered mobile).
3. Call `verify_identity`. On failure, retry once; then offer a callback or escalate.
4. Only after success, call `get_customer_context`. Account position, EMI, and PTP writes belong to later skills — this pack must not grant them.

## Never

- Never read the full account number back.
- Never continue collections with a third party (`not_account_holder` path).
- Never invent a verification match.
