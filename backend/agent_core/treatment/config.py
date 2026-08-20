"""Tunables for the treatment engine.

Read from the environment at call time, not import time, so a running process
picks up a change without a restart and tests can monkeypatch ``os.environ``
without reloading the module. Same discipline as ``reco.config`` and for the
same reason: deciding that a field visit is worth ₹1,100 rather than ₹800 is an
operational act, not a release.

The money constants deserve a word. They are **unit economics, not accounting**
— what one attempt on one channel costs the floor, all in. They are wrong on
day one for every deployment and they are supposed to be: the engine's output
is only as good as these, so they are the first thing a collections head is
asked to correct, and they sit in config precisely so that conversation ends in
an env change rather than a ticket.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from env_utils import env_float, env_int

logger = logging.getLogger(__name__)

# Engine modes:
#   off     — never recommend; callers get suppressed=engine_off
#   shadow  — decide and log everything, enact nothing (the safe rollout)
#   live    — decide, log, and let the executor act
MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_LIVE = "live"

#: Not a mode the engine can be *set* to — ``TREATMENT_MODE=simulated`` is a
#: typo and degrades to shadow like any other. It exists only as a stamp on
#: rows written by scripts/simulate_treatment_corpus.py, so a synthetic corpus
#: can live in the real table and be excluded everywhere by one predicate.
#:
#: Excluding it is not cosmetic. The executor claims any unspent plan whose
#: moment has arrived; without this stamp and the filters that read it, a live
#: worker would pick up a simulated decision and send a real message to a
#: borrower who does not exist — or, worse, to a real phone number a generator
#: happened to produce.
MODE_SIMULATED = "simulated"

_MODES = frozenset({MODE_OFF, MODE_SHADOW, MODE_LIVE})


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def mode() -> str:
    """Engine mode. Defaults to shadow — an engine earns its way to live.

    An unrecognised value degrades to shadow rather than off, for the reason
    reco gives: a typo must not silently stop collecting the data the rollout
    decision depends on.
    """
    raw = (os.getenv("TREATMENT_MODE") or MODE_SHADOW).strip().lower()
    if raw not in _MODES:
        logger.warning(
            "TREATMENT_MODE=%r is not one of %s — using shadow", raw, sorted(_MODES)
        )
        return MODE_SHADOW
    return raw


def scorer_name() -> str:
    return (os.getenv("TREATMENT_SCORER") or "ev").strip().lower()


def log_vectors() -> bool:
    """Write the model feature vector into each decision row.

    On by default. Without it there is no leakage-free training corpus, which
    is most of what shadow mode is for.
    """
    return _env_bool("TREATMENT_LOG_VECTORS", True)


def llm_rerank_enabled() -> bool:
    return _env_bool("TREATMENT_LLM_RERANK", False)


def greediness() -> float:
    """How deterministically the logging policy picks among approved actions.

    ``1.0`` is argmax — the highest-scoring approved action, every time, with a
    propensity of 1.0. That is the default, and it makes exploration a thing
    somebody switches on rather than a thing that happens to a book because a
    module was deployed.

    ``0.0`` is uniform over the approved set. In between, a rank-based power
    normalisation trades reward for information smoothly, so the exploration
    dial is one number a collections head can be shown rather than a rewrite.

    Nothing here is ever the difference between compliant and not: exploration
    runs *after* the veto stack, over actions all of which were already
    approved. The dial changes which permitted thing happens, never whether a
    forbidden one does.
    """
    return max(0.0, min(1.0, env_float("TREATMENT_GREEDINESS", 1.0)))


MANDATE_EXECUTOR_RAIL = "rail"
MANDATE_EXECUTOR_LMS = "lms"


def mandate_executor() -> str:
    """Who actually presents the mandate: us, or the lender's own system.

    The decision, the schema, the policy rules and the attribution are
    identical either way — only the last hop differs. Deployments where the
    platform holds presentment authority set ``rail``; deployments where we
    recommend and the LMS presents set ``lms`` and read the outcome back off
    the ``payment_events`` webhook.

    ``lms`` is the default because it is the safe half of the fork: recommending
    something the lender declines to do costs a missed collection, and
    presenting a debit we were never authorised to present costs a great deal
    more than that.
    """
    raw = (os.getenv("TREATMENT_MANDATE_EXECUTOR") or MANDATE_EXECUTOR_LMS).strip().lower()
    if raw not in {MANDATE_EXECUTOR_RAIL, MANDATE_EXECUTOR_LMS}:
        logger.warning(
            "TREATMENT_MANDATE_EXECUTOR=%r is not recognised — using %r",
            raw,
            MANDATE_EXECUTOR_LMS,
        )
        return MANDATE_EXECUTOR_LMS
    return raw


# ---------------------------------------------------------------------------
# Unit economics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Costs:
    """Rupees per attempt, all-in (provider + occupancy + overhead)."""

    sms: float
    whatsapp: float
    voice_bot: float
    human_call: float
    field_visit: float
    legal_notice: float
    represent_mandate: float
    emi_date_change: float

    def for_action(self, action: str) -> float:
        return float(getattr(self, action, 0.0))


def costs() -> Costs:
    return Costs(
        sms=env_float("TREATMENT_COST_SMS", 0.18),
        whatsapp=env_float("TREATMENT_COST_WHATSAPP", 0.42),
        # ~3 min of bot audio at the platform's own cost-per-minute. The
        # billing screen already computes cost/resolved-call from real usage;
        # this default is the planning figure until that number is wired in.
        voice_bot=env_float("TREATMENT_COST_VOICE_BOT", 7.50),
        # A telecaller minute, loaded. AiXBFS-style floors run 100–150 dials a
        # shift, so a dial is a meaningful fraction of a salaried hour.
        human_call=env_float("TREATMENT_COST_HUMAN_CALL", 45.0),
        # CarmaOne: ₹800–1,500 per doorstep visit, borrower absent 40–50% of
        # the time. The absence is priced in p_reach, not here.
        field_visit=env_float("TREATMENT_COST_FIELD_VISIT", 1150.0),
        legal_notice=env_float("TREATMENT_COST_LEGAL_NOTICE", 2500.0),
        # A presentment costs a per-transaction rail fee measured in paise,
        # and — unlike every other action here — it spends no goodwill at all,
        # so there is no fatigue term to add to it. Near-zero cost against a
        # real chance of collecting a whole instalment is the entire reason
        # this action outranks most contact in the early buckets.
        #
        # It is not exactly zero on purpose. At literally 0.00 the engine would
        # present at every opportunity the vetoes allow, because there would be
        # nothing to beat; the presentation limit would become the only thing
        # governing it, and a limit is a worse control than a price.
        represent_mandate=env_float("TREATMENT_COST_REPRESENT_MANDATE", 0.50),
        # An LMS work item and a schedule rewrite. Cheap, but not free: it is
        # somebody's ten minutes, and it changes the borrower's contract.
        emi_date_change=env_float("TREATMENT_COST_EMI_DATE_CHANGE", 15.0),
    )


@dataclass(frozen=True)
class Policy:
    """Arbitration limits and the shape of the value model."""

    # Below this expected value in rupees, the engine would rather wait. An
    # action nobody responds to costs money and goodwill, and goodwill is the
    # one a regulator reads as harassment.
    min_expected_value: float
    # Fraction of exposure a successful treatment actually recovers. Curing a
    # 1–30 DPD account rarely means collecting the whole balance; it means
    # collecting the instalment and stopping the roll-forward.
    recovery_fraction: float
    # Hours over which acting later halves its value. The roadmap's central
    # claim — "the profit lever is delay, not dialogue" — is this number.
    urgency_halflife_hours: float
    # Rupees of implied goodwill/attrition cost per unit of intrusiveness, per
    # touch already spent today. What stops the engine spending the daily
    # budget on three cheap SMS.
    fatigue_cost: float
    # How far up the ladder one decision may move. Digital → field in one step
    # is how a 3-day-old miss ends up with someone at the door.
    max_rung_advance: int
    # Reserve the last daily contact slot for a materially better action.
    reserve_budget: bool
    # Multiple of min_expected_value a future action must beat to justify
    # holding the last slot for it.
    reserve_margin: float
    # Digital attempts that must have failed before a field visit is offerable.
    field_digital_exhaustion: int
    # Horizon for "when could we act instead", in hours.
    planning_horizon_hours: int
    # Attempts on one case before the ladder stops. A borrower who has ignored
    # five contacts about the same bounce is not going to be persuaded by the
    # sixth, and RBI reads a sixth as persistent calling.
    max_attempts_per_case: int
    # Minimum gap before the same case is re-decided, whatever the last attempt
    # concluded. Stops a no-answer at 09:00 becoming a second dial at 09:05.
    retry_backoff_hours: float


def policy() -> Policy:
    return Policy(
        min_expected_value=env_float("TREATMENT_MIN_EV", 2.0),
        recovery_fraction=max(
            0.0, min(1.0, env_float("TREATMENT_RECOVERY_FRACTION", 0.35))
        ),
        urgency_halflife_hours=max(
            1.0, env_float("TREATMENT_URGENCY_HALFLIFE_HOURS", 36.0)
        ),
        fatigue_cost=env_float("TREATMENT_FATIGUE_COST", 6.0),
        max_rung_advance=max(1, env_int("TREATMENT_MAX_RUNG_ADVANCE", 1)),
        reserve_budget=_env_bool("TREATMENT_RESERVE_BUDGET", True),
        reserve_margin=max(1.0, env_float("TREATMENT_RESERVE_MARGIN", 3.0)),
        field_digital_exhaustion=max(
            0, env_int("TREATMENT_FIELD_DIGITAL_EXHAUSTION", 4)
        ),
        planning_horizon_hours=max(1, env_int("TREATMENT_HORIZON_HOURS", 72)),
        max_attempts_per_case=max(1, env_int("TREATMENT_MAX_ATTEMPTS_PER_CASE", 5)),
        retry_backoff_hours=max(0.0, env_float("TREATMENT_RETRY_BACKOFF_HOURS", 12.0)),
    )


#: How long to wait before concluding an attempt went unanswered, per action.
#: A dial resolves in minutes; a follow-up sitting in an agent's queue resolves
#: when they get to it, and calling that a no-answer after an hour would have
#: the ladder escalating past a human who has not yet picked up the phone.
_GRACE_DEFAULTS: dict[str, float] = {
    "sms": 8.0,
    "whatsapp": 8.0,
    "voice_bot": 2.0,
    "human_call": 24.0,
    "field_visit": 48.0,
    "legal_notice": 24.0 * 15,  # NI Act s.138 gives the drawer 15 days to pay
    # A NACH debit settles at T+1 and can return as late as T+2. Concluding
    # anything before then would label a presentation that is still in flight.
    "represent_mandate": 72.0,
    # A schedule change proves itself at the next due date, not before.
    "emi_date_change": 24.0 * 35,
}

_GRACE_ENV = {
    "sms": "TREATMENT_GRACE_DIGITAL_HOURS",
    "whatsapp": "TREATMENT_GRACE_DIGITAL_HOURS",
    "voice_bot": "TREATMENT_GRACE_VOICE_HOURS",
    "human_call": "TREATMENT_GRACE_HUMAN_HOURS",
    "field_visit": "TREATMENT_GRACE_FIELD_HOURS",
    "legal_notice": "TREATMENT_GRACE_LEGAL_HOURS",
    "represent_mandate": "TREATMENT_GRACE_MANDATE_HOURS",
    "emi_date_change": "TREATMENT_GRACE_SCHEDULE_HOURS",
}


def grace_hours(action: str) -> float:
    """How long an attempt is given before it counts as unanswered."""
    default = _GRACE_DEFAULTS.get(action, 8.0)
    name = _GRACE_ENV.get(action)
    return max(0.25, env_float(name, default)) if name else default


# ---------------------------------------------------------------------------
# A/B variants — same shape as reco, deliberately.
#
# A variant is a named bundle of settings declared up front. The name lands on
# every decision row, so "what was `patient`, exactly?" has an answer a week
# later that is not somebody's memory of the environment.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Variant:
    name: str
    mode: str | None = None
    scorer: str | None = None
    min_expected_value: float | None = None
    urgency_halflife_hours: float | None = None
    #: Withhold every *discretionary* action while still permitting the
    #: statutory ones. This is what a randomised control arm actually is, and
    #: it is not the same as switching the engine off — see ``null_treatment``.
    suppress_discretionary: bool = False


# NAMING HAZARD, and it is the kind that produces a confidently wrong number.
#
# ``control`` here is the *treated* baseline: whatever the process is already
# set to, the arm every other arm is compared against. It is not a control
# group. The untreated arms are ``holdout`` (decides and enacts nothing) and
# ``null_treatment`` (withholds discretionary action but still sends what the
# law requires).
#
# Reaching for ``control`` when measuring incremental effect gets the exact
# opposite of what was wanted: every borrower in it is contacted normally, so
# the measured uplift is zero by construction and looks like a finding.
_BUILTIN_VARIANTS: dict[str, Variant] = {
    # Whatever the process is already set to. The baseline, not the control.
    "control": Variant(name="control"),
    # Acts on anything that clears cost. Measures whether the floor is too high.
    "eager": Variant(name="eager", min_expected_value=0.0, urgency_halflife_hours=12.0),
    # Waits for a clearly worthwhile moment. Measures the harassment trade.
    "patient": Variant(
        name="patient", min_expected_value=25.0, urgency_halflife_hours=96.0
    ),
    # An explicit do-nothing arm. Measuring against no treatment at all is the
    # only way to know whether the engine helps or merely reallocates spend.
    #
    # Note what this arm actually withholds: *everything*, including a
    # statutory notice whose clock is running. That makes it the right arm for
    # measuring the engine and the wrong arm for a live book, which is what
    # null_treatment below is for.
    "holdout": Variant(name="holdout", mode=MODE_SHADOW),
    # The control arm proper. Discretionary outreach is withheld — no SMS, no
    # WhatsApp, no dial, no visit — while statutory communication still goes
    # out, because a borrower does not lose their right to a notice by being
    # randomised into a measurement.
    #
    # Silence where the law requires speech is not a control group; it is a
    # compliance breach that happens to be randomised. This arm is the reason
    # the difference is expressible at all.
    "null_treatment": Variant(name="null_treatment", suppress_discretionary=True),
}


def _parse_variants(raw: str) -> dict[str, Variant]:
    import json

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "TREATMENT_VARIANTS is not valid JSON — using the built-in variants only"
        )
        return {}
    if not isinstance(parsed, dict):
        logger.warning(
            "TREATMENT_VARIANTS must be a JSON object — using the built-in variants only"
        )
        return {}

    out: dict[str, Variant] = {}
    for name, spec in parsed.items():
        if not isinstance(spec, dict):
            logger.warning("TREATMENT_VARIANTS[%r] is not an object — skipped", name)
            continue
        key = str(name).strip().lower()
        arm_mode = str(spec.get("mode") or "").strip().lower() or None
        if arm_mode is not None and arm_mode not in _MODES:
            logger.warning(
                "TREATMENT_VARIANTS[%r].mode=%r is not a known mode — ignored",
                name,
                arm_mode,
            )
            arm_mode = None
        out[key] = Variant(
            name=key,
            mode=arm_mode,
            scorer=(str(spec.get("scorer") or "").strip().lower() or None),
            min_expected_value=_opt_float(spec.get("minExpectedValue"), name, "minExpectedValue"),
            urgency_halflife_hours=_opt_float(
                spec.get("urgencyHalflifeHours"), name, "urgencyHalflifeHours"
            ),
            suppress_discretionary=bool(spec.get("suppressDiscretionary", False)),
        )
    return out


def _opt_float(value: object, arm: object, field: str) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        logger.warning("TREATMENT_VARIANTS[%r].%s=%r is not a number — ignored", arm, field, value)
        return None


def variants() -> dict[str, Variant]:
    raw = (os.getenv("TREATMENT_VARIANTS") or "").strip()
    return {**_BUILTIN_VARIANTS, **(_parse_variants(raw) if raw else {})}


def resolve_variant(name: str | None) -> Variant | None:
    """Look up a variant by name. Unknown names fall back to process defaults.

    Never raises and never invents an arm: a typo must degrade to default
    behaviour, not create a phantom arm that pollutes the comparison with one
    customer.
    """
    key = (name or "").strip().lower()
    if not key:
        return None
    found = variants().get(key)
    if found is None:
        logger.warning("unknown treatment variant=%r — using the process defaults", name)
    return found


def ab_split() -> list[tuple[str, float]]:
    """``TREATMENT_AB_SPLIT="control:50,patient:50"`` → normalised buckets."""
    raw = (os.getenv("TREATMENT_AB_SPLIT") or "").strip()
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
            logger.warning("TREATMENT_AB_SPLIT names unknown variant %r — dropped", key)
            continue
        try:
            share = float(weight) if weight.strip() else 1.0
        except ValueError:
            logger.warning(
                "TREATMENT_AB_SPLIT weight for %r is not a number — using 1", key
            )
            share = 1.0
        if share > 0:
            buckets.append((key, share))

    total = sum(share for _, share in buckets)
    if total <= 0:
        return []
    return [(name, share / total) for name, share in buckets]


def arm_probability(name: str | None) -> float:
    """P(a borrower is assigned this arm), from the configured split.

    1.0 when no split is configured or the arm is not in it — there was no
    randomisation, so the arm assignment contributed nothing to how unlikely
    the decision was. This multiplies into the logged propensity, because a
    borrower had to land in the arm *and then* have an action drawn, and an
    estimate computed across arms that ignores the first half is biased toward
    whichever arm is largest.
    """
    if not name:
        return 1.0
    for arm, share in ab_split():
        if arm == name:
            return share
    return 1.0


def assign_variant(customer_id: str) -> Variant | None:
    """Deterministically bucket a customer into an arm.

    Hashed on the **customer**, not the event. A borrower treated patiently
    after Monday's bounce and eagerly after Thursday's belongs to neither arm,
    and every number computed from that split is noise. blake2b rather than
    :func:`hash`, whose per-process randomisation would reassign everyone on
    restart.
    """
    buckets = ab_split()
    if not buckets or not customer_id:
        return None

    import hashlib

    digest = hashlib.blake2b(
        customer_id.encode("utf-8"), digest_size=8, person=b"treatmnt"
    ).digest()
    position = int.from_bytes(digest, "big") / float(1 << 64)

    cumulative = 0.0
    for name, share in buckets:
        cumulative += share
        if position < cumulative:
            return variants().get(name)
    return variants().get(buckets[-1][0])


def apply_variant(base: Policy, arm: Variant | None) -> Policy:
    """Overlay an arm's overrides on the process policy."""
    if arm is None:
        return base
    from dataclasses import replace

    changes: dict[str, float] = {}
    if arm.min_expected_value is not None:
        changes["min_expected_value"] = arm.min_expected_value
    if arm.urgency_halflife_hours is not None:
        changes["urgency_halflife_hours"] = max(1.0, arm.urgency_halflife_hours)
    return replace(base, **changes) if changes else base
