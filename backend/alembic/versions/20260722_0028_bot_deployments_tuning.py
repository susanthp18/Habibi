"""Add AgentTuning JSONB on bot_deployments (Voice §4.7 / Sandbox §4.4).

Revision ID: 20260722_0028
Revises: 20260722_0027
"""

from __future__ import annotations

import json
from typing import Sequence, Union

from alembic import op

revision: str = "20260722_0028"
down_revision: Union[str, Sequence[str], None] = "20260722_0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Empathetic-collections preset — keep in sync with agent_core.tuning.
_DEFAULT_TUNING = {
    "llm": {
        "temperature": 0.4,
        "top_p": 0.9,
        "frequency_penalty": 0.3,
        "presence_penalty": 0.0,
        "max_completion_tokens": 220,
        "seed": None,
    },
    "tts": {
        "voice": "en-IN-NeerjaNeural",
        "style": "empathetic",
        "style_degree": "1.4",
        "rate": "1.05",
        "pitch": "+2%",
        "volume": "default",
        "emphasis": None,
        "text_aggregation_mode": "SENTENCE",
    },
    "stt": {"language": "en-IN", "profanity": "raw"},
    "vad": {
        "confidence": 0.7,
        "start_secs": 0.15,
        "stop_secs": 0.2,
        "min_volume": 0.6,
    },
    "turn": {
        "stop_secs": 3.0,
        "pre_speech_ms": 0,
        "max_duration_secs": 8.0,
    },
    "interaction": {
        "barge_in": "on",
        "min_words": 3,
        "mute": ["until_first_bot_complete", "during_function_calls"],
        "idle_timeout_secs": 6.0,
        "idle_ladder": ["nudge", "direct", "close"],
    },
}


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE bot_deployments
          ADD COLUMN IF NOT EXISTS tuning jsonb NOT NULL DEFAULT '{}'::jsonb
        """
    )
    # Seed the product default onto rows that still have an empty blob.
    payload = json.dumps(_DEFAULT_TUNING).replace("'", "''")
    op.execute(
        f"""
        UPDATE bot_deployments
        SET tuning = '{payload}'::jsonb,
            updated_at = now()
        WHERE tuning = '{{}}'::jsonb
           OR tuning IS NULL
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE bot_deployments DROP COLUMN IF EXISTS tuning")
