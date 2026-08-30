"""Per-route authorization.

Before this, ``require_admin`` gated exactly one of ~180 routes
(``POST /tts-voices/catalog/sync``), so any holder of any valid API key could
rotate webhook signing secrets, patch provider credentials, purge the knowledge
base, publish prompt versions and read every customer. The ``roles`` /
``permissions`` / ``role_permissions`` / ``user_roles`` tables existed and were
seeded; nothing consulted them.

Design
------
The requirement is declared **per route in one registry** rather than as 180
separate ``Depends`` arguments. Two reasons, and the second is the load-bearing
one:

* the policy is reviewable as a table — you can read what an Agent may do
  without grepping the endpoint bodies;
* :func:`assert_registry_covers` can then prove the registry is *total* over the
  app's route table, so a new endpoint cannot ship ungated. A per-route
  ``Depends`` has no such property: forgetting one is silent.

Enforcement is wired as a single global dependency (see ``main.py``), which
Starlette resolves *after* routing, so ``request.scope["route"]`` names the
matched path template.

Fail-open vs fail-closed
------------------------
Enforcement follows the same switch authentication already uses: when neither
``API_KEY`` nor ``API_KEY_MAP`` is configured the deployment has no notion of
who is calling, so gating on identity is meaningless and every route stays open
(unchanged local/demo behaviour). The moment credentials are configured — always
true in production, which refuses to boot without them — the registry is
enforced. ``AUTHZ_ENFORCE=1|0`` overrides in either direction.

Grant resolution
----------------
``role_permissions`` is authoritative when it says anything about a role. A role
with **no** explicit grant falls back to the built-in default for its name, so a
fresh database with no permission seed is usable rather than locked out; the
moment an operator grants that role anything, the database wins entirely and
revocation works. ``perm-admin-write`` is a superuser grant, matching the
existing semantics of :func:`db.actor_is_admin`.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Iterable

from env_utils import env_float

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Permission catalog
# ---------------------------------------------------------------------------
# Ids keep the existing ``perm-<module>-<action>`` shape. The first five already
# exist in seeded databases and are reused verbatim — do not renumber them.

ADMIN_WRITE = "perm-admin-write"

CUSTOMERS_READ = "perm-customers-read"
CUSTOMERS_WRITE = "perm-customers-write"
INTERACTIONS_READ = "perm-interactions-read"
INTERACTIONS_WRITE = "perm-interactions-write"
QA_REVIEW = "perm-qa-review"
QA_WRITE = "perm-qa-write"
WORKQUEUE_WRITE = "perm-workqueue-write"

COLLECTIONS_READ = "perm-collections-read"
COLLECTIONS_WRITE = "perm-collections-write"
LEADS_READ = "perm-leads-read"
LEADS_WRITE = "perm-leads-write"
CONSENT_READ = "perm-consent-read"
CONSENT_WRITE = "perm-consent-write"
ANALYTICS_READ = "perm-analytics-read"
BILLING_READ = "perm-billing-read"
BILLING_WRITE = "perm-billing-write"
COMPLIANCE_READ = "perm-compliance-read"
COMPLIANCE_WRITE = "perm-compliance-write"
KB_READ = "perm-kb-read"
KB_WRITE = "perm-kb-write"
BOT_READ = "perm-bot-read"
BOT_WRITE = "perm-bot-write"
AGENT_EDIT = "perm-agent-edit"
AGENT_PUBLISH = "perm-agent-publish"
EVAL_RUN = "perm-eval-run"
REDTEAM_RUN = "perm-redteam-run"
CONNECTOR_ATTACH = "perm-connector-attach"
POLICY_EXPORT = "perm-policy-export"
VOICE_OPERATE = "perm-voice-operate"
SUPERVISOR_READ = "perm-supervisor-read"
SUPERVISOR_WRITE = "perm-supervisor-write"
INTEGRATIONS_READ = "perm-integrations-read"
INTEGRATIONS_WRITE = "perm-integrations-write"
OBSERVABILITY_READ = "perm-observability-read"


#: ``(id, module, action, description)`` — upserted at boot by
#: :func:`ensure_permission_catalog` so an operator can grant them in the UI.
PERMISSION_CATALOG: tuple[tuple[str, str, str, str], ...] = (
    (ADMIN_WRITE, "admin", "write", "Full administrative access (superuser)"),
    (CUSTOMERS_READ, "customers", "read", "View customer records and insights"),
    (CUSTOMERS_WRITE, "customers", "write", "Add customer notes and edit customer records"),
    (INTERACTIONS_READ, "interactions", "read", "View interactions, transcripts and traces"),
    (INTERACTIONS_WRITE, "interactions", "write", "Create interactions and wrap them up"),
    (QA_REVIEW, "qa", "review", "View QA rubrics, scorecards and calibration"),
    (QA_WRITE, "qa", "write", "Score calls, raise coaching actions, run calibration"),
    (WORKQUEUE_WRITE, "workqueue", "write", "Act on assigned work items"),
    (COLLECTIONS_READ, "collections", "read", "View promises, plans, disputes, callbacks, documents"),
    (COLLECTIONS_WRITE, "collections", "write", "Capture promises, plans, disputes, callbacks, documents"),
    (LEADS_READ, "leads", "read", "View sales leads"),
    (LEADS_WRITE, "leads", "write", "Create and update sales leads"),
    (CONSENT_READ, "consent", "read", "View consent and opt-out state"),
    (CONSENT_WRITE, "consent", "write", "Change consent and record opt-outs"),
    (ANALYTICS_READ, "analytics", "read", "View dashboards, bot analytics and offer health"),
    (BILLING_READ, "billing", "read", "View spend, invoices and budgets"),
    (BILLING_WRITE, "billing", "write", "Change budget rules"),
    (COMPLIANCE_READ, "compliance", "read", "View violations, redaction records and exports"),
    (COMPLIANCE_WRITE, "compliance", "write", "Resolve violations, edit redaction, run exports"),
    (KB_READ, "kb", "read", "Search and browse the knowledge base"),
    (KB_WRITE, "kb", "write", "Upload, edit, reindex and purge knowledge base content"),
    (BOT_READ, "bot", "read", "View prompts, flows, deployments and bot configuration"),
    (BOT_WRITE, "bot", "write", "Author and publish prompts, flows and deployments"),
    (AGENT_EDIT, "agent", "edit", "Author agent cards, tools and handoff allowlists"),
    (AGENT_PUBLISH, "agent", "publish", "Compile and publish an agent card to production"),
    (EVAL_RUN, "eval", "run", "Run regression eval suites against a card"),
    (REDTEAM_RUN, "redteam", "run", "Run red-team suites against a card"),
    (CONNECTOR_ATTACH, "connector", "attach", "Bind an approved connector to an agent card"),
    (POLICY_EXPORT, "policy", "export", "Download the OPA/Cedar projection of live Python policy"),
    (VOICE_OPERATE, "voice", "operate", "Place outbound calls and run voice sandbox sessions"),
    (SUPERVISOR_READ, "supervisor", "read", "View the live floor: agent presence, live alerts"),
    (SUPERVISOR_WRITE, "supervisor", "write", "Floor supervision, takeover and handoff actions"),
    (INTEGRATIONS_READ, "integrations", "read", "View providers, connectors, vault refs and our MCP"),
    (INTEGRATIONS_WRITE, "integrations", "write", "Configure providers, connectors, vault secrets and MCP keys"),
    (OBSERVABILITY_READ, "observability", "read", "Scrape /metrics (service accounts and operators)"),
)

ALL_PERMISSIONS: frozenset[str] = frozenset(p[0] for p in PERMISSION_CATALOG)


#: Fallback grants, keyed by normalized role name. Applied only to a role that
#: has no row at all in ``role_permissions`` — see the module docstring.
ROLE_DEFAULTS: dict[str, frozenset[str]] = {
    "admin": ALL_PERMISSIONS,
    "supervisor": frozenset(
        {
            CUSTOMERS_READ, CUSTOMERS_WRITE,
            INTERACTIONS_READ, INTERACTIONS_WRITE,
            COLLECTIONS_READ, COLLECTIONS_WRITE,
            LEADS_READ, LEADS_WRITE,
            CONSENT_READ, CONSENT_WRITE,
            ANALYTICS_READ, BILLING_READ,
            QA_REVIEW, QA_WRITE,
            COMPLIANCE_READ,
            KB_READ, BOT_READ,
            VOICE_OPERATE, SUPERVISOR_READ, SUPERVISOR_WRITE, WORKQUEUE_WRITE,
            INTEGRATIONS_READ, OBSERVABILITY_READ,
        }
    ),
    "agent": frozenset(
        {
            CUSTOMERS_READ, CUSTOMERS_WRITE,
            INTERACTIONS_READ, INTERACTIONS_WRITE,
            COLLECTIONS_READ, COLLECTIONS_WRITE,
            LEADS_READ, LEADS_WRITE,
            CONSENT_READ,
            ANALYTICS_READ,
            KB_READ,
            WORKQUEUE_WRITE,
            VOICE_OPERATE,
        }
    ),
    "qa_reviewer": frozenset(
        {
            CUSTOMERS_READ,
            INTERACTIONS_READ,
            COLLECTIONS_READ,
            ANALYTICS_READ,
            QA_REVIEW, QA_WRITE,
            COMPLIANCE_READ, COMPLIANCE_WRITE,
            KB_READ,
        }
    ),
    # Forward-compat aliases for the role names db._actor_can_view_raw_pii
    # already recognises.
    "compliance_officer": frozenset(
        {
            CUSTOMERS_READ, INTERACTIONS_READ, COLLECTIONS_READ, CONSENT_READ,
            ANALYTICS_READ, QA_REVIEW,
            COMPLIANCE_READ, COMPLIANCE_WRITE,
            KB_READ,
        }
    ),
}
ROLE_DEFAULTS["dpo"] = ROLE_DEFAULTS["compliance_officer"]


# ---------------------------------------------------------------------------
# Route registry
# ---------------------------------------------------------------------------
#: Routes reachable without a permission check. Two disjoint reasons:
#:
#: * they are already in ``main._AUTH_EXEMPT_PREFIXES`` — unauthenticated by
#:   design, carrying their own HMAC/signature check (webhooks) or no identity
#:   at all (health, WebRTC signalling, media-stream sockets);
#: * or they are self-scoped: ``/me`` describes the caller, so any authenticated
#:   actor may read it.
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/health"),
        ("GET", "/ready"),
        # Signature-verified provider callbacks.
        ("GET", "/webhooks/whatsapp"),
        ("POST", "/webhooks/whatsapp"),
        ("GET", "/webhook/whatsapp"),
        ("POST", "/webhook/whatsapp"),
        ("POST", "/twilio/voice/incoming"),
        ("POST", "/twilio/voice/fallback"),
        ("POST", "/twilio/voice/stream-status"),
        ("POST", "/twilio/voice/call-status"),
        # Delivery receipts. Twilio carries no API key, so the signature check
        # inside the handler is the authentication — same as every other
        # callback above.
        ("POST", "/twilio/sms/status"),
        ("GET", "/pay/{token}"),
        ("POST", "/pay/{token}/complete"),
        ("POST", "/webhooks/payments/{provider}"),
        ("POST", "/webhooks/collections/payment-events"),
        # Media-stream / signalling sockets (no header can be attached).
        ("WS", "/ws"),
        ("WS", "/ws/{proxy_secret}"),
        ("POST", "/api/offer"),
        ("PATCH", "/api/offer"),
        ("POST", "/voice-rtc/api/offer"),
        ("PATCH", "/voice-rtc/api/offer"),
        # Self-scoped.
        ("GET", "/me"),
        ("GET", "/me/presence"),
        ("PATCH", "/me/presence"),
        ("GET", "/.well-known/agent-card.json"),
        ("POST", "/a2a"),
    }
)


#: ``(method, path template) -> permission id``. Kept sorted by path so it reads
#: as a policy table. Every non-public route in the app must appear here;
#: :func:`assert_registry_covers` enforces that.
ROUTE_PERMISSIONS: dict[tuple[str, str], str] = {
    # --- billing -----------------------------------------------------------
    ("GET", "/billing"): BILLING_READ,
    ("GET", "/billing/export.csv"): BILLING_READ,
    ("POST", "/billing/budgets/{budget_id}/rules"): BILLING_WRITE,
    ("PATCH", "/billing/budgets/{budget_id}/rules/{rule_id}"): BILLING_WRITE,
    ("DELETE", "/billing/budgets/{budget_id}/rules/{rule_id}"): BILLING_WRITE,
    # --- analytics ---------------------------------------------------------
    ("GET", "/bot-analytics"): ANALYTICS_READ,
    ("GET", "/dashboard"): ANALYTICS_READ,
    ("GET", "/offers/health"): ANALYTICS_READ,
    ("GET", "/offers/tuner-suggestions"): ANALYTICS_READ,
    ("GET", "/workspace/summary"): ANALYTICS_READ,
    # Reading the queue is a read. This was WORKQUEUE_WRITE, which meant an
    # oversight role could not open the screen it oversees while anyone able to
    # open it could also claim from it — a permission that gates a GET on the
    # right to mutate is wrong in both directions.
    ("GET", "/work-items"): COLLECTIONS_READ,
    # --- bot configuration -------------------------------------------------
    ("GET", "/bot-deployments"): BOT_READ,
    ("GET", "/bot-deployments/active"): BOT_READ,
    ("GET", "/bot-deployments/experiments"): BOT_READ,
    ("POST", "/bot-deployments/experiments/{experiment_id}/rollback"): AGENT_PUBLISH,
    ("POST", "/bot-deployments/{deployment_id}/rollback"): BOT_WRITE,
    ("GET", "/flow/reserved-keys"): BOT_READ,
    ("GET", "/flow/tools"): BOT_READ,
    ("POST", "/flow/validate"): BOT_READ,
    ("GET", "/persona-presets"): BOT_READ,
    ("GET", "/prompt-versions"): BOT_READ,
    ("GET", "/prompt-versions/published"): BOT_READ,
    ("GET", "/prompt-versions/{version_id}"): BOT_READ,
    ("POST", "/prompt-versions"): BOT_WRITE,
    ("PATCH", "/prompt-versions/{version_id}"): BOT_WRITE,
    ("POST", "/prompt-versions/{version_id}/discard"): BOT_WRITE,
    ("POST", "/prompt-versions/{version_id}/publish"): AGENT_PUBLISH,
    ("POST", "/prompt-versions/{version_id}/restore-as-draft"): BOT_WRITE,
    ("POST", "/prompt-versions/estimate-tokens"): BOT_READ,
    ("POST", "/prompt-versions/lint"): BOT_READ,
    ("GET", "/flow/built-in"): BOT_READ,
    ("GET", "/flow/transitions"): BOT_READ,
    ("GET", "/agent-studio/cards"): BOT_READ,
    # Read-only history of who changed what an agent says. BOT_READ, not
    # AGENT_EDIT: reviewing the record must not require the right to change it.
    ("GET", "/agent-studio/change-log"): BOT_READ,
    ("GET", "/agent-studio/cards/{bot_id}"): BOT_READ,
    ("PATCH", "/agent-studio/cards/{bot_id}"): AGENT_EDIT,
    ("POST", "/agent-studio/cards/{bot_id}/archive"): AGENT_EDIT,
    ("POST", "/agent-studio/cards/{bot_id}/restore"): AGENT_EDIT,
    ("POST", "/agent-studio/cards/{bot_id}/compile"): AGENT_EDIT,
    ("POST", "/agent-studio/cards/{bot_id}/connectors"): CONNECTOR_ATTACH,
    ("POST", "/agent-studio/cards/{bot_id}/publish"): AGENT_PUBLISH,
    ("GET", "/agent-studio/cards/{bot_id}/graph"): BOT_READ,
    ("POST", "/agent-studio/cards/clone"): AGENT_EDIT,
    ("GET", "/agent-studio/skills"): BOT_READ,
    ("GET", "/agent-studio/skills/scripts"): BOT_READ,
    ("GET", "/agent-studio/skills/{skill_id}"): BOT_READ,
    ("POST", "/agent-studio/skills"): AGENT_EDIT,
    ("PATCH", "/agent-studio/skills/{skill_id}"): AGENT_EDIT,
    # Delete refuses first-party / signed / attached packs in the handler, so
    # authoring rights are enough — it cannot reach anything production pins.
    ("DELETE", "/agent-studio/skills/{skill_id}"): AGENT_EDIT,
    ("POST", "/agent-studio/skills/{skill_id}/sign"): AGENT_PUBLISH,
    ("POST", "/agent-studio/skills/{skill_id}/revert"): AGENT_PUBLISH,
    ("POST", "/agent-studio/skills/{skill_id}/attach"): AGENT_EDIT,
    ("POST", "/agent-studio/skills/{skill_id}/clone"): AGENT_EDIT,
    ("POST", "/agent-studio/skills/{skill_id}/detach"): AGENT_EDIT,
    ("GET", "/agent-studio/skills/{skill_id}/export"): BOT_READ,
    ("POST", "/agent-studio/skills/import"): AGENT_EDIT,
    ("POST", "/agent-studio/skills/run-script"): AGENT_EDIT,
    ("GET", "/agent-studio/templates"): BOT_READ,
    ("POST", "/kb/gaps/{gap_id}/promote-skill"): AGENT_EDIT,
    ("GET", "/connectors"): INTEGRATIONS_READ,
    ("POST", "/connectors"): INTEGRATIONS_WRITE,
    ("GET", "/connectors/{connector_id}"): INTEGRATIONS_READ,
    ("POST", "/connectors/{connector_id}/approve"): INTEGRATIONS_WRITE,
    ("POST", "/connectors/{connector_id}/test"): INTEGRATIONS_WRITE,
    ("POST", "/connectors/{connector_id}/cimd"): INTEGRATIONS_WRITE,
    ("GET", "/vault/refs"): INTEGRATIONS_READ,
    ("POST", "/vault/refs"): INTEGRATIONS_WRITE,
    ("POST", "/vault/refs/{ref_id}/rotate"): INTEGRATIONS_WRITE,
    ("GET", "/mcp/keys"): INTEGRATIONS_READ,
    ("POST", "/mcp/keys"): INTEGRATIONS_WRITE,
    ("POST", "/mcp/keys/{key_id}/rotate"): INTEGRATIONS_WRITE,
    ("POST", "/mcp/keys/{key_id}/revoke"): INTEGRATIONS_WRITE,
    ("GET", "/mcp/tasks"): INTEGRATIONS_READ,
    ("GET", "/mcp/tasks/{task_id}"): INTEGRATIONS_READ,
    ("GET", "/mcp/status"): INTEGRATIONS_READ,
    ("GET", "/a2a/partners"): INTEGRATIONS_READ,
    ("POST", "/a2a/partners"): INTEGRATIONS_WRITE,
    ("GET", "/a2a/tasks"): INTEGRATIONS_READ,
    ("POST", "/a2a/tasks/{task_id}/signal"): INTEGRATIONS_WRITE,
    ("GET", "/gateway/status"): INTEGRATIONS_READ,
    ("GET", "/gateway/canary"): INTEGRATIONS_READ,
    ("POST", "/gateway/canary"): INTEGRATIONS_WRITE,
    ("POST", "/gateway/canary/{canary_id}/promote"): INTEGRATIONS_WRITE,
    ("POST", "/eval/suites/{suite_id}/run"): EVAL_RUN,
    ("POST", "/eval/schedule/run"): EVAL_RUN,
    ("POST", "/eval/tasks/{task_id}/graduate"): EVAL_RUN,
    ("GET", "/eval/suites"): BOT_READ,
    ("GET", "/eval/reports"): BOT_READ,
    ("GET", "/eval/reports/{report_id}"): BOT_READ,
    ("GET", "/eval/critiques"): BOT_READ,
    ("POST", "/eval/reports/{report_id}/critique"): EVAL_RUN,
    ("GET", "/eval/disagreements"): QA_REVIEW,
    ("GET", "/eval/twin-corpus"): BOT_READ,
    ("POST", "/eval/twin-corpus/grow"): EVAL_RUN,
    ("GET", "/roles"): BOT_READ,
    ("PATCH", "/roles/{role_id}/permissions"): ADMIN_WRITE,
    ("GET", "/routing-audit"): BOT_READ,
    ("GET", "/routing-rules"): BOT_READ,
    ("GET", "/routing-rules/{rule_id}/executions"): BOT_READ,
    ("POST", "/routing-rules"): BOT_WRITE,
    ("POST", "/routing-rules/reorder"): BOT_WRITE,
    ("PATCH", "/routing-rules/{rule_id}"): BOT_WRITE,
    ("DELETE", "/routing-rules/{rule_id}"): BOT_WRITE,
    ("GET", "/sandbox/scenarios"): BOT_READ,
    ("GET", "/sandbox/tuning/presets"): BOT_READ,
    ("GET", "/sandbox/runs/{run_id}"): BOT_READ,
    ("POST", "/sandbox/runs"): BOT_WRITE,
    ("POST", "/sandbox/runs/{run_id}/complete"): BOT_WRITE,
    ("POST", "/sandbox/runs/{run_id}/turns"): BOT_WRITE,
    ("POST", "/sandbox/payment-events"): COLLECTIONS_WRITE,
    ("GET", "/twins"): BOT_READ,
    ("POST", "/twins/{twin_id}/run"): BOT_WRITE,
    ("GET", "/work-runtime/jobs/{job_id}"): COLLECTIONS_READ,
    ("GET", "/tts-voices"): BOT_READ,
    ("GET", "/tts-voices/catalog"): BOT_READ,
    ("GET", "/tts-voices/catalog-warning"): BOT_READ,
    ("GET", "/tts-voices/catalog/sync-runs"): BOT_READ,
    ("GET", "/tts-voices/catalog/{short_name}"): BOT_READ,
    ("GET", "/tts-voices/pricing"): BOT_READ,
    ("POST", "/tts-voices/catalog/sync"): ADMIN_WRITE,
    ("GET", "/tts-voices/catalog-provider-counts"): BOT_READ,
    ("GET", "/tts-voices/catalog-locale-counts"): BOT_READ,
    # --- provider registry -------------------------------------------------
    # Reads are BOT_READ: the Voice tab needs the capability matrix to render
    # a picker at all. Writes are ADMIN_WRITE because a binding decides which
    # vendor a live call is routed to — and therefore where the caller's audio
    # is processed, which is a data-residency decision, not a preference.
    ("GET", "/providers/models"): BOT_READ,
    ("GET", "/providers/bindings"): BOT_READ,
    ("POST", "/providers/bindings"): ADMIN_WRITE,
    ("DELETE", "/providers/bindings/{binding_id}"): ADMIN_WRITE,
    # Key tails and retirement state — operational, not secret, but it
    # reveals which vendors a tenant pays for, so not public.
    ("GET", "/providers/pools"): BOT_READ,
    # --- QA / coaching -----------------------------------------------------
    ("GET", "/calibration-sessions"): QA_REVIEW,
    ("PATCH", "/calibration-sessions/{session_id}"): QA_WRITE,
    ("GET", "/coaching-actions"): QA_REVIEW,
    ("POST", "/coaching-actions"): QA_WRITE,
    ("PATCH", "/coaching-actions/{action_id}"): QA_WRITE,
    ("GET", "/rubric"): QA_REVIEW,
    ("GET", "/scorecards"): QA_REVIEW,
    ("GET", "/qa/coverage"): QA_REVIEW,
    ("GET", "/qa/interactions/{interaction_id}/pack"): COMPLIANCE_READ,
    ("POST", "/scorecards"): QA_WRITE,
    ("PATCH", "/scorecards/{scorecard_id}"): QA_WRITE,
    # --- collections -------------------------------------------------------
    ("GET", "/callbacks"): COLLECTIONS_READ,
    ("POST", "/callbacks"): COLLECTIONS_WRITE,
    ("PATCH", "/callbacks/{callback_id}"): COLLECTIONS_WRITE,
    ("POST", "/callbacks/{callback_id}/reminders"): COLLECTIONS_WRITE,
    ("GET", "/disputes"): COLLECTIONS_READ,
    ("POST", "/disputes"): COLLECTIONS_WRITE,
    ("PATCH", "/disputes/{dispute_id}"): COLLECTIONS_WRITE,
    ("POST", "/disputes/{dispute_id}/evidence"): COLLECTIONS_WRITE,
    ("POST", "/disputes/{dispute_id}/notes"): COLLECTIONS_WRITE,
    ("GET", "/document-requests"): COLLECTIONS_READ,
    ("POST", "/document-requests"): COLLECTIONS_WRITE,
    ("POST", "/document-requests/ingest"): COLLECTIONS_WRITE,
    ("PATCH", "/document-requests/{document_id}"): COLLECTIONS_WRITE,
    ("POST", "/document-requests/{document_id}/delivery-attempts"): COLLECTIONS_WRITE,
    ("PATCH", "/followups/{followup_id}"): COLLECTIONS_WRITE,
    ("GET", "/payment-plans"): COLLECTIONS_READ,
    ("POST", "/payment-plans"): COLLECTIONS_WRITE,
        ("GET", "/promises"): COLLECTIONS_READ,
        ("POST", "/promises"): COLLECTIONS_WRITE,
        ("PATCH", "/promises/{promise_id}"): COLLECTIONS_WRITE,
        ("POST", "/promises/{promise_id}/resend-confirm"): COLLECTIONS_WRITE,
    # --- next-best-treatment (P3) ------------------------------------------
    # Reading the plan is a collections read even though it writes a decision
    # row: the row is a log of the question, not a change to the borrower's
    # state, and gating it on write would keep it off the QA and oversight
    # screens that most need to see what the engine would do.
    ("GET", "/treatment/next"): COLLECTIONS_READ,
    ("GET", "/treatment/insights"): ANALYTICS_READ,
    ("GET", "/treatment/metrics"): ANALYTICS_READ,
    ("GET", "/treatment/model-health"): ANALYTICS_READ,
    ("GET", "/treatment/models"): ANALYTICS_READ,
    ("GET", "/treatment/holds"): COLLECTIONS_READ,
    ("GET", "/treatment/cases"): COLLECTIONS_READ,
    # Placing a hold stops outreach; lifting one resumes it. Both are
    # collections writes, and lifting is the one that needs the audit trail.
    ("POST", "/treatment/holds"): COLLECTIONS_WRITE,
    ("POST", "/treatment/holds/{hold_id}/release"): COLLECTIONS_WRITE,
    # --- outbound attempt ledger (O0) --------------------------------------
    # Reach figures are an analytics read; the dial log names borrowers and is
    # a collections read. Splitting them means a floor analyst can be shown the
    # answer rate without also being shown who was called.
    ("GET", "/outbound/stats"): ANALYTICS_READ,
    ("GET", "/outbound/reasons"): ANALYTICS_READ,
    ("GET", "/outbound/attempts"): COLLECTIONS_READ,
    ("GET", "/customers/{customer_id}/outbound/hours"): COLLECTIONS_READ,
    # --- campaigns, cadence, pools, obligations (O3/O4) --------------------
    # Reading a run is a collections read; creating one, adding borrowers to it
    # or starting it rings real phones and is a write. Starting is separated
    # from creating on purpose — the two most consequential buttons in the
    # product should not be the same button.
    ("GET", "/outbound/campaigns"): COLLECTIONS_READ,
    ("GET", "/outbound/campaigns/{run_id}"): COLLECTIONS_READ,
    # A POST that writes nothing: the selector is a request body rather than a
    # query string because it is a nested object, not because it changes state.
    # Read permission is therefore the right one - it returns borrower names, so
    # it is not public, and gating it behind WRITE would mean the only way to
    # see who a campaign would call is to hold the permission to call them.
    ("POST", "/outbound/campaigns/preview"): COLLECTIONS_READ,
    ("POST", "/outbound/campaigns"): COLLECTIONS_WRITE,
    ("POST", "/outbound/campaigns/{run_id}/targets"): COLLECTIONS_WRITE,
    ("POST", "/outbound/campaigns/{run_id}/status"): COLLECTIONS_WRITE,
    ("GET", "/outbound/cadence"): COLLECTIONS_READ,
    ("GET", "/outbound/number-pools"): COLLECTIONS_READ,
    ("GET", "/outbound/obligations"): COLLECTIONS_READ,
    ("GET", "/outbound/missions"): COLLECTIONS_READ,
    # Closed vocabularies for the Outbound card editor. Read-scoped with the
    # rest of outbound: it exposes no tenant data beyond the caller-ID pool
    # names, which the sibling number-pools route already returns at this scope.
    ("GET", "/outbound/card-vocabulary"): COLLECTIONS_READ,
    ("GET", "/authority/next"): COLLECTIONS_READ,
    ("POST", "/authority/apply"): COLLECTIONS_WRITE,
    # --- customers ---------------------------------------------------------
    ("GET", "/customers"): CUSTOMERS_READ,
    ("GET", "/customers/{customer_id}"): CUSTOMERS_READ,
    ("GET", "/customers/{customer_id}/insights"): CUSTOMERS_READ,
    ("GET", "/customers/{customer_id}/contact-policy"): CONSENT_READ,
    ("POST", "/customers/{customer_id}/notes"): CUSTOMERS_WRITE,
    ("GET", "/staff"): CUSTOMERS_READ,
    ("GET", "/teams"): CUSTOMERS_READ,
    ("GET", "/products"): CUSTOMERS_READ,
    ("GET", "/canned-responses"): CUSTOMERS_READ,
    # --- consent -----------------------------------------------------------
    ("GET", "/consent"): CONSENT_READ,
    ("PATCH", "/consent/{customer_id}"): CONSENT_WRITE,
    ("POST", "/consent/{customer_id}/opt-out"): CONSENT_WRITE,
    # --- conversations / interactions --------------------------------------
    ("GET", "/calls"): INTERACTIONS_READ,
    ("GET", "/conversations"): INTERACTIONS_READ,
    ("GET", "/conversations/{conversation_id}"): INTERACTIONS_READ,
    ("POST", "/conversations/{conversation_id}/messages"): INTERACTIONS_WRITE,
    ("POST", "/conversations/{conversation_id}/suggestions/refresh"): INTERACTIONS_WRITE,
    ("POST", "/conversations/{conversation_id}/return-to-bot"): SUPERVISOR_WRITE,
    ("POST", "/conversations/{conversation_id}/takeover"): SUPERVISOR_WRITE,
    ("POST", "/interactions"): INTERACTIONS_WRITE,
    ("POST", "/interactions/{interaction_id}/wrap-up"): INTERACTIONS_WRITE,
    ("GET", "/interactions/{interaction_id}/cost"): BILLING_READ,
    ("GET", "/interactions/{interaction_id}/export"): INTERACTIONS_READ,
    ("GET", "/interactions/{interaction_id}/trace"): INTERACTIONS_READ,
    ("GET", "/handoff/active"): INTERACTIONS_READ,
    ("GET", "/handoff/queue"): INTERACTIONS_READ,
    ("GET", "/handoff/{interaction_id}"): INTERACTIONS_READ,
    ("POST", "/handoff/{interaction_id}/claim"): INTERACTIONS_WRITE,
    ("POST", "/handoff/{interaction_id}/disclosures"): INTERACTIONS_WRITE,
    ("POST", "/handoff/{interaction_id}/suggestions/{suggestion_id}/accept"): INTERACTIONS_WRITE,
    # --- compliance / redaction --------------------------------------------
    ("GET", "/export-jobs"): COMPLIANCE_READ,
    ("POST", "/export-jobs"): COMPLIANCE_WRITE,
    ("PATCH", "/export-jobs/{job_id}"): COMPLIANCE_WRITE,
    ("GET", "/redaction-records"): COMPLIANCE_READ,
    ("GET", "/redaction-records/{redaction_id}"): COMPLIANCE_READ,
    ("PATCH", "/redaction-records/{redaction_id}"): COMPLIANCE_WRITE,
    ("PATCH", "/redaction-records/{redaction_id}/audio-mute"): COMPLIANCE_WRITE,
    ("GET", "/redaction-rules"): COMPLIANCE_READ,
    ("PATCH", "/redaction-rules/{pii_type}"): COMPLIANCE_WRITE,
    ("PATCH", "/pii-findings/{finding_id}"): COMPLIANCE_WRITE,
    ("GET", "/compliance/rule-coverage"): COMPLIANCE_READ,
    ("POST", "/compliance/rescan"): COMPLIANCE_WRITE,
    ("GET", "/violations"): COMPLIANCE_READ,
    ("PATCH", "/violations/{violation_id}"): COMPLIANCE_WRITE,
    ("POST", "/violations/{violation_id}/notes"): COMPLIANCE_WRITE,
    ("GET", "/compliance/policy-export"): POLICY_EXPORT,
    # --- knowledge base ----------------------------------------------------
    ("GET", "/kb/documents"): KB_READ,
    ("GET", "/kb/documents/{document_id}"): KB_READ,
    ("GET", "/kb/documents/{document_id}/chunks"): KB_READ,
    ("GET", "/kb/faqs"): KB_READ,
    ("GET", "/kb/gaps"): KB_READ,
    ("GET", "/kb/index-jobs/{job_id}"): KB_READ,
    ("GET", "/kb/snapshots"): KB_READ,
    ("GET", "/kb/stats"): KB_READ,
    ("POST", "/kb/retrieve"): KB_READ,
    ("POST", "/kb/documents"): KB_WRITE,
    ("PATCH", "/kb/documents/{document_id}"): KB_WRITE,
    ("DELETE", "/kb/documents/{document_id}"): KB_WRITE,
    ("POST", "/kb/documents/purge"): KB_WRITE,
    ("POST", "/kb/documents/{document_id}/reindex"): KB_WRITE,
    ("POST", "/kb/documents/{document_id}/versions"): KB_WRITE,
    ("POST", "/kb/faqs"): KB_WRITE,
    ("PATCH", "/kb/faqs/{faq_id}"): KB_WRITE,
    ("DELETE", "/kb/faqs/{faq_id}"): KB_WRITE,
    ("POST", "/kb/gaps/{gap_id}/link"): KB_WRITE,
    ("POST", "/kb/ingest/source-db"): KB_WRITE,
    ("POST", "/kb/reindex-all"): KB_WRITE,
    ("POST", "/kb/snapshots"): KB_WRITE,
    # --- leads -------------------------------------------------------------
    ("GET", "/leads"): LEADS_READ,
    ("GET", "/leads/metrics"): LEADS_READ,
    ("POST", "/leads"): LEADS_WRITE,
    ("PATCH", "/leads/{lead_id}"): LEADS_WRITE,
    ("POST", "/leads/{lead_id}/followups"): LEADS_WRITE,
    ("POST", "/leads/{lead_id}/revalidate"): LEADS_WRITE,
    # --- supervisor / floor ------------------------------------------------
    # Watching the floor is not supervising it. Gated on the write
    # permission, an oversight role could not open the screen it oversees,
    # and anyone who could watch could also intervene.
    ("GET", "/floor"): SUPERVISOR_READ,
    ("GET", "/floor/copilot/{interaction_id}"): SUPERVISOR_READ,
    ("GET", "/floor/copilot/{interaction_id}/stream"): SUPERVISOR_READ,
    ("GET", "/floor/approvals"): SUPERVISOR_READ,
    ("POST", "/floor/approvals/{job_id}/signal"): SUPERVISOR_WRITE,
    ("POST", "/floor/alerts/{alert_id}/ack"): SUPERVISOR_WRITE,
    ("POST", "/supervisor-actions"): SUPERVISOR_WRITE,
    # --- integrations ------------------------------------------------------
    ("GET", "/event-types"): INTEGRATIONS_READ,
    ("GET", "/providers"): INTEGRATIONS_READ,
    ("GET", "/providers/{provider_id}/test-logs"): INTEGRATIONS_READ,
    ("PATCH", "/providers/{provider_id}/configs/{environment}"): INTEGRATIONS_WRITE,
    ("POST", "/providers/{provider_id}/test"): INTEGRATIONS_WRITE,
    ("GET", "/metrics"): OBSERVABILITY_READ,
    ("GET", "/webhook-deliveries"): INTEGRATIONS_READ,
    ("GET", "/webhook-endpoints"): INTEGRATIONS_READ,
    ("POST", "/webhook-deliveries/{delivery_id}/retry"): INTEGRATIONS_WRITE,
    ("POST", "/webhook-endpoints"): INTEGRATIONS_WRITE,
    ("PATCH", "/webhook-endpoints/{endpoint_id}"): INTEGRATIONS_WRITE,
    ("DELETE", "/webhook-endpoints/{endpoint_id}"): INTEGRATIONS_WRITE,
    ("POST", "/webhook-endpoints/{endpoint_id}/rotate-secret"): INTEGRATIONS_WRITE,
    ("POST", "/webhook-endpoints/{endpoint_id}/test"): INTEGRATIONS_WRITE,
    # --- platform switches -------------------------------------------------
    # Reading is BOT_READ so the state is visible to anyone who can see the
    # Roles screen. Flipping the master outbound gate is ADMIN_WRITE: it decides
    # whether the product may telephone real people, which is the same class of
    # authority as granting agent.publish.
    ("GET", "/platform/switches"): BOT_READ,
    ("PATCH", "/platform/switches/{key}"): ADMIN_WRITE,
    # --- voice operation ---------------------------------------------------
    ("GET", "/voice/status"): BOT_READ,
    ("GET", "/twilio/voice/status"): BOT_READ,
    ("GET", "/demo/outbound-call"): BOT_READ,
    ("POST", "/demo/outbound-call"): VOICE_OPERATE,
    ("POST", "/twilio/voice/outbound"): VOICE_OPERATE,
    ("POST", "/voice/sandbox/start"): VOICE_OPERATE,
    ("POST", "/voice/sandbox/{session_id}/stop"): VOICE_OPERATE,
    ("POST", "/voice/sandbox/{session_id}/tune"): VOICE_OPERATE,
    ("POST", "/stt/transcribe"): VOICE_OPERATE,
    ("POST", "/tts/preview"): VOICE_OPERATE,
}


class PermissionDenied(Exception):
    """Raised by :func:`check` — ``main`` maps this to a 403."""

    def __init__(self, permission: str) -> None:
        super().__init__(permission)
        self.permission = permission


# ---------------------------------------------------------------------------
# Enforcement switch
# ---------------------------------------------------------------------------


def enforcement_enabled() -> bool:
    """True when route permissions are checked.

    Defaults to "on exactly when authentication is on", so a local run with no
    credentials behaves as it always has, and a production boot — which already
    refuses to start without ``API_KEY``/``API_KEY_MAP`` — is gated.
    """
    raw = (os.getenv("AUTHZ_ENFORCE") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False

    import actor_context

    return bool((os.getenv("API_KEY") or "").strip() or actor_context.parse_api_key_map())


# ---------------------------------------------------------------------------
# Grant resolution (TTL-cached; roles change rarely, this is on every request)
# ---------------------------------------------------------------------------

_PERMS_TTL_S = max(1.0, env_float("AUTHZ_CACHE_TTL_S", 30.0))
_PERMS_MAX = 512
_perms_cache: dict[str, tuple[float, frozenset[str]]] = {}
_perms_lock = threading.Lock()


def invalidate_permission_cache(user_id: str | None = None) -> None:
    """Drop cached grants for one user (or all) — call after a role change.

    Clears the role-name cache alongside the permission cache: both derive from
    ``user_roles``, so a change that invalidates one always invalidates the
    other, and leaving them to expire independently would mean a window where a
    user's permissions and their visibility disagreed about what role they hold.
    """
    with _perms_lock:
        if user_id is None:
            _perms_cache.clear()
            _roles_cache.clear()
        else:
            _perms_cache.pop(user_id, None)
            _roles_cache.pop(user_id, None)


def _normalize_role(name: str | None) -> str:
    return (name or "").strip().lower().replace("-", "_").replace(" ", "_")


def _load_grants(user_id: str) -> frozenset[str]:
    """Resolve grants from the database. See the module docstring for policy."""
    from sqlalchemy import text

    import db

    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT r.id AS role_id, r.name AS role_name, rp.permission_id
                  FROM user_roles ur
                  JOIN roles r ON r.id = ur.role_id
             LEFT JOIN role_permissions rp ON rp.role_id = r.id
                 WHERE ur.user_id = :uid
                """
            ),
            {"uid": user_id},
        ).mappings().all()

    explicit_by_role: dict[str, set[str]] = {}
    role_names: dict[str, str] = {}
    for row in rows:
        role_id = row["role_id"]
        role_names[role_id] = _normalize_role(row["role_name"])
        bucket = explicit_by_role.setdefault(role_id, set())
        if row["permission_id"]:
            bucket.add(row["permission_id"])

    granted: set[str] = set()
    for role_id, explicit in explicit_by_role.items():
        if explicit:
            # The database has an opinion about this role — it is authoritative,
            # so a revoked grant stays revoked.
            granted |= explicit
        else:
            granted |= ROLE_DEFAULTS.get(role_names.get(role_id, ""), frozenset())

    # Superuser: matches db.actor_is_admin, which also treats an 'admin' role
    # name as sufficient.
    if ADMIN_WRITE in granted or "admin" in set(role_names.values()):
        return ALL_PERMISSIONS
    return frozenset(granted)


def actor_permissions(user_id: str) -> frozenset[str]:
    """Cached permission set for ``user_id``. Empty set on any failure."""
    uid = (user_id or "").strip()
    if not uid:
        return frozenset()

    now = time.monotonic()
    with _perms_lock:
        hit = _perms_cache.get(uid)
        if hit is not None and now - hit[0] < _PERMS_TTL_S:
            return hit[1]

    try:
        perms = _load_grants(uid)
    except Exception:
        # Fail closed: an unreadable grant table must not become "allow".
        logger.exception("authz grant lookup failed for %s", uid)
        return frozenset()

    with _perms_lock:
        if len(_perms_cache) >= _PERMS_MAX:
            oldest = min(_perms_cache, key=lambda k: _perms_cache[k][0])
            _perms_cache.pop(oldest, None)
        _perms_cache[uid] = (now, perms)
    return perms


def has_permission(user_id: str, permission: str) -> bool:
    return permission in actor_permissions(user_id)


_roles_cache: dict[str, tuple[float, frozenset[str]]] = {}


def actor_roles(user_id: str) -> frozenset[str]:
    """Normalized role names held by ``user_id``. Empty set on any failure.

    ``actor_permissions`` deliberately throws the role names away — a permission
    check should ask what you may do, never who you are. Object-level
    visibility genuinely needs the identity: "which customers" is answered by
    the shape of the role (an agent's own book, a supervisor's teams), not by a
    permission flag. Kept here rather than in ``visibility`` so role resolution
    has one implementation and one cache-invalidation story.

    Fails closed like its sibling: an unreadable table yields no roles, which
    :mod:`visibility` treats as the most restricted scope.
    """
    from sqlalchemy import text

    uid = (user_id or "").strip()
    if not uid:
        return frozenset()

    now = time.monotonic()
    with _perms_lock:
        hit = _roles_cache.get(uid)
        if hit is not None and now - hit[0] < _PERMS_TTL_S:
            return hit[1]

    try:
        import db

        with db.engine.connect() as conn:
            names = frozenset(
                _normalize_role(row[0])
                for row in conn.execute(
                    text(
                        "SELECT r.name FROM user_roles ur "
                        "  JOIN roles r ON r.id = ur.role_id "
                        " WHERE ur.user_id = :uid"
                    ),
                    {"uid": uid},
                )
            )
    except Exception:
        logger.exception("authz role lookup failed for %s", uid)
        return frozenset()

    with _perms_lock:
        if len(_roles_cache) >= _PERMS_MAX:
            oldest = min(_roles_cache, key=lambda k: _roles_cache[k][0])
            _roles_cache.pop(oldest, None)
        _roles_cache[uid] = (now, names)
    return names


# ---------------------------------------------------------------------------
# Request-time check
# ---------------------------------------------------------------------------


def required_permission(method: str, path_template: str) -> str | None:
    """Permission for a route, or ``None`` when the route is public."""
    key = (method.upper(), path_template)
    if key in PUBLIC_ROUTES:
        return None
    return ROUTE_PERMISSIONS.get(key)


def check(method: str, path_template: str, user_id: str | None) -> None:
    """Raise :class:`PermissionDenied` when ``user_id`` may not call the route.

    An unregistered route is denied rather than allowed — a new endpoint that
    nobody classified must not be reachable. ``assert_registry_covers`` turns
    that runtime denial into a test failure at build time.
    """
    if not enforcement_enabled():
        return
    key = (method.upper(), path_template)
    if key in PUBLIC_ROUTES:
        return
    permission = ROUTE_PERMISSIONS.get(key)
    if permission is None:
        logger.error(
            "route %s %s has no authz registry entry — denying", key[0], key[1]
        )
        raise PermissionDenied("unregistered_route")
    if not has_permission(user_id or "", permission):
        raise PermissionDenied(permission)


# ---------------------------------------------------------------------------
# Catalog bootstrap + registry coverage
# ---------------------------------------------------------------------------


def ensure_permission_catalog(engine: Any | None = None) -> int:
    """Upsert :data:`PERMISSION_CATALOG` so operators can grant these in the UI.

    Catalog rows only — never grants. Adding a permission nobody holds cannot
    widen access, whereas re-seeding ``role_permissions`` would silently undo an
    operator's revocation on the next boot.
    """
    from sqlalchemy import text

    if engine is None:
        import db

        engine = db.engine

    written = 0
    with engine.begin() as conn:
        for pid, module, action, description in PERMISSION_CATALOG:
            result = conn.execute(
                text(
                    """
                    INSERT INTO permissions (id, module, action, description)
                    VALUES (:id, :module, :action, :description)
                    ON CONFLICT (id) DO UPDATE
                       SET module = EXCLUDED.module,
                           action = EXCLUDED.action,
                           description = COALESCE(EXCLUDED.description, permissions.description),
                           updated_at = now()
                    """
                ),
                {"id": pid, "module": module, "action": action, "description": description},
            )
            written += result.rowcount or 0
    return written


def assert_registry_covers(routes: Iterable[tuple[str, str]]) -> None:
    """Raise when a route is neither registered nor explicitly public.

    ``routes`` is ``(method, path_template)`` pairs. Called from the coverage
    test so an ungated endpoint fails CI instead of shipping.
    """
    missing = sorted(
        f"{method} {path}"
        for method, path in routes
        if (method.upper(), path) not in PUBLIC_ROUTES
        and (method.upper(), path) not in ROUTE_PERMISSIONS
    )
    if missing:
        raise AssertionError(
            "routes with no authz classification (add to ROUTE_PERMISSIONS or "
            "PUBLIC_ROUTES in authz.py):\n  " + "\n  ".join(missing)
        )
