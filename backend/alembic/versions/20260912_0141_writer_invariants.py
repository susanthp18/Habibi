"""What the writers assume, stated in the schema (sql/49).

Revision ID: 20260912_0141
Revises: 20260912_0140
Create Date: 2026-09-12

Mirror: sql/49_writer_invariants.sql. The base DDL (sql/02, 04, 05, 06, 09,
10) carries the same indexes for a fresh build.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op
from replay import apply_sql

revision: str = "20260912_0141"
down_revision: Union[str, None] = "20260912_0140"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL = Path(__file__).resolve().parents[2] / "sql" / "49_writer_invariants.sql"


def upgrade() -> None:
    apply_sql(_SQL)


def downgrade() -> None:
    for name in (
        "uq_conversations_interaction_id",
        "uq_emi_installments_account_index",
        "uq_promise_installments_plan_index",
        "idx_followups_status_due_at",
        "idx_followups_lead_id",
        "idx_ledger_entries_account_type_posted",
        "idx_kb_index_jobs_status",
        "idx_usage_events_source_occurred",
    ):
        op.execute(f"DROP INDEX IF EXISTS {name}")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leads_customer_id ON leads(customer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_status ON webhook_deliveries(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_kb_chunks_document_id ON kb_chunks(document_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_conversations_interaction_id ON conversations(interaction_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_interaction_transcript_interaction_id ON interaction_transcript(interaction_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_emi_installments_account_id ON emi_installments(account_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_promise_installments_plan_id ON promise_installments(plan_id)")
