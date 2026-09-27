"""Coaching actions and calibration sessions.

Was the first half of ``followups_db.py``; the redaction, routing and
workspace halves went to their owners (db_redaction, db_routing,
db_workspace). Imported at the bottom of db.py so call sites stay ``db.*``.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from db_core import current_tenant


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
        "dueAt": due.isoformat() if isinstance(due, (datetime, date)) else (due or ""),
        "status": _coach_status(row.get("status")),
        "notes": notes,
        "createdAt": created.isoformat()
        if isinstance(created, (datetime, date))
        else (created or ""),
    }


def list_coaching_actions(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    d = _db()
    page, skip = d.clamp_list_limit(limit), d.clamp_offset(offset)
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
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"tenant": d.current_tenant(), "limit": page, "offset": skip},
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
                    {"id": scorecard_id, "tenant_id": d.current_tenant()},
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
                "tenant": d.current_tenant(),
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
                {"id": action_id, "tenant": d.current_tenant()},
            )
        )
        if existing is None:
            raise KeyError("coaching_action_not_found")
        sets: list[str] = []
        params: dict[str, Any] = {"id": action_id, "tenant": d.current_tenant()}
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
        {"session_id": session_id, "tenant_id": current_tenant()},
    )
    return sessions[0] if sessions else None


def list_calibration_sessions(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    d = _db()
    return _calibration_sessions(
        _CALIBRATION_SESSION_SELECT
        + " ORDER BY cs.created_at DESC, cs.id LIMIT :limit OFFSET :offset",
        {
            "tenant_id": d.current_tenant(),
            "limit": d.clamp_list_limit(limit),
            "offset": d.clamp_offset(offset),
        },
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
                    # A reviewer invited to a session has no scores yet; their
                    # padded zeros are not a score to measure variance on.
                    "submitted": bool(r["scores"]),
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
                    "rubricId": rid,
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
                {"id": session_id, "tenant_id": d.current_tenant()},
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


def create_calibration_session(
    interaction_id: str, reviewer_user_ids: list[str]
) -> dict[str, Any]:
    """A calibration session over one scored call, with the reviewers invited.

    The target is the call's scorecard as it stands (published or AI draft)
    and the session uses that scorecard's rubric version, so reviewers are
    compared on the same criteria. An unscored call has no target to
    calibrate against and is refused.
    """
    d = _db()
    reviewers = list(dict.fromkeys(r for r in reviewer_user_ids if r))
    if not reviewers:
        raise ValueError("calibration_reviewers_required")
    session_id = d._id("CAL")
    with d.engine.begin() as conn:
        d._ensure_interaction(conn, interaction_id)
        card = d._one(
            conn.execute(
                text(
                    "SELECT id, rubric_id FROM qa_scorecards "
                    "WHERE interaction_id = :ix AND status <> 'unscored'"
                ),
                {"ix": interaction_id},
            )
        )
        if card is None:
            raise ValueError("calibration_needs_scored_call")
        target = {
            r["criterion_id"]: float(r["final_score"])
            for r in d._rows(
                conn.execute(
                    text(
                        "SELECT criterion_id, final_score FROM qa_scorecard_entries "
                        "WHERE scorecard_id = :id AND final_score IS NOT NULL"
                    ),
                    {"id": card["id"]},
                )
            )
        }
        for uid in reviewers:
            d._qa_ensure_user(conn, uid)
        conn.execute(
            text(
                """
                INSERT INTO calibration_sessions (id, interaction_id, rubric_id, target_scores)
                VALUES (:id, :ix, :rid, CAST(:target AS jsonb))
                """
            ),
            {"id": session_id, "ix": interaction_id, "rid": card["rubric_id"],
             "target": json.dumps(target)},
        )
        for uid in reviewers:
            conn.execute(
                text(
                    "INSERT INTO calibration_reviewer_scores (id, session_id, reviewer_user_id) "
                    "VALUES (:id, :sid, :uid)"
                ),
                {"id": f"{session_id}-{uid}", "sid": session_id, "uid": uid},
            )
        d._activity(
            conn,
            "calibration_session",
            session_id,
            "created",
            "Calibration session created",
            note=f"{len(reviewers)} reviewers",
        )
    row = get_calibration_session(session_id)
    if row is None:
        raise KeyError("calibration_session_not_found")
    return row


def submit_calibration_scores(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """An invited reviewer's scores for a calibration session.

    Only a reviewer the session invited, only while it is active; every
    criterion of the session's rubric version must be scored 0-5. The variance
    from the target (the call's scorecard when the session opened) is the mean
    absolute difference per criterion -- what the calibration measures.
    """
    d = _db()
    actor = d._actor_user_id()
    with d.engine.begin() as conn:
        session = d._one(conn.execute(
            text(
                """
                SELECT cs.id, cs.status, cs.rubric_id, cs.target_scores
                FROM calibration_sessions cs
                JOIN interactions i ON i.id = cs.interaction_id
                WHERE cs.id = :id AND i.tenant_id = :tenant_id
                FOR UPDATE OF cs
                """
            ),
            {"id": session_id, "tenant_id": d.current_tenant()},
        ))
        if session is None:
            raise KeyError("calibration_session_not_found")
        if _cal_status(session["status"]) != "active":
            raise ValueError("calibration_session_closed")
        seat = conn.execute(
            text("SELECT id FROM calibration_reviewer_scores WHERE session_id = :s AND reviewer_user_id = :u"),
            {"s": session_id, "u": actor},
        ).scalar()
        if seat is None:
            raise PermissionError("not_invited_to_this_calibration")
        criteria = _criterion_ids(conn, session["rubric_id"] or "rubric-v1")
        scores: dict[str, float] = {}
        for e in payload.get("entries") or []:
            cid, score = str(e.get("criterionId") or ""), e.get("score")
            if cid not in criteria:
                raise ValueError(f"unknown_criterion:{cid}")
            if not isinstance(score, (int, float)) or not 0 <= float(score) <= 5:
                raise ValueError(f"score_out_of_range:{cid}")
            scores[cid] = float(score)
        missing = [c for c in criteria if c not in scores]
        if missing:
            raise ValueError(f"unscored_criteria:{','.join(missing)}")
        target = {e["criterionId"]: e["score"] for e in _scores_to_entries(session["target_scores"] or {}, criteria)}
        variance = round(sum(abs(scores[c] - target.get(c, 0.0)) for c in criteria) / len(criteria), 2)
        conn.execute(
            text("UPDATE calibration_reviewer_scores SET scores = CAST(:sc AS jsonb), notes = :n, "
                 "variance_from_target = :v, updated_at = now() WHERE id = :id"),
            {"sc": json.dumps(scores), "n": payload.get("notes"), "v": variance, "id": seat},
        )
        d._activity(conn, "calibration_session", session_id, "scored", "Calibration scores submitted",
                    note=f"variance {variance}")
    row = get_calibration_session(session_id)
    if row is None:
        raise KeyError("calibration_session_not_found")
    return row
