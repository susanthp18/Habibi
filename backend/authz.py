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
``role_permissions`` is authoritative when the role has any explicit grant
**or** has been configured (``roles.configured_at`` is set). A role that has
never been configured and has no grant rows falls back to the built-in default
for its name, so a fresh database with no permission seed is usable rather than
locked out. Once an operator saves grants — including the empty set — the
database wins entirely and a revoked grant stays revoked. ``perm-admin-write``
is a superuser grant, matching the existing semantics of
:func:`db.actor_is_admin`.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Iterable

from env_utils import env_bool, env_float

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
TOOL_APPROVE = "perm-tool-approve"
EVAL_RUN = "perm-eval-run"
POLICY_EXPORT = "perm-policy-export"
POLICY_READ = "perm-policy-read"
POLICY_PUBLISH = "perm-policy-publish"
POLICY_APPROVE = "perm-policy-approve"
#: Tenant-less (global) rows: statutory rule sets and the platform budget.
#: Row security admits them to every tenant for reading and to none for
#: writing, except inside ``platform_scope.enter`` -- which requires this.
PLATFORM_WRITE = "perm-platform-write"
SUBJECT_RIGHTS_READ = "perm-subject-rights-read"
SUBJECT_RIGHTS_WRITE = "perm-subject-rights-write"
VOICE_OPERATE = "perm-voice-operate"
SUPERVISOR_READ = "perm-supervisor-read"
SUPERVISOR_WRITE = "perm-supervisor-write"
INTEGRATIONS_READ = "perm-integrations-read"
INTEGRATIONS_WRITE = "perm-integrations-write"
OBSERVABILITY_READ = "perm-observability-read"
BANK_BOUNDARY_READ = "perm-bank-boundary-read"
BANK_BOUNDARY_WRITE = "perm-bank-boundary-write"
#: Object-level scope. Which customers an actor may see was decided by the
#: *name* of their role ("supervisor" → their teams, "qa_reviewer" → everyone)
#: in a second table nobody could edit from the Roles screen; a renamed role
#: silently changed its reach. Now the reach is a grant like any other.
CUSTOMERS_READ_TEAM = "perm-customers-read-team"
CUSTOMERS_READ_ALL = "perm-customers-read-all"
#: Raw PII inside compliance findings, likewise: was Admin/Compliance/DPO by
#: name (db_redaction._actor_can_view_raw_pii).
PII_RAW_READ = "perm-pii-raw-read"


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
    (TOOL_APPROVE, "integrations", "approve_tool", "Approve or revoke a reviewed Voice Studio tool revision"),
    (EVAL_RUN, "eval", "run", "Run regression eval suites against a card"),
    (POLICY_EXPORT, "policy", "export", "Download the OPA/Cedar projection of live Python policy"),
    (POLICY_READ, "policy", "read", "Read the versioned policy catalogue"),
    (POLICY_PUBLISH, "policy", "publish", "Submit a policy draft for approval"),
    (POLICY_APPROVE, "policy", "approve", "Approve or reject a policy publication"),
    (
        PLATFORM_WRITE,
        "platform",
        "write",
        "Change platform-wide records every tenant reads: statutory rule sets and the platform budget",
    ),
    (SUBJECT_RIGHTS_READ, "subject_rights", "read", "Read DPDP subject requests and evidence packs"),
    (SUBJECT_RIGHTS_WRITE, "subject_rights", "write", "Create and progress DPDP subject requests"),
    (VOICE_OPERATE, "voice", "operate", "Place outbound calls and run voice sandbox sessions"),
    (SUPERVISOR_READ, "supervisor", "read", "View the live floor: agent presence, live alerts"),
    (SUPERVISOR_WRITE, "supervisor", "write", "Floor supervision, takeover and handoff actions"),
    (INTEGRATIONS_READ, "integrations", "read", "View providers, connectors, vault refs and our MCP"),
    (INTEGRATIONS_WRITE, "integrations", "write", "Configure providers, connectors, vault secrets and MCP keys"),
    (OBSERVABILITY_READ, "observability", "read", "Scrape /metrics (service accounts and operators)"),
    (BANK_BOUNDARY_READ, "bank_boundary", "read", "Read bank-boundary contracts, manifests, readiness and outbox"),
    (BANK_BOUNDARY_WRITE, "bank_boundary", "write", "Ingest bank-boundary manifests and file complaints"),
    (CUSTOMERS_READ_TEAM, "customers", "read_team", "See the customers of every agent on the teams you supervise"),
    (CUSTOMERS_READ_ALL, "customers", "read_all", "See every customer in the tenant (oversight roles)"),
    (PII_RAW_READ, "compliance", "raw_pii", "Read unredacted PII inside compliance findings"),
)

ALL_PERMISSIONS: frozenset[str] = frozenset(p[0] for p in PERMISSION_CATALOG)

#: Permissions that existed and gated no route. Removed from the catalog table
#: on the next boot so the Roles screen stops offering them.
RETIRED_PERMISSIONS: frozenset[str] = frozenset({"perm-redteam-run"})


#: Fallback grants, keyed by normalized role name. Applied only to a role that
#: has never been configured *and* has no row in ``role_permissions`` — see
#: the module docstring.
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
            POLICY_READ, SUBJECT_RIGHTS_READ, BANK_BOUNDARY_READ,
            KB_READ, BOT_READ,
            VOICE_OPERATE, SUPERVISOR_READ, SUPERVISOR_WRITE,
            INTEGRATIONS_READ, OBSERVABILITY_READ,
            CUSTOMERS_READ_TEAM,
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
            # A reviewer restricted to one agent's calls cannot sample across
            # agents, which is the whole job.
            CUSTOMERS_READ_ALL,
        }
    ),
    "compliance_officer": frozenset(
        {
            CUSTOMERS_READ, INTERACTIONS_READ, COLLECTIONS_READ, CONSENT_READ,
            ANALYTICS_READ, QA_REVIEW,
            COMPLIANCE_READ, COMPLIANCE_WRITE,
            POLICY_READ, POLICY_PUBLISH, POLICY_APPROVE,
            SUBJECT_RIGHTS_READ, SUBJECT_RIGHTS_WRITE,
            BANK_BOUNDARY_READ, BANK_BOUNDARY_WRITE,
            KB_READ,
            CUSTOMERS_READ_ALL, PII_RAW_READ,
        }
    ),
    # Assigned when an admin (or an invite) grants Viewer. Not auto-applied
    # on first login — uninvited SSO users request access instead. Writes,
    # voice placement, and admin grants stay off.
    "viewer": frozenset(
        {
            CUSTOMERS_READ, CUSTOMERS_READ_ALL,
            INTERACTIONS_READ,
            COLLECTIONS_READ,
            LEADS_READ,
            CONSENT_READ,
            ANALYTICS_READ, BILLING_READ,
            QA_REVIEW,
            COMPLIANCE_READ,
            POLICY_READ, SUBJECT_RIGHTS_READ, BANK_BOUNDARY_READ,
            KB_READ, BOT_READ,
            SUPERVISOR_READ,
            INTEGRATIONS_READ,
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
        ("POST", "/twilio/voice/connect"),
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
        # Sandbox Live from the browser; a single-use ticket is the credential.
        # AgentStudio live calls; a one-use ticket from the gateway is the credential.
        ("WS", "/studio-ws/{ticket}/{path:path}"),
        # Voice Studio engine hooks; the shared hook token is the credential.
        ("POST", "/voice-studio/hooks/tools/{name}"),
        ("POST", "/voice-studio/hooks/precall"),
        ("POST", "/voice-studio/hooks/transfer"),
        ("POST", "/voice-studio/hooks/run-completed"),
        ("POST", "/api/offer"),
        ("PATCH", "/api/offer"),
        ("POST", "/voice-rtc/api/offer"),
        ("PATCH", "/voice-rtc/api/offer"),
        # Self-scoped.
        ("GET", "/me"),
        ("GET", "/me/presence"),
        ("PATCH", "/me/presence"),
        # Any signed-in operator may ask for a page they cannot open.
        ("POST", "/access-requests"),
        ("GET", "/.well-known/agent-card.json"),
        ("POST", "/a2a"),
    }
)


#: ``(method, path template) -> permission id``. Kept sorted by path so it reads
#: as a policy table. Every non-public route in the app must appear here;
#: :func:`assert_registry_covers` enforces that.
ROUTE_PERMISSIONS: dict[tuple[str, str], str] = {
    # --- AgentStudio gateway -------------------------------------------------
    # The floor for touching the engine at all; each request is then checked
    # against routers/agentstudio_gateway.PERMISSION_RULES by engine path.
    ("POST", "/studio-api/_ws-ticket"): BOT_READ,
    ("GET", "/studio-api/{path:path}"): BOT_READ,
    ("POST", "/studio-api/{path:path}"): BOT_READ,
    ("PUT", "/studio-api/{path:path}"): BOT_READ,
    ("PATCH", "/studio-api/{path:path}"): BOT_READ,
    ("DELETE", "/studio-api/{path:path}"): BOT_READ,
    ("GET", "/studio-mcp/"): BOT_READ,
    ("POST", "/studio-mcp/"): BOT_READ,
    ("DELETE", "/studio-mcp/"): BOT_READ,
    ("GET", "/studio-mcp"): BOT_READ,
    ("POST", "/studio-mcp"): BOT_READ,
    ("DELETE", "/studio-mcp"): BOT_READ,
    ("GET", "/voice-studio/guardrails/{workflow_id}"): BOT_READ,
    ("PUT", "/voice-studio/guardrails/{workflow_id}"): AGENT_EDIT,
    ("GET", "/voice-studio/checks/scenarios"): BOT_READ,
    ("GET", "/voice-studio/checks"): BOT_READ,
    ("POST", "/voice-studio/checks"): EVAL_RUN,
    ("GET", "/voice-studio/routing"): BOT_READ,
    ("POST", "/voice-studio/routing/check"): BOT_READ,
    ("PUT", "/voice-studio/routing"): AGENT_PUBLISH,
    ("GET", "/voice-studio/agents/{workflow_id}/preflight"): BOT_READ,
    ("POST", "/voice-studio/agents/{workflow_id}/publish"): AGENT_PUBLISH,
    ("POST", "/voice-studio/agents/{workflow_id}/rollback"): AGENT_PUBLISH,
    ("GET", "/voice-studio/releases"): BOT_READ,
    ("POST", "/voice-studio/prompt/lint"): BOT_READ,
    ("POST", "/voice-studio/checks/simulate"): EVAL_RUN,
    ("POST", "/voice-studio/releases/reconcile"): AGENT_PUBLISH,
    ("POST", "/voice-studio/tools/{tool_uuid}/revisions/{revision}/review"): TOOL_APPROVE,
    ("GET", "/voice-studio/mcp-keys"): AGENT_EDIT,
    ("POST", "/voice-studio/mcp-keys"): AGENT_EDIT,
    ("POST", "/voice-studio/mcp-keys/{key_id}/rotate"): AGENT_EDIT,
    ("DELETE", "/voice-studio/mcp-keys/{key_id}"): AGENT_EDIT,
    # --- billing -----------------------------------------------------------
    ("GET", "/billing"): BILLING_READ,
    ("GET", "/billing/export.csv"): BILLING_READ,
    ("POST", "/billing/budgets/{budget_id}/rules"): BILLING_WRITE,
    ("PATCH", "/billing/budgets/{budget_id}/rules/{rule_id}"): BILLING_WRITE,
    ("DELETE", "/billing/budgets/{budget_id}/rules/{rule_id}"): BILLING_WRITE,
    # --- analytics ---------------------------------------------------------
    ("GET", "/bot-analytics"): ANALYTICS_READ,
    ("GET", "/dashboard"): ANALYTICS_READ,
    ("GET", "/dashboard.csv"): ANALYTICS_READ,
    ("GET", "/offers/health"): ANALYTICS_READ,
    ("GET", "/workspace/summary"): ANALYTICS_READ,
    # Reading the queue is a read. This was WORKQUEUE_WRITE, which meant an
    # oversight role could not open the screen it oversees while anyone able to
    # open it could also claim from it — a permission that gates a GET on the
    # right to mutate is wrong in both directions.
    ("GET", "/work-items"): COLLECTIONS_READ,
    # --- integrations, access and routing ------------------------------------
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
    ("GET", "/eval/disagreements"): QA_REVIEW,
    ("GET", "/roles"): ADMIN_WRITE,
    ("PATCH", "/roles/{role_id}/permissions"): ADMIN_WRITE,
    ("GET", "/users"): ADMIN_WRITE,
    ("PUT", "/users/{user_id}/roles"): ADMIN_WRITE,
    ("PATCH", "/users/{user_id}"): ADMIN_WRITE,
    ("GET", "/invites"): ADMIN_WRITE,
    ("POST", "/invites"): ADMIN_WRITE,
    ("POST", "/invites/{invite_id}/resend"): ADMIN_WRITE,
    ("POST", "/invites/{invite_id}/revoke"): ADMIN_WRITE,
    ("GET", "/access-requests"): ADMIN_WRITE,
    ("POST", "/access-requests/{request_id}/approve"): ADMIN_WRITE,
    ("POST", "/access-requests/{request_id}/deny"): ADMIN_WRITE,
    ("GET", "/routing-audit"): BOT_READ,
    ("GET", "/routing-rules"): BOT_READ,
    ("GET", "/routing-rules/{rule_id}/executions"): BOT_READ,
    ("POST", "/routing-rules"): BOT_WRITE,
    ("POST", "/routing-rules/reorder"): BOT_WRITE,
    ("POST", "/routing-rules/simulate"): BOT_READ,
    ("PATCH", "/routing-rules/{rule_id}"): BOT_WRITE,
    ("DELETE", "/routing-rules/{rule_id}"): BOT_WRITE,
    ("POST", "/sandbox/payment-events"): COLLECTIONS_WRITE,
    ("GET", "/work-runtime/jobs/{job_id}"): COLLECTIONS_READ,
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
        ("POST", "/promises/{promise_id}/revise"): COLLECTIONS_WRITE,
        ("POST", "/promises/{promise_id}/cancel"): COLLECTIONS_WRITE,
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
    ("POST", "/treatment/decisions/{decision_id}/feedback"): COLLECTIONS_WRITE,
    ("POST", "/treatment/decisions/{decision_id}/enact"): COLLECTIONS_WRITE,
    ("GET", "/treatment/ops/{kind}"): COLLECTIONS_READ,
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
    ("POST", "/customers/{customer_id}/outreach"): INTERACTIONS_WRITE,
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
    ("GET", "/interactions/{interaction_id}/recording"): INTERACTIONS_READ,
    ("GET", "/interactions/{interaction_id}/trace"): INTERACTIONS_READ,
    ("GET", "/handoff/active"): INTERACTIONS_READ,
    ("GET", "/handoff/queue"): INTERACTIONS_READ,
    ("GET", "/handoff/{interaction_id}"): INTERACTIONS_READ,
    ("POST", "/handoff/{interaction_id}/claim"): INTERACTIONS_WRITE,
    ("POST", "/handoff/{interaction_id}/disclosures"): INTERACTIONS_WRITE,
    ("POST", "/handoff/{interaction_id}/suggestions/{suggestion_id}/accept"): INTERACTIONS_WRITE,
    # --- compliance / redaction --------------------------------------------
    ("GET", "/export-jobs"): COMPLIANCE_READ,
    # ANALYTICS_READ is the floor so leadership can email a dashboard CSV.
    # Redaction ZIPs still require COMPLIANCE_WRITE inside the handler.
    ("POST", "/export-jobs"): ANALYTICS_READ,
    ("PATCH", "/export-jobs/{job_id}"): COMPLIANCE_WRITE,
    # Dashboard CSVs are an analytics read; redaction bundles still need
    # COMPLIANCE_READ, checked in the handler from the job's kind.
    ("GET", "/export-jobs/{job_id}/download"): ANALYTICS_READ,
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
    ("GET", "/compliance/policy-rules"): POLICY_READ,
    ("POST", "/compliance/policy-rules"): POLICY_PUBLISH,
    ("POST", "/compliance/policy-rules/{set_id}/submit"): POLICY_PUBLISH,
    ("POST", "/compliance/policy-rules/{set_id}/approve"): POLICY_APPROVE,
    ("POST", "/compliance/policy-rules/{set_id}/reject"): POLICY_APPROVE,
    ("POST", "/compliance/policy-replay"): POLICY_READ,
    ("GET", "/compliance/complaint-pack/{customer_id}"): SUBJECT_RIGHTS_READ,
    ("GET", "/compliance/subject-requests"): SUBJECT_RIGHTS_READ,
    ("POST", "/compliance/subject-requests"): SUBJECT_RIGHTS_WRITE,
    ("POST", "/compliance/subject-requests/{request_id}/transition"): SUBJECT_RIGHTS_WRITE,
    ("POST", "/compliance/security-incidents"): COMPLIANCE_WRITE,
    ("GET", "/compliance/security-incidents"): COMPLIANCE_READ,
    ("GET", "/integrations/bank/contracts"): BANK_BOUNDARY_READ,
    ("GET", "/integrations/bank/manifests"): BANK_BOUNDARY_READ,
    ("POST", "/integrations/bank/manifests"): BANK_BOUNDARY_WRITE,
    ("GET", "/integrations/bank/reconciliation"): BANK_BOUNDARY_READ,
    ("GET", "/integrations/bank/readiness"): BANK_BOUNDARY_READ,
    ("GET", "/integrations/bank/outbox"): BANK_BOUNDARY_READ,
    ("GET", "/integrations/bank/breach-coverage"): BANK_BOUNDARY_READ,
    ("GET", "/integrations/bank/fairness"): BANK_BOUNDARY_READ,
    ("POST", "/integrations/bank/complaints"): BANK_BOUNDARY_WRITE,
    ("GET", "/integrations/bank/complaints"): BANK_BOUNDARY_READ,
    # --- leads -------------------------------------------------------------
    ("GET", "/leads"): LEADS_READ,
    ("GET", "/leads/metrics"): LEADS_READ,
    # A borrower's answer to a deferred offer. LEADS_WRITE rather than
    # COLLECTIONS_WRITE: the row it closes is the sales side of the call, and
    # since W12 nobody on the collections side can have spoken the offer at all.
    ("POST", "/offers/{decisionId}/response"): LEADS_WRITE,
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
    ("GET", "/twilio/voice/status"): BOT_READ,
    ("GET", "/demo/outbound-call"): BOT_READ,
    ("POST", "/demo/outbound-call"): VOICE_OPERATE,
    ("POST", "/twilio/voice/outbound"): VOICE_OPERATE,
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
    import actor_context

    # Unset, blank, and a spelling that is in neither set all use this
    # default — the same contract as ``env_int``. Peeking emptiness and then
    # calling ``env_bool`` with an implicit ``False`` would treat a typo as
    # "off" and leave a production boot with ``API_KEY`` ungated.
    import entra

    default = bool(
        (os.getenv("API_KEY") or "").strip()
        or actor_context.parse_api_key_map()
        or entra.configured()
    )
    return env_bool("AUTHZ_ENFORCE", default=default)


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


def resolve_role_grants(
    role_name: str,
    explicit: Iterable[str],
    *,
    configured: bool,
) -> frozenset[str]:
    """Return the grants the enforcer will honour for one role.

    ``explicit`` is the ``role_permissions`` set (empty if none).
    ``configured`` is true once :func:`db.replace_role_permissions` has written
    an opinion, including the opinion "none". An unconfigured role with no rows
    falls back to :data:`ROLE_DEFAULTS`; a configured role with no rows is
    empty. Admin-by-name is still a superuser — that short-circuit is part of
    what the enforcer actually grants, so the Roles screen must report it.
    """
    name = _normalize_role(role_name)
    explicit_set = frozenset(p for p in explicit if p)
    if explicit_set or configured:
        granted = set(explicit_set)
    else:
        granted = set(ROLE_DEFAULTS.get(name, frozenset()))
    if ADMIN_WRITE in granted or name == "admin":
        return ALL_PERMISSIONS
    return frozenset(granted)


def _load_grants(user_id: str) -> frozenset[str]:
    """Resolve grants from the database. See the module docstring for policy."""
    from sqlalchemy import text

    import db

    with db.engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM users WHERE id = :uid"),
            {"uid": user_id},
        ).scalar()
        if str(status or "") != "active":
            return frozenset()
        rows = conn.execute(
            text(
                """
                SELECT r.id AS role_id, r.name AS role_name, r.configured_at,
                       rp.permission_id
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
    configured_by_role: dict[str, bool] = {}
    for row in rows:
        role_id = row["role_id"]
        role_names[role_id] = row["role_name"]
        configured_by_role[role_id] = row["configured_at"] is not None
        bucket = explicit_by_role.setdefault(role_id, set())
        if row["permission_id"]:
            bucket.add(row["permission_id"])

    granted: set[str] = set()
    for role_id, explicit in explicit_by_role.items():
        granted |= resolve_role_grants(
            role_names[role_id],
            explicit,
            configured=configured_by_role[role_id],
        )

    # Superuser: matches db.actor_is_admin, which also treats an 'admin' role
    # name as sufficient. Kept at user level so a holder of any admin-named
    # role (or of ADMIN_WRITE via another role) cannot be partially gated.
    if ADMIN_WRITE in granted or "admin" in {
        _normalize_role(n) for n in role_names.values()
    }:
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
        # A permission the route table no longer names is a checkbox on the
        # Roles screen that controls nothing. `perm-redteam-run` sat there
        # for months; the red-team route is `EVAL_RUN`. Retired rows go, and
        # their grants with them -- a grant to nothing is not a revocation.
        conn.execute(
            text(
                "DELETE FROM role_permissions WHERE permission_id = ANY(CAST(:ids AS text[]))"
            ),
            {"ids": list(RETIRED_PERMISSIONS)},
        )
        conn.execute(
            text("DELETE FROM permissions WHERE id = ANY(CAST(:ids AS text[]))"),
            {"ids": list(RETIRED_PERMISSIONS)},
        )
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
