# Callback & scheduling manager

- **URL:** `http://localhost:8080/callbacks`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Calendar + list for callbacks.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **High:** API lists multiple **missed** callbacks for Priya (Sameer 7:30 AM, Arjun 9:30, Kavya **5:30 AM IST**, Susanth WhatsApp confirm, etc.) while UI historically showed empty week — verify calendar binding to work-items.
- **High:** 5:30 AM IST slots vs RBI/permitted windows — dangerous if dialable.
- **Medium:** Filter chip overload (reason, status, channel, DND-safe, team…).
- **Medium:** DND-safe as a chip rather than a hard lock.


## 2. High-value gaps for a next-gen AI collections platform
- Calendar-first with contactability coloring.
- Auto-schedule from live call; WhatsApp confirm path for PTP callbacks.
- Weekend/holiday calendar + quiet hours enforcement.


## 3. Other bugs / issues
- Surface missed callbacks as red list above calendar.
- Block scheduling outside policy windows.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Work-items include CB-0001.. and CB-SUSANTH-1 missed; page SSR large HTML (~107KB) with manager chrome.
## Live API enrichment
- `_api-callbacks.json`: **7** callback records.
