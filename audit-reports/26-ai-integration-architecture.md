# 26 — AI / provider integration architecture

**Scope:** `backend/` voice, text, sandbox, embeddings; `Habibi/src` Agent Studio and Integrations. `PRAXIST-main/` excluded.
**Date:** 2026-09-02
**Mode:** Read-only. No application file was modified.
**Method:** six parallel analysts — LLM, STT, TTS, realtime/Pipecat, provider abstraction, prompt/configuration — plus a parent verification pass. The provider-abstraction specialist was stopped before returning; that boundary was covered by the parent pass and the other five. Every finding below was re-derived from source. Claims that failed a second source check were dropped.

Vocabulary is `CONTEXT.md`: Mouth, Agent Card, Skill Pack, Locked Engine, Deployment, Tool Grant, Offer, Gate, Flow, Handoff, Reachability, Mission, Cadence, Outcome.

Companion reports: [04-backend-architecture.md](./04-backend-architecture.md) (monolith shape), [17-state-cache.md](./17-state-cache.md) (`load_active_bundle` has no in-process Deployment cache), [18-security-audit.md](./18-security-audit.md) (envelope, not this surface), [20-config-secrets.md](./20-config-secrets.md) (env keys), [21-dependency-supply-chain.md](./21-dependency-supply-chain.md) (Pipecat / nltk live in the voice image).

This is a coupling and duplication audit, not a vulnerability hunt. “P0” here means **the Studio asserts a fact the runtime does not honour**, or two stacks that claim to be one. Exploitability is out of scope.

---

## Verdict

**Speech binding is a real capability boundary. The language-model path is not.**

STT and TTS on a live call go through `agent_core.providers.factory` and `voice.provider_bind`. An operator can pick Cartesia in Agent Studio, hear the preview, publish it, and the call constructs that Pipecat service — with Azure as a documented fallback when nothing is bound or the bound provider fails to build.

The Mouth’s language model does not take that path. Voice constructs `KeepAliveAzureLLMService` from env (`AZURE_OPENAI_VOICE_*`). WhatsApp and sandbox call `azure_openai.chat_with_tools`. The optional LiteLLM gateway wraps only the text client, defaults off, and is invisible to the voice process. The Bindings tab still offers an **LLM** slot. The seed has **zero** `kind="llm"` models. Binding LLM is decorative.

What is already disciplined:

- One Deployment loader (`agent_core.deployment.load_active_bundle`) for sandbox, WhatsApp, and voice.
- One authored prompt store (`prompt_versions`), rendered through `prompt_render` so CRM tokens cannot land in the system role.
- One serialisable knob object (`AgentTuning`) that *intends* to own temperature, voice, STT language, VAD, barge-in.
- A capability matrix (`provider_models`) whose `service_class` paths were read off installed Pipecat, not guessed from slugs.
- Session-sticky key pooling so free-tier rotation does not seam a caller mid-turn.
- Provenance on `session.extra["providers"]` so analytics cannot bill Cartesia for an Azure fallback.

What is not:

- Two Azure OpenAI clients that do not share a process, a timeout, a retry policy, or a gateway.
- Two TTS synthesis stacks (Pipecat live vs HTTP preview) and two STT stacks (Pipecat streaming vs Azure REST batch).
- Two prompt assemblers (text vs voice) plus a third hardcoded insurance prompt.
- WhatsApp ignoring `AgentTuning.llm` while sandbox and voice honour it.
- Two frontend “provider” screens that do not share identifiers (`azure_openai` vs `azure`).

The right consolidation is not “adopt LangChain.” It is: **put the Mouth’s LLM through the same bind/fallback/provenance seam STT and TTS already have**, and **stop letting the text channel hardcode knobs the Deployment already stores.**

---

## Layer map

```
Habibi Agent Studio / Integrations / Sandbox
        │
        ▼
Application (main.py routes, bot_runtime, sandbox_runtime, voice_sandbox)
        │
        ├─ Deployment ── load_active_bundle → prompt_versions + bot_deployments.tuning
        │
        ├─ Prompt assembly
        │     text  → agent_core.prompt.build_system_prompt
        │     voice → voice.natural.build_voice_system_prompt
        │     mesh  → hardcoded string in voice/workers/insurance.py
        │
        ├─ AI orchestration
        │     text  → bot_runtime / sandbox_runtime tool loop
        │     voice → Pipecat pipeline in voice/bot.py
        │
        ├─ Provider abstraction
        │     STT/TTS live → factory.resolve_chain → factory.build → Pipecat service
        │     STT/TTS unbound/broken → provider_bind fallback Azure
        │     TTS preview → provider_tts HTTP adapters (parallel stack)
        │     STT batch   → azure_speech.transcribe (always Azure)
        │     LLM text    → azure_openai.chat_with_tools → maybe llm_gateway
        │     LLM voice   → KeepAliveAzureLLMService (no registry)
        │
        └─ External API
              Azure OpenAI chat / embeddings / voice deployment
              Azure Speech (SDK via Pipecat, REST via azure_speech)
              Cartesia / Deepgram / ElevenLabs / Groq / Gladia / Speechmatics / Fish / OpenRouter
```

There is no single “AI orchestration” module. Text orchestration is a Python tool loop. Voice orchestration is Pipecat. They share Deployment, tools, and (partially) `AgentTuning`. They do not share an LLM client.

---

## Capability boundaries

Evaluate whether each boundary exists and whether it earns its keep. Not a framework shopping list.

| Capability | Where it lives | Who uses it | Who bypasses it | Earns its keep? |
|---|---|---|---|---|
| **LLM** | `azure_openai.chat_with_tools` + optional `llm_gateway`; voice `llm_pool.KeepAliveAzureLLMService` | Text Mouth, sandbox, analysis, copilot, vision, embeddings | Voice Mouth, AMD classifier, insurance worker | **Partial.** Text callers funnel through one function. Voice does not. Gateway is a flag, not a plane. |
| **STT** | `factory` + `provider_bind` → Pipecat STT services | Live call | `POST /stt/transcribe` → `azure_speech.transcribe` | **Yes** on the audio path. Batch HTTP is a second, Azure-only client. |
| **TTS** | Same factory/bind → Pipecat TTS (Azure subclass, Fish service, vendor services) | Live call | `POST /tts/preview` → `provider_tts` / `azure_speech.synthesize` | **Yes** on the audio path. Preview is an honest parallel stack (request/response vs barge-in streaming) but duplicates vendor HTTP. |
| **Voice session** | `voice.session.VoiceSession` (CRM bind); `voice_session_store` (sandbox bundle across API/voice processes) | Live tools; sandbox Live | Pipecat `session_id` is a third identifier, not a fourth store | **Yes.** Two stores for two jobs. The file-store split that hid sandbox tuning is already fixed. |
| **Prompt** | `prompt_versions` + `prompt_render` + two assemblers | All Mouths | Insurance worker system_instruction; MCP `PROMPTS` (operator-triggered, not a Mouth) | **Yes** for authored text. Assembler split is justified by channel. The insurance string is a leak. |
| **Model configuration** | Env deployments; `AgentTuning.llm`; `llm_gateway` profile env; `gateway_canaries`; unused `slot=llm` bindings | Mixed | WhatsApp hardcodes temperature | **No.** Four places claim to pick the model; only env actually does for chat. |
| **Provider adapter** | `agent_core.providers.{registry,factory,pool,persist}` | Live STT/TTS; preview key rotation; catalog sync | LLM; batch STT; ops Integrations catalog | **Yes for speech. Not for LLM.** |

---

## Client inventory

### LLM

| Client | Process | Shape | Timeout | Retries | Gateway? |
|---|---|---|---|---|---|
| `azure_openai.get_client()` — sync `AzureOpenAI` | API, worker, bot_worker | `chat.completions.create`, embeddings | `AZURE_OPENAI_TIMEOUT_S` default **20s** | **2** | `maybe_chat` first if `LLM_GATEWAY_ENABLED` and URL set |
| `azure_openai.get_analysis_client()` | same | same SDK, isolated semaphore | **8s** | **0** | routed as gateway profile `analysis` |
| `voice.llm_pool._build_client()` — `AsyncAzureOpenAI` | voice, voice_insurance | Pipecat `AzureLLMService` + prewarm ping | **30s** / connect **10s** | **2** | **No** |
| `llm_gateway.client._http_chat` — raw `httpx.post` | API (when flag on) | OpenAI-compatible `/chat/completions` | **20s** | **2** on 5xx | this *is* the gateway |

`azure_openai.py:300-316` documents “Do not construct AzureOpenAI elsewhere.” Voice does, on purpose (`llm_pool.py:1-8`): Pipecat’s Azure client does not set httpx keep-alive, and India→East US TLS was 1–2s per turn. That is a real constraint. It is also why a gateway in the API process cannot meter or cap the Mouth that talks.

Call sites that go through `chat_with_tools` (text plane):

| Caller | File | Profile | Notes |
|---|---|---|---|
| WhatsApp tool loop | `bot_runtime.py:965` | chat | `temperature=0.2`, `max_completion_tokens=500` — **ignores AgentTuning** |
| Sandbox tool loop | `sandbox_runtime.py:256` | chat | reads `AgentTuning.llm` (`:783-786`) |
| Turn understanding | `agent_core/understanding.py:363` | analysis | timeout from `_timeout_s()`, `max_retries=0` |
| Turn critic | `agent_core/turn_critic.py:353` | analysis | |
| Copilot polish | `agent_core/copilot.py:238` | analysis | |
| KB planner | `agent_core/tools/kb_plan.py:273` | chat | |
| Vision | `agent_core/vision.py:94` | analysis | |
| Treatment rerank / reco | `agent_core/treatment/rerank.py`, `reco/models.py` | chat | |

Call sites that do **not**:

| Caller | File | Client |
|---|---|---|
| Live Mouth | `voice/bot.py:679` | `KeepAliveAzureLLMService` |
| AMD voicemail classifier | `voice/bot.py:1235` | second `KeepAliveAzureLLMService`, hardcoded classifier instruction |
| Insurance mesh worker | `voice/workers/insurance.py:42` | same Azure client, hardcoded “HDFC insurance / upsell specialist” |
| Prewarm / spike | `voice/llm_pool.py`, `voice/spike.py` | shared async client |
| Embeddings | `azure_openai.embed_texts` | sync Azure; **no gateway**, no registry |

### STT

| Path | Abstraction | Provider selection |
|---|---|---|
| Live pipeline | `provider_bind.bind("stt")` → factory → Pipecat (`AzureSTTService`, Deepgram, Cartesia, ElevenLabs Scribe, Groq Whisper, Gladia, Speechmatics) | `agent_provider_bindings` most-specific-first; unbound → Azure |
| Studio / HTTP | `POST /stt/transcribe` (`main.py:3269`) | **Always** `azure_speech.transcribe` REST |

SEED STT models (`agent_core/providers/registry.py:242-496`): `azure-stt`, `nova-3-general`, `ink-whisper`, `scribe_v2_realtime`, `whisper-large-v3-turbo`, `solaria-1`, `ursa-2`, `bilingual-ar-en`. None of these reach `/stt/transcribe`.

### TTS

| Path | Abstraction | Notes |
|---|---|---|
| Live pipeline | `provider_bind.bind("tts")` → factory | Azure uses `voice.tts_pool.KeepAliveAzureTTSService` (not Pipecat base) so registry binding does not regress websocket pre-open |
| Fish live | `agent_core.providers.fish_service.FishTTSService` | Pipecat `TTSService`; shares `fish_tts.build_payload` with preview |
| OpenRouter live | `OpenRouterTTSService.__init__` **raises** | `live_capable=False`; audition only |
| Preview | `provider_tts.synthesize` | HTTP adapters for Cartesia, Deepgram, ElevenLabs, Fish, OpenRouter; Azure stays in `azure_speech.synthesize` + disk cache |
| Catalog | `tts_voice_catalog` | Azure sync (`tts_catalog_sync`) + non-Azure sync (`provider_voice_sync`) into **one** table |

Preview adapters re-implement Cartesia/Deepgram/ElevenLabs HTTP (`provider_tts.py:121-200`) instead of constructing the Pipecat service. That is the streaming vs request/response split, not laziness — but it is a second place vendor URLs, model ids, and timeouts live. Cartesia preview hardcodes `sonic-3.5` (`provider_tts.py:118`); the registry seed has the same id (`registry.py:318`). Drift is possible.

---

## Prompt stores

Canonical authored prompt: **`prompt_versions`**, loaded by `load_active_bundle` (`agent_core/deployment.py:15-93`). Sandbox, WhatsApp, and voice all resolve through this. There is no in-process Deployment cache (see report 17).

Assemblers (not stores):

| Assembler | Channel | Extra |
|---|---|---|
| `agent_core.prompt.build_system_prompt` | WhatsApp, sandbox text | persona numbers, KB block, channel framing |
| `voice.natural.build_voice_system_prompt` | live / sandbox voice | drops empty KB block (latency); adds `VOICE_NATURALNESS_OVERLAY` and clock; persona as directions |
| Skill pack prefix | both | `resolve_mouth(...).prompt().prefix` appended in `voice/bot.py:96-100` |
| Insurance worker | mesh specialist | string literal (`insurance.py:50-55`) — **not** a Mouth |

Other prompt-shaped objects that are **not** Mouth stores:

- `agent_core/mcp_http/prompts.py` — operator-triggered MCP (`prep_handoff`, `draft_ptp_sms`). Not sampled as a system prompt.
- `Habibi/src/data/prompt-studio-seed.ts` — mock editor seed when `USE_MOCK`.
- `backend/voice/evals/scenarios/*.yaml` — eval fixtures.
- Analysis `_SYSTEM_PROMPT` inside `understanding.py` / critic — task prompts, correctly separate.

The text/voice assembler split is documented (`natural.py:155-161`) and is a channel decision, not accidental duplication. The insurance literal is accidental: that worker does not load a Deployment.

---

## Model and voice configuration — too many SoTs

### Model (which LLM)

| Source | What it claims | What actually runs |
|---|---|---|
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | text Mouth | yes (`azure_openai.get_chat_deployment`) |
| `AZURE_OPENAI_VOICE_DEPLOYMENT` | voice Mouth | yes (`voice/config.py:67-69`, fallback to chat) |
| `AZURE_OPENAI_ANALYSIS_*` | understanding / critic | yes, isolated client |
| `LLM_GATEWAY_{PROFILE}_MODEL` / LiteLLM | text when flag on | only if URL set |
| `gateway_canaries` | staged promotion analysis→text→voice | overrides gateway model **only**; voice canary cannot change `KeepAliveAzureLLMService` |
| `AgentTuning.llm` | temperature, top_p, max tokens, seed | honoured by voice + sandbox; **ignored by WhatsApp** |
| `agent_provider_bindings` slot `llm` | per-Mouth vendor | **nothing in SEED, nothing in `voice/bot.py`** |
| Bindings tab UI | “Language model” column | writes rows the runtime never reads |

### Voice (which TTS voice)

Resolved in `load_active_bundle` as a cascade (`deployment.py:77-80`):

```
deployment.ttsVoiceId
  → AgentTuning.tts.voice
  → voiceConfig.azureVoiceName
```

Plus:

- `prompt_versions.voice` (JSON on the version; sandbox draft path uses `voice.voiceId`)
- `tts_voice_catalog` (picker; `provider_id` namespaced short names)
- `tts_voices` (legacy studio aliases `priya/…`; `db.list_tts_voices` still consulted on preview fallback, `main.py:3014`)
- `Habibi/src/lib/tts-voice-prefs.ts` localStorage favorites/recent — UI only
- Hardcoded default `en-IN-AartiNeural` in `AgentTuning` presets and `tts_catalog_sync.DEFAULT_VOICE`

That cascade is one runtime SoT with too many writers. The Azure-shaped fields on frontend `VoiceConfig` (`azureVoiceName`, pitch, warmth) are documented as Azure leftovers that `params` now supplements (`prompt-studio-seed.ts:16-39`). Live still folds them into `AgentTuning.tts`.

---

## Confirmed findings

### P0 — Studio fact the runtime does not honour

**F1. LLM binding is a UI contract with no runtime.**
`Kind` includes `"llm"` (`registry.py:53`). `BindingsTab` offers slot `llm` (`Habibi/src/components/prompt-studio/BindingsTab.tsx:40-45`). `GET /providers/models?kind=llm` is a valid query (`main.py:5284`). SEED defines **no** `kind="llm"` model. `voice/bot.py:679` constructs Azure LLM from env. `provider_bind.bind` is never called with `"llm"`.

This is the exact failure `provider_bind.py:1-8` was written to end for STT/TTS: “an operator could pick Cartesia in the Agent Studio, hear the preview, publish it, and every real call still ran Azure.” LLM is still there.

**F2. Two LLM stacks, one product Mouth.**
Text: sync Azure SDK, 20s, 2 retries, optional LiteLLM, spend cap, analysis isolation. Voice: async Azure SDK, 30s, keep-alive forever, no gateway, no spend cap in `llm_gateway._spend_inr`. A canary that “promotes to voice” (`llm_gateway/canary.py:24`) cannot change the process that speaks.

### P1 — duplication that causes drift

**F3. WhatsApp ignores `AgentTuning.llm`.**
Sandbox: `sandbox_runtime.py:782-786` reads tuning temperature / max tokens (fallback `CHAT_TEMPERATURE = 0.2`, max 320). Voice: `tuning_apply.build_llm_settings_kwargs` (`:272-298`). WhatsApp: `bot_runtime.py:968-969` hardcodes `temperature=0.2`, `max_completion_tokens=500`. Publishing a brisk-verification preset changes sandbox and the phone, not WhatsApp.

**F4. Fail-closed factory, fail-open binder.**
`factory.py:10-14` and the migration (`20260821_0092`: “No silent default”) raise `NoBindingError` rather than substituting `en-IN`. `provider_bind.py:13-20` catches that and builds Azure, because an unbound tenant would otherwise drop every call. Bound-but-broken also falls back (`:80-97`). Provenance records it. The remaining lie: a Mouth bound to Cartesia that is down **sounds like Azure** and the transcript must be read to know. Operators who only look at the Bindings tab will not.

**F5. Batch STT is not the STT boundary.**
Live STT is multi-vendor. `POST /stt/transcribe` is Azure REST (`main.py:3269-3292`, `azure_speech.py:631`). Same product name, different client, different language default (`en-IN`), no binding, no pool.

**F6. Preview TTS re-implements vendors the live path already wraps.**
`provider_tts.py` holds Cartesia/Deepgram/ElevenLabs HTTP. Live uses Pipecat services via `factory.build`. Fish is the exception that did it right: HTTP client (`fish_tts.py`) shared with `FishTTSService`. OpenRouter preview correctly calls `openrouter_tts.synthesize`; live correctly refuses to construct.

**F7. Three copies of “is this a reasoning deployment?”**
- `azure_openai._is_reasoning_deployment` (`:273-288`) — also matches `-o1` infixes; env `AZURE_OPENAI_REASONING_MODEL`
- `voice.llm_pool._is_reasoning_deployment` (`:91-103`) — also `AZURE_OPENAI_VOICE_REASONING_MODEL`
- `voice.tuning_apply._is_reasoning_model` (`:17-29`) — same as llm_pool

A voice-only flag does not affect WhatsApp; a chat-only flag does not affect Pipecat settings. The comment in `tuning_apply.py:283-285` says they match. They do not, quite.

**F8. Two “provider” screens, two identifier schemes.**
Integrations: `azure_openai`, `azure_speech_stt`, `azure_speech_tts`, `openai`, `pipecat` (`Habibi/src/data/integrations-seed.ts:14-22`). Live list is `GET /providers` (`main.py:1509`). Agent Studio: slugs `azure`, `deepgram`, `cartesia`, … via `GET /providers/models`. Key pooling uses the second scheme (`pool.get_pool("azure")`). An operator enabling “Azure OpenAI” on Integrations does not create an `llm` binding. An operator binding `azure` STT does not toggle the Integrations health card.

**F9. Insurance worker is a Mouth that is not a Mouth.**
`voice/workers/insurance.py:42-57` builds Azure LLM with a hardcoded HDFC specialist prompt and `default_tuning()`. No `load_active_bundle`. No Agent Card. No Tool Grant from a published version. Handoff onto this worker leaves the card’s grant behind (see ADR-0001 intent in report 04) *and* leaves the card’s prompt behind.

**F10. Temperature / token ceilings disagree across channels.**

| Channel | Temperature | Max output tokens |
|---|---|---|
| WhatsApp | hardcoded 0.2 | 500 |
| Sandbox text | AgentTuning else 0.2 | AgentTuning else **320** |
| Voice | AgentTuning (empathetic preset **0.4**) | preset **220** |
| Analysis | 0.0 | per-caller |
| Gateway default | 0.2 | **800** |

A Mouth published once does not speak with one sampling policy.

**F16. `SpokenTextFilter` destroys Fish emotion tags on every provider.**
Installed on the live TTS ctor for bound and Azure fallback alike (`voice/bot.py:663`). It strips `[]` (`spoken_text.py:46`) because Azure word-boundary events duplicated parentheticals into the transcript. Fish S2 steers delivery with `[happy]` / `[whispering]`. On a Fish-bound call those tags never reach the model. Azure-shaped content policy leaks into a provider that needs the brackets.

### P2 — leftover dual-SoT and copy-paste

**F11. Legacy `tts_voices` still on the preview fallback path.**
Catalog is `tts_voice_catalog`. `db.list_tts_voices` is still walked when preview gets a `voiceId` that is not an Azure ShortName (`main.py:3014-3017`). Two tables, one picker.

**F12. Duplicate Fish emotion palettes.**
`fish_emotions.py` is the registry/UI source. `fish_tts.py:65-91` keeps a parallel `EMOTION_TAGS` dict. Comments say the registry re-exports so they cannot drift (`providers/__init__.py` / `fish_emotions.py:1-6`). The HTTP module does not import the data module.

**F13. Embeddings are an unnamed third LLM capability.**
`embed_texts` is Azure-only, process-local LRU, no gateway, no binding, no profile. KB retrieve and ingest both call it. Fine today; the registry’s `kind` enum has no `"embed"` and will not grow one by accident — it will grow by another env var.

**F14. Gateway spend cap is process-local and text-only.**
`_spend_inr` is a module dict (`llm_gateway/client.py:22`). Voice tokens never enter it. Multi-worker API each have their own cap. Not a security finding; it is why “we have a gateway” does not mean “we have a spend plane.”

**F15. `CHAT_TEMPERATURE` lives in `agent_core.turn` and is a constant, not a Deployment field.**
Used as sandbox fallback. WhatsApp does not even read it — it inlines `0.2`. Three spellings of the same default.

**F17. Studio “Refresh catalog” only syncs Azure.**
`POST /tts-voices/catalog/sync` calls `tts_catalog_sync.run_sync` (`main.py:2939-2948`). Multi-vendor ingest lives in `provider_voice_sync.py` and is CLI-only. The picker can list Cartesia rows that a later Azure sync may soft-remove when the non-Azure set is small (`tts_catalog_sync.py:321-340`).

**F18. Bound STT `model_id` is provenance, not a constructor argument.**
`factory.build` passes credentials, filtered settings, and `ctor` (`factory.py:224-247`). It does not inject `binding.model_id`. Env vars `DEEPGRAM_STT_MODEL` / `GROQ_STT_MODEL` are documented and unused. A Deepgram bind named `nova-3-general` may construct the Pipecat class on whatever default the SDK uses unless the id is also in `settings`.

---

## Realtime / Pipecat

Pipecat **is** the voice orchestration layer, not a leaky implementation detail of the HTTP app. The API process does not import Pipecat on the WhatsApp path. The voice image does (`requirements-voice.txt`).

What Pipecat owns: transport (Twilio media / WebRTC), VAD, turn-taking, the STT→LLM→TTS graph, AMD gate, mesh `LLMWorker` for insurance.

What leaked into the pipeline (and should): Locked Engines, Tool Grant, Flow graph, CRM `VoiceSession` identity, `CrmSink`. Those are product, not provider. They are coupled to Pipecat frames because the audio path has no other dispatcher. That is acceptable.

What leaked that should not: Azure LLM construction, hardcoded AMD/insurance prompts, Azure-named fallbacks inside `provider_bind`.

Session managers — **not duplicates**:

| Object | Job |
|---|---|
| `VoiceSession` | CRM identity for tool closures (`customer_id` never from the model) |
| `voice_session_store` | sandbox bundle API→voice process (Postgres; file only if DB unreachable) |
| Pipecat `session_id` / runner offer | transport connection |
| Redis mesh bus | insurance worker activation |

Report 17 already recorded the file-store split-brain and the Postgres fix. Do not merge these four; they answer four questions.

Streaming abstractions — **not duplicates of each other**, but LLM streaming is Azure-only:

- Pipecat frame stream (live)
- `llm_gateway` is **non-streaming** `httpx.post` of the full completion
- `azure_openai.chat_with_tools` is **non-streaming** sync SDK
- TTS preview is request/response bytes; live TTS is streamed frames

A gateway that cannot stream cannot replace the voice Mouth without a new adapter.

---

## Timeout and retry

| Path | Timeout | Retries | Shed |
|---|---|---|---|
| Text chat | 20s | 2 | `AzureBusyError` after 10s acquire |
| Text chat with caller `timeout=` | caller | **0** | same semaphore |
| Analysis | 8s | 0 | 1s acquire; keyword fallback |
| Voice LLM | 30s / 10s connect | 2 | none (call stays up) |
| Gateway HTTP | 20s | 2 on 5xx | spend cap raises |
| Azure Speech REST | 45s / 10s connect | none | concurrency 8 |
| Fish / OpenRouter TTS | 90s | key rotation | next provider / preview 422 |
| Preview HTTP | 60s | key rotation | `PreviewUnavailable` |
| Azure TTS pre-open | 5s | n/a | continue cold |

Inconsistent on purpose for analysis vs chat (documented incident: 51s “Bot is typing”). Inconsistent by accident for WhatsApp vs voice vs gateway defaults. The accident is F10.

---

## Hardcoded provider names (census, not a witch hunt)

Expected in adapters and seed. Problematic when they sit in **business** modules:

| Location | Why it matters |
|---|---|
| `voice/bot.py:679` `KeepAliveAzureLLMService` | Mouth LLM is Azure in code, not in a binding |
| `voice/provider_bind.py:79` `"provider": "azure"` | fallback identity |
| `voice/workers/insurance.py` | Azure + HDFC prompt |
| `bot_runtime.py:2` docstring “runs Azure tool loop” | channel runtime named for a vendor |
| `AgentTuning` presets `en-IN-AartiNeural` | Azure ShortName as product default |
| `load_active_bundle` `azureVoiceName` | schema-level Azure |
| Integrations seed `azure_openai` / `openai` | ops catalog still vendor-first |
| `provider_tts._CARTESIA_MODEL = "sonic-3.5"` | preview model not read from `provider_models` |

Factory `_credentials` special-cases `provider_id == "azure"` for region (`factory.py:199-201`). That is adapter work and is fine.

---

## Does the abstraction layer provide value?

**Yes, for speech.** Before `provider_bind`, the studio was a lie. After it, STT/TTS selection, locale specificity, failover, key pools, capability honesty (`code_switch`, `live_capable`, empty Cartesia params_schema), and provenance are real. Fish’s split (HTTP client without Pipecat vs pipeline service) is the pattern to copy.

**No, for LLM, as currently wired.** `chat_with_tools` is a useful façade for the text process (tools, metering, circuit breaker, analysis isolation, optional HTTP backend). It is not a provider abstraction: the type is Azure, the deployments are env, the gateway is a kill-switch around the same JSON shape. The registry’s `llm` kind is a reserved column. Voice never imports `llm_gateway`.

**Do not impose a new framework.** The missing move is local:

1. Seed at least one LLM model (`AzureLLMService` / `KeepAliveAzureLLMService` as `service_class`) and call `provider_bind.bind("llm", …)` from `voice/bot.py` the way STT/TTS already do.
2. Point WhatsApp and sandbox at `AgentTuning.llm` (and, if the gateway is on, at the same profile the canary thinks it is promoting).
3. Keep preview HTTP adapters, but take `model_id` from `provider_models` rather than module constants.
4. Leave Pipecat as the voice orchestrator. Do not route spoken turns through `llm_gateway`’s non-streaming `httpx.post`.

---

## What is already good (do not “fix”)

- `load_active_bundle` as the Deployment seam — all three channels.
- `prompt_render` system-safe vs CRM-card split — injection architecture, not style.
- `AgentTuning` as the intended knob object — honour it; do not add a fourth.
- Factory fail-closed for *locale* (unservable language ≠ unbound tenant). Binder fail-open for *unbound tenant*. The distinction is documented and correct; the remaining issue is operator-visible provenance (F4).
- Key pool session-sticky rotation (`pool.py:9-20`) — do not round-robin per request.
- `OpenRouterTTSService` raising on construct rather than yielding silence.
- `tts_voice_catalog.provider_id` rather than a second catalog table.
- Voice sandbox session in Postgres (`voice_session_store.py:1-28`).
- Analysis client isolated so enrichment cannot stall the live turn.

---

## Prioritized consolidation

1. **Wire `slot=llm` the way `slot=stt` is wired** — seed Azure (and later others) as `provider_models` rows; `provider_bind.bind("llm")` in `voice/bot.py`; record provenance. Until then, hide or disable the LLM column in BindingsTab so the studio cannot assert a false fact.
2. **One sampling policy per published Mouth** — `bot_runtime` reads `bundle["tuning"]["llm"]` exactly as sandbox does.
3. **One reasoning-model helper** — env flags included; voice and chat both import it.
4. **Preview `model_id` from `provider_models`** — delete `_CARTESIA_MODEL` / `eleven_multilingual_v2` literals from `provider_tts.py`.
5. **Insurance worker loads a Deployment** (or a dedicated published Mouth) instead of a string and `default_tuning()`.
6. **Align Integrations slugs with `providers.id`** (`azure` not `azure_openai`) or document them as a separate ops catalog so nobody expects a click to bind a call.
7. **Drop `tts_voices` from the preview fallback** once catalog coverage is complete; keep the table only if aliases still have a named owner.
8. **Make `SpokenTextFilter` provider-aware** — keep Azure bracket stripping; pass Fish `[tags]` through.
9. **Wire Studio catalog refresh to `provider_voice_sync`** (or stop calling the button “refresh” when it only talks to Azure).
10. **Pass `binding.model_id` into STT/TTS constructors** (or into settings the service actually reads).

Do not merge `VoiceSession` with `voice_session_store`. Do not replace Pipecat. Do not send live spoken completions through the non-streaming gateway. Do not add a second prompt table.
