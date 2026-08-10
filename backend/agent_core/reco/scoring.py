"""Ranking — the pluggable layer.

:class:`Recommender` is the seam a propensity model drops into later. The
contract is deliberately narrow: given features, live signals and an
already-vetted candidate list, return scored offers. A scorer cannot add a
product, cannot overturn an eligibility veto, and cannot reach the database.
That is what makes swapping one safe.

:class:`RuleScorer` ships first on purpose. It needs no training data, it is
deterministic, and every number it produces can be explained to a compliance
officer in one sentence — which matters more in a regulated pipeline than the
few points of lift a model would add before there is anything to train it on.

The normalisation rule that makes it honest: a signal we have no data for is
dropped from *both* the numerator and the denominator, rather than scored zero.
A customer with no payment history should not be ranked as though they had a
terrible one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol, Sequence

from agent_core.reco.candidates import Candidate
from agent_core.reco.config import Weights
from agent_core.reco.features import CallSignals, CustomerFeatures

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScoredOffer:
    product_id: str
    name: str
    score: float
    suggested_amount: float | None
    roi: str | None
    category: str | None
    reason_codes: tuple[str, ...]
    # One sentence for the rep and the audit log: why this ranked where it did,
    # in terms a compliance reviewer can check.
    explanation: str
    # One sentence for the *customer*, generated deterministically in talk.py.
    # Empty until a channel is known, since voice and chat render money
    # differently; engine.recommend fills it in.
    talk_track: str = ""
    # Populated only by a model that produces a calibrated probability.
    p_convert: float | None = None
    expected_value: float | None = None
    # Per-signal contributions, kept for the decision log so a surprising rank
    # can be explained after the fact instead of re-derived by hand.
    components: dict[str, float] = field(default_factory=dict)

    def to_log(self) -> dict[str, object]:
        return {
            "productId": self.product_id,
            "score": round(self.score, 4),
            "suggestedAmount": self.suggested_amount,
            "reasonCodes": list(self.reason_codes),
            "pConvert": self.p_convert,
            "expectedValue": self.expected_value,
            "components": {k: round(v, 4) for k, v in self.components.items()},
        }


class Recommender(Protocol):
    name: str
    version: str

    def score(
        self,
        features: CustomerFeatures,
        signals: CallSignals,
        candidates: Sequence[Candidate],
    ) -> list[ScoredOffer]: ...


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _topic_matches(topics: Sequence[str], c: Candidate) -> bool:
    """Did a knowledge-base topic the caller pulled up refer to this product?

    Compared on normalised substrings against the product's id, category and
    family, in both directions — corpus doc types ("topup_loan_policy") and
    product ids ("topup-loan") are named by different people at different times
    and neither is going to be renamed to suit the other. Conservative by
    design: a missed match only forgoes a bonus, a false one mis-ranks.
    """
    if not topics:
        return False
    haystack = {
        _norm(v)
        for v in (c.product_id, c.category, c.family)
        if v and len(str(v)) > 3
    }
    for raw in topics:
        topic = _norm(raw)
        if not topic or len(topic) <= 3:
            continue
        if any(h and (h in topic or topic in h) for h in haystack):
            return True
    return False


def _norm(value: object) -> str:
    return str(value or "").strip().lower().replace("-", " ").replace("_", " ")


def _round_amount(value: float) -> float:
    """Round to something a human would say out loud.

    "About one lakh forty thousand" is a sentence; "₹138,412.57" is a spreadsheet
    cell. The bot has to speak this number.
    """
    if value >= 100_000:
        return float(round(value / 10_000) * 10_000)
    if value >= 10_000:
        return float(round(value / 5_000) * 5_000)
    return float(round(value / 1_000) * 1_000)


def suggest_amount(candidate: Candidate, features: CustomerFeatures) -> float | None:
    """Derive an offer amount from headroom, clamped to the product's band.

    Nothing derived one before: ``estimated_value`` was whatever optional
    argument the model happened to pass, so it was frequently NULL, and NULL is
    what produced ₹NaN pipeline totals.
    """
    lo, hi = candidate.ticket_min, candidate.ticket_max

    headroom = None
    if features.sanctioned_amount is not None and features.outstanding is not None:
        headroom = max(0.0, features.sanctioned_amount - features.outstanding)

    # 60% of available headroom is a deliberately conservative anchor: the
    # number is spoken as indicative and must not read as a sanction.
    base = headroom * 0.6 if headroom else None
    if base is None or base <= 0:
        base = lo if lo is not None else hi
    if base is None:
        return None

    if lo is not None:
        base = max(base, lo)
    if hi is not None:
        base = min(base, hi)
    return _round_amount(base)


# ---------------------------------------------------------------------------
# Sub-scores.
#
# Module-level, not methods, because the propensity model has to vectorise
# exactly what the rule scorer reads. The surest way to rot a deployed model is
# to let the training pipeline and the serving path grow separate opinions
# about what "affordability" means, and that happens the moment this logic is
# reachable from only one of them.
# ---------------------------------------------------------------------------


def affordability(features: CustomerFeatures, c: Candidate) -> float | None:
    """How comfortably the product's entry ticket fits the customer.

    None when there is no sanctioned/outstanding pair to reason from — absent,
    not zero.
    """
    if features.sanctioned_amount is None or features.outstanding is None:
        return None
    headroom = max(0.0, features.sanctioned_amount - features.outstanding)
    floor = c.ticket_min
    if not floor:
        # No band configured: fall back to utilisation, where lower is better.
        # Still a real signal, just a blunter one.
        if features.utilization is None:
            return None
        return _clamp01(1.0 - features.utilization)
    if headroom <= 0:
        return 0.0
    return _clamp01(headroom / (floor * 2.0))


def credit_health(features: CustomerFeatures) -> float | None:
    signals: list[float] = []
    if features.dpd_worst is not None:
        # 90+ DPD is the floor; the curve between 0 and 90 is linear because
        # anything cleverer would be a model, and this is explicitly not one.
        signals.append(_clamp01(1.0 - (features.dpd_worst / 90.0)))
    if features.on_time_payment_ratio is not None:
        signals.append(_clamp01(features.on_time_payment_ratio))
    if not signals:
        return None
    return sum(signals) / len(signals)


def intent_match(signals: CallSignals, c: Candidate) -> float:
    if c.product_id in signals.product_mentions:
        return 1.0
    # The customer read up on this product family during the call. Weaker than
    # saying its name, stronger than generic product curiosity — someone asking
    # the KB about top-up eligibility has self-selected.
    if _topic_matches(signals.kb_topics_queried, c):
        return 0.85
    if signals.dominant_intent == "upsell_opportunity":
        return 0.8
    if signals.product_interest:
        return 0.65
    if signals.ptp_captured or signals.commitment_secured:
        # A cooperative call is a receptive one, even without product talk.
        return 0.45
    return 0.25


def exit_intent(features: CustomerFeatures) -> float:
    """0..1 — how strongly the customer looks like they are leaving.

    Two closure documents in 90 days is a decision, not a query. The general
    document count contributes far less: statements are routine servicing and
    would otherwise punish the most engaged customers.
    """
    if features.closure_documents_90d:
        return _clamp01(0.6 + 0.4 * (features.closure_documents_90d - 1))
    return _clamp01(features.document_requests_90d / 12.0)


def fatigue_score(features: CustomerFeatures) -> float:
    """0..1 — how recently and how often we have already pitched."""
    fatigue = _clamp01(features.offers_last_30d / 3.0)
    if features.prior_leads_lost > features.prior_leads_won:
        fatigue = _clamp01(fatigue + 0.2)
    return fatigue


class RuleScorer:
    """Transparent weighted-signal ranker."""

    name = "rule"
    version = "1.0.0"

    def __init__(self, weights: Weights) -> None:
        self._w = weights

    def score(
        self,
        features: CustomerFeatures,
        signals: CallSignals,
        candidates: Sequence[Candidate],
    ) -> list[ScoredOffer]:
        scored = [self._score_one(features, signals, c) for c in candidates]
        # Deterministic ordering: ties break on product id so two identical runs
        # cannot disagree, which offline replay depends on.
        scored.sort(key=lambda o: (-o.score, o.product_id))
        return scored

    # ---------------------------------------------------------------- signals

    def _score_one(
        self, features: CustomerFeatures, signals: CallSignals, c: Candidate
    ) -> ScoredOffer:
        w = self._w
        parts: list[tuple[str, float, float]] = []  # (name, value, weight)
        reasons: list[str] = []

        # 1. Affinity to what they already hold.
        parts.append(("affinity", _clamp01(c.affinity), w.affinity))
        if c.affinity >= 0.7:
            reasons.append("complements_existing_product")

        # 2. Affordability — is the ticket band within reach?
        afford = affordability(features, c)
        if afford is not None:
            parts.append(("affordability", afford, w.affordability))
            if afford >= 0.7:
                reasons.append("comfortable_headroom")
            elif afford <= 0.3:
                reasons.append("tight_headroom")

        # 3. Credit health — worst DPD across accounts, plus punctuality.
        credit = credit_health(features)
        if credit is not None:
            parts.append(("credit_health", credit, w.credit_health))
            if credit >= 0.8:
                reasons.append("clean_repayment_record")

        # 4. In-call intent — the strongest and cheapest signal there is.
        intent = intent_match(signals, c)
        parts.append(("in_call_intent", intent, w.in_call_intent))
        if c.product_id in signals.product_mentions:
            reasons.append("customer_asked_for_it")
        elif signals.product_interest:
            reasons.append("product_interest_in_call")

        # 5. Sentiment — a receptive caller, not just a non-hostile one.
        sentiment = _clamp01((signals.sentiment_current + 1.0) / 2.0)
        parts.append(("sentiment", sentiment, w.sentiment))
        if signals.sentiment_current > 0.15:
            reasons.append("positive_sentiment")

        # 6. Commercial priority — campaign push × product margin.
        campaign = c.campaign_priority if c.campaign_priority is not None else 0.5
        commercial = _clamp01(campaign * 0.5 + c.margin_score * 0.5)
        parts.append(("campaign_priority", commercial, w.campaign_priority))
        if c.campaign_priority is not None and c.campaign_priority >= 0.7:
            reasons.append("campaign_priority")

        total_weight = sum(weight for _, _, weight in parts)
        raw = (
            sum(value * weight for _, value, weight in parts) / total_weight
            if total_weight > 0
            else 0.0
        )

        # 7. Penalties — subtracted after normalisation so they can veto a
        # strong score rather than being averaged away by it.
        fatigue = fatigue_score(features)
        penalty = fatigue * w.fatigue_penalty
        if fatigue > 0:
            reasons.append("recently_contacted")

        leaving = exit_intent(features)
        exit_penalty = leaving * w.exit_intent_penalty
        if features.closure_documents_90d:
            reasons.append("closure_documents_requested")
        elif leaving > 0:
            # Routine servicing traffic. Worth a nudge down, not the same
            # label — a reason code that overstates its evidence is worse than
            # no reason code, because a rep reads it as fact.
            reasons.append("heavy_document_activity")

        final = _clamp01(raw - penalty - exit_penalty)
        components = {name: value for name, value, _ in parts}
        components["fatigue_penalty"] = -penalty
        components["exit_intent_penalty"] = -exit_penalty

        return ScoredOffer(
            product_id=c.product_id,
            name=c.name,
            score=final,
            suggested_amount=suggest_amount(c, features),
            roi=c.roi,
            category=c.category,
            reason_codes=tuple(reasons),
            explanation=self._explain(c, reasons, final),
            components=components,
        )

    def _explain(self, c: Candidate, reasons: Sequence[str], score: float) -> str:
        if not reasons:
            return f"{c.name}: no strong signal either way (score {score:.2f})."
        pretty = ", ".join(r.replace("_", " ") for r in reasons[:3])
        return f"{c.name}: {pretty} (score {score:.2f})."


def rule_score_from_vector(vec: "dict[str, float | None]", w: Weights) -> float:
    """The rule score, recomputed from a logged feature vector.

    Offline replay cannot call :meth:`RuleScorer.score` — that needs a live
    ``CustomerFeatures``, and rebuilding one today for a decision made in March
    leaks the outcome into the inputs. The vector logged at decision time is
    the only leakage-free record, so replay re-derives the score from it.

    This duplicates the combination in :meth:`RuleScorer._score_one`, which is
    a genuine drift risk — ``test_rule_score_matches_vector_score`` exists
    solely to fail when the two stop agreeing. Do not change one without the
    other.
    """
    parts: list[tuple[float, float]] = []

    def take(name: str, weight: float) -> None:
        value = vec.get(name)
        # Absent from both numerator and denominator, exactly as the live
        # scorer does — a signal we lack must not read as a signal of zero.
        if value is not None:
            parts.append((_clamp01(float(value)), weight))

    take("affinity", w.affinity)
    take("affordability", w.affordability)
    take("credit_health", w.credit_health)
    take("in_call_intent", w.in_call_intent)
    take("sentiment", w.sentiment)

    # The live scorer blends campaign priority with margin before weighting,
    # and substitutes a neutral 0.5 for a product with no campaign.
    campaign = vec.get("campaign_priority")
    margin = vec.get("margin_score")
    if margin is not None:
        blended = _clamp01((0.5 if campaign is None else _clamp01(float(campaign))) * 0.5
                           + _clamp01(float(margin)) * 0.5)
        parts.append((blended, w.campaign_priority))

    total = sum(weight for _, weight in parts)
    raw = sum(value * weight for value, weight in parts) / total if total > 0 else 0.0

    penalty = float(vec.get("fatigue") or 0.0) * w.fatigue_penalty
    exit_penalty = float(vec.get("exit_intent") or 0.0) * w.exit_intent_penalty
    return _clamp01(raw - penalty - exit_penalty)


def build_scorer(
    name: str, weights: Weights, *, rule_weight: float | None = None
) -> Recommender:
    """Resolve a scorer by name, degrading to the rule scorer at every step.

    The degradation ladder, in order:

        hybrid → propensity → rule
        propensity → rule           (artifact missing, stale, or mismatched)
        anything unrecognised → rule

    An unknown name, a deleted artifact and a model that raises must all cost
    lift and never availability. This function is on the audio path of a live
    phone call; there is no failure here worth dropping a customer for.

    ``RECO_LLM_RERANK=true`` wraps whatever was resolved. The wrapper can only
    reorder an approved list, so it is safe to layer on any of them.

    ``rule_weight`` overrides the hybrid blend for one call, so an A/B arm can
    pin its own blend without changing it for every other arm in the process.
    """
    from agent_core.reco import models

    resolved = (name or "").strip().lower()
    scorer: Recommender

    if resolved in {"", "rule"}:
        scorer = RuleScorer(weights)
    elif resolved in {"propensity", "model"}:
        scorer = models.load_propensity(weights) or RuleScorer(weights)
    elif resolved == "hybrid":
        propensity = models.load_propensity(weights)
        rule = RuleScorer(weights)
        blend = models.hybrid_rule_weight() if rule_weight is None else rule_weight
        scorer = (
            models.HybridScorer(rule, propensity, blend) if propensity is not None else rule
        )
    else:
        logger.warning("unknown RECO_SCORER=%r — falling back to the rule scorer", name)
        scorer = RuleScorer(weights)

    if models.llm_rerank_enabled():
        scorer = models.LLMReranker(scorer)
    return scorer
