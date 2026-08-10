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
import threading
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


# Session-scoped state. A single module-level MeshState meant every concurrent
# call shared one active_role and one history: caller A entering the upsell node
# flipped caller B's specialist mid-sentence, and the transition history was an
# interleaved mix of unrelated calls. Keyed by session_id; `None` is the
# single-session/legacy bucket.
_states: dict[str | None, MeshState] = {}
_states_lock = threading.Lock()


def _state_for(session_id: str | None) -> MeshState:
    with _states_lock:
        state = _states.get(session_id)
        if state is None:
            state = MeshState()
            _states[session_id] = state
        return state


def release_session(session_id: str | None) -> None:
    """Drop a finished call's mesh state so the map does not grow unbounded."""
    with _states_lock:
        _states.pop(session_id, None)


def enabled() -> bool:
    return voice_config.voice_multi_agent_enabled()


def active_role(session_id: str | None = None) -> str:
    return _state_for(session_id).active_role


def activate_role(role: str, session_id: str | None = None) -> str:
    state = _state_for(session_id)
    if not enabled():
        return state.active_role
    return state.activate(role)


def bus_backend() -> str:
    if not enabled():
        return "off"
    return "redis" if voice_config.redis_url() else "local"


def status(session_id: str | None = None) -> dict[str, Any]:
    state = _state_for(session_id)
    return {
        "enabled": enabled(),
        "backend": bus_backend(),
        "activeRole": state.active_role,
        "history": list(state.history),
        "roles": list(ROLES.keys()),
        "redisUrlSet": bool(voice_config.redis_url()),
    }


async def maybe_activate_insurance_on_upsell(session_id: str | None = None) -> str:
    """Called when Flows enters gated_upsell — switches specialist role."""
    if not enabled():
        return active_role(session_id)
    return activate_role("insurance", session_id)


async def maybe_restore_collections(session_id: str | None = None) -> str:
    if not enabled():
        return active_role(session_id)
    return activate_role("collections", session_id)
