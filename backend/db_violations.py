"""Compliance violations: list, patch, notes (WP-036 peel).

Peeled from ``db.py``. Call sites stay ``db.*`` via a bottom-of-file
re-export. Reach the engine through :func:`_db`, never ``from db_core import
engine``: the ``db_tx`` fixture wraps ``db.engine``, and a name bound from
``db_core`` bypasses that proxy.
"""

from __future__ import annotations

from sqlalchemy import text
from typing import Any


def _db():
    """The ``db`` module object, resolved at call time."""
    import db as d

    return d


def _violation_status_screen(status: str | None) -> str:
    if status in {"open", "in_review", "acknowledged", "resolved"}:
        return status
    if status in {"reviewed", "review"}:
        return "acknowledged"
    return "open"

_RULE_ID_SCREEN = {
    "rule-recording": "r-rec",
    "rule-mini-miranda": "r-mm",
    "rule-identity": "r-verify",
    "rule-payment": "r-disp",
}

def _violation_rule_screen(rule_id: str | None) -> str:
    if not rule_id:
        return "r-rec"
    return _RULE_ID_SCREEN.get(rule_id, rule_id)

def _violation_severity_screen(severity: str | None) -> str:
    if severity in {"critical", "high", "medium", "low"}:
        return severity
    return "medium"

def _transcript_turn(row: dict[str, Any]) -> dict[str, Any]:
    _mod = _db()
    _speaker_screen = _mod._speaker_screen
    return {
        "id": row["id"],
        "t": int(row["at_sec"] or 0),
        "speaker": _speaker_screen(row["speaker"]),
        "text": row["text"] or "",
    }

def _violation_notes_grouped(conn: Any, violation_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Structured notes from activity_events (note_added / violation_note)."""
    _mod = _db()
    _rows = _mod._rows
    if not violation_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT ae.entity_id, ae.at, ae.label AS text, u.name AS author
                FROM activity_events ae
                LEFT JOIN users u ON u.id = ae.actor_user_id
                WHERE ae.entity_type = 'violation'
                  AND ae.entity_id = ANY(:ids)
                  AND ae.kind IN ('note_added', 'violation_note')
                ORDER BY ae.at
                """
            ),
            {"ids": violation_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["entity_id"], []).append(
            {
                "at": r["at"],
                "author": r["author"] or "System",
                "text": r["text"] or "",
            }
        )
    return grouped

def _transcripts_by_interaction(conn: Any, interaction_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    _mod = _db()
    _rows = _mod._rows
    if not interaction_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT id, interaction_id, turn_index, speaker, at_sec, text
                FROM interaction_transcript
                WHERE interaction_id = ANY(:ids)
                ORDER BY interaction_id, turn_index
                """
            ),
            {"ids": interaction_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["interaction_id"], []).append(r)
    return grouped

def _build_violation_evidence(
    turns: list[dict[str, Any]],
    at_sec: int,
    description: str | None,
) -> dict[str, Any]:
    """Offending turn + neighbours. Falls back to snippet-only when no transcript."""
    _mod = _db()
    _speaker_screen = _mod._speaker_screen
    snippet = (description or "").strip() or "No transcript evidence available."
    if not turns:
        return {
            "snippet": snippet,
            "preceding": None,
            "offending": {
                "id": "synthetic-offending",
                "t": at_sec,
                "speaker": "system",
                "text": snippet,
            },
            "following": None,
        }

    # Prefer the turn closest to at_sec; tie-break toward agent/bot speech.
    best_idx = 0
    best_dist = abs(int(turns[0]["at_sec"] or 0) - at_sec)
    for i, t in enumerate(turns):
        dist = abs(int(t["at_sec"] or 0) - at_sec)
        speaker = _speaker_screen(t["speaker"])
        better = dist < best_dist or (
            dist == best_dist and speaker in {"bot", "agent"} and _speaker_screen(turns[best_idx]["speaker"]) not in {"bot", "agent"}
        )
        if better:
            best_idx = i
            best_dist = dist

    offending = _transcript_turn(turns[best_idx])
    if not snippet or snippet == "No transcript evidence available.":
        snippet = offending["text"]
    preceding = _transcript_turn(turns[best_idx - 1]) if best_idx > 0 else None
    following = _transcript_turn(turns[best_idx + 1]) if best_idx + 1 < len(turns) else None
    return {
        "snippet": snippet,
        "preceding": preceding,
        "offending": offending,
        "following": following,
    }

def _violation_rows_to_screen(
    conn: Any,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ids = [r["id"] for r in rows]
    interaction_ids = [r["interaction_id"] for r in rows if r.get("interaction_id")]
    notes = _violation_notes_grouped(conn, ids)
    transcripts = _transcripts_by_interaction(conn, interaction_ids)
    result: list[dict[str, Any]] = []
    for r in rows:
        at_sec = int(r["at_sec"] or 0)
        call_id = r["interaction_id"] or ""
        actor_kind = "bot" if r["actor_kind"] == "bot" else "human"
        actor_name = r["actor_bot_name"] if actor_kind == "bot" else r["actor_user_name"]
        if not actor_name:
            actor_name = "Kaia v2.4" if actor_kind == "bot" else "Unknown agent"
        evidence = _build_violation_evidence(
            transcripts.get(call_id) or [],
            at_sec,
            r.get("description"),
        )
        result.append(
            {
                "id": r["id"],
                "callId": call_id,
                "customerName": r["customer_name"],
                "ruleId": _violation_rule_screen(r["rule_id"]),
                "severity": _violation_severity_screen(r["rule_severity"]),
                "occurredAt": r["occurred_at"] or r["created_at"],
                "atSec": at_sec,
                "actor": {"kind": actor_kind, "name": actor_name},
                "evidence": evidence,
                "status": _violation_status_screen(r["status"]),
                "assignee": r["assignee"] or None,
                "notes": notes.get(r["id"]) or [],
            }
        )
    return result

_VIOLATION_LIST_SQL = """
    SELECT v.id, v.interaction_id, v.customer_id, c.name AS customer_name,
           v.rule_id, cr.severity AS rule_severity, v.actor_kind,
           v.status, v.description, v.at_sec, v.created_at,
           COALESCE(i.started_at, v.created_at) AS occurred_at,
           u.name AS assignee,
           au.name AS actor_user_name,
           b.name AS actor_bot_name
    FROM violations v
    JOIN customers c ON c.id = v.customer_id
    JOIN compliance_rules cr ON cr.id = v.rule_id
    LEFT JOIN users u ON u.id = v.assignee_user_id
    LEFT JOIN users au ON au.id = v.actor_user_id
    LEFT JOIN bots b ON b.id = v.actor_bot_id
    LEFT JOIN interactions i ON i.id = v.interaction_id
"""

def list_violations(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    """Compliance Risk feed — screen Violation shape. Paged: it grows with every call."""
    _mod = _db()
    _rows = _mod._rows
    engine = _mod.engine
    page, skip = _mod.clamp_list_limit(limit), _mod.clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    _VIOLATION_LIST_SQL
                    + """
                    ORDER BY
                      CASE cr.severity
                        WHEN 'critical' THEN 4
                        WHEN 'high' THEN 3
                        WHEN 'medium' THEN 2
                        ELSE 1
                      END DESC,
                      COALESCE(i.started_at, v.created_at) DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": page, "offset": skip},
            )
        )
        return _violation_rows_to_screen(conn, rows)

def _violation_by_id(conn: Any, violation_id: str) -> dict[str, Any]:
    _mod = _db()
    _one = _mod._one
    row = _one(
        conn.execute(
            text(_VIOLATION_LIST_SQL + " WHERE v.id = :id"),
            {"id": violation_id},
        )
    )
    if row is None:
        raise KeyError("violation_not_found")
    items = _violation_rows_to_screen(conn, [row])
    return items[0]

def patch_violation(violation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is intentional,
    so an explicit None clears assignee. Notes are NOT written here —
    use add_violation_note → activity_events."""
    _mod = _db()
    _activity = _mod._activity
    _one = _mod._one
    _user_name = _mod._user_name
    engine = _mod.engine
    with engine.begin() as conn:
        row = _one(conn.execute(text("SELECT customer_id FROM violations WHERE id = :id"), {"id": violation_id}))
        if row is None:
            raise KeyError("violation_not_found")

        if "status" in payload and payload["status"] is not None:
            status = payload["status"]
            if status not in {"open", "in_review", "acknowledged", "resolved"}:
                raise ValueError(f"invalid_status: {status}")

        if "assigneeUserId" in payload and payload["assigneeUserId"] is not None:
            assignee = payload["assigneeUserId"]
            if not conn.execute(text("SELECT 1 FROM users WHERE id = :id"), {"id": assignee}).fetchone():
                raise KeyError(f"user_not_found: {assignee}")

        updates: list[str] = []
        params: dict[str, Any] = {"id": violation_id}
        if "status" in payload:
            updates.append("status = :status")
            params["status"] = payload["status"]
        if "assigneeUserId" in payload:
            updates.append("assignee_user_id = :assignee_user_id")
            params["assignee_user_id"] = payload["assigneeUserId"]
        if updates:
            updates.append("updated_at = now()")
            conn.execute(text(f"UPDATE violations SET {', '.join(updates)} WHERE id = :id"), params)

        status = payload.get("status")
        if "assigneeUserId" in payload and payload["assigneeUserId"] is None:
            label, note = "Violation unassigned", None
        elif payload.get("assigneeUserId"):
            label = "Violation assigned"
            note = _user_name(conn, payload["assigneeUserId"])
        elif status == "acknowledged":
            label, note = "Violation acknowledged", status
        elif status == "resolved":
            label, note = "Violation resolved", status
        elif status == "in_review":
            label, note = "Violation in review", status
        elif status:
            label, note = "Violation updated", status
        else:
            label, note = "Violation updated", None
        _activity(conn, "violation", violation_id, "violation_updated", label, note, row["customer_id"])
        return _violation_by_id(conn, violation_id)

def add_violation_note(violation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Free-text note on a violation. activity_events is the notes store."""
    _mod = _db()
    _activity = _mod._activity
    _one = _mod._one
    engine = _mod.engine
    with engine.begin() as conn:
        row = _one(conn.execute(text("SELECT customer_id FROM violations WHERE id = :id"), {"id": violation_id}))
        if row is None:
            raise KeyError("violation_not_found")
        text_value = (payload.get("text") or "").strip()
        if not text_value:
            raise ValueError("note text is required")
        _activity(conn, "violation", violation_id, "note_added", text_value, None, row["customer_id"])
        return {"id": violation_id, "text": text_value}

