# Handoff Hub

- **URL:** `http://localhost:8080/handoff`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Live escalated-call war room (Pipecat-related stack in monorepo historically).

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **Critical:** Page title promises "Live Escalated Call" but main content observed as **blank / skeleton** — no transcript, no 360, no wrap-up.
- **High:** This should be the Pipecat hero moment; instead it is a void when no live call AND no replayable last escalation.
- **Medium:** No explicit empty state ("No live handoff — replay last" / "Waiting for escalate").


## 2. High-value gaps for a next-gen AI collections platform
- Warm transcript + Mini-Miranda / RBI disclosure checklist + next-best-action from decision engine.
- One-key wrap: PTP + disposition + audit line.
- Supervisor whisper / barge entry from Floor.
- Packet ready on transfer (ledger, consent, authority envelope).


## 3. Other bugs / issues
- Skeletons without timeout→error path.
- Ensure handoff deep-links from Inbox and Floor share one conversation id.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- HTML extract: title Handoff Hub; skeletons=6; no H1 body text in SSR.
## Live API enrichment
- `_api-handoff-queue.json`: `{'items': [], 'activeInteractionId': None}`
- Queue empty / no activeInteractionId right now — blank UI may be “true empty” OR missing replay-of-last-escalation. Still need designed empty + Susanth voice hardship escalation (`CV-… needs_human`) deep-link.
