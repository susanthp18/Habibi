"""Add no_upsell hold kind and call_outcomes.business value.

Revision ID: 20260920_0152
Revises: 20260920_0151
Create Date: 2026-09-20

Hardship kills upsell for the rest of the relationship as kind=no_upsell
reason=hardship_declared, not by overloading the hardship hold. Mirror:
sql/05_collections.sql, sql/21_outbound.sql. Do not apply against a live
database from an agent session.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260920_0152"
down_revision: Union[str, None] = "20260920_0151"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HOLD_KINDS = (
    "hardship",
    "dispute",
    "complaint",
    "bereavement",
    "legal",
    "cease_and_desist",
    "deceased",
    "no_upsell",
)
_BUSINESS = (
    "ptp_captured",
    "ptp_recommitted",
    "paid_in_call",
    "part_payment_agreed",
    "plan_agreed",
    "dispute_raised",
    "hardship_declared",
    "refused",
    "callback_requested",
    "wrong_number",
    "deceased",
    "opt_out_requested",
    "escalated",
    "no_resolution",
    "abandoned_by_customer",
    "no_upsell",
)


def _replace_check(table: str, names: tuple[str, ...], expr: str) -> None:
    for name in names:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {names[0]} CHECK ({expr}) NOT VALID")
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {names[0]}")


def upgrade() -> None:
    kinds = ",".join(f"'{v}'" for v in _HOLD_KINDS)
    _replace_check(
        "treatment_holds",
        ("treatment_holds_kind_check",),
        f"kind IN ({kinds})",
    )
    business = ",".join(f"'{v}'" for v in _BUSINESS)
    _replace_check(
        "call_outcomes",
        ("call_outcomes_business_check", "ck_call_outcomes_business"),
        f"business IS NULL OR business IN ({business})",
    )


def downgrade() -> None:
    raise NotImplementedError("forward-only")
