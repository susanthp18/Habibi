"""The append-only decision log.

Written on every invocation — including the ones that chose silence, and
including shadow runs nothing acted on. Those are not noise. A log containing
only the contacts we made has no negative class in it: it cannot train
anything, and it cannot answer the question the rollout actually turns on,
which is *what would we have done, and what stopped us*.

The roadmap's exit criterion for this feature is two weeks of shadow logs with
a suppression breakdown before any live auto-act. This table is that
breakdown, and :func:`insights` is the report.

Nothing here fails loudly. A logging error must never cost a borrower their
decision, so every function swallows and logs. The price is that gaps are
possible; the alternative is dropping a treatment because an INSERT timed out.

Every function takes an optional ``conn``. The engine is called from inside
other people's transactions — bounce ingest holds ``FOR UPDATE`` on the account
row while it decides — and opening a second connection there would be a
deadlock waiting for load.
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Iterator, Mapping, Sequence

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _id() -> str:
    return f"TD-{uuid.uuid4().hex[:12].upper()}"


@contextlib.contextmanager
def _writer(conn: Any | None) -> Iterator[Any]:
    """Use the caller's transaction, or open one."""
    if conn is not None:
        yield conn
        return
    import db

    with db.engine.begin() as owned:
        yield owned


@contextlib.contextmanager
def _reader(conn: Any | None) -> Iterator[Any]:
    if conn is not None:
        yield conn
        return
    import db

    with db.engine.connect() as owned:
        yield owned


def record(
    *,
    conn: Any | None = None,
    tenant_id: str,
    customer_id: str,
    account_id: str | None,
    interaction_id: str | None,
    trigger_kind: str,
    trigger_ref: str | None,
    mode: str,
    variant: str | None,
    recommender: str,
    recommender_version: str,
    feature_schema_version: str,
    features: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    excluded: Mapping[str, str],
    chosen_action: str | None,
    chosen_channel: str | None,
    scheduled_at: datetime | None,
    expected_value: float | None,
    suppression_reason: str | None,
    rationale: str | None,
    latency_ms: int | None,
    propensity: float | None = None,
    explore_kind: str | None = None,
    policy_version: int | None = None,
) -> str | None:
    """Persist one decision. Returns its id, or None if logging failed."""
    decision_id = _id()
    try:
        with _writer(conn) as active:
            active.execute(
                text(
                    """
                    INSERT INTO treatment_decisions (
                      id, tenant_id, customer_id, account_id, interaction_id,
                      trigger_kind, trigger_ref, mode, variant,
                      recommender, recommender_version, feature_schema_version,
                      features, candidates, excluded,
                      chosen_action, chosen_channel, scheduled_at,
                      expected_value, propensity, explore_kind, policy_version,
                      suppression_reason, rationale,
                      latency_ms, created_at
                    ) VALUES (
                      :id, :tenant_id, :customer_id,
                      -- Resolved inside the INSERT: an account closed between
                      -- scoring and logging must null the column, not raise a
                      -- foreign-key error that loses the whole row.
                      (SELECT a.id FROM accounts a WHERE a.id = :account_id),
                      (SELECT i.id FROM interactions i WHERE i.id = :interaction_id),
                      :trigger_kind, :trigger_ref, :mode, :variant,
                      :recommender, :recommender_version, :feature_schema_version,
                      CAST(:features AS jsonb), CAST(:candidates AS jsonb),
                      CAST(:excluded AS jsonb),
                      :chosen_action, :chosen_channel, :scheduled_at,
                      :expected_value, :propensity, :explore_kind, :policy_version,
                      :suppression_reason, :rationale,
                      -- clock_timestamp(), not now(). This is an append-only
                      -- log, so created_at should say when the row was written;
                      -- now() is transaction start, and two decisions written
                      -- in one transaction would share a timestamp with no way
                      -- left to tell which came second.
                      :latency_ms, clock_timestamp()
                    )
                    """
                ),
                {
                    "id": decision_id,
                    "tenant_id": tenant_id,
                    "customer_id": customer_id,
                    "account_id": account_id,
                    "interaction_id": interaction_id,
                    "trigger_kind": trigger_kind,
                    "trigger_ref": trigger_ref,
                    "mode": mode,
                    "variant": variant,
                    "recommender": recommender,
                    "recommender_version": recommender_version,
                    "feature_schema_version": feature_schema_version,
                    "features": json.dumps(dict(features), default=str),
                    "candidates": json.dumps(list(candidates), default=str),
                    "excluded": json.dumps(dict(excluded), default=str),
                    "chosen_action": chosen_action,
                    "chosen_channel": chosen_channel,
                    "scheduled_at": scheduled_at,
                    "expected_value": expected_value,
                    # Clamped rather than trusted. The column's CHECK forbids
                    # zero because every off-policy estimator divides by this,
                    # and a caller that computes 0.0 through some future path
                    # would lose the whole decision row to an IntegrityError —
                    # a logging bug costing a borrower their decision is the
                    # one failure this module exists to prevent.
                    "propensity": (
                        None if propensity is None else max(1e-9, min(1.0, float(propensity)))
                    ),
                    "explore_kind": explore_kind,
                    "policy_version": policy_version,
                    "suppression_reason": suppression_reason,
                    "rationale": rationale,
                    "latency_ms": latency_ms,
                },
            )
        return decision_id
    except Exception:
        logger.exception("treatment decision log failed for customer=%s", customer_id)
        return None


def planned_actions(
    conn: Any,
    *,
    customer_id: str,
    trigger_kind: str,
    trigger_ref: str | None,
) -> frozenset[str]:
    """Every action already scheduled and unspent for this same trigger.

    The set rather than a yes/no about one action, and one query rather than
    one per candidate. The distinction matters once the engine can choose among
    several approved actions: the top-ranked one being already booked is no
    reason to withhold a *different* one, and asking the old per-action
    question would either suppress the whole decision or need a round trip per
    candidate.

    Never raises. A read that fails degrades to "nothing is planned", which
    risks a duplicate rather than a silence — and of the two failure modes,
    the one that still contacts the borrower is the one the caller can see.
    """
    try:
        clause = "trigger_ref = :ref" if trigger_ref else "trigger_ref IS NULL"
        with _reader(conn) as active:
            rows = active.execute(
                text(
                    f"""
                    SELECT DISTINCT chosen_action FROM treatment_decisions
                    WHERE customer_id = :cid
                      AND trigger_kind = :kind
                      AND {clause}
                      AND chosen_action IS NOT NULL
                      AND chosen_action <> 'wait'
                      AND suppression_reason IS NULL
                      AND enacted IS FALSE
                      -- A plan the executor claimed and deliberately did not
                      -- carry out (no executor, consent withdrawn, borrower
                      -- paid) is not "already planned" — it is a decision that
                      -- needs making again. Without this the first
                      -- cancellation freezes the borrower for 24 hours.
                      AND outcome IS NULL
                      AND created_at >= now() - interval '24 hours'
                    """
                ),
                {"cid": customer_id, "kind": trigger_kind, "ref": trigger_ref},
            ).scalars().all()
        return frozenset(str(r) for r in rows if r)
    except Exception:
        logger.exception("planned-action read failed for customer=%s", customer_id)
        return frozenset()


def already_planned(
    conn: Any,
    *,
    customer_id: str,
    trigger_kind: str,
    trigger_ref: str | None,
    action: str,
) -> bool:
    """Is an identical, unspent plan already on the books?

    Keyed on the trigger reference where there is one, because that is what
    makes a repeat genuinely a repeat. Without it a worker that ran twice would
    dial the same borrower twice about the same bounce, and the borrower would
    experience the retry as harassment rather than as diligence.
    """
    try:
        params: dict[str, Any] = {
            "cid": customer_id,
            "kind": trigger_kind,
            "action": action,
            "ref": trigger_ref,
        }
        clause = (
            "trigger_ref = :ref" if trigger_ref else "trigger_ref IS NULL"
        )
        row = conn.execute(
            text(
                f"""
                SELECT 1 FROM treatment_decisions
                WHERE customer_id = :cid
                  AND trigger_kind = :kind
                  AND {clause}
                  AND chosen_action = :action
                  AND suppression_reason IS NULL
                  AND enacted IS FALSE
                  -- A plan the executor claimed and deliberately did not carry
                  -- out (no executor, consent withdrawn, borrower paid) is not
                  -- "already planned" — it is a decision that needs making
                  -- again. Without this the first cancellation freezes the
                  -- borrower for 24 hours.
                  AND outcome IS NULL
                  AND created_at >= now() - interval '24 hours'
                LIMIT 1
                """
            ),
            params,
        ).fetchone()
        return row is not None
    except Exception:
        logger.exception("duplicate-plan check failed for %s", customer_id)
        # Fail closed: an unreadable log means assume a plan exists, which can
        # only under-contact.
        return True


def mark_enacted(
    decision_id: str | None,
    *,
    ref: str | None = None,
    conn: Any | None = None,
    enacted_by: str | None = None,
) -> None:
    """The plan was carried out. Distinct from having been chosen."""
    if not decision_id:
        return
    actor = enacted_by if enacted_by in {"treatment_executor", "clerk_agent", "human", "tuner"} else None
    try:
        with _writer(conn) as active:
            active.execute(
                text(
                    """
                    UPDATE treatment_decisions
                    SET enacted = true, enacted_at = now(), enacted_ref = :ref,
                        enacted_by = COALESCE(:by, enacted_by)
                    WHERE id = :id AND enacted IS FALSE
                    """
                ),
                {"id": decision_id, "ref": ref, "by": actor},
            )
    except Exception:
        logger.exception("mark_enacted failed for %s", decision_id)


OUTCOMES = frozenset(
    {
        "reached",
        "no_answer",
        "paid",
        "ptp",
        "refused",
        "undeliverable",
        "cancelled",
        "superseded",
    }
)


def record_outcome(
    decision_id: str | None, outcome: str, *, conn: Any | None = None
) -> None:
    """Label what happened. This is the training signal."""
    if not decision_id:
        return
    if outcome not in OUTCOMES:
        logger.warning("ignoring unknown treatment outcome %r", outcome)
        return
    try:
        with _writer(conn) as active:
            active.execute(
                text(
                    """
                    UPDATE treatment_decisions
                    SET outcome = :outcome, outcome_at = now()
                    WHERE id = :id AND outcome IS NULL
                    """
                ),
                {"id": decision_id, "outcome": outcome},
            )
    except Exception:
        logger.exception("record_outcome failed for %s", decision_id)


def claim_due(conn: Any, *, limit: int = 1) -> list[dict[str, Any]]:
    """Plans whose moment has arrived, locked for one worker.

    ``SKIP LOCKED`` so two workers drain in parallel without either waiting,
    and without both sending the same message.
    """
    rows = conn.execute(
        text(
            """
            SELECT * FROM treatment_decisions
            WHERE enacted IS FALSE
              -- Never a simulated row. The synthetic corpus writes decisions
              -- that look exactly like live ones because that is the point of
              -- it; the only thing standing between a generated borrower and a
              -- real outbound message is this predicate.
              AND mode <> 'simulated'
              AND suppression_reason IS NULL
              -- An outcome is the terminal marker for a plan that was claimed
              -- and deliberately not carried out (no executor, borrower paid,
              -- consent withdrawn). Without this the executor spins on it.
              AND outcome IS NULL
              AND chosen_action IS NOT NULL
              AND chosen_action <> 'wait'
              AND scheduled_at IS NOT NULL
              AND scheduled_at <= now()
              AND created_at >= now() - interval '7 days'
            ORDER BY scheduled_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT :limit
            """
        ),
        {"limit": max(1, limit)},
    ).mappings().all()
    return [dict(r) for r in rows]


def claim_by_id(conn: Any, decision_id: str) -> dict[str, Any] | None:
    """Lock one plan for the clerk. None if already enacted or claimed elsewhere."""
    row = conn.execute(
        text(
            """
            SELECT * FROM treatment_decisions
            WHERE id = :id
              AND enacted IS FALSE
              AND mode <> 'simulated'
              AND outcome IS NULL
            FOR UPDATE SKIP LOCKED
            """
        ),
        {"id": decision_id},
    ).mappings().first()
    return dict(row) if row else None


def insights(conn: Any, *, days: int = 14) -> dict[str, Any]:
    """The shadow-rollout scoreboard.

    Deliberately shaped around the decision a collections head has to make —
    "is this safe to switch on?" — rather than around what is easy to query.
    Coverage says whether it would do anything; the suppression breakdown says
    what is stopping it; the ladder mix says whether it is about to send vans.
    """
    window = f"{max(1, int(days))} days"
    totals = conn.execute(
        text(
            f"""
            SELECT
              count(*)::int AS decisions,
              -- "Would this have done something?" — the question the shadow
              -- fortnight is asked. Keyed on the action rather than on
              -- suppression_reason, because in shadow mode every actionable
              -- decision carries reason='shadow_mode' and counting those as
              -- suppressed would report zero coverage in exactly the mode this
              -- report exists to serve.
              count(*) FILTER (
                WHERE chosen_action IS NOT NULL AND chosen_action <> 'wait'
              )::int AS actionable,
              count(*) FILTER (WHERE enacted)::int AS enacted,
              count(DISTINCT customer_id)::int AS customers,
              COALESCE(sum(expected_value) FILTER (
                WHERE chosen_action IS NOT NULL AND chosen_action <> 'wait'
              ), 0) AS expected_value_inr,
              COALESCE(avg(latency_ms), 0)::int AS avg_latency_ms
            FROM treatment_decisions
            WHERE created_at >= now() - interval '{window}'
            """
        )
    ).mappings().first()
    suppression = conn.execute(
        text(
            f"""
            SELECT COALESCE(suppression_reason, 'none') AS reason, count(*)::int AS n
            FROM treatment_decisions
            WHERE created_at >= now() - interval '{window}'
            GROUP BY 1 ORDER BY 2 DESC
            """
        )
    ).mappings().all()
    by_action = conn.execute(
        text(
            f"""
            SELECT COALESCE(chosen_action, 'none') AS action, count(*)::int AS n,
                   COALESCE(avg(expected_value), 0)::numeric(14,2) AS avg_ev
            FROM treatment_decisions
            WHERE created_at >= now() - interval '{window}'
              AND chosen_action IS NOT NULL AND chosen_action <> 'wait'
            GROUP BY 1 ORDER BY 2 DESC
            """
        )
    ).mappings().all()
    by_mode = conn.execute(
        text(
            f"""
            SELECT mode, count(*)::int AS n FROM treatment_decisions
            WHERE created_at >= now() - interval '{window}'
            GROUP BY 1 ORDER BY 1
            """
        )
    ).mappings().all()
    outcomes = conn.execute(
        text(
            f"""
            SELECT outcome, count(*)::int AS n FROM treatment_decisions
            WHERE created_at >= now() - interval '{window}' AND outcome IS NOT NULL
            GROUP BY 1 ORDER BY 2 DESC
            """
        )
    ).mappings().all()

    t = dict(totals or {})
    decisions = int(t.get("decisions") or 0)
    actionable = int(t.get("actionable") or 0)
    return {
        "windowDays": int(days),
        "decisions": decisions,
        "actionable": actionable,
        "coverage": round(actionable / decisions, 4) if decisions else 0.0,
        "enacted": int(t.get("enacted") or 0),
        "customers": int(t.get("customers") or 0),
        "expectedValueInr": float(t.get("expected_value_inr") or 0),
        "avgLatencyMs": int(t.get("avg_latency_ms") or 0),
        "suppression": [{"reason": r["reason"], "count": r["n"]} for r in suppression],
        "byAction": [
            {"action": r["action"], "count": r["n"], "avgExpectedValue": float(r["avg_ev"])}
            for r in by_action
        ],
        "byMode": [{"mode": r["mode"], "count": r["n"]} for r in by_mode],
        "outcomes": [{"outcome": r["outcome"], "count": r["n"]} for r in outcomes],
    }
