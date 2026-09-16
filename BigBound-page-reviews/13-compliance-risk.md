# Compliance risk

- **URL:** `http://localhost:8080/compliance`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Rule hits / violations dashboard.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **Medium:** Loading violations then "No violations in scope" — OK if true, but **0% / 100% bot vs human with 0/0** style math is a lie when it appears.
- **Medium:** OPA/Cedar / pack jargon in chrome for compliance users who think in RBI circulars.
- **Low:** Critical/high/medium/low filters good when populated.


## 2. High-value gaps for a next-gen AI collections platform
- Default view: critical/high open exceptions only.
- Map rules to RBI/TRAI language, not engine pack names.
- Hotspot: which script line / agent turn triggered PROH-LANG etc.


## 3. Other bugs / issues
- Ban divide-by-zero percentages.
- Rename policy pack labels for business users; keep technical ids secondary.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Extract: Loading violations || No violations in scope; LOADING_00=1.
## Live API enrichment
- `_api-violations.json`: **116** violations — page must not permanently read as empty/zero.
