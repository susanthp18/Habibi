"""Drop the recording-disclosure line the platform already supplies.

Every preset shipped ``Always disclose that the call is recorded for quality and
compliance.`` — and every card cloned from one inherited it. The platform
appends its own rule from the ``alwaysDiscloseRecording`` guardrail, via
``agent_core.guardrail_rules``, on every render path there is. So the shipped
system message carried both, and they do not say the same thing:

    (preset)   Always disclose that the call is recorded for quality and compliance.
    (platform) State once, at the very start of the call and before any account
               detail, that the call is recorded ... never say it again, and
               never re-confirm it later.

"Always" against "once, then never again", in one message. ``agent_core/prompt.py``
records what that produced: a call that opened with the disclosure correctly and
then repeated it twice more, unprompted, minutes later. The platform wording was
made once-only specifically to stop that, and the preset line argues with it.

Linting the live rows found the duplicate on six of the thirteen prompt versions
in the database, including two published ones — every last instance traceable to
a preset.

The compliance preset stated it a third way ("Begin every call with the recording
disclosure and verify the caller's identity ..."), which the disclosure detector
does not match, so it was not even reported. Its identity-verification clause is
real and is kept; only the disclosure half is dropped.

This repairs rows that already exist. ``sql/09_bot_config.sql`` seeds fresh
installs and ``seed_postgres.py`` upserts on every seed run; all three were
regenerated from one source and ``tests/test_persona_preset_templates.py`` holds
them together.

Revision ID: 20260825_0101
Revises: 20260823_0100
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0101"
down_revision: Union[str, Sequence[str], None] = "20260823_0100"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Dropped wherever it appears as a whole line.
DROP_LINE = "Always disclose that the call is recorded for quality and compliance."

#: The compliance preset's variant, rewritten rather than deleted — the
#: verification half of the sentence is an instruction the platform does not
#: supply.
OLD_COMPLIANCE = (
    "Begin every call with the recording disclosure and verify the caller's "
    "identity before sharing any account information."
)
NEW_COMPLIANCE = "Verify the caller's identity before sharing any account information."


def _strip(template: str) -> str:
    lines = [ln for ln in template.split("\n") if ln.strip() != DROP_LINE]
    return "\n".join(NEW_COMPLIANCE if ln == OLD_COMPLIANCE else ln for ln in lines)


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, config FROM persona_presets")).fetchall()
    for preset_id, raw in rows:
        config = dict(raw) if isinstance(raw, dict) else json.loads(raw)
        template = config.get("promptTemplate")
        if not isinstance(template, str):
            continue
        stripped = _strip(template)
        if stripped == template:
            continue
        config["promptTemplate"] = stripped
        conn.execute(
            sa.text(
                "UPDATE persona_presets SET config = CAST(:config AS jsonb), "
                "updated_at = now() WHERE id = :id"
            ),
            {"id": preset_id, "config": json.dumps(config)},
        )


def downgrade() -> None:
    # Deliberately not reinstated. Putting the line back would restore a
    # duplicate of a rule the runtime injects anyway, whose only observable
    # effect was calls that disclosed two and three times over. The prior text
    # is recoverable from 20260819_0084 if it is ever genuinely wanted.
    pass
