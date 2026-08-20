# Live authority matrix (P4)

What may close on this call, in rupees. The model does not choose the number.

Collections policy already forbids live waivers and settlement quotes. Before
this engine that became a dead moment: log a `fee_waiver` dispute, or escalate,
and wait. The matrix is policy-as-code — `auto_approve` | `cap_inr` |
`escalate` — the same gated pipeline as reco and treatment.

```
features → matrix → log
```

`recommend_authority()` never raises. Escalate is always a valid outcome.
`approved_amount` is always inside the cap, or `None` — the same discipline
`suggest_amount()` has for upsell.

## Modes

| Mode | Default | Effect |
|---|---|---|
| `shadow` | yes | Decide and log. Humans see the allowed move. Nothing posts to the ledger. |
| `live` | | In-policy goodwill may post on the call via `apply_goodwill`. |
| `off` | | Escalate, no log noise beyond `engine_off`. |

An unrecognised `AUTHORITY_MODE` degrades to shadow, not off.

## Vetoes (not tunable via a score)

- Settlement % and restructuring: always escalate, never a quote.
- Bounce-charge reversal: always escalate.
- Hardship / legal / complaint / bereavement hold.
- Prior goodwill in the last 12 months (one-time).
- DPD at or above `AUTHORITY_LATE_FEE_MAX_DPD` (default 61).
- Outstanding above `AUTHORITY_LATE_FEE_MAX_OUTSTANDING` (default ₹1,00,000).
- Tenure below `AUTHORITY_MIN_TENURE_MONTHS` when tenure is **known**. Unknown is absent, not zero.

A dispute hold does **not** veto goodwill: the waiver request often *is* the dispute.

## Enact

- Bot / in-call agent: `apply_goodwill` in live mode, amount ≤ cap, one ledger `waiver` + outstanding drop + dispute resolve.
- Specialist desk: `valid_waive_fee` on a dispute still posts the ledger. That path *is* the review.

## Screens

`authority.policy.snapshot()` is the read. Floor, Handoff and Customer 360 consume it. Do not invent a second opinion of the cap.
