# Customer 360

- **URL:** `http://localhost:8080/customers`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Customer list + nested 360 profile routes.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **High:** List shows skeleton/zero chrome while `/customers?limit=5` returns real people (e.g. Anita Desai critical ₹12,480 outstanding).
- **High:** Nested 360 arrays historically empty (consent/ledger/EMI/interactions) — "360" without history.
- **High:** PII masking inconsistency risk (some phones masked, some full in prior pass) — re-verify per row.
- **Medium:** Last contact dates in July on a September review feel stale for a live demo book.


## 2. High-value gaps for a next-gen AI collections platform
- Person-centric layout: balance, DPD, consent lock, next-best action, one-click call, open PTP/dispute.
- Timeline merging bot+human+payments.
- Hardship / deceased / third-party flags as hard gates.


## 3. Other bugs / issues
- Counters All/Assigned/At-risk must match API.
- Click-to-call must read consent service first.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Customers API sample includes anita-desai critical outstanding 12480; page SSR skeletons=6.
