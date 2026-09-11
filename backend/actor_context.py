"""Request-scoped acting user (audit identity).

Until OIDC/JWT lands, identity is resolved from:
  1. ``API_KEY_MAP`` JSON ``{"secret":"user-id", ...}`` — per-user keys (preferred)
  2. Shared ``API_KEY`` + optional ``X-Actor-User-Id`` (when ``ALLOW_ACTOR_HEADER`` is on)
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

from env_utils import env_bool, env_float

logger = logging.getLogger(__name__)

_actor_var: ContextVar[str | None] = ContextVar("actor_user_id", default=None)

#: Who is acting when no person is: a worker draining a queue, the voice
#: process serving a call. Unset means a request context -- a human. The
#: audit trail used to write every machine action as ``actor_kind='human'``
#: by the process default user, which is a forgery with a name on it.
_actor_kind_var: ContextVar[str | None] = ContextVar("actor_kind", default=None)
_actor_bot_var: ContextVar[str | None] = ContextVar("actor_bot_id", default=None)

ACTOR_KINDS = frozenset({"human", "bot", "system"})


def bind_service_actor(kind: str = "system", *, bot_id: str | None = None) -> None:
    """Declare this process (or task) a machine actor. Call once at startup.

    ContextVars flow into every task and thread the caller spawns from here,
    so a worker binds at the top of ``main`` and every audit row it writes
    carries ``actor_kind='system'`` (or ``'bot'`` with the bot id) and no
    user id -- there is no user.
    """
    if kind not in ACTOR_KINDS:
        raise ValueError(f"actor kind {kind!r} is not one of {sorted(ACTOR_KINDS)}")
    _actor_kind_var.set(kind)
    _actor_bot_var.set((bot_id or "").strip() or None)


def get_actor_kind() -> str:
    return _actor_kind_var.get() or "human"


def get_actor_bot_id() -> str | None:
    return _actor_bot_var.get()

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
    # Same laptop allow-list as main._IS_PROD. Unrecognised names (staging,
    # a typo) are production — they must not inherit the open envelope.
    return (os.getenv("APP_ENV") or "dev").strip().lower() not in {"dev", "test", "local"}


def _allow_actor_header() -> bool:
    # Off unless set, in every environment (WP-070, decided 2026-09-12): a
    # shared API_KEY never impersonates by default. The laptop stack turns it
    # on explicitly in docker-compose.dev.yml; a typo'd value is also off.
    return env_bool("ALLOW_ACTOR_HEADER", default=False)


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
    # A shared API_KEY with no per-user map collapses every caller onto
    # ACTOR_USER_ID -- typically an admin -- so the audit trail names one
    # person for everything anyone did. Tolerated on a laptop; in production
    # it is a forged trail, and the process should not start on it.
    shared = (os.getenv("API_KEY") or "").strip()
    if shared and not parse_api_key_map() and _app_is_prod() and not _allow_actor_header():
        raise RuntimeError(
            "API_KEY is set with no API_KEY_MAP and no ALLOW_ACTOR_HEADER: every "
            f"caller would be audited as {default} -- configure per-user keys"
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
