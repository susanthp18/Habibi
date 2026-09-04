"""Distinguish "never configured" from "revoked to empty" on roles.

``authz._load_grants`` treated an empty ``role_permissions`` set as "fall
back to ROLE_DEFAULTS". That is the right behaviour for a role nobody has
ever saved — a fresh database stays usable — and the wrong behaviour for
the one action an operator takes in an incident: untick every grant.
``replace_role_permissions`` deleted the rows and inserted none, so a
stripped supervisor regained ``VOICE_OPERATE`` (and the rest of the
default set) while ``GET /roles`` showed ``[]``.

``roles.configured_at`` is the opinion bit. NULL means never saved;
a timestamp means the database's grant set is authoritative even when it
is empty. Mirrors ``sql/01_identity.sql``.

Revision ID: 20260904_0104
Revises: 20260901_0103
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260904_0104"
down_revision: Union[str, None] = "20260901_0103"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE roles ADD COLUMN IF NOT EXISTS configured_at timestamptz"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE roles DROP COLUMN IF EXISTS configured_at")
