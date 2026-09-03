# 29 — UI consistency and the design-system layer

**Question.** Where is the same UI built more than once, where do the pieces disagree, and what belongs in a canonical layer?

**Scope.** `Habibi/` — the TanStack Start + React 19 + Tailwind v4 frontend. 365 `.tsx`, 109 `.ts`, exactly one `.css`. 45 route files over ~33 screens, 33 feature component directories, 55 files in `src/components/ui/`.

**Method.** Five analysts (component, styling, design-token, form/modal/table, accessibility) over a read-only tree, plus first-hand verification by me of every load-bearing claim. Counts in this report were produced by ripgrep or by a purpose-written probe, and each is stated with the method that produced it so it can be re-derived. Nothing was installed, built, served or run except `node scripts/check-spacing-scale.mjs` and `node scripts/check-type-scale.mjs`, which are read-only.

**Relationship to report 24.** The same shape recurs, and it is the thesis of both reports: **the quality in this codebase is concentrated exactly where an incident already happened, and absent everywhere else.** In 24 it was instrumentation; here it is design-system enforcement. Three past UI incidents are recorded verbatim in the repository, each with a guard or a component written to close it. Each guard closed the specific hole and left the neighbouring one open, and this report is largely a map of the neighbours.

---

## Verdict

**The design layer is well built, well documented, and largely unused.**

This is not a codebase that lacks a design system. It has 399 design tokens in a coherent Atlassian-derived vocabulary, a clean compatibility bridge onto the shadcn names, two custom lint guards that both pass, a canonical status primitive adopted by 104 files, a working shared chart layer, and a genuinely well-engineered confirmation gate with a unit test. Somebody did serious work here.

The problem is the gap between that layer and the application. Eleven primitives in `src/components/ui/` have **zero or one** consumer, including `card`, `form`, `table`, `drawer`, `pagination`, `link`, `toggle-group` and `tag`. Meanwhile `Card`'s exact class string is hand-written 315 times, the app contains **one** `<form>` element, and no screen paginates. The primitives were not rejected — in several cases they are simply **weaker than the local code they were meant to replace**, so adopting one would be a downgrade.

Four findings are severe enough to name up front.

0. **`cn()` silently deletes the font size on two of the sixteen type tokens.** `src/lib/utils.ts` registers 14 of the 16 font-size utilities with `extendTailwindMerge`. The two it omits — `text-body-tiny` and `text-body-micro` — are **exactly the two steps `check-type-scale.mjs` says were added to close the scale gap**. Because `text-` is both a size and a colour namespace, tailwind-merge files an unregistered `text-body-tiny` as a *colour* and drops it whenever a real colour class is composed beside it. I reproduced this against the project's own installed tailwind-merge: `cn("text-body-tiny", "text-text-subtle")` returns `"text-text-subtle"`. The fix for the namespace collision is itself incomplete, in precisely the two tokens that were added to fix the namespace collision. (**U11**)

1. **A failed network read renders as a factual statement about the business.** `records/RecordsTable.tsx` — the de-facto standard table, ~20 adopters — accepts `isLoading` and `emptyMessage` but has **no `isError` prop at all**. There is nowhere to put an error. So `ConsentTable` says *"No consent records match the current filters."* and `PaymentPlansTable` says *"No payment plans yet. Use "+ Payment plan" to build one."* when the API simply failed to answer. Consent state governs whether this company may lawfully contact someone. (**U1**)

2. **Colour silently fails in twelve tokens across forty-six sites, and nothing can catch it.** Both shipped guards scan `className` strings. Neither inspects `style={{ … }}`. A `var(--danger)` that no rule defines makes the whole declaration invalid, so the element renders with no background and inherited text. On the consent screen this collapses four of five states to an identical unstyled chip — opted-in, DND and expired become indistinguishable. (**U2**)

3. **Rotating one webhook signing secret is ungated; rotating two is gated.** `routes/webhooks.tsx:263` confirms bulk delete and `:242` confirms bulk rotate with the warning *"Each receiver stops verifying deliveries until it is redeployed with the new secret."* The single-endpoint paths — `deleteEndpoint:70`, `rotateOne:103` — call `.mutate()` directly. The consequence is per-endpoint; only the plural path warns about it. (**U8**)

The good news is that the consolidation target is unusually clear, because the app has already voted. Where a primitive fits the need it is adopted overwhelmingly (`Lozenge`: 104 files). Where one does not exist, the same twenty-one files invent it independently. §17 lists the candidates in the order the evidence supports.

---

## 1. The surface

| | |
|---|---|
| Route files | 45 (~33 screens) |
| Feature component directories | 33 |
| `src/components/ui/` | 55 files (53 `.tsx`, 2 `.ts`) |
| Feature `.tsx` | 288 |
| Stylesheets | **1** (`src/styles.css`, 1,849 lines) |
| CSS custom property *names* | **399** (716 declarations across `:root` + `html.dark`) |
| `--color-*` hooks published by `@theme inline` | 318 |
| Design-token lint guards | 2, both passing |
| Files with a raw `<button>` outside `ui/` | 152 |
| Files with a raw `<input>` outside `ui/` | 37 |
| Files with a raw `<table>` outside `ui/` | 10 |
| `<form>` elements in the entire app | **1** |

There is no CSS-in-JS, no CSS modules, no second stylesheet. For a codebase this size that is a real achievement and it makes the token layer the single point of control it was designed to be.

---

## 2. What is genuinely well built

Stating this first, because the findings that follow are all *gaps in a real system* rather than the absence of one, and the remediation depends on that distinction.

**The token vocabulary.** 399 distinct custom properties, organised on the Atlassian Design System model: 129 `--background-*`, 56 `--chart-*`, 49 `--text-*`, 43 `--border-*`, 23 `--icon-*`, 13 `--surface-*`, plus `--space-*` (23), `--motion-*` (12), `--radius-*` (9), `--shadow-*`, `--blanket-*`, `--interaction-*`, `--sentiment-*`. Dark mode is a full re-mapping of the same names under `html.dark`, so night mode is a class toggle.

**The token *values* are clean — this is a faithful port, not a pile.** Worth stating because it is the finding one expects and it is not true here. 314 hex-valued tokens collapse to 114 distinct values, which is semantic aliasing working correctly (`#1868db` carries eleven roles: `--text-brand`, `--link`, `--icon-brand`, `--border-brand`, `--background-brand-bold`, …). A near-duplicate sweep at Manhattan-RGB distance ≤ 12 returned **zero accidents** — every close pair is either the same base colour at a different alpha (a deliberate interaction ramp) or two genuinely different ADS hues. There is no `#6b6e76` vs `#6b6e77` in this file. The classic fragmentation signature is absent.

**Light/dark is complete.** Zero tokens defined in dark but not light. Of the 82 defined in light and not redefined in dark, every one is correct: theme-invariant scales (radius, border-width, space, motion), the `var()`-indirection vars of the shadcn bridge, and `--sentiment-*`, all of which follow targets that *are* redefined. **No hex-valued colour token is missing from dark mode.**

**The shadcn bridge is clean, and is not fragmentation.** `styles.css:415-450` is an explicit compatibility block — `--primary: var(--background-brand-bold)`, `--muted: var(--surface-sunken)`, `--ring: var(--border-focused)`, and so on, each with its `-foreground` partner. I checked this specifically because "two competing token systems" is the finding one expects to write here, and it would have been wrong. The stock shadcn names resolve *through* the semantic tokens, so a Radix primitive and a hand-written component land on the same hex.

**Two lint guards, both passing, both born of real incidents.** `npm run lint` runs `eslint`, then `check-spacing-scale.mjs` (14 defined steps) and `check-type-scale.mjs` (16 defined tokens). Their docstrings are primary sources and worth reading in full:

- *"`px-125` does not error and does not fall back; it resolves through Tailwind's own scale to 125 × 0.25rem = **500px** of padding per side. That shipped. Three `px-125` in the flow node card gave every node 1000px of horizontal padding, collapsing its title and instructions to zero width."*
- *"169 sites across 60 files using 18 distinct sizes — 8.8, 9.6, 10, 10.4, 10.5, 11, 11.2, 11.5, 12, 12.5, 12.8, 13, 14, 16, 16.8, 20, 21.6 and 24 pixels. Half of those pairs are indistinguishable on a screen … `text-caption` shipped in 80 places this way, across 13 files, rendering at anything from 12px to 16px depending on where it sat."*

Both problems are fixed and stay fixed. This is the strongest evidence in the repository that the team can hold a design system when they decide to.

**`Lozenge` is a successful canonical primitive.** 104 files import it as a value (ripgrep on `import { … Lozenge … } from "@/components/ui/lozenge"`; three further files import only its types, which is where the analyst's 107 comes from). It carries seven semantic tones off the token set, and around eight feature components are thin, correct wrappers over it — `SlaPill`, `documents/StatusPill`, `customer360/StatusChip`, `consent/ContactablePill`, `dashboard/DeltaChip`, `callbacks/CallbackPill`. That is exactly how a design system is supposed to look.

**`Lozenge` and `Tag` are deliberately distinct, with a documented rule.** `lozenge.tsx` — semantic status, bordered and filled, *"Never use for pure decoration (see Tag)"*. `tag.tsx` — decorative classification, `bg-transparent`, colour carried only by the accent border, *"Never use for status — see Lozenge"*. Two components that cross-reference each other's contract is better documentation than most design systems manage. (What happened to `Tag` afterwards is **U5**.)

**`src/components/charts/` is a working canonical layer.** `billing/ServiceDonut.tsx` and `dashboard/BotVsHumanDonut.tsx` both import `ModernDonut`, `ChartCard` and `SnapshotPill` from `@/components/charts` — they are thin feature wrappers, not three donut implementations. I assumed duplication from the filenames and was wrong; see the corrections in §18. This is the model the rest of the codebase should follow, and it already exists in-tree.

**`confirm-gate.ts` is the best-engineered thing in the frontend.** The promise half of `useConfirm` is extracted with no React and no DOM in it, specifically so the property that matters can be tested: *"an unanswered dialog must never read as consent."* Cancel, Escape, overlay dismiss, a second question arriving, and unmount all resolve `false`, and a never-settled promise is treated as worse than either answer because it hangs the awaiting handler. It is unit-tested (`confirm-gate.test.ts`) and `window.confirm` is fully eradicated from the app. Its adoption is **U8**.

**`records/RecordsTable.tsx` is a good table.** Sorting, selection with indeterminate state, a sticky identity column, overflow handling, skeleton rows, footer aggregates. ~20 adopters. Its one missing prop is **U1**.

**`QueryState` names the failure mode precisely.** Its docstring is the clearest statement of intent in the repository and it is quoted in §3.

---

## 3. U1 — a failed read renders as a statement of fact

**The most serious finding in this report.**

`records/RecordsTable.tsx` is the app's de-facto table, used by roughly twenty screens. Its props include `isLoading` and `emptyMessage`. They do **not** include `isError`. There is no slot for a failed read, so every consumer's failure path falls through to the empty message.

Two consumers make this concrete, and neither passes even `isLoading`:

```tsx
// components/consent/ConsentTable.tsx:176
emptyMessage="No consent records match the current filters."

// components/promises/PaymentPlansTable.tsx:171
emptyMessage='No payment plans yet. Use "+ Payment plan" to build one.'
```

When the API fails, the consent registry states that no records match — about the dataset that determines whether this company may lawfully telephone a customer. The payment-plan screen goes further and issues an **instruction**: create a plan. An agent who follows it may create a duplicate plan for a customer who already has one.

This is not a novel problem to this team. It is verbatim the failure `ui/query-state.tsx` was written to prevent, and its docstring already names both halves:

> *"This codebase names 'graceful degradation lies' as its #1 failure mode and then reproduces it every time a panel reaches for `query.data ?? []` and renders the empty case as a statement of fact. … The Connectors tab told authors 'No approved connectors…' and linked them off to Integrations, while the API had two approved connectors and had merely failed to answer. Business advice, generated from a network error, sending someone to fix a problem that does not exist."*

The fix was written. It cannot reach the tables, because the table abstraction has nowhere to put it. **The abstraction is the reason the fix does not generalise.**

Adding an `isError` prop to `RecordsTable` and threading it from the ~20 adopters is the highest-value change in this report.

---

## 4. U2 — twelve undefined CSS variables, forty-six sites, zero guards

Both shipped guards read `className` strings. Neither looks inside `style={{ … }}`, and there are **121 inline `style={{}}` occurrences across 71 files**. That namespace is completely unchecked, and it is broken in production code today.

An undefined custom property with no fallback does not error and does not fall back — it makes the whole declaration invalid, so the property is dropped and the element inherits. This is the identical failure mode to the `text-caption` incident the type guard was written to stop, one namespace over.

I wrote a probe mirroring the repo's own guard logic (`scratchpad/check-var-refs.mjs`; it collects every `--x:` definition anywhere in `styles.css`, then diffs every `var(--x)` in `src/**.{ts,tsx}` that has no comma-fallback):

```
defined custom properties in styles.css: 746
var(--x) references in src/**.{ts,tsx}:  169
distinct UNDEFINED tokens (no fallback):  17
total broken reference sites:             51
```

Five of the seventeen are `--radix-*` values that Radix sets at runtime on the element (`dropdown-menu.tsx:66`, `navigation-menu.tsx:83`, `select.tsx:84`) — correct code, excluded. That leaves **12 undefined tokens across 46 sites in 15 files**:

| Token | Sites | Notable locations |
|---|---|---|
| `--warning` | 11 | `ChannelChip:18,23`, `ComplianceStatsStrip:21`, `ConsentStatsStrip:21`, `FlowNodes:93`, `LiveTranscript:53` |
| `--danger` | 9 | `CallDetailDrawer:82`, `ComplianceFilters:15`, `ChannelChip:20`, `FrequencyCapsEditor:24` |
| `--danger-bg` | 7 | `ViolationCard:168`, `ViolationSheet:255`, `ConsentDrawer:121` |
| `--warning-bg` | 5 | `ChannelChip:18,23`, `ExportAuditLog:98` |
| `--success` | 4 | `CallDetailDrawer:77`, `BotVsHumanDonut:8` |
| `--success-bg` | 3 | `TranscriptView:15`, `ChannelChip:16` |
| `--text-muted` | 2 | `ChannelChip:22` |
| `--brand-primary`, `--brand-navy` | 2 | `BotVsHumanDonut:6,7` |
| `--text-primary` | 1 | `LiveTranscript:52` |
| `--text-text-success`, `--text-text-warning` | 2 | `KpiTile:21,26` |

These are the remains of a **pre-port naming scheme**. The Atlassian port renamed everything to `--background-danger-subtler` / `--text-danger-bolder`; forty-odd references to the old flat names were never migrated, and nothing failed loudly enough to notice.

*(The token analyst independently measured 44 references with a slightly wider exclusion set. The difference is two sites and does not affect anything below.)*

### This bug is already known, written up, and fixed in exactly one file

`src/components/flow/FlowNodes.tsx:93-95`:

> `// border-danger / border-warning, not var(--danger) / var(--warning):`
> `// those two are used across the codebase but are not defined anywhere in`
> `// styles.css, so they resolve to nothing and the error state — the whole`
> `// point of this border — would silently not render.`

A developer hit this, diagnosed it precisely, wrote down the diagnosis including the phrase *"used across the codebase"*, fixed their own file, and moved on. Fifteen other files still carry it. **Nothing enforces it, so the knowledge stayed local to the file where it was learned** — the same shape as the two lint guards, except this time nobody wrote the guard.

The second workaround is worse. `dashboard/BotVsHumanDonut.tsx:5-18` carries a hand-maintained lookup table converting `var(--…)` strings to literal hex to route around the problem:

```js
const COLOR_ALIASES: Record<string, string> = {
  "var(--brand-primary)": "#1868db",
  "var(--brand-navy)":    "#505258",
  "var(--success)":       "#5b7f24",
  …
  "var(--background-brand-boldest)": "#505258",
```

Two things are wrong with it. The last line is **already incorrect** — `--background-brand-boldest` is `#1c2b42` (`styles.css:224`), not `#505258`. And the table is light-only, so every chart routed through it is **frozen at light values in dark mode**, silently undoing the one thing the dark token set exists to do.

### The worked example: the consent screen

`consent/ChannelChip.tsx` picks a colour pair per consent state and applies it inline:

```tsx
const tone =
  cc.status === "opted_in" && !capHit  ? { bg: "var(--success-bg)",     fg: "var(--success)" }
  : cc.status === "opted_in" && capHit ? { bg: "var(--warning-bg)",     fg: "var(--warning)" }
  : cc.status === "dnd"                ? { bg: "var(--danger-bg)",      fg: "var(--danger)" }
  : cc.status === "opted_out"          ? { bg: "var(--surface-sunken)", fg: "var(--text-muted)" }
  :                                      { bg: "var(--warning-bg)",     fg: "var(--warning)" };
…
<span style={{ background: tone.bg, color: tone.fg }}>
```

Seven of the eight tokens referenced here do not exist. Only `--surface-sunken` resolves. So **four of the five consent states render as an identical unstyled transparent chip**: opted-in, cap-hit, DND and expired are visually the same. Only "Opt-out" gets a background, and its text colour still fails.

An agent looking at the consent registry cannot see at a glance that a customer is on Do Not Disturb.

### The root cause: a prefix collision the eye cannot catch

Two independent bugs share one mechanism, and it explains why this is happening here specifically rather than being simple carelessness.

The Atlassian token namespace collides with Tailwind's utility prefixes. Token `--text-success` becomes class `text-text-success`. Token `--border-success` becomes class `border-border-success`. **The doubled prefix is correct in the class and wrong in the variable**, so neither a missing nor an extra prefix looks wrong to a reader.

`dashboard/KpiTile.tsx:17-27` contains both forms in one object literal:

```js
brand:   { stroke: "var(--background-brand-bold)", accent: "text-text-brand"   },  // correct
success: { stroke: "var(--text-text-success)",     accent: "text-text-success" },  // stroke dead
warning: { stroke: "var(--text-text-warning)",     accent: "text-text-warning" },  // stroke dead
```

The author copied the class name into the `var()`. `brand` works; `success` and `warning` have no stroke colour.

The same confusion runs the other way in class names — the token name pasted where the utility already supplies the prefix:

```
promises/FiltersBar.tsx:134  ring-border-border-warning/40
promises/FiltersBar.tsx:135  ring-border-border-success/40
promises/FiltersBar.tsx:136  ring-border-border-danger/40
promises/FiltersBar.tsx:137  ring-border-border-warning/40
routing/Simulator.tsx:141    ring-1 ring-border-border-success
```

Five dead classes. In `promises/FiltersBar.tsx` four of the five status tones have no ring; only `upcoming` renders. `check-type-scale.mjs` would have caught these had they begun `text-`; it only inspects that one prefix.

**Neither guard covers `bg-`, `border-`, `ring-`, `fill-`, `stroke-`, `shadow-`, `divide-`, `outline-`, or any `var()`.** Extending the existing scripts to those namespaces is mechanical — the logic is already written twice — and would have caught every site below.

### The same hole in the class namespace: 7 names, 15 sites

The token analyst replicated `check-type-scale.mjs`'s scan across the colour-bearing prefixes: 201 distinct prefix-name combinations, 3,762 occurrences, of which 43 are Tailwind stock, 5 are project `@utility` names, and 10 were hand-cleared as false positives. That leaves seven classes that emit no CSS at all:

| Class | Sites | Effect |
|---|---|---|
| `bg-text-muted` | 6 | `customer360/EmiTab.tsx:24` and `handoff/LiveTranscript.tsx:229` are **status and typing dots — they render transparent** |
| `ring-border-border-{warning,success,danger}` | 5 | §4 above |
| `bg-background-warning-subtlest` | 2 | `floor/ApprovalsQueue.tsx:22`, `handoff/HandoffCopilot.tsx:96` — banner strips with no fill |
| `bg-background-danger-subtlest` | 1 | `routes/customers.index.tsx:295` |
| `bg-surface-page` | 1 | `sandbox/ConversationPanel.tsx:244` |

I verified the hooks directly: `--color-text-muted`, `--color-surface-page`, `--color-background-warning-subtlest` and `--color-background-danger-subtlest` are all absent from `styles.css`, while the controls `--color-border-warning` and `--color-surface-sunken` are present. **The `-subtlest` step does not exist on the semantic ramps at all** — `--background-warning-*` runs `{,-hovered,-pressed,-subtler,-subtler-*,-subtle,-bold,-bold-*}`; `-subtlest` exists only on the `accent-<hue>` ramp. Two developers reached for a step that was never there.

### Raw hex — 105 occurrences in 28 files, all frozen at light

**26 of the 29 distinct hex values are exact copies of a defined token's light value** — `#1868db` ×25 (`--background-brand-bold`), `#5b7f24` ×14 (`--chart-success-bold`), `#e06c00` ×13 (`--icon-warning`). Because they are literals rather than `var()`, **all 105 are frozen at their light values in dark mode.** Concentrated in `dashboard/BotVsHumanDonut.tsx` (15), `bot-analytics/HeroStrip.tsx` (14), `data/redaction-seed.ts` (10), `lib/error-page.ts` (8).

### The guard's own two-place edit is a hazard it cannot see

`--space-*` (23 properties, the ADS vocabulary) and `--spacing-*` (14 properties in `@theme inline`, each `--spacing-N: var(--space-N)`, the hook that makes `p-200` compile) must stay in step. The guard reads `--spacing-(\d+)` only, which makes the drift **asymmetric**:

- Add a step to `--space-*` only → the guard never sees it, and `p-<step>` falls through to Tailwind's `n × 0.25rem`. **That is exactly the `px-125` → 500px incident the guard was written to prevent** — the guard does not cover its own founding bug if the token is added on the wrong side.
- Add a step to `--spacing-*` only → the guard **passes it**, and the emitted `padding: var(--space-N)` is invalid at computed-value time and collapses to `0`.

The script's error message already tells you to edit both places, which is an accurate description of a hazard nothing checks. Asserting the two sets are 1:1 is a one-line addition.

*(This is also why the nine `--space-negative-*` tokens are dead: no `--spacing-negative-*` counterpart exists, so Tailwind cannot reach them.)*

### Dead surface

40 of 399 tokens (10%) are referenced by no `var()` anywhere — 29 of them the entire per-hue chart ramp (`--chart-{lime,red,…}-{bold,bolder,boldest}`), defined but never published as `--color-*`. A further 168 of 318 published `--color-*` hooks (53%) are never used as a class, and 14 of 40 `@utility` blocks are unused, including three heading steps and six duration tokens.

---

## 5. U3 — eleven primitives with zero or one consumer

Counted by ripgrep on `from "@/components/ui/<name>"` across `src/`:

| Primitive | Value importers | What the app does instead |
|---|---|---|
| `ui/card.tsx` | **0** | `rounded-* border border-border bg-surface` hand-written **315×** in 162 files |
| `ui/form.tsx` | **0** | six ad-hoc validation strategies (§8) |
| `ui/drawer.tsx` (vaul) | **0** | six components *named* `*Drawer` import `ui/sheet` |
| `ui/pagination.tsx` | **0** | nothing paginates, anywhere |
| `ui/link.tsx` | **0** | raw `<a>` / router `Link` |
| `ui/toggle-group.tsx` | **0** | five hand-rolled segmented controls |
| `ui/tag.tsx` | **0 render sites** | one type-only import; `records/RecordsTag` reimplements it |
| `ui/table.tsx` | 1 | `RecordsTable` (~20), `FilterTable` (6), raw `<table>` (10) |
| `ui/section-message.tsx` | 1 | ~55 inline notice panels |
| `ui/query-state.tsx` | 1 | the inline ladder (§6) |
| `ui/spinner.tsx` | ~0 | `LoadingState` (28 files) |

Corroborating facts, each verified directly: `react-hook-form` is imported by exactly **one** file — `ui/form.tsx` itself. `zodResolver` appears **zero** times. `vaul` is imported only by `ui/drawer.tsx`, which nothing imports. And the entire 365-component application contains exactly **one** `<form>` element, at `floor/Inspector.tsx:282`.

`ui/card.tsx` is the sharpest number: zero importers against its own class string written out 315 times. But the analyst's diagnosis of *why* is the important part — **`Card` supplies no padding**, so all 162 sites would still need `p-200` alongside it. The primitive is strictly less useful than the literal it would replace. That is not neglect; it is a rational local decision, repeated 162 times.

---

## 6. U4 — the shared component is weaker than the code it was meant to replace

This is the mechanism behind §5, and it is the finding that should change how the team approaches consolidation. Consolidating onto a weaker primitive is a downgrade, and the app has correctly refused to do it.

**`QueryState` vs. the inline ladder.** I went looking for missing error handling and found the opposite. `routes/agent-studio.skills.index.tsx:256-264` and `routes/billing.tsx:108-112` use a four-branch ladder:

```tsx
isLoading && !data  ? <LoadingState label="Loading skills" />
: isError && !data  ? <error message />
: (data ?? []).length === 0 ? <empty state />
: <content />
```

The `&& !data` refinement is deliberate and good: it separates "failed with nothing cached" from "failed but we still hold the last good read." `skills.index.tsx:250-255` goes further and renders a stale-data banner above the table — *"The rows below are the last successful read."*

`QueryState` has no `&& !data` branch. **The shared component is a downgrade from the pattern it was written to absorb**, and it has one adopter. That is not developers ignoring the design system; that is the design system being worse.

`QueryState` also hand-rolls its own danger panel rather than using `ui/section-message.tsx` — a `ui/` primitive shadowing another `ui/` primitive — and in doing so violates SectionMessage's stated invariant that body copy stays neutral and only the icon and background carry semantic colour.

**`RecordsTable` vs. nothing.** Same shape, worse consequence: it lacks an error slot entirely, so ~20 screens have no way to express a failed read (**U1**).

The rule this suggests: **before consolidating onto a primitive, check it is at least as capable as the best local implementation.** Today `query-state`, `section-message`, `table`, `link` and `card` all fail that test.

---

## 7. U5 — the duplication inventory

Every pair below was confirmed by reading both files and checking the import list first. Where a feature component imports the shared thing it is a wrapper and is **not** listed here.

### The filter chip — the largest cluster, and the one primitive that never existed

No `ui/` primitive exists for a two-state selectable filter chip, so **21 files invent it**. The shared fingerprint is two class strings:

- inactive — `border-border bg-surface text-text-subtle hover:bg-surface-sunken` (23 sites / 19 files)
- active — `border-border-brand bg-background-brand-subtlest text-text-brand` (31 sites / 21 files)

Seven are named local components: `callbacks/FiltersBar.tsx:26` `Chip`, `documents/FiltersBar.tsx:22` `Chip`, `kb/KbToolbar.tsx:30` `Pill`, `customer360/InteractionsTab.tsx:239` `Chip`, `promises/FiltersBar.tsx:120` `StatusChip`, `prompt-studio/FilterChips.tsx:23`, `flow/FlowNodes.tsx:155`. The other fourteen are inlined.

**`callbacks/FiltersBar.tsx:26-40` and `documents/FiltersBar.tsx:22-36` are byte-identical** — I diffed them. So is the `toggle<T>` helper immediately below each, and those are the only two occurrences of that helper in the repository.

This copy-paste is also how the five dead `ring-border-border-*` classes of §4 spread.

### `FiltersBar` — six components of the same name

`dashboard/`, `callbacks/`, `documents/`, `disputes/`, `promises/`, `upsell/`, plus `floor/FilterBar.tsx`. `disputes` and `upsell` are the closest pair: identical search block, identical `<select>` class string (`h-400 rounded-medium border border-border bg-surface px-100 text-body-small`, four times each), identical My-queue button, identical reset button. The shells differ only by `shrink-0`.

### The stat tile — ten strips, eight renderings of "label + number + hint"

**`compliance/ComplianceStatsStrip.tsx:4-35` and `consent/ConsentStatsStrip.tsx:4-35` are near-byte-identical `KpiCard`s.** Same props, same markup, same `border-l-[var(--danger)]` / `warning` tone ternary — which is also two of the dead-token sites from §4, so the tone accent does not render in either. The only differences are `min-w-[11.25rem]` vs `min-w-[10.625rem]` and one prop's type. Their parents' wrapper divs are byte-identical.

`floor/StatsStrip.tsx:26-58` and `kb/KbStatsStrip.tsx:17-59` are a second near-identical `Tile` pair. A third, differently-shaped `KpiCard` lives at `billing/BillingKpiStrip.tsx:25`. Six further one-off tiles: `workspace/StatsStrip:73`, `qa/QaStatsStrip:13`, `redaction/RedactionStatsStrip:64`, `webhooks/WebhooksStats:61`, `routing/RoutingStats:16`, `routes/treatment.lazy.tsx:156`.

### The card surface — 315 hand-written instances

`rounded-(large|xlarge|medium) border border-border bg-surface` appears **315 times across 162 files** (verified). That is `ui/card.tsx`'s own class string minus `text-text`, and `ui/card.tsx` has zero importers.

### The empty state — no primitive, one string repeated verbatim

`rounded-medium border border-dashed border-border p-300 text-center text-body-small text-text-subtlest` appears **11 times across 10 files** (verified), concentrated in the sandbox inspector tabs. Five feature folders additionally wrap it in a local `Empty` component, and `charts/chart-shell.tsx:90` has a `ChartEmpty`. Around 55 dashed-border empty panels exist in total. There is no `ui/` empty-state primitive.

### The segmented control — five rebuilds while `ui/toggle-group.tsx` sits unused

`billing/BillingHeader.tsx:46,63`, `bot-analytics/BotAnalyticsHeader.tsx:36`, `integrations/IntegrationsHeader.tsx:24`, `workspace/AvailabilityToggle.tsx:86`.

Two components named `ViewToggle` — `upsell/ViewToggle.tsx:11` and `callbacks/ViewToggle.tsx:7` — share their wrapper, item and inactive classes but **disagree on the active state**: upsell uses `bg-background-brand-bold text-white`, callbacks uses `bg-background-brand-subtlest text-text-brand font-semibold`. A filled brand pill versus a tinted outline: two different answers to one control, in one product.

### Status pills that bypass the token layer

- **`disputes/SlaChip.tsx:4-15` vs `ui/SlaPill.tsx`** — the strongest named duplicate pair. Same concept, same three tones; `SlaChip` imports only `cn` and inlines the tone tokens `Lozenge` already owns.
- **`records/RecordsTag.tsx`** — its docstring says *"decorative classification only"*, which is `ui/tag.tsx`'s exact documented contract, and its ten hue keys are Tag's ten hues. It imports only `cn`, and it **breaks Tag's stated rule** that the background stays transparent and only the accent border carries colour: it renders `bg-surface` with a coloured dot. The one component in the app that genuinely needed a decorative tag built its own, while `ui/tag.tsx` sat with zero render sites.
- **`consent/ChannelChip.tsx`** — §4's worked example.
- **`redaction/ExportAuditLog.tsx:104`** — wraps `Lozenge`, then overrides it with `style={{backgroundColor, color, borderColor}}` from raw CSS vars, defeating the tone system it just imported. Three of those vars are undefined.

### `ui/badge.tsx` — the stock primitive that was never retired

`Lozenge` has 104 value importers; `Badge` has **12**. `badge.tsx` self-documents as a compact count primitive — *"For status use Lozenge"* — but its `success` and `destructive` variants use the same `background-*-subtler` / `text-*-bolder` token pair Lozenge does, so on screen they read as the same control.

**Six files import both**: `floor/PriorityLane.tsx`, `floor/AlertLane.tsx`, `webhooks/EndpointTable.tsx`, `webhooks/DeliveryRow.tsx`, `inbox/ContextRail.tsx`, `promises/PlanDetailDrawer.tsx`. Those screens show two different chip treatments side by side.

### `text-white` — 66 sites in 45 files

Hand-rolled primary buttons write `bg-background-brand-bold … text-white` where `ui/button.tsx:25` uses the token `text-text-inverse`. A literal `text-white` cannot follow a theme swap. `customer360/InteractionsTab.tsx:250-256` mixes both in a single ternary.

### `ui/SlaPill.tsx` — the naming outlier and the layering violation are the same file

It is the only PascalCase file among the 55 in `ui/`, and independently the only file in `ui/` that imports from `@/data` (`import type { SlaLevel } from "@/data/workspace-seed"`). It is a domain component parked in the primitive layer, and it carries an unrelated date formatter. The naming smell and the real defect coincide exactly — which is a decent argument for keeping the convention.

---

## 8. U6 — forms: one `<form>`, six validation strategies, zero adoption of the sanctioned one

| Strategy | Files |
|---|---|
| react-hook-form + `zodResolver` via `ui/form.tsx` | **0** |
| Imperative guard → `toast.error` | 6 |
| Disabled-submit-until-valid, no message | 5 |
| **Silent early return — the click does nothing** | 2 |
| Live-apply, no submit, no validation | 3 |
| Server-error-only | remainder |

`ui/form.tsx` adoption: **0 of ~16 form surfaces.** HTML5 validation: **0 uses** — every `required` in `src/components` is prose or a data field, never an input attribute. No `pattern=`. No field-level error state anywhere: no `setError`, no `errors` object.

I verified the supporting facts directly: `react-hook-form` is imported by exactly one file, `ui/form.tsx` itself; `zodResolver` appears zero times; and the entire 365-component application contains **one** `<form>` element, at `floor/Inspector.tsx:282`. So outside that single file there is no Enter-to-submit, no implicit submit semantics, and no native validation anywhere in the product.

The two silent-early-return sites are the worst of these — `promises/PlanBuilderSheet.tsx:109` (`if (!cust || totalN <= 0) return;`) and `integrations/McpConsole.tsx:151`. The user clicks and nothing happens at all, with no message.

Raw `<input>` bypasses (57 occurrences / 38 files): `type="checkbox"` in 12 files bypassing `ui/checkbox.tsx`, `type="range"` in 3 bypassing `ui/slider.tsx`, text/number/date in ~8 bypassing `ui/input.tsx`. Only `type="file"` is legitimate — `ui/input.tsx` has no file variant.

---

## 9. U7 — loading, empty and error states

**Query render sites, excluding `src/api/` (which holds 264 of the 356 hook occurrences and is definitions only): 88.**

| | Count |
|---|---|
| Full ladder (loading + error + empty) | **20 (23%)** |
| Partial — error, no loading | 1 |
| Loading only, **no error branch** | 9 |
| **No branch at all** | **58 (66%)** |

Fifteen route files never reference `isError` once, including `consent.tsx`, `compliance.tsx`, `promises.tsx`, `redaction.tsx`, `disputes.tsx`, `documents.tsx` and `webhooks.tsx`.

`routes/dashboard.tsx:63` is a distinct bug: `{!data ? <DashboardSkeleton/> : …}` with no error branch. On a failed fetch `data` stays undefined, so **the dashboard shows a loading skeleton forever**.

**Error presentation — six forms.** `toast.*` dominates at 416 calls across 73 files. `SectionMessage`: 1 adopter. `QueryState`: 1. Inline `text-text-danger`: ~12 files. Alert dialogs for errors: 0.

**All 38 `useMutation` definitions in `src/api/` have zero `onError`.** Handling is entirely at call sites — 118 `.mutate`/`.mutateAsync` calls against 59 `onError` handlers. The user-invisible failures matter most:

- `integrations/McpConsole.tsx:269` — **revoking an API key**, no `onError`, no confirmation.
- `integrations/McpConsole.tsx:104` — approving a connector, silent.
- `platform/OutboundControlPanel.tsx:594` — pausing or resuming a campaign run, silent.
- Six `void x.mutateAsync().then(…)` sites in `McpConsole.tsx` with no `.catch` — the success toast fires on success, and failure is an unhandled rejection with no UI at all.

The correct idiom exists and is applied inconsistently: `routes/roles.tsx:31-33` and `prompt-studio/ShipTab.tsx:235-250` both chain `.catch(err => toast.error(...))`.

**Loading — six forms.** `LoadingState` wins at 28 files and is good: `role="status"`, `aria-live="polite"`, an `aria-label`, and it honours `prefers-reduced-motion`. Hand-rolled skeleton/`animate-pulse`: 10 files. `Spinner`: effectively unused. Then the 58 sites with nothing.

Only **8 of ~20** `RecordsTable` adopters pass `isLoading` at all; the other twelve show the empty message *during* loading as well as on failure.

---

## 10. U8 — destructive actions: the gate exists and is bypassed two times in three

`useConfirm` has **4 adopters**. **Eight more files hand-roll an `AlertDialog` + pending state**: `agent-studio.index.tsx`, `agent-studio.skills.index.tsx`, `knowledge-base.lazy.tsx`, `FaqEditorSheet.tsx`, `DocumentInspector.tsx`, `prompt-studio.lazy.tsx`, `FlowCanvas.tsx`, `VersionHistory.tsx`. `knowledge-base.lazy.tsx` adds a fifth pattern — type-to-confirm. `floor/Inspector.tsx:250-275` hand-rolls an inline confirm panel from two raw buttons.

### One page, one action, gated only when plural

In `routes/webhooks.tsx` — all four paths read first-hand:

| Path | Gate |
|---|---|
| `bulkDelete:263` | `confirm({title: "Delete N endpoints?", description: "This cannot be undone…"})` ✓ |
| `deleteEndpoint:70` — per-row **and** drawer delete | `mut.remove.mutate(ep)` — **none** |
| `bulkRotate:256`, `rotateAll:282` | `confirmRotate` ✓ |
| `rotateOne:103` | `mut.rotate.mutate(ep)` — **none** |

`confirmRotate`'s own copy states the consequence: *"Each receiver stops verifying deliveries until it is redeployed with the new secret."* That consequence is **per endpoint**. Rotating one secret silently breaks that receiver's signature verification and takes a single click; rotating two explains it first. The gate is on the batch, and the harm is on the item.

Other ungated destructive actions: `McpConsole.tsx:269` revokes an API key; `McpConsole.tsx:262` rotates a gateway key; `routes/callbacks.tsx:304` cancels a scheduled customer callback.

---

## 11. U9 — modals, drawers and sheets: no rule, and a dead primitive

Sheet ~20 files · Dialog ~11 · AlertDialog ~8 · Popover 3 · **Drawer 0**.

Six components are *named* `*Drawer` and import `ui/sheet`: `CallDetailDrawer`, `ServiceDrawer`, `EndpointDrawer`, `ProviderDrawer`, `PlanDetailDrawer`, `ConsentDrawer`. The vaul-based `ui/drawer.tsx` is dead, and `vaul` is a shipped dependency serving one unimported file.

Same interaction, different container:

- Edit a billing budget rule → `Dialog`. Inspect a billing service → `Sheet`.
- Edit a KB FAQ → `Sheet`. Edit a KB chunk → `Dialog`.

Two "New X" creators use no primitive at all: `upsell/NewLeadSheet.tsx:101` and `disputes/NewDisputeSheet.tsx:68` hand-roll `fixed inset-0` overlays from raw divs — **no Radix, no focus trap, no Escape handling**. `NewLeadSheet.tsx:101` puts `onClick={onClose}` on the backdrop div rather than a button, so dismissing it is keyboard-unreachable.

*(`webhooks` having both an `EndpointSheet` and an `EndpointDrawer` is correct separation — edit versus detail — not duplication.)*

---

## 12. U10 — tables: four implementations, nothing paginates

1. **`records/RecordsTable.tsx`** — ~20 adopters, genuinely good, no error slot (**U1**), no pagination.
2. **`records/FilterTable.tsx`** — 6 adopters. CSS-grid; no sorting, no selection, no pagination.
3. **`ui/table.tsx`** — 1 adopter.
4. **Raw `<table>`** — 10 files.

**Nothing in the application paginates.** `ui/pagination.tsx` is dead and no adopter passes page state. **Virtualisation exists in exactly two files**, both in prompt-studio (`VoiceCatalogBrowser.tsx:291`, `VoiceCatalogTable.tsx:121`) — and not on the unbounded CRM grids, which are the ones that grow with the book.

---

## 13. U11 — `cn()` deletes the font size on the two newest type tokens

**The sharpest finding in this report**, because it is invisible, it is in the shared layer, and it is the fourth instance of one root cause.

`src/lib/utils.ts` exists to solve a specific problem, and its docstring states it exactly:

> *"`text-body-small` looks exactly like a `text-<color>` utility … Stock tailwind-merge therefore files them in the colour conflict groups, decides they clash with the real colour class beside them, and deletes whichever came first — so `cn("text-body-small", "text-text-brand")` shipped the colour alone and the element fell back to the inherited 16px. Chips rendered ~33% oversized wherever they were composed through `cn()`, and at the correct 12px wherever the className happened to be a plain string literal, which is what made type sizes look inconsistent between screens."*

The fix is `TYPE_PRESETS`, a list registered into the `font-size` conflict group. **`styles.css` defines 16 font-size `@utility` tokens. `TYPE_PRESETS` lists 14.** The two missing are `text-body-tiny` and `text-body-micro` — and `check-type-scale.mjs`'s own header names those two as the steps added to close the scale gap:

> *"The scale itself was the cause — it stopped at 0.75rem and the app did not, so every piece of micro-copy had to invent one. `text-body-tiny` and `text-body-micro` close that gap."*

So the two tokens introduced to fix the type scale were added to the stylesheet and to the guard, and never added to the merge config that makes them survive `cn()`.

I reproduced the behaviour against the project's own installed tailwind-merge, using `TYPE_PRESETS` copied verbatim from `utils.ts`:

```
cn("text-body-small", "text-text-subtle")  ->  "text-body-small text-text-subtle"   registered: both kept
cn("text-body-tiny",  "text-text-subtle")  ->  "text-text-subtle"                   SIZE DELETED
cn("text-body-micro", "text-text-danger")  ->  "text-text-danger"                   SIZE DELETED
cn("text-text-subtle", "text-body-tiny")   ->  "text-body-tiny"                     COLOUR DELETED

// the real call site, prompt-studio/VoiceCatalogTable.tsx:191
cn("text-body-tiny font-medium tracking-wide", "text-text-subtlest uppercase")
   ->  "font-medium tracking-wide text-text-subtlest uppercase"                     SIZE DELETED
```

`text-body-tiny` and `text-body-micro` account for **190 occurrences across 47 files**. Most are plain string literals and render correctly; the damage is confined to the sites composed through `cn()` with a colour class, which the styling analyst enumerates as **13**:

`flow/FlowNodes.tsx:139,315,350` · `prompt-studio/VoiceParamsPanel.tsx:174,473,502` · `charts/modern-bars.tsx:146` · `charts/segmented-bar.tsx:90` · `flow/FlowConditionEdge.tsx:144` · `prompt-studio/FilterChips.tsx:66` · `prompt-studio/ScrubField.tsx:101` · `prompt-studio/VoiceCatalogTable.tsx:191` · `records/FilterTable.tsx:98`

At every one of them the element falls back to its parent's font size. This reproduces the exact symptom `utils.ts` describes as fixed — *"type sizes look inconsistent between screens"* — for the two newest steps of the scale. **It is a one-line fix**, and it is the highest value-per-character change available in this codebase.

### The one root cause behind four bugs

`check-type-scale.mjs` states the problem in its own words: *"`text-` is two namespaces wearing one prefix — `text-body-small` is a size and `text-text-subtle` is a colour."* Every one of the following is that sentence:

| # | Bug | Where | Guarded? |
|---|---|---|---|
| 1 | `text-caption` undefined, rendered nothing, 80 sites | fixed | ✓ by `check-type-scale.mjs` |
| 2 | `var(--text-text-success)` — class form pasted into a token slot | `KpiTile.tsx:21,26` | ✗ |
| 3 | `ring-border-border-success` — token form pasted into a class slot | 5 sites | ✗ |
| 4 | `text-body-tiny` unregistered, deleted by `cn()` | 13 sites | ✗ |

The team diagnosed the namespace collision correctly and fixed the instance in front of them, four times, without ever generalising the fix. That is the whole report in one table.

---

## 14. U12 — colour, typography and responsive behaviour

### Everything is frozen at the light value

**There is exactly one `dark:` variant in the entire codebase** (`ui/chart.tsx:7`). Theming is done purely by remapping tokens under `html.dark`, which is a good design — but it means any literal colour has no escape hatch at all.

- **105 raw hex occurrences in 28 files**, 26 of 29 distinct values being verbatim copies of a token's light value. Seven of those values (`#e06c00`, `#e2483d`, `#505258`, `#82b536`, `#f68909`, `#357de8`, `#1c2b42`) correspond to tokens that *do* shift in dark, so they are unambiguously wrong at night.
- **`text-white` — 66 sites across 45 files** where `text-text-inverse` is the token. It passes the type guard because `white` sits in that script's Tailwind allowlist.
- **`bg-black/30`–`/80` — 13 sites**, including inside `ui/sheet.tsx`, `ui/drawer.tsx` and `ui/alert-dialog.tsx`, duplicating `--blanket`, which exists precisely for scrims and does adapt.

The worst instances are token tables re-implemented in JavaScript: `dashboard/BotVsHumanDonut.tsx:6-20` maps CSS-variable *name strings* to light hex, and `dashboard/Sparkline.tsx:16-20` sniffs a className substring (`if (stroke.includes("brand")) return "#1868db"`). `charts/liveline-spark.tsx:9` and `liveline-trend.tsx:43` hardcode `#1868db` as a **default parameter**, so every call site that omits `color` bakes it in.

Counterweight worth recording: **Tailwind's stock palette is essentially unused** — 2 sites plus 8 directional `border-t-<hue>-N` in two files. For a codebase of this size that is genuinely disciplined, and it is why the semantic token layer is worth repairing rather than replacing.

### The severity chips that don't render

`compliance/ComplianceFilters.tsx:15-18` is the clearest single consequence of §4:

```js
critical: "bg-[color:var(--danger)]  text-white border-transparent",
high:     "bg-[color:var(--warning)] text-white border-transparent",
medium:   "bg-[color:var(--sentiment-neutral)] text-white border-transparent",
low:      "bg-surface-sunken text-text border-border",
```

`--sentiment-neutral` resolves and `low` uses real tokens. `--danger` and `--warning` do not exist. **The two highest-severity chips on the compliance screen render as white text on a transparent background.** The same shape recurs in `compliance/ComplianceStatsStrip.tsx:19-21`, where the danger and warning accent bars fall back to `currentColor` while only the `default` branch uses a real token.

### `Button` is missing three variants, so 36 call sites paint over it

Of **286 `<Button>` call sites, 126 override something the cva already owns, and 36 override the variant's own paint** — 15 on the default, 14 on `ghost`, 7 on `outline`. Three coherent variants are being hand-rolled:

- **`primary`, reimplemented** — `customer360/NextBestActionCard.tsx:86` and `CustomerHeader.tsx:116` use the default variant plus `bg-background-brand-bold hover:bg-background-brand-bold-hovered`, which is the existing `primary` variant verbatim.
- **A danger-ghost that does not exist** — `ghost`/`outline` + `text-text-danger` + `hover:bg-background-danger*` at `flow/FlowInspector.tsx:278`, `callbacks/CallbackList.tsx:192`, `callbacks/CallbackSheet.tsx:205`, `billing/BudgetPanel.tsx:116`, `kb/DocumentInspector.tsx:289`, `kb/FaqEditorSheet.tsx:188`.
- **A `success` variant that does not exist** — `upsell/LeadSheet.tsx:632,691`, using `text-white` where all eleven real variants use `text-text-inverse`.

`promises/PromiseCard.tsx:146,161,172` and `disputes/DisputeCard.tsx:124` repeat the tone-ghost pattern four times with different semantic colours. A `tone` prop on `Button` would absorb every one of these.

### `className` sprawl is not a problem here

6,679 `className` sites; 77% carry fewer than six classes, and **all 13 of the longest are vendored `ui/` primitives** (`ui/calendar.tsx:167` at 47 classes). The only non-`ui/` outlier is `callbacks/CallbackPill.tsx:54`. Worth stating plainly so remediation effort does not go here.

### Arbitrary values, and a third scale nobody guards

684 bracket expressions, of which 256 are variant selectors (`data-[…]`, `group-[…]`) and legitimate. Of the ~428 real values, sizing dominates (339). Most use `rem`. The px minority breaks the scales outright, and **`rounded-[…]` is the notable gap**: `rounded-[7px]`, `rounded-[5px]`, `rounded-[1px]`, `rounded-t-[6px]` all sit *between* the eight defined radius steps. A `check-radius-scale.mjs` sibling would catch these by the same mechanism as the other two guards.

### Responsive coverage is thin

**191 breakpoint uses across 90 of 365 `.tsx` files (25%).** `sm:` 56 · `md:` 46 · `xl:` 46 · `lg:` 43 · **`2xl:` zero**. Container queries appear in two files. That `xl:` outnumbers `lg:` suggests breakpoints are added reactively per component rather than from a shared layout contract.

The real hazard is the **122 `min-w-[…]` values**: the wide tables (`records/RecordsTable.tsx`, `webhooks/EndpointTable.tsx`, `prompt-studio/VoiceCatalogTable.tsx`) pin column widths with no breakpoint handling at all.

### Two spacing vocabularies, 257 files mixing both

The spacing guard deliberately exempts one- and two-digit utilities as "a separate, valid scale." The result is **5,332 token-scale uses against 2,071 stock-scale uses, with 257 of 328 files mixing both**. Since `--space-150` is `0.75rem` and `h-3` is `0.75rem`, these are frequently *the same value spelled two ways*, and single elements carry both (`px-100 h-3`). `prompt-studio/VoiceCatalogTable.tsx` is the extreme case: 35 stock-scale uses and zero token-scale.

Much of the two-digit usage is icon sizing (`h-3`/`w-3` ×544 each) and defensible. The ~25 padding and gap sites that use the stock vocabulary are not — they are the same pixels in a different language, and they are invisible to the guard.

---

## 15. U13 — accessibility: the right answer exists in-tree for every finding

This section was produced from TypeScript ASTs rather than greps, after the analyst's first regex for `<div onClick=` returned **0** — prettier splits JSX tags across lines, and the real count is 21. That is the same anchored-pattern failure that produced a false finding in report 21, caught this time before it reached the page.

The through-line matters more than any single count: **the repository already contains a correct implementation of every item below.** `focus-ring` for focus, `ui/form.tsx` for labelling, `ui/sheet.tsx` for modals, `TableCaption` and `scope` for tables, `charts/segmented-bar.tsx` for charts, `inbox/ChatThread.tsx` for live regions. In each case the good pattern is applied to a minority of call sites and the rest hand-roll. This is not a knowledge gap; it is the same adoption gap as §5, with worse consequences.

### Two modal systems, one accessible

**34 files** use the Radix-backed `ui/sheet | dialog | drawer | alert-dialog` and get `role="dialog"`, focus trap, Escape, `aria-modal` and focus restore for free. **10 files hand-roll the same panel**, in two sub-conventions that disagree with each other:

- **Family A — the backdrop is a real `<button aria-label="Close overlay">`** (6 files): `callbacks/CallbackSheet.tsx:141`, `callbacks/NewCallbackSheet.tsx:115`, `documents/RequestSheet.tsx:75`, `documents/NewRequestSheet.tsx:69`, `disputes/DisputeSheet.tsx:138`, `disputes/NewDisputeSheet.tsx:68`.
- **Family B — the backdrop is a bare `<div onClick>`** (4 files): `qa/NewCoachingSheet.tsx:32`, `qa/RubricBuilderSheet.tsx:66`, `upsell/NewLeadSheet.tsx:101`, `upsell/LeadSheet.tsx:225`. Dismiss is mouse-only.

All ten lack `role="dialog"`, `aria-modal`, `aria-labelledby`, focus trap and focus restore, and **none of the ten handles Escape** — none appears in a grep for `Escape|keydown|onKeyDown`. Three teams wrote three answers to "how do I open a panel," and only one of the three is the one the design system already ships.

### `ui/form.tsx` is correct, and its absence is measurable

`ui/form.tsx:100-118` implements the textbook wiring — `FormControl` sets `id`, `aria-describedby` and `aria-invalid`; `FormLabel` sets `htmlFor`. It has **zero importers** (§5). The consequence is directly observable: **`aria-invalid` is set in exactly two places in the entire repository** — `ui/form.tsx:114`, which is dead, and `routes/agent-studio.skills.index.tsx:218`, which is the only live use.

The detail that makes this concrete: **`ui/input.tsx:11` carries `aria-invalid:border-border-danger`** in its class string — a validation style, on the shared input primitive, that can essentially never fire because nothing sets the attribute. The design system anticipated form validation correctly at both ends and nothing in between ever connected them.

**245 of 355 form controls (69%) have no accessible name.** 127 text inputs (86 falling back to a placeholder, which vanishes on typing and fails WCAG 3.3.2 as a sole label; **41 with nothing at all**), 58 native `<select>`, 51 Radix `SelectTrigger` (which announce the current *value*, never the *purpose*), 9 Sliders. **107 `<label>` elements have no `htmlFor`; only 30 do** — the house style is a label that is visible but not programmatically associated. Worst: `integrations/McpConsole.tsx` (12), `customer360/ActionSheets.tsx` (11), `promises/PromiseSheet.tsx` (10), `upsell/LeadSheet.tsx` (10).

### One `<tr>` makes every clickable row in the product mouse-only

Of 21 non-interactive elements carrying `onClick`, **12 are `e.stopPropagation()` guards** wrapping a real control inside a clickable row — benign, and correctly excluded rather than used to inflate the number. The honest count of keyboard-unreachable handlers is **9**, and none of the 21 has any keyboard affordance.

**`records/RecordsTable.tsx:234-244` is the whole finding.** The `<tr>` takes `onClick={onRowClick ? () => onRowClick(row) : undefined}` and `cursor-pointer`, with no `role`, no `tabIndex` and no key handler. That primitive is imported by **25 files** — customers, calls, callbacks, documents, webhooks, leads, payment plans, consent, KB docs, FAQs, the floor live table, billing and QA. Every clickable row in the product is mouse-only, from this one element.

And the inconsistency is *inside the same element*: thirteen lines below, the row's own checkbox is correctly labelled `aria-label={`Select row ${id}`}` (`:257`). Somebody thought about accessibility here and stopped at the checkbox.

### Icon-only controls: the convention exists and is applied two times in three

630 buttons (344 raw `<button>`, 286 `<Button>`). 85 are icon-only; **60 are named and 25 are not (29%)**.

The two worst clusters are both consequential. `webhooks/EndpointDrawer.tsx` has five unnamed adjacent controls — three separate `Copy` buttons, a `KeyRound` rotate-secret and an `Eye/EyeOff` reveal-secret — all announcing simply "button", on the screen where §10's ungated rotate also lives. And **`audit/AudioPlayer.tsx:74,82,85` leaves the entire transport of the call-recording player unnamed**; `:82` is `{playing ? <Pause/> : <Play/>}` inside `<Button size="icon">` — play/pause on a call recording, in a voice product, with no name and no state.

Four sheets, two answers: `disputes/DisputeSheet.tsx:170` and `documents/NewRequestSheet.tsx:79` label their close button; `callbacks/CallbackSheet.tsx:169` and `upsell/LeadSheet.tsx:245` do not.

*(Tooltips do not rescue these — Radix Tooltip supplies `aria-describedby` only while open, never an accessible name.)*

**Decorative icons are hidden 28 times out of 682 (4.1%)**, across 12 files, six of them `prompt-studio/*`. It is one team's habit, not a convention. The central fix point exists and was not used: `ui/button.tsx`'s cva base styles child svgs (`[&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0`) but sets no `aria-hidden`, so every labelled button leaks its icon into its accessible name. *(That same cva does apply `focus-ring` and `aria-busy={loading}` centrally — both real strengths.)*

### Four focus treatments, four of them invisible

`styles.css:1208` defines `@utility focus-ring` correctly, and the `ui/` primitives use it. **26 files use `focus-ring`; 34 use `outline-none`.** The app layer splits four ways: the sanctioned utility; `focus:border-border-brand focus:outline-none` (~13 sites, border-colour only and on `:focus` rather than `:focus-visible`, so it fires on mouse click too); `focus:outline-none focus:ring-2` (4 sites); and **the outline removed with no replacement at all** — `floor/CallTile.tsx:188`, `shell/Sidebar.tsx:357` (the sidebar search input), `sandbox/SandboxHeader.tsx:262`, `prompt-studio/ScrubField.tsx:125`. Only 5 files use `focus-visible:ring`.

### Tables

Eleven app-level raw `<table>` plus `ui/table.tsx`. **None has `aria-label`, `aria-labelledby` or a caption** — `TableCaption` is defined at `ui/table.tsx:98` and used zero times. Of **102 header cells, 2 carry `scope`** (both in `prompt-studio/VoiceCatalogTable.tsx`) and **0 carry `aria-sort`**, including the two sortable tables, where direction is conveyed only by a rotated `ArrowDown`. `ui/table.tsx:72` renders a bare `<th>` with no `scope` default, so the shared primitive cannot supply it.

### Live regions: six in the app, and none on the voice surfaces

All six: `inbox/ChatThread.tsx:16`, `sandbox/TuningStudio.tsx:234`, `routes/inbox.tsx:342`, plus `ui/loading-state.tsx:86`, `ui/section-message.tsx:49`, `ui/spinner.tsx:29`. Sonner was checked in `node_modules` and does render a polite live region, so toasts announce.

The gap falls precisely where this product lives:

- **`handoff/LiveTranscript.tsx`** — the streaming transcript a human agent reads while taking over a bot call. No `aria-live`, no `role="log"`, no accessible name on the section. Turns append silently.
- **`sandbox/ConversationPanel.tsx:248-258`** — the live call state (`idle → connecting → live → ended`) is a plain `<Lozenge>` in no live region. The call connects and drops silently. `:266-268` *does* set `aria-label="Speaking indicator"` on the speaking dots — labelled, but announced only if you happen to land on it.

Set against `inbox/ChatThread.tsx:14-19`, which wraps the **bot typing bubble** in `aria-live="polite"` with `aria-label="Bot is typing"`: the chat product announces that a bot is typing, and the voice product does not announce that the call connected.

### Charts, images, and what is fine

**Zero `<img>` elements** in `src` — there is no alt-text problem. Four hand-built chart components, four conventions: `charts/segmented-bar.tsx:44-55` is the best accessibility work in the repository (`role="group"`, per-segment `aria-pressed` and `aria-label` carrying the value as text); `modern-donut.tsx:54` has a generic `role="img"` with no data; `liveline-spark.tsx:37` is correctly `aria-hidden`; `modern-bars.tsx` has nothing. `charts/chart-shell.tsx` does give every chart an `<h3>`, so context exists.

**Navigation is a strength**, checked rather than assumed: `shell/Sidebar.tsx:243` sets `aria-current="page"`, and `MobileNav` imports the same `NavLinks`, so both navs get it. `<main>` and `<nav>` landmarks are present.

**`@xyflow/react` is not a finding** — `flow/FlowCanvas.tsx:1192` does not override `nodesFocusable`, `edgesFocusable` or `disableKeyboardA11y`, so the library's own keyboard navigation applies. The props were read before concluding.

### One more dead dependency

**`recharts` is imported by exactly one file — `ui/chart.tsx` — and `ui/chart.tsx` has zero importers.** Every rendered chart in the product is hand-built in `src/components/charts/`. Recharts joins `vaul` and `react-hook-form` as a shipped dependency serving only an unused primitive.

---

## 16. What a user actually sees, screen by screen

The findings above are organised by mechanism. This table reorganises them by the screen they land on, ordered by how much the defect matters to the business rather than how interesting it is technically.

| Screen | What is actually wrong on it today | Findings |
|---|---|---|
| **Consent registry** | A failed read says *"No consent records match the current filters."* And **four of five consent states render as the same unstyled transparent chip** — opted-in, cap-hit, DND and expired are visually identical, because seven of the eight colour tokens `ChannelChip` uses do not exist. This is the screen that governs whether the company may lawfully telephone someone. | U1, U2 |
| **Compliance** | The `critical` and `high` severity chips render **white text on a transparent background** (`ComplianceFilters.tsx:15-18`); the danger and warning accent bars on the stats strip fall back to `currentColor`. The route never references `isError`. | U2, U12 |
| **Payment plans** | A failed read tells the agent *"No payment plans yet. Use "+ Payment plan" to build one"* — an instruction to create a duplicate plan for a customer who may already have one. | U1 |
| **Promises** | Four of five status filter rings are dead classes (`ring-border-border-*`), so the selected filter is only visible on `upcoming`. | U2 |
| **Webhooks** | Deleting or rotating a **single** endpoint takes one click with no confirmation; doing two shows a dialog explaining that receivers stop verifying deliveries. Two different chip components appear on the same table. | U8, U5 |
| **Dashboard** | On a failed fetch the page shows a **loading skeleton forever** (`dashboard.tsx:63`). The KPI tiles' success and warning strokes are dead `var()`s. The bot-vs-human donut runs off a hand-maintained hex table that is already wrong on one line and frozen at light values. | U7, U2, U12 |
| **Integrations / MCP console** | Revoking an API key has **no confirmation and no error handling**. Six `void …mutateAsync()` calls have no `.catch`, so a failure is an unhandled rejection with no UI. | U8, U7 |
| **Voice catalogue** (prompt studio) | Every table header ships at the inherited font size instead of `text-body-tiny`, because `cn()` deletes it. The file also uses 35 stock-scale spacing utilities and zero token-scale ones. | U11, U12 |
| **Floor / handoff** | Status dots and the typing indicator use `bg-text-muted`, which emits no CSS — **they render transparent**. Banner strips using `bg-background-warning-subtlest` have no fill. | U2 |
| **New lead / new dispute** | Both hand-roll a `fixed inset-0` modal with no Radix, **no focus trap and no Escape handling**; the backdrop dismiss is a `div onClick`, so it is keyboard-unreachable. | U9 |
| **Callbacks** | Cancelling a scheduled customer callback is ungated. Its `ViewToggle` renders an active tab differently from the identical control in Upsell. | U8, U5 |
| **Redaction** | `ExportAuditLog` imports `Lozenge` and then overrides its tone with three undefined CSS variables. | U2, U5 |
| **Knowledge base** | Well gated, but through three different confirmation placements for one delete operation, plus a fourth type-to-confirm pattern for purge. | U8 |
| **Every list screen** | Nothing paginates anywhere in the product, and virtualisation exists on two prompt-studio tables but not on the CRM grids that grow with the book. | U10 |

Two observations from the table.

**The damage clusters on the compliance-facing screens.** Consent, compliance, promises and redaction hold four of the top six rows. That is not coincidence: those screens were built with semantic severity colouring, and semantic severity colouring is exactly what the abandoned `--danger` / `--warning` vocabulary was for. The screens that use plain neutral chrome were never exposed to the dead tokens.

**Every one of these is silent.** No console error, no failed build, no red test. `npm run lint` passes, `tsc --noEmit` passes, the two design guards pass. A dead `var()`, an unregistered merge token, an absent `isError` prop and a missing `confirm()` all produce a page that renders and looks approximately right. That is the property that lets fourteen screens accumulate defects nobody logged.

---

## 17. Candidates for a canonical design-system layer

The brief asked for these specifically. Ordered by evidence, with the rule that **a primitive is only worth creating if it is at least as capable as the best local implementation it replaces** — the failure mode of §6.

### Tier 1 — fix the shared layer that already exists

These are small, mechanical, and they unblock everything else. Do them first; consolidating onto a broken layer propagates the break.

1. **Add `text-body-tiny` and `text-body-micro` to `TYPE_PRESETS`** (`src/lib/utils.ts:21-35`). One line. Restores the font size at 13 call sites and removes a whole class of "why does this look wrong here" investigation. (**U11**)
2. **Add an `isError` prop to `records/RecordsTable.tsx`** and thread it from its ~20 adopters, starting with `ConsentTable` and `PaymentPlansTable`. This is the only change that stops the product making false statements about consent and payment state. (**U1**)
3. **Migrate the 12 dead `var()` names** to their Atlassian equivalents — `--danger` → `--background-danger-bold` or `--text-danger`, and so on — across 46 sites in 15 files. Delete the `COLOR_ALIASES` table in `BotVsHumanDonut.tsx` and the `Sparkline` className sniffing rather than porting them. (**U2**)
4. **Give `ui/query-state.tsx` the `&& !data` stale-data branch** the routes already have, and make it render `SectionMessage` rather than its own danger panel. Until it is at least as good as `billing.tsx:108-112`, nobody should adopt it. (**U4**)

### Tier 2 — the guard that should exist

5. **`check-color-tokens.mjs`**, a third sibling to the two that already work. It should validate:
   - every `var(--x)` in `src/**` against the properties defined in `styles.css` (allowlisting `--radix-*` and `--magicui-*`),
   - every `bg-` / `border-` / `ring-` / `fill-` / `stroke-` / `shadow-` / `divide-` / `outline-` class against the published `--color-*` hooks plus the Tailwind stock palette,
   - that `--space-*` and `--spacing-*` are 1:1,
   - that `TYPE_PRESETS` in `utils.ts` equals the set of font-size `@utility` names in `styles.css`.

   The detection logic already exists in `check-type-scale.mjs` and only needs its prefix list widened. This single script would have caught findings U2, U11, the five dead ring classes, the seven dead colour classes, and both `--space-*` drift directions — mechanically, at lint time, forever. **It is the highest-leverage item in this report.** A `check-radius-scale.mjs` for the `rounded-[Npx]` set is a cheap follow-on.

### Tier 3 — the primitives the app actually voted for

Each of these is a component 20+ files already wrote themselves, so the demand is demonstrated rather than assumed.

6. **`ui/chip.tsx`** — a two-state selectable filter chip. **21 files**, 7 named local duplicates, two byte-identical pairs. The single largest cluster in the codebase and the one primitive the system never had. Note this is *not* `Button` with a variant: it is a pressed-state control and wants `aria-pressed`, which is why every author correctly reached for a raw `<button>`.
7. **`ui/stat-tile.tsx`** — ten stats strips, eight renderings. Start with the two near-byte-identical `KpiCard`s (`ComplianceStatsStrip` / `ConsentStatsStrip`) and the two near-identical `Tile`s (`floor/StatsStrip` / `kb/KbStatsStrip`): four files, purely mechanical.
8. **`ui/empty-state.tsx`** — one class string repeated verbatim 11 times, five local `Empty` wrappers, ~55 panels total. Should take the same `label`/`hint`/`action` shape the existing `emptyMessage` props imply.
9. **`ui/segmented-control.tsx`** — five hand-rolled controls, and two `ViewToggle`s that disagree on what "active" looks like. `ui/toggle-group.tsx` already exists and has zero importers; determine whether it can be the answer before writing a new one.
10. **A `tone` prop on `ui/button.tsx`** — absorbing the danger-ghost (6 sites), `success` (2 sites) and reimplemented-`primary` (2 sites) variants, plus the four-site `PromiseCard`/`DisputeCard` cluster. 36 call sites currently paint over the variant they asked for.

### Tier 4 — decide, then act

11. **`ui/card.tsx`: give it padding variants or delete it.** Zero importers against 315 hand-written instances of its own class string. It is unusable as written because it supplies no padding, so every adopter would still need `p-200`. Either fix that and migrate, or remove it so it stops reading as an available primitive.
12. **Retire `ui/badge.tsx` in favour of `Lozenge`**, or give the two visibly different treatments. 104 files versus 12, with **6 files importing both**.
13. **Delete the dead primitives**: `ui/drawer.tsx` (and the `vaul` dependency it alone justifies), `ui/pagination.tsx`, `ui/link.tsx`, `ui/form.tsx` (with `react-hook-form` and `@hookform/resolvers`, which nothing else uses). Keeping an unused primitive is worse than having none: it reads as an endorsed solution and it is the reason `records/RecordsTag` was written from scratch beside an unrendered `ui/tag.tsx`.
14. **Rename `ui/SlaPill.tsx` to kebab-case and invert `SlaLevel` out of `@/data`** — it is the only PascalCase file and the only `@/data` importer in `ui/`, and those are the same defect.
15. **Write the missing `Design.md`, or delete the references to it.** `styles.css:9` instructs *"do not hand-tune a value here without updating Design.md first"* and `check-type-scale.mjs` cites "Design.md rules." **No such file exists anywhere in the repository.** Until it does, the port's claimed provenance ("Atlassian Design System manifest, revision 0.0.7") is unverifiable, the `rovo-*` omission is unreviewable, and the stated procedure for changing any of 399 token values cannot be followed. If the intent was that `styles.css` *is* the source of truth now, saying so in one line is a complete fix.

---

## Findings index

| ID | § | Finding | Why it matters |
|---|---|---|---|
| **U1** | 3 | `records/RecordsTable.tsx` has no `isError` prop; ~20 screens render `emptyMessage` on a failed read | The consent registry and payment-plan screens make **false factual statements** about regulated data |
| **U2** | 4 | 12 undefined CSS custom properties across 46 sites; 7 dead colour classes across 15 sites; neither guard covers `var()` or non-`text-` prefixes | Consent states collapse to one indistinguishable chip; compliance severity chips render invisibly. Already diagnosed in-tree at `flow/FlowNodes.tsx:93-95` and fixed in one file |
| **U3** | 5 | Eleven `ui/` primitives with zero or one consumer — `card`, `form`, `drawer`, `pagination`, `link`, `toggle-group`, `tag`, `table`, `section-message`, `query-state`, `spinner` | 315 hand-written cards, one `<form>` in the whole app, three dead dependencies |
| **U4** | 6 | The shared primitive is *weaker* than the local pattern it was meant to replace | Explains U3. Consolidating onto `query-state` or `card` today would be a downgrade |
| **U5** | 7 | Duplication inventory: 21-file filter-chip cluster, 6 `FiltersBar`s, 10 stat strips, 2 byte-identical `Chip`s, 2 disagreeing `ViewToggle`s | Same control, different appearance, across screens a single user sees in one session |
| **U6** | 8 | Six form-validation strategies; `ui/form.tsx` at 0 adopters; zero HTML5 validation; **one `<form>` element** | Two sites fail silently — the click does nothing at all |
| **U7** | 9 | 58 of 88 query render sites (66%) have no loading or error branch; all 38 `useMutation` definitions lack `onError` | `dashboard.tsx:63` shows a skeleton forever on failure; revoking an API key fails invisibly |
| **U8** | 10 | Destructive confirmation bypassed 2 times in 3; **single-endpoint delete and secret-rotate are ungated while the bulk paths are gated** | The consequence is per-endpoint; only the plural path warns about it |
| **U9** | 11 | No rule for dialog vs sheet vs drawer; `ui/drawer.tsx` dead; two creators hand-roll modals with no focus trap or Escape | Same interaction, different container, across features |
| **U10** | 12 | Four table implementations; **nothing in the product paginates**; virtualisation on two prompt-studio tables but not the CRM grids | The grids that grow with the book are the unvirtualised ones |
| **U11** | 13 | `cn()` deletes the font size on `text-body-tiny` and `text-body-micro` — the two tokens added to fix the type scale | Invisible, in the shared layer, 13 call sites. **One-line fix** |
| **U12** | 14 | 105 raw hex + 66 `text-white` + 13 `bg-black/*` frozen at light values, with exactly one `dark:` variant in the codebase; `Button` missing three variants that 36 call sites paint by hand | Dark mode is silently wrong wherever a literal was used |
| **U13** | 15 | 69% of form controls unnamed; one `<tr>` makes every clickable row in 25 screens mouse-only; 4 invisible focus treatments; no live region on either voice surface | A correct implementation of **every** item already exists in the repo and is applied to a minority of call sites |

---

## Checked and cleared

Things I examined and found to be *fine*, recorded because a consistency audit that reports only faults is not usable as a map.

- **Token values.** No accidental near-duplicates at all (RGB distance ≤ 12 yields only alpha ramps and genuinely distinct hues). 314 hex tokens collapsing to 114 values is semantic aliasing working as intended.
- **Light/dark completeness.** Zero colour tokens missing from the dark block. The 82 light-only definitions are all theme-invariant scales or `var()` aliases that follow redefined targets.
- **The shadcn compatibility bridge** (`styles.css:415-450`) — complete, every `-foreground` partner present, every target resolving. This is the finding one expects to write and it would have been wrong.
- **`src/components/charts/`** — a genuinely working canonical layer. `ServiceDonut` and `BotVsHumanDonut` are thin wrappers over a shared `ModernDonut`, not duplicates.
- **`Lozenge` vs `Tag`** — deliberately distinct concepts with documented, mutually cross-referencing contracts. Better documentation than most design systems manage.
- **`className` sprawl** — not a problem. 77% of 6,679 sites carry fewer than six classes, and all 13 of the longest are vendored `ui/` primitives.
- **Tailwind's stock colour palette** — essentially unused (2 sites plus 8 directional borders). Genuine discipline.
- **Navigation** — `aria-current="page"` is set, and `MobileNav` shares `Sidebar`'s `NavLinks`, so both navs get it. `<main>` and `<nav>` landmarks present.
- **`@xyflow/react`** — `FlowCanvas.tsx:1192` does not disable the library's keyboard navigation. Props read before concluding.
- **Images** — zero `<img>` elements in `src`. No alt-text problem exists.
- **Sonner toasts** — verified in `node_modules`; it renders a polite live region, so toasts do announce.
- **`ui/confirm-gate.ts`** — the best-engineered file in the frontend, and unit-tested.
- **`webhooks/EndpointSheet` vs `EndpointDrawer`** — correct separation (edit vs detail), not duplication.
- **`audit/AudioPlayer` vs `floor/Waveform`**, and **`audit/TranscriptView` vs `handoff/LiveTranscript`** — examined as suspected duplicate pairs and cleared. Different components with genuinely different presentations.
- **`src/registry/magicui/`** — a structurally odd second component root, but one real component with one importer. Not duplication.

---

## 18. Corrections

Recording these because several are mistakes I made and caught, and one is a pattern that has now bitten this audit series three times.

1. **I reported "716 design tokens in `:root`" as ground truth in all five briefs. It is wrong.** 716 is the count of *declarations across both* `:root` (399) and `html.dark` (317); the number of distinct token names is **399**, and every family count I gave was correspondingly doubled. The design-token analyst re-derived it and corrected me. The report now uses 399 throughout, and the correction propagated into the verdict and §1–2.

2. **I assumed three independent donut-chart implementations from three filenames.** `billing/ServiceDonut`, `dashboard/BotVsHumanDonut` and `charts/modern-donut` — the first two import the third. `charts/` is a working canonical layer, and it is now cited in §2 as the model. I had explicitly warned the component analyst not to infer duplication from filename similarity, and then did it myself within the hour.

3. **I hypothesised "two competing token systems" — shadcn names versus Atlassian semantic names — and it is false.** `styles.css:415-450` bridges them deliberately and completely. Checked before writing, so it never reached the page, but it is the finding this audit was most likely to get wrong.

4. **I framed the badge family to the component analyst in a leading way**, suggesting `badge`/`lozenge`/`tag`/`SlaPill` might be "four names for one thing." Reading `lozenge.tsx` and `tag.tsx` showed the opposite. I sent a correction mid-run; the analyst had already reached the same conclusion independently.

5. **I nearly published `?? []` at 237 occurrences across 65 files as evidence of the "graceful degradation lie" anti-pattern.** Sampling two sites showed the opposite — `billing.tsx:108-112` and `agent-studio.skills.index.tsx:256-264` handle loading, error and empty correctly, with an `&& !data` stale-data refinement better than `QueryState`'s. I sent that calibration to two analysts. The form analyst then pushed back **with data**: the good ladder exists at only 20 of 88 sites, and 58 have no branch at all. So my first reading was wrong, my second was too generous, and the report states the third. The `?? []` count appears nowhere as a finding.

6. **My grep for `text-text-(success|warning|danger|brand)` was malformed.** In a `className` that is the *correct* form — Tailwind's `text-` prefix plus the `text-success` colour token. Only the `var(--text-text-success)` form is a bug. The bad grep returned 92KB of legitimate matches; the real finding is two sites in `KpiTile.tsx`.

7. **The anchored-pattern failure recurred, and was caught.** The accessibility analyst's first regex for `<div onClick=` returned **0** because prettier splits JSX tags across lines; the true count is 21. It switched to parsing TypeScript ASTs and re-derived everything. This is the third report in this series where a plausible anchored grep produced a confident false negative — in report 21 it reached the page, in 24 I caught an analyst's, and here the analyst caught its own. It should be treated as the default failure mode of this method, not an occasional one.

8. **The same analyst declined to inflate its own headline.** 21 non-interactive elements carry `onClick`; 12 are `e.stopPropagation()` guards on real controls. It reported **9**, and said why. I am recording that because the 21 would have been the more striking number.

9. **Two counts differ between me and an analyst, and neither is wrong.** `Lozenge` adoption: I measured **104** value importers by ripgrep on the named import; the component analyst reported 107, which includes three type-only imports. The report uses 104 and states the method. Dead `var()` references: my probe found **46** sites, the token analyst **44** with a slightly wider exclusion set. Both are stated; the difference is two sites and changes nothing.

10. **Findings were renumbered once, deliberately.** The verdict was drafted before the section order settled and cited `U3` for the webhook gating finding, which had become `U9`, leaving a gap at U3. I renumbered U4–U14 down by one in a single mechanical pass and re-verified every cross-reference in the verdict and the §16 table. Reports 21 and 24 both shipped with body IDs disagreeing with their index; this one was checked after the fact rather than assumed.

11. **Claims I did not independently re-derive, and attribute rather than assert.** The 21-file filter-chip cluster and the byte-identical `KpiCard` pairs (component analyst; I verified the byte-identical `Chip` pair myself by diff, and the 315 and 11 counts by ripgrep). The 88-site query-ladder breakdown (form analyst). The 245-of-355 unlabelled-control count and the 630-button inventory (accessibility analyst, from ASTs). The 6,679 `className` and 684 arbitrary-value counts (styling analyst). Where a number below carries weight I re-ran it; these I did not.

12. **One thing I could not establish.** Colour contrast of the `--text-*` / `--background-*` token pairs was not evaluated by anyone, because it requires rendering and this audit was read-only. For a token set ported wholesale from another design system and then bridged onto a second one, that is a real gap, and it is the obvious next check.

---

## Sources

**Primary — code and configuration read in full or in relevant part**
`Habibi/src/styles.css` (1,849 lines) · `scripts/check-spacing-scale.mjs` · `scripts/check-type-scale.mjs` · `src/lib/utils.ts` · `package.json` · `components.json` · `src/routes/README.md` · `Habibi/AGENTS.md`
`src/components/ui/`: `lozenge.tsx`, `tag.tsx`, `query-state.tsx`, `loading-state.tsx`, `confirm-gate.ts`, `card.tsx`, `form.tsx`, `input.tsx`, `table.tsx`, `button.tsx`
`src/components/`: `records/RecordsTable.tsx`, `records/RecordsTag.tsx`, `consent/ChannelChip.tsx`, `consent/ConsentTable.tsx`, `promises/PaymentPlansTable.tsx`, `promises/FiltersBar.tsx`, `dashboard/KpiTile.tsx`, `dashboard/BotVsHumanDonut.tsx`, `inbox/meta.tsx`, `callbacks/FiltersBar.tsx`, `documents/FiltersBar.tsx`, `charts/modern-donut.tsx`, `billing/ServiceDonut.tsx`
`src/routes/`: `webhooks.tsx`, `billing.tsx`, `dashboard.tsx`, `agent-studio.skills.index.tsx`

**Probes written for this audit** (read-only, in the scratchpad, not in the repository)
`check-var-refs.mjs` — collects every `--x:` definition in `styles.css`, diffs every non-fallback `var(--x)` in `src/**.{ts,tsx}`. Output: 746 definitions, 169 references, 17 undefined names, 51 sites (46 after excluding Radix runtime vars).
`tw.mjs` — reproduces `cn()` against the project's own installed tailwind-merge with `TYPE_PRESETS` copied verbatim from `src/lib/utils.ts`, demonstrating the font-size deletion in U11.

**Commands run** — `node scripts/check-spacing-scale.mjs` (clean, 14 steps), `node scripts/check-type-scale.mjs` (clean, 16 tokens). Both read-only. Nothing was installed, built, served, migrated or tested.

**Analysts** — component, styling, design-token, form/modal/table, accessibility. Each was briefed with verified ground truth and explicit anti-false-positive warnings; each returned file:line evidence. Their claims are marked where I did not re-derive them (correction 11).

**Incident records quoted from the repository itself** — `scripts/check-spacing-scale.mjs:2-21` (the `px-125` → 500px flow-node incident), `scripts/check-type-scale.mjs:2-23` (169 arbitrary font sizes; `text-caption` in 80 places), `src/lib/utils.ts:4-19` (tailwind-merge deleting type presets), `src/components/ui/query-state.tsx:10-27` (the two "graceful degradation lie" incidents), `src/components/flow/FlowNodes.tsx:93-95` (the undefined `var(--danger)` diagnosis), `src/components/inbox/meta.tsx:10-14` (the filled-green WhatsApp pill reading as a success state).
