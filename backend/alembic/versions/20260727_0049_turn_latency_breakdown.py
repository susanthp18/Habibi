"""Per-turn latency breakdown columns on interaction_transcript.

Revision ID: 20260727_0049
Revises: 20260727_0048

``ttfb_ms`` alone cannot say *which* service was slow. Pipecat 1.6.0's
``UserBotLatencyObserver`` emits a per-turn ``LatencyBreakdown`` (per-service
TTFB, user-turn duration, text-aggregation cost, function-call time); these
columns persist it so a slow turn is attributable after the fact instead of by
grepping logs.

All nullable: rows written before this revision have no breakdown, and the
Twilio path may produce no ``VADUserStoppedSpeakingFrame`` at all, in which case
``user_turn_ms`` is legitimately absent. No index — these are read alongside the
row for one interaction, never filtered on.

The ``op.add_column`` calls below are deliberately written out one per column
with **literal** names rather than looped over a tuple. The CI drift assertion
in .github/workflows/backend-pytest.yml regexes
``op.add_column("T", sa.Column("C"`` out of these files to check that
sql/*.sql kept up; a loop passing ``sa.Column(name, ...)`` is invisible to it,
and the column silently never lands in the base schema. That is exactly how
``voice_sessions`` went missing (20260726_0045 used a raw ``op.execute``).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260727_0049"
down_revision: Union[str, Sequence[str], None] = "20260727_0048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("interaction_transcript", sa.Column("stt_ttfb_ms", sa.Integer(), nullable=True))
    op.add_column("interaction_transcript", sa.Column("llm_ttfb_ms", sa.Integer(), nullable=True))
    op.add_column("interaction_transcript", sa.Column("tts_ttfb_ms", sa.Integer(), nullable=True))
    op.add_column("interaction_transcript", sa.Column("user_turn_ms", sa.Integer(), nullable=True))
    op.add_column("interaction_transcript", sa.Column("tool_ms", sa.Integer(), nullable=True))
    op.add_column(
        "interaction_transcript", sa.Column("aggregation_ms", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("interaction_transcript", "aggregation_ms")
    op.drop_column("interaction_transcript", "tool_ms")
    op.drop_column("interaction_transcript", "user_turn_ms")
    op.drop_column("interaction_transcript", "tts_ttfb_ms")
    op.drop_column("interaction_transcript", "llm_ttfb_ms")
    op.drop_column("interaction_transcript", "stt_ttfb_ms")
