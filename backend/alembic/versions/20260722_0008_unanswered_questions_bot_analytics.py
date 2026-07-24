"""bot analytics: unanswered_questions top_intent + seed gaps

Adds top_intent so the Unanswered / RAG-miss table can show a top intent
without inventing one at read time, and seeds a handful of gap rows so the
Bot Analytics section isn't blank (the smoke table had a single row).

Revision ID: 20260722_0008
Revises: 20260722_0007
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op
from seed_guard import seed_demo_enabled
import sqlalchemy as sa


revision: str = "20260722_0008"
down_revision: Union[str, Sequence[str], None] = "20260722_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_ID = "hdfc.retail"

# (id, question, hits, last_seen, top_intent, suggested_fix, has_kb_link)
_SEED_GAPS = [
    (
        "uq-settlement-letter",
        "Can I get a settlement letter?",
        9,
        "2026-07-21T11:00:00Z",
        "statement",
        "kb",
        True,
    ),
    (
        "uq-instalments-cibil",
        "Can I pay in three instalments after due date without CIBIL hit?",
        84,
        "2026-07-21T09:00:00Z",
        "late-fee",
        "kb",
        False,
    ),
    (
        "uq-min-pay-interest",
        "What's the interest rate if I only pay minimum?",
        71,
        "2026-07-21T10:30:00Z",
        "emi",
        "prompt",
        True,
    ),
    (
        "uq-noc-closure",
        "How do I get a NOC after full closure?",
        63,
        "2026-07-20T14:00:00Z",
        "statement",
        "kb",
        False,
    ),
    (
        "uq-waiver-job-loss",
        "Can waiver be given if job loss proof provided?",
        58,
        "2026-07-21T08:15:00Z",
        "late-fee",
        "both",
        False,
    ),
    (
        "uq-foreclosure-charges",
        "Explain foreclosure charges for personal loan",
        52,
        "2026-07-19T16:40:00Z",
        "emi",
        "prompt",
        True,
    ),
    (
        "uq-emi-debit-date",
        "How to change EMI debit date?",
        47,
        "2026-07-20T11:20:00Z",
        "emi",
        "kb",
        False,
    ),
    (
        "uq-moratorium-medical",
        "Is there a moratorium option for medical emergency?",
        41,
        "2026-07-18T12:00:00Z",
        "late-fee",
        "kb",
        False,
    ),
    (
        "uq-late-fee-variance",
        "Why was late fee ₹599 vs standard ₹450?",
        39,
        "2026-07-21T07:45:00Z",
        "dispute",
        "prompt",
        True,
    ),
    (
        "uq-overdue-to-emi",
        "Can I convert overdue balance to EMI?",
        34,
        "2026-07-19T09:30:00Z",
        "topup",
        "both",
        False,
    ),
]


def upgrade() -> None:
    op.add_column("unanswered_questions", sa.Column("top_intent", sa.Text(), nullable=True))

    if not seed_demo_enabled():
        return

    for qid, question, hits, last_seen, top_intent, fix, _has_kb in _SEED_GAPS:
        op.execute(
            sa.text(
                """
                INSERT INTO unanswered_questions
                  (id, tenant_id, question, hit_count, last_seen_at, suggested_fix_type, top_intent)
                VALUES
                  (:id, :tenant_id, :question, :hits, CAST(:last_seen AS timestamptz), :fix, :top_intent)
                ON CONFLICT (id) DO UPDATE
                  SET question = EXCLUDED.question,
                      hit_count = EXCLUDED.hit_count,
                      last_seen_at = EXCLUDED.last_seen_at,
                      suggested_fix_type = EXCLUDED.suggested_fix_type,
                      top_intent = EXCLUDED.top_intent,
                      updated_at = now()
                """
            ).bindparams(
                id=qid,
                tenant_id=TENANT_ID,
                question=question,
                hits=hits,
                last_seen=last_seen,
                fix=fix,
                top_intent=top_intent,
            )
        )

    # KB coverage links for rows that should show "Doc exists".
    # Preserve the smoke link id for the original settlement-letter row.
    for qid, _q, _h, _ls, _ti, _fix, has_kb in _SEED_GAPS:
        if not has_kb:
            continue
        link_id = "gap-settlement-letter" if qid == "uq-settlement-letter" else f"gap-{qid}"
        op.execute(
            sa.text(
                """
                INSERT INTO analytics_kb_gap_links
                  (id, unanswered_question_id, kb_document_id, faq_pair_id, prompt_version_id)
                VALUES
                  (:id, :uq_id, 'kb-rbi-disclosures', 'faq-payment-link', 'prompt-v2-4')
                ON CONFLICT (id) DO UPDATE
                  SET unanswered_question_id = EXCLUDED.unanswered_question_id,
                      kb_document_id = EXCLUDED.kb_document_id
                """
            ).bindparams(id=link_id, uq_id=qid)
        )


def downgrade() -> None:
    for qid, *_rest in _SEED_GAPS:
        if qid == "uq-settlement-letter":
            continue
        op.execute(
            sa.text("DELETE FROM analytics_kb_gap_links WHERE unanswered_question_id = :id").bindparams(
                id=qid
            )
        )
        op.execute(sa.text("DELETE FROM unanswered_questions WHERE id = :id").bindparams(id=qid))

    # Restore the original smoke row shape (keep the row, clear top_intent).
    op.execute(
        sa.text(
            """
            UPDATE unanswered_questions
            SET top_intent = NULL,
                suggested_fix_type = 'faq',
                hit_count = 9,
                question = 'Can I get a settlement letter?'
            WHERE id = 'uq-settlement-letter'
            """
        )
    )
    op.drop_column("unanswered_questions", "top_intent")
