# 34 — Incremental-generation maintenance patterns

**Role:** Software forensics engineer, maintenance-pattern detection.  
**Question:** Where has rapid, feature-at-a-time development left *architectural entropy* — copy-modify families, unadopted primitives, speculative seams — that a later change will have to hold in its head?  
**Scope:** `Habibi/src` and `backend/`. Guest tree `PRAXIST-main/` is out of scope.  
**Date:** 2026-09-03  
**Mode:** Read-only. The only file written is this report.  
**Companions:** `06-duplication.md` (clones and drifted rules), `07-dead-code.md` (kit leftovers), `09-canonical-implementations.md` (who should own a question), `10-complexity-smells.md` (gods, not managers), `27-typescript-integrity.md` (seed types as live wire types).  
**Vocabulary:** `CONTEXT.md`. **Mouth**, **Agent Card**, **Tool Grant**, **Locked Engine**, **Offer**, **Gate**, **Cadence**, **Outcome** are that glossary.

**This is not an authorship claim.** Nothing below asserts that a model wrote a file. The signals are structural: the same screen was stood up again with the nouns swapped; a Protocol describes a second implementation that does not exist; a shared primitive was built and then the next feature did not import it. Those are maintenance patterns of *incremental generation*, human or otherwise.

**Method:** six parallel analysts (abstraction, duplication, naming, wrapper-chain, consistency, generated-scaffolding), then every headline claim re-read from the files named in this session.

---

## 1. Verdict

The product does **not** have a Java-style `*Manager` / `*Service` / `*Handler` explosion. `10-complexity-smells.md` already measured that. The entropy here is a different shape: **a screen factory and an engine factory**.

A queue screen is not designed once. It is copied. The copy is then edited until the new domain nouns compile. The fingerprint is the same six filenames, the same comment banner, a local `Chip` / `Tile` / overlay that a sibling already defined, and a `Filters` interface that lives in the seed file. Six `FiltersBar.tsx` files, five-plus `MetricsStrip.tsx` files with two visual languages, and a homemade `fixed inset-0 z-40` overlay family that sits *beside* shadcn `Sheet` are that factory.

A decision engine is not designed once either. `agent_core/reco`, `agent_core/treatment`, and `agent_core/authority` share the same first sentence (`Orchestration — the only entry point callers need.`), the same `FeatureProvider` Protocol with a docstring about a REST feature store that is not in the tree, and the same `MODE_OFF` / `MODE_SHADOW` / `MODE_LIVE` config. Three engines answering three questions is legitimate depth. Three copies of a seam that only ever has one SQL adapter is speculative.

The dangerous layer is not the unused shadcn kit. It is the copies that **already disagree**: two `fmtMoney` functions, two `createPromise` POST bodies, two overlay z-indexes, `Promise` / `Dispute` / `Channel` typed differently per seed, `QueryState` built to stop empty-from-error and then used in one file, `agent-card.ts` built so the studio would stop holding `Record<string, unknown>` and then `agent-studio.ts` still holding it.

Do not add a seventh `FiltersBar` abstraction, a `SheetManager`, or a generic `EngineBase`. The primitives that should win already exist: shadcn `Sheet`, `QueryState`, `FilterTable` / `RecordsTable`, `Lozenge` / `SlaPill`, `env_utils.env_float`, `money_inr`, `agent-card.ts`, `contact_policy.admit`. Consolidation is adoption, not invention.

---

## 2. Scope

| In | Out |
|----|-----|
| `Habibi/src/**` product TypeScript | `PRAXIST-main/` |
| `backend/` product Python (engines, flags, adapters, API mappers) | `node_modules/`, `.venv/`, Alembic bodies except as leftover evidence |
| Generated `routeTree.gen.ts` and shadcn `components/ui/*` as scaffolding | Secret values, live cluster |
| Comment banners and filenames as fingerprints | Authorship, git-blame psychology |

---

## 3. Methodology

| Analyst | What it looked for |
|---------|--------------------|
| Abstraction | Protocols / ABCs with 0–1 implementations; speculative adapters; unused engines; config objects wrapping a flag |
| Duplication | Near-identical modules; copy-modify fingerprints; feature-specific versions of a shared job |
| Naming | Same concept, several names; same name, several concepts; filename vs primitive mismatch |
| Wrapper-chain | Pass-through hops; Manager/Service/Handler/Factory/Adapter suffixes; mock/live/API/page depth |
| Consistency | Each feature inventing its own loading, overlay, money, table, query, error path |
| Scaffolding | Kit leftovers, seed-as-architecture, dead flags, generated files, compatibility shims |

A pair of files is a **factory clone** when the *job* is the same (filter a queue, render five KPIs, open a side panel) and the *delta* is nouns, labels, and one extra control. Two engines that answer different regulated questions and share a pipeline *shape* are a **skeleton clone**: legitimate if the leaves are shared, entropy if the seam is copied too.

Inference is labelled. Token-identical `Chip` helpers are high-confidence clones. "This looks like a prompt template" is not used as evidence.

---

## 4. Taxonomy

Seventeen patterns. They compose: a feature-folder clone (P1) almost always carries a comment-header template (P2), a local primitive fork (P5), and a name/chrome mismatch (P11).

| ID | Pattern | Signature | What a later edit hits |
|----|---------|-----------|------------------------|
| **P1** | Feature-folder clone | Same filenames (`FiltersBar`, `MetricsStrip`, `*Sheet`, `*Card`/`*Board`, `*-seed.ts`, `api/*.ts`), domain nouns swapped | A UX fix in one queue does not reach the others |
| **P2** | Comment-header template | Identical banner (`data access seam`, `mirrors the promises-seed pattern`) | Noise; the useful signal is that the *body* was cloned with the header |
| **P3** | Seed-became-contract | Mock factory types used as `apiGet<T>` | Server nulls / extra fields are invisible to `tsc` (see `27`) |
| **P4** | Homonymous types | Same English word, different shapes | Import the wrong `Promise` / `Dispute` / `Channel` / `Filters` |
| **P5** | Local primitive fork | Shared helper exists or a sibling already defined it; the copy stays | `fmtMoney` already disagrees; `Chip`/`toggle` are byte-identical in two files |
| **P6** | Unadopted shared primitive | A canonical widget was extracted; later screens did not import it | `QueryState`, `FilterTable`, `Sheet`, `SlaPill`, `AgentCard`, `env_utils` |
| **P7** | Speculative seam | Protocol / adapter / flag for N=0 or N=1 live implementations | `FeatureProvider` "REST / feature store"; `grant.py`; `agent_cards_enabled`; Temporal stub |
| **P8** | Package skeleton clone | Directory + entry-module docstring copied across engines | Reco / treatment / authority: three `engine.py`, three `features.py`, three mode enums |
| **P9** | Policy view-model twin | Parallel `status` / `LABEL` / `TONE` / `emptyX()` modules | `offer-policy.ts` ↔ `authority-policy.ts` |
| **P10** | Dual write mapper | Two functions POST the same path with different bodies | `api/customers.createPromise` vs `api/promises.createPromise` |
| **P11** | Name / chrome mismatch | Filename says Drawer/Sheet/Manager; the primitive is something else | `*Drawer` is `Sheet`; `*Sheet` is a homemade overlay; page titles say Manager |
| **P12** | Kit dump | Scaffolding shipped with the app shell, never imported by product routes | Unused shadcn modules; `BigBoundMark`; `ui/drawer` |
| **P13** | Config copypasta | Magic numbers restated after a default already exists | `staleTime: 15_000` on `QueryClient` *and* on most `useQuery`s |
| **P14** | Client Locked Engine | UI recomputes a regulated rule the server already owns | `isContactableNow` / `contactableSummary`; insights `?? deriveCustomerInsights` |
| **P15** | Dead compatibility prop | Parameter kept "for source compatibility" and ignored | `ContactablePill.dense` |
| **P16** | Worker-loop clone | Same `process_one(engine) -> bool` claim→run→retry skeleton, domain `handle_*` swapped | 15+ backend queues; `mark_failed_or_retry` already drifted |
| **P17** | Twin widgets, twin sources | Two UI names for one operator question, different data owners | `ContactablePill` (seed math) vs `ContactabilityPill` (API) |

**Not in this taxonomy (different reports):** competing *formulas* for Tool Grant / contact admit / Outcome vocab (`06`, `09`); god modules (`10`); HTTP IDOR (`11`, `18`). Those are control-plane defects. This report is about *how screens and engines get multiplied*.

---

## 5. What this is not

| Looks like entropy | Why it is not (or not this report) |
|--------------------|-----------------------------------|
| `apiGet` → `fetchPromises` → `usePromises` → page | Legitimate mock/live + HTTP boundary. The hop that *is* entropy is typing `T` from a seed file (P3), not the wrapper depth. |
| Three engines (reco / treatment / authority) | Three questions: in-call **Offer**, next **contact**, fee **authority**. Skeleton clone (P8) is the copied *seam*, not the existence of three owners. |
| `voice/flows.py` vs `flows_dynamic.py` | Dual path with an explicit selector (`VOICE_FLOW_GRAPH`). Compatibility, documented. |
| `work_runtime/adapter_temporal.py` raising | Fail-closed stub behind `TEMPORAL_ENABLED`. Reached when the flag is on. Not dead; not a second live orchestrator. |
| `campaign_runtime_enabled()` | Live: `cadence.py` and `campaigns.py` call it. `07` listed it as unread; that is stale. |
| shadcn `button` / `spinner` / `sheet` | Kit that product actually imports. |
| `routeTree.gen.ts` `@ts-nocheck` | Generated. Exclude from hand-written entropy. |
| Four English meanings of **Offer** | Naming *collision* (`06`). Merging them would be a worse bug. |

---

## 6. Key findings

| ID | Pattern | Severity | Confidence | Finding | Location |
|----|---------|----------|------------|---------|----------|
| F1 | P1+P5 | P1 | high | Six `FiltersBar.tsx` files. Documents and callbacks share a byte-identical `Chip` + `toggle`. Promises uses shadcn `Select`; disputes/upsell inline `<select>` + local chips. No shared filter chrome. | `Habibi/src/components/{promises,documents,disputes,callbacks,upsell,dashboard}/FiltersBar.tsx` |
| F2 | P1+P5 | P1 | high | `MetricsStrip` is two visual languages copied inside each. Promises/disputes/upsell: bordered card + `heading-large`. Callbacks/documents: icon-in-box horizontal row. Local `Tile` in every file. | `Habibi/src/components/**/MetricsStrip.tsx` and `*StatsStrip.tsx` |
| F3 | P1+P11 | P1 | high | Homemade overlay family (`fixed inset-0 z-40 flex` + `aria-label="Close overlay"`) in disputes, documents, callbacks. Upsell uses a *third* chrome (`z-50`, backdrop on the root). Promises/webhooks/billing use shadcn `Sheet` while naming the file Drawer. `ui/drawer.tsx` has no product import. | Overlay grep; `PlanDetailDrawer.tsx`; `EndpointDrawer.tsx`; `ServiceDrawer.tsx` |
| F4 | P2 | P2 | high | Twenty `api/*.ts` files open with `// … — data access seam.` Documents-seed says it "mirrors the promises/disputes-seed pattern." | `Habibi/src/api/*.ts`; `documents-seed.ts:2` |
| F5 | P3+P4 | P0 | high | Seed files own live shapes. `Promise` in `customer360-seed.ts` ≠ `Promise` in `promises-seed.ts`. `PtpStatus` omits `due_today`. `Channel` disagrees across five seeds. `apiGet<Customer[]>` trusts the 360 seed. | Seeds + `api/config.ts:183` + `27` |
| F6 | P5 | P1 | high | `fmtMoney` in `customer360-seed.ts` maps null to `₹0`. `fmtMoney` in `upsell-seed.ts` maps null to `"—"`. Disputes/documents/promises re-export the 360 version. Billing invented `inrCompact`. Backend has `money_inr`. | Seeds; `billing-seed.ts`; `backend/money_inr.py` |
| F7 | P6 | P1 | high | `QueryState` exists specifically to stop `query.data ?? []` lying. One product import (`AgentCardPanels`). Everyone else uses `LoadingState` or inline pending. `FilterTable` comment says prefer it for callbacks/documents; promises/disputes/upsell built boards instead. | `query-state.tsx`; `FilterTable.tsx`; `AgentCardPanels.tsx` |
| F8 | P7+P8 | P1 | high | `FeatureProvider` Protocol copied across treatment / reco / authority. Docstring promises a REST/feature-store adapter. Live class is `SqlFeatureProvider` or `PostgresFeatureProvider` (the copy did not even keep the name). `Recommender` Protocol copied treatment ↔ reco. | `agent_core/{treatment,reco,authority}/features.py`; `*/scoring.py` |
| F9 | P8 | P1 | high | `engine.py` in reco, treatment, and authority share the opening contract. Treatment's module *says* "One deliberate divergence from `reco.engine`." Reco `config.py` still has a local `_env_float` after `env_utils.env_float` exists; treatment imported the leaf. | `*/engine.py`; `reco/config.py:31`; `env_utils.py` |
| F10 | P7 | P1 | high | `grant.py` documents "Nothing imports this yet." `agent_cards_enabled()` has no production caller (tests only). Temporal adapter only raises. | `agent_core/tools/grant.py`; `platform_flags.py`; `work_runtime/adapter_temporal.py` |
| F11 | P9 | P2 | high | `offer-policy.ts` and `authority-policy.ts` are the same module with the nouns swapped: status union, `LABEL`, `TONE`, `emptyX()`. | `Habibi/src/lib/offer-policy.ts`, `authority-policy.ts` |
| F12 | P10 | P0 | high | Customer 360 `createPromise` POSTs `{ customerId, accountId, amount, promisedDate, channel }` with no owner. Promises desk `createPromise` POSTs owner triplet + `reminderStatus` via `resolveActor`. Same path, drifted body. Same split for `createDispute`. | `api/customers.ts`; `api/promises.ts`; `api/disputes.ts` |
| F13 | P14 | P0 | high | Consent screen computes contactability in the seed (`isContactableNow` / `contactableSummary`). `ContactablePill` renders it. Server `contact_policy.admit` is the Locked Engine. C360 insights still `?? deriveCustomerInsights` after the fetch already falls back. | `consent-seed.ts`; `ContactablePill.tsx`; `customers.$customerId.lazy.tsx` |
| F14 | P6 | P1 | high | `agent-card.ts` exists so the studio would stop `Record<string, unknown>` + `as never`. `agent-studio.ts` still types `agentCard` / `publishedCard` / compile `card` as `Record<string, unknown>`. | `api/agent-card.ts`; `api/agent-studio.ts:49-51,72` |
| F15 | P12 | P2 | high | Unused shadcn inventory and `BigBoundMark` (file says unused; live mark is `EqualizerMark`). `ContactablePill.dense` ignored "for source compatibility." | `07-dead-code.md`; `BigBoundMark.tsx`; `ContactablePill.tsx:5-7` |
| F16 | P13 | P2 | high | `QueryClient` default `staleTime: 15_000`, then restated on nearly every feature `useQuery`. `UNASSIGNED = "Unassigned"` copied in three API modules; `DisputeSheet` then inlines `"Unassigned"` anyway. | `router.tsx:10`; `api/{promises,disputes,documents,callbacks}.ts`; `DisputeSheet.tsx:135` |
| F17 | P16 | P1 | high | Job workers share `process_one` + `mark_failed_or_retry`. WhatsApp outbound's retry already diverged (Meta dead-letter rules). No shared runner; `bot_worker.process_one_any` only fans out. | `bot_jobs.py`, `whatsapp_outbound.py`, `cadence.py`, `campaigns.py`, `call_closer.py`, `webhooks_dispatch.py`, … |
| F18 | P5 | P1 | high | `_handoff_call` in `main.py` is a stale copy of `_handle_write`: still `str(exc)` on KeyError (the repr leak `_handle_write` was written to stop) and no `IntegrityError` → 409. | `main.py:720` vs `main.py:1311` |
| F19 | P14+P17 | P0 | high | Consent desk renders `ContactablePill` from seed `contactableSummary`. C360 header renders `ContactabilityPill` from `GET /contact-policy`. Same operator question, two widgets, two owners. | `consent/ContactablePill.tsx`; `customer360/ContactabilityPill.tsx` |
| F20 | P7 | P1 | high | `mockAuthorityNext` in `api/authority.ts` reimplements `recommend_authority` against the seed (~300 lines). File header warns not to duplicate the matrix; the mock still does. | `Habibi/src/api/authority.ts:488` |
| F21 | P7 | P1 | high | `FeatureProvider` is accepted as `provider=` on the three engines and **never passed from production** (`voice/`, `main.py`, `enact.py`). Only tests inject fakes. The Protocol is a test seam with a REST docstring. | `treatment/features.py` `build_features`; authority/reco twins |
| F22 | P5 | P2 | high | `cadence.enabled()` and `campaigns.enabled()` are one-line renames of `campaign_runtime_enabled()`. The flag is live; the wrappers are not. | `cadence.py:66`; `campaigns.py:60` |
| F23 | P1 | P1 | high | `PromiseCard` and `DisputeCard` share the kanban shell: `draggable` + danger banner + customer/account header + `fmtMoney`. Banner copy and extra chips differ. | `promises/PromiseCard.tsx`; `disputes/DisputeCard.tsx` |
| F24 | P12 | P2 | high | `test_tool_grant_characterization.py` opens `SCAFFOLDING — delete this file in #13`. It pins seven live formulas equal to unused `grant.py`. CI runs entropy, not behaviour. | `backend/tests/test_tool_grant_characterization.py:1` |

---

## 7. Pattern families

### 7.1 The screen factory (P1, P2, P5, P11)

A queue feature is a directory, not a composition. Typical members:

| Slot | Examples |
|------|----------|
| Seed + types + `Filters` + mutators | `promises-seed.ts`, `disputes-seed.ts`, `documents-seed.ts`, `callbacks-seed.ts`, `upsell-seed.ts` (24 `*-seed.ts` files total) |
| API seam with mock/live | matching `api/*.ts` |
| `FiltersBar.tsx` | six files, same export name |
| `MetricsStrip.tsx` / `*StatsStrip.tsx` | ~19 strip files |
| Detail `*Sheet.tsx` + `New*Sheet.tsx` | 16 product sheets |
| `*Card.tsx` / `*Board.tsx` | PromiseCard, DisputeCard, LeadCard; DisputeBoard, LeadBoard |

Documents-seed states the clone in the first comment:

```1:2:Habibi/src/data/documents-seed.ts
// Document Fulfillment Desk seed data
// Mutable in-memory store — mirrors the promises/disputes-seed pattern.
```

The API files use one banner. Twenty hits on `data access seam`, including:

```1:4:Habibi/src/api/promises.ts
// -----------------------------------------------------------------------------
// Promise-to-Pay & Payment Plans — data access seam.
//   fetchPromises()      → pipeline list   (GET /promises)
```

```1:4:Habibi/src/api/disputes.ts
// -----------------------------------------------------------------------------
// Disputes & Exceptions Queue — data access seam.
//   fetchDisputes()  → kanban list   (GET /disputes)
```

That header is not a defect. It is a fingerprint that the *next* file was started from the last one.

**FiltersBar.** Same export, incompatible props (`onChange` vs `onPatch`, counts vs no counts, shadcn `Select` vs raw `<select>`). Documents and callbacks share this helper verbatim:

```22:44:Habibi/src/components/documents/FiltersBar.tsx
function Chip({ on, label, onClick }: { on: boolean; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-full border px-100 py-025 text-body-small",
        on
          ? "border-border-brand bg-background-brand-subtlest text-text-brand font-semibold"
          : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
      )}
    >
      {label}
    </button>
  );
}

function toggle<T>(arr: T[], v: T): T[] {
  return arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v];
}
```

Callbacks copies both functions. Disputes/upsell inlined `toggleType` / `toggleSource` instead of importing `toggle`. Promises invented `StatusChip` with a `toneRing` map. Dashboard's `FiltersBar` is a page header (title + range/segment/team + Export) that only shares the filename.

**MetricsStrip.** Promises and disputes are the same `Tile` (tone unions `default | amber | red | brand | green`, identical class maps) with different icons and labels. Callbacks and documents are a second `Tile` (icon box, tones `brand | amber | emerald | red | slate`). Upsell forked the card `Tile` and added `violet` plus null rendering (`"—"` vs `"0"`). Workspace/floor/QA/consent each invented another strip. There is a dashboard `KpiTile` / `HeroKpiCard` pair on yet another chrome.

**Overlay vs Sheet.** Two (really three) side-panel implementations:

| Family | Chrome | Files |
|--------|--------|-------|
| A — shadcn `Sheet` | `SheetContent side="right"` | `PromiseSheet`, `PlanBuilderSheet`, `PlanDetailDrawer`, `EndpointSheet`, `EndpointDrawer`, `ServiceDrawer`, `ViolationSheet` |
| B — homemade z-40 | `fixed inset-0 z-40 flex` + close-overlay button + `<aside>` | `DisputeSheet`, `NewDisputeSheet`, `RequestSheet`, `NewRequestSheet`, `CallbackSheet`, `NewCallbackSheet` |
| C — homemade z-50 | `fixed inset-0 z-50 flex justify-end bg-black/30` | `LeadSheet`, `NewLeadSheet` |

Family B's create sheets (`NewDisputeSheet`, `NewRequestSheet`) are the same 25rem panel: toast on pick-customer, `busy` flag, identical overlay markup, domain fields swapped. Family A files named Drawer still import `Sheet`. `Habibi/src/components/ui/drawer.tsx` (vaul) is unused by product routes (`07`).

Page titles continue the Manager vocabulary the code never used as a type: "Upsell & Leads Manager", "Callback & Scheduling Manager". Help popover: "Callback Manager". Quick actions toast: "Opens Callback Manager — coming soon."

### 7.2 Seed-as-architecture (P3, P4)

Twenty-four `*-seed.ts` files. They started as mock values. They now own:

- the TypeScript interfaces the live `apiGet<T>` asserts
- per-feature `Filters` interfaces (five of them, all named `Filters`)
- formatters (`fmtMoney`, `fmtDate`, `inrCompact`)
- in-memory mutators the mock branch still calls

`customer360-seed.ts` `Promise` vs `promises-seed.ts` `Promise`:

```52:61:Habibi/src/data/customer360-seed.ts
export interface Promise {
  id: string;
  amount: number;
  promisedDate: string;
  createdAt: string;
  channel: Channel;
  handler: string;
  status: PtpStatus;
  reminderStatus: "queued" | "sent" | "acknowledged" | "off";
}
```

```21:44:Habibi/src/data/promises-seed.ts
export interface Promise {
  id: string;
  customerId: string;
  customerName: string;
  accountTail: string;
  amount: number;
  promisedDate: string; // ISO
  createdAt: string;
  channel: PromiseChannel;
  source: PromiseSource;
  owner: string;
  reminderStatus: ReminderStatus;
  status: PromiseStatus;
  // ...
}
```

`PtpStatus` is `"upcoming" | "kept" | "broken" | "partial"`. Desk `PromiseStatus` adds `"due_today"`. Reminder enums disagree (`queued` vs `scheduled`). `api/promises.ts` aliases the desk type as `Ptp` to dodge the collision; C360 still has its own.

`Channel` (and cousins) by file:

| File | Union |
|------|-------|
| `customer360-seed.ts` | `"voice" \| "whatsapp" \| "chat" \| "email" \| "sms"` |
| `inbox-seed.ts` | same members, different order |
| `audit-seed.ts` / `floor-seed.ts` | `"voice" \| "whatsapp" \| "sms"` (no chat/email) |
| `bot-analytics-seed.ts` | `ChannelKey` includes `"all"` |
| `agent-card.ts` | `"voice" \| "whatsapp" \| "sms" \| "internal" \| "mcp" \| "a2a"` |
| `grant.py` | `Literal["voice", "text"]` |
| `consent-seed.ts` | `ConsentChannel` uses `"call"` not `"voice"` |
| `customer360` `Consent.channel` | `"call" \| "whatsapp" \| "sms" \| "email"` |

`HandlerKind` is `"bot" \| "human"` on the floor and `"bot" \| "human" \| "handoff"` on audit. QA scoring queue adds the same third value locally.

This is `27`'s false safety property, restated as a generation pattern: each screen invented the type it needed, then `JSON.parse(text) as T` made the invention look like a contract.

```171:183:Habibi/src/api/config.ts
export async function apiGet<T>(path: string, init?: { signal?: AbortSignal }): Promise<T> {
  // ...
  return JSON.parse(text) as T;
}
```

### 7.3 Formatter and constant forks (P5, P13)

**Money.** `customer360-seed.ts` `fmtMoney` treats non-finite as `0` and always uses `toLocaleString("en-IN")`. `upsell-seed.ts` `fmtMoney` treats null as `"—"`, then Cr / L / k compact. Disputes, documents, and promises `export const fmtMoney = _fmtMoney` from 360. Billing has `inrCompact` (tested). Backend `money_inr` is the Locked Engine for arithmetic. Display has no owner.

**UNASSIGNED.** Declared in `api/disputes.ts`, `api/documents.ts`, `api/callbacks.ts`. `DisputeSheet` then builds `["Unassigned", ...assignees]` as a string literal and does not import the constant. Copy-modify dropped the import.

**staleTime.** `router.tsx` sets QueryClient default `15_000`. Feature hooks repeat `staleTime: 15_000` anyway (promises, disputes, documents, callbacks, consent, qa, billing, …). The repetition does not change behavior. It is the API-file template including a line the default already covers.

### 7.4 Unadopted primitives (P6)

The tree already contains the consolidations a later pass would invent:

| Primitive | Job | Adoption |
|-----------|-----|----------|
| `QueryState` | pending / error / empty must not collapse | One call site (`AgentCardPanels`). Comment documents the exact failure (`query.data ?? []`) that list screens still do. |
| `LoadingState` | spinner + label | Widely used. The *weaker* of the two loading widgets won. |
| `FilterTable` | chip-filtered queue table | Documents `RequestsTable`, callbacks `CallbackList`, some C360 tabs, billing invoices. Promises/disputes/upsell: custom boards. |
| `RecordsTable` | wide CRM grid | Customers, audit. Comment on `FilterTable` already tells you which to use. |
| shadcn `Sheet` | side panel | Promises, webhooks, billing, compliance. Queues that came later used homemade overlays. |
| `Lozenge` | status chip | Studio, QA, sandbox, compliance. Webhooks/promises/inbox still mix `Badge`. |
| `SlaPill` | SLA chip over `Lozenge` | Workspace. Disputes have a parallel `SlaChip` that does not use `Lozenge`. |
| `AgentCard` in `agent-card.ts` | editor/wire card | Studio API still `Record<string, unknown>` (`F14`). |
| `env_utils.env_float` | parse env numbers | Treatment config uses it. Reco config kept `_env_float`. |

`QueryState`'s own comment is the maintenance lesson:

```6:24:Habibi/src/components/ui/query-state.tsx
/**
 * The three answers a list query can give, kept distinct.
 *
 * This codebase names "graceful degradation lies" as its #1 failure mode and
 * then reproduces it every time a panel reaches for `query.data ?? []` ...
```

Building the primitive did not migrate the factory. That is P6: extraction without adoption.

`ContactablePill` keeps a dead argument:

```5:7:Habibi/src/components/consent/ContactablePill.tsx
/* `dense` used to switch the inline padding. The Lozenge is already the compact size the
 * dense call sites wanted, so the prop is kept for source compatibility and ignored. */
export function ContactablePill({ record }: { record: ConsentRecord; dense?: boolean }) {
```

### 7.5 The engine factory (P7, P8)

`agent_core/reco`, `agent_core/treatment`, and `agent_core/authority` are parallel packages. Shared slots: `engine.py`, `features.py`, `scoring.py` (reco + treatment), `config.py`, `decisions.py`, `arbitration.py` (reco + treatment).

All three engines open the same way:

```1:12:backend/agent_core/reco/engine.py
"""Orchestration — the only entry point callers need.

    features → candidates → veto → score → arbitrate → log

Two properties this function must hold, because it runs on the audio path of a
live phone call:

* **It never raises.** Any failure degrades to "no offer", logged. A
  recommender that can hang up on a customer is worse than no recommender.
* **It never blocks for long.** Everything is a handful of indexed reads; the
  caller runs it in a thread so the pipeline is not stalled either way.
"""
```

Treatment copies the header and then documents the fork:

```1:21:backend/agent_core/treatment/engine.py
"""Orchestration — the only entry point callers need.

    features → candidates → veto → score → arbitrate → log
...
One deliberate divergence from ``reco.engine``: in shadow mode this returns the
plan it would have carried out, rather than an empty result.
```

Authority shortens the pipeline comment to `features → matrix → log` and keeps the never-raises bullet.

**Speculative `FeatureProvider`.** Treatment:

```397:413:backend/agent_core/treatment/features.py
class FeatureProvider(Protocol):
    """The seam. Implement against your own schema and the rest works.

    ``conn`` is a hint, not a requirement: the engine holds a connection open
    anyway, and passing it means one checkout per decision instead of several.
    A provider backed by a feature store or a REST API ignores it.
    """
```

Reco's Protocol docstring is the same paragraph with "recommendation" instead of "decision". Authority has a slimmer Protocol. Live implementations: `SqlFeatureProvider` (treatment, authority) and `PostgresFeatureProvider` (reco) — one SQL adapter each. No feature-store class, no REST class. The Protocol is a future tense.

**`Recommender` Protocol** is copied as a skeleton, but unlike `FeatureProvider` it has **real variants**: treatment `EVScorer` / learned estimators / LLM rerank; reco `RuleScorer` / propensity / hybrid. That is legitimate strategy. Entropy is the knob name `"rule"` mapping to `EVScorer` in treatment and `RuleScorer` in reco.

`provider=` on `build_features` is never passed from production. Tests inject `Exploding()`. The Protocol is a test seam wearing a "REST feature store" docstring.

**Config.** Both reco and treatment define `MODE_OFF` / `MODE_SHADOW` / `MODE_LIVE` with the same three-line comment. Treatment's `config.py` says "Same discipline as `reco.config`" and imports `env_utils`. Reco still has:

```31:40:backend/agent_core/reco/config.py
def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number — using %s", name, raw, default)
        return default
```

`env_utils.py` exists because that helper used to drift. Reco was not migrated. That is P6 on the Python side.

Legitimate: swapping a scorer behind `build_scorer` (rule / propensity / hybrid / EV / estimators) is real polymorphism. Entropy: copying the *provider Protocol* and the *env parser* for a second implementation that is not in the repository.

### 7.6 Policy view-models (P9)

`Habibi/src/lib/offer-policy.ts` and `authority-policy.ts` are structural twins: a status union, a struct of optional wire fields, `STATUS_LABEL`, `STATUS_TONE`, `emptyX()`. Both start quiet as `"none"`. Both map `shadow` to tone `"discovery"`. `authority-policy.ts` imports `fmtOfferAmount` from the offer module — the second file knows it is a fork.

`gate-status.ts` is the healthy version of the same idea: one mapping, with a comment explaining the two screens that got `warn` / `skipped` wrong. Offer/authority view-models never got that third consolidation.

### 7.7 Dual write mappers (P10)

Customer 360 quick actions and the promises desk both create promises:

```80:103:Habibi/src/api/customers.ts
export async function createPromise(
  customer: Customer,
  input: { amount: number; date: string; channel: string; notes: string },
): Promise<PtpPromise> {
  // ...
  return apiPost<PtpPromise>("/promises", {
    customerId: customer.id,
    accountId: customer.accountId,
    amount: input.amount,
    promisedDate: new Date(input.date).toISOString(),
    channel: input.channel,
  });
}
```

```50:64:Habibi/src/api/promises.ts
export async function createPromise(input: CreateInput): Promise<{ id: string }> {
  // ...
  const actor = await resolveActor(input.owner);
  return apiPost<{ id: string }>("/promises", {
    customerId: input.customerId,
    amount: input.amount,
    promisedDate: input.promisedDate,
    channel: input.channel,
    reminderStatus: input.reminder,
    ownerUserId: actor.kind === "human" ? actor.id : undefined,
    ownerBotId: actor.kind === "bot" ? actor.id : undefined,
  });
}
```

Same route, different body, different return type, different mock. A field added to the desk mapper (owner, reminder) is invisible to C360. `createDispute` is split the same way. That is not "two similar functions." It is two writers for one resource.

### 7.8 Client-side Locked Engines (P14)

`consent-seed.ts` implements `isContactableNow` and `contactableSummary` (DND, expiry, frequency cap, window). `ContactablePill` displays the summary on the consent desk. Customer 360 already has the healthier twin: `ContactabilityPill` calls `GET /contact-policy`. Two widgets, two names (`Contactable` vs `Contactability`), two owners. Callbacks add a third formula (`isWithinDndWindow` in `callbacks-seed.ts`, browser `getHours()`, default 9–20). The server Locked Engine is `contact_policy.admit`. The consent pill can go green while admit says no, or the reverse. `06` / `09` named the dual formula. P17 is the UI fork that keeps both formulas on screen.

C360 insights: `fetchCustomerInsights` already derives offline on API failure, with a comment that a bare catch used to hide 500s. The route still does `insightsQuery.data ?? deriveCustomerInsights(customer)`. Two fallbacks. The client ladder comment in `customerInsights.ts` says the contact ladder used to be "written twice, once here and once in Python" and that those copies were removed — which is the healthy move. The remaining `?? derive` is the leftover dual path.

### 7.9 Speculative and leftover seams (P7, P12, P15)

**Documented unused owner.** `grant.py` is the ADR-0001 Tool Grant. First paragraph of the module: the seven formulas drifted. Last sentence of the prologue:

```30:31:backend/agent_core/tools/grant.py
Nothing imports this yet. It is added beside the seven formulas so they can be
migrated one at a time; see the parent issue for the sequence.
```

That is a compatibility layer in front of a migration that has not started. Production still uses the formulas. `09` owns the control-plane risk. This report owns the *pattern*: an engine was generated beside the live path and left unwired.

**Unread flag wrapper.** `platform_flags.agent_cards_enabled()` → `AGENT_CARDS_ENABLED`. Production callers: none (tests only). Cards compile regardless. Named flags for a factory whose other flags (`temporal_enabled`, `campaign_runtime_enabled`, `outbound_eval_gate_enabled`) *are* read. One wrapper in a row of wrappers was never attached.

**Temporal.** `adapter_temporal.py` is three functions that raise `temporal_adapter_not_promoted`. Fail-closed, flag-gated, imported when enabled. Classify as a **promoted stub** (P7, N=0 implementations), not as dead code. It is the honest form of speculative adapter.

**Kit.** `07` inventories unused shadcn (`menubar`, `navigation-menu`, `carousel`, `input-otp`, `form`, `chart`, `drawer`, …) and exclusive npm deps. `BigBoundMark.tsx` states it is unused; live chrome is `EqualizerMark`. Typical app-shell dump. Tree-shaken if `sideEffects: false` holds; still a maintenance surface (deps, grep noise, "which mark is live?").

**Generated.** `routeTree.gen.ts` is TanStack output (`@ts-nocheck`). Not a hand-written entropy source. Do not "fix" it.

**Characterization as scaffolding.** `test_tool_grant_characterization.py` is labelled for deletion with the seven formulas it pins. Until then CI treats equality of the unused owner and the live copies as a passing test.

**Mock engine port.** `mockAuthorityNext` reimplements authority against `customer360-seed`. Same pattern as `routing-seed.evalCondition` vs `db._routing_eval_condition`, and `api/contact-policy.ts` mock vs `contact_policy._veto`. Offline demo is the reason; two matrices is the cost.

**Unwired vendor sync.** `provider_voice_sync.py` is a complete non-Azure catalog sync with no production importer. Admin sync calls `tts_catalog_sync.run_sync` (Azure only). `07` already classified it **B**.

### 7.10 Worker-loop factory (P16)

Backend queues are copied like frontend desks. The unit is `process_one(engine) -> bool`: reclaim stuck → claim next → `handle_*` → `mark_failed_or_retry`. Sites include `bot_jobs.py`, `whatsapp_outbound.py`, `webhooks_dispatch.py`, `call_closer.py`, `cadence.py`, `campaigns.py`, `payment_events.py`, `promise_fulfillment.py`. Domain handlers differ. The retry helper already drifted: WhatsApp's `mark_failed_or_retry` inserts Meta ambiguous-transport dead-letter rules; `bot_jobs.py` keeps generic exponential backoff.

`bot_worker.process_one_any` fans across queues. It is not a shared runner. Do not invent `JobManager`. Extract a leaf for claim/retry if a third copy would otherwise fork retry again.

### 7.11 Stale error wrapper

`_handle_write` exists because `str(KeyError("x"))` leaked quotes into toasts. `_handoff_call` is the same try/except without that fix and without `IntegrityError` → 409:

```1311:1319:backend/main.py
def _handoff_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

Copy-modify of a boundary wrapper that already had a production bugfix. Handoff writes can still show the repr.

Kanban cards are the same story on the frontend: `PromiseCard` / `DisputeCard` share `draggable`, the danger-banner strip, and `#{accountTail} · {id}`. One is "Auto-routed to follow-up"; the other is "SLA breached."

---

## 8. Wrapper chains

Suffix hunt (`Manager`, `Service`, `Handler`, `Factory`, `Adapter`, `Wrapper`, `Orchestrator`) under `Habibi/src` and `backend/` product code does **not** find a class hierarchy. Hits are domain nouns (billing `Service`, floor `HandlerKind`, integrations category `"Orchestrator"`) or UI labels ("Callback Manager").

Actual chains:

| Chain | Hops | Which hop adds behavior |
|-------|------|-------------------------|
| HTTP | `apiGet<T>` → `fetchX` → `useX` → page | `apiGet`: auth, timeout, error. `fetchX`: mock vs live + sometimes body mapping. `useX`: query key. Page: render. Thin but mostly legitimate. Entropy is `T` from a seed (P3) and dual mappers (P10). |
| Mock | seed mutator → `if (USE_MOCK)` in `api/*.ts` | The mock branch *is* the old product. Live branch maps to HTTP. Two runtimes for one screen. |
| Engine | `FeatureProvider.build` → `engine.recommend/decide` → tool/webhook | Protocol hop adds no runtime behavior today (one SQL class). |
| Flags | `_flag` → `agent_cards_enabled` | Zero production readers. |
| Flags (live) | `cadence.enabled` / `campaigns.enabled` → `campaign_runtime_enabled` | Rename only. Flag is real. |
| Writes | `_handoff_call` vs `_handle_write` | Handoff copy dropped the KeyError and IntegrityError fixes. |
| Reads | `fetchX` → `apiGet("/x")` (~60 live one-liners) | Live fetchX is a rename. One real bypass: sandbox call-export `fetch` for a blob (`sandbox.lazy.tsx`). A consistency pass listed several lazy routes as raw `fetch`; those hits were React Query `refetch()`, not `window.fetch`. |
| Overlay | filename `*Drawer` → component `Sheet` | Rename only. |
| SLA chip | `SlaPill` → `Lozenge` | Thin but one-way. Disputes `SlaChip` skipped it. |
| Insights | API → catch derive → route `?? derive` | Second derive is a pass-through of the first fallback. |

Pass-through that *looks* like a wrapper and is actually a re-export: `export const fmtMoney = _fmtMoney` in three seeds so each feature folder can import from "its" seed. That is how formatter drift starts — upsell stopped re-exporting and wrote a second function.

---

## 9. Naming (inconsistent vs collision)

**Same job, several names (entropy):**

| Job | Names in the tree |
|-----|-------------------|
| Side panel | `*Sheet` (shadcn), `*Sheet` (homemade overlay), `*Drawer` (also shadcn Sheet) |
| KPI row | `MetricsStrip`, `StatsStrip`, `HeroStrip`, `*KpiStrip`, `PipelineStrip`, `WorkforceStrip` |
| Status chip | `Lozenge`, `Badge`, `SlaPill`, `SlaChip`, `StatusChip`, `Chip`, `Tag` |
| Queue table | `FilterTable`, `RecordsTable`, kanban `*Board` |
| Unassigned sentinel | `UNASSIGNED` constant vs `"Unassigned"` literal |
| Bot / mouth | glossary **Mouth**; tables and types still `botId`; UI "Bot" vs "Agent" as source filters |
| Scorer name `"rule"` | reco `RuleScorer` vs treatment `EVScorer` |

**Same word, several questions (collision — do not merge):**

| Word | Meanings |
|------|----------|
| **Offer** | Reco product offer; Tool Grant offer (subset of grant); UI "offer health"; generic "what we showed the model" |
| **Handoff** | Warm transfer; bot_id routing class; QA handler kind |
| **Cadence** | Outbound **Cadence** engine vs `PlanCadence` (`weekly \| biweekly \| monthly`) vs HTTP retry |
| **Service** | Billing cost row vs Pipecat `*Service` class vs "Service 1600" pool name |
| **Handler** | Floor bot/human vs QA bot/human/handoff vs React event handler |
| **Gate** | Compiler G0–G15 vs `query.data` empty vs publish Gate |
| **Filters** | Five incompatible interfaces, one name |

Page chrome saying "Manager" without a Manager type is P11, not a missing class.

---

## 10. Scaffolding inventory

| Kind | Examples | Action |
|------|----------|--------|
| Kit leftover | Unused `components/ui/{menubar,carousel,input-otp,form,drawer,…}`; exclusive npm (`vaul`, `embla-carousel-react`, …) | Product: keep as kit or prune wrapper+dep together (`07`) |
| Superseded brand | `BigBoundMark` + `.bb-mark` | Proven unused; live is `EqualizerMark` |
| Seed-became-contract | 24 `*-seed.ts` owning live `T` | Types move to wire models; seeds keep values |
| Unused engine | `grant.py` ("Nothing imports this yet") | Wire per ADR-0001 or stop implying it is the owner |
| Unread flag | `agent_cards_enabled()` | Delete wrapper or attach it |
| Promoted stub | Temporal adapter raises | Keep fail-closed until a cluster exists |
| Dead prop | `ContactablePill.dense` | Drop when call sites allow |
| Generated | `routeTree.gen.ts` | Leave |
| Dual path, documented | `flows.py` / `flows_dynamic.py`; mock vs live | Not scaffolding; operational |
| Characterization pins | Tests that exist because two copies would drift (`06`) | Evidence of entropy, not kit |

`platform_flags.py` is itself a small factory: `_flag` plus a named function per env key, "Do not invent a new name in a feature PR." That is a *good* abstraction (one parser). The entropy is the names that never gained a reader.

---

## 11. Consistency map (same job, several ways)

| Job | Variants | Closest canonical |
|-----|----------|-------------------|
| Load a list | `QueryState` (1 site); `LoadingState` (many); inline `isPending`; `query.data ?? []` | `QueryState` |
| Side panel | Sheet / overlay z-40 / overlay z-50 | shadcn `Sheet` |
| Filter chrome | 6× `FiltersBar` + `FilterTable` chips | `FilterTable` for queues; one `FiltersBar` primitive if chrome must be shared |
| Money display | `fmtMoney` ×2, `inrCompact`, raw `toLocaleString` | Pick one display helper; arithmetic stays `money_inr` |
| Query stale time | Client default + per-hook copy | Default only |
| Forms | shadcn `form.tsx` unused; feature sheets use `useState` + toasts | Status quo is fine; do not introduce react-hook-form as a seventh style unless `form.tsx` is actually adopted |
| Agent card in studio | `AgentCard` type vs `Record<string, unknown>` | `agent-card.ts` |
| Env floats | `env_utils.env_float` vs reco `_env_float` | `env_utils` |
| Contactability | seed `isContactableNow` vs `admit()` | `admit()`; pill should display a server field |
| Query keys | Flat `["documents"]` vs namespaced `["kb","documents"]` vs inline `["customer-insights", id]` | Namespace by domain; one invalidation owner per resource |
| Dates | `fmtDate` (360, IST); `fmtLongDate` (callbacks, browser locale); `formatDateTime` in audit-seed and redaction-seed; `formatKbDate` in `lib/utils.ts` | One IST helper; seeds stop owning formatters |
| Route size | Split desks (`callbacks.tsx` ~300 lines) vs monoliths (`prompt-studio.lazy.tsx`, `treatment.lazy.tsx`) | Desks already show the split; do not extract a BasePage |

---

## 12. Consolidation order

Not a rewrite. Not a new layer. Adopt what already won, delete the copy.

1. **One writer per resource.** C360 quick actions call `api/promises.createPromise` / `api/disputes.createDispute` (or a single mapper both import). Kill the second POST body.
2. **Wire types leave the seeds.** `27`: `schemas.py` (or generated client) owns `T`. Seeds keep mock *values*. Collapse `Promise` / `Dispute` / `Channel` homonyms as part of that, not as a rename PR.
3. **One overlay.** Homemade z-40/z-50 families become shadcn `Sheet`. Rename `*Drawer` that are Sheets, or actually use `ui/drawer`. Do not add `Overlay.tsx` as a fourth chrome.
4. **One display money helper; `money_inr` stays for arithmetic.** Delete the upsell/360 fork by picking the null policy (`"—"` vs `₹0`) once.
5. **Adopt `QueryState` on list screens** that currently `?? []`. The component already explains why.
6. **Reco `config.py` uses `env_utils`.** Delete `_env_float`.
7. **Studio API uses `AgentCard`.** Stop `Record<string, unknown>` for the card blob.
8. **Contact pill reads the server.** Point the consent desk at `ContactabilityPill` / `admit()`. Delete seed `isContactableNow` from the live path. Delete `_handoff_call`; use `_handle_write`.
9. **`grant.py`.** Wire it (`09`) or stop documenting it as the owner. Delete `test_tool_grant_characterization.py` with the formulas, as its own header says. Do not generate `grant_v2`.
10. **Kit prune** only with the `07` pairing (wrapper + exclusive dep). Optional. `provider_voice_sync.py`: wire or drop.

Do **not**: introduce `BaseQueuePage`, `EngineBase`, `FeatureProvider` REST adapters, a `FiltersBar` generic with twelve type parameters, or Manager/Service classes. The factory already over-abstracts in the Protocol direction and under-abstracts in the chrome direction. Fix that imbalance by deleting copies, not by adding a base class.

---

## 13. Confidence and limits

High-confidence clones were re-read side by side (`Chip`/`toggle`, overlay markup, engine module headers, `fmtMoney`, dual `createPromise`, FeatureProvider docstrings, `_handle_write` vs `_handoff_call`, PromiseCard vs DisputeCard). Counts of strip files (~19) and seed files (24) are directory listings, not jscpd. Worker `process_one` sites were sampled, not exhaustively counted; the duplication analyst’s “15+” is consistent with `06`. `07`'s `campaign_runtime_enabled` "no production call sites" is **wrong today** (`cadence.py`, `campaigns.py`); the wrappers `enabled()` are the entropy, not the flag.

The scaffolding analyst listed `campaign_runtime_enabled` as unread; that claim is rejected. `Recommender` Protocols have multiple live scorers and are not classed as speculative seams.

Voice `build_tools` vs `bot_tools.py` dual catalogs remain a control-plane issue for `06`/`09`, not re-litigated here.

The pattern that will produce the next defect without anyone opening a "refactor" ticket: **copy the last queue, change the nouns, ship.** The next `FiltersBar` will not import `QueryState`, will not use `Sheet`, and will invent another `Channel` union. That is the entropy this taxonomy is for.
