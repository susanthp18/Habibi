# Phase 3B — Screen Wiring Guide

How to wire each remaining screen from in-memory seed data to the live backend.
Proven end-to-end on **Promises** (the reference implementation). Follow the same
five moves per screen. Write endpoints already exist from Phase 3A — most screens
only need a **GET list endpoint** added plus the frontend re-pointed at it.

## The pattern (per screen)

1. **Backend read schema** (`backend/schemas.py`) — add a `*ListResponse` model that
   matches the screen's TypeScript shape *exactly* (field names, enums). Use
   `ConfigDict(extra="forbid")` so drift fails loudly. The screen shape is almost
   always **richer** than the Customer-360 contract (adds customerName, accountTail,
   owner/assignee names, events timeline, etc.) — don't reuse the 360 serializer.
2. **Backend accessor** (`backend/db.py`) — add `list_<thing>()` that JOINs the base
   table to `customers`/`users`/`bots` for display names, pulls child rows
   (evidence, installments) and the timeline from `activity_events`. Reuse existing
   helpers (`_rows`, `_account_tail`, `_id`, status/reminder mappers). Group child
   rows with one `= ANY(:ids)` query, not N+1.
3. **Backend route** (`backend/main.py`) — add `GET /<thing>` with
   `response_model=list[<Thing>ListResponse]`; import the schema. Restart the API
   (it runs without `--reload`) and `curl` the endpoint.
4. **Frontend seam** (new `Habibi/src/api/<thing>.ts`) — mirror `api/upsell.ts`:
   a `use<Thing>()` query hook + one wrapper per mutation, each with a
   `USE_MOCK ? seedFn(...) : apiPost/apiPatch(...)` branch. Keep the mock branch
   calling the existing seed mutators so mock mode is byte-for-byte unchanged.
5. **Rewire route + sheets** — swap the direct `seed*` import for the `use<Thing>()`
   hook; replace in-memory mutate + local `bump()`/`tick` re-render with the seam
   calls followed by `queryClient.invalidateQueries({ queryKey: [...] })`. Delete the
   `tick` counter. Derive the detail-sheet target from fetched data, not the seed array.

## Cross-cutting gotchas (learned on Promises)

- **Customer/owner pickers must use real IDs.** Seed rosters contain synthetic
  customers (`X1…`, fictional agent names) that don't exist in the DB — picking one
  in live mode 404s. Feed create/assign forms a **real** list (from `useCustomers()`),
  falling back to the seed only in mock.
- **One identity, from `GET /me`.** Never render a hardcoded user in the shell or
  default a form to a seed constant like `CURRENT_AGENT` — the UI would claim one
  actor while the backend records another, which makes the audit trail lie. Use
  `useMe()` / `currentActor()` (`api/me.ts`). Tenant and acting user are env config
  (`TENANT_ID`, `ACTOR_USER_ID`), not literals in SQL; Phase 5 swaps them for the
  JWT subject + RLS GUC without touching call sites.
- **The server owns storage paths.** Clients post `filename`/`mimeType`; the backend
  derives `storage_ref` (it knows the tenant). Don't let the UI invent paths.
- **Never hardcode name→ID maps.** Use `GET /staff` via `api/staff.ts`
  (`useStaff()` for pickers, `resolveActor(name)` inside mutations). Hardcoded maps
  silently drift from the DB — that's what `resolveActor` exists to prevent. It
  returns `{id, kind}` so callers can pick `ownerUserId` vs `ownerBotId`.
- **Don't fake a write.** If the UI collects a field, persist it — add the column
  and an Alembic migration (see `20260722_0003`) rather than dropping it silently
  or throwing. `activity_events` is the timeline store, so free-text notes belong
  there as a first-class entry, not in a new table.
- **PATCH semantics: `exclude_unset`, not `exclude_none`.** Otherwise an explicit
  `null` can never clear a column (that's what blocked unassigning a dispute).
  With `exclude_unset`, a *present* key means intent and `None` means clear.
- **Validate FK targets in the write path** and raise `KeyError` → 404 (unknown
  user/bot) or `ValueError` → 409 (contradictory input), so bad IDs fail loudly.
- **Widen backend enums, don't narrow the UI.** If the screen sends a value the 3A
  request model rejected (e.g. a reminder state), widen the `Literal` — it's
  backward-compatible and keeps Customer 360 working.
- **Derive what the DB doesn't store.** Some screen fields have no column (plan
  cadence/owner/start, resolution notes). Derive them in the accessor (from
  installment spacing, linked promise owner) or return `null` and note the gap.
- **Seed volume is lower than the mock.** Live lists show fewer rows and some empty
  columns — that's correct, not broken.

## Verification (what "done" means)

- `node_modules/.bin/tsc --noEmit` is clean (strict, all files).
- Load the screen in the browser against the live API: real data renders, **zero
  console errors**.
- Round-trip each write (create/patch) via curl or the UI, confirm it lands in the
  DB **and** in `activity_events`, then **clean up test rows** so the demo seed stays
  pristine.

---

## Done: Disputes ✅

Same five moves as Promises. `GET /disputes` returns the screen `Dispute` shape
(with `evidence[]` + `activity_events` timeline). Writes reuse Phase 3A
`POST/PATCH /disputes` and `POST /disputes/{id}/evidence`. Frontend seam:
`Habibi/src/api/disputes.ts`.

**No outstanding limitations** — the earlier gaps were closed rather than documented:
- `resolution_notes` column added (Alembic `20260722_0003`); resolve/reject notes persist.
- `POST /disputes/{id}/notes` writes a real `note_added` timeline entry.
- Unassign works (PATCH switched to `exclude_unset`, so explicit `null` clears).
- `GET /staff` replaced the hardcoded assignee map in both Disputes and Promises.
- Promise create honours the chosen owner (`ownerUserId`/`ownerBotId`), so `source`
  derives correctly instead of always defaulting to the acting user.

## Done: Callbacks ✅

Same five moves. `GET /callbacks` returns the screen `Callback` shape (customer/
assignee/queue JOINs, `reminders[]`, `activity_events` timeline). Writes reuse
`POST/PATCH /callbacks` and `POST /callbacks/{id}/reminders`. Frontend seam:
`Habibi/src/api/callbacks.ts`. Queues via `GET /teams` + `api/teams.ts`
(`resolveTeam`), assignees via `/staff` — no hardcoded maps.

**Closed for real (not flagged):**
- `transcript_snippet` + `outcome_notes` columns (Alembic `20260722_0004`); create
  notes and CRM outcome notes persist.
- Create honours chosen assignee (including Unassigned — no silent force to actor).
- Unassign / clear works (`exclude_unset` on PATCH).
- Priority, team/queue, disposition, window all patchable; unknown user/team → 404.
- Reminder POST accepts `status` (`queued` | `sent`); sending advances
  `scheduled → reminded`.
- `source` derived from origin interaction (no invented column).
- DND evaluated in IST against the customer's preferred window.
- Smoke callback `CB-FFB08AA926` removed.

## Done: Consent/DND ✅

Same five moves. `GET /consent` returns the screen `ConsentRecord` shape
(per-channel matrix, allowed window, opt-out log, `activity_events` audit).
Writes reuse / widen `PATCH /consent/{customer_id}` and
`POST /consent/{customer_id}/opt-out`. Frontend seam: `Habibi/src/api/consent.ts`.
No assignee/queue maps.

**Closed for real (not flagged):**
- `used_this_week` on `channel_consents` + `note` on `optout_events` (Alembic
  `20260722_0005`); frequency reset and opt-out notes persist.
- Opt-out channel check widened to allow `all` (one log row, all channels flipped).
- PATCH uses `exclude_unset`; accepts screen fields (`status`, caps, window,
  `consentExpiresAt`, `onDndRegistry`, free-text `note` → `activity_events`).
- Allowed hours parsed/written from `allowed_days` / `allowed_hours` (and synced
  to `customers.preferred_window`); DND registry syncs `customers.dnd`.
- Children loaded with `= ANY(:ids)` (channels, opt-outs, audit) — no N+1.

## Done: Documents ✅

Same five moves. `GET /document-requests` returns the screen `DocRequest` shape
(customer/assignee JOINs, template/period/timestamps, `activity_events` timeline).
Writes reuse / widen `POST/PATCH /document-requests` and
`POST /document-requests/{id}/delivery-attempts`. Frontend seam:
`Habibi/src/api/documents.ts`. Assignees via `/staff`; new-request customers via
`useCustomers()` + acting user via `currentActor()` — no `CURRENT_AGENT` defaults.

**Closed for real (not flagged):**
- `period`, `requested_via`, `failed_reason`, `size_kb`, `generated_at`, `sent_at`
  columns (Alembic `20260722_0006`); status transitions persist what the UI collects.
- Screen template IDs (`T-STMT-6M`, …) seeded into `document_templates`; legacy
  `template-statement` / `template-noc` remapped.
- PATCH uses `exclude_unset`; assignee/channel/template/status/timestamps/size/
  failedReason all patchable; explicit null clears assignee / failedReason.
- Retry = PATCH `requested` + POST delivery-attempt (bumps `attempts`).
- Server owns `storage_ref` on `document_files` (client posts filename/mimeType only).
- `_doc_channel` preserves `sms` (was collapsing non-whatsapp to email).
- Smoke leftover `DOC-70D46A45CC` removed.

## Done: Compliance ✅

Same five moves. `GET /violations` returns the screen `Violation` shape
(customer/assignee/rule JOINs, transcript evidence ± neighbours, structured
`notes[]` from `activity_events`). Writes reuse / harden `PATCH /violations/{id}`
and add `POST /violations/{id}/notes`. Frontend seam: `Habibi/src/api/compliance.ts`.
Assignees via `/staff`; note author via `currentActor()` — no hardcoded
"Compliance Ops" / "You".

**Closed for real (not flagged):**
- `at_sec` column + screen rule IDs (`r-rec`, …) (Alembic `20260722_0007`);
  legacy `rule-recording` etc. remapped; smoke `reviewed` → `acknowledged`.
- PATCH uses `exclude_unset`; status widened to `open | in_review | acknowledged |
  resolved`; unknown assignee → 404; explicit null unassigns.
- Notes no longer append to `description` — first-class `note_added` activity rows
  (same pattern as Disputes).
- PATCH returns the full list serializer, not `{id, status}`.
- Evidence derived from `interaction_transcript` neighbours around `at_sec`.

## Done: Bot Analytics ✅

Read-only Tier-1 screen (no writes / `/me` / `/staff`). Same schema + accessor +
route + seam + rewire pattern, adapted: one `BotAnalyticsResponse` object, not a
list. **Live aggregates from `interactions` (+ handoffs / transcript /
`unanswered_questions`)** — do not read the stub `analytics_daily` /
`intent_aggregates` / `escalation_reasons` tables. Frontend seam:
`Habibi/src/api/bot-analytics.ts` (`useBotAnalytics(range, channel)`). KPIs stay
client-side via `computeKpis(dailySeries)`.

**Closed for real (not flagged):**
- `GET /bot-analytics?range=30d&channel=all` → screen shape (`dailySeries`,
  `intentAggs`, `escalationReasons`, `unansweredQuestions`, `turnsHistogram`,
  `funnelStages`); channel filter pushed to SQL (`WHERE channel = :channel`).
- Latency percentiles via `percentile_cont(0.5/0.9/0.99)` in SQL.
- Escalation `trendDelta` vs the prior equal-length window.
- `unanswered_questions.top_intent` + seeded gap rows (Alembic `20260722_0008`)
  so the RAG-miss table isn't a single smoke row; `hasKbDoc` from
  `analytics_kb_gap_links`.
- Reconcile check: `sum(dailySeries.sessions)` == `count(*)` on interactions in
  the same window (verified for 30d).

## Done: QA Scorecards (core MVP) ✅

Biggest screen — wired **scorecard core** only (queue + per-criterion scoring).
Coaching + calibration tabs stay seed-backed until their endpoints land.

Same five moves, but the Phase 3A write path was a stub (`total_score`/`band`
only) so PATCH was substantially widened — not just a GET. Central gotcha:
criterion IDs must match the screen rubric, so Alembic `20260722_0010` seeds
the full `defaultRubric` tree (`rubric-v1` / `emp-acknowledge` / …) and rebuilds
entries on the 0–5 scale. Frontend seam: `Habibi/src/api/qa.ts`
(`useScorecards`, `useRubric`, `saveScorecard`, `finalizeScorecard`). Reviewer
from `currentActor()` — never a hardcoded "You".

**Closed for real (not flagged):**
- `GET /rubric` + `GET /scorecards` → screen shapes; entries padded to all 13
  criteria; `handledBy.kind` includes `handoff` when an interaction handoff exists.
- `PATCH /scorecards/{id}` accepts `entries[]` + status (`unscored|ai_draft|final`);
  upserts `qa_scorecard_entries`, recomputes `total_score`/`band` (critical-fail
  cap at 40), `exclude_unset`, subject/reviewer FK → 404, finalize writes
  `scorecard_finalized` activity + `scored_at`.
- Columns `description` / `accepted` / `scored_at` added rather than dropped.
- Local draft overlay in `qa.tsx` until Save draft / Publish; coaching +
  calibration remain isolated seed `useState` blocks.

## Remaining after QA core

~~Fast-follows on the same page: coaching actions + calibration sessions~~
**Done** — see seed-chip close-out below. Then Phase 4 bot emission / Tier-2
screens per the product roadmap.

## Done: Redaction & Export Hub (reads) ✅

Tier-1 close-out screen — **reads + writes**. Accept/reject finding, rule
toggles, mark-reviewed, and export jobs persist via live endpoints (see
seed-chip close-out).

Same five moves. Central gotcha: never leak raw PII through the read API —
`pii_findings.masked` is what non-Admin actors get in `finding.text`; raw
substring from the transcript turn is reserved for Admin / Compliance roles.
`accepted` is surfaced on every finding. Frontend seam:
`Habibi/src/api/redaction.ts` (`useRedactionRecords`, `useRedactionRules`).

**Also closed with this pass (Tier-1 crash fixes):**
- `LeadCard` null `owner` → `"Unassigned"` (3 unassigned leads no longer crash).
- Audit `fetchCalls` maps `[{flag,severity}]` → `CallFlag[]` and drops
  `smoke_flag`; leftover `smoke_flag` seed row deleted from `interaction_flags`.

**Closed for real (not flagged):**
- `GET /redaction-records` (+ `/{id}`) → screen `RedactionRecord` shape with
  nested `findings[]` + `audioSegments[]` + interaction transcript; tenant-scoped
  via `interactions.tenant_id` / `customers.tenant_id` = `hdfc.retail`.
- `GET /redaction-rules` → full 10-type vocabulary with labels; frontend maps
  the list into `RedactionRules`.
- Local overlays in `redaction.tsx` for finding accept/mute/reviewed; exports +
  rule edits remain seed-backed and labelled.

## Done: Conversation Inbox ✅

Tier-3 screen. Pre-A vocabulary migration first (`20260722_0011`: stored status
`mine` → `assigned` + `assigned_user_id`; message sender `human` → `agent`).
`GET /conversations` returns the screen `Thread` shape (messages, derived
SLA/unread/`isMine`, context rail). Writes: `POST .../takeover`,
`POST .../messages`, `GET /canned-responses`. Take-over writes
`activity_events` (`conversation_takeover`). Frontend seam:
`Habibi/src/api/inbox.ts`. Mine filter derived via `GET /me` / `ACTOR_USER_ID`
— never a stored `mine` status.

**Deferred by design (see `conversation_inbox_plan.md`):** WhatsApp Meta I/O
(Phase B), Azure RAG (Phase C), shared realtime with Handoff/Floor (Phase D).

## Done: Redaction PII seed polish ✅

Seed gap (not a code bug): all 8 `pii_findings` were identical phone clones with
`transcript_turn_id` NULL / offsets 0, and transcripts had no PII — so
TranscriptRedactor highlighted nothing and the masking / role-gate path was a
no-op. Alembic `20260722_0012` (+ `0014` card/aadhaar overlap fix) injects
varied PII into customer turns and rebuilds findings with correct turn anchors
+ offsets (phone/email/PAN/aadhaar/card/account/dob). A few records are left
unreviewed so pending-review is demonstrable.

## Done: Routing & Logic Builder (reads) ✅

Tier-2 screen — **reads first**. Create / reorder / toggle / edit / delete stay
optimistic/seed (flagged) until Phase 3A writes land. Audit log remains seed.

Seed pass first (`20260722_0013`): widen `routing_rules` with
`name` / `description` / `category`, seed ~8 screen-shaped rules (Habibi
FIELDS + ActionKey vocabulary), rewrite legacy `route-sentiment-drop`, and
redistribute the 42 `routing_rule_executions` across rules (one execution per
interaction — no double-count) with a matched slice bumped into the last 24h.

Same five moves. Frontend seam: `Habibi/src/api/routing.ts` (`useRoutingRules`).

**Closed for real (not flagged):**
- `GET /routing-rules` → priority-ordered screen `Rule` shape with `when[]`,
  `then`, `executionCount` (matched), `lastFiredAt`, `triggersLast24h`.
- `GET /routing-rules/{id}/executions` → firing log (optional; builder audit
  tab stays seed for rule-edit history).
- Tenant-scoped; aggregates via `LATERAL` / `rule_id` (no N+1, no version
  double-count — there is no rule-version column).

**Still seed-chipped:** ~~New rule / save / toggle / reorder / delete / audit log.~~
**Closed** — see seed-chip close-out.

## Done: My Workspace — AssignedQueue (reads) ✅

Agent home screen. Clean win off the `work_items` view (open-status UNION across
disputes / callbacks / docs / broken·partial PTPs / followups / leads). StatsStrip
and RightRail are follow-ons — **not** faked live.

**Product decisions (flagged honestly):**
- **Followups tab added.** The view has ~28 followups (Priya: 8) with no prior
  tab — leaving them out hid half the chase list. Leads stay on Upsell (returned
  with `entityType=lead` but not bucketed into tabs).
- **Broken PTPs** = `entity_type='promise'`. The view already excludes pending
  (`due_today|broken|partial` only); client keeps broken/partial/due_today.
- **StatsStrip stays seed-chipped.** Literal "today" aggregates over interactions
  would read all-zero on the historical seed (same liveness trap as Floor). Wire
  a rolling window later rather than ship fake zeros.

Same five moves. Frontend seam: `Habibi/src/api/workspace.ts` (`useWorkItems`,
`bucketWorkItems`). Greeting first name from `useMe()` — never hardcoded Priya.

**Closed for real (not flagged):**
- `GET /work-items?assignee=me` → screen `QueueRow` + `entityType` / `status` /
  `assigneeUserId`. Default `assignee=me` resolves via `ACTOR_USER_ID` (`/me`).
- `sla` / `slaLabel` / `ageHours` computed server-side from `sla_due_at` +
  `created_at` (not stored). Detail/amount via 6 grouped `= ANY(:ids)`
  enrichments (no N+1).
- AssignedQueue tabs are live slices; null `amount` / missing assignee safe
  (no `.split` crash class).

**Still seed-chipped:** ~~StatsStrip tiles, RightRail (next callback / SLA
countdowns / outside-window nudge count).~~ **Closed** — see seed-chip close-out.

## Done: Call Simulation Sandbox (PS-3) ✅

Demo climax — not the usual 5-move read. Heart is a compute path that spends
real Azure tokens + KB retrieve.

**Closed for real (not flagged):**
- `GET /sandbox/scenarios` → Habibi-shaped scenarios (persona + openingBot +
  scripted customer turns). Seeded via `20260722_0019` (6 scenarios, ≤2 turns).
- `GET /sandbox/runs/{id}` → run + turns with `groundedIn[]` doc-title chips
  (real `kb_chunks` ids only in `retrieved_chunk_ids`).
- `POST /sandbox/runs` → start session bound to `promptVersionId` (Studio
  deep-link) or active sandbox/prod deployment. Opening uses whitelist
  `render_prompt` (no `str.format` injection).
- `POST /sandbox/runs/{id}/turns` → retrieve (top-k, no draft) →
  `chat_complete_detailed` (temp 0.2) → persist customer+bot turns with
  chunk ids, guardrail flags, latency, tokens. Hard ceiling
  `SANDBOX_HARD_MAX_TURNS` (default 3). Prohibited / max-turns / max-seconds /
  waiver-blocked **halt** the run; `auto-escalate` flags without hard-stop.
- Frontend seam `Habibi/src/api/sandbox.ts` + rewired `/sandbox`:
  `useSandboxScenarios`, `usePromptVersions`, create/append on Next/Send.
  No auto-run on mount. `promptVersionId` search param from Studio "Test in
  Sandbox". Bot bubbles show **grounded in [doc title]** chips.

**Still seed-chipped:** ~~KB snapshot dropdown~~ (live), ~~Promote-to-Production~~
(now calls `publishPromptVersion`).

## Done: Prompt Studio TTS preview (PS-4) ✅

Replace the oscillator stand-in in VoicePanel with real Azure Speech neural TTS.

**Closed for real (not flagged):**
- `backend/azure_speech.py` — REST SSML synthesize (`audio-16khz-128kbitrate-mono-mp3`),
  whitelist voice resolve from `tts_voices.config.azureVoiceName`, disk cache under
  `.cache/tts/` keyed by hash(text, voice, speed, pitch, warmth, pauseMs).
- `POST /tts/preview` → `audio/mpeg` bytes + `X-TTS-Cache` / `X-TTS-Voice` /
  `X-TTS-Latency-Ms` headers. Caps sample text at 500 chars.
- Frontend `previewTts()` + rewired `VoicePanel`: Preview button hits Azure;
  while playing, slider/voice nudges are **debounced (450ms)** and identical
  params hit the server cache (no meter on every pixel).
- `.env.example` documents `AZURE_SPEECH_KEY` / `REGION` / default voice.

**Requires:** `AZURE_SPEECH_KEY` + `AZURE_SPEECH_REGION` in `backend/.env`
(503 if missing).

## Done: Seed-chip close-out (QA / Redaction / Routing / Workspace / Sandbox) ✅

Closed the remaining "Still seed-chipped" leftovers on already-wired screens.

**QA coaching + calibration**
- Alembic `20260722_0022` adds `coaching_actions.category`, `calibration_sessions.name`
  + `target_scores`, remaps statuses, seeds ~6 coaching + 2 calibration sessions.
- `GET/POST /coaching-actions`, `PATCH /coaching-actions/{id}`
- `GET /calibration-sessions`, `PATCH /calibration-sessions/{id}` (close)
- Notes via `activity_events`; FE `useCoachingActions` / `useCalibrationSessions`.

**Redaction writes + exports**
- `PATCH /pii-findings/{id}` (accepted), `PATCH .../audio-mute`,
  `PATCH /redaction-records/{id}` (reviewed), `PATCH /redaction-rules/{pii_type}`
- `GET/POST /export-jobs`, `PATCH /export-jobs/{id}` (download bump / retry)
- Seed chips removed from the Redaction route.

**Routing writes + audit**
- `POST/PATCH/DELETE /routing-rules`, `POST /routing-rules/reorder`
- `GET /routing-audit` from `activity_events` (`rule_*` kinds)
- Seed chips removed from the Routing route.

**My Workspace StatsStrip + RightRail**
- `GET /workspace/summary` — rolling 7d anchored to `max(interactions.started_at)`
  (honest non-zero on historical seed), next callback, SLA countdowns,
  outside-window count. No fake "today" zeros.

**Sandbox**
- KB dropdown already on live `GET /kb/snapshots` + "Current (live index)"
- Promote → `publishPromptVersion` (real prod publish path)

**Module:** `backend/followups_db.py` (re-exported from `db.py`).

**Still out of scope (unchanged):** Floor live interactions, Integrations table,
Webhooks/Billing thin screens, Phase 4 Pipecat/WebSocket, PS-5 deep-links.


