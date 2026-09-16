# Promises & payment plans

- **URL:** `http://localhost:8080/promises`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** PTP kanban + payment plans.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **High:** UI "No promises" / lane counts ·0 while work-items include **broken PTPs** (Vikram Rao ₹1,240; Susanth ₹4,800) and follow-ups `FU-PTP-*`.
- **Medium:** Tab chrome All/Upcoming/Due/Kept/Broken/Partial all zero is noise.
- **Medium:** Pluralization / copy glitches historically ("follow-up s").
- **Low:** "+ Payment plan" empty CTA is actually good — rare positive pattern.


## 2. High-value gaps for a next-gen AI collections platform
- Broken-PTP scream lane with WhatsApp confirm + UPI pay link artefact.
- Promise loop: capture on call → written confirm → calendar → breach auto work-item (partially in API) → visible here.
- Partial keep analytics (amount kept vs promised).


## 3. Other bugs / issues
- Sync kanban to work-items `entityType=promise|followup`.
- Default filter: Broken + Due today for agents.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Work-items contain p1 broken PTP and PTP-SUSANTH-2; page extract EMPTY/LOAD No promises; skeletons=6.
## Live API enrichment
- `_api-promises.json`: **15** promise records (not zero).
- UI “No promises” is a **binding bug**, not an empty book.
