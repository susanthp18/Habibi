"""Multi-agent voice mesh — local specialists + optional RedisBus.

Enabled when ``VOICE_MULTI_AGENT_ENABLED=true``.

Roles are data (``mesh_roles.json``), not Python constants. The file is the
shape a future Agent Card subset uses: ``name``, ``description``, ``tools[]``.
Adding a specialist is an edit to that file, not a code change.

Without ``REDIS_URL`` the mesh stays in-process (LocalWorkerBus). With Redis,
workers can run across processes using Pipecat's RedisBus when available.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from voice import config as voice_config

logger = logging.getLogger(__name__)

_ROLES_PATH = Path(__file__).with_name("mesh_roles.json")


@dataclass
class MeshRole:
    name: str
    description: str
    tools: tuple[str, ...] = ()


# Populated by ``reload_roles``. Importers that did ``from voice.mesh import
# ROLES`` keep seeing updates because this is the same dict object.
ROLES: dict[str, MeshRole] = {}


def load_roles(path: Path | None = None) -> dict[str, MeshRole]:
    """Read role cards from JSON. Raises on a malformed pack — silent empty
    would look like a disabled mesh."""
    src = path or _ROLES_PATH
    raw = json.loads(src.read_text(encoding="utf-8"))
    entries = raw.get("roles") if isinstance(raw, dict) else raw
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"mesh_roles_empty:{src}")
    loaded: dict[str, MeshRole] = {}
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError(f"mesh_role_not_object:{src}")
        name = str(item.get("name") or "").strip()
        if not name:
            raise ValueError(f"mesh_role_missing_name:{src}")
        if name in loaded:
            raise ValueError(f"mesh_role_duplicate:{name}")
        tools = item.get("tools") or ()
        if not isinstance(tools, (list, tuple)) or any(
            not isinstance(t, str) or not t.strip() for t in tools
        ):
            raise ValueError(f"mesh_role_invalid_tools:{name}")
        loaded[name] = MeshRole(
            name=name,
            description=str(item.get("description") or ""),
            tools=tuple(str(t).strip() for t in tools),
        )
    return loaded


def reload_roles(path: Path | None = None) -> dict[str, MeshRole]:
    """Replace the in-process role map. Tests use a temp file; production
    loads ``mesh_roles.json`` once at import."""
    loaded = load_roles(path)
    ROLES.clear()
    ROLES.update(loaded)
    return ROLES


reload_roles()


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
