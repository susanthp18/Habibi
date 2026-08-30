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
    "NON_PROD_ENVS",
    "env_name",
    "env_allows_dev_key",
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


def env_allows_dev_key() -> bool:
    """Whether the environment has *said* it is not production.

    The one question both the skill signing key and the vault master key ask
    before falling back to a constant that anyone reading this repository can
    see. A second copy of the allow-list would drift, and the two keys must
    agree on what counts as production.
    """
    return env_name() in NON_PROD_ENVS


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
