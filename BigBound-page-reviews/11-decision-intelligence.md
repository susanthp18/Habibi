# Decision intelligence

- **URL:** `http://localhost:8080/treatment`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Shadow-mode treatment / scoring UI.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **High:** Tabs Insights/Model health/Cases/Holds but first paint **Loading shadow-mode report / scoreboard** style emptiness.
- **High:** Without "why this treatment" artefacts, bank buyers cannot trust autonomy.
- **Medium:** Shadow vs live distinction must be impossible to miss (copy is good when visible).


## 2. High-value gaps for a next-gen AI collections platform
- Hero: policy clause + features + score in ₹ + veto list + override with reason code.
- Challenger promotion gate UI tied to Roles outbound switch.
- Off-policy evaluation charts vs propensity baseline (self-cure trap education).


## 3. Other bugs / issues
- Never show loading forever; show last successful shadow report.
- Export decision record JSON for audit.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Title Decision Intelligence; client loading strings observed in prior/current extracts.
## Live API enrichment
- `_api-treatment-cases.json`: **200** cases (+ insights/metrics/model-health files also dumped).
