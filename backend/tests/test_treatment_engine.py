"""The next-best-treatment engine (P3).

The engine decides whether a borrower gets contacted, on which channel, and at
what hour. Almost everything worth testing here is a *restraint* — a case where
the right answer is to do less than the score suggests — because a recommender
that only ever over-contacts still looks like it works right up until the point
somebody complains to the regulator.

Split deliberately:

* the pure layers (actions, timing, policy, scoring, arbitration, rerank) are
  tested against constructed feature vectors, so a restraint can be exercised
  without a fixture that reproduces a whole delinquent account;
* the engine and the executor are tested against the real database, because
  their contracts are about transactions, logging and idempotency, and a mock
  would agree with whatever the code happens to do.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import contact_policy
from agent_core.treatment import (
    actions as A,
    arbitration,
    config,
    decisions,
    enact,
    narrate,
    policy as policy_mod,
    rerank,
    scoring,
    timing,
)
from agent_core.treatment.engine import recommend_treatment
from agent_core.treatment.features import AccountFeatures, Trigger

#: 11:30 IST on a Friday — inside RBI's 08:00–19:00 window, so a test about
#: something other than calling hours is not silently a test about calling
#: hours.
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


@pytest.fixture
def allow_contact(monkeypatch):
    """Contact policy says yes, so a veto test is about the veto under test."""
    monkeypatch.setattr(
        contact_policy,
        "evaluate",
        lambda *a, **k: contact_policy.Decision(True, daily_cap=3),
    )


@pytest.fixture
def deny_contact(monkeypatch):
    def _deny(reason: str = contact_policy.REASON_DAILY):
        monkeypatch.setattr(
            contact_policy,
            "evaluate",
            lambda *a, **k: contact_policy.Decision(False, reason, daily_cap=3),
        )

    return _deny


def veto(action: str, features: AccountFeatures, **kw) -> str | None:
    return policy_mod.veto(
        None,
        action=action,
        features=features,
        trigger=kw.pop("trigger", Trigger(kind="dpd_tick", at=NOW)),
        at=kw.pop("at", NOW),
        policy=kw.pop("policy", config.policy()),
        last_rung=kw.pop("last_rung", 5),
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_default_mode_is_shadow(monkeypatch) -> None:
    monkeypatch.delenv("TREATMENT_MODE", raising=False)
    assert config.mode() == config.MODE_SHADOW


def test_an_unrecognised_mode_degrades_to_shadow_not_off(monkeypatch) -> None:
    """A typo must not silently stop collecting the data the rollout decision
    depends on. Same rule reco follows, for the same reason."""
    monkeypatch.setenv("TREATMENT_MODE", "lvie")
    assert config.mode() == config.MODE_SHADOW


def test_variants_bucket_on_the_customer_not_the_event(monkeypatch) -> None:
    monkeypatch.setenv("TREATMENT_AB_SPLIT", "control:50,patient:50")
    first = config.assign_variant("vikram-rao")
    for _ in range(20):
        assert config.assign_variant("vikram-rao") == first
    assert first is not None


def test_an_unknown_variant_falls_back_rather_than_inventing_an_arm() -> None:
    assert config.resolve_variant("does-not-exist") is None
    assert config.resolve_variant("patient") is not None


def test_a_variant_overlays_only_what_it_declares() -> None:
    base = config.policy()
    arm = config.variants()["patient"]
    tuned = config.apply_variant(base, arm)
    assert tuned.min_expected_value != base.min_expected_value
    assert tuned.recovery_fraction == base.recovery_fraction


# ---------------------------------------------------------------------------
# The action space
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dpd,expected",
    [
        (None, A.PRE_DUE),
        (0, A.PRE_DUE),
        (1, A.B_0_30),
        (30, A.B_0_30),
        (31, A.B_31_60),
        (60, A.B_31_60),
        (61, A.B_61_90),
        (90, A.B_61_90),
        (91, A.B_90_PLUS),
    ],
)
def test_dpd_maps_to_the_documented_bucket(dpd, expected: str) -> None:
    assert A.bucket_for(dpd) == expected


def test_waiting_is_permitted_in_every_bucket() -> None:
    """There must be no state with no legal action. Otherwise the engine has to
    invent one, and inventing one is how a 90+ distress case gets an SMS."""
    for bucket in A.BUCKET_ORDER:
        assert A.WAIT in A.bucket_policy(bucket).allowed


def test_a_bot_may_not_dial_an_npa_account() -> None:
    """90+ is a specialist's judgment. The published ~10% AI share there is
    logistics confirmation, and this engine cannot tell a logistics ping from a
    dunning call — so it emits neither."""
    assert A.VOICE_BOT not in A.bucket_policy(A.B_90_PLUS).allowed
    assert A.HUMAN_CALL in A.bucket_policy(A.B_90_PLUS).allowed


def test_pre_due_reaches_nobody_by_voice_or_doorstep() -> None:
    """The highest-ROI window in the book, and the one where a dial reads as
    harassment.

    Stated as a property rather than as a literal set, because the set has
    legitimately grown: ``represent_mandate`` and ``emi_date_change`` are
    pre-due actions that contact nobody at all. A frozen set would have failed
    on those without anything being wrong, and — worse — a frozen set fails
    just as loudly when something genuinely is, so nobody would have looked.
    What must stay true is that nothing in this bucket rings a phone or knocks
    on a door.
    """
    allowed = A.bucket_policy(A.PRE_DUE).allowed
    assert A.WAIT in allowed
    assert {A.SMS, A.WHATSAPP} <= allowed
    channels = {A.spec(a).channel for a in allowed}
    assert channels <= {None, "sms", "whatsapp", "email"}
    assert all(A.spec(a).digital for a in allowed & A.CONTACTING)


def test_every_action_has_a_spec_and_a_label() -> None:
    for action in A.ALL:
        assert A.spec(action).key == action
        assert A.label(action)


def test_escalation_rungs_are_strictly_ordered() -> None:
    ladder = [A.WAIT, A.SMS, A.VOICE_BOT, A.HUMAN_CALL, A.FIELD_VISIT, A.LEGAL_NOTICE]
    assert [A.rung(a) for a in ladder] == sorted(A.rung(a) for a in ladder)
    assert A.rung(A.SMS) == A.rung(A.WHATSAPP)


def test_a_statutory_notice_consumes_no_contact_budget() -> None:
    """A demand under NI Act s.138 is served by post and is time-barred.
    Letting a goodwill budget defer it would let a frequency cap invalidate a
    recovery."""
    assert A.spec(A.LEGAL_NOTICE).channel is None
    assert A.LEGAL_NOTICE not in A.CONTACTING


def test_an_agent_dial_costs_the_same_budget_as_a_bot_dial() -> None:
    """The entire point of the cross-channel cap: a borrower does not
    experience a telecaller and a bot as two separate allowances."""
    assert A.spec(A.HUMAN_CALL).channel == A.spec(A.VOICE_BOT).channel == "voice"


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------


def _ist_hour(moment: datetime) -> int:
    from zoneinfo import ZoneInfo

    return moment.astimezone(ZoneInfo("Asia/Kolkata")).hour


def test_a_dial_planned_at_night_lands_inside_rbi_hours() -> None:
    midnight_ist = datetime(2026, 8, 13, 20, 0, tzinfo=timezone.utc)  # 01:30 IST
    slot = timing.plan(A.VOICE_BOT, make_features(), now=midnight_ist, horizon_hours=72)
    assert slot.feasible
    assert _ist_hour(slot.at) == contact_policy.RBI_VOICE_START


def test_a_message_is_not_forced_into_the_voice_window() -> None:
    """An SMS at 21:00 is not a recovery call. Deferring it to 08:00 would push
    a pay-link past the moment the borrower was looking at their phone."""
    evening = datetime(2026, 8, 14, 15, 30, tzinfo=timezone.utc)  # 21:00 IST
    slot = timing.plan(A.SMS, make_features(), now=evening, horizon_hours=72)
    assert slot.at == evening


def test_the_consented_window_narrows_the_statutory_one() -> None:
    early = datetime(2026, 8, 14, 3, 0, tzinfo=timezone.utc)  # 08:30 IST
    slot = timing.plan(
        A.VOICE_BOT,
        make_features(allowed_hours=(10, 18)),
        now=early,
        horizon_hours=72,
    )
    assert _ist_hour(slot.at) == 10


def test_a_digital_nudge_is_timed_to_the_salary_credit() -> None:
    """Finezza: salary-credited balances peak within ~48h of credit. Retrying
    against the credit rather than the calendar is the highest-yield timing
    decision in the early buckets."""
    credit = NOW + timedelta(hours=20)
    slot = timing.plan(
        A.WHATSAPP,
        make_features(
            next_credit_at=credit,
            open_bounce_id="PE-1",
            bounce_reason="insufficient_funds",
        ),
        now=NOW,
        horizon_hours=72,
    )
    assert slot.at >= credit
    assert "salary" in slot.rationale


def test_a_salary_hint_is_ignored_when_the_bounce_was_not_about_money() -> None:
    slot = timing.plan(
        A.WHATSAPP,
        make_features(
            next_credit_at=NOW + timedelta(hours=20),
            open_bounce_id="PE-1",
            bounce_reason="mandate_expired",
        ),
        now=NOW,
        horizon_hours=72,
    )
    assert slot.at == NOW


def test_a_field_visit_gives_a_days_notice_and_avoids_sunday() -> None:
    slot = timing.plan(A.FIELD_VISIT, make_features(), now=NOW, horizon_hours=72)
    assert slot.feasible
    assert slot.at - NOW >= timedelta(hours=timing.FIELD_NOTICE_HOURS)
    assert timing._local_day_index(slot.at.astimezone()) != timing._SUNDAY


def test_a_dial_prefers_an_hour_the_borrower_has_answered_at() -> None:
    slot = timing.plan(
        A.VOICE_BOT,
        make_features(responsive_hours=(17,)),
        now=NOW,
        horizon_hours=72,
    )
    assert _ist_hour(slot.at) == 17
    assert "answered" in slot.rationale


def test_an_empty_consent_window_yields_no_slot_rather_than_a_guess() -> None:
    slot = timing.plan(
        A.VOICE_BOT,
        make_features(allowed_hours=(20, 22)),  # disjoint from 08:00–19:00
        now=NOW,
        horizon_hours=72,
    )
    assert not slot.feasible


def test_a_statutory_notice_is_not_deferred_to_a_calling_window() -> None:
    midnight = datetime(2026, 8, 13, 20, 0, tzinfo=timezone.utc)
    slot = timing.plan(A.LEGAL_NOTICE, make_features(dpd=120), now=midnight, horizon_hours=72)
    assert slot.at == midnight


# ---------------------------------------------------------------------------
# Vetoes
# ---------------------------------------------------------------------------


def test_waiting_is_never_vetoed() -> None:
    held = make_features(holds=("hardship", "legal", "complaint"), has_phone=False)
    assert veto(A.WAIT, held) is None


@pytest.mark.parametrize("kind", ["hardship", "complaint", "bereavement"])
def test_a_silencing_hold_stops_every_contact(kind: str, allow_contact) -> None:
    held = make_features(holds=(kind,))
    for action in (A.SMS, A.WHATSAPP, A.VOICE_BOT, A.HUMAN_CALL, A.FIELD_VISIT):
        assert veto(action, held) == f"hold:{kind}"


def test_a_legal_hold_still_permits_the_statutory_notice(allow_contact) -> None:
    """Once a matter is with legal, the clock is the only thing that may still
    fire. Blocking the notice too would let a hold invalidate the recovery it
    exists to protect."""
    held = make_features(dpd=120, holds=("legal",))
    assert veto(A.WHATSAPP, held) == "hold:legal"
    assert veto(A.LEGAL_NOTICE, held) is None


def test_a_dispute_hold_still_permits_a_specialist_call(allow_contact) -> None:
    """A dispute stops pressure about the amount. It must not stop a human
    ringing about the dispute itself, or the borrower is left with an open
    dispute nobody calls about."""
    held = make_features(holds=("dispute",))
    assert veto(A.WHATSAPP, held) == "hold:dispute"
    assert veto(A.HUMAN_CALL, held) is None


def test_the_bucket_gates_the_action(allow_contact) -> None:
    assert veto(A.VOICE_BOT, make_features(dpd=0)) == policy_mod.BUCKET_DISALLOWS
    assert veto(A.VOICE_BOT, make_features(dpd=95)) == policy_mod.BUCKET_DISALLOWS


def test_a_borrower_who_owes_nothing_is_not_contacted(allow_contact) -> None:
    assert (
        veto(A.WHATSAPP, make_features(instalment_amount=0, minimum_due=0, outstanding=0))
        == policy_mod.NO_EXPOSURE
    )


def test_a_closed_account_is_not_chased(allow_contact) -> None:
    assert veto(A.WHATSAPP, make_features(account_status="settled")) == policy_mod.ACCOUNT_CLOSED


def test_an_account_in_good_standing_gets_a_reminder_but_not_a_dial(allow_contact) -> None:
    current = make_features(dpd=0)
    assert veto(A.WHATSAPP, current) is None
    # Structurally blocked by the bucket before the delinquency test is reached,
    # which is the stronger of the two guards.
    assert veto(A.HUMAN_CALL, current) == policy_mod.BUCKET_DISALLOWS


def test_the_ladder_allows_one_rung_at_a_time(allow_contact) -> None:
    """Digital straight to a doorstep is how a three-day-old miss ends up with
    someone at the door — the single most complained-about behaviour on a
    collections floor."""
    f = make_features(dpd=45, secured=True, digital_attempts_since_connect=9)
    assert veto(A.VOICE_BOT, f, last_rung=1) is None
    assert veto(A.FIELD_VISIT, f, last_rung=1) == policy_mod.LADDER_TOO_FAR
    assert veto(A.FIELD_VISIT, f, last_rung=3) is None


def test_a_field_visit_waits_for_digital_to_be_exhausted(allow_contact) -> None:
    """₹800–1,500 a visit with the borrower absent 40–50% of the time. Digital
    first is arithmetic, not politeness."""
    f = make_features(dpd=45, secured=True, digital_attempts_since_connect=1)
    assert veto(A.FIELD_VISIT, f) == policy_mod.DIGITAL_NOT_EXHAUSTED


def test_a_field_visit_is_not_sent_for_a_trivial_amount(allow_contact) -> None:
    f = make_features(
        dpd=45, secured=True, digital_attempts_since_connect=9, instalment_amount=900.0
    )
    assert veto(A.FIELD_VISIT, f) == policy_mod.FIELD_NOT_PROPORTIONATE


def test_a_second_field_visit_needs_the_ladder_walked_again(allow_contact) -> None:
    f = make_features(
        dpd=45, secured=True, digital_attempts_since_connect=9, field_visits_90d=1
    )
    assert veto(A.FIELD_VISIT, f) == policy_mod.FIELD_ALREADY_DISPATCHED


def test_a_statutory_notice_waits_for_the_clock_to_be_real(allow_contact) -> None:
    fresh = make_features(dpd=45, open_bounce_id="PE-1", bounce_age_hours=6)
    assert veto(A.LEGAL_NOTICE, fresh) == policy_mod.BUCKET_DISALLOWS

    aged = make_features(dpd=75, open_bounce_id="PE-1", bounce_age_hours=6)
    assert veto(A.LEGAL_NOTICE, aged) == policy_mod.LEGAL_PREREQUISITES

    ripe = make_features(dpd=75, open_bounce_id="PE-1", bounce_age_hours=24 * 25)
    assert veto(A.LEGAL_NOTICE, ripe) is None


def test_a_notice_is_not_served_twice(allow_contact) -> None:
    f = make_features(dpd=120, legal_notice_at=NOW - timedelta(days=3))
    assert veto(A.LEGAL_NOTICE, f) == policy_mod.LEGAL_ALREADY_SERVED


def test_no_phone_means_no_message(allow_contact) -> None:
    assert veto(A.WHATSAPP, make_features(has_phone=False)) == policy_mod.NO_PHONE


def test_the_contact_policy_is_delegated_to_not_reimplemented(deny_contact) -> None:
    """One definition of RBI hours, DND, opt-out, the caps and cooling-off,
    shared with the dialler, the WhatsApp drain and the PTP confirm. A second
    copy that agreed in August is one that disagrees in November."""
    deny_contact(contact_policy.REASON_HOURS)
    assert veto(A.VOICE_BOT, make_features()) == f"contact:{contact_policy.REASON_HOURS}"


def test_an_unreadable_consent_record_fails_closed() -> None:
    class Exploding:
        def execute(self, *a, **k):
            raise RuntimeError("consent table is on fire")

    reason = policy_mod.veto(
        Exploding(),
        action=A.WHATSAPP,
        features=make_features(),
        trigger=Trigger(kind="dpd_tick", at=NOW),
        at=NOW,
        policy=config.policy(),
        last_rung=5,
    )
    assert reason == f"contact:{contact_policy.REASON_UNREADABLE}"


def test_third_party_contact_is_structurally_impossible() -> None:
    """RBI forbids contacting family or references without origination consent,
    and this schema has nowhere such a consent could be recorded. The gate
    exists to be the one place that changes when a references table lands."""
    assert policy_mod.permits_third_party_contact(make_features()) is False


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score(features: AccountFeatures, *actions: str, **kw) -> dict[str, scoring.ScoredAction]:
    candidates = [
        scoring.Candidate(action=a, at=kw.pop("at", NOW), timing_rationale="") for a in actions
    ]
    scored = scoring.EVScorer().score(
        features,
        kw.pop("trigger", Trigger(kind="dpd_tick", at=NOW)),
        candidates,
        now=NOW,
        policy=kw.pop("policy", config.policy()),
        costs=config.costs(),
    )
    return {s.action: s for s in scored}


def test_waiting_scores_exactly_zero() -> None:
    """The number every other action has to beat. A dimensionless score cannot
    express that without an arbitrary threshold pretending to be one."""
    assert _score(make_features(), A.WAIT)[A.WAIT].expected_value == 0.0


def test_a_channel_we_have_never_tried_uses_the_prior_not_zero() -> None:
    """Absent, not zero. A borrower we have never dialled must not be ranked as
    though they had never answered."""
    never = _score(make_features(connect_rate={}), A.VOICE_BOT)[A.VOICE_BOT]
    assert never.p_reach == pytest.approx(scoring.REACH_PRIOR["voice"])
    assert "reach_from_prior" in never.reason_codes

    known = _score(make_features(connect_rate={"voice": 0.8}), A.VOICE_BOT)[A.VOICE_BOT]
    assert known.p_reach > never.p_reach
    assert "reach_from_history" in known.reason_codes


def test_one_answered_dial_is_not_a_reachable_borrower(db_tx) -> None:
    """The two halves of the connect ratio come from different tables with
    different histories — ``interactions`` goes back to the seed,
    ``contact_events`` only began when the contact ledger shipped. Dividing one
    by the other produced rates above 1, and an expected value an order of
    magnitude too high: the scorer would book a ₹45 agent call against a ₹1,600
    instalment on the strength of a single data point.
    """
    from agent_core.treatment.features import MIN_ATTEMPTS_FOR_RATE, SqlFeatureProvider

    row = db_tx.execute(
        text(
            "SELECT a.id, a.customer_id FROM accounts a"
            " JOIN customers c ON c.id = a.customer_id"
            " WHERE a.dpd BETWEEN 1 AND 30 ORDER BY a.id LIMIT 1"
        )
    ).mappings().first()
    if row is None:
        pytest.skip("seed has no early-bucket account")

    db_tx.execute(
        text(
            """
            INSERT INTO contact_events (
              id, tenant_id, customer_id, channel, direction, purpose,
              actor_kind, outcome, touch_counted, occurred_at
            ) VALUES (
              'CE-SPARSE', 'hdfc.retail', :c, 'voice', 'outbound', 'outreach',
              'bot', 'allowed', true, now() - interval '1 day'
            )
            """
        ),
        {"c": row["customer_id"]},
    )
    built = SqlFeatureProvider().build(
        row["customer_id"],
        account_id=row["id"],
        trigger=Trigger(kind="dpd_tick"),
        now=datetime.now(timezone.utc),
        conn=db_tx,
    )
    assert built.attempts_90d.get("voice", 0) < MIN_ATTEMPTS_FOR_RATE
    assert built.connect_rate["voice"] is None, (
        "below the sample floor the prior is the better estimate, and saying so "
        "keeps 'we have never really tried' out of the log disguised as "
        "'they always answer'"
    )


def test_promise_history_moves_the_odds_in_both_directions() -> None:
    reliable = _score(make_features(ptp_keep_rate=1.0), A.VOICE_BOT)[A.VOICE_BOT]
    breaker = _score(make_features(ptp_keep_rate=0.0), A.VOICE_BOT)[A.VOICE_BOT]
    unknown = _score(make_features(ptp_keep_rate=None), A.VOICE_BOT)[A.VOICE_BOT]
    assert breaker.p_resolve < unknown.p_resolve < reliable.p_resolve


def test_repeating_the_same_action_on_a_case_is_penalised_hardest() -> None:
    """Found by walking the ladder against real data, not by inspection: a pure
    expected-value ranker sends the cheapest channel forever, because ₹0.42
    always beats ₹7.50 on a small balance. Four identical unanswered WhatsApps
    is exactly the persistent-contact pattern the ladder exists to prevent, so
    "this precise approach already failed here" has to outweigh its price."""
    fresh = _score(make_features(), A.WHATSAPP)[A.WHATSAPP]
    repeated = _score(
        make_features(case_attempts=2, case_actions_tried={A.WHATSAPP: 2}),
        A.WHATSAPP,
    )[A.WHATSAPP]
    untried = _score(
        make_features(case_attempts=2, case_actions_tried={A.WHATSAPP: 2}),
        A.VOICE_BOT,
    )[A.VOICE_BOT]

    assert repeated.p_resolve < fresh.p_resolve
    # The general attempt decay alone would not be enough — both actions carry
    # it — so the repeat penalty is what actually moves the ranking.
    assert repeated.p_resolve < untried.p_resolve
    assert "already_tried_on_this_case" in repeated.reason_codes


def test_repeated_unanswered_sends_lower_the_odds_of_the_next_one() -> None:
    fresh = _score(make_features(digital_attempts_since_connect=0), A.SMS)[A.SMS]
    stale = _score(make_features(digital_attempts_since_connect=6), A.SMS)[A.SMS]
    assert stale.p_reach < fresh.p_reach


def test_acting_later_is_worth_less_than_acting_now() -> None:
    now_ev = _score(make_features(), A.WHATSAPP, at=NOW)[A.WHATSAPP].expected_value
    later_ev = _score(
        make_features(), A.WHATSAPP, at=NOW + timedelta(hours=36)
    )[A.WHATSAPP].expected_value
    assert later_ev < now_ev


def test_a_stale_event_does_not_decay_the_value_of_acting_on_it() -> None:
    """Decay applies to the delay we choose, never to how old the event already
    is. Decaying by age too would push every stale account below the floor and
    the engine would fall silent on exactly the borrowers who need a decision —
    the opposite of what this product is for."""
    assert scoring.urgency_decay(NOW, now=NOW, halflife_hours=36) == 1.0
    old_trigger = Trigger(kind="bounce", at=NOW - timedelta(days=20))
    old = _score(make_features(), A.WHATSAPP, trigger=old_trigger)[A.WHATSAPP]
    assert old.expected_value > 0


def test_each_touch_already_spent_today_makes_the_next_one_dearer() -> None:
    """What stops three cheap SMS out-earning one useful call."""
    first = scoring.fatigue_cost(A.WHATSAPP, make_features(touches_today=0), policy=config.policy())
    third = scoring.fatigue_cost(A.WHATSAPP, make_features(touches_today=2), policy=config.policy())
    assert third > first > 0


def test_an_expensive_action_loses_to_a_cheap_one_on_a_small_balance() -> None:
    small = make_features(dpd=20, instalment_amount=1_200.0)
    scored = _score(small, A.WHATSAPP, A.HUMAN_CALL)
    assert scored[A.WHATSAPP].expected_value > scored[A.HUMAN_CALL].expected_value


def test_a_large_balance_can_justify_a_person() -> None:
    large = make_features(dpd=20, instalment_amount=90_000.0, connect_rate={"voice": 0.7})
    scored = _score(large, A.WHATSAPP, A.HUMAN_CALL)
    assert scored[A.HUMAN_CALL].expected_value > scored[A.WHATSAPP].expected_value


def test_the_ranking_is_deterministic() -> None:
    f = make_features()
    first = [s.action for s in scoring.EVScorer().score(
        f,
        Trigger(kind="dpd_tick", at=NOW),
        [scoring.Candidate(a, NOW, "") for a in (A.WAIT, A.SMS, A.WHATSAPP, A.VOICE_BOT)],
        now=NOW,
        policy=config.policy(),
        costs=config.costs(),
    )]
    for _ in range(5):
        again = [s.action for s in scoring.EVScorer().score(
            f,
            Trigger(kind="dpd_tick", at=NOW),
            [scoring.Candidate(a, NOW, "") for a in (A.VOICE_BOT, A.WHATSAPP, A.SMS, A.WAIT)],
            now=NOW,
            policy=config.policy(),
            costs=config.costs(),
        )]
        assert again == first


def test_the_logged_vector_carries_what_the_score_was_built_from() -> None:
    """Rebuilding features from today's tables to train on a March decision
    leaks the outcome into the inputs — DPD and touch counts have moved, and
    partly *because* of the decision being labelled."""
    f = make_features()
    s = _score(f, A.WHATSAPP)[A.WHATSAPP]
    vec = scoring.vector(f, Trigger(kind="bounce", at=NOW), s, now=NOW)
    assert vec["exposure"] == f.exposure
    assert vec["p_reach"] == s.p_reach
    assert vec["planned_delay_hours"] == 0.0


# ---------------------------------------------------------------------------
# Arbitration
# ---------------------------------------------------------------------------


def _arbitrate(features, scored, excluded=None, **kw):
    return arbitration.arbitrate(
        features=features,
        trigger=Trigger(kind="dpd_tick", at=NOW),
        scored=scored,
        excluded=excluded or {},
        policy=kw.pop("policy", config.policy()),
        # The helper still speaks in the old yes/no, because that is what the
        # tests below are actually about. Arbitration now asks per action, so
        # "already planned" means every contender is — which is exactly the
        # state the old boolean described.
        planned=(
            frozenset(s.action for s in scored)
            if kw.pop("already_planned", False)
            else frozenset()
        ),
    )


def _ranked(features, *actions, **kw):
    scored = _score(features, *actions, **kw)
    return sorted(scored.values(), key=lambda s: (-s.expected_value, s.rung, s.action))


def test_an_attempt_worth_less_than_it_costs_is_not_made() -> None:
    tiny = make_features(dpd=20, instalment_amount=10.0)
    verdict = _arbitrate(tiny, _ranked(tiny, A.WAIT, A.SMS, A.WHATSAPP))
    assert verdict.suppressed
    assert verdict.reason == arbitration.SUPPRESS_BELOW_FLOOR
    assert verdict.chosen.action == A.WAIT


def test_the_last_contact_slot_is_reserved_for_something_better() -> None:
    """Burning the day's last slot on a marginal SMS at 10:00 means a genuinely
    useful call at 18:00 is refused — the borrower gets the harassment without
    the benefit."""
    # Sized so the best action clears the floor (₹2) but not the reserve
    # margin (3×) — the band the reserve exists for. Below the floor a
    # different gate fires first, which would make this test pass for the
    # wrong reason.
    marginal = make_features(dpd=20, instalment_amount=300.0, touches_today=2, daily_cap=3)
    verdict = _arbitrate(marginal, _ranked(marginal, A.WAIT, A.SMS, A.WHATSAPP))
    assert verdict.reason == arbitration.SUPPRESS_BUDGET_RESERVED

    plenty = make_features(dpd=20, instalment_amount=300.0, touches_today=0, daily_cap=3)
    assert not _arbitrate(plenty, _ranked(plenty, A.WAIT, A.SMS, A.WHATSAPP)).suppressed


def test_a_clearly_worthwhile_action_may_still_take_the_last_slot() -> None:
    worth_it = make_features(dpd=20, instalment_amount=40_000.0, touches_today=2, daily_cap=3)
    assert not _arbitrate(worth_it, _ranked(worth_it, A.WAIT, A.WHATSAPP)).suppressed


def test_an_identical_plan_is_not_made_twice() -> None:
    f = make_features(dpd=20)
    verdict = _arbitrate(f, _ranked(f, A.WAIT, A.WHATSAPP), already_planned=True)
    assert verdict.reason == arbitration.SUPPRESS_ALREADY_PLANNED


def test_a_wholly_held_borrower_reports_the_hold_not_a_shrug() -> None:
    """"no eligible action" is true and useless. A supervisor looking at a
    silent queue needs to know whether this is a hardship hold or an exhausted
    budget, because those call for opposite responses."""
    f = make_features(holds=("hardship",))
    verdict = _arbitrate(
        f,
        _ranked(f, A.WAIT),
        excluded={a: "hold:hardship" for a in (A.SMS, A.WHATSAPP, A.VOICE_BOT)},
    )
    assert verdict.reason == "hold:hardship"


def test_a_wholly_capped_borrower_reports_the_cap() -> None:
    f = make_features()
    verdict = _arbitrate(
        f,
        _ranked(f, A.WAIT),
        excluded={a: "contact:daily_cap" for a in (A.SMS, A.WHATSAPP, A.VOICE_BOT)},
    )
    assert verdict.reason == "contact:daily_cap"


def test_mixed_blocks_do_not_claim_a_single_cause() -> None:
    f = make_features()
    verdict = _arbitrate(
        f,
        _ranked(f, A.WAIT),
        excluded={A.SMS: "hold:hardship", A.VOICE_BOT: "contact:daily_cap"},
    )
    assert verdict.reason == arbitration.SUPPRESS_ALL_HELD


# ---------------------------------------------------------------------------
# Narration
# ---------------------------------------------------------------------------


def test_a_silence_explains_itself_in_english() -> None:
    line = narrate.rationale(
        features=make_features(dpd=20),
        trigger=Trigger(kind="broken_ptp", at=NOW - timedelta(hours=3)),
        chosen=None,
        suppressed=True,
        reason="hold:hardship",
        now=NOW,
    )
    assert "hardship hold is active" in line
    assert "promise broken" in line


def test_an_action_states_the_arithmetic_behind_it() -> None:
    f = make_features(dpd=20)
    chosen = _score(f, A.WHATSAPP)[A.WHATSAPP]
    line = narrate.rationale(
        features=f,
        trigger=Trigger(kind="bounce", at=NOW),
        chosen=chosen,
        suppressed=False,
        reason=None,
        now=NOW,
    )
    assert "Whatsapp" in line
    assert "chance of reaching them" in line


def test_every_suppression_reason_renders_as_prose() -> None:
    """A code with no phrase reaches a supervisor as a raw identifier."""
    codes = [
        v
        for k, v in vars(arbitration).items()
        if k.startswith("SUPPRESS_") and isinstance(v, str)
    ]
    for code in codes:
        assert narrate.humanise(code) != code, f"{code} has no human phrasing"


# ---------------------------------------------------------------------------
# The bounded LLM layer
# ---------------------------------------------------------------------------


class _FakeBase:
    name = "fake"
    version = "1.0.0"

    def __init__(self, scored):
        self._scored = scored

    def score(self, *a, **k):
        return list(self._scored)


def _reranker(scored, monkeypatch, reply: str):
    import azure_openai

    monkeypatch.setattr(azure_openai, "chat_complete", lambda *a, **k: reply)
    return rerank.LLMReranker(_FakeBase(scored))


def _two_actions():
    f = make_features(dpd=20)
    scored = _score(f, A.WHATSAPP, A.SMS)
    return f, [scored[A.WHATSAPP], scored[A.SMS]]


def test_the_model_may_reorder_approved_actions(monkeypatch) -> None:
    f, scored = _two_actions()
    r = _reranker(scored, monkeypatch, '{"order": ["sms", "whatsapp"]}')
    out = r.score(f, Trigger(kind="bounce", at=NOW), [], now=NOW, policy=config.policy(), costs=config.costs())
    assert [s.action for s in out] == [A.SMS, A.WHATSAPP]


def test_the_model_cannot_introduce_an_action_nobody_approved(monkeypatch) -> None:
    """The failure that matters. Borrower speech reaches this model's context
    through the account summary, so the guard is code, not a prompt request."""
    f, scored = _two_actions()
    r = _reranker(scored, monkeypatch, '{"order": ["field_visit", "sms", "whatsapp"]}')
    out = r.score(f, Trigger(kind="bounce", at=NOW), [], now=NOW, policy=config.policy(), costs=config.costs())
    assert A.FIELD_VISIT not in {s.action for s in out}
    assert len(out) == 2


def test_an_omitted_action_keeps_its_place_rather_than_vanishing(monkeypatch) -> None:
    f, scored = _two_actions()
    r = _reranker(scored, monkeypatch, '{"order": ["sms"]}')
    out = r.score(f, Trigger(kind="bounce", at=NOW), [], now=NOW, policy=config.policy(), costs=config.costs())
    assert {s.action for s in out} == {A.SMS, A.WHATSAPP}


def test_a_rationale_that_invents_a_figure_is_dropped(monkeypatch) -> None:
    """An agent reads "₹4,200 outstanding" as fact and repeats it to the
    borrower."""
    f, scored = _two_actions()
    r = _reranker(
        scored,
        monkeypatch,
        '{"order": ["sms", "whatsapp"], "why": "They owe 98765 rupees."}',
    )
    out = r.score(f, Trigger(kind="bounce", at=NOW), [], now=NOW, policy=config.policy(), costs=config.costs())
    assert "98765" not in out[0].explanation


def test_a_model_failure_keeps_the_deterministic_order(monkeypatch) -> None:
    f, scored = _two_actions()
    import azure_openai

    def _boom(*a, **k):
        raise TimeoutError("no answer")

    monkeypatch.setattr(azure_openai, "chat_complete", _boom)
    r = rerank.LLMReranker(_FakeBase(scored))
    out = r.score(f, Trigger(kind="bounce", at=NOW), [], now=NOW, policy=config.policy(), costs=config.costs())
    assert [s.action for s in out] == [s.action for s in scored]


# ---------------------------------------------------------------------------
# The engine, against the real database
# ---------------------------------------------------------------------------


@pytest.fixture
def account(db_tx):
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
    return dict(row)


def _decide(account, **kw):
    """One decision for the seeded account.

    The default trigger carries a unique ref so these tests cannot be made to
    fail by a *committed* plan left behind by an earlier run — duplicate
    suppression is real behaviour and is covered by
    ``test_an_identical_plan_is_not_made_twice`` against constructed inputs,
    where it can be asserted rather than tripped over.
    """
    default = Trigger(kind="dpd_tick", at=NOW, ref=f"probe-{uuid.uuid4().hex[:8]}")
    return recommend_treatment(
        customer_id=account["customer_id"],
        account_id=account["id"],
        trigger=kw.pop("trigger", default),
        **kw,
    )


def test_the_engine_decides_and_logs(db_tx, account) -> None:
    result = _decide(account)
    assert result.decision_id
    row = db_tx.execute(
        text("SELECT * FROM treatment_decisions WHERE id = :id"),
        {"id": result.decision_id},
    ).mappings().first()
    assert row is not None
    assert row["chosen_action"] == result.action
    assert row["features"]["schemaVersion"]
    assert row["candidates"], "the counterfactual is the whole point of the log"


def test_shadow_decides_fully_and_enacts_nothing(db_tx, account) -> None:
    """Reco hides its shadow output because *speaking* is the risk it manages.
    Here the risk is *contacting*, and showing a supervisor exactly what the
    engine would have done is the entire point of the shadow fortnight."""
    result = _decide(account, force_mode=config.MODE_SHADOW)
    assert result.suppressed
    assert result.reason == arbitration.SUPPRESS_SHADOW
    assert result.action != A.WAIT, "shadow must still produce a plan to look at"
    scheduled = db_tx.execute(
        text("SELECT scheduled_at FROM treatment_decisions WHERE id = :id"),
        {"id": result.decision_id},
    ).scalar()
    assert scheduled is None, "a suppressed decision must not look due to the executor"


def test_live_produces_an_actionable_plan(db_tx, account) -> None:
    result = _decide(account, force_mode=config.MODE_LIVE)
    assert result.actionable
    assert result.at is not None
    scheduled = db_tx.execute(
        text("SELECT scheduled_at FROM treatment_decisions WHERE id = :id"),
        {"id": result.decision_id},
    ).scalar()
    assert scheduled is not None


def test_the_engine_off_switch_writes_nothing(db_tx, account) -> None:
    before = db_tx.execute(text("SELECT count(*) FROM treatment_decisions")).scalar()
    result = _decide(account, force_mode=config.MODE_OFF)
    assert result.reason == arbitration.SUPPRESS_ENGINE_OFF
    after = db_tx.execute(text("SELECT count(*) FROM treatment_decisions")).scalar()
    assert after == before


def test_the_engine_never_raises(db_tx, account) -> None:
    """It runs inside bounce ingest and inside the settle tick. An engine that
    can take those down is worse than no engine."""

    class Exploding:
        def build(self, *a, **k):
            raise RuntimeError("feature store is down")

    result = _decide(account, provider=Exploding())
    assert result.suppressed
    assert result.reason == arbitration.SUPPRESS_ERROR
    assert result.action == A.WAIT


def test_an_unknown_customer_is_a_held_decision_not_a_crash(db_tx) -> None:
    result = recommend_treatment(customer_id="nobody-at-all", trigger=Trigger(kind="manual"))
    assert result.suppressed
    assert result.reason == arbitration.SUPPRESS_ERROR


def test_an_unknown_trigger_degrades_to_manual(db_tx, account) -> None:
    """``trigger_kind`` has a CHECK constraint. A kind this module does not know
    is a kind the log would reject, losing the decision entirely."""
    result = _decide(account, trigger=Trigger(kind="not-a-real-trigger"))
    assert result.decision_id
    kind = db_tx.execute(
        text("SELECT trigger_kind FROM treatment_decisions WHERE id = :id"),
        {"id": result.decision_id},
    ).scalar()
    assert kind == "manual"


def test_the_engine_joins_the_callers_transaction(db_tx, account) -> None:
    """Bounce ingest holds FOR UPDATE on the account row while it asks what to
    do next. A second connection there is a deadlock waiting for load."""
    result = recommend_treatment(
        customer_id=account["customer_id"],
        account_id=account["id"],
        trigger=Trigger(kind="bounce", at=NOW, ref="PE-PROBE"),
        conn=db_tx,
    )
    assert result.decision_id
    # Visible on the caller's connection because it was written there — and it
    # will disappear with the fixture's rollback, which is the property that
    # stops a rolled-back bounce leaving a plan behind.
    seen = db_tx.execute(
        text("SELECT 1 FROM treatment_decisions WHERE id = :id"),
        {"id": result.decision_id},
    ).fetchone()
    assert seen is not None


def test_a_hold_silences_the_engine_end_to_end(db_tx, account) -> None:
    db_tx.execute(
        text(
            """
            INSERT INTO treatment_holds (id, tenant_id, customer_id, kind, source)
            VALUES ('THD-PROBE', :t, :c, 'hardship', 'manual')
            """
        ),
        {"t": "hdfc.retail", "c": account["customer_id"]},
    )
    result = _decide(account, force_mode=config.MODE_LIVE)
    assert result.action == A.WAIT
    assert result.reason == "hold:hardship"
    assert set(result.excluded.values()) == {"hold:hardship"}


def test_the_scoreboard_reports_coverage_in_shadow(db_tx, account) -> None:
    """In shadow every actionable decision carries reason='shadow_mode'.
    Counting those as suppressed would report zero coverage in exactly the mode
    the report exists to serve."""
    _decide(account, force_mode=config.MODE_SHADOW)
    report = decisions.insights(db_tx, days=1)
    assert report["decisions"] >= 1
    assert report["actionable"] >= 1
    assert report["coverage"] > 0
    assert any(r["reason"] == arbitration.SUPPRESS_SHADOW for r in report["suppression"])


# ---------------------------------------------------------------------------
# The executor
# ---------------------------------------------------------------------------


def test_the_executor_refuses_to_act_outside_live(monkeypatch) -> None:
    """Belt and braces. "The worker was pointed at the wrong environment" is
    precisely the mistake shadow mode exists to survive."""
    monkeypatch.setenv("TREATMENT_MODE", "shadow")
    acted, note = enact.enact_one(None, {"id": "TD-X", "chosen_action": A.WHATSAPP})
    assert acted is False
    assert note == "not_live"


def test_a_deferred_action_is_terminal_not_a_retry_loop(db_tx, account, monkeypatch) -> None:
    """Field dispatch is P8 and the legal clocks are P9. Recommending them is
    what tells a collections head how much field work the ladder would generate
    before anyone builds the dispatcher — but the executor must not spin."""
    monkeypatch.setenv("TREATMENT_MODE", "live")
    decision_id = decisions.record(
        conn=db_tx,
        tenant_id="hdfc.retail",
        customer_id=account["customer_id"],
        account_id=account["id"],
        interaction_id=None,
        trigger_kind="dpd_tick",
        trigger_ref=None,
        mode="live",
        variant=None,
        recommender="ev",
        recommender_version="1.0.0",
        feature_schema_version="v1",
        features={},
        candidates=[],
        excluded={},
        chosen_action=A.FIELD_VISIT,
        chosen_channel="field",
        # In the past because Postgres' now() is *transaction* start, and this
        # fixture holds one transaction open for the whole test. A plan stamped
        # with the wall clock would sort after it and never look due.
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        expected_value=100.0,
        suppression_reason=None,
        rationale="probe",
        latency_ms=1,
    )
    claimed = decisions.claim_due(db_tx, limit=50)
    row = next(r for r in claimed if r["id"] == decision_id)
    acted, note = enact.enact_one(db_tx, row)
    assert acted is False
    assert note == f"no_executor:{A.FIELD_VISIT}"
    assert decision_id not in {r["id"] for r in decisions.claim_due(db_tx, limit=50)}


def test_a_borrower_who_already_paid_is_not_dunned(db_tx, account, monkeypatch) -> None:
    monkeypatch.setenv("TREATMENT_MODE", "live")
    db_tx.execute(
        text(
            """
            INSERT INTO payment_events (
              id, tenant_id, customer_id, account_id, kind, reason, amount,
              source, source_ref, status, occurred_at
            ) VALUES (
              'PE-CURED', :t, :c, :a, 'bounce', 'insufficient_funds', 5000,
              'sandbox', 'probe-cured', 'cured', now()
            )
            """
        ),
        {"t": "hdfc.retail", "c": account["customer_id"], "a": account["id"]},
    )
    acted, note = enact.enact_one(
        db_tx,
        {
            "id": "TD-PROBE",
            "customer_id": account["customer_id"],
            "account_id": account["id"],
            "chosen_action": A.WHATSAPP,
            "trigger_kind": "bounce",
            "trigger_ref": "PE-CURED",
            "scheduled_at": datetime.now(timezone.utc),
        },
    )
    assert acted is False
    assert note == "already_resolved"


def test_a_stale_plan_is_re_decided_rather_than_sent(db_tx, monkeypatch) -> None:
    monkeypatch.setenv("TREATMENT_MODE", "live")
    acted, note = enact.enact_one(
        db_tx,
        {
            "id": "TD-STALE",
            "chosen_action": A.WHATSAPP,
            "scheduled_at": datetime.now(timezone.utc) - timedelta(days=2),
        },
    )
    assert acted is False
    assert note == "plan_expired"


def test_the_contact_gate_runs_again_at_send_time(db_tx, account, monkeypatch) -> None:
    """A plan made at 09:00 for 19:30 was made against a budget since spent and
    a consent that may have been withdrawn."""
    monkeypatch.setenv("TREATMENT_MODE", "live")
    monkeypatch.setattr(
        contact_policy,
        "admit",
        lambda *a, **k: contact_policy.Decision(False, contact_policy.REASON_DAILY),
    )
    acted, note = enact.enact_one(
        db_tx,
        {
            "id": "TD-CAPPED",
            "customer_id": account["customer_id"],
            "account_id": account["id"],
            "chosen_action": A.WHATSAPP,
            "trigger_kind": "dpd_tick",
            "trigger_ref": None,
            "scheduled_at": datetime.now(timezone.utc),
        },
    )
    assert acted is False
    assert note == f"contact:{contact_policy.REASON_DAILY}"


def test_a_cancelled_plan_does_not_freeze_the_borrower(db_tx, account) -> None:
    """Found by the suite, not by inspection: a plan the executor claimed and
    deliberately did not carry out is not "already planned" — it is a decision
    that needs making again. Without the outcome check the first cancellation
    silenced the borrower for a full day."""
    ref = f"freeze-{uuid.uuid4().hex[:8]}"
    decision_id = decisions.record(
        conn=db_tx,
        tenant_id="hdfc.retail",
        customer_id=account["customer_id"],
        account_id=account["id"],
        interaction_id=None,
        trigger_kind="dpd_tick",
        trigger_ref=ref,
        mode="live",
        variant=None,
        recommender="ev",
        recommender_version="1.0.0",
        feature_schema_version="v1",
        features={},
        candidates=[],
        excluded={},
        chosen_action=A.WHATSAPP,
        chosen_channel="whatsapp",
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        expected_value=50.0,
        suppression_reason=None,
        rationale="probe",
        latency_ms=1,
    )
    trigger = Trigger(kind="dpd_tick", at=NOW, ref=ref)
    blocked = _decide(account, trigger=trigger, force_mode=config.MODE_LIVE)
    assert blocked.reason == arbitration.SUPPRESS_ALREADY_PLANNED

    decisions.record_outcome(decision_id, "cancelled", conn=db_tx)
    freed = _decide(account, trigger=trigger, force_mode=config.MODE_LIVE)
    assert freed.reason != arbitration.SUPPRESS_ALREADY_PLANNED


def test_every_action_is_either_executable_or_explicitly_deferred() -> None:
    """Fails when a new action is added with no executor and no decision about
    it. Silently unexecutable is the state that looks fine in shadow and does
    nothing in live."""
    covered = set(enact._HANDLERS) | enact.DEFERRED | {A.WAIT}
    missing = set(A.ALL) - covered
    assert not missing, f"these actions can be recommended but never carried out: {sorted(missing)}"
