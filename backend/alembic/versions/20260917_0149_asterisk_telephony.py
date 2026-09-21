"""Allow sip_audio media and asterisk voice_sessions transport.

Revision ID: 20260917_0149
Revises: 20260917_0148
Create Date: 2026-09-17

Mirror: sql/58_asterisk_telephony.sql. Do not apply against a live
database from an agent session; the orchestrator runs upgrade after review.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260917_0149"
down_revision: Union[str, None] = "20260917_0148"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "58_asterisk_telephony.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
