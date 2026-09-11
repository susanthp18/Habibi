"""Redaction Hub reads.

Peeled from ``db.py`` (WP-036 peel 8). Call sites stay ``db.*`` via a
bottom-of-file re-export. Reach the engine through :func:`_db`, never
``from db_core import engine``: the ``db_tx`` fixture wraps ``db.engine``,
and a name bound from ``db_core`` bypasses that proxy.

``_speaker_screen`` moved to ``db_core`` first (roadmap peel 8
prerequisite): the violations/transcript kernel also calls it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text


def _db():
    """The ``db`` module object, resolved at call time.

    Carved modules must use ``_db().engine``, never ``from db_core import
    engine``. See ``db_core._db``.
    """
    import db as d

    return d


# ---------------------------------------------------------------------------
# Redaction & Export Hub — reads (writes stay Phase 3A / optimistic UI)
# ---------------------------------------------------------------------------

_PII_LABELS: dict[str, str] = {
    "card": "Card number",
    "pan": "PAN / SSN",
    "phone": "Phone",
    "email": "Email",
    "address": "Address",
    "dob": "Date of birth",
    "account": "Account #",
    "ifsc": "IFSC",
    "aadhaar": "Aadhaar",
    "custom": "Custom pattern",
}

_PII_TYPES = set(_PII_LABELS)


def _redaction_channel(channel: str | None) -> str:
    if channel in {"voice", "whatsapp", "sms"}:
        return channel
    if channel in {"chat", "email"}:
        return "whatsapp" if channel == "chat" else "sms"
    return "voice"


def _actor_role_names(conn: Any, user_id: str | None = None) -> list[str]:
    _mod = _db()
    _rows = _mod._rows
    _actor_user_id = _mod._actor_user_id
    uid = (user_id or _actor_user_id() or "").strip()
    if not uid:
        return []
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT r.name
                FROM user_roles ur
                JOIN roles r ON r.id = ur.role_id
                WHERE ur.user_id = :uid
                """
            ),
            {"uid": uid},
        )
    )
    out: list[str] = []
    for r in rows:
        name = (r.get("name") or "").strip().lower().replace("-", "_").replace(" ", "_")
        if name:
            out.append(name)
    return out


def _actor_can_view_raw_pii(conn: Any) -> bool:
    """Raw PII in finding.text needs ``PII_RAW_READ`` -- a grant, not a role name.

    ``authz.ROLE_DEFAULTS`` hands it to compliance_officer/dpo (admin holds
    everything); the Roles screen can move it.
    """
    import authz

    uid = (_db()._actor_user_id() or "").strip()
    return bool(uid) and authz.has_permission(uid, authz.PII_RAW_READ)


def actor_is_admin(user_id: str | None = None) -> bool:
    """True when the actor has Admin role or perm-admin-write."""
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _actor_user_id = _mod._actor_user_id
    uid = (user_id or _actor_user_id() or "").strip()
    if not uid:
        return False
    with engine.connect() as conn:
        for name in _actor_role_names(conn, uid):
            if name == "admin":
                return True
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT 1
                    FROM user_roles ur
                    JOIN role_permissions rp ON rp.role_id = ur.role_id
                    WHERE ur.user_id = :uid
                      AND rp.permission_id = 'perm-admin-write'
                    LIMIT 1
                    """
                ),
                {"uid": uid},
            )
        )
        return row is not None


def _pii_findings_grouped(
    conn: Any,
    redaction_ids: list[str],
    *,
    allow_raw: bool,
    turn_text_by_id: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    """Findings for many redaction records. Never puts raw PII in `text` unless allow_raw."""
    _mod = _db()
    _rows = _mod._rows
    if not redaction_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT id, redaction_id, type, masked, confidence, accepted,
                       transcript_turn_id, start_offset, end_offset
                FROM pii_findings
                WHERE redaction_id = ANY(:ids)
                ORDER BY redaction_id, created_at, id
                """
            ),
            {"ids": redaction_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        pii_type = r["type"] if r["type"] in _PII_TYPES else "custom"
        masked = r["masked"] or ""
        turn_id = r["transcript_turn_id"] or ""
        start = int(r["start_offset"] or 0)
        end = int(r["end_offset"] or 0)
        raw = masked
        if allow_raw and turn_id and turn_id in turn_text_by_id and end > start:
            turn_text = turn_text_by_id[turn_id]
            if 0 <= start < end <= len(turn_text):
                raw = turn_text[start:end]
        grouped.setdefault(r["redaction_id"], []).append(
            {
                "id": r["id"],
                "turnId": turn_id,
                "type": pii_type,
                "start": start,
                "end": end,
                "text": raw,
                "masked": masked,
                "confidence": float(r["confidence"] or 0),
                "source": "auto",
                "accepted": bool(r["accepted"]),
            }
        )
    return grouped


def _redaction_audio_grouped(conn: Any, redaction_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    _mod = _db()
    _rows = _mod._rows
    if not redaction_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT s.redaction_id, s.at_sec, s.duration_sec, s.muted, s.finding_id,
                       COALESCE(f.type, 'custom') AS type
                FROM redaction_audio_segments s
                LEFT JOIN pii_findings f ON f.id = s.finding_id
                WHERE s.redaction_id = ANY(:ids)
                ORDER BY s.redaction_id, s.at_sec, s.id
                """
            ),
            {"ids": redaction_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        pii_type = r["type"] if r["type"] in _PII_TYPES else "custom"
        finding_id = r["finding_id"] or ""
        if not finding_id:
            continue
        grouped.setdefault(r["redaction_id"], []).append(
            {
                "atSec": int(r["at_sec"] or 0),
                "durSec": float(r["duration_sec"] or 0),
                "type": pii_type,
                "findingId": finding_id,
                "muted": bool(r["muted"]),
            }
        )
    return grouped


def _redaction_transcripts_grouped(
    conn: Any,
    interaction_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    _mod = _db()
    _rows = _mod._rows
    _speaker_screen = _mod._speaker_screen
    if not interaction_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT id, interaction_id, at_sec, speaker, text
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
        grouped.setdefault(r["interaction_id"], []).append(
            {
                "id": r["id"],
                "t": int(r["at_sec"] or 0),
                "speaker": _speaker_screen(r["speaker"]),
                "text": r["text"] or "",
            }
        )
    return grouped


def _apply_masks_to_transcript(
    turns: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replace finding spans with masked values so the payload never leaks raw PII
    for viewers who are not allowed to see it."""
    by_turn: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        if f.get("turnId") and f.get("end", 0) > f.get("start", 0):
            by_turn.setdefault(f["turnId"], []).append(f)
    if not by_turn:
        return turns
    out: list[dict[str, Any]] = []
    for turn in turns:
        spans = sorted(by_turn.get(turn["id"], []), key=lambda x: x["start"], reverse=True)
        # `turn_text`, not `text` — the module-level sqlalchemy `text` import is
        # shadowed for the rest of the function otherwise, and any SQL added
        # here later would fail with a confusing TypeError.
        turn_text = turn["text"]
        invalid = False
        for f in spans:
            start, end = int(f["start"]), int(f["end"])
            if not (0 <= start < end <= len(turn_text)):
                invalid = True
                break
            turn_text = turn_text[:start] + (f.get("masked") or "") + turn_text[end:]
        if invalid:
            # Fail closed: do not leave raw PII when offsets are corrupt.
            masked_bits = [str(f.get("masked") or "[redacted]") for f in spans]
            turn_text = " ".join(masked_bits) if masked_bits else "[redacted]"
        out.append({**turn, "text": turn_text})
    return out


_REDACTION_LIST_SQL = """
    SELECT
      rr.id,
      rr.interaction_id AS call_id,
      rr.customer_id,
      rr.reviewed,
      c.name AS customer,
      i.channel,
      i.started_at,
      i.duration_sec,
      COALESCE(u.name, b.name, 'Unassigned') AS handler
    FROM redaction_records rr
    JOIN customers c ON c.id = rr.customer_id
    JOIN interactions i ON i.id = rr.interaction_id
    LEFT JOIN users u ON u.id = i.handler_user_id
    LEFT JOIN bots b ON b.id = i.handler_bot_id
    WHERE i.tenant_id = :tenant_id
      AND c.tenant_id = :tenant_id
"""


def _redaction_rows_to_screen(conn: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    allow_raw = _actor_can_view_raw_pii(conn)
    redaction_ids = [r["id"] for r in rows]
    interaction_ids = [r["call_id"] for r in rows]
    transcripts = _redaction_transcripts_grouped(conn, interaction_ids)
    turn_text_by_id: dict[str, str] = {}
    for turns in transcripts.values():
        for t in turns:
            turn_text_by_id[t["id"]] = t["text"]
    findings_by = _pii_findings_grouped(
        conn, redaction_ids, allow_raw=allow_raw, turn_text_by_id=turn_text_by_id
    )
    audio_by = _redaction_audio_grouped(conn, redaction_ids)

    out: list[dict[str, Any]] = []
    for r in rows:
        findings = findings_by.get(r["id"], [])
        turns = transcripts.get(r["call_id"], [])
        if not allow_raw:
            turns = _apply_masks_to_transcript(turns, findings)
        occurred = r["started_at"]
        out.append(
            {
                "id": r["id"],
                "callId": r["call_id"],
                "customer": r["customer"] or "",
                "customerId": r["customer_id"],
                "channel": _redaction_channel(r["channel"]),
                "handler": r["handler"] or "Unassigned",
                "occurredAt": occurred if isinstance(occurred, str) else (occurred.isoformat() if occurred else ""),
                "durationSec": int(r["duration_sec"] or 0),
                "transcript": turns,
                "findings": findings,
                "audioSegments": audio_by.get(r["id"], []),
                "reviewed": bool(r["reviewed"]),
            }
        )
    return out


def list_redaction_records(
    *,
    limit: int = 100,
    before_id: str | None = None,
) -> list[dict[str, Any]]:
    """Redaction Hub queue — screen RedactionRecord shape. Scoped to TENANT_ID.

    Newest-first with an enforced maximum page size. Optional ``before_id``
    names the last record of the previous page; the next page continues from
    that record's position in the sort (exclusive).
    """
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _tenant = _mod._tenant
    capped = max(1, min(int(limit or 100), 200))
    params: dict[str, Any] = {"tenant_id": _tenant(), "limit": capped}
    cursor_sql = ""
    if before_id:
        # The cursor must compare on the same key the ORDER BY uses. Comparing
        # `rr.id` alone against a list ordered by (started_at DESC, id DESC)
        # both skipped and repeated records, because id order and timestamp
        # order are unrelated.
        cursor_sql = """
              AND (COALESCE(i.started_at, rr.created_at), rr.id) < (
                    SELECT COALESCE(i2.started_at, rr2.created_at), rr2.id
                    FROM redaction_records rr2
                    JOIN interactions i2 ON i2.id = rr2.interaction_id
                    WHERE rr2.id = :before_id AND i2.tenant_id = :tenant_id
                  )
        """
        params["before_id"] = before_id
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    _REDACTION_LIST_SQL
                    + cursor_sql
                    + """
                    ORDER BY COALESCE(i.started_at, rr.created_at) DESC, rr.id DESC
                    LIMIT :limit
                    """
                ),
                params,
            )
        )
        return _redaction_rows_to_screen(conn, rows)


def get_redaction_record(redaction_id: str) -> dict[str, Any]:
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _tenant = _mod._tenant
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(_REDACTION_LIST_SQL + " AND rr.id = :id"),
                {"tenant_id": _tenant(), "id": redaction_id},
            )
        )
        if row is None:
            raise KeyError("redaction_record_not_found")
        return _redaction_rows_to_screen(conn, [row])[0]


def list_redaction_rules() -> list[dict[str, Any]]:
    """Tenant redaction rule configs — screen RedactionRules entries."""
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _tenant = _mod._tenant
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT pii_type, enabled, replacement
                    FROM redaction_rule_configs
                    WHERE tenant_id = :tenant_id
                    ORDER BY pii_type
                    """
                ),
                {"tenant_id": _tenant()},
            )
        )
        by_type = {r["pii_type"]: r for r in rows if r["pii_type"] in _PII_TYPES}
        # Always return the full screen vocabulary so the Rules sheet never gaps.
        return [
            _map_redaction_rule(pii_type, by_type.get(pii_type))
            for pii_type in _PII_LABELS
        ]


def _map_redaction_rule(pii_type: str, row: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "piiType": pii_type,
        "enabled": bool(row["enabled"]) if row else False,
        "replacement": (row["replacement"] if row else f"[REDACTED-{pii_type.upper()}]"),
        "label": _PII_LABELS[pii_type],
    }


def get_redaction_rule(pii_type: str) -> dict[str, Any] | None:
    """Single redaction rule — used by write paths instead of re-listing."""
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _tenant = _mod._tenant
    if pii_type not in _PII_LABELS:
        return None
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT pii_type, enabled, replacement
                    FROM redaction_rule_configs
                    WHERE tenant_id = :tenant_id AND pii_type = :pii_type
                    """
                ),
                {"tenant_id": _tenant(), "pii_type": pii_type},
            )
        )
    return _map_redaction_rule(pii_type, row)


