"""The append-only decision log.

Written on every invocation — including the ones that recommended nothing, and
including shadow runs that were never spoken. Those are not noise: a log that
only contains offers we actually made has no negative class in it and cannot
train anything, and it cannot answer "why did the engine go quiet on Tuesday?".

Nothing here is allowed to fail loudly. A logging error must never cost a
customer their offer, so every function swallows and logs. The cost of that
choice is that gaps in the log are possible; the alternative is dropping a
call because an INSERT timed out.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Mapping, Sequence

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _id() -> str:
    return f"OD-{uuid.uuid4().hex[:12].upper()}"


def record(
    *,
    conn: Any,
    customer_id: str,
    interaction_id: str | None,
    channel: str,
    mode: str,
    variant: str | None,
    recommender: str,
    recommender_version: str,
    feature_schema_version: str,
    features: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    excluded: Mapping[str, str],
    chosen_product_id: str | None,
    suggested_amount: float | None,
    score: float | None,
    suppression_reason: str | None,
    latency_ms: int | None,
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
) -> str | None:
    """Persist one decision. Returns the id, or None if logging failed."""
    import db

    decision_id = _id()
    try:
        extra_cols = ""
        extra_vals = ""
        params = {
            "id": decision_id,
            "tenant": db.current_tenant(),
            "customer_id": customer_id,
            "interaction_id": interaction_id,
            "channel": channel,
            "mode": mode,
            "variant": variant,
            "recommender": recommender,
            "recommender_version": recommender_version,
            "feature_schema_version": feature_schema_version,
            "features": json.dumps(features, default=str),
            "candidates": json.dumps(list(candidates), default=str),
            "excluded": json.dumps(dict(excluded), default=str),
            "chosen_product_id": chosen_product_id,
            "suggested_amount": suggested_amount,
            "score": score,
            "suppression_reason": suppression_reason,
            "latency_ms": latency_ms,
        }
        has_w2 = conn.execute(
            text(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'offer_decisions' AND column_name = 'arm_propensity'
                """
            )
        ).first()
        if has_w2:
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
                    "arm_propensity": arm_propensity if arm_propensity is not None else 1.0,
                    "action_propensity": action_propensity if action_propensity is not None else 1.0,
                    "replay_nonce": replay_nonce,
                    "veto_stack_version": veto_stack_version,
                    "engine_image_digest": engine_image_digest,
                    "config_version": config_version,
                    "lambda_bucket": lambda_bucket or "none",
                    "logging_contract_version": logging_contract_version or 2,
                }
            )
            if conn.execute(
                text(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'offer_decisions'
                      AND column_name = 'policy_binding'
                    """
                )
            ).first():
                extra_cols += ", policy_binding, policy_binding_hash"
                extra_vals += ", CAST(:policy_binding AS jsonb), :policy_binding_hash"
                params["policy_binding"] = json.dumps(list(policy_binding or []), default=str)
                params["policy_binding_hash"] = policy_binding_hash
        conn.execute(
            text(
                f"""
                INSERT INTO offer_decisions (
                  id, tenant_id, customer_id, interaction_id, channel, mode,
                  variant, recommender, recommender_version,
                  feature_schema_version,
                  features, candidates, excluded,
                  chosen_product_id, suggested_amount, score,
                  suppression_reason, latency_ms, created_at
                  {extra_cols}
                ) VALUES (
                  :id, :tenant, :customer_id, :interaction_id, :channel, :mode,
                  :variant, :recommender, :recommender_version,
                  :feature_schema_version,
                  CAST(:features AS jsonb), CAST(:candidates AS jsonb),
                  CAST(:excluded AS jsonb),
                  (SELECT p.id FROM products p WHERE p.id = :chosen_product_id),
                  :suggested_amount, :score,
                  :suppression_reason, :latency_ms, now()
                  {extra_vals}
                )
                """
            ),
            params,
        )
        _mirror(conn, params)
        return decision_id
    except Exception:
        logger.exception("offer decision log failed for customer=%s", customer_id)
        return None


#: What an offer decision is triggered by, in the treatment log's vocabulary.
#: The offer is scored during a servicing contact the borrower is already on,
#: which is what ``inbound`` means there. Not a new trigger value: the CHECK on
#: ``treatment_decisions.trigger_kind`` is a closed list precisely so that the
#: two engines cannot invent parallel vocabularies for the same event, and §15.4
#: absorbs the offer family at the infrastructure layer rather than beside it.
MIRROR_TRIGGER = "inbound"

#: §9.7. Not a channel a message goes out on -- a state meaning "scored during a
#: servicing contact, held for the promotional series". The offer is scored on
#: the call and it is never spoken on it.
DEFERRED_PROMOTIONAL = "deferred_promotional"


def _mirror(conn: Any, params: Mapping[str, Any]) -> None:
    """Write the same decision into ``treatment_decisions`` as ``action_family='offer'``.

    The dual write, and it is deliberately a *window* rather than a cutover.
    §15.4 absorbs the offer family into one log, one propensity contract, one
    registry and one OPE panel; but `offer_decisions` still has a dozen readers,
    and moving the write and every reader in one commit is how a reader gets
    missed silently. So both tables are written until the last reader moves, and
    `tests/test_honest_engines_exit_criteria.py` ratchets the reference count
    downward so "until" cannot quietly become "forever".

    Swallows, on the same rule as the rest of this module: a logging failure
    must never cost a customer their offer. It logs at ``exception`` because a
    mirror that silently stops is how the two tables come to disagree, which is
    the state the absorption exists to end.
    """
    from agent_core.treatment import schema_ready

    if not schema_ready.w12_ready(conn):
        # Every deployment is in this state until 0121 is applied. Not a
        # degradation to report per decision -- `offer_decisions` is still the
        # complete log, and w12_ready is cached.
        return
    product = params.get("chosen_product_id")
    try:
        # W0's lent-connection rule, and this is exactly the case it exists for:
        # `conn` belongs to the caller, the primary INSERT has already succeeded
        # on it, and a failed mirror without a savepoint would abort the whole
        # transaction -- losing the offer log entry this function was called to
        # duplicate, on a database where nothing was wrong with it.
        with conn.begin_nested():
            conn.execute(
                text(
                    """
                    INSERT INTO treatment_decisions (
                      id, tenant_id, customer_id, interaction_id, trigger_kind,
                      trigger_ref, mode, variant, recommender, recommender_version,
                      feature_schema_version, features, candidates, excluded,
                      action_family, chosen_action, chosen_channel, product_id,
                      suggested_amount, propensity, arm_propensity, action_propensity,
                      replay_nonce, veto_stack_version, engine_image_digest,
                      config_version, lambda_bucket, logging_contract_version,
                      suppression_reason, latency_ms, created_at
                    ) VALUES (
                      :id, :tenant, :customer_id, :interaction_id, :trigger_kind,
                      :interaction_id, :mode, :variant, :recommender,
                      :recommender_version,
                      :feature_schema_version, CAST(:features AS jsonb),
                      CAST(:candidates AS jsonb), CAST(:excluded AS jsonb),
                      'offer', :chosen_action, :chosen_channel,
                      (SELECT p.id FROM products p WHERE p.id = :chosen_product_id),
                      :suggested_amount, :propensity, :arm_propensity,
                      :action_propensity,
                      :replay_nonce, :veto_stack_version, :engine_image_digest,
                      :config_version, :lambda_bucket, :logging_contract_version,
                      :suppression_reason, :latency_ms, now()
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    **params,
                    "trigger_kind": MIRROR_TRIGGER,
                    # A suppressed offer is a `wait` carrying a logged propensity,
                    # exactly as it is on the treatment side -- W11a's repair to
                    # `ope.py` was that dropping those scores every policy against
                    # the population the engine had already decided to act on.
                    "chosen_action": "offer" if product else "wait",
                    "chosen_channel": DEFERRED_PROMOTIONAL if product else None,
                    # `treatment_decisions.propensity` is the fused figure every
                    # pre-W2 estimator reads; the two halves sit beside it.
                    "propensity": params.get("action_propensity") or 1.0,
                    "arm_propensity": params.get("arm_propensity") or 1.0,
                    "action_propensity": params.get("action_propensity") or 1.0,
                    "replay_nonce": params.get("replay_nonce"),
                    "veto_stack_version": params.get("veto_stack_version"),
                    "engine_image_digest": params.get("engine_image_digest"),
                    "config_version": params.get("config_version"),
                    "lambda_bucket": params.get("lambda_bucket") or "none",
                    "logging_contract_version": params.get("logging_contract_version") or 2,
                },
            )
    except Exception:
        logger.exception("offer decision mirror failed for %s", params.get("id"))


def mirror_update(conn: Any, assignments: str, params: Mapping[str, Any]) -> None:
    """Apply the same UPDATE to the mirrored row. See :func:`_mirror`.

    Scoped to ``action_family = 'offer'`` rather than to the id alone. The two
    logs share their ids by construction, but a predicate that would still match
    if they ever stopped is a predicate that would one day set an offer response
    on a collections decision.
    """
    from agent_core.treatment import schema_ready

    if not schema_ready.w12_ready(conn):
        return
    try:
        with conn.begin_nested():
            conn.execute(
                text(
                    f"UPDATE treatment_decisions SET {assignments}"
                    " WHERE id = :id AND action_family = 'offer'"
                ),
                params,
            )
    except Exception:
        logger.exception("offer decision mirror update failed for %s", params.get("id"))


def mark_presented(decision_id: str | None) -> None:
    """The offer was actually spoken. Distinct from having been chosen."""
    if not decision_id:
        return
    import db

    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE offer_decisions SET presented = true, presented_at = now()"
                    " WHERE id = :id AND presented IS FALSE"
                ),
                {"id": decision_id},
            )
            mirror_update(
                conn,
                "presented = true, presented_at = now()",
                {"id": decision_id},
            )
    except Exception:
        logger.exception("mark_presented failed for %s", decision_id)


#: The four things a borrower can do with an offer. `not_reached` is CENSORING
#: rather than refusal (§11.5): the offer never arrived, so nobody declined it,
#: and an estimator that scores the two the same is measuring delivery and
#: calling it demand.
RESPONSES = ("interested", "declined", "deferred", "not_reached")


def record_response(decision_id: str | None, response: str) -> bool:
    """Label the outcome. Returns whether this call is the one that wrote it.

    ``False`` when the decision already carried a response -- the predicate is
    ``response IS NULL`` and the first answer stands. A label that can be
    overwritten is a label somebody can tune, and this one is the training
    target for the whole offer family.
    """
    if not decision_id:
        return False
    if response not in RESPONSES:
        logger.warning("ignoring unknown offer response %r", response)
        return False
    import db

    written = False
    try:
        with db.engine.begin() as conn:
            written = bool(
                conn.execute(
                    text(
                        "UPDATE offer_decisions SET response = :response,"
                        " responded_at = now()"
                        " WHERE id = :id AND response IS NULL"
                    ),
                    {"id": decision_id, "response": response},
                ).rowcount
            )
            mirror_update(
                conn,
                "offer_response = :response, responded_at = now()",
                {"id": decision_id, "response": response},
            )
    except Exception:
        logger.exception("record_response failed for %s", decision_id)
    return written


def attach_lead(decision_id: str | None, *, lead_id: str, response: str = "interested") -> None:
    """Join the decision to the lead it produced — the training label."""
    if not decision_id:
        return
    import db

    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE offer_decisions
                    SET lead_id = :lead_id,
                        response = COALESCE(response, :response),
                        responded_at = COALESCE(responded_at, now()),
                        presented = true,
                        presented_at = COALESCE(presented_at, now())
                    WHERE id = :id
                    """
                ),
                {"id": decision_id, "lead_id": lead_id, "response": response},
            )
            mirror_update(
                conn,
                "lead_id = :lead_id,"
                " offer_response = COALESCE(offer_response, :response),"
                " responded_at = COALESCE(responded_at, now()),"
                " presented = true,"
                " presented_at = COALESCE(presented_at, now())",
                {"id": decision_id, "lead_id": lead_id, "response": response},
            )
    except Exception:
        logger.exception("attach_lead failed for %s", decision_id)
