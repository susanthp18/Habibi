"""Phase 3B seed-chip close-out — coaching, calibration, redaction writes,
routing writes, workspace rolling stats / right-rail.

Imported at the bottom of db.py so call sites stay `db.*`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

# Operating timezone for operator-facing time labels. Fixed offset, same as
# db._IST — India has no DST, so this needs no tz database at runtime.
_IST = timezone(timedelta(hours=5, minutes=30))

# Re-use helpers/engine from db — imported lazily inside functions to avoid cycles
# when this module is loaded from db.py itself.


def _db():
    import db as d

    return d


# ---------------------------------------------------------------------------
# QA Coaching
# ---------------------------------------------------------------------------

_COACH_STATUSES = frozenset({"assigned", "in_progress", "done"})


def _coach_status(raw: str | None) -> str:
    """Normalize known coaching statuses; unknown → assigned (read path)."""
    s = (raw or "").strip().lower()
    if s in {"done", "completed", "closed"}:
        return "done"
    if s in {"in_progress", "in-progress", "progress"}:
        return "in_progress"
    if s in {"assigned"}:
        return "assigned"
    return "assigned"


def _require_coach_status(raw: str | None) -> str:
    """Validate write payloads — reject unknown verbs like complete/canceled."""
    s = (raw or "").strip().lower()
    if s in {"done", "completed", "closed"}:
        return "done"
    if s in {"in_progress", "in-progress", "progress"}:
        return "in_progress"
    if s in {"assigned"}:
        return "assigned"
    raise ValueError("invalid_coaching_status")


def _scores_to_entries(scores: Any, criterion_ids: list[str]) -> list[dict[str, Any]]:
    if isinstance(scores, str):
        try:
            scores = json.loads(scores)
        except json.JSONDecodeError:
            scores = {}
    if not isinstance(scores, dict):
        scores = {}
    out: list[dict[str, Any]] = []
    for cid in criterion_ids:
        val = scores.get(cid)
        try:
            n = float(val) if val is not None else 0.0
        except (TypeError, ValueError):
            n = 0.0
        n = max(0.0, min(5.0, n))
        out.append(
            {
                "criterionId": cid,
                "aiSuggested": n,
                "score": n,
            }
        )
    return out


def _criterion_ids(conn: Any, rubric_id: str = "rubric-v1") -> list[str]:
    d = _db()
    rows = d._rows(
        conn.execute(
            text(
                """
                SELECT c.id
                FROM qa_rubric_criteria c
                JOIN qa_rubric_sections s ON s.id = c.section_id
                WHERE s.rubric_id = :rid
                ORDER BY s.weight DESC, c.id
                """
            ),
            {"rid": rubric_id},
        )
    )
    return [r["id"] for r in rows]


def _resolve_subject_by_name(conn: Any, name: str) -> tuple[str | None, str | None]:
    """Return (user_id, bot_id) for a display name — never invent IDs."""
    d = _db()
    row = d._one(
        conn.execute(
            text("SELECT id FROM users WHERE lower(name) = lower(:n) LIMIT 1"),
            {"n": name.strip()},
        )
    )
    if row:
        return row["id"], None
    row = d._one(
        conn.execute(
            text("SELECT id FROM bots WHERE lower(name) = lower(:n) LIMIT 1"),
            {"n": name.strip()},
        )
    )
    if row:
        return None, row["id"]
    raise KeyError(f"subject_not_found:{name}")


def _coaching_notes_grouped(conn: Any, ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    d = _db()
    if not ids:
        return {}
    rows = d._rows(
        conn.execute(
            text(
                """
                SELECT ae.entity_id, ae.created_at, ae.note,
                       coalesce(u.name, 'System') AS author
                FROM activity_events ae
                LEFT JOIN users u ON u.id = ae.actor_user_id
                WHERE ae.entity_type = 'coaching_action'
                  AND ae.kind = 'note_added'
                  AND ae.entity_id = ANY(:ids)
                ORDER BY ae.created_at ASC
                """
            ),
            {"ids": ids},
        )
    )
    out: dict[str, list[dict[str, Any]]] = {i: [] for i in ids}
    for r in rows:
        at = r["created_at"]
        out.setdefault(r["entity_id"], []).append(
            {
                "at": at.isoformat() if hasattr(at, "isoformat") else str(at),
                "author": r["author"] or "System",
                "text": r["note"] or "",
            }
        )
    return out


def _map_coaching(row: dict[str, Any], notes: list[dict[str, Any]]) -> dict[str, Any]:
    agent = row.get("agent_name") or row.get("bot_name") or "Unassigned"
    due = row.get("due_at")
    created = row.get("created_at")
    return {
        "id": row["id"],
        "agentId": agent,
        "title": row["action"] or "",
        "category": row.get("category") or "General",
        "scorecardId": row.get("scorecard_id"),
        "callId": row.get("interaction_id"),
        "dueAt": due.isoformat() if hasattr(due, "isoformat") else (due or ""),
        "status": _coach_status(row.get("status")),
        "notes": notes,
        "createdAt": created.isoformat()
        if hasattr(created, "isoformat")
        else (created or ""),
    }


def list_coaching_actions() -> list[dict[str, Any]]:
    d = _db()
    with d.engine.connect() as conn:
        rows = d._rows(
            conn.execute(
                text(
                    """
                    SELECT ca.*,
                           u.name AS agent_name,
                           b.name AS bot_name
                    FROM coaching_actions ca
                    LEFT JOIN users u ON u.id = ca.subject_user_id
                    LEFT JOIN bots b ON b.id = ca.subject_bot_id
                    WHERE ca.tenant_id = :tenant
                    ORDER BY ca.created_at DESC, ca.id
                    """
                ),
                {"tenant": d.TENANT_ID},
            )
        )
        notes = _coaching_notes_grouped(conn, [r["id"] for r in rows])
        return [_map_coaching(r, notes.get(r["id"], [])) for r in rows]


def create_coaching_action(payload: dict[str, Any]) -> dict[str, Any]:
    d = _db()
    with d.engine.begin() as conn:
        agent_name = (payload.get("agentId") or "").strip()
        if not agent_name:
            raise ValueError("agent_required")
        user_id, bot_id = _resolve_subject_by_name(conn, agent_name)
        scorecard_id = payload.get("scorecardId")
        interaction_id = payload.get("callId")
        if scorecard_id:
            # Tenant-scoped through the interaction, like every other QA read:
            # an unscoped lookup let a coaching action be attached to another
            # tenant's scorecard (and copy its interaction_id) by id alone.
            sc = d._one(
                conn.execute(
                    text(
                        """
                        SELECT sc.id, sc.interaction_id
                        FROM qa_scorecards sc
                        JOIN interactions i ON i.id = sc.interaction_id
                        WHERE sc.id = :id AND i.tenant_id = :tenant_id
                        """
                    ),
                    {"id": scorecard_id, "tenant_id": d.TENANT_ID},
                )
            )
            if sc is None:
                raise KeyError("scorecard_not_found")
            if not interaction_id:
                interaction_id = sc["interaction_id"]
        if interaction_id:
            d._ensure_interaction(conn, interaction_id)
        cid = d._id("COACH")
        title = (payload.get("title") or "").strip()
        if not title:
            raise ValueError("title_required")
        category = (payload.get("category") or "General").strip() or "General"
        due_at = payload.get("dueAt")
        conn.execute(
            text(
                """
                INSERT INTO coaching_actions (
                  id, tenant_id, subject_user_id, subject_bot_id, scorecard_id,
                  interaction_id, action, category, status, due_at
                ) VALUES (
                  :id, :tenant, :uid, :bid, :sid,
                  :iid, :action, :category, 'assigned', CAST(:due AS timestamptz)
                )
                """
            ),
            {
                "id": cid,
                "tenant": d.TENANT_ID,
                "uid": user_id,
                "bid": bot_id,
                "sid": scorecard_id,
                "iid": interaction_id,
                "action": title,
                "category": category,
                "due": due_at,
            },
        )
        d._activity(
            conn,
            "coaching_action",
            cid,
            "created",
            "Coaching action created",
            note=title,
        )
        row = d._one(
            conn.execute(
                text(
                    """
                    SELECT ca.*, u.name AS agent_name, b.name AS bot_name
                    FROM coaching_actions ca
                    LEFT JOIN users u ON u.id = ca.subject_user_id
                    LEFT JOIN bots b ON b.id = ca.subject_bot_id
                    WHERE ca.id = :id
                    """
                ),
                {"id": cid},
            )
        )
        assert row is not None
        return _map_coaching(row, [])


def patch_coaching_action(action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    d = _db()
    with d.engine.begin() as conn:
        existing = d._one(
            conn.execute(
                text(
                    "SELECT id, status FROM coaching_actions "
                    "WHERE id = :id AND tenant_id = :tenant"
                ),
                {"id": action_id, "tenant": d.TENANT_ID},
            )
        )
        if existing is None:
            raise KeyError("coaching_action_not_found")
        sets: list[str] = []
        params: dict[str, Any] = {"id": action_id, "tenant": d.TENANT_ID}
        if "status" in payload and payload["status"] is not None:
            st = _require_coach_status(str(payload["status"]))
            sets.append("status = :status")
            params["status"] = st
        if "title" in payload and payload["title"] is not None:
            sets.append("action = :action")
            params["action"] = str(payload["title"]).strip()
        if "category" in payload and payload["category"] is not None:
            sets.append("category = :category")
            params["category"] = str(payload["category"]).strip() or "General"
        if "dueAt" in payload:
            sets.append("due_at = CAST(:due AS timestamptz)")
            params["due"] = payload["dueAt"]
        if sets:
            sets.append("updated_at = now()")
            conn.execute(
                text(
                    f"UPDATE coaching_actions SET {', '.join(sets)} "
                    "WHERE id = :id AND tenant_id = :tenant"
                ),
                params,
            )
            d._activity(
                conn,
                "coaching_action",
                action_id,
                "updated",
                "Coaching action updated",
                note=params.get("status"),
            )
        row = d._one(
            conn.execute(
                text(
                    """
                    SELECT ca.*, u.name AS agent_name, b.name AS bot_name
                    FROM coaching_actions ca
                    LEFT JOIN users u ON u.id = ca.subject_user_id
                    LEFT JOIN bots b ON b.id = ca.subject_bot_id
                    WHERE ca.id = :id
                    """
                ),
                {"id": action_id},
            )
        )
        assert row is not None
        notes = _coaching_notes_grouped(conn, [action_id]).get(action_id, [])
        return _map_coaching(row, notes)


# ---------------------------------------------------------------------------
# QA Calibration
# ---------------------------------------------------------------------------


def _cal_status(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    if s in {"closed", "done", "completed"}:
        return "closed"
    return "active"


def _require_cal_status(raw: str | None) -> str:
    """Strict variant for the PATCH path.

    ``_cal_status`` coerces anything it does not recognise to "active", which is
    right when reading a legacy row but wrong on a write: PATCH status=cancelled
    silently re-opened the session instead of failing, and the caller was told
    the update had succeeded.
    """
    s = (raw or "").strip().lower()
    if s in {"closed", "done", "completed"}:
        return "closed"
    if s in {"active", "open", "in_review"}:
        return "active"
    raise ValueError(f"invalid_calibration_status: {raw}")


# calibration_sessions has no tenant column of its own — it reaches the tenant
# through the interaction it calibrates, so every read and write goes through
# this join. Without it the QA calibration screen is cross-tenant readable and
# patchable by id.
_CALIBRATION_SESSION_SELECT = """
    SELECT cs.*,
           c.name AS customer_name
    FROM calibration_sessions cs
    JOIN interactions i ON i.id = cs.interaction_id
    JOIN customers c ON c.id = i.customer_id
    WHERE i.tenant_id = :tenant_id
"""


def get_calibration_session(session_id: str) -> dict[str, Any] | None:
    """Single session with its criterion/reviewer data — no list-wide scan."""
    sessions = _calibration_sessions(
        _CALIBRATION_SESSION_SELECT + " AND cs.id = :session_id",
        {"session_id": session_id, "tenant_id": _db().TENANT_ID},
    )
    return sessions[0] if sessions else None


def list_calibration_sessions() -> list[dict[str, Any]]:
    return _calibration_sessions(
        _CALIBRATION_SESSION_SELECT + " ORDER BY cs.created_at DESC, cs.id",
        {"tenant_id": _db().TENANT_ID},
    )


def _calibration_sessions(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    d = _db()
    with d.engine.connect() as conn:
        sessions = d._rows(conn.execute(text(sql), params))
        if not sessions:
            return []
        ids = [s["id"] for s in sessions]
        criterion_cache: dict[str, list[str]] = {}
        reviewers = d._rows(
            conn.execute(
                text(
                    """
                    SELECT crs.*, u.name AS reviewer_name
                    FROM calibration_reviewer_scores crs
                    JOIN users u ON u.id = crs.reviewer_user_id
                    WHERE crs.session_id = ANY(:ids)
                    ORDER BY crs.created_at ASC, crs.id
                    """
                ),
                {"ids": ids},
            )
        )
        # Session → rubric, built once. The per-reviewer `next(...)` scan was
        # O(reviewers × sessions), and worse: when a session's rubric_id was
        # NULL it returned None rather than the "rubric-v1" default (the
        # generator *found* the session, the value was just null), so those
        # reviewers were scored against an empty criterion set while the
        # session block below coalesced correctly.
        rubric_by_session = {s["id"]: (s["rubric_id"] or "rubric-v1") for s in sessions}
        by_session: dict[str, list[dict[str, Any]]] = {i: [] for i in ids}
        for r in reviewers:
            rid = r["session_id"]
            rubric_id = rubric_by_session.get(rid, "rubric-v1")
            if rubric_id not in criterion_cache:
                criterion_cache[rubric_id] = _criterion_ids(conn, rubric_id)
            by_session.setdefault(rid, []).append(
                {
                    "reviewer": r["reviewer_name"],
                    "entries": _scores_to_entries(
                        r["scores"], criterion_cache[rubric_id]
                    ),
                }
            )
        out: list[dict[str, Any]] = []
        for s in sessions:
            rid = s["rubric_id"] or "rubric-v1"
            if rid not in criterion_cache:
                criterion_cache[rid] = _criterion_ids(conn, rid)
            created = s["created_at"]
            out.append(
                {
                    "id": s["id"],
                    "name": s.get("name") or f"Calibration · {s['interaction_id']}",
                    "callId": s["interaction_id"],
                    "customerName": s.get("customer_name") or "—",
                    "target": _scores_to_entries(
                        s.get("target_scores") or {}, criterion_cache[rid]
                    ),
                    "reviewers": by_session.get(s["id"], []),
                    "status": _cal_status(s.get("status")),
                    "createdAt": created.isoformat()
                    if hasattr(created, "isoformat")
                    else str(created),
                }
            )
        return out


def patch_calibration_session(
    session_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    d = _db()
    with d.engine.begin() as conn:
        existing = d._one(
            conn.execute(
                text(
                    """
                    SELECT cs.id
                    FROM calibration_sessions cs
                    JOIN interactions i ON i.id = cs.interaction_id
                    WHERE cs.id = :id AND i.tenant_id = :tenant_id
                    """
                ),
                {"id": session_id, "tenant_id": d.TENANT_ID},
            )
        )
        if existing is None:
            raise KeyError("calibration_session_not_found")
        if "status" in payload and payload["status"] is not None:
            st = _require_cal_status(str(payload["status"]))
            conn.execute(
                text(
                    """
                    UPDATE calibration_sessions
                    SET status = :st, updated_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": session_id, "st": st},
            )
            d._activity(
                conn,
                "calibration_session",
                session_id,
                "updated",
                "Calibration session updated",
                note=st,
            )
    # Re-read via the same mapper, single row.
    row = get_calibration_session(session_id)
    if row is None:
        raise KeyError("calibration_session_not_found")
    return row


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
                {"id": finding_id, "tenant": d.TENANT_ID},
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
                {"rid": redaction_id, "fid": finding_id, "tenant": d.TENANT_ID},
            )
        )
        if row is None:
            raise KeyError("audio_segment_not_found")
        conn.execute(
            text("UPDATE redaction_audio_segments SET muted = :m WHERE id = :id"),
            {"id": row["id"], "m": bool(muted)},
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
                {"id": redaction_id, "tenant": d.TENANT_ID},
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
                {"tenant": d.TENANT_ID, "t": pii_type},
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
        return {"parts": [], "actorRole": "", "downloadCount": 0, "entitiesRedacted": 0}
    parts = raw.get("parts") or raw.get("scope") or []
    if not isinstance(parts, list):
        parts = []
    return {
        "parts": [p for p in parts if p in _EXPORT_SCOPES],
        "actorRole": str(raw.get("actorRole") or ""),
        "downloadCount": int(raw.get("downloadCount") or 0),
        "entitiesRedacted": int(raw.get("entitiesRedacted") or 0),
    }


def _map_export_job(row: dict[str, Any], record_ids: list[str]) -> dict[str, Any]:
    meta = _parse_scope_blob(row.get("scope"))
    status = (row.get("status") or "queued").lower()
    if status == "completed":
        status = "ready"
    if status not in _EXPORT_STATUSES:
        status = "queued"
    at = row.get("created_at")
    return {
        "id": row["id"],
        "at": at.isoformat() if hasattr(at, "isoformat") else str(at),
        "actor": row.get("actor_name") or "Unknown",
        "actorRole": meta["actorRole"] or "Compliance Officer",
        "recordIds": record_ids,
        "format": row["format"] if row.get("format") in _EXPORT_FORMATS else "pdf",
        "scope": meta["parts"] or ["transcript"],
        "watermark": row.get("watermark") or "",
        "status": status,
        "downloadCount": meta["downloadCount"],
        "entitiesRedacted": meta["entitiesRedacted"],
    }


def list_export_jobs() -> list[dict[str, Any]]:
    d = _db()
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
                    """
                ),
                {"tenant": d.TENANT_ID},
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


def create_export_job(payload: dict[str, Any]) -> dict[str, Any]:
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
                {"ids": record_ids, "tenant": d.TENANT_ID},
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
        # Demo: mark ready immediately (no real zip/pdf pipeline yet)
        conn.execute(
            text(
                """
                INSERT INTO export_jobs (
                  id, actor_user_id, format, scope, watermark, status, storage_ref
                ) VALUES (
                  :id, :uid, :fmt, CAST(:scope AS jsonb), :wm, 'ready', :ref
                )
                """
            ),
            {
                "id": job_id,
                "uid": d._actor_user_id(),
                "fmt": fmt,
                "scope": json.dumps(meta),
                "wm": payload.get("watermark") or "",
                "ref": f"minio://export-bundles/{d.TENANT_ID}/{job_id}.{fmt}",
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
                {"id": job_id, "tenant": d.TENANT_ID},
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


# ---------------------------------------------------------------------------
# Routing writes + audit
# ---------------------------------------------------------------------------

_AUDIT_ACTIONS = frozenset(
    {"created", "edited", "reordered", "toggled", "deleted", "duplicated"}
)


def _routing_priority_next(conn: Any) -> int:
    d = _db()
    n = conn.execute(
        text(
            "SELECT coalesce(max(priority), 0) + 10 FROM routing_rules WHERE tenant_id = :t"
        ),
        {"t": d.TENANT_ID},
    ).scalar()
    return int(n or 10)


def create_routing_rule(payload: dict[str, Any]) -> dict[str, Any]:
    d = _db()
    with d.engine.begin() as conn:
        name = (payload.get("name") or "Untitled rule").strip()
        category = d._routing_category(payload.get("category"))
        then = payload.get("then") or {}
        action_key = d._routing_action_key(
            then.get("key") if isinstance(then, dict) else None
        )
        params = then.get("params") if isinstance(then, dict) else None
        when = payload.get("when") if isinstance(payload.get("when"), list) else []
        rule_id = payload.get("id") or d._id("RULE")
        # If client sent an id that already exists, mint a new one
        exists = d._one(
            conn.execute(
                text("SELECT id FROM routing_rules WHERE id = :id"), {"id": rule_id}
            )
        )
        if exists:
            rule_id = d._id("RULE")
        priority = payload.get("priority")
        if priority is None:
            priority = _routing_priority_next(conn)
        enabled = bool(payload.get("enabled", True))
        conn.execute(
            text(
                """
                INSERT INTO routing_rules (
                  id, tenant_id, priority, enabled, conditions,
                  action_key, action_params, name, description, category
                ) VALUES (
                  :id, :tenant, :priority, :enabled, CAST(:cond AS jsonb),
                  :akey, CAST(:aparams AS jsonb), :name, :desc, :cat
                )
                """
            ),
            {
                "id": rule_id,
                "tenant": d.TENANT_ID,
                "priority": int(priority),
                "enabled": enabled,
                "cond": json.dumps(when),
                "akey": action_key,
                "aparams": json.dumps(params if params else {}),
                "name": name,
                "desc": payload.get("description") or "",
                "cat": category,
            },
        )
        d._activity(
            conn,
            "routing_rule",
            rule_id,
            "created",
            "Routing rule created",
            note=name,
        )
        _append_routing_audit(conn, rule_id, name, "created", "Rule created")
        created_id = rule_id
    created = d.get_routing_rule(created_id)
    if created is None:
        raise KeyError("routing_rule_not_found")
    return created


def patch_routing_rule(rule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    d = _db()
    with d.engine.begin() as conn:
        existing = d._one(
            conn.execute(
                text(
                    """
                    SELECT id, name, enabled FROM routing_rules
                    WHERE id = :id AND tenant_id = :tenant
                    """
                ),
                {"id": rule_id, "tenant": d.TENANT_ID},
            )
        )
        if existing is None:
            raise KeyError("routing_rule_not_found")
        sets: list[str] = []
        params: dict[str, Any] = {"id": rule_id}
        audit_action = "edited"
        summary_bits: list[str] = []
        if "name" in payload and payload["name"] is not None:
            sets.append("name = :name")
            params["name"] = str(payload["name"]).strip() or existing["name"]
            summary_bits.append("name")
        if "description" in payload and payload["description"] is not None:
            sets.append("description = :description")
            params["description"] = str(payload["description"])
        if "category" in payload and payload["category"] is not None:
            sets.append("category = :category")
            params["category"] = d._routing_category(payload["category"])
        if "enabled" in payload and payload["enabled"] is not None:
            sets.append("enabled = :enabled")
            params["enabled"] = bool(payload["enabled"])
            audit_action = "toggled"
            summary_bits.append(f"enabled={params['enabled']}")
        if "priority" in payload and payload["priority"] is not None:
            sets.append("priority = :priority")
            params["priority"] = int(payload["priority"])
            audit_action = "reordered"
            summary_bits.append(f"priority={params['priority']}")
        if "when" in payload and payload["when"] is not None:
            if not isinstance(payload["when"], list):
                raise ValueError("when_must_be_list")
            sets.append("conditions = CAST(:cond AS jsonb)")
            params["cond"] = json.dumps(payload["when"])
            summary_bits.append(f"{len(payload['when'])} conditions")
        if "then" in payload and payload["then"] is not None:
            then = payload["then"]
            if not isinstance(then, dict):
                raise ValueError("then_must_be_object")
            sets.append("action_key = :akey")
            params["akey"] = d._routing_action_key(then.get("key"))
            aparams = then.get("params")
            sets.append("action_params = CAST(:aparams AS jsonb)")
            params["aparams"] = json.dumps(aparams if aparams else {})
            summary_bits.append(f"action {params['akey']}")
        if not sets:
            raise ValueError("no_fields")
        sets.append("updated_at = now()")
        conn.execute(
            text(f"UPDATE routing_rules SET {', '.join(sets)} WHERE id = :id"),
            params,
        )
        name = params.get("name") or existing["name"]
        _append_routing_audit(
            conn,
            rule_id,
            name,
            audit_action,
            " · ".join(summary_bits) or "Updated",
        )
        patched_id = rule_id
    patched = d.get_routing_rule(patched_id)
    if patched is None:
        raise KeyError("routing_rule_not_found")
    return patched


def reorder_routing_rules(ordered_ids: list[str]) -> list[dict[str, Any]]:
    d = _db()
    with d.engine.begin() as conn:
        # Count matched rows, not submitted ids: the UPDATE is tenant-scoped, so
        # an id from another tenant (or a deleted rule) updates nothing. The
        # audit trail must record what actually changed.
        updated = 0
        for i, rid in enumerate(ordered_ids):
            result = conn.execute(
                text(
                    """
                    UPDATE routing_rules
                    SET priority = :p, updated_at = now()
                    WHERE id = :id AND tenant_id = :tenant
                    """
                ),
                {"id": rid, "p": (i + 1) * 10, "tenant": d.TENANT_ID},
            )
            updated += int(result.rowcount or 0)
        if updated:
            _append_routing_audit(
                conn,
                ordered_ids[0],
                "library",
                "reordered",
                f"Reordered {updated} rules",
            )
    return d.list_routing_rules()


def delete_routing_rule(rule_id: str) -> None:
    d = _db()
    with d.engine.begin() as conn:
        existing = d._one(
            conn.execute(
                text(
                    """
                    SELECT id, name FROM routing_rules
                    WHERE id = :id AND tenant_id = :tenant
                    """
                ),
                {"id": rule_id, "tenant": d.TENANT_ID},
            )
        )
        if existing is None:
            raise KeyError("routing_rule_not_found")
        _append_routing_audit(
            conn, rule_id, existing["name"], "deleted", "Rule deleted"
        )
        conn.execute(
            text("DELETE FROM routing_rules WHERE id = :id AND tenant_id = :tenant"),
            {"id": rule_id, "tenant": d.TENANT_ID},
        )


def _append_routing_audit(
    conn: Any, rule_id: str, rule_name: str, action: str, summary: str
) -> None:
    d = _db()
    # activity_events note stores JSON for the audit feed
    payload = json.dumps(
        {
            "ruleId": rule_id,
            "ruleName": rule_name,
            "action": action if action in _AUDIT_ACTIONS else "edited",
            "summary": summary,
        }
    )
    d._activity(
        conn,
        "routing_rule",
        rule_id,
        f"rule_{action}",
        f"Rule {action}",
        note=payload,
    )


def list_routing_audit(limit: int = 100) -> list[dict[str, Any]]:
    d = _db()
    with d.engine.connect() as conn:
        rows = d._rows(
            conn.execute(
                text(
                    """
                    SELECT ae.id, ae.created_at, ae.note, ae.entity_id,
                           coalesce(u.name, 'System') AS author
                    FROM activity_events ae
                    LEFT JOIN users u ON u.id = ae.actor_user_id
                    WHERE ae.tenant_id = :tenant
                      AND ae.entity_type = 'routing_rule'
                      AND ae.kind LIKE 'rule_%'
                    ORDER BY ae.created_at DESC
                    LIMIT :lim
                    """
                ),
                {"tenant": d.TENANT_ID, "lim": limit},
            )
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            meta: dict[str, Any] = {}
            note = r.get("note") or ""
            try:
                meta = json.loads(note) if note.startswith("{") else {}
            except json.JSONDecodeError:
                meta = {}
            action = meta.get("action") or "edited"
            if action not in _AUDIT_ACTIONS:
                action = "edited"
            at = r["created_at"]
            out.append(
                {
                    "id": r["id"],
                    "at": at.isoformat() if hasattr(at, "isoformat") else str(at),
                    "author": r["author"],
                    "ruleId": meta.get("ruleId") or r["entity_id"],
                    "ruleName": meta.get("ruleName") or r["entity_id"],
                    "action": action,
                    "summary": meta.get("summary") or note,
                }
            )
        return out


# ---------------------------------------------------------------------------
# Workspace stats + right rail (rolling window anchored to max interaction)
# ---------------------------------------------------------------------------


def workspace_summary(*, assignee: str | None = "me") -> dict[str, Any]:
    """Honest rolling-window stats + next callback + SLA countdowns for My Workspace."""
    d = _db()
    if assignee in (None, "", "all"):
        assignee_id = None
    elif assignee == "me":
        assignee_id = d._actor_user_id()
    else:
        assignee_id = assignee

    with d.engine.connect() as conn:
        anchor = conn.execute(
            text("SELECT max(started_at) FROM interactions WHERE tenant_id = :t"),
            {"t": d.TENANT_ID},
        ).scalar()
        if anchor is None:
            anchor = datetime.now(timezone.utc)

        # Current 7d vs prior 7d, scoped to handler when assignee set
        params: dict[str, Any] = {"tenant": d.TENANT_ID, "anchor": anchor}
        handler_clause = ""
        if assignee_id:
            handler_clause = "AND i.handler_user_id = :uid"
            params["uid"] = assignee_id

        cur = d._one(
            conn.execute(
                text(
                    f"""
                    SELECT
                      count(*) AS calls,
                      coalesce(avg(duration_sec), 0) AS aht_sec,
                      count(*) FILTER (WHERE query_resolved IS TRUE) AS resolutions
                    FROM interactions i
                    WHERE i.tenant_id = :tenant
                      AND i.started_at > CAST(:anchor AS timestamptz) - interval '7 days'
                      AND i.started_at <= CAST(:anchor AS timestamptz)
                      {handler_clause}
                    """
                ),
                params,
            )
        )
        prev = d._one(
            conn.execute(
                text(
                    f"""
                    SELECT
                      count(*) AS calls,
                      coalesce(avg(duration_sec), 0) AS aht_sec,
                      count(*) FILTER (WHERE query_resolved IS TRUE) AS resolutions
                    FROM interactions i
                    WHERE i.tenant_id = :tenant
                      AND i.started_at > CAST(:anchor AS timestamptz) - interval '14 days'
                      AND i.started_at <= CAST(:anchor AS timestamptz) - interval '7 days'
                      {handler_clause}
                    """
                ),
                params,
            )
        )
        # Team AHT for delta (all handlers, same window)
        team = d._one(
            conn.execute(
                text(
                    """
                    SELECT coalesce(avg(duration_sec), 0) AS aht_sec
                    FROM interactions i
                    WHERE i.tenant_id = :tenant
                      AND i.started_at > CAST(:anchor AS timestamptz) - interval '7 days'
                      AND i.started_at <= CAST(:anchor AS timestamptz)
                    """
                ),
                {"tenant": d.TENANT_ID, "anchor": anchor},
            )
        )

        ptp_params: dict[str, Any] = {"tenant": d.TENANT_ID, "anchor": anchor}
        ptp_clause = ""
        if assignee_id:
            ptp_clause = "AND p.owner_user_id = :uid"
            ptp_params["uid"] = assignee_id
        ptp = d._one(
            conn.execute(
                text(
                    f"""
                    SELECT count(*) AS n, coalesce(sum(p.amount), 0) AS amt
                    FROM promises p
                    JOIN customers c ON c.id = p.customer_id
                    WHERE c.tenant_id = :tenant
                      AND p.created_at > CAST(:anchor AS timestamptz) - interval '7 days'
                      AND p.created_at <= CAST(:anchor AS timestamptz)
                      {ptp_clause}
                    """
                ),
                ptp_params,
            )
        )

        calls = int((cur or {}).get("calls") or 0)
        prev_calls = int((prev or {}).get("calls") or 0)
        aht_sec = float((cur or {}).get("aht_sec") or 0)
        team_aht = float((team or {}).get("aht_sec") or 0)
        resolutions = int((cur or {}).get("resolutions") or 0)
        rate = f"{round(100 * resolutions / calls)}%" if calls else "0%"
        delta_calls = calls - prev_calls
        aht_vs_team = int(round(aht_sec - team_aht))

        def fmt_aht(sec: float) -> str:
            s = max(0, int(round(sec)))
            return f"{s // 60}m {s % 60:02d}s"

        stats = {
            "callsHandled": calls,
            "callsHandledDelta": f"{delta_calls:+d} vs prior 7d",
            "aht": fmt_aht(aht_sec),
            "ahtDelta": f"{aht_vs_team:+d}s vs team",
            "resolutions": resolutions,
            "resolutionRate": rate,
            "promisesCount": int((ptp or {}).get("n") or 0),
            "promisesAmount": float((ptp or {}).get("amt") or 0),
            "windowLabel": "Rolling 7 days",
        }

        # Next callback
        cb_params: dict[str, Any] = {}
        cb_clause = ""
        if assignee_id:
            cb_clause = "AND cb.assignee_user_id = :uid"
            cb_params["uid"] = assignee_id
        cb = d._one(
            conn.execute(
                text(
                    f"""
                    SELECT cb.id, cb.reason, cb.scheduled_at,
                           c.name AS customer_name, a.id AS account_id
                    FROM callbacks cb
                    JOIN customers c ON c.id = cb.customer_id
                    LEFT JOIN LATERAL (
                      SELECT id FROM accounts
                      WHERE customer_id = cb.customer_id
                      ORDER BY CASE WHEN id LIKE 'AC-%' THEN 0 ELSE 1 END, created_at, id
                      LIMIT 1
                    ) a ON true
                    WHERE lower(coalesce(cb.status,'')) NOT IN ('completed','cancelled','done','closed')
                      AND cb.scheduled_at IS NOT NULL
                      AND cb.scheduled_at >= now() - interval '1 hour'
                      AND c.tenant_id = :tenant
                      {cb_clause}
                    ORDER BY cb.scheduled_at ASC
                    LIMIT 1
                    """
                ),
                {**cb_params, "tenant": d.TENANT_ID},
            )
        )
        next_cb = None
        if cb and cb.get("scheduled_at"):
            sched = cb["scheduled_at"]
            if isinstance(sched, str):
                try:
                    sched = datetime.fromisoformat(sched.replace("Z", "+00:00"))
                except ValueError:
                    sched = None
            if sched is not None:
                now = datetime.now(timezone.utc)
                if getattr(sched, "tzinfo", None) is None:
                    sched = sched.replace(tzinfo=timezone.utc)
                mins = int((sched - now).total_seconds() // 60)
                # Fixed offset, matching db._IST: India observes no DST, so this
                # needs no tzdata. The ZoneInfo lookup silently fell back to a
                # raw ISO timestamp on any image without the tz database.
                time_label = sched.astimezone(_IST).strftime("%I:%M %p").lstrip("0")
                next_cb = {
                    "id": cb["id"],
                    "customer": cb["customer_name"] or "Unknown",
                    "accountId": cb["account_id"] or "",
                    "reason": cb.get("reason") or "Scheduled callback",
                    "time": time_label,
                    "timezone": "IST",
                    "inMinutes": mins,
                }

        # SLA countdowns from work_items already assigned
        wi_params: dict[str, Any] = {}
        wi_clause = ""
        if assignee_id:
            wi_clause = "AND w.assignee_user_id = :uid"
            wi_params["uid"] = assignee_id
        wi_rows = d._rows(
            conn.execute(
                text(
                    f"""
                    SELECT w.entity_type, w.entity_id, w.sla_due_at, w.status,
                           c.name AS customer_name
                    FROM work_items w
                    JOIN customers c ON c.id = w.customer_id
                    WHERE w.sla_due_at IS NOT NULL
                      AND c.tenant_id = :tenant
                      {wi_clause}
                    ORDER BY w.sla_due_at ASC
                    LIMIT 8
                    """
                ),
                {**wi_params, "tenant": d.TENANT_ID},
            )
        )
        sla_countdowns: list[dict[str, Any]] = []
        for w in wi_rows:
            sla, label = d._work_item_sla(
                w["sla_due_at"], entity_type=w["entity_type"], status=w["status"]
            )
            kind = {
                "dispute": "Dispute",
                "promise": "Broken PTP",
                "document_request": "Doc",
                "callback": "Callback",
                "followup": "Follow-up",
            }.get(w["entity_type"], w["entity_type"])
            sla_countdowns.append(
                {
                    "id": w["entity_id"],
                    "label": f"{kind} · {w['customer_name']}",
                    "remaining": label,
                    "level": sla,
                }
            )

        # Outside preferred window nudge
        outside = 0
        open_cbs = d._rows(
            conn.execute(
                text(
                    f"""
                    SELECT cb.scheduled_at, c.preferred_window
                    FROM callbacks cb
                    JOIN customers c ON c.id = cb.customer_id
                    WHERE lower(coalesce(cb.status,'')) NOT IN ('completed','cancelled','done','closed')
                      AND cb.scheduled_at IS NOT NULL
                      AND c.tenant_id = :tenant
                      {cb_clause}
                    """
                ),
                {**cb_params, "tenant": d.TENANT_ID},
            )
        )
        for row in open_cbs:
            sched = row["scheduled_at"]
            sched_s = sched.isoformat() if hasattr(sched, "isoformat") else str(sched)
            try:
                if d._outside_preferred_window(sched_s, row.get("preferred_window")):
                    outside += 1
            except Exception:
                continue

        return {
            "stats": stats,
            "nextCallback": next_cb,
            "slaCountdowns": sla_countdowns,
            "outsideWindowCount": outside,
        }
