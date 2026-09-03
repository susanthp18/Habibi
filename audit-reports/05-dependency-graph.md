# 05 — Dependency graph

**Repo:** [susanthp18/Habibi](https://github.com/susanthp18/Habibi) at `D:\Hackathon`  
**Product:** Habibi CRM (`Habibi/`) + collections backend (`backend/`)  
**Guest tree:** `PRAXIST-main/` — no runtime import edge into the product  
**Date:** 2026-09-01  
**Mode:** read-only. No source, lockfile, or config was changed except this file.  
**Companions:** `01-repository-xray.md`, `02-domain-capability-map.md`, `03-frontend-architecture.md`, `04-backend-architecture.md`

This report is the **call graph of the codebase**: who imports whom, who cannot change without moving everyone else, and which cycles are architectural rather than an `ImportError`.

Domain terms follow `CONTEXT.md`: Mouth, Agent Card, Skill Pack, Locked Engine, Tool Grant, Offer, Gate, Flow, Handoff, Mission, Cadence, Outcome.

---

## Verdict

The product is **three acyclic import-time graphs glued into one cyclic runtime**.

| Graph | Import-time cycles | What actually couples |
|---|---|---|
| Habibi TypeScript (`src/`, 474 modules) | **0** runtime (1 generated type-only 2-cycle) | Design-system gravity + seed files acting as the domain model |
| Backend Python (269 production modules) | **0** module-load SCCs across packages | A **~110-module coupling SCC** closed by *function-level* imports, glued by `db.py` |
| npm / pip / Praxist extras | n/a | Frontend is a shadcn kit graph; backend is a partial process split; Praxist is the inverted graph the backend only pretends to be |

The architectural meaning is not “Python has circular imports.” Import order is already defended (`tests/test_import_cycles.py`, PEP 562 on `agent_core.cards`, 162/269 modules with delayed imports). The meaning is: **Card compile, WhatsApp Mouth, Locked Engines, Cadence, contact policy, and voice persistence are one strongly connected component the moment any of them runs.** A mid-call Handoff that must swap the Tool Grant walks that blob. ADR-0001 named the owner (`agent_core/tools/grant.py`); production still does not import it.

Frontend layering is the healthy one: **routes → components → api/data/lib**, zero `components → routes`, no app cycles. Its damage is unused kit surface and types trapped in `data/*-seed.ts`.

---

## 1. Scope and method

**In scope**

- `Habibi/src` TypeScript/TSX (app graph). `routeTree.gen.ts` counted, then discounted.
- `backend/` Python production modules: top-level, `agent_core/`, `voice/`, `work_runtime/`. Not `tests/`, not `alembic/versions`, not `.venv`, not `scripts/` except as orphans.
- Package manifests: `Habibi/package.json` + lockfile, `backend/requirements*.txt`, `PRAXIST-main/pyproject.toml`.
- ADRs `0001` (one owner for the Tool Grant) and `0002` (cardless ⇒ deny-all).

**Out of scope as a product graph**

- `PRAXIST-main/examples/**/vendor`, templates, tests. Praxist appears only as a **guest** with a documented core/plugin contract.
- Generated frontend route tree internals, except the type-only cycle it forms with `router.tsx`.

**How the five analyses were combined**

1. **TypeScript dependency analyst** — resolved `@/*` and relative imports; compared to knip (`artifacts/frontend-static-review`); `madge --circular` on `src`.
2. **Python import analyst** — stdlib `ast` over first-party modules; edges classified runtime / lazy / `TYPE_CHECKING`; Tarjan SCCs; in/out degree.
3. **Package dependency analyst** — manifests, lockfile, knip unused deps, grep of named libraries (`liveline`, `recharts`, `pipecat`, `temporalio`).
4. **Circular dependency analyst** — ranked every serious cycle as `A → B → C → A` with why.
5. **Architecture-boundary analyst** — intended layers vs measured inner→outer edges; Martin instability; DIP around Grant / Cadence / Locked Engines.

**Tooling caveats**

- `npx madge --extensions ts,tsx` is unreliable in Windows PowerShell (the comma splits the argument; one run processed **0 files**). Cycle claims for TypeScript come from an explicit import graph plus a madge run that did see `src`. Prefer the graph.
- Knip unused-*exports* on `src/api/*.ts` are noisy: hooks in the same file consume `fetch*`. Prefer the import graph for **files**.
- Backend “cycle count” depends on whether lazy edges and package `__init__` re-exports are included. This report always states which graph.

---

## 2. The workspace is three graphs, not one

```
Habibi/src  --HTTP fetch-->  backend (FastAPI / workers / voice)
                │
                └── no Python import, no Praxist import

PRAXIST-main/praxist  — guest. backend does not `import praxist`.
```

There is **no module-level edge** between the CRM UI and the Python Mouth, and **none** between Habibi and Praxist. Shared *names* (Pipecat, MCP, OpenAI) are separately pinned. Vite proxies `/voice-rtc` to the voice runner; that is an operational edge, not an import.

So “the entire codebase” has three legitimate dependency universes. Treating them as one graph would invent coupling that does not exist. The rest of this report analyses each universe, then the **permission graph** that cuts across Python processes (the one that matters for Handoff).

---

## 3. Measured inventory

### 3.1 TypeScript (`Habibi/src`)

| Metric | Count |
|---|---|
| Modules | **474** (473 app + generated `routeTree.gen.ts`) |
| Directed import edges | **1692** (1646 excluding generated) |
| Mean out-degree | 3.48 |
| `@/` alias imports | 1483 (86%) |
| Relative internal imports | 239 |
| Runtime SCCs size > 1 | **0** |
| Type-only SCC | 1 (`router.tsx` ↔ `routeTree.gen.ts`) |
| Fan-in 0 (orphans) | 41 (11 tests + 1 SSR entry + 1 ambient + **28** unreferenced) |
| Fan-out 0 (leaves) | 50 |
| Barrel files (re-export `index.ts`) | 2 (`charts/`, `records/`) |

Layout: `components/` 331, `api/` 48, `routes/` 44, `data/` 28, `lib/` 15. Wide and shallow — a collections console of parallel feature slices, plus one star (Mouth / Agent Studio).

### 3.2 Python (`backend/` production)

| Metric | Count |
|---|---|
| First-party modules | **269** |
| Unique runtime (module-level) edges | **445** |
| Unique lazy (in-function) edges | **539** |
| Unique `TYPE_CHECKING` edges | **7** |
| Modules with delayed imports | **162 / 269 (60%)** |
| Import-time SCCs across packages | **0** |
| Coupling SCCs (runtime + lazy) | **4** (sizes **~108–111**, 2, 2, 2) |
| Reachable from 5 entrypoints (coupling) | 247 / 269 |
| Orphans (coupling in=0, not an entrypoint) | 20 |
| Leaves (coupling out=0) | 57 |

Entrypoints: `main.py`, `bot_worker.py`, `worker.py`, `voice/bot.py`, `mcp_server.py`.

God-module sizes (lines): `db.py` **18,087**, `main.py` **5,448**, `schemas.py` **3,453**, `voice/tools.py` **2,914**, `bot_runtime.py` **1,292**, `grant.py` **247**.

### 3.3 Packages

| Graph | Direct | Notes |
|---|---|---|
| Habibi `dependencies` | **58** | 26 `@radix-ui/*`, 3 `@pipecat-ai/*`, 5 `@tanstack/*` |
| Habibi `devDependencies` | **19** | |
| Habibi lockfile | ~535 top-level / ~587 entries | ~7× fan-out |
| knip unused production deps | **27 / 58 (~47%)** | mostly unused Radix + form/chart kit |
| Backend `requirements.txt` | **17** | 14 runtime + pytest + ruff in the API image |
| Backend voice extra | 3 directs (`pipecat-ai[…]==1.6.0`, numpy, fastembed) | huge native tree |
| Backend MCP extra | 1 (`mcp>=1.2.0`, unpinned) | |
| Praxist core | **3** (pyyaml, jinja2, pydantic) | extras are capability-shaped |

---

## 4. TypeScript graph — a console with one star

### 4.1 Intended vs measured layers

Expected: **routes → feature components → api + data + lib → ui primitives**.

| Edge | Count | Verdict |
|---|---|---|
| components → components | 575 | OK |
| routes → components | 285 | OK |
| components → lib | 231 | OK |
| components → data | 191 | Heavy: UI imports seeds/types directly |
| components → api | 115 | OK |
| routes → api | 76 | OK |
| api → data | 34 | OK (mock branch) |
| **components → routes** | **0** | Clean |
| api → components | 2 | Type-only DIP miss |
| data → components | 1 | Type-only |
| data → api | 1 | Type inversion (`FlowGraph`) |
| lib → api | 2 | Type-only |
| lib → components | 1 | Gate tone → lozenge |

`@/*` erases folder depth in 86% of imports. Layering cannot be eyeballed; it has to be linted or graphed. ESLint today only bans `server-only` (Next.js leftover), not layer direction.

### 4.2 Cycles

**Runtime: none.**

The only SCC:

```
src/router.tsx  →  src/routeTree.gen.ts  →  src/router.tsx
```

`router.tsx` imports `routeTree` at runtime. The generated file has `import type { getRouter } from './router.tsx'` so TanStack can type `Register.router`. Erased at compile. Ignore it.

No `api` ↔ `data` runtime cycle. No route ↔ component cycle. Barrels do not close loops (leaves never import `./index`).

Closest type inversion (not a cycle): `data/prompt-studio-seed.ts` `import type { FlowGraph }` from `api/flow.ts`. Flow’s graph type lives in the HTTP client; Mouth persona defaults live in the seed.

### 4.3 Fan-in hubs (accidental infrastructure)

| Rank | Module | In | Out | Meaning |
|---|---|---|---|---|
| 1 | `src/lib/utils.ts` | **213** | 0 | `cn()`. True global. Healthy leaf. |
| 2 | `src/components/ui/lozenge.tsx` | **107** | 1 | Status chip that now *is* Gate / Outcome / SLA / contactability vocabulary |
| 3 | `src/components/ui/button.tsx` | 89 | 2 | Design-system primitive |
| 4 | `src/api/config.ts` | **67** | 0 | Mock/live switch + `apiGet`/`apiPost`. Leaf — and a leak: ~20 UI files branch on `USE_MOCK` |
| 5 | `src/components/ui/input.tsx` | 42 | 1 | Primitive |
| 6 | `src/components/shell/AppShell.tsx` | 30 | 4 | Chrome. Every screen wraps it. Earned. |
| 7 | `src/components/charts/index.ts` | 25 | 8 | Outcome visualization kit |
| 8 | `src/data/customer360-seed.ts` | **25** | 1 | **Account record types + `fmtMoney` living in a mock fixture** |
| 9 | `src/components/records/RecordsTable.tsx` | 20 | 3 | Collections data-grid (the unused barrel sits on top of this) |
| 10 | `src/api/agent-studio.ts` | 16 | 2 | Agent Card / Skill Pack / compile / evals. Earned product hub |

**Accidental globals, not just popular UI:**

1. **`data/customer360-seed.ts`** — Customer / Promise / Dispute / Consent types and formatters. API modules, `lib/customerInsights`, and almost every 360 tab import a *seed*. Domain model and mock data are the same module. Strongest “we cannot turn mocks off without a rewrite” node after `cn()`.
2. **`api/config.ts` used from screens** — Handoff, sandbox, floor, compliance, approvals, `TwinTab` (which calls `apiGet`/`apiPost` and skips a domain `api/*` module). Presentation knows whether the Mouth is live.
3. **`lib/gate-status.ts` → `LozengeTone`** — compiler Gate verdicts (`pass|fail|warn|skipped`) typed as a chip colour.
4. **`data/callbacks-seed.ts` → `LozengeTone`** — Cadence status typed as a chip.

### 4.4 Fan-out (composition roots, not failure)

Top outbound edges are **lazy routes assembling a screen**. That is the architecture:

| Module | Out | Role |
|---|---|---|
| `routeTree.gen.ts` | 45 | Generated. Ignore. |
| `routes/prompt-studio.lazy.tsx` | **27** | Mouth editor God route (prompt, Flow, voice, guardrails, skills, connectors, outbound, Gates, evals, ship) |
| `routes/knowledge-base.lazy.tsx` | 21 | KB |
| `routes/sandbox.lazy.tsx` | 20 | Call simulation |
| `routes/customers.$customerId.lazy.tsx` | 19 | Customer 360 |
| `routes/handoff.lazy.tsx` | 18 | Human takeover of a Mouth session |

First component-level Gods: `prompt-studio/OutboundTab.tsx` and `VoiceCatalogBrowser.tsx` (fan-out 12). Thin `*.tsx` route stubs that only talk to `@tanstack/react-router` are healthy leaves; work lives in `*.lazy.tsx`.

**Prompt Studio is the only real God module, and it is the product** (Agent Card compiler), not an accident of folder structure. `/prompt-studio` already redirects into `/agent-studio/$botId`; the lazy file still wires ~15 tabs.

### 4.5 Barrels

| Barrel | Fan-in | Fan-out | Cycle? | Meaning |
|---|---|---|---|---|
| `components/charts/index.ts` | 25 | 8 | No | Live Outcome widget kit. Importers depend on the *kit*, not a leaf. Tree-shaking can drop unused exports; it cannot undo the hub. Two files bypass it (`FlowCanvas`, `sonner` → `use-dark-mode`). |
| `components/records/index.ts` | **0** | 3 | No | **Dead facade.** `RecordsTable` itself has fan-in 20; every caller imports the leaf file. Knip agrees. Deleting the barrel changes nothing at runtime. |

Barrel smell here is not “barrels cause cycles.” It is: **charts over-couples a healthy kit; records is leftover.**

### 4.6 Orphans (28 truly unreferenced)

Dead product UI (rewrites left the old files): `floor/CallTile.tsx`, `floor/AlertLane.tsx`, `documents/StatusPill.tsx`, `sandbox/ScenarioList.tsx`, `records/index.ts`, `brand/BigBoundMark.tsx`, `hooks/use-mobile.tsx`.

Dead shadcn kit (~21): `aspect-ratio`, `avatar`, `breadcrumb`, `calendar`, `card`, `carousel`, `chart`, `context-menu`, `drawer`, `form`, `hover-card`, `input-otp`, `link`, `menubar`, `navigation-menu`, `pagination`, `progress`, `radio-group`, `scroll-area`, `toggle-group`, `tooltip`. `@/components/ui/card` has **zero** importers. The product uses custom surfaces + `ChartCard`.

Knip listed 33 unused files; **five are false positives** vs this graph: `api/offer-health.ts` (used by Offer health on `/upsell`), `ui/collapsible`, `ui/resizable`, `ui/section-message`, `ui/table`. Do not delete Offer health or Voice panel primitives from knip alone.

### 4.7 Layer violations that matter

1. **`api/promises.ts` imports types from `PromiseSheet` / `PlanBuilderSheet`.** Promise-to-pay write DTOs live in JSX. `import type` avoids a runtime cycle (sheets do not import the API module; the *route* does). The Cadence/PTP contract still belongs in `api` or `data`, not in a sheet.
2. **Seeds are the domain package** (191 component→data + 26 route→data edges). Until types move out of `data/`, “seed used everywhere” *is* global infrastructure.
3. **Feature → feature (not in the layer table, still coupling):**
   - `prompt-studio/AgentCardPanels` → `sandbox/EvalCockpit`
   - `sandbox/TuningStudio` → prompt-studio voice catalog (bidirectional with the Card studio)
   - `sandbox/ConversationPanel` → `floor/Waveform`
   - `flow/FlowCanvas` → `inbox/SplitPanes` (inbox split panes became a layout primitive)

---

## 5. Python graph — a DAG that runs as a knot

### 5.1 Import-time is a DAG on purpose

No package-crossing module-load SCC. No self-loops. Four modules use `TYPE_CHECKING` to keep the type checker happy without closing a load cycle (`agent_core.cards`, `skills.runtime`, `tools.grant`, `reco.talk`). `tests/test_import_cycles.py` proves the dangerous first-imports survive a fresh interpreter: `skills.runtime`, `intersect`, `cards.schema`, `cards.compile`, `cards`, `tools.grant`.

That is **load-order engineering**, not layering. 60% of modules delay imports. When those edges are restored, **~110 modules collapse into one SCC**. Almost every reverse edge is inside a function. `ImportError` is gone; the architecture cycle is not.

`main.py` is a true composition root (coupling fan-out **78**, fan-in **0**) and is **not** in the knot. `mcp_server.py` is the same shape. `db.py` is the opposite.

### 5.2 Fan-in / fan-out (coupling graph = runtime + lazy)

**Fan-in (imported by many):**

| Rank | Module | In | Out | Meaning |
|---|---|---|---|---|
| 1 | `db` | **101** | **52** | Accidental platform kernel |
| 2 | `contact_policy` | 21 | 4 | Reachability Gate (Cadence-adjacent). Healthy-*stable* shape |
| 3 | `env_loader` | 20 | — | Bootstrap |
| 4 | `azure_openai` | 19 | 7 | LLM client. Unstable-central |
| 5 | `agent_core.platform_flags` | 17 | — | Feature flags |
| 6 | `agent_core.cards.schema` | **15** | 0 | Agent Card type. **Healthy leaf** |
| 7 | `capture` | 15 | — | Outcome/event capture, in the knot |
| 8 | `agent_core.tools.catalog` | **14** | 1 | Tool catalog. **Healthy, not in the SCC** |
| 9 | `agent_core.skills.pack` | **11** | 0 | Skill Pack type. Healthy leaf |
| 10 | `mission` | 9 | — | Outbound reason-to-call, in the knot with PTP/payments |

**Fan-out (imports many):**

| Rank | Module | Out | Meaning |
|---|---|---|---|
| 1 | `main` | **78** | FastAPI composition root (OK as an entry) |
| 2 | `db` | **52** | God module (not OK) |
| 3 | `voice.bot` | 44 | Mouth process |
| 4 | `voice.tools` | 29 | Voice handlers + `ALWAYS_ON` filter. Martin *I* ≈ 0.91 |
| 5 | `bot_runtime` | 20 | Text Mouth |
| 6 | `bot_worker` / `bot_tools` / `treatment.engine` | 13–17 | |

### 5.3 Martin stability — unstable central modules

*I* = *Ce* / (*Ca* + *Ce*). High Ca and high Ce together is the zone of pain (cannot change, cannot depend on stably).

| Rank | Module | Ca | Ce | *I* | Product Ca×Ce |
|---|---|---|---|---|---|
| 1 | `db` | 101 | 52 | 0.34 | **5252** |
| 2 | `azure_openai` | 19 | 7 | 0.27 | 133 |
| 3 | `voice.tools` | 3 | 29 | **0.91** | 87 |
| 4 | `contact_policy` | 21 | 4 | 0.16 | 84 |
| 5 | `voice.persist` | 7 | 10 | 0.59 | 70 |
| 6 | `agent_core.tools.domain` | 8 | 8 | 0.50 | 64 |
| 7 | `promise_fulfillment` | 6 | 10 | 0.63 | 60 |
| 8 | `agent_core` (barrel) | 7 | 8 | 0.53 | 56 |

**Healthy-stable (high Ca, low *I*):** `contact_policy`, `env_loader` / `env_utils`, `cards.schema`, `tools.catalog`. A Grant/Card/contact veto should look like these.

**Healthy-unstable (entrypoints):** `main`, `voice.bot`, `bot_worker` — high *I*, low Ca.

**Vacuous-stable:** `agent_core.tools.grant` has Ca **0**. It is stable because nothing uses it.

### 5.4 Orphans and leaves

**Orphans that are findings, not noise:**

| Module | Why it is orphan |
|---|---|
| **`agent_core.tools.grant`** | ADR-0001 owner. Production importers: **none**. Tests only. Docstring: “Nothing imports this yet.” |
| **`rls`** | RLS policy compiler. Runtime tenant isolation is libpq GUC inside `db`, not this module. Tests/scripts only. |
| `voice.spike`, `voice.node_contracts`, `voice.workers.insurance`, `provider_voice_sync`, `treatment.ope` | Operator / spike / unused engine |

**Healthy leaves (high fan-in, out=0):** `cards.schema`, `skills.pack`, `tools.schema`, `policy_rules`, `money_inr`, `pii_redact`, `env_utils`. Catalog is almost a leaf (out=1 → `tools.schema`). `policy_rules` is versioned Locked-Engine / contact data — right shape.

Package barrels nobody imports (`agent_core.cards`, `.skills`, `.eval`, `.reco`, `voice`, …) inflate the orphan count; they are not dead product.

### 5.5 The `agent_core` barrel is a trap

`agent_core/__init__.py` eagerly re-exports `deployment.load_active_bundle`. Deployment eagerly imports `db`. Importing “the brain” for `estimate_sentiment` therefore loads Postgres. `voice.persist` does exactly that. `money_inr` documents the trap.

That barrel is how voice persistence joins the WhatsApp worker knot (cycle §6.3).

---

## 6. Circular dependencies — every serious cycle

Convention: **eager** = module-level import; **lazy** = inside a function. Import-time is a DAG; these cycles exist because both directions eventually run.

### 6.1 HIGH — the ~110-module knot glued by `db.py`

**Why it exists:** `db.py` (18,087 lines, 440 functions) is SQL *and* the place that **runs** treatment, authority, compile, canary, twin, live QA, reco policy, card routing, and bot jobs. Every engine that needs a connection imports `db`; `db` functions then import those engines. There is no store protocol. Persistence owns orchestration.

Twenty-plus **direct 2-cycles** have `db` on them. Representative longer cycles:

```
db  -lazy→  agent_core.cards.compile  -lazy→  connectors.persist  -runtime→  db
```

Publish Gate lives in `compile`; API handlers in `db` call it; compile/connectors write through `db`. The Gate is not a pure function over a Card.

```
skills.intersect  -lazy→  connectors.persist  -runtime→  db  -lazy→  cards.compile  -runtime→  intersect
```

Skill Pack tool intersection (the **live Tool Grant formula**) is pulled into persistence via compile. This is how connector tools (`ext.*`) already drifted out of the publish Gate’s copy — the bug ADR-0001 recorded.

```
skills.runtime  -lazy→  skills.persist  -runtime→  db  -lazy→  bot_jobs  -lazy→  bot_runtime  -lazy→  skills.runtime
```

Mouth turn state (Offer) ↔ job queue ↔ WhatsApp runtime ↔ `db`.

```
flow_graph  -lazy→  agent_core.tools  -runtime→  tools.kb  -lazy→  db  -lazy→  flow_graph
```

Authored Flow is imported by `schemas.py` at **runtime** (HTTP DTOs reuse `FlowGraph`). `db` imports `schemas`. Transport models put Flow in the knot.

```
treatment.engine  -lazy→  db  -lazy→  agent_core.treatment  -runtime→  treatment.engine
```

Locked Engine package `__init__` re-exports the engine; `db` lazily imports the package. Same shape for `reco`, `authority`, `live_qa`.

```
mission  -lazy→  db  -lazy→  promise_fulfillment  -lazy→  payments  -lazy→  payment_events  -lazy→  mission
```

Mission / Outcome / money: the reason to place a call is tangled with PTP and payment writes.

```
work_runtime.api  -lazy→  adapter_pg  -runtime→  db  -lazy→  a2a  -lazy→  work_runtime  -runtime→  api
```

Work runtime is not an isolated Temporal-shaped island.

**Not in the knot (important negatives):** `agent_core.tools.grant`, `agent_core.tools.catalog`, `agent_core.cards.schema`, `agent_core.skills.pack`, `voice.tools`, `voice.bot`, `main`, `mcp_server`, `policy_rules`, `rls`. Domain *types* and the catalog are DAG leaves. The *runtimes and the publish Gate* are not.

**Architectural meaning:** Handoff cannot change the Agent Card (and therefore the Tool Grant) in a live session without touching this blob. ADR-0001 called a single Grant owner a **prerequisite for Handoff**. The graph says why.

`tests/test_import_cycles.py` does **not** cover this SCC. It covers first-import of cards/skills/grant.

---

### 6.2 HIGH — WhatsApp Mouth knot

```
bot_runtime  -eager→  bot_jobs  -lazy→  bot_runtime
bot_runtime  -eager→  bot_tools  -eager→  db  -lazy→  bot_jobs  -lazy→  bot_runtime
```

**Why:** historical worker split. The turn loop, tool handlers, and job queue all needed CRM writes, so each imported `db`. Jobs needed to call back into the turn loop, so `bot_jobs` imported `bot_runtime`.

**Meaning:** a tool-handler change import-pulls the entire text Mouth and the SQL god module. You cannot load tools without the worker.

---

### 6.3 HIGH — voice persistence ↔ brain barrel ↔ WhatsApp

**Not a cycle:** `voice.bot → agent_core` (eager) is one-way. `voice.tools` is **not** in the ~110-SCC. The voice *process* is a composition root.

**Is a cycle:**

```
voice.persist  -eager→  agent_core  -eager→  deployment  -eager→  db
    -lazy→  bot_jobs  -lazy→  bot_runtime  -lazy→  voice.persist
```

**Why:** `voice.persist` was extracted so voice writes would not sit on `db`’s mutation surface, then imported sentiment/guardrails from the **barrel**, which pulls deployment, which pulls `db`. `bot_runtime` lazily imports `voice.persist` on the WhatsApp path that records voice-shaped rows.

**Meaning:** a sandbox-only voice persist change can still traverse the WhatsApp worker. Voice modules **in** the knot: `voice.persist`, `voice.config`, `voice.twilio_ops`. The rest of `voice/*` is outside — including the Mouth process itself.

---

### 6.4 HIGH — compile ↔ persistence (the Grant is *not* in this cycle)

```
cards.compile  -eager→  skills.intersect  -lazy→  connectors.persist  -runtime→  db  -lazy→  compile
compile  →  contact_policy  →  db  →  compile
a2a  ↔  db  →  compile  →  a2a
```

**Why:** publish lives in `db.py`. The compiler needs the connector registry and RBI contact policy, which live behind `db`. Missing interface: `ConnectorRegistry` / `PublishStore`.

**Grant is not in any SCC.** It TYPE_CHECKING-imports `AgentCard` / `SkillPack` and lazily imports catalog, `intersect`, `skills.runtime`. Those modules do not import `grant`. Wiring `grant` into `compile` at **module level** would recreate the cards/skills first-import crash. Any migration must keep Grant’s imports inside functions (the test already pins that).

---

### 6.5 HIGH historically, now LOW — cards ↔ skills load cycle

Documented in `agent_core/cards/__init__.py`:

```
skills.intersect  →  cards.schema
  →  cards.__init__
    →  cards.compile          # used to be eager
      →  skills.intersect     # still initialising
→ ImportError: cannot import name 'PLATFORM_SKILL_TOOLS'
```

`voice/bot.py` defers `from agent_core.skills.runtime import mouth_turn_state` into prompt assembly, so the **voice worker was the first process to hit the cycle** and every call died building the system prompt.

**Fix:** PEP 562 `__getattr__` on `agent_core.cards`; `TYPE_CHECKING` re-exports; `skills.runtime` TYPE_CHECKING-only `AgentCard`. The named-module graph treats `agent_core.cards` and `agent_core.cards.schema` as distinct, so Tarjan never reported this as an SCC — but it shipped as a runtime `ImportError`.

**Landmine:** re-eager-importing `compile` from `cards/__init__.py` brings it back.

---

### 6.6 MEDIUM — identity / tenancy

```
actor_context  -lazy→  db  -lazy→  actor_context
authz  -lazy→  db  -lazy→  authz
actor_context  →  db  →  visibility  →  actor_context
tenant_context  ←eager-  db  -lazy→  tenant_context
capture  ↔  db
contact_policy  ↔  db
followups_db  ↔  db     # late re-export so call sites stay db.*
```

**Why:** request-scoped identity was layered onto a module that already owned SQL and tenant RLS. Comments admit it: “Lazy import to avoid circular import at module load.” These **broke crashes** by pushing edges into functions. They did not remove the architecture cycle.

---

### 6.7 MEDIUM — clerk / PTP / treatment enact

```
clerk  →  treatment.enact  →  promise_fulfillment  →  clerk
clerk  →  db  →  promise_fulfillment  →  clerk
```

Treatment plans enqueue work; fulfilment calls back into the clerk. Missing: a one-way enqueue port.

---

### 6.8 MEDIUM — isolated 2-cycles (not in the ~110)

```
voice.bot  -lazy→  voice.host  -lazy→  voice.bot
```

Host embeds the Mouth inside FastAPI (`from voice.bot import bot`). The bot lazily `release_worker`s on teardown. Intentional dual-mode hosting. Importing `voice.host` from a unit test can drag Pipecat.

```
observability  -lazy→  voice.admission  -lazy→  observability
```

Metrics sampler reads admission snapshot; admission increments metrics. Fail-soft (`except Exception`).

```
seed_postgres  ↔  seed_susanth
```

Demo seeds. Unreachable from entrypoints. Ignore.

---

### 6.9 LOW — eager package barrels

`treatment` (9 modules), `authority`, `reco`, `live_qa`, `mcp_http`, `providers`, `agent_core` itself, `work_runtime`: `__init__` re-exports an engine; the engine does `from package import sibling`. Works because the submodule is already in `sys.modules`. Import-order-sensitive if a sibling does `from pkg import name` before `__init__` bound `name`.

Worst of these: **`treatment.engine` imports `agent_core.treatment` (the package), not siblings.**

---

### 6.10 Cycle count (so the number is not a slogan)

| Graph | What is counted | Number |
|---|---|---|
| TS runtime SCCs > 1 | 0 | **0** |
| TS type-only SCCs | 1 | **1** |
| Python import-time package-crossing SCCs | 0 | **0** |
| Python coupling SCCs | 4 | **1 giant + 3 tiny** |
| Python giant SCC size | lazy+runtime, first-party | **~108–111 modules** (108 if parent-package synthetic edges omitted; 111 in the explicit-import walk) |
| Direct 2-cycles with `db` on them | coupling | **~21** |
| Praxist runtime SCCs | 0 | **0** |
| Praxist coupling SCCs | 2 | research_loop blob (25) + scheduler↔pids |

Do not quote “321 cycles of length ≤6”. Johnson enumeration on the giant SCC was capped and lexicographically biased. The **glue module** is the finding, not the cycle cardinality.

---

## 7. Architecture boundaries and DIP

### 7.1 Intended backend layers (allowed direction: down)

```
entry (main, bot_worker, worker, voice.bot, mcp_server)
  → adapters (whatsapp, outbound, campaigns, twilio_sms, payments, webhooks)
    → Mouth runtime (voice/*, bot_runtime, bot_tools)
      → agent core (cards, skills, tools, treatment, reco, live_qa)
        → policy / locked engines (grant, authority, compliance, cadence, contact_policy, authz)
          → infra (db, storage, redis, providers)
```

**Measured inner→outer (strict):** ~**90** edges. ~40 of those are `db.py` alone.

| Kind | Count | Notes |
|---|---|---|
| Infra importing outer layers | ~65 | `db` calling engines, WhatsApp, compile |
| Policy importing adapters | 2 | both **Cadence → outbound / campaigns** |
| Core importing adapters | 4 | `treatment.enact` → outbound, twilio_sms, promise_fulfillment |
| Core/policy importing `voice.*` | 2 | live QA barge; text Mouth persist |
| Locked engines importing LLM/voice | **0** | authority, compliance, grant stay below the model |
| Grant imported by production | **0** | ADR-0001 not in the call graph |

There is **no `routers/` package**. HTTP and process entry are fused in `main.py` (314 route decorators, zero `APIRouter`s). That is fan-out, not a cycle.

### 7.2 Inappropriate upward dependencies (worst 10)

Ranked by how much they let a Mouth or a scheduler outvote a Card / Locked Engine.

1. **`MouthTurn.tools()` → `intersect`, not `tools.grant`.** Cardless returns `ToolState(allowed=None, offered=None)` (`skills/runtime.py`). Callers treat `None` as “no filter.” ADR-0002 is accepted and still live.
2. **`voice.tools.build_tools`:** `keep = set(allowed_tool_names) | ALWAYS_ON`. After the Card’s Grant is computed, the Mouth unions tools the author did not attach. Offer is no longer a subset of Grant. This is the hardcoded keep-set ADR-0001 forbids.
3. **`cadence` → `outbound`** (module-level). Cadence may only **repeat** a Mission. Importing the dialler lets the retry loop *place* the call. The file’s own docstring states the boundary this import crosses.
4. **`treatment.enact` → `outbound.place`.** Treatment (what follows an Outcome) dials.
5. **`treatment.enact` → `twilio_sms` / `promise_fulfillment`.** The engine that should decide *whether* also *sends*.
6. **`live_qa.enact` → `voice.twilio_ops`.** A Handoff-shaped barge/whisper is core importing the Mouth stack.
7. **`db` → `whatsapp` / `whatsapp_outbound`.** Persistence sends WhatsApp. Infra is an accidental Mouth.
8. **`db` → `authority.enact`.** Persistence can dispose money (goodwill waiver) without going through a granted tool.
9. **`bot_runtime` → `whatsapp`.** Text Mouth imports the channel adapter; the cycle through `db` / `bot_jobs` closes it.
10. **`praxist.core.workflow` → `reviewer_stub.adapter`** (guest). Core special-cases a plugin implementation.

### 7.3 The permission graph (the one ADR cares about)

Live formulas that still recompute Grant / Offer (none go through `ToolGrant.may_execute` / `offer` / `static_grant`):

| Site | What it computes |
|---|---|
| `skills.intersect.effective_tools` | Grant |
| `skills.intersect.offered_tools` / `idle_offered_tools` | Offer |
| `cards.compile.effective_tools` + Gate G4/G9 | Publish Gate; wraps intersect, **not** `static_grant` |
| `skills.runtime.MouthTurn.tools()` | Per-turn allowed + offered |
| `bot_runtime` | `mouth.tools()` then catalog; cardless → `bot_tools.TOOL_DEFINITIONS` |
| `voice.tools.build_tools` | `allowed ∪ ALWAYS_ON` |
| `flow_graph._FLOW_CONTROL_TOOLS` | Third copy of flow-control names (omits `capture_call_goal`) |
| `grant.VOICE_ALWAYS` | Fourth copy, **pinned by test** to `ALWAYS_ON` |

Catalog itself is a shared leaf. The violation is **many owners of the intersection**, not many owners of the spec list. Three (four) literals of the voice floor are how Flow authoring and the runtime already disagree on `capture_call_goal`.

`grant.py` cannot import `voice.tools` (Pipecat; the API process compiles Cards). That constraint is real. The migration path is: voice imports Grant’s frozenset, not the other way around.

**Handoff consequence, in graph language:** voice still filters the registry **once** at session start, then widens it with `ALWAYS_ON`. A mid-call Card change cannot change the Grant. ADR-0001 said this out loud.

---

## 8. Package graphs — kit vs process vs extras

### 8.1 Habibi npm is a generated UI platform

Production `dependencies` look like a wholesale shadcn install, not a collections CRM.

- **Live Radix (13):** accordion, alert-dialog, checkbox, dialog, dropdown-menu, label, popover, select, separator, slider, slot, switch, tabs.
- **Dead Radix (13):** aspect-ratio, avatar, collapsible*, context-menu, hover-card, menubar, navigation-menu, progress, radio-group, scroll-area, toggle, toggle-group, tooltip.  
  \*`collapsible` is a knip false positive (Voice params panel). Still: half the Radix kit is accidental lockfile surface. 26 directs explode to **53** `@radix-ui/*` lockfile entries.

**Named libraries:**

| Package | In `src`? | Reality |
|---|---|---|
| `liveline` | **No** | Custom SVG `LivelineTrend` / `LivelineSpark`. npm `liveline@0.0.7` is dead pre-1.0 in the production lockfile |
| `recharts` | only unused `ui/chart.tsx` | App charts are hand-rolled. Lockfile marks recharts 2.x deprecated |
| `date-fns` | **No** | Would only matter via unused calendar |
| `@pipecat-ai/client-js` + `small-webrtc-transport` | **Yes** (dynamic `import()`) | Live sandbox voice |
| `@pipecat-ai/client-react` | **No** | Comment only. Pulls jotai for nothing |

Build plugins sitting in `dependencies`: `@tailwindcss/vite`, `tailwindcss`, `tw-animate-css`, `vite-tsconfig-paths`, `@tanstack/router-plugin`. Lovable’s Vite config already injects several of these.

**Transitive risk worth naming:** `nitro@3.0.260603-beta` (dated beta) + Vite 8 (rolldown) + Node ≥ 22.12. Almost every prod dep is caret-ranged; the lockfile is the only freeze. `bun.lock` is committed and **stale** (x-ray): CI uses `npm ci`.

### 8.2 Backend pip — split on paper, union in the venv

`requirements.txt` is tightly pinned (good). Three floats remain: `twilio>=9,<10`, `redis>=5,<6`, `websockets>=12,<16`. pytest and ruff install into the **API Docker image**.

| Import | Declared where | Who actually needs it |
|---|---|---|
| `pipecat.*` | `requirements-voice.txt` | Voice runner. `agent_core.tools.schema` lazy-imports Pipecat so API/bot_worker can build OpenAI tool dicts **without** the voice graph — correct split |
| `fastembed` | voice extra | `agent_core/tools/kb_rerank.py`, called from **`kb_retrieve` (API path)** when `KB_RERANK_ENABLED`. Graph lie: API image cannot honour that flag |
| `mcp` | `requirements-mcp.txt`, unpinned | `mcp_server.py` only |
| `azure.cognitiveservices.speech` | **undeclared** (transitive of `pipecat-ai[azure]`) | `voice/tts_pool.py`. API `azure_speech.py` is httpx REST |
| `temporalio` | **nowhere** | Not imported. `TEMPORAL_ENABLED` loads a stub that raises `temporal_adapter_not_promoted` |

**Docker** matches the split: `collections-api` = `requirements.txt`; `collections-voice` adds the voice extra; MCP is not a compose service.

**Local** does not: `requirements-voice.txt` says install into the **same** `backend/.venv`. API, worker, bot_worker, and voice share site-packages and the native audio stack.

### 8.3 Praxist is the inverted graph the backend only partially matches

Core: three libraries. Optional extras (`agents`, `storage`, `codex`, `product-usage-server`, `docs`) are capability-shaped. Exact pins where runtime identity matters (`claude-agent-sdk==0.2.136`).

Contrast: backend’s “optional” stacks are three requirements *files*, local install is their union, and openai/twilio/tiktoken/minio live in the default API set for every process.

Caveat: `PRAXIST-main/requirements.txt` is a **legacy unpinned ML dump** (transformers, wandb, …) that contradicts `pyproject.toml`. Guest-tree noise, not Habibi’s graph.

---

## 9. Accidental global infrastructure

Modules that function as a platform kernel without being named as one:

| Module | Why it is global | Should it be? |
|---|---|---|
| **`db.py`** | Ca 101, Ce 52, 115 delayed imports, ~21 two-cycles, ~110-SCC glue. Serializes HTTP, enacts Authority, compiles Cards, retrieves KB, sends WhatsApp, records Outcomes | No. SQL façade ≠ application service |
| **`main.py`** | Fan-out 78, 314 routes, zero routers | Yes as *entry*; no as *the* HTTP layer forever |
| **`agent_core/__init__.py`** | Eager `deployment` → `db`. Importing sentiment loads Postgres | No. Barrel should not bind infra |
| **`voice/tools.py`** | 2,914 lines, Ce 29, `ALWAYS_ON` owner, tool bus for Authority/reco/skills/KB/Twilio | Local Mouth god. Expected density; unexpected permission ownership |
| **`schemas.py`** | Not a hub (in=2) but runtime-imports `flow_graph`, which is how HTTP DTOs join the knot | Name collision: this is HTTP DTOs, **not** Agent Card schema |
| **`src/lib/utils.ts` (`cn`)** | Fan-in 213 | Yes |
| **`src/api/config.ts`** | Fan-in 67, `USE_MOCK` leaked into UI | The client belongs; the mock switch in screens does not |
| **`src/data/customer360-seed.ts`** | Fan-in 25 — account record | No. Types are not fixtures |
| **`src/components/ui/lozenge.tsx`** | Fan-in 107 — Gate/Outcome vocabulary | Primitive yes; domain enum no |
| **`RecordsTable`** | Fan-in 20 — collections list primitive | Yes. The unused barrel is the smell |

---

## 10. Praxist (guest) — contract vs graph

Praxist is not the collections product. It sits in the workspace and has a written core/plugin/task boundary (`PRAXIST-main/AGENTS.md`). The graph mostly honours it.

| Rule | Graph |
|---|---|
| Core must not import plugin implementations | **One hit:** `praxist.core.workflow` lazily imports `plugins.workflow_stages.reviewer_stub.adapter.run_local_artifact_review` for local reviewer modes |
| Plugins may import core | 82 coupling edges. Allowed. Core hubs: `protocol` (15), `storage` (13), `redaction` (11) |
| Registry discovers plugins via `importlib` + `plugin.yaml` | Confirmed. Static core→plugin edges are not the discovery path |
| Task projects must not be imported by `praxist/` | Confirmed (CLI listing aside) |
| Import-time cycles | **0** |
| Coupling SCCs | **2**: 25-node research_loop + finding-graph + evaluation_tools blob; `experiment_scheduler_client` ↔ `protected_pids` |

Research-loop blob (lazy):

```
evaluation_tools.adapter  →  findings_sync  →  findings_collection  →  adapter
agent  →  peer_memory  →  findings_collection  →  resume_state  →  pi_agent  →  agent
finding_graph engine  ↔  viz
```

`findings_collection` lazily imports `evaluation_tools.adapter._gen_id_from_peer_id`. A workflow-stage module importing a tool_server adapter is the same class of violation as core importing a plugin, one layer down. AGENTS.md already owns this as migrated compatibility code **inside** `workflow_stage:research_loop`. It is plugin-local mud, not a core leak — except the reviewer_stub shortcut.

Praxist import-time is cleaner than Habibi’s backend. The remaining mess is one plugin plus one core shortcut.

---

## 11. Architectural meaning

### What the graphs say about the product

Habibi is a **collections operations console** plus a **Mouth compiler**.

- Ops slices (inbox, floor, handoff, 360, disputes, promises, documents, callbacks, consent, upsell, compliance, QA, audit, routing, webhooks) are **parallel**: `routes/X` → `components/X` → `api/X` → `data/X-seed`. Low coupling *between* slices. Shared gravity is chrome, `cn()`, lozenge, `RecordsTable`, and **customer360-seed**.
- Mouth / Agent Studio is a **star** on both sides of HTTP: `prompt-studio.lazy.tsx` + `api/agent-studio.ts` in the UI; `cards.compile` + `db.publish_*` + `skills.intersect` in Python. Skill Packs, Tool Grants, Flow, Gates, outbound, evals, and sandbox all attach here.

The Python runtime is a **modular monolith that already knows how it wants to look**. Locked Engines (authority, treatment, reco, live QA) and contact policy are real packages with healthy *type* leaves (`cards.schema`, `skills.pack`, `catalog`, `policy_rules`). They do not import the LLM. They **do** import `db`, and `db` imports them back. Policy engines own money, contact, and consent **as code**; they do not own the **call graph**.

Cadence’s module docstring is the architecture: *retry the same Mission; only treatment may change the action.* Cadence’s imports are the violation: `import outbound`. Treatment’s `enact` then also dials and SMS-sends. Two engines that should only *decide* now *speak*.

The frontend’s corresponding sin is milder: mock seeds reimplement contactability (`consent-seed.isContactableNow`) and routing (`routing-seed.evaluateRule`) beside the backend Gate. Live tenants correctly defer. Mock mode is a second opinion the comments say must not disagree with the dialler.

### What “acyclic” is hiding

An import-time DAG with 60% lazy imports is a **delay tactic**. It is the right tactic for not crashing `voice.bot` at prompt-assembly (the cards/skills cycle was a real outage). It is the wrong thing to celebrate as layering. The coupling SCC is the graph that Handoff, publish, and Locked-Engine enactment actually walk.

### Transitive cost of touching one module

- Import `agent_core` (the barrel) → deployment → `db` → Postgres.
- Import `voice.host` → can drag the full Pipecat pipeline (`voice.bot` 2-cycle).
- Import `bot_tools` → `db` + catalog + capture; jobs close back to `bot_runtime`.
- Import `@/components/charts` → eight chart modules, even if you wanted one sparkline.
- Depend on `@radix-ui/react-menubar` → you ship it even though no screen imports it.

---

## 12. Ranked findings

| Sev | Finding | Graph evidence | Why it matters |
|---|---|---|---|
| **P1** | `db.py` is the platform kernel | Ca 101, Ce 52, ~21 two-cycles, ~110-SCC glue, 18k lines | Every Mouth, Gate, Locked Engine, Mission, and work-runtime path round-trips here. No Handoff, no Grant swap, no engine swap without this blob |
| **P1** | ADR-0001 unwired: `grant.py` is an orphan | Production importers = 0; live math in `intersect` + `MouthTurn` + `ALWAYS_ON` | Publish Gate, text Mouth, and voice still recompute. Connector drift already happened. Cardless still fail-opens (ADR-0002) |
| **P1** | Voice Mouth unions `ALWAYS_ON` after the Card speaks | `voice/tools.py` `keep = allowed \| ALWAYS_ON` | Offer ⊈ Grant. Session-start filter cannot change on Handoff |
| **P2** | Cadence and treatment.enact import the dialler | `cadence.py` module-level `import outbound`; `treatment/enact.py` lazy `outbound.place` / `twilio_sms` | Policy that may only repeat or decide a Mission now places it |
| **P2** | `agent_core` barrel + `voice.persist` close voice into the WhatsApp knot | cycle §6.3 | Persist was extracted from `db` and then reattached through the barrel |
| **P2** | `schemas` → `flow_graph` | HTTP DTOs import the Flow domain model | Flow joins the ~110-SCC; transport and authoring share a type the wrong way |
| **P2** | Domain types trapped in `data/*-seed.ts`, especially `customer360-seed` (fan-in 25) | 191 component→data edges | Cannot turn mocks off without touching 360, API, and insights |
| **P2** | Unused shadcn/Radix/liveline/recharts/form kit | 27 unused prod deps, ~21 unused `ui/*`, dead `records/index.ts` | Production lockfile attack/audit surface for widgets the product does not ship |
| **P2** | `fastembed` declared as voice extra, invoked from API retrieval | `kb_retrieve` → `kb_rerank` | Process graph lies; `KB_RERANK_ENABLED` breaks the API image |
| **P3** | `api/promises.ts` types from sheet components | 2 type-only api→UI edges | PTP write contract owned by JSX |
| **P3** | `USE_MOCK` / `apiGet` in ~20 screens; `TwinTab` uses config as HTTP client | `api/config.ts` fan-in 67, including UI | Presentation encodes backend mode |
| **P3** | `prompt-studio.lazy.tsx` fan-out 27 | Mouth editor God route | Largest UI change-risk surface (Flow, Gates, Skill Packs, Tool Grants) |
| **P3** | Charts barrel fan-in 25 | No cycle | Every sparkline depends on the kit. Records already showed the better pattern (direct leaf imports) |
| **P3** | `lib/gate-status` and callback seed → lozenge | type-only | Gate/Cadence status modeled as a chip tone |
| **P3** | Praxist `core.workflow` → `reviewer_stub` | 1 forbidden lazy import | Core knows a plugin module path |
| **P4** | Generated `routeTree.gen.ts` ↔ `router.tsx` | type-only | Ignore |
| **P4** | `voice.bot` ↔ `voice.host`, observability ↔ admission | isolated 2-cycles | Contained |
| **P4** | Knip unused-file false positives | offer-health, collapsible, resizable, table, section-message | Do not delete from knip alone |

**If you cut one cycle:** stop `db.py` from importing engines. Give treatment / authority / compile / canary a store protocol. That collapses the ~110-SCC. Do **not** module-level-import `grant` from `compile` or `cards/__init__.py`.

**If you wire one module:** import `ToolGrant` from `MouthTurn.tools()`, `cards.compile` G4/G9, and `voice.tools.build_tools` (voice reads Grant’s frozenset; Grant never imports Pipecat). Delete the pin test’s “three copies” section when only one remains.

---

## 13. What is healthy (so the graph is not only a complaint)

- **Zero TypeScript app cycles.** Zero `components → routes`. Feature folders map to collections domains. Lazy routes keep stub leaves small.
- **Python import-time DAG**, with a test that boots the dangerous modules in a fresh interpreter. The cards/skills outage was real; the fix is real.
- **Agent Card, Skill Pack, and tool catalog are leaves.** That is the shape a Grant owner can sit on.
- **Locked Engines do not import the LLM or Twilio** (except live QA barge and treatment enact — those are the DIP misses, and they are localised).
- **`contact_policy` / `policy_rules`:** high fan-in, low fan-out. Reachability as data + one `admit`.
- **`main` and `mcp_server` are true roots.** Voice *process* (`voice.bot`) is a true root; only persist leaked.
- **Frontend ↔ backend is HTTP only.** Praxist is not on the product import graph.
- **Praxist core is three packages and plugin discovery is data.** The inverted graph exists in this workspace as a worked example.
- **Characterization tests for the Grant migration already exist** (`test_tool_grant.py`, `test_tool_grant_characterization.py`). The destination is specified; the call graph has not moved.

---

## 14. Method appendix

**TypeScript.** Import graph over `Habibi/src` resolving `@/` and relatives. Compared to knip unused files (`artifacts/frontend-static-review/summary.json`). Madge circular check used as a corroboration, not as the source of truth on Windows.

**Python.** AST walk of `import` / `from … import` / `importlib.import_module`. Classification: module-level = runtime; inside `FunctionDef`/`AsyncFunctionDef` = lazy; under `if TYPE_CHECKING` = type-only. SCCs via Tarjan. Degrees reported on the coupling graph unless labelled import-time. Parent-package synthetic edges were **not** added in the cycle catalog (a cycle is an explicit import loop). Giant-SCC size therefore differs by a few modules depending on whether `__init__` re-exports are in the walk — hence “~108–111”.

**Packages.** Manifests + `package-lock.json` + knip unusedDepsList + grep of import specifiers. No `npm ls` tree dump. No pip freeze of transitives (backend has no lockfile).

**Not claimed.** Runtime bundle sizes, Python import *time*, or that a static unused file is safe to delete without a product pass (floor `CallTile` looks dead; confirm the live floor table covers its alerts first).
