"""QA rubric and scorecard accessors (WP-036 peel: QA scorecards).

Peeled from ``db.py``. Call sites stay ``db.*`` via a bottom-of-file
re-export. Reach the engine through :func:`_db`, never ``from db_core import
engine``: the ``db_tx`` fixture wraps ``db.engine``, and a name bound from
``db_core`` bypasses that proxy.
"""

from __future__ import annotations

from sqlalchemy import text
from typing import Any
from agent_core.clock import utc_now
from db_core import (
    _activity,
    _actor_user_id,
    _ensure_interaction,
    _id,
    _one,
    _rows,
    clamp_list_limit,
    clamp_offset,
    current_tenant,
)


def _db():
    """The ``db`` module object, resolved at call time."""
    import db as d

    return d


_QA_DEFAULT_RUBRIC_ID = "rubric-v1"

_QA_CLERK_RUBRIC_ID = "rubric-clerk-sms"

_QA_STATUSES = frozenset({"unscored", "ai_draft", "final"})


def _qa_status_screen(status: str | None) -> str:
    raw = (status or "").strip().lower()
    if raw in {"final", "completed", "reviewed"}:
        return "final"
    if raw in {"ai_draft", "draft", "in_review"}:
        return "ai_draft"
    return "unscored"


def _qa_band_for(total: float) -> str:
    if total >= 85:
        return "green"
    if total >= 70:
        return "amber"
    return "red"


def _qa_score_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _load_rubric_tree(
    conn: Any, rubric_id: str = _QA_DEFAULT_RUBRIC_ID
) -> dict[str, Any] | None:
    rubric = _one(
        conn.execute(
            text(
                "SELECT id, name, version FROM qa_rubrics WHERE id = :id AND enabled = true"
            ),
            {"id": rubric_id},
        )
    )
    if rubric is None:
        rubric = _one(
            conn.execute(
                text(
                    """
                    SELECT id, name, version
                    FROM qa_rubrics
                    WHERE enabled = true
                    ORDER BY updated_at DESC, id
                    LIMIT 1
                    """
                )
            )
        )
    if rubric is None:
        return None
    sections = _rows(
        conn.execute(
            text(
                """
                SELECT id, name AS label, weight
                FROM qa_rubric_sections
                WHERE rubric_id = :rubric_id
                ORDER BY weight DESC, id
                """
            ),
            {"rubric_id": rubric["id"]},
        )
    )
    section_ids = [s["id"] for s in sections]
    criteria_by_section: dict[str, list[dict[str, Any]]] = {
        sid: [] for sid in section_ids
    }
    if section_ids:
        criteria = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, section_id, label, coalesce(description, '') AS description,
                           weight, critical_fail
                    FROM qa_rubric_criteria
                    WHERE section_id = ANY(:ids)
                    ORDER BY weight DESC, id
                    """
                ),
                {"ids": section_ids},
            )
        )
        for c in criteria:
            criteria_by_section.setdefault(c["section_id"], []).append(
                {
                    "id": c["id"],
                    "label": c["label"],
                    "description": c["description"] or "",
                    "weight": _qa_score_float(c["weight"]),
                    "critical": bool(c["critical_fail"]) or None,
                }
            )
    return {
        "id": rubric["id"],
        "name": rubric["name"],
        "version": rubric["version"],
        "sections": [
            {
                "id": s["id"],
                "label": s["label"],
                "weight": _qa_score_float(s["weight"]),
                "criteria": [
                    {
                        k: v
                        for k, v in crit.items()
                        if not (k == "critical" and v is None)
                    }
                    for crit in criteria_by_section.get(s["id"], [])
                ],
            }
            for s in sections
        ],
    }


def get_rubric(rubric_id: str | None = None) -> dict[str, Any]:
    engine = _db().engine
    with engine.connect() as conn:
        tree = _load_rubric_tree(conn, rubric_id or _QA_DEFAULT_RUBRIC_ID)
        if tree is None:
            raise KeyError("rubric_not_found")
        return tree


def load_rubric_tree(rubric_id: str | None = None) -> dict[str, Any] | None:
    """Rubric tree, or None when there is no enabled rubric.

    ``get_rubric`` raises for the HTTP layer, which wants a 404. The QA
    auto-scorer is a background sweep and a missing rubric is a reason to skip
    the tick, not to raise into a worker loop.
    """
    engine = _db().engine
    with engine.connect() as conn:
        return _load_rubric_tree(conn, rubric_id or _QA_DEFAULT_RUBRIC_ID)


def rubric_id_for_interaction(interaction_id: str) -> str | None:
    """Voice collections rubric, or the clerk SMS rubric. Never mix them.

    A clerk WhatsApp/SMS must not be scored against recording-disclosure or
    barge criteria. If the clerk rubric is missing, return None so autoscore
    skips rather than using the voice tree.
    """
    engine = _db().engine
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text("SELECT channel, handler_kind FROM interactions WHERE id = :id"),
                {"id": interaction_id},
            )
        )
        if row is None:
            return _QA_DEFAULT_RUBRIC_ID
        channel = str(row.get("channel") or "")
        if (
            channel in {"sms", "whatsapp"}
            or str(row.get("handler_kind") or "") == "system"
        ):
            exists = conn.execute(
                text("SELECT 1 FROM qa_rubrics WHERE id = :id AND enabled = true"),
                {"id": _QA_CLERK_RUBRIC_ID},
            ).first()
            return _QA_CLERK_RUBRIC_ID if exists else None
        return _QA_DEFAULT_RUBRIC_ID


def _qa_all_criteria(rubric: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for s in rubric["sections"] for c in s["criteria"]]


def _qa_section_total(
    section: dict[str, Any], entries_by_id: dict[str, dict[str, Any]]
) -> float:
    weight_sum = sum(_qa_score_float(c["weight"]) for c in section["criteria"]) or 1.0
    acc = 0.0
    for c in section["criteria"]:
        entry = entries_by_id.get(c["id"]) or {}
        score = _qa_score_float(entry.get("score"))
        acc += (score / 5.0) * (_qa_score_float(c["weight"]) / weight_sum)
    return acc * 100.0


def _qa_compute_total(rubric: dict[str, Any], entries: list[dict[str, Any]]) -> float:
    by_id = {e["criterionId"]: e for e in entries}
    has_critical_zero = any(
        c.get("critical")
        and _qa_score_float((by_id.get(c["id"]) or {}).get("score")) == 0
        for s in rubric["sections"]
        for c in s["criteria"]
    )
    weight_sum = sum(_qa_score_float(s["weight"]) for s in rubric["sections"]) or 1.0
    total = sum(
        (_qa_section_total(s, by_id) * _qa_score_float(s["weight"])) / weight_sum
        for s in rubric["sections"]
    )
    return min(total, 40.0) if has_critical_zero else total


def _qa_entries_grouped(
    conn: Any, scorecard_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    if not scorecard_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT scorecard_id, criterion_id, ai_suggested_score, final_score, note, accepted
                FROM qa_scorecard_entries
                WHERE scorecard_id = ANY(:ids)
                ORDER BY criterion_id
                """
            ),
            {"ids": scorecard_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["scorecard_id"], []).append(
            {
                "criterionId": r["criterion_id"],
                "aiSuggested": _qa_score_float(r["ai_suggested_score"]),
                "score": _qa_score_float(r["final_score"]),
                "note": r["note"] or None,
                "accepted": r["accepted"],
            }
        )
    return grouped


def _qa_pad_entries(
    rubric: dict[str, Any], entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {e["criterionId"]: e for e in entries}
    padded: list[dict[str, Any]] = []
    for c in _qa_all_criteria(rubric):
        existing = by_id.get(c["id"])
        if existing:
            padded.append(
                {
                    "criterionId": existing["criterionId"],
                    "aiSuggested": _qa_score_float(existing.get("aiSuggested")),
                    "score": _qa_score_float(existing.get("score")),
                    "note": existing.get("note") or None,
                    "accepted": existing.get("accepted"),
                }
            )
        else:
            padded.append(
                {
                    "criterionId": c["id"],
                    "aiSuggested": 0.0,
                    "score": 0.0,
                    "note": None,
                    "accepted": None,
                }
            )
    return padded


def _qa_handled_by(
    handler_kind: str | None, handler_name: str | None, has_handoff: bool
) -> dict[str, str]:
    label = handler_name or ("Bot" if handler_kind == "bot" else "Agent")
    if has_handoff:
        return {"kind": "handoff", "label": label}
    kind = "bot" if handler_kind == "bot" else "human"
    return {"kind": kind, "label": label}


def _qa_ensure_user(conn: Any, user_id: str | None) -> None:
    if user_id is None:
        return
    if not conn.execute(
        text("SELECT 1 FROM users WHERE id = :id"), {"id": user_id}
    ).fetchone():
        raise KeyError("user_not_found")


def _qa_ensure_bot(conn: Any, bot_id: str | None) -> None:
    if bot_id is None:
        return
    if not conn.execute(
        text("SELECT 1 FROM bots WHERE id = :id"), {"id": bot_id}
    ).fetchone():
        raise KeyError("bot_not_found")


def _qa_ensure_criterion(conn: Any, criterion_id: str) -> None:
    if not conn.execute(
        text("SELECT 1 FROM qa_rubric_criteria WHERE id = :id"), {"id": criterion_id}
    ).fetchone():
        raise KeyError(f"criterion_not_found:{criterion_id}")


def _qa_upsert_entries(
    conn: Any, scorecard_id: str, entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Upsert per-criterion rows; returns the screen-shaped entries written."""
    written: list[dict[str, Any]] = []
    for raw in entries:
        criterion_id = raw.get("criterionId")
        if not criterion_id:
            raise ValueError("entries require criterionId")
        _qa_ensure_criterion(conn, criterion_id)
        existing = _one(
            conn.execute(
                text(
                    """
                    SELECT id, ai_suggested_score, final_score, note, accepted
                    FROM qa_scorecard_entries
                    WHERE scorecard_id = :scorecard_id AND criterion_id = :criterion_id
                    """
                ),
                {"scorecard_id": scorecard_id, "criterion_id": criterion_id},
            )
        )
        ai = (
            raw["aiSuggested"]
            if "aiSuggested" in raw and raw["aiSuggested"] is not None
            else (_qa_score_float(existing["ai_suggested_score"]) if existing else 0.0)
        )
        score = (
            raw["score"]
            if "score" in raw and raw["score"] is not None
            else (_qa_score_float(existing["final_score"]) if existing else 0.0)
        )
        note = (
            raw["note"] if "note" in raw else (existing["note"] if existing else None)
        )
        accepted = (
            raw["accepted"]
            if "accepted" in raw
            else (existing["accepted"] if existing else None)
        )
        entry_id = existing["id"] if existing else f"{scorecard_id}-{criterion_id}"
        conn.execute(
            text(
                """
                INSERT INTO qa_scorecard_entries
                  (id, scorecard_id, criterion_id, ai_suggested_score, final_score, note, accepted)
                VALUES
                  (:id, :scorecard_id, :criterion_id, :ai, :score, :note, :accepted)
                ON CONFLICT (id) DO UPDATE
                  SET ai_suggested_score = EXCLUDED.ai_suggested_score,
                      final_score = EXCLUDED.final_score,
                      note = EXCLUDED.note,
                      accepted = EXCLUDED.accepted,
                      updated_at = now()
                """
            ),
            {
                "id": entry_id,
                "scorecard_id": scorecard_id,
                "criterion_id": criterion_id,
                "ai": ai,
                "score": score,
                "note": note,
                "accepted": accepted,
            },
        )
        written.append(
            {
                "criterionId": criterion_id,
                "aiSuggested": _qa_score_float(ai),
                "score": _qa_score_float(score),
                "note": note,
                "accepted": accepted,
            }
        )
    return written


_SCORECARD_LIST_SQL = """
    SELECT qs.id, qs.interaction_id, qs.rubric_id, qs.status, qs.total_score, qs.band,
           qs.scored_at, qs.created_at,
           qs.subject_user_id, qs.subject_bot_id, qs.reviewer_user_id,
           c.name AS customer_name,
           coalesce(i.disposition, '') AS disposition,
           i.handler_kind,
           coalesce(hu.name, hb.name) AS handler_name,
           su.name AS subject_user_name,
           sb.name AS subject_bot_name,
           ru.name AS reviewer_name,
           EXISTS (
             SELECT 1 FROM interaction_handoffs h WHERE h.interaction_id = qs.interaction_id
           ) AS has_handoff
    FROM qa_scorecards qs
    JOIN interactions i ON i.id = qs.interaction_id
    JOIN customers c ON c.id = i.customer_id
    LEFT JOIN users hu ON hu.id = i.handler_user_id
    LEFT JOIN bots hb ON hb.id = i.handler_bot_id
    LEFT JOIN users su ON su.id = qs.subject_user_id
    LEFT JOIN bots sb ON sb.id = qs.subject_bot_id
    LEFT JOIN users ru ON ru.id = qs.reviewer_user_id
"""


def _scorecard_rows_to_screen(
    conn: Any,
    rows: list[dict[str, Any]],
    rubric: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    trees: dict[str, dict[str, Any] | None] = {}

    def tree_for(rubric_id: str | None) -> dict[str, Any] | None:
        key = rubric_id or _QA_DEFAULT_RUBRIC_ID
        if key not in trees:
            trees[key] = _load_rubric_tree(conn, key)
        return trees[key]

    if rubric is not None:
        trees[rubric.get("id") or _QA_DEFAULT_RUBRIC_ID] = rubric
    fallback = tree_for(_QA_DEFAULT_RUBRIC_ID)
    entries_by = _qa_entries_grouped(conn, [r["id"] for r in rows])
    result: list[dict[str, Any]] = []
    for r in rows:
        rid = r.get("rubric_id") or _QA_DEFAULT_RUBRIC_ID
        tree = tree_for(rid) or fallback
        if tree is None:
            raise KeyError("rubric_not_found")
        agent_id = (
            r["subject_user_name"]
            or r["subject_bot_name"]
            or r["handler_name"]
            or "Unknown"
        )
        entries = _qa_pad_entries(tree, entries_by.get(r["id"]) or [])
        result.append(
            {
                "id": r["id"],
                "callId": r["interaction_id"],
                "customerName": r["customer_name"],
                "disposition": r["disposition"] or "",
                "handledBy": _qa_handled_by(
                    r["handler_kind"], r["handler_name"], bool(r["has_handoff"])
                ),
                "agentId": agent_id,
                "reviewer": r["reviewer_name"] or None,
                "status": _qa_status_screen(r["status"]),
                "entries": entries,
                "scoredAt": r["scored_at"],
                "createdAt": r["created_at"],
                "rubricId": rid,
            }
        )
    return result


def list_scorecards(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    """QA Scoring Queue — screen Scorecard shape. Paged: one row per scored call."""
    engine = _db().engine
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    _SCORECARD_LIST_SQL
                    + """
                    ORDER BY
                      CASE qs.status
                        WHEN 'unscored' THEN 0
                        WHEN 'ai_draft' THEN 1
                        WHEN 'draft' THEN 1
                        WHEN 'final' THEN 2
                        ELSE 3
                      END,
                      i.started_at DESC NULLS LAST,
                      qs.created_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": page, "offset": skip},
            )
        )
        return _scorecard_rows_to_screen(conn, rows)


def qa_coverage_stats(*, days: int = 7) -> dict[str, Any]:
    """Share of completed interactions that have a scorecard in the window."""
    engine = _db().engine
    window = max(1, min(int(days), 90))
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    """
                SELECT
                  count(*) FILTER (
                    WHERE i.status IN ('completed', 'abandoned')
                      AND i.ended_at >= now() - CAST(:window AS interval)
                  )::int AS completed,
                  count(*) FILTER (
                    WHERE i.status IN ('completed', 'abandoned')
                      AND i.ended_at >= now() - CAST(:window AS interval)
                      AND qs.id IS NOT NULL
                  )::int AS scored,
                  count(*) FILTER (
                    WHERE qs.status = 'ai_draft'
                      AND qs.created_at >= now() - CAST(:window AS interval)
                  )::int AS pending_review,
                  count(*) FILTER (
                    WHERE qs.band = 'red'
                      AND qs.created_at >= now() - CAST(:window AS interval)
                  )::int AS critical
                FROM interactions i
                LEFT JOIN qa_scorecards qs ON qs.interaction_id = i.id
                WHERE i.tenant_id = :tenant
                """
                ),
                {"tenant": current_tenant(), "window": f"{window} days"},
            )
            .mappings()
            .one()
        )
    completed = int(row["completed"] or 0)
    scored = int(row["scored"] or 0)
    coverage = (scored / completed) if completed else None
    return {
        "windowDays": window,
        "completed": completed,
        "scored": scored,
        "coverage": round(coverage, 4) if coverage is not None else None,
        "pendingReview": int(row["pending_review"] or 0),
        "criticalFails": int(row["critical"] or 0),
    }


def _scorecard_by_id(conn: Any, scorecard_id: str) -> dict[str, Any]:
    row = _one(
        conn.execute(
            text(_SCORECARD_LIST_SQL + " WHERE qs.id = :id"),
            {"id": scorecard_id},
        )
    )
    if row is None:
        raise KeyError("scorecard_not_found")
    return _scorecard_rows_to_screen(conn, [row])[0]


def create_scorecard(payload: dict[str, Any]) -> dict[str, Any]:
    engine = _db().engine
    with engine.begin() as conn:
        interaction = _ensure_interaction(conn, payload["interactionId"])
        rubric_id = payload.get("rubricId") or _QA_DEFAULT_RUBRIC_ID
        rubric = _load_rubric_tree(conn, rubric_id)
        if rubric is None:
            raise KeyError("rubric_not_found")
        subject_user_id = payload.get("subjectUserId")
        subject_bot_id = payload.get("subjectBotId")
        if subject_user_id and subject_bot_id:
            raise ValueError("set subjectUserId or subjectBotId, not both")
        _qa_ensure_user(conn, subject_user_id)
        _qa_ensure_bot(conn, subject_bot_id)
        reviewer_user_id = payload.get("reviewerUserId")
        _qa_ensure_user(conn, reviewer_user_id)
        status = _qa_status_screen(payload.get("status") or "unscored")
        if status not in _QA_STATUSES:
            raise ValueError(f"invalid status: {status}")
        scorecard_id = f"qa-{interaction['id']}"
        if conn.execute(
            text("SELECT 1 FROM qa_scorecards WHERE id = :id"), {"id": scorecard_id}
        ).fetchone():
            scorecard_id = _id("QA")
        entries_payload = payload.get("entries") or []
        total = payload.get("totalScore")
        band = payload.get("band")
        conn.execute(
            text(
                """
                INSERT INTO qa_scorecards
                  (id, interaction_id, rubric_id, subject_user_id, subject_bot_id, reviewer_user_id,
                   status, total_score, band, scored_at)
                VALUES
                  (:id, :interaction_id, :rubric_id, :subject_user_id, :subject_bot_id, :reviewer_user_id,
                   :status, :total_score, :band, :scored_at)
                """
            ),
            {
                "id": scorecard_id,
                "interaction_id": payload["interactionId"],
                "rubric_id": rubric["id"],
                "subject_user_id": subject_user_id,
                "subject_bot_id": subject_bot_id,
                "reviewer_user_id": reviewer_user_id
                or (_actor_user_id() if status == "final" else None),
                "status": status,
                "total_score": total,
                "band": band,
                "scored_at": utc_now() if status == "final" else None,
            },
        )
        if entries_payload:
            written = _qa_upsert_entries(conn, scorecard_id, entries_payload)
            total = _qa_compute_total(rubric, written)
            band = _qa_band_for(total)
            conn.execute(
                text(
                    """
                    UPDATE qa_scorecards
                    SET total_score = :total, band = :band
                    WHERE id = :id
                    """
                ),
                {"id": scorecard_id, "total": total, "band": band},
            )
        _activity(
            conn,
            "qa_scorecard",
            scorecard_id,
            "scorecard_created",
            "QA scorecard created",
            customer_id=interaction["customer_id"],
        )
        return _scorecard_by_id(conn, scorecard_id)


def patch_scorecard(scorecard_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is intentional.

    entries[] upserts qa_scorecard_entries and recomputes total_score/band.
    status=final sets scored_at + reviewer and writes a finalize activity row.
    """
    engine = _db().engine
    with engine.begin() as conn:
        existing = _one(
            conn.execute(
                text(
                    """
                    SELECT qs.id, qs.rubric_id, qs.status, qs.reviewer_user_id, i.customer_id
                    FROM qa_scorecards qs
                    JOIN interactions i ON i.id = qs.interaction_id
                    WHERE qs.id = :id
                    """
                ),
                {"id": scorecard_id},
            )
        )
        if existing is None:
            raise KeyError("scorecard_not_found")
        rubric = _load_rubric_tree(conn, existing["rubric_id"] or _QA_DEFAULT_RUBRIC_ID)
        if rubric is None:
            raise KeyError("rubric_not_found")

        if "subjectUserId" in payload and "subjectBotId" in payload:
            if payload["subjectUserId"] and payload["subjectBotId"]:
                raise ValueError("set subjectUserId or subjectBotId, not both")
        if "subjectUserId" in payload:
            _qa_ensure_user(conn, payload["subjectUserId"])
        if "subjectBotId" in payload:
            _qa_ensure_bot(conn, payload["subjectBotId"])
        if "reviewerUserId" in payload:
            _qa_ensure_user(conn, payload["reviewerUserId"])

        status = _qa_status_screen(existing["status"])
        if "status" in payload and payload["status"] is not None:
            status = _qa_status_screen(payload["status"])
            if status not in _QA_STATUSES:
                raise ValueError(f"invalid status: {status}")
        elif (
            "entries" in payload
            and payload["entries"] is not None
            and status == "unscored"
        ):
            # Saving criterion edits from unscored promotes to AI draft.
            status = "ai_draft"

        entries_written: list[dict[str, Any]] | None = None
        if "entries" in payload and payload["entries"] is not None:
            entries_written = _qa_upsert_entries(conn, scorecard_id, payload["entries"])

        updates: list[str] = []
        params: dict[str, Any] = {"id": scorecard_id}

        if status != _qa_status_screen(existing["status"]) or (
            "status" in payload and payload["status"] is not None
        ):
            updates.append("status = :status")
            params["status"] = status

        if "subjectUserId" in payload:
            updates.append("subject_user_id = :subject_user_id")
            params["subject_user_id"] = payload["subjectUserId"]
            if payload["subjectUserId"]:
                updates.append("subject_bot_id = NULL")
        if "subjectBotId" in payload:
            updates.append("subject_bot_id = :subject_bot_id")
            params["subject_bot_id"] = payload["subjectBotId"]
            if payload["subjectBotId"]:
                updates.append("subject_user_id = NULL")

        reviewer_user_id = existing["reviewer_user_id"]
        if "reviewerUserId" in payload:
            reviewer_user_id = payload["reviewerUserId"]
            updates.append("reviewer_user_id = :reviewer_user_id")
            params["reviewer_user_id"] = reviewer_user_id

        if entries_written is not None:
            # Merge with any criteria not in this patch so totals stay complete.
            grouped = _qa_entries_grouped(conn, [scorecard_id]).get(scorecard_id) or []
            padded = _qa_pad_entries(rubric, grouped)
            total = _qa_compute_total(rubric, padded)
            band = _qa_band_for(total) if status != "unscored" else None
            updates.extend(["total_score = :total_score", "band = :band"])
            params["total_score"] = total if status != "unscored" else None
            params["band"] = band
        else:
            if "totalScore" in payload:
                updates.append("total_score = :total_score")
                params["total_score"] = payload["totalScore"]
            if "band" in payload:
                updates.append("band = :band")
                params["band"] = payload["band"]

        if status == "final":
            if "reviewerUserId" not in payload:
                reviewer_user_id = reviewer_user_id or _actor_user_id()
                updates.append("reviewer_user_id = :reviewer_user_id")
                params["reviewer_user_id"] = reviewer_user_id
            updates.append("scored_at = coalesce(scored_at, now())")
        elif "status" in payload and status != "final":
            updates.append("scored_at = NULL")

        if updates:
            conn.execute(
                text(f"UPDATE qa_scorecards SET {', '.join(updates)} WHERE id = :id"),
                params,
            )

        if status == "final" and _qa_status_screen(existing["status"]) != "final":
            _activity(
                conn,
                "qa_scorecard",
                scorecard_id,
                "scorecard_finalized",
                "QA scorecard published",
                customer_id=existing["customer_id"],
            )
        else:
            _activity(
                conn,
                "qa_scorecard",
                scorecard_id,
                "scorecard_updated",
                "QA scorecard updated",
                status,
                customer_id=existing["customer_id"],
            )
        return _scorecard_by_id(conn, scorecard_id)
