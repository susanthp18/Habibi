# Shell / navigation (cross-cutting)

- **URL:** all authenticated product routes under `http://localhost:8080/`
- **Reviewed:** 2026-09-12 IST
- **Stack notes:** `AppShell`, `Sidebar`, `TopBar` shared by every module.


## Cross-cutting (applies to this page's shell)
- **Critical — identity not in chrome:** API knows Priya Nair; many pages still greet/act as anonymous ("there") or show no avatar/user menu.
- **High — 26-item sidebar for every role:** agent, floor, compliance, builder, billing share one nav. Duplicate Activity icon (Floor vs Bot analytics).
- **High — loading/absence collapse:** skeletons, zeros, and `Loading … 0.0s` often indistinguishable from true empty; API failure and empty render the same.
- **Medium — Windows chords:** topbar shows ⌘K; machine is Windows (should be Ctrl+K). Duplicate search (sidebar Quick search + topbar).
- **Medium — tenant hardcode:** "HDFC · Loans & Insurance" in sidebar; fine for demo, wrong for multi-tenant.


## 1. UI/UX issues, bugs, inconsistencies, staleness
- **Critical:** No role-based information architecture. Collectors see Agent studio, Webhooks, Billing.
- **High:** Two collapse-sidebar controls (logo cluster + topbar chevrons).
- **High:** Notifications bell has no unread badge path tied to breached SLAs (API has 8 breach timers for Priya).
- **Medium:** Footer still shows product version chrome (`BigBound · v0.1` historically) while selling enterprise OS.
- **Medium:** British/US spelling mix across modules (fulfilment vs Fulfillment).
- **Low:** Equalizer mark animation with no `prefers-reduced-motion` callout in shell.

## 2. High-value gaps for a next-gen AI collections platform
- Role shells: **Agent / Floor / Compliance / Builder / Admin** with different default homes.
- Global **contactability atom** (DND + RBI window + frequency) on every customer chip.
- Command palette that **enacts** work (PTP, DND, handoff), not only search.
- Shift-aware availability auto Wrap-up after hours / weekends.

## 3. Other bugs / issues
- Silent product 404s for settings/profile; login exists but app still usable without auth gate on other routes (OIDC still "Phase 5" historically).
- `/prompt-studio` redirect exists — keep nav and copy aligned with Agent studio.

## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
