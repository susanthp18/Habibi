"""Next-best-treatment: what should happen to this account, and when.

    from agent_core.treatment import Trigger, recommend_treatment

    result = recommend_treatment(
        customer_id="vikram-rao",
        account_id="ACC-9021",
        trigger=Trigger(kind="bounce", at=bounced_at, ref="PE-123"),
    )
    result.action          # 'whatsapp'
    result.at              # when it should happen
    result.expected_value  # rupees
    result.rationale       # one line for the queue and the audit log

See ``README.md`` for the pipeline, the vetoes and the rollout.
"""

from agent_core.treatment.actions import (
    FIELD_VISIT,
    HUMAN_CALL,
    LEGAL_NOTICE,
    SMS,
    VOICE_BOT,
    WAIT,
    WHATSAPP,
)
from agent_core.treatment.engine import TreatmentResult, recommend_treatment
from agent_core.treatment.features import Trigger

__all__ = [
    "FIELD_VISIT",
    "HUMAN_CALL",
    "LEGAL_NOTICE",
    "SMS",
    "VOICE_BOT",
    "WAIT",
    "WHATSAPP",
    "Trigger",
    "TreatmentResult",
    "recommend_treatment",
]
