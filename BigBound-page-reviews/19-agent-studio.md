# Agent studio

- **URL:** `http://localhost:8080/agent-studio`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Agent cards / fleet / skills.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **Medium:** **Loading fleet** / `0.0s`; Skills subroute **Loading skills**.
- **Medium:** Author jargon ("mouths", "Publish is a compiler", HMAC signing) without a business mode.
- **Medium:** Builder tools live in the same shell as collector queues.


## 2. High-value gaps for a next-gen AI collections platform
- Separate Builder app shell.
- Publish gates: eval, sandbox personas, canary %, rollback.
- Skill grant narrowing visualization (grant vs offer).


## 3. Other bugs / issues
- `/agent-studio/skills` should inherit fleet context breadcrumbs.
- Align Prompt Studio redirect story in nav labels.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Titles Agent studio / Skills; LOADING_00=1 on both extracts.
