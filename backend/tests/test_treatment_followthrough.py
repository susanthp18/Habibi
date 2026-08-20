"""The closed loop (P5): attribution, and the ladder that walks.

P3 on its own decides once per event, which makes it advisory. What turns one
recommendation into "reminder → bot retry → human → field" is this: watching
what each attempt produced, writing the answer back, and asking again while the
case is still open.

The tests that matter most here are the ones about *stopping* — a loop that
never runs out is not a collections ladder, it is persistent calling with extra
steps, and RBI has a word for that.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import db
from agent_core.treatment import (
    actions as A,
    arbitration,
    config,
    decisions,
    followthrough,
)
from agent_core.treatment.engine import recommend_treatment
from agent_core.treatment.features import Trigger

TENANT = "hdfc.retail"


@pytest.fixture
def account(db_tx):
    row = db_tx.execute(
        text(
            """
            SELECT a.id, a.customer_id FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE c.tenant_id = :t AND c.phone_primary IS NOT NULL
              AND a.dpd BETWEEN 1 AND 30
            ORDER BY a.id LIMIT 1
            """
        ),
        {"t": TENANT},
    ).mappings().first()
    if row is None:
        pytest.skip("seed has no early-bucket account with a phone number")
    return dict(row)


@pytest.fixture
def bounce(db_tx, account):
    """An open bounce — a case the loop is allowed to chase."""
    event_id = f"PE-{secrets.token_hex(4).upper()}"
    db_tx.execute(
        text(
            """
            INSERT INTO payment_events (
              id, tenant_id, customer_id, account_id, kind, reason, amount,
              source, source_ref, status, occurred_at
            ) VALUES (
              :id, :t, :c, :a, 'bounce', 'insufficient_funds', 6000,
              'sandbox', :ref, 'open', now() - interval '2 hours'
            )
            """
        ),
        {
            "id": event_id,
            "t": TENANT,
            "c": account["customer_id"],
            "a": account["id"],
            "ref": f"loop-{event_id}",
        },
    )
    return event_id


def _decision(
    conn,
    account,
    *,
    action: str = A.WHATSAPP,
    trigger_kind: str = "bounce",
    trigger_ref: str | None = None,
    enacted: bool = True,
    enacted_ago_hours: float = 24.0,
) -> str:
    decision_id = decisions.record(
        conn=conn,
        tenant_id=TENANT,
        customer_id=account["customer_id"],
        account_id=account["id"],
        interaction_id=None,
        trigger_kind=trigger_kind,
        trigger_ref=trigger_ref,
        mode="live" if enacted else "shadow",
        variant=None,
        recommender="ev",
        recommender_version="1.0.0",
        feature_schema_version="v2",
        features={},
        candidates=[],
        excluded={},
        chosen_action=action,
        chosen_channel=A.spec(action).channel,
        scheduled_at=datetime.now(timezone.utc) - timedelta(hours=enacted_ago_hours),
        expected_value=50.0,
        suppression_reason=None if enacted else "shadow_mode",
        rationale="probe",
        latency_ms=1,
    )
    if enacted:
        conn.execute(
            text(
                """
                UPDATE treatment_decisions
                SET enacted = true, enacted_at = now() - (CAST(:h AS double precision) * interval '1 hour')
                WHERE id = :id
                """
            ),
            {"id": decision_id, "h": enacted_ago_hours},
        )
    return decision_id


def _outcome(conn, decision_id: str) -> str | None:
    return conn.execute(
        text("SELECT outcome FROM treatment_decisions WHERE id = :id"),
        {"id": decision_id},
    ).scalar()


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


def test_an_unanswered_attempt_is_labelled_after_its_grace_period(
    db_tx, account, bounce
) -> None:
    decision_id = _decision(db_tx, account, trigger_ref=bounce, enacted_ago_hours=24)
    followthrough.attribute_outcomes(db_tx)
    assert _outcome(db_tx, decision_id) == "no_answer"


def test_an_attempt_inside_its_grace_period_is_left_alone(db_tx, account, bounce) -> None:
    """Calling a follow-up a no-answer an hour after it was queued would have
    the ladder escalating past a person who has not yet picked up the phone."""
    decision_id = _decision(
        db_tx, account, action=A.HUMAN_CALL, trigger_ref=bounce, enacted_ago_hours=2
    )
    followthrough.attribute_outcomes(db_tx)
    assert _outcome(db_tx, decision_id) is None


def test_grace_is_sized_to_the_channel() -> None:
    assert config.grace_hours(A.VOICE_BOT) < config.grace_hours(A.HUMAN_CALL)
    assert config.grace_hours(A.HUMAN_CALL) < config.grace_hours(A.FIELD_VISIT)


def test_a_payment_beats_an_unanswered_dial(db_tx, account, bounce) -> None:
    """Recording ``no_answer`` because the phone rang out, on a borrower who
    then paid, would teach the model the opposite of what happened."""
    decision_id = _decision(db_tx, account, trigger_ref=bounce, enacted_ago_hours=24)
    db_tx.execute(
        text(
            """
            INSERT INTO ledger_entries (id, account_id, type, description, amount, posted_at)
            VALUES (:id, :a, 'payment', 'probe', -6000, now() - interval '1 hour')
            """
        ),
        {"id": f"LED-{secrets.token_hex(4)}", "a": account["id"]},
    )
    followthrough.attribute_outcomes(db_tx)
    assert _outcome(db_tx, decision_id) == "paid"


def test_a_promise_captured_after_the_attempt_is_the_outcome(db_tx, account, bounce) -> None:
    decision_id = _decision(db_tx, account, trigger_ref=bounce, enacted_ago_hours=24)
    db_tx.execute(
        text(
            """
            INSERT INTO promises (id, customer_id, account_id, owner_kind, owner_bot_id,
                                  amount, promised_at, status, reminder_status, created_at)
            VALUES (:id, :c, :a, 'bot', :bot, 3000, now() + interval '3 days',
                    'upcoming', 'off', now() - interval '1 hour')
            """
        ),
        {
            "id": f"PR-{secrets.token_hex(4).upper()}",
            "c": account["customer_id"],
            "a": account["id"],
            "bot": db.DEFAULT_BOT_ID,
        },
    )
    followthrough.attribute_outcomes(db_tx)
    assert _outcome(db_tx, decision_id) == "ptp"


def test_an_inbound_reply_counts_as_reached(db_tx, account, bounce) -> None:
    decision_id = _decision(db_tx, account, trigger_ref=bounce, enacted_ago_hours=24)
    conversation = db._open_whatsapp_conversation(db_tx, account["customer_id"])
    db_tx.execute(
        text(
            """
            INSERT INTO messages (id, conversation_id, sender, body, created_at)
            VALUES (:id, :cv, 'customer', 'who is this', now() - interval '1 hour')
            """
        ),
        {"id": f"MSG-{secrets.token_hex(4)}", "cv": conversation},
    )
    followthrough.attribute_outcomes(db_tx)
    assert _outcome(db_tx, decision_id) == "reached"


def test_a_shadow_decision_is_never_called_unanswered(db_tx, account, bounce) -> None:
    """Nothing was sent, so there is nothing to call unanswered. Labelling it
    would manufacture a training signal out of a decision nobody acted on."""
    decision_id = _decision(
        db_tx, account, trigger_ref=bounce, enacted=False, enacted_ago_hours=200
    )
    followthrough.attribute_outcomes(db_tx)
    assert _outcome(db_tx, decision_id) is None


def test_a_shadow_decision_still_records_the_counterfactual(db_tx, account, bounce) -> None:
    """A plan nobody carried out, on an account that paid anyway, is the only
    evidence that would ever say the engine is reallocating spend rather than
    earning it."""
    decision_id = _decision(
        db_tx, account, trigger_ref=bounce, enacted=False, enacted_ago_hours=48
    )
    db_tx.execute(
        text(
            """
            INSERT INTO ledger_entries (id, account_id, type, description, amount, posted_at)
            VALUES (:id, :a, 'payment', 'probe', -6000, now() + interval '1 hour')
            """
        ),
        {"id": f"LED-{secrets.token_hex(4)}", "a": account["id"]},
    )
    followthrough.attribute_outcomes(db_tx)
    assert _outcome(db_tx, decision_id) == "paid"


def test_an_overtaken_plan_is_superseded_not_unanswered(db_tx, account, bounce) -> None:
    old = _decision(db_tx, account, trigger_ref=bounce, enacted=False, enacted_ago_hours=48)
    _decision(db_tx, account, trigger_ref=bounce, enacted=False, enacted_ago_hours=1)
    followthrough.attribute_outcomes(db_tx)
    # Both rows carry the same created_at — this fixture holds one transaction
    # and Postgres now() is transaction start — so the id tiebreak is what
    # decides which one is the newer plan.
    assert _outcome(db_tx, old) == "superseded"


def test_an_enacted_attempt_is_never_superseded(db_tx, account, bounce) -> None:
    """It happened. Erasing it from the ladder would let the engine repeat a
    rung the borrower has already experienced."""
    old = _decision(db_tx, account, trigger_ref=bounce, enacted=True, enacted_ago_hours=48)
    _decision(db_tx, account, trigger_ref=bounce, enacted=False, enacted_ago_hours=1)
    followthrough.attribute_outcomes(db_tx)
    assert _outcome(db_tx, old) == "no_answer"


def test_a_provider_failure_is_not_a_borrower_ignoring_us(db_tx, account, bounce) -> None:
    """An undeliverable number is a data-quality problem for ops; a no-answer is
    a treatment problem for the engine. Escalating up the ladder is the right
    response to only one of them."""
    decision_id = _decision(db_tx, account, trigger_ref=bounce, enacted_ago_hours=24)
    conversation = db._open_whatsapp_conversation(db_tx, account["customer_id"])
    message_id = f"MSG-{secrets.token_hex(4)}"
    db_tx.execute(
        text(
            """
            INSERT INTO messages (id, conversation_id, sender, body, delivery_status)
            VALUES (:id, :cv, 'bot', 'probe', 'failed')
            """
        ),
        {"id": message_id, "cv": conversation},
    )
    db_tx.execute(
        text(
            """
            INSERT INTO whatsapp_outbound_jobs (
              id, message_id, conversation_id, customer_id, to_phone, body,
              source, status, created_at
            ) VALUES (
              :id, :msg, :cv, :c, '+910000000000', 'probe',
              'treatment', 'failed', now() - interval '2 hours'
            )
            """
        ),
        {
            "id": f"WAJ-{secrets.token_hex(4)}",
            "msg": message_id,
            "cv": conversation,
            "c": account["customer_id"],
        },
    )
    followthrough.attribute_outcomes(db_tx)
    assert _outcome(db_tx, decision_id) == "undeliverable"


# ---------------------------------------------------------------------------
# Which cases the loop picks up
# ---------------------------------------------------------------------------


def _cases(conn) -> set[tuple[str, str]]:
    return {
        (c["trigger_kind"], c["trigger_ref"])
        for c in followthrough.open_cases(conn, limit=50)
    }


def test_an_unresolved_case_comes_back_round(db_tx, account, bounce) -> None:
    decision_id = _decision(db_tx, account, trigger_ref=bounce, enacted_ago_hours=24)
    decisions.record_outcome(decision_id, "no_answer", conn=db_tx)
    assert ("bounce", bounce) in _cases(db_tx)


def test_a_cured_bounce_is_left_alone(db_tx, account, bounce) -> None:
    decision_id = _decision(db_tx, account, trigger_ref=bounce, enacted_ago_hours=24)
    decisions.record_outcome(decision_id, "no_answer", conn=db_tx)
    db_tx.execute(
        text("UPDATE payment_events SET status = 'cured' WHERE id = :id"), {"id": bounce}
    )
    assert ("bounce", bounce) not in _cases(db_tx)


def test_a_resolved_case_is_left_alone(db_tx, account, bounce) -> None:
    decision_id = _decision(db_tx, account, trigger_ref=bounce, enacted_ago_hours=24)
    decisions.record_outcome(decision_id, "paid", conn=db_tx)
    assert ("bounce", bounce) not in _cases(db_tx)


def test_a_case_with_four_attempts_yields_one_candidate(db_tx, account, bounce) -> None:
    """Otherwise a well-worked case out-competes every other borrower for the
    worker's attention."""
    for _ in range(4):
        decision_id = _decision(db_tx, account, trigger_ref=bounce, enacted_ago_hours=24)
        decisions.record_outcome(decision_id, "no_answer", conn=db_tx)
    matching = [
        c
        for c in followthrough.open_cases(db_tx, limit=50)
        if c["trigger_ref"] == bounce
    ]
    assert len(matching) == 1


def test_a_one_shot_question_is_not_looped(db_tx, account) -> None:
    """A supervisor asking "what would you do here?" is a question, not a
    campaign. Re-deciding it on a timer would answer it repeatedly, unasked."""
    ref = f"manual-{uuid.uuid4().hex[:8]}"
    decision_id = _decision(
        db_tx, account, trigger_kind="manual", trigger_ref=ref, enacted_ago_hours=24
    )
    decisions.record_outcome(decision_id, "no_answer", conn=db_tx)
    assert ("manual", ref) not in _cases(db_tx)
    assert "manual" not in followthrough.LOOPED_TRIGGERS


# ---------------------------------------------------------------------------
# The ladder walks — and stops
# ---------------------------------------------------------------------------


def _attempt(conn, account, result) -> None:
    """Mark a plan as sent and record it in the shared contact ledger."""
    decisions.mark_enacted(result.decision_id, ref="probe", conn=conn)
    conn.execute(
        text(
            "UPDATE treatment_decisions SET enacted_at = now() - interval '1 day'"
            " WHERE id = :id"
        ),
        {"id": result.decision_id},
    )
    conn.execute(
        text(
            """
            INSERT INTO contact_events (
              id, tenant_id, customer_id, channel, direction, purpose,
              actor_kind, outcome, touch_counted, occurred_at
            ) VALUES (
              :id, :t, :c, :ch, 'outbound', 'outreach',
              :ak, 'allowed', false, now() - interval '1 day'
            )
            """
        ),
        {
            "id": f"CE-{secrets.token_hex(5).upper()}",
            "t": TENANT,
            "c": account["customer_id"],
            "ch": result.channel,
            "ak": A.spec(result.action).actor_kind,
        },
    )
    followthrough.attribute_outcomes(conn)


def _walk(db_tx, account, bounce, *, steps: int = 8) -> list:
    trigger = Trigger(kind="bounce", at=datetime.now(timezone.utc), ref=bounce)
    walked = []
    for _ in range(steps):
        result = recommend_treatment(
            customer_id=account["customer_id"],
            account_id=account["id"],
            trigger=trigger,
            conn=db_tx,
            force_mode=config.MODE_LIVE,
        )
        walked.append(result)
        if not result.actionable:
            break
        _attempt(db_tx, account, result)
    return walked


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    """Compress the retry gap. The backoff has its own test; here it would only
    make every ladder test a test of the clock."""
    monkeypatch.setenv("TREATMENT_RETRY_BACKOFF_HOURS", "0")


def test_the_ladder_does_not_repeat_one_channel_forever(db_tx, account, bounce) -> None:
    """The naive expected-value failure: ₹0.42 always beats ₹7.50 on a small
    balance, so a pure cost ranker sends the same WhatsApp five times — which is
    exactly the persistent-contact pattern the ladder exists to prevent."""
    walked = _walk(db_tx, account, bounce)
    acted = [r.action for r in walked if r.actionable]
    assert len(set(acted)) > 1, f"the ladder never escalated: {acted}"


def test_the_ladder_climbs_before_it_repeats(db_tx, account, bounce) -> None:
    walked = _walk(db_tx, account, bounce)
    acted = [r.action for r in walked if r.actionable]
    assert acted[0] in {A.SMS, A.WHATSAPP}
    assert A.rung(acted[1]) > A.rung(acted[0])


def test_the_ladder_runs_out(db_tx, account, bounce) -> None:
    """A borrower who has ignored five contacts about one bounce will not be
    persuaded by the sixth, and RBI reads a sixth as persistent calling — which
    is a finding, not a conversion problem."""
    walked = _walk(db_tx, account, bounce, steps=12)
    assert not walked[-1].actionable
    assert walked[-1].reason == arbitration.SUPPRESS_ATTEMPTS_EXHAUSTED
    acted = [r for r in walked if r.actionable]
    assert len(acted) <= config.policy().max_attempts_per_case


def test_a_recent_attempt_blocks_the_next_one(db_tx, account, bounce, monkeypatch) -> None:
    """Without this, a no-answer at 09:00 becomes a second dial at 09:05."""
    monkeypatch.setenv("TREATMENT_RETRY_BACKOFF_HOURS", "48")
    trigger = Trigger(kind="bounce", at=datetime.now(timezone.utc), ref=bounce)
    first = recommend_treatment(
        customer_id=account["customer_id"],
        account_id=account["id"],
        trigger=trigger,
        conn=db_tx,
        force_mode=config.MODE_LIVE,
    )
    assert first.actionable
    _attempt(db_tx, account, first)  # enacted 1 day ago, backoff is 2 days
    second = recommend_treatment(
        customer_id=account["customer_id"],
        account_id=account["id"],
        trigger=trigger,
        conn=db_tx,
        force_mode=config.MODE_LIVE,
    )
    assert second.reason == arbitration.SUPPRESS_BACKOFF


# ---------------------------------------------------------------------------
# Closing a case out
# ---------------------------------------------------------------------------


def test_a_payment_retires_the_scheduled_plans(db_tx, account, bounce) -> None:
    """The worst thing a collections system can do is ring somebody about a debt
    they have already paid, and a plan scheduled for 18:00 does not know about a
    payment received at 15:00 unless something tells it."""
    pending = _decision(db_tx, account, trigger_ref=bounce, enacted=False)
    followthrough.resolve_case(
        db_tx, trigger_kind="bounce", trigger_ref=bounce, outcome="paid"
    )
    assert _outcome(db_tx, pending) == "paid"
    assert pending not in {r["id"] for r in decisions.claim_due(db_tx, limit=50)}


def test_closing_a_case_does_not_rewrite_what_already_happened(
    db_tx, account, bounce
) -> None:
    done = _decision(db_tx, account, trigger_ref=bounce, enacted=True)
    decisions.record_outcome(done, "reached", conn=db_tx)
    followthrough.resolve_case(
        db_tx, trigger_kind="bounce", trigger_ref=bounce, outcome="paid"
    )
    assert _outcome(db_tx, done) == "reached"


def test_a_settled_payment_closes_the_bounce_case(db_tx, account, bounce) -> None:
    """End to end through the real payment path rather than the helper."""
    import payments

    pending = _decision(db_tx, account, trigger_ref=bounce, enacted=False)
    payments._close_treatment_cases(db_tx, bounce_ids=[bounce], promises=[])
    assert _outcome(db_tx, pending) == "paid"


def test_closing_never_costs_the_payment(db_tx, monkeypatch) -> None:
    """A payment must record even if the cleanup does not."""
    import payments

    monkeypatch.setattr(
        followthrough,
        "resolve_case",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    payments._close_treatment_cases(db_tx, bounce_ids=["PE-NOPE"], promises=[])


# ---------------------------------------------------------------------------
# Worker entry point and the case view
# ---------------------------------------------------------------------------


def test_the_loop_is_inert_when_the_engine_is_off(monkeypatch) -> None:
    monkeypatch.setenv("TREATMENT_MODE", "off")
    assert followthrough.process_one(db.engine) is False


def test_the_loop_attributes_in_shadow(db_tx, account, bounce, monkeypatch) -> None:
    """Labelling what happened is not an intervention, and the counterfactuals
    are most of what the shadow fortnight is for."""
    monkeypatch.setenv("TREATMENT_MODE", "shadow")
    decision_id = _decision(db_tx, account, trigger_ref=bounce, enacted_ago_hours=24)
    assert followthrough.process_one(db.engine) is True
    assert _outcome(db_tx, decision_id) == "no_answer"


def test_the_case_view_shows_the_rungs_already_walked(db_tx, account, bounce) -> None:
    """``/treatment/next`` answers "what does the engine say?". A floor lead's
    question is "what has been tried, and what is left"."""
    _walk(db_tx, account, bounce, steps=3)
    cases = db.list_treatment_cases(customer_id=account["customer_id"])
    case = next(c for c in cases if c["triggerRef"] == bounce)
    assert case["attempts"] >= 1
    assert case["ladder"], "the ladder should list the actions actually enacted"
    assert case["rationale"]


def test_the_case_view_hides_what_has_been_paid(db_tx, account, bounce) -> None:
    decision_id = _decision(db_tx, account, trigger_ref=bounce)
    decisions.record_outcome(decision_id, "paid", conn=db_tx)
    open_cases = db.list_treatment_cases(
        customer_id=account["customer_id"], open_only=True
    )
    assert bounce not in {c["triggerRef"] for c in open_cases}
    everything = db.list_treatment_cases(
        customer_id=account["customer_id"], open_only=False
    )
    assert bounce in {c["triggerRef"] for c in everything}
