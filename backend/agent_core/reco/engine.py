"""Orchestration — the only entry point callers need.

    features → candidates → veto → score → arbitrate → log

Two properties this function must hold, because it runs on the audio path of a
live phone call:

* **It never raises.** Any failure degrades to "no offer", logged. A
  recommender that can hang up on a customer is worse than no recommender.
* **It never blocks for long.** Everything is a handful of indexed reads; the
  caller runs it in a thread so the pipeline is not stalled either way.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
from typing import Any

from agent_core.reco import (
    arbitration,
    candidates as candidates_mod,
    config,
    decisions,
    talk,
    vectorize,
)
from agent_core.reco.features import (
    CallSignals,
    CustomerFeatures,
    FeatureProvider,
    SCHEMA_VERSION,
    build_features,
)
from agent_core.reco.scoring import ScoredOffer, build_scorer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecommendationResult:
    """What the tool layer hands the model.

    ``offers`` is empty whenever ``suppressed`` is true. Both are returned so a
    caller can distinguish "nothing to say" from "told not to say it", which
    the close probe needs in order to decide between asking a bare "anything
    else?" and folding an offer into the question.
    """

    offers: list[ScoredOffer] = field(default_factory=list)
    suppressed: bool = True
    reason: str | None = None
    decision_id: str | None = None
    mode: str = config.MODE_SHADOW
    latency_ms: int = 0
    variant: str | None = None

    @property
    def top(self) -> ScoredOffer | None:
        return self.offers[0] if self.offers else None

    def to_tool_payload(self) -> dict[str, Any]:
        """Compact, model-facing shape. Scores and feature internals stay out:
        the model's job is to phrase the offer, not to second-guess the rank."""
        return {
            "offers": [
                {
                    "offerId": f"{self.decision_id}:{o.product_id}" if self.decision_id else o.product_id,
                    "productId": o.product_id,
                    "productName": o.name,
                    "suggestedAmount": o.suggested_amount,
                    "roi": o.roi,
                    "talkTrack": o.talk_track,
                    "reasonCodes": list(o.reason_codes),
                }
                for o in self.offers
            ],
            "suppressed": self.suppressed,
            **({"suppressionReason": self.reason} if self.reason else {}),
        }


def recommend(
    *,
    customer_id: str,
    interaction_id: str | None = None,
    channel: str = "voice",
    live: CallSignals | None = None,
    provider: FeatureProvider | None = None,
    force_mode: str | None = None,
    variant: str | None = None,
) -> RecommendationResult:
    """Run the pipeline. Never raises.

    ``variant`` is the per-session A/B override (``session.extra["recoVariant"]``).
    When absent, the customer is bucketed deterministically by ``RECO_AB_SPLIT``
    so the same customer always lands in the same arm — a customer who is
    pitched by the rule scorer on Monday and the model on Thursday belongs to
    neither, and every number computed from that split is noise.
    """
    started = time.perf_counter()

    # Explicit override beats the split; the split beats the process default.
    # The override exists so the Sandbox can force an arm for a single call
    # without dragging every other customer into it.
    arm = config.resolve_variant(variant) or config.assign_variant(customer_id)
    mode = (force_mode or (arm.mode if arm and arm.mode else None) or config.mode()).strip().lower()
    arm_name = arm.name if arm else None

    if mode == config.MODE_OFF:
        return RecommendationResult(
            suppressed=True, reason="engine_off", mode=mode, variant=arm_name
        )

    try:
        return _recommend(
            customer_id=customer_id,
            interaction_id=interaction_id,
            channel=channel,
            live=live,
            provider=provider,
            mode=mode,
            arm=arm,
            started=started,
        )
    except Exception:
        # The audio path must survive anything this module does wrong.
        logger.exception("recommendation failed for customer=%s", customer_id)
        return RecommendationResult(
            suppressed=True,
            reason="engine_error",
            mode=mode,
            variant=arm_name,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _recommend(
    *,
    customer_id: str,
    interaction_id: str | None,
    channel: str,
    live: CallSignals | None,
    provider: FeatureProvider | None,
    mode: str,
    arm: config.Variant | None,
    started: float,
) -> RecommendationResult:
    import db

    policy = config.policy()
    arm_name = arm.name if arm else None

    # One connection for the whole read phase. Feature building used to open
    # its own, so every recommendation checked out two — and at four concurrent
    # calls against a pool of five that alone pushed p99 past the 150ms budget.
    with db.engine.connect() as conn:
        features, signals = build_features(
            customer_id,
            interaction_id=interaction_id,
            channel=channel,
            live=live,
            provider=provider,
            conn=conn,
        )

        pool, excluded = candidates_mod.generate(
            conn,
            features=features,
            channel=channel,
            decline_cooldown_days=policy.decline_cooldown_days,
            family_cooldown_days=policy.family_cooldown_days,
        )
        vetted, vetoed = _apply_eligibility(
            conn, customer_id=customer_id, channel=channel, pool=pool
        )
        # Collection / upsell separation. Read here rather than folded into
        # CustomerFeatures so the feature schema version — and therefore every
        # trained artifact scored against it — is unaffected by a gate that is
        # not a feature.
        hold_reason = _collections_hold(conn, customer_id)
    excluded.update(vetoed)

    scorer = build_scorer(
        (arm.scorer if arm and arm.scorer else None) or config.scorer_name(),
        config.weights(),
        rule_weight=(arm.rule_weight if arm else None),
    )
    scored = scorer.score(features, signals, vetted)

    verdict = arbitration.arbitrate(
        features=features,
        signals=signals,
        offers=scored,
        policy=policy,
        channel=channel,
        external_suppression=hold_reason,
    )

    # Phrased only for what survived arbitration. Generating a talk track for a
    # suppressed offer would put a sentence about an offer we decided not to
    # make into the decision log, one copy-paste away from being said.
    verdict = replace(
        verdict,
        offers=[
            replace(
                o,
                talk_track=talk.talk_track(
                    o, channel=channel, preferred_window=features.preferred_window
                ),
            )
            for o in verdict.offers
        ],
    )

    latency_ms = int((time.perf_counter() - started) * 1000)
    top = verdict.offers[0] if verdict.offers else None

    decision_id = decisions.record(
        customer_id=customer_id,
        interaction_id=interaction_id,
        channel=channel,
        mode=mode,
        variant=arm_name,
        recommender=scorer.name,
        recommender_version=scorer.version,
        feature_schema_version=SCHEMA_VERSION,
        features={**features.to_log(), "call": signals.to_log()},
        # Log the full ranked list, not just the winner: the counterfactual is
        # what offline evaluation compares against.
        candidates=_candidate_log(features, signals, vetted, scored),
        excluded=excluded,
        chosen_product_id=top.product_id if top else None,
        suggested_amount=top.suggested_amount if top else None,
        score=top.score if top else None,
        suppression_reason=verdict.reason,
        latency_ms=latency_ms,
    )

    # Shadow mode scores and logs exactly as live does, then declines to speak.
    # Same code path, so what ships to live is what was measured.
    if mode == config.MODE_SHADOW:
        return RecommendationResult(
            offers=[],
            suppressed=True,
            reason="shadow_mode",
            decision_id=decision_id,
            mode=mode,
            variant=arm_name,
            latency_ms=latency_ms,
        )

    return RecommendationResult(
        offers=verdict.offers,
        suppressed=verdict.suppressed,
        reason=verdict.reason,
        decision_id=decision_id,
        mode=mode,
        variant=arm_name,
        latency_ms=latency_ms,
    )


def _candidate_log(
    features: CustomerFeatures,
    signals: CallSignals,
    vetted: list[Any],
    scored: list[ScoredOffer],
) -> list[dict[str, Any]]:
    """Ranked candidates, each with the model vector that produced it.

    The vector is written *here*, at decision time, because it cannot be
    recovered later. Rebuilding features from today's tables to train on a
    decision made in March would leak the outcome straight into the inputs —
    the DPD, the lead count and the offer history have all moved since, and
    they moved partly *because* of the decision being labelled. Logging the
    vector as it was is the difference between a trainable corpus and a model
    that scores 0.95 offline and nothing in production.

    ``RECO_LOG_VECTORS=false`` turns it off if row size ever becomes a problem;
    the consequence is simply that those rows cannot be trained on.
    """
    rows = [o.to_log() for o in scored]
    if not config.log_vectors():
        return rows

    by_id = {c.product_id: c for c in vetted}
    for row in rows:
        candidate = by_id.get(row.get("productId"))
        if candidate is None:
            continue
        try:
            row["vector"] = {
                k: (round(v, 6) if v is not None else None)
                for k, v in vectorize.vector(features, signals, candidate).items()
            }
        except Exception:
            # A vector we cannot build costs one training row, not the call.
            logger.exception("feature vector logging failed for %s", row.get("productId"))
    return rows


def _collections_hold(conn: Any, customer_id: str) -> str | None:
    """A hardship / complaint / bereavement / legal hold, or None.

    Delegated to the treatment engine so there is one definition of the
    separation rather than two that drift. Never raises — but an unreadable
    hold table returns a suppression reason rather than None, because failing
    open here means pitching a product to someone in hardship.
    """
    try:
        from agent_core.treatment import policy as treatment_policy

        return treatment_policy.suppresses_upsell(conn, customer_id)
    except Exception:
        logger.exception("collections hold lookup failed for %s", customer_id)
        return "treatment_hold_unreadable"


def _apply_eligibility(
    conn: Any, *, customer_id: str, channel: str, pool: list[Any]
) -> tuple[list[Any], dict[str, str]]:
    """Run the existing compliance veto over each candidate.

    Reuses capture.evaluate_product_eligibility rather than reimplementing the
    rules, so there is exactly one definition of "may we offer this" in the
    system — the bot, the API and the engine cannot drift apart.
    """
    import capture

    kept: list[Any] = []
    vetoed: dict[str, str] = {}
    # Hoisted out of the loop: accounts, consent and DND are customer-level and
    # cannot change between candidates. Re-reading them per product turned an
    # 8-product catalog into ~32 queries on the audio path of a live call.
    try:
        facts = capture.customer_eligibility_facts(conn, customer_id)
    except Exception:
        logger.exception("eligibility facts unavailable for %s", customer_id)
        return [], {c.product_id: "eligibility_error" for c in pool}

    for candidate in pool:
        try:
            flags = capture.evaluate_product_eligibility(
                conn,
                customer_id=customer_id,
                product_id=candidate.product_id,
                channel=channel,
                facts=facts,
            )
            block = capture.eligibility_blocks_capture(flags)
        except Exception:
            # Fail closed: an unevaluable product is not offered.
            logger.exception(
                "eligibility veto errored for %s/%s", customer_id, candidate.product_id
            )
            vetoed[candidate.product_id] = "eligibility_error"
            continue
        if block:
            vetoed[candidate.product_id] = f"eligibility:{block}"[:200]
            continue
        kept.append(candidate)
    return kept, vetoed


def present(decision_id: str | None, product_id: str | None = None) -> None:
    """Mark a logged decision as actually spoken, and consume campaign quota."""
    if not decision_id:
        return
    decisions.mark_presented(decision_id)
    if not product_id:
        return
    try:
        import db

        with db.engine.begin() as conn:
            campaign = conn.execute(
                _campaign_lookup(), {"pid": product_id}
            ).fetchone()
            if campaign:
                arbitration.reserve_campaign_quota(conn, campaign[0])
    except Exception:
        logger.exception("campaign quota reservation failed for %s", product_id)


def _campaign_lookup():
    from sqlalchemy import text

    return text(
        """
        SELECT id FROM product_campaigns
        WHERE product_id = :pid AND enabled IS TRUE
          AND (starts_at IS NULL OR starts_at <= now())
          AND (ends_at IS NULL OR ends_at >= now())
        ORDER BY priority DESC, id
        LIMIT 1
        """
    )
