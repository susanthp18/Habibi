"""Environment parsing helpers shared across modules.

Single implementation so ``CIRCUIT_FAILURE_THRESHOLD`` and ``DB_POOL_SIZE`` can
never disagree about what an unset / malformed value means: both fall back to
the caller's default rather than raising at import time.
"""

from __future__ import annotations

import math
import os

__all__ = ["env_int", "env_float"]


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
