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
    arm_propensity: float | None = None,
    action_propensity: float | None = None,
    replay_nonce: str | None = None,
    veto_stack_version: str | None = None,
    engine_image_digest: str | None = None,
    config_version: str | None = None,
    lambda_bucket: str | None = None,
    logging_contract_version: int | None = None,
    policy_binding: Any = None,
    policy_binding_hash: str | None = None,
    feature_snapshot_build_id: str | None = None,
    feature_snapshot_date: Any = None,
    features_known_ts: datetime | None = None,
) -> str | None:
    """Persist one decision. Returns its id, or None if logging failed."""
    decision_id = _id()
    try:
        from agent_core.treatment import partitions, schema_ready

        extra_cols = ""
        extra_vals = ""
        params: dict[str, Any] = {
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
            "propensity": (
                None if propensity is None else max(1e-9, min(1.0, float(propensity)))
            ),
            "explore_kind": explore_kind,
            "policy_version": policy_version,
            "suppression_reason": suppression_reason,
            "rationale": rationale,
            "latency_ms": latency_ms,
        }
        with _writer(conn) as active:
            if schema_ready.w2_ready(active):
                extra_cols = (
                    ", arm_propensity, action_propensity, replay_nonce, "
                    "veto_stack_version, engine_image_digest, config_version, "
                    "lambda_bucket, logging_contract_version"
                )
                extra_vals = (
                    ", :arm_propensity, :action_propensity, :replay_nonce, "
                    ":veto_stack_version, :engine_image_digest, :config_version, "
                    ":lambda_bucket, :logging_contract_version"
                )
                params.update(
                    {
                        "arm_propensity": arm_propensity,
                        "action_propensity": action_propensity,
                        "replay_nonce": replay_nonce,
                        "veto_stack_version": veto_stack_version,
                        "engine_image_digest": engine_image_digest,
                        "config_version": config_version,
                        "lambda_bucket": lambda_bucket or "none",
                        "logging_contract_version": logging_contract_version or 2,
                    }
                )
            if schema_ready.has_column(active, "treatment_decisions", "policy_binding"):
                extra_cols += ", policy_binding, policy_binding_hash"
                extra_vals += ", CAST(:policy_binding AS jsonb), :policy_binding_hash"
                params["policy_binding"] = json.dumps(list(policy_binding or []), default=str)
                params["policy_binding_hash"] = policy_binding_hash
            if schema_ready.w6_ready(active):
                extra_cols += (
                    ", feature_snapshot_build_id, feature_snapshot_date, "
                    "features_known_ts"
                )
                extra_vals += (
                    ", :feature_snapshot_build_id, :feature_snapshot_date, "
                    ":features_known_ts"
                )
                params["feature_snapshot_build_id"] = feature_snapshot_build_id
                params["feature_snapshot_date"] = feature_snapshot_date
                params["features_known_ts"] = features_known_ts
            active.execute(
                text(
                    f"""
                    INSERT INTO treatment_decisions (
                      id, tenant_id, customer_id, account_id, interaction_id,
                      trigger_kind, trigger_ref, mode, variant,
                      recommender, recommender_version, feature_schema_version,
                      features, candidates, excluded,
                      chosen_action, chosen_channel, scheduled_at,
                      expected_value, propensity, explore_kind, policy_version,
                      suppression_reason, rationale,
                      latency_ms, created_at
                      {extra_cols}
                    ) VALUES (
                      :id, :tenant_id, :customer_id,
                      (SELECT a.id FROM accounts a WHERE a.id = :account_id),
                      (SELECT i.id FROM interactions i WHERE i.id = :interaction_id),
                      :trigger_kind, :trigger_ref, :mode, :variant,
                      :recommender, :recommender_version, :feature_schema_version,
                      CAST(:features AS jsonb), CAST(:candidates AS jsonb),
                      CAST(:excluded AS jsonb),
                      :chosen_action, :chosen_channel, :scheduled_at,
                      :expected_value, :propensity, :explore_kind, :policy_version,
                      :suppression_reason, :rationale,
                      :latency_ms, clock_timestamp()
                      {extra_vals}
                    )
                    """
                ),
                params,
            )
            partitions.maybe_dual_write(
                active,
                decision_id=decision_id,
                features=params["features"],
                candidates=params["candidates"],
                excluded=params["excluded"],
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


#: Mirrors the CHECK on ``treatment_decisions.outcome``. A value this set does
#: not know is dropped with a warning rather than sent to Postgres, so a typo
#: costs one label instead of aborting whatever transaction the engine was lent.
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
        # We deliberately withheld treatment and the borrower did not pay
        # inside the observation window. The counterfactual's negative class,
        # and the only kind of row that can measure self-cure.
        "unresolved",
    }
)


def record_outcome(
    decision_id: str | None,
    outcome: str,
    *,
    conn: Any | None = None,
    cancel_reason: str | None = None,
    reach_outcome: str | None = None,
    cure_outcome: str | None = None,
    observed_days: int | None = None,
    event_at: datetime | None = None,
    label_mature_at: datetime | None = None,
    label_definition_version: str | None = None,
) -> None:
    """Label what happened. This is the training signal."""
    if not decision_id:
        return
    if outcome not in OUTCOMES:
        logger.warning("ignoring unknown treatment outcome %r", outcome)
        return
    try:
        from agent_core.treatment import cancel as cancel_mod, schema_ready

        with _writer(conn) as active:
            extra = ""
            params: dict[str, Any] = {"id": decision_id, "outcome": outcome}
            if cancel_reason and schema_ready.has_column(active, "treatment_decisions", "cancel_reason"):
                if cancel_reason not in cancel_mod.REASONS:
                    cancel_reason = cancel_mod.from_note(cancel_reason)
                extra += ", cancel_reason = :cancel_reason"
                params["cancel_reason"] = cancel_reason
            if schema_ready.labels_ready(active):
                if reach_outcome is not None:
                    extra += ", reach_outcome = :reach_outcome"
                    params["reach_outcome"] = reach_outcome
                if cure_outcome is not None:
                    extra += ", cure_outcome = :cure_outcome"
                    params["cure_outcome"] = cure_outcome
                if observed_days is not None:
                    extra += ", observed_days = :observed_days"
                    params["observed_days"] = observed_days
                if event_at is not None:
                    extra += ", event_at = :event_at"
                    params["event_at"] = event_at
                if label_mature_at is not None:
                    extra += ", label_mature_at = :label_mature_at"
                    params["label_mature_at"] = label_mature_at
                if label_definition_version is not None:
                    extra += ", label_definition_version = :label_def"
                    params["label_def"] = label_definition_version
            active.execute(
                text(
                    f"""
                    UPDATE treatment_decisions
                    SET outcome = :outcome, outcome_at = now()
                    {extra}
                    WHERE id = :id AND outcome IS NULL
                    """
                ),
                params,
            )
    except Exception:
        logger.exception("record_outcome failed for %s", decision_id)


def claim_due(conn: Any, *, limit: int = 1, owner: str | None = None) -> list[dict[str, Any]]:
    """Plans whose moment has arrived, locked for one worker.

    ``FOR NO KEY UPDATE SKIP LOCKED`` so two workers drain in parallel without
    either waiting, and without taking a lock that blocks the FK insert the
    voice path needs on ``call_attempts``.
    """
    from agent_core.treatment import schema_ready

    lease_sql = ""
    if schema_ready.has_column(conn, "treatment_decisions", "lease_until"):
        lease_sql = """
              AND (lease_until IS NULL OR lease_until < now())
              AND claimed_at IS NULL
        """
    rows = conn.execute(
        text(
            f"""
            SELECT * FROM treatment_decisions
            WHERE enacted IS FALSE
              AND mode <> 'simulated'
              AND suppression_reason IS NULL
              AND outcome IS NULL
              AND chosen_action IS NOT NULL
              AND chosen_action <> 'wait'
              AND scheduled_at IS NOT NULL
              AND scheduled_at <= now()
              AND created_at >= now() - interval '7 days'
              {lease_sql}
            ORDER BY scheduled_at ASC
            FOR NO KEY UPDATE SKIP LOCKED
            LIMIT :limit
            """
        ),
        {"limit": max(1, limit)},
    ).mappings().all()
    claimed = [dict(r) for r in rows]
    if claimed and schema_ready.has_column(conn, "treatment_decisions", "lease_until"):
        ids = [r["id"] for r in claimed]
        conn.execute(
            text(
                """
                UPDATE treatment_decisions
                SET claimed_at = now(),
                    lease_until = now() + interval '2 minutes',
                    lease_owner = :owner
                WHERE id = ANY(:ids)
                """
            ),
            {"ids": ids, "owner": owner or "treatment_executor"},
        )
    return claimed


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
            FOR NO KEY UPDATE SKIP LOCKED
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
