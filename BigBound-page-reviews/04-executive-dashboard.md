# Executive Dashboard

- **URL:** `http://localhost:8080/dashboard`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Exec KPIs; heavy client widgets.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **High:** First paint dominated by **skeletons (14)** / "Loading dashboard" — unacceptable for a page named Executive.
- **High:** No durable KPI story visible in SSR (recovery, cost-to-collect, cure lift vs control).
- **Medium:** Export affordance without visible numbers trains distrust.


## 2. High-value gaps for a next-gen AI collections platform
- Five numbers + why: early-bucket cure lift vs holdout, cost per resolution, consent breaches=0 aspirational with audit link, agency scorecards.
- Drill from KPI → work-item list → call evidence.
- Shadow-mode treatment uplift panel shared with `/treatment`.


## 3. Other bugs / issues
- Prefetch aggregates; never flash 14 gray bars as the exec experience.
- Timezone label IST on every chart.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Title Executive Dashboard; skeletons=14; Loading dashboard string present.
