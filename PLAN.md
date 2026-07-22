# Collections Agent — Build Plan (Frontend → Backend → Voice)

> **Status:** Frontend done (TanStack Start, 27 screens, dummy data, running on `localhost:8080`).
> **Goal:** A working PoC demo of the voice-first inbound collections agent that visibly produces the three required outputs (query resolution, upsell presented, call summary) and moves the two hero metrics (AHT ↓, upsell conversion).

---

## The architecture (three moving parts)

```
  ┌─────────────┐     WebSocket (live transcript/sentiment)   ┌──────────────┐
  │  FRONTEND   │◄────────────────────────────────────────────│              │
  │ TanStack UI │                                             │   PIPECAT    │
  │ 27 screens  │                                             │  Voice Bot   │
  └──────┬──────┘                                             │ STT·LLM·TTS  │
         │ REST (read data)                                   └──────┬───────┘
         ▼                                                           │ tool calls
  ┌─────────────────────────────────────────────────────────────────▼──────┐
  │                       CRM BACKEND API  (FastAPI + DB)                    │
  │  customers · dues · EMI · calls · summaries · disputes · upsell · KPIs   │
  └─────────────────────────────────────────────────────────────────────────┘
```

- **Frontend** — already built. Reads from the CRM API; live-ops screens also subscribe to Pipecat's WebSocket.
- **CRM Backend API** — the single source of truth (a DB the screens read and Pipecat writes to). Schema mirrors the existing seed files.
- **Pipecat** — the voice bot. On a call it *calls the CRM API as tools* (look up dues, check upsell eligibility) and on hang-up *writes the call summary + metrics back*.

**Recommended stack:** FastAPI + SQLite for the CRM API (same language as Pipecat → one codebase for backend + bot; SQLite is zero-setup for a hackathon). Swap to Postgres only if needed.

---

## Demo scope — what actually needs to be "live"

Do **not** wire all 27 screens to the backend. For the demo, make the **golden-path** screens live and leave the rest on dummy data (they still look great for the pitch).

**Live screens (wired to backend):**
`Executive Dashboard` · `Customer 360` · `Handoff Hub` (live) · `Upsell & Leads` · `Audit / Call History` (where summaries land)

**Stay on dummy data (pitch-only):** everything else (Disputes, Consent, Compliance, Billing, KB manager UI, etc.)

**The golden path to make work end-to-end:**
inbound call → bot identifies caller (phone → customer) → answers a dues/EMI query (RAG + CRM lookup) → presents an eligibility-gated upsell → hangs up → writes a call summary → Dashboard AHT + upsell-conversion tiles tick.

---

## Phases

### Phase 1 — Data seam + API contract *(frontend, ~half day)*
Turn the implicit contract into an explicit one so backend work can start in parallel.
- Add `src/api/` with one module per feature: `fetchDashboard()`, `fetchCustomer(id)`, etc. — **today they return the seed data**.
- Wrap each in a TanStack Query hook (`useDashboard()`), and swap screens from `import ...seed` to the hook.
- Do the **golden-path screens first**; others can follow or stay on seeds.
- **Output:** a frozen list of endpoints + response shapes (derived from the seed files) = the backend contract.

### Phase 2 — CRM Backend API *(backend, ~1 day)*
- FastAPI project + SQLite. Models mirror the seed shapes from Phase 1.
- Seed the DB with the **synthetic dataset** (a handful of realistic customers with dues/EMI, an upsell product catalog, policy FAQs).
- Implement the golden-path endpoints: `GET /customers/:id`, `GET /dashboard`, `GET /calls`, `POST /calls` (summary writeback), `GET /upsell/eligibility/:id`.
- Point the Phase-1 `fetch*()` functions at the real API. Golden-path screens now run on the DB.

### Phase 3 — Pipecat voice bot *(backend, ~1–1.5 days)*
- Pipeline: **Twilio** (telephony) → **Deepgram** (STT) → **LLM** (OpenAI/Azure) with tools + RAG → **ElevenLabs** (TTS).
- **Tools call the CRM API:** `identify_caller(phone)`, `get_dues(customer_id)`, `get_emi_schedule`, `check_upsell_eligibility`.
- **RAG** over the policy FAQ docs for informational answers.
- **Guardrail:** informational only — the bot never takes a payment (matches the brief + sidesteps financial-action rules).
- On call end: generate summary → `POST /calls` → Dashboard/Audit update.

### Phase 4 — Realtime live-ops *(optional, if time)*
- WebSocket from Pipecat streaming transcript + sentiment → Handoff Hub & Floor Command Center render it live.
- If time is short, demo Handoff Hub on a replayed/scripted transcript instead.

### Phase 5 — Demo polish
- Rehearse the golden path via the **Call Simulation Sandbox** using synthetic scripts.
- Craft one compelling customer scenario end-to-end.
- Fallback: pre-recorded run in case of live network/telephony flakiness.

---

## Immediate next action
Start **Phase 1 on the Dashboard screen** as the reference pattern (`src/api/dashboard.ts` + `useDashboard()`), confirm it renders identically, then roll the same pattern across the golden-path screens. This unblocks backend work immediately because it produces the concrete API contract.

## Parallelization
Once Phase 1 fixes the contract, Phases 2 (CRM API) and 3 (Pipecat) can proceed **in parallel** — the API contract is the interface between them.

## Phase 1 — DONE ✅ (data seam on golden-path screens)

All golden-path screens now read through `src/api/*` instead of importing seeds directly. Swap point: `src/api/config.ts` (`USE_MOCK`, `API_BASE_URL`, `apiGet`). Two consumption idioms, both calling the same `fetch*` functions:
- **React-Query hooks** (list/dashboard screens): Dashboard, Customers list, Audit, Upsell.
- **Router loader** (detail route, keeps SSR + `notFound()`): Customer 360 detail.

Sub-components keep importing **types** and **pure formatters** from the seeds (those are frontend presentation code, not backend data). Only record data moved behind the seam.

### Frozen API contract (what the CRM backend must serve in Phase 2)

| Endpoint | Returns | Consumed by |
|---|---|---|
| `GET /dashboard?range&segment&team` | `{ heroKpis[], kpis[], recoveryTrend[], callVolumeStacked[], sentimentDistribution, botVsHuman[], leaderboard[], atRiskAccounts[] }` (already filtered server-side) | Executive Dashboard |
| `GET /customers` | `Customer[]` (list rows) | Customers index |
| `GET /customers/:id` | `Customer` (full record w/ ledger, emi, interactions, promises, disputes, documents, notes) or 404 | Customer 360 detail |
| `GET /calls` | `CallRecord[]` | Audit Trail |
| `GET /leads` | `Lead[]` | Upsell & Leads |
| `GET /handoff/active` | `{ activeCall, customerContext, transcriptScript[], suggestions[], complianceItems[], dispositions[] }` | Handoff Hub (initial snapshot; live stream is Phase 4 WebSocket) |

The exact TypeScript response shapes live in `src/data/*-seed.ts` (the type exports) — the backend mirrors those. **Mutations** (create PTP, move lead stage, log call, save wrap-up) are still local/in-memory and become POST/PATCH endpoints + `useMutation` in Phase 2/3.

### Remaining screens
The other ~21 screens still import seeds directly and render fine on dummy data. Apply the same pattern only if/when they need live data — not required for the demo.

## Phase 2 — DONE ✅ (CRM backend + seeded database)

FastAPI + SQLite backend in `backend/`, serving the frozen Phase-1 contract from a database seeded with the **exact** data the frontend showed.

- **Schema:** queryable columns + a JSON blob per record (right fit for deeply-nested BFSI documents; same shape the bot will INSERT in Phase 3). Tables: `customers`, `calls`, `leads`, `snapshots` (dashboard + handoff).
- **Seeding:** `Habibi/scripts/export-seeds.ts` snapshots the TS seed data → `backend/seed/*.json`; the API loads it into SQLite on first start (idempotent). 6 customers, 42 calls, 22 leads, dashboard + handoff snapshots.
- **Endpoints live:** `GET /health`, `/customers`, `/customers/:id` (404s correctly), `/dashboard?range&segment&team` (filtering ported to Python), `/calls`, `/leads`, `/handoff/active`.
- **Frontend flipped to live** via `Habibi/.env.local` (`VITE_USE_MOCK=false`). All seamed screens verified rendering on real HTTP data, no console errors.

Mutations are still local/in-memory — they become POST/PATCH + `useMutation` when the bot needs to write (Phase 3).

## Running the stack

**Backend** (terminal 1):
```
cd backend
.venv/Scripts/python -m uvicorn main:app --host 127.0.0.1 --port 8000
```
**Frontend** (terminal 2):
```
cd Habibi
npm run dev        # http://localhost:8080 (falls back to 8081 if busy)
```
- Re-seed after editing seed data: `cd Habibi && npx tsx scripts/export-seeds.ts`, then delete `backend/collections.db` and restart the backend.
- Back to offline mock: delete `Habibi/.env.local` (or set `VITE_USE_MOCK=true`) and restart Vite.

## Notes / decisions
- **Package manager:** machine has Node/npm, not Bun. `npm install` used; `package-lock.json` now coexists with Lovable's `bun.lock` — harmless.
- **Lovable sync:** repo is Lovable-connected — don't rewrite git history; keep the branch working.
- **Secrets:** API keys (Twilio/Deepgram/ElevenLabs/LLM) live in the backend `.env`, never in the frontend.
