# Audit trail

- **URL:** `http://localhost:8080/audit`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Immutable interaction/call log.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **High:** **Loading calls** / `0.0s` HUD; Flagged-only counts at 0 without a clear data contract.
- **High:** Auditor needs actor, object, before/after, policy version, recording link — not a spinner.
- **Medium:** No obvious regulator export pack from this page alone (may live under redaction).


## 2. High-value gaps for a next-gen AI collections platform
- One record per action with gate results + score + redaction-ready export.
- Search by account, agent, rule id (RBI-*), time window IST.
- Tamper-evident hash chain indicator.


## 3. Other bugs / issues
- Error state if interactions API fails.
- Deep link from Compliance violations into audit rows.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Extract: Loading calls; LOADING_00=1.
