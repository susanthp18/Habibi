"""Treatment holds, cases, and the treatment/authority read surfaces.

Peeled from ``db.py`` (WP-036 peel 2). Call sites stay ``db.*`` via a
bottom-of-file re-export. Reach the engine through :func:`_db`, never
``from db_core import engine``: the ``db_tx`` fixture wraps ``db.engine``,
and a name bound from ``db_core`` bypasses that proxy.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _db():
    """The ``db`` module object, resolved at call time.

    Carved modules must use ``_db().engine``, never ``from db_core import
    engine``. See ``db_core._db``.
    """
    import db as d

    return d


# Treatment holds (P3)
#
# The veto that had no home. Hardship, an open dispute, a regulatory complaint,
# bereavement and a matter with legal all mean "stop dunning this borrower",
# and all five used to live as prose in the policy corpus or as a routing rule
# that fired only when a human was already on the call. As rows they bind the
# bot at 02:00 exactly as they bind a supervisor.
# ---------------------------------------------------------------------------

HOLD_KINDS = (
    "hardship",
    "dispute",
    "complaint",
    "bereavement",
    "legal",
    "cease_and_desist",
    "deceased",
)
HOLD_SOURCES = ("manual", "bot", "system", "regulator", "feedback", "consent_event")
TWO_PERSON_RELEASE = frozenset({"legal", "cease_and_desist", "deceased", "bereavement"})


def list_treatment_holds(
    *,
    customer_id: str | None = None,
    active_only: bool = True,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    """Holds visible to the caller. Tenant- and object-scoped like any queue."""
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _sql = _mod._sql
    _tenant = _mod._tenant
    _vis_params = _mod._vis_params
    clamp_list_limit = _mod.clamp_list_limit
    clamp_offset = _mod.clamp_offset
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    where = ["c.tenant_id = :tenant_id"]
    params: dict[str, Any] = {
        "tenant_id": _tenant(),
        "limit": page,
        "offset": skip,
        **_vis_params(),
    }
    if customer_id:
        where.append("h.customer_id = :customer_id")
        params["customer_id"] = customer_id
    if active_only:
        where.append(
            "h.released_at IS NULL AND h.starts_at <= now()"
            " AND (h.expires_at IS NULL OR h.expires_at > now())"
        )
    clause = " AND ".join(where)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
                    f"""
                    SELECT h.id, h.customer_id, c.name AS customer_name, h.account_id,
                           h.kind, h.reason, h.source, h.interaction_id,
                           h.sla_due_at, h.starts_at, h.expires_at,
                           h.released_at, h.released_reason, h.created_at,
                           p.name AS placed_by, s.name AS specialist
                    FROM treatment_holds h
                    JOIN customers c ON c.id = h.customer_id
                     /*VISIBILITY*/
                    LEFT JOIN users p ON p.id = h.placed_by_user_id
                    LEFT JOIN users s ON s.id = h.specialist_user_id
                    WHERE {clause}
                    ORDER BY h.starts_at DESC, h.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
        )
    return [
        {
            "id": r["id"],
            "customerId": r["customer_id"],
            "customerName": r["customer_name"],
            "accountId": r["account_id"],
            "kind": r["kind"],
            "reason": r["reason"],
            "source": r["source"],
            "interactionId": r["interaction_id"],
            "slaDueAt": r["sla_due_at"],
            "startsAt": r["starts_at"],
            "expiresAt": r["expires_at"],
            "releasedAt": r["released_at"],
            "releasedReason": r["released_reason"],
            "placedBy": r["placed_by"],
            "specialist": r["specialist"],
            "active": r["released_at"] is None,
            "createdAt": r["created_at"],
        }
        for r in rows
    ]


def create_treatment_hold(payload: dict[str, Any]) -> dict[str, Any]:
    """Place a hold. Re-placing an active one is a no-op, not an error.

    Idempotent by design rather than by an idempotency key: a bot that hears
    "I lost my job" twice in one call, and an agent who clicks twice, must both
    end with one hold. The partial unique index is what enforces it; this
    surfaces the existing row instead of a 409 so the caller's flow continues.
    """
    _mod = _db()
    engine = _mod.engine
    _actor_user_id = _mod._actor_user_id
    _assert_tenant_owns = _mod._assert_tenant_owns
    _assert_tenant_owns_customer = _mod._assert_tenant_owns_customer
    _id = _mod._id
    _one = _mod._one
    _tenant = _mod._tenant
    record_activity = _mod.record_activity
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in HOLD_KINDS:
        raise ValueError(f"invalid_kind: {kind}")
    source = str(payload.get("source") or "manual").strip().lower()
    if source not in HOLD_SOURCES:
        raise ValueError(f"invalid_source: {source}")
    customer_id = payload.get("customerId")

    with engine.begin() as conn:
        _assert_tenant_owns_customer(conn, customer_id)
        account_id = payload.get("accountId")
        if account_id:
            _assert_tenant_owns(conn, "accounts", account_id)
        existing = _one(
            conn.execute(
                text(
                    """
                    SELECT id FROM treatment_holds
                    WHERE customer_id = :cid
                      AND COALESCE(account_id, '') = COALESCE(:aid, '')
                      AND kind = :kind
                      AND released_at IS NULL
                    """
                ),
                {"cid": customer_id, "aid": account_id, "kind": kind},
            )
        )
        if existing:
            return _treatment_hold(conn, existing["id"])

        hold_id = _id("THD")
        conn.execute(
            text(
                """
                INSERT INTO treatment_holds (
                  id, tenant_id, customer_id, account_id, kind, reason, source,
                  interaction_id, placed_by_user_id, specialist_user_id,
                  sla_due_at, expires_at
                ) VALUES (
                  :id, :tenant_id, :customer_id, :account_id, :kind, :reason, :source,
                  :interaction_id, :placed_by, :specialist, :sla_due_at, :expires_at
                )
                """
            ),
            {
                "id": hold_id,
                "tenant_id": _tenant(),
                "customer_id": customer_id,
                "account_id": account_id,
                "kind": kind,
                "reason": payload.get("reason"),
                "source": source,
                "interaction_id": payload.get("interactionId"),
                "placed_by": _actor_user_id(),
                "specialist": payload.get("specialistUserId"),
                "sla_due_at": payload.get("slaDueAt"),
                "expires_at": payload.get("expiresAt"),
            },
        )
        record_activity(
            conn,
            "customer",
            str(customer_id),
            "hold_placed",
            f"{kind.capitalize()} hold placed",
            payload.get("reason"),
            str(customer_id),
        )
        return _treatment_hold(conn, hold_id)


def release_treatment_hold(
    hold_id: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Lift a hold. Two-person release for the acts §13.4 requires."""
    _mod = _db()
    engine = _mod.engine
    _actor_user_id = _mod._actor_user_id
    _assert_tenant_owns = _mod._assert_tenant_owns
    record_activity = _mod.record_activity
    body = payload or {}
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "treatment_holds", hold_id)
        row = _treatment_hold(conn, hold_id)
        actor = _actor_user_id()
        kind = str(row.get("kind") or "")
        if kind in TWO_PERSON_RELEASE:
            placed = conn.execute(
                text("SELECT placed_by_user_id FROM treatment_holds WHERE id = :id"),
                {"id": hold_id},
            ).scalar()
            if not actor or (placed and actor == placed):
                raise ValueError("two_person_release_required")
            extra = ""
            from agent_core.treatment import schema_ready

            if schema_ready.has_column(conn, "treatment_holds", "release_approver_user_id"):
                extra = ", release_approver_user_id = :actor"
            conn.execute(
                text(
                    f"""
                    UPDATE treatment_holds
                    SET released_at = now(),
                        released_by_user_id = :actor,
                        released_reason = :reason
                        {extra}
                    WHERE id = :id AND released_at IS NULL
                    """
                ),
                {"id": hold_id, "actor": actor, "reason": body.get("reason")},
            )
        else:
            conn.execute(
                text(
                    """
                    UPDATE treatment_holds
                    SET released_at = now(),
                        released_by_user_id = :actor,
                        released_reason = :reason
                    WHERE id = :id AND released_at IS NULL
                    """
                ),
                {"id": hold_id, "actor": actor, "reason": body.get("reason")},
            )
        row = _treatment_hold(conn, hold_id)
        record_activity(
            conn,
            "customer",
            str(row["customerId"]),
            "hold_released",
            f"{str(row['kind']).capitalize()} hold released",
            body.get("reason"),
            str(row["customerId"]),
        )
        return row


def _treatment_hold(conn: Any, hold_id: str) -> dict[str, Any]:
    _mod = _db()
    _one = _mod._one
    row = _one(
        conn.execute(
            text(
                """
                SELECT h.id, h.customer_id, h.account_id, h.kind, h.reason, h.source,
                       h.interaction_id, h.sla_due_at, h.starts_at, h.expires_at,
                       h.released_at, h.released_reason, h.created_at
                FROM treatment_holds h WHERE h.id = :id
                """
            ),
            {"id": hold_id},
        )
    )
    if row is None:
        raise KeyError("treatment_holds_not_found")
    return {
        "id": row["id"],
        "customerId": row["customer_id"],
        "accountId": row["account_id"],
        "kind": row["kind"],
        "reason": row["reason"],
        "source": row["source"],
        "interactionId": row["interaction_id"],
        "slaDueAt": row["sla_due_at"],
        "startsAt": row["starts_at"],
        "expiresAt": row["expires_at"],
        "releasedAt": row["released_at"],
        "releasedReason": row["released_reason"],
        "active": row["released_at"] is None,
        "createdAt": row["created_at"],
    }


def next_treatment(
    *,
    customer_id: str,
    account_id: str | None = None,
    trigger: str = "manual",
) -> dict[str, Any]:
    """What the treatment engine would do for this borrower, right now.

    Read-only. Preview persistence writes zero decision rows; event and sweep
    callers remain the only producers of enactable plans.
    """
    _mod = _db()
    engine = _mod.engine
    _assert_tenant_owns = _mod._assert_tenant_owns
    _assert_tenant_owns_customer = _mod._assert_tenant_owns_customer
    from agent_core.treatment import Trigger, recommend_treatment

    with engine.begin() as conn:
        _assert_tenant_owns_customer(conn, customer_id)
        if account_id:
            _assert_tenant_owns(conn, "accounts", account_id)
        result = recommend_treatment(
            customer_id=customer_id,
            account_id=account_id,
            trigger=Trigger(kind=trigger),
            conn=conn,
            persist="preview",
        )
    payload = result.to_payload()

    # The Action Contract, for whoever is going to execute this. Until now it
    # existed and nothing served it, which made it an interface with no other
    # side -- a voice runner, a WhatsApp job or a field dispatcher had no way to
    # receive the authorisation the design note says it must be handed.
    #
    # Built with a connection so the authority matrix can price a fee waiver
    # once, here, rather than leaving a bot to query it mid-call under latency.
    # Absent for a suppressed or `wait` decision rather than present-and-empty:
    # a contract is an authorisation to act, and an empty one invites a channel
    # to decide for itself what that means.
    try:
        with engine.connect() as conn:
            contract = result.action_contract(conn=conn)
    except Exception:
        logger.exception("action contract build failed for %s", result.decision_id)
        contract = result.action_contract()
    if contract is not None:
        payload["contract"] = contract
    return payload


def list_treatment_cases(
    *,
    customer_id: str | None = None,
    open_only: bool = True,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    """The ladder, one row per case, with every rung it has walked.

    A case is ``(customer, trigger kind, trigger ref)`` — one bounce, one broken
    promise. The single-decision view answers "what did the engine say?"; this
    answers the question a floor lead actually has, which is "what has already
    been tried on this account and what is left".
    """
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _sql = _mod._sql
    _tenant = _mod._tenant
    _vis_params = _mod._vis_params
    clamp_list_limit = _mod.clamp_list_limit
    clamp_offset = _mod.clamp_offset
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    where = ["c.tenant_id = :tenant_id", "td.trigger_ref IS NOT NULL"]
    params: dict[str, Any] = {
        "tenant_id": _tenant(),
        "limit": page,
        "offset": skip,
        **_vis_params(),
    }
    if customer_id:
        where.append("td.customer_id = :customer_id")
        params["customer_id"] = customer_id
    if open_only:
        where.append(
            "NOT EXISTS (SELECT 1 FROM treatment_decisions r"
            " WHERE r.customer_id = td.customer_id AND r.trigger_kind = td.trigger_kind"
            "   AND r.trigger_ref = td.trigger_ref AND r.outcome IN ('paid','ptp'))"
        )
    clause = " AND ".join(where)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
                    f"""
                    SELECT td.customer_id, c.name AS customer_name, td.account_id,
                           td.trigger_kind, td.trigger_ref,
                           count(*)::int AS decisions,
                           count(*) FILTER (WHERE td.enacted)::int AS attempts,
                           max(td.created_at) AS last_decided_at,
                           max(td.enacted_at) AS last_attempt_at,
                           (array_agg(td.chosen_action ORDER BY td.created_at DESC))[1]
                             AS last_action,
                           (array_agg(td.outcome ORDER BY td.created_at DESC))[1]
                             AS last_outcome,
                           (array_agg(td.suppression_reason ORDER BY td.created_at DESC))[1]
                             AS last_suppression,
                           (array_agg(td.rationale ORDER BY td.created_at DESC))[1]
                             AS last_rationale,
                           array_remove(
                             array_agg(td.chosen_action ORDER BY td.created_at)
                               FILTER (WHERE td.enacted), NULL
                           ) AS ladder
                    FROM treatment_decisions td
                    JOIN customers c ON c.id = td.customer_id
                     /*VISIBILITY*/
                    WHERE {clause}
                    GROUP BY td.customer_id, c.name, td.account_id,
                             td.trigger_kind, td.trigger_ref
                    ORDER BY max(td.created_at) DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
        )
    return [
        {
            "id": f"{r['trigger_kind']}:{r['trigger_ref']}",
            "customerId": r["customer_id"],
            "customerName": r["customer_name"],
            "accountId": r["account_id"],
            "trigger": r["trigger_kind"],
            "triggerRef": r["trigger_ref"],
            "decisions": r["decisions"],
            "attempts": r["attempts"],
            "ladder": list(r["ladder"] or []),
            "lastAction": r["last_action"],
            "lastOutcome": r["last_outcome"],
            "lastSuppression": r["last_suppression"],
            "rationale": r["last_rationale"],
            "lastDecidedAt": r["last_decided_at"],
            "lastAttemptAt": r["last_attempt_at"],
        }
        for r in rows
    ]


def treatment_insights(days: int = 14) -> dict[str, Any]:
    """The shadow-rollout scoreboard behind ``GET /treatment/insights``."""
    _mod = _db()
    engine = _mod.engine
    from agent_core.treatment import decisions as treatment_decisions

    with engine.connect() as conn:
        return treatment_decisions.insights(conn, days=days)


def treatment_metrics(days: int = 28, *, include_simulated: bool = False) -> dict[str, Any]:
    """The design note's S17 scoreboard: causal, efficiency, model health,
    compliance, borrower experience, capacity.

    Distinct from ``treatment_insights``, which answers "is this safe to switch
    on?". This answers "is it working, and what is it costing?" -- and its
    headline is incremental recovery per rupee against the control arm, never a
    collections rate. A response model looks excellent on collections rate
    precisely because it targets borrowers who would have paid anyway.
    """
    _mod = _db()
    engine = _mod.engine
    from agent_core.treatment import metrics as treatment_metrics_mod

    with engine.connect() as conn:
        return treatment_metrics_mod.report(
            conn, days=days, include_simulated=include_simulated
        )


def treatment_model_health(days: int = 14, *, include_simulated: bool = False) -> dict[str, Any]:
    """Drift and calibration only -- the S15 half, without the rest of S17."""
    _mod = _db()
    engine = _mod.engine
    from agent_core.treatment import monitor

    with engine.connect() as conn:
        return monitor.report(conn, days=days, include_simulated=include_simulated)


def treatment_models(target: str | None = None, limit: int = 50) -> dict[str, Any]:
    """The champion/challenger ledger, plus whether it matches what is serving.

    ``verify`` is the part worth reading first. A registry that only records
    promotions cannot tell you that the file underneath one was replaced
    afterwards, and every log line downstream would keep naming the promoted
    version while different coefficients decided whether borrowers got called.
    """
    _mod = _db()
    engine = _mod.engine
    current_tenant = _mod.current_tenant
    from agent_core.treatment import registry

    tenant = current_tenant()
    with engine.connect() as conn:
        return {
            "history": registry.history(conn, tenant_id=tenant, target=target, limit=limit),
            "serving": registry.verify(conn, tenant_id=tenant),
        }


def next_authority(
    *,
    customer_id: str,
    account_id: str | None = None,
    fee_type: str = "late_fee",
    asked_amount: float | None = None,
    interaction_id: str | None = None,
) -> dict[str, Any]:
    """What the authority matrix would allow on this call, right now.

    Writes a decision row (the shadow corpus) and enacts nothing outside live
    mode. Safe to call from Handoff / Floor / 360.
    """
    _mod = _db()
    engine = _mod.engine
    _assert_tenant_owns = _mod._assert_tenant_owns
    _assert_tenant_owns_customer = _mod._assert_tenant_owns_customer
    from agent_core.authority import recommend_authority

    with engine.begin() as conn:
        _assert_tenant_owns_customer(conn, customer_id)
        if account_id:
            _assert_tenant_owns(conn, "accounts", account_id)
        result = recommend_authority(
            customer_id=customer_id,
            account_id=account_id,
            interaction_id=interaction_id,
            fee_type=fee_type,
            asked_amount=asked_amount,
            conn=conn,
        )
    return result.to_payload()


def apply_authority(payload: dict[str, Any]) -> dict[str, Any]:
    """Post the goodwill the matrix already approved. Live mode only."""
    _mod = _db()
    engine = _mod.engine
    _assert_tenant_owns = _mod._assert_tenant_owns
    from agent_core.authority import enact as authority_enact
    from agent_core.authority.enact import AuthorityError

    decision_id = payload["decisionId"]
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "authority_decisions", decision_id)
        try:
            return authority_enact.apply_goodwill(
                decision_id=decision_id,
                amount=payload.get("amount"),
                dispute_id=payload.get("disputeId"),
                conn=conn,
            )
        except AuthorityError as exc:
            raise ValueError(str(exc)) from exc

