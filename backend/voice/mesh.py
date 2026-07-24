"""Multi-agent voice mesh — local specialists + optional RedisBus.

Enabled when ``VOICE_MULTI_AGENT_ENABLED=true``.

Roles
-----
* ``collections`` — default Flows graph (PTP / dispute / escalate)
* ``insurance``   — upsell / product FAQ specialist (activated on gated_upsell)
* ``supervisor_brief`` — short handoff brief for warm transfer (future)

Without ``REDIS_URL`` the mesh stays in-process (LocalWorkerBus). With Redis,
workers can run across processes using Pipecat's RedisBus when available.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from voice import config as voice_config

logger = logging.getLogger(__name__)

SpecialistHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass
class MeshRole:
    name: str
    description: str
    tools: tuple[str, ...] = ()


ROLES: dict[str, MeshRole] = {
    "collections": MeshRole(
        name="collections",
        description="Debt collections, PTP, dispute, callback, escalate",
        tools=(
            "verify_identity",
            "get_account_position",
            "create_promise_to_pay",
            "flag_dispute",
            "request_callback",
            "escalate_to_human",
            "search_knowledge_base",
        ),
    ),
    "insurance": MeshRole(
        name="insurance",
        description="Product eligibility, lead capture, insurance FAQ",
        tools=(
            "check_product_eligibility",
            "capture_lead",
            "request_documents",
            "search_knowledge_base",
            "escalate_to_human",
        ),
    ),
    "supervisor_brief": MeshRole(
        name="supervisor_brief",
        description="Compact handoff brief for warm-transfer agent",
        tools=(),
    ),
}


@dataclass
class MeshState:
    active_role: str = "collections"
    history: list[str] = field(default_factory=list)

    def activate(self, role: str) -> str:
        if role not in ROLES:
            raise ValueError(f"unknown_mesh_role:{role}")
        if role != self.active_role:
            self.history.append(f"{self.active_role}->{role}")
            self.active_role = role
            logger.info("voice mesh role → %s", role)
        return self.active_role


_state = MeshState()


def enabled() -> bool:
    return voice_config.voice_multi_agent_enabled()


def active_role() -> str:
    return _state.active_role


def activate_role(role: str) -> str:
    if not enabled():
        return _state.active_role
    return _state.activate(role)


def bus_backend() -> str:
    if not enabled():
        return "off"
    return "redis" if voice_config.redis_url() else "local"


def status() -> dict[str, Any]:
    return {
        "enabled": enabled(),
        "backend": bus_backend(),
        "activeRole": _state.active_role,
        "history": list(_state.history),
        "roles": list(ROLES.keys()),
        "redisUrlSet": bool(voice_config.redis_url()),
    }


async def maybe_activate_insurance_on_upsell() -> str:
    """Called when Flows enters gated_upsell — switches specialist role."""
    if not enabled():
        return _state.active_role
    return activate_role("insurance")


async def maybe_restore_collections() -> str:
    if not enabled():
        return _state.active_role
    return activate_role("collections")
