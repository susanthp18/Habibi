"""R-INJ-1 — where every model input came from, and what that permits.

§12.3 of ``engines-production-design.md``:

    Every perception field is tagged with its provenance, and no field whose
    declared input set includes borrower speech may enter the EV vector as a
    numeric — whether or not a classifier wraps it.

The rule is easy to state and easy to lose. The design note says so itself:
naming ``cooperation band`` and ``p(hardship)`` as the examples of an
admissible ``model_inference`` "leaves the invariant intact in prose and gone
in code", because both are functions of speech. So the rule lives here as
data, and three enforcement points read it:

1. **Artifact load.** ``treatment.models.load_artifact`` and
   ``reco.models.load_artifact`` refuse an artifact that names a speech-derived
   feature, that declares ``borrower_utterance`` in its own ``inputProvenance``,
   or — the load-bearing one — **that names a feature this registry has never
   heard of**. Unknown is refused rather than permitted, because a rule whose
   default is "allow" is a comment.
2. **The veto stack.** ``treatment.policy._speech_veto`` may only ever add a
   veto. That is enforced by the shape of the function, not by review.
3. **Calibration.** A ``model_inference`` feature over non-speech inputs is
   EV-admissible only with a per-stratum calibration record. The check is here;
   producing the strata is W10/W11's work.

The threat this closes is not primarily adversarial. A miscalibrated signal
derived from how a borrower *sounds* raises the expected value of pursuing the
borrowers who sound a particular way, which is a fluency and dialect
classifier under another name — and the Voice of India benchmark measures a
systematic 19–21% male-speaker penalty across every Tier-I ASR architecture,
so the upstream signal is already differentially noisy by demographic before a
classifier touches it.

**Why the two engines get different answers, stated so it is a decision rather
than an oversight.** R-INJ-1 governs the *collections* EV, where the quantity
being maximised is how hard to pursue a delinquent borrower — and "she sounded
cooperative, so call her again" is the failure. The recommendation engine ranks
product offers during a call the borrower is already on, and its whole premise
is that what they asked about should decide what they are shown. So its
in-call signals are admitted, by name, in :data:`RECO_SPEECH_ADMITTED`. A
ninth in-call signal is still refused until somebody adds it there and says
why. Neither engine may admit a speech-derived feature into a *contacting*
decision, which is the property the treatment registry holds.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Ledger entries, DPD, NACH return codes, delivery receipts. May enter EV and
#: the veto stack.
SYSTEM_OF_RECORD = "system_of_record"
#: A supervisor's hold, an agent's correction. May enter EV with the actor
#: logged, and the veto stack.
OPERATOR_INPUT = "operator_input"
#: What the borrower said. Never EV; the veto stack only, and only as a flag.
BORROWER_UTTERANCE = "borrower_utterance"
#: A model's output. EV only with a live per-stratum calibration record, and
#: never where any of the model's own inputs was speech.
MODEL_INFERENCE = "model_inference"

CLASSES: frozenset[str] = frozenset(
    {SYSTEM_OF_RECORD, OPERATOR_INPUT, BORROWER_UTTERANCE, MODEL_INFERENCE}
)

#: The classes a feature may not carry into an EV vector without an explicit
#: admission. ``MODEL_INFERENCE`` is not here: it is conditionally admissible,
#: which :meth:`Registry.refuse` handles separately.
SPEECH_DERIVED: frozenset[str] = frozenset({BORROWER_UTTERANCE})


class ProvenanceUndeclared(KeyError):
    """A vector key exists that this registry does not classify."""


@dataclass(frozen=True)
class Registry:
    """One engine's vector, every key classified."""

    name: str
    provenance: dict[str, str]
    #: Keys the vector emits but no artifact ever carries — the engine's own
    #: priors, which the trainer strips. Registered so the completeness test
    #: passes; never reachable through an artifact.
    derived: frozenset[str] = frozenset()
    #: Speech-derived keys this engine admits anyway, each because the module
    #: docstring says why. Empty for anything that decides whether to contact.
    speech_admitted: frozenset[str] = frozenset()

    def classify(self, key: str) -> str:
        try:
            return self.provenance[key]
        except KeyError as exc:  # pragma: no cover - the message is the point
            raise ProvenanceUndeclared(
                f"{self.name} vector key {key!r} declares no provenance — "
                "add it to agent_core.feature_provenance"
            ) from exc

    def refuse(
        self,
        feature_names: object,
        *,
        declared: object = (),
        calibration_strata: object = None,
    ) -> str | None:
        """Why this feature set may not enter the EV, or None if it may.

        Returns a short reason rather than raising, because every caller is an
        artifact loader whose contract is to refuse quietly and score on the
        priors instead — a loader that raises takes the engine down, which is
        strictly worse than one that declines to use a model.
        """
        # An engine that admits named in-call signals has already answered this
        # question for itself; asking it again by way of a whole-model
        # declaration would refuse the artifact that honestly says what it read.
        if not self.speech_admitted:
            for value in tuple(declared or ()):
                if str(value) in SPEECH_DERIVED:
                    return f"declares input provenance {value!r}"

        strata = dict(calibration_strata or {})
        for raw in tuple(feature_names or ()):
            key = str(raw)
            if key in self.speech_admitted:
                continue
            try:
                kind = self.classify(key)
            except ProvenanceUndeclared:
                return f"feature {key!r} declares no provenance"
            if kind in SPEECH_DERIVED:
                return f"feature {key!r} is {kind} and may never enter the EV"
            if kind == MODEL_INFERENCE and not strata:
                # Aggregate ECE is not enough: a model can be well calibrated
                # overall and badly calibrated on the hardship stratum, which
                # is the one stratum where the EV contribution matters.
                return f"feature {key!r} is a model inference with no per-stratum calibration"
        return None


# ---------------------------------------------------------------------------
# The treatment engine — agent_core.treatment.scoring.vector
# ---------------------------------------------------------------------------

TREATMENT = Registry(
    name="treatment",
    derived=frozenset({"p_reach", "p_resolve", "cost"}),
    provenance={
        # --- the action being priced ---------------------------------------
        # Ours, not the borrower's: which rung of the ladder, and how intrusive
        # the action is. Constants from the action table.
        "rung": SYSTEM_OF_RECORD,
        "intrusiveness": SYSTEM_OF_RECORD,
        "planned_delay_hours": SYSTEM_OF_RECORD,
        "trigger_age_hours": SYSTEM_OF_RECORD,
        # --- the engine's own priors, stripped before training --------------
        "p_reach": MODEL_INFERENCE,
        "p_resolve": MODEL_INFERENCE,
        "cost": MODEL_INFERENCE,
        # --- the ledger -----------------------------------------------------
        "exposure": SYSTEM_OF_RECORD,
        "dpd": SYSTEM_OF_RECORD,
        "days_overdue": SYSTEM_OF_RECORD,
        "bucket_curability": SYSTEM_OF_RECORD,
        "open_bounce": SYSTEM_OF_RECORD,
        "secured": SYSTEM_OF_RECORD,
        "bounce_insufficient_funds": SYSTEM_OF_RECORD,
        "bounce_mandate_expired": SYSTEM_OF_RECORD,
        "bounce_account_closed": SYSTEM_OF_RECORD,
        "bounce_technical": SYSTEM_OF_RECORD,
        "has_mandate": SYSTEM_OF_RECORD,
        "mandate_active": SYSTEM_OF_RECORD,
        "mandate_attempts_this_cycle": SYSTEM_OF_RECORD,
        "salary_timing_gap_days": SYSTEM_OF_RECORD,
        # --- our own ledger of what we did ----------------------------------
        "promises_total": SYSTEM_OF_RECORD,
        "promises_broken": SYSTEM_OF_RECORD,
        "ptp_keep_rate": SYSTEM_OF_RECORD,
        "touches_today": SYSTEM_OF_RECORD,
        "touches_7d": SYSTEM_OF_RECORD,
        "digital_attempts_since_connect": SYSTEM_OF_RECORD,
        "connect_rate_channel": SYSTEM_OF_RECORD,
        "case_attempts": SYSTEM_OF_RECORD,
        "this_action_tried": SYSTEM_OF_RECORD,
        "hours_since_last_attempt": SYSTEM_OF_RECORD,
        "field_visits_90d": SYSTEM_OF_RECORD,
        "has_email": SYSTEM_OF_RECORD,
        # --- filed by a person ----------------------------------------------
        "open_disputes": OPERATOR_INPUT,
        "risk_score": OPERATOR_INPUT,
        # A hold placed by a supervisor is operator input. A hold placed by the
        # bot from what the borrower said on a call is not, and
        # ``treatment_holds.source`` is what tells them apart — which is why
        # ``scoring.vector`` counts only the non-speech ones here. The veto
        # stack still sees every hold; see ``features.AccountFeatures.holds``.
        "on_hold": OPERATOR_INPUT,
    },
)


# ---------------------------------------------------------------------------
# The recommendation engine — agent_core.reco.vectorize.vector
# ---------------------------------------------------------------------------

#: The in-call signals the offer ranker is allowed to read. Each one is what
#: the borrower asked about on a call they are already on; none of them decides
#: whether to contact anybody. See the module docstring.
RECO_SPEECH_ADMITTED: frozenset[str] = frozenset(
    {
        "in_call_intent",
        "sentiment",
        "sentiment_trend",
        "product_mentioned",
        "kb_topic_match",
        "commitment_secured",
        "customer_turns",
    }
)

RECO = Registry(
    name="reco",
    speech_admitted=RECO_SPEECH_ADMITTED,
    provenance={
        # --- the catalogue ---------------------------------------------------
        "affinity": SYSTEM_OF_RECORD,
        "margin_score": SYSTEM_OF_RECORD,
        "campaign_priority": SYSTEM_OF_RECORD,
        "has_campaign": SYSTEM_OF_RECORD,
        # --- the customer's own record --------------------------------------
        "affordability": SYSTEM_OF_RECORD,
        "credit_health": SYSTEM_OF_RECORD,
        "fatigue": SYSTEM_OF_RECORD,
        "exit_intent": SYSTEM_OF_RECORD,
        "dpd_worst": SYSTEM_OF_RECORD,
        "utilization": SYSTEM_OF_RECORD,
        "relationship_months": SYSTEM_OF_RECORD,
        "account_count": SYSTEM_OF_RECORD,
        "months_since_last_payment": SYSTEM_OF_RECORD,
        "offers_last_30d": SYSTEM_OF_RECORD,
        "prior_win_rate": SYSTEM_OF_RECORD,
        "open_disputes": OPERATOR_INPUT,
        # --- the call in progress -------------------------------------------
        "in_call_intent": BORROWER_UTTERANCE,
        "sentiment": BORROWER_UTTERANCE,
        "sentiment_trend": BORROWER_UTTERANCE,
        "product_mentioned": BORROWER_UTTERANCE,
        "kb_topic_match": BORROWER_UTTERANCE,
        "commitment_secured": BORROWER_UTTERANCE,
        "customer_turns": BORROWER_UTTERANCE,
    },
)
