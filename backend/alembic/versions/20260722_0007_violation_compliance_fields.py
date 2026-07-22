"""compliance risk: at_sec + screen rule IDs + status normalize

Persists the segment offset the Compliance screen shows (atSec), seeds the
screen's rule IDs so RULES_BY_ID lookups work, remaps legacy violation rows,
and normalizes the smoke "reviewed" status into the screen vocabulary.

Revision ID: 20260722_0007
Revises: 20260722_0006
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0007"
down_revision: Union[str, Sequence[str], None] = "20260722_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (id, code, label, severity) — mirrors Habibi/src/data/compliance-seed.ts RULES
_SCREEN_RULES = [
    ("r-rec", "RBI-DISC-01", "Missed call recording notice", "high"),
    ("r-mm", "RBI-DISC-02", "Missed Mini-Miranda disclosure", "critical"),
    ("r-dnd-disc", "RBI-DISC-03", "Missed DND / opt-out reminder", "medium"),
    ("r-disp", "RBI-DISC-04", "Missed right-to-dispute notice", "medium"),
    ("r-threat", "PROH-LANG-01", "Threatening language", "critical"),
    ("r-abuse", "PROH-LANG-02", "Abusive / disrespectful tone", "high"),
    ("r-false", "PROH-LANG-03", "False legal claim", "critical"),
    ("r-guarantee", "PROH-LANG-04", "Guarantee-of-outcome claim", "medium"),
    ("r-dnd-win", "CONSENT-01", "Contact outside DND window", "high"),
    ("r-verify", "VERIFY-01", "Skipped identity verification", "high"),
    ("r-distress", "SENT-01", "Customer distress not addressed", "medium"),
]

_LEGACY_RULE_MAP = {
    "rule-recording": "r-rec",
    "rule-mini-miranda": "r-mm",
    "rule-identity": "r-verify",
    "rule-payment": "r-disp",
}


def upgrade() -> None:
    op.add_column("violations", sa.Column("at_sec", sa.Integer(), nullable=True))

    for rid, code, label, severity in _SCREEN_RULES:
        op.execute(
            sa.text(
                """
                INSERT INTO compliance_rules (id, code, label, severity, enabled)
                VALUES (:id, :code, :label, :severity, true)
                ON CONFLICT (id) DO UPDATE
                  SET code = EXCLUDED.code,
                      label = EXCLUDED.label,
                      severity = EXCLUDED.severity,
                      enabled = true
                """
            ).bindparams(id=rid, code=code, label=label, severity=severity)
        )

    for legacy, screen in _LEGACY_RULE_MAP.items():
        op.execute(
            sa.text(
                "UPDATE violations SET rule_id = :screen WHERE rule_id = :legacy"
            ).bindparams(screen=screen, legacy=legacy)
        )

    # Screen vocabulary (open | in_review | acknowledged | resolved).
    op.execute("UPDATE violations SET status = 'acknowledged' WHERE status = 'reviewed'")
    op.execute("UPDATE violations SET status = 'in_review' WHERE status = 'review'")
    op.execute(
        """
        UPDATE violations
        SET status = 'open'
        WHERE status IS NULL
           OR status NOT IN ('open', 'in_review', 'acknowledged', 'resolved')
        """
    )

    # Backfill at_sec from the first transcript turn on the linked call.
    op.execute(
        """
        UPDATE violations v
        SET at_sec = t.at_sec
        FROM (
          SELECT DISTINCT ON (interaction_id) interaction_id, at_sec
          FROM interaction_transcript
          ORDER BY interaction_id, turn_index
        ) t
        WHERE v.interaction_id = t.interaction_id
          AND v.at_sec IS NULL
        """
    )
    op.execute("UPDATE violations SET at_sec = 0 WHERE at_sec IS NULL")

    # Match the canonical schema (sql/07_compliance_qa.sql): NOT NULL DEFAULT 0,
    # so migrated databases don't diverge from fresh installs.
    op.alter_column(
        "violations", "at_sec", nullable=False, server_default="0"
    )

    op.execute(
        """
        ALTER TABLE violations
        ADD CONSTRAINT violations_status_check
        CHECK (status IN ('open','in_review','acknowledged','resolved'))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE violations DROP CONSTRAINT IF EXISTS violations_status_check")

    for legacy, screen in _LEGACY_RULE_MAP.items():
        op.execute(
            sa.text(
                "UPDATE violations SET rule_id = :legacy WHERE rule_id = :screen"
            ).bindparams(legacy=legacy, screen=screen)
        )

    for rid, _code, _label, _severity in _SCREEN_RULES:
        op.execute(sa.text("DELETE FROM compliance_rules WHERE id = :id").bindparams(id=rid))

    op.drop_column("violations", "at_sec")
