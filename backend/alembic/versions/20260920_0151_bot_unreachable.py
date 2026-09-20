"""Allow retryable call_outcomes.connection = bot_unreachable.

Revision ID: 20260920_0151
Revises: 20260918_0150
Create Date: 2026-09-20

When the voice bot's media leg never comes up, the attempt is
``bot_unreachable`` — retryable, not a completed conversation. Mirror:
sql/21_outbound.sql. Do not apply against a live database from an agent
session; the orchestrator runs upgrade after review.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260920_0151"
down_revision: Union[str, None] = "20260918_0150"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONNECTION = (
    "no_answer",
    "busy",
    "rejected",
    "failed",
    "invalid_number",
    "voicemail",
    "wrong_party",
    "ivr_only",
    "connected",
    "suppressed",
    "bot_unreachable",
)
_ATTEMPT = (
    "reserved",
    "suppressed",
    "dialing",
    "ringing",
    "answered",
    "live",
    "completed",
    "voicemail_left",
    "voicemail_skipped",
    "no_answer",
    "busy",
    "rejected",
    "failed",
    "invalid_number",
    "canceled",
    "transferred",
    "abandoned",
    "bot_unreachable",
)


def _replace_check(table: str, names: tuple[str, ...], column: str, values: tuple[str, ...]) -> None:
    for name in names:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    listed = ",".join(f"'{v}'" for v in values)
    constraint = names[0]
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
        f"CHECK ({column} IN ({listed})) NOT VALID"
    )
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {constraint}")


def upgrade() -> None:
    _replace_check(
        "call_outcomes",
        ("call_outcomes_connection_check", "ck_call_outcomes_connection"),
        "connection",
        _CONNECTION,
    )
    _replace_check(
        "call_attempts",
        ("call_attempts_state_check", "ck_call_attempts_state"),
        "state",
        _ATTEMPT,
    )


def downgrade() -> None:
    raise NotImplementedError("forward-only")
