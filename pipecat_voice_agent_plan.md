# Pipecat Voice Agent Plan — BigBound AI

> Grounded in: DeepWiki (`pipecat-ai/pipecat`, `pipecat-ai/pipecat-flows`), Daily Docs (RTVI / transports / VAD / SmartTurn / voicemail / warm transfer / multi-worker), Context7 (`/pipecat-ai/docs`, `/pipecat-ai/pipecat-flows`), and a full audit of `backend/voice/*`, `voice_sandbox.py`, Habibi `useSandboxLiveCall`.

**Goal:** Make the **voice agent alone** more intelligent, natural, observable, and production-ready — optimizing turn-taking, session lifecycle, RTVI client UX, telephony path, handoff, outbound AMD, metrics, recording/transcripts, and context — while keeping **our BigBound UI** (not the stock playground).

**Relationship to other plans:**
| Plan | Owns |
|------|------|
| `sandbox_plan.md` | Sandbox UX, Tuning Studio, Live vs Text honesty |
| `pipecat_unification_plan.md` | Shared `CallContext` + tool catalog across voice / WA / sandbox |
| **This file** | Voice-runtime intelligence: transports, turn detection, RTVI depth, Flows quality, telephony, handoff, AMD, multi-agent readiness, recording/metrics/summarization UX |

**Status:** Living plan after **3** audit↔docs cycles (frozen for implementation). Prefer implementing **P0→P1** here in parallel with unification Phase A (tools/context), not instead of it.

---

## 0. Verdict (current state)

| Capability area | Reality | Docs alignment | Intelligence / UX impact |
|-----------------|---------|----------------|--------------------------|
| Pipeline core | **Strong** — `PipelineWorker` + Azure STT→LLM→TTS + Flows + CrmSink + keep-alive pools | Matches Pipecat 1.5+ | Solid foundation |
| Turn detection | **Good** — Silero + `LocalSmartTurnAnalyzerV3` + mute strategies + idle ladder | Docs default stack | Naturalness is already competitive |
| Incomplete-turn LLM tagging | **Intentionally off** — `filter_incomplete_user_turns=False` (✓/◐ pollution) | Docs SOTA is 3-layer (VAD+SmartTurn+LLM tag) | Gap vs docs SOTA; re-enable carefully later |
| Flows graph | **Present** — collections script | Node tools / context_strategy underused | “Scripted” not fully “adaptive” |
| RTVI / client | **Thin** — transcripts + metrics + tune only | Full event surface unused | Sandbox feels dumb; supervisors blind |
| Transport | **Sandbox only** — SmallWebRTC | Docs: SmallWebRTC = self-host/dev; Daily = prod web; WS = telephony | No real phone path |
| Session lifecycle | **Fragile** — `latest.json` race; dual session IDs | Runner body should carry session | Concurrent Live breaks |
| Handoff | **Cold CRM row** — speak + hangup | Docs: warm transfer (Daily PSTN) or LLMWorker `activate_worker` | Feels unfinished to callers |
| Voicemail / IVR | **Absent** | Official `VoicemailDetector` + `IVRNavigator` | Blocks outbound / bank IVR demos |
| Multi-agent / jobs / proxy | **Absent** (single `PipelineWorker`) | WorkerBus / RedisBus / proxy examples | Overkill for hackathon; design for later |
| Recording | **Good** — disclosure-gated stereo WAV | Chunked `buffer_size` optional | Fine for demo; add chunks for long calls |
| Transcripts | **CRM path yes** / **Live UI ephemeral** | Persist + export kinds exist in schema | Analytics / QA incomplete |
| Context summarization | **On** — high thresholds (8000 / 36) | Native summarizer; Flows `RESET_WITH_SUMMARY` deprecated | Correct approach; add on-demand RESET at topic hops |
| Metrics | **Partial** — TTFB to CRM; client MetricsTab | `enable_metrics` + observers | Missing per-turn TTFA/tokens in CRM |

**Root cause:** The voice bot is a **strong single-pipeline collections script** with modern Pipecat APIs, but it is not yet a **full voice product** — thin client observability, no telephony, cold escalate, unused persona/KB snapshot, and no outbound AMD.

---

## 1. Target architecture (voice-only)

```
                         Habibi Sandbox / (future) phone client
                         PipecatClient + matching transport
                                      │  RTVI
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Voice session host                           │
│  WorkerRunner(auto_end=False)  ·  session registry by peer id    │
│  Transport factory: SmallWebRTC | Daily | Twilio WS              │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Optional outbound gate (telephony only)                         │
│    VoicemailDetector.detector() → … → .gate()                    │
│  Optional IVRNavigator (outbound “reach human” only)             │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Core duplex pipeline (always)                                   │
│  in → STT → KbEnrich? → user_agg → LLM(+Flows) → TTS → out       │
│       AudioBufferProcessor · CrmSink observer · RTVIObserver     │
│       auto context summarization · AgentTuning live deltas       │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
              Postgres CRM · KB · MinIO recordings · Analytics

Optional later (same bus):
  LLMWorker "collections" | LLMWorker "insurance_upsell" | LLMWorker "supervisor_brief"
  RedisBus / PgmqBus only when we outgrow one process
```

### Non-negotiables

1. **Stay cascaded STT→LLM→TTS + Flows** — not Gemini Live / OpenAI Realtime (Flows cannot rewrite tools/context on S2S today; matches unification plan).
2. **Our UI** — RTVI feeds Sandbox / future supervisor chrome; never embed stock Voice UI Kit as the product shell.
3. **Transport pair must match** — client `SmallWebRTCTransport` ↔ server SmallWebRTC; Daily↔Daily; telephony WS is provider→server only.
4. **Warm transfer is Daily/SIP (or Twilio conference), not “DB handoff + hangup”** — escalate tool must grow into real transfer when telephony exists; until then label UI honestly: “Queue for agent (callback)”.
5. **Do not invent multi-agent for collections PTP** — one Flow graph is enough; multi-worker is for specialist handoff / parallel research / remote LLM later.
6. **Unification plan owns shared tools/CallContext** — this plan consumes them; don’t fork a third catalog.

---

## 2. Capability gap matrix (docs × code)

### 2.1 Pipecat Flows — make the script intelligent

| Gap | Evidence | Docs | Plan |
|-----|----------|------|------|
| Flat-ish node tools | Upsell = speech-only; hub heavy | Node-scoped tools + globals | Wire eligibility/lead (unification); keep globals lean (escalate, KB, note, pause, end) |
| No `context_strategy` | Default APPEND forever | `ContextStrategyConfig` APPEND / RESET; use native summarizer not deprecated RESET_WITH_SUMMARY | APPEND default; on hub→upsell / hub→dispute topic hop optionally push `LLMSummarizeContextFrame` in `pre_actions` then continue APPEND |
| `respond_immediately` uneven | Only negotiate_ptp = False | Listen-first where user just spoke intent | Audit: dispute entry should often be False if user already stated dispute in hub |
| No flow.node RTVI | Silent transitions | Custom `RTVIServerMessageFrame` | Emit `{type:"flow.node", name}` on every `FlowManager` set_node |
| Role vs task | System prompt outside Flows | `role_message` on nodes persists via `LLMUpdateSettingsFrame` | Keep global system in bot; use node `task_messages` only (already) — don’t duplicate role on every node |

**Intelligence target:** The LLM should never see “all tools always”; node scope + CRM developer card (unification) + topic-hop summary = fewer wrong tool calls and shorter latency.

### 2.2 Clients & RTVI standard

| Gap | Evidence | Docs | Plan |
|-----|----------|------|------|
| Few events subscribed | `useSandboxLiveCall`: UserTranscript, BotOutput, TrackStarted, BotReady, Disconnected, Metrics | Full matrix includes speaking, mute, LLM/TTS lifecycle, function calls, ServerMessage | Subscribe: User/Bot Started/Stopped Speaking, UserMute*, LLMFunctionCall*, BotLlm/Tts*, ServerMessage |
| No `RTVIObserverParams` | Default worker RTVI | `function_call_report_level` FULL/NAME/NONE/DISABLED | Sandbox FULL for CRM tools; production NAME (or NONE for verify args) |
| No server→UI domain events | Tools return JSON to LLM only | `send_server_message` / `RTVIServerMessageFrame` | Contract below |
| Audio levels unused | Available on SmallWebRTC | `LocalAudioLevel` / `RemoteAudioLevel` | Optional waveform in Live chrome (nice-to-have) |
| Device events ignored | Mic switch / deviceError | Client callbacks | Surface device errors in Sandbox toast |

**RTVI contract (voice product):**

| Type | Direction | Payload |
|------|-----------|---------|
| `tuning_delta` | C→S | Already |
| `llm-function-call-*` | S→C | Native |
| `server-message` `flow.node` | S→C | `{name}` |
| `server-message` `crm.entity` | S→C | `{entity,id,deepLink}` |
| `server-message` `rag.hits` | S→C | `{query,chunkIds,snapshotId}` |
| `server-message` `session.lifecycle` | S→C | `{phase, reason}` connect/idle/escalate/end |
| `server-message` `handoff.status` | S→C | `{mode: cold\|warm, state, agentId?}` |

### 2.3 Choosing a transport

| Mode | Docs recommendation | Our plan |
|------|---------------------|----------|
| Sandbox Live / local | SmallWebRTC (P2P, simple) | **Keep** + Vite `/voice-rtc` |
| Production browser coaching / supervisor listen-in | Daily (PoPs, AEC, resilience) | **Phase T2** — optional Daily room for web-facing voice demos |
| Production phone collections | Twilio/Telnyx Media Streams **WebSocket** (provider→server) **or** Daily PSTN dial-in/out | **Phase T1** — pick **one**: prefer Daily PSTN if warm-transfer demo is priority; Twilio if existing SIP trunk |
| Browser↔bot over raw WS | **Do not** | Rejected (HOL blocking, no AEC) |

**Decision rule:** Hackathon demo path stays SmallWebRTC. Telephony is a **separate transport profile** behind `create_transport` (stubs already exist) — do not force Daily into sandbox.

### 2.4 Session lifecycle

| Gap | Evidence | Plan |
|-----|----------|------|
| `read_session("latest")` | `bot.py` | **Docs-aligned fix:** client sends `request_data: { sessionId }` on SmallWebRTC `/api/offer`; runner puts it on `SmallWebRTCRunnerArguments.body` + `runner_args.session_id`. Bot loads `.cache/…/{sessionId}.json` from **body**, never `latest`. Runner already supports **MULTIPLE** concurrent peers — our file race is self-inflicted. |
| Dual IDs | Sandbox `sessionId` ≠ `VS-…` VoiceSession | Map 1:1 in session file: `sandbox_session_id` + `voice_session_id`; CRM interaction keyed once; prefer aligning `VS-…` with sandbox id when sandbox-originated |
| HTTP stop ≠ kill worker | File patch only | Document: FE must `disconnect()` first; add optional `WorkerRegistry` cancel by session when runner is embedded |
| Idle / max duration | 180s worker idle; 10 min max; idle ladder | Keep; emit `session.lifecycle` RTVI events for UI countdown |
| Tune path split | HTTP persist + data-channel live | Require live apply via RTVI; HTTP = persist-for-next-call only (already labeled) — fail loudly if no RTVI channel |
| FE connect API | `useSandboxLiveCall` offer URL only | Pass custom data through whatever `@pipecat-ai/small-webrtc-transport` exposes for `requestData` / connect opts (verify SDK field name in PR) |

**Target lifecycle:**

```
POST /voice/sandbox/start → writes {sessionId}.json  (latest.json optional debug only)
client.connect({ webrtcUrl, requestData: { sessionId } })   # SmallWebRTCRequest.request_data
bot(runner_args): sid = runner_args.body["sessionId"] → read_session(sid)
  → bind CRM → FlowManager.initialize → set_bot_ready
… live tune / tools / idle …
client.disconnect → on_client_disconnected → stop recording → sink.stop → worker.cancel
POST …/stop → idempotent metadata + sandbox_run complete
```
### 2.5 Events & callbacks (server)

| Present | Gap |
|---------|-----|
| `on_function_calls_started` fillers | Also mirror via RTVI function events |
| User turn idle/started/stopped → CrmSink | Push speaking state to UI (client events exist) |
| Tripwires → escalate / language | Emit `handoff.status` / STT language server-message |
| Worker idle timeout farewell | Already; add lifecycle event |

### 2.6 Media management

| Present | Gap / plan |
|---------|------------|
| Client `enableMic` mute | Show server mute strategy state via `UserMuteStarted/Stopped` |
| Manual `HTMLAudioElement` on TrackStarted | Keep for SmallWebRTC |
| Construction-time mute strategies | Document restart for strategy changes; Tuning Studio already warns |
| No hold music | Needed for warm transfer — `SoundfileMixer` + `MixerEnableFrame` (Daily example) |
| No supervisor barge | Out of scope until Daily multi-participant |

### 2.7 Speech input & turn detection

| Present | Docs SOTA | Plan |
|---------|-----------|------|
| Silero + SmartTurn V3 + barge modes | VAD + SmartTurn + optional LLM single-token tags | **Keep** current as default |
| `filter_incomplete_user_turns=False` | LLM tagging layer | Revisit as **experiment flag** after prompt mixin hardened for Hindi/Indian English + collections (phone numbers, amounts); never re-enable blindly |
| `user_turn_stop_timeout=5.0` | — | Keep |
| Mute until first bot complete | Recommended vs greeting interruption loops | Ensure strategy always on for telephony greet/disclose |
| Mid-call VAD/SmartTurn not live-tunable | Construction-time | Accept; Tuning Studio “applies next call” for those knobs (already) |
| No Krisp / RNNoise | Docs: filter noise before VAD | Optional Phase L: Krisp VIVA or RNNoise if noisy PSTN |

**UX wins without new models:** fillers already; add “thinking” RTVI chip on function-call-started; speaking indicators in Live chrome.

### 2.8 Agent handoff

| Mode | Docs | Our state | Plan |
|------|------|-----------|------|
| Cold escalate | Hang up + queue | **What we have** (`record_handoff` + `escalate_close`) | Keep as default; rename UX to “Request human callback”; create inbox thread (unification) |
| Warm transfer | Daily PSTN: hold + dialout + brief + bridge | Absent | Phase T1b after Daily/Twilio transport |
| Multi-agent LLM handoff | `activate_worker` between LLMWorkers | Absent | Only if we split collections vs insurance specialists — **not** required for PTP |

Until warm transfer ships: escalate tool result must say `transfer_mode: "callback_queue"` so the LLM doesn’t promise “connecting you now”.

### 2.9 Job coordination / distributed / proxy / multi-agent

| Pattern | When we need it | Plan |
|---------|-----------------|------|
| Single `PipelineWorker` | Now | Stay |
| Local multi-LLM handoff | Specialist voices / compliance co-pilot | Phase M1 optional |
| `job_group` parallel | e.g. dispute research + policy check | Phase M2 — only if latency budget allows (speech path must not wait on 3 LLMs without filler) |
| RedisBus / PgmqBus | Multi-machine scale | Phase M3 / post-hackathon |
| WebSocket proxy agents | Remote LLM VPC | Phase M3 |
| UIWorker | Voice drives GUI tasks | Not product priority (we have Habibi) |

**Explicit:** Do not refactor bot.py into LLMWorker mesh before telephony + RTVI depth land.

### 2.10 IVR navigation

| State | Plan |
|-------|------|
| Absent; only consent “IVR” labels in CRM | **Outbound-only** feature: when bot must navigate bank/partner IVR to reach customer service before speaking to human — use official `IVRNavigator` + DTMF |
| Inbound DTMF from customer | `DTMFAggregator` → treat as transcript for “press 1” menus **inside our bot** if we expose a self-service IVR — low priority for collections script |
| Sandbox | Skip IVR (no PSTN) |

### 2.11 Voicemail detection

| State | Plan |
|-------|------|
| Persist allows `kind=voicemail`; no detector | For **outbound** dial: add `VoicemailDetector` (classifier LLM + TTS gate) per docs placement |
| Leave message → `record_media(kind=voicemail)` + disposition | Wire `on_voicemail_detected` → canned TTS + EndFrame + analytics disposition |
| Mid-call AMD during warm transfer | Docs: not supported out of the box; defer / watch upstream PR |
| Sandbox Live | N/A (browser user is always human) — gate behind `channel=telephony_outbound` |

### 2.12 Metrics

| Present | Plan |
|---------|------|
| `enable_metrics` + `enable_usage_metrics` | Keep |
| CrmSink median TTFB on complete | Persist **per-turn** TTFB/TTFA/tokens into interaction metrics or turn rows |
| Client MetricsTab | Add speaking RTT, function-call duration, STT final delay |
| India→East US floor | ~1.3–1.9s warm LLM TTFB (`SPIKE_NOTES.md`); keep-alive already removes ~1.2s TLS tax — surface honestly; don’t chase sub-second without region move |

### 2.13 Recording conversation audio

| Present | Plan |
|---------|------|
| Disclosure-gated stereo; MinIO/local | Keep |
| Full-call buffer | For long calls (>10–15 min later): chunked `buffer_size` 30s uploads per docs |
| `enable_turn_audio` | Optional for QA “listen to this turn” in Sandbox Inspector |
| Redacted audio | Offline redaction pipeline (domain page) — voice only stores raw + metadata |

### 2.14 Saving conversation transcripts

| Present | Plan |
|---------|------|
| CrmSink → `append_transcript_turn` | Keep as source of truth |
| Live UI ephemeral | On call end, optional hydrate Inspector from CRM **or** stream `transcript_export` media |
| Interrupted bot text | Rely on Pipecat word-timestamp truncation (framework) — verify Azure TTS path preserves heard-text in assistant aggregator |
| Export | Write `transcript_export` JSON/VTT to MinIO for disputes/QA |

### 2.15 Context summarization

| Present | Plan |
|---------|------|
| Auto summarization high thresholds | Keep thresholds; do not lower without tool-call soak tests |
| No on-demand summarize | On major Flow hops (verify→hub done, enter upsell), optional `LLMSummarizeContextFrame` pre_action |
| Dedicated summary LLM | Optional later (`LLMContextSummaryConfig.llm`) if main LLM TTFB suffers |
| `on_summary_applied` | Log + RTVI `session.lifecycle` debug in sandbox |

### 2.16 Persona / KB / intelligence inputs (voice-consumed)

Owned primarily by unification plan; **voice must consume**:

| Input | Voice action |
|-------|--------------|
| `sandboxPersona` | Developer message at flow start |
| `kbSnapshotId` | Pass into KbEnrich + `search_knowledge_base` |
| Product keys by node | Collections vs insurance upsell |
| CRM card post-verify | `LLMMessagesAppendFrame` developer |

---

## 3. UX principles (what “more intelligent” feels like)

1. **Heard correctly** — SmartTurn + mute-until-first-bot; speaking indicators; no greeting interrupt loops.
2. **Knows who you are** — after verify, bot cites balance/DPD from injected card without re-asking.
3. **Does things, not just talks** — tools create real CRM rows; UI shows chips.
4. **Honest about humans** — never imply live transfer until warm path exists.
5. **Audible & tunable** — Live voice + Tuning Studio; next-call vs live knobs labeled.
6. **Recoverable silence** — idle ladder already; show countdown in UI.
7. **Observable** — Inspector: node, tools, RAG, metrics, mute state.
8. **Safe** — disclosure before record; tripwires; escalate reasons logged.

---

## 4. Implementation phases

### Phase V0 — Correctness spine (P0) — ~1–2 days
1. Session-id via SmallWebRTC `request_data` → `runner_args.body` (kill `latest` authority).
2. Unify sandbox/voice session IDs in file + CRM bind.
3. RTVI: speaking + function-call + ServerMessage wiring (FE + `RTVIObserverParams`).
4. Escalate copy / tool result: `transfer_mode=callback_queue`; optional inbox thread (share with unification).
5. Apply `sandboxPersona` + `kbSnapshotId` in voice path.

### Phase V1 — Intelligence & Flows (P1) — ~2–3 days
1. Consume shared tool catalog (unification) for upsell/docs/eligibility.
2. `flow.node` + `crm.entity` + `rag.hits` server messages.
3. Topic-hop `LLMSummarizeContextFrame` on select transitions.
4. Per-turn metrics persist; transcript_export on complete.
5. Idle/lifecycle RTVI events for Sandbox chrome.

### Phase V2 — Turn-taking polish (P1/P2)
1. Audit barge modes per node (disclose locked; negotiate open).
2. Experimental `filter_incomplete_user_turns` behind env flag + India EN prompt soak.
3. Optional turn-audio in Inspector.
4. Krisp/RNNoise only if PSTN noise demands it.

### Phase T1 — Telephony transport (P0 for “real phone”, else P2)
1. Choose Daily PSTN **or** Twilio Media Streams; implement one end-to-end inbound.
2. `MuteUntilFirstBotComplete` + disclose path on PSTN.
3. Disposition + recording + transcripts same CrmSink.

### Phase T1b — Warm transfer + AMD
1. Daily warm transfer pattern (hold music, dialout, brief, bridge).
2. Outbound `VoicemailDetector` on dial-out campaigns.
3. Mid-call AMD deferred.

### Phase T2 — Daily web transport (optional)
1. Production browser clients on Daily when Sandbox SmallWebRTC insufficient.

### Phase IVR — Outbound IVRNavigator (P2)
1. Only for “navigate partner IVR to leave callback” demos.

### Phase M — Multi-agent (explicitly later)
1. Local LLMWorker handoff for insurance specialist.
2. RedisBus only with load evidence.
3. Proxy agents only for remote VPC LLM.

---

## 5. Explicit non-goals

- Embedding Pipecat Voice UI Kit / stock playground as the product UI.
- Switching collections bot to speech-to-speech realtime APIs.
- Multi-agent mesh before RTVI + session correctness + (if needed) telephony.
- Mid-call VoicemailDetector for warm transfer (upstream limitation).
- Browser WebSocket voice transport.
- Replacing Flows with a free-form single-node mega-prompt.
- Lowering summarization thresholds without soak tests.
- Building our own VAD/SmartTurn models.

---

## 6. Acceptance criteria

| Criterion | Passes when |
|-----------|-------------|
| Concurrent Live | Two browsers, two sessions, correct persona/tuning each |
| Observable call | Inspector shows node, tool calls, RAG hits, speaking state live |
| Intelligent upsell | Eligibility + lead tools on voice; Upsell page shows row |
| Honest handoff | Bot never says “connecting you” unless warm transfer active |
| Transcript truth | CRM transcript matches what was heard (interrupt-safe) |
| Recording | Disclosure-gated WAV linked to interaction |
| Summarization | No mid-tool false summaries (thresholds hold); optional hop summarize works |
| Telephony (if T1) | Inbound PSTN call runs same Flows + CRM writes |
| Outbound (if T1b) | Voicemail leaves message + disposition; human continues Flow |
| Latency honesty | Metrics show TTFB; no fake “instant” claims |

---

## 7. Doc references (pinned)

- Transports / choosing: Daily Docs “Choosing a Transport”; server transports learn page
- RTVI: RTVIProcessor, RTVIObserver, `RTVIFunctionCallReportLevel`, client event matrix
- Turn detection: Silero VAD, SmartTurn V3, user mute strategies, filter incomplete turns
- Recording: AudioBufferProcessor chunking
- Context: `enable_auto_context_summarization`, `LLMSummarizeContextFrame`
- Flows: NodeConfig, ContextStrategy, global_functions, pre/post actions
- Voicemail: `pipecat.extensions.voicemail.VoicemailDetector`
- IVR: IVRNavigator + DTMF frames
- Warm transfer: Daily PSTN warm transfer example
- Multi-agent: WorkerBus, jobs, RedisBus, WebSocketProxyClient/Server
- Lifecycle: `PipelineWorker` / `WorkerRunner` (not deprecated PipelineTask/Runner)

---

## 8. Suggested first PR slice (voice-only)

1. **SmallWebRTC `request_data.sessionId`** → `bot()` reads `runner_args.body`; load that session file only — delete `latest` authority.
2. **RTVI depth** — observer params + FE subscribe speaking/function/ServerMessage; Inspector Tools tab.
3. **Persona + kbSnapshotId** consumption in `bot.py` / KbEnrich / search tool.
4. **Escalate honesty** — tool result + spoken copy + optional inbox link.
5. **flow.node server messages** on Flow transitions.

(Tools catalog extraction stays in unification first PR — don’t duplicate.)

---

## 9. Cycle log

### Cycle 1 — Docs + audit → v1 outline
- Confirmed modern stack already: PipelineWorker, SmartTurn, Flows, summarization, AudioBuffer, CrmSink.
- Major absences: telephony, AMD, IVR, warm transfer, multi-agent, thin RTVI, latest.json race.
- Pulled official patterns for VoicemailDetector placement, Daily warm transfer, WorkerBus vs proxy.

### Cycle 2 — Cross-check plan vs code → tighten
- Validated `filter_incomplete_user_turns=False` is intentional (✓/◐ pollution) — plan treats re-enable as experiment, not regression.
- Validated summarization thresholds raised for tool-heavy turns — plan forbids blind lowering.
- Validated MuteUntilFirstBotComplete already in `tuning_apply` — keep for PSTN.
- Validated recording is disclosure-gated stereo — add chunking only when duration grows.
- Clarified ownership split vs `pipecat_unification_plan.md` (tools/context) vs this file (runtime/UX/telephony).
- Softened multi-agent: design-ready, not Phase V0.
- Escalate: require honest `callback_queue` until warm path exists.
- Transport: SmallWebRTC stays sandbox; one telephony choice in T1; reject browser WS.

### Cycle 3 — Docs session API + final freeze
- DeepWiki: concurrent peers are supported; pass config via `SmallWebRTCRequest.request_data` → `runner_args.body` / `session_id` — plan §2.4 rewritten to this API (not invent a custom registry first).
- Cited measured latency floor from `SPIKE_NOTES.md` (~1.3–1.9s warm TTFB).
- Confirmed MetricsTab + `mapRtviMetrics` exist but only wired to Metrics event — speaking/tools still missing (plan stands).
- Transport stubs: `create_transport` has `twilio` + `webrtc` lambdas; persist hard-codes `smallwebrtc`; Daily not in factory map yet — T1 must add Daily params if chosen.
- Re-scanned user topic list against §2: all covered. **No further material plan changes** — implement V0.

---

## 10. Priority cheat sheet

| Pri | Item |
|-----|------|
| P0 | Session via `request_data` → `runner_args.body` (no `latest` race) |
| P0 | RTVI depth (speaking, tools, server messages) → Sandbox feels real |
| P0 | Persona + kbSnapshotId actually used |
| P0 | Escalate honesty (+ inbox when unification ready) |
| P1 | Flows intelligence (upsell tools, hop summarize, flow.node) |
| P1 | Per-turn metrics + transcript_export |
| P1/P2 | Turn-taking experiment flag; turn audio |
| P2* | Telephony transport (*P0 if demo requires phone) |
| P2 | Warm transfer + VoicemailDetector |
| P3 | IVRNavigator, Daily web, multi-agent/Redis/proxy |
