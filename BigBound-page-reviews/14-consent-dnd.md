# Consent & communication preferences

- **URL:** `http://localhost:8080/consent`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** Consent / DND registry.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **High:** Page is a registry, but consent is not visibly enforced as a **lock on click-to-call** elsewhere.
- **Medium:** Skeletons / filter-empty copy ("No consent records match filters") blames filters when registry may be empty.
- **Medium:** Expiring ≤30d is valuable but not surfaced on Customer 360 chips.


## 2. High-value gaps for a next-gen AI collections platform
- Runtime veto before any dial/WhatsApp/SMS.
- Preference center sync from CBS/CRM; TRAI DND + bank DNC lists.
- Expiring consent badges on every queue row.


## 3. Other bugs / issues
- Import CSV needs validation report.
- Export for auditor with watermark.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Extract: skeletons=6 on consent page; filters Contactable/DND/opt-out/expiring in prior review.
## Live API enrichment
- `_api-consent.json` sizeable dump present (23979 bytes). Registry is not inherently empty.
