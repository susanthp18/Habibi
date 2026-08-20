"""Tunables for live QA.

Read at call time, not import time — same discipline as reco / treatment /
authority. Scoring itself is always on: it is evidence. The mode only gates
whether a critical finding auto-takes the Twilio call.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_LIVE = "live"
_MODES = frozenset({MODE_OFF, MODE_SHADOW, MODE_LIVE})

#: Findings that may auto-barge in live mode. Sentiment and long-hold stay
#: recommend-only — a dip in tone is not a reason to dump the bot.
AUTO_BARGE_CHECKS = frozenset(
    {
        "hours-breach",
        "third-party-leak",
        "identity-before-verify",
        "authority-cap-exceeded",
        "auto-escalate",
        "opt-out-ignored",
    }
)


def mode() -> str:
    """Auto-barge mode. Defaults to shadow.

    An unrecognised value degrades to shadow, not off: a typo must not silently
    stop collecting the data the rollout decision depends on.
    """
    raw = (os.getenv("LIVE_QA_BARGE_MODE") or MODE_SHADOW).strip().lower()
    if raw not in _MODES:
        logger.warning(
            "LIVE_QA_BARGE_MODE=%r is not one of %s — using shadow",
            raw,
            sorted(_MODES),
        )
        return MODE_SHADOW
    return raw
