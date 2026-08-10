"""Tunables for the offer engine.

Weights live here, not in the scorer, because tuning a recommender is an
operational act. Changing how much sentiment matters must not require a code
review, a build and a deploy — it has to be a config change someone can make on
a Tuesday afternoon and roll back on Wednesday morning.

Every value is read from the environment at call time (not import time) so a
running process picks up a change without a restart, and tests can monkeypatch
os.environ without reloading the module.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Engine modes:
#   off     — never recommend; the tool returns suppressed=engine_off
#   shadow  — score and log everything, present nothing (the safe rollout)
#   live    — score, log, and hand the shortlist to the model
MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_LIVE = "live"
_MODES = frozenset({MODE_OFF, MODE_SHADOW, MODE_LIVE})


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number — using %s", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer — using %s", name, raw, default)
        return default


def mode() -> str:
    """Engine mode. Defaults to shadow: a new recommender earns its way to live.

    An unrecognised value falls back to shadow rather than off — a typo should
    degrade to "log but stay quiet", not to "silently stop collecting the data
    the whole thing is supposed to learn from".
    """
    raw = (os.getenv("RECO_MODE") or MODE_SHADOW).strip().lower()
    if raw not in _MODES:
        logger.warning("RECO_MODE=%r is not one of %s — using shadow", raw, sorted(_MODES))
        return MODE_SHADOW
    return raw


def scorer_name() -> str:
    """Which Recommender implementation to use."""
    return (os.getenv("RECO_SCORER") or "rule").strip().lower()


def log_vectors() -> bool:
    """Whether to write the model feature vector into each decision row.

    On by default: without it there is no leakage-free training corpus, and the
    whole point of shadow mode is to build one. Turn it off only if row size
    becomes a real problem, and understand that those rows are then untrainable.
    """
    return (os.getenv("RECO_LOG_VECTORS") or "true").strip().lower() != "false"


@dataclass(frozen=True)
class Weights:
    """Rule-scorer signal weights. They do not have to sum to 1 — the score is
    normalised by the total weight actually applied, so a signal that is
    unavailable for a given customer drops out of both numerator and
    denominator instead of silently scoring zero."""

    affinity: float
    affordability: float
    credit_health: float
    in_call_intent: float
    sentiment: float
    campaign_priority: float
    # Subtracted after normalisation, so a penalty can veto a strong score
    # instead of being averaged away by it.
    fatigue_penalty: float
    # A customer who just pulled a no-dues certificate is on their way out.
    # Kept separate from fatigue so the decision log distinguishes "we have
    # pitched them too often" from "they are trying to leave" — the two call
    # for opposite interventions.
    exit_intent_penalty: float


def weights() -> Weights:
    return Weights(
        affinity=_env_float("RECO_W_AFFINITY", 0.20),
        affordability=_env_float("RECO_W_AFFORDABILITY", 0.20),
        credit_health=_env_float("RECO_W_CREDIT", 0.15),
        in_call_intent=_env_float("RECO_W_INTENT", 0.20),
        sentiment=_env_float("RECO_W_SENTIMENT", 0.10),
        campaign_priority=_env_float("RECO_W_CAMPAIGN", 0.10),
        fatigue_penalty=_env_float("RECO_W_FATIGUE", 0.05),
        exit_intent_penalty=_env_float("RECO_W_EXIT_INTENT", 0.15),
    )


# ---------------------------------------------------------------------------
# A/B variants
#
# A variant is a *named bundle* of engine settings, declared up front. Naming
# them is the point: "challenger" appears on every decision row, so a week
# later the question "what was challenger, exactly?" has an answer that is not
# somebody's memory of what the environment looked like at the time.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Variant:
    name: str
    mode: str | None = None
    scorer: str | None = None
    # Only meaningful for the hybrid scorer; ignored otherwise.
    rule_weight: float | None = None


# Always available, so an A/B can be run without configuring anything.
_BUILTIN_VARIANTS: dict[str, Variant] = {
    # Whatever the process is already set to — the honest control arm.
    "control": Variant(name="control"),
    "rule": Variant(name="rule", scorer="rule"),
    "model": Variant(name="model", scorer="propensity"),
    "hybrid": Variant(name="hybrid", scorer="hybrid"),
    # An explicit "say nothing" arm. Measuring against no offer at all is the
    # only way to know whether the engine helps or merely reallocates.
    "holdout": Variant(name="holdout", mode=MODE_SHADOW),
}


def _parse_variants(raw: str) -> dict[str, Variant]:
    import json

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("RECO_VARIANTS is not valid JSON — using the built-in variants only")
        return {}
    if not isinstance(parsed, dict):
        logger.warning("RECO_VARIANTS must be a JSON object — using the built-in variants only")
        return {}

    out: dict[str, Variant] = {}
    for name, spec in parsed.items():
        if not isinstance(spec, dict):
            logger.warning("RECO_VARIANTS[%r] is not an object — skipped", name)
            continue
        key = str(name).strip().lower()
        mode = str(spec.get("mode") or "").strip().lower() or None
        if mode is not None and mode not in _MODES:
            logger.warning("RECO_VARIANTS[%r].mode=%r is not a known mode — ignored", name, mode)
            mode = None
        weight = spec.get("ruleWeight")
        try:
            rule_weight = None if weight is None else max(0.0, min(1.0, float(weight)))
        except (TypeError, ValueError):
            logger.warning("RECO_VARIANTS[%r].ruleWeight=%r is not a number — ignored", name, weight)
            rule_weight = None
        out[key] = Variant(
            name=key,
            mode=mode,
            scorer=(str(spec.get("scorer") or "").strip().lower() or None),
            rule_weight=rule_weight,
        )
    return out


def variants() -> dict[str, Variant]:
    """Built-ins, overridable and extendable through ``RECO_VARIANTS`` JSON."""
    raw = (os.getenv("RECO_VARIANTS") or "").strip()
    return {**_BUILTIN_VARIANTS, **(_parse_variants(raw) if raw else {})}


def resolve_variant(name: str | None) -> Variant | None:
    """Look up a variant by name. Unknown names fall back to process defaults.

    Never raises and never invents an arm. A typo in a session's
    ``recoVariant`` must degrade to the default behaviour, not take the offer
    path down and not silently create a phantom arm that pollutes the
    comparison with one call.
    """
    key = (name or "").strip().lower()
    if not key:
        return None
    found = variants().get(key)
    if found is None:
        logger.warning("unknown recoVariant=%r — using the process defaults", name)
    return found


def ab_split() -> list[tuple[str, float]]:
    """``RECO_AB_SPLIT="control:50,challenger:50"`` → normalised buckets."""
    raw = (os.getenv("RECO_AB_SPLIT") or "").strip()
    if not raw:
        return []

    known = variants()
    buckets: list[tuple[str, float]] = []
    for part in raw.split(","):
        chunk = part.strip()
        if not chunk:
            continue
        name, _, weight = chunk.partition(":")
        key = name.strip().lower()
        if key not in known:
            logger.warning("RECO_AB_SPLIT names unknown variant %r — dropped", key)
            continue
        try:
            share = float(weight) if weight.strip() else 1.0
        except ValueError:
            logger.warning("RECO_AB_SPLIT weight for %r is not a number — using 1", key)
            share = 1.0
        if share > 0:
            buckets.append((key, share))

    total = sum(share for _, share in buckets)
    if total <= 0:
        return []
    return [(name, share / total) for name, share in buckets]


def assign_variant(customer_id: str) -> Variant | None:
    """Deterministically bucket a customer into an arm.

    **Hashed on the customer, not the call.** A customer who is pitched by the
    rule scorer on Monday and the model on Thursday belongs to neither arm, and
    every number computed from that split is meaningless. Stable bucketing is
    what makes the comparison an experiment rather than an anecdote.

    Uses blake2b rather than :func:`hash`, whose per-process randomisation
    would reassign every customer on restart.
    """
    buckets = ab_split()
    if not buckets or not customer_id:
        return None

    import hashlib

    digest = hashlib.blake2b(customer_id.encode("utf-8"), digest_size=8).digest()
    position = int.from_bytes(digest, "big") / float(1 << 64)

    cumulative = 0.0
    for name, share in buckets:
        cumulative += share
        if position < cumulative:
            return variants().get(name)
    return variants().get(buckets[-1][0])


@dataclass(frozen=True)
class Policy:
    """Arbitration limits."""

    min_score: float
    max_offers_returned: int
    max_offers_per_call: int
    max_offers_per_customer_30d: int
    decline_cooldown_days: int
    family_cooldown_days: int
    sentiment_floor: float
    require_commitment: bool


def policy() -> Policy:
    return Policy(
        # Below this the engine would rather say nothing. An offer nobody wants
        # costs handle time and goodwill, and both are more expensive than the
        # lead is worth.
        min_score=_env_float("RECO_MIN_SCORE", 0.35),
        max_offers_returned=_env_int("RECO_MAX_OFFERS", 2),
        max_offers_per_call=_env_int("RECO_MAX_PER_CALL", 1),
        max_offers_per_customer_30d=_env_int("RECO_MAX_PER_CUSTOMER_30D", 3),
        decline_cooldown_days=_env_int("RECO_DECLINE_COOLDOWN_DAYS", 90),
        family_cooldown_days=_env_int("RECO_FAMILY_COOLDOWN_DAYS", 30),
        # estimate_sentiment returns [-1, 1]; sentiment_label calls anything
        # below -0.15 negative, so the gate matches the label the rest of the
        # system already uses.
        sentiment_floor=_env_float("RECO_SENTIMENT_FLOOR", -0.15),
        require_commitment=(os.getenv("RECO_REQUIRE_COMMITMENT") or "true").strip().lower()
        != "false",
    )
