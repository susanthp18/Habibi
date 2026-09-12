# The borrower is told what the record says now

---
Status: accepted
---

A message that actually reached a customer:

> "We've recorded your promise to pay ₹4,800 by **28 Aug 2026**. Pay securely
> here: … This link is valid until **23 Aug 2026**, 11:59 PM IST."

A payment link that dies five days before the money is due, in a sentence that
contradicts itself. `_confirm_copy` reads the date off the **promise** and the
amount and expiry off the **intent**, and those two records had stopped agreeing:

```
PI-E71780FF85   promise PTP-SUSANTH-1   promised_at 2026-08-28
                                        expires_at  2026-08-23
```

`create_pay_intent`'s reuse path was `return dict(existing)`, discarding the
`amount` and `expires_at` its caller had computed three lines earlier from the
live promise. There is no `UPDATE payment_intents SET expires_at` anywhere in the
tree, so once an intent existed its expiry was frozen at whatever the promise
date had been when it was minted. And `db.patch_promise` — the only path that
moves `promised_at` — never re-entered fulfilment at all.

## Decision

**Reuse refreshes.** All three reuse paths (by promise, by payment event, and the
raced-insert recovery) go through `_refreshed`, which re-derives `amount` and
`expires_at` from the live promise and writes them if they have moved.
`patch_promise` re-enters `fulfill` when it changes the date.

Reuse itself is not optional: `uq_payment_intents_open_promise` permits exactly
one open intent per promise, and that index is the reason the reuse branch exists
at all. So the fix is to refresh the row, not to mint a second one.

**The token and URL are deliberately untouched.** The borrower may already be
holding that link; rotating it would break the one they have in order to fix the
sentence describing it.

## Consequences

**A re-fulfil that fails does not fail the reschedule.** The operator's edit is
the record; the message is a consequence of it. The re-entry is wrapped in a
savepoint and logged.

**Two adjacent honesty bugs go with it**, because they are the same mistake in
different places:

*The reminder drain would quote a dead link.* It read the latest intent for a
promise with no `OPEN_INTENT` filter — unlike every other read of that table — so
the expiry sweep could mark an intent `expired` and this would still send its URL
alongside a validity date that had already passed. It now refuses.

*A job said `succeeded` when Meta had rejected the message.* The POST was
accepted, so the job was marked succeeded; Meta then failed the message in a
status callback, and the handler wrote the reason onto the row and left the
status alone. `WAO-14F8282BF6AC` reads `succeeded` while carrying
`code=131047 … Message failed to send`, with its message row reading `failed`.
Anything counting job status over-reported delivery. `failed` has been legal in
the check constraint since the table was created and written by nothing; it is
now written here, and only from `succeeded`, so a late callback cannot resurrect
a dead job or disturb a queued one.

**The template fallback is no longer silent.** `WHATSAPP_PTP_TEMPLATE_NAME` is
unset on this deployment and the last resort is
`jaspers_market_order_confirmation_v1` — Meta's sample grocery-order template —
standing in for a bank's payment links. Meta validates parameter *count*, so
arity is guarded for us; the body *text* is not, and a template registered for
something else sends cleanly and says the wrong thing. The fallback is still
used, because with no template at all an out-of-window send simply does not
happen and silently not telling a borrower about their own promise is its own
failure. But it now warns on every resolution, naming the variable that would
stop it.

## What this does not fix

`_intent_expiry` gives a promise dated today or earlier a **30-minute** link.
That is the documented behaviour and it is left alone, but it means a
back-dated reschedule produces a link with a very short life. Worth revisiting
with real data on how often borrowers pay against a same-day promise.
