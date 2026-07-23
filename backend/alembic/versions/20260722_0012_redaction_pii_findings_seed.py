"""redaction: realistic PII in transcripts + turn-anchored findings

The demo seeded 8 identical phone findings with transcript_turn_id NULL and
no offsets, while transcripts themselves contained no PII. TranscriptRedactor
therefore highlighted nothing, and the masking / role-gate path was a no-op.

This migration:
  1. Injects varied PII strings into customer turns (phone/email/PAN/aadhaar/
     card/account/dob) matching the Habibi detector regexes.
  2. Rebuilds pii_findings with correct transcript_turn_id + start/end offsets.
  3. Re-links redaction_audio_segments to the new findings.
  4. Marks a few records unreviewed so pending-review is demonstrable.

Data-only for the demo tenant. Downgrade restores the clone phone stubs
(and original short greeting turn text).

Revision ID: 20260722_0012
Revises: 20260722_0011
Create Date: 2026-07-22
"""

from __future__ import annotations

import re
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0012"
down_revision: Union[str, Sequence[str], None] = "20260722_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_ID = "hdfc.retail"


def _mask_card(s: str) -> str:
    digits = re.sub(r"\D", "", s)
    return f"**** **** **** {digits[-4:]}"


def _mask_aadhaar(s: str) -> str:
    return f"•••• •••• {s[-4:]}"


def _mask_phone(s: str) -> str:
    digits = re.sub(r"\D", "", s)
    return f"+91 ••••••••{digits[-2:]}"


def _mask_account(s: str) -> str:
    return f"••••{s[-4:]}"


# Mirror Habibi/src/data/redaction-seed.ts DETECTORS.
_DETECTORS: list[tuple[str, re.Pattern[str], Any]] = [
    ("card", re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"), _mask_card),
    ("aadhaar", re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b"), _mask_aadhaar),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), lambda _s: "[REDACTED-PAN]"),
    ("phone", re.compile(r"\+91[- ]?\d{5}[- ]?\d{5}\b"), _mask_phone),
    ("email", re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.I), lambda _s: "[REDACTED-EMAIL]"),
    (
        "dob",
        re.compile(r"\b(?:0?[1-9]|[12]\d|3[01])[-/](?:0?[1-9]|1[0-2])[-/](?:19|20)\d{2}\b"),
        lambda _s: "[REDACTED-DOB]",
    ),
    ("account", re.compile(r"\bHDFC-(?:CC|PL|RL|AL)-\d{4}\b"), _mask_account),
]

# Per redaction record: customer turn rewrite + review flag + optional mute.
_PLANS: list[dict[str, Any]] = [
    {
        "redaction_id": "RX-CL-100004",
        "interaction_id": "CL-100004",
        "turn_id": "CL-100004-t1",
        "text": (
            "Yes, speaking. My mobile is +91 98765 43210 and DOB is 14/03/1988 "
            "if you need to verify."
        ),
        "reviewed": False,
        "audio_type": "phone",
        "at_sec": 18,
    },
    {
        "redaction_id": "RX-CL-100005",
        "interaction_id": "CL-100005",
        "turn_id": "CL-100005-t1",
        "text": (
            "Yes, speaking. Please email the statement to sameer.khan@gmail.com "
            "or WhatsApp +91 98123 45678."
        ),
        "reviewed": True,
        "audio_type": "phone",
        "at_sec": 22,
    },
    {
        "redaction_id": "RX-CL-100006",
        "interaction_id": "CL-100006",
        "turn_id": "CL-100006-t6",
        "text": (
            "Your reminders are too frequent. Stop them or I'm closing the card. "
            "Account HDFC-CC-8842, PAN ABCDE1234F — put that on the DND note."
        ),
        "reviewed": False,
        "audio_type": "account",
        "at_sec": 95,
    },
    {
        "redaction_id": "RX-CL-100016",
        "interaction_id": "CL-100016",
        "turn_id": "CL-100016-t1",
        "text": (
            "Yes, speaking. Card ending 4532-1488-9012-3344 and Aadhaar "
            "2345 6789 0123 — please confirm the last EMI."
        ),
        "reviewed": True,
        "audio_type": "card",
        "at_sec": 20,
    },
    {
        "redaction_id": "RX-CL-100018",
        "interaction_id": "CL-100018",
        "turn_id": "CL-100018-t1",
        "text": (
            "Yes, speaking. Mail me at priya.menon@outlook.com — PAN FGHIJ5678K "
            "is already on file."
        ),
        "reviewed": True,
        "audio_type": None,
        "at_sec": None,
    },
    {
        "redaction_id": "RX-CL-100031",
        "interaction_id": "CL-100031",
        "turn_id": "CL-100031-t1",
        "text": (
            "Yes, that's me. Reach me on +91 99001 12233 about account "
            "HDFC-PL-2291."
        ),
        "reviewed": False,
        "audio_type": "phone",
        "at_sec": 16,
    },
    {
        "redaction_id": "RX-CL-100032",
        "interaction_id": "CL-100032",
        "turn_id": "CL-100032-t1",
        "text": (
            "Yes, that's me. Aadhaar 4567 8901 2345, date of birth 07-11-1991."
        ),
        "reviewed": True,
        "audio_type": "aadhaar",
        "at_sec": 19,
    },
    {
        "redaction_id": "RX-CL-100039",
        "interaction_id": "CL-100039",
        "turn_id": "CL-100039-t1",
        "text": (
            "Yes, that's me. Card 6011-0009-9012-3456 and email "
            "arjun.nair@yahoo.com for the receipt."
        ),
        "reviewed": True,
        "audio_type": "card",
        "at_sec": 21,
    },
]

_ORIGINAL_TURNS = {
    "CL-100004-t1": "Yes, speaking.",
    "CL-100005-t1": "Yes, speaking.",
    "CL-100006-t6": "Your reminders are too frequent. Stop them or I'm closing the card.",
    "CL-100016-t1": "Yes, speaking.",
    "CL-100018-t1": "Yes, speaking.",
    "CL-100031-t1": "Yes, that's me.",
    "CL-100032-t1": "Yes, that's me.",
    "CL-100039-t1": "Yes, that's me.",
}


def _findings_for(text: str, turn_id: str, redaction_id: str, interaction_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    n = 0
    for pii_type, pattern, mask_fn in _DETECTORS:
        for m in pattern.finditer(text):
            raw = m.group(0)
            out.append(
                {
                    "id": f"pii-{interaction_id}-{pii_type}-{n}",
                    "redaction_id": redaction_id,
                    "type": pii_type,
                    "masked": mask_fn(raw),
                    "confidence": 0.97,
                    "accepted": True,
                    "transcript_turn_id": turn_id,
                    "start_offset": m.start(),
                    "end_offset": m.end(),
                }
            )
            n += 1
    return out


def upgrade() -> None:
    conn = op.get_bind()

    for plan in _PLANS:
        row = conn.execute(
            sa.text(
                """
                SELECT rr.id
                FROM redaction_records rr
                JOIN interactions i ON i.id = rr.interaction_id
                WHERE rr.id = :rid AND i.tenant_id = :tenant
                """
            ),
            {"rid": plan["redaction_id"], "tenant": TENANT_ID},
        ).fetchone()
        if row is None:
            continue

        conn.execute(
            sa.text(
                """
                UPDATE interaction_transcript
                SET text = :text
                WHERE id = :turn_id AND interaction_id = :iid
                """
            ),
            {
                "text": plan["text"],
                "turn_id": plan["turn_id"],
                "iid": plan["interaction_id"],
            },
        )

        conn.execute(
            sa.text(
                """
                UPDATE redaction_records
                SET reviewed = :reviewed,
                    reviewed_by_user_id = CASE WHEN :reviewed THEN reviewed_by_user_id ELSE NULL END,
                    reviewed_at = CASE WHEN :reviewed THEN reviewed_at ELSE NULL END
                WHERE id = :rid
                """
            ),
            {"reviewed": plan["reviewed"], "rid": plan["redaction_id"]},
        )

        conn.execute(
            sa.text("DELETE FROM redaction_audio_segments WHERE redaction_id = :rid"),
            {"rid": plan["redaction_id"]},
        )
        conn.execute(
            sa.text("DELETE FROM pii_findings WHERE redaction_id = :rid"),
            {"rid": plan["redaction_id"]},
        )

        findings = _findings_for(
            plan["text"], plan["turn_id"], plan["redaction_id"], plan["interaction_id"]
        )
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

        audio_type = plan.get("audio_type")
        if audio_type and plan.get("at_sec") is not None:
            media = conn.execute(
                sa.text(
                    """
                    SELECT id FROM interaction_media
                    WHERE interaction_id = :iid AND kind = 'audio'
                    LIMIT 1
                    """
                ),
                {"iid": plan["interaction_id"]},
            ).fetchone()
            target = next((f for f in findings if f["type"] == audio_type), None)
            if media is not None and target is not None:
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO redaction_audio_segments (
                          id, redaction_id, media_id, finding_id, at_sec, duration_sec, muted
                        ) VALUES (
                          :id, :rid, :media_id, :finding_id, :at_sec, 4, true
                        )
                        """
                    ),
                    {
                        "id": f"mute-{plan['interaction_id']}-{audio_type}",
                        "rid": plan["redaction_id"],
                        "media_id": media[0],
                        "finding_id": target["id"],
                        "at_sec": int(plan["at_sec"]),
                    },
                )


def downgrade() -> None:
    conn = op.get_bind()
    for turn_id, text in _ORIGINAL_TURNS.items():
        conn.execute(
            sa.text("UPDATE interaction_transcript SET text = :text WHERE id = :tid"),
            {"text": text, "tid": turn_id},
        )

    for plan in _PLANS:
        rid = plan["redaction_id"]
        iid = plan["interaction_id"]
        conn.execute(
            sa.text("DELETE FROM redaction_audio_segments WHERE redaction_id = :rid"),
            {"rid": rid},
        )
        conn.execute(
            sa.text("DELETE FROM pii_findings WHERE redaction_id = :rid"),
            {"rid": rid},
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO pii_findings (
                  id, redaction_id, type, masked, confidence, accepted,
                  transcript_turn_id, start_offset, end_offset
                ) VALUES (
                  :id, :rid, 'phone', '+91 98XXXXXX42', 0.98, true, NULL, NULL, NULL
                )
                """
            ),
            {"id": f"pii-{iid}-phone", "rid": rid},
        )
        conn.execute(
            sa.text(
                """
                UPDATE redaction_records
                SET reviewed = true,
                    reviewed_by_user_id = 'priya-nair',
                    reviewed_at = '2026-07-21T12:00:00Z'
                WHERE id = :rid
                """
            ),
            {"rid": rid},
        )
        media = conn.execute(
            sa.text(
                """
                SELECT id FROM interaction_media
                WHERE interaction_id = :iid AND kind = 'audio'
                LIMIT 1
                """
            ),
            {"iid": iid},
        ).fetchone()
        if media is not None:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO redaction_audio_segments (
                      id, redaction_id, media_id, finding_id, at_sec, duration_sec, muted
                    ) VALUES (
                      :id, :rid, :media_id, :fid, 12, 4, true
                    )
                    """
                ),
                {
                    "id": f"mute-{iid}-phone",
                    "rid": rid,
                    "media_id": media[0],
                    "fid": f"pii-{iid}-phone",
                },
            )
