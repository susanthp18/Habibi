# Webhooks & event subscriptions

- **URL:** `http://localhost:8080/webhooks`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Outbound event subscriptions.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **Medium:** **Loading webhooks** / sparse SSR body — empty state not designed.
- **Medium:** Missing visible signed-secret / replay / dead-letter affordances in first paint.


## 2. High-value gaps for a next-gen AI collections platform
- Signed webhooks, retry/DLQ, replay for auditors.
- Event catalog aligned to work-item lifecycle (PTP broken, consent changed…).


## 3. Other bugs / issues
- Show example payload drawer.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Title Webhooks & Event Subscriptions; Loading-style emptiness.
