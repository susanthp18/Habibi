"""The append-only live QA decision log.

Written on failing turns and barge recommendations, including shadow. A log
that only contains the barges we executed has no negative class.

Nothing here fails loudly. A logging error must never cost the call.
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from typing import Any, Iterator, Mapping, Sequence

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _id() -> str:
    return f"LQ-{uuid.uuid4().hex[:12].upper()}"


@contextlib.contextmanager
def _writer(conn: Any | None) -> Iterator[Any]:
    if conn is not None:
        yield conn
        return
    import db

    with db.engine.begin() as owned:
        yield owned


def record(
    *,
    conn: Any | None = None,
    tenant_id: str,
    customer_id: str | None,
    account_id: str | None,
    interaction_id: str | None,
    mode: str,
    feature_schema_version: str,
    features: Mapping[str, Any],
    verdict: str,
    recommended_action: str,
    reason: str | None,
    reason_codes: Sequence[str],
    findings: Sequence[Mapping[str, Any]],
    latency_ms: int | None,
) -> str | None:
    decision_id = _id()
    try:
        with _writer(conn) as c:
            import db

            c.execute(
                text(
                    """
                    INSERT INTO live_qa_decisions (
                      id, tenant_id, customer_id, account_id, interaction_id,
                      mode, feature_schema_version, features, verdict,
                      recommended_action, reason, reason_codes, findings,
                      latency_ms, created_at
                    ) VALUES (
                      :id, :tenant, :customer_id, :account_id, :interaction_id,
                      :mode, :feature_schema_version, CAST(:features AS jsonb),
                      :verdict, :recommended_action, :reason,
                      CAST(:reason_codes AS jsonb), CAST(:findings AS jsonb),
                      :latency_ms, now()
                    )
                    """
                ),
                {
                    "id": decision_id,
                    "tenant": tenant_id or db.current_tenant(),
                    "customer_id": customer_id,
                    "account_id": account_id,
                    "interaction_id": interaction_id,
                    "mode": mode,
                    "feature_schema_version": feature_schema_version,
                    "features": json.dumps(dict(features), default=str),
                    "verdict": verdict,
                    "recommended_action": recommended_action,
                    "reason": reason,
                    "reason_codes": json.dumps(list(reason_codes)),
                    "findings": json.dumps(list(findings), default=str),
                    "latency_ms": latency_ms,
                },
            )
        return decision_id
    except Exception:
        logger.exception("live_qa decision log failed for ix=%s", interaction_id)
        return None


def mark_enacted(
    decision_id: str | None,
    *,
    conn: Any | None = None,
    ref: str | None = None,
) -> None:
    if not decision_id:
        return
    try:
        with _writer(conn) as c:
            c.execute(
                text(
                    """
                    UPDATE live_qa_decisions
                    SET enacted = true,
                        enacted_at = now(),
                        enacted_ref = COALESCE(:ref, enacted_ref)
                    WHERE id = :id AND enacted IS FALSE
                    """
                ),
                {"id": decision_id, "ref": ref},
            )
    except Exception:
        logger.exception("live_qa mark_enacted failed for %s", decision_id)


def pending_auto_barge(interaction_id: str, *, conn: Any | None = None) -> dict[str, Any] | None:
    """Latest un-enacted critical barge decision for this call, if any."""
    if not interaction_id:
        return None
    try:
        with _writer(conn) as c:
            row = c.execute(
                text(
                    """
                    SELECT id, reason, reason_codes, recommended_action, mode
                    FROM live_qa_decisions
                    WHERE interaction_id = :iid
                      AND enacted IS FALSE
                      AND recommended_action = 'barge'
                      AND verdict = 'fail_critical'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"iid": interaction_id},
            ).mappings().first()
        return dict(row) if row else None
    except Exception:
        logger.exception("live_qa pending_auto_barge failed for %s", interaction_id)
        return None
