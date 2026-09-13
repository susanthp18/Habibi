"""Environment parsing helpers shared across modules.

Single implementation so ``CIRCUIT_FAILURE_THRESHOLD`` and ``DB_POOL_SIZE`` can
never disagree about what an unset / malformed value means: both fall back to
the caller's default rather than raising at import time.

The same reasoning is why :data:`NON_PROD_ENVS` and :func:`env_name` live here.
They used to sit in ``agent_core/skills/sign.py``, and ``agent_core/vault/seal``
reached across for the private ``_env_name`` — so the vault, which knows nothing
about skill packs, imported the skill signer just to ask what environment it was
running in. This is a leaf module (``math`` and ``os`` only), so both key
helpers can take it without either depending on the other.
"""

from __future__ import annotations

import math
import os

__all__ = [
    "env_int",
    "env_float",
    "env_bool",
    "as_bool",
    "NON_PROD_ENVS",
    "env_name",
]

# The same allow-list shape ``main.py`` uses to decide it is not production,
# read the other way round: there, anything that is not prod/production is dev;
# here, only an *explicitly* non-production name earns a built-in development
# key, so a deployment with APP_ENV=staging (or a typo) raises rather than
# trusting a constant that is committed to this repository.
NON_PROD_ENVS = frozenset({"dev", "development", "local", "test", "testing", "sandbox", "ci"})


def env_name() -> str:
    """The declared environment, lower-cased. Unset means a laptop."""
    return (os.getenv("APP_ENV") or os.getenv("ENV") or "dev").strip().lower()


def is_prod() -> bool:
    """Is this process production? Unrecognised means yes.

    The one answer. Only an environment that has *said* it is not production
    (``NON_PROD_ENVS``) gets the open envelope, the development keys, the
    seedable database and the loopback defaults; ``staging``, a typo, or an
    unset name on a deployed host is production. Seven sites used to decide
    this for themselves and five of them asked the question the other way
    round -- ``in {"prod", "production"}`` -- so ``APP_ENV=staging`` was
    allowed the dev MinIO credentials and the demo seeder.
    """
    return env_name() not in NON_PROD_ENVS


# One truth set for every flag. ``"on"`` belongs here: ``MINIO_SECURE=on`` used
# to disable TLS because ``storage.py`` omitted it while twenty other sites
# accepted it. Empty / unset / unrecognised is the caller's default — the same
# contract as ``env_int`` — never true-by-blank, and never false-by-typo. A
# spelling that is not in either set must not force plaintext the way omitting
# ``"on"`` did.
_BOOL_TRUE = frozenset({"1", "true", "yes", "on"})
_BOOL_FALSE = frozenset({"0", "false", "no", "off"})


def as_bool(value: object, default: bool = False) -> bool:
    """The same truth set, applied to a value that did not come from the env.

    JSON is where this earns its place. ``bool("false")`` is ``True``, so a
    config document saying ``{"suppressDiscretionary": "false"}`` used to mint
    a control arm through a bare ``bool()`` -- one of the six silent-corruption
    classes §13.2 of the engines design names. A real bool passes through; a
    string is read against the one truth set above; anything else is the
    caller's default rather than a coincidence of truthiness.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in _BOOL_TRUE:
            return True
        if raw in _BOOL_FALSE:
            return False
    return default


def env_bool(name: str, default: bool = False) -> bool:
    return as_bool(os.getenv(name), default)


def env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    # ``float()`` happily parses "nan" and "inf". These feed timeouts, TTLs and
    # breaker windows: NaN makes every comparison false (a reset that never
    # fires), inf makes a bounded wait unbounded. Neither is a usable override.
    if not math.isfinite(value):
        return default
    return value
