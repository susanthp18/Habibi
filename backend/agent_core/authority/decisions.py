"""The append-only authority decision log.

Written on every invocation — including escalate, including shadow. A log that
only contains waivers we posted has no negative class and cannot answer "why
did the bot refuse Tuesday?".

``record`` never fails loudly: a logging error must never cost the call.
``mark_enacted`` and ``bind_ceiling`` are the money path. They raise.
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
) -> bool:
    """Claim the decision. Returns True only when this writer flipped enacted.

    A lost race or a failed write must not look like success: the ledger insert
    that called this sits in the same transaction and has to roll back with it.
    """
    if not decision_id:
        return True
    with _writer(conn) as c:
        result = c.execute(
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
        return int(result.rowcount or 0) == 1


#: Appended when a Mission profile lowers the stored cap. Stable for counting.
MISSION_CEILING = "mission_ceiling"


def bind_ceiling(
    decision_id: str,
    *,
    ceiling: float,
    profile: str | None = None,
    conn: Any | None = None,
) -> None:
    """Persist a Mission profile ceiling onto the decision the enact path trusts.

    Can only ever lower ``approved_amount`` / ``cap_amount``. An already-enacted
    row is left alone — the waiver has posted and rewriting the cap would
    disagree with the ledger.
    """
    from agent_core.authority import talk as authority_talk
    from agent_core.authority.matrix import (
        VERDICT_ESCALATE,
        MatrixDecision,
    )

    cap = max(0.0, float(ceiling))
    with _writer(conn) as c:
        row = (
            c.execute(
                text(
                    """
                    SELECT id, fee_type, verdict, reason, approved_amount, cap_amount,
                           enacted
                    FROM authority_decisions
                    WHERE id = :id
                    FOR UPDATE
                    """
                ),
                {"id": decision_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ValueError("decision_not_found")
        if row["enacted"]:
            return

        current_approved = float(row["approved_amount"] or 0)
        current_cap = float(row["cap_amount"] or current_approved or 0)
        new_approved = min(current_approved, cap) if current_approved > 0 else cap
        new_cap = min(current_cap, cap) if current_cap > 0 else cap
        if (
            cap > 0
            and current_approved > 0
            and new_approved >= current_approved
            and new_cap >= current_cap
        ):
            return

        fee_type = row["fee_type"] or "late_fee"
        if cap <= 0:
            new_verdict = VERDICT_ESCALATE
            track = authority_talk.escalate_line(
                MISSION_CEILING, fee_type=fee_type
            )
        else:
            new_verdict = row["verdict"]
            matrix = MatrixDecision(
                verdict=new_verdict,
                approved_amount=new_approved,
                cap_amount=new_cap,
                reason=str(row["reason"] or MISSION_CEILING),
                reason_codes=(MISSION_CEILING,),
            )
            track = authority_talk.talk_track(matrix, fee_type=fee_type)

        result = c.execute(
            text(
                """
                UPDATE authority_decisions
                SET approved_amount = :approved,
                    cap_amount = :cap,
                    verdict = :verdict,
                    talk_track = :talk_track,
                    reason_codes = CASE
                      WHEN reason_codes @> CAST(:code AS jsonb) THEN reason_codes
                      ELSE COALESCE(reason_codes, '[]'::jsonb)
                           || CAST(:code AS jsonb)
                    END
                WHERE id = :id AND enacted IS FALSE
                """
            ),
            {
                "id": decision_id,
                "approved": new_approved,
                "cap": new_cap,
                "verdict": new_verdict,
                "talk_track": track,
                "code": json.dumps([MISSION_CEILING]),
            },
        )
        if int(result.rowcount or 0) != 1:
            raise ValueError("already_applied")
    if profile:
        logger.info(
            "authority ceiling bound to %s by mission profile %s for %s",
            cap,
            profile,
            decision_id,
        )
