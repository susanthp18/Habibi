# Habibi / BigBound — Multilingual SLM + Azure Voice Pipeline Blueprint (v2)

**Product:** Habibi / BigBound AI (BFSI collections)  
**Scope (IN):** `agent_core/understanding.py` (per-turn); `qa_autoscore.py` + `call_closer.py` (post-call); the Azure STT/TTS binding in `voice/`  
**Scope (OUT):** `agent_core/treatment/` and `agent_core/reco/` — remain deterministic; **no LLM/SLM inside those modules**. The live bot LLM (`KeepAliveAzureLLMService`, Azure OpenAI) is also out of scope.  
**STT/TTS lock:** **Azure AI Speech only** (cloud *or* Azure Speech containers). The provider binder in `voice/provider_bind.py` can bind Deepgram / Speechmatics / Fish / Cartesia — that is a Studio capability, not a licence to use them here.  
**Date:** 2026-09-18 (IST). **v2 review:** 2026-09-18 — verified against the codebase (`backend/`), Microsoft Learn (pages dated Jul–Sep 2026), the Hugging Face API, MCR container tags, and the Pipecat 1.6.0 source in `.venv`.  
**Status:** **Discovery + Azure experiments** (not production build-ready). v1 errata (Sol, Kimi K3) retained in Appendix C; v2 findings in Appendix D.

### How to use this doc
- **Allowed now:** the Phase 0 code fixes in §0 (they are small and unblock everything else); Azure Speech pilots in **Central India** (monolingual PSR GA, multilingual PSR preview, custom speech training all present); the Qwen3.5 runtime gate; latency measurement under the discipline in §3.6.  
- **Not allowed yet:** shipping any new SLM enum into treatment without the decision log persisted to a table; quoting any p95 as SLA; treating the Gulf track as co-equal with India (it is a new market with missing prerequisites — §1.0); designing the on-prem topology around features that only exist in the cloud (§3.7); counting MohamedRashad CS audio as a Gulf go/no-go.

---

## 0. What the code actually does today (read before planning)

The v1 doc planned several things the repo already has, and assumed several things it does not. This section is the ground truth as of `3d7c342`.

| Area | Reality in `backend/` | Consequence for the plan |
| :--- | :--- | :--- |
| Understanding | `agent_core/understanding.py`: one **Azure OpenAI** tool call (`record_understanding`, pinned `tool_choice`, `temperature=0`, 6 s timeout, `analysis` profile) **merged over a keyword baseline**. `abuse`/`legal` are `keyword OR llm`; out-of-range sentiment is rejected, not clamped; unregistered intents are dropped; a merge exception returns the baseline. | The **fail-closed contract already exists** as `_merge`. Phase 0 is *extend*, not *build*. The SLM work is "swap `azure_openai.chat_with_tools` for a local server behind the same profile", not a new module. |
| Understanding schema | `intent` ∈ 12 values (`ALLOWED_INTENTS`), `sentiment` float, `abuse`, `legal`, `unresolved_repeat`, `language ∈ {en, hi, hinglish, other}`, `english_gloss` (scrubbed, ≤200 chars), `confidence`. **No** `promise_to_pay` / `promise_date` — promises are captured by `tools_negotiate.py` and read from rows by `call_closer.py`. | v1 Appendix B was fiction. The canonical schema must be a **superset of `_TOOL_SCHEMA`**, with promise fields explicitly *not* in understanding. |
| Confidence | `_merge`: `chosen = confidence if confidence is not None else 0.9`. A model that omits `confidence` is recorded at **0.9**. | Direct contradiction of "abstain below threshold". Fix in Phase 0 (one line). |
| Where it runs | Voice: CrmSink's **analysis queue**, off the audio path (`crm_sink.py` `enqueue_understanding`). Text/WhatsApp: **on the critical path** of the reply (docstring). | The SLM's per-turn latency is **not** part of the voice turn budget. It *is* the WhatsApp reply budget. §3.5 was conflating them. |
| Decision log | `logger.info("turn understanding refined …")` only. The api/voice root logger has no handler — these lines are discarded in prod. `interaction_transcript` stores `intent`, `intent_score`, `source`, `sentiment`; **not** raw model output, prompt hash, model id, or abstain reason. | The Phase 0 decision log must be a **table**, not a log line. |
| Language handling | `agent_core/languages.py`: **8 Indian languages** (en, hi, ta, te, kn, mr, bn, gu). **No Arabic anywhere** — not in the registry, prompts ("bank collections call in India"), lexicon, or TTS voice config. Mid-call switching = `voice/safety.py::detect_language_signal` (keyword, **Hindi-only**) → `STTUpdateSettingsFrame(language=…)` → Azure STT **disconnect + reconnect**. | Gulf is a new-market track, not a locale toggle. The "language switch" today drops in-flight audio; continuous LID would replace it. |
| Azure STT binding | Pipecat **1.6.0** `AzureSTTService`: `language`, `profanity`, `endpoint_id`, `private_endpoint`. **No** `AutoDetectSourceLanguageConfig`, **no** `PhraseListGrammar`, **no** `SpeechServiceResponse_PostProcessingOption`, **no** `segmentation_silence_timeout_ms` (added in Pipecat 1.9). | Every STT feature in §3.2 needs a Habibi subclass (same pattern as `KeepAliveAzureTTSService`) or a Pipecat upgrade. Nothing in §3.2 is "config". |
| Turn detection | Silero VAD (`build_vad_params`) + `LocalSmartTurnAnalyzerV3` (`TurnAnalyzerUserTurnStopStrategy`), VAD-only start (transcription start deliberately removed). `user_turn_stop_timeout=5.0`. | Matches v1. Missing: Azure's own **500 ms segmentation silence** is a second end-pointer nobody tuned (§3.1). |
| Measured latency | `bot_pipeline.py`: STT TTFB **p50 ≈ 1.18 s** (`ttfs_p99_latency=1.15`, from logs). Understanding LLM p50 unknown; one recorded 51 s outlier motivated the 6 s cap. | v1 said "TBD" for STT; we have a number. Use it. |
| QA / closer | `qa_autoscore.py`: rubric tool call, **coverage gate 0.8**, writes both score columns, `ai_draft` status. `call_closer.py`: deterministic-first, closed vocab (`BUSINESS_OUTCOMES`), **numeric fence** on summaries, runs off `call_attempts.closed_at IS NULL`. | Both already have the safety gates v1 wanted. The SLM plan is a backend swap behind identical gates. |
| Azure Speech SDK | `azure-cognitiveservices-speech` **1.51.0** installed (PSR needs ≥1.50 ✓). Pipecat pinned 1.6.0; upstream is 1.11.0. | PSR/multilingual PSR is reachable from the installed SDK today; only the Pipecat wrapper is missing. |

### 0.1 Phase 0 code changes (small, unblock everything)

1. `understanding.py::_merge` — missing/unparseable `confidence` ⇒ **keep keyword scores, mark `source=keyword`, set `abstain_reason="no_confidence"`**; never default to 0.9.  
2. Add `understanding_decisions` table (schema §0.2), written from the analysis queue in the same job as the transcript refinement. RLS on at create (`operator_invites` precedent, `3d7c342`); mirrored into `sql/` (fresh builds stamp, not migrate).  
3. Extend `LANGUAGES` to the registry tags plus `hinglish`/`tanglish`/`other` and make `language` a **registry-driven enum**, not a hand list.  
4. Feature flag per tenant: `UNDERSTANDING_BACKEND ∈ {azure_openai, slm_shadow, slm_live}`. `slm_shadow` runs both and logs both; treatment sees Azure. That is how Phase 3 works without a second code path.

### 0.2 Decision-log table (Phase 0 — BFSI reconstructibility)

For a dispute ("your system escalated me wrongly") an abstention or enum change must be reconstructible months later. One row per understanding call — success, abstain, or fail-closed:

| Column | Purpose |
| :--- | :--- |
| `turn_id`, `call_id` / `interaction_id`, `tenant_id`, `created_at` | Join to CRM, recording, RLS |
| `backend`, `model_id`, `revision_sha`, `quant_id`, `adapter_id` | Exact artifact (Azure deployment name or GGUF filename + SHA256) |
| `prompt_hash`, `schema_version` | Prompt + JSON-schema drift control |
| `stt_locale`, `stt_detected_locale`, `stt_text_hash`, `stt_final_is_refined` | Input provenance; whether PSR replaced the final |
| `keyword_json`, `raw_model_output`, `validated_json` | Baseline vs model vs what engines saw |
| `abstain`, `fail_closed_reason` | `none / invalid_json / unregistered_intent / no_confidence / below_threshold / timeout / shed / merge_error` |
| `confidence_raw`, `confidence_calibrated` (nullable) | Calibrated only once a reliability set exists |
| `latency_ms`, `shed` | Ops |

Retention: same DPDP / counsel schedule as call artifacts (§2.5). Drift monitoring (enum distribution, abstain rate, fail-closed rate **by locale and backend**) is Phase 0 ops, not polish.

---

## Architectural invariant (keep) + fail-closed

```
[Customer / Call State]
         │
         ├── Deterministic engines (RBI FPC, DPDP, EV ₹, DND, windows)
         │     ├── treatment/  → NBA   ❌ never call an SLM
         │     └── reco/       → NBO   ❌ never call an SLM
         │
         └── Linguistic / acoustic layer
               ├── understanding.py     → keyword baseline ⊕ SLM → validated canonical JSON
               ├── voice bot (Pipecat)   → Azure STT ↔ bot LLM (Azure OpenAI, out of scope) ↔ Azure TTS
               └── qa_autoscore / call_closer → larger SLM (batch / near-realtime)
```

Canonical outputs stay **language-agnostic enums**. Keeping SLMs out of `treatment/` / `reco/` does **not** make understanding harmless: its enums are inputs to those engines. Hence:

### Fail-closed contract for `understanding.py` (extends the existing `_merge`)

| Condition | Required behavior | Status |
| :--- | :--- | :--- |
| Invalid / non-JSON / schema fail | Keyword baseline; `fail_closed_reason=invalid_json` | ✅ exists |
| Unregistered intent | Keep keyword intent | ✅ exists |
| Out-of-range / NaN sentiment | Reject, keep keyword | ✅ exists |
| Missing `confidence` | **Abstain** (keyword scores) | ❌ defaults to 0.9 — fix §0.1 |
| `confidence` below threshold | Abstain; threshold per model **after** calibration (§2.4) | ❌ not implemented |
| Timeout / shed / crash | Keyword baseline, no retry on the voice path (queue would back up); ≤1 retry on WhatsApp within the reply budget | ✅ partly (no retry either way) |
| Contradicts hard call state (wrong person, DND, legal hold) | Deterministic state wins; never override compliance flags | ✅ by construction (understanding never writes those) |
| STT prompt-injection | Schema allowlist; `english_gloss` is the only free text and never reaches treatment; fence lives in the system role (Prompt Shields lesson in the file header) | ✅ exists — keep the test |
| `abuse` / `legal` | `keyword OR model` — model may **add** escalation, never remove | ✅ exists |
| Illegal combos (e.g. `unresolved_repeat` on first turn) | Reject field, keep others | ❌ add when schema grows |
| Decision reconstructible | Row in `understanding_decisions` | ❌ §0.2 |

Two consequences of the OR-merge that v1 did not state: (a) a hallucinated `legal=true` **does** trigger a compliance escalation — that is the intended high-recall bias, so **false-positive escalation rate by locale** is a release metric, not an afterthought; (b) GBNF / guided decoding guarantees syntax only — it changes none of the rows above.

---

## 1. Model shortlist (Hub-verified 2026-09-18; bake-off required)

### 1.0 Two tracks, not one

| Track | Locales | Prerequisites present? | Stance |
| :--- | :--- | :--- | :--- |
| **A — India** | `hi-IN`, `ta-IN`, `en-IN` (+ te/kn/mr/bn/gu in registry); Hinglish, Tanglish | Registry ✅, prompts ✅, Azure Central India ✅ (custom speech training, mono PSR GA, multi PSR preview, Voice Live, LLM-speech), Smart Turn hi ✅ / ta community model | **Primary.** Everything below is sequenced for this track. |
| **B — Gulf** | `ar-AE` (+ `ar-SA` if phrase lists / refinement matter more than locale fidelity) | Registry ❌, prompts ❌ ("India"), lexicon ❌, TTS voice config ❌, UAE North Speech: real-time + batch + NTTS only (**no** PSR, **no** custom-speech training, **no** fast transcription) | **New market.** Runs after Track A Phase 3, or in parallel only with its own owner. Do not let it gate India. |

Prefer **one unified multilingual SLM** over disjoint language routers (intra-sentential code-switch breaks LID routers). Labels like "strong / specialist" are hypotheses until the Habibi harness (messy Azure STT → constrained JSON → class-weighted safety metrics) says otherwise.

### 1.1 Primary candidates (live understanding + QA)

| Role | Model ID (exact, verified) | Params / ctx | License | Notes | Local on Btcerlp-016 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Understanding bake-off A** | [`Qwen/Qwen3-1.7B`](https://huggingface.co/Qwen/Qwen3-1.7B) | 1.7B (1.4B non-emb); safetensors ≈2.03B BF16; 32k | Apache-2.0 | Official post-trained artifact (no `-Instruct` ID). Mature llama.cpp path. | Official GGUF = **Q8_0 only** ([`Qwen/Qwen3-1.7B-GGUF`](https://huggingface.co/Qwen/Qwen3-1.7B-GGUF)); Q4 via Unsloth, pin SHA |
| **Understanding bake-off B** | [`Qwen/Qwen3.5-2B`](https://huggingface.co/Qwen/Qwen3.5-2B) (released **2026-03-02**) | 2B; 262k ctx; 201 langs; Gated DeltaNet hybrid + vision encoder | Apache-2.0 | Text-only path. **Card: "more prone to thinking loops than other Qwen3.5 models"** → hard-disable thinking, cap `max_tokens`, presence_penalty 1.5. GGUF exists: [`unsloth/Qwen3.5-2B-GGUF`](https://huggingface.co/unsloth/Qwen3.5-2B-GGUF) (Q4_K_M 1.28 GB, UD-Q4_K_XL 1.34 GB; mmproj bundled — ignore). llama.cpp had day-1 support; §1.1.1 gate is now cheap, still mandatory. | After gate |
| **Understanding bake-off C (new)** | [`Qwen/Qwen3.5-4B`](https://huggingface.co/Qwen/Qwen3.5-4B) | 4B; 262k | Apache-2.0 | Insurance if both 2B-class fail schema adherence on Tanglish. [`unsloth/Qwen3.5-4B-GGUF`](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF) | Q4 fits; live risky on Iris |
| **Ultra-light / smoke** | [`Qwen/Qwen3-0.6B`](https://huggingface.co/Qwen/Qwen3-0.6B) or [`Qwen/Qwen3.5-0.8B`](https://huggingface.co/Qwen/Qwen3.5-0.8B) | 0.6B / 0.8B | Apache-2.0 | Harness plumbing; keyword-baseline replacement candidate | Yes |
| **QA / Call closer (batch)** | [`Qwen/Qwen3.5-9B`](https://huggingface.co/Qwen/Qwen3.5-9B) (**replaces** Qwen3-8B) | 9B; 262k native | Apache-2.0 | Same family as the live winner → one prompt style, one template quirk set. Keep `Qwen/Qwen3-8B` only as the A/B control. Larger: `Qwen/Qwen3.6-27B`, `Qwen3.6-35B-A3B` (Apr 2026) if GPU budget appears. | Eval-only ([`unsloth/Qwen3.5-9B-GGUF`](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF)); serve on cloud/on-prem GPU |

**Runtime note (Qwen3):** non-thinking via `enable_thinking=False` in the chat template. `/no_think` is soft and may still emit an empty `<think>` block — test the exact llama.cpp / vLLM template.

**Runtime note (Qwen3.5):** different architecture (Gated DeltaNet + gated attention; vision encoder on all small cards). Card guidance points at **main-branch** SGLang/vLLM; llama.cpp needs a recent build. Unsloth non-thinking recipe: `temperature 0.7, top_p 0.8, top_k 20, presence_penalty 1.5` — for JSON extraction we still run `temperature 0` + grammar and verify the loop-rate ourselves.

#### 1.1.1 Qwen3.5 runtime-maturity gate (before Phase 2 bake-off)

1. **Pinned runtime:** exact `llama.cpp` commit + Windows build flags (native Windows build, not WSL — see §3.6 on the 4 GB WSL cap).  
2. **Artifact:** `unsloth/Qwen3.5-2B-GGUF` filename + revision SHA + SHA256 recorded; text-only load confirmed (`--language-model-only` equivalent / no mmproj).  
3. **JSON smoke:** ≥500 constrained generations, thinking disabled, on real Hinglish + Tanglish STT text; record valid-JSON rate, **loop/timeout rate**, p50/p95 at fixed power plan.  
4. **Memory:** peak RSS under browser + CRM + Pipecat.  
5. **Go/no-go:** gate fails → bake-off is Qwen3-only (1.7B vs 0.6B vs 4B). Do not invent parity.

### 1.2 Teachers / specialists (not laptop-primary)

| Model | Hub (verified) | License | Fit | Caveat |
| :--- | :--- | :--- | :--- | :--- |
| **Sarvam-30B** (MoE ~2.4B active) | [`sarvamai/sarvam-30b`](https://huggingface.co/sarvamai/sarvam-30b) (upd. 2026-03) | Apache-2.0 | Indic teacher (22 langs incl. hi/ta) | No Arabic; GPU; custom code paths |
| **Sarvam-105B** | [`sarvamai/sarvam-105b`](https://huggingface.co/sarvamai/sarvam-105b) | Apache-2.0 | Indic offline QA teacher | Cloud only |
| **Fanar-1-9B-Instruct** | [`QCRI/Fanar-1-9B-Instruct`](https://huggingface.co/QCRI/Fanar-1-9B-Instruct) | Apache-2.0 | Gulf/MSA teacher hypothesis; 4k ctx | Card warns against high-stakes financial use without safeguards |
| **Jais-2-8B-Chat** | [`inception42/Jais-2-8B-Chat`](https://huggingface.co/inception42/Jais-2-8B-Chat) (upd. 2026-08; `gated:auto`) | Apache-2.0 | Arabic–English CS claim; ~8k ctx | Request access early; chunk transcripts |
| **SILMA-9B-Instruct-v1.0** | [`silma-ai/SILMA-9B-Instruct-v1.0`](https://huggingface.co/silma-ai/SILMA-9B-Instruct-v1.0) | Gemma | Arabic benchmarks | `gated:false`; not laptop-first |
| **Gemma 4 E2B-it** | [`google/gemma-4-E2B-it`](https://huggingface.co/google/gemma-4-E2B-it) (upd. 2026-07) | Apache-2.0 | Text A/B only | `any-to-any` card; native audio **not** used under the Azure lock |
| AceGPT-v2-8B-Chat | [`FreedomIntelligence/AceGPT-v2-8B-Chat`](https://huggingface.co/FreedomIntelligence/AceGPT-v2-8B-Chat) | Apache-2.0 | Legacy | Prefer Fanar / Jais-2 |

### 1.3 Selection matrix (hypotheses until Habibi harness)

| Family | Hinglish / Tanglish | Arabic / Gulf | JSON | Laptop live | Stance |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Qwen3 0.6–1.7B | claim | claim | strong, thinking off | yes | Bake-off A |
| Qwen3.5 0.8–4B | 201-lang claim | 201-lang claim | TBD; loop risk on 2B | after gate | Bake-off B/C |
| Qwen3.5-9B | claim | claim | strong | eval only | QA / closer |
| Sarvam-30B | strong focus | none | tools | no | Indic teacher |
| Fanar / Jais-2 | limited | strong / CS claim | chat | eval only | Track B teachers |
| Gemma 4 E2B | claim | claim | function calling | possible | Text A/B |

**Working decision:** one backbone (winner of A/B/C on messy STT→JSON) + optional language LoRA adapters trained on cloud GPU. Adapter hot-swap by tenant locale is unsolved for live code-switch — the fallback is *no adapter*, never *wrong adapter*.

---

## 2. Data plan (code-switch first)

### 2.1 Public datasets (verified 2026-09-18)

| Dataset | Link | Langs | Use | License / notes |
| :--- | :--- | :--- | :--- | :--- |
| **COMI-LINGUA** | [`LingoIITGN/COMI-LINGUA`](https://huggingface.co/datasets/LingoIITGN/COMI-LINGUA) | hi–en | LID, MLI, POS, NER, TN, MT | cc-by-4.0; resolve size-tag inconsistency before volume estimates |
| **SPRING-INX Tamil R1** (new) | SPRING Lab, IIT Madras (CC BY 4.0) — the corpus behind `smart-turn-tamil` | ta telephone | **Narrowband Tamil call audio** — STT feasibility + EOU | Verify licence terms directly; telephone conversations, not banking |
| Ara–Eng CS (speech) | [`MohamedRashad/arabic-english-code-switching`](https://huggingface.co/datasets/MohamedRashad/arabic-english-code-switching) | ar–en audio | Plumbing only | GPL-tagged; YouTube; **not Gulf-labelled** |
| ArZen upstream | `ahmedheakl/arzen-llm-speech-ds` | — | — | **404** — not a dependency |
| Tamilmixsentiment | [`community-datasets/tamilmixsentiment`](https://huggingface.co/datasets/community-datasets/tamilmixsentiment) | ta–en comments | research only | `license:unknown` → excluded from prod training |
| DravidianCodeMix | [site](https://dravidian-codemix.github.io/2020/datasets.html) | ta/ml–en | broader CS | redistribution unclear |

**Gaps:** Gulf collections lexicon; Tamil banking Tanglish; Hindi collections Hinglish; Arabizi; promise/hardship/legal taxonomies aligned to `ALLOWED_INTENTS`.

### 2.2 Proprietary corpus (highest ROI) — and how to get "messy STT" text cheaply

1. **Shadow data already exists.** `interaction_transcript` rows carry `text`, keyword intent/score, and (when the LLM ran) the refined intent with `source=llm`. The Phase 0 table adds raw model output. That is the seed of the gold set — no new capture path.  
2. **Two transcripts per call.** Live final (Azure real-time, the text understanding actually saw) + a post-call second pass with **MAI-Transcribe-2** (preview, Central India, file-based, auto-LID, code-switching incl. Hinglish, verbatim mode, phrase list). The pair gives (a) a better transcript for QA/closer and human labelling, (b) a *measured* live-STT error distribution per locale, which is what "train on messy STT" should mean.  
3. **Synthetic messy STT without a recording:** clean text → Azure TTS (locale voice) → G.711 μ-law 8 kHz round trip (`ffmpeg`) → Azure real-time STT with the production config. Group by seed utterance so paraphrases never straddle splits. This is the only honest way to synthesise STT noise for Tanglish, where no public banking audio exists.  
4. Gold set: ≥2k turns per family (Hinglish, Tanglish; Gulf when Track B starts) with raw live STT, refined STT, corrected text, canonical JSON. **Double-annotate 20 %**, report κ per field; `legal`/`abuse` need ≥0.8 before they gate anything.  
5. Azure Custom Speech packs per locale (§3) — bilingual CS outcome is a feasibility experiment, not an assumption.

### 2.3 Train/eval splits (sum to 100 %; no leakage)

| Split | Allocation | Grouping |
| :--- | :--- | :--- |
| Train | 80 % of each pool (proprietary; public; synthetic) | `call_id` / `customer_id` / `speaker_id` / `synth_seed` |
| Dev | 10 % | same |
| Blind test | 10 % + live shadow set | same; never re-labelled after first look |

### 2.4 Metrics / release gates

- **Understanding:** class-weighted F1; **min recall** on `legal`, `abuse`, hardship; JSON valid ≥ 99 %; abstain rate; fail-closed rate; **false-positive compliance-escalation rate** (OR-merge side effect); subgroup CIs for hi / ta / hinglish / tanglish (ar later).  
- **Calibration:** reliability diagram + ECE per model on the blind set **before** any `confidence` threshold is used for abstention. Until then `confidence` is logged, never acted on.  
- **STT:** WER/CER on CS gold, split by locale × PSR on/off × 8 kHz vs 16 kHz; phrase-list gains only where supported (`hi-IN`, `en-IN`, `ar-SA`).  
- **QA:** κ vs auditors per criterion; PII leakage tests; unsafe-summary red team; numeric-fence rejection rate.  
- **Rollback:** any subgroup below its gate ⇒ flag back to `azure_openai` for that tenant.

### 2.5 DPDP / RBI calendar (hard dates, not vibes)

| Date | Obligation | Impact here |
| :--- | :--- | :--- |
| 2025-11-13 | DPDP Rules 2025 notified; Data Protection Board constituted | Retention + purpose limitation for training corpora must be documented now |
| **2026-11-13** | Consent Manager framework operative (Rule 4) | Consent capture for using call audio/transcripts in model training must be in the CRM flow before this |
| **2027-05-13** | Full substantive compliance (notice, consent, security safeguards, breach reporting, data-principal rights) | Deletion-into-datasets/adapters must actually work (erasure requests reach training data lineage) |

De-identification is not "strip PAN/Aadhaar": names, phones, employers, addresses, free-text narratives, voice biometrics, and call metadata are all re-identification vectors. `pii_redact` + `_LONG_DIGIT_RUN_RE` is the current floor; counsel defines the ceiling. Azure Speech processes data **in the resource region only** — Central India is the residency-safe choice for Track A; the UAE North feature gap (§3.7) is the price of residency for Track B.

---

## 3. Full voice pipeline (VAD → STT → SLM → TTS) — Azure-only

```
 PSTN / WebRTC audio (PSTN = 8 kHz G.711, upsampled to 16 kHz for VAD/Smart Turn)
        │
        ▼
 ┌──────────────────┐
 │ Silero VAD       │  local ONNX; stop_secs from AgentTuning.vad
 └────────┬─────────┘
          ▼
 ┌──────────────────┐
 │ Smart Turn v3.2  │  LocalSmartTurnAnalyzerV3 — 23 langs incl. ar, hi; **ta via community model** (§3.1)
 └────────┬─────────┘
          ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ Azure AI Speech STT — via a Habibi subclass of AzureSTTService │
 │ • Continuous recognition                                       │
 │ • EITHER continuous LID (≤10 candidates, 1 locale per base     │
 │   language, custom endpoint per candidate)                     │
 │   OR multilingual PSR (open-range auto-detect, no candidates)  │
 │ • Monolingual PSR (GA) where one locale is known               │
 │ • Phrase lists: hi-IN / en-IN / ar-SA only                     │
 │ • segmentation_silence_timeout_ms tuned WITH Smart Turn        │
 └────────┬─────────────────────────────────────────────────────┘
          │ text + detected locale + refined flag
          ▼
 ┌──────────────────┐        ┌──────────────────────────────┐
 │ Bot LLM (Azure   │        │ understanding.py (analysis   │
 │ OpenAI) — out of │        │ queue, off audio path) →     │
 │ scope            │        │ keyword ⊕ SLM → validated JSON│
 └────────┬─────────┘        └──────────────┬───────────────┘
          │ reply text                      │ validated signals only
          ▼                                 ▼
 ┌──────────────────┐        ┌──────────────────────────────┐
 │ Azure Neural TTS │        │ Deterministic engines        │
 │ locale voice;    │        │ treatment/reco UNCHANGED     │
 │ force_locale for │        └──────────────────────────────┘
 │ borrowings       │
 └────────┬─────────┘
          ▼
     Audio out
```

### 3.1 VAD + Smart Turn (Pipecat) — three end-pointers, not one

- Docs: [Smart Turn](https://docs.pipecat.ai/api-reference/server/utilities/turn-detection/smart-turn-overview), [Silero VAD](https://docs.pipecat.ai/api-reference/server/services/vad/silero-vad-analyzer), model [`pipecat-ai/smart-turn-v3`](https://huggingface.co/pipecat-ai/smart-turn-v3) (v3.2, Jan 2026).  
- **Pipecat pin:** 1.6.0 (2026-07-21) today; upstream **1.11.0 (2026-09-17)**. From the CHANGELOG, what the upgrade buys and what it does not:

  | Version (date) | Relevant change |
  | :--- | :--- |
  | 1.7.0 (2026-08-01) | Azure TTS `force_locale` (SSML `<lang>` for multilingual voices); fix for `TurnAnalyzerUserTurnStopStrategy` ending a turn on every finalized transcript when the turn was transcript-started |
  | 1.8.0 (2026-08-26) | `AudioBufferProcessor.on_user_turn_audio` — one event per user turn with the turn's audio + turn number (**the gold-set capture hook**); Azure `token_provider` (Entra ID, no API key); Azure v1 endpoint surface |
  | 1.9.0 (2026-09-10) | `AzureSTTService.Settings.segmentation_silence_timeout_ms` (100–5000 ms, Azure default 500); **`SpeakingObserver`** (user_speech_started/stopped vs user_turn_started/stopped vs bot_speech — the instrument for §3.1's three-end-pointer measurement); Azure TTS `voice_parameters` for HD voices. Eager end-of-turn is Deepgram Flux / Cartesia only — not Azure |
  | 1.11.0 (2026-09-17) | Azure TTS `effect` (`eq_car`, `eq_telecomhp8k`) |
  | **Absent through 1.11.0** | Any Azure STT `AutoDetectSourceLanguageConfig`, `PhraseListGrammar`, or post-processing property. Google/Gemini/Whisper/Cartesia got biasing hooks; Azure did not. The Habibi subclass is required regardless of upgrade. |

  Already in 1.6.0 and earlier: Smart Turn v3.2 weights (0.0.99), auto-resample of 8 kHz input to 16 kHz for Smart Turn (0.0.104, 2026-03-02), `transformers` dropped from Smart Turn — RSS ~566 → ~60 MB, cold start ~5 s → ~0.3 s (1.3.0), Azure STT runtime settings reconnect (0.0.105), `finalized=True` on Azure finals (1.4.0).

#### 3.1.1 Pipecat version decision (2026-09-18)

**Current:** `pipecat-ai[azure,webrtc,runner,silero,deepgram]==1.6.0` (2026-07-21) — pinned in `backend/requirements-voice.txt:26`, and what is installed in `.venv`.

**Decision: upgrade to 1.11.0** (2026-09-17, current release). Fallback if the regression suites object: **1.9.0** — it still carries the three features that matter most (`segmentation_silence_timeout_ms`, `SpeakingObserver`, `on_user_turn_audio`) and loses only the telecom EQ effect. Stopping anywhere below 1.9 is not worth it.

Breaking / deprecated surfaces between 1.6.0 and 1.11.0, checked against what Habibi touches:

| Change | Habibi exposure | Action |
| :--- | :--- | :--- |
| 1.10.0 ⚠️ `SpeechmaticsSTTService` moves to the Agent STT SDK (`speechmatics-agent-stt` extra); legacy endpoint unsupported; `SpeakerFocus*`, `update_params()` removed | Registry lists Speechmatics (`agent_core/providers/registry.py:469`) but its extras are **not installed** and policy is Azure-only | None. If Speechmatics is ever enabled, it is a re-binding, not a bump. |
| 1.8.0 deprecates `api_version` on `AzureLLMService` (removed in 2.0); non-v1 endpoints route through `2025-04-01-preview` | Passed in `voice/llm_pool.py:65`, `voice/bot_pipeline.py:201`, `voice/bot_pipeline.py:530` | Deprecation warning only. Keep for now; switch `endpoint` to `…/openai/v1` + drop `api_version` as a follow-up. |
| 1.8.0 ⚠️ `ExternalUserTurnStrategies` now pushes its own start/stop frames; 1.4/1.5 auto-configure `realtime_service_mode` | Not used — VAD start + Smart Turn stop, cascaded Azure | None. |
| 1.8.0 deprecates `enable_user_speaking_frames` on strategy constructors; 1.6.0 deprecates strategy `reset()` | `voice/tuning_apply.py` constructs stock strategies without these | None. |
| 1.9.0 and 1.11.0 rewrote the `filter_incomplete_user_turns` system-prompt instructions | Off by default (`voice/bot_pipeline.py:283`, `VOICE_FILTER_INCOMPLETE_TURNS`) | Redo the India-EN soak on 1.11 before enabling. |
| 1.7.0 fix: `TurnAnalyzerUserTurnStopStrategy` ended a transcript-started turn on every final | `min_words` mode already pairs `SpeechTimeoutUserTurnStopStrategy`; default mode is VAD-started | Bonus, no action. |
| 1.7.0 fix: Azure TTS with `pause_frame_processing=True` could hang the pipeline on a zero-audio completion (e.g. quota-exhausted key) | `KeepAliveAzureTTSService` inherits this path | Real fix for a real failure mode — one more reason to move. |
| 1.5.0 fix: services/transports leaked connections when torn down without `EndFrame`/`CancelFrame` | Every reaper / watchdog teardown path | Already in 1.6.0; stays. |

Upgrade procedure: bump the pin; run the provider-binder regression, the `tests/e2e_telephony` harness on a scratch DB, and the voice-container suite; re-measure STT TTFB and the three end-pointers with `SpeakingObserver` before touching any tuning defaults. If a 1.11.x patch lands during the sprint, take it — 1.11.0 is a day old at the time of this decision.  
- **Three independent end-of-turn signals exist and the slowest wins:** (1) Silero `stop_secs` (≥200 ms physics), (2) Smart Turn inference (~12–100 ms CPU), (3) **Azure's segmentation silence timeout, default 500 ms**, which gates when the *final* transcript is emitted. Tuning (1)+(2) while (3) sits at 500 ms buys nothing. Measure all three from the same audio end timestamp.  
- **Tamil:** not in the v3 list. Community model [`santhosh-005/smart-turn-tamil`](https://huggingface.co/santhosh-005/smart-turn-tamil) (BSD-2, Sep 2026): Whisper-encoder EOU trained on 18,485 turn boundaries from 116 **narrowband Tamil telephone calls**; held-out 86.1 % (base int8) vs **70.3 % for zero-shot smart-turn-v3.2**; ~120–155 ms; loads via `LocalSmartTurnAnalyzerV3(smart_turn_model_path=…)`. Caveats: **narrowband only** (wideband OOD — the inverse of v3's 16 kHz training), 8 s window, not speaker-disjoint. Action: Phase 4 A/B on Tanglish PSTN; if it wins, the turn analyzer becomes **locale-routed** (Tamil card → Tamil model), which the tuning binder can already express.  
- **Codec isolation:** run every EOU experiment twice — clean 16 kHz and G.711 8 kHz→16 kHz — so "dialect prosody" and "narrowband" are not confounded. Pipecat already resamples 8 kHz to 16 kHz before Smart Turn (0.0.104), so the open question is *accuracy on upsampled narrowband*, not plumbing. Capture the per-turn audio for both conditions with `on_user_turn_audio` (Pipecat ≥1.8) so the same clips feed the Tamil A/B and the STT gold set.

### 3.2 Azure STT — can / cannot / experiments (verified Sep 2026)

**Sources:** [Language support](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support), [LID](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-identification) (updated 2026-08-10), [Post-processing](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-post-processing) (2026-07-28), [Regions](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/regions) (2026-09-16), [PSR GA blog](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/post-stream-refinement-is-now-generally-available-in-microsoft-foundry/4540174), [Multilingual PSR blog](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/for-the-first-time-real-time-transcription-goes-multilingual/4539089) (both 2026-07-23).

| Capability | `hi-IN` | `ta-IN` | `en-IN` | `ar-AE` | `ar-SA` | Notes |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| Real-time streaming | ✅ | ✅ | ✅ | ✅ | ✅ | continuous recognition |
| Custom speech (audio + transcript) | ✅ | ✅ | ✅ | ✅ | ✅ | availability only; CS gain unproven |
| Custom speech: structured text / output format | ✅ | ✅ (structured) | ✅ | ❌ | ✅ | |
| **Phrase list (runtime)** | ✅ | ❌ | ✅ | ❌ | ✅ | ≤ ~2000 phrases; `PhraseListGrammar` — not in Pipecat 1.6.0 wrapper |
| LID candidate | ✅ | ✅ | ✅ | ✅ | ✅ | ≤10 for continuous, one locale per base language; **service always returns a candidate even when none was spoken** |
| **Monolingual PSR (GA)** | ✅ | ❌ | ✅ | ❌ | ✅ | one locale/session; phrase lists + diarization supported; 22 regions incl. Central India |
| **Multilingual PSR (preview)** | ✅ | ❌ | ✅ | ❌ | ✅ | **open-range auto-detect, code-switching within one utterance claimed**; 25 langs / 29 locales; **6 regions: East US, West US, North Europe, Central India, Southeast Asia, Japan East**; diarization only (no phrase list, no custom speech); SDK ≥ 1.50 (installed 1.51.0) |
| Fast transcription / LLM speech (file) | ✅ | ✅ | ✅ | ✅ | ✅ | file APIs — post-call only |
| **MAI-Transcribe-2 (preview, file)** | `hi` | `ta` | `en` | `ar` | `ar` | 60 langs, auto-LID, **code-switching (Hinglish named)**, phrase list, verbatim; Central India ✅; no dialect locales — `ar` only |

**What changed since v1:** the "Azure cannot do intra-sentence code-switch" statement was true of *continuous LID* and is still true of it. It is **no longer the whole story**: multilingual PSR is a different path (one multilingual model refining the final) and Microsoft claims mid-utterance CS on it. Preview, no SLA, no phrase lists, `ta-IN`/`ar-AE` absent — so it is a **Track A Hinglish experiment**, not a design dependency.

#### 3.2.1 Region ∩ locale ∩ residency (resolved for India, open for Gulf)

| Region | Real-time | Custom speech training | Mono PSR | Multi PSR | Voice Live | LLM speech / MAI |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `centralindia` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `uaenorth` | ✅ | ❌ | ❌ | ❌ | ✅ (GPT models only) | ❌ |
| `qatarcentral` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `southindia` | not supported for speech | | | | | |

India residency + every Azure STT feature is compatible. Gulf residency (`uaenorth`) means base models only; custom speech would be trained elsewhere and **copied** into the region (Microsoft documents model copy), and all refinement is unavailable. State this to Track B stakeholders before anyone promises Gulf WER numbers.

#### 3.2.2 Azure-only code-switch strategy (honest, v2)

1. **Hinglish (Track A, first):** A/B three configurations on the same 8 kHz gold audio — (a) `hi-IN` + phrase list + mono PSR, (b) continuous LID `{hi-IN, en-IN}` + per-locale custom endpoints, (c) multilingual PSR open-range. Metric: CS-segment WER + entity WER (amounts, dates, product names) + final-latency delta. Expect (c) to win WER and lose on phrase lists; the SLM must absorb the difference.  
2. **Tanglish:** no phrase list, no PSR. Custom speech on `ta-IN` with bilingual audio+transcripts **is the only Azure lever**; run it as a pass/fail feasibility gate with the SPRING-INX-style narrowband audio plus Habibi calls. If it fails, Tanglish robustness moves entirely to the SLM (train on measured messy STT, §2.2).  
3. **Gulf:** `ar-AE` base only in-region; `ar-SA` outside region gets phrase lists + PSR. Decide residency first; only then run the CS gate. MohamedRashad remains plumbing.  
4. **LID semantics:** continuous LID always returns a candidate, so "caller is speaking an unsupported language" **cannot** come from LID. Keep that decision in understanding (`language=other`) → `offer_agent`, as `safety.py` does today.  
5. **Continuous LID mechanics:** needs `SpeechConfig.FromEndpoint`, `SpeechServiceConnection_LanguageIdMode=Continuous`, `AutoDetectSourceLanguageConfig(SourceLanguageConfig(locale, endpoint_id)…)`; adds initial latency (Microsoft's own warning). Only Python/C#/C++/Java/JS SDKs.  
6. Train understanding on **measured** messy STT (live vs MAI-refined pairs), not clean text.

### 3.3 Azure TTS

- Locale voices: `hi-IN-*`, `ta-IN-*`, `en-IN-*`, `ar-AE-FatimaNeural` / `HamdanNeural`.  
- English borrowings inside a Hindi/Tamil sentence: Pipecat ≥1.7 `force_locale` wraps text in SSML `<lang>`; multilingual/DragonHD voices only where the voice supports it — `xml:lang` alone does nothing on a monolingual voice.  
- Telephony: Pipecat ≥1.11 Azure TTS `effect=eq_telecomhp8k` pre-shapes audio for narrowband; test against the Asterisk G.711 leg before enabling.  
- Amounts in Indic/Arabic TTS: every on-prem Arabic model tested earlier misread amounts; Azure neural voices need the same **amount-readback test set** (₹/AED, lakh/crore, decimals) as a release gate, not a spot check.

### 3.4 SLM integration

| Module | Model | Latency budget | Notes |
| :--- | :--- | :--- | :--- |
| `understanding.py` (voice) | bake-off winner | **Turn cadence**, not turn latency: must land before the next customer turn's tripwires (~3–6 s); current 6 s cap stands | Off audio path; `slm_shadow` flag; decision-log row |
| `understanding.py` (WhatsApp/text) | same | On the reply path — budget = reply p95 minus generation; measure | ≤1 retry allowed here only |
| `qa_autoscore.py` / `call_closer.py` | Qwen3.5-9B | seconds–minutes | Backend swap behind existing coverage gate + numeric fence; input = MAI-refined transcript when available |
| Live bot LLM | out of scope | — | Do not force a 2B model into the tool graph |

### 3.5 Latency budget (measure; do not treat as SLA)

**Timing origin:** true user speech end → first audible PSTN sample. Split into what the SLM affects and what it does not.

| Stage | Working note | Status |
| :--- | :--- | :--- |
| VAD silence (`stop_secs`) | ≥ stop_secs by construction | physics |
| Smart Turn inference | 12–100 ms CPU per vendor; Tamil model 120–155 ms | measure |
| Azure segmentation silence | **500 ms default**, tunable 100–5000 ms (Pipecat ≥1.9) | untuned today |
| Azure STT final | **p50 ≈ 1.18 s TTFB** (repo measurement); PSR "may add a small amount" to the final | measured / re-measure with PSR |
| Bot LLM (Azure OpenAI) | out of scope | — |
| Azure TTS TTFB | network + service | measure |
| **Understanding SLM** | **not on this path** for voice | measure separately (§3.6) |

Treat 1.5–2.5 s total as an optimistic median aspiration until measured under browser + CRM + Pipecat load.

### 3.6 Measurement discipline on Btcerlp-016 (from prior benchmark runs)

- The i7-1355U is a 15 W part whose throughput **swings 5–9×** with power state. Never compare absolute numbers across sessions: pin the Windows power plan, interleave candidates A/B/A/B in one run, report **ratios** and per-run baselines.  
- **WSL/Docker is capped at 4 GB** on this machine; a GGUF that OOMs is killed with no traceback (`State.OOMKilled`). Run llama.cpp **natively on Windows** for the bake-off, or raise `.wslconfig` explicitly and record it.  
- Backgrounded runs produce 0-byte output for minutes; that is normal, not dead.  
- Log: model SHA, quant, threads, ctx, power plan, build flags, wall clock — in the decision-log format, so laptop numbers are as reconstructible as prod ones.

### 3.7 Deployment topology (cloud vs bank DC) — the on-prem target vs Azure features

Habibi's stated direction is Pipecat on-prem inside a bank. Under the Azure-only lock the on-prem path is **Azure Speech containers** (connected or disconnected-commitment). What survives the move:

| Feature | Cloud (Central India) | Azure Speech container (bank DC) |
| :--- | :---: | :--- |
| Real-time STT | ✅ | ✅ `speech-to-text` **4.12.0** tags verified for `hi-in`, `ta-in`, `en-in`, `te-in`, `mr-in`, `bn-in`, `gu-in`, `ar-ae`, `ar-sa`; **`kn-in` absent** (overview says 5.1.0 latest — pin the tag you tested) |
| Custom speech model | ✅ | ✅ `custom-speech-to-text` container |
| Phrase list | ✅ (3 locales) | verify in-container per locale |
| Continuous LID | ✅ | `language-detection` container is **preview and not available disconnected** |
| Mono / multilingual PSR | ✅ / preview | ❌ cloud-only |
| MAI-Transcribe / LLM speech | preview / GA | ❌ cloud-only |
| Neural TTS | ✅ all locales | `neural-text-to-speech` **3.13.1**: `ar-ae-fatimaneural`, `ar-sa-zariyahneural`, `hi-in-swaraneural`, `en-in-prabhatneural`; **no `ta-in`, `te-in`, `mr-in`, `bn-in`, `gu-in`, `kn-in`** |
| Understanding SLM | any | ✅ (that is the point of an SLM) |

Consequences: (a) an on-prem Tamil deployment has **no Azure Tamil TTS** — either a hybrid (TTS from cloud, audio never leaves… it does) or a policy exception; (b) on-prem loses every code-switch lever except custom speech + SLM, which is exactly why the SLM must be trained on the *container's* STT output, not the cloud's; (c) disconnected containers need Microsoft approval (form, ~10 business days) and a commitment plan — start the paperwork in Phase 1. Voice Live (GA for prompt agents, Central India) is the managed Azure alternative; use it only as a **quality/latency reference** in Phase 4, since it cannot run in a bank DC.

---

## 4. Hardware-aware fine-tuning plan

### 4.1 What NOT to do on Btcerlp-016
- QLoRA of anything ≥ 4B on Iris Xe / CPU as the iteration loop.  
- Claim realtime 9B locally.  
- Benchmark inside WSL without raising the memory cap.

### 4.2 Hybrid loop

```
[Laptop] label + review + GGUF latency/quality eval (llama.cpp, native Windows, pinned power plan)
    │
    ▼
[Cloud GPU] Unsloth / TRL QLoRA
    ├── base: bake-off winner (Qwen3-1.7B | Qwen3.5-2B | Qwen3.5-4B)
    └── base: Qwen/Qwen3.5-9B (QA / closer)
    │
    ▼
Export LoRA → merge or adapter load → quantize (document quant recipe + SHA256)
    │
    ▼
[Laptop] regression harness → [Prod pod / bank DC] serve
```

### 4.3 Recipes

| Job | Base | Method | Data | Success |
| :--- | :--- | :--- | :--- | :--- |
| Understanding LoRA | bake-off winner | QLoRA r=16–32 | live-STT → JSON pairs (§2.2) | class-weighted F1 + min-recall + JSON ≥99 % + calibration curve |
| Indic adapter | same + Sarvam teacher | LoRA | COMI-LINGUA + Tanglish gold | Hinglish/Tanglish subgroup gates |
| Gulf adapter (Track B) | same + Fanar/Jais teacher | LoRA | Gulf gold | Gulf subgroup gates |
| QA LoRA | Qwen3.5-9B | QLoRA | rubric-labelled calls (MAI-refined transcripts) | κ per criterion + safety gates |
| Azure Custom Speech | — | Azure | bilingual wav+txt (8 kHz where PSTN) | pass/fail WER on CS gold, live + container |

### 4.4 Serving
- Dev: llama.cpp / llama-server, pinned build flags, threads, quant, power plan.  
- Prod understanding: small CPU/GPU pod (cloud) or the same image in the bank DC; thinking disabled; grammar-constrained; hard `max_tokens`.  
- Prod QA: async worker on the existing `call_attempts` claim loop.

### 4.5 Cost / capacity (TBD, but enumerate)
GPU type-hours (incl. failed runs); custom speech training + **endpoint hosting $/hr per locale**; STT per-minute × (base | custom | PSR | MAI second pass); TTS per-character; container commitment tiers; concurrent channels; adapter storage. Do not treat "L4/A10 24–40 GB" as a budget.

---

## 5. Roadmap, risks, open questions

### 5.1 Phased roadmap (Track A; Track B forks after Phase 3)

| Phase | When | Deliverable |
| :--- | :--- | :--- |
| **0 — Code truth + fail-closed + decision log** | Week 0 | §0.1 fixes; `understanding_decisions` table + `sql/` mirror; registry-driven `language` enum; `UNDERSTANDING_BACKEND` flag; drift dashboard queries |
| **1 — Azure STT wrapper + Central India pilots** | Weeks 1–3 | `HabibiAzureSTTService` (LID / PSR / phrase list / segmentation timeout); Hinglish 3-way A/B (§3.2.2); Tanglish custom-speech gate; MAI-Transcribe-2 second-pass job; disconnected-container application filed |
| **1b — Qwen3.5 runtime gate** | Weeks 1–2 (parallel) | §1.1.1 with the §3.6 discipline |
| **2 — Bake-off** | Weeks 2–5 | Qwen3-1.7B vs Qwen3.5-2B vs Qwen3.5-4B on measured messy STT → JSON; calibration curves; laptop ratios |
| **3 — Shadow** | Weeks 4–7 | `slm_shadow` per tenant; both backends logged; gate on class-weighted + fail-closed + FP-escalation metrics; DPDP consent path live before **2026-11-13** |
| **4 — Turn quality + Pipecat upgrade** | Weeks 4–8 | Pipecat 1.6.0 → **1.11.0** (fallback 1.9.0; §3.1.1) with provider-binder + telephony e2e regression; three-end-pointer tuning; Tamil Smart Turn A/B; 8 kHz vs 16 kHz isolation; Voice Live as reference |
| **5 — QA / closer on Qwen3.5-9B** | Weeks 7–10 | Backend swap behind coverage gate + numeric fence; MAI-refined input; κ report |
| **6 — Adapters (optional)** | Weeks 10–14 | Hot-swap + "no adapter" fallback |
| **7 — Track B kickoff** | after Phase 3 | Registry/prompt/lexicon/TTS prerequisites; residency decision (`uaenorth` vs `ar-SA` elsewhere); Gulf gold set; Fanar/Jais bake-off |
| **8 — Container parity** | before any bank-DC deploy | Re-run Phase 1–2 gates against the container STT output; Tamil TTS policy decision |

### 5.2 Risks

| Risk | Sev | Mitigation |
| :--- | :---: | :--- |
| SLM enums alter treatment indirectly | Critical | Fail-closed + decision-log table + high-recall safety classes + FP-escalation metric |
| Confidence defaults to 0.9 today | High | §0.1 fix; no threshold until calibrated |
| Azure STT features not in Pipecat wrapper | High | Habibi subclass in Phase 1; Pipecat upgrade in Phase 4 |
| Multilingual PSR is preview / `ta-IN`+`ar-AE` absent | High | Experiment only; custom speech + SLM is the default CS strategy |
| Continuous LID adds latency and always returns a candidate | Med | Measure; unsupported-language decision stays in understanding |
| Three uncoordinated end-pointers | Med | Tune together; report from one timestamp |
| Tamil: no phrase list, no PSR, no Smart Turn v3, no TTS container | High | Custom speech gate; community EOU model; cloud TTS or policy exception |
| Gulf prerequisites absent in product | High | Track B with its own owner; never gates India |
| `uaenorth` has no custom-speech training / PSR | Med | Train elsewhere + copy; set expectations |
| On-prem loses LID / PSR / MAI | High | Train SLM on container STT; §3.7 matrix in every design review |
| Laptop benchmarks drift 5–9× | High | §3.6 discipline |
| Qwen3.5-2B thinking loops | Med | Hard-disable thinking; grammar; `max_tokens`; loop-rate in gate |
| Stale shortlist (Qwen3-8B for QA) | Med | Qwen3.5-9B primary, Qwen3-8B control |
| DPDP deadlines (2026-11-13, 2027-05-13) | High | Consent + erasure lineage in Phase 3 |
| Unknown-licence / YouTube data | High | Excluded until counsel |
| Adapter hot-swap vs live CS | Med | "no adapter" fallback |

### 5.3 Explicit Azure cannot / workaround (v2)

| Need | Azure? | Action |
| :--- | :---: | :--- |
| Word-level CS via **continuous LID** | No | Use multilingual PSR (preview, Hinglish only in practice) or custom speech + SLM |
| Word-level CS via **multilingual PSR** | Claimed (preview) | Verify on Habibi audio; not a GA dependency |
| Phrase lists on `ar-AE` / `ta-IN` | No | Custom speech + SLM |
| Any PSR / MAI on-prem | No | Container STT + SLM |
| Tamil neural TTS container | No | Cloud TTS or policy decision |
| Arabic dialect locale in MAI-Transcribe | No (`ar` only) | Live `ar-AE` for dialect; MAI for post-call |
| Non-Azure STT/TTS | Out of policy | N/A |

---

## References

### Codebase (ground truth)
- `backend/agent_core/understanding.py`, `backend/agent_core/languages.py`, `backend/voice/tuning_apply.py`, `backend/voice/bot_pipeline.py`, `backend/voice/safety.py`, `backend/voice/crm_sink.py`, `backend/qa_autoscore.py`, `backend/call_closer.py`, `backend/requirements-voice.txt`  
- `.venv/Lib/site-packages/pipecat/services/azure/stt.py` (1.6.0)

### Models (all IDs verified via HF API 2026-09-18)
- https://huggingface.co/Qwen/Qwen3-0.6B · /Qwen3-1.7B · /Qwen3-4B · /Qwen3-8B · /Qwen3-1.7B-GGUF  
- https://huggingface.co/Qwen/Qwen3.5-0.8B · /Qwen3.5-2B · /Qwen3.5-4B · /Qwen3.5-9B (2026-03-02)  
- https://huggingface.co/unsloth/Qwen3.5-2B-GGUF · /Qwen3.5-4B-GGUF · /Qwen3.5-9B-GGUF · https://unsloth.ai/docs/models/qwen3.6  
- https://huggingface.co/Qwen/Qwen3.6-27B · /Qwen3.6-35B-A3B  
- https://huggingface.co/sarvamai/sarvam-30b · /sarvam-105b  
- https://huggingface.co/QCRI/Fanar-1-9B-Instruct · https://huggingface.co/inception42/Jais-2-8B-Chat · https://huggingface.co/silma-ai/SILMA-9B-Instruct-v1.0  
- https://huggingface.co/google/gemma-4-E2B-it · https://huggingface.co/FreedomIntelligence/AceGPT-v2-8B-Chat

### Datasets
- https://huggingface.co/datasets/LingoIITGN/COMI-LINGUA · https://aclanthology.org/2025.findings-emnlp.422/  
- https://huggingface.co/datasets/MohamedRashad/arabic-english-code-switching  
- https://huggingface.co/datasets/community-datasets/tamilmixsentiment  
- SPRING-INX (IIT Madras) via https://huggingface.co/santhosh-005/smart-turn-tamil

### Azure Speech
- https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support  
- https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-identification  
- https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-post-processing  
- https://learn.microsoft.com/en-us/azure/ai-services/speech-service/regions  
- https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe  
- https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-container-overview  
- https://learn.microsoft.com/en-us/azure/ai-services/speech-service/custom-speech-overview  
- https://learn.microsoft.com/en-us/azure/ai-services/speech-service/improve-accuracy-phrase-list  
- https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/post-stream-refinement-is-now-generally-available-in-microsoft-foundry/4540174  
- https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/for-the-first-time-real-time-transcription-goes-multilingual/4539089  
- https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/azure-speech-at-build-2026-powering-voice-agents-with-real-time-and-life-like-ex/4524638  
- MCR tags: https://mcr.microsoft.com/v2/azure-cognitive-services/speechservices/speech-to-text/tags/list · …/neural-text-to-speech/tags/list

### Voice stack
- https://docs.pipecat.ai/api-reference/server/utilities/turn-detection/smart-turn-overview  
- https://docs.pipecat.ai/api-reference/server/services/vad/silero-vad-analyzer  
- https://github.com/pipecat-ai/smart-turn · https://huggingface.co/pipecat-ai/smart-turn-v3  
- https://github.com/pipecat-ai/pipecat/blob/main/CHANGELOG.md (read 2026-09-18: 1.7.0 2026-08-01 `force_locale`; 1.8.0 2026-08-26 `on_user_turn_audio`; 1.9.0 2026-09-10 `segmentation_silence_timeout_ms`, `SpeakingObserver`; 1.11.0 2026-09-17 `eq_telecomhp8k`; no Azure STT LID/phrase list in any release)

### Regulatory
- DPDP Rules 2025 (notified 2025-11-13): https://www.pib.gov.in/PressReleasePage.aspx?PRID=2190014 — phases 2025-11-13 / 2026-11-13 / 2027-05-13

---

## Appendix A — Continuous LID candidate sets

| Tenant mix | Candidates (≤10; one locale per base language) | Notes |
| :--- | :--- | :--- |
| Hindi belt | `hi-IN`, `en-IN` | phrase lists on both; or multilingual PSR open-range (preview) instead of LID |
| Tamil Nadu | `ta-IN`, `en-IN` | no phrase list / no PSR on `ta-IN`; custom speech critical |
| Multi-Indic pilot | `hi-IN`, `ta-IN`, `te-IN`, `en-IN` | test flapping before pan-India |
| Gulf | `ar-AE`, `en-IN` or `en-US` | `ar-SA` only if phrase lists + PSR outweigh locale fidelity — and only outside `uaenorth` |

LID returns one of the candidates **even if none was spoken**; "unsupported language" is an understanding decision (`language=other`).

## Appendix B — Canonical understanding JSON (v2, superset of `_TOOL_SCHEMA`)

```json
{
  "intent": "hardship",
  "confidence": 0.81,
  "sentiment": -0.55,
  "abuse": false,
  "legal": false,
  "unresolved_repeat": false,
  "language": "hinglish",
  "language_tags": ["hi", "en"],
  "english_gloss": "no money this month, job lost, asking for time",
  "stt_locale": "hi-IN",
  "stt_detected_locale": "hi-IN",
  "stt_final_is_refined": true,
  "abstain": false,
  "fail_closed_reason": null
}
```

- `intent` ∈ `ALLOWED_INTENTS` (12 values in code). **No promise fields** — promises are tool/closer owned.  
- `language` is registry-driven (`en, hi, ta, te, kn, mr, bn, gu, hinglish, tanglish, other`; `ar`, `arabizi` when Track B lands).  
- `confidence` is model-reported until calibrated; missing ⇒ `abstain: true`. Treatment/reco consume only `intent`, `sentiment`, `abuse`, `legal`, `unresolved_repeat` — never `english_gloss`.

## Appendix C — Errata log v1 (2026-09-18, Sol + Kimi K3)

| Issue | Fix |
| :--- | :--- |
| Status "build-ready" | Demoted to discovery + Azure experiments |
| Qwen3-only shortlist | Added Qwen3.5-0.8B/2B bake-off |
| `Qwen3-*-Instruct` IDs | Replaced with official IDs |
| Official GGUF cited as Q4 | Official = Q8_0; Q4 = third-party pin |
| ArZen dataset | 404; removed |
| SILMA "gated" | `gated:false` |
| AceGPT/Jais licence | Apache-2.0; Jais `gated:auto` |
| Phrase lists for all Arabic/Indic | Narrowed |
| Fast transcription as live proof | Corrected |
| Custom Speech CS as fact | Feasibility gate |
| VAD+SmartTurn <150 ms | Removed |
| 200–600 ms SLM p95 | Withdrawn |
| Split math / leakage | 80/10/10 per pool, grouped |
| GPL isolation as sufficient | Counsel-driven |
| Fail-closed missing | Contract table |
| "Best Gulf / SOTA Indic" | Hypotheses |
| Qwen3.5 as drop-in peer | §1.1.1 gate |
| COMI-LINGUA tasks | LID, MLI, POS, NER, TN, MT |
| MohamedRashad as Gulf gate | Plumbing only |
| Refinement region omission | §3.2.1 |
| Smart Turn vs PSTN bandwidth | Phase 4 8 kHz condition |
| No BFSI reconstructibility | Decision-log schema |
| Jais ctx | ~8,192 |

## Appendix D — v2 review findings (2026-09-18)

Ordered by what would have hurt most if built as written.

| # | Finding | Evidence | Change in v2 |
| :--- | :--- | :--- | :--- |
| 1 | Appendix B schema did not match the code; promise fields don't belong in understanding | `understanding.py::_TOOL_SCHEMA`, `tools_negotiate.py`, `call_closer.py` | §0, Appendix B rewritten as superset |
| 2 | Missing `confidence` is recorded as 0.9 | `_merge`: `chosen = … else 0.9` | §0.1 fix; contract row |
| 3 | Fail-closed contract already existed; v1 planned to build it | `_merge`, `analyze_turn` | Contract table now marks ✅/❌ per row |
| 4 | Decision log as log lines would be discarded | root logger has no handler in api/voice | Table §0.2 |
| 5 | Pipecat 1.6.0 Azure STT has no LID / phrase list / PSR / segmentation timeout; language switch reconnects | `.venv/…/pipecat/services/azure/stt.py` | Habibi subclass in Phase 1; pipeline diagram corrected |
| 6 | "Azure cannot do intra-sentence CS" is now only true of continuous LID | Multilingual PSR blog + docs, 2026-07-23 | §3.2 rewritten; Hinglish 3-way A/B |
| 7 | Region conflict resolved for India, not Gulf | Regions table 2026-09-16: `centralindia` all ✅; `uaenorth` base only | §3.2.1 table |
| 8 | Arabic absent from product; Gulf treated as co-equal | `languages.py`, prompts, `safety.py` | Two tracks §1.0; Phase 7 |
| 9 | SLM latency conflated with voice-turn latency | `crm_sink.py` analysis queue; docstring | §3.4/§3.5 split; WhatsApp is the critical path |
| 10 | Azure's 500 ms segmentation silence is an untuned third end-pointer | Pipecat 1.9 changelog; Azure default | §3.1 |
| 11 | Shortlist stale: Qwen3.5 small models shipped 2026-03-02 with GGUFs; Qwen3.6/3.8 exist | HF API | §1.1; QA → Qwen3.5-9B |
| 12 | Qwen3.5-2B loop warning on the card | `unsloth/Qwen3.5-2B-GGUF` | Gate item; hard-disable thinking |
| 13 | Tamil EOU model exists (telephony-trained, +16 pts) | `santhosh-005/smart-turn-tamil` 2026-09-17 | §3.1; locale-routed analyzer |
| 14 | MAI-Transcribe-2 (Hinglish CS, verbatim, phrase list) fits post-call + corpus building | Learn page 2026-09-10 | §2.2, §3.4 |
| 15 | On-prem target vs cloud-only features never reconciled | MCR tags: STT 4.12.0 locales; NTTS 3.13.1 lacks Tamil; LID container not disconnected | §3.7 matrix; Phase 8 |
| 16 | Laptop benchmark drift and WSL 4 GB cap not in the method | Prior runs on Btcerlp-016 | §3.6 |
| 17 | STT TTFB already measured (p50 ≈ 1.18 s) but listed TBD | `bot_pipeline.py` | §3.5 |
| 18 | DPDP had no dates | Rules notified 2025-11-13; phases 2026-11-13 / 2027-05-13 | §2.5; Phase 3 |
| 19 | LID "always returns a candidate" makes it unusable for unsupported-language detection | LID docs | §3.2.2 item 4 |
| 20 | Synthetic messy-STT recipe missing | — | §2.2 item 3 (TTS → G.711 → STT) |
| 21 | FP compliance-escalation rate absent from metrics despite OR-merge | `_merge` abuse/legal | §2.4 |
| 22 | Azure Speech SDK version never checked | 1.51.0 installed (PSR ≥1.50) | §0 |
| 23 | Pipecat feature/date mapping taken from a summariser | Read CHANGELOG.md directly: dates corrected; `SpeakingObserver` and `on_user_turn_audio` added; confirmed no Azure STT LID/phrase list through 1.11.0 | §3.1 table |
