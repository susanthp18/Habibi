"""Model-backed recommenders behind the :class:`Recommender` protocol.

Three of them, in the order they earn their way in:

* :class:`PropensityScorer` — a calibrated linear model loaded from a JSON
  artifact. Produces ``p_convert`` and therefore ``expected_value``, which is
  the number the business actually wants ranked.
* :class:`HybridScorer` — a blend of rule and propensity, with the blend weight
  annealed as the model earns confidence. This is what a real rollout uses:
  going straight from hand-tuned weights to a fresh model is a step change
  nobody can attribute.
* :class:`LLMReranker` — a wrapper that may reorder an *already approved* list
  and rewrite the talk track. It cannot add a product, cannot resurrect a
  vetoed one, and cannot change an amount.

**Why a linear model and not a gradient-boosted one.** A logistic regression
with recorded coefficients is a 3KB JSON file this service can load, explain
line by line to a regulator, and diff between versions. It adds no dependency
to an image that sits on the audio path, and it is a genuinely strong baseline
on a few thousand rows — which is all `offer_decisions` will have for months.
The artifact format carries a ``type`` field precisely so a GBM can replace it
later without touching anything in this file but :func:`_predict`.

**The fallback chain is the point.** Missing artifact, stale artifact, version
mismatch, malformed JSON, or an exception mid-scoring all degrade to the rule
scorer, warned once per process. A recommender that can fail a phone call is
worse than a recommender that is merely less accurate.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from agent_core.reco import vectorize
from agent_core.reco.candidates import Candidate
from agent_core.reco.config import Weights
from agent_core.reco.features import CallSignals, CustomerFeatures, SCHEMA_VERSION
from agent_core.reco.scoring import Recommender, RuleScorer, ScoredOffer

logger = logging.getLogger(__name__)

# One warning per distinct reason per process. A model that is missing is
# missing on every call, and a log line per call would bury the incident it is
# trying to report.
_warned: set[str] = set()
_warn_lock = threading.Lock()


def _warn_once(key: str, message: str, *args: Any) -> None:
    with _warn_lock:
        if key in _warned:
            return
        _warned.add(key)
    logger.warning(message, *args)


def _reset_warnings() -> None:
    """Test hook — production never calls this."""
    with _warn_lock:
        _warned.clear()


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelArtifact:
    name: str
    version: str
    kind: str
    feature_names: tuple[str, ...]
    coefficients: tuple[float, ...]
    intercept: float
    means: dict[str, float]
    # Platt scaling applied to the logit: p = sigmoid(a * logit + b). Identity
    # (1, 0) when the trainer did not calibrate, which is honest rather than
    # pretending the raw output is a probability.
    calibration_a: float = 1.0
    calibration_b: float = 0.0
    # Conversion rate of the training population. Load-bearing: it is what
    # makes a probability comparable to the rule scorer's 0..1 confidence.
    base_rate: float = 0.1
    trained_at: datetime | None = None
    n_samples: int = 0
    vector_version: str = vectorize.VECTOR_VERSION
    feature_schema_version: str = SCHEMA_VERSION

    def age_days(self) -> float | None:
        if self.trained_at is None:
            return None
        return (datetime.now(timezone.utc) - self.trained_at).total_seconds() / 86400.0

    def predict(self, vec: dict[str, float | None]) -> float:
        """Calibrated conversion probability from a feature vector.

        Takes a raw vector rather than (features, signals, candidate) so that
        offline replay can score decisions from the vectors logged at the time,
        which is the only leakage-free way to evaluate a historical decision.
        """
        row = [
            float(vec.get(n) if vec.get(n) is not None else self.means.get(n, 0.5))
            for n in self.feature_names
        ]
        logit = self.intercept + sum(x * c for x, c in zip(row, self.coefficients))
        return _sigmoid(self.calibration_a * logit + self.calibration_b)

    def comparable_score(self, p: float) -> float:
        """Probability mapped onto the rule scorer's 0..1 confidence scale."""
        denominator = p + self.base_rate
        return max(0.0, min(1.0, p / denominator)) if denominator > 0 else 0.0


def _parse_trained_at(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        logger.warning("model artifact has unparseable trainedAt=%r", raw)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_artifact(path: str | Path) -> ModelArtifact | None:
    """Read and validate an artifact. Returns None (never raises) on any fault.

    Validation is strict on purpose: a truncated or hand-edited artifact that
    scores *slightly* wrong is far more dangerous than one that refuses to
    load, because nothing downstream will notice.
    """
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _warn_once(f"missing:{p}", "no propensity artifact at %s — using the rule scorer", p)
        return None
    except (OSError, json.JSONDecodeError) as exc:
        _warn_once(f"unreadable:{p}", "propensity artifact at %s is unreadable (%s)", p, exc)
        return None

    if not isinstance(raw, dict):
        _warn_once(f"shape:{p}", "propensity artifact at %s is not an object", p)
        return None

    names = raw.get("featureNames") or list(vectorize.FEATURE_NAMES)
    coefficients = raw.get("coefficients")
    if not isinstance(names, list) or not isinstance(coefficients, list):
        _warn_once(f"fields:{p}", "propensity artifact at %s lacks featureNames/coefficients", p)
        return None
    if len(names) != len(coefficients):
        _warn_once(
            f"len:{p}",
            "propensity artifact at %s has %d names for %d coefficients",
            p,
            len(names),
            len(coefficients),
        )
        return None

    try:
        coefficient_values = tuple(float(c) for c in coefficients)
        intercept = float(raw.get("intercept", 0.0))
        cal = raw.get("calibration") or {}
        cal_a = float(cal.get("a", 1.0))
        cal_b = float(cal.get("b", 0.0))
        means = {str(k): float(v) for k, v in (raw.get("means") or {}).items()}
        # Clamped away from 0 and 1: base_rate is a divisor below, and a
        # trainer that recorded 0.0 (no positives in the holdout) would
        # otherwise make every offer look infinitely above average.
        base_rate = min(0.9, max(0.001, float((raw.get("metrics") or {}).get("baseRate") or 0.1)))
    except (TypeError, ValueError) as exc:
        _warn_once(f"numeric:{p}", "propensity artifact at %s has non-numeric fields (%s)", p, exc)
        return None

    artifact = ModelArtifact(
        name=str(raw.get("name") or "propensity"),
        version=str(raw.get("version") or "unversioned"),
        kind=str(raw.get("type") or "logistic"),
        feature_names=tuple(str(n) for n in names),
        coefficients=coefficient_values,
        intercept=intercept,
        means=means,
        calibration_a=cal_a,
        calibration_b=cal_b,
        base_rate=base_rate,
        trained_at=_parse_trained_at(raw.get("trainedAt")),
        n_samples=int(raw.get("nSamples") or 0),
        vector_version=str(raw.get("vectorVersion") or vectorize.VECTOR_VERSION),
        feature_schema_version=str(raw.get("featureSchemaVersion") or SCHEMA_VERSION),
    )

    if artifact.kind != "logistic":
        _warn_once(
            f"kind:{p}",
            "propensity artifact at %s is type=%r which this build cannot score",
            p,
            artifact.kind,
        )
        return None
    # Compatibility is decided here, in one place, so that every caller —
    # the serving path, offline replay, an operator poking at a file — gets the
    # same verdict on the same artifact.
    if artifact.vector_version != vectorize.VECTOR_VERSION:
        # The same feature *names* now mean something different. Scoring anyway
        # would be worse than not scoring: it would look like it worked.
        _warn_once(
            f"vector:{p}",
            "propensity artifact %s was fitted on vector %s, this build emits %s — refusing",
            artifact.version,
            artifact.vector_version,
            vectorize.VECTOR_VERSION,
        )
        return None
    if artifact.feature_schema_version != SCHEMA_VERSION:
        _warn_once(
            f"schema:{p}",
            "propensity artifact %s expects feature schema %s, this build emits %s — refusing",
            artifact.version,
            artifact.feature_schema_version,
            SCHEMA_VERSION,
        )
        return None
    return artifact


def _model_path() -> str:
    return (os.getenv("RECO_MODEL_PATH") or "models/propensity.json").strip()


def _max_age_days() -> float:
    raw = (os.getenv("RECO_MODEL_MAX_AGE_DAYS") or "").strip()
    if not raw:
        return 90.0
    try:
        return float(raw)
    except ValueError:
        logger.warning("RECO_MODEL_MAX_AGE_DAYS=%r is not a number — using 90", raw)
        return 90.0


def _sigmoid(x: float) -> float:
    # Split on the sign so neither branch overflows exp() on an extreme logit.
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


# ---------------------------------------------------------------------------
# Scorers
# ---------------------------------------------------------------------------


class PropensityScorer:
    """Calibrated probability of conversion, ranked by expected value.

    Ordering is by expected value where an amount is known: a 20% chance on
    ₹5 lakh beats a 45% chance on ₹25,000, and ranking on probability alone
    gets that backwards.

    **``score`` is not the raw probability, deliberately.** Every threshold in
    config — ``RECO_MIN_SCORE`` above all — was calibrated against the rule
    scorer's 0..1 weighted confidence. Emitting a raw probability with a 16%
    base rate under the same name would mean that switching ``RECO_SCORER`` to
    ``propensity`` silently suppresses every offer in the system against a
    threshold of 0.35, and the symptom would be "the engine went quiet",
    diagnosed a week later.

    So the probability is reported on a comparable scale::

        score = p / (p + base_rate)

    which is monotone in ``p`` (the ranking is unchanged), sits at 0.5 when the
    customer is exactly average, and rises towards 1 as they beat the base
    rate. "How much better than a typical prospect is this" is the same
    question the rule scorer's confidence answers, so one threshold governs
    both. The raw calibrated probability stays on ``p_convert``, which is what
    ``expected_value`` and every report should use.
    """

    def __init__(self, artifact: ModelArtifact, weights: Weights) -> None:
        self._artifact = artifact
        self._fallback = RuleScorer(weights)
        self.name = artifact.name
        self.version = artifact.version

    def score(
        self,
        features: CustomerFeatures,
        signals: CallSignals,
        candidates: Sequence[Candidate],
    ) -> list[ScoredOffer]:
        # The rule pass runs regardless: it supplies the amount, the reason
        # codes and the explanation, none of which a coefficient vector has.
        base = self._fallback.score(features, signals, candidates)
        by_id = {c.product_id: c for c in candidates}

        try:
            scored = [self._score_one(features, signals, by_id[o.product_id], o) for o in base]
        except Exception:
            # Never let a scoring fault reach the audio path. The rule ranking
            # is already computed and is a perfectly good answer.
            logger.exception("propensity scoring failed — falling back to rule ranking")
            _warn_once("predict", "propensity scoring raised; serving rule ranking")
            return base

        scored.sort(key=lambda o: (-(o.expected_value or o.score), -o.score, o.product_id))
        return scored

    def _score_one(
        self,
        features: CustomerFeatures,
        signals: CallSignals,
        candidate: Candidate,
        base: ScoredOffer,
    ) -> ScoredOffer:
        a = self._artifact
        # Routed through the same predict() offline replay uses, so a model
        # cannot score one way in production and another in evaluation.
        p = a.predict(vectorize.vector(features, signals, candidate))

        expected = None
        if base.suggested_amount:
            expected = p * candidate.margin_score * base.suggested_amount

        comparable = a.comparable_score(p)

        components = dict(base.components)
        components["p_convert"] = p
        components["base_rate"] = a.base_rate
        components["rule_score"] = base.score
        return replace(
            base,
            score=max(0.0, min(1.0, comparable)),
            p_convert=p,
            expected_value=expected,
            components=components,
            reason_codes=base.reason_codes + (f"model:{a.version}",),
            explanation=(
                f"{candidate.name}: {p:.0%} modelled conversion"
                + (f", expected value {expected:,.0f}" if expected else "")
                + f" ({a.name} {a.version})."
            ),
        )


class HybridScorer:
    """``final = w·rule + (1−w)·propensity``.

    ``w`` starts at 1.0 (pure rule) and is annealed down as the model earns
    confidence — a rollout knob, not a hyperparameter. Ranking by the blend
    rather than switching outright is what makes a regression attributable:
    a step change from hand weights to a model moves everything at once.
    """

    def __init__(self, rule: RuleScorer, propensity: PropensityScorer, rule_weight: float) -> None:
        self._rule = rule
        self._propensity = propensity
        self._w = max(0.0, min(1.0, rule_weight))
        self.name = "hybrid"
        self.version = f"{propensity.version}+rule@{self._w:.2f}"

    def score(
        self,
        features: CustomerFeatures,
        signals: CallSignals,
        candidates: Sequence[Candidate],
    ) -> list[ScoredOffer]:
        rule_scores = {o.product_id: o.score for o in self._rule.score(features, signals, candidates)}
        model = self._propensity.score(features, signals, candidates)

        blended: list[ScoredOffer] = []
        for offer in model:
            rule_score = rule_scores.get(offer.product_id, offer.score)
            final = self._w * rule_score + (1.0 - self._w) * offer.score
            components = dict(offer.components)
            components["rule_score"] = rule_score
            components["blend_rule_weight"] = self._w
            blended.append(replace(offer, score=max(0.0, min(1.0, final)), components=components))

        blended.sort(key=lambda o: (-o.score, o.product_id))
        return blended


class LLMReranker:
    """Reorders an approved shortlist and rewrites its talk track.

    The narrow contract is the whole design. The model sees only offers that
    already cleared candidate generation, the eligibility veto and scoring; it
    returns ids, and **any id not in the input set is dropped and logged**. It
    cannot introduce a product, cannot resurrect a vetoed one, and cannot touch
    an amount. This is the bounded, defensible answer to "just use an LLM":
    the LLM does language, the deterministic layers do selection.

    Any failure — timeout, malformed JSON, empty result — returns the base
    ranking unchanged.
    """

    def __init__(self, base: Recommender, *, top_k: int = 3) -> None:
        self._base = base
        self._top_k = max(1, top_k)
        self.name = f"llm_rerank({getattr(base, 'name', 'base')})"
        self.version = getattr(base, "version", "1.0.0")

    def score(
        self,
        features: CustomerFeatures,
        signals: CallSignals,
        candidates: Sequence[Candidate],
    ) -> list[ScoredOffer]:
        base = self._base.score(features, signals, candidates)
        if len(base) < 2:
            # Nothing to reorder. Not worth a network round trip on the audio
            # path to confirm that a one-item list is already sorted.
            return base

        head, tail = base[: self._top_k], base[self._top_k :]
        order = self._ask(head, signals)
        if not order:
            return base

        by_id = {o.product_id: o for o in head}
        reordered = [by_id.pop(pid) for pid in order if pid in by_id]
        # Anything the model omitted keeps its original relative position
        # rather than being silently dropped from the shortlist.
        reordered.extend(o for o in head if o.product_id in by_id)
        return reordered + tail

    def _ask(self, head: Sequence[ScoredOffer], signals: CallSignals) -> list[str]:
        allowed = {o.product_id for o in head}
        payload = [
            {
                "productId": o.product_id,
                "productName": o.name,
                "reasonCodes": list(o.reason_codes),
                "suggestedAmount": o.suggested_amount,
            }
            for o in head
        ]
        prompt = (
            "You are ranking pre-approved offers for a collections call. "
            "Reorder them by how relevant each is to what the customer has "
            "said in this conversation.\n\n"
            f"Conversation intents: {', '.join(signals.intents_seen) or 'none recorded'}\n"
            f"Products the customer named: {', '.join(signals.product_mentions) or 'none'}\n"
            f"Knowledge-base topics they asked about: "
            f"{', '.join(signals.kb_topics_queried) or 'none'}\n"
            f"Current sentiment: {signals.sentiment_current:+.2f}\n\n"
            f"Offers: {json.dumps(payload)}\n\n"
            'Reply with JSON only: {"order": ["productId", ...]}. '
            "Use only the product ids given. Do not invent products, do not "
            "add commentary, do not change any amount."
        )

        try:
            import azure_openai

            raw = azure_openai.chat_complete(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_completion_tokens=200,
            )
            parsed = json.loads(_strip_fence(raw))
            order = [str(pid) for pid in (parsed.get("order") or [])]
        except Exception:
            logger.warning("LLM rerank failed — keeping the base order", exc_info=True)
            return []

        rejected = [pid for pid in order if pid not in allowed]
        if rejected:
            # The one failure mode that matters: the model naming a product
            # nobody approved. Dropped here, and loud, because a silent drop
            # would hide a prompt-injection attempt as easily as a typo.
            logger.warning("LLM rerank returned unapproved product ids %s — dropped", rejected)
        return [pid for pid in order if pid in allowed]


def _strip_fence(raw: str) -> str:
    """Tolerate ```json fences, which models add regardless of instructions."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def load_propensity(weights: Weights) -> PropensityScorer | None:
    """Load the artifact and wrap it, or return None with a single warning."""
    artifact = load_artifact(_model_path())
    if artifact is None:
        return None

    age = artifact.age_days()
    limit = _max_age_days()
    if age is not None and age > limit:
        # Stale is its own failure. A model fitted before a product launch or a
        # pricing change is confidently wrong about a world that moved.
        _warn_once(
            f"stale:{artifact.version}",
            "propensity artifact %s is %.0f days old (limit %.0f) — using the rule scorer",
            artifact.version,
            age,
            limit,
        )
        return None

    logger.info(
        "propensity model %s loaded (%d samples, %.0f days old)",
        artifact.version,
        artifact.n_samples,
        age if age is not None else -1,
    )
    return PropensityScorer(artifact, weights)


def hybrid_rule_weight() -> float:
    raw = (os.getenv("RECO_HYBRID_RULE_WEIGHT") or "").strip()
    if not raw:
        return 0.5
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        logger.warning("RECO_HYBRID_RULE_WEIGHT=%r is not a number — using 0.5", raw)
        return 0.5


def llm_rerank_enabled() -> bool:
    return (os.getenv("RECO_LLM_RERANK") or "").strip().lower() in {"1", "true", "yes", "on"}
