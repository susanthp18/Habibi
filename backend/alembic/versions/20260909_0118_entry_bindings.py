"""The Door: which card answers a contact becomes an authored row.

Revision ID: 20260909_0118
Revises: 20260909_0117
Create Date: 2026-09-09

NOT applied to the running database by this work package. Mirror:
sql/29_entry_bindings.sql.

Creating the table changes nothing on its own, and that is deliberate.
`resolve_entry` falls back to the current `os.getenv("BOT_ID") or
db.DEFAULT_BOT_ID` lookup on three separate conditions -- the table is absent,
the table is empty, or `DOOR_ENABLED` is unset -- so an unmigrated database, a
migrated-but-unconfigured one, and a configured one with the flag off all route
exactly as they do today. No caller is switched here.

The table is created empty. There is one `TWILIO_PHONE_NUMBER` in this
deployment and `number_pools`/`pool_numbers` are both empty, so seeding a row
now would only restate the env var; the first row is authored when a second DID
exists or when intake-v1 is ready to answer. `number_pools` is not reused for
this despite the name: its columns (`attempts_7d`, `answer_rate_7d`, `state`,
`health_checked_at`) are an outbound caller-ID rotation pool and it carries no
bot reference at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

revision: str = "20260909_0118"
down_revision: Union[str, None] = "20260909_0117"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "29_entry_bindings.sql"


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    raise NotImplementedError("forward-only")
