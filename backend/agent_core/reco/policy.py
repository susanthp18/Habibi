"""The living offer policy — latest decision + open lead, one shape every screen reads.

``recommend()`` is the write. This module is the read. Floor, Handoff, Customer
360 and Workspace must not each invent a different opinion of "what may we
say"; they consume this snapshot.

Talk tracks are reconstructed from logged reason codes rather than stored,
because ``offer_decisions`` never persisted them. ``talk.talk_track`` is
deterministic, so the sentence a rep sees is the sentence the bot would have
said.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

from sqlalchemy import text

from agent_core.reco import talk

logger = logging.getLogger(__name__)

STATUSES = (
    "none",
    "suppressed",
    "shadow",
    "ready",
    "presented",
    "interested",
    "declined",
    "open_lead",
)

_SUPPRESSION_LABELS: dict[str, str] = {
    "dnd": "DND is on — do not pitch",
    "channel_consent_closed": "No consent on this channel",
    "no_commitment_yet": "No PTP or callback yet — collections first",
    "sentiment_below_floor": "Sentiment too low to pitch",
    "escalated": "Call is escalated — do not pitch",
    "dispute_open_this_call": "Dispute opened this call — do not pitch",
    "hardship_stated": "Hardship stated — do not pitch",
    "declined_this_call": "Already declined this call",
    "per_call_cap_reached": "Per-call offer cap reached",
    "per_customer_cap_reached": "30-day offer cap reached",
    "no_eligible_candidates": "Nothing eligible in the catalog",
    "below_score_threshold": "Best candidate below the score floor",
    "engine_off": "Offer engine is off",
    "engine_error": "Offer engine errored — stayed quiet",
    "shadow_mode": "Shadow mode — scored, not spoken",
}


def empty() -> dict[str, Any]:
    return {
        "status": "none",
        "decisionId": None,
        "customerId": None,
        "interactionId": None,
        "mode": None,
        "channel": None,
        "suppressionReason": None,
        "suppressionLabel": None,
        "productId": None,
        "productName": None,
        "suggestedAmount": None,
        "talkTrack": None,
        "reasonCodes": [],
        "score": None,
        "presented": False,
        "response": None,
        "leadId": None,
        "leadStage": None,
        "preferredWindow": None,
        "createdAt": None,
    }


def humanize_suppression(reason: str | None) -> str | None:
    if not reason:
        return None
    if reason in _SUPPRESSION_LABELS:
        return _SUPPRESSION_LABELS[reason]
    if reason.startswith("eligibility:"):
        return "Eligibility blocked this product"
    return reason.replace("_", " ")


def snapshot(
    conn: Any,
    *,
    customer_id: str,
    tenant_id: str,
    interaction_id: str | None = None,
) -> dict[str, Any]:
    """Latest policy for a customer, optionally pinned to one interaction."""
    decision = _latest_decision(
        conn, customer_id=customer_id, tenant_id=tenant_id, interaction_id=interaction_id
    )
    lead = _open_lead(conn, customer_id)
    return _merge(customer_id, decision, lead)


def snapshots_for_interactions(
    conn: Any, *, tenant_id: str, interaction_ids: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """One snapshot per live interaction. Empty dict values are still shaped."""
    ids = [i for i in interaction_ids if i]
    if not ids:
        return {}
    decisions = _latest_decisions_by_interaction(conn, tenant_id=tenant_id, interaction_ids=ids)
    customer_ids = {d["customer_id"] for d in decisions.values() if d.get("customer_id")}
    leads = _open_leads_by_customer(conn, customer_ids) if customer_ids else {}
    out: dict[str, dict[str, Any]] = {}
    for iid in ids:
        decision = decisions.get(iid)
        cid = (decision or {}).get("customer_id")
        lead = leads.get(cid) if cid else None
        out[iid] = _merge(cid, decision, lead) if cid else empty()
    return out


def _merge(
    customer_id: str | None,
    decision: Mapping[str, Any] | None,
    lead: Mapping[str, Any] | None,
) -> dict[str, Any]:
    out = empty()
    out["customerId"] = customer_id
    if decision:
        out.update(_from_decision(decision))
    if lead:
        out["leadId"] = lead.get("id")
        out["leadStage"] = lead.get("stage")
        if not out["productId"]:
            out["productId"] = lead.get("product_id")
            out["productName"] = lead.get("product_name")
            amt = lead.get("offer_amount")
            out["suggestedAmount"] = float(amt) if amt is not None else None
        out["status"] = "open_lead"
        if not out["talkTrack"] and out["productName"]:
            out["talkTrack"] = _talk(
                name=out["productName"],
                amount=out["suggestedAmount"],
                reason_codes=tuple(out["reasonCodes"] or ()),
                channel=out["channel"] or "voice",
                preferred_window=out["preferredWindow"],
            )
    return out


def _from_decision(row: Mapping[str, Any]) -> dict[str, Any]:
    chosen = row.get("chosen_product_id")
    reason = row.get("suppression_reason")
    mode = (row.get("mode") or "").strip().lower()
    presented = bool(row.get("presented"))
    response = row.get("response")
    amount = row.get("suggested_amount")
    features = row.get("features") if isinstance(row.get("features"), dict) else {}
    window = features.get("preferredWindow")
    codes = _reason_codes(row, chosen)
    name = row.get("product_name")
    channel = row.get("channel") or "voice"

    status = "none"
    if reason and not chosen:
        status = "suppressed"
    elif mode == "shadow" and chosen:
        status = "shadow"
    elif response == "declined":
        status = "declined"
    elif response == "interested":
        status = "interested"
    elif presented:
        status = "presented"
    elif chosen and mode == "live":
        status = "ready"
    elif reason:
        status = "suppressed"

    created = row.get("created_at")
    created_iso = (
        created.isoformat().replace("+00:00", "Z") if hasattr(created, "isoformat") else created
    )

    return {
        "status": status,
        "decisionId": row.get("id"),
        "customerId": row.get("customer_id"),
        "interactionId": row.get("interaction_id"),
        "mode": mode or None,
        "channel": channel,
        "suppressionReason": reason,
        "suppressionLabel": humanize_suppression(reason),
        "productId": chosen,
        "productName": name,
        "suggestedAmount": float(amount) if amount is not None else None,
        "talkTrack": _talk(
            name=name or "this product",
            amount=float(amount) if amount is not None else None,
            reason_codes=codes,
            channel=channel,
            preferred_window=window,
        )
        if chosen
        else None,
        "reasonCodes": list(codes),
        "score": float(row["score"]) if row.get("score") is not None else None,
        "presented": presented,
        "response": response,
        "preferredWindow": window,
        "createdAt": created_iso,
    }


def _talk(
    *,
    name: str,
    amount: float | None,
    reason_codes: tuple[str, ...],
    channel: str,
    preferred_window: str | None,
) -> str:
    from agent_core.reco.scoring import ScoredOffer

    stub = ScoredOffer(
        product_id="",
        name=name,
        score=0.0,
        suggested_amount=amount,
        roi=None,
        category=None,
        reason_codes=reason_codes,
        explanation="",
    )
    return talk.talk_track(stub, channel=channel, preferred_window=preferred_window)


def _reason_codes(row: Mapping[str, Any], product_id: str | None) -> tuple[str, ...]:
    if not product_id:
        return ()
    candidates = row.get("candidates")
    if not isinstance(candidates, list):
        return ()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        if item.get("productId") == product_id:
            codes = item.get("reasonCodes") or []
            return tuple(str(c) for c in codes if c)
    return ()


_DECISION_SELECT = """
    SELECT
      d.id, d.customer_id, d.interaction_id, d.channel, d.mode,
      d.chosen_product_id, d.suggested_amount, d.score,
      d.presented, d.response, d.suppression_reason,
      d.features, d.candidates, d.created_at,
      p.name AS product_name
    FROM offer_decisions d
    LEFT JOIN products p ON p.id = d.chosen_product_id
"""


def _latest_decision(
    conn: Any,
    *,
    customer_id: str,
    tenant_id: str,
    interaction_id: str | None,
) -> dict[str, Any] | None:
    if interaction_id:
        row = conn.execute(
            text(
                _DECISION_SELECT
                + """
                WHERE d.interaction_id = :iid
                  AND d.tenant_id = :tenant
                  AND d.mode <> 'simulated'
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
            _DECISION_SELECT
            + """
            WHERE d.customer_id = :cid
              AND d.tenant_id = :tenant
              AND d.mode <> 'simulated'
            ORDER BY d.created_at DESC
            LIMIT 1
            """
        ),
        {"cid": customer_id, "tenant": tenant_id},
    ).mappings().first()
    return dict(row) if row else None


def _latest_decisions_by_interaction(
    conn: Any, *, tenant_id: str, interaction_ids: list[str]
) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        text(
            _DECISION_SELECT
            + """
            WHERE d.interaction_id = ANY(:ids)
              AND d.tenant_id = :tenant
              AND d.mode <> 'simulated'
              AND d.id IN (
                SELECT DISTINCT ON (interaction_id) id
                FROM offer_decisions
                WHERE interaction_id = ANY(:ids)
                  AND tenant_id = :tenant
                  AND mode <> 'simulated'
                ORDER BY interaction_id, created_at DESC
              )
            """
        ),
        {"ids": interaction_ids, "tenant": tenant_id},
    ).mappings().all()
    return {str(r["interaction_id"]): dict(r) for r in rows if r.get("interaction_id")}


def _open_lead(conn: Any, customer_id: str) -> dict[str, Any] | None:
    import db

    row = conn.execute(
        text(
            """
            SELECT l.id, l.product_id, l.stage, l.offer_amount, p.name AS product_name
            FROM leads l
            LEFT JOIN products p ON p.id = l.product_id
            WHERE l.customer_id = :cid
              AND l.stage = ANY(:stages)
            ORDER BY
              CASE l.priority
                WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                WHEN 'normal' THEN 2 ELSE 3
              END,
              l.captured_at DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"cid": customer_id, "stages": list(db.OPEN_LEAD_STAGES)},
    ).mappings().first()
    return dict(row) if row else None


def _open_leads_by_customer(
    conn: Any, customer_ids: set[str]
) -> dict[str, dict[str, Any]]:
    import db

    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (l.customer_id)
              l.customer_id, l.id, l.product_id, l.stage, l.offer_amount,
              p.name AS product_name
            FROM leads l
            LEFT JOIN products p ON p.id = l.product_id
            WHERE l.customer_id = ANY(:ids)
              AND l.stage = ANY(:stages)
            ORDER BY
              l.customer_id,
              CASE l.priority
                WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                WHEN 'normal' THEN 2 ELSE 3
              END,
              l.captured_at DESC NULLS LAST
            """
        ),
        {"ids": list(customer_ids), "stages": list(db.OPEN_LEAD_STAGES)},
    ).mappings().all()
    return {str(r["customer_id"]): dict(r) for r in rows}
