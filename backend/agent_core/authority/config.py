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


#: Named ceilings a mission may be sent out under, in rupees.
#:
#: The authority matrix decides what policy permits for this account and this
#: fee; a profile is a second, *narrower* bound the mission carries — a pre-due
#: courtesy call has no business conceding what a broken-promise chase might.
#:
#: It can only ever lower. That direction is the whole safety property: a card
#: cannot author itself more discretion than the matrix would grant, only less,
#: so a mistake here costs a concession rather than making an unauthorised one.
_PROFILE_CEILINGS: dict[str, float] = {
    "none": 0.0,
    "collections_tier1": 250.0,
    "collections_tier2": 500.0,
    "collections_tier3": 1500.0,
}


def profile_names() -> tuple[str, ...]:
    """The named profiles a card may choose from, cheapest ceiling first.

    Public so the Outbound editor can offer exactly these. ``profile_ceiling``
    treats an unrecognised name as "no extra bound" rather than refusing every
    concession, which is the right runtime behaviour and the wrong thing for an
    author to discover — a typo there silently *widens* what the mission may
    concede, and nothing on screen would say so.
    """
    return tuple(sorted(_PROFILE_CEILINGS, key=lambda k: _PROFILE_CEILINGS[k]))


def profile_ceilings() -> dict[str, float]:
    """Name → rupee ceiling, for showing an author what they are choosing."""
    return dict(_PROFILE_CEILINGS)


def profile_ceiling(name: str | None) -> float | None:
    """Rupee ceiling for a named authority profile, or None for no extra bound.

    An unrecognised name returns None rather than 0: refusing every concession
    because somebody typed a profile that does not exist would be a silent
    behaviour change dressed as a safety measure, and the compile gate is where
    a bad name should be caught.
    """
    key = (name or "").strip().lower()
    if not key:
        return None
    override = os.getenv(f"AUTHORITY_PROFILE_{key.upper()}")
    if override:
        try:
            return max(0.0, float(override))
        except ValueError:
            logger.warning("AUTHORITY_PROFILE_%s is not a number", key.upper())
    if key not in _PROFILE_CEILINGS:
        logger.warning("unknown authority profile %r — no additional ceiling applied", name)
        return None
    return _PROFILE_CEILINGS[key]
