"""The Action Contract — the interface every execution channel receives.

§12 of the design note, and the thing that makes voice, WhatsApp, SMS and field
interchangeable: the executing agent never decides *whether* to contact. It
receives an authorisation to perform one intervention, with the bounds of that
authorisation attached.

**The executing channel is not trusted to look anything up.** A voice bot that
had to query the policy gate mid-call would be a voice bot that can be wrong
about it under latency, and a field agent has no gate to query at all. So the
envelope carries what it may do and what it may not, resolved once at decision
time by the layer that owns those questions.

**Two fields carry the whole learning loop**, and the design note is right that
they are the ones most easily forgotten — they were, here, for a fortnight. Both
were being written to ``treatment_decisions`` and neither reached the payload:

* ``decisionId`` — without it a conversation outcome cannot be attributed back
  to the decision that caused it, and the feedback loop is an open arc rather
  than a flywheel.
* ``propensity`` — without it no off-policy estimate over anything the channel
  learns is valid. A channel that logs its own outcomes against a decision whose
  odds it never saw produces a corpus with the same defect the engine spent P0
  fixing.

And the score is ``expectedValueInr``, not a dimensionless ``priority: 0.87``. A
rupee figure is something a collections head can argue with.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_core import logging_contract
from agent_core.treatment import actions as A
from bank_boundary import ACTION_CONTRACT_VERSION

logger = logging.getLogger(__name__)

#: What the intervention is *for*. The channel's own success criterion, and the
#: reason a bot on a pre-due reminder should not be negotiating a settlement.
OBJECTIVE_BY_BUCKET: dict[str, str] = {
    A.PRE_DUE: "payment_reminder",
    A.B_0_30: "payment_commitment",
    A.B_31_60: "payment_commitment",
    # 61-90 is triage: find out which of willing / distress / dispute this is
    # and route. Asking a bot to close here is asking it to exceed what the
    # bucket policy already says it may own.
    A.B_61_90: "triage",
    A.B_90_PLUS: "settlement_discussion",
}

#: How to say it. Distinct from the objective because the same objective is
#: pursued differently at day 3 and day 80, and because "firm" is a word a
#: compliance officer will want to see bounded rather than inferred.
STRATEGY_BY_BUCKET: dict[str, str] = {
    A.PRE_DUE: "courtesy_reminder",
    A.B_0_30: "soft_reminder",
    A.B_31_60: "structured_ask",
    A.B_61_90: "diagnostic",
    A.B_90_PLUS: "empathetic_resolution",
}

#: Seconds. Voice only — the others have no duration to bound. A ceiling rather
#: than a target: a call that needs longer than this is a call that should have
#: been a human's.
MAX_DURATION_BY_BUCKET: dict[str, int] = {
    A.PRE_DUE: 90,
    A.B_0_30: 180,
    A.B_31_60: 240,
    A.B_61_90: 300,
    A.B_90_PLUS: 420,
}

#: Never permitted, on any channel, in any bucket. Stated on every contract
#: rather than left to the prompt, because a prohibition that lives only in a
#: system prompt is a prohibition one jailbreak away from not existing — and
#: because a field agent has no system prompt at all.
ALWAYS_PROHIBITED: tuple[str, ...] = (
    # RBI Fair Practices: a debt may not be discussed with anyone but the
    # borrower, however helpfully the person who answered offers to pass it on.
    "third_party_disclosure",
    "pressure_language",
    "threat_of_legal_action",
    "calling_outside_permitted_hours",
    "cross_sell",
    "promotional_content",
)

REQUIRED_ASSERTIONS: tuple[str, ...] = (
    "identify_lender",
    "state_automated",
    "offer_human_handoff",
    "grievance_officer_contact",
)

RETENTION_CLASS = "collections_operational"


def build(
    result: Any,
    *,
    features: Any | None = None,
    policy_version: int | None = None,
    propensity: float | None = None,
    conn: Any | None = None,
) -> dict[str, Any]:
    """The envelope for one authorised intervention.

    Returns a plain dict rather than a dataclass because it crosses a process
    boundary — into a voice runner, a WhatsApp job, a field dispatcher — and
    every one of those serialises it immediately.
    """
    bucket = getattr(features, "bucket", None) or A.B_0_30
    action = result.action
    spec = A.spec(action) if action in A.SPECS else None
    arm_p = getattr(result, "arm_propensity", None)
    action_p = getattr(result, "action_propensity", None)
    if arm_p is None:
        arm_p = propensity
    if action_p is None:
        action_p = 1.0 if propensity is not None else None
    ev_paise = int(round(float(result.expected_value or 0) * 100))
    endpoint = None
    if features is not None:
        endpoint = getattr(features, "phone_primary", None) or getattr(
            features, "endpoint", None
        )
    tenant_id = getattr(features, "tenant_id", None) or getattr(result, "tenant_id", None)
    portfolio_id = getattr(features, "portfolio_id", None) or ""
    binding_hash = getattr(result, "policy_binding_hash", None)
    image = getattr(result, "engine_image_digest", None) or logging_contract.engine_image_digest()
    config_ver = getattr(result, "config_version", None) or logging_contract.config_version(
        conn=conn, portfolio_id=portfolio_id
    )

    contract: dict[str, Any] = {
        "version": ACTION_CONTRACT_VERSION,
        "decision_id": result.decision_id,
        "tenant_id": tenant_id,
        "portfolio_id": portfolio_id,
        "policy_binding": list(getattr(result, "policy_binding", None) or []),
        "policy_binding_hash": binding_hash,
        "engine_image_digest": image,
        "config_version": config_ver,
        "veto_stack_version": logging_contract.VETO_STACK_VERSION,
        "arm_propensity": arm_p,
        "action_propensity": action_p,
        "propensity": propensity,
        "action": action,
        "channel": result.channel,
        "endpoint": endpoint,
        "scheduled_at": result.at.isoformat() if result.at else None,
        "expected_value_paise": ev_paise,
        "ev_lcb_paise": ev_paise,
        "expected_value_inr": round(result.expected_value, 2),
        "variant": result.variant,
        "objective": OBJECTIVE_BY_BUCKET.get(bucket, "payment_commitment"),
        "strategy": STRATEGY_BY_BUCKET.get(bucket, "soft_reminder"),
        "prohibitions": list(_prohibited(features)),
        "required_assertions": list(REQUIRED_ASSERTIONS),
        "retention_class": RETENTION_CLASS,
        "policy_version": policy_version,
        # Collections contracts never carry promotional offers.
        "allowed_offers": [],
        # CamelCase aliases for the existing operator payload.
        "decisionId": result.decision_id,
        "policyVersion": policy_version,
        "scheduledAt": result.at.isoformat() if result.at else None,
        "expectedValueInr": round(result.expected_value, 2),
        "prohibited": list(_prohibited(features)),
    }

    if spec is not None and spec.channel == "voice":
        contract["maxDurationSec"] = MAX_DURATION_BY_BUCKET.get(bucket, 180)
        contract["max_duration_sec"] = contract["maxDurationSec"]

    contract["allowedOffers"] = list(contract["allowed_offers"])

    waiver = _waiver_ceiling(conn, result, features)
    if waiver is not None:
        # The concession an agent is actually asked for on a collections call,
        # resolved here so the channel does not have to stop mid-conversation
        # and ask. A voice bot that had to query the authority matrix under
        # latency is a voice bot that can be wrong about it.
        contract["allowedOffers"].append("late_fee_waiver")
        contract["maxWaiverInr"] = waiver
        # The ceiling is conditional, and saying so on the envelope is the
        # point. ``build_features`` cannot know whether the person who answers
        # is the borrower — nobody can, before the call — so the matrix is asked
        # its question with identity assumed, and the condition travels with the
        # answer instead of being silently baked into it.
        contract["waiverRequiresIdentityCheck"] = True
    return contract


def require_for_enactment(
    conn: Any, decision: dict[str, Any], customer: dict[str, Any]
) -> dict[str, Any]:
    """Load or persist the send-time snapshot after a freshness re-check.

    Handlers must consume this object. They may not reconstruct authorisation
    from loose decision fields.
    """
    from bank_boundary import freshness, snapshots
    from bank_boundary import schema_ready as w5_schema
    from bank_boundary.snapshots import ContractError

    decision_id = str(decision.get("id") or "")
    if not decision_id:
        raise ContractError("missing")
    tenant_id = str(customer.get("tenant_id") or decision.get("tenant_id") or "")
    action = str(decision.get("chosen_action") or "")
    channel = decision.get("chosen_channel")
    if w5_schema.w5_ready(conn):
        ready = freshness.resolve(
            conn,
            tenant_id=tenant_id,
            action=action,
            channel=channel,
            endpoint=customer.get("phone_primary"),
            customer_id=customer.get("id"),
        )
        if ready.veto:
            raise ContractError(f"stale:{ready.veto}")

    try:
        existing = snapshots.load(conn, decision_id)
        expected = {
            "decision_id": decision_id,
            "tenant_id": tenant_id,
            "action": action,
            "channel": channel,
            "policy_binding_hash": decision.get("policy_binding_hash"),
            "veto_stack_version": logging_contract.VETO_STACK_VERSION,
        }
        if any(existing.get(key) != value for key, value in expected.items()):
            raise ContractError("stale")
        return existing
    except ContractError as exc:
        if str(exc) != "missing":
            raise

    payload = {
        "version": ACTION_CONTRACT_VERSION,
        "decision_id": decision_id,
        "tenant_id": tenant_id,
        "portfolio_id": "",
        "policy_binding": list(decision.get("policy_binding") or []),
        "policy_binding_hash": decision.get("policy_binding_hash"),
        "engine_image_digest": decision.get("engine_image_digest")
        or logging_contract.engine_image_digest(),
        "config_version": decision.get("config_version")
        or logging_contract.config_version(conn=conn),
        "veto_stack_version": logging_contract.VETO_STACK_VERSION,
        "arm_propensity": decision.get("arm_propensity"),
        "action_propensity": decision.get("action_propensity"),
        "propensity": decision.get("propensity"),
        "action": action,
        "channel": channel,
        "endpoint": customer.get("phone_primary"),
        "scheduled_at": (
            decision["scheduled_at"].isoformat()
            if hasattr(decision.get("scheduled_at"), "isoformat")
            else decision.get("scheduled_at")
        ),
        "expected_value_paise": int(
            round(float(decision.get("expected_value") or 0) * 100)
        ),
        "ev_lcb_paise": int(round(float(decision.get("expected_value") or 0) * 100)),
        "expected_value_inr": float(decision.get("expected_value") or 0),
        "variant": decision.get("variant"),
        "objective": OBJECTIVE_BY_BUCKET.get(
            str(decision.get("bucket") or A.B_0_30), "payment_commitment"
        ),
        "strategy": STRATEGY_BY_BUCKET.get(
            str(decision.get("bucket") or A.B_0_30), "soft_reminder"
        ),
        "prohibitions": list(ALWAYS_PROHIBITED),
        "required_assertions": list(REQUIRED_ASSERTIONS),
        "retention_class": RETENTION_CLASS,
        "allowed_offers": [],
        "decisionId": decision_id,
        "policyVersion": decision.get("policy_version"),
        "expectedValueInr": float(decision.get("expected_value") or 0),
        "prohibited": list(ALWAYS_PROHIBITED),
        "allowedOffers": [],
    }
    return snapshots.persist(conn, payload)


def _waiver_ceiling(conn: Any, result: Any, features: Any | None) -> float | None:
    """The rupee ceiling the authority matrix allows here, or None.

    **Only ever a ceiling, never an instruction.** The matrix answers
    "auto_approve / cap / escalate" for a fee the borrower has *asked* about;
    this asks the weaker question "if they ask, what may be said yes to?" and
    puts the answer in the envelope. Nothing here tells a channel to offer a
    waiver, and a channel that volunteers one is misreading its own contract.

    **Conditional on identity.** Whether the person who answers is the borrower
    is not knowable before the call, so the matrix is asked with identity
    assumed and the contract carries ``waiverRequiresIdentityCheck`` alongside
    the number. A ceiling that quietly assumed verification would be a bot
    waiving a fee for whoever picked up the phone.

    Requires a connection and returns None without one. That is the honest
    default: an absent ceiling means the channel may not concede, which is the
    same thing an empty ``allowedOffers`` already means, and it degrades toward
    conceding less rather than more.

    Restructures and settlements are deliberately never reachable from here.
    ``matrix.decide`` escalates both unconditionally, so a contract that offered
    one would be offering something no authority exists to grant.
    """
    if conn is None or features is None:
        return None
    try:
        from agent_core.authority import config as authority_config
        from agent_core.authority import matrix
        from agent_core.authority.features import FEE_LATE, build_features

        if authority_config.mode() == authority_config.MODE_OFF:
            return None
        customer_id = getattr(features, "customer_id", None)
        if not customer_id:
            return None
        authority = build_features(
            conn,
            customer_id=customer_id,
            account_id=getattr(features, "account_id", None),
        )
        decision = matrix.decide(authority, fee_type=FEE_LATE, asked_amount=None)
        if decision.verdict == matrix.VERDICT_ESCALATE:
            return None
        cap = decision.cap_amount or 0.0
        return cap if cap > 0 else None
    except Exception:
        # A contract that cannot be built is a decision that cannot be executed.
        # The waiver ceiling is an enrichment, not a requirement, so a failure
        # here costs the channel a concession it may not make rather than the
        # intervention itself.
        logger.exception("authority ceiling lookup failed; omitting it from the contract")
        return None


def _prohibited(features: Any | None) -> tuple[str, ...]:
    """What this specific borrower's state forbids, on top of the universals.

    Derived from holds rather than from the action, because a hold is a fact
    about the person: a borrower with an open dispute must not be asked to pay
    the disputed amount whichever channel reaches them.
    """
    out = list(ALWAYS_PROHIBITED)
    holds = tuple(getattr(features, "holds", ()) or ())
    if "dispute" in holds or (getattr(features, "open_dispute_count", 0) or 0) > 0:
        out.append("demand_disputed_amount")
    if "hardship" in holds:
        out.append("request_immediate_payment")
    if "bereavement" in holds:
        out.append("discuss_arrears")
    if "legal" in holds:
        # A matter with legal is a matter where anything said becomes evidence.
        out.append("any_settlement_discussion")
    return tuple(out)
