# Live QA (P7) — 100% FPC coverage, same-call barge

Score every interaction. A critical flag can take over the same Twilio call.

The model does not barge. Coverage is deterministic FPC, not Azure. The gated
LLM autoscore may later fill empathy/tone; it cannot overwrite a `[live]` cell
or take over audio.

```
turn facts → checks → log
                 ↘ live_alert + violation
                 ↘ recommendedAction (Floor)
                 ↘ scorecard criterion (0 or 5)
                 ↘ barge executor (shadow | click | live-auto)
```

`evaluate_live_qa()` never raises. Pass / no action is always valid.

## Modes (`LIVE_QA_BARGE_MODE`)

| Mode | Default | Effect |
|---|---|---|
| `shadow` | yes | Decide and log. Floor shows "Would barge". Supervisor still clicks. |
| `live` | | Narrow critical set auto-executes Twilio takeover. |
| `off` | | Score in memory, no log row, never auto-barge. |

An unrecognised value degrades to shadow, not off.

Scoring itself is always on. It is evidence, like `contact_policy`.

## Auto-barge set

`hours-breach`, `third-party-leak`, `identity-before-verify`,
`authority-cap-exceeded`, `auto-escalate`, `opt-out-ignored`.

Sentiment drop and long hold stay recommend-whisper / listen.

## Listen / whisper

Listen is the live transcript in Floor Inspector. Whisper is a coach note
injected into the next bot turn through the same developer-message path as
`turn_critic`. True listen-in audio needs the Media Stream in a Conference
from call start — that is not this item.

## Barge

Reuses `twilio_ops.warm_transfer_to_supervisor`. No `provider_call_id` (sandbox,
WhatsApp) → CRM takeover only, `{audio: false}`. Twilio failure does not roll
back the Handoff claim.

## Coverage

On hangup (and a worker sweep) every completed interaction with enough turns
gets an `ai_draft` scorecard. Critical criteria come from flags/disclosures/
clocks. Soft criteria are a neutral 3 until `QA_AUTOSCORE_ENABLED` fills them.
