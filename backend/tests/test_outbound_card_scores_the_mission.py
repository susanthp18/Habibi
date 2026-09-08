"""The published card decides what closed the mission, and who owns it after.

Two authored fields that were gated at publish and read by nobody:

* ``CardObjective.success`` / ``.partial`` — the Closer scored every mission
  off a module-level table, so "Closes the case" and "Partly worked" in the
  Outbound tab were decoration. The comment above the table claimed the card
  overrode it; it never had (RUNTIME-08, OUTBOUND-01).
* ``CardCadence.escalate_to`` — validated by G-OB7, which checks the target is
  a known agent on the card's handoff allowlist, and then read by no caller at
  all. An exhausted ladder escalated to nobody (RUNTIME-09).

``escalate_to`` is *recorded*, not acted on. cadence.py's contract is that it
may retry an action and never change one, so the card's answer becomes evidence
on the case and the decision stays ``treatment/followthrough.py``'s.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import cadence
import call_closer
from agent_core.cards.schema import AgentCard

TENANT = "hdfc.retail"
OBJECTIVE = "bounce_cure"


def _card(*, success=None, partial=None, escalate_to=None) -> AgentCard:
    return AgentCard.model_validate(
        {
            "identity": {"bot_id": "score-probe", "slug": "score-probe", "display_name": "P"},
            "outbound": {
                "direction": "outbound",
                "objectives": [
                    {
                        "key": OBJECTIVE,
                        "success": success or [],
                        "partial": partial or [],
                        "cadence": "ladder",
                    }
                ],
                "cadences": [{"name": "ladder", "escalate_to": escalate_to}],
            },
        }
    )


def _needs_escalate_column(conn) -> None:
    from agent_core.treatment.schema_ready import has_column

    if not has_column(conn, "call_cadence_state", "escalate_to"):
        pytest.skip("call_cadence_state.escalate_to not applied yet (20260906_0112)")


def _customer(conn) -> str:
    cid = f"cust-score-{uuid.uuid4().hex[:8]}"
    conn.execute(
        text(
            "INSERT INTO customers (id, tenant_id, name, risk, phone_primary) "
            "VALUES (:id, :tenant, 'Score Test', 'low', '+919000000003')"
        ),
        {"id": cid, "tenant": TENANT},
    )
    return cid


# ---------------------------------------------------------------------------
# What closes the mission
# ---------------------------------------------------------------------------


def test_the_card_overrides_the_default_table(monkeypatch) -> None:
    import mission as mission_mod

    monkeypatch.setattr(
        mission_mod, "card_for_bot", lambda *_a, **_k: _card(success=["plan_agreed"])
    )
    success, partial = call_closer._outcome_sets({"bot_id": "score-probe"}, OBJECTIVE)
    assert success == frozenset({"plan_agreed"})
    assert partial == frozenset()
    # The table would have said otherwise, which is the whole finding.
    assert "plan_agreed" not in call_closer.SUCCESS_BY_OBJECTIVE[OBJECTIVE]


def test_an_unclaimed_mission_still_falls_back_to_the_table(monkeypatch) -> None:
    import mission as mission_mod

    monkeypatch.setattr(mission_mod, "card_for_bot", lambda *_a, **_k: _card())
    success, _ = call_closer._outcome_sets({"bot_id": "score-probe"}, "hardship_intake")
    assert success == call_closer.SUCCESS_BY_OBJECTIVE["hardship_intake"]


def test_an_empty_success_list_is_not_a_card_saying_nothing_closes_it(monkeypatch) -> None:
    """An author who declares a mission and leaves ``success`` empty has not
    said "nothing closes this" — they have not said anything."""
    import mission as mission_mod

    monkeypatch.setattr(mission_mod, "card_for_bot", lambda *_a, **_k: _card(success=[]))
    success, _ = call_closer._outcome_sets({"bot_id": "score-probe"}, OBJECTIVE)
    assert success == call_closer.SUCCESS_BY_OBJECTIVE[OBJECTIVE]


def test_an_unreadable_card_falls_back_rather_than_failing_the_close(monkeypatch) -> None:
    import mission as mission_mod

    def _boom(*_a, **_k):
        raise RuntimeError("card store down")

    monkeypatch.setattr(mission_mod, "card_for_bot", _boom)
    success, partial = call_closer._outcome_sets({"bot_id": "score-probe"}, OBJECTIVE)
    assert success == call_closer.SUCCESS_BY_OBJECTIVE[OBJECTIVE]
    assert partial == frozenset()


def test_a_partial_is_never_scored_as_a_win(monkeypatch) -> None:
    """The Outbound tab's own words: partials are "kept apart so a partial is
    not scored as a win". Checked before success so an outcome listed under
    both does not get promoted."""
    import mission as mission_mod

    monkeypatch.setattr(
        mission_mod,
        "card_for_bot",
        lambda *_a, **_k: _card(success=["part_payment_agreed"], partial=["part_payment_agreed"]),
    )
    success, partial = call_closer._outcome_sets({"bot_id": "score-probe"}, OBJECTIVE)
    assert "part_payment_agreed" in success and "part_payment_agreed" in partial
    import inspect

    src = inspect.getsource(call_closer.close_one)
    assert "business not in partial and business in success" in src


# ---------------------------------------------------------------------------
# Who owns the case once the ladder runs out
# ---------------------------------------------------------------------------


def test_escalation_target_reads_the_cards_cadence() -> None:
    card = _card(escalate_to="human")
    assert cadence.escalation_target(card.outbound, OBJECTIVE) == "human"
    assert cadence.escalation_target(None, OBJECTIVE) is None


def test_an_exhausted_ladder_records_the_cards_target(db_tx) -> None:
    _needs_escalate_column(db_tx)
    cid = _customer(db_tx)
    case = cadence.ensure_case(
        db_tx,
        tenant_id=TENANT,
        customer_id=cid,
        objective=OBJECTIVE,
        case_ref="TD-esc-1",
    )
    state = cadence._exhaust(
        db_tx,
        case["id"],
        card_outbound=_card(escalate_to="human").outbound,
        objective=OBJECTIVE,
        outcome="no_resolution",
    )
    assert state == cadence.STATE_ESCALATED
    row = db_tx.execute(
        text("SELECT state, escalate_to, stopped_reason FROM call_cadence_state WHERE id = :i"),
        {"i": case["id"]},
    ).mappings().first()
    assert row["state"] == "escalated"
    assert row["escalate_to"] == "human"
    assert "escalate_to=human" in row["stopped_reason"]


def test_a_card_naming_nobody_still_just_exhausts(db_tx) -> None:
    """No target is not an escalation. The old behaviour is the default."""
    cid = _customer(db_tx)
    case = cadence.ensure_case(
        db_tx,
        tenant_id=TENANT,
        customer_id=cid,
        objective=OBJECTIVE,
        case_ref="TD-esc-2",
    )
    state = cadence._exhaust(
        db_tx,
        case["id"],
        card_outbound=_card().outbound,
        objective=OBJECTIVE,
        outcome=None,
    )
    assert state == cadence.STATE_EXHAUSTED
    row = db_tx.execute(
        text("SELECT state, stopped_reason FROM call_cadence_state WHERE id = :i"),
        {"i": case["id"]},
    ).mappings().first()
    assert row["state"] == "exhausted"
    assert row["stopped_reason"] == "max_attempts"


def test_cadence_records_the_target_and_does_not_act_on_it() -> None:
    """The module's stated boundary. A dialler that decided "three no-answers,
    send it to a human" would be a second escalation ladder."""
    import inspect

    src = inspect.getsource(cadence._exhaust)
    assert "escalation_target" in src
    assert "UPDATE call_cadence_state SET escalate_to" in src
    # Nothing here hands the case anywhere: no dial, no queue, no handoff.
    for verb in ("outbound.place", "reserve(", "handoff", "escalate_conversation"):
        assert verb not in src


def test_both_exhaustion_sites_go_through_one_helper() -> None:
    import inspect

    for fn in (cadence.on_outcome, cadence.process_one):
        src = inspect.getsource(fn)
        assert "_exhaust(" in src
        assert 'STATE_EXHAUSTED, "max_attempts"' not in src
