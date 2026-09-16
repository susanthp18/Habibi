# Redaction & export hub

- **URL:** `http://localhost:8080/redaction`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** PII redaction + regulator export.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **Medium:** Empty queue; "Select all w/ PII" is powerful and scary without preview.
- **Medium:** Plural bugs historically ("0 record s").
- **Low:** Role chips (DPO/auditor) without records.


## 2. High-value gaps for a next-gen AI collections platform
- Forced preview diff before export; watermark who exported.
- Purpose binding (regulatory request id) required field.
- Irreversible delivery receipt.


## 3. Other bugs / issues
- Disable Select-all until query scoped.
- Test with Susanth/Vikram artefacts containing PII.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Title Redaction & Export Hub; empty states No records / No exports in prior extracts.
