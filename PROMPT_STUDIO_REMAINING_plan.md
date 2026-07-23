# Prompt Studio — Remaining Work Plan (PS-5 + Deferred)

> Status: **Done** (2026-07-22) — D1–D11 accepted as **(rec)**; implemented 5C→5B→5A→5D→5E→DEF-1→DEF-2  
> Basis: codebase inspection after PS-0–PS-4 landed — **no invented tables/APIs**  
> Companion: `PROMPT_STUDIO_plan.md` (locked decisions for PS-0–4 still apply)

---

## 0. What’s already done (do not re-plan)

| Phase | Status |
|---|---|
| PS-0 Schema + seed + live-config invariant | Done |
| PS-1 Read APIs + Studio rewire | Done |
| PS-2 Draft / publish / restore / rollback | Done |
| PS-3 Sandbox runs + turns (retrieve + Azure chat) | Done |
| PS-4 Azure Speech TTS preview + debounce/cache | Done |
| Integrations labels → Azure Speech (seed copy) | Done |

**Locked invariants still in force**

- Active prod `bot_deployments.prompt_version_id` ≡ sole `prompt_versions.status = 'published'`
- JSONB writes validated with Pydantic `extra="forbid"`
- `render_prompt` whitelist-only (no `str.format`)
- Azure-only for LLM / embeddings / TTS / STT
- `prompt_versions` remains **global** (no `bot_id`) until multi-bot structural work

---

## 1. Remaining scope (evidence-based)

### In scope — this plan

| ID | Item | Evidence of gap |
|---|---|---|
| **PS-5A** | Analytics → Prompt Studio deep-link + optional gap link | `UnansweredTable` toasts only; Studio has **no** `validateSearch` |
| **PS-5B** | Publish attaches a real `kb_snapshot_id` | Publish **copies prior** deployment snap; can stay `NULL` forever |
| **PS-5C** | `get_active_deployment(bot_id, env)` helper | Only `list_bot_deployments`; Sandbox/publish reimplement fallbacks |
| **PS-5D** | Sandbox KB dropdown → live snapshots | FE seed ids (`2026-07-15`, …) ≠ DB (`kb-snapshot-2026-07`); retrieve ignores snap |
| **PS-5E** | Azure STT endpoint (API-only) | `azure_speech.py` is TTS-only; mic in Sandbox is visual affordance |
| **DEF-1** | Optional prompt lint (`POST /prompt-versions/lint`) | Planned in original plan; **no** route exists |
| **DEF-2** | Token estimate honesty | Client `length/4` heuristic; tiktoken only in KB chunking |

### Explicitly out of scope (do not sneak in)

| Item | Why |
|---|---|
| Pipecat / Twilio live telephony | Original non-goal; Phase 4 product |
| Full multi-bot / `bot_id` on `prompt_versions` | Needs schema + index redesign (flagged §13 of original plan) |
| Snapshot-filtered ANN retrieve (freeze embeddings per snap) | Snapshots today store **id lists only**; filtering live index by those lists is a separate KB workstream |
| Multi-provider TTS/STT | Locked Azure-only |

---

## 2. Facts locked from the codebase

### 2.1 Analytics row contract (already shipped)

`UnansweredQuestion` / `BotAnalyticsUnansweredQuestionResponse`:

- `id`, `text`, `hits`, `lastSeen`, `topIntent`, `hasKbDoc`, `suggestedFix` ∈ `{kb, prompt, both}`

Tables:

- `unanswered_questions` (`11_analytics.sql`)
- `analytics_kb_gap_links` — already has nullable `prompt_version_id`, `kb_document_id`, `faq_pair_id`, `routing_rule_id`

Existing write (KB side only):

- `POST /kb/gaps/{gap_id}/link` → FAQ/doc; **forces `prompt_version_id = NULL` today**

### 2.2 KB snapshots (already shipped)

- Table: `kb_snapshots(id, label, document_ids, faq_ids, created_at)`
- `create_kb_snapshot()` / `list_kb_snapshots()` / `GET|POST /kb/snapshots` exist
- Auto-snapshot on `POST /kb/reindex-all`
- Seed: one row `kb-snapshot-2026-07`
- **Retrieve does not consume snapshot membership** — only stores id on `sandbox_runs` / `bot_deployments`

### 2.3 Deployments

- `DEFAULT_BOT_ID = os.getenv("BOT_ID", "kaia-v2-4")` — **not** in `.env.example`
- Publish/rollback use that constant
- Sandbox omit-`promptVersionId` path: active **sandbox** dep → else active **production** → else 404

### 2.4 Speech

- TTS: `POST /tts/preview` + disk cache — working against `eastus2`
- STT: **absent**
- Sandbox mic: `ConversationPanel` advances scenario on release — no audio upload

---

## 3. Open decisions (need explicit choice — no silent assumptions)

Answer these before/during implementation. Recommended defaults are marked **(rec)**; they are **proposals**, not locked.

| # | Question | Options | Rec |
|---|---|---|---|
| D1 | Analytics “Prompt fix” — navigate only, or also persist a gap link? | (a) navigate + URL context only (b) navigate + `POST` link with `prompt_version_id` = current published (c) create draft first, then link | **(b)** — uses existing `analytics_kb_gap_links.prompt_version_id`; no new table |
| D2 | Studio deep-link param shape | (a) `?note=` + `?gapId=` (b) `?unansweredId=` only, Studio fetches text (c) both note + id | **(c)** — id for durable link; note for instant banner if fetch fails |
| D3 | “Add to KB” from Bot Analytics | (a) leave toast (b) navigate `/knowledge-base?gapId=` (c) call existing `/kb/gaps/{id}/link` after creating gap | **(b)** for this workstream — KB ownership stays on KB screen; don’t fork gap UX in Analytics |
| D4 | Publish snapshot policy | (a) inherit prior only (today) (b) attach **latest** existing snapshot (c) **create** new snapshot on every publish (d) create only if none on prior | **(b)** if any snapshot exists, else `NULL`; optional UI checkbox later for (c) |
| D5 | Snapshot-on-publish create? | Always create vs never create in PS-5B | **Never auto-create** in publish transaction — creation is side-effect heavy (lists all docs); use `POST /kb/snapshots` / reindex-all separately |
| D6 | Sandbox “Current” KB meaning | (a) `kb_snapshot_id = NULL` + live retrieve (today) (b) resolve to latest snapshot id for bookkeeping only | **(a)** — honest: retrieve is live; label “Current (live index)” |
| D7 | Should Sandbox retrieve filter by snapshot doc ids? | (a) no — bookkeeping only (b) yes — restrict ANN to `document_ids` | **(a) in PS-5D**; (b) is KB-plan work (needs retrieve filter + tests) — **call out as follow-on** |
| D8 | STT scope in this plan | (a) `POST /stt/transcribe` + wire Sandbox mic (b) API only, Sandbox mic later (c) defer all STT to Phase 4 | **(a)** if Speech key already live — small vertical slice; else **(b)** |
| D9 | STT audio format contract | browser `audio/webm` vs force wav | Accept `webm`/`wav`/`mp3`; Azure Speech REST supports several — detect `Content-Type` |
| D10 | Prompt lint | (a) skip (b) Azure chat checklist vs guardrails (c) deterministic only (vars + prohibited words) | **(c) first**, optional (b) behind flag — lint must not burn tokens on every keystroke |
| D11 | Token estimate | (a) keep heuristic (b) tiktoken in API (c) remove $ cost display | **(a)** for PoC; document as estimate; **(c)** if demo reviewers object to fake $ |

**Please confirm D1–D11** (or accept all **(rec)**) before coding starts.

---

## 4. Target architecture (remaining)

```
Bot Analytics UnansweredTable
    │ "Prompt fix"
    ├─► navigate /prompt-studio?unansweredId=&note=
    └─► POST /kb/gaps/{id}/link { promptVersionId }   (if D1=b)

Prompt Studio
    ├─ validateSearch { unansweredId?, note? }
    ├─ banner: “Fixing unanswered: …”
    └─ publish ──► attach latest kb_snapshot_id (D4=b)
                      via get_active_deployment / list snapshots

get_active_deployment(bot_id, env)
    ▲ used by: publish, sandbox default, future live voice

Sandbox
    ├─ KB dropdown ← GET /kb/snapshots + “Current (live index)”
    └─ mic ──► POST /stt/transcribe ──► customer text turn (PS-5E)

azure_speech.py
    ├─ synthesize (done)
    └─ transcribe (new)
```

---

## 5. Phased delivery

### PS-5A — Analytics → Studio deep-link (+ gap link)

**Backend**

1. Extend gap-link request to accept **exactly one of** `faqPairId` | `kbDocumentId` | `promptVersionId` (today prompt is hard-nulled).
2. `POST /kb/gaps/{gap_id}/link` with `{ "promptVersionId": "<published or draft id>" }` → set `analytics_kb_gap_links.prompt_version_id`.
3. Validate FK; `409` if contradictory multi-target; `404` if gap/version missing.
4. Do **not** invent a new “prompt fix task” table — the link row **is** the audit trail.

**Frontend**

1. `UnansweredTable` “Prompt fix”:
   - `navigate({ to: '/prompt-studio', search: { unansweredId, note: r.text } })`
   - If live API + D1=b: also `link` with current published id (from `usePublishedPromptVersion`).
2. `prompt-studio.tsx`: add `validateSearch` for `unansweredId?: string`, `note?: string`.
3. Show dismissible banner when `note` or fetched gap text present; **do not** auto-mutate the system prompt (agent decides what to edit — avoids silent prompt pollution).
4. “Add to KB”: navigate to `/knowledge-base` with `gapId` / `q` search if that route already supports it; else toast → KB with copy of question in clipboard **only if** KB route has no search yet — prefer extending KB search over clipboard hacks.

**Acceptance**

- Click Prompt fix → lands on Studio with visible context banner.
- After link call, `analytics_kb_gap_links` row has non-null `prompt_version_id`.
- Mock mode: navigate works; link write skipped or no-ops cleanly.

---

### PS-5B — Publish attaches snapshot id

**Backend**

1. In `publish_prompt_version` transaction, resolve `kb_snapshot_id` as:
   ```
   prior.active.kb_snapshot_id
     OR latest kb_snapshots by created_at   # D4=b
     OR NULL
   ```
2. Never call `create_kb_snapshot()` inside publish (D5).
3. Document in endpoint docstring.
4. Add `BOT_ID` to `.env.example` (default `kaia-v2-4`).

**Acceptance**

- Fresh DB with seed snapshot → new deployment after publish has `kb_snapshot_id = kb-snapshot-2026-07` (or latest).
- No snapshot rows → `NULL` allowed; publish still succeeds.
- Live-config invariant unchanged.

---

### PS-5C — `get_active_deployment(bot_id, env)`

**Backend**

```python
def get_active_deployment(bot_id: str | None = None, environment: str = "production") -> dict | None:
    """Authoritative runtime loader. One active row per (bot, env) expected."""
```

Rules:

1. `bot_id` defaults to `DEFAULT_BOT_ID`.
2. Filter `environment` + `status='active'` + `bot_id`.
3. Order `published_at DESC NULLS LAST`; take first.
4. Return same shape as `list_bot_deployments` row (or `None`).
5. Refactor:
   - `publish_prompt_version` / `rollback_bot_deployment` prior lookup
   - `sandbox_runtime.create_sandbox_run` default path  
   to call this helper (sandbox env first, then production — keep **documented** fallback).

**HTTP (optional thin wrapper)**

- `GET /bot-deployments/active?environment=production&botId=` → 404 if none  
  Prefer this over clients guessing from list.

**Acceptance**

- Single function; grep shows Sandbox + publish use it.
- Multi-bot: still filtered by `bot_id` even though prompt versions are global (honest limitation documented).

---

### PS-5D — Sandbox KB dropdown uses live snapshots

**Frontend**

1. Replace `KB_SNAPSHOTS` seed usage in `SandboxHeader` with `useKbSnapshots()` from `api/kb.ts` (already exists).
2. Options: `{ id: "current", label: "Current (live index)" }` + API rows `{ id, label }`.
3. Pass through to `createSandboxRun` as today (`null` when current).

**Backend (bookkeeping only unless D7=b approved)**

1. Keep existence check; stop soft-nulling without logging — return `400` if client sends unknown snapshot id (fail loud).
2. **Do not** claim RAG is snapshot-pinned in UI copy while retrieve is live.

**Follow-on (separate KB ticket, not PS-5D)**

- `retrieve(..., document_ids=[...])` filter from snapshot membership.

**Acceptance**

- Dropdown shows real `kb-snapshot-*` ids from API.
- Selecting a real snapshot stores that id on `sandbox_runs`.
- Selecting Current stores `NULL`.

---

### PS-5E — Azure STT (API + optional Sandbox mic)

**Backend**

1. `azure_speech.transcribe(audio: bytes, *, content_type: str, language: str | None) -> dict`
   - REST: `https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1`
   - Auth: same `AZURE_SPEECH_KEY` / `REGION`
2. `POST /stt/transcribe` — multipart `file` + optional `language` (default `en-IN`).
3. Errors: missing config → `503`; Azure failure → `502`; empty audio → `400`.
4. No persistence of raw audio in PoC (privacy); only return `{ text, latencyMs, language }`.

**Frontend (if D8=a)**

1. `ConversationPanel` mic: MediaRecorder → blob → `apiUpload('/stt/transcribe')` → feed text into existing turn pipeline.
2. Fallback: if mic permission denied, toast + keep text input.
3. Copy: remove “visual affordance only” comment; label accurately.

**Acceptance**

- curl/multipart smoke returns transcript for a short wav/webm.
- Sandbox (if wired): spoken line becomes a customer turn + bot RAG reply.

---

### DEF-1 — Prompt lint (optional)

**Deterministic pass (ship first)**

- `POST /prompt-versions/lint` body: `{ prompt, guardrails }`
- Checks: unknown `{vars}`, missing recording disclosure phrase if `alwaysDiscloseRecording`, prohibited words present in prompt text.
- Response: `{ findings: [{ severity, code, message, span? }] }` — no LLM.

**Optional Azure pass** (flag `includeLlm: true`)

- Chat: “list missing compliance behaviors vs guardrails” — never auto-edit.

---

### DEF-2 — Token estimate

- Keep client heuristic; label UI “≈ tokens (est.)”.
- Do **not** add tiktoken to Studio request path unless product asks (latency + dep weight).

---

### Multi-bot (documented only — not scheduled)

When needed later:

1. Alembic: `prompt_versions.bot_id` NOT NULL FK → `bots`
2. Drop global `ux_prompt_versions_one_published`; add partial unique `(bot_id) WHERE status='published'`
3. Scope publish/rollback/list by `bot_id`
4. Backfill existing rows to `kaia-v2-4`

Do **not** implement under current global unique index.

---

## 6. API surface (delta only)

| Method | Path | Phase | Notes |
|---|---|---|---|
| `POST` | `/kb/gaps/{id}/link` | PS-5A | Extend body: optional `promptVersionId` |
| `GET` | `/bot-deployments/active` | PS-5C | Thin wrapper over helper |
| `POST` | `/stt/transcribe` | PS-5E | multipart audio |
| `POST` | `/prompt-versions/lint` | DEF-1 | Deterministic (+ optional LLM) |

Reuse existing: `GET /kb/snapshots`, `GET /bot-analytics`, Studio write APIs, Sandbox runs/turns, `POST /tts/preview`.

---

## 7. Infra / config deltas

`.env.example` additions/updates:

```env
BOT_ID=kaia-v2-4
# Speech already present for TTS; STT reuses same key/region
# AZURE_SPEECH_KEY=
# AZURE_SPEECH_REGION=eastus2
```

No new Azure resources required for PS-5A–D. STT uses existing `BT-Speech` F0 resource (same free-tier character/time limits apply — monitor throttling).

---

## 8. Dependency order

```
PS-5C get_active_deployment  ──┐
                               ├─► PS-5B publish snapshot attach
PS-5A analytics deep-link  ────┤
PS-5D sandbox snapshot UI  ────┘  (independent of 5B)

PS-5E STT ───────────────────── after Speech creds verified (done)
DEF-1 lint ──────────────────── anytime after PS-5A (Studio banner synergy)
DEF-2 copy-only ─────────────── anytime
KB follow-on: snapshot-filtered retrieve ── after PS-5D, owned by KB plan
```

Suggested build order: **5C → 5B → 5A → 5D → 5E → DEF-1**.

---

## 9. Success criteria

| Criterion | Measure |
|---|---|
| Analytics → Studio | Prompt fix navigates with visible context; no toast-only dead end |
| Gap audit | Optional link row with `prompt_version_id` set |
| Publish + KB | New prod deployment gets latest snapshot id when any exist |
| Loader | One helper; Sandbox default + publish prior-lookup use it |
| Sandbox KB UI | Dropdown ids match `GET /kb/snapshots`; unknown id → 400 |
| Honest RAG | UI does not claim snapshot-pinned retrieve until KB follow-on ships |
| STT | `/stt/transcribe` returns text; optional mic path works |
| No scope creep | No Pipecat/Twilio; no multi-bot schema; no ElevenLabs |

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Auto-create snapshot on publish slows/fails publish | D5: never create inside publish txn |
| Deep-link auto-edits prompt | Banner only; human edits |
| Snapshot UI implies frozen KB | Label “live index”; defer filtered retrieve |
| F0 Speech throttling (TTS+STT) | Cache TTS; short STT clips; document limits |
| Gap link vs dual Analytics/KB UIs | Extend existing link API; don’t invent second store |
| Key leaked in chat history | Rotate Speech key before production demo |

---

## 11. Immediate next step

1. **Confirm open decisions D1–D11** (or “accept all rec”).
2. On approval, implement in order **PS-5C → 5B → 5A → 5D → 5E**.
3. Open a separate KB ticket for snapshot-filtered `retrieve()` if product wants true dated RAG.

---

## Appendix — file touch list (expected)

| Area | Files |
|---|---|
| Loader | `backend/db.py`, `backend/main.py`, `backend/.env.example` |
| Publish snap | `backend/db.py` (`publish_prompt_version`) |
| Gap link | `backend/schemas.py`, `backend/db.py` (`link_kb_gap`), Analytics + Studio FE |
| Studio search | `Habibi/src/routes/prompt-studio.tsx` |
| Sandbox KB | `Habibi/src/components/sandbox/SandboxHeader.tsx`, `sandbox.tsx` |
| STT | `backend/azure_speech.py`, `main.py`, `ConversationPanel.tsx`, `api/sandbox.ts` or `api/speech.ts` |
| Lint | `backend/main.py`, `schemas.py`, optional Studio button |
