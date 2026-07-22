# Collections Agent — Full Product Spec (Screens + Design System)

> **Product:** An AI **Inbound Collections Agent** — a **voice-first** (telephony) agent for BFSI clients, wrapped in an enterprise CRM workspace to track, manage, resolve, supervise, and audit every customer interaction. WhatsApp/omnichannel is an optional secondary channel.
> **Purpose of this doc:** Hand this to **lovable.dev** to generate the frontend. Backend (bot orchestration) is built separately with **Pipecat** and wired in via the API/webhook screens defined below.
> **Bot capabilities driving these screens:** caller ID & verification, dues/balance lookup, payment history, EMI schedules, late-fee/waiver info, dispute capture, RAG FAQ, document requests, eligibility-gated upsell, compliance disclosures, sentiment monitoring, human handoff, summaries, CRM writeback, AHT/conversion logging.

---

## Part 0 — Hackathon Alignment (the North Star)

This maps the official hackathon brief to this spec so the build stays on target.

| Hackathon field | Value | How the spec serves it |
|---|---|---|
| **Problem** | Inbound dues/payment queries consume agent time; upsell chances are missed | Bot deflects queries (Bot Analytics *containment rate*); upsell is a first-class flow |
| **Solution** | Inbound **voice** agent for informative query handling + contextual upsell | Voice-first Handoff Hub, Sandbox, Prompt Studio; Upsell & Leads Manager |
| **Users** | Customer Service, Collections Teams | Agent My Workspace, Floor Command Center, Customer 360 |
| **Data needed** | Customer account data, product catalog, policy FAQs | Customer 360 (accounts), Upsell Manager (catalog), Knowledge Base/RAG (FAQs) |
| **Required outputs** | ① Query resolution ② Upsell offer presented ③ Call summary | Each must be visibly produced and viewable per call (see hero flow below) |
| **Hero metrics** | ① Reduced **AHT** ② **Upsell conversion rate** | Both pinned as primary tiles on the Executive Dashboard |
| **Data availability** | None — **synthetic scenario scripts** needed for PoC | Ship every screen with realistic **seed/mock data**; Call Simulation Sandbox drives scripted demos |
| **Tech** | Voice AI, NLP, RAG, AI Agent | Prompt Studio, Knowledge Base (RAG), Routing/Logic Builder |
| **Systems** | Core Banking, CRM, Telephony | Integrations screen (Twilio telephony, core banking, CRM) |

**Scope note:** the 26 screens below are the *full enterprise vision* (use them for the pitch & roadmap). For the **hackathon PoC demo**, focus on the **Tier 1** set in Part 3 and make sure a single call visibly produces all three required outputs.

**Demo "golden path" to rehearse:** inbound call → bot identifies caller & pulls account (Customer 360) → answers a dues/EMI query from RAG → presents an eligibility-gated **upsell** → generates a **call summary** → dashboard **AHT** and **upsell conversion** tick. Drive it live from the **Call Simulation Sandbox** using synthetic scripts.

---

## Part 1 — Design System

The look should feel like **WhatsApp / Facebook**: clean, blue-and-white, high-trust, dense-but-calm. Professional enough for a bank's compliance officer, friendly enough for a floor agent staring at it 8 hours a day.

### 1.1 Color Palette

| Token | Hex | Use |
|---|---|---|
| `--brand-primary` | `#1877F2` | Primary blue — buttons, active nav, links, focus rings |
| `--brand-primary-hover` | `#166FE5` | Hover state for primary |
| `--brand-primary-dark` | `#0A4DA6` | Pressed / deep accents |
| `--brand-navy` | `#0B2447` | Headings, top bar, high-emphasis text |
| `--brand-tint` | `#E7F0FE` | Selected rows, active chips, subtle blue fills |
| `--surface-app` | `#F0F2F5` | App background (the Facebook grey-blue) |
| `--surface-card` | `#FFFFFF` | Cards, panels, tables |
| `--surface-sunken` | `#F7F9FB` | Nested/inset areas, input backgrounds |
| `--border` | `#E4E6EB` | Dividers, card borders, table lines |
| `--text-primary` | `#1C1E21` | Body text |
| `--text-secondary` | `#65676B` | Labels, metadata, timestamps |
| `--text-muted` | `#8A8D91` | Placeholders, disabled |

**Semantic / status colors** (used heavily — this is a collections product):

| Token | Hex | Meaning |
|---|---|---|
| `--success` | `#2E7D32` | Paid, resolved, promise kept, positive sentiment |
| `--success-bg` | `#E6F4EA` | Success chip/row background |
| `--warning` | `#F9A825` | At-risk, due soon, neutral-declining sentiment |
| `--warning-bg` | `#FEF6E0` | Warning chip/row background |
| `--danger` | `#D93025` | Overdue, dispute, compliance breach, angry sentiment |
| `--danger-bg` | `#FCE8E6` | Danger chip/row background |
| `--info` | `#1877F2` | Informational / in-progress |
| `--sentiment-positive` | `#2E7D32` | Sentiment bubble green |
| `--sentiment-neutral` | `#F9A825` | Sentiment bubble amber |
| `--sentiment-negative` | `#D93025` | Sentiment bubble red |

**Optional dark mode:** invert surfaces to `#18191A` / `#242526`, keep `--brand-primary` as the accent. Nice-to-have, not required for the demo.

### 1.2 Typography

- **UI font:** `Inter` (fallback: `-apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`). Load Inter from Google Fonts.
- **Numeric / currency / IDs:** `"Roboto Mono"` or `"IBM Plex Mono"` — tabular figures so money columns and account numbers align. Always enable `font-variant-numeric: tabular-nums` on tables.

| Role | Size / Weight | Notes |
|---|---|---|
| Display (dashboard KPI) | 32px / 700 | Tabular nums |
| H1 page title | 24px / 700 | Navy |
| H2 section | 18px / 600 | |
| H3 card title | 15px / 600 | |
| Body | 14px / 400 | Default |
| Small / meta | 13px / 400 | Secondary text |
| Micro / labels | 11px / 600 uppercase, letter-spacing 0.4px | Table headers, chip labels |

### 1.3 Spacing, Radius, Shadow

- **Spacing scale (px):** 4, 8, 12, 16, 24, 32, 48. Default gutter 16, card padding 20–24.
- **Radius:** `--r-sm: 6px` (chips, inputs), `--r-md: 10px` (cards, buttons), `--r-lg: 16px` (modals, large panels), `--r-full: 999px` (avatars, sentiment bubbles, pills).
- **Shadows (soft, FB-like — never harsh):**
  - `--shadow-sm: 0 1px 2px rgba(0,0,0,0.06)`
  - `--shadow-md: 0 2px 8px rgba(0,0,0,0.08)`
  - `--shadow-lg: 0 8px 28px rgba(0,0,0,0.12)` (modals, popovers)

### 1.4 Core Components (consistent across all screens)

- **App shell:** fixed left **sidebar nav** (collapsible to icons), sticky **top bar** (global search, notifications bell, help, avatar/menu). Content area on `--surface-app`.
- **Buttons:** primary (filled blue), secondary (white + border), ghost (text), danger (red). Height 40px, radius `--r-md`.
- **Chips/pills:** status pills using semantic bg + text colors. Rounded-full.
- **Data tables:** sticky header, zebra optional, row hover `--brand-tint`, right-aligned monospace numeric columns, per-column sort, sticky first column for wide tables.
- **Cards:** white, `--shadow-sm`, `--r-md`, 20px padding, optional header row with title + action.
- **Sentiment indicator:** a small filled circle (green/amber/red) + optional trend arrow, reused everywhere sentiment appears.
- **Empty states:** friendly illustration + one-line explanation + primary action.
- **Toasts:** bottom-right, auto-dismiss, semantic color left border.
- **Command palette (⌘K / Ctrl+K):** global jump-to (customer, call, dispute, screen).

### 1.5 Animation & Motion (subtle, purposeful — never bouncy)

Use `framer-motion` or CSS transitions. Motion should communicate state, not decorate.

- **Global easing:** `cubic-bezier(0.4, 0, 0.2, 1)`, durations **150ms** (micro), **250ms** (panels), **400ms** (page).
- **Page/route transitions:** fade + 8px upward slide, 250ms.
- **Cards / list items on load:** staggered fade-in (30ms stagger), respect `prefers-reduced-motion`.
- **Live data (transcripts, sentiment, active-call grid):** new items slide/fade in from top; number changes count-up (200ms); a soft pulse ring on the live/"recording" dot.
- **Sentiment shifts:** color cross-fade the bubble (250ms) rather than a hard swap.
- **Buttons:** 100ms scale-to-0.98 on press; skeleton shimmer for loading states (not spinners) on tables/cards.
- **Kanban / drag:** lift shadow + 1.02 scale on grab, smooth reorder.
- **Modals:** backdrop fade + panel scale 0.96→1, 200ms.
- **Handoff / escalation alerts:** attention-grab pulse on the incoming card (2 pulses then settle), plus toast.

### 1.6 Layout Rules

- Left sidebar **240px** (expanded) / 64px (collapsed). Top bar **56px**.
- Max content width for dashboards/forms **1440px**; tables/consoles go full-width.
- Live-ops screens (Handoff Hub, Floor Command) are **full-bleed, dense**. CRM/config screens are **calmer, more whitespace**.
- Responsive: fully usable down to laptop (1280px). Tablet supported for dashboards; live-ops is desktop-first.

---

## Part 2 — Screens

The original 18 screens are kept and refined. **8 new screens (⭐ or [NEW])** close real gaps for a collections product — most importantly **Promise-to-Pay tracking** and **Consent/DND management**, which are non-negotiable in BFSI collections, plus **Bot Analytics** and an **Agent home**.

Each screen lists **Purpose** and **Key elements** so lovable.dev can scaffold directly.

### 🧭 Module 0 — Foundation

*(Auth is intentionally out of scope for this demo — the app opens straight into the workspace. Login/SSO/MFA can be added later for production.)*

*(Global patterns — not standalone screens: the **left nav**, **⌘K command palette**, **notifications bell**, and **user menu** appear on every screen.)*

### 🟢 Module 1 — Live Operations

**1.1 Agent My Workspace (Home / My Queue)** `[NEW]`
- **Purpose:** What an individual agent sees when *not* on a live call — their shift home base. (The original list jumped straight to live-call screens with no agent landing page.)
- **Key elements:** "My assigned" queue (disputes, callbacks, doc requests routed to me), today's stats (calls handled, AHT, resolutions), availability toggle (Available / On-break / Wrap-up), next scheduled callback, quick links, personal SLA countdowns.

**1.2 Conversation Inbox (Omnichannel)** `[NEW — optional / post-PoC]`
- **Purpose:** *Secondary channel.* The PoC is voice-first (telephony), so this is optional. If WhatsApp/text is added later, agents get a WhatsApp-style threaded inbox to read/monitor/take over **text** conversations (voice calls live in the Handoff Hub). Reinforces the WhatsApp aesthetic.
- **Key elements:** Left conversation list (search, filters: bot-handled / needs-human / escalated), center chat thread (bubbles, bot vs customer vs agent, delivery ticks), right context rail (mini Customer 360). "Take over from bot" button, canned responses, RAG-suggested replies inline.

**1.3 The Handoff Hub (Agent Workspace)** *(refined)*
- **Purpose:** Split-screen cockpit for a human agent handling an **escalated live voice call**.
- **Key elements:** Live transcript (streaming, speaker-labeled), **live sentiment meter** + trend, **AI-suggested responses** with one-click insert, customer context panel (dues, last promise, EMI, open disputes), compliance checklist ("disclosure read? ✓"), call controls (mute/hold/transfer/end), post-call wrap-up (disposition + notes) that feeds CRM writeback.

**1.4 Floor Command Center** *(refined)*
- **Purpose:** Floor-manager grid to monitor all active bot + human calls in real time.
- **Key elements:** Live grid/tiles per active call (agent/bot name, customer, duration, live sentiment bubble, topic), filters, aggregate live stats bar (calls in progress, avg sentiment, escalation rate, queue depth). Actions: **silent Listen-In**, **Whisper** (coach agent only), **Barge/Force-handoff**. Alert lane for calls turning negative.

### 🗄️ Module 2 — CRM & Resolution Workflows

**2.1 Executive Dashboard** *(refined)*
- **Purpose:** Home for managers/leadership — high-level health.
- **Key elements:** KPI tiles (Total dues recovered, Recovery rate, AHT, **Bot containment/resolution rate**, Upsell conversions, Promise-kept rate, CSAT/sentiment avg). Trend charts (recovery over time, call volume, sentiment distribution), leaderboard, at-risk accounts summary, date-range + segment filters.

**2.2 Customer 360 (The Ledger)** *(refined)*
- **Purpose:** Unified master record for a debtor.
- **Key elements:** Header (name, account #, risk badge, outstanding, contactability/consent status). Tabs: **Ledger** (dues, invoices, transactions), **EMI schedule** (timeline with paid/upcoming/overdue), **Interactions** (unified call+chat timeline with sentiment + summaries), **Promises** (PTP history), **Disputes**, **Documents**, **Notes**. Right rail: quick actions (log call, create PTP, raise dispute, send statement).

**2.3 Promise-to-Pay & Payment Plans** `⭐ [NEW — high value]`
- **Purpose:** **The core of any collections product.** When a customer (or the bot) commits to paying $X by date Y, that promise must be captured, tracked, and monitored for kept/broken/partial. This was entirely missing.
- **Key elements:** PTP pipeline (Upcoming → Due today → Kept → Broken → Partial), each card: customer, amount, promised date, channel (bot/agent), auto-reminder status, countdown. Payment-plan/installment builder. "Broken promise" auto-flag → routes to follow-up queue. Filters by agent/bot, aging, amount. Metrics strip: promise-kept rate, $ in active promises, at-risk $.

**2.4 Disputes & Exceptions Queue** *(refined)*
- **Purpose:** Kanban to review disputes the bot **captured** (e.g., "I paid this yesterday") — bot flags, humans resolve.
- **Key elements:** Kanban columns (New → Under Review → Awaiting Customer → Resolved / Rejected). Cards: customer, dispute type, amount, captured transcript snippet, SLA timer. Drag between columns, assignee, evidence attach, resolution notes → CRM writeback.

**2.5 Document Fulfillment Desk** *(refined)*
- **Purpose:** Back-office queue to process statement/document requests captured by the bot.
- **Key elements:** Request list (customer, doc type, requested-via, date, status), generate/attach document, **delivery channel** (WhatsApp/email), status pipeline (Requested → Generating → Sent → Failed), bulk actions, template picker, audit of what was sent.

**2.6 Callback & Scheduling Manager** `[NEW]`
- **Purpose:** Customers who ask the bot for a callback / "call me tomorrow at 5" need scheduling + assignment.
- **Key elements:** Calendar + list view of scheduled callbacks, customer + reason + preferred window + timezone, assign to agent/queue, reminders, reschedule/cancel, "missed callback" flag. Respects **consent/DND windows** (links to 3.3).

**2.7 Upsell & Leads Manager** *(refined)*
- **Purpose:** Sales follow-up for customers who expressed interest in eligibility-gated upsells (e.g., debt consolidation).
- **Key elements:** Leads pipeline/board (Interested → Contacted → Qualified → Won/Lost), lead card (customer, offer, eligibility flags, sentiment at capture, transcript snippet), assignment, follow-up scheduling, conversion tracking that feeds the Exec Dashboard.

### 🛡️ Module 3 — Compliance, QA & Analytics

**3.1 The Audit Trail (Call History)** *(refined)*
- **Purpose:** Searchable database of every historical interaction.
- **Key elements:** Powerful filters (date, agent/bot, customer, disposition, sentiment, flagged), row → detail drawer with **audio player synced to transcript**, summary, disclosures-read checklist, sentiment timeline. Export (respecting redaction). Immutable log feel.

**3.2 Compliance Risk Dashboard** *(refined)*
- **Purpose:** QA/compliance screen flagging calls where mandatory disclosures were missed or prohibited language was used (bot or human).
- **Key elements:** Risk feed (severity-ranked), rule-hit cards (which rule, transcript evidence, timestamp, who), trend of violations over time, filter by rule/severity/agent, assign-for-review, resolve/acknowledge workflow, exportable compliance report.

**3.3 Consent & Communication Preferences (DND / Opt-out)** `⭐ [NEW — high value]`
- **Purpose:** BFSI-critical. Collections is heavily regulated (TCPA/FDCPA/RBI-style rules). The bot **must** honor DND, opt-outs, and allowed contact windows/frequency — with an auditable record. Missing from the original list and a real compliance risk.
- **Key elements:** Per-customer consent record (channels opted in/out: call/WhatsApp/SMS/email), DND registry, allowed contact hours/timezone, contact-frequency caps, opt-out capture log (who/when/how), consent-expiry tracking, bulk import/export, and a clear "contactable now?" status that other screens (Callback, Inbox) read from.

**3.4 Redaction & Export Hub** *(refined)*
- **Purpose:** Compliance officers securely export transcripts/audio with PII auto-redacted for regulators.
- **Key elements:** Select records → **PII detection preview** (card numbers, SSN/PAN, phone auto-masked, editable), redaction rules config, export format (PDF/CSV/audio), watermark + export audit log, access-controlled.

**3.5 QA Scorecards & Coaching** `[NEW]`
- **Purpose:** Score bot + agent interactions against a QA rubric and drive coaching. (Compliance Risk = binary rule breaches; this = graded quality.)
- **Key elements:** Scorecard rubric builder (weighted criteria: empathy, resolution, compliance, script adherence), per-call scoring (manual + AI-assisted), agent scorecard trends, calibration view, coaching notes/action items assignable to agents.

**3.6 Conversation & Bot Analytics** `⭐ [NEW — high value]`
- **Purpose:** Diagnostic analytics for the *bot's* performance (the Exec Dashboard is business KPIs; this is conversation intelligence). Tells you *why* the bot fails and where to improve prompts/RAG.
- **Key elements:** **Intent distribution** (what customers call about), **containment rate** & deflection, **drop-off/abandonment funnel**, escalation reasons breakdown, top unanswered/RAG-miss questions, avg turns-to-resolution, sentiment-by-intent heatmap, latency/response-time metrics. Feeds directly into Knowledge Base and Prompt Studio work.

### ⚙️ Module 4 — Bot Configuration (The Brain)

**4.1 Knowledge Base (RAG) Manager** *(refined)*
- **Purpose:** Upload, chunk, and manage policy PDFs/FAQs the bot uses.
- **Key elements:** Document library (status, version, last indexed), upload + chunking preview, chunk inspector, **test-query panel** (see what the bot retrieves), FAQ pair editor, enable/disable sources, re-index button, "flagged from Analytics" gaps to fill.

**4.2 Persona & Prompt Studio** *(refined)*
- **Purpose:** Tune the bot's system prompt and voice (TTS).
- **Key elements:** System-prompt editor with variables, persona presets (empathy/firmness sliders), **TTS controls** (voice, speed, tone, pauses) with live preview play, guardrail/prohibited-language config, **version history + diff**, "test in Sandbox" and "publish" (with confirm).

**4.3 Call Simulation Sandbox** *(refined)*
- **Purpose:** Safely text/talk to the bot before pushing prompts to production.
- **Key elements:** Chat + voice test panel, scenario/persona selector (angry customer, disputes, etc.), which prompt-version + KB-version under test, live view of retrieved chunks + intent + sentiment classification, transcript export, "promote this config to production".

**4.4 Routing & Logic Builder** *(refined)*
- **Purpose:** Visual rule engine for handoff/routing triggers.
- **Key elements:** Rule cards / lightweight flow canvas — `IF {sentiment = angry} AND {dues > X} THEN {route to Tier 2}`. Condition builder (sentiment, intent, amount, verification status, consent), priority ordering, enable/disable, test/simulate a rule, audit of rule changes.

### 🛠️ Module 5 — System Administration

**5.1 Integrations & API Connections** *(refined — where Pipecat backend plugs in)*
- **Purpose:** Manage API keys for the underlying stack.
- **Key elements:** Connection cards for **LLM (Azure/OpenAI)**, **STT (Deepgram)**, **TTS (ElevenLabs)**, **telephony (Twilio)**, **WhatsApp Business API**, core banking. Each: key entry (masked), status/health check, usage summary, test-connection button, environment (sandbox/prod).

**5.2 Webhooks & Event Subscriptions** *(refined)*
- **Purpose:** Configure real-time data push back to the client's legacy banking system.
- **Key elements:** Endpoint registry (URL, events subscribed, secret), event catalog (call.completed, promise.created, dispute.raised, payment.updated…), **delivery log** (success/fail, retries, payload preview), test-fire, signing-secret rotation.

**5.3 User Management & RBAC** *(refined)*
- **Purpose:** Invite staff, assign granular roles.
- **Key elements:** User table (name, role, status, last active), invite flow, **role matrix** (Agent, Manager, Auditor, Compliance, Admin) with per-module permissions, team/queue assignment, deactivate/suspend, SSO-provisioning note, activity log.

**5.4 Billing & Usage Analytics** *(refined)*
- **Purpose:** Track cloud spend across the AI/telephony stack.
- **Key elements:** Cost dashboard by service (LLM tokens, STT/TTS minutes, telephony minutes, WhatsApp conversations), trend charts, per-tenant breakdown, budget alerts/thresholds, invoice/export, cost-per-resolved-call metric.

**5.5 Notifications & Alert Center** `[NEW]`
- **Purpose:** Central place for system + operational alerts (SLA breaches, broken promises, compliance flags, integration failures, escalations). The bell in the top bar opens a preview; this is the full page.
- **Key elements:** Alert feed (grouped by type, severity-colored), read/unread, filters, per-user notification preferences (in-app / email / channel), snooze/dismiss, deep-links to the relevant record.

**5.6 Org & Workspace Settings** `[NEW]`
- **Purpose:** Tenant-level configuration for industrial multi-client deployments.
- **Key elements:** Org profile & branding (logo/colors per client), business hours & timezones, data-retention policies, default compliance disclosures & language, currency/locale, security (session timeout, IP allowlist), plus personal **User Profile & Preferences** (name, avatar, notifications, theme).

---

## Part 3 — Build Priority (for a hackathon / phased delivery)

You almost certainly can't polish all 26 for a demo. Suggested tiers:

**🥇 Tier 1 — Demo heroes (build first, make them shine — these carry the hackathon golden path):**
`Executive Dashboard` (AHT + upsell-conversion tiles) · `Customer 360` · `Handoff Hub` · `Upsell & Leads Manager` · `Call Simulation Sandbox` (drives the live demo) · `Knowledge Base / RAG` · `Floor Command Center`

**🥈 Tier 2 — Depth & credibility:**
`Conversation & Bot Analytics ⭐` (containment) · `Promise-to-Pay ⭐` · `Persona & Prompt Studio` · `Audit Trail` · `Compliance Risk Dashboard` · `Consent/DND ⭐` · `Agent My Workspace` · `Disputes Queue`

**🥉 Tier 3 — Completeness (scaffold, lower fidelity):**
`Knowledge Base` · `Routing Builder` · `Redaction Hub` · `QA Scorecards` · `Document Fulfillment` · `Callback Manager` · `Integrations` · `Webhooks` · `User Management/RBAC` · `Billing` · `Notifications Center` · `Org Settings`

---

## Part 4 — Summary of Changes vs. Original

- **Kept & refined** all 18 original screens (added purpose + concrete key-elements so lovable.dev can build directly).
- **Added 8 screens**, most notably:
  - **Promise-to-Pay & Payment Plans ⭐** — the missing heart of a collections tool.
  - **Consent & Communication Preferences (DND/Opt-out) ⭐** — mandatory BFSI compliance layer.
  - **Conversation & Bot Analytics ⭐** — diagnostic bot intelligence (distinct from business KPIs).
  - **Agent My Workspace**, **Conversation Inbox (omnichannel)**, **Callback Manager**, **QA Scorecards**, **Notifications Center**, **Org Settings**.
- **Added a full design system** (blue/white, WhatsApp/Facebook feel): colors, typography, spacing, components, motion.
- **Added build-priority tiers** for phased/hackathon delivery.
