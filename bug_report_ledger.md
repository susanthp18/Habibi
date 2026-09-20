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

## OPEN — decision-gated (D1–D17). Do not implement until answered

D1 Asterisk record vs disclose · D2 hardship PTP upsell · D3 inbound last-4 · D4 28s idle · D5 max-turns hangup vs copy · D6 temporal DND product · D7 IFSC/address · D8 `no_upsell` CHECK · D9 dead-bot media · D10 WS proxy PSTN · **D11 voice LLM 30s×2** · D12 `retain_until` · D13 fabricated 0.9 · D14 IVR default-on · D15 understanding LLM default · D16 voice escalate nudge · D17 BYPASSRLS

Original latency Wave 6 (D11 / `llm_pool.py` 30s×2) stays skipped.

## OPEN — product-gated (not this close)

RC-KB-WAIT · RC-MIN-WORDS · RC-LOCKED-STOP · Q-097 buffer · Q-099 clock origin · A-021 CircuitOpen spoken fallback

## KNOWN (not closed here)

- **O-074 CONFIRMED-DIFFERENT**: Studio campaign Start is `COLLECTIONS_WRITE`, not admin.
- F-091 remainder: spoken PAN/Aadhaar/card last-4, non-HDFC account ids.
- Container pytest remaining ERRORs: access-requests / invites / entra_oid ALTER / uncommitted routing — blocked on orchestrator schema apply, not this wave.

Answering **D11 / D14 / D5 / D9** unblocks the largest remaining caller-visible clusters.
