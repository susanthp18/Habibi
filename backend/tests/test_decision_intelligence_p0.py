"""P0 of the decision engine: the parts that cannot be added retrospectively.

Three things landed together, and each one is a claim that has to stay true:

* **Propensity and exploration.** A deterministic argmax records every action it
  took at probability 1.0, which makes the log useless for asking what a
  *different* policy would have recovered. Exploration runs strictly after the
  veto stack, so it changes which permitted thing happens and never whether a
  forbidden one does.
* **Interventions that reach nobody.** ``represent_mandate`` and
  ``emi_date_change`` bypass the contact cap and the calling window because they
  contact no one — which is why they carry limits of their own, and why the
  tests below spend more effort on what stops them than on what allows them.
* **Rules as versioned data.** The calling window used to be two module
  constants with no effective date. The question a regulator asks is not "would
  you dial at 19:15" but "why did you, last March", and a constant cannot
  answer it.

The regression this file exists for above all others is the first test: with the
default configuration, every one of these changes must leave the engine choosing
exactly what it chose before.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import policy_rules
from agent_core.treatment import (
    actions as A,
    arbitration,
    config,
    decisions,
    explore,
    policy as policy_mod,
    scoring,
    timing,
)
from agent_core.treatment.engine import (
    CONTROL_ARM,
    NON_CONTACT_HORIZON_MULTIPLIER,
    _horizon_for,
)
from agent_core.treatment.features import AccountFeatures, Trigger

NOW = datetime(2026, 8, 14, 6, 0, tzinfo=timezone.utc)


def make_features(**overrides) -> AccountFeatures:
    dpd = overrides.pop("dpd", 10)
    base: dict = {
        "customer_id": "probe-cust",
        "tenant_id": "hdfc.retail",
        "account_id": "probe-acct",
        "dpd": dpd,
        "bucket": A.bucket_for(dpd),
        "outstanding": 50_000.0,
        "instalment_amount": 5_000.0,
        "has_phone": True,
        "has_email": True,
        "daily_cap": 3,
        "timezone_name": "Asia/Kolkata",
    }
    base.update(overrides)
    return AccountFeatures(**base)


def _scored(*actions: str, evs: list[float] | None = None) -> list[scoring.ScoredAction]:
    """A ranked list, best first, with expected values we control."""
    values = evs or [100.0 - 10 * i for i in range(len(actions))]
    return [
        scoring.ScoredAction(
            action=action,
            channel=A.spec(action).channel,
            at=NOW,
            expected_value=value,
            p_reach=0.5,
            p_resolve=0.2,
            cost=1.0,
            explanation="probe",
        )
        for action, value in zip(actions, values)
    ]


# ---------------------------------------------------------------------------
# The regression that matters most: nothing changes until it is switched on
# ---------------------------------------------------------------------------


def test_the_default_configuration_is_a_deterministic_argmax() -> None:
    """The whole of P0 is inert until an operator turns the dial.

    Exploration that arrives switched on is exploration nobody chose to run.
    With ``TREATMENT_GREEDINESS`` at its default the engine picks the
    top-ranked approved action, every time, and the only observable difference
    from the engine that existed before this module is that the log now says
    the odds were 1.0.
    """
    assert config.greediness() == 1.0
    approved = _scored(A.WHATSAPP, A.SMS, A.VOICE_BOT)
    for _ in range(25):
        choice = explore.choose(approved, greediness=1.0, seed="anything")
        assert choice is not None
        assert choice.chosen.action == A.WHATSAPP
        assert choice.propensity == 1.0
        assert choice.kind == explore.KIND_GREEDY


def test_exploration_is_reproducible_for_one_decision() -> None:
    """Offline replay is how a challenger is evaluated before it meets a borrower.

    ``EVScorer`` already guarantees two identical runs cannot disagree.
    Exploration must not be the thing that breaks it.
    """
    approved = _scored(A.WHATSAPP, A.SMS, A.VOICE_BOT)
    first = explore.choose(approved, greediness=0.5, seed="cust|bounce|PE-1|a,b,c")
    for _ in range(10):
        again = explore.choose(approved, greediness=0.5, seed="cust|bounce|PE-1|a,b,c")
        assert again is not None and first is not None
        assert again.chosen.action == first.chosen.action
        assert again.propensity == pytest.approx(first.propensity)


def test_two_different_decisions_draw_independently() -> None:
    """A seed that ignored the decision would explore the same way for everyone,
    which is a deterministic policy with extra steps."""
    approved = _scored(A.WHATSAPP, A.SMS, A.VOICE_BOT, A.HUMAN_CALL)
    picks = {
        explore.choose(approved, greediness=0.35, seed=f"cust-{i}").chosen.action
        for i in range(40)
    }
    assert len(picks) > 1


def test_the_distribution_does_not_depend_on_the_size_of_the_account() -> None:
    """The regression that rules out a softmax over expected value.

    Scores are rupees and rupees are unbounded. A Boltzmann temperature tuned so
    a ₹68 account explores sensibly gives the second-best action a vanishing
    share on a ₹6,800 one, so the book would explore only where it has least to
    learn. Ranks have no scale, and this asserts that they do not acquire one.
    """
    small = _scored(A.WHATSAPP, A.SMS, A.VOICE_BOT, evs=[68.0, 41.0, 12.0])
    large = _scored(A.WHATSAPP, A.SMS, A.VOICE_BOT, evs=[6800.0, 4100.0, 1200.0])
    a = explore.choose(small, greediness=0.5, seed="s")
    b = explore.choose(large, greediness=0.5, seed="s")
    assert a is not None and b is not None
    assert a.distribution == pytest.approx(b.distribution)


def test_every_logged_probability_is_usable_as_a_divisor() -> None:
    """Off-policy estimators divide by this. A zero is a crash, and a value too
    small to store is a zero once it reaches the column."""
    approved = _scored(*[A.WHATSAPP, A.SMS, A.VOICE_BOT, A.HUMAN_CALL, A.FIELD_VISIT])
    for greed in (0.0, 0.25, 0.5, 0.75, 0.99):
        choice = explore.choose(approved, greediness=greed, seed="s")
        assert choice is not None
        assert choice.propensity >= explore.MIN_PROPENSITY
        assert sum(choice.distribution.values()) == pytest.approx(1.0)
        assert all(p > 0 for p in choice.distribution.values())


def test_greediness_is_monotone() -> None:
    """The dial must never explore *more* when turned up. A collections head is
    going to be shown this number, and a non-monotone control is not a control."""
    approved = _scored(A.WHATSAPP, A.SMS, A.VOICE_BOT, A.HUMAN_CALL)
    tops = [
        explore.choose(approved, greediness=g, seed="s").distribution[A.WHATSAPP]
        for g in (0.0, 0.25, 0.5, 0.75, 0.9)
    ]
    assert tops == sorted(tops)


# ---------------------------------------------------------------------------
# Ordering: explore over the approved set, never into it
# ---------------------------------------------------------------------------


def test_the_chooser_never_sees_an_action_below_the_value_floor() -> None:
    """§7's architectural boundary, as a test.

    Randomising between two already-compliant actions is defensible.
    Randomising and then checking compliance is experimenting on borrowers, and
    the difference is entirely in which list the chooser is handed.
    """
    seen: list[list[str]] = []

    def _spy(approved):
        seen.append([s.action for s in approved])
        return explore.choose(approved, greediness=0.0, seed="s")

    features = make_features()
    scored = _scored(A.WHATSAPP, A.SMS, A.VOICE_BOT, evs=[100.0, 50.0, -5.0])
    scored.append(
        scoring.ScoredAction(
            action=A.WAIT,
            channel=None,
            at=NOW,
            expected_value=0.0,
            p_reach=0.0,
            p_resolve=0.0,
            cost=0.0,
            explanation="hold",
        )
    )
    arbitration.arbitrate(
        features=features,
        trigger=Trigger(kind="dpd_tick", at=NOW),
        scored=scored,
        excluded={},
        policy=config.policy(),
        chooser=_spy,
    )
    assert seen, "the chooser was never called"
    assert A.VOICE_BOT not in seen[0], "an action below the floor reached the draw"
    assert A.WAIT not in seen[0]


def test_a_suppressed_decision_still_records_odds() -> None:
    """Silence is the negative class the corpus exists to carry. A NULL there
    makes every suppression invisible to an off-policy estimate."""
    features = make_features()
    verdict = arbitration.arbitrate(
        features=features,
        trigger=Trigger(kind="dpd_tick", at=NOW),
        scored=_scored(A.WHATSAPP, evs=[-50.0]),
        excluded={},
        policy=config.policy(),
    )
    assert verdict.suppressed
    assert verdict.propensity == 1.0


def test_silence_inside_a_randomised_arm_is_not_certain() -> None:
    """A borrower had to be assigned the arm before the gates could close on
    them. Recording 1.0 would tell an estimator that every control observation
    was inevitable, which is the opposite of what randomising it means."""
    verdict = arbitration.arbitrate(
        features=make_features(),
        trigger=Trigger(kind="dpd_tick", at=NOW),
        scored=_scored(A.WHATSAPP, evs=[-50.0]),
        excluded={},
        policy=config.policy(),
        arm_probability=0.2,
    )
    assert verdict.suppressed
    assert verdict.propensity == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# The control arm
# ---------------------------------------------------------------------------


def test_the_control_arm_is_not_the_control_variant(monkeypatch) -> None:
    """The naming hazard, pinned.

    ``control`` is the *treated* baseline — whatever the process is already set
    to. Reaching for it when measuring incremental effect contacts every
    borrower in it, so the measured uplift is zero by construction and looks
    like a finding.
    """
    arms = config.variants()
    assert arms["control"].suppress_discretionary is False
    assert arms["null_treatment"].suppress_discretionary is True


def test_the_control_arm_still_permits_a_statutory_notice() -> None:
    """§8. A borrower does not lose their right to a notice by being randomised
    into a measurement, and silence where the law requires speech is not a
    control group — it is a compliance breach that happens to be randomised."""
    from agent_core.treatment.engine import CONTROL_ARM_PERMITS

    assert A.LEGAL_NOTICE in CONTROL_ARM_PERMITS
    assert A.WAIT in CONTROL_ARM_PERMITS
    for action in (A.SMS, A.WHATSAPP, A.VOICE_BOT, A.HUMAN_CALL, A.FIELD_VISIT):
        assert action not in CONTROL_ARM_PERMITS
    # And a mandate presentment is discretionary too: it is cheap and invisible,
    # but it is still an intervention whose effect the arm exists to measure.
    assert A.REPRESENT_MANDATE not in CONTROL_ARM_PERMITS


def test_a_control_arm_decision_says_why_it_was_quiet(db_tx, monkeypatch) -> None:
    """A supervisor looking at a silent queue should not have to infer it from
    an arm name."""
    monkeypatch.setenv("TREATMENT_AB_SPLIT", "control:50,null_treatment:50")
    row = db_tx.execute(
        text(
            """
            SELECT a.id, a.customer_id FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE a.dpd BETWEEN 1 AND 30 AND c.phone_primary IS NOT NULL
            ORDER BY a.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("seed has no early-bucket account with a phone number")

    from agent_core.treatment.engine import recommend_treatment

    result = recommend_treatment(
        customer_id=row["customer_id"],
        account_id=row["id"],
        trigger=Trigger(kind="manual", at=NOW),
        conn=db_tx,
        variant="null_treatment",
        force_mode=config.MODE_LIVE,
    )
    assert result.action == A.WAIT
    assert result.excluded.get(A.WHATSAPP) == CONTROL_ARM
    assert result.excluded.get(A.VOICE_BOT) == CONTROL_ARM


# ---------------------------------------------------------------------------
# Interventions that reach nobody
# ---------------------------------------------------------------------------


def test_a_mandate_presentment_spends_no_contact_budget() -> None:
    """Derived, not declared — so a future channel=None action inherits the
    exemption without anyone remembering to list it."""
    assert A.spec(A.REPRESENT_MANDATE).channel is None
    assert A.REPRESENT_MANDATE not in A.CONTACTING
    assert A.REPRESENT_MANDATE in A.NON_CONTACTING
    assert scoring.fatigue_cost(
        A.REPRESENT_MANDATE, make_features(touches_today=3), policy=config.policy()
    ) == 0.0


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({}, policy_mod.NO_MANDATE),
        (
            {"mandate_id": "M1", "mandate_status": "cancelled"},
            policy_mod.MANDATE_NOT_ACTIVE,
        ),
        (
            {"mandate_id": "M1", "mandate_status": "active"},
            policy_mod.MANDATE_NO_CYCLE,
        ),
    ],
)
def test_the_mandate_veto_distinguishes_its_refusals(overrides, expected) -> None:
    """"We have no mandate", "the borrower cancelled it" and "there is nothing
    due" call for three different next actions, so they are three reasons."""
    features = make_features(**overrides)
    assert policy_mod._mandate_veto(None, features, at=NOW) == expected


def test_a_cancelled_mandate_is_never_presented_again() -> None:
    """Retrying does not recreate authority the borrower withdrew, and a debit
    against a withdrawn mandate is not a missed collection — it is an
    unauthorised debit."""
    from datetime import date

    features = make_features(
        mandate_id="M1",
        mandate_status="active",
        mandate_cycle=date(2026, 8, 1),
        mandate_last_return_reason="mandate_expired",
    )
    assert policy_mod._mandate_veto(None, features, at=NOW) == policy_mod.MANDATE_RETURN_BLOCKS


def test_two_presentations_of_one_cycle_do_not_overlap() -> None:
    """A NACH debit settles at T+1/T+2. Submitting again before the first has
    returned debits the borrower twice for one EMI, which is the fastest way to
    lose a mandate permanently."""
    from datetime import date

    features = make_features(
        mandate_id="M1",
        mandate_status="active",
        mandate_cycle=date(2026, 8, 1),
        mandate_last_presented_at=NOW - timedelta(hours=6),
    )
    assert policy_mod._mandate_veto(None, features, at=NOW) == policy_mod.MANDATE_TOO_SOON


def test_a_bank_side_failure_does_not_dun_the_borrower() -> None:
    """A technical return was never the borrower's doing. Chasing them for it is
    the collections equivalent of billing somebody for our own outage."""
    from datetime import date

    features = make_features(
        bounce_reason="technical",
        open_bounce_id="PE-1",
        mandate_id="M1",
        mandate_status="active",
        mandate_cycle=date(2026, 8, 1),
    )
    assert (
        policy_mod.veto(
            None,
            action=A.WHATSAPP,
            features=features,
            trigger=Trigger(kind="bounce", at=NOW),
            at=NOW,
            policy=config.policy(),
            last_rung=5,
        )
        == policy_mod.TECHNICAL_RETURN
    )


def test_the_suppression_lifts_once_the_fix_leaves_our_hands() -> None:
    """Suppressed only while re-presenting is still available. Once it is not,
    the money is genuinely outstanding and contact is legitimate again —
    otherwise a technical return would silence the account forever."""
    features = make_features(
        bounce_reason="technical", open_bounce_id="PE-1"
    )  # no mandate at all
    reason = policy_mod.veto(
        None,
        action=A.WHATSAPP,
        features=features,
        trigger=Trigger(kind="bounce", at=NOW),
        at=NOW,
        policy=config.policy(),
        last_rung=5,
    )
    assert reason != policy_mod.TECHNICAL_RETURN


def test_moving_the_emi_date_is_self_limiting() -> None:
    """No "already changed" flag to keep in sync: a successful change puts the
    salary credit ahead of the due date, the gap goes non-positive, and the
    veto starts firing on its own."""
    mismatched = make_features(emi_due_day=1, salary_credit_day=5)
    assert mismatched.salary_timing_gap_days == 4
    assert policy_mod._emi_date_veto(mismatched) is None

    fixed = make_features(emi_due_day=7, salary_credit_day=5)
    assert policy_mod._emi_date_veto(fixed) == policy_mod.EMI_DATE_ALIGNED


def test_the_timing_gap_wraps_around_the_month() -> None:
    """The distance between the 29th and the 2nd is four days, not twenty-seven.
    Without the wrap a borrower paid at month end reads as the worst mismatch in
    the book."""
    assert make_features(emi_due_day=29, salary_credit_day=2).salary_timing_gap_days == 3
    assert make_features(emi_due_day=2, salary_credit_day=29).salary_timing_gap_days == -3


# ---------------------------------------------------------------------------
# The horizon and the decay: found by the simulator, not by reading the code
# ---------------------------------------------------------------------------


def test_a_presentment_may_be_planned_as_far_out_as_payday() -> None:
    """The regression the corpus simulator found.

    ``TREATMENT_HORIZON_HOURS`` is a *contact* horizon: three days is about how
    long a decision to dial somebody stays relevant. Payday comes once a month,
    so a 72-hour horizon excluded the correctly-timed presentment for roughly
    nine days in ten — reported as ``no_slot_in_horizon``, which reads like a
    data gap rather than like a horizon that was never meant to answer this
    question. The action the design note calls the highest-ROI change in the
    system was being chosen about five percent of the time it was eligible.
    """
    policy = config.policy()
    assert _horizon_for(A.WHATSAPP, policy) == policy.planning_horizon_hours
    assert _horizon_for(A.REPRESENT_MANDATE, policy) == (
        policy.planning_horizon_hours * NON_CONTACT_HORIZON_MULTIPLIER
    )
    # Far enough to reach any payday in the month, which is the whole point.
    assert _horizon_for(A.REPRESENT_MANDATE, policy) >= 24 * 31


def test_a_debit_does_not_go_stale_the_way_an_argument_does() -> None:
    """The decay models persuasion going stale. Nobody has to be persuaded of a
    direct debit, so applying the contact half-life to one is a category error —
    and an expensive one, since it put the best action in the book below the
    value floor for all but a handful of borrowers."""
    payday = NOW + timedelta(days=14)
    contact = scoring.urgency_decay(
        payday, now=NOW, halflife_hours=36.0, action=A.WHATSAPP
    )
    debit = scoring.urgency_decay(
        payday, now=NOW, halflife_hours=36.0, action=A.REPRESENT_MANDATE
    )
    # Two orders of magnitude apart is the whole finding: at the contact
    # half-life a fortnight-out plan keeps 0.2% of its value, which is how the
    # best action in the book ended up below a ₹2 floor on every account.
    assert contact < 0.01, "a fortnight-old nudge should be worth almost nothing"
    assert debit > 0.5, "a debit timed to payday should keep most of its value"
    # Not exempt, though: waiting still costs, because the account rolls
    # further into delinquency and a mandate can be cancelled in the meantime.
    assert debit < 1.0


def test_a_presentment_waits_for_money_rather_than_guessing() -> None:
    """Declining to guess is the decision. A blind retry into an account we have
    no reason to think has been funded earns the borrower a bounce charge and us
    nothing."""
    blind = make_features(mandate_last_return_reason="insufficient_funds")
    slot = timing.plan(A.REPRESENT_MANDATE, blind, now=NOW, horizon_hours=72)
    assert not slot.feasible

    funded = make_features(
        mandate_last_return_reason="insufficient_funds",
        next_credit_at=NOW + timedelta(days=2),
    )
    assert timing.plan(A.REPRESENT_MANDATE, funded, now=NOW, horizon_hours=72).feasible


def test_a_bank_side_return_is_retried_at_once() -> None:
    """The money was there; the rail was not. There is nothing to wait for."""
    features = make_features(mandate_last_return_reason="technical")
    slot = timing.plan(A.REPRESENT_MANDATE, features, now=NOW, horizon_hours=72)
    assert slot.feasible and slot.at == NOW


# ---------------------------------------------------------------------------
# Rules as versioned data
# ---------------------------------------------------------------------------


def test_no_published_rules_means_the_constants_still_apply() -> None:
    """What makes the resolver deployable ahead of its data. "Unregulated by
    this table" must not read as "unrestricted"."""
    assert policy_rules.EMPTY.calling_window("voice") is None
    assert policy_rules.EMPTY.daily_cap() is None
    assert policy_rules.EMPTY.version is None

    import contact_policy

    # The fallback window is still the statutory one.
    assert (contact_policy.RBI_VOICE_START, contact_policy.RBI_VOICE_END) == (8, 19)


def test_a_later_layer_may_only_tighten() -> None:
    """A client who could widen the statutory window by adding a row would be a
    client who could delete the regulation. Enforced per rule kind rather than
    asserted in a comment."""
    window = policy_rules._tighten(
        policy_rules.KIND_CALLING_WINDOW,
        {"startHour": 8, "endHour": 19},
        {"startHour": 6, "endHour": 21},  # a client trying to open it up
    )
    assert (window["startHour"], window["endHour"]) == (8, 19)

    cap = policy_rules._tighten(
        policy_rules.KIND_DAILY_CAP, {"value": 3}, {"value": 9}
    )
    assert cap["value"] == 3

    cool = policy_rules._tighten(
        policy_rules.KIND_COOLING_OFF, {"minutes": 120}, {"minutes": 30}
    )
    assert cool["minutes"] == 120


def test_a_layer_may_withdraw_permission_but_never_grant_it() -> None:
    merged = policy_rules._tighten(
        policy_rules.KIND_MANDATE_RETURN,
        {"byReason": {"account_closed": "veto", "insufficient_funds": "allow"}},
        {"byReason": {"account_closed": "allow", "insufficient_funds": "veto"}},
    )
    assert merged["byReason"]["account_closed"] == "veto"
    assert merged["byReason"]["insufficient_funds"] == "veto"


def test_the_rules_in_force_depend_on_when_you_ask(db_tx) -> None:
    """The property the whole table exists for: same code, two instants, two
    answers, no deploy in between."""
    policy_rules.reset_cache()
    db_tx.execute(text("DELETE FROM policy_rules"))
    db_tx.execute(text("DELETE FROM policy_rule_sets"))
    for version, label, start, end in (
        (1, "old rules", datetime(2020, 1, 1, tzinfo=timezone.utc), datetime(2027, 1, 1, tzinfo=timezone.utc)),
        (2, "new rules", datetime(2027, 1, 1, tzinfo=timezone.utc), None),
    ):
        db_tx.execute(
            text(
                """
                INSERT INTO policy_rule_sets
                  (id, tenant_id, scope, version, label, effective_from, effective_to)
                VALUES (:id, NULL, 'statutory', :v, :label, :start, :end)
                """
            ),
            {"id": f"PRS-T{version}", "v": version, "label": label, "start": start, "end": end},
        )
        db_tx.execute(
            text(
                """
                INSERT INTO policy_rules (id, rule_set_id, kind, channel, params)
                VALUES (:id, :set_id, 'calling_window', 'voice', CAST(:p AS jsonb))
                """
            ),
            {
                "id": f"PR-T{version}",
                "set_id": f"PRS-T{version}",
                "p": '{"startHour": 8, "endHour": %d}' % (19 if version == 1 else 18),
            },
        )

    before = policy_rules.resolve(
        db_tx, tenant_id="hdfc.retail", at=datetime(2026, 3, 1, tzinfo=timezone.utc)
    )
    after = policy_rules.resolve(
        db_tx, tenant_id="hdfc.retail", at=datetime(2027, 3, 1, tzinfo=timezone.utc)
    )
    policy_rules.reset_cache()

    assert before.version == 1 and before.calling_window("voice") == (8, 19)
    assert after.version == 2 and after.calling_window("voice") == (8, 18)


def test_a_broken_resolver_does_not_take_the_contact_gate_down() -> None:
    """A gate that is down fails closed on every borrower in the book. Degrading
    to the constants is a known-good state; raising is an outage."""

    class Exploding:
        def execute(self, *_a, **_k):
            raise RuntimeError("database is on fire")

    policy_rules.reset_cache()
    resolved = policy_rules.resolve(Exploding(), tenant_id="t", at=NOW)
    policy_rules.reset_cache()
    assert resolved is policy_rules.EMPTY


# ---------------------------------------------------------------------------
# The simulated corpus must never touch a borrower
# ---------------------------------------------------------------------------


def test_the_executor_cannot_claim_a_simulated_plan(db_tx) -> None:
    """The only thing between a generated borrower and a real outbound message.

    The simulator writes decisions that look exactly like live ones, because
    that is the point of it: same engine, same vetoes, same schedule. Which
    means the mode stamp and this predicate are the entire safety story.
    """
    row = db_tx.execute(
        text(
            """
            SELECT a.id, a.customer_id FROM accounts a
            WHERE a.dpd > 0 ORDER BY a.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("seed has no delinquent account")

    for mode in (config.MODE_LIVE, config.MODE_SIMULATED):
        decisions.record(
            conn=db_tx,
            tenant_id="hdfc.retail",
            customer_id=row["customer_id"],
            account_id=row["id"],
            interaction_id=None,
            trigger_kind="manual",
            trigger_ref=f"claim-probe-{mode}",
            mode=mode,
            variant=None,
            recommender="ev",
            recommender_version="1.0.0",
            feature_schema_version="v3",
            features={},
            candidates=[],
            excluded={},
            chosen_action=A.WHATSAPP,
            chosen_channel="whatsapp",
            scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            expected_value=50.0,
            suppression_reason=None,
            rationale="probe",
            latency_ms=1,
            propensity=1.0,
        )

    claimed = decisions.claim_due(db_tx, limit=50)
    modes = {c["mode"] for c in claimed}
    assert config.MODE_SIMULATED not in modes


def test_simulated_is_not_a_mode_the_engine_can_be_set_to(monkeypatch) -> None:
    """It is a stamp on rows, not a setting. Allowing it as a mode would let a
    typo put a live deployment into a state nothing else in the system expects."""
    monkeypatch.setenv("TREATMENT_MODE", config.MODE_SIMULATED)
    assert config.mode() == config.MODE_SHADOW


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


def test_the_sweep_is_off_until_somebody_turns_it_on(monkeypatch) -> None:
    """A worker that starts deciding across an entire book the moment it is
    deployed is a worker nobody chose to run."""
    from agent_core.treatment import sweep

    monkeypatch.delenv("TREATMENT_SWEEP", raising=False)
    assert sweep.enabled() is False
    monkeypatch.setenv("TREATMENT_SWEEP", "1")
    assert sweep.enabled() is True


def test_the_sweep_decides_the_book_and_then_stops(db_tx, monkeypatch) -> None:
    """The corpus generator, end to end against the real schema.

    Worth an integration test rather than unit coverage of its parts: the bug
    this caught first time was Postgres declining to infer a bind parameter's
    type inside ``jsonb_build_object``, which every mocked test in the world
    would have passed. The sweep either writes rows into a real table or it does
    not exist.

    Two properties, and the second is the one that matters operationally: a
    sweep that reported work on an empty batch would spin, and starve every
    other loop in ``bot_worker``.
    """
    import db as dbmod
    from agent_core.treatment import sweep

    monkeypatch.setenv("TREATMENT_SWEEP", "1")
    monkeypatch.setenv("TREATMENT_MODE", config.MODE_SHADOW)

    # Clear today's sweep and the cursor inside the fixture's transaction, so
    # the write path is exercised on every run rather than only on the first
    # one of the day. Without this the test passes vacuously the moment anybody
    # has swept the dev database, which is the state it will spend most of its
    # life in.
    db_tx.execute(
        text(
            "DELETE FROM treatment_decisions WHERE trigger_kind = 'dpd_tick'"
            " AND created_at >= now() - interval '2 days'"
        )
    )
    db_tx.execute(
        text("DELETE FROM work_runtime_jobs WHERE workflow_type = :w"),
        {"w": sweep.CURSOR_WORKFLOW},
    )

    before = db_tx.execute(
        text("SELECT count(*) FROM treatment_decisions WHERE trigger_kind = 'dpd_tick'")
    ).scalar()

    assert sweep.process_one(dbmod.engine) is True
    after = db_tx.execute(
        text("SELECT count(*) FROM treatment_decisions WHERE trigger_kind = 'dpd_tick'")
    ).scalar()
    assert after > before, "the sweep decided nobody"

    # Running it again on the same day must not decide anybody twice.
    repeat = sweep.process_one(dbmod.engine)
    twice = db_tx.execute(
        text("SELECT count(*) FROM treatment_decisions WHERE trigger_kind = 'dpd_tick'")
    ).scalar()
    assert repeat is False
    assert twice == after


def test_every_sweep_decision_carries_the_columns_it_exists_for(db_tx, monkeypatch) -> None:
    """A corpus row without a propensity is a row no estimator can use, and a
    row without a policy version cannot answer "under which rules?"."""
    import db as dbmod
    from agent_core.treatment import sweep

    monkeypatch.setenv("TREATMENT_SWEEP", "1")
    monkeypatch.setenv("TREATMENT_MODE", config.MODE_SHADOW)
    sweep.process_one(dbmod.engine)

    gaps = db_tx.execute(
        text(
            """
            SELECT count(*) FROM treatment_decisions
            WHERE trigger_kind = 'dpd_tick' AND propensity IS NULL
            """
        )
    ).scalar()
    assert gaps == 0


def test_the_sweep_keys_a_case_on_the_borrowers_own_day() -> None:
    """A "day" is the borrower's day. An account swept at 23:30 IST and again at
    00:30 IST has been swept twice; under UTC dates it would look like once."""
    from agent_core.treatment import sweep

    late = datetime(2026, 8, 20, 18, 30, tzinfo=timezone.utc)  # 00:00 IST on the 21st
    assert sweep._local_day(late, "Asia/Kolkata") == "2026-08-21"
    assert sweep._local_day(late, "UTC") == "2026-08-20"
