"""redaction: fix card/aadhaar detector overlap on CL-100016

Card text used spaces (4532 1488 9012 3344), so the aadhaar regex
(four-digit groups with spaces) also matched the first three groups.
Switch the card to dashed form so only the real aadhaar span is detected.

Revision ID: 20260722_0014
Revises: 20260722_0013
Create Date: 2026-07-22
"""

from __future__ import annotations

import re
from typing import Any, Sequence, Union

from alembic import op
from seed_guard import seed_demo_enabled
import sqlalchemy as sa


revision: str = "20260722_0014"
down_revision: Union[str, Sequence[str], None] = "20260722_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_ID = "hdfc.retail"
RID = "RX-CL-100016"
IID = "CL-100016"
TURN = "CL-100016-t1"
TEXT = (
    "Yes, speaking. Card ending 4532-1488-9012-3344 and Aadhaar "
    "2345 6789 0123 — please confirm the last EMI."
)


def _mask_card(s: str) -> str:
    digits = re.sub(r"\D", "", s)
    return f"**** **** **** {digits[-4:]}"


def _mask_aadhaar(s: str) -> str:
    return f"•••• •••• {s[-4:]}"


_DETECTORS = [
    ("card", re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"), _mask_card),
    ("aadhaar", re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b"), _mask_aadhaar),
]


def upgrade() -> None:
    if not seed_demo_enabled():
        return
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            """
            SELECT rr.id FROM redaction_records rr
            JOIN interactions i ON i.id = rr.interaction_id
            WHERE rr.id = :rid AND i.tenant_id = :tenant
            """
        ),
        {"rid": RID, "tenant": TENANT_ID},
    ).fetchone()
    if row is None:
        return

    conn.execute(
        sa.text("UPDATE interaction_transcript SET text = :text WHERE id = :tid"),
        {"text": TEXT, "tid": TURN},
    )
    conn.execute(sa.text("DELETE FROM redaction_audio_segments WHERE redaction_id = :rid"), {"rid": RID})
    conn.execute(sa.text("DELETE FROM pii_findings WHERE redaction_id = :rid"), {"rid": RID})

    findings: list[dict[str, Any]] = []
    n = 0
    for pii_type, pattern, mask_fn in _DETECTORS:
        for m in pattern.finditer(TEXT):
            findings.append(
                {
                    "id": f"pii-{IID}-{pii_type}-{n}",
                    "redaction_id": RID,
                    "type": pii_type,
                    "masked": mask_fn(m.group(0)),
                    "confidence": 0.97,
                    "accepted": True,
                    "transcript_turn_id": TURN,
                    "start_offset": m.start(),
                    "end_offset": m.end(),
                }
            )
            n += 1

    for f in findings:
        conn.execute(
            sa.text(
                """
                INSERT INTO pii_findings (
                  id, redaction_id, type, masked, confidence, accepted,
                  transcript_turn_id, start_offset, end_offset
                ) VALUES (
                  :id, :redaction_id, :type, :masked, :confidence, :accepted,
                  :transcript_turn_id, :start_offset, :end_offset
                )
                """
            ),
            f,
        )

    media = conn.execute(
        sa.text(
            "SELECT id FROM interaction_media WHERE interaction_id = :iid AND kind = 'audio' LIMIT 1"
        ),
        {"iid": IID},
    ).fetchone()
    card = next((f for f in findings if f["type"] == "card"), None)
    if media is not None and card is not None:
        conn.execute(
            sa.text(
                """
                INSERT INTO redaction_audio_segments (
                  id, redaction_id, media_id, finding_id, at_sec, duration_sec, muted
                ) VALUES (
                  :id, :rid, :media_id, :finding_id, 20, 4, true
                )
                """
            ),
            {
                "id": f"mute-{IID}-card",
                "rid": RID,
                "media_id": media[0],
                "finding_id": card["id"],
            },
        )


def downgrade() -> None:
    # No-op: prior overlapping spans were incorrect demo data.
    pass
