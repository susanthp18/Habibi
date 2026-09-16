# Document fulfilment desk

- **URL:** `http://localhost:8080/documents`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Document request pipeline (NDC, statements, foreclosure, etc.).

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **Medium:** Dense filter toolbar (doc types, channels, Bot/Agent/MCP/Vision) above empty/skeleton data.
- **Medium:** Title spelling mix **Fulfillment** (title) vs **fulfilment** (H1).
- **Medium:** Jargon chips (MCP agent, Vision scan) on a clerk desk UI.
- **Low:** Skeletons on first paint without clear empty CTA.


## 2. High-value gaps for a next-gen AI collections platform
- Request inbox default: what customer asked on call/WhatsApp, SLA to deliver, channel to send.
- Auto-generate NDC/interest cert from CBS with audit stamp.
- Customer self-serve link with consent check.


## 3. Other bugs / issues
- Hide advanced generator modes behind Advanced.
- British/US spelling consistency.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Title Document Fulfillment Desk; H1 Document fulfilment desk; skeletons=6.
## Live API enrichment
- `_api-document-requests.json`: **6** requests.
