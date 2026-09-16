# Upsell & leads manager

- **URL:** `http://localhost:8080/upsell`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Lead pipeline kanban.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **High:** UI empty / 0-of-0 while API has leads (Deepa Iyer contacted ₹600k; Anita qualified/interested).
- **High:** Upsell adjacent to collections without hard suitability gate in UI — RFP risk.
- **Medium:** "Loading offer engine health…" historically sticky.
- **Medium:** Sentiment chips on a collections floor need policy framing.


## 2. High-value gaps for a next-gen AI collections platform
- Separate motion visually from collections; eligibility veto before pitch.
- Next-best-offer with explain + decline reasons.
- Convert lead → account treatment with audit.


## 3. Other bugs / issues
- Wire stages to work-items entityType=lead.
- Hide from pure collector role shells.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- nextLead Deepa Iyer in workspace summary; LD-* in work-items; page title Upsell & Leads Manager.
## Live API enrichment
- `_api-leads.json`: **22** leads (large payload).
