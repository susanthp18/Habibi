# Roles & access

- **URL:** `http://localhost:8080/roles`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** RBAC + outbound calling master gate.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **High:** Outbound calling master switch + demo "call outside hours" is either a compliance landmine or a spinner (`Reading switch 0.0s` historically) — both bad.
- **High:** Roles page does not appear to **shrink the 26-item sidebar**; RBAC theater if nav ignores roles.
- **Medium:** Priya has extremely broad permissions in `/me` (admin-write, pii-raw-read, policy-publish, …) — fine for demo supervisor, dangerous if default.


## 2. High-value gaps for a next-gen AI collections platform
- Role → allowed nav → allowed actions matrix that actually drives UI.
- Outbound gate hard-stops dialer + shows policy reason.
- Least-privilege templates: Collector, Supervisor, QA, Builder, Auditor, Admin.


## 3. Other bugs / issues
- Display current user permissions summary from `/me`.
- Require reason code to enable outbound.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- `/me` permissions count=44; includes perm-admin-write and perm-pii-raw-read.
