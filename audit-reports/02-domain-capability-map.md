# Domain Capability Map

**Repo:** [susanthp18/Habibi](https://github.com/susanthp18/Habibi) at `D:\Hackathon`
**Companion:** [01-repository-xray.md](./01-repository-xray.md) (topology). This document reconstructs *what the product does*, from implementation.
**Date:** 2026-09-01
**Scope:** `Habibi/` + `backend/`. Guest tree `PRAXIST-main/` is out of scope. Read-only except this file.
**Glossary:** `CONTEXT.md`. Terms in **bold** are that glossary. Where code disagrees, the drift is named.

Evidence from five parallel analyses: domain discovery, business logic, API/flow, data model, UI capabilities. Claims below are from code, SQL, workers, and UI routes — not from folder names or sidebar grouping.

---

## 1. How the product actually works

A regulated collections platform. Autonomous **Mouths** speak to borrowers on voice and WhatsApp. Operators work a CRM. **Locked Engines** — not the language model — decide money, contact, and consent.

The implementation is a **single bounded product with several strong internal seams and one integration hub**. It is not yet a set of independently deployable domains. The hub is `interactions` plus two god modules (`backend/db.py` ~16.5k lines, `backend/main.py` ~4.5k lines, all ~170 HTTP routes). The seams that *do* exist are real: contact admission, mouth publish, outbound attempt → **Outcome** → **Cadence**, and four locked engines with append-only decision logs.

Dev UI defaults to `USE_MOCK=true` (`Habibi/src/api/config.ts`). Screens exist even when they are not talking to the API. Capabilities below are judged live if SQL, routes, workers, and tests exist — not if a mock seed paints the page.

```text
Borrower ──voice/WhatsApp──► Mouth (card + grant + flow)
                                 │
                                 ├── Locked engines dispose (treatment, reco, authority, live QA)
                                 ├── Contact policy admits or vetoes outreach
                                 └── CRM tools write promises / disputes / leads / wrap-up
                                        │
Operator ──Habibi CRM──────────► same Postgres book + work_items view
```

---

## 2. Language vs implementation

`CONTEXT.md` is the intended vocabulary. SQL, HTTP, and UI still carry the previous spelling. This is not cosmetic: it is how the same concept acquires multiple models.

| Glossary | What the code usually says | Where it hurts |
|---|---|---|
| **Mouth** | `bots`, `bot_id`, “Bot configuration”, “Bot analytics” | Identity table is `bots`; every FK follows |
| **Agent Card** | `prompt_versions.agent_card` jsonb (aligned) + leftover “prompt studio” | Two HTTP surfaces for one editor |
| **Mission** | `objective` on `call_attempts`, `campaign_runs`; `/outbound/campaigns` | Mission is JSON on the card, not a table |
| **Cadence** | `cadence.py`, `call_cadence_state` | Aligned |
| **Outcome** | `call_outcomes` (aligned) vs `interactions.disposition` (legacy) vs UI “disposition” | Three words for one settlement |
| **Handoff** | Tool `handoff_to_agent` (glossary) vs UI “Handoff hub” (human **transfer**) vs nav “Routing / logic” (`routing_rules`) | Three mechanisms, one word |
| **Tool Grant / Offer** | Canonical `agent_core/tools/grant.py` **is not imported by runtime** | Seven live formulas remain |
| **Gate** | Compile G0–G15 (aligned) vs contact `admit()` (also a gate) | Two “gate” meanings |
| **Offer** | Reco product offer vs tool **Offer** vs treatment action vs authority waiver | Four engines, one English word |
| **Transfer** (human) | `escalate_to_human`, `warm_transfer_to_supervisor`, `STATE_TRANSFERRED` | Partially reserved as intended |

Do not treat sidebar groups as domains. “Routing / logic” is inbound dispatch. “Handoff hub” is human claim. “Decision intelligence” is the treatment engine. “Agent studio” is the **Mouth**.

---

## 3. Domain map (from coupling, not nav)

Nine domains hold together under load. Three more are real but weak. The rest are platform.

### Strong (independent language + lifecycle + data)

| Domain | Language | Lifecycle | Store |
|---|---|---|---|
| **Contact policy** | `admit`, purpose, cap, veto | Append-only `contact_events` | `03_consent.sql`, `contact_policy.py`, `policy_rules.py` |
| **Mouth publish** | card, **Gate**, **Deployment**, **Flow**, **Reachability** | draft → compile → publish → deploy | `prompt_versions`, `bot_deployments`, `agent_core/cards/` |
| **Outbound attempt** | reserve → suppress/dial → terminal | `call_attempts.state` (17 values) | `21_outbound.sql`, `outbound.py` |
| **Mission / Cadence / Outcome** | mission brief, mechanical retry, closed codes | case-scoped; Closer writes **Outcome**; cadence does not change the action | `mission.py`, `cadence.py`, `call_closer.py`, `call_outcomes`, `call_cadence_state` |

### Medium (own engines and logs; enact through other domains)

| Domain | What it owns | What it borrows |
|---|---|---|
| **Treatment** (locked) | Next contact *action*; holds; shadow/live | Enacts via outbound / WhatsApp; vetoes via contact policy |
| **Reco / NBO** (locked) | Next *product* offer; leads | Products, promotional consent, treatment hold veto |
| **Authority** (locked) | Fee-waiver verdict + INR cap | Ledger on enact; identity on the call |
| **Live QA** (locked) | Same-call barge/whisper/score | Voice turn stream |
| **Skill packs** | Signed procedural knowledge | Attached to cards; intersected into the grant |
| **Book** (customer + account) | Party, account, EMI, ledger, products | Read by almost every engine |

### Weak as a module boundary (cohesive entities, no owner module)

| Domain | Why it is still a domain | Why it is not a context yet |
|---|---|---|
| **Collections resolution** | Distinct lifecycles: promise, plan, dispute, callback, document, follow-up | All CRUD lives in `db.py`; no application service |
| **Human ops** | Inbox takeover, floor, human **transfer** queue | Three channels, one word “handoff” in the UI |
| **Inbound routing rules** | Own tables + DSL | Evaluator lives in `db.py`; outside the locked-engine model |

### Not a domain (on purpose)

- **`interactions`** — hub entity. Voice, WhatsApp, human wrap-up, QA, redaction, billing, and engines all hang off `interaction_id`. Splitting it would be a product change, not a cleanup.
- **Analytics / dashboard** — read models over the book and interactions.
- **Identity, billing metering, providers, webhooks plumbing, MCP/vault, observability** — platform. They serve every domain and contain almost no collections semantics.

```text
                    ┌── Contact policy ──────────────────────────┐
                    │                                            │
 Book ──────────────┼── Treatment ──enact──► Outbound attempt ───┤
                    │                          │                 │
                    │                          ├── Cadence       │
                    │                          └── Outcome       │
                    │                                            │
                    ├── Reco ──► Leads                           │
                    ├── Authority ──► Ledger                     │
                    └── Collections resolution (PTP, dispute…)   │
                                                                 │
 Mouth publish ──► Tool Grant ──► Voice / WhatsApp runtime ──────┘
      │
      ├── Flow, Skill packs, Deployment
      └── Locked engines bound on the card
```

---

## 4. Capability catalog

Each capability is listed as a stack. Empty layers are written `—` rather than invented. “Owner” is who *does the work today*, not who should.

### How to read a stack

```text
Capability
├── UI
├── API
├── Application service     (often missing — handler → db.py)
├── Domain logic
├── Persistence
├── Integrations
└── Tests
```

---

### 4.1 Book — customer and account

**Purpose.** One borrower, their delinquent accounts, EMI, ledger, notes, and product holdings. The book is the fact source every engine reads.

| Layer | Implementation |
|---|---|
| **UI** | `/customers`, `/customers/$customerId` (`OverviewTab`, `LedgerTab`, `EmiTab`, `NotesTab`, `QuickActionsRail`) |
| **API** | `GET /customers`, `GET /customers/{id}`, `GET /customers/{id}/insights`, `POST /customers/{id}/notes`, `GET /products` |
| **Application service** | — handlers in `main.py` call `db.*` |
| **Domain logic** | `customer_insights.py` (derived NBA); tools in `agent_core/tools/domain.py` / `bot_tools.py` for spoken reads; `money_inr.py` for display |
| **Persistence** | `customers`, `customer_notes`, `accounts`, `ledger_entries`, `emi_installments`, `products`, `product_eligibility_rules` (`02_customer_account.sql`) |
| **Integrations** | — |
| **Tests** | `tests/test_customer_insights_api.py`, `tests/test_customer_memory_roundtrip.py` |
| **Validation** | DB CHECKs on `customers.risk`; Pydantic `CustomerResponse` flattens **one** primary account |
| **Business rules** | Risk band on the customer; DND flag duplicated with consent (`customers.dnd` vs `consent_records.dnd_registry`) |
| **Events** | `activity_events` on mutations |
| **Background** | — |
| **Config** | tenant GUC `app.tenant_id` |

**Split model:** `CustomerResponse` presents 1:1 customer↔account. SQL is 1:N. Insights NBA is a read model over treatment/reco, not book state.

---

### 4.2 Promise to pay (PTP)

**Purpose.** Capture a commitment to pay, send a pay link, remind, settle against the ledger.

```text
Promise to pay
├── UI          /promises, Customer 360 PromisesTab + ActionSheets
├── API         GET/POST/PATCH /promises, POST /promises/{id}/resend-confirm
│               GET/POST /payment-plans
│               GET/POST /pay/{token}  (public hosted checkout)
│               POST /webhooks/payments/{provider}
├── App         — (create in db.create_promise)
├── Domain      promise_fulfillment.py (fulfill, remind, settle)
│               payments.py (intent + webhook → ledger)
├── Persist     promises, promise_reminders, payment_plans,
│               promise_installments, payment_intents
├── Integrate   Razorpay / hosted PSP; WhatsApp/SMS confirm
└── Tests       tests/test_promise_fulfillment.py
```

| Concern | Detail |
|---|---|
| **Business rules** | IST date: `upcoming → due_today → broken`; payment → `kept` / `partial`; broken PTP triggers treatment (`promise_fulfillment.settle_promises`) |
| **Validation** | DB: five statuses including `due_today`. `PromiseResponse` omits `due_today`; `PromiseListResponse` includes it. Reminder enum is 6 values in SQL, narrower in some Pydantic models |
| **Events** | `webhooks_dispatch`: `promise.created\|kept\|broken`; `activity_events` |
| **Background** | `bot_worker`: settle every 20 ticks; `process_one_reminder` |
| **Config** | contact policy for statutory/confirm sends; `BLOCKING_CONSENT` frozenset copied in this module |
| **UI rules** | `promises-seed.ts` `computeMetrics` / `filterPromises` (mock); live 360 tab is read-only — queue owns kept/broken |

**Parallel state (one PTP, three status columns):**

| Object | Statuses |
|---|---|
| `promises.status` | upcoming, due_today, kept, broken, partial |
| `promises.reminder_status` | off, queued, scheduled, sent, acknowledged, failed |
| `payment_intents.status` | created, sent, opened, paid, expired, failed, cancelled |

Payment plans: DB `active`; API computes `on_track \| slipped \| completed` in `db.list_payment_plans()`. Installments reuse the promise status enum.

---

### 4.3 Disputes

**Purpose.** Exception cases on an account, with evidence, notes, and an SLA clock.

| Layer | Implementation |
|---|---|
| **UI** | `/disputes` Kanban; 360 `DisputesTab` |
| **API** | `GET/POST/PATCH /disputes`, notes, evidence |
| **Domain logic** | `db._dispute_sla()` — warn at 25% of filing→due window. **Lives in the repository.** |
| **Persistence** | `disputes`, `dispute_evidence` |
| **Tests** | `tests/test_dispute_sla.py`; UI mirror `Habibi/src/data/dispute-sla.test.ts` |
| **Background** | — (appears on `work_items` view) |
| **UI rules** | Live UI **displays** API SLA fields and does not recompute. Mock copies `_dispute_sla` line-for-line (`dispute-sla.ts`: “change one, change both”) |

Statuses: `new \| under_review \| awaiting_customer \| resolved \| rejected`. SLA is computed, not a status.

---

### 4.4 Callbacks, documents, follow-ups, mandates

| Capability | Purpose | UI | API | Domain | Persist | Background |
|---|---|---|---|---|---|---|
| **Callbacks** | Schedule a human/agent return call | `/callbacks` | `/callbacks`, reminders | CRUD in `db.py`; UI `autoMarkMissed` in mock | `callbacks`, `callback_reminders` | `work_items` |
| **Document desk** | Request / generate / send borrower documents | `/documents`; 360 tab | `/document-requests`, ingest, delivery-attempts | `db.py`; source includes crm/vision/clerk/mcp | `document_*` | — |
| **Follow-ups** | Work items tied to a promise **xor** a lead | Workspace + upsell | `/followups`, lead followups | `followups_db.py` | `followups` | `worker.py` overdue sweep (~10 min, escalate only — no contact) |
| **Mandates** | Auto-debit re-presentment | No dedicated route; 360 insights | Treatment features / simulation | `treatment/policy._mandate_*` | `mandates`, `mandate_presentations` | treatment enact |

360 **writes through** the same POST endpoints as the queues for PTP, disputes, and documents. Queues own workflow UX. Callbacks from 360 NBA still toast “coming soon”.

---

### 4.5 Consent and contact policy

**Purpose.** Whether outreach is allowed *now*, on this channel, for this purpose. Fail-closed. This is the strongest seam in the codebase.

```text
Contact admission
├── UI          /consent; Customer 360 ContactabilityPill
├── API         GET/PATCH /consent, POST /consent/{id}/opt-out
│               GET /customers/{id}/contact-policy
├── App         db.get_contact_policy → contact_policy.evaluate
├── Domain      contact_policy.admit / _veto
│               policy_rules.resolve (versioned layers, tighten-only)
│               compliance_copy.footer (RBI ¶100AA grievance officer)
├── Persist     consent_records, channel_consents, optout_events,
│               contact_events, contact_day_counters,
│               policy_rule_sets, policy_rules, contact_delivery_events
├── Integrate   — (enforced before Twilio / Meta send)
└── Tests       tests/test_contact_policy.py, tests/test_outbound_completion.py
```

| Concern | Detail |
|---|---|
| **Business rules** | Channel opt-out / DND / expired; customer DND; RBI 08:00–19:00 voice; borrower window; cooling-off; daily/weekly caps; DPDP promotional vs servicing (`DATA_PURPOSES` vs outreach `PURPOSES` — two deliberate axes) |
| **Locked?** | Card binds `dnd`. Enforcement is a shared module, not a per-card engine. Required policy key on the card. |
| **Invokers** | `outbound.place`, `treatment/enact`, promise confirm, payment bounce voice, `main.py` dial handlers |
| **Config** | `policy_rules` rows; fallback constants; `demo_ignores_window` platform switch |
| **Events** | `contact_events` (allowed/denied); `consent.dnd.updated`, `consent.opted_out` webhook keys; delivery transitions |
| **UI logic** | Production displays the API verdict. Mock `contact-policy.ts` `mockVeto()` ports `_veto` but **skips cooling-off and caps** (`outreachToday: 0`). Consent UI uses `call` not `voice`, and `optedIn: boolean` vs four SQL statuses |

**Duplication:** `BLOCKING_CONSENT` restated in `contact_policy.py`, `promise_fulfillment.py`, `payment_events.py`. RBI hours restated in `live_qa/checks.py` and the frontend mock.

---

### 4.6 Mouth, Agent Card, Flow, Deployment

**Purpose.** Author one speaking surface, compile it, publish it, put one version live.

```text
Mouth publish pipeline
├── UI          /agent-studio, /agent-studio/$botId (PromptStudioPage)
│               /prompt-studio redirects here
├── API         /agent-studio/cards*  AND  /prompt-versions*
│               /bot-deployments*, /flow/*, /persona-presets, /tts-*
├── App         main.py publish handlers
├── Domain      agent_core/cards/schema.py, compile.py (G0–G15, G-OB*)
│               agent_core/deployment.py, canary.py, change_log.py
│               flow_graph.py, voice/flows_dynamic.py
├── Persist     bots, prompt_versions (Mouth + Card JSON), bot_deployments,
│               deployment_experiments, tts_*, persona_presets
├── Integrate   Azure Speech / Fish / OpenRouter TTS catalog
└── Tests       test_agent_card_compile.py, test_flow_graph_authoring.py,
                test_outbound_card_vocabulary.py, test_agent_studio_card_persistence.py
```

| Concern | Detail |
|---|---|
| **Business rules** | **Gates** are pass / block / skip — never green for a skipped check. Locked engines cannot be unbound (`LOCKED_POLICY_ENGINES`). Cardless mouth → no tools (ADR-0002). **Reachability**: entry / handoff / direct / unreachable |
| **Validation** | Compile report; flow `validateFlow` also in UI (`api/flow.ts`, live-only — no mock) |
| **Config** | Card JSON; env for TTS providers; canary `auto_rollback` triggers from schema (shared with compile — previously drifted) |
| **Events** | Hash-chained entries in `audit_log` (`agent.publish`, rollback, archive) — no `change_log` table |
| **Split surface** | `POST /prompt-versions/{id}/publish` and `POST /agent-studio/cards/{bot_id}/publish` (resolves draft, same publish). UI is one `PromptStudioPage` (~authoring god component) |

**God JSON:** `prompt_versions` holds persona, voice, guardrails, **flow**, **agent_card** (tools, handoffs, missions, locked engines), tuning. The **Agent Card** is not a table.

`LOCKED_POLICY_ENGINES` = `recommend_next_offer`, `recommend_treatment`, `evaluate_authority`, `evaluate_live_qa`. Only the first and third are in the mouth tool catalog (`LOCKED_MOUTH_TOOLS`). Treatment and live QA are Python engines bound on the card with no mouth tool yet.

---

### 4.7 Skill packs

**Purpose.** Procedural knowledge pinned to a card. Passive: a pack never decides when it applies. Loading a skill narrows the **Offer**, never widens the **Tool Grant** (ADR-0001).

| Layer | Implementation |
|---|---|
| **UI** | `/agent-studio/skills/*`; Skills tab on the card |
| **API** | `/agent-studio/skills*` CRUD, sign, attach, import/export, run-script; `POST /kb/gaps/{id}/promote-skill` |
| **Domain** | `agent_core/skills/{persist,runtime,pack,sign,lint,gardener,intersect}.py`; stock packs under `agent_core/skills/packs/` |
| **Persistence** | `skills`, `skill_versions`, `skill_attachments` |
| **Background** | `worker.py` gardener daily 03:10 UTC from KB gaps |
| **Tests** | `test_skills_phase2.py`, `test_skill_crud.py`, `test_skill_packs_fail_closed.py` |
| **Business rules** | Unsigned packs fail closed; G9 compile intersects attached packs into the grant |

---

### 4.8 Tool Grant and Offer

**Purpose.** Everything a mouth **may** execute (**Grant**), vs what the model is **shown** this turn (**Offer** ⊆ Grant). Safety is the grant. Offer narrowing is a cost decision.

| Layer | Implementation |
|---|---|
| **UI** | Tools tab; `/flow/tools` inspector |
| **API** | `GET /flow/tools` (catalog). No grant endpoint |
| **Domain (canonical)** | `agent_core/tools/grant.py` — ADR-0001 owner. **Production runtime does not import it.** Comment: “Nothing imports this yet.” Importers: `tests/test_tool_grant.py`, `tests/test_tool_grant_characterization.py` only |
| **Domain (live)** | `agent_core/skills/intersect.py` `effective_tools` / `offered_tools`; `voice/tools.py` `ALWAYS_ON`; `flow_graph.py` `_FLOW_CONTROL_TOOLS`; compile G6/G9 |
| **Persistence** | No grant table. Audit: `bot_tool_calls` |
| **Tests** | Characterization tests **pin** `VOICE_ALWAYS == voice.tools.ALWAYS_ON` so the four formulas cannot silently diverge further |

This is the highest-risk duplicated capability. Publish and runtime have already disagreed once (connectors omitted from the gate — the bug ADR-0001 records). Agent-to-agent **Handoff** cannot be correct until the grant is recomputed from the receiving card (ADR-0001 consequence).

---

### 4.9 Locked Engine — Treatment

**Purpose.** Next-best *contact action* for a delinquent account. The model does not choose the ladder.

```text
Treatment
├── UI          /treatment (“Decision intelligence”); 360 NBA card
├── API         /treatment/next, insights, metrics, models, holds, cases
├── App         db.next_treatment / _treatment_snapshot
│               (snapshot may WRITE a decision row on GET — documented)
├── Domain      agent_core/treatment/{engine,policy,arbitration,
│               scoring,timing,enact,followthrough,sweep,decisions}.py
├── Persist     treatment_decisions, treatment_holds,
│               treatment_model_registry, capacity_duals, mandates
├── Integrate   enact → outbound.place / WhatsApp / mandate presentment
└── Tests       test_treatment_engine.py, test_treatment_followthrough.py,
                test_treatment_wiring.py, test_decision_intelligence_p*.py
```

| Concern | Detail |
|---|---|
| **Business rules** | Vetoes (holds, bucket, field proportionality, mandate, EMI timing, self-service job, contact delegation) then score/arbitrate. Cadence retries the **same** action; treatment picks a **new** one on follow-through |
| **Outcomes** | `reached \| no_answer \| paid \| ptp \| refused \| undeliverable \| cancelled \| superseded \| unresolved` |
| **Background** | `bot_worker`: enact (live), follow-through (shadow+live), sweep if `TREATMENT_SWEEP=1` |
| **Config** | `TREATMENT_MODE` = off / shadow / live; `TREATMENT_SWEEP` |
| **Events** | append-only `treatment_decisions`; `call_attempts.decision_id` |

Cross-engine: `treatment/policy.suppresses_upsell()` is a reco veto. Mission `NEVER_OFFER` blocks hardship/mandate/broken-PTP objectives.

---

### 4.10 Locked Engine — Reco (upsell)

**Purpose.** Next-best *product offer* during a conversation. Parallel to treatment: different object (product vs contact action).

| Layer | Implementation |
|---|---|
| **UI** | `/upsell`; 360 `OfferPolicyBlock`; `/offers/health` panel |
| **API** | `/leads*`, `/offers/health`, `/offers/tuner-suggestions` |
| **Domain** | `agent_core/reco/{engine,arbitration,policy,scoring}.py`; `capture.py` eligibility; tool `recommend_next_offer` |
| **Persistence** | `leads`, `lead_eligibility`, `product_relations`, `product_campaigns`, `offer_decisions` |
| **Tests** | `test_reco_engine.py`, `test_offer_policy.py`, `test_lead_pipeline.py`, `test_lead_eligibility.py` |
| **Background** | `worker.py` lead revalidation 01:15 UTC |
| **Config** | Reco mode; promotional consent; treatment hold |

**Naming collision:** `product_campaigns` (NBO marketing switches) vs `campaign_runs` (dial batches). Glossary forbids “campaign” for **Missions**.

---

### 4.11 Locked Engine — Authority

**Purpose.** Model may *ask* for a fee waiver. The matrix *disposes*: auto-approve, cap INR, or escalate.

| Layer | Implementation |
|---|---|
| **UI** | 360 / handoff `AuthorityPolicyBlock` |
| **API** | `GET /authority/next`, `POST /authority/apply` |
| **Domain** | `agent_core/authority/{engine,matrix,enact,talk}.py`; tools `evaluate_authority`, `apply_goodwill` |
| **Persistence** | `authority_decisions`; enact posts `ledger_entries` |
| **Tests** | `test_authority_engine.py`, `test_demo_call_waiver.py` |
| **Config** | `AUTHORITY_MODE` = off / shadow / live |
| **UI logic** | Mock matrix in `api/authority.ts`; `applyAuthority` throws in mock |

---

### 4.12 Locked Engine — Live QA

**Purpose.** Same-call supervision: deterministic checks each turn; barge / whisper / inbox.

| Layer | Implementation |
|---|---|
| **UI** | `/floor` inspector; `/qa` pack view |
| **API** | Floor copilot; `GET /qa/interactions/{id}/pack` |
| **Domain** | `agent_core/live_qa/{engine,checks,enact,policy,pack}.py` |
| **Persistence** | `live_qa_decisions` |
| **Invokers** | `voice/persist.py` on each turn (not HTTP) |
| **Tests** | `test_live_qa_engine.py`, `test_live_qa_wiring.py` |
| **Background** | `worker.py` ~2 min pending scorecards |

Distinct from post-call **QA scorecards** (human rubric). Same English “QA”, two capabilities.

---

### 4.13 Compliance scan (post-call)

**Purpose.** Batch-judge completed transcripts against a rule catalog (RBI disclosure, prohibited language, checklists).

| Layer | Implementation |
|---|---|
| **UI** | `/compliance` |
| **API** | `/violations`, `/compliance/rescan`, `/compliance/rule-coverage`, `/compliance/policy-export` |
| **Domain** | `agent_core/compliance/{detectors,scan}.py`; `guardrails.py` is a **different** runtime path (sandbox/chat turn caps) |
| **Persistence** | `compliance_rules`, `violations`, `compliance_scans` |
| **Background** | `worker.py` sweep ~5 min |
| **Tests** | `test_compliance_detectors.py`, `test_guardrail_violations.py` |

Statuses: `open \| in_review \| acknowledged \| resolved`.

---

### 4.14 Interaction hub and channels

**Purpose.** Canonical record of a touch, plus the two speaking runtimes.

| Layer | Voice | WhatsApp / inbox |
|---|---|---|
| **UI** | `/sandbox` live call; `/audit` history; `/handoff` live | `/inbox` |
| **API** | `/twilio/voice/*`, `/ws`, `/voice/sandbox/*`, `GET /calls` | `/webhooks/whatsapp`, `/conversations*`, canned, suggestions |
| **Domain** | `voice/{bot,session,admission,tools,persist,amd,crm_sink}.py` | `bot_runtime.py`, `bot_jobs.py`, `whatsapp.py`, `whatsapp_outbound.py` |
| **Persistence** | `interactions`, `interaction_transcript`, `voice_sessions`, `bot_tool_calls` | `conversations`, `messages`, `bot_turn_jobs`, `whatsapp_outbound_jobs` |
| **Integrations** | Twilio PSTN + Media Streams; Azure STT/TTS; Pipecat | Meta Graph API; Twilio SMS status |
| **Background** | Real-time process (`voice.bot` or embedded host) | `bot_worker` drains turns + outbound |
| **Config** | `VOICE_MAX_CONCURRENT_CALLS`, `VOICE_EMBEDDED_HOST`, WS secret | `BOT_RUNTIME_ENABLED` |

**Conversation state is split three ways:** `interactions.status` (active/completed/abandoned/failed) vs `conversations.status` (bot/needs_human/escalated/assigned) vs `conversations.bot_state` jsonb. Voice adds `call_attempts.state` and `voice_sessions.status`. An outbound call that never connects has an attempt row and **no** interaction.

Audit UI (`/audit`) is **call history** (`GET /calls`), not `audit_log`.

---

### 4.15 Handoff (agent → agent) vs transfer (human) vs routing rules

Three capabilities share vocabulary. They are not one.

#### A. Agent **Handoff** (glossary)

| Layer | Implementation |
|---|---|
| **UI** | Studio graph / reachability lozenges — **not** Handoff Hub |
| **API** | `GET /agent-studio/cards/{id}/graph` |
| **Domain** | `handoff_to_agent` tool; `cards/handoff_policy.py` (insurance allowlist) |
| **Persistence** | `interaction_handoffs`; card `handoffs[]` JSON |
| **Gap** | Receiving card must replace the grant. Voice still filters tools once at session start (ADR-0001). Runtime incomplete |

#### B. Human **transfer** (Handoff Hub, floor)

| Layer | Implementation |
|---|---|
| **UI** | `/handoff`, `/floor` |
| **API** | `/handoff/queue\|active\|claim\|disclosures\|suggestions`; `/floor*`; `/supervisor-actions` |
| **Domain** | `db.escalate_interaction`; `voice/twilio_ops.warm_transfer_to_supervisor`; `agent_core/copilot.py` |
| **Persistence** | `interaction_handoffs` (to_kind=human), `supervisor_actions`, `live_alerts`, `ai_response_suggestions`, `agent_presence` |
| **Tool** | `escalate_to_human` |

Inbox **takeover** (`POST /conversations/{id}/takeover`) is a fourth path: WhatsApp-only human override. Not glossary **Handoff**.

#### C. Inbound routing rules (nav: “Routing / logic”)

| Layer | Implementation |
|---|---|
| **UI** | `/routing` + **client-only** `evaluateRules` simulator (`routing-seed.ts`) |
| **API** | `/routing-rules*`, `/routing-audit` |
| **Domain** | `db._match_routing_rule`, `_routing_eval_condition` (~L11731) — **a fifth decision engine inside the repository** |
| **Persistence** | `routing_rules`, `routing_rule_executions` |
| **Invoked from** | `db.escalate_interaction()` |

This engine is outside the card / locked-engine model. It is the clearest “business rules in the repository” finding.

---

### 4.16 Mission, outbound dial, cadence, outcome

**Purpose.** Authorised outbound intervention: why we are calling (**Mission**), whether we may (**contact policy**), the dial evidence (**attempt**), what settled (**Outcome**), whether to try the same action again (**Cadence**).

```text
Outbound intervention
├── UI          Agent Studio Outbound tab; /roles OutboundControlPanel (kill switch)
├── API         POST /twilio/voice/outbound, /demo/outbound-call
│               /outbound/{stats,attempts,cadence,campaigns,missions,
│               number-pools,obligations,card-vocabulary}
├── App         main.py dial orchestration (reserve → admit → place)
├── Domain      mission.assemble
│               outbound.{reserve,place,apply_status}
│               call_closer.process_one
│               cadence.{on_outcome,process_one}
│               post_call_actions (card-authored verbs)
│               campaigns.process_one
├── Persist     call_attempts, call_outcomes, call_cadence_state,
│               campaign_runs, campaign_targets, agent_obligations,
│               number_pools, pool_numbers
├── Integrate   Twilio; number pools
└── Tests       test_outbound_*.py, test_cadence_pause_and_strand.py,
                test_outbound_missions.py, test_outbound_card_vocabulary.py
```

| Concern | Detail |
|---|---|
| **Attempt FSM** | `reserved → suppressed \| dialing → ringing → answered → live → terminal`. Terminals include voicemail_*, no_answer, busy, transferred, abandoned. Monotonic rank in `outbound._RANK` |
| **Outcome axes** | Connection (from attempt state) **and** business (`call_closer.BUSINESS_OUTCOMES`). Legacy `interactions.disposition` still exists |
| **Cadence** | `open \| exhausted \| stopped \| escalated`. Mechanical: same mission, backoff, `stop_on`. Does not pick a new treatment action |
| **Background** | `bot_worker` priority: closer → cadence → campaigns → treatment enact |
| **Config** | `CAMPAIGN_RUNTIME_ENABLED` **and** `platform_switches.outbound.enabled` (default off). Both required to dial. `demo_ignores_window` |
| **Events** | Twilio call-status → `outbound.apply_status`; closer writes `call_outcomes`; optional `call.completed` webhook |

**Mission is not a table.** It is `agent_card.outbound.objectives[]` assembled at dial time into `call_attempts.context` / `objective`. `mission_id` on attempts is TEXT with no FK.

---

### 4.17 Payments and bounce cases

**Purpose.** Hosted pay links for PTP; CBS bounce ingest; optional statutory voice.

| Layer | Implementation |
|---|---|
| **UI** | Public `/pay/{token}` HTML (not Habibi chrome); bounce rows on `work_items` |
| **API** | `/pay/{token}`, `/pay/{token}/complete` (sandbox hosted only); `POST /webhooks/payments/{provider}`; `POST /webhooks/collections/payment-events`; `POST /sandbox/payment-events` |
| **Domain** | `payments.py`, `payment_events.py` (`ingest` → treatment trigger, `process_one_voice`) |
| **Persistence** | `payment_intents`, `payment_events`, `ledger_entries` |
| **Integrations** | Razorpay HMAC; CBS HMAC |
| **Background** | `bot_worker` bounce voice |
| **Tests** | `tests/test_payment_events.py` |
| **Events** | `payment.updated`; treatment decision on bounce |

---

### 4.18 Knowledge base

**Purpose.** Grounding corpus for mouths and inbox suggestions.

| Layer | Implementation |
|---|---|
| **UI** | `/knowledge-base` |
| **API** | `/kb/*` retrieve, documents, FAQs, gaps, snapshots, index jobs |
| **Domain** | `kb_retrieve.py`, `kb_ingest.py`, `kb_chunking.py`, `agent_core/tools/kb.py` |
| **Persistence** | `kb_documents`, `kb_chunks`, `kb_index_jobs`, `kb_snapshots`, `faq_pairs` (**no tenant_id**), `unanswered_questions` |
| **Integrations** | MinIO originals; embeddings |
| **Background** | `worker.py` `kb_ingest.process_one`; gardener |
| **Config** | `kb_rate_limit` |

`faq_pairs` without `tenant_id` is a tenancy hole relative to the rest of the book.

---

### 4.19 Sandbox, eval, twin

**Purpose.** Rehearse a mouth without ringing a borrower; regression gates at publish.

| Capability | UI | API | Domain | Persist | Background |
|---|---|---|---|---|---|
| Text sandbox | `/sandbox` | `/sandbox/runs*` | `sandbox_runtime.py` | `sandbox_*` | — |
| Voice sandbox | `/sandbox` voice panel | `/voice/sandbox/*` | `voice_sandbox.py` | `voice_sandbox_sessions` | session purge on `worker` |
| Eval suites | Studio Evals tab | `/eval/*` | `agent_core/eval/*` | `eval_*` (`14_agent_factory.sql`) | daily 04:15 UTC schedule |
| Twin replay | Sandbox twin | `/twins`, `/eval/twin-corpus` | `agent_core/twin.py` | `twin_*`, `simulation_twins` | — |
| Work runtime | Floor approvals | `/work-runtime/jobs/{id}` | `work_runtime/` (Postgres; Temporal adapter fails closed) | `work_runtime_jobs` | clerk, self-service plan veto |

Sandbox vs production is a **Deployment** environment (`sandbox` / `production`), a billing bucket, and `TREATMENT_MODE` / `AUTHORITY_MODE` — not a separate product.

---

### 4.20 QA scorecards, redaction, analytics, billing

| Capability | Purpose | UI | API | Domain / persist | Notes |
|---|---|---|---|---|---|
| **QA scorecards** | Human scoring, coaching, calibration | `/qa` | `/scorecards`, `/rubric`, coaching, calibration | `qa_*`, `coaching_actions`, `calibration_*` | Aggregates in `qa-seed.ts` for mock |
| **Redaction & export** | PII review, audio mute, regulated export | `/redaction` | `/redaction-*`, `/pii-findings`, `/export-jobs` | `08_redaction.sql`; MinIO | — |
| **Executive dashboard** | Portfolio KPIs | `/dashboard` | `GET /dashboard` | `analytics_daily`; `db.get_dashboard` | Export is toast-only |
| **Bot analytics** | Containment, intents, KB gaps | `/bot-analytics` | `GET /bot-analytics` | `11_analytics.sql` | Nav still says “Bot” |
| **Billing & usage** | Metering, budgets, invoices | `/billing` | `/billing*` | `usage_events` → `billing_usage_daily` | **Live only** (no mock). `inrCompact` duplicated with `money_inr.py` |

---

### 4.21 Human workspace

**Purpose.** What a collector should do this shift.

| Layer | Implementation |
|---|---|
| **UI** | `/` (`AssignedQueue`, `NeedsAttention`, IST 09:00–18:30 countdown in `index.tsx`) |
| **API** | `GET /work-items`, `GET /workspace/summary`, `GET/PATCH /me/presence` |
| **Domain** | UI buckets the flat list (`api/workspace.ts`) |
| **Persistence** | **`work_items` VIEW** unions disputes, callbacks, documents, promises, leads, follow-ups, payment bounce events (`95_views.sql`) |
| **Presence** | `agent_presence` |

Not a write model. A projection over collections resolution.

---

### 4.22 Platform capabilities (not collections semantics)

| Capability | UI | API / process | Persist |
|---|---|---|---|
| AuthZ / roles | `/roles` | `authz.py` + global FastAPI dependency; `/roles` | `roles`, `permissions`, `user_roles` |
| Tenancy | — | `app.tenant_id` GUC + Python `:tenant_id`; RLS (`rls.py`) | Almost every table |
| Provider registry (studio) | `/integrations` | `/providers/models\|bindings\|pools` | `agent_provider_bindings`, `provider_*` |
| Provider registry (legacy ops) | same page | `/providers`, test, configs | `ops_screens` + `providers` |
| Webhooks (tenant outbound) | `/webhooks` | `/webhook-endpoints*`, deliveries | `webhook_*`; drain in `bot_worker` |
| MCP / connectors / vault | Integrations MCP console | `/mcp/*`, `/connectors`, `/vault/refs`; separate `:8081` app + stdio `mcp_server` | `16_mcp_phase3.sql` |
| A2A | Integrations | `/.well-known/agent-card.json`, `/a2a*` | `a2a_partners`, `a2a_tasks` |
| LLM gateway canary | Integrations | `/gateway/*` | `gateway_canaries` |
| Platform switches | Roles `OutboundControlPanel` | `/platform/switches` | `platform_switches` |
| Health | — | `/health`, `/ready`, `/metrics` | — |

**Two provider APIs** on one Integrations screen. **Three MCP access patterns** (stdio, HTTP 8081, REST on :8000).

---

## 5. Placement violations

### 5.1 One capability, many homes

| Capability | Homes |
|---|---|
| **Tool Grant** | `grant.py` (unused), `intersect.py` (live), `voice/tools.ALWAYS_ON`, `flow_graph._FLOW_CONTROL_TOOLS`, compile G6/G9, leftover comments in `bot_tools.py` |
| **Mouth publish** | `/prompt-versions/*` and `/agent-studio/cards/*` |
| **Outbound dial** | `POST /twilio/voice/outbound`, `/demo/outbound-call`, `campaigns.process_one`, `treatment/enact`, cadence retry |
| **“Handoff”** | Agent tool, human hub, inbox takeover, routing-rule escalation, `supervisor_actions.force_handoff` |
| **Contact window** | `contact_policy.py`, `live_qa/checks.py`, frontend `mockVeto` |
| **Outcome vocabulary** | `call_closer.BUSINESS_OUTCOMES`, `cards/compile.OUTCOME_CODES`, card schema, SQL CHECK — restated so they cannot import each other |
| **Provider config** | `/providers` (ops) vs `/providers/bindings` (studio runtime) |
| **Voice status** | `/voice/status` vs `/twilio/voice/status` |
| **WhatsApp webhook** | `/webhooks/whatsapp` and `/webhook/whatsapp` |
| **KB gap → skill** | Manual `POST /kb/gaps/{id}/promote-skill` and daily gardener |
| **INR compact** | `money_inr.py` and `Habibi/src/data/billing-seed.ts` |

### 5.2 Unrelated capabilities in one god module

| Module | Lines (non-blank) | Domains inside it |
|---|---|---|
| `backend/db.py` | 16 583 | Book, CRM mutations, handoff queue, dashboard, studio list, routing **engine**, dispute SLA, payment-plan status derivation, treatment snapshot (writes on read), inbox, violations, calls list |
| `backend/main.py` | 4 471 | All HTTP: CRM, ops, studio, KB, outbound, treatment, voice webhooks, WhatsApp, eval, platform. No `include_router` |
| `backend/bot_worker.py` | 210 | Orchestrator: WA send, bot turns, PTP settle, closer, cadence, campaigns, treatment enact/follow/sweep, webhooks, clerk |
| `backend/bot_runtime.py` | 1 192 | WhatsApp turn loop, tools, policy, outbound send |
| `Habibi/.../prompt-studio.lazy.tsx` | large | Entire mouth authoring surface (flow, card, missions, evals, ship) |

`bot_worker.py` is a *justified* orchestrator (one drain loop, documented priority). `db.py` is not: it is the application layer, the repository, and at least one rules engine.

### 5.3 Business logic in the UI

Live paths increasingly **display server verdicts**. Remaining client rules:

| Location | Rule | Risk |
|---|---|---|
| `api/contact-policy.ts` `mockVeto` | Partial port of `_veto`; skips caps and cooling-off | Mock shows green when backend would deny |
| `data/dispute-sla.ts` | Intentional mirror of `db._dispute_sla` | Documented; mock-only |
| `data/routing-seed.ts` `evaluateRules` | Full routing simulator, **client-only** | Simulator can disagree with `db._match_routing_rule` |
| `api/authority.ts` | Mock goodwill matrix | Mock-only; apply is disabled |
| `lib/customerInsights.ts` | NBA fallback when insights API fails | Can invent a next action |
| `routes/index.tsx` | IST shift 09:00–18:30 | Operator UX, not policy |
| `api/workspace.ts` | Bucket `work_items` by entity type | Presentation |
| `api/flow.ts` `validateFlow` | Client graph checks before publish | Server compile is authoritative |
| `components/prompt-studio/OutboundCardEditor.tsx` | Daily cap hint vs G-OB3 | Authoring aid |
| `data/billing-seed.ts` `inrCompact` | Duplicate of `money_inr.py` | Display drift |
| `data/{promises,compliance,qa,consent}-seed.ts` | Metrics/filters | Mock aggregations |

`USE_MOCK=true` in dev means most capability UX is a **second implementation**. Production builds forbid mock.

### 5.4 Business rules in controllers (`main.py`)

Most handlers are thin `db.*` wrappers. Exceptions that orchestrate policy:

- Outbound dial (~reserve, `contact_policy.admit`, suppress, fleet gate, `outbound.place`)
- Public pay page complete
- Payment / CBS webhook ingest
- Document ingest
- Inbox suggestion refresh (KB retrieve)
- Platform switch PATCH (audit)
- Interaction export bundle

This is acceptable *application* logic. It is not a locked engine. The problem is that there is no application-service layer *beside* the god router — the same file also declares 170 routes.

### 5.5 Business rules in the repository (`db.py`)

| Function | Rule that does not belong in persistence |
|---|---|
| `_match_routing_rule` / `_routing_eval_condition` | Full condition DSL + first-match actions |
| `_dispute_sla` | Warn fraction 0.25, countdown copy |
| `list_payment_plans` | Derives `on_track/slipped/completed` from installments |
| `_treatment_snapshot` | Calls `recommend_treatment()` — **decision write on GET** |
| `_inbox_promise_status` | Display normalization |
| `escalate_interaction` | Combines queue write + routing engine |

### 5.6 Duplicated domain logic (same rule, two codes)

Already listed in §5.1. The ones that can **disagree under load**:

1. Tool grant (publish vs voice vs text) — proven historical bug.
2. Contact mock vs `admit()` — false contactability in dev.
3. Routing simulator vs `db.py` evaluator.
4. Outcome code lists (compile vs closer vs SQL).
5. RBI voice window (contact policy vs live QA checks).

---

## 6. One concept, many models / services / states

### 6.1 Mouth

| Model | Role |
|---|---|
| `bots` | Identity (legacy name) |
| `prompt_versions` columns | Prompt, persona, voice, guardrails, flow, tuning |
| `prompt_versions.agent_card` jsonb | **Agent Card** |
| `bot_deployments` | Live **Deployment** per environment |
| `deployment_experiments` | Canary split (also `card.experiment` JSON) |
| Frontend `PromptVersion` vs `AgentCard` types | Two TS models for one publish |

### 6.2 “Offer”

| Meaning | Store / module |
|---|---|
| Tool **Offer** (turn subset of grant) | Runtime only — no table |
| Product offer (NBO) | `offer_decisions`, reco engine |
| Treatment action | `treatment_decisions.chosen_action` |
| Authority waiver | `authority_decisions` |
| Mission allowlist | `card.outbound.objectives[].allowed_offers` |

### 6.3 Settlement of a call

| Layer | Field |
|---|---|
| Legacy | `interactions.disposition` |
| Canonical outbound | `call_outcomes.connection` + `.business` |
| Treatment | `treatment_decisions.outcome` |
| Reco | `offer_decisions.response` |
| Callback wrap | `callbacks.disposition` |
| UI / QA | “disposition” copy |

### 6.4 Promise (see §4.2)

Three status columns plus plan API statuses that do not exist on the plan row.

### 6.5 Consent

| Store | Grain |
|---|---|
| `customers.dnd` | Party flag |
| `consent_records.dnd_registry` | Registry flag |
| `channel_consents` | Channel **and** purpose |
| `optout_events` | Append-only |
| `contact_events` / `contact_day_counters` | Admission ledger / cap cache |
| UI `optedIn: boolean` | Loses dnd/expired |

### 6.6 Work

| Surface | What it is |
|---|---|
| `work_items` VIEW | Human CRM queue |
| `/handoff/queue` | Live escalated interactions |
| Inbox needs_human | WhatsApp threads |
| `work_runtime_jobs` | Durable clerk / self-service / approvals |
| `followups` | Promise-xor-lead tasks |
| Floor live table | In-progress voice |

### 6.7 Memory of a commitment

| Store | What it remembers |
|---|---|
| `promises` | PTP money object |
| `agent_obligations` | What *we* promised on the call (callback, doc, waiver) |
| `customer_memory.open_commitments` jsonb | Cross-call LLM memory — **outside** the promises table |

---

## 7. Events, background, configuration (cross-cutting)

### 7.1 Who produces events

| Producer | Events / logs |
|---|---|
| `promise_fulfillment` | `promise.*` webhooks |
| `payments.py` | `payment.updated` |
| `webhooks_dispatch` | HTTP outbox → tenant endpoints (`webhook_deliveries`) |
| `contact_policy` / send paths | `contact_events`, `contact_delivery_events` |
| Engines | append-only `*_decisions` tables |
| `agent_core/change_log.py` | `audit_log` hash chain |
| `db.record_activity` | `activity_events` |
| `voice/crm_sink.py` | post-call CRM writeback (not REST) |
| Catalog (partially unwired) | `call.started\|completed\|escalated`, `dispute.*`, `bot.handoff`, `bot.compliance.flag` — listed in `ops_screens.EVENT_CATALOG`; not all have producers |

### 7.2 Background map → capability

**`bot_worker.py` (collections loop, priority order):** WhatsApp outbound → PTP reminders/settle → bounce voice → **call closer (Outcome)** → **Cadence** → campaigns → treatment enact → treatment follow-through → treatment sweep → webhook delivery → clerk / canary.

**`worker.py` (hygiene):** KB index → TTS catalog sync → lead revalidate → follow-up sweep → compliance sweep → QA autoscore / live QA scores → gardener → eval schedule → MCP drain.

**Not a queue:** voice (`voice.bot` or embedded). **Optional:** Temporal (`work_runtime/adapter_temporal.py` fails closed).

### 7.3 Configuration that changes domain behaviour

| Knob | Effect |
|---|---|
| `TREATMENT_MODE` / `AUTHORITY_MODE` | off / shadow / live |
| `TREATMENT_SWEEP` | Book-wide new decisions |
| `CAMPAIGN_RUNTIME_ENABLED` + `platform_switches.outbound.enabled` | Both required to dial |
| `BOT_RUNTIME_ENABLED` | WhatsApp bot turns |
| `demo_ignores_window` | Contact-policy waiver for demos |
| `VOICE_MAX_CONCURRENT_CALLS` | Admission cap (separate from outbound fleet gate) |
| `USE_MOCK` / `VITE_USE_MOCK` | Entire second UI implementation |
| Card `tools.locked` / policy bindings | Cannot publish without locked engines |
| `policy_rule_sets` rows | Versioned statutory/client/product rules |

---

## 8. Potential bounded contexts

These are **hypotheses from coupling**, not a proposed microservice cut. Weak evidence is marked. DDD terms are used only where the code already has a language and a lifecycle.

### Keep together (do not split)

1. **Contact policy + consent + delivery events** — one admit function, one ledger. Strongest context.
2. **Mouth + Card + Flow + Skill attachment + compile Gates + Deployment** — publish is one transaction (`compile.py` is large *because* it must be).
3. **Outbound attempt + Mission assembly + Closer + Cadence + post-call actions** — the best-isolated pipeline. Treatment *authorises*; this pipeline *executes and records*.
4. **Book (customer, account, ledger, EMI)** — every engine reads it; splitting it first would multiply joins without reducing coupling.

### Eligible to extract as modules (still in-process)

| Context | Extract because | Do not extract until |
|---|---|---|
| Treatment | Own engine package already; append-only log | Enact no longer inlined into `bot_worker` knowledge of WhatsApp internals |
| Reco | Parallel engine; clear veto from treatment | Product catalog stays with the book |
| Authority | Narrow matrix; own log | — already small |
| Live QA | Turn-hooked; own log | Voice persist stops being the only caller |
| Skill packs | Own versioning/signing | Grant migration completes (G9 vs runtime) |
| Tool Grant | ADR-0001 already names the owner | `grant.py` is imported by voice and text |

### Do not call a context yet

| Cluster | Why not |
|---|---|
| Collections resolution (PTP, dispute, callback, docs) | Shared `db.py`, shared `work_items`, shared 360 aggregate. Cohesive *entities*, no cohesive *module* |
| Human ops (inbox, floor, hub) | Three channel-specific queues; shared word “handoff” |
| Routing rules | Tiny; evaluator trapped in `db.py`; language clashes with **Handoff** |
| Analytics | Derived |
| `interactions` | Hub by design |

### Suggested module boundaries (target, not current)

```text
contact_policy/     admit, rules, delivery ledger
mouth/              card, compile, deploy, flow, skills attach
grant/              ToolGrant + Offer (already started, unwired)
outbound/           attempt, mission, closer, cadence, campaigns   (files exist, not a package)
treatment/          already a package
reco/               already a package
authority/          already a package
live_qa/            already a package
book/               customer, account, ledger                      (today: db.py)
resolution/         promise, dispute, callback, document           (today: db.py)
ops/                human transfer, floor, inbox                   (today: db.py + ops_screens)
platform/           authz, billing meter, webhooks, providers
```

`agent_core/` is already this shape for engines. The gap is **CRM + contact + outbound + HTTP**, which never left the two god modules.

---

## 9. What a later architecture pass should believe

1. **The product principle is implemented, unevenly.** Locked engines exist and are invoked on the voice/worker path. Contact policy is the outbound veto. Cadence does not change actions. The LLM is not supposed to dispose — and on the engine paths, it does not.

2. **The grant migration is the structural prerequisite for Handoff.** Until `grant.py` is the runtime enforcement point, publish/runtime can diverge again, and agent-to-agent **Handoff** will keep the handing-off mouth’s tools (ADR-0001).

3. **Rename after seams, not before.** `bots` → **Mouth** and `objective` → **Mission** are glossary work. They will not create a context. Extracting routing out of `db.py` and wiring the grant will.

4. **Do not invent a “Handoff bounded context”.** Split the word: **Handoff** (card, new grant), **transfer** (human hub + Twilio), **takeover** (WhatsApp), **routing rules** (inbound DSL). The UI already merged two of these.

5. **CRM entities can stay a modular monolith package.** They share the book, the 360 read model, and `work_items`. Forcing PTP vs disputes into separate services would split the operator’s job, not the code’s.

6. **Mock UI is a second domain model.** Any capability map of “what the operator sees in dev” is not the backend. Production forbids mock; architecture work should treat `src/data/*-seed.ts` as fixtures, not as rules — except where they already admit to mirroring server functions.

7. **`interactions` should remain the hub.** Every later context will still take an `interaction_id`. That is domain truth (a conversation happened), not accidental coupling.

---

## 10. Capability index (sidebar → actual capability)

| Nav item | Actual capability | Domain |
|---|---|---|
| My workspace | Human work projection | Resolution + presence |
| Conversation inbox | WhatsApp ops + takeover | Channel ops |
| Handoff hub | Human **transfer** | Ops |
| Floor command | Supervisor live QA / barge | Live QA + ops |
| Executive dashboard | Read model | Analytics |
| Customer 360 | Book aggregate + write-through | Book + resolution |
| Promise to pay | PTP + plans + pay links | Resolution |
| Disputes queue | Disputes + SLA | Resolution |
| Document desk | Fulfilment | Resolution |
| Callbacks | Scheduled return | Resolution |
| Upsell & leads | Reco + lead pipeline | Reco |
| Decision intelligence | Treatment engine | Treatment |
| Audit trail | Call history (`/calls`) | Interaction hub |
| Compliance risk | Post-call scan + violations | Compliance |
| Consent / DND | Consent registry | Contact policy |
| Redaction & export | PII / export jobs | Compliance ops |
| QA scorecards | Human scoring | QA (not live QA) |
| Bot analytics | Mouth performance + KB gaps | Analytics |
| Knowledge base | RAG corpus | KB |
| Agent studio | **Mouth** + **Card** + **Flow** + **Mission** | Mouth publish |
| Call sandbox | Rehearsal | Eval |
| Routing / logic | Inbound rule DSL | Routing (≠ Handoff) |
| Integrations | Providers + MCP + vault + A2A | Platform |
| Webhooks | Tenant event outbox | Platform |
| Billing & usage | Metering | Platform |
| Roles & access | RBAC + outbound kill switch | Platform + outbound |

**Present in backend, absent as a top-level nav item:** hosted pay page, mandates, agent **Handoff** graph (inside studio), campaigns (inside Outbound tab), twins, work-runtime jobs, grievance-officer copy.

---

*Analysts: [domain discovery](2311e992-d210-4f0b-aa95-78880812d801), [business logic](36f2436f-f458-42c9-9aff-6df7e91687ea), [API/flow](f8fef830-aa13-4d1d-9a2e-5fd5b5f6b6cd), [data model](532960e4-1b93-405a-a8e6-409df92425f6), [UI capabilities](36b5c249-7b1f-461c-97d4-332bc72e8bf8).*
