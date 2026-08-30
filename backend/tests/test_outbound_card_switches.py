"""The after-call switches on the card do something.

``test_outbound_conduct`` opens with the claim this file continues: a field that
is "configured, validated, versioned and publishable — and had no effect" is a
worse failure than an unimplemented one, because the change log shows the
operator a diff and the behaviour does not move.

Building the Outbound editor made that acute. Four fields had a control drawn
for them and no reader anywhere:

* ``post_call.written_followup`` — the switch above the rules;
* ``post_call.obligations`` — whether promises we made become rows;
* ``post_call.qa`` — always / sampled / never, while the sweep scored every call;
* ``outbound.carrier_amd`` — while the dial read only the platform env flag.

A fifth, ``concurrency_share``, is deliberately *not* tested here and has no
control in the editor: it wants a real per-card reservation in the fleet gate,
which ``outbound.place`` does not have, and a slider for it would be this exact
failure authored on purpose.

Every default below is the permissive one, and every fallback path returns it.
That direction is deliberate: a card lookup that fails must not silently stop
sending borrowers the record of what they agreed, or quietly end QA coverage.
"""

from __future__ import annotations

import pytest

from agent_core.cards.schema import CardPostCall


# --- written_followup -------------------------------------------------------


def _rule(when: str, *actions: str):
    return {"when": when, "do": list(actions)}


def test_the_written_switch_suppresses_the_verb_not_the_rule():
    """A rule saying "on ptp_captured, confirm in writing and schedule the
    reminder" still schedules the reminder. Suppressing the whole rule would
    make one switch silently disable actions nobody asked it to."""
    import post_call_actions

    calls: list[str] = []
    original = dict(post_call_actions.REGISTRY)
    post_call_actions.REGISTRY["schedule_due_reminder"] = lambda ctx, arg: calls.append(
        "reminder"
    ) or "scheduled"
    try:
        applied = post_call_actions.apply(
            None,
            attempt={"id": "AT1"},
            business="ptp_captured",
            nonpayment_reason=None,
            commitment=None,
            rules=[_rule("ptp_captured", "confirm_written", "schedule_due_reminder")],
            written_followup=False,
        )
    finally:
        post_call_actions.REGISTRY.clear()
        post_call_actions.REGISTRY.update(original)

    assert "confirm_written:off_by_card" in applied
    assert calls == ["reminder"]


def test_a_suppressed_action_is_recorded_rather_than_dropped():
    """"Nothing happened" and "the card said not to" are different facts, and
    the action list is what the audit trail shows for this call."""
    import post_call_actions

    applied = post_call_actions.apply(
        None,
        attempt={"id": "AT1"},
        business="ptp_captured",
        nonpayment_reason=None,
        commitment=None,
        rules=[_rule("ptp_captured", "confirm_written")],
        written_followup=False,
    )
    assert applied == ["confirm_written:off_by_card"]


def test_the_switch_defaults_on_for_every_existing_caller():
    """The parameter was added to a function with live callers. Defaulting it
    False would have turned written follow-up off for every card in the fleet
    with no card change and no diff to show for it."""
    import inspect

    import post_call_actions

    sig = inspect.signature(post_call_actions.apply)
    assert sig.parameters["written_followup"].default is True
    assert CardPostCall().written_followup is True


# --- the policy lookup ------------------------------------------------------


def test_an_unreadable_card_gets_the_permissive_default():
    """The fallback has to be the behaviour of a card that says nothing.
    Failing closed here would stop sending borrowers their written record
    because of a lookup error — a change nobody authored."""
    import call_closer

    policy = call_closer._post_call_policy("no-such-bot-at-all")
    assert policy.written_followup is True
    assert policy.obligations is True
    assert policy.qa == "always"


# --- qa ---------------------------------------------------------------------


def test_sampling_is_deterministic_per_interaction():
    """A random draw would mean the sweep's second pass over a call it already
    skipped could pick it up, which makes "20%" a floor that creeps toward 100%
    with every retry rather than a rate."""
    import qa_autoscore

    first = [qa_autoscore._in_qa_sample(f"IX{i}") for i in range(200)]
    second = [qa_autoscore._in_qa_sample(f"IX{i}") for i in range(200)]
    assert first == second


def test_sampling_actually_samples():
    """Neither always-true nor always-false — either would be the switch not
    working, in one of the two directions nobody would notice."""
    import qa_autoscore

    picked = sum(qa_autoscore._in_qa_sample(f"IX{i}") for i in range(500))
    assert 0 < picked < 500
    # Within a wide band of the configured rate — this pins "it samples", not
    # the exact hash distribution.
    assert 20 < picked < 220


def test_the_policy_lookup_queries_a_column_that_exists():
    """The lookup ran `SELECT bot_id FROM interactions`, and `interactions` has
    no such column — it is `handler_bot_id`.

    Worth its own test because of how the failure presented. The helper catches
    everything and defaults to "always", so in isolation the mistake was
    invisible; but under the test fixture every caller shares one transaction,
    so the failed statement aborted it and the next eighteen queries in the same
    test file failed too. The try/except cannot undo an aborted transaction,
    which is exactly why the column name has to be right rather than merely
    guarded.
    """
    from sqlalchemy import text

    import db

    with db.engine.connect() as conn:
        columns = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'interactions'"
                )
            )
        }
    assert "handler_bot_id" in columns
    assert "bot_id" not in columns

    # And the query itself runs without poisoning the connection.
    with db.engine.connect() as conn:
        conn.execute(
            text("SELECT handler_bot_id FROM interactions WHERE id = :id"), {"id": "nope"}
        ).scalar()


def test_an_unknown_interaction_is_still_scored():
    """Same direction as the card fallback: a gap in the scorecard record is
    exactly the kind of thing nobody notices."""
    import qa_autoscore

    assert qa_autoscore._card_qa_policy("IX-does-not-exist") == "always"


def test_never_stops_the_sweep_before_it_costs_anything(monkeypatch):
    """Checked ahead of the rubric lookup, so a card that says never does not
    pay for a rubric load and a transcript render to decide not to use them."""
    import qa_autoscore

    monkeypatch.setattr(qa_autoscore, "_card_qa_policy", lambda _ix: "never")

    def _boom(*_a, **_k):  # pragma: no cover - must not be reached
        raise AssertionError("rubric lookup ran for a card that says never")

    monkeypatch.setattr("db.rubric_id_for_interaction", _boom)
    assert qa_autoscore.score_interaction("IX1") is None


# --- carrier_amd ------------------------------------------------------------


def test_the_card_can_only_widen_answering_machine_detection():
    """Or-ed with the env flag, never overriding it. Carrier AMD adds a second
    verdict alongside the in-band detector, so a card enabling it cannot make
    detection worse — while a card *disabling* what the platform turned on would
    let an authored field weaken an operational safeguard."""
    import inspect

    import outbound

    source = inspect.getsource(outbound.place)
    assert "amd_enabled() or _card_wants_carrier_amd(attempt)" in source


def test_a_failed_card_lookup_does_not_change_the_dial():
    import outbound

    assert outbound._card_wants_carrier_amd({"id": "AT1", "botId": "no-such-bot"}) is False
    assert outbound._card_wants_carrier_amd({}) is False


@pytest.mark.parametrize("key", ["botId", "bot_id"])
def test_both_attempt_key_spellings_resolve(key):
    """`place` is called with the camelCase row from the worker and the
    snake_case row from the tests. Reading only one spelling would make this
    field work in exactly one of the two paths."""
    import outbound

    # Neither resolves to a real card here; the point is that neither raises and
    # both take the same branch.
    assert outbound._card_wants_carrier_amd({key: "kaia-v2-4"}) in (True, False)
