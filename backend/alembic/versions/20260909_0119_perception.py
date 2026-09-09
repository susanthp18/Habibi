"""W9a perception: what was said, and what it is allowed to touch.

Revision ID: 20260909_0119
Revises: 20260909_0118
Create Date: 2026-09-09

NOT applied to the running database by this work package. Mirror:
sql/30_perception.sql.

No backfill runs here, and the reason is the measurement. Read-only on
collections (2026-09-09, alembic 20260909_0115):

  interaction_transcript   135 customer turns across 54 interactions
                            57 of them carrying a classified intent
  treatment_holds            1 row, source='bot', kind='hardship', open

Those 57 classifications could in principle be replayed into `perception_facts`
from `interaction_transcript.intent` / `intent_score` / `sentiment_delta`. They
are not, and deliberately: the transcript columns record no model, no adapter,
no guard verdict and no abstention, so a backfill would have to invent every
field this table exists to carry. A perception corpus whose provenance is
fabricated is worse than an empty one -- it is the same corpus with the audit
trail forged. `perception_facts` starts empty and fills from the next call.

Both tables are CREATE TABLE IF NOT EXISTS with no ALTER on an existing table,
so this migration takes no lock any running query would notice.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "20260909_0119"
down_revision: Union[str, None] = "20260909_0118"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "30_perception.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError("forward-only")
