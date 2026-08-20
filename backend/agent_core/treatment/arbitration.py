"""Whether to act at all — and it is allowed to answer no to a good action.

Scoring answers *which*. This answers *whether*, and the two are separate for
the reason reco gives: the moment a restraint becomes a score penalty, someone
can tune it away while chasing recovery, and the tuning will look like progress
right up until a regulator reads the call log.

Every suppression returns a stable reason. It is logged, counted and charted, so
"the engine went quiet on Tuesday" always has an answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Collection, Mapping, Sequence

from agent_core.treatment import actions as A
from agent_core.treatment.config import Policy
from agent_core.treatment.features import AccountFeatures, Trigger
from agent_core.treatment.policy import CONTACT_PREFIX, HOLD_PREFIX
from agent_core.treatment.scoring import ScoredAction

SUPPRESS_NO_ACTION = "no_eligible_action"
SUPPRESS_BELOW_FLOOR = "below_value_floor"
SUPPRESS_BUDGET_RESERVED = "budget_reserved"
SUPPRESS_ALREADY_PLANNED = "already_planned"
SUPPRESS_ATTEMPTS_EXHAUSTED = "attempts_exhausted"
SUPPRESS_BACKOFF = "retry_backoff"
SUPPRESS_ALL_HELD = "all_actions_held"
SUPPRESS_ALL_CAPPED = "all_channels_capped"
SUPPRESS_ENGINE_OFF = "engine_off"
SUPPRESS_ERROR = "engine_error"
SUPPRESS_SHADOW = "shadow_mode"


@dataclass(frozen=True)
class Verdict:
    chosen: ScoredAction | None
    alternatives: list[ScoredAction]
    suppressed: bool
    reason: str | None
    #: π(a|x) under the logging policy: the probability this decision, as
    #: taken, would have been taken again. 1.0 for a deterministic pick outside
    #: any experiment; the arm's share when the borrower was randomised, whether
    #: the arm ended in an action or in silence.
    propensity: float = 1.0
    #: How the pick was made, for the decision log. See :mod:`explore`.
    explore_kind: str | None = None
    #: action → π over the approved set, when there was a draw.
    distribution: Mapping[str, float] = field(default_factory=dict)


def arbitrate(
    *,
    features: AccountFeatures,
    trigger: Trigger,
    scored: Sequence[ScoredAction],
    excluded: Mapping[str, str],
    policy: Policy,
    planned: Collection[str] = (),
    chooser: Callable[[Sequence[ScoredAction]], Any] | None = None,
    arm_probability: float = 1.0,
) -> Verdict:
    """Pick the action to enact, or explain the silence.

    ``scored`` is ranked and always contains ``wait``: silence is an action
    here, so there is no state in which the engine has nothing legal to choose.

    Two things happen in a particular order and the order is load-bearing.

    **The case-level guards run first**, because they are properties of the
    case rather than of any one action: a borrower who has ignored five
    contacts about one bounce is done being contacted, whichever channel is
    ranked top today.

    **Then the per-action filters, and only then the draw.** ``chooser`` sees
    exactly the actions that survived every gate — floor, reserve, already
    planned — so exploration can never be the reason a borrower is contacted in
    a way that would otherwise have been refused. It picks *which* permitted
    thing happens, never *whether* a forbidden one does. Without a ``chooser``
    the top-ranked survivor wins, which is what this function did before
    exploration existed and what it still does by default.

    ``planned`` is the set of actions already scheduled and unspent for this
    same trigger. A set rather than a flag about the top-ranked action, because
    the old form asked the case-level question through a proxy that stopped
    answering it whenever the ranking moved.

    ``arm_probability`` lands on the *suppressed* verdicts, which never reach
    the chooser. Silence inside a randomised arm is still an outcome the
    logging policy produced with a probability below one — the borrower had to
    be assigned the arm before the gates could close on them — and recording
    1.0 there would tell an off-policy estimator that every control-arm
    observation was certain, which is the opposite of what randomising it means.
    """
    wait = next((s for s in scored if s.action == A.WAIT), None)
    contenders = [s for s in scored if s.action != A.WAIT]

    if not contenders:
        return _hold(wait, scored, _why_nothing_survived(excluded), arm_probability)

    if features.case_attempts >= policy.max_attempts_per_case:
        # The ladder runs out. A borrower who has ignored five contacts about
        # one bounce will not be persuaded by the sixth, and RBI reads a sixth
        # as persistent calling — which is a finding, not a conversion problem.
        return _hold(wait, scored, SUPPRESS_ATTEMPTS_EXHAUSTED, arm_probability)

    if (
        features.hours_since_last_attempt is not None
        and features.hours_since_last_attempt < policy.retry_backoff_hours
    ):
        # Whatever the last attempt concluded, it concluded recently. Without
        # this a no-answer at 09:00 becomes a second dial at 09:05, which is
        # the behaviour the frequency cap exists to make impossible and which
        # the engine should not be trying in the first place.
        return _hold(wait, scored, SUPPRESS_BACKOFF, arm_probability)

    # --- per-action filters, in the order their reasons should be reported ---
    #
    # Each keeps the *first* reason that removed everything, so a suppressed
    # decision names the gate that actually closed rather than the last one
    # checked. A supervisor looking at a silent queue needs to know whether the
    # engine ran out of value or out of budget.

    if planned:
        # *Any* unspent plan for this case, not just an identical one. This
        # used to test only the top-ranked action, which was a proxy for the
        # case-level question and quietly stopped working whenever the ranking
        # shifted between two runs: a booked WhatsApp no longer blocked
        # anything once a different action outscored it, and the borrower
        # collected a second plan for one bounce.
        #
        # Stacking plans is the failure this prevents, and it does not care
        # which channel each plan is on — two messages about one missed EMI is
        # the persistent-contact pattern whether or not they rhyme.
        return _hold(wait, scored, SUPPRESS_ALREADY_PLANNED, arm_probability)

    above_floor = [s for s in contenders if s.expected_value >= policy.min_expected_value]
    if not above_floor:
        # Every available attempt costs more than it is worth. Waiting is not a
        # failure to decide; it is the decision.
        return _hold(wait, scored, SUPPRESS_BELOW_FLOOR, arm_probability)

    # The last contact slot of the day is an option, not a quota to spend.
    # Burning it on a marginal SMS at 10:00 means a genuinely useful call at
    # 18:00 is refused — and the borrower experiences the harassment without
    # the benefit. The reserve is only held for something clearly better, which
    # ``reserve_margin`` defines.
    #
    # Applied per action rather than to the top one alone: an action that costs
    # the borrower nothing — a mandate presentment has no channel — was never
    # spending the slot in the first place, and holding the reserve against it
    # would withhold the cheapest useful thing in the ladder for no benefit.
    reserving = policy.reserve_budget and features.budget_left <= 1
    affordable = [
        s
        for s in above_floor
        if not (
            reserving
            and A.spec(s.action).channel is not None
            and s.expected_value < policy.min_expected_value * policy.reserve_margin
        )
    ]
    if not affordable:
        return _hold(wait, scored, SUPPRESS_BUDGET_RESERVED, arm_probability)

    best = affordable[0]
    propensity, kind, distribution = 1.0, None, {}
    if chooser is not None:
        choice = chooser(affordable)
        if choice is not None:
            best = choice.chosen
            propensity = choice.propensity
            kind = choice.kind
            distribution = choice.distribution

    return Verdict(
        chosen=best,
        alternatives=[s for s in scored if s is not best],
        suppressed=False,
        reason=None,
        propensity=propensity,
        explore_kind=kind,
        distribution=distribution,
    )


def _hold(
    wait: ScoredAction | None,
    scored: Sequence[ScoredAction],
    reason: str,
    arm_probability: float = 1.0,
) -> Verdict:
    """Suppressed, but still a decision: ``wait`` is what gets recorded."""
    return Verdict(
        chosen=wait,
        alternatives=[s for s in scored if s is not wait],
        suppressed=True,
        reason=reason,
        propensity=max(1e-9, min(1.0, arm_probability)),
    )


def _why_nothing_survived(excluded: Mapping[str, str]) -> str:
    """Turn a pile of per-action vetoes into one honest headline.

    "no eligible action" is true and useless. A supervisor looking at a silent
    queue needs to know whether this borrower is on a hardship hold or simply
    out of contact budget until tomorrow, because those call for opposite
    responses.
    """
    reasons = list(excluded.values())
    if not reasons:
        return SUPPRESS_NO_ACTION
    holds = {r for r in reasons if r.startswith(HOLD_PREFIX)}
    if holds and len(holds) == len(set(reasons)):
        return sorted(holds)[0]
    if holds:
        return SUPPRESS_ALL_HELD
    contact = [r for r in reasons if r.startswith(CONTACT_PREFIX)]
    if contact and len(set(contact)) == len(set(reasons)):
        # Every route is closed by the same contact rule — report that rule
        # rather than burying it.
        distinct = sorted(set(contact))
        return distinct[0] if len(distinct) == 1 else SUPPRESS_ALL_CAPPED
    return SUPPRESS_NO_ACTION
