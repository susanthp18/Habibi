# BigBound AI — page-by-page review

- **App:** `http://localhost:8080/` (Habibi / TanStack Start)
- **API:** `http://127.0.0.1:8000/`
- **Reviewed:** 2026-09-12 IST
- **Constraint:** Parallel development ongoing — slow loads were retried; findings prefer evidence over speed.
- **Output folder:** `D:\Hackathon\BigBound-page-reviews\`

## Live API snapshot (evidence shared across pages)

Acting user `/me`: **Priya Nair** (`priya-nair`), team Supervisors, tenant `hdfc.retail`. Work-items assignee=me: **19** items ({'callback': 7, 'lead': 3, 'followup': 5, 'promise': 2, 'dispute': 2}). Workspace summary: stats calls=0, resolutions=0, nextLead='Deepa Iyer', slaCountdowns=8 (all breach in dump). `GET /inbox` on :8000 returned **404** in this review window.

## Files

| File | Route | Top severity signal |
|------|-------|---------------------|
| [00-my-workspace.md](00-my-workspace.md) | `/` | Critical — UI empty vs API work queue |
| [01-conversation-inbox.md](01-conversation-inbox.md) | `/inbox` | Critical — API `/inbox` 404 |
| [02-handoff-hub.md](02-handoff-hub.md) | `/handoff` | Critical — blank war-room |
| [03-floor-command.md](03-floor-command.md) | `/floor` | High — stuck loading HUD |
| [04-executive-dashboard.md](04-executive-dashboard.md) | `/dashboard` | High — skeleton exec view |
| [05-customer-360.md](05-customer-360.md) | `/customers` | High — hollow 360 |
| [06-promises.md](06-promises.md) | `/promises` | High — broken PTPs in API, UI 0 |
| [07-disputes.md](07-disputes.md) | `/disputes` | High — disputes in API, UI empty |
| [08-documents.md](08-documents.md) | `/documents` | Medium — filter chrome > data |
| [09-callbacks.md](09-callbacks.md) | `/callbacks` | High — missed callbacks in API |
| [10-upsell-leads.md](10-upsell-leads.md) | `/upsell` | High — leads in API, UI 0 |
| [11-decision-intelligence.md](11-decision-intelligence.md) | `/treatment` | High — loading / no explainability UI |
| [12-audit-trail.md](12-audit-trail.md) | `/audit` | High — loading only |
| [13-compliance-risk.md](13-compliance-risk.md) | `/compliance` | Medium — empty + jargon |
| [14-consent-dnd.md](14-consent-dnd.md) | `/consent` | High — not gating click-to-call |
| [15-redaction-export.md](15-redaction-export.md) | `/redaction` | Medium — empty + plural bugs |
| [16-qa-scorecards.md](16-qa-scorecards.md) | `/qa` | Medium — homework queue, not live |
| [17-bot-analytics.md](17-bot-analytics.md) | `/bot-analytics` | Medium — loading |
| [18-knowledge-base.md](18-knowledge-base.md) | `/knowledge-base` | Medium — empty RAG |
| [19-agent-studio.md](19-agent-studio.md) | `/agent-studio` | Medium — loading fleet |
| [20-call-sandbox.md](20-call-sandbox.md) | `/sandbox` | High — demo path is a spinner |
| [21-routing-logic.md](21-routing-logic.md) | `/routing` | Medium — empty rules / fake latency |
| [22-integrations.md](22-integrations.md) | `/integrations` | Medium — jargon catalog |
| [23-webhooks.md](23-webhooks.md) | `/webhooks` | Medium — loading blank |
| [24-billing-usage.md](24-billing-usage.md) | `/billing` | Medium — loading |
| [25-roles-access.md](25-roles-access.md) | `/roles` | High — roles don't hide nav |
| [99-shell-cross-cutting.md](99-shell-cross-cutting.md) | shell | Cross-cutting IA / search / a11y |

## Also observed (not full product pages)

- `/login` — **200**, title "Sign in — PayInt" (branding drift from BigBound).
- `/settings`, `/profile` — **404**.
- `/prompt-studio` — **307** redirect (improved vs prior orphan).


## API dump note
Parallel crawl also saved `_api-*.json` evidence beside these markdowns (conversations, floor, promises=15, disputes=5, violations=116, leads, treatment cases, scorecards, KB, etc.). Several UIs still render empty/loading despite this data — treat as wiring bugs.
