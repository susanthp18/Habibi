"""Compliance detection — evaluate an interaction against the rule catalog.

Before this package, ``violations`` had exactly one writer: the voice runtime's
guardrail hook, which fires only for a bot-handled *voice* call. Three
consequences, none of them visible on the Compliance Risk screen:

* **Human agents could not be audited at all.** The table has carried
  ``actor_kind='human'`` and ``actor_user_id`` since it was created; nothing
  ever wrote such a row. The screen's "Bot & human" filter and its
  "Bot vs human" KPI were reading a column that only ever said "bot".
* **Chat and WhatsApp were never checked.**
* **Nothing could be re-evaluated.** Detection happened once, live, in the
  middle of a call. Adding a rule, fixing a detector or amending a threshold
  left every past interaction judged by the old code, and no way to tell.

The unit of work here is therefore an *interaction*, not a turn, and detection
runs after the fact from what was persisted. That makes it re-runnable, which
is what turns a rule change into a backfill instead of a fresh start.

One rule is load-bearing throughout: **a rule with no detector is never
reported as clean.** :data:`detectors.DETECTORS` is keyed by rule id and
:func:`scan.detector_coverage` reports which catalog rules are actually
evaluated. Fifteen of the sixteen seeded rules had never produced a row, and
nothing on the screen could distinguish "no breaches" from "nobody is looking".
"""

from agent_core.compliance.context import ScanContext, load_context
from agent_core.compliance.detectors import DETECTORS, Finding
from agent_core.compliance.scan import (
    RULES_VERSION,
    backfill,
    detector_coverage,
    scan_interaction,
    sweep,
)

__all__ = [
    "DETECTORS",
    "Finding",
    "RULES_VERSION",
    "ScanContext",
    "backfill",
    "detector_coverage",
    "load_context",
    "scan_interaction",
    "sweep",
]
