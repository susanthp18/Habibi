"""self_service_plan — the third non-contacting action.

Revision ID: 20260821_0090
Revises: 20260821_0089
Create Date: 2026-08-21

Mirrors sql/05_collections.sql.

§6 of the design note proposes three concession actions. Only one of them is
actually an *action*, and this is it: a borrower-initiated repayment path,
enabled on the account and taken up in the borrower's own time. Nothing is sent,
so ``channel`` is ``None`` and the contact-frequency budget does not see it.

The other two — ``part_payment_offer`` and ``restructure_offer`` — are
deliberately not added. A concession has to be *said* to somebody, which makes
it a property of a contact rather than an alternative to one. They live on the
Action Contract's ``allowedOffers``, where the authority matrix decides them.
Modelling them as actions would have the engine ranking "send a WhatsApp"
against "offer a settlement" as though those were the same kind of thing, and
the first time the settlement won, a bot would have conceded money that no
authority matrix was asked about.

As with the other two ``channel=None`` actions, the exemption from the frequency
cap is exactly why this one needs limits of its own — ``policy._self_service_veto``
bounds it on arrears size, on whether the borrower has any digital surface to be
offered on at all, and on whether a plan is already open.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260821_0090"
down_revision: Union[str, Sequence[str], None] = "20260821_0089"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACTIONS_BEFORE = (
    "'wait','sms','whatsapp','voice_bot','human_call','field_visit','legal_notice',"
    "'represent_mandate','emi_date_change'"
)
_ACTIONS_AFTER = _ACTIONS_BEFORE + ",'self_service_plan'"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE treatment_decisions"
        " DROP CONSTRAINT IF EXISTS treatment_decisions_chosen_action_check"
    )
    op.execute(
        "ALTER TABLE treatment_decisions"
        " ADD CONSTRAINT treatment_decisions_chosen_action_check"
        " CHECK (chosen_action IS NULL OR chosen_action IN"
        f" ({_ACTIONS_AFTER}))"
    )


def downgrade() -> None:
    # Any row already carrying the new action would fail the narrower check, so
    # it is cleared rather than left to abort the migration. A downgrade that
    # cannot run is not a downgrade.
    op.execute(
        "UPDATE treatment_decisions SET chosen_action = 'wait', chosen_channel = NULL"
        " WHERE chosen_action = 'self_service_plan'"
    )
    op.execute(
        "ALTER TABLE treatment_decisions"
        " DROP CONSTRAINT IF EXISTS treatment_decisions_chosen_action_check"
    )
    op.execute(
        "ALTER TABLE treatment_decisions"
        " ADD CONSTRAINT treatment_decisions_chosen_action_check"
        " CHECK (chosen_action IS NULL OR chosen_action IN"
        f" ({_ACTIONS_BEFORE}))"
    )
