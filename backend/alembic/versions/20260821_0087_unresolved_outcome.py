"""'unresolved' — the negative class a control arm cannot exist without.

Revision ID: 20260821_0087
Revises: 20260821_0086
Create Date: 2026-08-21

Mirrors sql/05_collections.sql.

``followthrough._outcome_for`` refuses to label an un-enacted decision as
anything but paid / ptp / superseded, and the reasoning is sound: nothing was
sent, so there is nothing to call unanswered, and labelling it would manufacture
a training signal out of a decision nobody acted on.

That reasoning stops holding the moment a randomised control arm exists. A
control-arm decision is not a plan that happened to go uncarried-out — it is a
deliberate withholding, and "we withheld treatment and the borrower did not pay
within the observation window" is the single most informative row in the entire
corpus. It is the counterfactual. Without it the control arm has only positives
in it, every measured cure rate is 1.0, and the estimated treatment effect comes
out large and negative, which is not a finding about collections but a finding
about the labeller.

Caught by the uplift trainer reporting a control cure rate of exactly 1.000.

``unresolved`` is a separate value rather than a reuse of ``no_answer`` because
the two are different facts and the distinction is the whole point: nobody was
asked, so nobody failed to answer.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260821_0087"
down_revision: Union[str, Sequence[str], None] = "20260821_0086"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE treatment_decisions"
        " DROP CONSTRAINT IF EXISTS treatment_decisions_outcome_check"
    )
    op.execute(
        "ALTER TABLE treatment_decisions"
        " ADD CONSTRAINT treatment_decisions_outcome_check"
        " CHECK (outcome IS NULL OR outcome IN ("
        "'reached','no_answer','paid','ptp','refused','undeliverable',"
        "'cancelled','superseded','unresolved'))"
    )


def downgrade() -> None:
    op.execute("UPDATE treatment_decisions SET outcome = NULL WHERE outcome = 'unresolved'")
    op.execute(
        "ALTER TABLE treatment_decisions"
        " DROP CONSTRAINT IF EXISTS treatment_decisions_outcome_check"
    )
    op.execute(
        "ALTER TABLE treatment_decisions"
        " ADD CONSTRAINT treatment_decisions_outcome_check"
        " CHECK (outcome IS NULL OR outcome IN ("
        "'reached','no_answer','paid','ptp','refused','undeliverable',"
        "'cancelled','superseded'))"
    )
