## Module 5.4 Billing & Usage Analytics

Route: `/billing`. Finance-facing dashboard that tracks cloud spend across the voice AI + telephony stack (LLM tokens, STT/TTS minutes, telephony, WhatsApp), trends, per-tenant breakdown, budget alerts and invoices. Ties the ops story back to unit economics — "cost per resolved call" is the hero metric.

### Layout

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Header: title · Period picker · Tenant picker · [Export CSV/PDF]     │
├──────────────────────────────────────────────────────────────────────┤
│ Hero KPI strip (4 tiles)                                             │
│  Spend MTD · Cost / resolved call · Forecast EOM · Budget usage %    │
├────────────────────────────────────┬─────────────────────────────────┤
│ Spend trend (stacked area, 30d)    │ Budget & alerts card            │
│                                    │  - budget bar per env           │
│                                    │  - threshold rules              │
├────────────────────────────────────┴─────────────────────────────────┤
│ Cost breakdown (service table + donut)                               │
│  columns: service · unit · usage · unit cost · cost · Δ vs last      │
├──────────────────────────────────────────────────────────────────────┤
│ Two-column: Per-tenant breakdown table │ Invoice history list        │
└──────────────────────────────────────────────────────────────────────┘
```

Full-bleed under `AppShell`, `h-full min-h-0 overflow-y-auto` on the main scroll body (page is content-heavy, not a fixed cockpit).

### 1. Header controls
- Period select: MTD (default) / Last 7d / Last 30d / Last quarter / Custom.
- Tenant select: All tenants / HDFC Retail / HDFC Cards / Kotak Personal / ICICI Auto.
- Env toggle chip: Prod / Sandbox (defaults Prod).
- `Export` split button → CSV, PDF invoice-style summary (toast on click).

### 2. Hero KPI strip (`BillingKpiStrip`)
- **Spend MTD** — ₹ big value, sparkline, Δ vs same period last month.
- **Cost / resolved call** — ₹ / call, delta vs last month; connects to hackathon hero AHT metric.
- **Forecast EOM** — projected based on current daily burn.
- **Budget usage** — % of monthly cap consumed with color threshold (green <70, amber 70–90, red >90).

### 3. Spend trend (`SpendTrendChart`)
Recharts stacked area across 30 days, stacked by service (LLM, STT, TTS, Telephony, WhatsApp, Infra). Toggle legend to hide/show a service; y-axis in ₹ / day. Tooltip lists all layers with totals.

### 4. Budget & alerts card (`BudgetPanel`)
- Progress bar per env: `Prod ₹4.2L / ₹6L`, `Sandbox ₹18k / ₹40k`.
- List of threshold rules with severity + channel: e.g. "≥ 80% MTD → email finance-ops", "≥ 100% → Slack #billing + freeze non-critical jobs".
- Add / edit rule opens a small dialog (in-memory).
- Alert history strip (last 3 alerts with timestamp).

### 5. Service cost table (`ServiceCostTable`)
Rows for each service line — the same set used across `/integrations`:
- Azure OpenAI GPT-4o (LLM · per 1K tokens)
- Deepgram Nova-3 (STT · per minute)
- ElevenLabs Turbo (TTS · per 1K chars)
- Twilio Voice (Telephony · per minute)
- Twilio WhatsApp BSP (per conversation)
- Pipecat Orchestrator (per active minute)
- Data Lake ingest (per GB)
- Postgres + Redis infra (flat monthly)

Columns: Service / Category / Usage this period / Unit cost / Cost / Δ vs previous period / share % (color bar).
Sortable by cost. Row click → drawer with 30-day sparkline of that service and top 5 tenants driving it.

Alongside the table: `ServiceDonut` — donut showing % share by category (LLM / Voice / Messaging / Infra).

### 6. Per-tenant breakdown (`TenantTable`)
Columns: Tenant · Resolved calls · AHT · Total spend · Cost / call · Δ · Budget bar. Highlights tenants exceeding budget in rose.

### 7. Invoice history (`InvoiceList`)
List cards for last 6 months: month · status (Paid / Pending / Draft) · amount · `View PDF` (toast) · `Download`.

### Data (`src/data/billing-seed.ts`)
Types: `Service`, `ServiceCategory`, `DayPoint`, `TenantSpend`, `Invoice`, `BudgetRule`, `Env`, `Period`.
- `SERVICES` — 8 rows with realistic unit rates in ₹.
- `daily(30)` — 30-day timeseries per service (varied realistic curves; weekends dip).
- `TENANTS` — 4 tenants with resolved-call counts, AHT and derived spend.
- `INVOICES` — last 6 months with statuses.
- `BUDGETS` — Prod ₹6L / Sandbox ₹40k with 3 alert rules.
- Helpers: `sumRange(days)`, `changePct(cur, prev)`, `forecastEom(daily, dayOfMonth, daysInMonth)`, `costPerCall(total, calls)`, INR formatter `inr()`, `inrCompact()`.

### Components (`src/components/billing/`)
- `BillingHeader.tsx`
- `BillingKpiStrip.tsx`
- `SpendTrendChart.tsx` (recharts stacked area, legend toggling)
- `BudgetPanel.tsx` + `BudgetRuleDialog.tsx`
- `ServiceCostTable.tsx` + `ServiceDrawer.tsx`
- `ServiceDonut.tsx`
- `TenantTable.tsx`
- `InvoiceList.tsx`

Route: `src/routes/billing.tsx` orchestrates period/tenant state and reuses seed helpers.

### Sidebar
Add "Billing & Usage" (icon: `Receipt`) under **Bot Configuration** group after Webhooks.

### Design
Reuse existing tokens (`brand-primary`, `brand-navy`, `surface-card`, sentiment colors for over-budget). All currency values render with `inr()` / `inrCompact()`. Recharts uses the same color palette established across `/dashboard` and `/bot-analytics` for consistency. In-memory state only; no backend.
