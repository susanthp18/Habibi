"""Require review of existing webhook subscriptions before event egress.

Revision ID: 20260928_0172
Revises: 20260928_0171
Mirror: sql/77_webhook_subscription_review.sql
"""

from pathlib import Path
from typing import Sequence, Union

from replay import apply_sql

revision: str = "20260928_0172"
down_revision: Union[str, None] = "20260928_0171"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "77_webhook_subscription_review.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    raise NotImplementedError("forward-only: existing webhook subscriptions require explicit review")
