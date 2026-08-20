"""The living authority policy — latest decision, one shape every screen reads.

``recommend_authority()`` is the write. This module is the read. Floor, Handoff
and Customer 360 must not each invent a different opinion of "what may we
waive"; they consume this snapshot.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

from sqlalchemy import text

from agent_core.authority.matrix import VERDICT_AUTO, VERDICT_CAP, VERDICT_ESCALATE
from agent_core.authority.talk import escalate_line, talk_track
from agent_core.authority.matrix import MatrixDecision

logger = logging.getLogger(__name__)

STATUSES = (
    "none",
    "escalate",
    "shadow",
    "cap",
    "auto_approve",
    "applied",
)

_REASON_LABELS: dict[str, str] = {
    "engine_off": "Authority engine is off",
    "engine_error": "Authority engine errored — escalate",
    "unknown_fee_type": "Unknown fee type — escalate",
    "identity_not_verified": "Identity not verified",
    "prior_goodwill_12m": "Goodwill already used in the last 12 months",
    "dpd_too_high": "DPD too high for live goodwill",
    "dpd_unknown": "DPD unknown — escalate",
    "outstanding_too_high": "Ticket too large for live goodwill",
    "tenure_too_short": "Tenure too short for live goodwill",
    "settlement_live_forbidden": "Do not quote a settlement percentage",
    "restructure_live_forbidden": "Restructuring needs a specialist",
    "bounce_reversal_live_forbidden": "Do not promise bounce-charge reversal",
    "asked_above_cap": "Asked above the goodwill ceiling",
    "within_cap": "Asked amount is inside the cap",
    "cap_available": "In-policy goodwill ceiling",
    "nothing_to_waive": "No late fee on the ledger to reverse",
    "hold:hardship": "Hardship hold — do not pitch a waiver",
    "hold:legal": "Legal hold — do not pitch a waiver",
    "hold:complaint": "Complaint hold — do not pitch a waiver",
    "hold:bereavement": "Bereavement hold — do not pitch a waiver",
}


def empty() -> dict[str, Any]:
    return {
        "status": "none",
        "decisionId": None,
        "customerId": None,
        "accountId": None,
        "interactionId": None,
        "mode": None,
        "feeType": None,
        "askedAmount": None,
        "verdict": None,
        "approvedAmount": None,
        "capAmount": None,
        "reason": None,
        "reasonLabel": None,
        "reasonCodes": [],
        "talkTrack": None,
        "enacted": False,
        "disputeId": None,
        "createdAt": None,
    }


def humanize(reason: str | None) -> str | None:
    if not reason:
        return None
    if reason in _REASON_LABELS:
        return _REASON_LABELS[reason]
    if reason.startswith("hold:"):
        return _REASON_LABELS.get(reason) or f"{reason.split(':', 1)[-1].title()} hold — do not pitch a waiver"
    return reason.replace("_", " ")


def snapshot(
    conn: Any,
    *,
    customer_id: str,
    tenant_id: str,
    interaction_id: str | None = None,
) -> dict[str, Any]:
    row = _latest(
        conn, customer_id=customer_id, tenant_id=tenant_id, interaction_id=interaction_id
    )
    return _from_row(row) if row else empty() | {"customerId": customer_id}


def snapshots_for_interactions(
    conn: Any, *, tenant_id: str, interaction_ids: Iterable[str]
) -> dict[str, dict[str, Any]]:
    ids = [i for i in interaction_ids if i]
    if not ids:
        return {}
    rows = conn.execute(
        text(
            _SELECT
            + """
            WHERE d.interaction_id = ANY(:ids)
              AND d.tenant_id = :tenant
              AND d.id IN (
                SELECT DISTINCT ON (interaction_id) id
                FROM authority_decisions
                WHERE interaction_id = ANY(:ids)
                  AND tenant_id = :tenant
                ORDER BY interaction_id, created_at DESC
              )
            """
        ),
        {"ids": ids, "tenant": tenant_id},
    ).mappings().all()
    by_ix = {str(r["interaction_id"]): _from_row(dict(r)) for r in rows if r.get("interaction_id")}
    return {iid: by_ix.get(iid) or empty() for iid in ids}


def _from_row(row: Mapping[str, Any] | None) -> dict[str, Any]:
    out = empty()
    if not row:
        return out
    verdict = (row.get("verdict") or "").strip().lower()
    mode = (row.get("mode") or "").strip().lower()
    enacted = bool(row.get("enacted"))
    reason = row.get("reason")
    codes = row.get("reason_codes")
    if isinstance(codes, str):
        import json

        try:
            codes = json.loads(codes)
        except Exception:
            codes = []
    if not isinstance(codes, list):
        codes = []

    status = "none"
    if enacted:
        status = "applied"
    elif verdict == VERDICT_ESCALATE:
        status = "escalate"
    elif mode == "shadow" and verdict in {VERDICT_AUTO, VERDICT_CAP}:
        status = "shadow"
    elif verdict == VERDICT_AUTO:
        status = "auto_approve"
    elif verdict == VERDICT_CAP:
        status = "cap"
    elif verdict:
        status = "escalate"

    created = row.get("created_at")
    created_iso = (
        created.isoformat().replace("+00:00", "Z") if hasattr(created, "isoformat") else created
    )
    approved = row.get("approved_amount")
    cap = row.get("cap_amount")
    fee_type = row.get("fee_type") or "late_fee"
    track = row.get("talk_track")
    if not track:
        stub = MatrixDecision(
            verdict=verdict or VERDICT_ESCALATE,
            approved_amount=float(approved) if approved is not None else None,
            cap_amount=float(cap) if cap is not None else None,
            reason=reason or "",
            reason_codes=tuple(str(c) for c in codes),
        )
        track = talk_track(stub, fee_type=fee_type) if verdict else escalate_line(reason)

    asked = row.get("asked_amount")
    return {
        "status": status,
        "decisionId": row.get("id"),
        "customerId": row.get("customer_id"),
        "accountId": row.get("account_id"),
        "interactionId": row.get("interaction_id"),
        "mode": mode or None,
        "feeType": fee_type,
        "askedAmount": float(asked) if asked is not None else None,
        "verdict": verdict or None,
        "approvedAmount": float(approved) if approved is not None else None,
        "capAmount": float(cap) if cap is not None else None,
        "reason": reason,
        "reasonLabel": humanize(reason),
        "reasonCodes": [str(c) for c in codes if c],
        "talkTrack": track,
        "enacted": enacted,
        "disputeId": row.get("dispute_id"),
        "createdAt": created_iso,
    }


_SELECT = """
    SELECT
      d.id, d.customer_id, d.account_id, d.interaction_id, d.fee_type,
      d.asked_amount, d.mode, d.verdict, d.approved_amount, d.cap_amount,
      d.reason, d.reason_codes, d.talk_track, d.enacted, d.dispute_id, d.created_at
    FROM authority_decisions d
"""


def _latest(
    conn: Any,
    *,
    customer_id: str,
    tenant_id: str,
    interaction_id: str | None,
) -> dict[str, Any] | None:
    if interaction_id:
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
        if row:
            return dict(row)
    row = conn.execute(
        text(
            _SELECT
            + """
            WHERE d.customer_id = :cid AND d.tenant_id = :tenant
            ORDER BY d.created_at DESC
            LIMIT 1
            """
        ),
        {"cid": customer_id, "tenant": tenant_id},
    ).mappings().first()
    return dict(row) if row else None
