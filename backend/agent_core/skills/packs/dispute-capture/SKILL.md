---
name: dispute-capture
description: Record a dispute (paid already, wrong amount, not my account). Call flag_dispute. Treatment vetoes collection. Do not negotiate PTP on a live dispute.
allowed-tools:
  - flag_dispute
  - evaluate_authority
  - apply_goodwill
  - add_customer_note
  - escalate_to_human
  - get_customer_context
metadata:
  version: 1.0.0
  data_class:
    - pii
    - money
  eval_suite: skill.dispute-capture
  mouth:
    - voice
    - whatsapp
---

# Dispute capture

A live dispute vetoes collection treatment. The write is `flag_dispute`, not a note pretending to be a case.

## Steps

1. Classify: `paid_already`, `wrong_amount`, `not_my_account`, or other allowed type.
2. Call `flag_dispute` with type and a one-line summary in the caller's words.
3. Stop PTP / upsell language. Escalate if the caller asks for legal next steps.

## Goodwill on a resolved dispute

Only where a late fee is the thing in dispute, and only in this order:
`evaluate_authority` decides whether a waiver is in policy and for how much,
then `apply_goodwill` posts that decision at or below the approved amount. The
engine owns the number; this skill owns neither.

The `handle_dispute` step of the built-in script has offered both tools since it
was written, but `apply_goodwill` was on no pack, so the grant dropped it and
the agent could size a waiver it had no way to post.

## Never

- Never argue the ledger from memory.
- Never call `create_promise_to_pay` while this skill is active.
- Never call `apply_goodwill` without a `decision_id` from `evaluate_authority`,
  and never for settlement, restructuring or bounce charges.
