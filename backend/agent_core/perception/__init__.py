"""The perception plane — facts from one turn, typed and provenance-tagged.

§12 of ``docs/design/engines-production-design.md``. The boundary this package sits on is
the point of it: perception produces *facts*, the ranking path produces
*decisions*, and nothing crosses from here into the expected-value arithmetic.

    Borrower audio → ASR → PERCEPTION → (flags only, monotone-suppressive) →
    the veto stack.  Never into the EV vector.

What is here today is the day-1 configuration §12.6 asks for and no more: **a
deterministic lexicon baseline writing provenance-tagged facts with no
calibration record, permitted to touch the veto and flag path only, and
structurally barred from EV.** The classifier is not new — ``understanding``
already runs it on every turn, keyword-first, and its ``_merge`` already refuses
to let a model suppress a compliance escalation the deterministic path found.
What was missing is that the result went nowhere: three untyped columns on
``interaction_transcript``, with no record of which model produced them.

Deliberately absent, so the gap is a decision rather than a silence: the
encoder (mmBERT), the slot extractor (Qwen3.5-4B under a grammar), the guard
tier, the adapters and the weights bundle. Those need cards on an 8-16 week
lead time and a golden set of 1,400-2,800 human-labelled turns. Until then
``source_model`` says ``keyword`` or names an Azure deployment, and no
perception fact is EV-admissible at any golden-set size — which is R-INJ-1's
permanent state for the speech-derived class, not a temporary one.

The import contract in ``tests/test_perception_boundary.py`` is what keeps this
true: no module in the ranking path may reach this package.
"""

from agent_core.perception.facts import Fact, from_understanding
from agent_core.perception.record import record_turn, record_turn_for_interaction

__all__ = [
    "Fact",
    "from_understanding",
    "record_turn",
    "record_turn_for_interaction",
]
