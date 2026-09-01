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

from agent_core.treatment import actions as A

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
)


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

    contract: dict[str, Any] = {
        "decisionId": result.decision_id,
        "policyVersion": policy_version,
        "propensity": propensity,
        "action": action,
        "channel": result.channel,
        "scheduledAt": result.at.isoformat() if result.at else None,
        "expectedValueInr": round(result.expected_value, 2),
        "variant": result.variant,
        "objective": OBJECTIVE_BY_BUCKET.get(bucket, "payment_commitment"),
        "strategy": STRATEGY_BY_BUCKET.get(bucket, "soft_reminder"),
        "prohibited": list(_prohibited(features)),
    }

    if spec is not None and spec.channel == "voice":
        contract["maxDurationSec"] = MAX_DURATION_BY_BUCKET.get(bucket, 180)

    contract["allowedOffers"] = list(_allowed_offers(features))

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


def _allowed_offers(features: Any | None) -> tuple[str, ...]:
    """Concessions this intervention may put on the table, and no others.

    Empty is a meaningful answer and the safe one: a channel with no allowed
    offers may collect, and may not bargain. Widening this is the authority
    matrix's job (P4) and not the treatment engine's — the engine decides
    whether to contact, not what may be conceded, and conflating the two is how
    a bot ends up waiving a fee nobody authorised.
    """
    if features is None:
        return ()
    holds = tuple(getattr(features, "holds", ()) or ())
    if any(h in holds for h in ("hardship", "bereavement", "legal", "complaint")):
        return ()
    # A pay-link is not a concession — it is the same amount, made easier to
    # pay — so it needs no authority and is always available where the borrower
    # has a digital channel.
    offers = ["payment_link"]
    if getattr(features, "bucket", None) in {A.B_31_60, A.B_61_90, A.B_90_PLUS}:
        offers.append("part_payment")
    return tuple(offers)
