# Persona & Prompt Studio — Production Plan

> Status: **Approved decisions locked** (2026-07-22); revised with review feedback  
> Screen: Habibi `/prompt-studio` (currently mock)  
> Goal: Production-grade prompt/persona/voice/guardrails editor with versioned publish, wired to Sandbox and (later) live voice — **Azure-only** for LLM, embeddings, TTS, and STT

---

## 1. Decisions (locked)

| # | Question | Decision |
|---|---|---|
| 1 | Persistence | **Reuse existing tables** — `prompt_versions`, `persona_presets`, `tts_voices`, `bot_deployments`, `sandbox_*`. No parallel “studio” schema. |
| 2 | JSONB contract | **Frontend types are the API contract** — store `PersonaState` / `VoiceConfig` / `Guardrails` as jsonb, but **validate on every write** via Pydantic submodels with `extra="forbid"` (not free `dict`/`Any`). Malformed drafts are rejected at the API boundary. |
| 3 | Version metadata | Add **`label`** (`v1.4`, nullable — backfill in seed) + **`summary`** (`TEXT NOT NULL DEFAULT ''`) on `prompt_versions`. |
| 4 | LLM / embeddings | **Azure OpenAI only** — reuse existing `azure_openai.py` + env already configured (`AZURE_OPENAI_*`). Chat for Sandbox replies (+ optional lint later). Embeddings stay KB-owned via shared `retrieve()`. |
| 5 | TTS / STT | **Azure Speech only** — no ElevenLabs, Deepgram, or other providers. Studio Voice tab → Azure TTS preview; Sandbox/live voice → Azure STT + Azure TTS. |
| 6 | Publish semantics | Atomic: archive current `published` → promote target → create/retire **`bot_deployments`** (`production`). “Test in Sandbox” uses draft/`prompt_version_id` or a **sandbox** deployment — does **not** promote prod. |
| 7 | **Live-config authority** | **`bot_deployments` is authoritative for what runs** (prod/sandbox loaders, live runtime). `prompt_versions.status = 'published'` is **editor state** for the Studio UI. **Invariant:** the active production deployment’s `prompt_version_id` **MUST equal** the single published prompt version. Publish and rollback both maintain this atomically — rollback **always** re-publishes (never optional). |
| 8 | Tenancy / bot scope | Same PoC model: `TENANT_ID=hdfc.retail` via env; deployments scoped through `bots.tenant_id`. **No `tenant_id` / `bot_id` on `prompt_versions` until Phase 5.** Today’s global singleton published index is accepted for single-bot PoC (see §13). |
| 9 | Delivery approach | **PS-0 foundations → PS-1 reads → PS-2 publish writes → PS-3 Sandbox LLM → PS-4 Azure TTS preview → PS-5 cross-page glue.** STT belongs to Sandbox/live voice, not the Studio editor itself. Integrations label rewrite is **independent** of PS-4 (mock copy only). |
| 10 | Wire-up pattern | Phase 3B **five moves**: `schemas.py` → `db.py` → `main.py` → `Habibi/src/api/prompt-studio.ts` → rewire route. `USE_MOCK` preserved. |

### Why these choices

- **Reuse tables** — `DATA_MODEL.md` / `09_bot_config.sql` already define “bot behavior is release-versioned” via `bot_deployments` (prompt + KB snapshot + voice). Inventing new tables would fork the contract Sandbox/live load.
- **Deployments own runtime** — a deployment also carries KB snapshot + TTS voice; reading only `prompt_versions.published` would drop those. Editor still needs a single “live” badge → keep `status = 'published'` in sync via the invariant, don’t use it as the runtime loader’s source of truth.
- **Azure-only speech** — one cloud, one credential story, matches Azure OpenAI already in `.env`.
- **Chat not used for editing** — Prompt Studio is a CRUD + publish surface. Azure chat earns its keep in **Sandbox** (and optional lint), same way embeddings earn theirs in **KB**.
- **Sandbox ≠ Publish** — demo safety: agents can try a draft without flipping the unique published row or prod deployment.
- **Validated jsonb** — “as-is storage” without Pydantic submodels lets garbage persist and fail much later in Sandbox/runtime with no trace to the write.

---

## 2. Current state

### Frontend (mock only)
- Route: `Habibi/src/routes/prompt-studio.tsx`
- Components: `Habibi/src/components/prompt-studio/*` (`StudioHeader`, `PromptEditor`, `PersonaSliders`, `VoicePanel`, `GuardrailsPanel`, `VersionHistory`, `DiffModal`, `PublishDialog`)
- Seed/types: `Habibi/src/data/prompt-studio-seed.ts` — TS contract types (`PersonaState`, `VoiceConfig`, `Guardrails`, `PromptVersion`, …) already exist
- No `Habibi/src/api/prompt-studio.ts` (or persona/voice client)
- Tabs: System Prompt | Persona | Voice (TTS) | Guardrails
- Publish / restore / dirty-check are **in-memory React state** only
- Voice preview = Web Audio oscillators (not real TTS)
- “Test in Sandbox” = toast only; does not navigate or pass version id
- Known bug: after first local publish, `dirty` / live label can desync from history (computed from initial seed published row)

### Backend (schema ready, APIs missing)
- Tables in `backend/sql/09_bot_config.sql`: `prompt_versions`, `persona_presets`, `tts_voices`, `bot_deployments`, `sandbox_scenarios`, `sandbox_runs`, `sandbox_run_turns`
- Partial unique index `ux_prompt_versions_one_published`: **one** row with `status = 'published'` **globally** (no `bot_id` on the table)
- Seed (`seed_postgres.py`): **1-row stub** — one published prompt, one preset, one `local-tts` voice, one prod deployment — **not** aligned with rich UI seed (`v1.0`–`v1.4`, 4 presets, 6 voices, full trait/guardrail shapes)
- No `/prompt-*` or `/bot-deployments` HTTP routes yet
- `azure_openai.py` exists (chat + embeddings) — used by KB ingest; **not** used by Prompt Studio
- No Azure Speech client yet

### Related consumers (later)
- Call Sandbox → load explicit `prompt_version_id` (draft try) **or** active sandbox/prod deployment; Azure chat + KB retrieve
- Bot Analytics → “send to Prompt Studio” deep-link (today toast-only)
- Knowledge Base → `kb_snapshots` attached on publish when available
- Routing → escalate when guardrail flags fire
- Live voice (Phase 4) → **`get_active_deployment(bot_id, env)`** + Azure STT/TTS

---

## 3. Product goal & page wiring

Golden path: inbound collections voice agent (HDFC retail) → identify → CRM + RAG answer → gated upsell → call summary.

| Surface | Role relative to Prompt Studio |
|---------|--------------------------------|
| **Prompt Studio** | Edit **behavior** (prompt, persona, voice, guardrails); version + publish |
| **Knowledge Base** | Edit **knowledge**; freeze `kb_snapshots` for a deployment |
| **Routing** | Escalation / handoff rules (consume guardrail signals) |
| **Sandbox** | Dry-run prompt version (+ KB) before prod |
| **Integrations** | Azure OpenAI + **Azure Speech** credentials/health |
| **Bot Analytics** | Unanswered / containment gaps → Prompt Studio or KB |
| **Live voice runtime** | Loads active `bot_deployments`; Azure STT → LLM → Azure TTS |

```
┌─────────────────────────────────────────────────────────────┐
│ Bot Configuration                                           │
│  Prompt Studio  ·  Knowledge Base  ·  Routing  ·  Integrations│
└────────────┬───────────────┬───────────────┬────────────────┘
             │ publish       │ snapshot      │ Azure keys
             ▼               ▼               ▼
        prompt_versions   kb_snapshots   Azure Speech / OpenAI
             \               /             (editor sync)
              \             /
               ▼           ▼
            bot_deployments  ◄── authoritative for runtime
             /            \
            ▼              ▼
     Call Sandbox     Live voice runtime
     (Azure chat +    (Azure STT → chat → Azure TTS)
      KB retrieve)
```

---

## 4. Target architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Habibi /prompt-studio                                       │
│  Prompt | Persona | Voice | Guardrails | Version History    │
└────────────────────────────┬────────────────────────────────┘
                             │ Habibi/src/api/prompt-studio.ts
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ FastAPI                                                     │
│  /prompt-versions · /persona-presets · /tts-voices          │
│  /bot-deployments (publish / rollback / list)               │
│  Optional: POST /prompt-versions/lint   (Azure chat)        │
│  Optional: POST /tts/preview            (Azure Speech TTS)  │
│  Later:    /sandbox/runs                (chat + retrieve)   │
└───────┬──────────────────┬──────────────────┬───────────────┘
        │                  │                  │
        ▼                  ▼                  ▼
   Postgres           Azure OpenAI       Azure Speech
   prompt_versions    chat (+ lint)      TTS preview
   persona_presets    embeddings via     STT (Sandbox /
   tts_voices         KB retrieve()      live voice only)
   bot_deployments
```

**Locked stack**

| Layer | Choice |
|---|---|
| Config store | Postgres (`prompt_versions` jsonb + deployments) |
| Runtime loader truth | **Active `bot_deployments` row** (env + status) |
| Editor “live” badge | `prompt_versions.status = 'published'` (kept in sync by invariant) |
| LLM | Azure OpenAI **chat** deployment (existing env) |
| Embeddings | Azure OpenAI **embedding** deployment — via KB `retrieve()` only |
| TTS | **Azure Speech** neural TTS |
| STT | **Azure Speech** (Sandbox voice / live runtime — not Studio CRUD) |
| API style | Same five moves as Routing/Inbox |
| Tenancy | Env `TENANT_ID`; no prompt-row tenant/bot until Phase 5 |

**Out of scope providers:** ElevenLabs, Deepgram, OpenAI TTS, local-tts (seed placeholder only until Azure Speech catalog is seeded).

---

## 5. Infra & configuration

### 5.1 Azure OpenAI (already configured — reuse)

Do not invent a second client. Use `backend/azure_openai.py`.

```env
AZURE_OPENAI_ENDPOINT=https://....openai.azure.com/
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_API_VERSION=2025-04-01-preview
AZURE_OPENAI_CHAT_DEPLOYMENT=
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=
AZURE_OPENAI_EMBEDDING_DIMS=1536
```

### 5.2 Azure Speech (new — TTS/STT only)

```env
AZURE_SPEECH_KEY=
AZURE_SPEECH_REGION=          # e.g. eastus, centralindia
AZURE_SPEECH_TTS_VOICE_DEFAULT=en-IN-NeerjaNeural
# Optional map: studio voice id → Azure neural voice name
# AZURE_SPEECH_VOICE_MAP=priya:en-IN-NeerjaNeural,ravi:en-IN-PrabhatNeural
```

Add to `backend/.env.example` when PS-4 starts. Never commit real keys.

**SDK / module (planned):** `backend/azure_speech.py`
- `synthesize(text, voice_name, *, speed, …) -> bytes` (audio/mpeg or wav)
- `transcribe(audio_bytes, *, language) -> str` (for Sandbox/live — not Prompt Studio page)

### 5.3 App / tenant (existing)

```env
TENANT_ID=hdfc.retail
ACTOR_USER_ID=priya-nair
DATABASE_URL=...
```

### 5.4 Frontend seam (existing pattern)

```env
VITE_USE_MOCK=false
VITE_API_BASE_URL=http://localhost:8000
```

---

## 6. Data model & mapping

### 6.1 Tables (existing)

| Table | Studio use |
|---|---|
| `prompt_versions` | Versioned prompt + persona/voice/guardrails jsonb; one published (**global** singleton today) |
| `persona_presets` | Empathetic / Firm / Compliance / Upsell |
| `tts_voices` | Catalog; `provider` = `azure-speech`; `config` holds Azure voice name + UI metadata |
| `bot_deployments` | **Runtime release unit:** prompt + optional kb_snapshot + tts_voice + env |
| `sandbox_scenarios` / `sandbox_runs` / `sandbox_run_turns` | Sandbox execution log (PS-3+) |

### 6.2 Schema delta (PS-0 Alembic)

```sql
ALTER TABLE prompt_versions
  ADD COLUMN IF NOT EXISTS label TEXT,                      -- nullable; backfill in seed
  ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT ''; -- safe for existing rows
```

Backfill labels for seed rows (`v1.0` … `v1.4`). Keep unique published index as-is for PoC.

### 6.3 UI ↔ DB mapping

| UI (`PromptVersion`) | DB |
|---|---|
| `id`, `prompt`, `status` | columns |
| `label`, `summary` | new columns (`label` nullable) |
| `author` | join `users` via `author_user_id` |
| `createdAt` | `created_at` |
| `persona` / `voice` / `guardrails` | jsonb — **exact TS shapes**, validated by Pydantic submodels |

**Pydantic write contract (required):** nest full models, not `dict`. Top-level `extra="forbid"` alone is **not** enough if jsonb fields are typed as `dict` — mirror the TS types fully so a bad draft fails at write time.

```python
class PersonaTraits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    empathy: int
    firmness: int
    formality: int
    verbosity: int
    upsell: int

class PersonaState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    traits: PersonaTraits
    language: str
    fallbackLanguages: list[str]

class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voiceId: str
    speed: float
    pitch: int
    warmth: int
    pauseMs: int
    sampleText: str

class Guardrails(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # fields mirror prompt-studio-seed.ts exactly
    ...
```

**PersonaState / VoiceConfig / Guardrails** shapes match `Habibi/src/data/prompt-studio-seed.ts`.

**Known template variables** (substitution at runtime, not publish time):

`customer_name`, `account_no`, `overdue_amount`, `due_date`, `last_payment`, `agent_name`, `bank_name`, `language`, `time_of_day`

**`render_prompt` (PS-3) — injection-safe substitution only:**

- Do **not** use `str.format`, f-strings with user data, or `Template.safe_substitute` over untrusted keys.
- Replace **only** whitelist tokens of the form `{var_name}` for `var_name ∈ KNOWN_VARIABLES`.
- Treat context values as **inert strings** (no recursive substitution — a customer name containing `{overdue_amount}` must not expand).
- Unknown `{…}` tokens in the template: leave as-is or flag in lint; never interpret as format fields / attribute access.

### 6.4 Live-config invariant & mutations

**Invariant (always):**  
`active production bot_deployments.prompt_version_id` = the single `prompt_versions` row with `status = 'published'`.

| Role | Source of truth |
|---|---|
| What **runs** (Sandbox default “live”, live voice, Pipecat) | Active `bot_deployments` for that `environment` |
| Studio “published / live” badge & history | `prompt_versions.status` (must match deployment via invariant) |
| Explicit draft try in Sandbox | Requested `prompt_version_id` (bypasses prod; does not change invariant) |

**Publish** — single DB transaction:

1. Archive current published: `UPDATE … SET status = 'archived' WHERE status = 'published'`
2. Promote target: `UPDATE … SET status = 'published', summary = :note WHERE id = :id AND status = 'draft'` (or allow republish rules as coded)
3. Retire prior active prod deployment (`status = 'retired'`)
4. `INSERT bot_deployments` — `environment = 'production'`, `status = 'active'`, same `prompt_version_id`, optional latest `kb_snapshot_id`, `tts_voice_id` from `voice.voiceId`, actor + `published_at`

**Concurrency:** the partial unique index rejects a second published row. Catch unique-violation → map to clean **409**; the losing concurrent publish must **fail atomically** (transaction rollback) so it never half-archives the current live row. Document this failure mode in the publish endpoint.

**Rollback** — single DB transaction (re-publish is **mandatory**, not optional):

1. Resolve target deployment `D` (must be prior prod deployment for this bot)
2. Archive current `published` prompt version
3. Set `D.prompt_version_id`’s row to `status = 'published'` (re-publish)
4. Retire current active prod deployment; set `D` to `status = 'active'` (or insert a new active row pointing at `D`’s prompt/KB/voice with `rollback_deployment_id` link — either pattern is fine if invariant holds)

After rollback, active prod deployment and published prompt version **must not diverge**.

---

## 7. API surface

Response shapes must match Habibi TS types **exactly**. Request bodies for persona/voice/guardrails use the nested Pydantic models in §6.3.

### 7.1 Reads (PS-1)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/prompt-versions` | History, newest first (editor) |
| `GET` | `/prompt-versions/published` | Editor “live” badge — the published row (**must** match active prod deployment’s version) |
| `GET` | `/prompt-versions/{id}` | Full version (restore / compare) |
| `GET` | `/persona-presets` | Preset cards |
| `GET` | `/tts-voices` | Voice tab catalog (`provider=azure-speech`) |
| `GET` | `/bot-deployments` | Filter `?environment=production\|sandbox` — **runtime truth** |

Prefer `GET /bot-deployments?environment=production&status=active` (or a dedicated helper) for Sandbox “run as live” and Phase-4 loaders — not “guess from published alone.”

### 7.2 Writes (PS-2)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/prompt-versions` | Create **draft** (validated jsonb) |
| `PATCH` | `/prompt-versions/{id}` | Update draft only (`409` if not draft) |
| `POST` | `/prompt-versions/{id}/publish` | Body `{ "summary": "..." }` — publish + prod deployment in **one transaction**; unique-violation → **409** |
| `POST` | `/prompt-versions/{id}/restore-as-draft` | Copy archived → new draft (never overwrite live) |
| `POST` | `/bot-deployments/{id}/rollback` | Activate prior deployment **and** re-publish its prompt version atomically |

Client still requires typing `PUBLISH` in `PublishDialog` before calling the API.

**PoC scope note:** `prompt_versions` has **no `bot_id`**; `ux_prompt_versions_one_published` is a **global** singleton. Fine for one bot. Phase 5 must add `bot_id` (or tenant) on `prompt_versions` and change the partial unique index to per-`(bot_id, status)` — see §13.

### 7.3 Optional / later

| Method | Path | Phase | Purpose |
|---|---|---|---|
| `POST` | `/prompt-versions/lint` | PS-3+ | Azure chat: missing disclosures vs guardrails |
| `POST` | `/tts/preview` | PS-4 | Azure Speech synthesize `sampleText` → audio (debounced + cache — see PS-4) |
| `POST` | `/sandbox/runs` | PS-3 | Run scenario against draft/published + **KB retrieve** (gate on retrieve existing) |
| `POST` | `/stt/transcribe` | Sandbox voice | Azure Speech STT (not on Studio page) |

Errors: `KeyError → 404`, `ValueError → 409`, unique-violation on publish → **409** (same family as other screens).

---

## 8. Phased delivery

### PS-0 — Foundations (schema + seed)
- Alembic: `label` (nullable), `summary NOT NULL DEFAULT ''` on `prompt_versions`
- Enrich seed to match UI: history `v1.0`–`v1.4`, 4 presets, 6 Azure Speech–mapped voices, rich jsonb
- Ensure seed satisfies the live-config invariant (one published + matching active prod deployment)
- Set `tts_voices.provider = 'azure-speech'`; store Azure neural voice name in `config`
- Add Pydantic submodel stubs (or TypedDicts) documenting jsonb shapes — wire fully in PS-1/2
- **No HTTP yet**
- **Anytime:** rewrite Integrations mock labels Deepgram/ElevenLabs → Azure Speech (§11) — do not wait for PS-4

### PS-1 — Read API + frontend seam
- `schemas.py` / `db.py` / `main.py` GETs (nested response models for persona/voice/guardrails)
- `Habibi/src/api/prompt-studio.ts` + React Query hooks + `USE_MOCK`
- Rewire `/prompt-studio` off seed for history / presets / voices
- Fix dirty/published derivation from **current** published row (and/or active deployment)

### PS-2 — Draft + Publish writes
- Draft create/patch with **full Pydantic jsonb validation**
- Publish + rollback in single transactions maintaining §6.4 invariant; concurrent publish → 409
- Invalidate queries; header live label from API
- “Test in Sandbox” → `navigate({ to: '/sandbox', search: { promptVersionId } })`
- Sandbox may still be mock-LLM until PS-3

### PS-3 — Sandbox LLM (Azure chat + RAG)
- **Prerequisite:** KB `retrieve()` exists and is callable — do **not** ship PS-3 as “prompt-only answers” labeled RAG
- `POST /sandbox/runs` (+ turn persistence)
- Load prompt version → whitelist `render_prompt` → `retrieve()` → `chat_complete()`
- Enforce guardrails (prohibited words, max turns/seconds flags on turns)
- Wire Sandbox UI to `promptVersionId` query param; default “live” run loads **active deployment**, not published-alone
- Stop importing static `VERSION_HISTORY` as source of truth

### PS-4 — Azure Speech TTS preview
- `backend/azure_speech.py` + env in `.env.example`
- `POST /tts/preview` → audio bytes / short-lived URL
- **Debounce** slider-driven previews; **cache** by hash of `(text, voice, speed, pitch)` (and warmth/pause if they affect synthesis) so nudges aren’t metered on every pixel
- Replace oscillator preview in `VoicePanel`

### PS-5 — Cross-page glue
- Bot Analytics unanswered → deep-link Prompt Studio with context note
- Publish attaches current `kb_snapshot_id` when KB snapshots exist
- Single `get_active_deployment(bot_id, env)` helper for live runtime (authoritative loader)
- Live path: Azure STT → Azure chat (+ retrieve) → Azure TTS

---

## 9. Dependency order vs other workstreams

```
KB retrieve spine ──────────────┐  (hard gate for PS-3)
                                ▼
PS-0 → PS-1 → PS-2 → PS-3 (Sandbox LLM + RAG)
                │         │
                │         └─→ PS-5 analytics / snapshot-on-publish
                └─→ PS-4 Azure TTS preview
                              │
                              ▼
                     Live voice runtime (Azure STT + TTS)

Integrations label rewrite ─── anytime (independent of PS-4)
```

- **Studio CRUD (PS-0–2)** does not block on MinIO, STT, or full KB admin UI.
- **PS-3 must not land before `retrieve()`** — otherwise Sandbox answers from the prompt alone while looking like RAG.
- **STT** is never required to ship Prompt Studio itself — only Sandbox voice mode / live calls.

---

## 10. Frontend fixes (ship with PS-1 / PS-2)

| Issue | Fix with |
|---|---|
| Dirty / live label desync after publish | Derive from API published row + respect deployment invariant (PS-1/2) |
| Test in Sandbox is toast-only | Navigate with `promptVersionId` (PS-2) |
| Sandbox uses static `VERSION_HISTORY` | Load versions / active deployment from API (PS-2/3) |
| Oscillator TTS preview | Azure Speech preview + debounce/cache (PS-4) |
| Fake token/cost estimate | Keep heuristic for PoC; optional tiktoken later |
| No shared draft across pages | Server + URL params as source of truth |

Preserve existing UX composition (tabs, presets rail, version timeline, publish confirm). Do not redesign the screen while wiring.

---

## 11. Integrations screen implication

Today’s Integrations seed lists Deepgram STT + ElevenLabs TTS. For this project:

| Capability | Provider |
|---|---|
| LLM | Azure OpenAI (chat) |
| Embeddings | Azure OpenAI (embedding) |
| TTS | **Azure Speech** |
| STT | **Azure Speech** |
| Telephony | Twilio (unchanged when Phase 4 lands) |

**Update Integrations mock/labels anytime** (even during PS-0/1) so the demo story stays coherent — this is copy/seed only, not gated on Azure Speech wiring. Do not implement multi-provider voice switching.

---

## 12. Success criteria

| Criterion | Measure |
|---|---|
| Persistence | Refresh → same published prompt + history |
| Publish safety | Exactly one `published` row; client `PUBLISH` confirm retained; concurrent loser → clean 409, no half-archive |
| **No live split-brain** | **Active prod deployment and published prompt version never diverge** (after publish and after rollback) |
| Consumer contract | Runtime loaders use **active `bot_deployments`**; Studio badge uses published status kept in sync |
| Validated config | Bad persona/voice/guardrails rejected at write (`extra="forbid"` submodels) |
| Safe substitution | `render_prompt` whitelist-only; no `str.format` on customer-controlled values |
| Azure usage | Chat for Sandbox; embeddings via KB; Speech for TTS/STT only |
| No third-party voice AI | Zero ElevenLabs / Deepgram dependencies in backend |
| Pattern fit | Five-move wire-up; `USE_MOCK` still works |
| Demo story | Edit prompt/persona → Publish → Sandbox (via deployment / version id) reply behavior changes |

---

## 13. Explicit non-goals (this workstream)

- Pipecat / Twilio live telephony wiring (Phase 4; consumes this plan’s `get_active_deployment` loader)
- MinIO / KB upload wizard (owned by `KB_plan.md`)
- JWT / RLS multi-tenant (Phase 5)
- Redesigning Prompt Studio visual layout
- Multi-provider TTS/STT abstraction

### Known Phase-5 structural change (flag now)

Today `prompt_versions` has **no `bot_id` / `tenant_id`**, and `ux_prompt_versions_one_published` enforces a **global** singleton published row. Acceptable for single-bot PoC. Multi-bot or multi-tenant will require:

1. `bot_id` (and/or `tenant_id`) on `prompt_versions`
2. Partial unique index per `(bot_id, status)` where `status = 'published'`
3. Publish/rollback scoped to that bot’s deployment row

Do not silently invent multi-bot behavior under the current global index.

---

## 14. Suggested immediate next step

1. This file is **locked** (live-config invariant + Azure Speech-only + validated jsonb).
2. Implement **PS-0** (Alembic + seed alignment satisfying the invariant; Integrations label rewrite can land in the same pass).
3. Implement **PS-1** (read APIs + `api/prompt-studio.ts` + rewire).

Parallel: finish KB `retrieve()` before starting PS-3.
