"""Role-scoped worker stage names.

``bot_worker --role`` filters the combined drain. Compose services with
``profiles: [split-workers]`` start one role each; the default bot_worker
keeps ``--role all`` so local compose does not multiply the connection budget
until the orchestrator cuts over.
"""

from __future__ import annotations

ROLES: dict[str, frozenset[str]] = {
    "messaging": frozenset(
        {"whatsapp_outbound", "bot_jobs", "promise_reminders", "promise_settle"}
    ),
    "dialer": frozenset(
        {
            "bounce_voice",
            "call_closer",
            "cadence",
            "campaigns",
            "outbound_stale",
            "number_pool_health",
        }
    ),
    "treatment": frozenset(
        {"treatment_enact", "treatment_followthrough", "treatment_sweep"}
    ),
    "integration": frozenset(
        {"webhooks_dispatch", "clerk", "clerk_overdue", "canary"}
    ),
}
