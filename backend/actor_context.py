"""Request-scoped acting user (audit identity).

Until OIDC/JWT lands, identity is resolved from:
  1. ``API_KEY_MAP`` JSON ``{"secret":"user-id", ...}`` — per-user keys (preferred)
  2. Shared ``API_KEY`` + optional ``X-Actor-User-Id`` (dev / ALLOW_ACTOR_HEADER)
  3. Fallback ``ACTOR_USER_ID`` env

``db._actor_user_id()`` reads the ContextVar set by ApiKeyMiddleware so every
CRM write attributes the real caller, not a process-wide env spoof.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)

_actor_var: ContextVar[str | None] = ContextVar("actor_user_id", default=None)

_DEFAULT_ACTOR = (os.getenv("ACTOR_USER_ID") or "priya-nair").strip() or "priya-nair"

# Cached API_KEY_MAP — env does not change mid-process. Call reload_api_key_map()
# from tests after monkeypatching.
_api_key_map_cache: dict[str, str] | None = None
_api_key_map_lock = threading.Lock()


def default_actor_user_id() -> str:
    return _DEFAULT_ACTOR


def get_actor_user_id() -> str:
    """Current request actor, or process default outside a request."""
    return _actor_var.get() or _DEFAULT_ACTOR


def set_actor_user_id(user_id: str | None):
    """Return a context token; reset with ``_actor_var.reset(token)``."""
    return _actor_var.set((user_id or "").strip() or None)


def reset_actor_user_id(token: Any) -> None:
    _actor_var.reset(token)


def _app_is_prod() -> bool:
    return (os.getenv("APP_ENV") or "dev").strip().lower() in {"prod", "production"}


def _allow_actor_header() -> bool:
    raw = (os.getenv("ALLOW_ACTOR_HEADER") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    # Default: allow in non-prod only (shared API_KEY must not spoof in prod).
    return not _app_is_prod()


def reload_api_key_map() -> dict[str, str]:
    """Force re-parse of ``API_KEY_MAP`` (tests / config reload)."""
    global _api_key_map_cache
    with _api_key_map_lock:
        _api_key_map_cache = _parse_api_key_map_raw()
        return dict(_api_key_map_cache)


def parse_api_key_map() -> dict[str, str]:
    """``API_KEY_MAP`` JSON object: api-key string → users.id (cached)."""
    global _api_key_map_cache
    with _api_key_map_lock:
        if _api_key_map_cache is None:
            _api_key_map_cache = _parse_api_key_map_raw()
        return dict(_api_key_map_cache)


def _parse_api_key_map_raw() -> dict[str, str]:
    raw = (os.getenv("API_KEY_MAP") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("API_KEY_MAP is not valid JSON — ignoring")
        return {}
    if not isinstance(data, dict):
        logger.error("API_KEY_MAP must be a JSON object — ignoring")
        return {}
    out: dict[str, str] = {}
    for k, v in data.items():
        key = str(k).strip()
        uid = str(v).strip()
        if key and uid:
            out[key] = uid
    return out


def _user_exists(user_id: str) -> bool:
    """Lazy import to avoid circular import at module load."""
    import db

    return db.user_exists(user_id)


def validate_configured_actors() -> None:
    """Boot-time check: default actor + every API_KEY_MAP user id must exist.

    Call after DB is up (lifespan). Raises RuntimeError on missing users so a
    typo'd map fails fast instead of per-request.
    """
    missing: list[str] = []
    default = _DEFAULT_ACTOR
    if default and not _user_exists(default):
        missing.append(f"ACTOR_USER_ID={default}")
    for uid in sorted(set(parse_api_key_map().values())):
        if not _user_exists(uid):
            missing.append(f"API_KEY_MAP→{uid}")
    if missing:
        raise RuntimeError(
            "actor identity config references unknown users.id: " + ", ".join(missing)
        )


def _digest_eq(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def resolve_authenticated_actor(
    *,
    provided_key: str,
    actor_header: str | None,
) -> tuple[bool, str | None, str | None]:
    """Validate API key and resolve actor.

    Returns ``(ok, actor_user_id, error_detail)``.
    ``error_detail`` is ``unauthorized`` or ``actor_not_found``.
    """
    key_map = parse_api_key_map()
    if key_map:
        for secret, user_id in key_map.items():
            if _digest_eq(provided_key, secret):
                if not _user_exists(user_id):
                    return False, None, "actor_not_found"
                return True, user_id, None
        # Fall through: also accept legacy single API_KEY if set
        single = (os.getenv("API_KEY") or "").strip()
        if single and _digest_eq(provided_key, single):
            return _resolve_shared_key_actor(actor_header)
        return False, None, "unauthorized"

    single = (os.getenv("API_KEY") or "").strip()
    if not single:
        # Auth disabled — still honour header in non-prod for local multi-agent demos.
        if actor_header and _allow_actor_header():
            header = actor_header.strip()
            if not _user_exists(header):
                return False, None, "actor_not_found"
            return True, header, None
        if not _user_exists(_DEFAULT_ACTOR):
            return False, None, "actor_not_found"
        return True, _DEFAULT_ACTOR, None

    if not _digest_eq(provided_key, single):
        return False, None, "unauthorized"
    return _resolve_shared_key_actor(actor_header)


def _resolve_shared_key_actor(actor_header: str | None) -> tuple[bool, str | None, str | None]:
    header = (actor_header or "").strip()
    if header and _allow_actor_header():
        if not _user_exists(header):
            return False, None, "actor_not_found"
        return True, header, None
    if not _user_exists(_DEFAULT_ACTOR):
        return False, None, "actor_not_found"
    return True, _DEFAULT_ACTOR, None
