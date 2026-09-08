"""Complaint pack: one signed bundle, missing evidence is an error."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from agent_core.treatment import schema_ready

REQUIRED_SECTIONS = (
    "identity",
    "complaintEvents",
    "subjectRequests",
    "decisions",
    "policyBindings",
    "consentHistory",
    "endpointOwnership",
    "contactLedger",
    "receipts",
    "suppressions",
    "enactmentAttempts",
    "incidents",
    "externalLedger",
    "reconciliation",
    "mappings",
    "actionContracts",
    "acknowledgements",
    "generatedAt",
)


class IncompletePack(ValueError):
    """A required section was empty or unreadable."""


def compose(
    conn: Any,
    *,
    tenant_id: str,
    customer_id: str,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> dict[str, Any]:
    start = window_start or datetime(1970, 1, 1, tzinfo=timezone.utc)
    end = window_end or datetime.now(timezone.utc)
    identity = conn.execute(
        text(
            """
            SELECT id, tenant_id, name, timezone, language
            FROM customers WHERE id = :cid AND tenant_id = :tid
            """
        ),
        {"cid": customer_id, "tid": tenant_id},
    ).mappings().first()
    if identity is None:
        raise IncompletePack("identity")

    schema_ready.reset_cache()

    def _rows(sql: str, **params: Any) -> list[dict[str, Any]]:
        return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]

    pack = {
        "identity": {
            "customerId": identity["id"],
            "tenantId": identity["tenant_id"],
            "timezone": identity["timezone"],
            "language": identity["language"],
        },
        "complaintEvents": (
            _rows(
                """
                SELECT id, kind, reason, created_at FROM treatment_holds
                WHERE customer_id = :cid AND kind IN ('complaint','legal')
                  AND created_at >= :start AND created_at < :end
                ORDER BY created_at
                """,
                cid=customer_id,
                start=start,
                end=end,
            )
            + (
                _rows(
                    """
                    SELECT id, kind, direction AS reason, created_at
                    FROM bank_complaint_events
                    WHERE customer_id = :cid AND tenant_id = :tid
                      AND created_at >= :start AND created_at < :end
                    ORDER BY created_at
                    """,
                    cid=customer_id,
                    tid=tenant_id,
                    start=start,
                    end=end,
                )
                if schema_ready.has_table(conn, "bank_complaint_events")
                else []
            )
        ),
        "subjectRequests": (
            _rows(
                """
                SELECT id, kind, state, received_at, due_at FROM subject_requests
                WHERE customer_id = :cid AND received_at >= :start AND received_at < :end
                ORDER BY received_at
                """,
                cid=customer_id,
                start=start,
                end=end,
            )
            if schema_ready.has_table(conn, "subject_requests")
            else []
        ),
        "decisions": _rows(
            """
            SELECT id, chosen_action, suppression_reason, policy_version, created_at
            FROM treatment_decisions
            WHERE customer_id = :cid AND created_at >= :start AND created_at < :end
            ORDER BY created_at
            """,
            cid=customer_id,
            start=start,
            end=end,
        ),
        "policyBindings": _rows(
            """
            SELECT id, policy_binding, policy_binding_hash FROM treatment_decisions
            WHERE customer_id = :cid AND created_at >= :start AND created_at < :end
              AND policy_binding IS NOT NULL
            """,
            cid=customer_id,
            start=start,
            end=end,
        )
        if schema_ready.has_column(conn, "treatment_decisions", "policy_binding")
        else [],
        "consentHistory": _rows(
            """
            SELECT cc.channel, cc.status, cc.purpose, cc.updated_at
            FROM channel_consents cc
            JOIN consent_records cr ON cr.id = cc.consent_id
            WHERE cr.customer_id = :cid
            """,
            cid=customer_id,
        ),
        "endpointOwnership": (
            _rows(
                """
                SELECT endpoint, channel, state, verified_at, revoked_at
                FROM endpoint_ownership WHERE customer_id = :cid
                """,
                cid=customer_id,
            )
            if schema_ready.has_table(conn, "endpoint_ownership")
            else []
        ),
        "contactLedger": _rows(
            """
            SELECT id, channel, purpose, outcome, reason, occurred_at
            FROM contact_events
            WHERE customer_id = :cid AND occurred_at >= :start AND occurred_at < :end
            ORDER BY occurred_at
            """,
            cid=customer_id,
            start=start,
            end=end,
        ),
        "receipts": (
            _rows(
                """
                SELECT id, channel, state, occurred_at FROM contact_delivery_events
                WHERE customer_id = :cid AND occurred_at >= :start AND occurred_at < :end
                ORDER BY occurred_at
                """,
                cid=customer_id,
                start=start,
                end=end,
            )
            if schema_ready.has_table(conn, "contact_delivery_events")
            else []
        ),
        "suppressions": _rows(
            """
            SELECT id, kind, reason, source, starts_at, released_at
            FROM treatment_holds WHERE customer_id = :cid
            ORDER BY starts_at
            """,
            cid=customer_id,
        ),
        "enactmentAttempts": (
            _rows(
                """
                SELECT a.id, a.channel, a.action, a.state, a.created_at
                FROM enactment_attempts a
                JOIN treatment_decisions d ON d.id = a.decision_id
                WHERE d.customer_id = :cid AND a.created_at >= :start AND a.created_at < :end
                """,
                cid=customer_id,
                start=start,
                end=end,
            )
            if schema_ready.has_table(conn, "enactment_attempts")
            else []
        ),
        "incidents": (
            _rows(
                """
                SELECT id, severity, state, summary, detected_at
                FROM security_incidents
                WHERE tenant_id = :tid AND detected_at >= :start AND detected_at < :end
                """,
                tid=tenant_id,
                start=start,
                end=end,
            )
            if schema_ready.has_table(conn, "security_incidents")
            else []
        ),
        "externalLedger": (
            _rows(
                """
                SELECT id, external_key, channel, occurred_at, outcome
                FROM bank_external_contacts
                WHERE tenant_id = :tid AND customer_id = :cid
                  AND occurred_at >= :start AND occurred_at < :end
                """,
                tid=tenant_id,
                cid=customer_id,
                start=start,
                end=end,
            )
            if schema_ready.has_table(conn, "bank_external_contacts")
            else []
        ),
        "reconciliation": (
            _rows(
                """
                SELECT id, contract_code, business_date, status
                FROM bank_reconciliation_runs
                WHERE tenant_id = :tid
                  AND created_at >= :start AND created_at < :end
                """,
                tid=tenant_id,
                start=start,
                end=end,
            )
            if schema_ready.has_table(conn, "bank_reconciliation_runs")
            else []
        ),
        "mappings": (
            _rows(
                """
                SELECT catalogue, raw_value, state FROM bank_mapping_reviews
                WHERE tenant_id = :tid
                """,
                tid=tenant_id,
            )
            if schema_ready.has_table(conn, "bank_mapping_reviews")
            else []
        ),
        "actionContracts": (
            _rows(
                """
                SELECT ac.id, ac.decision_id, ac.digest, ac.version
                FROM action_contracts ac
                JOIN treatment_decisions d ON d.id = ac.decision_id
                WHERE ac.tenant_id = :tid AND d.customer_id = :cid
                """,
                tid=tenant_id,
                cid=customer_id,
            )
            if schema_ready.has_table(conn, "action_contracts")
            else []
        ),
        "acknowledgements": (
            _rows(
                """
                SELECT a.id, a.provider_ref, a.status, a.received_at
                FROM bank_outbound_acks a
                JOIN bank_outbound_outbox o ON o.id = a.outbox_id
                WHERE a.tenant_id = :tid AND o.decision_id IN (
                  SELECT id FROM treatment_decisions WHERE customer_id = :cid
                )
                """,
                tid=tenant_id,
                cid=customer_id,
            )
            if schema_ready.has_table(conn, "bank_outbound_acks")
            else []
        ),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "recordingRetentionMonths": _retention(conn, tenant_id),
    }
    missing = [key for key in REQUIRED_SECTIONS if key not in pack or pack[key] in (None,)]
    if missing:
        raise IncompletePack(",".join(missing))
    # Empty green sections are forbidden for the complaint itself and the ledger.
    for required in ("identity", "generatedAt"):
        if not pack[required]:
            raise IncompletePack(required)
    pack["digest"] = "sha256:" + hashlib.sha256(
        json.dumps(pack, default=str, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return pack


def _retention(conn: Any, tenant_id: str) -> int | None:
    import policy_rules

    try:
        rules = policy_rules.resolve(conn, tenant_id=tenant_id)
        return rules.recording_retention_months()
    except Exception:
        return None
