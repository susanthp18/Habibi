# A policy refusal is a schedule, not a failure

---
Status: accepted
---

`whatsapp_outbound` called `contact_policy.admit` before every send, and handed
the refusal to `mark_failed_or_retry`:

```python
if not decision.allowed:
    status = mark_failed_or_retry(conn, job, decision.reason or "contact_policy")
```

That function's entire contract is about Meta transport errors and the fact that
the WhatsApp Cloud API has no idempotency key. Its two classifiers read the
`whatsapp_send_failed:*` vocabulary. A reason like `cooling_off` is in a
different namespace, matches neither, and falls through to `attempt >= cap`.

The arithmetic made the outcome certain rather than unlucky. Cooling-off is 120
**minutes**; the ladder is five attempts with the backoff capped at 120
**seconds** — about 30 seconds of actual waiting, 480 in the worst case. The job
could not survive to the retry that would have succeeded. In the live queue:

```
dead  cooling_off             18
dead  outside_allowed_window   1
succeeded                      9
```

Nineteen messages discarded, none for a reason a borrower would recognise as a
failure. Every other caller of `admit` already routed refusals away from its
retry ladder — `written_followup`, `outbound.gate`, `treatment.enact`,
`promise_fulfillment`. This was the one site that did not.

## Decision

**Refusals split by whether they expire.**

A refusal about the *clock* — cooling-off, the daily and weekly caps, the
statutory hours, the borrower's own window — stops being true at a moment we can
name. `Decision` now carries `next_allowed_at`, and the queue reschedules to it.

A refusal about the *customer* — DND, a withdrawn or expired consent, an opt-out,
a settled account, an unverified endpoint — does not expire. Those cancel.

The deadline is computed from facts already in hand at each refusal site, and
shares `_statutory_window` / `_consent_window` with the veto that produced the
refusal, so *"why not now"* and *"then when"* cannot come from two readings of
the same rules.

## Considered options

**Special-case `cooling_off` in `mark_failed_or_retry`.** The smallest possible
patch, and it leaves the next reason to be discovered in production. The function
would also then be classifying two unrelated vocabularies, which is how it came
to have an opinion about a policy verdict in the first place.

**Give deferred jobs their own status.** Rejected: `run_after` already exists, is
already indexed (`ix_whatsapp_outbound_jobs_status_run_after`), and is already
honoured by `claim_next_job`. A deferral is `status='queued'` with a far-future
`run_after`, and needs no migration and no new state in the check constraint.

**Cancel everything and let the cadence raise a fresh job later.** Coherent — it
puts all timing in one place — but a statutory PTP confirmation would be silently
skipped, and that is the one message class the borrower is actually waiting for.

**Reschedule everything, with no expiry.** Rejected. A nudge whose moment has
passed is worse delivered late than not at all; it is what "why is this bank
messaging me about last Tuesday" looks like from the other side. Hence a TTL per
purpose: statutory 2 days, outreach 1 day, in-session 4 hours.

## Consequences

**A deferral does not count as an attempt.** Counting it would walk the job
toward the dead-letter cap for doing nothing but waiting — the original bug in
miniature.

**The denial-event spam stops on its own.** Every denied `admit` writes a
`contact_events` row, so one suppressed message wrote five of them. Not retrying
five times fixes that without a second change.

**Deferral honours each borrower's own window, not a global one.** Checked
against the nine customers whose messages actually died: the deadline lands at
09:00 IST for one and 10:00 for the others, because that is what each of them
consented to.

**`claim_next_job` now selects two columns it never did.** `created_at`, because
the TTL needs it — and `decision_id`, which was the adjacent bug. Nothing
selected it, so `job.get("decision_id")` was always `None`, the treatment session
key silently fell through to the conversation id, and `_finalize_treatment_send`
has no-opped on every message since the column was added. Treatment attribution
has never worked on this path.

**`window_deferred_statutory` is now deferrable rather than merely named.** It
was always meant to mean "send this at the next lawful instant" — the module
docstring says so — and there was no mechanism behind the name.
