# bug_report accounting close

Evidence dump remains [`bug_report.md`](bug_report.md). This ledger is the close-out index so that file is not rewritten.

IDs below use the dump's own prefixes (F-### Cursor/Qoder, plus auditor tags cited in the waves). Cursor F-001–F-083 and the Qoder ranges listed under **NEVER IN FILE** were never in the dump.

## FIXED this engagement

Waves 1–6 (reconstructibility and caller-visible correctness):

- Court / latch alerts / waiver / RBI directory / temporal opt-out carve
- Redaction fail-closed
- Callback `scheduled_at`
- Bind / disclose Pipecat
- Last-4 outbound
- HABIBI_CTX
- Embedded admission
- Lexicon (courtesy ≠ court)
- Reconstructibility: Q-043–Q-045, C-094, Q-041–Q-042, F-040, C-084, Q-110, Q-112
- Q-042 barge / `spoke_this_response` test (`f3f460b`)

Wave 7 suite hygiene:

- `escalate_close.endConversation: true` (terminals export hangup)
- `api_headers` follows `enforcement_enabled()`; Entra cleared in unrecognised-enforce
- Contact-policy / W9 perception isolation
- Wave 6 closer claim SQL executed, not `inspect.getsource`
- Alembic twin for `sql/54_viewer_demo_reads.sql` (**not applied**)

Wave 8:

- Q-098: `resolve_call` DB lookups via `asyncio.to_thread`; ANI reused (`65eda31`)

Wave 9:

- F-091 (partial): lowercase PAN + unspaced Aadhaar in `pii_redact.py` (not spoken-number / non-HDFC account / D7)
- F-106: product-interest `snippet` redacted before Inbox
- F-108: forced rollup does not overwrite `escalated`
- F-114: `_auto_barge` does not `mark_enacted` when handoff INSERT fails
- F-115: recording download fail-closed when audit write fails — **in the working tree** on the untracked telephony recording route; not committed as a whole telephony module

Wave 10:

- RC-TUNE-CLAMP: `clampAgentTuning` keeps `always` / `first_speech`, token cap 32–1024, idle default 12s
- F-109: Audit filter/labels use runtime vocab (`ptp_captured`, `escalated`, …)

Decision packet D1–D17 (one commit each; D2+D8 shared). Schema files only — not applied to `collections_db`.

- D13 `158b322` understanding: missing LLM confidence abstains (`source=keyword`, `fail_closed_reason=no_confidence`); persist `abstained` + `guard_verdict`
- D11 `dd9304a` voice: LLM client timeouts 3/15/5/2, `max_retries=1` (Azure analysis client and A-021 spoken fallback unchanged)
- D15 `f1b3667` understanding: `UNDERSTANDING_LLM_ENABLED` defaults True
- D16 `00638d3` voice: one ignored escalate nudge still closes to a human
- D5 `59a7691` voice: max-turns goes through `wrap_up`, not a hardcoded English goodbye
- D9 `9db506d` voice: apology WAV then hangup when the bot is unreachable (`connection=bot_unreachable`)
- D3 `cc95292` voice: inbound ANI identifies; last-4 verifies
- D2+D8 `5a18314` collections: hardship latches `no_upsell`; PTP no longer clears it
- D4 `c46f0cb` voice: idle timeout clamp 2–20s, persisted on the tuning-apply record
- D1 `d704505` voice: disclose and callback when recording cannot start (`recording_unavailable`)
- D12 `affd341` voice: stamp `retain_until` when a call interaction is written (backfill file only)
- D7 `7c6749d` redact: mask IFSC, labelled PIN and address lines (spoken last-4 / non-HDFC accounts remain open)
- D14 `39946bd` voice: pin IVR off unless explicitly enabled
- D10 `a5ea1e3` voice: WS proxy is a dev flag, not PSTN media
- D17 `a5980cb` rls: no api/voice/worker login may bypass row security
- D6 `cfb845e` timing: 08:00–19:00 is a voice floor published windows may only narrow

## INTENDED

- C-110 tool-proof closer
- A-030 45s grace
- A-032 empty edges
- A-033 provider lock
- Q-051 KB floor 0.0
- AMD greeting skip
- QA / critic / memory defaults
- C-119 shadow live-QA

## STALE

- A-027 depth 8
- O-003, O-026, O-027
- Q-101
- Silent disclose-without-fallback (partial)

## DUPLICATE

Findings that name the same mechanism as a FIXED id above are closed with that fix, not a second patch.

## NEVER IN FILE

- Cursor F-001–F-083
- Qoder Q-028–Q-039, Q-052–Q-054, Q-091–Q-092, Q-124

## OPEN — decision-gated (D1–D17)

All answered and FIXED above. A-021 spoken fallback and Azure analysis-client lock remain product/latency-gated, not D11.

## OPEN — product-gated (not this close)

RC-KB-WAIT · RC-MIN-WORDS · RC-LOCKED-STOP · Q-097 buffer · Q-099 clock origin · A-021 CircuitOpen spoken fallback

## KNOWN (not closed here)

- **O-074 CONFIRMED-DIFFERENT**: Studio campaign Start is `COLLECTIONS_WRITE`, not admin.
- F-091 remainder: spoken last-4 / non-HDFC account ids (IFSC + labelled PIN/address closed in D7 `7c6749d`).
- Container pytest remaining ERRORs: access-requests / invites / entra_oid ALTER / uncommitted routing — blocked on orchestrator schema apply, not this packet.
- Alembic `0151`–`0154` (and untracked `0147`–`0149`) are files only; do not apply to `collections_db`.
- D1–D17 close-out suite (`docker exec collections_voice python -m pytest tests/ -q`): **32 failed · 4,987 passed · 80 skipped · 14 errors** in 17:42. Packet tests themselves are not in the red list. Reds: Entra 401s, `entra_oid` ALTER (app role is not table owner), untracked access-requests/invites schema, other-stream `bot_flow` source-pins, untracked `0149` + committed `0154` as two Alembic heads. Packet-adjacent ratchets: `bot_handlers_idle.build` 325 lines (D16), `persist.py` 1507 lines (D12). Aadhaar `[REDACTED-ID]` vs bullet mask is the Wave 9 F-091 remainder, not D7.
