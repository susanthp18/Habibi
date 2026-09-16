# Floor Command

- **URL:** `http://localhost:8080/floor`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Live ops wallboard; client fetch.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **High:** Stuck on **Loading floor** with `0.0s` HUD rather than occupancy mosaic or "floor is quiet" empty.
- **High:** No visible agent cells, SLA heat, or barge targets in first successful HTML snapshot.
- **Medium:** Duplicate Activity icon vs Bot analytics in sidebar confuses IA.


## 2. High-value gaps for a next-gen AI collections platform
- True wallboard: who’s in-call, wrapping, about to breach; click-to-listen/whisper.
- Heat by bucket/language/team for India floors.
- Silent-listen compliance recording indicator.


## 3. Other bugs / issues
- Replace stopwatch loader with skeleton cards shaped like agent tiles.
- After N seconds, show error/retry, never infinite Loading.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Title Floor Command — Live Ops; EMPTY/LOAD contains Loading floor; LOADING_00=1.
## Live API enrichment
- `_api-floor.json` present with keys calls/alerts/stats/agents — **agents=10, calls=13, alerts=40**.
- UI still showed Loading floor in SSR — **Critical wiring gap**, not lack of backend floor data.
