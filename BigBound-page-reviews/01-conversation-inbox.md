# Conversation Inbox

- **URL:** `http://localhost:8080/inbox`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Client-heavy live operations surface; depends on inbox list API.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **Critical:** `GET http://127.0.0.1:8000/inbox` returns **404** `{{"detail":"Not Found"}}` while nav advertises Conversation inbox as Live ops #2.
- **High:** SSR/HTML shows **Loading conversations** / `0.0s`-style loading HUD — not a designed empty, not an error with retry.
- **High:** Without inbox, agents cannot triage voice/chat/WhatsApp in one place — the product’s promised multi-channel OS collapses.
- **Medium:** No visible channel filters / SLA / contactability in first paint because data never arrives.


## 2. High-value gaps for a next-gen AI collections platform
- Unified conversation object: channel, consent lock, SLA fuse, last decision reason, deep link to Customer 360 + Handoff.
- AI triage: suggested disposition, hardship detection, auto-priority by uplift×exposure not FIFO.
- Realtime presence of bot vs human ownership per thread.


## 3. Other bugs / issues
- Distinguish network/404 error from empty inbox (retry + link to API health).
- Remove debug elapsed `0.0s` from production chrome.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Route HTTP 200 for `/inbox` page shell; backend inbox endpoint 404 in this review.
## Live API enrichment (2026-09-12, after patient dump)
- `GET /inbox` still **404**, but **`_api-conversations.json` has 23 conversations**.
- Includes live WhatsApp thread for **Susanth** with PTP pay links (ngrok), travel-insurance RAG misses, agent takeover, `contactableNow:false`.
- `4` conversations in needs_human/escalated; `1` marked isMine for Priya.
- **Implication:** Inbox UI is wired to the wrong/missing path — data exists under conversations.
