# Conversation Trace — one WhatsApp thread through every layer

**Specimen:** `CV-SUSANTH-WA1` (24 messages — richest live thread; organic traffic + a seeded tail).
**Contrast case:** `CV-CL-100023` (escalated, sla=breach, negative sentiment).
**Method:** zero-assumption trace. Every link below is either verified against code (`file:line`) **and** live runtime state, or explicitly marked SUSPECTED. Byte-level charset ground truth was re-established *first* (see §0) so no finding rests on a mangled measurement.

---

## §0 Instrument calibration (before any interpretation)

The audit harness is Windows PowerShell 5.1 masquerading as `pwsh`. Three distinct mojibake traps were identified and neutralized before reading any conversational data:

| Trap | Mechanism | Countermeasure used |
|---|---|---|
| HTTP decode | `Invoke-RestMethod` decodes charset-less JSON as ISO-8859-1/CP1252 | `$r.RawContentStream.ToArray()` → `[Text.Encoding]::UTF8.GetString()` |
| File read-back | `Get-Content` on BOM-less UTF-8 defaults to ANSI | `-Encoding UTF8` everywhere / `read` tool |
| Console render | stdout pipe can re-encode glyphs | codepoint audits computed on in-memory strings, printed as `U+XXXX` |

**Ground truth on the specimen wire payload:** double-encoded signatures (`C3A2 C280 C294…`) absent (−1 at byte level); clean UTF-8 present (`E28099` @9662, `E28094` @486, `E282B9` ₹ @12370). In-memory codepoints of all non-ASCII message text: `U+2019 U+201C U+201D U+2014 U+2013 U+2026 U+20B9` — all correct. **Stored conversation data is clean.** (First-pass "mojibake" seen mid-audit was my own file read-back, not the system.)

Auth context: dev deployment, `APP_ENV=dev`, `API_KEY`/`API_KEY_MAP` empty in `.env` → routes public by design (main.py:431-436 warns); default actor = `ACTOR_USER_ID` (priya-nair).

---

## §1 The specimen, established facts

Wire thread shape (`id, customer, customerId, accountId, channel, status, assignedUserId, isMine, botTyping, pendingOutbound, updatedAt, sla, unread, lastTime, lastPreview, lastFrom, sentiment, ragSuggestions, ragDraftAnswer, handlerBotId, messages[], context{}`); wire message shape exactly `{id, sender, text, time, delivery}` (+`kind:"system"` on activity rows).

Timeline (display clock times, IST): customer "Hey" 12:26 AM → agent "yes us" 12:27 → ACT "You took over from bot" 12:27 → agent "tell me" → agent "are you there susanth" 8:48 AM → ACT "Returned conversation to bot" 8:49 → customer "Yes" → bot reply 8:50 AM → travel-insurance Q&A pair 9:39/9:40 (full RAG answer) → countries Q 10:48/bot answer → bot promise ₹3,200 by 23 Aug + pay link 11:08 → "hi"/bot greeting (mentions "HDFC Bank") 1:49 PM → agent 2:52 PM (no takeover event) → same exclusions Q again 2:53 PM → **bot refuses this time** → agent pastes policy dump → bot promise ₹4,800 "by 22 Aug" 2:55 PM → `[seeded]` 4-message scripted exchange 10:22–10:29 AM next morning.

Context card: outstanding ₹62,400 · 32 days overdue · nextEmi 2026-06-24 · lastPromise {₹4,800, 2026-08-28, Pending} · contactableNow=false · window 10:00–19:00 IST.

Raw payloads saved at `_conv_trace/CV-SUSANTH-WA1.json`, `_conv_trace/CV-CL-100023.json`.

---

## §2 Link-by-link trace (verified spine)

### L1 — Inbound webhook surface
- Both `/webhooks/whatsapp` and `/webhook/whatsapp` bind the SAME handlers via stacked decorators — deliberate Meta alias ("Meta UI sometimes omits the plural s", main.py:4203, 4218). Not a duplication bug.
- GET verification handshake: compares `hub.verify_token`, echoes challenge only on exact match + `hub.mode=subscribe`; else 403 `whatsapp_verify_failed` (main.py:4204-4214). Comparison is `==` (not constant-time) — negligible risk (token is not a secret derivable from timing; standard practice).
- POST: signature REQUIRED — `verify_signature` fails closed when app_secret or header missing (whatsapp.py:48-57), HMAC-SHA256 over raw body with `hmac.compare_digest`. 403 on failure (main.py:4228-4229). JSON decode failure → 400.

### L2 — Webhook processing
- Per-item SAVEPOINTS inside one transaction (db.py:10906-10928) — Meta cannot partially ack, so one bad item would otherwise discard siblings; each message/status gets its own nested txn. Errors logged + returned per item, outer 200 always.
- Inbound types: text/button/interactive extract bodies; other types become `"[{type} message]"` placeholders (db.py:10884-10898). Meta epoch seconds → UTC `sent_at`.
- Statuses branch maps delivery callbacks back through provider wamid (`_apply_whatsapp_status`, db.py:10930-10953).

### L3 — Identity, threading, ids
- Phone normalization = digits-only (whatsapp.py:41-45).
- Runtime id generator `_id(prefix)` = `PREFIX-` + 10 hex chars (db.py:415-416). All hex ids in the specimen came from real API paths.
- `MSG-SUSANTH-0..3`: NOT runtime-generated — they come from `backend/seed_susanth.py` (line 399), an idempotent fixture that inserts 4 messages at `now−12/−10/−8/−5 min`, guarded against production (`APP_ENV=prod` refused twice, lines 26-28, 612-619).

### L4 — Timestamps, ordering, and the "identical updatedAt" clue
- All 14 threads sharing `updatedAt=2026-08-23T05:04:18.379714+00:00` to the MICROSECOND is a single-Postgres-transaction fingerprint: `now()` is transaction-stable, so one bulk seed statement touched every conversation at once. Seed artifact, not a product bug.
- Seeded tail explains apparent out-of-order clock times: msgs 20-23 were written by the last re-seed run (~10:34 IST), stamped ~10:22-10:29 IST. The organic block (00-19) is earlier traffic. Array order is chronological within each insert wave.
- Wire `time` is clock-only ("10:29 AM") — no date component anywhere in the payload. *(Frontend date-separator handling: see §5/E.)*

### L5 — Operator send path (the "agent messaged before takeover" anomaly)
- Backend DOES enforce ownership on WhatsApp: `status=='bot' && assigned!=me` → `bot_still_handling`; whatsapp && !mine → `take_over_required`; plus Meta 24h window enforced with seed rows excluded via `provider_ref IS NOT NULL` (db.py:10176-10211, comment at 10184-10186).
- Human replies inside the 24h session are classified `purpose="in_session"` (db.py:10255-10261) → contact-policy window bypassed BY DESIGN (contact_policy.py:459-460 admits in-session immediately; window/caps bind `outreach` only, :465-488). This is why agent sends at 12:26 AM are compliant.
- Non-WhatsApp channels have NO ownership guard — any agent can send on any SMS/email thread, and `_finalize` auto-assigns unassigned threads on send (db.py:10214-10232). Channel-policy inconsistency (finding F2).
- Agent messages are inserted `sending` then queued through the same outbound worker (`wa_out.enqueue_agent_send`, db.py:10296-10305) — delivery ticks progress identically to bot mail.
- Residual anomaly: msg 01 (agent) sorts before its takeover ACT while enforcement requires prior assignment ⇒ either an earlier takeover event existed and is not shown, or the exchange was seeded by a script using the normal id generator. UNRESOLVED from API alone (needs DB row timestamps) — flagged OQ-1.

### L6 — Contact policy engine
- Veto order: blocking consent → promo consent → in_session admit → DND (outreach) → channel window → preferred hours/days → cooling-off/daily/weekly caps (contact_policy.py:446-553).
- Fail behavior: `outreach` denies on internal error (`REASON_UNREADABLE`, :554-557) — fail-closed where it legally matters; `in_session` allows (a DB error there aborts the send transaction anyway).
- `require_admit` raises `ValueError(reason)` → HTTP 409 path (:985-990).
- Statutory voice window defaults RBI 08:00–19:00; published rules per-channel; borrower preference can only NARROW, never widen (narrow_window docstring :589-612).

### L7 — Bot turn gating (why a bot may reply "outside the window")
- `_policy_gate`: refuses if last REAL inbound (`provider_ref` set) is >24h old → `whatsapp_window_closed`; then `contact_policy.admit(purpose="in_session", actor_kind="bot")` (bot_runtime.py:140-160). Bot replies are session replies, not outreach — the 8:50 AM send was compliant. `contactableNow=False` on the card reflects OUTREACH admissibility, not a ban on replying (UI semantics nuance → F6).
- Race guard: gate re-evaluated immediately BEFORE persist/send; a takeover during the LLM call cancels the job (`mark_cancelled(gate)`, bot_runtime.py:1059-1065).
- Missing recipient phone → finalize `failed`, no retry/escalation noise (:1091-1104).

*(L8+ queue internals, tool effects, serialization, frontend — merged from segment auditors below.)*

---

## §3 Findings ledger (owner-side verifications)

Severity reflects operator/business impact in this deployment. Every item is VERIFIED unless marked otherwise.

| # | Sev | Where | Finding |
|---|-----|-------|---------|
| F1 | MAJOR | bot_runtime.py:1189,1204 | WhatsApp turns are written to `interaction_transcript` with **hard-coded `at_sec=0`**. The voice path computes real elapsed seconds (voice/persist.py:909); the WA bridge (a "Phase 1 gap-fix", comment :1174-1176) never does. Every live turn sits at t=0, so atSec-based sequencing/timing analytics are degenerate for the whole WhatsApp channel. turn_index ordering still correct. |
| F2 | MAJOR | capture/db paths; evidence trace_ix.json | **Interaction transcript ≠ conversation record.** Agent takeovers/replies (db.send_conversation_message) and tool-sent messages (promise/pay-link confirmations) never write `interaction_transcript`; only the LLM reply pair does (bot_runtime.py:1183-1205). Specimen: 24 inbox messages vs 15 transcript turns, missing exactly the agent + tool-sent items. Anything built on transcript rolls (QA packs, cost/trace views, compliance context) undercounts what the customer experienced. |
| F3 | MINOR | bot_runtime.py:1199-1205 | Latency fields (ttfb_ms/ttfa_ms/tokens) accepted by the insert but never populated on the WA path — trace API returns empty strings for every latency field on WhatsApp turns. |
| F4 | MINOR | Habibi/src/api/inbox.ts:66-71 | Delta-merge sort tiebreak compares 12-hour clock strings lexicographically: `"9:40 AM" > "10:29 AM"` as strings, so equal-`updatedAt` threads (currently ALL 14 seeded ones) render in scrambled chronological order whenever hour digit-counts differ. Live-visible today. |
| F5 | MINOR | db.py:9731 (+ return-to-bot equivalent) | Takeover activity title is the literal `"You took over from bot"` stored at write time. Any OTHER viewer (and audit exports) read a false first-person attribution; actor exists in columns but not in display text. |
| F6 | MINOR | db.py:10194-10212 vs :10214-10232 | Ownership guard exists ONLY for whatsapp. On sms/email/etc. any agent can POST messages on any thread (no `take_over_required`), and `_finalize` then auto-assigns it to them. Channel-policy inconsistency in a supervised-teams product. |
| F7 | INFO | main.py:4212 | Verify-token compare is `==`, not constant-time. Negligible practical risk (token not timing-derivable at this granularity); noted for completeness. |
| F8 | MINOR | db.py:10884-10898 (+ bot_runtime consumption) | Non-text WhatsApp inbound degrades to a `"[{type} message]"` text placeholder — media not stored, **captions discarded** (`image.caption` never read), and worst: the placeholder then drives a real conversational bot reply, so a sticker/reaction makes the LLM answer the literal string. Ingestion permits it (no media branch); runtime consumes it verbatim. *(supersedes earlier info-level note; per Segment A)* |
| F8b | MINOR | whatsapp.py:57 | Non-ASCII `X-Hub-Signature-256` header raises TypeError inside `hmac.compare_digest(str,str)` → 500 instead of 403. Fail-closed, but pollutes 5xx alerting. |
| F8c | MINOR | db.py:10389-10406 vs :10424-10426 | Duplicate exact-phone customers resolve arbitrarily (most-recently-updated wins, logged only) while the last-10-digit tail path FAILS CLOSED on ambiguity — inconsistent identity risk under dirty data. |
| F8d | MINOR | db.py:10644 | Inbound customer rows hardcode `delivery_status='delivered'` — an unverifiable receipt rendered as fact in the UI. |
| F12 | MAJOR | db.py:10911-10927, :10955 | **A failed inbound message is permanently lost.** Per-item savepoint rollback + `{"status":"error"}` + outer 200 → Meta never redelivers; no dead-letter/replay exists for inbound items (unlike bot jobs). One bad item = silent message disappearance. |
| F13 | INFO | .env flags | Deployment posture: `APP_ENV=dev` but `BOT_ENVIRONMENT=production` — dev testing exercises production guardrail bundles (deliberate separation worth knowing when judging dev behavior). |
| F14 | MINOR · SUSPECTED | Meta edit payloads | Message edits appear unhandled anywhere in the messages path; if Meta delivers edits as new items they become junk rows and can trigger bot turns. Contingent on Meta payload shape (unverifiable here). |
| F15 | MINOR | db.py:660 (`_activity`) | `"note": note or customer_id` persists the CUSTOMER ID into `activity_events.note` whenever note is None — i.e., on every takeover/return/inbound event. Data hygiene: notes columns across audit rows carry ids that render as if they were human notes. |
| F16 | MINOR | db.py:9456-9458 vs main.py:4195-4196 | The suggestions-refresh 429 path is **dead code**: `refresh_conversation_suggestions` swallows `RateLimitExceeded` inside a broad `except Exception`, so the endpoint's 429 handler never fires — throttled refreshes return 200 with STALE chips and no signal. Silent staleness instead of backpressure. |
| F17 | MAJOR (perf-shaped) | db.py:8745-8846 + list route | List view is N+1 heavy (~5-10 extra queries per thread, including a full `contact_policy.evaluate` PER ROW) and embeds FULL unbounded message arrays in the LIST payload (live: 24 msgs × 15 threads). Fine at demo scale; collapses at real inbox volume. |
| F18 | MAJOR (structural) | db.py:8983-9045 vs :9689/:9745 | Conversation READS have NO tenant filter while writes assert `_assert_tenant_owns`. Single-tenant today; any future multi-tenant split leaks every thread cross-tenant through GET /conversations. |
| F19 | INFO | live probes (Segment D) | Delta contract verified end-to-end: strict `>` at exact watermark returns `[]`; malformed `updatedAfter` → 400 `invalid_updated_after`; unknown id → 404; list≡detail serialization byte-identical live; sla/sentiment computed at read time from interaction columns + last-inbound age. |
| F20 | MAJOR | meta.tsx:66-68, Composer.tsx:167-168, ChatThread.tsx:114-124, inbox.tsx:45-47 | **Composer dead-end on teammate-assigned WhatsApp threads.** `needsClaim` is false when `status==='assigned' && !isMine`, so the composer ENABLES ("Reply on WhatsApp…") while the Take-over button is HIDDEN (render requires needsClaim). Any send is guaranteed-rejected (`take_over_required`) and the friendly error tells the operator to use a button that isn't rendered. No recovery except the other agent releasing. Backend would permit a claim (takeover has no ownership check — silent steal, db.py:9686-9709). |
| F21 | MAJOR | ChatThread.tsx / MessageBubble.tsx / ConversationList.tsx (grep clean for any date logic) | **Cross-day transcripts have zero date context** — bubbles/system lozenges/list previews render clock-only strings verbatim; specimen timeline visibly runs backwards across midnight. SLA-sensitive collection decisions get made on a misread timeline. |
| F22 | MINOR | db.py:8928-8937 + frontend render-only `unread` | Unread badge is stateless "unanswered customer turns since last reply", forced 0 when mine. Opening/reading changes nothing; badges persist across reloads until someone replies or the thread becomes mine. UI labels it "unread" — operators can't trust it as such. |
| F23 | MINOR | inbox.tsx:307-316 + router.tsx:6-17 | One failed poll blanks the ENTIRE inbox behind `!isError` even when valid cached data exists; `retryUnlessClientError` is not wired into this query (global `retry:1` retries deterministic 4xx too) — query-state.tsx discipline not applied on this route. |
| F24 | MINOR | inbox.tsx:199-206 vs :210; db.py:9486-9557 | RAG cache patches for a NON-current conversation apply without paired invalidate, and `refresh_conversation_suggestions` never bumps `conversations.updated_at` — so refreshed chips are invisible to deltas, don't propagate to other tabs, and can be overwritten by an in-flight stale-prev delta commit until the ~60s full refresh. |
| F25 | MINOR | Composer.tsx:165,376-380; api/inbox.ts:138-144 | Canned-responses failure is masked by `data=[]` → panel asserts "**No canned responses configured.**" during an API outage — the exact graceful-degradation lie query-state.tsx documents as this codebase's #1 failure mode. |
| F26 | MINOR | inbox.tsx:138-141; ChatThread.tsx:65-68; api/inbox.ts:59-72 | Cluster: bogus `?conversationId` silently renders `threads[0]` (no dead-link guard, unlike agent-studio); transcript force-scrolls to bottom on every change (no scrolled-up check, yanked mid-read at 1.5s typing cadence); deleted threads linger up to ~60s (upsert-only merge; longer when deletions happen while tab hidden). Also: single global `ragLoading` sticks through superseded requests (~500ms+latency spinner freeze on quick thread flips), and list ties reshuffle between poll types (server `cv.id` vs client `localeCompare(lastTime)`). |
| F27 | MINOR | db.py:8548-8570 + :10644; sql/04_interactions.sql:190 | No CHECK on `messages.delivery_status`, and `_inbox_delivery` falls back to `"delivered"` for any unknown/NULL bot-or-agent status — a never-sent seeded bot bubble displays a delivered tick. Inbound rows store `'delivered'` unconditionally but serialize as null by design. |
| F28 | MEDIUM | db.py:10174 vs :10244 | `sent_at = datetime.now()` is captured BEFORE the `FOR UPDATE OF cv` lock wait. Under contention with a concurrent takeover commit, the message commits later but sorts earlier — sub-second timeline inversions (the specimen's 12:27:24 msg vs 12:27:26 event is this mechanism and/or prior assignment). |
| F29 | MINOR | db.py:9686-9738; main.py:714-715 | Takeover has no idempotency or steal guard: re-takeover always succeeds (duplicate ACT rows, hidden from wire by read-side dedupe) and any agent silently steals another's thread — which is what makes frontend dead-end F20 possible yet unrecoverable in-UI. Separately, `return_to_bot_not_allowed` maps to 409 Conflict where 403 is the honest code. |
| F30 | MINOR | db.py:8929-8937, :8925, :8922-8924, :8542-8545, :8954, :8952 | Field-level silent-mislead inventory: `unread` forced 0 whenever thread is mine EVEN with unseen trailing customer turns; `lastPreview` never truncated (full last message); `lastFrom` falls back to "bot" when only system events exist; `channel` coerces chat→whatsapp and unknown→whatsapp; unknown status→"bot"; `accountId:''` when no account. Each individually defensible; collectively they present plausible-but-wrong state — the house failure mode. |
| F31 | HIGH | bot_runtime.py:142-157 + contact_policy.py:459-487 + tests gap | **Reply-path window exemption is by design but unpinned, and its cancel path is traceless.** `in_session` admits before any hour/window check (docstring documents intent); NO test pins nighttime-reply behavior; the card's `contactableNow=False` comes from outreach-mode evaluate that the reply pipeline never consults. Net: nothing blocks a 03:00 IST bot send beyond dnd/opt-out/24h-window; and when gates DO trip (or takeover races), the job is cancelled with NO activity event or inbox card — conversation stays status='bot' with the customer message permanently unanswered and invisible-to-operator explanation. |
| F32 | HIGH | bot_runtime.py:158-159; contact_policy.py:978-982 vs :554-557 | **Policy gate fails OPEN on infrastructure error for replies.** The admit call's `except Exception → return None` plus `admit` swallowing everything for non-outreach purposes means an unreadable consent schema silently disables remaining policy protections on the live send path — while outreach paths deliberately fail closed (`REASON_UNREADABLE`). Asymmetric fail-direction on the riskier path. |
| F33 | MEDIUM · mechanism VERIFIED / impact SUSPECTED | bot_jobs.py:241-243,441-443,465; :138-182; bot_runtime.py:358-369 | Advisory-lock asymmetry: the xact lock lives only inside the claim txn; execution runs outside any lock, guarded solely by the persisted running row. A legitimate turn exceeding BOT_JOB_STALE_RUNNING_SEC=300 (repo itself logs a 51s analyze incident) gets swept→requeued→re-claimed WHILE the original runs: duplicate LLM/tool spend, whole-blob `bot_state` lost-update, job flapping. Duplicate SEND is prevented (unique `uq_messages_bot_turn_job_id` + sent/sending/failed pre-checks). |
| F34 | MEDIUM | bot_jobs.py:447-459, :478-479 | Dead-letter reclaim escalation failure is swallowed (log-only, both sites). If `escalate_conversation_to_human` throws, the conversation stays 'bot' with a dead job and nothing surfaces — the original silent-drop bug reintroduced one layer down. |
| F35 | MEDIUM | bot_runtime.py:1124-1141; whatsapp_outbound.py:181,573-576 | Bot outbound rows stranded in `'sending'` forever on ambiguous transport error or a crash before finalize — no sweeper covers bot messages (only the outbound-jobs table has reclaim), and the Inbox hides sending/failed/cancelled rows (:8656-8658). Requires manual DB reconciliation that nothing surfaces. |
| F36 | MINOR | bot_runtime.py:675-679,940-944,1104-1105; db.py:8629-8633 | Cancel-cluster tracelessness (folded into F31's second half but distinct writers): `no_customer_text`, mid-flight takeover, missing recipient all write only `bot_turn_jobs.error`. |
| F37 | MINOR | bot_runtime.py:955-958,1054-1057; bot_jobs.py:203-240,76-88; db.py:8849-8852,8941 | Edge cluster: (a) tool_calls on the FINAL iteration discarded as `tool_loop_exhausted`; (b) whitespace-only model text → canned "Thanks for your message…" ack instead of escalation — a confident-looking empty reply; (c) claim loop returns None after 3 advisory misses despite ready work elsewhere (bounded starvation, acknowledged); (d) enqueue idempotency matches ANY existing job incl. dead/cancelled → Meta redelivery after a dead-lettered turn never re-enqueues; (e) typing indicator is DERIVED ONLY (60s freshness union; job row touched once at claim → indicator blinks off during long turns); `pendingOutbound = bool(bot_typing)` WITHOUT the status/unassigned gate → can be true on taken-over threads; (f) display clock is fixed UTC+05:30 regardless of `customers.timezone`. |
| F38 | MAJOR | bot_runtime.py:45-46,:918; domain.py:1004-1010; defaults.py:31 | **Handoff allowlist resolves against env `BOT_ID` (kaia-v2-4), not the thread's actual handler** (collectionsbot-v2-4) — the published card's allowlist is ignored whenever env and reality diverge; and if the running id has no built-in card, `card_for` raises → allowlist=None → **the check is skipped entirely**, making any existing bot id a legal handoff target. routing.py:14's guarantee holds only when env matches deployment truth. |
| F39 | MAJOR · auditability | kb_plan.py:494-564 (≤700-char snippet clamp :81,:520); kb.py:704-715; bot_tools.py:241-249; bot_runtime.py:981 | **LLM-judge verdicts are unpersisted.** `confident` never survives into artifacts (result_preview truncated at 1500 chars BEFORE the flag), and judge verdicts log nowhere on the normal path — so a judge-authored refusal (proven mechanism behind the specimen's 2:53 PM regression) is unauditable after the fact. Compounded: empty-retrieval + judge early-return lands in the FAIL-OPEN branch → `confident=true` over ZERO snippets while the directive says "Answer ONLY from these snippets" about an empty set. |
| F40 | MAJOR | promise_fulfillment.py:190-200,224-345; db.py:5200-5220; _thread_context db.py:8745-8758 | **Immutable transcripts vs mutable promise rows drift.** Confirm messages are byte-exact `_confirm_copy` (₹ literal :198; expiry = promised-day+1 23:59 IST); but `promised_at` is patchable AFTER the link/confirm shipped, with no re-issue/void of the delivered pay link and no transcript correction. Specimen: ₹3,200 row patched to Aug 9 four seconds after enqueue; ₹4,800 row re-seeded Aug 22→Aug 28. Customers hold links for dates the CRM no longer shows; agents reconcile ghosts. Card selector (`ORDER BY promised_at DESC LIMIT 1`, no status filter) is truthful vs DB and contradictory vs transcript simultaneously. |
| F41 | MAJOR · data integrity | seed_susanth.py:379-407; trace TR-…-0..3 toolCalls=[] | The "Promise for next Friday works → I've logged a promise" exchange is fixture text with ZERO tool calls — the bot sentence asserts a CRM action that never ran. Seed artifacts that fabricate agentive behavior poison audits, demos, and any analytics trained on this inbox. |
| F42 | MINOR | bot_tools.py:255; domain.py:682-772 | Promise idempotency is JOB-scoped (`{job_id}:create_promise_to_pay`), unlike leads' conversation-scoped key — every renegotiating turn mints another promise + another live pay intent; nothing revokes sibling intents. Multiple concurrently payable links can coexist in-thread. `request_callback` passes no idempotency key at all. |
| F43 | MINOR | promise_fulfillment.py:105-112 vs money_inr.py:32-74; domain.py:122-133 | Two rupee formatters disagree above ₹99,999 (Western grouping in customer-facing confirms vs lakh/crore in UI). No past-date guard on `_parse_promise_date` — yesterday's date yields a 30-minute link auto-broken at next settle tick. |
| F44 | MINOR | contact_policy.py:449-462,:941-945; db.py:8573-8589 | Tools have NO contactability gate — only sends do. The bot records promises/mints links freely while `contactableNow=False`; the pay-confirm send rides `purpose="statutory"` which ignores DND-registry/hours/caps BY DESIGN. Net: exactly what the specimen shows is legal everywhere except channel opt-out/dnd flags. |
| F45 | MINOR | promise_fulfillment.py:50-73; .env WHATSAPP_FALLBACK_TEMPLATE_NAME | Out-of-window PTP confirms fall back to `jaspers_market_order_confirmation_v1` — a CONSUMER-ORDER template; code comment itself warns Meta rejects mismatched body params ⇒ a silent send-failure class waiting on real 24h-window expiry. Adjacent: bot self-identified as "HDFC Bank" against an HL-Assurance corpus (persona/bundle drift). Stale-chip preservation (db.py:9482-9486) leaves Travel-insurance suggestions pinned under the EMI thread indefinitely — chips contradict the live conversation by design. |
| F9 | MINOR | bot_runtime copy, msg 14 | Bot greeting on the text channel says "**This call is recorded**…" — voice-channel compliance copy leaking into WhatsApp text. Compliance statement inaccurate per-channel. |
| F10 | INFO | api/inbox.ts:59-71 + backend contract | Threads deleted server-side persist as ghosts in client cache up to ~60s until the `%15` full refresh. Acceptable tradeoff, undocumented in UI. |
| F11 | INFO | contact_policy.py:454-457 | Promotional consent is checked BEFORE the in-session shortcut deliberately (comment) — good; recorded so future refactors don't "simplify" it into a consent hole. |

## §4 Anomaly resolutions

| # | Observation | Resolution |
|---|---|---|
| A1 | Mojibake glyphs in first dump | Auditor-side PS 5.1 ANSI read-back; wire verified clean (§0) |
| A2 | Identical microsecond updatedAt ×14 | Single bulk-seed transaction (`now()` transaction-stable) |
| A3 | MSG-SUSANTH-* id pattern break | `seed_susanth.py:399` fixture inserts |
| A4 | Clock-only times appear out of order | Seeded tail vs organic wave; no day markers exist in payload |
| A5 | Bot replied 8:50 AM despite 10-19 window | Replies are `in_session` — window binds outreach only (L6/L7) |
| A6 | Agent sent at 12:26 AM | Same in-session exemption for human replies (L5) |
| A7 | Bot answered exclusions 9:40 AM, refused 2:53 PM | **RESOLVED (Segment C, trace ground truth):** the refused turn's retrieval SUCCEEDED — topScore 0.7983 with the GENERAL EXCLUSIONS chunk present. The refusal was authored by the LLM judge (`judge_passages` answerable=false → "do NOT answer… specialist will follow up" directive), the ONLY code path producing that shape; verdicts are unpersisted (F39), so post-hoc attribution stops at the judge. Corollary: T8 answered at topScore 0.6872 < the 0.70 gate ⇒ numeric thresholds are no longer the operative gate; nothing was "fixed" between 9:40 and 14:53 — the flip lives in unpersisted LLM-layer decisions |
| A8 | Three promises vs one context-card promise | **RESOLVED (Segment C reconciliation):** ₹3,200 msg = PTP-8B3876B988 (activity matches to the second) later PATCHED to Aug 9 four seconds after link enqueue; ₹4,800 msg = PTP-SUSANTH-1 in its Aug-17 seed era (Aug 22@11:00Z reproduces body+expiry exactly), re-seeded to Aug 28 on Aug 23; the "Friday promise" exchange is seeded fixture text with zero tool calls (F41). Card = current DB truth; transcript = two earlier eras. Both contradictions are F40's immutable-message-vs-mutable-row design |
| A9 | Agent msg precedes takeover event | **RESOLVED (DB ground truth, Segment D):** activity_events holds 37 rows for the specimen — 9× takeover, 9× return-to-bot from repeated testing. Read-side stitcher dedupes by exact text equality (db.py:8684), collapsing all repeats into the 2 visible items. First agent msg sent_at 12:27:24 AM vs that event 12:27:26 AM: thread was already assigned from a prior cycle, so the send was legal; enforcement intact |
| A10 | Trace view shows `tools=1 retr=1` on CUSTOMER turns | Tool-call/retrieval backfill deliberately attaches to the trigger turn's row (bot_runtime.py:1206-1224) — convention, not a bug |
| A11 | Transcript turns all show empty latency + atSec=0 | F1/F3 — hard-coded at the WA bridge call site |
| A12 | updatedAt +5m15s after last message | Writer inventory complete (Segment B): 9 explicit sites + schema trigger `trg_conversations_updated_at` bumps it on ANY update; delivery callbacks/dedupe ruled out. Exact writer indeterminate without DB/log history — OQ-12 |

## §5 Segment reports

### Segment A — Ingestion (webhook → DB rows → bot job)

Scope note: this checkout's `backend/main.py` is **5053 lines**; the WhatsApp webhook block sits exactly at main.py:4202-4235. No POST probes were made (non-mutating audit); no secret values printed.

**LINKS VERIFIED CORRECT**

- **L1. GET verify handshake — both aliases, one handler.** `@app.get("/webhooks/whatsapp")` + `@app.get("/webhook/whatsapp")` stack on the same function (main.py:4202-4214). Requires `hub.mode == "subscribe"` (case-sensitive), non-empty configured token, exact match, `hub.challenge` present; echoes challenge verbatim as `text/plain`; else 403 `whatsapp_verify_failed`. Fail-closed when token unset.
- **L2. LIVE PROBES (GET only):** wrong token → HTTP 403 `{"detail":"whatsapp_verify_failed"}` · missing params → 403 · wrong mode with real token → 403 · real token + challenge on BOTH aliases → HTTP 200 `text/plain` echoing challenge exactly.
- **L3. POST handler** main.py:4217-4235: raw bytes → signature check → UTF-8 JSON decode (400 `invalid_json`) → `asyncio.to_thread(db.process_whatsapp_webhook)`. Both aliases exempt from API-key auth via `_AUTH_EXEMPT_PREFIXES` (main.py:233-237) — "webhooks use their own HMAC".
- **L4. Signature validation mandatory & fail-closed** (whatsapp.py:48-57): False if secret OR header missing; HMAC-SHA256 over raw body; `hmac.compare_digest`. **No dev-mode bypass exists.** Injection fear does not materialize.
- **L5-L7. Batch walk with per-item savepoints:** one outer txn per POST; each message/status inside `begin_nested()` so a bad item doesn't discard siblings (db.py:10906-10953).
- **L8. Status callbacks:** `_apply_whatsapp_status` (db.py:10757-10864) — lookup by `messages.provider_ref = wamid`; EVERY transition recorded into `delivery_receipts`; monotonic rank `{sent:1, delivered:2, read:3}` prevents late out-of-order downgrade; `failed` always wins and persists Meta error codes onto `whatsapp_outbound_jobs.error`. Outbound wamid backfill closes the read-receipt loop (whatsapp_outbound.py:522, 554-558).
- **L9. Identity/threading:** digits-normalize → exact match then last-10 tail that FAILS CLOSED on ambiguity (db.py:10382-10482); unknown number → new customer+account+conversation (`status='bot'`, unassigned, `collectionsbot-v2-4`) matching specimen shape exactly.
- **L10. Idempotency:** unique partial index on `messages.provider_ref` (alembic `20260722_0016`); SQLSTATE 23505 → `{"status":"duplicate"}` returning existing row (db.py:10655-10674). Meta retries are safe.
- **L11-L12. Enqueue gates:** only when post-update `status=='bot' AND assigned_user_id IS NULL` (db.py:10708-10712); idempotent on `trigger_provider_ref`; enqueue failure degrades to a `bot_enqueue_failed` activity instead of failing the webhook (db.py:10716-10739). Flags here: `BOT_RUNTIME_ENABLED=true`, `BOT_ENVIRONMENT=production`, max attempts 5, stale-running 300s. Single-flight advisory lock + sibling supersede confirmed (bot_jobs.py:203-291).
- **L13. Error semantics to Meta:** escaping exception → default plain-text **500** → Meta retries whole payload (safe due to L10 dedupe). Per-item failures → 200 with `results[].status="error"`.

**FINDINGS**

| # | Sev | Status | Evidence | Finding |
|---|-----|--------|----------|---------|
| A-F1 | MAJOR | VERIFIED | db.py:10911-10927, :10955 | Failed inbound message permanently lost behind 200 OK — savepoint rollback, no dead-letter/replay for inbound items. |
| A-F2 | MINOR | VERIFIED | main.py:4212 | Verify-token compare not constant-time (vs `compare_digest` on POST path). |
| A-F3 | MINOR | VERIFIED | whatsapp.py:57 | Non-ASCII signature header → TypeError in `compare_digest(str,str)` → 500 instead of 403. Fail-closed but noisy. |
| A-F4 | MINOR | VERIFIED | db.py:10884-10898; bot_runtime consumption | Placeholder text drives real bot replies ("[reaction message]"); media captions discarded entirely. |
| A-F5 | MINOR | SUSPECTED | messages path | Message edits unhandled — contingent on Meta edit payload shape. |
| A-F6 | MINOR | VERIFIED | db.py:10644 | Inbound rows hardcode `delivery_status='delivered'`. |
| A-F7 | INFO | VERIFIED | .env flags | `APP_ENV=dev` with `BOT_ENVIRONMENT=production` — dev exercises production guardrails. |
| A-F8 | MINOR | VERIFIED | db.py:10389-10406 | Duplicate exact-phone customers resolve arbitrarily (most-recent wins), unlike fail-closed tail path. |

*(cross-referenced into master ledger §3 as F8/F8b-d, F12-F14)*

### Segment D — Read-side serialization + operator actions

**LINKS VERIFIED CORRECT**

- Authz: both webhook spellings public (authz.py:218-221); five conversation routes scoped INTERACTIONS_READ/WRITE + SUPERVISOR_WRITE (:500-505); only supervisors hold SUPERVISOR_WRITE (:150-177); enforcement on iff API key(s) set (:615-631) → all open in dev. `_handle_write` mapping main.py:703-721: KeyError→404, PermissionError→403, **ValueError→409**, IntegrityError→409.
- Dev "me": no keys configured → `actor_context` default `priya-nair` (actor_context.py:37, :201-214); `db._actor_user_id()` falls back to process default even outside requests (db.py:419-430) — this decides every isMine/unread/composer evaluation.
- Read SQL: batched messages/events/suggestions (no N+1 in those three); deterministic `(sort_at,id)` ordering with ACT-/MSG- alphabetical tie across id namespaces; typing = 3-way UNION over bot_turn_jobs / whatsapp_outbound_jobs(excl inbox_reply) / stuck-'sending' messages, bounded by 60s staleness constant (f-string of a module constant — injection-safe).
- Writes: takeover asserts tenant, sets assignee, cancels queued/running bot jobs (db.py:9711-9725); return-to-bot guards owner-or-needs_human/escalated, clears intent state, dialog reset (:9741-9809), enqueues nothing; WA send gated on last inbound **with provider_ref** for the 24h window (:10184-10211); non-WA inserts `'sent'`, WA inserts `'sending'` + queue (:10287-10336). Enqueue gate: status=='bot' AND unassigned only (:10708-10712).
- Refresh pipeline: score gate INBOX_RAG_MIN_SCORE=0.38 (:9173); delete+reinsert chips in one txn; stale-chip fallback when retrieval empty (:9540-9557); rate limit = 30/min/tenant shared Postgres counter (`kb_rate_limit.py:48-104`).

**FINDINGS** (D1-D12, summarized in master ledger as F15-F18, F27-F30)

- **D1 HIGH:** assignment enforcement channel-asymmetric — non-WA channels post with zero takeover and silently self-assign with NO activity event.
- **D2 HIGH (DB ground truth):** read-side exact-text dedupe (db.py:8684) erases repeated takeover/return events — DB holds 37 activity rows (9 takeovers, 9 returns) for the specimen; wire renders 1 each. Timeline contradicts database.
- **D3 MEDIUM:** `sent_at` captured before row lock ⇒ sub-second inversions under contention (specimen 2-second case).
- **D4 MEDIUM:** `_activity` note-or-customer_id audit pollution (F15).
- **D5 MEDIUM:** refresh 429 dead code; throttling silent (F16).
- **D6 MEDIUM:** reads lack tenant filter while writes assert ownership; RLS exists but docstring says inert while app connects as superuser (F18).
- **D7 LOW:** strict `>` blind spot for rows committed AT the watermark; naive params silently assumed UTC rather than rejected.
- **D8 LOW:** list N+1 fan-out (~6-10 stmts/thread incl. contact_policy.evaluate) + full transcripts embedded in LIST (F17).
- **D9 LOW:** no delivery_status CHECK; unknown statuses render "delivered" (F27).
- **D10 LOW:** takeover steal/idempotency gap; return-to-bot 409-vs-403 semantics (F29).
- **D11 LOW:** field mislead inventory incl. unread-forced-0-when-mine even with unseen turns (F22/F30).
- **D12 INFO:** ordering deterministic within namespaces; cross-namespace tie arbitrary but stable.

**ANOMALY RESOLUTIONS:** (1) three stacked truths — channel asymmetry, no-auto-takeover on WA (the 2:52 PM send proves a real takeover occurred at 02:52:47 PM per DB), and read-side dedupe hiding it; (2) `_inbox_clock` emits `%I:%M %p` IST only, never a date, in both list and detail; (3) strict `>` verified live with exact watermark → `[]`; naive→UTC assumption documented; (4) customer delivery null by serializer design regardless of stored 'delivered'; (5) sla/sentiment fully derived at read time (`_inbox_sla` >24h-customer-silence rule; sentiment blend 0.35·prev+0.65·new via `_touch_interaction_sentiment`, db.py:10595-10623); (6) all 22 fields 1:1 live-verified, misleads catalogued.

### Segment B — Job queue + bot turn runtime

Env flags: `BOT_RUNTIME_ENABLED=true`, `BOT_ENVIRONMENT=production`, `BOT_HARD_MAX_TURNS=12`, `BOT_MAX_TOOL_ITERATIONS=6`, `BOT_JOB_MAX_ATTEMPTS=5`, `BOT_JOB_STALE_RUNNING_SEC=300`. Live probe reproduced the specimen byte-for-byte. (Correction to the audit brief: there is **no** typing-indicator lifecycle store anywhere — it is purely derived; see read-side note below.)

**PIPELINE MAP (execution spine)**

- Meta webhook → ingest txn: insert msg 'delivered' (savepoint) db.py:10638-10654 → dup? exit :10662-10673 → touch conversations + keep/flip status 'bot' :10677-10694 → activity :10695 → if bot & unassigned: enqueue_bot_turn (pre-check ref bot_jobs.py:76-88 → INSERT 'queued' w/ unique idx :94-116 → unique-violation recovery :117-128)
- Worker bot_worker.py:218-234 (poll 1.5s; bot turns get every 4th iteration ahead of agent outbound, else last priority :59,:70,:93,:162-163) → process_one
- Txn A bot_jobs.py:441-443: reclaim_stuck_jobs (:138-182; stale>300s → dead if attempt≥5 else queued) → claim_next_job (CTE oldest queued, no running sibling, FOR UPDATE SKIP LOCKED :206-229 → try-advisory-lock verdict + ≤3 skip-retries :230-240 → mark running :245-258 → supersede siblings :263-276 → delete their failed drafts :278-290); COMMIT releases lock
- Post-commit: escalate reclaimed-dead conversations :447-459 → handle_turn :465 (exception → backoff/dead :468-469 + escalate-on-dead :470-479)
- _handle_turn: idempotency pre-check sent/sending/failed bot_runtime.py:593-655 → load conv, missing→cancel :657-661 → GATE #1 :668-673 (runtime flag :129 · bot/unassigned :131 · whatsapp :133 · dnd :135 · WA opt-in :137-139 · Meta-24h :140-141 · admit(in_session,bot_reply) :142-157; trip→cancel only; infra-error→fail-open :158-159) → latest customer text, none→cancel :675-679 → bot_state load :681 → stale-reuse regen check :688-696 → turn_count++ :698 → bundle load, KeyError→retry :700-711 → analyze_turn on ISOLATED analysis breaker :722-729 → sentiment/intent persistence :734-795 → abuse/guardrail early-escalate (job marked succeeded) :804-835 → max_turns exceeded→escalate+cancel :839-853
- Reply build: history single query DESC LIMIT 64 (customer/bot/agent only — system events excluded; optional dialog_reset cutoff; head-truncation bounded by compaction summary) :860-869,:181-229 → bound to 16 + summary persist :870-894 → untrusted-CRM-card + WhatsApp-block messages :902-911
- Tool loop ×6 :938-1052: per-iter takeover reload→cancel :940-944 → chat_with_tools on live breaker :949-954 → no-tools→final_text break :956-958 → execute+audit :974-999 → tool-escalate :1025-1039 → failures≥3→'repeated_tool_failure' :1041-1045 → exhausted :1046-1052 → empty-text canned fallback :1054-1057
- GATE #2 fresh reload + policy gate pre-send :1060-1065 → persist 'sending' (+outbound_message_id + updated_at touch) :1067-1089 → recipient phone_primary→alt, none→failed+cancel :1091-1111 → wa.send_text_message (whatsapp_meta breaker) :1112-1113 → finalize 'sent'+wamid+activity :1114-1123 | ambiguous→row LEFT 'sending', job cancelled :1124-1141 | client-error→failed+cancel :1151-1159 | else failed+raise→worker retry :1142-1160
- Success tail: save bot_state (whole-blob overwrite) :1162-1172 → transcript×2 + tool-call/retrieval backfill + rollup :1174-1247 → live_qa :1248-1266 → mark_succeeded :1268-1269
- Read side: typing = derived union (jobs/outbound-jobs fresh≤60s ∪ bot msgs 'sending' fresh≤60s), NO lifecycle writes exist; `pendingOutbound=bool(bot_typing)` WITHOUT the bot/unassigned gate; thread hides sending/failed/cancelled rows; clock = FIXED UTC+05:30 regardless of customers.timezone

**FINDINGS:** masters F31-F37 (window bypass deliberate-but-unpinned + traceless cancels; fail-open reply gate; advisory-lock asymmetry with 300s double-execution exposure; swallowed dead-letter escalation; stranded 'sending' rows without sweeper; edge cluster).

**ANOMALY (b):** complete writer inventory — 9 explicit sites PLUS a schema trigger (`trg_conversations_updated_at BEFORE UPDATE`, sql/13_triggers.sql:36,:91-98) bumping updated_at on ANY conversation update. Delivery callbacks and webhook dedupe ruled out by code. The +5m15s residual touch is indeterminate without DB/log history; best-fit candidates recorded in §6.

**ANOMALY (a):** resolved definitively — the 08:50 IST send passed gates #1/#2 because `in_session` never sees the window; the card's False is outreach-mode semantics nobody applies to replies.

**Escalate helper shape (verified):** sets `status='needs_human'` + updated_at, cancels that conversation's queued/running bot jobs, writes `conversation_escalated` activity. No push notification, no assignee change (db.py:10113-10163).

### Segment E — Frontend conversation inbox

**LINKS VERIFIED CORRECT**

- Full render path wired as mapped below; error map includes the backend's exact raise strings (`take_over_required|bot_still_handling` → friendly copy, inbox.tsx:45-47 ↔ db.py:10196/:10201).
- Watermark contract matches end-to-end: client lexicographic max over fixed-width UTC isoformat ↔ server strict `>` with created_at fallback — **brand-new threads ARE included in deltas**; malformed→400; hidden tab pauses polls; typing/outbound accelerates to 1.5s.
- RAG race guard sound: monotonic token + activeIdRef gate ALL local state writes; cache patches keyed by conversation id; debounce cleanup on dep-change and unmount; fingerprint skips system items.
- Double-click safety: single shared `pending` flag across takeover/return/send + disabled buttons; React Query v5 `cancelRefetch:true` (verified in installed query-core source) cancels in-flight polls before mutation commits — the classic lost-update is defused except F24's residual hole.
- Charset: zero transforms in the render path (grep clean for atob/TextEncoder/normalize/dangerouslySetInnerHTML); raw auto-escaped JSX with pre-wrap — specimen ₹/dashes/quotes pass untouched. Live SSR probe: `/inbox` → 200, healthy shell, no error overlay.

```
/inbox ─ useConversations(poll 4s / 1.5s active / off hidden)
        queryFn: poll1|%15 → FULL else DELTA(updatedAfter=maxUpdatedAt) upsert-merge
        ├ ConversationList(search+filters; row: avatar·customer·bot·lastTime·dot·badge)
        ├ ChatThread(system lozenges; sender-run bubbles; ticks; typing bubble)
        ├ Composer(key=thread.id): disabled = needsClaim||pending||sending   ← F20 hole
        │   [Suggest reply][Sources(n)=rag chips] … attach/canned/textarea/Send
        └ ContextRail(contactability, risk, outstanding, promises, disputes, links)
writes → mergeThread(setQueryData) + void invalidate()
RAG    → cache patch(any thread) + state patch(current only)   ← F24 residual
```

**FINDINGS:** 12 total — masters F20-F26 plus: delivery-tick inverse-video `read` vs `delivered` distinction correct; list rows show "Bot is typing…" whenever botTyping regardless of thread-header's extra gating (consistency note); `errorDetail` clips at 400 chars and can split a surrogate pair (trivial).

**Open questions folded into §6.**

### Segment C — Bot tools, promises/pay-links, RAG regression

**LINKS VERIFIED CORRECT:** 23-tool catalog + executor with allowlist gate and stable error taxonomy (bot_tools.py:58-852); create_promise_to_pay chain (handler :254-284 → domain.py:682-772 ISO-only date parse → db.py:5083-5175 INSERT 'upcoming' + activity + fulfill-in-txn); idempotency machinery (db.py:679-729 advisory-lock replay); card lastPromise selector (db.py:8745-8758 — `ORDER BY promised_at DESC NULLS LAST LIMIT 1`, no status filter); ₹ literal in `_confirm_copy` (promise_fulfillment.py:190-200); pay-intent minting with open-intent reuse per promise + token_urlsafe(24) (:224-345); expiry rule = promised-day 23:59 IST **+1 day** (:121-129) — reproduces both specimen "valid until" strings exactly; fulfillment send-gating consent→admit(statutory)→suppression rows (:559-651); KB adapter directives (:234-249) over planner+judge pipeline (kb.py:618-715; kb_plan.py judge ≤700-char clamps, empty→answerable=False, unavailable→fail-open); retrieval internals (kb_retrieve.py:235-656, rate check before embed, indexed+enabled filter, retrieval_logs); runtime prompt rule "Never say you cannot access policy wording if snippets are present" (bot_runtime.py:537-541). Live ground truth pulled from /promises, /interactions/{id}/trace, /agent-studio/cards/*.

**FINDINGS:** masters F38-F45 above. The reconciliation table (§4/A8) is the segment's centerpiece: every transcript artifact matched to its row via second-exact WA-queue activities, both contradictions traced to post-send mutation or re-seeding, and the fabricated Friday-promise proven by empty toolCalls in trace turns.

**RAG REGRESSION (A7) mechanism ranking:** judge-veto on clamped snippets (VERIFIED — only path matching the refusal shape), model disobedience of the never-say-can't rule (weaker — reply echoes the directive's specialist script nearly verbatim), rate-limit soft-fail / corpus-status narrowing (VERIFIED paths but contradicted by T12's ok=true + populated preview), embed-cache (irrelevant to correctness). Post-hoc falsification impossible because verdicts aren't persisted — that gap is the finding.

**Latency note:** T6 search_knowledge_base 24,695ms vs inner retrieval 2,390ms; T12 6,319ms vs 1,356ms — consistent with Azure cold-start/retry (prewarm logged 19.1s cold at 12:02 IST); morning attribution blocked because botworker.err.log starts at 12:02.

## §6 Open questions for the owner

- ~~OQ-1~~ resolved — see A9/A10: 9 takeovers/9 returns existed; read-side dedupe hid them; the 2-second inversion is D3's now-before-lock capture and/or prior assignment. No enforcement gap.
- OQ-2 (A7): Did anything happen to KB/embedding infra between 9:40 and 14:53? *(Segment C analysis pending)*
- OQ-3 (A): Has alembic `20260722_0016` (provider_ref unique index) been applied live? Dedupe safety depends on it.
- OQ-4 (A): What supervises `bot_worker` here — is a worker actually draining jobs in this deployment?
- OQ-5 (method): DB-row-level ground truth across Segments C/D came from read APIs (/promises?customer_id=, /interactions/{id}/trace tool results, activity timestamps) — not container access. Residual: `bot_tool_calls.result_preview` beyond char 1500 has NO API surface; would need sanctioned DB read to settle F39 post-hoc.
- OQ-16 (C): Who patched PTP-8B3876B988.promised_at back to Aug 9 four seconds after queueing its WhatsApp link (actor in PATCH audit trail)? And was PTP-SUSANTH-1's confirm sent via tool flow or operator resend?
- OQ-17 (C): Is `BOT_ID=kaia-v2-4` intentional for the WhatsApp worker while live traffic shows collectionsbot-v2-4 as handler (clone-card workflow)? Decides whether the allowlist mismatch (F38) is latent or active. Related: botworker.err.log prints "env=production" while APP_ENV=dev — confirm which flag drives what.
- OQ-18 (C): Which process served the Aug-20 morning turns (botworker.err.log starts 12:02 IST)? Needed to attribute the 24.7s T6 latency and to rule out a second worker.
- OQ-19 (C): Was APP_ENV dev at seed time (seed_susanth refuses production)? If a scheduler re-seeds shared environments systematically, fixture leakage (F41) will recur.
- OQ-6 (D): Which path assigned CV-SUSANTH-WA1 before its first *visible* takeover (seed assignment? another assign-path?) — needs seed/git archaeology.
- OQ-7 (D): Was the WA `take_over_required` guard present when Day-1 specimen data was created? Current code is enforced either way.
- OQ-8 (D): Is any consumer relying on `activity_events.note` holding customer ids (the D4 accident)? `whatsapp_inbound` uses note=body[:120] — conventions already inconsistent.
- OQ-9 (D): Is refresh's 200-with-stale-chips intended graceful degradation with a vestigial 429 branch — or should rate-limit signal propagate (F16)?
- OQ-10 (D): RLS posture — confirm the live `DATABASE_URL` role; if it's superuser, `_assert_tenant_owns`' own docstring says RLS is inert and D6 stands as deployment-conditional.
- OQ-11 (E): Product intent for `unread` — mark-on-read (needs endpoint + persistence) or is "unanswered" the honest semantic? And should non-WhatsApp channels mirror WhatsApp's takeover gate (F6/F20), given silent steal is currently legal backend-side?
- OQ-12 (B): Exact writer of the +5m15s `updated_at` touch — needs bot_turn_jobs/whatsapp_outbound_jobs/identity_verifications rows for that instant. Top suspects: capture identity-link update during a post-sweep retry (capture.py:1740-1748), or a whatsapp_outbound dead/sent touch (:478/:543/:561/:598).
- OQ-13 (B): Was the 08:50 send produced by handle_turn? Code says any bot reply passes gates #1/#2; confirm via bot_tool_calls/activity rows for that morning.
- OQ-14 (B): Is the in_session window bypass compliance-reviewed? Documented deliberate (contact_policy.py:10-11) but no test pins nighttime-reply behavior either way.
- OQ-15 (B): Does ops have ANY reconciliation UI for stranded 'sending' bot rows (F35)? None exists in backend scope.

## §7 Verdict

**The conversation pipeline is structurally sound at its security spine and dishonest at its edges.**

What holds under zero-assumption pressure: webhook authentication (mandatory, fail-closed, timing-safe HMAC with no dev bypass), inbound idempotency (unique provider_ref + SQLSTATE-matched duplicates → Meta retries safe), per-item savepoints protecting sibling messages, takeover's race discipline (cancels queued/running bot jobs; gate re-checked immediately pre-send), delivery-status monotonicity, the enqueue→single-flight→coalesce job spine, and the RAG planner/judge architecture itself. The feared injection endpoint does not exist.

Where it fails, it fails in one repeated shape: **state that looks right and isn't.** The inbox shows a promise the transcript contradicts and a transcript that hides nine takeovers; a "delivered" tick on a row that never shipped; an unread badge that means unanswered; chips for a conversation that moved on; a composer enabled against a guaranteed 409 whose remedy button is hidden; bot text asserting a Friday promise that no tool ever executed; a refusal whose author (the LLM judge) leaves no record. Ten of the MAJOR-class findings are exactly this — not crashes, but confident presentations of stale, partial, or fabricated state. That is this codebase's documented #1 failure mode, confirmed here at every layer from Postgres to React.

Two findings deserve priority beyond cosmetics: **F12** (a failed inbound message is lost forever behind a 200 OK — silent customer-message loss in a regulated domain) and **F38** (handoff allowlist keyed to env identity that doesn't match the live handler, silently disabling itself on mismatch — a compliance control that evaporates under reconfiguration). **F31/F32** together mean: outside outreach campaigns, nothing but dnd/opt-out/24h stands between a borrower's phone and a 3 AM bot message, and if policy infrastructure errors, even those checks fail open.

The audit's own instrument lesson held to the end: three charset traps were calibrated away before interpretation (§0), every anomaly was chased to a mechanism rather than explained away, and the two scariest early observations — mojibake corruption and a takeover enforcement bypass — both dissolved into auditor-side artifacts once ground truth was obtained. The system's real bugs were subtler than its apparent ones.

*23 findings above MAJOR-threshold discussion: F1-equivalents F12, F17, F18, F20, F21, F31-F34, F38-F41 + queue/runtime set; full ledger §3, evidence chain §2/§5, owner questions §6.*
