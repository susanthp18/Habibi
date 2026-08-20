"""Live authority matrix — what may close on this call, in rupees.

    from agent_core.authority import recommend_authority

    result = recommend_authority(
        customer_id="vikram-rao",
        fee_type="late_fee",
        asked_amount=500,
    )
    result.verdict           # auto_approve | cap_inr | escalate
    result.approved_amount   # inside the cap, or None
    result.talk_track        # the only sentence anyone may speak

The model does not choose the number. See README.md.
"""

from agent_core.authority.engine import AuthorityResult, recommend_authority
from agent_core.authority.features import (
    FEE_BOUNCE,
    FEE_LATE,
    FEE_RESTRUCTURE,
    FEE_SETTLEMENT,
)
from agent_core.authority.matrix import VERDICT_AUTO, VERDICT_CAP, VERDICT_ESCALATE

__all__ = [
    "FEE_BOUNCE",
    "FEE_LATE",
    "FEE_RESTRUCTURE",
    "FEE_SETTLEMENT",
    "VERDICT_AUTO",
    "VERDICT_CAP",
    "VERDICT_ESCALATE",
    "AuthorityResult",
    "recommend_authority",
]
