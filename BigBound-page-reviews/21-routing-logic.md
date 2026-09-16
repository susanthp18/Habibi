# Routing & logic builder

- **URL:** `http://localhost:8080/routing`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** xyflow rules + simulator.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **Medium:** Active rules 0; editor empty "Select a rule…".
- **Medium:** Fake-precision latency (e.g. 0.31 ms) on empty libraries historically.
- **Low:** Simulator tab exists (good) but not default on cold start.


## 2. High-value gaps for a next-gen AI collections platform
- Simulator-first: paste account → see veto/score/route.
- Diff view on rule publish; audit log of who changed what.
- Throttle / compliance / handoff templates.


## 3. Other bugs / issues
- Cold start: seed 3 read-only example rules.
- Hide latency metrics when n=0.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Title Routing & Logic Builder; tabs Rule editor / Simulator / Audit log from prior review.
## Live API enrichment
- `_api-routing-rules.json`: **8** rules — not an empty engine.
