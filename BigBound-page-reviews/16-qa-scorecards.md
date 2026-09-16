# QA scorecards & coaching

- **URL:** `http://localhost:8080/qa`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** QA queue AI draft vs final.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **Medium:** "No calls match these filters" with duplicate All/all style filters.
- **Medium:** QA as homework queue instead of score-on-the-call.
- **Low:** Watch for leftover "seed" copy in metrics (seen in earlier pass).


## 2. High-value gaps for a next-gen AI collections platform
- Live barge when score drifts; coaching clips from real turns.
- Calibration variance across reviewers made visible.
- Auto-fail on hard disclosure misses.


## 3. Other bugs / issues
- Dedupe filter controls.
- Link each scorecard to Audit + Handoff recording.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Extract: No calls match these filters.
## Live API enrichment
- `_api-scorecards.json`: **52** scorecard rows.
