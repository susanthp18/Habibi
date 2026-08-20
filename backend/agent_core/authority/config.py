"""Tunables for the live authority matrix.

Read from the environment at call time, not import time — same discipline as
``reco.config`` and ``treatment.config``. Deciding that a first-time late-fee
goodwill cap is ₹500 rather than ₹300 is an operational act, not a release.
"""

from __future__ import annotations

import logging
import os

from env_utils import env_float, env_int

logger = logging.getLogger(__name__)

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_LIVE = "live"
_MODES = frozenset({MODE_OFF, MODE_SHADOW, MODE_LIVE})


def mode() -> str:
    """Engine mode. Defaults to shadow — an engine earns its way to live.

    An unrecognised value degrades to shadow, not off: a typo must not silently
    stop collecting the data the rollout decision depends on.
    """
    raw = (os.getenv("AUTHORITY_MODE") or MODE_SHADOW).strip().lower()
    if raw not in _MODES:
        logger.warning(
            "AUTHORITY_MODE=%r is not one of %s — using shadow", raw, sorted(_MODES)
        )
        return MODE_SHADOW
    return raw


def late_fee_cap() -> float:
    """Maximum first-time late-fee goodwill in the 1–30 DPD bucket, rupees."""
    return max(0.0, env_float("AUTHORITY_LATE_FEE_CAP", 500.0))


def late_fee_mid_cap() -> float:
    """Maximum first-time late-fee goodwill in the 31–60 DPD bucket, rupees."""
    return max(0.0, env_float("AUTHORITY_LATE_FEE_MID_CAP", 250.0))


def late_fee_max_outstanding() -> float:
    """Above this outstanding, live goodwill is always an escalate."""
    return max(0.0, env_float("AUTHORITY_LATE_FEE_MAX_OUTSTANDING", 100_000.0))


def late_fee_max_dpd() -> int:
    """At or above this DPD, live goodwill is always an escalate."""
    return max(0, env_int("AUTHORITY_LATE_FEE_MAX_DPD", 61))


def min_tenure_months() -> int:
    """Below this tenure, live goodwill is always an escalate.

    Applied only when tenure is known. Unknown is absent, not zero.
    """
    return max(0, env_int("AUTHORITY_MIN_TENURE_MONTHS", 6))
