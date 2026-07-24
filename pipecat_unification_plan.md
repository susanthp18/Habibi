# Pipecat Unification Plan — BigBound AI

> Grounded in: DeepWiki (`pipecat-ai/pipecat`, `pipecat-ai/pipecat-flows`), Daily Docs (RTVI / Flows / MCP), Context7 (`/pipecat-ai/docs`, `/pipecat-ai/pipecat`), and a full audit of `backend/voice/*`, `bot_tools.py`, `bot_runtime.py`, `sandbox_runtime.py`, Habibi Sandbox Live.

**Goal:** Make voice (Pipecat), WhatsApp/text (`bot_runtime`), and Sandbox share one **context spine**, one **tool catalog**, and one **domain write path** so PTP / disputes / callbacks / upsell / KB / analytics / inbox stay consistent. Keep our UI; use Pipecat runtime + RTVI as the protocol layer — do not embed the stock playground.

**Status:** Living plan after 2 audit↔docs cycles. Do not treat `sandbox_plan.md` as superseded for Sandbox UX; this file owns **channel unification + tool/context architecture**.

---

## 0. Verdict (current state)

| Layer | Reality | Docs alignment |
|-------|---------|----------------|
| Pipeline plumbing | **Strong** — `PipelineWorker` + `WorkerRunner`, Azure STT→LLM→TTS, Flows, summarization, live tuning, CrmSink | Matches modern Pipecat 1.3+ APIs |
| Tooling | **Split brain** — `voice/tools.py` (Flows) ≠ `bot_tools.py` (WhatsApp) | Docs: one `FunctionSchema` / DirectFunction catalog, Flows adapts via `FlowsFunctionSchema` |
| Context | **Fragmented** — `VoiceSession` + prompt bundle + Pipecat `LLMContext` + unused `sandboxPersona` / half-wired `kbSnapshotId` | Docs: CRM facts as `developer` messages (`LLMMessagesAppendFrame`), not prompt bloat; snapshot should hit retrieve |
| Domain writes | **Partial** — voice can create PTP/dispute/callback/note/escalate; **cannot** eligibility/lead/docs; upsell node is speech-only | Domain pages expect real rows (Upsell leads, Documents, Analytics flags) |
| RTVI → UI | **Thin** — Live listens to transcripts + metrics only | Docs: `llm-function-call-*` + `RTVIServerMessageFrame` + `function_call_report_level` |
| Sandbox | Text path ≠ Live CRM path; Live races on `latest.json` | Runner `/start` body should carry session id; avoid shared “latest” file |

**Root cause:** Pipecat is integrated as a **voice transport + Flows script**, not as the **unified agent runtime** for all channels. Tools and context were duplicated instead of shared.

---

## 1. Target architecture

```
                    ┌─────────────────────────────────────────┐
                    │           agent_core (shared)           │
                    │  CallContext · ToolCatalog · Intent     │
                    │  PromptBundle · AgentTuning · Guardrails│
                    │  Domain writers (promises/disputes/…)   │
                    └───────────────┬─────────────────────────┘
           ┌────────────────────────┼────────────────────────┐
           ▼                        ▼                        ▼
   voice/bot.py (Pipecat)    bot_runtime.py (WA)      sandbox_runtime
   Flows + RTVI + STT/TTS    text tool loop           text rehearsal
           │                        │                        │
           └────────────┬───────────┴────────────────────────┘
                        ▼
              Postgres CRM + KB retrieve + analytics
                        │
                        ▼
         Habibi domain pages (deep-link from tool results)
```

### Non-negotiables

1. **One tool catalog** — handlers live in `agent_core/tools/`; voice and WhatsApp are adapters only.
2. **One CallContext** — customer, account, interaction, open work items, KB snapshot, persona, channel, tuning, deployment ids.
3. **Pipecat stays cascaded STT→LLM→TTS + Flows** — do not move collections script to realtime S2S (Flows cannot rewrite tools/context on Gemini Live / OpenAI Realtime today).
4. **No MCP hop for our own DB** — Pipecat `MCPClient` is for *external* MCP servers. In-process `FunctionSchema`/`DirectFunction` is lower latency and correct for CRM. Optional later: expose CRM via MCP only if a third-party agent needs it.
5. **Our UI** — RTVI events feed Sandbox Inspector / Workspace; never embed Voice UI Kit as the product shell.

---

## 2. Gap matrix (docs × code × domain)

### 2.1 Unified context

| Gap | Evidence | Docs fix | Plan |
|-----|----------|----------|------|
| No single CallContext object | `VoiceSession` + bundle dict + `LLMContext` messages | Inject CRM via `LLMMessagesAppendFrame` / transform; keep system prompt lean | Introduce `agent_core.context.CallContext` loaded once at session start; refresh via developer messages on verify / tool writes |
| `sandboxPersona` dead | Set in `bot.py`, never read | Persona → developer message or scenario system overlay | Apply persona into CallContext → append at flow start |
| `kbSnapshotId` half-wired | Session/bundle store it; voice `search_knowledge_base` + `KbEnrichProcessor` ignore it | Snapshot must filter retrieve | Pass `kb_snapshot_id` into all `kb_retrieve.retrieve` calls from voice + text |
| KB product scope wrong for insurance | Voice hard-codes `product_keys=["collections"]` | Tool should choose keys by intent / node | Hub/collections → collections FAQ; upsell/product_faq → insurance product keys (mirror `bot_tools` gating) |
| CRM placeholders stripped; facts only via tools | `_strip_unresolved_crm_placeholders`; hub must call `get_account_position`; `LLMMessagesAppendFrame` today is only for idle/escalate/language nudges — **not** CRM cards | Docs: inject CRM as `developer` messages | After `verify_identity`, push one compact CRM developer card (balance, DPD, open work); keep `get_account_position` as refresh tool |

### 2.2 Tools — catalog & quality

| Gap | Evidence | Docs fix | Plan |
|-----|----------|----------|------|
| Dual catalogs drift | Arg names differ (`promise_date` vs `promisedDate`); WA has extra tools | `FunctionSchema` shared; Flows wraps as `FlowsFunctionSchema` | Migrate handlers to `agent_core/tools/{crm,kb,upsell,docs}.py`; generate OpenAI dicts for WA + Flows schemas for voice |
| Upsell incomplete | `gated_upsell` only has `begin_wrap_up` | Node-scoped tools per Flows best practice | Add `check_product_eligibility` + `capture_lead`; set analytics `upsell_presented` / lead events |
| Missing CRM reads on voice | No `get_customer_context`, payment history, EMI | Global or hub tools | Port as hub/global DirectFunctions (voice-safe compact payloads) |
| Documents | `db.create_document_request` exists; no bot tool | — | Add `request_documents` tool; deep-link Documents page |
| Routing / redaction / inbox | Domain UIs exist; voice writes `interactions` not inbox conversations | — | Phase C: optional `create_inbox_thread` on escalate; routing evaluated at handoff; redaction stays offline on recordings |
| Tool latency | `asyncio.to_thread` per tool + KbEnrich every turn | Keep tools async; avoid enrich-every-turn if tool exists | Make KbEnrich opt-in / intent-gated; cache retrieve; prefer tool-first for explicit FAQ |

**Canonical tool set (target):**

| Tool | Channels | Domain page |
|------|----------|-------------|
| `identify_customer` / `verify_identity` | WA / Voice (adapters, same handler core) | Customers |
| `get_customer_context` | Both | — |
| `get_payment_history` | Both | — |
| `get_emi_schedule` | Both | — |
| `get_account_position` | Voice hub (thin wrapper over context) | — |
| `search_knowledge_base` | Both | Knowledge Base |
| `create_promise_to_pay` | Both | Promises |
| `flag_dispute` | Both | Disputes |
| `request_callback` | Both | Callbacks |
| `check_product_eligibility` | Both | Upsell |
| `capture_lead` | Both | Upsell |
| `request_documents` | Both (new) | Documents |
| `add_customer_note` | Both | — |
| `escalate_to_human` | Both | Inbox / Workspace |
| `pause_for_caller` / `end_call` / disclose | Voice-only | — |

### 2.3 Flows graph

| Gap | Evidence | Docs fix | Plan |
|-----|----------|----------|------|
| Upsell node has no tools | `flows.py` gated_upsell | Focused tools per node | Wire eligibility + capture; transition to wrap_up on decline/success |
| No dedicated FAQ node (OK) | Global KB tool | Flows recommends not dumping all tools every node | Keep global KB; tighten descriptions; intent-gate product keys |
| Context strategy not explicit | Default APPEND only | `ContextStrategyConfig` APPEND vs RESET | Use APPEND globally; RESET only on terminate nodes if needed; summarize via existing `LLMContextSummarizer` (already in bot) — **not** deprecated `RESET_WITH_SUMMARY` |
| Node/tool visibility opaque in UI | No RTVI function events | `RTVIObserverParams.function_call_report_level` | Sandbox: FULL for CRM tools; prod voice: NAME (or NONE for PII-heavy) |

### 2.4 RTVI / Sandbox Live

| Gap | Evidence | Docs fix | Plan |
|-----|----------|----------|------|
| No function-call UI | `useSandboxLiveCall` ignores `LLMFunctionCall*` | Subscribe to started/in-progress/stopped | Inspector Tools tab |
| No CRM entity push | Tools return IDs only to LLM | `RTVIServerMessageFrame` / `send_server_message` | Emit `{type:"crm.entity", entity, id, deepLink}` after PTP/dispute/callback/lead |
| No RAG event | KbEnrich silent to client | Custom server-message | Emit `{type:"rag.hits", query, chunkIds, snapshotId}` |
| Session race | `read_session("latest")` | Runner `/start` body carries custom data | Pass `sessionId` in WebRTC start body; bot loads that file only; kill `latest` as authority |
| HTTP stop ≠ worker cancel | Session file patched; worker dies on disconnect | FE already `disconnect()` then `stopVoiceSandbox` | Keep that order; ensure HTTP stop is idempotent metadata only |
| Text vs Live parity | Text: no tools, hard turn cap; Live: full CRM | Be honest in UI | Mode labels: **Prompt rehearsal** vs **Live CRM call**; text path optionally gains shared tool loop later (Phase D) |

### 2.5 Domain page unification

| Page | Today from voice | Target |
|------|------------------|--------|
| Promises | Create works | Same + return deep-link; optional plan amount tool |
| Disputes | Create works | Same + reason taxonomy aligned with UI |
| Callbacks | Create works | Align DND/window validation with WA payload |
| Upsell | Speech only — **no lead** | Eligibility + capture → `/upsell?id=` |
| Knowledge Base | Weak (collections-only, no snapshot) | Snapshot + product-key routing; inspector shows hits |
| Bot Analytics | Partial (no upsell flags) | Set `upsell_presented`, lead captured, tool latency metrics |
| Inbox | Not wired | Escalate creates/links conversation; agent presence aware |
| Documents | Not wired | `request_documents` tool |
| Routing | Not evaluated on voice | On escalate, apply routing rules → assignee queue |
| Redaction | Offline recordings | Keep offline; ensure recording metadata links to interaction |
| Prompt Studio / Sandbox | Tuning + promote | Promote already pins tuning/KB; Live must honor both |

### 2.6 Infra / bottlenecks

| Gap | Plan |
|-----|------|
| Separate processes (FastAPI :8000 + voice :7860) | Keep for hackathon; document start order; long-term: host bot workers from FastAPI via `WorkerRunner(auto_end=False)` or Pipecat Cloud |
| Vite `/voice-rtc` proxy | Keep; prefer runner `/start` with body `{sessionId}` over ad-hoc offer-only if client SDK supports it |
| Thread pool for sync DB | Batch CRM load into CallContext at verify; tools become thin writes |
| KbEnrich every turn | Gate by intent / cooldown / disable when global KB tool used recently |
| India → East US RTT | Keep keep-alive pool; surface TTFB honestly in Metrics; no fake “instant” claims |
| Concurrent Live sessions | Session-id file routing + optional in-memory registry keyed by WebRTC peer |

### 2.7 Already good (do not regress)

- Modern `PipelineWorker` / `WorkerRunner` / `from pipecat.flows import FlowManager`
- Lean voice system prompt + guardrails overlay
- Live `AgentTuning` via RTVI client-message + `LLMUpdateSettingsFrame` / TTS frames
- CrmSink off the audio critical path
- Flows node graph for collections (greet → verify → hub → PTP/dispute/upsell)
- Text Sandbox KB snapshot filter (server path) + Promote bundle fields
- Auto context summarization wiring in `bot.py`

---

## 3. Design: CallContext

```python
# agent_core/context.py (target shape)
class CallContext:
    channel: Literal["voice", "whatsapp", "sandbox_text", "sandbox_live"]
    customer_id / account_id / interaction_id
    customer_card: dict          # compact facts for LLM
    open_work: {
        promises: [], disputes: [], callbacks: [], leads: [], document_requests: []
    }
    kb_snapshot_id: str | None
    product_keys_default: list[str]
    persona: dict | None         # sandbox
    prompt_version_id / deployment_id / tuning: AgentTuning
    bot_id / session_id
```

**Injection rules (docs-aligned):**

1. System prompt = identity + guardrails + channel voice rules only.
2. On verify success → `LLMMessagesAppendFrame([{role:"developer", content: crm_card}])`.
3. After mutating tools → append short developer delta (`PTP created id=…`) **and** RTVI server-message for UI.
4. Never re-render full system prompt mid-call for CRM numbers.

---

## 4. Design: Tool adapters

```
agent_core/tools/
  schema.py          # ToolSpec → FunctionSchema + OpenAI tool dict
  handlers.py        # pure async/sync handlers(ctx, args) → ToolResult
  voice_adapter.py   # ToolSpec → FlowsFunctionSchema (+ node transition helpers)
  text_adapter.py    # ToolSpec → bot_runtime TOOL_DEFINITIONS + execute_tool

voice/tools.py       # thin: session binding, node hops, disclose/pause/end only
bot_tools.py         # thin re-export or deleted after migration
```

`ToolResult` always includes: `ok`, `spoken_summary` (short), `entity`/`id`/`deepLink` (optional), `analytics_flags` (optional).

---

## 5. Design: RTVI event contract (BigBound)

| Message | Direction | Purpose |
|---------|-----------|---------|
| `tuning_delta` | Client → Server | Already implemented |
| `llm-function-call-*` | Server → Client | Native RTVI; enable FULL in sandbox |
| `server-message` `crm.entity` | Server → Client | Deep-link chips in Inspector / toast |
| `server-message` `rag.hits` | Server → Client | RAG tab in Live |
| `server-message` `flow.node` | Server → Client | Show current Flows node |
| `server-message` `context.card` | Server → Client | Debug CallContext snapshot (sandbox only) |

Frontend: extend `useSandboxLiveCall` listeners; add Inspector **Tools** + feed RAG/Intent tabs from server messages.

---

## 6. Implementation phases

### Phase A — Spine (must-have) — ~1–2 days

1. `agent_core/context.py` + loaders (customer card, open work).
2. Extract shared handlers from `bot_tools` into `agent_core/tools`.
3. Voice adapter: rewire Flows tools to shared handlers (keep node-hop wrappers in `voice/tools.py`).
4. Pass `kb_snapshot_id` + dynamic `product_keys` into voice KB paths.
5. Apply `sandboxPersona` as developer message at Live start.
6. Session-id routing: start body / session file keyed by id; stop using `latest` as authority.

**Exit:** Same PTP/dispute/callback behavior; WA and voice share handler code for overlapping tools; Live honors KB snapshot.

### Phase B — Upsell + Documents + Analytics — ~1 day

1. `gated_upsell` tools: eligibility + capture_lead.
2. Analytics flags on interaction / lead.
3. `request_documents` tool + Documents deep-link.
4. Align callback validation with WA.

**Exit:** Completing a Live call with consent creates a real Upsell lead visible on `/upsell`.

### Phase C — RTVI observability + domain UX — ~1–2 days

1. `RTVIObserverParams.function_call_report_level` for sandbox.
2. Emit `crm.entity` / `rag.hits` / `flow.node` server messages from tools / KbEnrich / FlowManager hooks.
3. Habibi: Tools tab, deep-link buttons, Live Inspector parity with text mode.
4. Escalate → routing rule evaluation → optional inbox conversation link.

**Exit:** Demo can point at Inspector showing tool calls + click into Disputes/Promises/Upsell.

### Phase D — Text Sandbox tool parity (optional) — ~1–2 days

1. Text sandbox turns call shared tool loop (or a subset) under a max-tools budget.
2. Or keep text as prompt-only rehearsal and lock Live as the only CRM path — **product decision**; UI must say which.
3. Pipecat `evals` YAML scenarios for critical tools (PTP, dispute, lead).

**Exit:** Reproducible eval suite for collections + upsell happy paths.

### Phase E — Hardening (post-hackathon / if time)

1. In-process worker host from FastAPI (no dual-port footgun).
2. Concurrent session registry.
3. Intent-gated KbEnrich / retrieve cache.
4. External MCP only if needed for third-party tools.
5. Migrate any remaining deprecated Pipecat APIs as versions bump.

---

## 7. Explicit non-goals (cycle decisions)

| Temptation | Why reject |
|------------|------------|
| Embed Pipecat Voice UI Kit / playground | Product must stay BigBound UI |
| Switch collections to OpenAI Realtime / Gemini Live | Flows needs mid-call tool/context rewrite — unsupported on S2S |
| Wrap Postgres CRM as MCP server for our own bot | Extra hop; docs intend MCP for external servers |
| One giant prompt with all tools always on | Flows designed to prevent this |
| Unify Inbox as the sole voice transcript store in Phase A | Voice already has interactions; link on escalate first |
| Rewrite WhatsApp to full Pipecat pipeline now | Share tools/context first; transport unification later |

---

## 8. Acceptance criteria (definition of “unified”)

1. **Single handler** for `create_promise_to_pay` / `flag_dispute` / `request_callback` / `capture_lead` / `search_knowledge_base` used by voice and WhatsApp.
2. **CallContext** visible in Sandbox Live (debug) and injected as developer CRM card after verify.
3. **KB snapshot** from Sandbox filters Live retrieve hits.
4. **Upsell lead** row appears after consent on Live call.
5. **Inspector** shows tool name + result summary + deep-link for CRM writes.
6. **Bot Analytics** reflects voice upsell + handoff + PTP rates without channel holes.
7. **No `latest.json` race** — two sandbox sessions cannot steal each other’s bundle.
8. Mode copy makes Text vs Live purpose obvious.

---

## 9. Doc references (pin)

- Flows: focused nodes + `global_functions` — https://docs.pipecat.ai (Flows overview / FlowManager)
- Context strategies — APPEND / RESET; prefer `LLMSummarizeContextFrame` over deprecated `RESET_WITH_SUMMARY`
- Function calling — `LLMContext(tools=...)`, `LLMSetToolsFrame`, DirectFunction
- CRM injection — `LLMMessagesAppendFrame` developer role
- RTVI — `RTVIObserver` function-call report levels; `RTVIServerMessageFrame`; client `onServerMessage` / `LLMFunctionCall*`
- MCP — `MCPClient` for external tools only (`pipecat-ai[mcp]`)
- Orchestration — `PipelineWorker` + `WorkerRunner` (not `PipelineTask` / `PipelineRunner`)
- Evals — `pipecat.evals` scenario YAML

DeepWiki entry points: Context System §3.6, RTVI §3.11, Function Calling §8.1, Memory §8.6, Migration §8.7.

---

## 10. Cycle log (plan refinement)

### Cycle 1 — Docs + codebase audit

- Found dual tool catalogs, speech-only upsell, dead persona/snapshot wiring, thin RTVI, `latest` session race.
- Confirmed pipeline stack already on modern Worker APIs.

### Cycle 2 — Cross-check plan vs code + docs

- **Kept:** Shared tool spine over MCP-for-CRM (docs + latency).
- **Kept:** Cascaded + Flows (S2S incompatible with Flows).
- **Added:** Documents tool, analytics flags, escalate→routing/inbox as Phase C (not A).
- **Added:** Explicit Text vs Live product honesty (Phase D decision).
- **Corrected:** Text sandbox already filters KB snapshot — gap is **Live voice**, not text.
- **Corrected:** Voice already uses `LLMMessagesAppendFrame` for compliance nudges (idle/escalate/language), **not** CRM cards — CallContext injection after verify is net-new; pattern already proven in-repo.
- **Corrected:** FE Live stop already disconnects WebRTC then hits HTTP stop — not a FE bug; remaining risk is bot still binding config via `read_session("latest")` while start also writes a per-id file.
- **Added:** KbEnrich gating (bottleneck) and eval suite.
- **Rejected:** Full WhatsApp→Pipecat transport rewrite in this plan.

### Cycle 3 — Residual gaps check (final)

Searched for remaining plan holes:

| Question | Answer |
|----------|--------|
| Is there a third catalog (sandbox text tools)? | No tools today — only chat completion + retrieve; covered in Phase D |
| Does promote already pin tuning/KB? | Yes — honor in Live retrieve/tuning load (Phase A) |
| Payment-plan / keep-break PTP tools? | Nice-to-have; not blocking unification — backlog under Promises page |
| Multi-language / redaction live? | Out of scope; recordings → redaction offline |
| Twilio prod parity with Sandbox Live? | Same `voice.bot` — fixing tools/context fixes both |
| Is CRM already injected as developer messages? | No — only tool `get_account_position` + stripped prompt; AppendFrame used for idle/safety only |
| Does FE forget to disconnect on stop? | No — already correct; don’t list as a gap |
| Does start write both `latest` and `{sessionId}`? | Yes (`voice_sandbox.py`) — bot ignores the id file today |

**Conclusion:** Architecture is stable. No further plan iterations without implementation. Execute Phases A→C in order.

---

## 11. Suggested first PR slice (when implementing)

1. `agent_core/tools` extraction for overlapping CRM tools (no behavior change).
2. Voice `search_knowledge_base` + KbEnrich: `kb_snapshot_id` + product_keys by intent.
3. Persona developer message + session-id file load.
4. `gated_upsell` + capture_lead/eligibility.
5. RTVI function_call_report_level + `crm.entity` messages + FE Tools tab.

Order preserves demo safety: shared code first, visible CRM wins second, observability third.
