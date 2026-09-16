# Login (adjacent route)

- **URL:** `http://localhost:8080/login`
- **Reviewed:** 2026-09-12 IST
- **Status:** HTTP **200** (was 404 in earlier August review)

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **High — branding drift:** Title **"Sign in — PayInt"** while product chrome is BigBound AI.
- **High — auth optional:** Product routes remain reachable without completing login (historical OIDC Phase 5). Login page copy: "The floor is already working the book." / "No password is stored on this product."
- **Medium:** `/profile` and `/settings` still **404**, so account/prefs have nowhere to land after sign-in.

## 2. High-value gaps
- Real OIDC/SAML against bank IdP; session in chrome (avatar, tenant switch).
- Post-login land on role-based home, not a generic workspace.

## 3. Other bugs / issues
- Align PayInt vs BigBound naming before external demos.

## Evidence
- Curl `/login` → 200, H1 "The floor is already working the book."; `/settings` & `/profile` → 404.
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
