# 30 — Accessibility

**Scope.** The operator console at `Habibi/src`: 365 `.tsx` files, 66,780 lines, 43 routes, 54 primitives in `src/components/ui/`, and the 1,849-line design-token sheet at `src/styles.css`. Target: WCAG 2.1 Level AA, with WCAG 2.2 criteria noted where they apply. The audit is read-only — no repo file was modified, no dependency installed, no server started.

**Method.** Five analysts (semantic HTML, keyboard navigation, forms/validation, ARIA, visual contrast/state) plus a direct thread. Every count in this report is produced by a script over the source, and the technique is stated beside the number; nothing is estimated from a filename or a raw grep total. Every Critical was re-verified by hand against the cited `file:line` before it was written down. Where an analyst and I disagreed, both numbers appear with their methods.

**On tooling.** Neither `eslint-plugin-jsx-a11y` nor `axe-core` is installed, and installing one would have modified `package.json`/`node_modules`, so under the read-only constraint I wrote the checkers instead: a brace- and quote-aware JSX tag scanner, an icon-only-control detector, an overlay classifier, and a WCAG relative-luminance calculator run over the parsed tokens. That is a real limitation and it is stated honestly in *What could not be verified*: static analysis cannot compute an accessible name the way a browser does, and no contrast figure here was read off a rendered pixel.

---

## Verdict

**Habibi's accessible primitives are well built, and the feature surfaces route around them.**

This is not a codebase that is ignorant of accessibility. `src/components/ui/` contains a genuinely careful primitive layer: `button.tsx` sets `aria-busy` and pairs every variant with the design system's `focus-ring`; `loading-state.tsx` is a `role="status"` live region that honours `prefers-reduced-motion` and marks its decorative pixel grid `aria-hidden`; `use-confirm.tsx` builds on Radix AlertDialog and **every one of its 7 call sites passes a real verb label and a consequence description**; `SplitPanes.tsx:153-166` is a textbook `role="separator"` with the full `aria-valuemin/max/now` set, `tabIndex={0}` and arrow-key handling. Positive `tabIndex` appears **zero** times in 474 files. There are **zero** duplicate static `id`s and **zero** dangling `aria-labelledby`/`aria-describedby`/`htmlFor` references.

The defects are not spread evenly over that work. They cluster in one shape: **where a correct in-house primitive exists, a subset of feature surfaces reimplements it by hand and loses everything the primitive was providing.**

| The primitive | Status | Adoption | What the surfaces that skip it lose |
|---|---|---|---|
| `ui/form.tsx` (shadcn + RHF + zod) | correct and complete | **0 importers** | label association, `aria-invalid`, error wiring |
| `ui/sheet.tsx` (Radix Dialog) | correct | 22 overlays use it | focus trap, Escape, `aria-modal`, return-focus — **10 sheets hand-roll it** |
| `ui/input.tsx` (`focus-ring`) | correct | — | visible focus; **147 raw controls bypass it** |
| `ui/section-message.tsx` (`role="alert"`) | correct | **1 importer** | error announcement |
| `focus-ring` utility (`styles.css:1208`) | correct | 51 call sites | 2px/2px-offset indicator; 18 sites strip it |
| `ui/loading-state.tsx`, `ui/button.tsx` | correct | widely used ✅ | — |

The single clearest instance. `src/components/ui/form.tsx` is the stock shadcn implementation and it is right: `FormControl` slots `id`, `aria-describedby` and `aria-invalid` onto whatever it wraps, `FormLabel` sets the matching `htmlFor`, `FormMessage` renders the resolver's error at the id already referenced.

```tsx
// src/components/ui/form.tsx:109-116
<Slot
  ref={ref}
  id={formItemId}
  aria-describedby={!error ? `${formDescriptionId}` : `${formDescriptionId} ${formMessageId}`}
  aria-invalid={!!error}
  {...props}
/>
```

**None of it runs.** `react-hook-form`, `@hookform/resolvers` and `zod` are installed; the only file in `src/` that imports any of them is `form.tsx` itself. `<FormField>`, `<FormControl>`, `<FormItem>` and `<FormMessage>` have zero call sites. There is exactly **one** `<form>` element in the entire product (`floor/Inspector.tsx:282`, a whisper box); every legally consequential form — promise-to-pay, dispute intake, opt-out capture, callback scheduling — is a `<div>` with `useState` and a `<Button onClick>`. Verified independently twice, by the forms analyst's import sweep and by my own.

The measured consequence, across app code excluding `components/ui/`:

| | occurrences |
|---|---|
| `aria-required` | **0** |
| `required` on any control | **0** |
| `aria-errormessage` | **0** |
| `aria-invalid` | 1 |
| `aria-describedby` | 1 |

**295 of 356 form controls have no name source at all.** For 105 of them a visible label is sitting right next to the control in a `<div>` or an unassociated `<Label>` — the screen looks correct and the accessibility tree is empty. That is the characteristic bug of this codebase, and it is worth separating from the other 190, because it means the labels have already been written and only need connecting.

### The two findings that block work outright

Everything above degrades the experience. Three things make a task **impossible** without a mouse, and two of them are the same bug in different features: a state transition whose only trigger is `onDrop`.

**Routing rule priority cannot be changed by keyboard.** `onReorder` has exactly one call site in the codebase — inside the drop handler at `RuleList.tsx:79`. `RuleCard`'s overflow menu offers Edit, Duplicate and Delete, but no Move up or Move down. Rule priority decides which routing rule wins.

**A QA coaching action cannot be advanced by keyboard.** `onMove` is reachable only from the column's `onDrop` (`CoachingBoard.tsx:52-57`); the card is a non-focusable `<div draggable onClick>`; and the click escape hatch does not help, because `openCoachDetail` only raises a toast:

```tsx
// src/routes/qa.tsx:224-227
const openCoachDetail = (id: string) => {
  const a = coaching.find((c) => c.id === id);
  if (a) toast(a.title, { description: `${a.agentId} · ${a.category}` });
};
```

The board's own instruction text — *"drag between columns to update status"* (`CoachingBoard.tsx:36-38`) — documents the mouse-only path as the only path.

This is not a blanket condemnation of drag-and-drop here, and the distinction matters for remediation: **of six drag surfaces, four have a verified keyboard alternative.** Disputes have "Move to" buttons (`DisputeSheet.tsx:484-501`), promises have mark-kept/partial/broken (`PromiseCard.tsx:156,167,178`), leads have a stage stepper (`LeadSheet.tsx:291-303`), callbacks have a datetime input and Reschedule button. Drag is a convenience on those four. On routing and QA coaching it is the only door.

**The live floor cannot be operated by keyboard.** `RecordsTable.tsx:234` renders `<tr onClick>` with no `tabIndex`, `role` or key handler — acceptable if a cell contains a focusable control. In four of its seven consumers, no cell does: `floor/LiveTable.tsx`, `dashboard/AgentLeaderboard.tsx`, `qa/AgentTrendsTable.tsx` and `billing/ServiceCostTable.tsx` render zero buttons and zero links. `LiveTable`'s customer cell is a plain `<span>` (`LiveTable.tsx:55`). Selecting a live call to open the Inspector is the most-used action on the floor, and it is mouse-only.

---

## Findings — Critical

### C1 — The form-accessibility layer the app ships is dead code, and 295 controls have no accessible name
**`src/components/ui/form.tsx` (whole file), 0 importers** · WCAG 1.3.1, 3.3.1, 3.3.2, 4.1.2

Established in the Verdict: the shadcn/react-hook-form/zod stack is installed, correct, and never imported. This is the root cause of the largest single class of defect in the console.

Measured over the 356 form controls in app code (excluding `components/ui/`), by a brace- and quote-aware JSX scanner:

| Control | usages | `aria-label` | `aria-labelledby` | `id=` | no name source |
|---|---|---|---|---|---|
| `<Input>` | 93 | 4 | 0 | 12 | **77** |
| raw `<select>` | 81 | 4 | 0 | 11 | **66** |
| `<SelectTrigger>` | 56 | 0 | 0 | 3 | **53** |
| raw `<input>` | 56 | 2 | 0 | 0 | **54** |
| `<Textarea>` | 20 | 0 | 0 | 2 | **18** |
| `<Checkbox>` | 12 | 4 | 0 | 0 | **8** |
| raw `<textarea>` | 10 | 0 | 0 | 0 | **10** |
| `<Slider>` | 9 | 0 | 0 | 0 | **9** |
| `<Switch>` | 19 | 17 | 2 | 0 | **0** ✅ |
| **Total** | **356** | 31 | 2 | 28 | **295** |

The split that matters for remediation: **105 of the 295 have a visible label already on screen**, sitting in a `<div>` or an unassociated `<Label>` next to the control. The words are written; they are not connected. The other 190 have no visible label found within the scanned window.

The mechanism is a helper cloned into six business forms. Three render a real `<Label>` with no `htmlFor`; three do not reach for `<Label>` at all:

```tsx
// src/components/promises/PromiseSheet.tsx:240-247 — promise-to-pay capture
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-050">
      <Label className="text-body-small font-semibold text-text-subtlest">{label}</Label>
      {children}
    </div>
  );
}
```

Definitions: `promises/PromiseSheet.tsx:240`, `promises/PlanBuilderSheet.tsx:248`, `customer360/ActionSheets.tsx:305` (unassociated `<Label>`); `disputes/DisputeSheet.tsx:509`, `documents/NewRequestSheet.tsx:185`, `documents/RequestSheet.tsx:366` (plain `<div>`). **34 controls** sit inside a `<Field label=…>` this way.

Tabbing the promise sheet, a screen reader announces `edit, blank` … `edit, blank` … `combo box`. "Amount (₹)" and "Promised date" are on screen and in no programmatic relationship with the two boxes into which the operator types a rupee figure and a date.

**Fix.** One change per helper repairs every call site: `const id = React.useId()`, `<Label htmlFor={id}>`, clone the child with that id. Then adopt `FormField`/`FormControl` for the six legally consequential sheets. Nothing needs installing — it is already in `package.json`.

---

### C2 — No skip link, and 33 tab stops stand between the page and its content
**`src/components/shell/AppShell.tsx:8-19`** · WCAG 2.4.1 Bypass Blocks (A)

```tsx
// src/components/shell/AppShell.tsx:9-14
<div className="flex h-screen w-full overflow-hidden bg-surface">
  <Sidebar />
  <div className="flex min-h-0 min-w-0 flex-1 flex-col">
    <TopBar />
    <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
```

A sweep for `skip.?to.?(content|main)` and `href="#main"` across `src/` returns **0 matches**. `<main>` has no `id` and no `tabIndex`.

Tab stops before `<main>` on a desktop viewport, hand-counted from source: `Sidebar.tsx:398` workspace button (1) + `Sidebar.tsx:402` quick-search input (1) + the four nav groups at `Sidebar.tsx:57-104` (4 + 8 + 6 + 8 = **26** router `<Link>`s) + `TopBar.tsx:23,41,53,63,64` (5) = **33**. Collapsing the sidebar does not help: 28 + 5 = 33.

This is the single highest-leverage fix in the report. A keyboard or screen-reader collections agent working a callback queue crosses the entire 26-item product nav on **every route change** before reaching the first row action.

**Fix.** `id="main-content" tabIndex={-1}` on the `<main>` at `AppShell.tsx:14`, and a first-child `<a href="#main-content" className="sr-only focus:not-sr-only">`. One file.

---

### C3 — Customer 360's EMI schedule and payment ledger render as a div grid with zero table semantics
**`src/components/records/FilterTable.tsx:110-155`** · WCAG 1.3.1 Info and Relationships (A)

The scroll wrapper is correct — `role="region"`, `aria-label`, `tabIndex={0}` (`:110-114`). What it contains is not a table:

```tsx
// src/components/records/FilterTable.tsx:117-123, 142-149
<div className="sticky top-0 z-10 grid border-b …" style={{ gridTemplateColumns: gridTemplate }}>
  {columns.map((col) => (
    <span key={col.id} className={col.className}>{col.header}</span>
  ))}
</div>
…
      <div className="grid items-center border-b …" style={{ gridTemplateColumns: gridTemplate }}>
        {columns.map((col) => (
          <div key={col.id} className={col.className}>{col.cell(row)}</div>
        ))}
```

Header cells are bare `<span>`s, body cells bare `<div>`s. Across the whole codebase there are **0** occurrences of `role="table"`, `role="row"`, `role="cell"`, `role="gridcell"`, `role="columnheader"` or `role="rowheader"`.

Call sites: `customer360/EmiTab.tsx:181` (EMI schedule), `customer360/LedgerTab.tsx:152` (payment ledger), `customer360/DocumentsTab.tsx:126`, `callbacks/CallbackList.tsx:210`, `documents/RequestsTable.tsx:333`, `billing/InvoiceList.tsx:79`.

A screen-reader agent on a collections call hears a flat run — "12 Apr 2026 ₹4,200 Paid 15 May 2026 ₹4,200 Overdue…" — with no column association and no row boundary. Reading the ledger back to a borrower *is* the call. The sibling `RecordsTable` in the same directory is a real `<table>`, so the codebase already knows how.

**Fix.** Convert to a real `<table>` (`display:grid` works on `<table>`/`<tr>`), or add the **complete** role set with `aria-rowcount`/`aria-rowindex`. A partial role set is worse than none.

---

### C4 — Four row-click tables have no focusable content in any cell
**`src/components/records/RecordsTable.tsx:234-244`** · WCAG 2.1.1 Keyboard (A), 4.1.2

```tsx
// src/components/records/RecordsTable.tsx:234-244
<tr key={id} data-row-id={id}
    className={cn(…, onRowClick && "cursor-pointer", …)}
    onClick={onRowClick ? () => onRowClick(row) : undefined}
>
```

No `role`, no `tabIndex`, no `onKeyDown`. That is acceptable when a cell renders a focusable control. Scripted across all seven `onRowClick` consumers:

| consumer | `<button>` | `<Link>` | dropdown |
|---|---|---|---|
| `floor/LiveTable.tsx:157` | **0** | **0** | **0** |
| `dashboard/AgentLeaderboard.tsx:137` | **0** | **0** | **0** |
| `qa/AgentTrendsTable.tsx:123` | **0** | **0** | **0** |
| `billing/ServiceCostTable.tsx:198` | **0** | **0** | **0** |
| `webhooks/EndpointTable.tsx:245` | 1 | 1 | 3 |
| `kb/FaqTable.tsx:137` | 1 | 0 | 0 |
| `kb/DocumentsTable.tsx:244` | 2 | 0 | 0 |

`LiveTable`'s identity cell is plain text — `LiveTable.tsx:55`: `<span className="truncate font-semibold text-text">{r.customer}</span>`.

On Floor Command a supervisor watching a live escalating call cannot select the row to open the Inspector without a mouse. It is the most-used action on the screen.

**Fix.** When `onRowClick` is set, wrap the identity cell's content in a `<button type="button">` — the pattern `workspace/AssignedQueue.tsx:218-223` and `kb/DocumentsTable.tsx:185-196` already use.

---

### C5 — Routing rule priority can only be changed by dragging
**`src/components/routing/RuleList.tsx:76-80`** · WCAG 2.1.1 Keyboard (A), 2.5.7 Dragging Movements (AA, 2.2)

```tsx
// src/components/routing/RuleList.tsx:76-80
onDragStart={() => setDragIdx(i)}
onDragOver={(e) => e.preventDefault()}
onDrop={() => {
  if (dragIdx !== null && dragIdx !== i) props.onReorder(dragIdx, i);
  setDragIdx(null);
}}
```

`onReorder` has exactly three references in the codebase and only one is a call: the type at `RuleList.tsx:25`, the prop pass at `routing.tsx:199`, and the invocation at `RuleList.tsx:79` inside `onDrop`. `RuleCard`'s overflow menu (`RuleCard.tsx:97-118`) offers Edit, Duplicate and Delete — no Move up, no Move down. The drag host is a plain div (`RuleCard.tsx:51`).

Rule priority decides which routing rule wins. A keyboard operator cannot change routing precedence at all.

**Fix.** Two `DropdownMenuItem`s calling the existing `onReorder(from, to)`. The menu is already there.

---

### C6 — A QA coaching action cannot be advanced without a mouse
**`src/components/qa/CoachingBoard.tsx:52-57, 79-84`** · WCAG 2.1.1 Keyboard (A), 2.5.7

`onMove` is invoked only from the column's drop handler, and the card is a non-focusable div:

```tsx
// src/components/qa/CoachingBoard.tsx:79-84
<div key={a.id} draggable
     onDragStart={(e) => e.dataTransfer.setData("text/plain", a.id)}
     onClick={() => onOpen(a.id)}
     className="group cursor-pointer rounded-medium border border-border …">
```

The click path is not an escape hatch — it raises a toast and nothing else:

```tsx
// src/routes/qa.tsx:224-227
const openCoachDetail = (id: string) => {
  const a = coaching.find((c) => c.id === id);
  if (a) toast(a.title, { description: `${a.agentId} · ${a.category}` });
};
```

The board's own copy states the constraint: *"Assign actions to agents; drag between columns to update status."* (`CoachingBoard.tsx:36-38`).

**C5 and C6 are the only two of six drag surfaces with no alternative.** Disputes (`DisputeSheet.tsx:484-501`), promises (`PromiseCard.tsx:156,167,178`), leads (`LeadSheet.tsx:291-303`) and callbacks (`CallbackSheet.tsx:316-330`) all have a verified keyboard path; drag is a convenience there. Fix C5 and C6 and drag-and-drop stops being an accessibility problem in this product.

**Fix.** Make the card body a `<button className="w-full text-left">` (drag handlers stay on the wrapper) and add a status control wired to the existing `onMove`.

---

### C7 — Ten modal sheets are hand-rolled divs with no dialog semantics
WCAG 4.1.2 (A), 2.4.3 Focus Order (A), 1.3.1

Confirmed by three independent methods — my overlay classifier, the keyboard analyst's per-file grep matrix, the semantic analyst's AST sweep. The same ten files, and all ten score zero on every dialog affordance:

| | Escape | `role="dialog"` | `aria-modal` | focus trap | focus on open |
|---|---|---|---|---|---|
| all ten | **0** | **0** | **0** | **0** | **0** |

`callbacks/CallbackSheet.tsx:141`, `callbacks/NewCallbackSheet.tsx:115`, `disputes/DisputeSheet.tsx:138`, `disputes/NewDisputeSheet.tsx:68`, `documents/RequestSheet.tsx:75`, `documents/NewRequestSheet.tsx:69`, `qa/NewCoachingSheet.tsx:32`, `qa/RubricBuilderSheet.tsx:66`, `upsell/LeadSheet.tsx:225`, `upsell/NewLeadSheet.tsx:101`.

```tsx
// src/components/disputes/DisputeSheet.tsx:138-140
<div className="fixed inset-0 z-40 flex">
  <button aria-label="Close overlay" onClick={onClose} className="flex-1 bg-black/30" />
  <aside className="flex h-full w-full max-w-[37.5rem] flex-col bg-surface shadow-overlay">
```

The panel is an `<aside>`, so AT announces it as a *complementary landmark*, not a dialog. The whole codebase contains **3** `.focus()` calls (`PromptEditor.tsx:56`, `Sidebar.tsx:384`, `ui/calendar.tsx:149`) — none in any sheet, confirming focus never moves in.

**This is a call-site problem, not a primitive problem.** `src/components/ui/sheet.tsx` is a correct Radix Dialog wrapper and **22 overlays already use it**, getting role, modality, focus trap, Escape and title association for free. Partial credit where it is due: six of the ten make the backdrop a real `<button aria-label="Close overlay">`; four leave it a bare `<div onClick>` (`qa/NewCoachingSheet.tsx:32`, `qa/RubricBuilderSheet.tsx:66`, `upsell/LeadSheet.tsx:225`, `upsell/NewLeadSheet.tsx:101`).

Opening a dispute or a callback does not move focus. The operator tabs through the whole page underneath to reach the sheet's first field, and on close focus is lost. This also undercuts C6's siblings — `LeadSheet`'s stage stepper *is* the keyboard alternative to lead drag, and it lives inside one of these unmanaged overlays.

**Fix.** Port the ten onto `@/components/ui/sheet`. Mechanical, and it resolves L3 as a side effect.

---
### C8 — Twelve CSS custom properties are referenced but never defined, and two of them make a compliance control invisible
**38 references across 16 files** · WCAG 1.4.1, 1.4.3

This is a rendering defect with accessibility consequences, and it is the sharpest finding in the report because it is not only an accessibility problem — the feature is broken for everyone.

Diffing every `var(--x)` in `src/**/*.{ts,tsx}` against every declaration in `styles.css`, twelve are undefined: `--danger`, `--danger-bg`, `--warning`, `--warning-bg`, `--success`, `--success-bg`, `--text-muted`, `--text-primary`, `--brand-navy`, `--brand-primary`, `--text-text-success`, `--text-text-warning`. I re-verified the first ten by hand — **zero definitions each**, against controls (`--text-danger`, `--background-danger-bold`, `--sentiment-neutral`, `--surface`) that all resolve, confirming the check is sound.

Per CSS Variables §3.2 an unresolvable `var()` is invalid-at-computed-value-time, so `background-color` falls to `transparent`, `color` to inherited, `border-left-color` to `currentColor`. The consequences, with ratios computed by the analyst's WCAG calculator (self-tested against reference values: black/white 21.00, `#777`/white 4.4781):

**The compliance severity filter cannot be seen in the on state.** `compliance/ComplianceFilters.tsx:14-19`:

```tsx
const SEV_COLORS: Record<Severity, string> = {
  critical: "bg-[color:var(--danger)] text-white border-transparent",
  high: "bg-[color:var(--warning)] text-white border-transparent",
  medium: "bg-[color:var(--sentiment-neutral)] text-white border-transparent",
  low: "bg-surface-sunken text-text border-border",
};
```

Applied at `:160` when `active`. The background resolves to transparent, so the chip is **white text on `--surface`: 1.00:1** in light theme. The two severities that vanish are `critical` and `high`; `medium` survives only because `--sentiment-neutral` happens to be defined — and it inverts to **1.57:1 in dark**. An operator filtering the violation queue cannot tell which severities are selected.

**A borrower's contact-frequency cap breach has no visual channel at all.** `consent/ChannelChip.tsx:14-23` picks a tone from six undefined tokens, and the label does not disambiguate:

```tsx
const tone =
  cc.status === "opted_in" && !capHit  ? { bg: "var(--success-bg)", fg: "var(--success)" }
  : cc.status === "opted_in" && capHit ? { bg: "var(--warning-bg)", fg: "var(--warning)" }
  …
const label = cc.status === "opted_in" ? `${cc.usedThisWeek}/${cc.frequencyCapPerWeek}` : …
```

Under-cap and at-cap both render the same `4/5` string, and colour was the only differentiator. "This borrower has hit their weekly contact cap" is now invisible to **every** user, sighted or not. Contact-frequency caps are a regulatory control on this platform; an agent dialling past one is a violation.

Two more of the same root cause: `compliance/ComplianceStatsStrip.tsx:18-22` and `consent/ConsentStatsStrip.tsx:19-21` set `border-l-[var(--danger)]` / `border-l-[var(--warning)]`, which fall back to `currentColor` — so the danger tile and the warning tile draw an identical near-black bar (14.34:1 against the tile, highly visible and semantically wrong). And `data/compliance-seed.ts:356-367` `severityColor()` feeds `RuleBreakdown.tsx:57-61`'s progress bar, which therefore renders as an **empty track for critical, high and low**.

**The codebase already diagnosed this and fixed one file.** `flow/FlowNodes.tsx:93-96`:

> `// border-danger / border-warning, not var(--danger) / var(--warning): those two are used across the codebase but are not defined anywhere in styles.css, so they resolve to nothing and the error state — the whole point of this border — would silently not render.`

The note was written, applied once, and never propagated to the other fifteen files.

**Fix.** Either define the twelve as aliases in `styles.css`, or sweep the 38 references onto the tokens that exist (`critical: "bg-background-danger-bold text-text-inverse"` measures 5.16 in both themes; `high: "bg-background-warning-bold text-text-warning-inverse"` measures 9.14/8.18). A lint rule that fails the build on an undefined `var(--…)` would have caught all sixteen files.

---

## Findings — High

### H1 — Filtered-out rows are `aria-hidden` and still keyboard-focusable, with live action buttons inside
**`src/components/records/FilterTable.tsx:131-140`** · WCAG 4.1.2 (A), 2.4.3

```tsx
// src/components/records/FilterTable.tsx:131-140
<div
  className="grid transition-[grid-template-rows,opacity] duration-300"
  style={{
    gridTemplateRows: shown ? "1fr" : "0fr",
    opacity: shown ? 1 : 0,
  }}
  aria-hidden={!shown}
>
```

The collapse is `grid-template-rows: 0fr` + `overflow-hidden` — **not** `display:none`. Descendants stay in the DOM and stay tabbable while `aria-hidden` removes them from the accessibility tree: the textbook "focusable element inside `aria-hidden`" condition, which Chrome logs and axe flags.

Those rows contain real actions. `callbacks/CallbackList.tsx:182-200` renders `title="Open detail"` and `title="Cancel"` buttons per row; `documents/RequestsTable.tsx:277-305` renders `Generate` / `Retry` / `Open`.

**Blast radius: 31 `FilterTable` call sites** — call audit, invoice history, consent registry, EMI schedule, account ledger, document requests. An operator filtering the consent registry to "DND" then tabs into invisible rows belonging to revoked-consent customers, hears nothing, and can fire *Cancel* against a callback that is not on screen. In a regulated collections context that is a compliance event, not a UX nit.

**Fix.** `shown ? row : null`, or add `visibility: hidden` at the end of the transition so focus cannot enter.

---

### H2 — A global Space handler hijacks activation for every control in the call-audit drawer
**`src/components/audit/AudioPlayer.tsx:60-69`** · WCAG 2.1.1 (A), 2.1.4 Character Key Shortcuts (A)

```tsx
useEffect(() => {
  const handler = (e: KeyboardEvent) => {
    if (e.code === "Space") {
      e.preventDefault();
      onPlayPause();
    }
  };
  window.addEventListener("keydown", handler);
  return () => window.removeEventListener("keydown", handler);
}, [onPlayPause]);
```

No target-tag guard, no focus scoping. `AudioPlayer` is mounted inside `audit/CallDetailDrawer.tsx:156`, whose subtree holds six Radix `TabsTrigger`s (`:178-188`) and two Buttons (`:141`, `:147`). `preventDefault()` on Space suppresses native button and tab activation throughout.

The same file's sibling gets this exactly right — `Sidebar.tsx:379-382` checks `INPUT`/`TEXTAREA`/`isContentEditable` and modifier keys before firing. Reviewing a recorded call is the compliance-audit path, and on it Space stops pressing buttons.

**Fix.** Copy the `Sidebar` guard, and scope the listener to the drawer element rather than `window`.

---

### H3 — The consent and compliance editors are hand-rolled native controls with `<div>` labels
**`consent/ChannelMatrix.tsx:49`, `consent/AllowedHoursEditor.tsx:55,69`, `consent/ConsentDrawer.tsx:171-210`, `compliance/ComplianceFilters.tsx:62-111`** · WCAG 1.3.1, 3.3.2, 4.1.2

A specific instance of C1, called out separately because it is the surface with the most regulatory exposure. **147 raw `<select>`/`<input>`/`<textarea>` bypass the `ui/` primitives** (81/56/10 — a figure my scan and the forms analyst's produced independently and identically), and **129 of them have neither an `id` nor an `aria-label`**.

The consent matrix, which decides whether a borrower may be contacted on a channel:

```tsx
// src/components/consent/ChannelMatrix.tsx:46-52
<div className="inline-flex items-center gap-075 text-body-small font-medium text-text">
  <Icon className="h-3.5 w-3.5 text-text-subtle" /> {label}
</div>
<select
  value={c.status}
  onChange={(e) => update(key, { status: e.target.value as ConsentStatus })}
  className="h-7 rounded-medium border border-border bg-surface px-100 text-body-small"
>
```

The channel name ("SMS", "Voice", "WhatsApp") is in a sibling `<div>`, associated with nothing. A screen-reader operator changing consent cannot tell which channel's row they are on.

The calling-window editor is the same shape — "Start" and "End" at `AllowedHoursEditor.tsx:53,67` are `<div className="mb-050 text-body-small text-text-subtlest">`. The RBI Fair Practices Code restricts collections calls to 08:00–19:00; this is the control that sets it.

`ComplianceFilters.tsx` has five consecutive bare `<select>`s (`:62,75,88,98,111`) with no label of any kind. `audit/AuditFilters.tsx:44,59,74,86,103,120` has six `<SelectTrigger>`s in a row with no label and no `aria-label`, so AT reads "Today, combobox / All, combobox / All, combobox…" on the regulated call-audit screen.

**Fix.** These are native elements, so `<Label htmlFor>` is a one-line change each — no Radix involvement needed.

---

### H4 — Only seven live regions exist, and the ones that matter most are missing or inert
WCAG 4.1.3 Status Messages (AA)

The entire 66,780-line frontend contains **7** live-region sites: `aria-live` ×3 (`inbox/ChatThread.tsx:18`, `sandbox/TuningStudio.tsx:235`, `ui/loading-state.tsx:88`), `role="status"` ×3 (`ui/loading-state.tsx:87`, `ui/spinner.tsx:33`, `routes/inbox.tsx:343`), `role="alert"` ×1 (`ui/section-message.tsx:51`). Meanwhile **40 files render `isPending`/`isError` query states** and 39 of them have no live region of their own.

Four distinct defects:

**(a) The live call transcript is silent.** `handoff/LiveTranscript.tsx` takes a `streaming: boolean`, auto-scrolls on every new turn (`:18-22`), and contains **zero** `aria-live`, `role="status"` or `role="log"` — verified by grep returning 0. An operator on a live collections call gets no announcement of what the bot or the borrower just said. `sandbox/ConversationPanel.tsx` is the same.

**(b) Load failures are never announced.** `ui/query-state.tsx` routes its pending branch through `LoadingState` (`role="status"`), so "Loading connectors" is spoken — then, on failure, that region *unmounts* and is replaced by a plain `<div>` with no role. The polite region announces the load starting and then goes silent forever. The file's own docstring names two shipped incidents where an empty state was rendered from a network error and calls that the codebase's "#1 failure mode"; the error message it so carefully writes is the one thing a screen reader never hears. `treatment.lazy.tsx`'s `StateGate` has the identical shape.

**(c) Two live regions can never fire.** `sandbox/TuningStudio.tsx:234-240` wraps a permanently-present "Applied" text node in `aria-live="polite"` and animates only `opacity` — a live region fires on *content mutation*, and nothing mutates, so mid-call tuning confirmation is never announced. `inbox/ChatThread.tsx:16-19` puts `aria-label="Bot is typing"` on a live region, but a live region announces its *content*, which is three animated empty `<span>` dots.

**(d) Skeleton loading announces nothing.** `routes/dashboard.tsx:121` sets `aria-busy="true" aria-label="Loading dashboard"` on a bare `<div>` — `aria-busy` is meaningful on a live region or widget, and `aria-label` on a role-less `div` is not exposed at all. Same at `routes/handoff.lazy.tsx:203`. `ui/skeleton.tsx` adds no ARIA.

**Not a defect, checked:** sonner's `<Toaster>` ships its own polite live region (verified in `node_modules/sonner/dist/index.mjs`), so toast *text* is announced. The problem is what gets routed through it — see H5.

**Fix.** `role="log" aria-live="polite" aria-relevant="additions"` on `LiveTranscript`'s always-mounted scroll container; give `QueryState`'s error branch the existing `SectionMessage` (which already carries `role="alert"`); move the conditional inside the live region for (c); wrap skeletons the way `LoadingState` already does.

---

### H5 — Validation errors are transient toasts, never attached to a field, and focus never moves
WCAG 3.3.1 (A), 3.3.3 (AA), 4.1.3

385 `toast.*` calls carry field validation:

```tsx
// src/components/disputes/DisputeSheet.tsx:115,125
toast.error("Resolution notes are required");
toast.error("Reason is required to reject");
```

Also `documents/NewRequestSheet.tsx:42,46`, `callbacks/NewCallbackSheet.tsx:87`, `disputes/NewDisputeSheet.tsx:43`. The text is announced, but the message is never associated with the offending control (`aria-describedby` occurs **once** in app code), focus stays on the submit button, nothing is marked `aria-invalid`, and the toast auto-dismisses — so an operator who tabs away loses the only record of the error.

A dispute resolution is refused, the operator hears "Resolution notes are required" once, and must then hunt for which of four unlabelled textareas it meant.

**Fix.** Inline `FormMessage` (or a `role="alert"` node referenced by the control's `aria-describedby`), set `aria-invalid`, and `focus()` the first invalid control. Keep toasts for server failures.

---

### H6 — 75 state-gated disabled buttons give no perceivable reason, and the repo already documents the fix
WCAG 1.3.1, 3.3.1, 3.3.3

Of 284 app-code `<Button>`s, **75** carry a `disabled={…}` gated on form state (pure `busy`/`isPending` excluded as legitimately transient). Of those, **0** have `aria-disabled` and **0** have `aria-describedby`.

```tsx
// src/components/consent/ConsentDrawer.tsx:203-209 — opt-out capture
<Button size="sm" variant="outline" className="h-400"
  disabled={!optNote.trim()}
  onClick={captureOptOut}>
  <Ban className="mr-050 h-3.5 w-3.5" /> Log opt-out
</Button>
```

The greyed button is the only signal that a note is mandatory, and `disabled` removes it from the tab order — so a keyboard operator never reaches it to discover the requirement exists.

What makes this a departure rather than an oversight: `routes/agent-studio.index.tsx:130-175` already solves it and explains why.

> `// So a blocked action here is not `disabled`. It is `aria-disabled`, which keeps it hoverable and focusable, dims it the same way, ignores the click, and — through `aria-describedby` onto an off-screen sentence — reaches a screen reader, which `title` alone does not and never does on keyboard focus.`

**Fix.** Promote that `ReasonedAction` pattern out of `agent-studio.index.tsx` into `components/ui/` and apply it to the 75.

---

### H7 — 25 icon-only controls have no accessible name, including "rotate signing secret" and two delete actions
WCAG 4.1.2 (A)

Two independent detectors agreed closely: mine found **23 of 657** button-like elements (3.5%) that are genuinely icon-only and unnamed; the ARIA analyst, using a wider population (adding `ToggleGroupItem`/`TabsTrigger`, and hand-rejecting 6 false positives from 89 candidates), found **25 of 83 true icon-only controls (30.1%)**. The difference is denominator, not disagreement — see *Analyst disagreements*.

The worst cluster is five in one drawer, three of them identical:

```tsx
// src/components/webhooks/EndpointDrawer.tsx:302-313
<Button size="sm" variant="ghost" onClick={() => setRevealSecret((v) => !v)}>
  {revealSecret ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
</Button>
<Button size="sm" variant="ghost" onClick={() => copy(endpoint.secret, "Secret")}>
  <Copy className="h-3.5 w-3.5" />
</Button>
<Button size="sm" variant="ghost" onClick={() => onRotate(endpoint)}>
  <KeyRound className="h-3.5 w-3.5" />
</Button>
```

Announced as "button, button, button". One of them **rotates the webhook signing secret**, which breaks every downstream receiver until they re-key.

Other unnamed business actions: delete a QA rubric criterion (`qa/RubricBuilderSheet.tsx:125,173`), delete a custom header (`webhooks/EndpointSheet.tsx:311`), remove a routing condition (`routing/ConditionRow.tsx:101`), the row overflow menus for a routing rule and a webhook endpoint (`routing/RuleCard.tsx:98`, `webhooks/EndpointTable.tsx:197`), seek back/forward on the call recording (`audit/AudioPlayer.tsx:74,85`), previous/next week (`callbacks/WeekCalendar.tsx:72,78`), and eight unnamed **Close** buttons.

The gap is inconsistency rather than ignorance: `RuleCard.tsx:91` gives the *adjacent* Switch a template-literal `aria-label={\`Enable rule ${rule.name}\`}`, and the overflow menu six lines below gets nothing. Note too that 23 of the 58 labelled controls rely on `title` alone — that computes a name but is the weakest fallback and invisible to touch users.

**Fix.** `aria-label` on each of the 25.

---

### H8 — Hover and selection are the same colour in the bulk-action table
**`src/components/records/RecordsTable.tsx:237-241`** · WCAG 1.4.11, 1.4.1

```tsx
className={cn(
  "group/row bg-surface transition-colors hover:bg-background-brand-subtlest",
  isSelected && "bg-background-selected",
  onRowClick && "cursor-pointer",
```

`--background-selected` and `--background-brand-subtlest` are **the same hex in both themes** (`#e9f2fe` light, `#1c2b42` dark). Computed: hover vs surface 1.13/1.14, selected vs surface 1.13/1.14, **hover vs selected 1.00/1.00**.

This is the table bulk actions run against. An operator cannot confirm which accounts are selected before acting on them — and per C4 the row exposes no selection state to AT either.

**Fix.** Keep hover on `--background-neutral-subtle-hovered` and give selected a non-colour cue: `border-l-2 border-border-selected` measures 5.20/5.91.

---

### H9 — Four routes have no `<h1>`, including the live-call takeover screen
WCAG 1.3.1 (A), 2.4.6 (AA)

Resolving each route's transitive import graph and intersecting with the heading index (so a `0` is a proven absence, not an unscanned file):

| route | h1 | h2 | h3 |
|---|---|---|---|
| `handoff.tsx` / `handoff.lazy.tsx` | **0** | 0 | 0 |
| `inbox.tsx` | **0** | 2 | 0 |
| `floor.tsx` | **0** | 1 | 0 |
| `agent-studio.skills.$skillId.tsx` | **0** | 0 | 0 |

These are page titles demoted to divs, not missing content — `handoff/CallHeader.tsx:55-56` renders the escalated call's customer name in a `<div className="truncate text-body font-semibold text-text">`, and `agent-studio.skills.$skillId.tsx:174` renders the skill slug in a `<div className="font-mono heading-medium font-semibold">`. Its own sibling `agent-studio.skills.index.tsx:156` does it correctly with an `<h1>` carrying the same class.

The handoff screen is where an agent takes over a live escalated call from the bot; a screen-reader user landing there gets no announced page identity and no `h`-key entry point. SPA route-change announcements lean on the h1.

**Fix.** Four tag swaps. The type scale is orthogonal to the tag, so no styling changes.

---

### H10 — `RecordsTable`'s carefully written scroll-region label is silently discarded on 24 screens
**`src/components/records/RecordsTable.tsx:137-140`** · WCAG 4.1.2, 1.3.1

```tsx
<div
  className="records-scroll min-h-0 flex-1 overflow-auto focus-visible:outline-none"
  tabIndex={0}
  aria-label={`${ariaLabel}. Scroll horizontally and vertically to view all columns and records.`}
>
```

`aria-label` on a `role`-less `<div>` is not exposed — a generic element takes no accessible name. The label is thoughtful and goes nowhere, and the element is a tab stop that announces as nothing. Its sibling `FilterTable.tsx:110-114` uses the identical pattern *with* `role="region"` and works.

**24 `<RecordsTable>` call sites** — assigned queue, customer list, audit call log, consent register, floor live table, webhooks, KB documents.

**Fix.** Add `role="region"` at `:137`. One line, 24 screens.

---

### H11 — Twenty-one `<aside>` landmarks and the primary `<nav>` have no accessible names
WCAG 1.3.1 (A), 2.4.1

Landmark census: `<main>` 1 (unnamed), `<nav>` 4 (2 named — both `ui/` primitives), `<aside>` 21 (**0 named**), `<header>` 20, `<section>` 39, `<footer>` 1.

The two that matter are the shell's own: `Sidebar.tsx:391` `<aside>` and `Sidebar.tsx:406` `<nav>`, both unnamed. On `/sandbox` a screen-reader user's landmark list reads "complementary, complementary, complementary" with no way to tell the scenario list from the inspector from the tuning studio (`sandbox/ScenarioList.tsx:28`, `InspectorPanel.tsx:78`, `TuningStudio.tsx:179`). With no skip link (C2), landmarks are the only bypass mechanism, and they carry no information.

**Deliberately not reported:** the 20 `<header>`s all render inside `AppShell`'s `<main>`, so per HTML-AAM they map to `generic`, not `banner` — there is exactly one banner (`TopBar.tsx:19`) and it is correct. The 39 unnamed `<section>`s likewise map to `generic`, not `region`, and are harmless.

**Fix.** `aria-label` on each `<aside>`; make `Sidebar.tsx:391` `<nav aria-label="Primary">` and drop the redundant inner `<nav>`.

---

### H12 — A hand-rolled tablist promises arrow-key navigation it does not implement
**`src/components/workspace/AssignedQueue.tsx:307-338, 358-363`** · WCAG 2.1.1, 4.1.2

```tsx
<div className="flex gap-075 overflow-x-auto" role="tablist" aria-label="Queue tabs">
  {visibleTabs.map((t) => (
    <button type="button" role="tab" aria-selected={isActive}
      id={`queue-tab-${t.key}`} aria-controls="queue-tabpanel"
      onClick={() => setActive(t.key)}>
```

The roles, ids, `aria-controls` and the panel's `aria-labelledby` are all wired correctly — this is the most carefully built ARIA in the codebase. But there is no roving `tabIndex` and no `onKeyDown`. Once `role="tab"` is claimed, AT tells the user "tab, 1 of 5, use arrow keys", and arrow keys do nothing. **Wrong ARIA is worse than none**: this is a promise the widget does not keep. The `role="tabpanel"` at `:361` also lacks `tabIndex={0}`, so a panel with no focusable content is unreachable.

`src/components/ui/tabs.tsx` is a Radix wrapper used correctly by six other files.

**Fix.** Swap in `@/components/ui/tabs`.

---

### H13 — The push-to-talk control has no keyboard activation
**`src/components/sandbox/ConversationPanel.tsx:430-444`** · WCAG 2.1.1 (A)

```tsx
<button type="button"
  onMouseDown={(e) => { e.preventDefault(); void holdStart(); }}
  onMouseUp={() => void holdEnd()}
  onMouseLeave={() => void holdEnd()}
  onPointerUp={() => void holdEnd()}
  onTouchStart={(e) => { e.preventDefault(); void holdStart(); }}
  disabled={micBusy}
```

It is a real `<button>` so it takes focus, but there is no `onClick` and no `onKeyDown` — Enter and Space do nothing. Mic input in the sandbox simulator is unusable by keyboard.

**Fix.** Add `onKeyDown`/`onKeyUp` for Space/Enter, or a click-to-toggle mode.

---

### H14 — The window splitter reports an impossible value range
**`src/components/inbox/SplitPanes.tsx:157-159`** · WCAG 4.1.2 (A)

```tsx
aria-valuemin={Math.round(minWidthsPx[i] ?? 160)}
aria-valuemax={100 - Math.round(minWidthsPx[i + 1] ?? 160)}
aria-valuenow={Math.round(widths[i])}
```

`minWidthsPx` is pixels — the drag code at `:79-80` divides it by `totalPx` to convert, which proves the unit — while `widths` is a percentage. With the Inbox call site `minWidthsPx={[240, 420, 280]}` (`routes/inbox.tsx:390`), the first separator reports **valuemin=240, valuemax=−320, valuenow≈24**: minimum above maximum, current value outside both. Screen readers derive a percentage from these and produce nonsense.

Also at `flow/FlowCanvas.tsx:1051`, `customers.$customerId.lazy.tsx:304`, `sandbox.lazy.tsx:582`.

I initially recorded this component as the repo's reference implementation on the strength of its structure; that was wrong on the numbers and is corrected here and in *Corrections made during verification*.

**Fix.** Convert to percentages using the same arithmetic the drag handler already performs, or drop the three value attributes — a splitter is valid without them.

---

### H15 — Compliance violation trend lines are separated by hue alone, at 1.00–1.21:1
**`src/components/compliance/ViolationTrendChart.tsx:5-8`** · WCAG 1.4.1

```tsx
{ id: "critical", label: "Critical", color: "#e2483d", key: "critical" as const },
{ id: "high",     label: "High",     color: "#e06c00", key: "high"     as const },
{ id: "medium",   label: "Medium",   color: "#b38600", key: "medium"   as const },
{ id: "low",      label: "Low",      color: "#7d818a", key: "low"      as const },
```

Computed pairwise: high vs medium **1.00** (identical luminance), critical vs low **1.03**, critical vs high 1.21, medium vs low 1.18. Orange-vs-yellow at 1.00:1 and red-vs-grey at 1.03:1 are precisely the pairs a protanope or deuteranope cannot separate, and no dash pattern or marker distinguishes the series. The legend (`:29`) is a dot plus text, so 1.4.1 is met for the *key* — but not for the lines themselves. Being literal hex, the values also never remap under `.dark`.

More broadly, no chart in the app has a text alternative: `charts/modern-donut.tsx:54` has `role="img" aria-label="Distribution chart"` (correct mechanics, a category rather than an alternative), `charts/liveline-trend.tsx:142` and `handoff/SentimentMeter.tsx:81` have no ARIA at all.

**Fix.** Vary luminance across the series and add `strokeDasharray`; give each chart either `aria-hidden` plus an adjacent `sr-only` data summary, or `role="img"` with a label stating the actual figures.

---

### H16 — Status, priority and SLA are carried by a 6px `aria-hidden` dot
WCAG 1.4.1 (A)

```tsx
// src/components/disputes/DisputeCard.tsx:69-72
<span className={cn("h-1.5 w-1.5 rounded-full", priorityDot[d.priority])} aria-hidden />
<div className="truncate text-body font-semibold text-text">{d.customerName}</div>
```

Nothing else on the card states priority, so *urgent* is invisible to a screen reader by construction and to a colour-blind operator by hue. Same at `upsell/LeadCard.tsx:33-37,66-69`.

`inbox/ConversationList.tsx:191-197` is the sharpest case: **one 6px dot encodes eight meanings** — five thread states plus three SLA levels — disambiguated only by a `title=` attribute, which is mouse-hover only. SLA breach, escalation and "needs human" are the triage signals an agent scans all day. `floor/PriorityLane.tsx:22-26` encodes live-call severity 1/2/3 with a border colour that appears nowhere as text.

**Counter-examples that get it right and must not be "fixed":** `ui/SlaPill.tsx:27-35` (dot *plus* text inside a bordered Lozenge), `ui/lozenge.tsx:18-26` (background + text + border on every tone, documented as deliberately never fill-only), `customer360/ContactabilityPill.tsx:141-165`, `dashboard/CallVolumeChart.tsx:31-43`.

**Fix.** Pair each dot with a text or `sr-only` label — the `SlaPill` pattern already in the codebase.

---
## Findings — Medium

**M1 — `<Button loading>` deletes its own accessible name.** `ui/button.tsx:84-97` wraps children in `<span className={cn(loading && "invisible", "contents")}>`. Tailwind `invisible` is `visibility:hidden`, which removes the label from the accessibility tree — while `ui/spinner.tsx:33-34` renders `role="status" aria-label="Loading"` *inside* the button. The name flips from "Publish version 12" to "Loading", and a live region ends up nested inside an interactive control. 6 call sites (`agent-studio.index.tsx:165,316,536`, `knowledge-base.lazy.tsx:685,722,735`). Fix: `aria-hidden` the spinner (`aria-busy` already carries the state) and use `opacity-0` instead of `invisible`. WCAG 4.1.2.

**M2 — `role="alert"` fires unconditionally, including on informational banners.** `ui/section-message.tsx:51` sets `role="alert"` for every variant. `alert` is *assertive* — it interrupts whatever the user is reading — and it fires on every SPA route transition that mounts an `information` message. 7 call sites. Fix: `role={variant === "error" || variant === "warning" ? "alert" : "status"}`, and no live role when the message is static page furniture. WCAG 4.1.3.

**M3 — No `aria-sort` anywhere, on two sortable tables.** `grep -c aria-sort src` → **0**. Both `records/RecordsTable.tsx:183-199` and `prompt-studio/VoiceCatalogTable.tsx:198-210` convey sort state through a rotating `<ArrowDown>` glyph only (correctly `aria-hidden` in the latter). Fix: `aria-sort={active ? (dir === 1 ? "ascending" : "descending") : "none"}` on the `<th>`. WCAG 1.3.1.

**M4 — Heading levels skip h1 → h3 on the executive dashboard and billing.** `dashboard.tsx` has its `h1` at `dashboard/FiltersBar.tsx:33` then jumps to `h3` at `AgentLeaderboard.tsx:127` and `AtRiskAccounts.tsx:28`; `billing.tsx` has `h1` at `BillingHeader.tsx:37` then five `h3`s. These are top-level panels under the page title and should be `h2`; classNames need no change. WCAG 1.3.1.

**M5 — The same panel-title class is a heading in 27 places and a plain div in 39.** Exact-className match on the four canonical panel-title strings: 27 on `h1`–`h6`, 39 on `div`/`span`/`p` across 33 files. `routes/redaction.tsx` contains both, at `:217` (`<h1>`) and `:285` (`<div className="text-body font-semibold text-text">Transcript preview</div>`). The heading list a screen-reader user pulls up is roughly 40% incomplete, and which panels appear is arbitrary. About 8 of the 39 are empty-state or error text and correctly *not* headings — those were checked individually and excluded. WCAG 1.3.1, 2.4.6.

**M6 — The sidebar is div soup: 26 links, no list, group labels not headings.** `shell/Sidebar.tsx:185-268` renders four group labels as `<div>`s and 26 `<Link>`s in nested `<div>`s. This is an outlier, not a house style — the codebase has 89 `<ul>`/`<ol>` across 63 files and 106 `<li>`, and `shell/NotificationsPopover.tsx:166-175` does `<ul>` + `<li>` + `<button>` correctly. AT announces no item count and no group boundaries, compounding C2's 26-stop gauntlet. WCAG 1.3.1.

**M7 — The virtualised catalog sets no `aria-rowcount`/`aria-rowindex`.** `prompt-studio/VoiceCatalogTable.tsx` windows rows with `@tanstack/react-virtual` and spacer rows (`:282-287`); `aria-rowcount`, `aria-rowindex`, `aria-colcount` and `aria-colindex` occur **0** times in the codebase. AT announces "row 4 of 22" while the catalog holds hundreds. Credit where due: this file is otherwise the best table work in the repo — a real `<table>`, a `<colgroup>`, and the only `scope="col"` attributes in the codebase. Fix: `aria-rowcount={sorted.length + 1}` and `aria-rowindex={row.index + 2}`. WCAG 1.3.1.

**M8 — A single-select control is exposed as three independent toggles.** `workspace/AvailabilityToggle.tsx:87-94` uses `role="group"` + `aria-pressed` for Available / Busy / Offline, which are mutually exclusive — nothing conveys that picking one clears the others, and it gates whether calls route to this agent. The codebase has the right pattern twice already (`prompt-studio/ScrubField.tsx:158`, `flow/FlowInspector.tsx:124` use `radiogroup`/`radio`/`aria-checked`). Sub-finding: `FlowInspector.tsx:123-124`'s `role="radiogroup"` has no accessible name, and neither radiogroup implements arrow keys. WCAG 4.1.2.

**M9 — Brand-tinted action buttons lose their label on hover (light theme).** `text-text-brand` on `background-brand-subtlest` measures 4.60 at rest but **3.92 on hover** and **3.15 on pressed**, against a 4.5 requirement. Sites: `qa/RubricScorer.tsx:101` (accept AI suggestion on the QA scorecard), `bot-analytics/UnansweredTable.tsx:159,180`, `workspace/AssignedQueue.tsx:219` and `NeedsAttention.tsx:149` (the "Open" button on the assigned work queue). Fix: pair the hover with `hover:text-text-information-bolder` (9.53). WCAG 1.4.3.

**M10 — Primary, danger and discovery button labels drop to ~4.0:1 on hover in dark theme.** `ui/button.tsx:25,31,33,36`: primary 5.20 → **4.00**, danger 5.16 → **4.02**, discovery 5.20 → **3.93**. Light mode improves on hover; dark mode's `-bold-hovered` ramp brightens *toward* the white label instead of away from it. Eight further call sites re-implement the pattern by hand. Fix: in `.dark`, remap `--background-brand-bold-hovered` downward — today's `-pressed` value measures 6.66. WCAG 1.4.3, dark theme only.

**M11 — `--border` at 1.35:1 is the only boundary on interactive controls, across 544 call sites.** `--border: #0b120e24` over `--surface` measures **1.35 light / 1.41 dark** against SC 1.4.11's 3:1. Decorative card outlines are exempt; these are not: `ui/button.tsx:23` (`default` variant's only edge), `:38` (`outline` variant), `ui/badge.tsx:20` (the only thing making a badge a badge), `ui/table.tsx:59` (the only row separator), and the outer edge of every floating surface (`dialog.tsx:47,84`, `select.tsx:71`, `dropdown-menu.tsx:49,66`, `hover-card.tsx:19`, `menubar.tsx:85`). The system already ships a token that passes — `--border-bold: #7d818a` measures **3.90/5.70**, and `--border-input` 3.24/3.93. Fix: keep `--border` for decorative dividers, move interactive boundaries to `--border-bold`. WCAG 1.4.11.

**M12 — Hover and selection on the base table are background-only shifts at 1.13:1.** `ui/table.tsx:59` changes only the background for both hover and `data-[state=selected]`, with no border, text or icon change. Same pattern in `input.tsx:11`, `textarea.tsx:10`, `select.tsx:22`. WCAG 1.4.11, 1.4.1.

**M13 — Slider thumb and track boundaries fall below 3:1.** `ui/slider.tsx:15-18`: thumb `border-primary/50` vs `bg-background` measures **2.14 light / 1.69 dark**; track `bg-primary/20` measures 1.33/1.20. The thumb is white-on-white with a faint rim, separated only by a shadow. Fix: `border-border-selected` (5.20/5.91) on the thumb. WCAG 1.4.11.

**M14 — Eighteen inputs replace the 2px focus ring with a 1px border-colour change, and five remove it entirely.** The design system's recipe is at `styles.css:1205-1214` (`outline: 2px solid var(--border-focused); outline-offset: 2px`) and is used at 51 sites. Five controls strip it with nothing put back — `ui/command.tsx:47` (the command-palette search box), `shell/Sidebar.tsx:357`, `floor/CallTile.tsx:188`, `prompt-studio/ScrubField.tsx:125`, `records/RecordsTable.tsx:138`. Thirteen more downgrade to `focus:outline-none … focus:border-border-brand` — a colour swap on an already-present 1px border. My coarser scan independently flagged 19 of these 18. The Sidebar case is the sharpest: the `/` shortcut deliberately *sends* focus to an input that then shows no focus state. **The ring itself is sound** — because of `outline-offset: 2px` the adjacent colour is the page, so `--border-focused` measures 3.50 light / 5.91 dark and passes 1.4.11, and 2px satisfies WCAG 2.2 SC 2.4.13. WCAG 2.4.7.

**M15 — Four modal backdrops are close-buttons implemented as unfocusable divs.** `qa/NewCoachingSheet.tsx:32`, `qa/RubricBuilderSheet.tsx:66`, `upsell/LeadSheet.tsx:225`, `upsell/NewLeadSheet.tsx:101`. The other six hand-rolled sheets do this correctly — `disputes/DisputeSheet.tsx:139` uses `<button aria-label="Close overlay">`. Each of the four does have a separate X button, so close is reachable; the backdrop itself is not. WCAG 2.1.1.

**M16 — The audio scrub bar and sentiment timeline are pointer-only seek surfaces.** `audit/AudioPlayer.tsx:95` (`<div onClick>`) and `audit/SentimentTimeline.tsx:52` (`<svg onClick>`) both compute the seek target from `e.clientX`, with no `tabIndex`, `role` or key handler. Partially mitigated by the ±10s skip buttons at `AudioPlayer.tsx:100-106` — but reaching 40:00 in a long call takes ~240 keypresses. `prompt-studio/ScrubField.tsx:64-99` already implements the correct `role="slider"` pattern in this codebase. WCAG 2.1.1.

**M17 — Two clickable cards have no keyboard path.** `routing/RuleCard.tsx:51-64` makes an entire routing rule card a `<div draggable onClick={onSelect}>` with no `role`, `tabIndex` or focus style; `qa/CoachingBoard.tsx:79-84` is the same. `role="button"` appears **0** times in `src/`, and all 5 `tabIndex` uses are on `role="region"` scroll containers, never on an activation target. WCAG 2.1.1, 4.1.2.

## Findings — Low

**L1 — `role="link"` + `aria-disabled` on the breadcrumb current page.** `ui/breadcrumb.tsx:54-62` announces "link, current page, dimmed" for a non-focusable `<span>` that does nothing when activated — telling the user an action exists that does not. `aria-current="page"` alone is the APG pattern. This is hand-written code in the repo, not Radix.

**L2 — A focusable `role="slider"` nests inside a `<label>` for a different control.** `prompt-studio/ScrubField.tsx:50` opens a `<label>` containing both the slider span (`:64-76`, `tabIndex={0}`) and the `<input>` it labels (`:115-124`): one value, two tab stops, and clicking the slider forwards a label click into the text input mid-drag. Fix: make the wrapper a `<div>`.

**L3 — Six icon-only `<button>`s sit inside the hand-rolled sheets.** `qa/NewCoachingSheet.tsx:44`, `qa/RubricBuilderSheet.tsx:78,125,173`, `upsell/LeadSheet.tsx:245`, `upsell/NewLeadSheet.tsx:113` — a subset of H7, listed separately because porting those files to the Sheet primitive (C7) resolves them for free.

**L4 — Lozenge borders fall under 3:1 against their own fill in light theme** — success 2.70, warning 2.66, discovery 2.95. Marginal, and every tone's border passes against the *page* (3.33–5.20), so the pill's outer shape always reads, and every label passes comfortably (8.12–9.53). The Lozenge is the strongest component in the system; graded Low accordingly.

**L5 — Five decorative `<svg>`s lack `aria-hidden`** — `charts/liveline-trend.tsx:142`, `liveline-spark.tsx:32`, `handoff/SentimentMeter.tsx:81`, `audit/SentimentTimeline.tsx:52`, plus two in `Sidebar.tsx` that are already inside labelled parents. There are **0** `<img>` elements in the codebase, so there is no alt-text debt at all.

**L6 — Two chart-tooltip font sizes bypass the type scale in raw px** — `styles.css:1767-1779` (10.5px, 11.5px), the only two font sizes in the app off the token scale, and they render money values. Being px rather than rem they still scale under zoom, so SC 1.4.4 is met. Related note: `text-body-micro` is 10px and used at 34 sites including money labels — rem-based and conformant, but small for numeric data. **Zero** arbitrary `text-[Npx]` utilities exist anywhere; the type scale is genuinely enforced.

**L7 — No `<table>` has a `<caption>` or an accessible name, and 100 of 102 `<th>`/`TableHead` have no `scope`.** Graded Low because browsers auto-compute column-header scope for simple single-header-row tables and all twelve hand-rolled tables here are simple. The naming gap is sharper: in Customer 360 four tables in a row all announce as "table". `TableCaption` exists in the primitive (`ui/table.tsx:102`) with zero call sites. Fix: default `scope="col"` in `TableHead`; add `aria-labelledby` on each `<table>` pointing at its panel heading.

**L8 — Dialog footers reverse visual order against DOM order below the `sm` breakpoint.** `ui/dialog.tsx:84`, `ui/sheet.tsx:81`, `ui/alert-dialog.tsx:53` use `flex-col-reverse … sm:flex-row`, so tab order (Cancel → Confirm) inverts against reading order on narrow viewports. Stock shadcn, and desktop operators are unaffected. These three are the **only** `flex-*-reverse`/`order-N` occurrences in `src/`, so tab-vs-visual order is otherwise clean.

**L9 — The `/` shortcut is undocumented and cannot be disabled or remapped.** `Sidebar.tsx:377-386`'s typing guard is correct, but WCAG 2.1.4 additionally requires that a single-character shortcut can be turned off, remapped, or made active-on-focus-only. `shell/HelpPopover.tsx:76-82` documents only `⌘K`/`Ctrl+K`, and a search for "Keyboard shortcuts" returns 0 files.

**L10 — No `prefers-contrast` or `forced-colors` story.** Zero occurrences in `src/`. Not an AA conformance failure, but it is the missing third mode beside light and dark, and Windows High Contrast users are a meaningful share of an enterprise operator population.

---


---

## Risk by operator capability

Ranked by what a collections operator cannot do, not by defect count. "Blocked" means there is no path at all; "Unusable" means the path exists but conveys nothing to assistive technology.

| Capability | Surface | Keyboard | Screen reader | Low vision | Worst finding |
|---|---|---|---|---|---|
| **Read a borrower's ledger / EMI schedule** | `customer360/LedgerTab.tsx:152`, `EmiTab.tsx:181` | OK | **Unusable** — flat text run, no row or column association | OK | C3 |
| **Record an opt-out / change consent** | `consent/ConsentDrawer.tsx:171-210`, `ChannelMatrix.tsx:49` | OK | **Unusable** — channel and source selects unnamed; verbatim field placeholder-only | **Blind spot** — cap breach has no visual channel | C1, C8, H3 |
| **See that a contact-frequency cap is hit** | `consent/ChannelChip.tsx:14-23` | — | **Invisible** — same label both states | **Invisible** — undefined token | C8 |
| **Set a calling window (RBI 08:00–19:00)** | `consent/AllowedHoursEditor.tsx:55,69` | OK | **Unusable** — "Start"/"End" are `<div>`s | OK | C1, H3 |
| **Triage the compliance violation queue** | `compliance/ComplianceFilters.tsx:14-19,62-111` | OK | **Unusable** — 5 unnamed selects | **Blocked** — active critical/high filter renders at 1.00:1 | C8, C1 |
| **Judge violation severity at a glance** | `compliance/ComplianceStatsStrip.tsx:18-22`, `RuleBreakdown.tsx:57-61` | OK | partial | **Blocked** — danger and warning accents identical; severity bar empty | C8 |
| **Work the live floor** | `floor/LiveTable.tsx:157` via `RecordsTable.tsx:234` | **Blocked** — no focusable cell | **Blocked** — `<tr onClick>` exposes no role | hover vs selected 1.00:1 | C4, H8 |
| **Change routing rule precedence** | `routing/RuleList.tsx:76-80` | **Blocked** — drag only | **Blocked** | OK | C5 |
| **Advance a QA coaching action** | `qa/CoachingBoard.tsx:52-57,79-84` | **Blocked** — drag only | **Blocked** — card not focusable | OK | C6 |
| **Record a promise to pay** | `promises/PromiseSheet.tsx:132-160` | OK | **Unusable** — amount and date announce as `edit, blank` | OK | C1 |
| **Resolve a dispute** | `disputes/DisputeSheet.tsx:138,509` | OK (Move-to buttons) | **Unusable** — no dialog role, fields labelled by `<div>` | OK | C7, C1 |
| **Schedule / reschedule a callback** | `callbacks/CallbackSheet.tsx:141` | OK | **Unusable** — no dialog role, focus never enters | OK | C7 |
| **Cancel a callback you filtered away** | `records/FilterTable.tsx:131-140` + `callbacks/CallbackList.tsx:190-201` | **Hazard** — hidden rows keep focusable buttons | **Hazard** — `aria-hidden` + focusable | OK | H1 |
| **Review a recorded call for compliance** | `audit/AudioPlayer.tsx:60-69,93-95` | **Degraded** — Space hijacked; seek is pointer-only | no slider role | OK | H2, M16 |
| **Rotate a webhook signing secret** | `webhooks/EndpointDrawer.tsx:302-313` | OK | **Unusable** — three adjacent unnamed icon buttons | OK | H7 |
| **Select accounts for a bulk action** | `records/RecordsTable.tsx:237-241` | **Blocked** (C4) | no state exposed | **Blocked** — hover and selected are the same colour | H8 |
| **Take over an escalated live call** | `routes/handoff.lazy.tsx` | OK | **Degraded** — no `<h1>`, page has no announced identity | OK | H9 |
| **Read any chart** | `compliance/ViolationTrendChart.tsx:5-8`, `charts/` | OK | **Unusable** — no text alternative | **Degraded** — series 1.00–1.21:1 apart | H15 |
| **Reach page content at all** | `shell/AppShell.tsx:14` | **Degraded** — 33 tab stops per route change | no landmark names | OK | C2, H11 |

Three capabilities are outright **blocked** for a keyboard-only operator: the live floor, routing precedence, and QA coaching. Two are blocked for a low-vision operator: compliance severity filtering and bulk-selection state. The consent surface is the worst overall — it is unusable by screen reader *and* has an invisible compliance signal, and it is the surface with the most direct regulatory exposure under the RBI Fair Practices Code and the DPDP Act.

---

## What is done well

Recorded so a remediation pass does not regress it. Several of these are better than what a typical React console ships.

**The token system is the best-executed part of the product.** A scripted diff of `:root` against `html.dark` found **314 literal-hex colour tokens in each, 0 missing, 0 orphans** — no token silently inherits its light value. Every semantic text token passes AA on both page surfaces in both themes: `--text` 14.34/10.47, `--text-subtle` 7.81/7.08, `--text-brand` 5.20/7.99, `--text-danger` 6.53/7.77. All ten Tag hues pass both text (5.93–7.81 / 7.08–10.64) and border. **Zero** arbitrary `text-[Npx]` utilities exist anywhere — the type scale is genuinely enforced.

**`prefers-reduced-motion` is handled globally and the one gap is handled by hand.** `styles.css:1842-1849` kills `animation-duration`/`transition-duration` on `*, *::before, *::after`; two brand marks *opt in* behind `no-preference` rather than relying on the override. The one animation the CSS blanket cannot reach — the View Transitions theme toggle, since `::view-transition-*` is outside the `*` tree — is guarded in JS at `registry/magicui/animated-theme-toggler.tsx:222-228`.

**Switch, checkbox and radio are exemplary.** `ui/switch.tsx:40-47` renders a `Check` and an `X` glyph in the uncovered track segment, so state never depends on colour: three channels (glyph, thumb travel, track fill). The file also enforces `aria-label` in the type system — and it shows: **19 `<Switch>` usages, 17 `aria-label` + 2 `aria-labelledby` = 100% named**, the only control class in the app with full coverage.

**`use-confirm.tsx` is the model for destructive actions.** Built on Radix AlertDialog, and every one of its 7 call sites passes a real verb and a consequence rather than "Confirm" — `confirmLabel: "Allow out-of-hours demo"` / `cancelLabel: "Keep hours enforced"` (`platform/OutboundControlPanel.tsx:66-67`), `"Take over anyway"` (`routes/inbox.tsx`), `"Rotate"` (`routes/webhooks.tsx:247`). The `?? "Confirm"` fallback is never exercised. `window.confirm` survives only in comments explaining its removal.

**`prompt-studio/ScrubField.tsx:64-99` is the reference implementation** for a custom widget in this repo: `role="slider"`, the full value set, `tabIndex={disabled ? -1 : 0}`, arrow keys with a Shift×10 multiplier alongside the pointer drag, and a comment at `:66-68` explaining why it *omits* `aria-valuemin` rather than announce "Infinity" — a judgement call most codebases get wrong.

`inbox/SplitPanes.tsx:153-166` has the same care and one bug: `role="separator"`, `aria-orientation`, `tabIndex={0}`, `onKeyDown` and `focus-ring` are all correct, but its three value attributes mix units (H14). Structure right, numbers wrong.

**The `/` shortcut is guarded correctly** — `Sidebar.tsx:377-386` checks `INPUT`/`TEXTAREA`/`isContentEditable` and modifier keys before firing. This is the model `AudioPlayer` should have followed (H2). Sidebar hover state also pairs every `onMouseEnter` with an `onFocus`/`onBlur` twin (`Sidebar.tsx:225-229`).

**Hygiene that is frequently wrong elsewhere and is right here.** Positive `tabIndex`: **0**. `tabIndex={-1}`: **0**. `preventDefault` on Tab: **0** — there are no keyboard traps anywhere in the product, so WCAG 2.1.2 has no violations. Duplicate static `id`s: **0**. Dangling `aria-labelledby`/`aria-describedby`/`htmlFor` references: **0**. `<html lang="en">` is set at `routes/__root.tsx:147`. `<img>` elements: **0**, so there is no alt-text debt.

**`ui/query-state.tsx` refuses to lie about failure** — its docstring names two shipped incidents where an empty state was rendered from a network error and gives business advice from it, and the component makes that mistake structurally unreachable. The design instinct is right; the gap (H4) is only that the error branch it so carefully writes is not announced.

**`agent-studio.index.tsx:130-175` already solves the disabled-button problem**, with a comment explaining exactly why `aria-disabled` + `aria-describedby` beats `disabled` + `title`. The pattern is correct and needs promoting to `components/ui/`, not inventing.

**Sonner's `<Toaster>` ships its own polite live region** — verified in `node_modules/sonner/dist/index.mjs` (`aria-live: "polite"`, `aria-atomic`). Toast *text* is announced; the defect in H4 is what gets routed through it, not the toast mechanism.

**lucide-react auto-injects `aria-hidden` on decorative icons** — verified in the library source. All **688** icon instances are handled; only 28 set it explicitly. Reporting 660 "missing `aria-hidden`" would have been noise, and this report does not.

---

## Remediation

Ordered by operator harm relieved per unit of work. Items 1–6 are each a single file.

### Immediate — unblock and un-break

1. **Add the skip link.** `id="main-content" tabIndex={-1}` on `AppShell.tsx:14`, plus a `sr-only focus:not-sr-only` anchor as the shell's first child. Removes 33 tab stops from every route change. (C2)
2. **Sweep the twelve undefined CSS variables**, starting with `ComplianceFilters.tsx:14-19` and `ChannelChip.tsx:14-23`. Two of the 38 references make a regulatory signal invisible to everyone. Add a lint rule that fails the build on an undefined `var(--…)`. (C8)
3. **Add `role="region"` to `RecordsTable.tsx:137`.** One line; restores a carefully written label on 24 screens. (H10)
4. **Give the QA coaching card a status control and a `<button>` body**, and add Move up / Move down to the routing rule menu. Both call handlers that already exist. These are the only two capabilities in the product with no keyboard path. (C5, C6)
5. **Stop `FilterTable` collapsing rows into an `aria-hidden` tab trap** — render `shown ? row : null`. 31 call sites; today an operator can fire *Cancel* on a callback that is not on screen. (H1)
6. **Guard the `AudioPlayer` Space handler** with the tag check `Sidebar.tsx:379-382` already uses, and scope it to the drawer. (H2)

### Near-term — the labelling debt

7. **Fix the six `Field` helpers** with `React.useId()` + `htmlFor`. Six edits, 34 controls, and it is the pattern the whole app copies. (C1)
8. **Label the consent and compliance controls by hand first** — `ChannelMatrix.tsx:49`, `AllowedHoursEditor.tsx:55,69`, `ConsentDrawer.tsx:177,188,200`, `ComplianceFilters.tsx:62-111`, `AuditFilters.tsx:44-120`. These are native elements; `<Label htmlFor>` is a one-line change each, and they are the surfaces with regulatory exposure. (H3)
9. **`aria-label` the 25 icon-only controls**, starting with the webhook secret trio and the two delete actions. (H7)
10. **Wrap in-cell row actions in a `<button>`** for the four row-click tables with no focusable cell. (C4)
11. **Add the four missing `<h1>`s** — four tag swaps, no styling change. (H9)
12. **`aria-label` the 21 `<aside>` landmarks** and name the primary `<nav>`. (H11)

### Structural — stop the divergence recurring

13. **Port the ten hand-rolled sheets onto `ui/sheet.tsx`.** Resolves C7, M15 and L3 together, and is mechanical.
14. **Adopt `ui/form.tsx` for the six legally consequential forms** — promise-to-pay, dispute intake, opt-out capture, callback scheduling, document request, waiver. Nothing needs installing. (C1, H5)
15. **Give `FilterTable` real table semantics**, or convert it to a `<table>` with `display:grid`. (C3)
16. **Add the missing live regions**: `role="log"` on `LiveTranscript`, `SectionMessage` on `QueryState`'s error branch, a `role="status"` wrapper on the dashboard and handoff skeletons, and fix the two regions that can never fire. (H4)
17. **Promote `ReasonedAction` from `agent-studio.index.tsx:130-175` into `components/ui/`** and apply it to the 75 state-gated disabled buttons. The pattern and its rationale are already written. (H6)
18. **Swap `AssignedQueue`'s hand-rolled tablist for `ui/tabs.tsx`** and `AvailabilityToggle`'s toggle group for a radiogroup. (H12, M8)
19. **Move interactive boundaries from `--border` to `--border-bold`** (1.35 → 3.90) and fix the two dark-theme hover ramps. (M11, M10, M9)
20. **Add `eslint-plugin-jsx-a11y` to the lint script.** It would have caught H1, H7, M17, L1 and much of C1 mechanically. `package.json` already runs two custom design-system checks in `lint`, so the harness exists.
21. **Add an axe-core pass over the 33 screens in CI.** Everything in *What could not be verified* below is settled by one such run.

### One item for a different report

`compliance/ComplianceFilters.tsx`, `ChannelChip.tsx`, `ComplianceStatsStrip.tsx` and `RuleBreakdown.tsx` are shipping **broken rendering**, not merely inaccessible rendering — the severity bar draws empty and the frequency-cap state does not display. That belongs in a correctness report as well as this one.

---

## Analyst disagreements, resolved

**Icon-only unlabelled controls: 23 vs 25 vs 6.** Three counts, three populations, no contradiction. My detector examined 657 `<button>`/`<Button>`/trigger elements and found **23** whose body is exclusively self-closing icon elements. The ARIA analyst examined a wider set (adding `ToggleGroupItem`/`TabsTrigger`, resolving lucide imports per file), found 89 candidates, hand-rejected 6 false positives, and reported **25 of 83 true icon-only controls (30.1%)**. The semantic analyst counted only raw lowercase `<button>` and found **6**. All three are correct for what they measured; 25 is the figure to act on. My own count is a known undercount — a ternary whose arms are both icons (`EndpointDrawer.tsx:302`) leaves the identifier behind after stripping and escapes the filter, which is exactly how I missed the reveal-secret button.

**Form controls without a name: 295 vs 276.** The forms analyst's 295-of-356 counts named-ness by attribute. The ARIA analyst's 276-of-318 (86.8%) used a different denominator and flagged its own high false-positive risk, because it cannot detect a control implicitly named by a wrapping `<label>`. The ARIA analyst accordingly rested its finding on the 43 orphaned `<Label>`s and 6 hand-read `AuditFilters` triggers rather than the 276. I have used 295 and stated the 105/190 split, which is the number remediation can act on.

**`<aside>` count: 21 vs 22.** The semantic analyst's AST walk found 21; my regex-based tag scanner found 22. The difference is one occurrence my scanner attributed to a file where the AST resolves it differently. Immaterial to the finding (0 are named either way); the AST figure is the more reliable and is used above.

**`outline-none` without a replacement: 5 vs 19.** The keyboard analyst classified 48 occurrences into 11 correct Radix menu-item patterns, 2 non-interactive chart layers, 17 already paired with a ring, 13 downgraded to a border-colour swap, and 5 with no indicator at all. My coarser rule — which did not treat `focus:border-*` as a replacement — flagged 19, i.e. the 13 + 5 + one boundary case. The classified breakdown is the useful one and is what M14 reports.

**Whether the `default` button variant's low contrast is a finding.** It reads like one: `ui/button.tsx:20-22` carries a comment saying Design.md explicitly forbids "fixing" the contrast. Computed, it is **7.81 light / 7.08 dark** — comfortably past AA and AAA. The deliberate de-emphasis costs 7.81 against `--text`'s 14.34, which is a real design trade-off and not a conformance issue. **Not reported.** The actual defect in that same class string is the 1.35:1 border (M11).

---

## Corrections made during verification

**My first scanner under-counted everything and produced three false positives.** A prop whose value is JSX (`actions={<div>…</div>}`) caused the tokenizer to consume nested elements as part of the *outer* tag's attribute text, hiding them entirely and mis-attributing their attributes upward. That is how `htmlFor="cases-open-only"` came back "dangling" when `<Switch id="cases-open-only">` sits nine lines below it at `treatment.lazy.tsx:941`. Rewritten to stop the attribute region at the first nested element and resume after the tag name; re-run, the dangling count is **0**.

**"182 buttons with no accessible name" was wrong.** The corrected scanner produced it by stripping `{…}` expressions and then finding no literal text — which flags every `<Button>{PRIORITY_LABELS[p]}</Button>` and `<Button>{children}</Button>` in the app. Sampling 25 of the 182 showed nearly all were labelled by an expression. Replaced with a detector that asks the narrower question — is the body *exclusively* self-closing icon elements — giving 23 of 657, and cross-checked against the ARIA analyst's independent 25.

**The one duplicate `id` was a false positive.** `id="ob-pool"` appears twice in `prompt-studio/OutboundCardEditor.tsx` (`:280`, `:305`), but they are the two arms of a `poolNames.length > 0 ? <select> : <Input>` ternary; only one mounts. The ARIA analyst independently flagged and independently rejected the same hit. The codebase has **no** duplicate-ID instance.

**I praised `SplitPanes` as the repo's reference implementation before checking its numbers.** Its structure is right, but `aria-valuemin` is in pixels while `aria-valuenow` is a percentage, so the Inbox splitter reports min 240, max −320, now 24 (H14). "What is done well" now names `ScrubField` as the reference and records `SplitPanes` with its bug.

**I nearly reported the default button's contrast as a finding** on the strength of its source comment, before computing it. See *Analyst disagreements*.

**The contrast analyst withdrew four of its own findings during source review** — three were ternary arms or opacity modifiers the first pass merged into one class list (`text-brand` on `background-brand-bold` at a spurious 1.00:1; `text-subtle` on `background-brand-bold`; `text-subtlest` on `background-danger-subtler`, where the hover swaps *both* colours), and one (`--border-focused` at 1.33–2.23 against bold fills) was neutralised by `outline-offset: 2px` putting page background on both sides of the ring. Its scanner was fixed to split template literals on `${…}` and re-run.

**660 icons were not reported.** `lucide-react@0.575.0` auto-injects `aria-hidden` when an icon has no children and no a11y prop, verified in the library source. Only 28 of the 688 icon instances set it explicitly; reporting the other 660 would have been noise.

---

## What could not be verified

This audit is static, and five things genuinely need a running browser. An `axe-core` pass over the 33 screens would settle all of them in one run — and is remediation item 21 for exactly that reason.

1. **Computed accessible names.** Static analysis cannot resolve what a browser computes. The 295-control figure in C1 is an attribute-level count; some controls may inherit a name from an ancestor or a wrapping `<label>` that the scanners cannot trace across component boundaries. The direction is certain; the exact number is not.
2. **Whether focus actually enters the `aria-hidden` subtree in H1.** `grid-template-rows: 0fr` + `overflow-hidden` *should* leave descendants focusable, unlike `display:none`, but browsers differ on zero-size focusables. Chrome logs a specific warning when it happens — a 30-second tab test confirms or dismisses this finding.
3. **Undefined-`var()` fallback behaviour in C8.** The CSS spec makes this invalid-at-computed-value-time, and I am confident of `background-color` → `transparent`, `color` → inherit, `border-left-color` → `currentColor`. A single screenshot of `/compliance` with the *critical* filter active would settle it visually.
4. **Runtime heading and focus order.** Per-route heading analysis is import-reachability, so a `0` is a proven absence but DOM order is not proven. `treatment.lazy.tsx` has an `h2` at line 181 above an `h1` at line 279; reading the components suggests the rendered order is correct, and it is **not** reported as a finding.
5. **Radix's return-focus on the 22 correct overlays**, and whether Radix's portal `aria-hidden` on sibling nodes silences the toast container while a sheet is open — which would make H5's toasts inaudible exactly when they fire.

Two further limits worth stating plainly. **Compositing:** the 27 alpha tokens were composited over a named backdrop, usually `--surface`; where a translucent token nests two deep the true ratio is slightly lower than reported. `--border` at 1.35 does not survive any correction, but L4's marginal 2.66–3.02 Lozenge borders could move either way. And **no contrast figure here was read off a rendered pixel** — every ratio is computed from parsed tokens by a calculator self-tested against published reference values (black/white 21.00, `#777` on white 4.4781, `#00f` on white 8.5925).

Finally, this audit covers WCAG 2.1 AA with WCAG 2.2 criteria noted where they arose (2.4.13 Focus Appearance, 2.5.7 Dragging Movements). It does not cover screen-magnifier behaviour, reflow at 320px, cognitive-load criteria, or any assessment against the Rights of Persons with Disabilities Act 2016, which a regulated Indian financial platform may separately need.
