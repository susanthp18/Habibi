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

## Remaining Tier 1 after Documents

Compliance, Bot Analytics — same five moves.

## Next screen: Compliance

- Wire `GET` list to the compliance screen shape and reuse existing violation
  writes.
- Same five moves.
