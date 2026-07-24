# Dynamic Azure TTS Voice Catalog — Build Plan

> **Status:** approved for implementation · **Owner:** Susanth · **Date:** 2026-07-24  
> **Scope:** Replace the static 6-voice Prompt Studio seed with a region-synced Azure Speech catalog, budget-first picker UI, and daily refresh. Wire selection into deployments / `AgentTuning` / live voice bot.  
> **Grounding:** `azure_tts_voices.json` (769 voices for this Speech region), existing `tts_voices` table + `VoicePanel.tsx` + `azure_speech.py` + `AgentTuning.tts.voice`.

---

## 0. Decisions (locked)

| # | Decision | Choice |
|---|---|---|
| 1 | Picker scope | **No locale limits** — full catalog is in scope (all locales Azure returns for this region). Default UI filters may still prefer `en-IN` / `hi-IN` for convenience, but users can browse everything. |
| 2 | Default voice | Switch product default from `en-IN-NeerjaNeural` → **`en-IN-AartiNeural`** (standard Neural — not Dragon HD). |
| 3 | Premium voices | **Hidden behind a toggle** (“Show premium”). Off by default. Premium = HD / HD Flash / Turbo / MAI / DragonHD tiers. |
| 4 | Catalog freshness | **Daily sync job** against Azure `voices/list`, plus admin “Refresh now” and boot-seed if empty. |

---

## 1. Why this exists

Today the app only exposes six studio aliases (`priya`/`anjali`/`neha`/`ravi`/`arjun`/`kabir`) mapped to **four** real Azure ShortNames (`Neerja`, `Aashi`, `Prabhat`, `Kunal`). Live calls log `tts_voice=en-IN-NeerjaNeural` and feel like a generic “bot lady.”

Azure already returns **769** voices for this region (from `azure_tts_voices.json`):

| Slice | Count (this dump) |
|---|---|
| Total | 769 |
| `VoiceType=Neural` | 580 |
| `VoiceType=NeuralHD` | 189 |
| Status GA / Preview / Deprecated | 614 / 154 / 1 |
| `en-IN` | 20 (≈14 standard Neural + HD variants) |
| `hi-IN` | 17 |
| All `*-IN` | 59 |

Users need to **pick any voice**, see **price / language / gender / styles**, **preview** it, and have the catalog **auto-update** when Microsoft adds/removes/renames voices — without editing seed SQL by hand.

---

## 2. Current state (grounded)

| Asset | Role today | Gap |
|---|---|---|
| `tts_voices` table | 6 static rows with `config.azureVoiceName` | Not a catalog; no sync; duplicates map to same Azure voice |
| `GET /tts-voices` | Lists those 6 | No filters, no price tier, no Azure metadata |
| `POST /tts/preview` | Preview by studio `voiceId` | Must accept Azure `ShortName` directly |
| `VoicePanel.tsx` | Radio-ish list + prosody sliders | No search/filters/hover details/premium toggle |
| `AgentTuning.tts.voice` / presets | Defaults `en-IN-NeerjaNeural` | Change default to Aarti; picker must write ShortName |
| `azure_speech.resolve_azure_voice_name` | Maps studio id → Azure name via env/DB | Keep as legacy bridge; catalog ShortName becomes authoritative |
| `voice/bot.py` | Uses `tuning["tts"]["voice"]` | Already ShortName-capable once defaults/UI write Aarti |
| Worker / cron | Usage metering exists | Need daily TTS catalog sync task |

**Source of truth for inventory:** Azure Speech  
`GET https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/voices/list`  
Header: `Ocp-Apim-Subscription-Key: {AZURE_SPEECH_KEY}`

Offline/dev bootstrap: import `azure_tts_voices.json` (UTF-8 BOM).

---

## 3. Architecture

```
┌─────────────────────┐     daily / admin / boot      ┌──────────────────────────┐
│ Azure voices/list   │ ───────────────────────────► │ tts_voice_catalog (DB)   │
│ (region-specific)   │   upsert + soft-remove         │ + tts_voice_sync_runs    │
└─────────────────────┘                                │ + tts_price_tiers        │
                                                       └────────────┬─────────────┘
                                                                    │
                    GET /tts-voices/catalog?filters                 │
                                                                    ▼
┌─────────────────────┐     select ShortName          ┌──────────────────────────┐
│ Voice picker UI     │ ───────────────────────────► │ voiceConfig / tuning.tts │
│ (Prompt Studio +    │     preview by ShortName       │ → bot_deployments       │
│  Sandbox Tuning)    │                                │ → voice/bot AzureTTS    │
└─────────────────────┘                                └──────────────────────────┘
```

**Two layers (do not collapse):**

1. **Catalog** — synced inventory + derived price tier (read-mostly).  
2. **Selection** — what a deployment/prompt version uses (`tuning.tts.voice` = Azure ShortName).

Never call Azure `voices/list` on every UI paint. Sync into Postgres; serve from DB.

---

## 4. Data model

### 4.1 `tts_voice_catalog`

One row per Azure `ShortName`.

| Column | Type | Notes |
|---|---|---|
| `short_name` | `text` PK | e.g. `en-IN-AartiNeural` |
| `display_name` | `text` | `DisplayName` |
| `local_name` | `text` | `LocalName` |
| `gender` | `text` | Female / Male / Neutral |
| `locale` | `text` | `en-IN` |
| `locale_name` | `text` | `English (India)` |
| `voice_type` | `text` | Neural / NeuralHD |
| `status` | `text` | GA / Preview / Deprecated |
| `sample_rate_hertz` | `int` nullable | |
| `words_per_minute` | `int` nullable | |
| `styles` | `jsonb` | `StyleList` or `[]` |
| `model_series` | `text[]` / jsonb | from `VoiceTag.ModelSeries` |
| `personalities` | `jsonb` | `VoiceTag.VoicePersonalities` |
| `scenarios` | `jsonb` | `VoiceTag.TailoredScenarios` |
| `price_tier` | `text` | **derived** — see §4.3 |
| `is_premium` | `boolean` | true when tier ≠ `standard` |
| `raw` | `jsonb` | full Azure object for hover “Technical” |
| `first_seen_at` | `timestamptz` | |
| `last_seen_at` | `timestamptz` | updated every successful sync |
| `removed_at` | `timestamptz` nullable | soft-delete when missing from Azure |
| `enabled_for_picker` | `boolean` default true | admin kill-switch |

Indexes: `(locale)`, `(price_tier)`, `(gender)`, `(status)`, `(is_premium)`, `(removed_at)`, GIN on `styles` if needed; trigram/ILIKE on `display_name` + `short_name` for search.

### 4.2 `tts_voice_sync_runs`

Audit each sync:

- `id`, `started_at`, `finished_at`, `source` (`azure` | `json_import` | `admin`)
- `fetched_count`, `upserted`, `soft_removed`, `unchanged`
- `error` text nullable
- `region` text

### 4.3 `tts_price_tiers` (config, not magic strings forever)

| `tier` | `label` | `approx_usd_per_1m_chars` | `is_premium` | `notes` |
|---|---|---|---|---|
| `standard` | Standard Neural | 15 | false | Prebuilt Neural (budget) |
| `hd_flash` | Neural HD Flash | 15 | true | Treat as premium in UI (toggle) even if $≈Neural — product choice: Flash/MAI behind toggle |
| `hd` | Neural HD | 22 | true | DragonHD / NeuralHD |
| `turbo` | Turbo / AOAI | null or high | true | Rare; keep behind toggle |

Prices are **approximate display guidance** (Azure list price moves). UI shows badge + “~$X / 1M chars · verify on Azure Pricing”. Admin can edit the config table without code deploy.

### 4.4 Price-tier derivation rules

Applied on every upsert from Azure payload / ShortName:

```
if ShortName contains "DragonHD" or ":Dragon"           → hd
elif VoiceType == "NeuralHD"                            → hd
elif ShortName contains "HDFlash" or ends with "Flash"
     or contains "MAI-Voice"                            → hd_flash   # premium toggle
elif ShortName contains "Turbo"                         → turbo
else                                                    → standard
```

`is_premium = (price_tier != 'standard')`.

### 4.5 Legacy `tts_voices`

Keep the table for FK compatibility (`bot_deployments.tts_voice_id`) during transition:

- Either migrate FKs to `short_name`, **or**
- Keep thin alias rows that point `config.azureVoiceName` → catalog ShortName and stop using them as the picker source.

**Preferred end state:** selection stores **Azure ShortName** in `tuning.tts.voice` (and optionally `voice_config.azureVoiceName`). Studio ids `priya` become optional display aliases only.

### 4.6 Default voice migration

| Location | Old | New |
|---|---|---|
| `agent_core/tuning.py` presets / `normalize_tuning` | `en-IN-NeerjaNeural` | `en-IN-AartiNeural` |
| `AZURE_SPEECH_TTS_VOICE_DEFAULT` in `.env.example` | Neerja | Aarti |
| Alembic seed / deployment tuning backfill | Neerja where still default | Aarti **only when** still equal to old default (don’t clobber custom picks) |
| Frontend `agent-tuning.ts` seed | Neerja | Aarti |

---

## 5. Sync job

### 5.1 Implementation

- Module: `backend/tts_catalog_sync.py`
- CLI: `python -m scripts.sync_tts_voices [--from-json PATH] [--force]`
- Daily: schedule inside existing `backend/worker.py` (or APScheduler sibling) at a fixed UTC time (e.g. 02:30 UTC)
- Admin: `POST /tts-voices/catalog/sync` (authz: admin)

### 5.2 Algorithm

1. Insert `tts_voice_sync_runs` (started).
2. Fetch Azure list **or** load JSON (`utf-8-sig`).
3. For each voice: derive `price_tier` / `is_premium`; upsert by `short_name`; set `last_seen_at=now()`.
4. Soft-remove: any row with `removed_at IS NULL` and `short_name` not in fetch → set `removed_at=now()`.
5. Do **not** hard-delete (deployments may still reference).
6. Finish run row with counts; log errors without crashing the worker loop.

### 5.3 Boot behavior

On API startup (or first catalog list): if `tts_voice_catalog` is empty → run sync once (Azure if creds present, else import bundled/dev JSON if configured).

### 5.4 Stale selection guard

When loading a deployment/prompt:

- If selected `short_name` is missing / `removed_at` set / `status=Deprecated` → warn in API response (`voiceWarning`) and fall back to `en-IN-AartiNeural` for runtime (persist warning; don’t silently rewrite DB unless admin confirms).

---

## 6. API

### 6.1 `GET /tts-voices/catalog`

Query params:

- `q` — search display/local/short name
- `locale` — exact or prefix (`en-IN`, `hi-`, …)
- `gender`
- `status` — default `GA` (allow `Preview` via filter)
- `price_tier` / `is_premium`
- `include_premium` — default `false` (honors product decision #3)
- `include_removed` — default `false`
- `limit` / `cursor` — pagination (full catalog is 769+; don’t dump unpaged in UI)

Response item (picker DTO):

```json
{
  "shortName": "en-IN-AartiNeural",
  "displayName": "Aarti",
  "localName": "Aarti",
  "gender": "Female",
  "locale": "en-IN",
  "localeName": "English (India)",
  "voiceType": "Neural",
  "status": "GA",
  "priceTier": "standard",
  "isPremium": false,
  "approxUsdPer1MChars": 15,
  "styles": [],
  "personalities": [],
  "scenarios": [],
  "wordsPerMinute": null,
  "sampleRateHertz": 48000,
  "modelSeries": ["Monolingual"]
}
```

Envelope:

```json
{
  "items": [...],
  "total": 120,
  "lastSyncedAt": "2026-07-24T02:30:00Z",
  "defaultVoice": "en-IN-AartiNeural",
  "premiumHiddenByDefault": true
}
```

### 6.2 `GET /tts-voices/catalog/{shortName}`

Full DTO + `raw` (for hover Technical section).

### 6.3 `POST /tts-voices/catalog/sync`

Admin trigger; returns latest sync run summary.

### 6.4 `GET /tts-voices/pricing`

List tier config for badges.

### 6.5 `POST /tts/preview` (extend)

Accept either:

- legacy `voiceId` (priya/…), or
- `shortName` / `azureVoiceName`

Preview synthesizes with that ShortName + existing speed/pitch/warmth/style mapping when `StyleList` supports it.

### 6.6 Deprecate as picker source

`GET /tts-voices` may remain for backward compatibility but UI switches to `/catalog`.

---

## 7. UI / UX

### 7.1 Surfaces

1. **Prompt Studio → Voice tab** (`VoicePanel.tsx`) — primary.  
2. **Sandbox Agent Tuning Studio** — same catalog control bound to `tuning.tts.voice` (live delta already supports TTS updates).

### 7.2 Layout

**Toolbar**

- Search
- Locale filter (All · English (India) · Hindi · Other Indic · … grouped from catalog — **not** a hard allowlist; “All” shows everything)
- Gender
- Status (GA default)
- **Show premium voices** toggle (off by default)
- Catalog freshness: “Synced 3h ago” + Refresh (admin)

**Voice results**

- Virtualized grid/list (769 is fine with virtualization + server filters)
- Card: DisplayName · gender · locale badge · price badge (`Standard` / `HD · ~$22/1M`) · styles chip if any
- Selected state ring
- Inline ▶ preview (per-card, independent of main sample strip)

**Hover / detail popover (ⓘ or card hover)**

- Voice name (Display + Local)
- ShortName (copyable)
- Language / LocaleName
- Gender, Status, VoiceType, Model series
- Cost: tier label + approx $/1M + premium flag
- Styles, personalities, scenarios
- WPM, sample rate
- ▶ Play fixed demo line in **that** voice
- “Use this voice”
- Collapsible **Technical**: pretty-printed subset of `raw`

**Selected strip (sticky)**

- Current ShortName + display name
- Prosody: speed / pitch / warmth (and **style dropdown** only when catalog `styles` non-empty)
- Sample text + main Play (existing debounce behavior)
- Warning banner if voice stale/removed

### 7.3 Accessibility / performance

- Keyboard selectable list
- Don’t autoplay on hover (click ▶ only)
- Cache preview blobs by `(shortName, speed, pitch, warmth, style, textHash)` (existing TTS cache dir can key on ShortName)

### 7.4 What not to do

- Do not render 769 unfiltered cards on first paint — default query: `status=GA&include_premium=false` (still all locales, but GA + standard).
- Do not put Azure pricing as contractual — label as approximate.

---

## 8. Runtime wiring

1. Publish / save prompt → fold selected ShortName into `tuning.tts.voice` (and `voiceConfig` for Studio).  
2. `resolve_session_tuning` already prefers `tts.voice` — ensure overlay doesn’t clobber with Neerja.  
3. `KeepAliveAzureTTSService` / Pipecat Azure TTS settings use ShortName as `voice`.  
4. Style: if voice has `empathetic` (e.g. Neerja), keep warmth→style mapping; if not (Aarti), skip express-as / use neutral SSML.  
5. Live tuning: allow `tts.voice` in `tuning_delta` mid-call via existing `TTSUpdateSettingsFrame` path.

---

## 9. Phased delivery

### Phase A — Catalog foundation
- Alembic: `tts_voice_catalog`, `tts_voice_sync_runs`, `tts_price_tiers`
- Sync module + JSON import of `azure_tts_voices.json`
- `GET /tts-voices/catalog` (+ detail + pricing)
- Unit tests: tier derivation, soft-remove, Aarti default normalize

### Phase B — Picker UI
- Rebuild `VoicePanel` against catalog API
- Premium toggle, filters, hover details, per-voice preview
- Extend `/tts/preview` for ShortName

### Phase C — Defaults + publish path
- Default → `en-IN-AartiNeural` everywhere (env, tuning normalize, FE seed)
- Publish writes ShortName into deployment tuning
- Voice bot smoke: log shows `tts_voice=en-IN-AartiNeural`

### Phase D — Daily job + ops
- Schedule daily sync in worker
- Admin Refresh endpoint + UI control
- Stale-voice warning in Studio + runtime fallback
- Sync run history (simple admin strip)

### Phase E — Polish (optional)
- Virtualized grid if needed
- Locale groupings / favorites / recently used
- Per-tenant allowlist (not required by current decisions)
- Migrate away from legacy `tts_voices` FK entirely

---

## 10. Acceptance criteria

- [ ] Catalog populated from Azure or JSON (≥700 rows for this region).  
- [ ] Daily job runs and updates `last_seen_at` / soft-removes vanished voices.  
- [ ] Admin can force refresh; UI shows `lastSyncedAt`.  
- [ ] Picker can show **all locales**; default filter is GA + non-premium.  
- [ ] Premium voices only visible when toggle is on.  
- [ ] Hover/detail shows language, cost tier, ShortName, styles, ▶ demo.  
- [ ] Selecting a voice + publish → next Live call uses that ShortName.  
- [ ] New sessions default to **`en-IN-AartiNeural`** when no override.  
- [ ] Preview works for arbitrary catalog ShortName without studio alias.  
- [ ] Removed/deprecated selection warns and falls back safely.

---

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Azure pricing page changes | Tier table is config; UI says “approx” |
| HD Flash priced like Neural but product wants it gated | `is_premium=true` for Flash/MAI regardless of $ |
| Sync fails (key/region) | Keep last good catalog; surface error on sync run; boot doesn’t wipe |
| Mid-call voice change glitches | Apply on next TTS utterance; document in Tuning Studio |
| SSML styles unsupported on Aarti | Capability from catalog `styles`; don’t send express-as blindly |
| 769-row UI jank | Server filters + pagination/virtualization |

---

## 12. Out of scope (this plan)

- Custom Neural Voice / Personal Voice training  
- Buying commitment tiers / billing meter changes beyond display  
- Non-Azure TTS providers (ElevenLabs, Cartesia) — future adapter if needed  
- Changing STT language automatically when TTS locale changes (nice follow-up; not blocking)

---

## 13. Implementation order (when building)

1. Write this plan ✅  
2. Phase A (schema + sync + catalog API)  
3. Phase B (VoicePanel)  
4. Phase C (Aarti default + bot wiring)  
5. Phase D (daily job + admin refresh)  
6. Live smoke call confirming Aarti + alternate locale voice

---

## 14. References

- Dump: `azure_tts_voices.json` (UTF-8 BOM, 769 voices)  
- Azure list API: `{region}.tts.speech.microsoft.com/cognitiveservices/voices/list`  
- Existing code: `backend/azure_speech.py`, `Habibi/src/components/prompt-studio/VoicePanel.tsx`, `backend/agent_core/tuning.py`, `backend/voice/bot.py`  
- Related plans: `PROMPT_STUDIO_plan.md`, `VOICE_AGENT_plan.md` §4.7 AgentTuning  
