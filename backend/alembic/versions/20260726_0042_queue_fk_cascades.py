"""Combined-pass review: complete the delete cascade through the bot queues.

``conversations`` already cascades from both ``customers`` and ``interactions``,
so deleting a customer (erasure request, tenant teardown) cascades down to their
conversations. The bot queue tables then blocked it: ``bot_turn_jobs``,
``bot_tool_calls`` and ``whatsapp_outbound_jobs`` referenced ``conversations``
with the default NO ACTION, so the delete aborted with a foreign-key violation
and left the erasure half-done. ``bot_tool_calls.job_id`` had the same problem
against its owning ``bot_turn_jobs`` row.

These are queue/audit records owned by the conversation — when the conversation
goes, they go with it.

Revision ID: 20260726_0042
Revises: 20260726_0041
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_0042"
down_revision: Union[str, Sequence[str], None] = "20260726_0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, referenced table, referenced column, constraint name)
_CASCADES = [
    ("bot_turn_jobs", "conversation_id", "conversations", "id", "fk_bot_turn_jobs_conversation"),
    ("bot_tool_calls", "conversation_id", "conversations", "id", "fk_bot_tool_calls_conversation"),
    ("bot_tool_calls", "job_id", "bot_turn_jobs", "id", "fk_bot_tool_calls_job"),
    (
        "whatsapp_outbound_jobs",
        "conversation_id",
        "conversations",
        "id",
        "fk_whatsapp_outbound_jobs_conversation",
    ),
]


def _existing_fk_name(conn, table: str, column: str) -> str | None:
    """Name of the single-column FK on ``table.column``, whatever it is called.

    The base schema declares these inline, so Postgres auto-names them
    (``bot_turn_jobs_conversation_id_fkey``); a database built from an earlier
    migration may carry a different name. Look it up rather than guess.
    """
    return conn.execute(
        sa.text(
            """
            SELECT con.conname
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace ns ON ns.oid = rel.relnamespace
            WHERE con.contype = 'f'
              AND ns.nspname = current_schema()
              AND rel.relname = :table
              AND con.conkey = ARRAY[
                (SELECT attnum FROM pg_attribute
                 WHERE attrelid = rel.oid AND attname = :column)
              ]::smallint[]
            LIMIT 1
            """
        ),
        {"table": table, "column": column},
    ).scalar()


def _table_exists(conn, table: str) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT to_regclass(:t)"), {"t": table}
        ).scalar()
    )


def _rebuild(conn, table, column, ref_table, ref_column, name, ondelete):
    if not _table_exists(conn, table):
        return
    existing = _existing_fk_name(conn, table, column)
    if existing:
        op.drop_constraint(existing, table, type_="foreignkey")
    op.create_foreign_key(
        name, table, ref_table, [column], [ref_column], ondelete=ondelete
    )


def upgrade() -> None:
    conn = op.get_bind()
    for table, column, ref_table, ref_column, name in _CASCADES:
        _rebuild(conn, table, column, ref_table, ref_column, name, "CASCADE")


def downgrade() -> None:
    conn = op.get_bind()
    # Back to NO ACTION (the inline default the base schema used).
    for table, column, ref_table, ref_column, name in _CASCADES:
        _rebuild(conn, table, column, ref_table, ref_column, name, None)
