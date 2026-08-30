"""Orchestration — the only entry point callers need.

    features → candidates → veto → score → arbitrate → log

Two properties this function must hold, because it is called from a webhook
handler inside someone else's transaction, from a background worker, and from
the wrap-up of a live phone call:

* **It never raises.** Any failure degrades to "hold", logged. An engine that
  can take down bounce ingest is worse than no engine.
* **It never opens its own connection when given one.** Bounce ingest holds
  ``FOR UPDATE`` on the account row while it asks what to do next; a second
  connection there is a deadlock waiting for load.

One deliberate divergence from ``reco.engine``: in shadow mode this returns the
plan it would have carried out, rather than an empty result. Reco hides its
shadow output because *speaking* is the risk it is managing. Here the risk is
*contacting*, and showing a supervisor what the engine would have done — while
doing none of it — is the entire point of the shadow fortnight. ``suppressed``
is still true and the executor still refuses to act on it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from agent_core.treatment import (
    actions as A,
    arbitration,
    config,
    decisions,
    explore,
    narrate,
    policy as policy_mod,
    timing,
)
from agent_core.treatment.features import (
    AccountFeatures,
    FeatureProvider,
    SCHEMA_VERSION,
    Trigger,
    build_features,
)
from agent_core.treatment.scoring import Candidate, ScoredAction, build_scorer, vector

logger = logging.getLogger(__name__)

#: How far back the ladder remembers what was actually done to this borrower.
#: A field visit in March must not authorise a second one in August without the
#: digital ladder being walked again.
LADDER_MEMORY = timedelta(days=30)

NO_SLOT = "no_slot_in_horizon"
CONTROL_ARM = "control_arm"

#: What a control-arm borrower may still receive. ``wait`` because the engine
#: must always have a legal action, and ``legal_notice`` because a statutory
#: demand runs on a clock that a measurement does not get to stop.
CONTROL_ARM_PERMITS: frozenset[str] = frozenset({A.WAIT, A.LEGAL_NOTICE})


@dataclass(frozen=True)
class TreatmentResult:
    """What the caller gets. Always a complete answer, never an exception."""

    action: str = A.WAIT
    channel: str | None = None
    at: datetime | None = None
    expected_value: float = 0.0
    suppressed: bool = True
    reason: str | None = None
    rationale: str = ""
    decision_id: str | None = None
    mode: str = config.MODE_SHADOW
    variant: str | None = None
    latency_ms: int = 0
    alternatives: list[ScoredAction] = field(default_factory=list)
    excluded: dict[str, str] = field(default_factory=dict)
    #: pi(a|x) under the logging policy, and the rule set that approved this.
    #:
    #: Both were being written to treatment_decisions and neither reached the
    #: caller, which the design note warns about by name: without the
    #: propensity, nothing an execution channel logs against this decision can
    #: be off-policy evaluated, and the corpus acquires the exact defect P0
    #: existed to remove.
    propensity: float = 1.0
    policy_version: int | None = None
    #: The features this was decided against. Carried so the Action Contract can
    #: state what the channel may and may not do without re-reading the
    #: database from inside a live call.
    features: Any | None = None

    @property
    def actionable(self) -> bool:
        """True only when something should actually happen, now or later."""
        return not self.suppressed and self.action != A.WAIT

    def action_contract(self, *, conn: Any | None = None) -> dict[str, Any] | None:
        """The authorisation an execution channel receives. None when there is none.

        Deliberately absent for a suppressed or ``wait`` decision rather than
        present-and-empty: a contract is an authorisation to act, and handing a
        channel an empty one invites it to decide for itself what that means.

        ``conn`` is optional and enriches rather than enables. With one, the
        authority matrix is consulted and the envelope carries the fee-waiver
        ceiling the channel may work inside; without one, the contract simply
        permits no waiver — which degrades toward conceding less, never more.
        """
        if not self.actionable:
            return None
        from agent_core.treatment import contract

        return contract.build(
            self,
            features=self.features,
            policy_version=self.policy_version,
            propensity=self.propensity,
            conn=conn,
        )

    def to_payload(self) -> dict[str, Any]:
        """Model- and UI-facing shape.

        Expected values and per-action probabilities are included on purpose,
        unlike reco's tool payload: a collections supervisor overriding this
        decision needs to see the arithmetic, and unlike an offer, none of it is
        a number the borrower will be quoted.
        """
        return {
            "action": self.action,
            "actionLabel": A.label(self.action),
            "channel": self.channel,
            "at": self.at.isoformat() if self.at else None,
            "expectedValueInr": round(self.expected_value, 2),
            "suppressed": self.suppressed,
            "reason": self.reason,
            "reasonText": narrate.humanise(self.reason) if self.reason else None,
            "rationale": self.rationale,
            "decisionId": self.decision_id,
            "propensity": round(self.propensity, 6),
            "policyVersion": self.policy_version,
            "mode": self.mode,
            "variant": self.variant,
            "latencyMs": self.latency_ms,
            "alternatives": [s.to_log() for s in self.alternatives],
            "excluded": dict(self.excluded),
        }


def recommend_treatment(
    *,
    customer_id: str,
    account_id: str | None = None,
    trigger: Trigger | str = "manual",
    interaction_id: str | None = None,
    now: datetime | None = None,
    conn: Any | None = None,
    provider: FeatureProvider | None = None,
    force_mode: str | None = None,
    variant: str | None = None,
) -> TreatmentResult:
    """Decide what should happen next for one borrower. Never raises.

    ``variant`` is an explicit per-call override; without one the borrower is
    bucketed deterministically by ``TREATMENT_AB_SPLIT``, so the same borrower
    always lands in the same arm. A borrower treated patiently after Monday's
    bounce and eagerly after Thursday's belongs to neither, and every number
    computed from that split is noise.
    """
    started = time.perf_counter()
    instant = _aware(now)
    trig = (
        trigger if isinstance(trigger, Trigger) else Trigger(kind=str(trigger))
    ).normalised()

    arm = config.resolve_variant(variant) or config.assign_variant(customer_id)
    mode = (
        force_mode or (arm.mode if arm and arm.mode else None) or config.mode()
    ).strip().lower()
    arm_name = arm.name if arm else None

    if mode == config.MODE_OFF:
        return TreatmentResult(
            suppressed=True,
            reason=arbitration.SUPPRESS_ENGINE_OFF,
            rationale="The treatment engine is switched off.",
            mode=mode,
            variant=arm_name,
        )

    try:
        return _recommend(
            customer_id=customer_id,
            account_id=account_id,
            trigger=trig,
            interaction_id=interaction_id,
            now=instant,
            conn=conn,
            provider=provider,
            mode=mode,
            arm=arm,
            started=started,
        )
    except Exception:
        # Whatever this module gets wrong, the caller's transaction survives it.
        logger.exception("treatment recommendation failed for customer=%s", customer_id)
        return TreatmentResult(
            suppressed=True,
            reason=arbitration.SUPPRESS_ERROR,
            rationale="Holding — the engine could not complete a decision.",
            mode=mode,
            variant=arm_name,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _recommend(
    *,
    customer_id: str,
    account_id: str | None,
    trigger: Trigger,
    interaction_id: str | None,
    now: datetime,
    conn: Any | None,
    provider: FeatureProvider | None,
    mode: str,
    arm: config.Variant | None,
    started: float,
) -> TreatmentResult:
    import db

    arm_name = arm.name if arm else None
    active_policy = config.apply_variant(config.policy(), arm)
    unit_costs = config.costs()

    if conn is not None:
        return _decide(
            conn,
            customer_id=customer_id,
            account_id=account_id,
            trigger=trigger,
            interaction_id=interaction_id,
            now=now,
            provider=provider,
            mode=mode,
            arm=arm,
            arm_name=arm_name,
            active_policy=active_policy,
            unit_costs=unit_costs,
            started=started,
        )
    # One connection for the whole read phase, then the log writes on its own.
    with db.engine.connect() as owned:
        return _decide(
            owned,
            customer_id=customer_id,
            account_id=account_id,
            trigger=trigger,
            interaction_id=interaction_id,
            now=now,
            provider=provider,
            mode=mode,
            arm=arm,
            arm_name=arm_name,
            active_policy=active_policy,
            unit_costs=unit_costs,
            started=started,
            log_conn=None,
        )


def _decide(
    conn: Any,
    *,
    customer_id: str,
    account_id: str | None,
    trigger: Trigger,
    interaction_id: str | None,
    now: datetime,
    provider: FeatureProvider | None,
    mode: str,
    arm: config.Variant | None,
    arm_name: str | None,
    active_policy: config.Policy,
    unit_costs: config.Costs,
    started: float,
    log_conn: Any | None = ...,  # type: ignore[assignment]
) -> TreatmentResult:
    """The pipeline itself, against one connection.

    ``log_conn`` defaults to ``conn`` — when the caller lends us a transaction,
    the decision row belongs in it, so a bounce that rolls back does not leave a
    plan behind describing a case that no longer exists.
    """
    writer = conn if log_conn is ... else log_conn

    features = build_features(
        customer_id,
        account_id=account_id,
        trigger=trigger,
        now=now,
        provider=provider,
        conn=conn,
    )
    last_rung = policy_mod.last_rung_used(
        conn, customer_id, within=LADDER_MEMORY, bucket=features.bucket
    )

    candidates, excluded = _generate(
        conn,
        features=features,
        trigger=trigger,
        now=now,
        active_policy=active_policy,
        last_rung=last_rung,
        arm=arm,
    )

    scorer = build_scorer((arm.scorer if arm and arm.scorer else None) or config.scorer_name())
    scored = scorer.score(
        features,
        trigger,
        candidates,
        now=now,
        policy=active_policy,
        costs=unit_costs,
    )

    planned = decisions.planned_actions(
        conn,
        customer_id=customer_id,
        trigger_kind=trigger.kind,
        trigger_ref=trigger.ref,
    )

    verdict = arbitration.arbitrate(
        features=features,
        trigger=trigger,
        scored=scored,
        excluded=excluded,
        policy=active_policy,
        planned=planned,
        arm_probability=config.arm_probability(arm_name),
        chooser=_chooser(
            customer_id=customer_id,
            trigger=trigger,
            arm=arm,
            scored=scored,
        ),
    )

    # Shadow decides exactly as live does and then declines to act, through the
    # same code path — so what ships to live is what was measured.
    suppressed = verdict.suppressed or mode == config.MODE_SHADOW
    reason = verdict.reason or (
        arbitration.SUPPRESS_SHADOW if mode == config.MODE_SHADOW else None
    )
    chosen = verdict.chosen

    rules = _rules(conn, features.tenant_id, now)

    line = narrate.rationale(
        features=features,
        trigger=trigger,
        chosen=chosen,
        suppressed=verdict.suppressed,
        reason=verdict.reason,
        now=now,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    decision_id = decisions.record(
        conn=writer,
        tenant_id=features.tenant_id,
        customer_id=customer_id,
        account_id=features.account_id,
        interaction_id=interaction_id,
        trigger_kind=trigger.kind,
        trigger_ref=trigger.ref,
        mode=mode,
        variant=arm_name,
        recommender=scorer.name,
        recommender_version=scorer.version,
        feature_schema_version=SCHEMA_VERSION,
        features={
            **features.to_log(),
            "trigger": trigger.to_log(now),
            # Full provenance of the rules that approved this: statutory,
            # client and product layers with their labels and versions. The
            # indexed policy_version column carries the statutory one, which is
            # the number a regulator's question is about; this carries the rest
            # so nothing is lost.
            "policy": rules.to_log(),
        },
        # The full ranked list, not just the winner. The counterfactual is what
        # offline evaluation compares against, and it cannot be recovered later.
        candidates=_candidate_log(
            features, trigger, scored, now=now, distribution=verdict.distribution
        ),
        excluded=excluded,
        chosen_action=chosen.action if chosen else A.WAIT,
        chosen_channel=chosen.channel if chosen else None,
        # A suppressed decision has no schedule. Writing one would leave a row
        # the executor's index considers due.
        scheduled_at=(chosen.at if chosen and not suppressed else None),
        expected_value=round(chosen.expected_value, 2) if chosen else 0.0,
        # A suppressed decision has a propensity of 1.0 and that is not a
        # placeholder: silence was not drawn from anything, it was the only
        # thing left after the gates. Writing NULL instead would make every
        # suppression invisible to an off-policy estimator, which is exactly
        # the negative class the corpus exists to carry.
        propensity=verdict.propensity,
        explore_kind=verdict.explore_kind,
        policy_version=rules.version,
        suppression_reason=reason,
        rationale=line,
        latency_ms=latency_ms,
    )

    return TreatmentResult(
        action=chosen.action if chosen else A.WAIT,
        channel=chosen.channel if chosen else None,
        at=chosen.at if chosen else None,
        expected_value=chosen.expected_value if chosen else 0.0,
        suppressed=suppressed,
        reason=reason,
        rationale=line,
        decision_id=decision_id,
        mode=mode,
        variant=arm_name,
        latency_ms=latency_ms,
        alternatives=list(verdict.alternatives),
        excluded=dict(excluded),
        propensity=verdict.propensity,
        policy_version=rules.version,
        features=features,
    )


#: How much further ahead a non-contacting action may be planned.
#:
#: ``TREATMENT_HORIZON_HOURS`` is 72 by default and it is a *contact* horizon:
#: three days is about how long a decision to dial somebody stays relevant.
#: A mandate presentment is not a decision to dial somebody. It has to land on
#: the borrower's payday, payday comes once a month, and a 72-hour horizon
#: therefore excludes the correctly-timed presentment for roughly nine days in
#: every ten — reported as ``no_slot_in_horizon``, which reads like a data gap
#: rather than like a horizon that was never meant to answer this question.
#:
#: Found by the corpus simulator rather than by reading the code: the action
#: the design note calls the highest-ROI change in the system was being chosen
#: about five percent of the time it was eligible, and the vetoes all looked
#: fine.
NON_CONTACT_HORIZON_MULTIPLIER = 15


def _horizon_for(action: str, policy: config.Policy) -> int:
    hours = policy.planning_horizon_hours
    if action in A.NON_CONTACTING:
        return hours * NON_CONTACT_HORIZON_MULTIPLIER
    return hours


def _chooser(
    *,
    customer_id: str,
    trigger: Trigger,
    arm: config.Variant | None,
    scored: list[ScoredAction],
):
    """Build the draw arbitration will use over its approved set.

    Deliberately a closure rather than a branch inside ``arbitrate``: the
    chooser must not be able to see anything except the actions that survived
    every gate, and handing it a function is how that is enforced rather than
    remembered.

    With the default ``TREATMENT_GREEDINESS=1.0`` this returns the top-ranked
    approved action with a propensity of 1.0 — byte-identical to what the
    engine did before exploration existed. The log simply starts saying so.
    """
    greed = config.greediness()
    arm_p = config.arm_probability(arm.name if arm else None)
    seed = explore.seed_for(
        customer_id=customer_id,
        trigger_kind=trigger.kind,
        trigger_ref=trigger.ref,
        actions=[s.action for s in scored],
    )

    def _choose(approved):
        if arm is not None and arm.suppress_discretionary:
            # Nothing was drawn: the arm withheld every discretionary option
            # and what remains was forced. The only randomness in this path is
            # the arm assignment, and recording an imaginary within-arm draw
            # would understate every importance weight computed off these rows.
            return explore.control_arm_choice(approved[0], arm_probability=arm_p)
        return explore.choose(
            approved, greediness=greed, seed=seed, arm_probability=arm_p
        )

    return _choose


def _generate(
    conn: Any,
    *,
    features: AccountFeatures,
    trigger: Trigger,
    now: datetime,
    active_policy: config.Policy,
    last_rung: int,
    arm: config.Variant | None = None,
) -> tuple[list[Candidate], dict[str, str]]:
    """Plan an instant for every action, then veto it at that instant.

    Timing first is what makes the veto meaningful. Asking "may we dial?" at
    02:00 answers no for every borrower on earth; asking "may we dial at the
    first moment we actually would?" answers the question the engine is for.
    """
    candidates: list[Candidate] = []
    excluded: dict[str, str] = {}
    control_arm = bool(arm is not None and arm.suppress_discretionary)

    for action in A.ALL:
        if control_arm and action not in CONTROL_ARM_PERMITS:
            # The control arm withholds *discretionary* action, not all of it.
            # Silence where the law requires a notice is not a control group;
            # it is a compliance breach that happens to be randomised. Recorded
            # per action so the log says why the engine was quiet, rather than
            # leaving a supervisor to infer it from an arm name.
            excluded[action] = CONTROL_ARM
            continue
        slot = timing.plan(
            action,
            features,
            now=now,
            horizon_hours=_horizon_for(action, active_policy),
        )
        if not slot.feasible:
            excluded[action] = NO_SLOT
            continue
        reason = policy_mod.veto(
            conn,
            action=action,
            features=features,
            trigger=trigger,
            at=slot.at or now,
            policy=active_policy,
            last_rung=last_rung,
        )
        if reason:
            excluded[action] = reason
            continue
        candidates.append(Candidate(action=action, at=slot.at, timing_rationale=slot.rationale))

    return candidates, excluded


def _rules(conn: Any, tenant_id: str, now: datetime) -> Any:
    """The rule set in force at decision time. Never raises."""
    import policy_rules

    try:
        return policy_rules.resolve(conn, tenant_id=tenant_id, at=now)
    except Exception:
        logger.exception("policy rule resolution failed for tenant=%s", tenant_id)
        return policy_rules.EMPTY


def _candidate_log(
    features: AccountFeatures,
    trigger: Trigger,
    scored: list[ScoredAction],
    *,
    now: datetime,
    distribution: Any = None,
) -> list[dict[str, Any]]:
    rows = [s.to_log() for s in scored]
    if distribution:
        # π over the *whole* approved set, not just the action taken. IPS needs
        # only the chosen action's probability; a doubly-robust estimator needs
        # the others, and they cannot be reconstructed afterwards because the
        # approved set itself depended on vetoes evaluated at that instant.
        for row in rows:
            share = distribution.get(str(row.get("action")))
            if share is not None:
                row["propensity"] = round(float(share), 8)
    if not config.log_vectors():
        return rows
    by_action = {s.action: s for s in scored}
    for row in rows:
        s = by_action.get(str(row.get("action")))
        if s is None:
            continue
        # ``wait`` is vectorised too, and it was not always. Skipping it made
        # sense while silence was just the absence of an action: its
        # action-specific half is all zeros and there is nothing to rank.
        #
        # It stopped making sense the moment a randomised control arm existed.
        # A control-arm decision *is* a wait, and its account-level features are
        # the counterfactual — the only rows in the corpus that can say what
        # would have happened anyway. Without a vector on them the timing model
        # has no training data at all and the control half of the uplift
        # T-learner cannot be fitted, so the engine logs a full feature vector
        # for every action it did not take and none for the one it did.
        #
        # Found by the trainer refusing to fit, which is what that refusal is
        # for.
        try:
            row["vector"] = {
                k: (round(v, 6) if v is not None else None)
                for k, v in vector(features, trigger, s, now=now).items()
            }
        except Exception:
            # A vector we cannot build costs one training row, not the decision.
            logger.exception("treatment vector logging failed for %s", row.get("action"))
    return rows


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
