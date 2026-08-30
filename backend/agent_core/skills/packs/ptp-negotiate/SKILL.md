---
name: ptp-negotiate
description: Negotiate a Promise-to-Pay. Authority decides the cap; DND blocks writes outside the calling window. Call create_promise_to_pay only after verify. Use run_skill_script for EMI remaining and date-in-window.
allowed-tools:
  - create_promise_to_pay
  - capture_nonpayment_reason
  - evaluate_authority
  - request_callback
  - get_customer_context
  - get_account_position
  - get_emi_schedule
  - run_skill_script
metadata:
  version: 1.5.0
  data_class:
    - money
    - pii
  eval_suite: skill.ptp-negotiate
  mouth:
    - voice
    - whatsapp
---

# Promise-to-Pay negotiate

The mouth speaks a date and amount. The engines decide whether the write is legal.

## Steps

1. Confirm identity already passed this call. If not, stop and load `verify-and-disclose`.
2. Call `run_skill_script` with `emi_remaining` when the caller asks how many EMIs are left.
3. Call `run_skill_script` with `promise_date_in_window` before offering a date. Preferred window is `10:00-19:00 IST` unless the CRM card says otherwise.
4. Call `evaluate_authority` before any concession language.
5. Call `create_promise_to_pay` with amount and ISO date. A spoken promise with no row is a miss.

## Never

- Never write a PTP for a DND customer or outside the calling window.
- Never promise a waiver; goodwill is a different skill and a locked engine.
- Never accept a date the script marked `in_window: false`.
