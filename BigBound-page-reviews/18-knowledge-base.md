# Knowledge base

- **URL:** `http://localhost:8080/knowledge-base`
- **Reviewed:** 2026-09-12 IST
- **Load notes:** Fetched with extended timeouts; re-checked against live API on :8000 because parallel dev can leave SSR mid-hydration.
- **Stack notes:** RAG docs/FAQs/gaps.

## 1. UI/UX issues, bugs, inconsistencies, staleness
- **Medium:** Empty KB metrics (0 docs/FAQs/gaps) with skeletons — cold start unfriendly.
- **Medium:** Test retrieval exists (good) but not hero.
- **Low:** Last re-index dates with nothing indexed confuse.


## 2. High-value gaps for a next-gen AI collections platform
- Citation required on every bot answer; gap inbox from live misses.
- Version KB with agent card publish gates.
- Policy docs vs marketing docs separation.


## 3. Other bugs / issues
- Onboarding: upload 3 sample policies + run retrieval test.


## Evidence
Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.
- Extract: skeletons=6; Test retrieval affordance known from prior review.
## Live API enrichment
- KB dumps: documents=21, faqs=119. UI zeros are suspicious.
