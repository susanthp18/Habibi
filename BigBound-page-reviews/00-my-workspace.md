# My Workspace

- **URL:** `http://localhost:8080/`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** SSR route `index` + client React Query for `/me`, `/workspace/summary`, work-items.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **Critical:** Greeting renders **"Good evening, there"** while `/me` returns **Priya Nair**.
- **Critical:** UI copy: "No upcoming callbacks", "No open leads", disputes tab **0**, skeletons on queue — but API has **nextLead Deepa Iyer**, **8 SLA breach timers**, and **19 work-items** including missed callbacks, broken PTPs (Vikram ₹1,240; Susanth ₹4,800), disputes.
- **High:** Stats show **0** calls / AHT `0m 00s` with **delta chips** (`+0 vs prior 7d`, team comparisons) — emptiness dressed as performance.
- **High:** Availability still **Available** with green pulse even when shift messaging historically said shift ended (time-truth / weekend issue).
- **Medium:** Assigned queue defaulted to Disputes-only chrome while richer entity types exist in work-items.
- **Medium:** Wide `min-width` tables force horizontal scroll on a personal home.


## 2. High-value gaps for a next-gen AI collections platform
- **Start next** primary action: worst SLA first (e.g. Sameer Khan callback overdue ~1252h in dump), one click into Handoff/360.
- Prefetch `/me` + summary + work-items on the **server** so first paint is truthful.
- Personal coaching strip: broken PTP recovery playbook, WhatsApp confirm loop for Susanth-style promises.
- Kill fake trend arrows whenever baseline n=0.


## 3. Other bugs / issues
- Empty states lack CTAs ("load demo queue" / "start next breach").
- Duplicate Available chip + Available/On break/Wrap-up control cluster is noisy.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- SSR title: My Workspace — BigBound AI; observed skeletons on assigned queue; empty callback/lead sentences in HTML extract.
