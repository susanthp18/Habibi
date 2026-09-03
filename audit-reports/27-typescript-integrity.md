# 27 — TypeScript integrity

**Role:** Senior TypeScript architect.  
**Question:** Is the type system an *architectural safety mechanism*, or a compile-time refactor net that stops at the JSON boundary?  
**Scope:** `Habibi/` (TanStack Start / React). Backend `schemas.py` / Pydantic is in scope only as the other side of the wire. `PRAXIST-main/` is out of scope.  
**Date:** 2026-09-02  
**Mode:** Read-only. The only file written is this report.  
**Companions:** `11-api-contracts.md` (HTTP governance — this report does not re-litigate `requestedVia` or billing IDOR), `03-frontend-architecture.md`, `06-duplication.md`, `14-error-handling.md`.  
**Vocabulary:** `CONTEXT.md`. **Agent Card**, **Mouth**, **Tool Grant** are that glossary.

**Method:** five parallel analysts — strictness, API typing, schema/type duplication, `any`/casts, generics — then every headline claim re-read from source in this session. `npx tsc --noEmit` was reported clean by the strictness analyst; this document does not treat that as proof the *boundary* is sound.

---

## 1. Executive Summary

TypeScript in Habibi is a **strong interior lock and a weak exterior lock**.

`strict: true` is on. CI runs `tsc --noEmit` on every `Habibi/**` change. Hand-written `@ts-ignore` is absent. Hand-written `as any` is essentially one Pipecat SDK workaround. `QueryState`, `ApiError` + `unknown` catch narrowing, `FilterTable<T>`, and the `AgentCard` editor type are evidence the authors *know* what a type-as-safety-mechanism looks like.

The mechanism stops at `fetch`. Every live JSON body is trusted with:

```183:183:Habibi/src/api/config.ts
  return JSON.parse(text) as T;
```

`T` is chosen by the caller. There is no Zod parse, no generated OpenAPI client, and no shared package with Pydantic. For most screens, `T` is an interface that lives in `src/data/*-seed.ts` — the mock factory — not a wire type derived from `backend/schemas.py`.

That is not a style complaint. It is a **false safety property**: `tsc` will not fail when the server starts sending `summary: null` (it already does — `InteractionResponse.summary: str | None`) while the client type says `summary: string`. Insights code learned to call `str()` after a crash; `InteractionsTab` still types the field as a string. The type system certified the lie.

**Canonical ownership (target, already true on the server):** `backend/schemas.py` (and engine `to_payload()` where no model exists) owns the wire. `Habibi/src/api/agent-card.ts` is the one honest handwritten mirror, with a regex drift test. `src/lib/*` owns UI view-models. `src/data/*-seed.ts` should own mock *values*, not live *shapes*. Today the seed files own both.

Do not generate a new type-abstraction layer for tables, query helpers, or shadcn. Do not enable `exactOptionalPropertyTypes` as a flag day. Fix the boundary: either parse at `apiGet`, or generate types from the backend, or both — starting with the types that already lie.

---

## 2. Scope

| In | Out |
|----|-----|
| `Habibi/tsconfig.json`, `eslint.config.js`, `package.json` | Python type hints except as wire counterparts |
| `Habibi/src/**/*.ts(x)` | `PRAXIST-main/` |
| `Habibi/src/routeTree.gen.ts` (as generated exception) | Rewriting the app, installing parsers, enabling flags |
| `backend/schemas.py`, `agent_core/cards/schema.py`, `tests/test_agent_card_schema_drift.py` | Secret values, live cluster |
| `.github/workflows/frontend-typecheck.yml` | |

---

## 3. Methodology

1. Read `tsconfig.json` and `eslint.config.js` as the declared safety policy.
2. Inventory suppressions (`@ts-ignore` / `@ts-expect-error` / `@ts-nocheck`), `any`, `as unknown as`, `JSON.parse`, Zod, `satisfies`.
3. Trace `apiGet`/`apiPost` generics to call sites and to Pydantic `response_model`.
4. Compare same-named types across `data/`, `api/`, `lib/` (Customer, Dispute, Promise, Channel, Consent).
5. Classify every significant cast as **legitimate boundary** vs **dangerous interior hatch**.
6. Identify who actually owns each contract today vs who should.

Inference is labelled. Counts of `as SomeType` (684 in one analyst pass) are **not** treated as 684 bugs — most are enum/DOM/`as const` assertions.

---

## 4. Repository / System Context

Habibi is the operator console for a FastAPI CRM. Domain types were born as **mock seeds** so screens could ship before the API. The live path (`USE_MOCK=false`, production mock hard-error in `config.ts`) still types responses with those seed interfaces.

The contract triangle (also in `11-api-contracts.md`):

```
sql CHECK  →  schemas.py Literal/BaseModel  →  Habibi TS union
     (enforced)         (enforced on ~some routes)     (compile-time only)
```

One cross-language test exists: `test_agent_card_schema_drift.py` regex-reads `AGENT_CARD_MEMBERS` from `agent-card.ts`. It runs in the **backend** workflow (`paths: backend/**`). Editing the TypeScript file alone does not run it.

---

## 5. Key Findings

| ID | Severity | Confidence | Finding | Location | Impact |
|----|----------|------------|---------|----------|--------|
| TS-01 | P1 | HIGH | `apiGet<T>` / `apiSend<T>` assert `JSON.parse` as caller-chosen `T`. No runtime schema. | `Habibi/src/api/config.ts:171–211` | TypeScript cannot catch API drift. Every live screen inherits this. |
| TS-02 | P1 | HIGH | Live wire types are imported from mock seeds (~26 `src/api` modules). | `src/api/*.ts` → `@/data/*-seed` | Mock shape becomes the production contract. Seed edits look like type-safe API changes. |
| TS-03 | P1 | HIGH | `Interaction.summary` (and `disposition`) typed `string`; Pydantic is `str \| None`. | `customer360-seed.ts:38–50`; `schemas.py:89–100` | `tsc` allows `.slice`/`.toLowerCase` on a value that is null on the wire. Prior crash is documented in `scripts/test-c360-insights.ts`. |
| TS-04 | P2 | HIGH | Two exported types named `Dispute` and two named `Promise` with incompatible fields. | `customer360-seed.ts` vs `disputes-seed.ts` / `promises-seed.ts` | TS distinguishes the imports; humans will not. Wrong import types the wrong endpoint. |
| TS-05 | P2 | HIGH | `Channel` (and cousins) defined ≥5 times with different members. | seeds, `agent-card.ts`, `contact-policy.ts` | Contact/consent/card channels are not one vocabulary. `call` ≠ `voice`. |
| TS-06 | P2 | HIGH | Agent Studio still stores the card as `Record<string, unknown>` beside a real `AgentCard` type. | `agent-studio.ts:49–51,72`; `agent-card.ts` | Editor-side typos survive until backend `extra="forbid"` rejects publish. |
| TS-07 | P2 | HIGH | Extra-strict TS flags off; ESLint is not type-aware (`no-unsafe-*` absent). | `tsconfig.json`; `eslint.config.js` | `as T` and indexed access are invisible to lint. |
| TS-08 | P2 | HIGH | Pipecat client erased with `as any`. | `useSandboxLiveCall.ts:261–264` | Voice sandbox event payloads are untyped. Legitimate SDK gap, still a hole. |
| TS-09 | P2 | HIGH | Floor copilot SSE `pack` is `as unknown as FloorCopilot`. | `api/floor.ts:233–235` | Malformed pack renders as a successful copilot state. |
| TS-10 | P2 | HIGH | `npm run build` does not typecheck; only CI `tsc` does. | `package.json`; `frontend-typecheck.yml` | A skipped CI job ships a type-unsafe Vite bundle. |
| TS-11 | P2 | HIGH | `test_agent_card_schema_drift.py` does not run on frontend-only edits. | `backend/tests/…`; workflow path filters | The only TS↔Python member gate can rot silently. |
| TS-12 | P3 | HIGH | Zod is a dependency but used on one route search schema; forms are `useState`. | `customers.$customerId.tsx`; `package.json` | Untrusted URL/search and form input are mostly unparsed. |
| TS-13 | P3 | HIGH | Query-key tuples are ad hoc; prefix bugs already documented in code. | `agent-studio.ts` comments ~186–205 | Invalidation misses are a type-shaped problem with no `queryKeys` factory. |
| TS-14 | P3 | HIGH | `noUncheckedIndexedAccess` off; `exactOptionalPropertyTypes` off. | `tsconfig.json` | `arr[0]` is `T`; `foo?: string \| null` conflates missing / undefined / null. |
| TS-15 | P3 | HIGH | Router `navigate` typed `any` to escape branded search. | `lib/workspace-nav.ts:33–45` | Deep links can pass invalid search without a type error. |
| TS-16 | P3 | HIGH | `fetchQaInteractionPack` is a bare `apiGet(...)` → `unknown`. | `api/qa.ts:66` | Consumers get no shape; easy to recast unsafely. |
| TS-17 | P4 | HIGH | `skipLibCheck`, unused-locals off, `verbatimModuleSyntax: false`. | `tsconfig.json` | Hygiene, not correctness. |

---

## 6. Detailed Findings

### TS-01 — Unconstrained `apiGet<T>` is an unsound generic

**Severity:** P1  
**Confidence:** HIGH  
**Category:** Weak generics / missing runtime validation for untrusted data  
**Location:** `Habibi/src/api/config.ts:171–211` (`apiGet`, `apiSend`); consumers across `src/api/`

**Evidence:**

```170:184:Habibi/src/api/config.ts
/** Thin typed GET helper for the live API. */
export async function apiGet<T>(path: string, init?: { signal?: AbortSignal }): Promise<T> {
  ...
  if (res.status === 204) return undefined as T;
  ...
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}
```

Empty/204 bodies are `undefined as T`, so `apiGet<Customer>` can resolve to `undefined` while still typing as `Customer` if the caller omitted `| undefined`. `fetchCustomer` happens to add `| undefined` (`customers.ts:31–33`); most callers do not.

Status handling *is* typed: non-OK throws `ApiError`. The hole is the **200 JSON body**.

**Observed behavior:** Compile-time `T` is a documentation comment the compiler cannot check against bytes. Backend `ResponseValidationError` (when `response_model` is set) becomes a 500 and an `ApiError`. Backend routes *without* `response_model` (authority/treatment — see `11-api-contracts.md`) return 200 with unvalidated dicts; the client still `as T`.

**Why this matters:** This is the architectural claim under test. A type system used as a safety mechanism must either (a) generate `T` from the same schema the server validates, or (b) parse `T` at the boundary. Habibi does neither. Interior refactors are safe; the regulated collections payload is not.

**Dependencies / blast radius:** Every `apiGet`/`apiPost`/`apiPatch`/`apiUpload` call site. Zod is already in `package.json` and unused here.

**Recommended action:** Keep the helper. Add an optional parse argument (`apiGet(path, schema)`) or a small set of endpoint-specific parsers for Customer, Dispute list, Authority next, Treatment next, Billing, Agent card. Do not wrap the entire CRM in Zod on day one.

**Verification required:** Force a backend field to `null` where TS says `string`; confirm `tsc` still passes and UI either guards or crashes. After a parser: the same payload must fail closed with `ApiError`, not render `₹NaN`.

**Duplication class:** J (client types are a third copy of the HTTP contract).

---

### TS-02 — Mock seeds own live wire types

**Severity:** P1  
**Confidence:** HIGH  
**Category:** Canonical ownership inverted / duplicate API types (J)  
**Location:** 26 modules under `Habibi/src/api/` importing `@/data/*-seed` (grep, this session). Examples: `customers.ts:11–20`, `disputes.ts:16–31`, `promises.ts`, `consent.ts`, `inbox.ts`, `floor.ts`, `handoff.ts`, `billing.ts`.

**Evidence:** `fetchCustomers` is `apiGet<Customer[]>("/customers")` where `Customer` is exported from `customer360-seed.ts` — the file whose first comment is “Customer 360 synthetic data”.

Modules that **do not** do this, and instead declare wire types in `api/` (better): `treatment.ts`, `authority.ts`, `contact-policy.ts`, `agent-card.ts`, `flow.ts`, `me.ts`, `staff.ts`, `teams.ts`, `trace.ts`, `call-cost.ts`, `outbound.ts`, `platform.ts`.

**Observed behavior:** Changing a mock customer to make a screenshot look right is indistinguishable, to `tsc`, from changing the HTTP contract.

**Why this matters:** Seeds are the right place for *values*. They are the wrong place for *authority*. `11-api-contracts.md` already named `schemas.py` as the schema module; this report names the frontend mistake: the console treats seed interfaces as if they were generated clients.

**Dependencies / blast radius:** Customer 360, disputes, promises, inbox, floor, billing nested types (`Service`, `Tenant` from seed).

**Recommended action:** Extract wire interfaces to `src/api/types/` or generate them. Leave seeds importing those types (or factories returning them). `workspace.ts` `WorkItemApi` → `mapWorkItem()` is the pattern to copy.

**Verification required:** `Customer` in TS vs `CustomerResponse` field-by-field (nullability especially). A seed-only field (`contact.allowedDays`, commented as mock-only in `customer360-seed.ts:111–116`) must not be read as live-required.

---

### TS-03 — Nullability lie: `Interaction.summary: string` vs `str | None`

**Severity:** P1  
**Confidence:** HIGH  
**Category:** Nullability confusion / type assertion hiding bugs  
**Location:** `Habibi/src/data/customer360-seed.ts:38–50`; `backend/schemas.py:89–100` (`InteractionResponse`); consumers `InteractionsTab.tsx:172,192`; mitigation `lib/customerInsights.ts:137–144,383`; probe `Habibi/scripts/test-c360-insights.ts` (not in `tsconfig` include)

**Evidence:**

```38:50:Habibi/src/data/customer360-seed.ts
export interface Interaction {
  ...
  disposition: string;
  ...
  summary: string;
  ...
}
```

```89:100:backend/schemas.py
class InteractionResponse(BaseModel):
    ...
    startedAt: str | None = None
    ...
    disposition: str | None = None
    ...
    summary: str | None = None
```

`customerInsights.ts` already documents “API fields may be null” and wraps with `str()`. That is runtime compensation for a type that still says `string`. `InteractionsTab` interpolates `i.summary` (React will render `null` as empty — **observed fact** that this particular call site does not throw). `scripts/test-c360-insights.ts` uses `@ts-expect-error` to probe `ix.summary.slice(0, 120)` — evidence a **previous** crash class.

**Observed behavior:** `tsc` is green while the wire type is optional. Adding `.toLowerCase()` on `i.summary` typechecks and can throw.

**Why this matters:** This is the concrete proof of TS-01. Not hypothetical drift — the Pydantic model and the TS interface disagree today.

**Dependencies / blast radius:** Customer 360 interactions tab, insights derivation, any new code that treats `Interaction` as fully populated.

**Recommended action:** Align TS with Pydantic: `summary: string | null`, `disposition: string | null`, `startedAt: string | null`. Then fix call sites. Optionally add `str()` only at display edges.

**Verification required:** Live `GET /customers/{id}` with a row that has `summary: null`; `tsc` after the type change; UI does not throw; insights still format.

---

### TS-04 — Homonymous `Dispute` and `Promise` types

**Severity:** P2  
**Confidence:** HIGH  
**Category:** Structural duplication (C) / naming collision — **not** an unsound assignability hole  
**Location:** `customer360-seed.ts:52–76`; `disputes-seed.ts:15,46–72`; `promises-seed.ts:10–44`; `api/customers.ts` vs `api/disputes.ts` / `api/promises.ts`

**Evidence:** Customer 360 `Dispute` has `amount`. Board `Dispute` (`DisputeRecord & DisputeSla`) has `disputedAmount`, plus evidence, events, priority. 360 `Promise` uses `PtpStatus` without `due_today` and `reminderStatus` including `"queued" | "acknowledged"`. Pipeline `Promise` uses `PromiseStatus` including `"due_today"` and `ReminderStatus` `"off" | "scheduled" | "sent"`.

**Important distinction (fact):** These live in different modules. TypeScript will **reject** assigning a 360 `Dispute` to a board `Dispute`. The type system is doing its job *if the import is correct*. The architectural failure is **one English name for two projections**, so the wrong import types `apiGet` against the wrong endpoint.

360 `Promise` matches `PromiseResponse` in `schemas.py:103–111` more closely than the pipeline type does. **Strong inference:** `due_today` is a board/view status, not the customer-embed wire status.

**Why this matters:** `DisputeSla` is already correctly shared (`dispute-sla.ts`) — proof the authors know how to share the overlapping slice. The remainder should be named `CustomerDisputeSummary` / `DisputeRecord`.

**Dependencies / blast radius:** Disputes kanban, 360 disputes tab, create-from-360 vs create-from-desk (`customers.ts` vs `disputes.ts` create return types already differ).

**Recommended action:** Rename; do not merge the shapes. Keep SLA on the shared module.

**Verification required:** `tsc` after rename; no `apiGet<Dispute>` left ambiguous in grep.

---

### TS-05 — Fragmented `Channel` unions

**Severity:** P2  
**Confidence:** HIGH  
**Category:** Semantic duplication (D) / duplicate business vocabulary (E)  
**Location:** `customer360-seed.ts:8` (`voice|whatsapp|chat|email|sms`); `inbox-seed.ts:3` (same members, different order); `audit-seed.ts` / `floor-seed.ts` (subset); `agent-card.ts:38` (`voice|whatsapp|sms|internal|mcp|a2a`); `consent-seed.ts:5` (`call|whatsapp|sms|email`); `contact-policy.ts:31` (`voice|whatsapp|sms|email|chat|field`); `backend/schemas.py:28` `Channel = Literal["voice","whatsapp","chat","email","sms"]`

**Evidence:** Inbox seed comments that it “Mirrors the conversations.channel CHECK constraint” and is “Narrower than the database”. Consent uses **`call`**, not `voice`. Agent card channels are the **Mouth** channel vocabulary (includes `mcp`, `a2a`), not the CRM interaction channel.

**Observed behavior:** These are **not** all the same type. Mixing them is a compile error — good. Mapping `call` ↔ `voice` at the consent boundary is easy to get wrong because nothing named `Channel` warns you.

**Why this matters:** Contactability, cards, and inbox are three domains. One identifier `Channel` pretends they are one.

**Recommended action:** `CrmChannel` (align with `schemas.py`), `ConsentChannel` (keep `call` if the API does), `CardChannel` (agent-card). Map at API adapters.

**Verification required:** Grep `export type Channel`; confirm each import site.

**False merge:** Do not unify agent-card channels with CRM channels — **Mouth** identity.channels is a different concept (`CONTEXT.md`).

---

### TS-06 — `AgentCard` type vs `Record<string, unknown>` on the same object

**Severity:** P2  
**Confidence:** HIGH  
**Category:** Overly broad types / migration incomplete  
**Location:** `Habibi/src/api/agent-card.ts:1–33,306–339`; `Habibi/src/api/agent-studio.ts:49–51,72`; `prompt-studio.ts` card fields; bridge `prompt-studio.lazy.tsx` `asCard`

**Evidence:** `agent-card.ts` exists specifically because `as never` into six tabs removed checking, and because Pydantic `extra="forbid"` makes a typo a failed **publish**, not a ignored extra key. `AgentCardSummary.agentCard` is still `Record<string, unknown>`. Compile report `card` is the same.

`asCard(value: unknown)` checks object-ness then `value as AgentCard` — a **legitimate but weak** boundary: it does not validate keys.

**Observed behavior:** Panels that take `AgentCard` are safer. The fetch layer still does not.

**Why this matters:** The best type in the frontend is not connected to the HTTP helper that loads it.

**Recommended action:** Type `agentCard` / `publishedCard` as `AgentCard` (all-optional editor shape is already designed for `{}`). Keep `Record` only for truly schemaless JSON (connector config bags, `payload_schema`).

**Verification required:** Assign a misspelled key in a mock card; `tsc` should fail. Publish path still hits backend forbid as last line.

---

### TS-07 — Lint and compiler extras do not police unsafety

**Severity:** P2  
**Confidence:** HIGH  
**Category:** Configuration discipline  
**Location:** `Habibi/tsconfig.json`; `Habibi/eslint.config.js:8–37`

**Evidence:** `strict: true` implies `noImplicitAny`, `strictNullChecks`, `useUnknownInCatchVariables`. Not enabled: `exactOptionalPropertyTypes`, `noUncheckedIndexedAccess`, `noImplicitReturns`, `isolatedModules`. `skipLibCheck: true`. `noUnusedLocals`/`noUnusedParameters`: false.

ESLint: `tseslint.configs.recommended` only — **not** `recommendedTypeChecked`. No `parserOptions.project`. `@typescript-eslint/no-explicit-any` is on (hence the two eslint-disable comments). `@typescript-eslint/no-unsafe-*` is off. `no-unused-vars` explicitly off.

**Observed behavior:** `JSON.parse as T` is invisible to both ESLint and `tsc`.

**Why this matters:** The repo’s TypeScript *policy* is “strict compile, recommended lint.” The *unsafe* family is what would catch TS-01 without a new framework.

**Recommended action:** Add `recommendedTypeChecked` in CI (may be slow — measure). Or a one-rule exception: ban `as T` on `JSON.parse` via custom lint. Do not turn on `exactOptionalPropertyTypes` until TS-14 is scoped.

**Verification required:** ESLint on `config.ts` after type-aware rules; count of new errors; do not widen ignore lists to go green.

---

### TS-08 — Pipecat `client as any`

**Severity:** P2  
**Confidence:** HIGH  
**Category:** Dangerous cast at a third-party boundary (partially legitimate)  
**Location:** `Habibi/src/components/sandbox/voice/useSandboxLiveCall.ts:261–264`

**Evidence:**

```261:264:Habibi/src/components/sandbox/voice/useSandboxLiveCall.ts
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = client as any;
      clientRef.current = c as typeof clientRef.current;
```

Subsequent `.on(RTVIEvent.*)` handlers add local annotation on `data` (e.g. `{ text?: string; final?: boolean }`) — some payloads are re-typed by hand.

**Observed behavior:** SDK `.on` typing is insufficient; the escape hatch untypes the **entire** client, not just `.on`.

**Why this matters:** Voice sandbox is not production Twilio, but it is how authors rehearse the **Mouth**. Wrong event shapes fail silently.

**Recommended action:** Typed adapter: `function on<E>(client: PipecatClient, event: E, handler: …)` with a mapped event table. Keep `any` inside that one module if the SDK forces it.

**Verification required:** SDK upgrade; UserTranscript / LLMFunctionCall / Error paths.

**Cast class:** Legitimate *motivation* (third-party `.d.ts` gap) + dangerous *scope* (`as any` on the whole object).

---

### TS-09 — Floor copilot SSE double assertion

**Severity:** P2  
**Confidence:** HIGH  
**Category:** Unsafe cast on untrusted stream data  
**Location:** `Habibi/src/api/floor.ts:230–245`

**Evidence:** `apiEventStream` already types parsed JSON as `unknown` (`config.ts` — good). The pack handler then `payload as unknown as FloorCopilot`. Token events correctly use `String(payload.text ?? "")`.

**Observed behavior:** A `pack` event with missing `vetoes` is patched with `?? []`. `engineDraft` uses `|| ""`. `card` is passed through unvalidated.

**Why this matters:** Copilot vetoes/approvals are operator guidance on a live call. A malformed pack should be an error state, not a quiet empty list that looks like “no vetoes.”

**Recommended action:** Narrow `unknown` with typeof/Array.isArray on required fields; else `error: "bad pack"`. Same pattern as `tts-voice-prefs.ts` and skill script JSON.

**Verification required:** Inject SSE `pack` with `vetoes: "nope"`; UI must not treat it as a successful empty veto list.

**Cast class:** Dangerous (untrusted network → domain object). Contrast with localStorage parsers that narrow.

---

### TS-10 — Build script skips `tsc`

**Severity:** P2  
**Confidence:** HIGH  
**Category:** Safety mechanism not on the ship path  
**Location:** `Habibi/package.json` (`build`: `vite build`; `typecheck`: `tsc --noEmit`); `.github/workflows/frontend-typecheck.yml:32–33`

**Evidence:** CI job runs `npx tsc --noEmit` then vitest then lint, path-filtered to `Habibi/**`. Vite build typechecks only as much as the bundler requires (not the full program).

**Observed behavior:** `npm run build` locally can succeed with type errors if the author never runs `typecheck` and never pushes to CI.

**Why this matters:** TypeScript-as-gate only counts if it sits on the artifact path.

**Recommended action:** `"build": "tsc --noEmit && vite build"` or a `prebuild` script. Lovable-connected branch should stay green (`Habibi/AGENTS.md`).

**Verification required:** Insert a type error; `npm run build` must fail.

---

### TS-11 — Agent-card drift test is on the wrong CI path filter

**Severity:** P2  
**Confidence:** HIGH  
**Category:** Generated vs handwritten schema — the one existing gate is mis-wired  
**Location:** `backend/tests/test_agent_card_schema_drift.py:1–40,44–83`; `.github/workflows/backend-pytest.yml` `paths:`; `frontend-typecheck.yml` `paths: Habibi/**`

**Evidence:** The test reads `Habibi/src/api/agent-card.ts` via path relative to the backend tests dir. Docstring: handwritten mirrors rot; `extra="forbid"` makes invented keys a publish failure. Frontend job never runs pytest. Backend job is path-filtered to `backend/**` (**strong inference** from workflow `paths:` — confirm when changing CI).

**Why this matters:** The repository already invented the correct cheap gate (regex `AGENT_CARD_MEMBERS` vs Pydantic `model_fields`). TypeScript cannot span Python. CI must.

**Recommended action:** Run this test on changes to *either* `agent-card.ts` or `schema.py`. Or duplicate a node script in the frontend job that only checks member names if pytest is too heavy.

**Verification required:** Edit `AGENT_CARD_MEMBERS` only; confirm which workflow runs; today, **weak inference** that GitHub skips backend pytest.

---

### TS-12 — Zod and RHF generics are unused (except one search schema)

**Severity:** P3  
**Confidence:** HIGH  
**Category:** Missing validation at untrusted edges  
**Location:** `Habibi/package.json` (`zod`, `@hookform/resolvers`); `Habibi/src/routes/customers.$customerId.tsx` (only `from "zod"` in `src/`); `components/ui/form.tsx` (RHF generics, no `useForm` in routes)

**Evidence:** Route search elsewhere uses `validateSearch: (search: Record<string, unknown>) => …` or `parseDeepLinkSearch` (`workspace-nav.ts:70–76`) with `typeof` guards — **sound enough** for `{ id?, new? }`. Forms use `useState`.

**Why this matters:** Dependencies promised a schema layer. The HTTP boundary (TS-01) is the place it would pay rent. Wiring Zod everywhere “because we have it” is not the recommendation.

**Recommended action:** Use Zod at `apiGet` for a handful of payloads, and keep `parseDeepLinkSearch` (or convert that one helper to Zod). Do not migrate every form to RHF as a type project.

**Verification required:** Count `from "zod"` remains 1 until HTTP parsers land.

---

### TS-13 — Query keys have no typed factory

**Severity:** P3  
**Confidence:** HIGH  
**Category:** Missing generic abstraction where it would help  
**Location:** `Habibi/src/api/agent-studio.ts` (comments on prefix invalidation, `invalidateAgentStudio`); scattered `queryKey: ["…"]` in `api/*.ts`

**Evidence:** Code comments document a real bug: `["agent-studio", "skill", id]` vs `["agent-studio","skills"]` prefix. `invalidateAgentStudio` is the mitigation — a function, not a typed key tree.

**Why this matters:** TanStack Query will happily cache under the wrong tuple. Types would help if keys were `as const` objects.

**Recommended action:** `queryKeys.agentStudio.skill(id)` returning `as const`. Incremental, per domain.

**Verification required:** Invalidation tests already in vitest if present; add one if not.

---

### TS-14 — Optional / null / index access are loose by compiler default

**Severity:** P3  
**Confidence:** HIGH  
**Category:** Optionality confusion  
**Location:** `tsconfig.json` (flags absent); API DTOs with `foo?: string | null` (`trace.ts`, `inbox.ts`, `kb.ts`); `inbox.tsx` `useState<string | null | undefined>` for drafts; `stableStringify.ts` treating missing ≡ undefined

**Evidence:** Python JSON uses `null`. TypeScript optional properties use `undefined` when omitted. Without `exactOptionalPropertyTypes`, `{ foo: undefined }` assignable to `{ foo?: string }` hides “key present but empty” vs “key absent.” `noUncheckedIndexedAccess` off means `versions[0]` is not `T | undefined` — related to sandbox `versions[0]!` (`sandbox.lazy.tsx`).

**Why this matters:** Enabling the flags without a migration will fail hundreds of sites. They are still the right *eventual* safety knobs.

**Recommended action:** Enable `noUncheckedIndexedAccess` first on a branch and measure. Leave `exactOptionalPropertyTypes` until wire types use `null` consistently (TS-03).

**Verification required:** `tsc` error count with each flag in isolation.

---

### TS-15 — `navigate: (opts: any)` 

**Severity:** P3  
**Confidence:** HIGH  
**Category:** Legitimate-motivation dangerous cast  
**Location:** `Habibi/src/lib/workspace-nav.ts:33–45`

**Evidence:** Comment: “Accept router navigate without fighting TanStack's branded search types.” Index signature `[key: string]: any` on `NavigateFn`. `parseDeepLinkSearch` itself is carefully guarded.

**Cast class:** Legitimate (branded router types vs heterogeneous destinations) with a wide `any`. Safer than `as any` on the client: the *destination* is computed by `workItemDestination` with a switch.

**Recommended action:** `NavigateOptions` from TanStack with a union of destination routes, or overload `navigateWorkItem` per entity type. Low priority if deep-link tests exist.

**Verification required:** Notification click for each `WorkItemEntityType`.

---

### TS-16 — Bare `apiGet` infers `unknown`

**Severity:** P3  
**Confidence:** HIGH  
**Location:** `Habibi/src/api/qa.ts:66`

**Evidence:** `return apiGet(\`/qa/interactions/${…}/pack\`);` — no type argument. Analyst: `fetchQaInteractionPack` returns `Promise<unknown>` (or an implicit wide type). Isolated but a template for mistakes.

**Recommended action:** `apiGet<QaInteractionPack>(…)` **after** defining a real interface (not `Record<string, unknown>`).

**Verification required:** Call-site compile errors once typed.

---

### TS-17 — Hygiene flags

**Severity:** P4  
**Confidence:** HIGH  
**Location:** `tsconfig.json:13,17–20`

**Evidence:** `skipLibCheck: true` (normal for Vite apps). Unused locals off (matches ESLint). `verbatimModuleSyntax: false` despite many `import type` already.

**Recommended action:** Periodic `skipLibCheck: false` experiment; unused-locals later. Not a safety incident.

---

## 7. Positive Findings

1. **`strict: true`** with CI-gated `tsc --noEmit` (`.github/workflows/frontend-typecheck.yml`).
2. **Almost no suppressions.** Zero `@ts-ignore` in `src/`. `@ts-nocheck` only on generated `routeTree.gen.ts`. One `@ts-expect-error` in an out-of-include probe script.
3. **Hand-written `any` is rare.** Two `: any` + index signature in `workspace-nav.ts`; one `as any` in the Pipecat hook. `Record<string, any>`: none found. `catch (e: any)`: none (`useUnknownInCatchVariables` is working).
4. **`ApiError` + `isNotFound` + `retryUnlessClientError`** — errors are `unknown` then narrowed. Status is not a stringly-typed throw.
5. **`QueryState`** — documents the `#1` failure mode (`data ?? []` as fact) and makes the honest path shorter. That is type-adjacent product design.
6. **`AgentCard` + `AGENT_CARD_MEMBERS` + `isAuthoredCard` + `asRollbackTriggers(raw: unknown)`** — the intended pattern for a forbid-extra schema. Drift test exists even if CI pathing is wrong (TS-11).
7. **`FilterTable<T>` / `RecordsTable<T>`** — generics preserve row types; they do not erase props.
8. **`satisfies` on mocks** (customers, compliance, kb, etc.) — structural check without widening.
9. **Good `unknown` narrowing:** `tts-voice-prefs.ts`, skill script JSON, floor SSE *token* path, many `instanceof Error` sites. `liveEvents.ts` even accepts `summary: string | null`.
10. **Production mock hard-error** (`config.ts`) — types are not the only gate; shipping mock as prod is a thrown Error.
11. **`WorkItemApi` mapper** (`workspace.ts`) — explicit wire vs UI type. Copy this.
12. **Dispute SLA** extracted to `dispute-sla.ts` with tests — shared slice done right (cycle 4).
13. **`parseDeepLinkSearch`** uses typeof guards, not `as DeepLinkSearch`.
14. **Ambient DOM** (`view-transitions.d.ts`) instead of `window as any`.
15. **Backend `CustomerResponse` `extra="forbid"`** — server *does* validate some egress shapes; the frontend should not pretend it can skip aligning with those models.

---

## 8. False Positives / Ambiguous Findings

| Item | Looks like | Do not do |
|------|------------|-----------|
| `routeTree.gen.ts` `@ts-nocheck` + ~33 `as any` | Hygiene failure | Do not hand-edit generated Router output. Exclude from metrics. |
| 684 `as SomeType` | Mass unsafe casts | Most are `as const`, select-value enums, test fixtures. Review clusters, not the count. |
| Seed `!` in generators | Non-null abuse | Deterministic mock maps (`RULES_BY_ID[id]!`) are OK. |
| Two `Dispute` types | “TS is unsound” | Different modules; assignability **fails**. Rename; don’t merge. |
| Two `ActiveCall` types (floor vs handoff) | Duplicate | **Live session vs floor tile** — different view-models. Rename if grepping hurts. |
| `AuthorityPolicy` / `OfferPolicy` in `lib/` vs API payloads | Duplicate schema | **UI view-models** with mappers (`authorityPolicyFromNext`). Keep. |
| `Consent` 360 embed vs `ConsentRecord` | Duplicate | Projection vs registry. Rename 360 to `ConsentSummary`. |
| `JSON.parse as T` in `prompt-studio` after `stableStringify` | Same as apiGet | **Self round-trip**, not untrusted input. |
| `undefined as T` on 204 | Lie | Documented empty-body; callers must include `\| undefined` (many don’t — that’s TS-01 adjacent, not a separate P0). |
| `skipLibCheck: true` | Hidden SDK bugs | Industry default; Pipecat issues are handled with a local `any` (TS-08), which is the visible symptom. |
| `no-explicit-any` eslint-disable | Policy hole | Two sites, commented. Prefer adapter types over deleting the rule. |
| Enabling `exactOptionalPropertyTypes` immediately | Instant safety | Will conflict with `stableStringify` and `?: T \| null` wire types. Measure first. |
| Zod everywhere | Completeness | Unused dependency is a missed tool, not a defect in existing `parseDeepLinkSearch`. |
| Analyst claim “backend absent from checkout” | Can’t verify Pydantic | **False.** `D:\Hackathon\backend` is present. Card mirror is verifiable. |
| `Interaction.summary` in JSX | Crash | React rendering `null` is safe. The lie is `.` methods and `tsc`. Don’t “fix” JSX interpolation alone. |

---

## 9. Prioritized Recommendations

### Immediate

1. **Tell the truth on `Interaction`:** `summary` / `disposition` / `startedAt` as `string | null` to match `InteractionResponse` (TS-03). Fix call sites that assume `string`.
2. **Stop shipping typecheck-optional builds:** `tsc --noEmit && vite build` (TS-10).
3. **Run `test_agent_card_schema_drift.py` when `agent-card.ts` changes** (TS-11).

### Near-term

1. **Parse or generate at the HTTP boundary** for Customer, insights, disputes list, authority next, treatment next, billing (TS-01, TS-02). `apiGet` can take a Zod schema without rewriting the helper’s call signature everywhere at once (`apiGetParsed`).
2. **Retype `AgentCardSummary.agentCard` as `AgentCard`** (TS-06).
3. **Rename colliding types** (`CustomerDisputeSummary`, `PipelinePromise`) (TS-04). Domain-prefix `Channel` (TS-05) without merging Mouth channels into CRM channels.
4. **Narrow Floor copilot `pack`** (TS-09). **Adapter for Pipecat** (TS-08).
5. **Type-aware ESLint** on `src/api/config.ts` first, then expand (TS-07).

### Long-term

1. OpenAPI or Pydantic→TS codegen as the third leg of the contract triangle (`11-api-contracts.md`). Until then, generalize the regex drift test beyond the card.
2. `noUncheckedIndexedAccess` on a dedicated branch (TS-14).
3. Typed `queryKeys` factory per domain (TS-13).
4. `exactOptionalPropertyTypes` only after wire types use `null` consistently.

**Do not:** rewrite the console; introduce io-ts and Zod and codegen in the same change; enable all extra `tsc` flags at once; delete seed files (they are mock *data*); treat `OfferPolicy` as a wire type.

---

## 10. Metrics / Baseline

| Metric | Value | Source |
|--------|------:|--------|
| `strict` | true | `tsconfig.json` |
| `noUncheckedIndexedAccess` / `exactOptionalPropertyTypes` | off / off | `tsconfig.json` |
| `@ts-ignore` in `src/` | 0 | search |
| `@ts-nocheck` | 1 (`routeTree.gen.ts`) | file header |
| `@ts-expect-error` in `src/` | 0 | search |
| Hand-written `as any` | 1 (`useSandboxLiveCall.ts`) | this session |
| Hand-written `: any` | 2 (`workspace-nav.ts`) | this session |
| `Record<string, any>` | 0 | analyst |
| `catch (e: any)` | 0 | analyst |
| `JSON.parse(...) as T` in `config.ts` | 2 helpers (`apiGet`, `apiSend`) | this session |
| `from "zod"` in `src/` | 1 file (route search) | grep |
| `src/api/*.ts` modules | 48 (incl. tests) | glob |
| `src/api` files importing `@/data/` | 26 (excl. tests) | grep this session |
| CI `tsc --noEmit` | yes, path-filtered | `frontend-typecheck.yml` |
| `npm run build` runs `tsc` | no | `package.json` |
| Cross-language TS member test | 1 (`test_agent_card_schema_drift.py`) | backend tests |
| `Interaction.summary` TS vs Py | `string` vs `str \| None` | this session |
| `Channel` type definitions (frontend) | ≥5 incompatible unions | this session |
| Generated `as any` in `routeTree.gen.ts` | ~33 | analyst; do not “fix” |

---

## 11. Final Assessment

Habibi’s TypeScript **is** an architectural safety mechanism **inside the bundle**: strict null checks, almost no `any`, honest error types, generic tables that don’t erase rows, and an Agent Card type introduced specifically because `as never` made publish failures undebuggable.

It **is not** a safety mechanism **on untrusted data**. The generic `apiGet<T>` plus seed-owned wire types means `tsc --noEmit` passing is a statement about self-consistency of the console, not about agreement with `schemas.py`. The `Interaction.summary` mismatch is the exhibit: Pydantic optional, TypeScript required, a probe script recording the crash, insights code privately null-safe, the interface still lying.

Canonical ownership is already written down in comments (`agent-card.ts`, `schemas.py extra=forbid`, `QueryState`’s failure-mode essay). The work is to **connect** those owners: generate or parse the HTTP boundary, stop using seed files as OpenAPI, and put the one existing drift test on the path that edits the TypeScript.

That is an incremental migration. The type system does not need a new philosophy. It needs to be allowed to see the bytes.

---

*End of report. No product source was modified.*
