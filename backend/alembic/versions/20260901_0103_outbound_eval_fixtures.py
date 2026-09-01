"""Give the nine outbound conduct tasks fixtures they can actually fail.

Migration ``20260822_0096`` created the outbound suite and seeded all nine tasks
with ``'{}'::jsonb``, on the stated theory that fixtures are supplied by the
runner. No runner supplies them: ``agent_core/eval/run.py`` passes
``task.fixture or {}`` straight through to the grader.

Eight of the nine graders open with a "not applicable" guard — no machine
answered, no voicemail left, no opt-out requested, not a service pool, no
hardship declared. Against ``{}`` every one of them returns **passed: True**
with a reason. The ninth, ``outbound_opens_by_confirming``, reads an empty
``agent_turns`` as ``"silence"`` and fails. So for as long as
``OUTBOUND_EVAL_GATE_ENABLED`` has been true the suite has been a permanently
red gate standing in front of eight borrower-safety checks that could never go
red — third-party disclosure, voicemail conduct, opt-out, IVR identifiers.

The fixtures now live in ``agent_core/eval/fixtures.OUTBOUND_TASKS`` and are
written by ``seed_eval_catalog``, which is the path CI, ``scripts/seed_demo.py``
and a fresh pilot all take. That is the authoritative definition. This revision
exists only to repair databases that already ran 0096 and therefore hold the
empty rows; it imports the same dict rather than restating it, so the two cannot
drift.

It touches only rows still holding ``'{}'``. A task somebody has since filled in
by hand is left alone.

Revision ID: 20260901_0103
Revises: 20260826_0102
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0103"
down_revision: Union[str, None] = "20260826_0102"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tasks() -> list[dict]:
    # Imported inside the function so a collection-time import error in the
    # agent_core package cannot break `alembic history` on an unrelated command.
    from agent_core.eval.fixtures import PUBLISH_OUTBOUND_TASKS

    return PUBLISH_OUTBOUND_TASKS


def upgrade() -> None:
    conn = op.get_bind()
    for task in _tasks():
        conn.execute(
            sa.text(
                """
                UPDATE eval_tasks
                   SET fixture = CAST(:fixture AS jsonb),
                       name = :name
                 WHERE id = :id
                   AND fixture = '{}'::jsonb
                """
            ),
            {
                "id": task["id"],
                "name": task["name"],
                "fixture": json.dumps(task["fixture"]),
            },
        )


def downgrade() -> None:
    # Restores exactly what 0096 wrote. This is one of the rare cases where the
    # inverse is honest: the previous state of these rows was an empty object,
    # not lost data, so putting it back invents nothing. It does of course
    # restore the vacuous pass, which is the behaviour a downgrade to 0102 is
    # asking for.
    conn = op.get_bind()
    for task in _tasks():
        conn.execute(
            sa.text("UPDATE eval_tasks SET fixture = '{}'::jsonb WHERE id = :id"),
            {"id": task["id"]},
        )
