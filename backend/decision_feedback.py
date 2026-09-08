"""Decision feedback write seam: corrections never widen consent."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import text

from agent_core.treatment import schema_ready

logger = logging.getLogger(__name__)

VERDICTS = frozenset({"wrong_number", "stop_contact", "deceased", "other"})


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def record_feedback(
    conn: Any,
    *,
    tenant_id: str,
    decision_id: str,
    verdict: str,
    actor_user_id: str | None,
    actor_role: str | None = None,
    reason_code: str | None = None,
    note_redacted: str | None = None,
    endpoint: str | None = None,
    channel: str = "voice",
) -> dict[str, Any]:
    if verdict not in VERDICTS:
        raise ValueError(f"invalid_verdict:{verdict}")
    customer_id = conn.execute(
        text("SELECT customer_id FROM treatment_decisions WHERE id = :id"),
        {"id": decision_id},
    ).scalar()
    if not customer_id:
        raise KeyError("decision_not_found")

    feedback_id = None
    if schema_ready.has_table(conn, "decision_feedback"):
        feedback_id = _id("DFB")
        conn.execute(
            text(
                """
                INSERT INTO decision_feedback (
                  id, tenant_id, decision_id, actor_user_id, actor_role,
                  verdict, reason_code, note_redacted
                ) VALUES (
                  :id, :tid, :did, :actor, :role, :verdict, :reason, :note
                )
                """
            ),
            {
                "id": feedback_id,
                "tid": tenant_id,
                "did": decision_id,
                "actor": actor_user_id,
                "role": actor_role,
                "verdict": verdict,
                "reason": reason_code,
                "note": note_redacted,
            },
        )

    if verdict == "wrong_number":
        _revoke_endpoint(
            conn,
            tenant_id=tenant_id,
            customer_id=customer_id,
            endpoint=endpoint,
            channel=channel,
            evidence_ref=feedback_id or decision_id,
        )
    elif verdict == "stop_contact":
        _withdraw_consent(
            conn,
            tenant_id=tenant_id,
            customer_id=customer_id,
            endpoint=endpoint,
            channel=channel,
            evidence_ref=feedback_id or decision_id,
            actor_user_id=actor_user_id,
        )
        _place_hold(
            conn,
            tenant_id=tenant_id,
            customer_id=customer_id,
            kind="cease_and_desist",
            actor_user_id=actor_user_id,
            pending=True,
        )
    elif verdict == "deceased":
        _place_hold(
            conn,
            tenant_id=tenant_id,
            customer_id=customer_id,
            kind="deceased",
            actor_user_id=actor_user_id,
            pending=True,
        )
    return {"id": feedback_id, "customerId": customer_id, "verdict": verdict}


def append_consent_event(
    conn: Any,
    *,
    tenant_id: str,
    customer_id: str,
    verb: str,
    channel: str,
    purpose: str = "all",
    endpoint: str | None = None,
    source: str,
    evidence_ref: str | None,
    actor_kind: str,
    actor_user_id: str | None,
) -> str | None:
    if verb not in {"withdraw", "restrict", "expire", "opt_out"}:
        raise ValueError("consent_events_are_restrict_only")
    if not schema_ready.has_table(conn, "consent_events"):
        return None
    event_id = _id("CVE")
    conn.execute(
        text(
            """
            INSERT INTO consent_events (
              id, tenant_id, customer_id, endpoint, channel, purpose, verb,
              source, evidence_ref, actor_kind, actor_user_id
            ) VALUES (
              :id, :tid, :cid, :endpoint, :channel, :purpose, :verb,
              :source, :evidence, :actor_kind, :actor
            )
            """
        ),
        {
            "id": event_id,
            "tid": tenant_id,
            "cid": customer_id,
            "endpoint": endpoint,
            "channel": channel,
            "purpose": purpose,
            "verb": verb,
            "source": source,
            "evidence": evidence_ref,
            "actor_kind": actor_kind,
            "actor": actor_user_id,
        },
    )
    return event_id


def _revoke_endpoint(
    conn: Any,
    *,
    tenant_id: str,
    customer_id: str,
    endpoint: str | None,
    channel: str,
    evidence_ref: str,
) -> None:
    if not endpoint or not schema_ready.has_table(conn, "endpoint_ownership"):
        return
    conn.execute(
        text(
            """
            INSERT INTO endpoint_ownership (
              id, tenant_id, customer_id, endpoint, channel, slot, state,
              source, evidence_ref, revoked_at, revoked_reason
            ) VALUES (
              :id, :tid, :cid, :ep, :ch, 'other', 'revoked',
              'feedback', :ev, now(), 'wrong_number'
            )
            ON CONFLICT (tenant_id, endpoint, channel) DO UPDATE SET
              state = 'revoked',
              revoked_at = now(),
              revoked_reason = 'wrong_number',
              evidence_ref = EXCLUDED.evidence_ref,
              updated_at = now()
            """
        ),
        {
            "id": _id("EPO"),
            "tid": tenant_id,
            "cid": customer_id,
            "ep": endpoint,
            "ch": channel,
            "ev": evidence_ref,
        },
    )


def _withdraw_consent(
    conn: Any,
    *,
    tenant_id: str,
    customer_id: str,
    endpoint: str | None,
    channel: str,
    evidence_ref: str,
    actor_user_id: str | None,
) -> None:
    append_consent_event(
        conn,
        tenant_id=tenant_id,
        customer_id=customer_id,
        verb="withdraw",
        channel=channel if channel else "all",
        purpose="all",
        endpoint=endpoint,
        source="decision_feedback",
        evidence_ref=evidence_ref,
        actor_kind="human",
        actor_user_id=actor_user_id,
    )


def _place_hold(
    conn: Any,
    *,
    tenant_id: str,
    customer_id: str,
    kind: str,
    actor_user_id: str | None,
    pending: bool,
) -> None:
    existing = conn.execute(
        text(
            """
            SELECT id FROM treatment_holds
            WHERE customer_id = :cid AND kind = :kind AND released_at IS NULL
            """
        ),
        {"cid": customer_id, "kind": kind},
    ).first()
    if existing:
        return
    extra_cols = ""
    extra_vals = ""
    params = {
        "id": _id("THD"),
        "tid": tenant_id,
        "cid": customer_id,
        "kind": kind,
        "actor": actor_user_id,
        "source": "feedback",
    }
    if schema_ready.has_column(conn, "treatment_holds", "confirmation_state"):
        extra_cols = ", confirmation_state, writer"
        extra_vals = ", :state, 'feedback'"
        params["state"] = "pending" if pending else "confirmed"
    try:
        conn.execute(
            text(
                f"""
                INSERT INTO treatment_holds (
                  id, tenant_id, customer_id, kind, reason, source,
                  placed_by_user_id
                  {extra_cols}
                ) VALUES (
                  :id, :tid, :cid, :kind, :kind, :source, :actor
                  {extra_vals}
                )
                """
            ),
            params,
        )
    except Exception:
        logger.exception("feedback hold insert failed kind=%s", kind)
