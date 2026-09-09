"""Fail-closed runtime gates for the treatment executor and its labeller.

Absence is off. A missing row, an unreachable database, and a process that
cannot read Postgres all refuse to enact. Pytest is allowed through so the
suite can exercise the drain without flipping a production switch.
"""

from __future__ import annotations

import logging
import os

from env_utils import env_bool

logger = logging.getLogger(__name__)

TREATMENT_ENACT = "treatment.enact.enabled"
TREATMENT_LABELS = "treatment.labels.enabled"


def _pytest() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST"))


def enact_allowed() -> bool:
    if _pytest():
        return True
    try:
        import platform_switches

        return bool(platform_switches.is_enabled(TREATMENT_ENACT))
    except Exception:
        logger.exception("treatment enact kill switch unreadable — refusing")
        return False


def labels_allowed() -> bool:
    if _pytest():
        return True
    return env_bool("TREATMENT_LABELS_ENABLED")
