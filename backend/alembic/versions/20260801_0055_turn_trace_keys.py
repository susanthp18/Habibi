"""Join tool calls, retrievals and latency to a single turn.

Three surfaces record what happened during a conversation and none of them can
be joined to the others:

  bot_tool_calls        keyed by job_id  — and job_id only exists on the
                        WhatsApp/text path, so voice tool calls were never
                        recorded anywhere at all
  retrieval_logs        keyed by interaction_id (whole session) or
                        sandbox_run_id, and POST /kb/retrieve passes neither
  interaction_transcript carries the per-turn latency breakdown

So "show me what the bot did on turn 4" was unanswerable, which is also why the
Sandbox's Trace tab reconstructs a timeline from client-side state instead of
reading one.

No new tables: ``interaction_transcript.id`` is already a per-turn primary key
and is already used as an FK target by ``pii_findings.transcript_turn_id``. The
two event tables get the same FK.

``bot_tool_calls.job_id`` and ``conversation_id`` drop NOT NULL so a voice tool
call — which has neither — can be recorded. The CHECK keeps the invariant that
mattered: a row must be attributable to *something*.

Revision ID: 20260801_0055
Revises: 20260801_0054
Create Date: 2026-08-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0055"
down_revision: Union[str, Sequence[str], None] = "20260801_0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ATTRIBUTION_CHECK = "ck_bot_tool_calls_attribution"


def upgrade() -> None:
    op.alter_column("bot_tool_calls", "job_id", existing_type=sa.Text(), nullable=True)
    op.alter_column(
        "bot_tool_calls", "conversation_id", existing_type=sa.Text(), nullable=True
    )

    op.add_column("bot_tool_calls", sa.Column("interaction_id", sa.Text(), nullable=True))
    op.add_column("bot_tool_calls", sa.Column("transcript_turn_id", sa.Text(), nullable=True))
    op.add_column("bot_tool_calls", sa.Column("channel", sa.Text(), nullable=True))

    op.create_foreign_key(
        "fk_bot_tool_calls_interaction",
        "bot_tool_calls",
        "interactions",
        ["interaction_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # SET NULL, not CASCADE: a transcript turn deleted by a redaction sweep must
    # not silently remove the audit record that a CRM tool was called.
    op.create_foreign_key(
        "fk_bot_tool_calls_turn",
        "bot_tool_calls",
        "interaction_transcript",
        ["transcript_turn_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Replaces the NOT NULLs above. Weaker, but it is the invariant that was
    # actually load-bearing: an unattributable tool call is not auditable.
    op.create_check_constraint(
        _ATTRIBUTION_CHECK,
        "bot_tool_calls",
        "job_id IS NOT NULL OR interaction_id IS NOT NULL",
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bot_tool_calls_turn "
        "ON bot_tool_calls (transcript_turn_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bot_tool_calls_interaction "
        "ON bot_tool_calls (interaction_id, created_at)"
    )

    op.add_column("retrieval_logs", sa.Column("transcript_turn_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_retrieval_logs_turn",
        "retrieval_logs",
        "interaction_transcript",
        ["transcript_turn_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_retrieval_logs_turn "
        "ON retrieval_logs (transcript_turn_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_retrieval_logs_turn")
    op.drop_constraint("fk_retrieval_logs_turn", "retrieval_logs", type_="foreignkey")
    op.drop_column("retrieval_logs", "transcript_turn_id")

    op.execute("DROP INDEX IF EXISTS ix_bot_tool_calls_interaction")
    op.execute("DROP INDEX IF EXISTS ix_bot_tool_calls_turn")
    op.drop_constraint(_ATTRIBUTION_CHECK, "bot_tool_calls", type_="check")
    op.drop_constraint("fk_bot_tool_calls_turn", "bot_tool_calls", type_="foreignkey")
    op.drop_constraint("fk_bot_tool_calls_interaction", "bot_tool_calls", type_="foreignkey")
    op.drop_column("bot_tool_calls", "channel")
    op.drop_column("bot_tool_calls", "transcript_turn_id")
    op.drop_column("bot_tool_calls", "interaction_id")

    # Restoring NOT NULL would fail against any voice-originated row, which by
    # definition has no job_id. Delete them first — they are audit records that
    # only exist because of this migration, and the pre-migration schema had
    # nowhere to put them.
    op.execute("DELETE FROM bot_tool_calls WHERE job_id IS NULL OR conversation_id IS NULL")
    op.alter_column("bot_tool_calls", "conversation_id", existing_type=sa.Text(), nullable=False)
    op.alter_column("bot_tool_calls", "job_id", existing_type=sa.Text(), nullable=False)
