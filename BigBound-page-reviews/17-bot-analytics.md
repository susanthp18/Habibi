# Conversation & bot analytics

- **URL:** `http://localhost:8080/bot-analytics`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Containment / latency / RAG analytics.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **Medium:** **Loading bot analytics** / `0.0s`.
- **Medium:** 7/30/90d only is weak for India ops (need hour-of-day, language, bucket).
- **Low:** Copy referring to Prompt Studio vs Agent studio naming drift.


## 2. High-value gaps for a next-gen AI collections platform
- Containment, handoff reason, silence, barge-in, language split.
- Tie spikes to routing/version canaries.
- Cost per resolved contact bridge to Billing.


## 3. Other bugs / issues
- Replace loader HUD; show last cached dashboard.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Extract: Loading bot analytics; LOADING_00=1.
