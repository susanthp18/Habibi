"""Live QA — 100% FPC scoring and same-call barge.

    from agent_core.live_qa import evaluate_live_qa

    result = evaluate_live_qa(facts, interaction_id=ix)
    result.recommended_action   # none | listen | whisper | barge | inbox
    result.auto_barge           # True only in LIVE_QA_BARGE_MODE=live

The model does not barge. See README.md.
"""

from agent_core.live_qa.checks import TurnFacts
from agent_core.live_qa.engine import LiveQaResult, evaluate_live_qa

__all__ = [
    "LiveQaResult",
    "TurnFacts",
    "evaluate_live_qa",
]
