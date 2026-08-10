"""The (features, signals, candidate) → numeric vector map.

This module exists so that training and serving cannot disagree. A propensity
model is only as good as the guarantee that the number called ``affordability``
at 3am in production is computed by the same code that computed it when the
model was fitted. Every other arrangement drifts, silently, and the first
symptom is a model that is merely mediocre rather than obviously broken.

Two rules:

* **Names are frozen.** A key in :data:`FEATURE_NAMES` is part of the artifact
  contract. Rename one and every model trained before the rename is scoring a
  different quantity under the same label. Add to the end instead; the loader
  ignores names an artifact does not know and imputes ones it expects but this
  build no longer emits.
* **Missing stays missing.** ``None`` is returned as ``None``, not as zero. The
  model applies its own recorded mean for that column, which is the only
  honest thing to do with an unobserved value in a linear model.
"""

from __future__ import annotations

from typing import Any

from agent_core.reco import scoring
from agent_core.reco.candidates import Candidate
from agent_core.reco.features import CallSignals, CustomerFeatures

# Bumped when the *meaning* of an existing name changes. An artifact whose
# vector_version does not match is refused rather than silently mis-scored.
VECTOR_VERSION = "v1"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _norm(value: float | None, cap: float) -> float | None:
    """Scale to 0..1 against a cap, preserving None."""
    if value is None:
        return None
    return _clamp01(float(value) / cap)


def vector(
    features: CustomerFeatures,
    signals: CallSignals,
    candidate: Candidate,
) -> dict[str, float | None]:
    """One row. Values are 0..1 where bounded, ``None`` where unobserved."""
    won = features.prior_leads_won
    lost = features.prior_leads_lost
    decided = won + lost

    return {
        # --- the rule scorer's own sub-scores, verbatim -------------------
        "affinity": _clamp01(candidate.affinity),
        "affordability": scoring.affordability(features, candidate),
        "credit_health": scoring.credit_health(features),
        "in_call_intent": scoring.intent_match(signals, candidate),
        "sentiment": _clamp01((signals.sentiment_current + 1.0) / 2.0),
        "fatigue": scoring.fatigue_score(features),
        "exit_intent": scoring.exit_intent(features),
        # --- catalog / commercial ----------------------------------------
        "margin_score": _clamp01(candidate.margin_score),
        "campaign_priority": (
            _clamp01(candidate.campaign_priority)
            if candidate.campaign_priority is not None
            else None
        ),
        "has_campaign": 1.0 if candidate.campaign_id else 0.0,
        # --- raw customer state the sub-scores compress away --------------
        # The rule scorer folds DPD into credit_health; a model may find the
        # raw value carries signal the fold discards.
        "dpd_worst": _norm(features.dpd_worst, 180.0),
        "utilization": _clamp01(features.utilization) if features.utilization is not None else None,
        "relationship_months": _norm(features.relationship_months, 120.0),
        "account_count": _norm(float(features.account_count), 5.0),
        "months_since_last_payment": _norm(features.months_since_last_payment, 24.0),
        "open_disputes": _norm(float(features.open_dispute_count), 3.0),
        "offers_last_30d": _norm(float(features.offers_last_30d), 5.0),
        # Win rate is None until they have decided at least one lead — a
        # customer with no history is not a customer with a 0% win rate.
        "prior_win_rate": (won / decided) if decided else None,
        # --- in-call ------------------------------------------------------
        "product_mentioned": 1.0 if candidate.product_id in signals.product_mentions else 0.0,
        "kb_topic_match": (
            1.0 if scoring._topic_matches(signals.kb_topics_queried, candidate) else 0.0
        ),
        "commitment_secured": 1.0 if (signals.commitment_secured or signals.ptp_captured) else 0.0,
        "customer_turns": _norm(float(signals.customer_turns), 30.0),
        "sentiment_trend": _clamp01((signals.sentiment_trend + 1.0) / 2.0),
    }


# Frozen order. Artifacts store their own name list, so this is the *current*
# build's view, used when training and as the default when an artifact omits it.
FEATURE_NAMES: tuple[str, ...] = tuple(
    vector(
        CustomerFeatures(customer_id="_"),
        CallSignals(),
        Candidate(
            product_id="_",
            name="_",
            category=None,
            family=None,
            description=None,
            ticket_min=None,
            ticket_max=None,
            roi=None,
            roi_numeric=None,
            margin_score=0.5,
            affinity=0.5,
            campaign_id=None,
            campaign_priority=None,
        ),
    )
)


def as_row(
    features: CustomerFeatures,
    signals: CallSignals,
    candidate: Candidate,
    names: "tuple[str, ...] | list[str]" = FEATURE_NAMES,
    means: "dict[str, float] | None" = None,
) -> list[float]:
    """Dense row in ``names`` order, imputing missing values from ``means``.

    A name the artifact expects but this build no longer produces imputes too,
    rather than raising: a model outliving a feature is a reason to retrain,
    not a reason to drop the offer path on the floor mid-call.
    """
    raw: dict[str, Any] = vector(features, signals, candidate)
    means = means or {}
    out: list[float] = []
    for name in names:
        value = raw.get(name)
        if value is None:
            value = means.get(name, 0.5)
        out.append(float(value))
    return out
