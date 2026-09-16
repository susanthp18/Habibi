# Call simulation sandbox

- **URL:** `http://localhost:8080/sandbox`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Simulation / Pipecat rehearsal.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **High:** Sales-demo path shows **Loading sandbox** instead of persona picker + start call.
- **High:** Without a 90s happy path to a PTP artefact landing on Workspace/Promises, demos fail.
- **Medium:** No obvious persona library (angry, hardship, DND, vernacular) in first paint.


## 2. High-value gaps for a next-gen AI collections platform
- Scripted HDFC borrower path; equalizer as voice presence.
- Scorecard attachment after sim.
- "Try to break the agent" scenarios matching marketing site promise.


## 3. Other bugs / issues
- Cached offline sim if voice stack down — still show UI.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Title Call Simulation Sandbox; Loading sandbox; LOADING_00=1.
## Live API enrichment
- `_api-sandbox-scenarios.json`: **4** scenarios; runs file nearly empty — UI can at least list scenarios.
