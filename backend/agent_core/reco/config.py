"""Tunables for the offer engine.

Weights live here, not in the scorer, because tuning a recommender is an
operational act. Changing how much sentiment matters must not require a code
review, a build and a deploy — it has to be a config change someone can make on
a Tuesday afternoon and roll back on Wednesday morning.

Every value is resolved through :mod:`agent_core.engine_config` at call time
(not import time) so a running process picks up a change without a restart, and
tests can monkeypatch os.environ without reloading the module. §1462 of the
engines design makes this engine a reader of the same rows the treatment engine
reads: one cost book, one validation, one ``config_version``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agent_core import engine_config

logger = logging.getLogger(__name__)

# Engine modes:
#   off     — never recommend; the tool returns suppressed=engine_off
#   shadow  — score and log everything, present nothing (the safe rollout)
#   live    — score, log, and hand the shortlist to the model
MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_LIVE = "live"
_MODES = frozenset({MODE_OFF, MODE_SHADOW, MODE_LIVE})


# Kept as names rather than rewritten at twenty call sites: these were
# private duplicates of ``env_utils``, and the resolver is a drop-in with
# the same (key, default) shape plus bounds and an ``engine_config`` layer.
_env_float = engine_config.number
_env_int = engine_config.integer


def mode() -> str:
    """Engine mode. Defaults to shadow: a new recommender earns its way to live.

    An unrecognised value falls back to shadow rather than off — a typo should
    degrade to "log but stay quiet", not to "silently stop collecting the data
    the whole thing is supposed to learn from".
    """
    raw = engine_config.text_value("RECO_MODE", MODE_SHADOW).strip().lower()
    if raw not in _MODES:
        logger.warning("RECO_MODE=%r is not one of %s — using shadow", raw, sorted(_MODES))
        return MODE_SHADOW
    return raw


def scorer_name() -> str:
    """Which Recommender implementation to use."""
    return engine_config.text_value("RECO_SCORER", "rule").strip().lower()


def log_vectors() -> bool:
    """Whether to write the model feature vector into each decision row.

    On by default: without it there is no leakage-free training corpus, and the
    whole point of shadow mode is to build one. Turn it off only if row size
    becomes a real problem, and understand that those rows are then untrainable.
    """
    return engine_config.flag("RECO_LOG_VECTORS", True)


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


def _parse_variants(raw: object) -> dict[str, Variant]:
    import json

    if isinstance(raw, str):
        try:
            parsed: object = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("RECO_VARIANTS is not valid JSON — using the built-in variants only")
            return {}
    else:
        parsed = raw
    if not isinstance(parsed, dict):
        logger.warning("RECO_VARIANTS must be a JSON object — using the built-in variants only")
        return {}

    out: dict[str, Variant] = {}
    for name, spec in parsed.items():
        key = str(name).strip().lower()
        if key in RESERVED_VARIANTS:
            logger.warning(
                "RECO_VARIANTS[%r] would redefine a built-in arm — ignored", name
            )
            continue
        if not isinstance(spec, dict):
            logger.warning("RECO_VARIANTS[%r] is not an object — skipped", name)
            continue
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


#: The arms configuration may not redefine. ``holdout`` and ``control`` are
#: what every comparison is measured against; an arm that can be redefined from
#: a config value is not a control arm.
RESERVED_VARIANTS: frozenset[str] = frozenset(_BUILTIN_VARIANTS)


def variants() -> dict[str, Variant]:
    """Built-ins plus ``RECO_VARIANTS``. Built-ins win."""
    configured = engine_config.raw("RECO_VARIANTS")
    parsed = _parse_variants(configured) if configured else {}
    return {**parsed, **_BUILTIN_VARIANTS}


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
    """``RECO_AB_SPLIT="control:50,challenger:50"`` → normalised buckets.

    An unknown arm name refuses the whole split rather than dropping it and
    renormalising the rest — the renormalised weights are not the probabilities
    anybody was assigned with, and they multiply into every logged propensity.
    """
    raw = engine_config.text_value("RECO_AB_SPLIT", "").strip()
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
            logger.error(
                "RECO_AB_SPLIT names unknown variant %r — refusing the whole split", key
            )
            return []
        try:
            share = float(weight) if weight.strip() else 1.0
        except ValueError:
            logger.error(
                "RECO_AB_SPLIT weight for %r is not a number — refusing the split", key
            )
            return []
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
        require_commitment=engine_config.flag("RECO_REQUIRE_COMMITMENT", True),
    )
