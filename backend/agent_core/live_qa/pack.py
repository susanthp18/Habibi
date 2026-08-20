"""Examiner pack — one interaction, last 12 months of evidence.

QA humans and compliance officers pull this. It is a zipper over tables that
already exist, not a second audit trail.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def build_pack(interaction_id: str) -> dict[str, Any] | None:
    """Tenant-scoped evidence pack. Never raises. None if the interaction is missing."""
    try:
        return _build(interaction_id)
    except Exception:
        logger.exception("live_qa pack failed for %s", interaction_id)
        return None


def _build(interaction_id: str) -> dict[str, Any] | None:
    import db
    import transcript_view

    tenant = db.current_tenant()
    with db.engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT i.id, i.customer_id, i.account_id, i.channel, i.direction,
                       i.handler_kind, i.status, i.disposition, i.started_at, i.ended_at,
                       i.duration_sec, i.summary, i.redaction_applied, i.hash,
                       c.name AS customer_name
                FROM interactions i
                LEFT JOIN customers c ON c.id = i.customer_id
                WHERE i.id = :id AND i.tenant_id = :tenant
                """
            ),
            {"id": interaction_id, "tenant": tenant},
        ).mappings().first()
        if row is None:
            return None

        flags = db._rows(
            conn.execute(
                text(
                    """
                    SELECT flag, severity, created_at
                    FROM interaction_flags WHERE interaction_id = :id
                    ORDER BY created_at
                    """
                ),
                {"id": interaction_id},
            )
        )
        disclosures = db._rows(
            conn.execute(
                text(
                    """
                    SELECT rule_id, label, read, read_at_sec, created_at
                    FROM interaction_disclosures WHERE interaction_id = :id
                    ORDER BY created_at
                    """
                ),
                {"id": interaction_id},
            )
        )
        violations = db._rows(
            conn.execute(
                text(
                    """
                    SELECT v.id, v.rule_id, r.code, r.label, v.status, v.description, v.at_sec
                    FROM violations v
                    JOIN compliance_rules r ON r.id = v.rule_id
                    WHERE v.interaction_id = :id
                    ORDER BY v.created_at
                    """
                ),
                {"id": interaction_id},
            )
        )
        alerts = db._rows(
            conn.execute(
                text(
                    """
                    SELECT id, kind, severity, reason, created_at, acknowledged_at
                    FROM live_alerts WHERE interaction_id = :id
                    ORDER BY created_at
                    """
                ),
                {"id": interaction_id},
            )
        )
        actions = db._rows(
            conn.execute(
                text(
                    """
                    SELECT id, action, note, audio_joined, created_at
                    FROM supervisor_actions WHERE interaction_id = :id
                    ORDER BY created_at
                    """
                ),
                {"id": interaction_id},
            )
        )
        qa_rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT d.id, d.verdict, d.recommended_action, d.reason,
                           d.reason_codes, d.mode, d.enacted, d.created_at
                    FROM live_qa_decisions d
                    WHERE d.interaction_id = :id
                    ORDER BY d.created_at
                    """
                ),
                {"id": interaction_id},
            )
        )
        media = db._rows(
            conn.execute(
                text(
                    """
                    SELECT id, kind, storage_ref, duration_sec, mime_type, hash
                    FROM interaction_media WHERE interaction_id = :id
                    ORDER BY created_at
                    """
                ),
                {"id": interaction_id},
            )
        )
        scorecard = conn.execute(
            text(
                """
                SELECT id, status, total_score, band, scored_at
                FROM qa_scorecards WHERE interaction_id = :id
                LIMIT 1
                """
            ),
            {"id": interaction_id},
        ).mappings().first()
        entries = []
        if scorecard:
            entries = db._rows(
                conn.execute(
                    text(
                        """
                        SELECT criterion_id, ai_suggested_score, final_score, note
                        FROM qa_scorecard_entries
                        WHERE scorecard_id = :id
                        ORDER BY criterion_id
                        """
                    ),
                    {"id": scorecard["id"]},
                )
            )

    transcript = ""
    try:
        transcript = transcript_view.fenced_transcript(interaction_id, limit=200) or ""
    except Exception:
        logger.exception("pack transcript failed for %s", interaction_id)

    def _iso(value: Any) -> Any:
        if hasattr(value, "isoformat"):
            return value.isoformat().replace("+00:00", "Z")
        return value

    return {
        "interactionId": row["id"],
        "customerId": row["customer_id"],
        "customerName": row["customer_name"],
        "accountId": row["account_id"],
        "channel": row["channel"],
        "direction": row["direction"],
        "handlerKind": row["handler_kind"],
        "status": row["status"],
        "disposition": row["disposition"],
        "startedAt": _iso(row["started_at"]),
        "endedAt": _iso(row["ended_at"]),
        "durationSec": row["duration_sec"],
        "summary": row["summary"],
        "redactionApplied": bool(row["redaction_applied"]),
        "hash": row["hash"],
        "transcript": transcript,
        "flags": [
            {"flag": r["flag"], "severity": r["severity"], "createdAt": _iso(r["created_at"])}
            for r in flags
        ],
        "disclosures": [
            {
                "ruleId": r["rule_id"],
                "label": r["label"],
                "read": bool(r["read"]),
                "readAtSec": r["read_at_sec"],
                "createdAt": _iso(r["created_at"]),
            }
            for r in disclosures
        ],
        "violations": [
            {
                "id": r["id"],
                "ruleId": r["rule_id"],
                "code": r["code"],
                "label": r["label"],
                "status": r["status"],
                "description": r["description"],
                "atSec": r["at_sec"],
            }
            for r in violations
        ],
        "alerts": [
            {
                "id": r["id"],
                "kind": r["kind"],
                "severity": r["severity"],
                "reason": r["reason"],
                "createdAt": _iso(r["created_at"]),
                "acknowledgedAt": _iso(r["acknowledged_at"]),
            }
            for r in alerts
        ],
        "supervisorActions": [
            {
                "id": r["id"],
                "action": r["action"],
                "note": r["note"],
                "audioJoined": bool(r.get("audio_joined")),
                "createdAt": _iso(r["created_at"]),
            }
            for r in actions
        ],
        "liveQa": [
            {
                "id": r["id"],
                "verdict": r["verdict"],
                "recommendedAction": r["recommended_action"],
                "reason": r["reason"],
                "reasonCodes": r["reason_codes"] or [],
                "mode": r["mode"],
                "enacted": bool(r["enacted"]),
                "createdAt": _iso(r["created_at"]),
            }
            for r in qa_rows
        ],
        "media": [
            {
                "id": r["id"],
                "kind": r["kind"],
                "storageRef": r["storage_ref"],
                "durationSec": r["duration_sec"],
                "mimeType": r["mime_type"],
                "hash": r["hash"],
            }
            for r in media
        ],
        "scorecard": None
        if scorecard is None
        else {
            "id": scorecard["id"],
            "status": scorecard["status"],
            "totalScore": float(scorecard["total_score"])
            if scorecard["total_score"] is not None
            else None,
            "band": scorecard["band"],
            "scoredAt": _iso(scorecard["scored_at"]),
            "entries": [
                {
                    "criterionId": e["criterion_id"],
                    "aiSuggested": float(e["ai_suggested_score"] or 0),
                    "score": float(e["final_score"] or 0),
                    "note": e["note"],
                }
                for e in entries
            ],
        },
    }
