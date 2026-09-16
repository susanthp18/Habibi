# Billing & usage

- **URL:** `http://localhost:8080/billing`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Usage meters Prod/Sandbox.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **Medium:** **Loading billing data** / `0.0s`.
- **Medium:** MTD/7/30/90 toggles without numbers.
- **Low:** FX × list price copy needs visible assumptions.


## 2. High-value gaps for a next-gen AI collections platform
- Cost per resolved contact; per-tenant caps; voice minute vs resolution pricing bridge (align to marketing site).
- Alerts before budget burn.


## 3. Other bugs / issues
- CFO export CSV.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Extract: Loading billing data; LOADING_00=1.
