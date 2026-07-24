# Call Simulation Sandbox — Architecture & Build Plan

> **Status:** proposed · **Date:** 2026-07-23 (rev. 2026-07-23 — Agent Tuning Studio)  
> **Screen:** Habibi `/sandbox`  
> **Goal:** Make Sandbox a real pre-prod rehearsal lab — text RAG harness, duplex voice via **native Pipecat runtime**, **and a live "AI-Studio" tuning console** over every Pipecat knob — all in **BigBound AI UI only** (no stock Pipecat playground chrome).  
> **Docs grounding:** Pipecat official docs via Context7 MCP (`/pipecat-ai/docs`, `/websites/pipecat_ai`, `/pipecat-ai/pipecat`) · verified 2026-07-23. All service/turn-management claims below are **Pipecat 1.0+** (post-migration API — see §4.4); legacy `PipelineParams.allow_interruptions` / `interruption_strategies` symbols are explicitly avoided.  
> **Related:** `PROMPT_STUDIO_plan.md`, `VOICE_AGENT_plan.md`, `whatsapp_reply_bot_plan.md`, `KB_plan.md`

---

## 1. What this page is for (product truth)

**Call Simulation Sandbox** is the **safe rehearsal room** before a prompt / KB / voice config touches real customers.

| Actor | Uses Sandbox to… |
|---|---|
| Prompt author | Prove a draft sounds/behaves right before Promote |
| Compliance / QA | Replay hard scenarios (waiver, hardship, dispute) and inspect retrieval + guardrails |
| Demo | Golden-path live call without telephony carriers |

It is **not** Floor (live ops), not Customer 360, not the production Twilio dialer. It is the **pre-prod channel adapter** over the same bot brain.

---

## 2. Locked decisions

| # | Question | Decision |
|---|---|---|
| 1 | Pipecat “playground” | **Bring the native Pipecat *runtime*** (dev runner contract + SmallWebRTC + RTVI client SDK). **Do not** iframe / ship Pipecat’s stock client UI or Voice UI Kit chrome. |
| 2 | Our UI | **100% Habibi / BigBound** — existing shell, ScenarioList, PersonaCard, ConversationPanel, Inspector, Promote. Voice mode is a **panel mode**, not a second app. |
| 3 | Dual modes | Keep both: **Text** (cheap Azure chat + retrieve) and **Live voice** (Pipecat duplex). Same scenario / prompt / KB selectors. |
| 4 | Client SDK | `@pipecat-ai/client-js` + `@pipecat-ai/client-react` + `@pipecat-ai/small-webrtc-transport` as **invisible plumbing** under our components. |
| 5 | Local transport | **SmallWebRTC** first (no Daily account). Matches docs: `client.connect({ webrtcUrl: "…/api/offer" })`. Daily/Twilio later for prod telephony. |
| 6 | Bot process | Reuse existing `backend/voice/bot.py` (already Pipecat Flows + Azure STT/TTS + CRM sink). Sandbox starts sessions against a **sandbox-env** deployment / explicit `promptVersionId`, not silent prod. |
| 7 | TTS on text mode | Even without WebRTC: every bot bubble can **Play** via existing `POST /tts/preview` using the selected prompt’s voice config. |
| 8 | KB snapshot | Dropdown must **actually filter** retrieve (today it is cosmetic). Promote must pin snap on deployment. |
| 9 | Promote | = publish **deployment bundle** (prompt + KB snap + **`AgentTuning`** + TTS voice + env), not prompt-only. The knobs you tuned in Sandbox are pinned into what ships. |
| 10 | Azure-only speech | Unchanged — Azure Speech STT/TTS, Azure OpenAI chat. No ElevenLabs / Deepgram. |
| 11 | Tuning surface | Ship a live **Agent Tuning Studio** (§4.4) over every Pipecat runtime knob, applied mid-call via `LLMUpdateSettingsFrame` / `TTSUpdateSettingsFrame`. One `AgentTuning` struct is the single source for all three brains. |
| 12 | Pipecat API version | Ground on **Pipecat 1.0+** turn-management (`user_turn_strategies` / `user_mute_strategies` / `user_idle_timeout`). Do **not** build against deprecated `PipelineParams.allow_interruptions`. |

### Why not embed Pipecat’s playground UI

From Pipecat docs (`running-bots-locally`):

- `uv run bot.py` / `pipecat.runner.run` starts a local server (default `localhost:7860`) and **serves a prebuilt client UI** at `GET /`.
- That UI is a **dev convenience**, not a product surface.
- The portable contract is the **session API** (`POST /start`, `/sessions/{id}/…`, WebRTC `/api/offer`) that mimics Pipecat Cloud — so a **custom client** built against the runner works unchanged when we graduate transports.

From client docs (`building-a-voice-ui`, `pipecat-client-web`):

- Recommended pattern is **our React tree** + `PipecatClientProvider` + `PipecatClientAudio` + hooks (`usePipecatClient`, `usePipecatConversation`, `useRTVIClientEvent`).
- Transcripts arrive as RTVI events (`UserTranscript`, `BotOutput`) — we map those into our existing `SandboxTurn[]` / inspector.

**Therefore:** native Pipecat **yes**; stock playground skin **no**.

---

## 3. Current state (grounded)

### 3.1 What already works

| Piece | Where | Notes |
|---|---|---|
| Text turn loop | `sandbox_runtime.py` | Retrieve → Azure chat → persist `sandbox_runs` / turns |
| Scenarios | `GET /sandbox/scenarios` | Seeded personas + scripted customer lines |
| Studio deep-link | `?promptVersionId=` | Prompt Studio “Test in Sandbox” |
| Hold-to-talk STT | `ConversationPanel` → `POST /stt/transcribe` | Customer → text only |
| Inspector | Retrieval / Intent / Sentiment / Trace | Mostly live on bot turns |
| Promote dialog | → `publishPromptVersion` | Prompt publish only |
| **Voice bot (Pipecat)** | `backend/voice/bot.py` | Flows, Smart Turn, Azure STT/TTS, CRM sink; `transport="smallwebrtc"` |
| Studio TTS preview | `POST /tts/preview` | Unused by Sandbox today |

### 3.2 Critical gaps (why the page feels fake)

1. **No bot voice in Sandbox** — cannot hear how the agent sounds.  
2. **“Call Simulation” ≠ duplex call** — chat + optional mic; Pipecat bot is a **separate process/UI**.  
3. **KB snapshot is a lie** — `kb_retrieve` ignores `kbSnapshotId`.  
4. **No tools / routing** in text path — escalate/PTP/dispute only exist on voice Flows path.  
5. **Promote incomplete** — doesn’t pin KB + voice into the deployment bundle UX.  
6. **No scorecard** — scenario `expectedIntent` never compared to classifier output.  
7. **No run history UI** — `GET /sandbox/runs/{id}` unused.  
8. **Hard ceiling** — `SANDBOX_HARD_MAX_TURNS` default 3 (text cost control; voice needs its own budget).  
9. **Opening line** is template fill, not model-spoken.  
10. **Cross-page links** weak (KB deep-link, Routing, C360, Inbox).  
11. **No tuning surface — the biggest miss.** Pipecat exposes ~30 runtime-tunable knobs (LLM temperature/top-p/penalties, TTS style/rate/pitch, VAD sensitivity, Smart-Turn timing, barge-in policy, mute strategies, idle ladder). Today none are adjustable from the product — they are hard-coded in `bot.py`. A rehearsal lab that cannot **change how the agent sounds and decides, and hear the result immediately**, is a transcript viewer, not a studio. §4.4 fixes this.

### 3.3 Infra reality

- Habibi Vite app and FastAPI backend are separate origins → WebRTC offer URL needs **proxy or CORS + explicit endpoint**.  
- `python -m voice.bot` already uses Pipecat’s **development runner** (`pipecat.runner.run.main`) — that *is* the native playground server; we keep the process, replace the browser UI with Habibi.  
- `requirements.txt` at repo root may lag installed venv packages; voice code already imports `pipecat.*` — plan assumes Pipecat is present in the voice venv used to run `voice.bot`.

---

## 4. Target architecture

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Habibi /sandbox  (OUR UI ONLY)                                           │
│  Header: Prompt · KB snap · Scenario · Mode[Text|Live voice] · Promote   │
│  Left: ScenarioList                                                      │
│  Center: PersonaCard + ConversationPanel (bubbles + call chrome)         │
│  Right: Inspector (retrieval · intent · sentiment · trace · routing)     │
└───────────────┬─────────────────────────────┬────────────────────────────┘
                │ Text mode                    │ Live voice mode
                │ POST /sandbox/runs…          │ PipecatClient + SmallWebRTC
                ▼                              ▼
┌──────────────────────────┐    ┌──────────────────────────────────────────┐
│ sandbox_runtime          │    │ Voice session gateway                    │
│  agent_core + retrieve   │    │  POST /voice/sandbox/start               │
│  (snap-aware)            │    │    → ensure bot worker / return offer URL│
│  optional TTS play       │    │  WebRTC /api/offer (runner or mounted)   │
└──────────────────────────┘    │  voice.bot run_bot(transport)            │
                                │    load bundle (sandbox / explicit PV)   │
                                │    scenario context inject               │
                                │    Flows + tools + CrmSink               │
                                │    RTVI transcripts → FE + sandbox_runs  │
                                └──────────────────────────────────────────┘
```

### 4.1 Mode A — Text (keep, harden)

- Existing create/append turn APIs.  
- Fix snapshot filter; server-authoritative history.  
- **Hear bot:** after each bot text, optional auto-play or ▶ via `/tts/preview` with prompt voice params.  
- Scorecard: expected vs actual intent/sentiment; remaining turns meter.

### 4.2 Mode B — Live voice (native Pipecat, our chrome)

**Server**

1. `POST /voice/sandbox/start` body:  
   `{ promptVersionId?, kbSnapshotId?, scenarioId?, persona?, runId? }`  
   Returns: `{ sessionId, webrtcUrl, sandboxRunId }`  
2. Gateway either:  
   - **A (v1):** documents that `python -m voice.bot` must be running; returns `http://127.0.0.1:7860/api/offer` (dev), or  
   - **B (preferred):** mount SmallWebRTC offer routes on FastAPI / spawn worker per session (closer to Pipecat Cloud `POST /start` contract).  
3. `voice.bot` must accept **session config** (not only `load_active_bundle("production")`) so Sandbox can test a **draft** prompt without publishing.

**Client (Habibi)**

```tsx
// Plumbing only — never render Pipecat Voice UI Kit chrome
<PipecatClientProvider client={client}>
  <PipecatClientAudio />          {/* audio element, invisible */}
  <OurCallChrome />               {/* BigBound buttons, meters, bubbles */}
</PipecatClientProvider>
```

Connect pattern (from docs):

```ts
import { PipecatClient } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";

const client = new PipecatClient({
  transport: new SmallWebRTCTransport(),
  enableMic: true,
});
await client.connect({ webrtcUrl }); // from /voice/sandbox/start
```

Map events → our turns:

| RTVI event | Our UI |
|---|---|
| `UserTranscript` (final) | customer bubble + intent/sentiment refresh |
| `BotOutput` / conversation messages | bot bubble (+ latency when metrics available) |
| `BotReady` / transport state | call status pill (Connecting / Live / Ended) |
| `Error` | toast + fail the run |

**Call chrome (ours):** Start call · Mute · End · waveform/level · elapsed timer · “Hearing: {Azure voice name}”. Reuse PersonaCard + Inspector; feed live turns into the same inspector tabs.

### 4.3 What we explicitly will NOT do

- Iframe `http://localhost:7860/` playground.  
- Adopt Pipecat Voice UI Kit layouts/colors as the page shell.  
- Force Daily/Twilio for the first voice-in-Sandbox milestone.  
- Delete the text harness (still best for cheap prompt iteration).

---

### 4.4 Agent Tuning Studio — the AI-Studio surface (centerpiece)

This is what turns Sandbox from a rehearsal transcript into a **console**. It borrows the Google-AI-Studio / OpenAI-Playground pattern: **one panel of typed controls, a value for every knob, and — the part that makes it a studio — the change is applied and audible without restarting the call.**

#### 4.4.1 The `AgentTuning` object — one struct, three consumers

Every knob lives in a single serialisable object. It is the contract the Studio edits, the DB persists (per prompt version / deployment), and all three brains (`sandbox_runtime` text, `voice/bot.py`, WhatsApp) read. **A knob that is not in `AgentTuning` does not exist in the product.**

```jsonc
// AgentTuning — persisted on prompt_versions / bot_deployments; default-filled from a preset
{
  "llm": {                    // → AzureLLMService.Settings(...) + LLMUpdateSettingsFrame(delta=…)
    "temperature": 0.4,       // 0–2  focus ↔ creativity  (biggest "personality" dial)
    "top_p": 0.9,             // 0–1  nucleus sampling
    "frequency_penalty": 0.3, // -2–2 discourage repetition (kills the "as I said…" loops)
    "presence_penalty": 0.0,  // -2–2 push new topics
    "max_completion_tokens": 220, // hard cap → shorter spoken turns = lower TTS latency
    "seed": null              // set for reproducible A/B in evals
  },
  "tts": {                    // → AzureTTSService.Settings(...) + TTSUpdateSettingsFrame(delta=…)
    "voice": "en-IN-NeerjaNeural",
    "style": "empathetic",    // Azure express-as; floor is empathetic, never neutral
    "style_degree": "1.4",    // 0.01–2  how audible the emotion is over a phone codec
    "rate": "1.05",           // speaking rate
    "pitch": "+2%",           // prosody pitch
    "volume": "default",
    "emphasis": null,
    "text_aggregation_mode": "SENTENCE" // SENTENCE = natural · TOKEN = lowest latency
  },
  "stt": {                    // → AzureSTTService.Settings(...)
    "language": "en-IN",
    "profanity": "raw"        // raw|masked|removed — "raw" avoids over-masking Indian-English
  },
  "vad": {                    // → VADParams(...)  (Silero)
    "confidence": 0.7,
    "start_secs": 0.15,       // lower = snappier barge-in onset
    "stop_secs": 0.2,         // keep 0.2 when Smart Turn is on (docs)
    "min_volume": 0.6
  },
  "turn": {                   // → SmartTurnParams(...) on LocalSmartTurnAnalyzerV3
    "stop_secs": 3.0,         // silence fallback before force-completing a turn
    "pre_speech_ms": 0,
    "max_duration_secs": 8.0
  },
  "interaction": {            // → UserTurnStrategies (Pipecat 1.0, see §4.4.3)
    "barge_in": "on",         // on | min_words | locked
    "min_words": 3,           // used only when barge_in = "min_words"
    "mute": ["until_first_bot_complete", "during_function_calls"],
    "idle_timeout_secs": 6.0, // 0 disables; drives the silence ladder
    "idle_ladder": ["nudge", "direct", "close"]
  }
}
```

Design rule: the Studio never invents a knob the runtime can't honour, and the runtime never reads a knob the Studio can't show. This 1:1 mapping is what keeps "what you tuned" == "what ships."

#### 4.4.2 Live apply — why it's a *studio*, not a form

The docs give us two frames that mutate a **running** service in place:

- `LLMUpdateSettingsFrame(delta=AzureLLMSettings(temperature=…, max_completion_tokens=…))`
- `TTSUpdateSettingsFrame(delta=AzureTTSService.Settings(style=…, rate=…, voice=…))`

> Grounding: *"Model settings can be changed mid-conversation using `LLMUpdateSettingsFrame`"* and *"Dynamically change TTS voice settings during a conversation using `TTSUpdateSettingsFrame`"* — Context7 `/pipecat-ai/docs`, LLM & TTS service refs, 2026-07-23. (Note: changing TTS **voice/language** reconnects the WebSocket with new params; style/rate/pitch apply on the next utterance without a reconnect.)

So in **Live voice** mode, dragging the temperature slider or switching the TTS style sends a settings frame to the worker mid-call; the caller hears the new delivery on the **very next bot turn**. That immediate feedback loop is the entire point.

- **VAD / Smart-Turn / interruption / mute / idle** knobs are **not** hot-swappable mid-pipeline (they're wired into aggregator construction). The Studio marks these **"applies on next call"** and offers a one-click **Restart call with these settings** (re-`/voice/sandbox/start` with the edited `AgentTuning`) — no page reload.
- **Text mode** has no live frames; it re-reads `AgentTuning` on each turn, so LLM knobs take effect on the next message and TTS knobs on the next ▶ playback.

Transport: reuse the RTVI client message channel (`client.sendMessage`) → a small `on_app_message` handler on the worker that maps the delta to the right `*UpdateSettingsFrame`. No new socket.

#### 4.4.3 Mapping each knob to the **Pipecat 1.0** API (grounded)

| Studio control | Runtime target | Live? | Source (Context7, 2026-07-23) |
|---|---|---|---|
| LLM temp / top_p / penalties / max tokens / seed | `AzureLLMService.Settings` ← `LLMUpdateSettingsFrame` | ✅ mid-call | `/services/llm/openai`, `/services/llm/azure` |
| TTS style / style_degree / rate / pitch / volume / emphasis | `AzureTTSService.Settings` ← `TTSUpdateSettingsFrame` | ✅ next utterance | `/services/tts/azure` |
| TTS voice / language | same, but **reconnects WS** | ✅ (brief reconnect) | `/services/tts/azure` |
| `text_aggregation_mode` SENTENCE↔TOKEN | `AzureTTSService(text_aggregation_mode=…)` | next call | `/services/tts/azure` |
| STT language / profanity | `AzureSTTService.Settings` | next call | `/services/stt/azure` |
| VAD confidence/start/stop/min_volume | `VADParams` on `SileroVADAnalyzer` | next call | `/utilities/audio/silero-vad-analyzer` |
| Smart-Turn stop/pre_speech/max_duration | `SmartTurnParams` on `LocalSmartTurnAnalyzerV3` | next call | `/utilities/turn-detection/smart-turn-overview` |
| Barge-in **on** | default (`TurnAnalyzerUserTurnStopStrategy` + smart turn) | next call | `/fundamentals/interruptions` |
| Barge-in **min_words** | `MinWordsUserTurnStartStrategy(min_words=N)` + `SpeechTimeoutUserTurnStopStrategy()` | next call | `/utilities/turn-management/user-turn-strategies` |
| Barge-in **locked** | `VADUserTurnStartStrategy(enable_interruptions=False)` | next call | `/fundamentals/interruptions` |
| Mute until greeting done | `MuteUntilFirstBotCompleteUserMuteStrategy()` | next call | `/utilities/turn-management/user-mute-strategies` |
| Mute during tool calls | `FunctionCallUserMuteStrategy()` | next call | `/utilities/turn-management/user-mute-strategies` |
| Idle timeout + ladder | `LLMUserAggregatorParams(user_idle_timeout=…)` + `on_user_turn_idle` | next call | `/fundamentals/detecting-user-idle` |

All of the interaction-row controls live on **`LLMUserAggregatorParams`** (`user_turn_strategies`, `user_mute_strategies`, `user_idle_timeout`) — the Pipecat-1.0 home for what used to be `PipelineParams.allow_interruptions` / `UserIdleProcessor` / `STTMuteFilter`. Building against the new names now avoids a rewrite later.

#### 4.4.4 Presets, diff, and guardrails

- **Presets** ship as named `AgentTuning` blobs: *Empathetic-collections* (default), *Brisk-verification*, *Firm-legal*, *Low-latency-demo* (TOKEN aggregation, temp 0.3, max_tokens 140). One click loads; sliders then fine-tune.
- **A/B diff:** two `AgentTuning` blobs run the **same** seeded scenario; Inspector shows a side-by-side of transcript + measured TTFB/TTFA (from Pipecat metrics, §Metrics) so "warmer but +180 ms" is a visible trade, not a hunch.
- **Bounded knobs:** the Studio clamps to doc-legal ranges (temp 0–2, style_degree 0.01–2, VAD stop_secs ≥ 0.2 when Smart Turn is on) and **never** exposes anything that would break Flows (e.g. it cannot switch the LLM to a speech-to-speech model — Flows requires cascaded text, per `voice_agent_plan.md` §3.1-B).

---

## 5. Infra plan

| Concern | Plan |
|---|---|
| Process model (dev) | Habibi (Vite) + FastAPI + **voice worker** (`python -m voice.bot`) |
| Process model (later) | FastAPI dispatches session → worker pool; same client contract |
| CORS / proxy | Vite proxy `/voice-rtc` → runner `7860`, or runner CORS allow Habibi origin |
| ICE / localhost | SmallWebRTC fine on same machine; document firewall for remote demos |
| Secrets | Existing `AZURE_*` only; no Daily key for v1 |
| Cost | Text: turn ceiling; Voice: max session seconds + idle hangup |
| Recording | Reuse `voice/recording.py` / `interaction_media`; tag `source=sandbox` |
| Persistence | Voice sessions write `interactions` **and** link/update `sandbox_runs` for Promote evidence |
| Health | Sandbox header badges: LLM / STT / TTS / Voice worker (from Integrations health or lightweight `/voice/status`) |

### Env / ops checklist

```bash
# Terminal A — API
uvicorn main:app --reload --port 8000

# Terminal B — Pipecat runner (native playground server, no stock UI used)
python -m voice.bot
# exposes SmallWebRTC offer (docs default :7860)

# Terminal C — Habibi
npm run dev
```

Habibi Live voice mode calls our gateway → connects WebRTC to runner → **never opens runner’s HTML UI**.

---

## 6. Cross-page wiring

| Page | Wire |
|---|---|
| **Prompt Studio** | Keep `Test in Sandbox`; add “Open Live voice” (same `promptVersionId`). Back link + voice/persona summary chip on Sandbox header. |
| **Knowledge Base** | Snapshot select filters retrieve; retrieval chips deep-link `?doc=` / chunk. |
| **Routing** | Inspector “Routing” tab: which rule *would* fire; link to rule id. |
| **Customer 360** | Optional bind scenario → real `customerId` for CRM-true context in Live mode. |
| **Inbox / Handoff** | Escalation tool → sandbox-tagged conversation / handoff preview. |
| **Disputes / PTP / Callbacks** | Tool dry-run or `source=sandbox` writes with clear banner. |
| **Audit / Bot Analytics** | Sandbox runs + voice interactions appear as pre-prod trials; Promote events audited. |
| **Integrations** | Pipecat card = worker base URL + status (not fake keys). |
| **Floor** | Out of scope for Sandbox; Floor consumes *prod* live sessions only. |

---

## 7. UI / UX (ours)

### Header
- Mode toggle: **Text** | **Live voice**  
- Prompt / KB / Scenario selects (unchanged)  
- **Preset dropdown** (`AgentTuning` presets, §4.4.4) + "modified" dot when sliders diverge from the preset  
- Status: `Idle` · `Connecting` · `Live` · `Ended` · `Text run active`  
- Promote (bundle-aware, **includes tuning**) · Export · Reset  

### Center
- PersonaCard unchanged  
- Text: current ConversationPanel + ▶ TTS on bot bubbles  
- Live: same bubble list fed by RTVI + **Start / Mute / End** call bar (BigBound styling)  

### Left rail — **Tuning Studio** (new; the §4.4 surface)
A collapsible accordion of typed controls grouped as the `AgentTuning` object:
- **Voice & delivery** — TTS style, style_degree, rate, pitch, volume; live-apply badge ✅  
- **Reasoning** — temperature, top_p, penalties, max tokens, seed; live-apply badge ✅  
- **Listening** — VAD sensitivity, Smart-Turn timing, STT language/profanity; "applies next call"  
- **Turn-taking** — barge-in (on / min-words / locked), mute strategies, idle timeout + ladder; "applies next call"  
- Each control shows its doc-legal range; a **Restart call with these settings** button appears whenever a "next-call" knob is dirty during a live call.

### Right inspector
- Existing four tabs + **Routing** (phase C) + **Metrics** (new): per-turn TTFB / TTFA / leading-silence / tokens / TTS chars from Pipecat `MetricsFrame` (`enable_metrics` + `enable_usage_metrics`). This is what makes a tuning change measurable — "warmer but +180 ms" is read here.  
- Live mode: show STT partials faintly; finalize on `final`  

### Clarity copy (one line under title)
> Rehearse the collections bot before production. Text mode spends chat tokens; Live voice is a real duplex call via Pipecat — same prompt and knowledge you selected.

---

## 8. Phased delivery

### SB-0 — Clarity + audible text (fast win)
- Purpose strip + mode labels  
- ▶ TTS on bot turns (`/tts/preview` + prompt voice)  
- Remaining turns meter; expected-vs-actual intent chips  
- No Pipecat client yet  

### SB-1 — Honest config
- Snapshot-scoped `kb_retrieve`  
- Promote = deployment bundle (prompt + KB + TTS)  
- Server-owned turn history  

### SB-2 — Native Pipecat Live voice **in our UI**
- Add FE deps: `client-js`, `client-react`, `small-webrtc-transport`  
- `POST /voice/sandbox/start` + Vite proxy / CORS  
- Wire `voice.bot` to accept sandbox session config (draft promptVersionId + scenario)  
- Map RTVI → `SandboxTurn[]`; call chrome in ConversationPanel  
- **Do not** link users to `:7860` HTML  

### SB-2.5 — Agent Tuning Studio (the AI-Studio surface, §4.4)
- Define `AgentTuning` schema + column on `prompt_versions` / `bot_deployments` (JSONB, default-filled from *Empathetic-collections* preset)  
- `voice/bot.py` reads `AgentTuning` at start → constructs `Settings`, `VADParams`, `SmartTurnParams`, `UserTurnStrategies`, `user_mute_strategies`, `user_idle_timeout` from it  
- Left-rail Tuning accordion (typed, range-clamped controls)  
- **Live apply:** slider/select → `client.sendMessage(delta)` → worker `on_app_message` → `LLMUpdateSettingsFrame` / `TTSUpdateSettingsFrame`  
- **Metrics** inspector tab from `MetricsFrame` (TTFB/TTFA/leading-silence/tokens/chars)  
- Presets + "Restart call with these settings" for next-call knobs  
- Promote writes `AgentTuning` into the bundle  

### SB-3 — Production-shaped behavior
- Shared BotRuntime alignment (tools in text path or document “tools = Live only”)  
- Routing evaluation in inspector  
- Optional C360-backed persona  
- Run history drawer  
- **A/B tuning diff:** two `AgentTuning` blobs, same scenario, side-by-side transcript + metrics  

### SB-4 — Telephony graduation (optional)
- Same Habibi client; switch transport to Daily/Twilio per Pipecat runner flags  
- Still our UI — only transport config changes  

---

## 9. Package / API sketch (SB-2)

### Frontend packages
```json
"@pipecat-ai/client-js": "…",
"@pipecat-ai/client-react": "…",
"@pipecat-ai/small-webrtc-transport": "…"
```

### New / extended endpoints
| Method | Path | Purpose |
|---|---|---|
| `POST` | `/voice/sandbox/start` | Create sandbox voice session **with an `AgentTuning` body**; return `{ sessionId, webrtcUrl, sandboxRunId }` |
| `POST` | `/voice/sandbox/{id}/stop` | Hangup + finalize run |
| `POST` | `/voice/sandbox/{id}/tune` | Push a live `AgentTuning` **delta** into a running call (worker maps to `*UpdateSettingsFrame`); may also travel over the RTVI app-message channel instead |
| `GET` | `/voice/status` | Worker up? accepted transports? |
| `GET` | `/sandbox/tuning/presets` | Named `AgentTuning` presets |
| (existing) | runner `/api/offer` | SmallWebRTC SDP exchange (proxied) |
| (existing) | `/tts/preview`, `/sandbox/runs…` | Text mode + hear-bot |

### Session config into `voice.bot`
Pass via runner start payload / env / DB row keyed by `sessionId`:

```json
{
  "sandboxRunId": "SBX-…",
  "promptVersionId": "v1_4",
  "kbSnapshotId": "snap-…",
  "scenarioId": "angry-waiver",
  "environment": "sandbox",
  "customerContext": { "customer_name": "Rahul Sharma", "overdue_amount": "₹18,450" },
  "tuning": { "llm": { "temperature": 0.4, "max_completion_tokens": 220 },
              "tts": { "style": "empathetic", "style_degree": "1.4", "rate": "1.05" },
              "interaction": { "barge_in": "min_words", "min_words": 3,
                               "mute": ["until_first_bot_complete", "during_function_calls"],
                               "idle_timeout_secs": 6.0 } }
}
```

The worker constructs the pipeline from `tuning` (see §4.4.3). Sending `tuning` alone to `/voice/sandbox/{id}/tune` mid-call live-applies the LLM/TTS subset.

`load_active_bundle` becomes `load_bundle_for_session(...)` — **draft allowed in sandbox env only**.

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Two brains (text sandbox vs voice Flows) diverge | SB-3 unify; until then label Live as “production-shaped” and Text as “prompt/RAG lab” |
| Draft prompt accidentally hits prod voice | Explicit `environment=sandbox`; refuse prod bundle for Sandbox Live without confirm |
| WebRTC flaky on corporate Wi‑Fi | Localhost demo path; fallback Text+TTS always available |
| Cost blowups on Live | Session TTL, idle disconnect, visible timer |
| Stock playground confusion | Never deep-link `:7860` UI; docs say “worker only” |
| Python 3.14 / Pipecat wheel quirks | Pin known-good Pipecat in voice venv; document in README |
| Tuning drift (Sandbox values ≠ prod) | `AgentTuning` is one struct, promoted **in the bundle**; prod reads the same field — no hand-copied constants |
| A knob live-applied that isn't hot-swappable | Studio labels each control ✅ live vs "next call"; VAD/turn/mute/idle only ever take effect via **Restart call**, never a no-op frame |
| TTS voice change stutters the call | Voice/language swap reconnects the WS (docs); Studio warns and debounces; style/rate/pitch stay reconnect-free |

---

## 11. Success criteria

1. A new user understands in **&lt;10 seconds** that Sandbox = rehearse before Promote.  
2. In Text mode they can **hear** the bot in the selected Studio voice.  
3. In Live voice mode they complete a **duplex** scenario call **inside Habibi** — mic in, neural voice out, bubbles + inspector updating — with **zero** Pipecat stock UI.  
4. KB snapshot choice changes retrieval; Promote pins that snap.  
5. Prompt Studio → Sandbox → Promote → live deployment is one coherent loop.  
6. **Live tuning is audible:** in a live call, moving the TTS-style or temperature control changes the **next bot turn** without a restart, and the Metrics tab shows the latency cost of the change.  
7. **Tuning promotes:** the exact `AgentTuning` rehearsed in Sandbox is what the deployed bot runs — no separate re-entry of values in code.  
8. Every tuning control maps to a **real, current (1.0) Pipecat API** — no deprecated symbols, no knob the runtime silently ignores.

---

## 12. Immediate next implementation step

**Approve this plan → implement SB-0 + SB-1**, then **SB-2** (Pipecat client under our ConversationPanel + `/voice/sandbox/start` against existing `voice.bot` runner), then **SB-2.5** (Agent Tuning Studio — the AI-Studio surface, §4.4). SB-2.5 is where Sandbox stops being a viewer and becomes a console.

The single highest-leverage first move inside SB-2.5: **define `AgentTuning` and make `voice/bot.py` construct its entire pipeline from it** (instead of hard-coded constants). Everything else — sliders, live-apply, presets, promote — hangs off that one struct.

No code in this document; implementation starts only after explicit go-ahead.
