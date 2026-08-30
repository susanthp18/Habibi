"""Ranking, in rupees.

The scorer answers *which* action, and it answers in expected value rather than
in an opinion between 0 and 1. That choice does most of the work:

* **"Do nothing" competes on the same axis.** ``WAIT`` scores exactly zero, so
  any action has to be worth more than silence to be chosen. A dimensionless
  score cannot express that without an arbitrary threshold pretending to be one.
* **Cost is in the model, not bolted on.** A ₹1,150 field visit and a ₹0.18 SMS
  are not two points on a preference curve; they are two amounts of money.
* **The number is arguable.** A collections head can disagree with "an agent
  call is worth ₹68 of expected recovery here" in a way nobody can disagree
  with "0.62".

``EVScorer`` ships first for the reason ``RuleScorer`` does in reco: it needs no
training data, it is deterministic, and every term can be explained in one
sentence to someone who will be asked about it by a regulator. The priors below
are **planning figures, wrong on day one, and shadow mode exists to replace
them** — every one is logged per decision so a fortnight of traffic produces the
real ones.

A scorer cannot add an action, cannot overturn a veto, and cannot reach the
database. That is what makes swapping one safe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

import money_inr
from typing import Any, Protocol, Sequence

from agent_core.treatment import actions as A
from agent_core.treatment.config import Costs, Policy
from agent_core.treatment.features import AccountFeatures, Trigger

logger = logging.getLogger(__name__)

#: Probability a single attempt on this channel reaches a human, absent any
#: history for this borrower. Voice is low on purpose: CarmaOne and AiXBFS both
#: report ~70% of dials to unknown numbers going unanswered.
REACH_PRIOR: dict[str, float] = {
    "sms": 0.35,
    "whatsapp": 0.55,
    "voice": 0.30,
    "field": 0.55,  # borrower absent 40–50% of visits
    "email": 0.25,
}

#: Probability the account is cured *given* the message landed. Rises up the
#: ladder because the actions higher up can negotiate, not because they shout.
RESOLVE_PRIOR: dict[str, float] = {
    # A debit that clears collects the instalment outright — there is no
    # persuasion step to lose the borrower at, which is why the number sits
    # above every message and below a conversation. It is also the prior most
    # obviously wrong on day one, because the true value depends almost
    # entirely on whether the account was funded, and the whole design of the
    # timing module is an attempt to make that true.
    A.REPRESENT_MANDATE: 0.35,
    # Collects nothing today. Its value is in VALUE_HORIZON below, and this is
    # the probability the borrower actually takes up the change once offered.
    A.EMI_DATE_CHANGE: 0.30,
    # Lower than a date change because it asks more of the borrower:
    # a date change is applied for them, a plan has to be started.
    A.SELF_SERVICE_PLAN: 0.18,
    A.SMS: 0.06,
    A.WHATSAPP: 0.12,
    A.VOICE_BOT: 0.22,
    A.HUMAN_CALL: 0.35,
    A.FIELD_VISIT: 0.45,
    A.LEGAL_NOTICE: 0.30,
}

#: What an action puts at stake, as a multiple of the current exposure.
#:
#: Everything that chases *this* arrears is 1.0 — one instalment, one cure —
#: and is absent from this dict rather than listed as 1.0, so the exception
#: reads as an exception.
#:
#: A date change is the exception and it is a real one, not a thumb on the
#: scale: it collects nothing today. Scoring it against this instalment would
#: value it at nearly zero and the engine would never choose it, which is
#: exactly how a book ends up dunning the same borrower every month for a
#: mismatch nobody fixed. What it is worth is the cycles it stops from
#: bouncing, and three is the planning figure for how many of those we are
#: willing to claim credit for.
VALUE_HORIZON: dict[str, float] = {
    A.EMI_DATE_CHANGE: 3.0,
    # A plan settles the arrears it was opened against, and that is
    # already more than one instalment by the time the veto lets it
    # through. Two, not three: unlike a date change it does not stop
    # future cycles from bouncing, so claiming a third would be
    # claiming a cure it does not produce.
    A.SELF_SERVICE_PLAN: 2.0,
}

#: How curable a bucket is. Day-1 is forgetfulness; Day-92 is distress and a
#: specialist's problem.
BUCKET_CURABILITY: dict[str, float] = {
    A.PRE_DUE: 1.30,
    A.B_0_30: 1.15,
    A.B_31_60: 1.00,
    A.B_61_90: 0.80,
    A.B_90_PLUS: 0.60,
}

#: Each unanswered digital send is evidence the number is stale. Multiplicative
#: so the fifth SMS is not priced like the first.
DIGITAL_DECAY = 0.85

#: Landing a pay-link just after a salary credit, when the bounce was for
#: insufficient funds. Finezza: balances peak within ~48h of credit.
SALARY_TIMING_LIFT = 1.25

#: Each enacted attempt on this case that did not resolve it. A borrower who
#: ignored the first three contacts about one bounce is not three times as
#: likely to answer the fourth, and pricing that in is what makes the ladder
#: run out rather than grind on.
ATTEMPT_DECAY = 0.85

#: Repeating the *same* action on the same case. Much steeper than the general
#: attempt decay, and deliberately: a naive expected-value ranker sends the
#: cheapest channel forever, because ₹0.42 always beats ₹7.50 on a small
#: balance. Four identical unanswered WhatsApps is precisely the persistent-
#: contact pattern the escalation ladder exists to prevent, so the evidence that
#: this exact approach did not work has to outweigh its price.
REPEAT_ACTION_DECAY = 0.55


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


@dataclass(frozen=True)
class ScoredAction:
    action: str
    channel: str | None
    at: datetime | None
    #: Rupees. Negative means the attempt costs more than it is worth.
    expected_value: float
    p_reach: float
    p_resolve: float
    cost: float
    #: One sentence for the rep and the audit log, in terms a reviewer can check.
    explanation: str
    timing_rationale: str = ""
    reason_codes: tuple[str, ...] = ()
    components: dict[str, float] = field(default_factory=dict)

    @property
    def rung(self) -> int:
        return A.rung(self.action)

    def to_log(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "channel": self.channel,
            "at": self.at.isoformat() if self.at else None,
            "expectedValue": round(self.expected_value, 2),
            "pReach": round(self.p_reach, 4),
            "pResolve": round(self.p_resolve, 4),
            "cost": round(self.cost, 2),
            "reasonCodes": list(self.reason_codes),
            "components": {k: round(v, 4) for k, v in self.components.items()},
        }


@dataclass(frozen=True)
class Candidate:
    """An action that survived the veto, with the instant it would happen."""

    action: str
    at: datetime | None
    timing_rationale: str

    @property
    def channel(self) -> str | None:
        return A.spec(self.action).channel


class Recommender(Protocol):
    name: str
    version: str

    def score(
        self,
        features: AccountFeatures,
        trigger: Trigger,
        candidates: Sequence[Candidate],
        *,
        now: datetime,
        policy: Policy,
        costs: Costs,
    ) -> list[ScoredAction]: ...


# ---------------------------------------------------------------------------
# Sub-scores.
#
# Module-level rather than methods, for the same reason reco keeps them free:
# a propensity model has to vectorise exactly what the shipped scorer reads,
# and that stops being true the moment the logic is reachable from only one of
# them.
# ---------------------------------------------------------------------------


def p_reach(
    action: str, features: AccountFeatures, *, at: datetime | None
) -> tuple[float, bool]:
    """Chance one attempt reaches a person. Returns (p, used_history).

    History beats the prior whenever we have any, and its absence is reported
    rather than hidden: a borrower we have never dialled gets the channel prior
    and a decision log that says so.
    """
    spec = A.spec(action)
    channel = spec.channel
    if channel is None:
        # Nothing here is answered, so "reach" is delivery rather than pickup.
        # A statutory notice is served; a mandate presentation is submitted to
        # a rail; a schedule change is written to the account. All three either
        # happen or fail outright, and the failure is priced in p_resolve where
        # it belongs. ``WAIT`` alone reaches nobody by design.
        return (0.0, False) if action == A.WAIT else (1.0, False)

    observed = features.connect_rate.get(channel)
    used_history = observed is not None
    base = observed if observed is not None else REACH_PRIOR.get(channel, 0.3)

    if channel == "voice" and at is not None and features.responsive_hours:
        from agent_core.treatment.features import zone

        if at.astimezone(zone(features.timezone_name)).hour in features.responsive_hours:
            base *= 1.4

    if spec.digital and features.digital_attempts_since_connect:
        base *= DIGITAL_DECAY ** features.digital_attempts_since_connect

    return _clamp(base, 0.01, 0.95), used_history


def p_resolve(
    action: str,
    features: AccountFeatures,
    trigger: Trigger,
    *,
    now: datetime,
    timed_with_credit: bool,
) -> float:
    """Chance the account is cured given the message landed."""
    base = RESOLVE_PRIOR.get(action, 0.0)
    if base <= 0:
        return 0.0

    base *= BUCKET_CURABILITY.get(features.bucket, 1.0)

    if features.ptp_keep_rate is not None:
        # 0.6× for a serial breaker, 1.4× for someone who always pays. Absent
        # history leaves the multiplier at 1.0 rather than assuming the worst.
        base *= 0.6 + 0.8 * _clamp(features.ptp_keep_rate)

    if timed_with_credit and (A.spec(action).digital or action == A.REPRESENT_MANDATE):
        # For a message, landing after the credit is a helpful nudge. For a
        # presentment it is the entire intervention — the difference between
        # debiting a funded account and buying the borrower a bounce charge.
        base *= SALARY_TIMING_LIFT

    if features.case_attempts:
        base *= ATTEMPT_DECAY ** features.case_attempts

    repeats = features.case_actions_tried.get(action, 0)
    if repeats:
        base *= REPEAT_ACTION_DECAY ** repeats

    age_hours = trigger.age_hours(now)
    if age_hours:
        # Intent goes stale. A borrower who bounced this morning still
        # remembers; one who bounced three weeks ago has reorganised around it.
        base *= max(0.6, 1.0 - 0.02 * (age_hours / 24.0))

    return _clamp(base, 0.0, 0.95)


#: Multiplier on the urgency half-life for actions that reach nobody.
#:
#: The decay models *persuasion going stale*: a borrower who was willing on
#: Tuesday has reorganised around the debt by Friday, so a message planned for
#: Friday is worth less than one sent now. That reasoning does not apply to a
#: debit. A mandate presented on payday in three weeks collects exactly what one
#: presented on payday tomorrow collects, because nobody has to be persuaded of
#: anything in between.
#:
#: Without this the engine could never choose the highest-ROI action in the
#: book. Salary lands once a month, so the correctly-timed presentment is
#: usually a fortnight out; at the contact half-life of 36 hours that is a decay
#: factor of about 0.0001, and ``represent_mandate`` would sit below the value
#: floor for every borrower except the handful whose payday happens to be
#: tomorrow. The engine would then dun the rest — which is precisely the
#: substitution of contact for intelligence this design exists to reverse.
#:
#: Not infinite, because waiting is not free even here: the account rolls
#: further into delinquency while we wait, the bucket gets less curable, and a
#: mandate can be cancelled in the meantime. Twenty is roughly a month's
#: half-life against the 36-hour default, which prices the roll-forward without
#: pretending the debit went stale.
NON_CONTACT_DECAY_RELIEF = 20.0


def urgency_decay(
    at: datetime | None,
    *,
    now: datetime,
    halflife_hours: float,
    action: str | None = None,
) -> float:
    """How much of the value survives waiting until ``at``.

    Applied to the *planned* delay only, never to how old the event already is.
    Decaying by the event's age too would make every stale account score below
    the floor, and the engine would fall silent on exactly the borrowers who
    most need a decision — the opposite of the behaviour this product exists to
    fix.
    """
    if at is None:
        return 1.0
    delay_hours = max(0.0, (at - now).total_seconds() / 3600.0)
    if delay_hours <= 0:
        return 1.0
    halflife = max(1.0, halflife_hours)
    if action in A.NON_CONTACTING:
        halflife *= NON_CONTACT_DECAY_RELIEF
    return 0.5 ** (delay_hours / halflife)


def fatigue_cost(action: str, features: AccountFeatures, *, policy: Policy) -> float:
    """Rupees of goodwill an attempt spends, given what today already cost.

    Rises with the touches already spent: the third contact in a day is not the
    first one again. This is what stops three cheap SMS out-earning one useful
    call, and it is priced rather than capped because the cap already exists in
    :mod:`contact_policy` and does a different job.
    """
    spec = A.spec(action)
    if not spec.channel:
        return 0.0
    return spec.intrusiveness * policy.fatigue_cost * (1 + features.touches_today)


class EVScorer:
    """Expected-value ranker. Transparent, deterministic, arguable in rupees."""

    name = "ev"
    version = "1.0.0"

    def score(
        self,
        features: AccountFeatures,
        trigger: Trigger,
        candidates: Sequence[Candidate],
        *,
        now: datetime,
        policy: Policy,
        costs: Costs,
    ) -> list[ScoredAction]:
        scored = [
            self._score_one(
                features, trigger, c, now=now, policy=policy, costs=costs
            )
            for c in candidates
        ]
        # Deterministic ordering: ties break on rung then key, so two identical
        # runs cannot disagree. Offline replay depends on that.
        scored.sort(key=lambda s: (-s.expected_value, s.rung, s.action))
        return scored

    def _score_one(
        self,
        features: AccountFeatures,
        trigger: Trigger,
        candidate: Candidate,
        *,
        now: datetime,
        policy: Policy,
        costs: Costs,
    ) -> ScoredAction:
        action = candidate.action
        reasons: list[str] = []

        if action == A.WAIT:
            # Zero by construction, and that is the point: it is the number
            # every other action has to beat.
            return ScoredAction(
                action=A.WAIT,
                channel=None,
                at=candidate.at,
                expected_value=0.0,
                p_reach=0.0,
                p_resolve=0.0,
                cost=0.0,
                explanation="Hold: no contact is worth more than any attempt available now.",
                timing_rationale=candidate.timing_rationale,
                reason_codes=("baseline",),
                components={},
            )

        timed_with_credit = bool(
            features.next_credit_at
            and candidate.at
            and candidate.at >= features.next_credit_at
        )
        reach, used_history = p_reach(action, features, at=candidate.at)
        resolve = p_resolve(
            action, features, trigger, now=now, timed_with_credit=timed_with_credit
        )
        decay = urgency_decay(
            candidate.at,
            now=now,
            halflife_hours=policy.urgency_halflife_hours,
            action=action,
        )
        exposure = features.exposure
        if action == A.REPRESENT_MANDATE and features.mandate_max_amount is not None:
            # A mandate authorises a ceiling. Presenting for more than the
            # borrower agreed to is refused by the rail, so scoring the full
            # arrears would price a collection that cannot happen.
            exposure = min(exposure, features.mandate_max_amount)
        value = exposure * policy.recovery_fraction * VALUE_HORIZON.get(action, 1.0)
        gross = value * reach * resolve * decay
        cost = costs.for_action(action)
        fatigue = fatigue_cost(action, features, policy=policy)
        ev = gross - cost - fatigue

        if used_history:
            reasons.append("reach_from_history")
        else:
            reasons.append("reach_from_prior")
        if timed_with_credit:
            reasons.append("timed_to_salary_credit")
        if decay < 0.85:
            reasons.append("value_lost_to_delay")
        if features.ptp_keep_rate is not None and features.ptp_keep_rate < 0.4:
            reasons.append("weak_promise_history")
        if features.touches_today >= max(1, features.daily_cap - 1):
            reasons.append("near_daily_cap")
        if A.spec(action).human_effort:
            reasons.append("consumes_floor_capacity")
        if features.case_attempts:
            reasons.append(f"attempt_{features.case_attempts + 1}_on_this_case")
        if features.case_last_outcome == "no_answer":
            reasons.append("last_attempt_unanswered")
        if features.case_actions_tried.get(action):
            reasons.append("already_tried_on_this_case")

        return ScoredAction(
            action=action,
            channel=candidate.channel,
            at=candidate.at,
            expected_value=ev,
            p_reach=reach,
            p_resolve=resolve,
            cost=cost,
            explanation=self._explain(action, ev, reach, resolve, cost, fatigue),
            timing_rationale=candidate.timing_rationale,
            reason_codes=tuple(reasons),
            components={
                "exposure": exposure,
                "value_at_stake": value,
                "p_reach": reach,
                "p_resolve": resolve,
                "urgency_decay": decay,
                "gross": gross,
                "cost": -cost,
                "fatigue": -fatigue,
            },
        )

    def _explain(
        self,
        action: str,
        ev: float,
        reach: float,
        resolve: float,
        cost: float,
        fatigue: float,
    ) -> str:
        # Attempt cost keeps its paise (it is often under ₹10, and rounding it
        # to whole rupees would make every channel look free); the expected
        # value is a rupee figure. Both go through the shared formatter so the
        # sentence does not carry two conventions, as it used to.
        return (
            f"{A.label(action).capitalize()}: {reach:.0%} chance of reaching them, "
            f"{resolve:.0%} of curing if reached, "
            f"{money_inr.inr_compact(cost + fatigue)} to try — "
            f"net {money_inr.inr(ev)}."
        )


def vector(
    features: AccountFeatures, trigger: Trigger, scored: ScoredAction, *, now: datetime
) -> dict[str, float | None]:
    """The model input vector, as it was at decision time.

    Written into the decision row for the same reason reco writes its own:
    rebuilding features from today's tables to train on a decision made in
    March leaks the outcome into the inputs. The DPD, the touch counts and the
    promise history have all moved since, and they moved partly *because* of
    the decision being labelled.
    """
    return {
        "rung": float(A.rung(scored.action)),
        "intrusiveness": A.spec(scored.action).intrusiveness,
        "exposure": features.exposure,
        "dpd": float(features.dpd) if features.dpd is not None else None,
        "bucket_curability": BUCKET_CURABILITY.get(features.bucket, 1.0),
        "ptp_keep_rate": features.ptp_keep_rate,
        "promises_total": float(features.promises_total),
        "touches_today": float(features.touches_today),
        "touches_7d": float(features.touches_7d),
        "digital_attempts_since_connect": float(
            features.digital_attempts_since_connect
        ),
        "connect_rate_channel": (
            features.connect_rate.get(scored.channel) if scored.channel else None
        ),
        "case_attempts": float(features.case_attempts),
        "this_action_tried": float(features.case_actions_tried.get(scored.action, 0)),
        "hours_since_last_attempt": features.hours_since_last_attempt,
        "trigger_age_hours": trigger.age_hours(now),
        "planned_delay_hours": (
            max(0.0, (scored.at - now).total_seconds() / 3600.0) if scored.at else None
        ),
        "p_reach": scored.p_reach,
        "p_resolve": scored.p_resolve,
        "cost": scored.cost,
        "open_bounce": 1.0 if features.open_bounce_id else 0.0,
        "risk_score": float(features.risk_score) if features.risk_score is not None else None,
        # --- who this borrower is -------------------------------------------
        # Added after the first reach and timing models both scored an AUC of
        # 0.50 on a corpus that demonstrably contained learnable heterogeneity.
        # The vector had the *account* and the *attempt* in it and almost
        # nothing about the borrower, so a model asked to tell two borrowers
        # apart had nothing to tell them apart with.
        #
        # The design note asks for segment-level uplift over "bucket × channel ×
        # contactability × cash-flow pattern". Bucket, channel and
        # contactability were already here. This is the cash-flow pattern.
        "secured": 1.0 if features.secured else 0.0,
        "promises_broken": float(features.promises_broken),
        "days_overdue": (
            float(features.days_overdue) if features.days_overdue is not None else None
        ),
        "open_disputes": float(features.open_dispute_count),
        "field_visits_90d": float(features.field_visits_90d),
        "on_hold": 1.0 if features.holds else 0.0,
        "has_email": 1.0 if features.has_email else 0.0,
        # The return code, one-hot. This is the single most diagnostic thing we
        # know about a delinquent account and it was not in the vector at all:
        # a borrower whose debit bounced for insufficient funds is a cash-flow
        # problem, one whose mandate was cancelled is a willingness problem, and
        # a model that cannot see the difference will price them the same.
        **{
            f"bounce_{reason}": (
                1.0 if (features.bounce_reason or "") == reason else 0.0
            )
            for reason in (
                "insufficient_funds",
                "mandate_expired",
                "account_closed",
                "technical",
            )
        },
        # Mandate state. Absent rather than zero where it is genuinely unknown:
        # an account with no mandate row and an account whose mandate we have
        # simply not read are different, and a model that reads both as 0 will
        # learn that mandates never help.
        "has_mandate": 1.0 if features.mandate_id else 0.0,
        "mandate_active": (
            1.0 if (features.mandate_status or "").lower() == "active" else 0.0
        ),
        "mandate_attempts_this_cycle": float(features.mandate_attempts_this_cycle),
        "salary_timing_gap_days": (
            float(features.salary_timing_gap_days)
            if features.salary_timing_gap_days is not None
            else None
        ),
    }


def build_scorer(name: str) -> Recommender:
    """Resolve a scorer by name, degrading to the EV scorer at every step.

    An unknown name must cost lift and never availability — this runs on the
    path that decides whether a borrower gets contacted at all.

    ``TREATMENT_LLM_RERANK=true`` wraps whatever was resolved. The wrapper can
    only reorder an already-approved list, so it is safe to layer on any of
    them.
    """
    from agent_core.treatment import config, rerank

    from agent_core.treatment import models

    resolved = (name or "").strip().lower()
    scorer: Recommender
    if resolved in {"", "ev", "rule"}:
        scorer = EVScorer()
    elif resolved in {"estimators", "ev+", "learned"}:
        # Whatever is fitted right now. ``models.build`` returns the EV scorer
        # unchanged when no artifact loads, so this name is safe to set before
        # any model exists — which is the point, because the alternative is an
        # env change coupled to a training run.
        scorer = models.build(EVScorer())
    else:
        logger.warning("unknown TREATMENT_SCORER=%r — falling back to ev", name)
        scorer = EVScorer()

    if config.llm_rerank_enabled():
        scorer = rerank.LLMReranker(scorer)
    return scorer
