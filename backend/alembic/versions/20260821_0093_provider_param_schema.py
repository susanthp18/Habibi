"""provider_models.params_schema — a model declares its own knobs.

Revision ID: 20260821_0093
Revises: 20260821_0092
Create Date: 2026-08-21

Mirrors sql/10_admin.sql.

The Voice tab rendered Azure's parameter set — style, rate, pitch, warmth,
sentence pause — because Azure was the only provider. Those are the knobs of a
*parametric* synthesiser, and they are not a superset of anything.

Fish Audio S2.1 Pro, reached through OpenRouter, has none of them. It is a
generative model: you steer it with ``temperature``, ``top_p`` and
``repetition_penalty``, plus an OpenAI-standard ``speed``. Rendering a pitch
slider for it would be a control that silently does nothing — the exact failure
this codebase keeps finding in its own language handling.

So the knobs move into the row. ``params_schema`` is a JSON array of control
descriptors the UI renders generically:

    [{"key": "temperature", "label": "Temperature", "kind": "number",
      "min": 0.1, "max": 2.0, "step": 0.05, "default": 0.7,
      "help": "Higher is more expressive and less repeatable."}]

Two rules keep this honest, both learned by probing the live endpoint rather
than reading a vendor page:

* **Only verified controls go in.** Fish's own docs describe ``prosody`` and
  ``X-Fish-*`` headers; neither survives the OpenRouter hop — a 0.5 speed sent
  that way changed duration by 7% (noise), while the top-level ``speed`` field
  changed it by 1.94x. Only the latter is in the schema.
* **``transport`` says where a value goes.** ``body`` is a top-level JSON field;
  ``ssml`` is an Azure prosody attribute. A control with no transport cannot be
  sent at all, which is what stops a knob from being decorative.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260821_0093"
down_revision: Union[str, Sequence[str], None] = "20260821_0092"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE provider_models "
        "ADD COLUMN IF NOT EXISTS params_schema jsonb NOT NULL DEFAULT '[]'::jsonb"
    )
    # The OpenRouter identity row. Same reason as 0092: the seed in
    # agent_core.providers.registry upserts capability over this, but a clean
    # database must be able to hold a binding to it without app code running.
    op.execute(
        """
        INSERT INTO providers (id, name, category)
        VALUES ('openrouter', 'OpenRouter', 'speech')
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE provider_models DROP COLUMN IF EXISTS params_schema")
