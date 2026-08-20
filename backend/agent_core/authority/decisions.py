"""The append-only authority decision log.

Written on every invocation — including escalate, including shadow. A log that
only contains waivers we posted has no negative class and cannot answer "why
did the bot refuse Tuesday?".

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
    return f"AD-{uuid.uuid4().hex[:12].upper()}"


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
    customer_id: str,
    account_id: str | None,
    interaction_id: str | None,
    fee_type: str,
    asked_amount: float | None,
    mode: str,
    feature_schema_version: str,
    features: Mapping[str, Any],
    verdict: str,
    approved_amount: float | None,
    cap_amount: float | None,
    reason: str | None,
    reason_codes: Sequence[str],
    talk_track: str | None,
    latency_ms: int | None,
) -> str | None:
    decision_id = _id()
    try:
        with _writer(conn) as c:
            import db

            c.execute(
                text(
                    """
                    INSERT INTO authority_decisions (
                      id, tenant_id, customer_id, account_id, interaction_id,
                      fee_type, asked_amount, mode, feature_schema_version,
                      features, verdict, approved_amount, cap_amount,
                      reason, reason_codes, talk_track, latency_ms, created_at
                    ) VALUES (
                      :id, :tenant, :customer_id, :account_id, :interaction_id,
                      :fee_type, :asked_amount, :mode, :feature_schema_version,
                      CAST(:features AS jsonb), :verdict, :approved_amount, :cap_amount,
                      :reason, CAST(:reason_codes AS jsonb), :talk_track, :latency_ms, now()
                    )
                    """
                ),
                {
                    "id": decision_id,
                    "tenant": tenant_id or db.current_tenant(),
                    "customer_id": customer_id,
                    "account_id": account_id,
                    "interaction_id": interaction_id,
                    "fee_type": fee_type,
                    "asked_amount": asked_amount,
                    "mode": mode,
                    "feature_schema_version": feature_schema_version,
                    "features": json.dumps(dict(features), default=str),
                    "verdict": verdict,
                    "approved_amount": approved_amount,
                    "cap_amount": cap_amount,
                    "reason": reason,
                    "reason_codes": json.dumps(list(reason_codes)),
                    "talk_track": talk_track,
                    "latency_ms": latency_ms,
                },
            )
        return decision_id
    except Exception:
        logger.exception("authority decision log failed for customer=%s", customer_id)
        return None


def mark_enacted(
    decision_id: str | None,
    *,
    conn: Any | None = None,
    ledger_id: str | None = None,
    dispute_id: str | None = None,
) -> None:
    if not decision_id:
        return
    try:
        with _writer(conn) as c:
            c.execute(
                text(
                    """
                    UPDATE authority_decisions
                    SET enacted = true,
                        enacted_at = now(),
                        enacted_ref = COALESCE(:ledger_id, enacted_ref),
                        dispute_id = COALESCE(:dispute_id, dispute_id)
                    WHERE id = :id AND enacted IS FALSE
                    """
                ),
                {
                    "id": decision_id,
                    "ledger_id": ledger_id,
                    "dispute_id": dispute_id,
                },
            )
    except Exception:
        logger.exception("authority mark_enacted failed for %s", decision_id)
