# SLM & Multilingual Strategy: Architecture, Code-Switching, and Model Selection

**Product:** Habibi / BigBound AI (Collections Monolith & Voice Runtime)  
**Date:** September 2026  
**Status:** Strategic Architecture & Research Report  
**Target Areas:** `agent_core/understanding.py`, `agent_core/treatment/`, `agent_core/reco/`, `voice/bot_pipeline.py`, `qa_autoscore.py`, `call_closer.py`

---

## 1. Executive Summary

This evaluation analyzes the technical feasibility and ROI of fine-tuning Small Language Models (SLMs) across the Habibi codebase, specifically addressing **multilingual operations (English, Arabic, Tamil, Hindi)** and **intra-call code-switching**.

### Key Conclusions
1. **Never use an SLM for Next-Best-Action (NBA / Treatment) or Product Reco (Offers):**  
   These systems are strictly bounded by RBI Fair Practices Code, DPDP Act, statutory calling windows (08:00–19:00), DND registries, and arithmetic expected value (EV in ₹). They must remain deterministic Python/SQL pipelines.
2. **Unified Multilingual Model Beats Disjoint Models (English vs. Arabic):**  
   Splitting into separate monolingual models shatters on real-world calls due to **intra-sentential code-switching** (borrowers mixing Arabic/English or Tamil/English within the same sentence), language-identification latency taxes, and state desynchronization. A single unified multilingual SLM (e.g., Qwen 2.5) with a shared semantic latent space is the industry-standard winning strategy.
3. **Primary Value Area for Fine-Tuning:**  
   **Per-Turn Conversation Understanding (`agent_core/understanding.py`)** via a 1.5B–3B multilingual SLM (sub-30ms local latency, zero cloud rate-limiting) and **Post-Call QA & Closer (`qa_autoscore.py`, `call_closer.py`)** via a 7B–8B SLM for privacy-preserving on-premise audit evaluation.

---

## 2. Codebase Reality & Architectural Invariants

Habibi operates in a regulated debt-collection environment. The codebase already enforces an intentional architectural boundary:

```
[Customer / Call State]
         │
         ├───► Deterministic Engines (Rules, RBI FPC, EV math, suitability vetoes)
         │        ├── Treatment Engine (NBA: wait, SMS, WhatsApp, bot call, human)
         │        └── Reco Engine (Next-Best-Offer: suitability, held products, cooldowns)
         │
         └───► LLM & Acoustic Layer (Linguistic synthesis, understanding, audio)
                  ├── Understanding (Intent, sentiment, Hinglish/Arabic gloss, abuse/legal)
                  ├── Voice / WhatsApp Bot (Pipecat pipeline, multi-turn tool calling)
                  └── Post-Call Analytics (Call closer, promise extraction, QA auto-scoring)
```

### Component Breakdown & SLM Suitability

| Module | Purpose | Current Implementation | SLM Fine-Tuning Recommendation |
| :--- | :--- | :--- | :---: |
| `agent_core/treatment/` | Next-Best-Action (NBA) | Deterministic gated pipeline: `timing → veto → score (EV INR) → arbitrate → explore → log`. | ❌ **Do Not Replace** (Regulatory Liability) |
| `agent_core/reco/` | Next-Best-Offer (NBO) | Deterministic catalog veto: candidates, eligibility, suitability audit trail. | ❌ **Do Not Replace** (RBI Mis-selling Risk) |
| `agent_core/understanding.py` | Turn Intent & Sentiment | Hybrid: fast keyword baseline + Azure OpenAI analysis call (`chat_with_tools`). | 🟢 **Highest ROI (1.5B–3B SLM)** |
| `voice/bot_pipeline.py` | STT & TTS Pipeline | Pluggable provider matrix (`agent_core/providers/registry.py`) with Speechmatics, Azure, Gladia, Cartesia. | ❌ **Acoustic, Not SLM** (Use Provider Binding) |
| `voice/bot.py`, `bot_runtime.py` | Live Conversational Core | Streaming LLM + dynamic graph tool calling (`flow_graph.py`). | ⚠️ **Marginal / High Risk** (Frontier models needed for tools) |
| `qa_autoscore.py`, `call_closer.py` | Post-call Audit & Summaries | Background workers (`bot_worker`) running 80-turn transcript audits against banking rubrics. | 🟢 **High Value (7B–8B SLM)** |

---

## 3. The Multilingual Dilemma: Unified SLM vs. Disjoint Language Models

### Option A: Disjoint Models (Separate English Model, Separate Arabic Model, Separate Tamil Model)
* **Architecture:** Inbound Audio → Language ID (LID) Router → Route to English Agent OR Arabic Agent.
* **Why This Breaks on Real Calls:**
  1. **Intra-Sentential Code-Switching:** Real borrowers blend languages inside the *same sentence*.
     * *Gulf Arabic / Arabizi:* `"Habibi, sawweyt transfer online bil-mobile app bas it failed, what should I do?"`
     * *Tamil / Tanglish:* `"Enakku salary innum credit aagala, can I pay the balance next week?"`
     * *Hinglish:* `"Paisa nahi hai bhai, company down chal rahi hai, can you give me 10 days?"`
  2. **The Routing Tax & Flapping:** A router takes 200–500ms to analyze an utterance. If turn 1 is English, turn 2 is Arabic, and turn 3 is mixed, the session either flaps between models or misclassifies the turn, causing jarring voice/personality resets.
  3. **3× Operational Footprint:** Three models require 3× GPU VRAM, separate prompt maintenance, disparate fine-tuning datasets, and complex cross-model session synchronization.

### Option B: Single Unified Multilingual Model (Recommended Strategy)
* **Architecture:** A single multilingual SLM trained across a shared semantic latent space.
* **Why This Wins:**
  1. **Seamless Code-Switching:** The model parses mixed vocabulary natively. Concepts map to the same internal representations regardless of script or dialect.
  2. **Language-Agnostic Canonical Layer:** The model extracts standardized canonical signals:
     * Arabic: `"والله ما عندي فلوس هالشهر"` ➔ `{"intent": "hardship", "sentiment": -0.6}`
     * Tamil: `"Kaasu illa, late-aa pay panren"` ➔ `{"intent": "hardship", "sentiment": -0.5}`
     * English: `"I have lost my job, cannot pay"` ➔ `{"intent": "hardship", "sentiment": -0.6}`
     The database, ledger, and treatment engines remain 100% language-agnostic.
  3. **Mirroring:** The model dynamically mirrors the caller’s dialect and linguistic style without requiring an artificial model swap.

---

## 4. The End-to-End Pipeline Reality (Audio-to-Audio)

A language model is only one component of a live voice bot. An end-to-end multilingual call requires coordination across three layers:

```
[Audio In] ──► 1. STT (Acoustic) ──► 2. SLM (Linguistic Reasoning) ──► 3. TTS (Acoustic) ──► [Audio Out]
```

### Layer 1: Speech-to-Text (STT) — The Primary Bottleneck
Standard STT engines fail on code-switching if locked to a single locale (`en-IN` or `ar-AE`).
* **Requirement:** The STT engine must support intra-sentence code-switching.
* **Codebase Alignment:** `agent_core/providers/registry.py` already includes the `code_switch: bool` flag:
  * Speechmatics (`bilingual-ar-en`, `code_switch=True`): Handles Arabic/English switching within one sentence.
  * Gladia (`solaria-1`, `code_switch=True`): Real-time multilingual code-switching across 100+ languages.
  * Whisper Large-v3 Turbo (Groq / local): Auto-detects mixed multilingual streams.

### Layer 2: Small Language Model (SLM) — The Brain
A unified model that simultaneously excels at English, Modern Standard Arabic, Gulf Arabic dialects, and Indic languages (Tamil, Hindi).

### Layer 3: Text-to-Speech (TTS)
Multilingual neural synthesis (Azure Neural Multilingual voices, ElevenLabs Multilingual v2, or Cartesia Sonic) capable of rendering bilingual text without phoneme corruption.

---

## 5. Model Selection Matrix

| Model Family | Arabic Benchmarks | Indic / Tamil / Hinglish | JSON Schema / Tool Adherence | Context Window | Latency Profile | Recommendation |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Qwen 2.5 (3B / 7B)** | ⭐⭐⭐⭐⭐ Exceptional (Beats Jais-13B on Arabic MMLU) | ⭐⭐⭐⭐⭐ Native 152k vocab; retains Romanized & native scripts | ⭐⭐⭐⭐⭐ Best-in-class function calling under 10B | 32k native (up to 128k) | 3B: ~25ms on GPU, ~30 tps on CPU | 🏆 **Primary Choice** for both Understanding (3B) and QA (7B) |
| **Llama 3.2 (3B) / 3.1 (8B)** | ⭐⭐⭐ Moderate | ⭐⭐⭐ Western-biased tokenizer; splits Indic into byte chunks | ⭐⭐⭐⭐ Very good | 128k | Very fast, but token expansion on Arabic/Indic | 🥈 Strong for English-first workflows |
| **Gemma 2 (2B / 9B)** | ⭐⭐⭐⭐ Strong | ⭐⭐⭐ Good | ⭐⭐⭐ Moderate (stricter schema prompt needed) | 8k | Efficient compute | 🥉 Viable alternative |
| **Sarvam-1 (2B)** | ❌ No Arabic | ⭐⭐⭐⭐⭐ Native 10 Indic languages | ⭐⭐ Weak on complex JSON | 8k | Ultra-fast on Indic | Specialized only |

---

## 6. Phased Implementation Roadmap

```
Phase 1: Canonical Standardization (Immediate)
   │  • Ensure all internal database enums & intent codes remain strictly canonical.
   │  • Verify no language-specific keys exist in DB schemas.
   ▼
Phase 2: Unified Multilingual SLM for Understanding (Months 1–2)
   │  • Replace Azure OpenAI dependency in agent_core/understanding.py with Qwen 2.5 3B.
   │  • Fine-tune on historical multi-turn Hinglish and Arabic transcripts with GBNF grammar.
   ▼
Phase 3: Telephony Bilingual Provider Binding (Months 2–3)
   │  • Bind code_switch=True STT providers (Speechmatics/Gladia) in agent_core/providers/registry.py.
   │  • Configure multilingual TTS voices in voice/bot_pipeline.py.
   ▼
Phase 4: Post-Call QA & Closer Local SLM (Months 3–4)
      • Deploy Qwen 2.5 7B on-premise for qa_autoscore.py and call_closer.py.
      • Enforce local DPDP compliance and eliminate cloud API token spend.
```
