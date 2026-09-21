"""Redaction Hub reads.

Peeled from ``db.py`` (WP-036 peel 8). Call sites stay ``db.*`` via a
bottom-of-file re-export. Reach the engine through :func:`_db`, never
``from db_core import engine``: the ``db_tx`` fixture wraps ``db.engine``,
and a name bound from ``db_core`` bypasses that proxy.

``_speaker_screen`` moved to ``db_core`` first (roadmap peel 8
prerequisite): the violations/transcript kernel also calls it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
import logging

from sqlalchemy import text
import json
from db_core import _actor_user_id, _one, _rows, _speaker_screen, _tenant

logger = logging.getLogger(__name__)


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


def _actor_can_view_raw_pii(conn: Any) -> bool:
    """Raw PII in finding.text needs ``PII_RAW_READ`` -- a grant, not a role name.

    ``authz.ROLE_DEFAULTS`` hands it to compliance_officer/dpo (admin holds
    everything); the Roles screen can move it.
    """
    import authz

    uid = (_actor_user_id() or "").strip()
    return bool(uid) and authz.has_permission(uid, authz.PII_RAW_READ)


def actor_is_admin(user_id: str | None = None) -> bool:
    """True when the actor is a superuser.

    One reading: ``authz.has_permission(uid, ADMIN_WRITE)``. authz resolves
    the grants (and the documented admin-by-name rule for an unconfigured
    role) in one place; this used to restate both halves with its own SQL, so
    the Redaction Hub and the route guard could disagree about who is admin.
    """
    import authz

    uid = (user_id or _actor_user_id() or "").strip()
    return bool(uid) and authz.has_permission(uid, authz.ADMIN_WRITE)


def _pii_findings_grouped(
    conn: Any,
    redaction_ids: list[str],
    *,
    allow_raw: bool,
    turn_text_by_id: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    """Findings for many redaction records. Never puts raw PII in `text` unless allow_raw."""
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
    engine = _db().engine
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
    engine = _db().engine
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
    engine = _db().engine
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
    engine = _db().engine
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


# ---------------------------------------------------------------------------
# Redaction writes + export jobs
# ---------------------------------------------------------------------------

_EXPORT_FORMATS = frozenset({"pdf", "csv", "audio-zip"})
_EXPORT_SCOPES = frozenset({"transcript", "audio", "metadata"})
_EXPORT_STATUSES = frozenset({"queued", "ready", "failed"})


def patch_pii_finding(finding_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    d = _db()
    with d.engine.begin() as conn:
        row = d._one(
            conn.execute(
                text(
                    """
                    SELECT f.id, f.redaction_id, f.accepted
                    FROM pii_findings f
                    JOIN redaction_records r ON r.id = f.redaction_id
                    JOIN interactions i ON i.id = r.interaction_id
                    WHERE f.id = :id AND i.tenant_id = :tenant
                    """
                ),
                {"id": finding_id, "tenant": d.current_tenant()},
            )
        )
        if row is None:
            raise KeyError("finding_not_found")
        if "accepted" not in payload:
            raise ValueError("accepted_required")
        accepted = bool(payload["accepted"])
        conn.execute(
            text("UPDATE pii_findings SET accepted = :a WHERE id = :id"),
            {"id": finding_id, "a": accepted},
        )
        d._activity(
            conn,
            "redaction_record",
            row["redaction_id"],
            "finding_updated",
            "PII finding updated",
            note=f"{finding_id}:accepted={accepted}",
        )
        return {"id": finding_id, "accepted": accepted, "redactionId": row["redaction_id"]}


def patch_audio_segment_mute(
    redaction_id: str, finding_id: str, muted: bool
) -> dict[str, Any]:
    d = _db()
    with d.engine.begin() as conn:
        row = d._one(
            conn.execute(
                text(
                    """
                    SELECT s.id
                    FROM redaction_audio_segments s
                    JOIN redaction_records r ON r.id = s.redaction_id
                    JOIN interactions i ON i.id = r.interaction_id
                    WHERE s.redaction_id = :rid AND s.finding_id = :fid
                      AND i.tenant_id = :tenant
                    LIMIT 1
                    """
                ),
                {"rid": redaction_id, "fid": finding_id, "tenant": d.current_tenant()},
            )
        )
        if row is None:
            raise KeyError("audio_segment_not_found")
        conn.execute(
            text("UPDATE redaction_audio_segments SET muted = :m WHERE id = :id"),
            {"id": row["id"], "m": bool(muted)},
        )
        # Muting audio changes what an export of the call contains: an evidence
        # change, and it leaves the same activity row a finding decision does.
        d._activity(
            conn,
            "redaction_record",
            redaction_id,
            "audio_segment_updated",
            "Audio segment muted" if muted else "Audio segment unmuted",
            note=f"{finding_id}:muted={bool(muted)}",
        )
        return {
            "redactionId": redaction_id,
            "findingId": finding_id,
            "muted": bool(muted),
        }


def patch_redaction_record(
    redaction_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    d = _db()
    with d.engine.begin() as conn:
        existing = d._one(
            conn.execute(
                text(
                    """
                    SELECT r.id
                    FROM redaction_records r
                    JOIN interactions i ON i.id = r.interaction_id
                    WHERE r.id = :id AND i.tenant_id = :tenant
                    """
                ),
                {"id": redaction_id, "tenant": d.current_tenant()},
            )
        )
        if existing is None:
            raise KeyError("redaction_record_not_found")
        if "reviewed" in payload and payload["reviewed"] is not None:
            reviewed = bool(payload["reviewed"])
            if reviewed:
                conn.execute(
                    text(
                        """
                        UPDATE redaction_records
                        SET reviewed = true,
                            reviewed_by_user_id = :uid,
                            reviewed_at = now(),
                            updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {"id": redaction_id, "uid": d._actor_user_id()},
                )
            else:
                conn.execute(
                    text(
                        """
                        UPDATE redaction_records
                        SET reviewed = false,
                            reviewed_by_user_id = NULL,
                            reviewed_at = NULL,
                            updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {"id": redaction_id},
                )
            d._activity(
                conn,
                "redaction_record",
                redaction_id,
                "reviewed" if reviewed else "unreviewed",
                "Redaction review updated",
            )
        return d.get_redaction_record(redaction_id)


def patch_redaction_rule(pii_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    d = _db()
    with d.engine.begin() as conn:
        row = d._one(
            conn.execute(
                text(
                    """
                    SELECT id, pii_type, enabled, replacement
                    FROM redaction_rule_configs
                    WHERE tenant_id = :tenant AND pii_type = :t
                    LIMIT 1
                    """
                ),
                {"tenant": d.current_tenant(), "t": pii_type},
            )
        )
        if row is None:
            raise KeyError("redaction_rule_not_found")
        sets: list[str] = []
        params: dict[str, Any] = {"id": row["id"]}
        if "enabled" in payload and payload["enabled"] is not None:
            sets.append("enabled = :enabled")
            params["enabled"] = bool(payload["enabled"])
        if "replacement" in payload and payload["replacement"] is not None:
            sets.append("replacement = :replacement")
            params["replacement"] = str(payload["replacement"])
        if not sets:
            raise ValueError("no_fields")
        sets.append("updated_at = now()")
        conn.execute(
            text(f"UPDATE redaction_rule_configs SET {', '.join(sets)} WHERE id = :id"),
            params,
        )
    rule = d.get_redaction_rule(pii_type)
    if rule is None:
        raise KeyError("redaction_rule_not_found")
    return rule


def _parse_scope_blob(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        return {
            "parts": [],
            "actorRole": "",
            "downloadCount": 0,
            "entitiesRedacted": 0,
            "kind": "redaction",
        }
    parts = raw.get("parts") or raw.get("scope") or []
    if not isinstance(parts, list):
        parts = []
    kind = raw.get("kind") if raw.get("kind") in {"redaction", "dashboard"} else "redaction"
    return {
        "parts": [p for p in parts if p in _EXPORT_SCOPES],
        "actorRole": str(raw.get("actorRole") or ""),
        "downloadCount": int(raw.get("downloadCount") or 0),
        "entitiesRedacted": int(raw.get("entitiesRedacted") or 0),
        "kind": kind,
        "range": str(raw.get("range") or "30d"),
        "segment": str(raw.get("segment") or "all"),
        "team": str(raw.get("team") or "all"),
        "emailTo": str(raw.get("emailTo") or ""),
        "mailStatus": raw.get("mailStatus"),
    }


def _map_export_job(row: dict[str, Any], record_ids: list[str]) -> dict[str, Any]:
    meta = _parse_scope_blob(row.get("scope"))
    status = (row.get("status") or "queued").lower()
    if status == "completed":
        status = "ready"
    if status not in _EXPORT_STATUSES:
        status = "queued"
    at = row.get("created_at")
    kind = row.get("kind") if row.get("kind") in {"redaction", "dashboard"} else meta["kind"]
    fmt = row["format"] if row.get("format") in _EXPORT_FORMATS else ("csv" if kind == "dashboard" else "pdf")
    mail = meta.get("mailStatus")
    return {
        "id": row["id"],
        "at": at.isoformat() if isinstance(at, (datetime, date)) else str(at),
        "actor": row.get("actor_name") or "Unknown",
        "actorRole": meta["actorRole"] or ("Leadership" if kind == "dashboard" else "Compliance Officer"),
        "recordIds": record_ids,
        "format": fmt,
        "scope": meta["parts"] or (["metadata"] if kind == "dashboard" else ["transcript"]),
        "watermark": row.get("watermark") or "",
        "status": status,
        "downloadCount": meta["downloadCount"],
        "entitiesRedacted": meta["entitiesRedacted"],
        "kind": kind,
        "mailStatus": str(mail) if mail else None,
    }


def _export_jobs_has_kind_column(conn: Any) -> bool:
    return bool(
        conn.execute(
            text(
                """
                SELECT 1 FROM information_schema.columns
                 WHERE table_schema = 'public'
                   AND table_name = 'export_jobs'
                   AND column_name = 'kind'
                """
            )
        ).scalar()
    )


def _materialize_export_zip(
    job_id: str, record_ids: list[str], scope_parts: list[str], fmt: str
) -> tuple[str | None, str]:
    """Write the zip to MinIO (or local fallback). Returns (storage_ref, status)."""
    from pathlib import Path

    from voice.redaction_export import build_export_zip, write_redacted_wav

    d = _db()
    try:
        with d.engine.connect() as conn:
            for rid in record_ids:
                rec = d._one(
                    conn.execute(
                        text(
                            """
                            SELECT r.id, r.interaction_id
                            FROM redaction_records r
                            JOIN interactions i ON i.id = r.interaction_id
                            WHERE r.id = :id AND i.tenant_id = :tenant
                            """
                        ),
                        {"id": rid, "tenant": d.current_tenant()},
                    )
                )
                if rec is None:
                    continue
                muted = conn.execute(
                    text(
                        """
                        SELECT count(*) FROM redaction_audio_segments
                        WHERE redaction_id = :id AND muted = true
                        """
                    ),
                    {"id": rid},
                ).scalar()
                if int(muted or 0) > 0 or "audio" in scope_parts:
                    try:
                        write_redacted_wav(rec["interaction_id"], rid)
                    except Exception:
                        logger.exception("redacted wav for %s failed", rid)
        blob = build_export_zip(job_id, record_ids, scope_parts)
        key = f"export-bundles/{d.current_tenant()}/{job_id}.zip"
        storage_ref: str | None = None
        try:
            import storage

            if storage.is_configured():
                storage_ref = storage.put_bytes(
                    key, blob, "application/zip", bucket=storage.RECORDINGS_BUCKET
                )
        except Exception:
            logger.exception("export zip minio upload failed")
        if not storage_ref:
            local_dir = Path(__file__).resolve().parent / ".cache" / "export-bundles"
            local_dir.mkdir(parents=True, exist_ok=True)
            (local_dir / f"{job_id}.zip").write_bytes(blob)
            storage_ref = f"local://export-bundles/{job_id}.zip"
        _ = fmt
        return storage_ref, "ready"
    except Exception:
        logger.exception("export zip failed job=%s", job_id)
        return None, "failed"


def download_export_job(job_id: str) -> dict[str, Any]:
    """Bytes + filename for GET /export-jobs/{id}/download. Bumps download count."""
    d = _db()
    with d.engine.begin() as conn:
        row = d._one(
            conn.execute(
                text(
                    """
                    SELECT ej.id, ej.storage_ref, ej.status, ej.scope, ej.format
                    FROM export_jobs ej
                    WHERE ej.id = :id
                      AND ej.tenant_id = :tenant
                      AND (
                        coalesce(ej.scope->>'kind', 'redaction') = 'dashboard'
                        OR EXISTS (
                          SELECT 1
                          FROM export_job_records ejr
                          JOIN redaction_records r ON r.id = ejr.redaction_id
                          JOIN interactions i ON i.id = r.interaction_id
                          WHERE ejr.export_job_id = ej.id
                            AND i.tenant_id = :tenant
                        )
                      )
                    FOR UPDATE OF ej
                    """
                ),
                {"id": job_id, "tenant": d.current_tenant()},
            )
        )
        if row is None:
            raise KeyError("export_job_not_found")
        if row["status"] != "ready" or not row.get("storage_ref"):
            raise ValueError("export_not_ready")
        meta = _parse_scope_blob(row["scope"])
        meta["downloadCount"] = int(meta["downloadCount"]) + 1
        conn.execute(
            text(
                """
                UPDATE export_jobs
                SET scope = CAST(:scope AS jsonb), updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": job_id, "scope": json.dumps(meta)},
        )
        d._activity(
            conn,
            "export_job",
            job_id,
            "downloaded",
            "Export bundle downloaded",
            note=str(row["storage_ref"]),
        )
        ref = str(row["storage_ref"])
        kind = meta.get("kind") or "redaction"
        fmt = row.get("format") or ("csv" if kind == "dashboard" else "pdf")
        if kind != "dashboard":
            import authz

            if not authz.has_permission(d._actor_user_id(), authz.COMPLIANCE_READ):
                raise PermissionError("forbidden")
    from voice.recordings import _load_bytes

    if kind == "dashboard" or fmt == "csv":
        return {
            "bytes": _load_bytes(ref),
            "filename": f"{job_id}.csv",
            "mimeType": "text/csv",
        }
    return {
        "bytes": _load_bytes(ref),
        "filename": f"{job_id}.zip",
        "mimeType": "application/zip",
    }


def list_export_jobs(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    d = _db()
    page, skip = d.clamp_list_limit(limit), d.clamp_offset(offset)
    with d.engine.connect() as conn:
        rows = d._rows(
            conn.execute(
                text(
                    """
                    SELECT ej.*, u.name AS actor_name
                    FROM export_jobs ej
                    LEFT JOIN users u ON u.id = ej.actor_user_id
                    WHERE EXISTS (
                      SELECT 1
                      FROM export_job_records ejr
                      JOIN redaction_records r ON r.id = ejr.redaction_id
                      JOIN interactions i ON i.id = r.interaction_id
                      WHERE ejr.export_job_id = ej.id
                        AND i.tenant_id = :tenant
                    )
                    ORDER BY ej.created_at DESC, ej.id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"tenant": d.current_tenant(), "limit": page, "offset": skip},
            )
        )
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        links = d._rows(
            conn.execute(
                text(
                    """
                    SELECT export_job_id, redaction_id
                    FROM export_job_records
                    WHERE export_job_id = ANY(:ids)
                    """
                ),
                {"ids": ids},
            )
        )
        by_job: dict[str, list[str]] = {i: [] for i in ids}
        for link in links:
            by_job.setdefault(link["export_job_id"], []).append(link["redaction_id"])
        return [_map_export_job(r, by_job.get(r["id"], [])) for r in rows]


def _actor_mailbox(conn: Any, user_id: str) -> str | None:
    row = _one(
        conn.execute(
            text(
                """
                SELECT coalesce(nullif(trim(u.email), ''), nullif(trim(u.entra_upn), '')) AS email
                  FROM users u
                 WHERE u.id = :id
                """
            ),
            {"id": user_id},
        )
    )
    email = (row or {}).get("email") if row else None
    if not email or "@" not in str(email):
        return None
    return str(email).strip().lower()


def _create_dashboard_export_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Leadership CSV. No export_job_records rows — those require a redaction id."""
    import invite_mail
    from pathlib import Path

    d = _db()
    range_key = str(payload.get("range") or "30d")
    segment = str(payload.get("segment") or "all")
    team = str(payload.get("team") or "all")
    csv_body = d.get_dashboard_csv(range_key, segment, team)
    blob = csv_body.encode("utf-8")
    job_id = d._id("EX")
    actor_id = d._actor_user_id()
    with d.engine.begin() as conn:
        email_to = _actor_mailbox(conn, actor_id)
        if not email_to:
            raise ValueError("actor_email_missing")
        meta = {
            "kind": "dashboard",
            "parts": ["metadata"],
            "actorRole": payload.get("actorRole") or "Leadership",
            "downloadCount": 0,
            "entitiesRedacted": 0,
            "range": range_key,
            "segment": segment,
            "team": team,
            "emailTo": email_to,
        }
        has_kind = _export_jobs_has_kind_column(conn)
        cols = "id, tenant_id, actor_user_id, format, scope, watermark, status, storage_ref"
        vals = ":id, :tenant_id, :uid, :fmt, CAST(:scope AS jsonb), :wm, 'queued', NULL"
        params: dict[str, Any] = {
            "id": job_id,
            "tenant_id": d.current_tenant(),
            "uid": actor_id,
            "fmt": "csv",
            "scope": json.dumps(meta),
            "wm": payload.get("watermark") or "",
        }
        if has_kind:
            cols = cols.replace("format,", "kind, format,")
            vals = vals.replace(":fmt,", "'dashboard', :fmt,")
        conn.execute(
            text(f"INSERT INTO export_jobs ({cols}) VALUES ({vals})"),
            params,
        )
        d._activity(conn, "export_job", job_id, "created", "Dashboard export created")

    storage_ref: str | None = None
    status = "failed"
    try:
        import storage

        key = f"export-bundles/{d.current_tenant()}/{job_id}.csv"
        if storage.is_configured():
            storage_ref = storage.put_bytes(key, blob, "text/csv", bucket=storage.RECORDINGS_BUCKET)
    except Exception:
        logger.exception("dashboard csv minio upload failed")
    if not storage_ref:
        local_dir = Path(__file__).resolve().parent / ".cache" / "export-bundles"
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / f"{job_id}.csv").write_bytes(blob)
        storage_ref = f"local://export-bundles/{job_id}.csv"
        status = "ready"
    else:
        status = "ready"

    origin = invite_mail.public_origin()
    download_url = f"{origin}/export-jobs/{job_id}/download"
    mail_status = invite_mail.send_dashboard_report_email(
        to_email=email_to, download_url=download_url, range_key=range_key
    )
    meta["mailStatus"] = mail_status or "sent"

    with d.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE export_jobs
                   SET status = :status, storage_ref = :ref,
                       scope = CAST(:scope AS jsonb), updated_at = now()
                 WHERE id = :id
                """
            ),
            {
                "id": job_id,
                "status": status,
                "ref": storage_ref,
                "scope": json.dumps(meta),
            },
        )
        row = d._one(
            conn.execute(
                text(
                    """
                    SELECT ej.*, u.name AS actor_name
                    FROM export_jobs ej
                    LEFT JOIN users u ON u.id = ej.actor_user_id
                    WHERE ej.id = :id
                    """
                ),
                {"id": job_id},
            )
        )
        assert row is not None
        return _map_export_job(row, [])


def create_export_job(payload: dict[str, Any]) -> dict[str, Any]:
    kind = payload.get("kind") or "redaction"
    if kind == "dashboard":
        return _create_dashboard_export_job(payload)
    d = _db()
    with d.engine.begin() as conn:
        record_ids = list(payload.get("recordIds") or [])
        if not record_ids:
            raise ValueError("record_ids_required")
        fmt = payload.get("format") or "pdf"
        if fmt not in _EXPORT_FORMATS:
            raise ValueError("invalid_format")
        scope_parts = [s for s in (payload.get("scope") or []) if s in _EXPORT_SCOPES]
        if not scope_parts:
            scope_parts = ["transcript"]
        # Validate records exist + tenant
        found = d._rows(
            conn.execute(
                text(
                    """
                    SELECT r.id
                    FROM redaction_records r
                    JOIN interactions i ON i.id = r.interaction_id
                    WHERE r.id = ANY(:ids) AND i.tenant_id = :tenant
                    """
                ),
                {"ids": record_ids, "tenant": d.current_tenant()},
            )
        )
        found_ids = {r["id"] for r in found}
        missing = [x for x in record_ids if x not in found_ids]
        if missing:
            raise KeyError(f"redaction_records_not_found:{','.join(missing)}")
        entities = conn.execute(
            text(
                """
                SELECT count(*) FROM pii_findings
                WHERE redaction_id = ANY(:ids) AND accepted = true
                """
            ),
            {"ids": record_ids},
        ).scalar()
        job_id = d._id("EX")
        meta = {
            "parts": scope_parts,
            "actorRole": payload.get("actorRole") or "Compliance Officer",
            "downloadCount": 0,
            "entitiesRedacted": int(entities or 0),
        }
        conn.execute(
            text(
                """
                INSERT INTO export_jobs (
                  id, tenant_id, actor_user_id, format, scope, watermark, status,
                  storage_ref
                ) VALUES (
                  :id, :tenant_id, :uid, :fmt, CAST(:scope AS jsonb), :wm, 'queued', NULL
                )
                """
            ),
            {
                "id": job_id,
                "tenant_id": d.current_tenant(),
                "uid": d._actor_user_id(),
                "fmt": fmt,
                "scope": json.dumps(meta),
                "wm": payload.get("watermark") or "",
            },
        )
        for rid in record_ids:
            conn.execute(
                text(
                    """
                    INSERT INTO export_job_records (export_job_id, redaction_id)
                    VALUES (:jid, :rid)
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"jid": job_id, "rid": rid},
            )
        d._activity(
            conn,
            "export_job",
            job_id,
            "created",
            "Export job created",
            note=f"{len(record_ids)} records",
        )
    storage_ref, status = _materialize_export_zip(job_id, record_ids, scope_parts, fmt)
    with d.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE export_jobs
                SET status = :status, storage_ref = :ref, updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": job_id, "status": status, "ref": storage_ref},
        )
        row = d._one(
            conn.execute(
                text(
                    """
                    SELECT ej.*, u.name AS actor_name
                    FROM export_jobs ej
                    LEFT JOIN users u ON u.id = ej.actor_user_id
                    WHERE ej.id = :id
                    """
                ),
                {"id": job_id},
            )
        )
        assert row is not None
        return _map_export_job(row, record_ids)


def patch_export_job(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    d = _db()
    with d.engine.begin() as conn:
        row = d._one(
            conn.execute(
                text(
                    """
                    SELECT ej.id, ej.scope, ej.status
                    FROM export_jobs ej
                    WHERE ej.id = :id
                      AND EXISTS (
                        SELECT 1
                        FROM export_job_records ejr
                        JOIN redaction_records r ON r.id = ejr.redaction_id
                        JOIN interactions i ON i.id = r.interaction_id
                        WHERE ejr.export_job_id = ej.id
                          AND i.tenant_id = :tenant
                      )
                    FOR UPDATE OF ej
                    """
                ),
                {"id": job_id, "tenant": d.current_tenant()},
            )
        )
        if row is None:
            raise KeyError("export_job_not_found")
        meta = _parse_scope_blob(row["scope"])
        status = row["status"]
        if payload.get("bumpDownload"):
            meta["downloadCount"] = int(meta["downloadCount"]) + 1
        if "status" in payload and payload["status"] is not None:
            st = str(payload["status"]).lower()
            if st == "completed":
                st = "ready"
            if st not in _EXPORT_STATUSES:
                raise ValueError("invalid_export_status")
            status = st
        conn.execute(
            text(
                """
                UPDATE export_jobs
                SET scope = CAST(:scope AS jsonb),
                    status = :status,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": job_id, "scope": json.dumps(meta), "status": status},
        )
        full = d._one(
            conn.execute(
                text(
                    """
                    SELECT ej.*, u.name AS actor_name
                    FROM export_jobs ej
                    LEFT JOIN users u ON u.id = ej.actor_user_id
                    WHERE ej.id = :id
                    """
                ),
                {"id": job_id},
            )
        )
        links = [
            r["redaction_id"]
            for r in d._rows(
                conn.execute(
                    text(
                        "SELECT redaction_id FROM export_job_records WHERE export_job_id = :id"
                    ),
                    {"id": job_id},
                )
            )
        ]
        assert full is not None
        return _map_export_job(full, links)
