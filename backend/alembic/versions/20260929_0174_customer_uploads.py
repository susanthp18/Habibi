"""Customer uploads: tenant and retention stamp on document_files.

Revision ID: 20260929_0174
Revises: 20260928_0173
Mirror: sql/79_customer_uploads.sql
"""

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260929_0174"
down_revision: Union[str, None] = "20260928_0173"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "79_customer_uploads.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only")
