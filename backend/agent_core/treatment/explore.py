"""Choosing among approved actions, and recording the odds it chose them at.

This is the only component of the decision engine that cannot be added later.
A model can be retrained on old data forever; a control group cannot be
retro-fitted onto a log, and neither can a propensity. Every decision the engine
has ever made was a deterministic argmax, which means every action it took was
taken with probability 1.0 — and an importance-weighted estimate over a log
where every weight is 1 is just the logged average. It cannot tell you what a
*different* policy would have recovered, which is the only question worth
asking of a corpus.

So this module does two things and nothing else: it picks one action out of a
set that has already been approved, and it says how likely that pick was.

**Where it sits.** Strictly after the veto stack, over the approved set only:

    candidates → statutory → client → customer → APPROVED SET → explore

Not the other way round. Randomising between two *already-compliant* actions —
WhatsApp now versus a bot call tomorrow morning — costs almost nothing and is
the only way to learn the ladder. Randomising and *then* checking compliance is
experimenting on borrowers, and no amount of expected information justifies it.
The ordering is the architectural boundary, and it is why exploration here is
defensible to a regulator.

**Why rank power-normalisation and not a softmax over expected value.** The
scores are rupees, and rupees are unbounded. A Boltzmann temperature tuned so a
₹68 account explores sensibly is degenerate on a ₹6,800 one: the same
temperature that gives the second-best action a 30% share on the small account
gives it 10^-9 on the large one, so the book explores only where it has least to
learn. Ranks have no scale. ``w_i ∝ i**-alpha`` gives the same distribution over
positions whatever the account is worth, and it has exactly one parameter, which
is what makes the exploration dial something a collections head can be shown.

**Determinism.** The draw is seeded from the decision's own inputs, so a replay
of the same decision reproduces the same choice. ``EVScorer.score`` already
guarantees that two identical runs cannot disagree; exploration must not be the
thing that breaks it, because offline replay is how a challenger policy is
evaluated before it is allowed near a borrower.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Sequence

from agent_core.treatment.scoring import ScoredAction

KIND_GREEDY = "greedy"
KIND_RANKED = "ranked"
KIND_CONTROL_ARM = "control_arm"

#: Ceiling on the rank exponent. Beyond roughly this the distribution is argmax
#: with extra arithmetic — at alpha=6 the second-ranked action already has a
#: 1.6% share — and the floating-point tail starts producing propensities so
#: small that their reciprocals dominate any estimate they appear in.
ALPHA_MAX = 6.0

#: Nothing is logged with a smaller probability than this. It doubles as
#: importance-weight clipping: a decision logged at p=1e-9 contributes a weight
#: of a billion to an IPS estimate and swamps every other row in the corpus, so
#: an estimator built on unclipped weights has a variance nobody can defend.
#: Clipping at the point of *logging* rather than at the point of estimation
#: means every downstream consumer inherits the bound without having to know.
MIN_PROPENSITY = 1e-6


@dataclass(frozen=True)
class Choice:
    """One pick, and the distribution it was picked from."""

    chosen: ScoredAction
    #: π(a|x) for the action actually taken.
    propensity: float
    #: action → π, over the whole approved set. Written into the candidate log
    #: so an off-policy estimate can be recomputed for actions *not* taken,
    #: which is what doubly-robust estimation needs and IPS alone does not.
    distribution: dict[str, float]
    kind: str

    @property
    def explored(self) -> bool:
        """True when the pick was not simply the top-ranked action."""
        return bool(self.distribution) and self.chosen.action != next(
            iter(self.distribution)
        )


def choose(
    eligible: Sequence[ScoredAction],
    *,
    greediness: float = 1.0,
    seed: str = "",
    arm_probability: float = 1.0,
) -> Choice | None:
    """Pick one action from an already-approved, already-ranked list.

    ``eligible`` must be ordered best-first and must contain no vetoed action
    and no action below the value floor — this function does not re-judge
    anything, it only draws.

    ``arm_probability`` is P(this borrower is in this experimental arm), which
    multiplies into the recorded propensity. Recording only P(action | arm)
    would understate how unlikely the whole path was and bias every estimate
    computed across arms — the borrower had to land in the arm *and then* be
    drawn, and both are things the logging policy did.
    """
    if not eligible:
        return None

    arm_p = _clamp01(arm_probability) or 1.0

    if greediness >= 1.0 or len(eligible) == 1:
        top = eligible[0]
        return Choice(
            chosen=top,
            propensity=max(MIN_PROPENSITY, min(1.0, arm_p)),
            distribution={top.action: 1.0},
            kind=KIND_GREEDY,
        )

    weights = _rank_weights(len(eligible), greediness)
    distribution = {
        action.action: weight for action, weight in zip(eligible, weights)
    }

    index = _draw(weights, seed=seed)
    chosen = eligible[index]
    return Choice(
        chosen=chosen,
        propensity=max(MIN_PROPENSITY, min(1.0, weights[index] * arm_p)),
        distribution=distribution,
        kind=KIND_RANKED,
    )


def control_arm_choice(action: ScoredAction, *, arm_probability: float) -> Choice:
    """The propensity of a decision made inside the control arm.

    The action was not drawn from anything — the arm withheld every
    discretionary option, so what remains was forced. The only randomness in
    the path is the arm assignment itself, and that is exactly what gets
    recorded: pretending there was a within-arm draw would inflate the
    denominator of every weight computed off these rows.
    """
    p = max(MIN_PROPENSITY, min(1.0, _clamp01(arm_probability) or 1.0))
    return Choice(
        chosen=action,
        propensity=p,
        distribution={action.action: 1.0},
        kind=KIND_CONTROL_ARM,
    )


def _rank_weights(n: int, greediness: float) -> list[float]:
    """Normalised ``i**-alpha`` over ranks 1..n.

    ``greediness`` maps to the exponent through ``g / (1 - g)``: 0 is uniform,
    0.5 is harmonic, 0.8 is a fourth power, and 1.0 is handled by the caller as
    a pure argmax. The map is smooth and monotone, so turning the dial up never
    makes the engine explore more.
    """
    g = _clamp01(greediness)
    alpha = min(ALPHA_MAX, g / (1.0 - g)) if g < 1.0 else ALPHA_MAX
    raw = [(i + 1) ** -alpha for i in range(n)]
    total = sum(raw)
    if total <= 0:  # pragma: no cover - unreachable while n >= 1
        return [1.0 / n] * n
    weights = [w / total for w in raw]
    # Renormalise after flooring so the distribution still sums to one. Without
    # this a long candidate list quietly sums to 1.0000x and the log carries a
    # distribution that is not a distribution.
    floored = [max(MIN_PROPENSITY, w) for w in weights]
    scale = sum(floored)
    return [w / scale for w in floored]


def _draw(weights: Sequence[float], *, seed: str) -> int:
    """Index sampled from ``weights``, reproducibly for a given seed.

    ``blake2b`` rather than :func:`hash`, whose per-process randomisation would
    make a replay of yesterday's decisions disagree with yesterday.
    """
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


def seed_for(
    *, customer_id: str, trigger_kind: str, trigger_ref: str | None, actions: Sequence[str]
) -> str:
    """A stable seed for one decision.

    Includes the candidate set, so two decisions that faced genuinely different
    options draw independently. Excludes the clock, so the same decision replays
    to the same answer.
    """
    return "|".join(
        [customer_id, trigger_kind, trigger_ref or "", ",".join(actions)]
    )


def _clamp01(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 1.0
