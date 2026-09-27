"""Offers, end to end: what the customer said, what was decided, what was sent.

Read from the unified decision log (``treatment_decisions`` with
``action_family='offer'``), which every offer is written to.

The offer family's counterpart to ``decision_trace``. Everything is read from
what was logged at decision time and from the rows the decision's id links to
afterwards (the WhatsApp job, the lead, the response). A signal's evidence is
the customer's turn in the masked transcript, rendered here on read, so a
redaction applied after the fact also applies to the evidence.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from db_core import _tenant

logger = logging.getLogger(__name__)

SIGNAL_LABELS = {
    "vehicle_purchase": "Planning to buy a vehicle",
    "home_purchase": "Planning to buy a home",
    "home_renovation": "Planning home repairs",
    "new_job_or_raise": "New job or a raise",
    "business_expansion": "Growing a business",
    "marriage": "A wedding coming up",
    "child_education": "Paying for a child's education",
    "travel": "Planning travel",
    "insurance_need": "Wants insurance cover",
    "credit_limit_need": "Needs more credit",
    "high_interest_debt": "Has expensive debt to reduce",
    "gold_holding": "Holds gold",
    "product_interest": "Asked about a product",
    "not_interested": "Does not want offers",
}

SKIP_TEXT = {
    "on_dnd": "customer is on DND",
    "no_promotional_consent": "no consent to marketing on any channel",
    "promotional_consent_withdrawn": "withdrew consent to marketing",
    "said_something_that_rules_out_selling": "said something on a call that rules out selling (hardship, dispute, stop contacting)",
}


def _redact(text_in: str) -> str:
    from transcript_view import redact_line

    return redact_line(text_in or "")


def signals(conn: Any, customer_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT s.id, s.signal_code, s.product_hint, s.horizon, s.confidence, s.channel,
                   s.interaction_id, s.created_at, s.feedback, t.text AS said, t.turn_index
              FROM customer_signals s
              LEFT JOIN interaction_transcript t ON t.id = s.transcript_turn_id
             WHERE s.tenant_id = :t AND s.customer_id = :c AND s.superseded_at IS NULL
             ORDER BY s.created_at DESC LIMIT 50
            """
        ),
        {"t": _tenant(), "c": customer_id},
    ).mappings().all()
    return [
        {
            "id": r["id"],
            "code": r["signal_code"],
            "label": SIGNAL_LABELS.get(r["signal_code"], r["signal_code"]),
            "productHint": r["product_hint"],
            "horizon": r["horizon"],
            "confidence": float(r["confidence"]),
            "channel": r["channel"],
            "interactionId": r["interaction_id"],
            "createdAt": r["created_at"],
            "feedback": r["feedback"],
            # The customer's own words, masked on read.
            "evidence": _redact(r["said"])[:240] if r["said"] else None,
        }
        for r in rows
    ]


def trace(decision_id: str) -> dict[str, Any]:
    """One offer decision end to end. ``KeyError`` when it is not this tenant's."""
    import db

    tenant = _tenant()
    with db.engine.connect() as conn:
        found = conn.execute(
            text(
                "SELECT * FROM treatment_decisions"
                " WHERE id = :id AND tenant_id = :t AND action_family = 'offer'"
            ),
            {"id": decision_id, "t": tenant},
        ).mappings().first()
        if found is None:
            raise KeyError("decision_not_found")
        row = dict(found)
        features = row.get("features") or {}
        cited = features.get("citedSignals") or []
        cited_ids = [s.get("id") for s in cited if s.get("id")]
        cited_rows = [s for s in signals(conn, row["customer_id"]) if s["id"] in cited_ids]
        products = {
            r["id"]: dict(r)
            for r in conn.execute(
                text("SELECT id, name, category FROM products WHERE tenant_id = :t"), {"t": tenant}
            ).mappings()
        }
        suitability = [
            dict(r)
            for r in conn.execute(
                text(
                    """
                    SELECT product_id, verdict, assessor, assessed_at, expires_at, evidence_ref
                      FROM suitability_assessments
                     WHERE tenant_id = :t AND customer_id = :c
                       AND assessed_at <= :at + interval '1 minute'
                     ORDER BY assessed_at DESC LIMIT 20
                    """
                ),
                {"t": tenant, "c": row["customer_id"], "at": row["created_at"]},
            ).mappings()
        ]
        messages = [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT id, status, template_name, created_at FROM whatsapp_outbound_jobs WHERE decision_id = :id"
                ),
                {"id": decision_id},
            ).mappings()
        ]
        leads = [
            dict(r)
            for r in conn.execute(
                text(
                    """
                    SELECT id, stage, owner_user_id, loss_reason, won_amount, created_at
                      FROM leads WHERE to_jsonb(leads) ->> 'decision_id' = :id OR id = :lead
                    """
                ),
                {"id": decision_id, "lead": row.get("lead_id") or ""},
            ).mappings()
        ]
        name = conn.execute(text("SELECT name FROM customers WHERE id = :c"), {"c": row["customer_id"]}).scalar()

    candidates = row.get("candidates") or []
    excluded = row.get("excluded") or {}
    chosen = row.get("product_id")
    chosen_score = next(
        (c.get("score") for c in candidates if str(c.get("productId") or "") == chosen), None
    )
    options = []
    for c in candidates:
        pid = str(c.get("productId") or c.get("product_id") or "")
        options.append(
            {
                "productId": pid,
                "name": (products.get(pid) or {}).get("name") or pid,
                "status": "scored",
                "chosen": pid == chosen,
                "score": c.get("score"),
                "explanation": c.get("explanation"),
                "reasonCodes": c.get("reasonCodes") or c.get("reason_codes") or [],
            }
        )
    for pid, code in excluded.items():
        options.append(
            {
                "productId": pid,
                "name": (products.get(pid) or {}).get("name") or pid,
                "status": "blocked",
                "chosen": False,
                "reason": _offer_reason(str(code)),
                "code": code,
            }
        )
    reason = row.get("suppression_reason")
    return {
        "id": row["id"],
        "family": "offer",
        "customerId": row["customer_id"],
        "customerName": name,
        "createdAt": row["created_at"],
        "mode": row["mode"],
        "context": features.get("context") or "call",
        "signals": cited_rows,
        "choice": {
            "productId": chosen,
            "name": (products.get(chosen) or {}).get("name") if chosen else None,
            "suggestedAmount": row.get("suggested_amount"),
            "score": chosen_score,
            "held": bool(reason) or not chosen,
            "holdReason": reason,
            "holdReasonText": _offer_reason(reason) if reason else None,
            "pickProbability": row.get("action_propensity"),
        },
        "options": options,
        "suitability": suitability,
        "delivery": {
            "presented": bool(row.get("presented")),
            "presentedAt": row.get("presented_at"),
            "response": row.get("offer_response"),
            "respondedAt": row.get("responded_at"),
            "messages": messages,
            "leads": leads,
        },
        "versions": {
            "recommender": f"{row.get('recommender')} {row.get('recommender_version')}",
            "vetoStack": row.get("veto_stack_version"),
            "config": row.get("config_version"),
        },
    }


def _offer_reason(code: str | None) -> str:
    from agent_core.treatment import narrate

    if not code:
        return ""
    phrases = {
        "no_promotional_consent": "the customer has not consented to marketing",
        "promo_control_group": "held back: this customer is in the comparison group for offers",
        "shadow_mode": "shadow mode: decided, not sent",
        "bucket_too_late_for_upsell": "the account is too far overdue for any offer",
        "suitability:assessed unsuitable": "judged unsuitable for this customer",
    }
    if code in phrases:
        return phrases[code]
    if code.startswith("send:"):
        return "could not be sent: " + narrate.humanise("contact:" + code[len("send:"):])
    if code.startswith("suitability:"):
        return code[len("suitability:"):]
    if code.startswith("eligibility:"):
        return "not eligible: " + code[len("eligibility:"):].replace("_", " ")
    if code.startswith("hold:"):
        return narrate.humanise(code)
    return code.replace("_", " ").replace(":", ": ")


def log(*, customer_id: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Offer decisions, newest first."""
    import db

    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT d.id, d.created_at, d.customer_id, c.name AS customer_name, d.mode,
                       d.product_id AS chosen_product_id, p.name AS product_name,
                       NULL::float AS score, d.suppression_reason,
                       d.presented, d.offer_response AS response, d.features ->> 'context' AS context,
                       jsonb_array_length(COALESCE(d.features -> 'citedSignals', '[]'::jsonb)) AS signals
                  FROM treatment_decisions d
                  JOIN customers c ON c.id = d.customer_id
                  LEFT JOIN products p ON p.id = d.product_id
                 WHERE d.tenant_id = :t AND d.action_family = 'offer' AND d.mode <> 'simulated'
                   AND (CAST(:c AS text) IS NULL OR d.customer_id = :c)
                 ORDER BY d.created_at DESC
                 LIMIT :n OFFSET :o
                """
            ),
            {"t": _tenant(), "c": customer_id, "n": max(1, min(limit, 500)), "o": max(0, offset)},
        ).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["holdReasonText"] = _offer_reason(d["suppression_reason"]) if d["suppression_reason"] else None
        out.append(d)
    return out


def opportunities(customer_id: str) -> dict[str, Any]:
    """The customer card's panel: their signals and their latest offer decision."""
    import db

    with db.engine.connect() as conn:
        latest = conn.execute(
            text(
                """
                SELECT id FROM treatment_decisions
                 WHERE tenant_id = :t AND customer_id = :c AND action_family = 'offer'
                   AND mode <> 'simulated'
                 ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"t": _tenant(), "c": customer_id},
        ).scalar()
        found = signals(conn, customer_id)
    return {"signals": found, "decision": trace(latest) if latest else None}


def signal_health(days: int = 30) -> dict[str, Any]:
    """Is the sweep reading conversations, what is it skipping, and is it right?"""
    import db

    with db.engine.connect() as conn:
        scans = conn.execute(
            text(
                """
                SELECT status, skip_reason, count(*)::int AS n FROM signal_scans
                 WHERE tenant_id = :t AND scanned_at > now() - make_interval(days => :d)
                 GROUP BY 1, 2 ORDER BY 3 DESC
                """
            ),
            {"t": _tenant(), "d": days},
        ).mappings().all()
        precision = conn.execute(
            text(
                """
                SELECT signal_code, count(*)::int AS found,
                       count(*) FILTER (WHERE feedback = 'right')::int AS right,
                       count(*) FILTER (WHERE feedback = 'wrong')::int AS wrong
                  FROM customer_signals
                 WHERE tenant_id = :t AND created_at > now() - make_interval(days => :d)
                 GROUP BY 1 ORDER BY 2 DESC
                """
            ),
            {"t": _tenant(), "d": days},
        ).mappings().all()
    return {
        "scans": [
            {**dict(r), "skipText": SKIP_TEXT.get(r["skip_reason"] or "", r["skip_reason"])} for r in scans
        ],
        "codes": [{**dict(r), "label": SIGNAL_LABELS.get(r["signal_code"], r["signal_code"])} for r in precision],
    }


def signal_feedback(signal_id: str, verdict: str, *, by: str) -> dict[str, Any]:
    """A person marks a signal right or wrong: the extractor's precision."""
    import db

    if verdict not in {"right", "wrong"}:
        raise ValueError("verdict is right or wrong")
    with db.engine.begin() as conn:
        done = conn.execute(
            text(
                """
                UPDATE customer_signals SET feedback = :v, feedback_by = :by, feedback_at = now()
                 WHERE id = :id AND tenant_id = :t RETURNING customer_id
                """
            ),
            {"id": signal_id, "v": verdict, "by": by, "t": _tenant()},
        ).first()
    if done is None:
        raise KeyError("signal_not_found")
    return {"id": signal_id, "feedback": verdict}
