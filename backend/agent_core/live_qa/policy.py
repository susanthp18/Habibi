"""The living live-QA policy — latest decision, one shape every screen reads."""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

from sqlalchemy import text

from agent_core.live_qa.checks import ACTION_NONE, VERDICT_PASS

logger = logging.getLogger(__name__)


def empty() -> dict[str, Any]:
    return {
        "status": "none",
        "decisionId": None,
        "interactionId": None,
        "mode": None,
        "verdict": None,
        "recommendedAction": ACTION_NONE,
        "reason": None,
        "reasonCodes": [],
        "enacted": False,
        "audioCapable": False,
        "createdAt": None,
    }


def snapshot(
    conn: Any,
    *,
    tenant_id: str,
    interaction_id: str | None,
) -> dict[str, Any]:
    if not interaction_id:
        return empty()
    try:
        row = conn.execute(
            text(
                _SELECT
                + """
                WHERE d.interaction_id = :iid AND d.tenant_id = :tenant
                ORDER BY d.created_at DESC
                LIMIT 1
                """
            ),
            {"iid": interaction_id, "tenant": tenant_id},
        ).mappings().first()
        return _from_row(dict(row) if row else None)
    except Exception:
        logger.exception("live_qa snapshot failed for %s", interaction_id)
        return empty()


def snapshots_for_interactions(
    conn: Any, *, tenant_id: str, interaction_ids: Iterable[str]
) -> dict[str, dict[str, Any]]:
    ids = [i for i in interaction_ids if i]
    if not ids:
        return {}
    try:
        rows = conn.execute(
            text(
                _SELECT
                + """
                WHERE d.interaction_id = ANY(:ids)
                  AND d.tenant_id = :tenant
                  AND d.id IN (
                    SELECT DISTINCT ON (interaction_id) id
                    FROM live_qa_decisions
                    WHERE interaction_id = ANY(:ids)
                      AND tenant_id = :tenant
                    ORDER BY interaction_id, created_at DESC
                  )
                """
            ),
            {"ids": ids, "tenant": tenant_id},
        ).mappings().all()
        by_ix = {
            str(r["interaction_id"]): _from_row(dict(r))
            for r in rows
            if r.get("interaction_id")
        }
        return {iid: by_ix.get(iid) or empty() for iid in ids}
    except Exception:
        logger.exception("live_qa snapshots_for_interactions failed")
        return {iid: empty() for iid in ids}


def audio_capable_map(conn: Any, interaction_ids: Iterable[str]) -> dict[str, bool]:
    ids = [i for i in interaction_ids if i]
    if not ids:
        return {}
    try:
        rows = conn.execute(
            text(
                """
                SELECT DISTINCT interaction_id
                FROM voice_sessions
                WHERE interaction_id = ANY(:ids)
                  AND status IN ('starting', 'live')
                  AND transport = 'twilio'
                  AND provider_call_id IS NOT NULL
                """
            ),
            {"ids": ids},
        ).mappings().all()
        live = {str(r["interaction_id"]) for r in rows}
        return {iid: iid in live for iid in ids}
    except Exception:
        logger.exception("live_qa audio_capable_map failed")
        return {iid: False for iid in ids}


def _from_row(row: Mapping[str, Any] | None) -> dict[str, Any]:
    out = empty()
    if not row:
        return out
    verdict = (row.get("verdict") or "").strip().lower()
    mode = (row.get("mode") or "").strip().lower()
    enacted = bool(row.get("enacted"))
    action = (row.get("recommended_action") or ACTION_NONE).strip().lower()
    codes = row.get("reason_codes") or []
    if isinstance(codes, str):
        import json

        try:
            codes = json.loads(codes)
        except Exception:
            codes = []
    if not isinstance(codes, list):
        codes = []

    status = "none"
    if enacted and action == "barge":
        status = "barge"
    elif action == "barge" and mode == "shadow":
        status = "would_barge"
    elif action == "barge":
        status = "barge"
    elif action == "whisper":
        status = "whisper"
    elif action == "inbox":
        status = "inbox"
    elif verdict and verdict != VERDICT_PASS:
        status = "flagged"

    created = row.get("created_at")
    created_iso = (
        created.isoformat().replace("+00:00", "Z")
        if hasattr(created, "isoformat")
        else created
    )
    return {
        "status": status,
        "decisionId": row.get("id"),
        "interactionId": row.get("interaction_id"),
        "mode": mode or None,
        "verdict": verdict or None,
        "recommendedAction": action or ACTION_NONE,
        "reason": row.get("reason"),
        "reasonCodes": [str(c) for c in codes if c],
        "enacted": enacted,
        "audioCapable": False,
        "createdAt": created_iso,
    }


_SELECT = """
    SELECT
      d.id, d.interaction_id, d.mode, d.verdict, d.recommended_action,
      d.reason, d.reason_codes, d.enacted, d.created_at
    FROM live_qa_decisions d
"""
