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
import time
from contextvars import ContextVar
from typing import Any

from env_utils import env_float

logger = logging.getLogger(__name__)

_actor_var: ContextVar[str | None] = ContextVar("actor_user_id", default=None)

# Cached API_KEY_MAP — env does not change mid-process. Call reload_api_key_map()
# from tests after monkeypatching.
_api_key_map_cache: dict[str, str] | None = None
_api_key_map_lock = threading.Lock()


def default_actor_user_id() -> str:
    """Read ACTOR_USER_ID at call time (env may change in tests)."""
    return (os.getenv("ACTOR_USER_ID") or "priya-nair").strip() or "priya-nair"


def get_actor_user_id() -> str:
    """Current request actor, or process default outside a request."""
    return _actor_var.get() or default_actor_user_id()


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


# Bounded TTL cache for user-existence lookups. Every authenticated request hit
# the database once (twice on the shared-key path) just to confirm the actor
# still exists — a fixed cost on the hot path for a value that changes rarely.
# TTL-bounded rather than permanent so a deactivated user stops resolving
# within a bounded window; boot-time validate_configured_actors() is unaffected
# because it runs before any request populates the cache.
# Parsed through env_utils so a malformed value falls back instead of raising
# during import — this module is imported by the auth middleware, so a bad
# value here would take the whole API down at boot.
_USER_EXISTS_TTL_S = max(1.0, env_float("ACTOR_USER_CACHE_TTL_S", 30.0))
_USER_EXISTS_MAX = 512
_user_exists_cache: dict[str, tuple[float, bool]] = {}
_user_exists_lock = threading.Lock()


def invalidate_user_exists_cache(user_id: str | None = None) -> None:
    """Drop cached existence for one user (or all) — call after user writes."""
    with _user_exists_lock:
        if user_id is None:
            _user_exists_cache.clear()
        else:
            _user_exists_cache.pop(user_id, None)


def _user_exists(user_id: str) -> bool:
    """Lazy import to avoid circular import at module load."""
    if not user_id:
        return False
    now = time.monotonic()
    with _user_exists_lock:
        hit = _user_exists_cache.get(user_id)
        if hit is not None and now - hit[0] < _USER_EXISTS_TTL_S:
            return hit[1]

    import db

    exists = db.user_exists(user_id)

    with _user_exists_lock:
        if len(_user_exists_cache) >= _USER_EXISTS_MAX:
            # Cheap bound: drop the oldest entry rather than track full LRU.
            oldest = min(_user_exists_cache, key=lambda k: _user_exists_cache[k][0])
            _user_exists_cache.pop(oldest, None)
        _user_exists_cache[user_id] = (now, exists)
    return exists


def validate_configured_actors() -> None:
    """Boot-time check: default actor + every API_KEY_MAP user id must exist.

    Call after DB is up (lifespan). Raises RuntimeError on missing users so a
    typo'd map fails fast instead of per-request.
    """
    missing: list[str] = []
    default = default_actor_user_id()
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
        # Auth disabled — refuse in production; honour header in non-prod only.
        if _app_is_prod():
            return False, None, "unauthorized"
        if actor_header and _allow_actor_header():
            header = actor_header.strip()
            if not _user_exists(header):
                return False, None, "actor_not_found"
            return True, header, None
        default = default_actor_user_id()
        if not _user_exists(default):
            return False, None, "actor_not_found"
        return True, default, None

    if not _digest_eq(provided_key, single):
        return False, None, "unauthorized"
    return _resolve_shared_key_actor(actor_header)


def _resolve_shared_key_actor(actor_header: str | None) -> tuple[bool, str | None, str | None]:
    header = (actor_header or "").strip()
    if header and _allow_actor_header():
        if not _user_exists(header):
            return False, None, "actor_not_found"
        return True, header, None
    default = default_actor_user_id()
    if not _user_exists(default):
        return False, None, "actor_not_found"
    return True, default, None
