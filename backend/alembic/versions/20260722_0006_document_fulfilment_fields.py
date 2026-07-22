"""document fulfilment desk columns + screen templates

Persists fields the Documents screen collects that had nowhere to live:
failed_reason, size_kb, generated_at, sent_at, period, requested_via.
Also seeds the screen's template IDs so template_id FK writes from the UI work.

Revision ID: 20260722_0006
Revises: 20260722_0005
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0006"
down_revision: Union[str, Sequence[str], None] = "20260722_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCREEN_TEMPLATES = [
    ("T-STMT-6M", "Statement · Last 6 months", "account_statement"),
    ("T-STMT-12M", "Statement · Last 12 months", "account_statement"),
    ("T-NODUES", "No-dues certificate", "no_dues_certificate"),
    ("T-INTCERT", "Interest certificate · FY 25-26", "interest_certificate"),
    ("T-FORECLOSE", "Foreclosure letter", "foreclosure_letter"),
    ("T-SCHEDULE", "Loan repayment schedule", "loan_schedule"),
    ("T-RECEIPT", "Payment receipt", "payment_receipt"),
    ("T-KYC", "KYC confirmation letter", "kyc_letter"),
]


def upgrade() -> None:
    op.add_column("document_requests", sa.Column("period", sa.Text(), nullable=True))
    op.add_column("document_requests", sa.Column("requested_via", sa.Text(), nullable=True))
    op.add_column("document_requests", sa.Column("failed_reason", sa.Text(), nullable=True))
    op.add_column("document_requests", sa.Column("size_kb", sa.Integer(), nullable=True))
    op.add_column("document_requests", sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("document_requests", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        """
        ALTER TABLE document_requests
        ADD CONSTRAINT document_requests_requested_via_check
        CHECK (requested_via IS NULL OR requested_via IN ('bot_voice','bot_chat','agent'))
        """
    )

    # Screen template IDs (UI pickers) — keep legacy rows; remap FKs to screen IDs.
    for tid, name, doc_type in _SCREEN_TEMPLATES:
        op.execute(
            sa.text(
                """
                INSERT INTO document_templates (id, name, doc_type, preview_lines)
                VALUES (:id, :name, :doc_type, '[]'::jsonb)
                ON CONFLICT (id) DO NOTHING
                """
            ).bindparams(id=tid, name=name, doc_type=doc_type)
        )

    op.execute(
        """
        UPDATE document_requests
        SET template_id = 'T-STMT-6M'
        WHERE template_id = 'template-statement'
        """
    )
    op.execute(
        """
        UPDATE document_requests
        SET template_id = 'T-NODUES'
        WHERE template_id = 'template-noc'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE document_requests
        SET template_id = 'template-statement'
        WHERE template_id IN ('T-STMT-6M', 'T-STMT-12M')
        """
    )
    op.execute(
        """
        UPDATE document_requests
        SET template_id = 'template-noc'
        WHERE template_id = 'T-NODUES'
        """
    )
    for tid, _name, _doc_type in _SCREEN_TEMPLATES:
        op.execute(sa.text("DELETE FROM document_templates WHERE id = :id").bindparams(id=tid))

    op.execute("ALTER TABLE document_requests DROP CONSTRAINT IF EXISTS document_requests_requested_via_check")
    op.drop_column("document_requests", "sent_at")
    op.drop_column("document_requests", "generated_at")
    op.drop_column("document_requests", "size_kb")
    op.drop_column("document_requests", "failed_reason")
    op.drop_column("document_requests", "requested_via")
    op.drop_column("document_requests", "period")
