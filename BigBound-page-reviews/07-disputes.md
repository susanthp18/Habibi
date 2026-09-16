# Disputes & exceptions

- **URL:** `http://localhost:8080/disputes`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Disputes kanban.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **High:** UI "No disputes" while API has **D-4821 Wrong amount** (Vikram) and **D-SUSANTH-1 Fee waiver** under_review.
- **Medium:** Filters (Bot Voice/Chat, Agent, SLA) with nothing to filter.
- **Medium:** Drag-and-drop promised with empty columns.


## 2. High-value gaps for a next-gen AI collections platform
- Exception intake from live call one-tap.
- SLA-at-risk default for agents; root-cause tags (fee, posting, fraud).
- Link dispute ↔ payment posting evidence from core banking.


## 3. Other bugs / issues
- Bucket by work-items entityType=dispute.
- Show amount + age + assignee on cards.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Extract: No disputes; API work-items include D-4821 and D-SUSANTH-1.
## Live API enrichment
- `_api-disputes.json`: **5** disputes.
- Confirms D-4821 / fee-waiver class work exists server-side while kanban said empty.
