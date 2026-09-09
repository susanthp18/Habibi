"""One draw/replay implementation for treatment actions and reco offers.

Treatment and reco keep separate scorers. They share this contract so an
off-policy estimator can read either log without learning two alphabets.

Propensities are never fused at write time. ``arm_propensity`` is P(this
experimental arm). ``action_propensity`` is the within-arm draw over the
already-approved set. The product is stored as ``propensity`` for readers that
have not been taught the split; it is derived, not an independent third draw.

Unsupported mass is not clipped into existence: a candidate that was not in
the approved set is absent from the distribution, not given ``MIN_PROPENSITY``.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

CONTRACT_VERSION = 2
LEGACY_CONTRACT_VERSION = 1

KIND_GREEDY = "greedy"
KIND_RANKED = "ranked"
KIND_CONTROL_ARM = "control_arm"

ALPHA_MAX = 6.0
MIN_PROPENSITY = 1e-6
LAMBDA_BUCKET_NONE = "none"
VETO_STACK_VERSION = "treatment-veto-v4"

#: Source set the evaluator digest covers. A veto-stack bump without a digest
#: change, or the reverse, is a CI failure.
DIGEST_SOURCES: tuple[str, ...] = (
    "contact_policy.py",
    "policy_rules.py",
    "policy_binding.py",
    "agent_core/treatment/policy.py",
    "agent_core/reco/policy.py",
    "bank_boundary/freshness.py",
)

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_DIGEST_CACHE: str | None = None


def deployed_image_identity() -> str:
    """The running container/image label. Distinct from the evaluator digest."""
    return (os.getenv("APP_RELEASE") or os.getenv("IMAGE_TAG") or "local").strip() or "local"


def engine_image_digest() -> str:
    """SHA-256 over the declared policy/veto source set."""
    global _DIGEST_CACHE
    if _DIGEST_CACHE is not None:
        return _DIGEST_CACHE
    hasher = hashlib.sha256()
    for rel in DIGEST_SOURCES:
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        path = _BACKEND_ROOT / rel
        hasher.update(path.read_bytes() if path.is_file() else b"missing")
        hasher.update(b"\0")
    _DIGEST_CACHE = "sha256:" + hasher.hexdigest()
    return _DIGEST_CACHE


def config_version(*, conn: Any = None, portfolio_id: str = "") -> str:
    """``cfg:<epoch>`` when configuration resolved to ``engine_config`` rows.

    W8's exit criterion is that this *resolves*: given the string on a decision
    row, the rows in force when that decision was made can be read back. The
    environment sha below is what W2 shipped as the stated day-1 value, and it
    remains the fallback on a database where ``0116`` has not been applied or
    where nobody has written a config row yet -- the column stays non-null,
    which is W2's own exit criterion, and it names nothing, which is why W8
    exists.
    """
    from agent_core import engine_config

    resolved = engine_config.version(portfolio_id, conn=conn)
    if resolved:
        return resolved
    return environment_config_version()


def environment_config_version() -> str:
    """W2's day-1 value: a sha over the economics that were in the env."""
    keys = (
        "CONTACT_DAILY_CAP",
        "CONTACT_WEEKLY_CAP",
        "CONTACT_COOLING_OFF_MINUTES",
        "RECO_AB_SPLIT",
    )
    payload = {key: os.getenv(key, "") for key in keys}
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"env:{digest}"


@dataclass(frozen=True)
class Draw:
    """One pick, and the two probabilities that produced it."""

    index: int
    kind: str
    arm_propensity: float
    action_propensity: float
    propensity: float
    distribution: dict[str, float]
    nonce: str
    seed: str

    @property
    def explored(self) -> bool:
        if not self.distribution:
            return False
        top = next(iter(self.distribution))
        keys = list(self.distribution)
        chosen = keys[self.index] if 0 <= self.index < len(keys) else top
        return chosen != top


def new_nonce() -> str:
    return uuid.uuid4().hex


def seed_for(
    *,
    subject_id: str,
    trigger_kind: str,
    trigger_ref: str | None,
    items: Sequence[str],
    nonce: str,
) -> str:
    """A stable seed for one decision, including the per-decision nonce."""
    parts = [subject_id, trigger_kind, trigger_ref or "", ",".join(items)]
    if nonce:
        parts.append(nonce)
    return "|".join(parts)


def draw(
    items: Sequence[str],
    *,
    greediness: float = 1.0,
    arm_probability: float = 1.0,
    nonce: str = "",
    subject_id: str = "",
    trigger_kind: str = "",
    trigger_ref: str | None = None,
    kind: str | None = None,
) -> Draw | None:
    """Pick one already-approved item and return both propensities.

    ``items`` must be ordered best-first. This function does not re-judge
    eligibility. Default greediness 1.0 is a pure argmax with action
    probability 1.0 — byte-identical to the historical logging policy.
    """
    if not items:
        return None
    arm_p = _clamp01(arm_probability) or 1.0
    nonce = nonce or new_nonce()
    seed = seed_for(
        subject_id=subject_id,
        trigger_kind=trigger_kind,
        trigger_ref=trigger_ref,
        items=items,
        nonce=nonce,
    )
    names = [str(item) for item in items]

    if kind == KIND_CONTROL_ARM or (greediness >= 1.0 or len(names) == 1):
        chosen_kind = KIND_CONTROL_ARM if kind == KIND_CONTROL_ARM else KIND_GREEDY
        action_p = 1.0
        product = max(MIN_PROPENSITY, min(1.0, arm_p * action_p))
        return Draw(
            index=0,
            kind=chosen_kind,
            arm_propensity=arm_p,
            action_propensity=action_p,
            propensity=product,
            distribution={names[0]: 1.0},
            nonce=nonce,
            seed=seed,
        )

    weights = rank_weights(len(names), greediness)
    distribution = {name: weight for name, weight in zip(names, weights)}
    index = sample(weights, seed=seed)
    action_p = weights[index]
    product = max(MIN_PROPENSITY, min(1.0, action_p * arm_p))
    return Draw(
        index=index,
        kind=KIND_RANKED,
        arm_propensity=arm_p,
        action_propensity=action_p,
        propensity=product,
        distribution=distribution,
        nonce=nonce,
        seed=seed,
    )


def rank_weights(n: int, greediness: float) -> list[float]:
    g = _clamp01(greediness)
    alpha = min(ALPHA_MAX, g / (1.0 - g)) if g < 1.0 else ALPHA_MAX
    raw = [(i + 1) ** -alpha for i in range(n)]
    total = sum(raw)
    if total <= 0:  # pragma: no cover
        return [1.0 / n] * n
    weights = [w / total for w in raw]
    floored = [max(MIN_PROPENSITY, w) for w in weights]
    scale = sum(floored)
    return [w / scale for w in floored]


def sample(weights: Sequence[float], *, seed: str) -> int:
    digest = hashlib.blake2b(
        seed.encode("utf-8"), digest_size=8, person=b"explore\x00"
    ).digest()
    rng = random.Random(int.from_bytes(digest, "big"))
    position = rng.random()
    cumulative = 0.0
    for index, weight in enumerate(weights):
        cumulative += weight
        if position < cumulative:
            return index
    return len(weights) - 1


def _clamp01(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 1.0


def replay(draw_row: Draw, items: Sequence[str], *, greediness: float) -> Draw | None:
    """Reproduce a logged draw from the stored nonce and inputs."""
    return draw(
        items,
        greediness=greediness,
        arm_probability=draw_row.arm_propensity,
        nonce=draw_row.nonce,
        subject_id="",
        trigger_kind="",
        trigger_ref=None,
        kind=draw_row.kind if draw_row.kind == KIND_CONTROL_ARM else None,
    )
