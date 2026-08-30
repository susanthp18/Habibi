"""Missions, cadence and the outbound compile gates — O2 through O5.

The claims these defend, in rough order of what it would cost to lose them:

* **An outbound call knows why it is happening.** The whole point of a mission.
  Without it every dial ran ``discover_intent`` and asked the borrower why they
  thought we were calling — on a call we placed, for a reason we chose.
* **The graph has more than one door.** One agent, one persona, one authority
  envelope, one compliance surface; several ways in. The alternative is a second
  card per direction, and then two of everything that has to stay in step.
* **Nothing about the debt is said to the wrong person.** The third-party
  protocol is the single place an outbound collections agent is most likely to
  cause real harm.
* **Cadence retries; it never escalates.** A dialler that could change the
  action would be a second treatment engine with no expected value, no
  propensity and no audit trail.
* **A card that cannot work does not publish.** Outbound failures are invisible
  until they are at scale: an inbound bug annoys one caller, an outbound bug
  rings ten thousand phones.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

import cadence
import flow_graph as fg
import mission
from agent_core.cards.compile import compile_card
from agent_core.cards.defaults import COLLECTIONS_BOT_ID, collections_card, intake_card
from agent_core.cards.schema import CardCadence, CardObjective, VoicemailPolicy
from agent_core.tools.catalog import CATALOG


def _card_with(**outbound_kw):
    card = collections_card()
    for key, value in outbound_kw.items():
        setattr(card.outbound, key, value)
    return card


def _builtin_flow():
    from voice.flow_export import built_in_collections_graph

    return built_in_collections_graph()


def _compile(card, flow=None):
    return compile_card(
        bot_id=COLLECTIONS_BOT_ID,
        card_raw=card.model_dump(mode="json"),
        flow=_builtin_flow() if flow is None else flow,
        catalog_names=set(CATALOG.specs),
        known_bot_ids={"kaia-v2-4", "insurance-v1", "supervisor-brief", "intake-v1"},
    )


def _gate(report, gate: str):
    return next((g for g in report.gates if g.gate == gate), None)


# ---------------------------------------------------------------------------
# The graph has several doors
# ---------------------------------------------------------------------------


def _graph(entries: dict[str, list[str]], *, start: str = "greet") -> dict:
    nodes = []
    for i, (key, claims) in enumerate(entries.items()):
        nodes.append(
            {
                "id": f"n-{key}",
                "key": key,
                "type": "conversation",
                "position": {"x": 0, "y": i * 150},
                "data": {
                    "name": key,
                    "instructions": "say something",
                    "isStart": key == start,
                    "entryFor": claims,
                    "respondImmediately": True,
                },
            }
        )
    return {"version": 1, "globalTools": [], "nodes": nodes, "edges": []}


def test_a_graph_can_have_more_than_one_way_in(db_tx) -> None:
    graph = fg.parse_graph(
        _graph({"greet": ["inbound"], "chase": ["broken_ptp_chase"], "cure": ["bounce_cure"]})
    )
    assert graph.entry_for("broken_ptp_chase").key == "chase"
    assert graph.entry_for("bounce_cure").key == "cure"
    assert graph.entry_for("inbound").key == "greet"
    assert graph.entry_objectives() == {
        "inbound": "greet",
        "broken_ptp_chase": "chase",
        "bounce_cure": "cure",
    }


def test_inbound_falls_back_to_the_start_node() -> None:
    """A graph authored before missions existed must keep behaving as it did."""
    graph = fg.parse_graph(_graph({"greet": [], "next": []}))
    assert graph.entry_for("inbound").key == "greet"
    assert graph.entry_for("bounce_cure") is None


def test_two_steps_cannot_claim_the_same_mission() -> None:
    """The runtime would pick whichever the node list ordered first, so a graph
    edit could change what a borrower hears without changing anything visible."""
    issues = fg.validate_graph(
        fg.parse_graph(_graph({"greet": ["inbound"], "a": ["bounce_cure"], "b": ["bounce_cure"]}))
    )
    codes = {i.code for i in issues.issues if i.severity == "error"}
    assert "duplicate_entry" in codes


def test_a_mission_cannot_begin_at_a_step_that_says_nothing() -> None:
    """The borrower answered a call we placed and heard silence."""
    graph = _graph({"greet": ["inbound"], "quiet": ["bounce_cure"]})
    node = next(n for n in graph["nodes"] if n["key"] == "quiet")
    node["data"]["respondImmediately"] = False
    node["data"]["entryLine"] = ""
    issues = fg.validate_graph(fg.parse_graph(graph))
    assert "silent_outbound_entry" in {i.code for i in issues.issues if i.severity == "error"}


def test_an_unknown_mission_name_is_rejected() -> None:
    issues = fg.validate_graph(fg.parse_graph(_graph({"greet": ["inbound"], "x": ["sell_them_a_boat"]})))
    assert "unknown_objective" in {i.code for i in issues.issues if i.severity == "error"}


def test_a_mission_entry_is_not_flagged_unreachable() -> None:
    """It is reached by being dialled, not by an edge."""
    issues = fg.validate_graph(fg.parse_graph(_graph({"greet": ["inbound"], "cure": ["bounce_cure"]})))
    assert "unreachable" not in {i.code for i in issues.issues}


# ---------------------------------------------------------------------------
# The mission itself
# ---------------------------------------------------------------------------


def _a_customer(conn) -> dict:
    row = conn.execute(
        text(
            """
            SELECT c.id, c.tenant_id, a.id AS account_id
            FROM customers c JOIN accounts a ON a.customer_id = c.id
            WHERE c.id <> 'UNKNOWN-CALLER'
            ORDER BY c.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no seeded customer with an account")
    return dict(row)


def test_a_mission_carries_the_reason_and_the_position(db_tx) -> None:
    cust = _a_customer(db_tx)
    built = mission.build(
        db_tx,
        customer_id=cust["id"],
        objective="bounce_cure",
        account_id=cust["account_id"],
        card=collections_card(),
        bot_id=COLLECTIONS_BOT_ID,
    )
    assert built is not None
    assert built["objective"] == "bounce_cure"
    assert built["brief"], "an agent that does not know why it called is the whole problem"
    assert built["entryNode"] == "confirm_identity"
    assert built["context"]["position"]["accountId"] == cust["account_id"]


def test_the_briefing_never_reads_letters_as_an_account_tail(db_tx) -> None:
    """`AC-SUSANTH`[-4:] is "ANTH", and the agent would have said it aloud.

    ``agent_core.context.account_tail`` was written for exactly this and returns
    None when an id has no trailing digits — so the briefing omits the phrasing
    instead of inventing a number.
    """
    from agent_core.context import account_tail

    assert account_tail("AC-SUSANTH") is None
    assert account_tail("AC-77410") == "7410"

    cust = _a_customer(db_tx)
    built = mission.build(
        db_tx,
        customer_id=cust["id"],
        objective="dpd_reminder",
        account_id=cust["account_id"],
        card=collections_card(),
    )
    tail = built["context"]["position"].get("accountTail")
    assert tail is None or (tail.isdigit() and len(tail) == 4)
    if tail is None:
        assert "account ending" not in mission.briefing(built)


def test_the_briefing_says_confirm_before_disclosing(db_tx) -> None:
    cust = _a_customer(db_tx)
    built = mission.build(
        db_tx,
        customer_id=cust["id"],
        objective="dpd_reminder",
        account_id=cust["account_id"],
        card=collections_card(),
    )
    brief = mission.briefing(built)
    assert "OUTBOUND CALL" in brief
    lowered = brief.lower()
    assert "before mentioning" in lowered
    assert "do not mention any product" in lowered


def test_a_hardship_mission_can_never_carry_an_offer(db_tx) -> None:
    """Even if the card allows one. Pitching to somebody who just declared
    hardship is the conduct failure that ends a bank pilot."""
    cust = _a_customer(db_tx)
    card = collections_card()
    card.outbound.objectives.append(
        CardObjective(key="hardship_intake", entry_node="confirm_identity",
                      allowed_offers=["personal-loan"], cadence="collections")
    )
    built = mission.build(
        db_tx, customer_id=cust["id"], objective="hardship_intake", card=card
    )
    assert built["allowedOffers"] == []
    assert "cross_sell" in built["prohibited"]


def test_a_service_number_forbids_offers_on_every_mission(db_tx) -> None:
    """TRAI's 1600 series carries service and transactional calls; a product
    pitch is neither."""
    cust = _a_customer(db_tx)
    card = collections_card()
    card.outbound.pool_kind = "service_1600"
    card.outbound.objectives[0].allowed_offers = ["personal-loan"]
    built = mission.build(
        db_tx,
        customer_id=cust["id"],
        objective=card.outbound.objectives[0].key,
        card=card,
    )
    assert built["allowedOffers"] == []


def test_the_decision_travels_with_the_mission(db_tx) -> None:
    """Without decision_id an outcome cannot be attributed; without propensity
    no off-policy estimate over the log is valid. Neither is reconstructable."""
    cust = _a_customer(db_tx)
    built = mission.build(
        db_tx,
        customer_id=cust["id"],
        objective="dpd_reminder",
        card=collections_card(),
        decision={
            "id": "TD-PROBE",
            "propensity": 0.62,
            "policy_version": 7,
            "variant": "treatment",
            "expected_value": 68.4,
            "trigger_kind": "dpd_tick",
        },
    )
    assert built["decisionId"] == "TD-PROBE"
    assert built["propensity"] == 0.62
    assert built["policyVersion"] == 7


def test_trigger_maps_to_one_mission_in_one_place() -> None:
    assert mission.objective_for_trigger("broken_ptp") == "broken_ptp_chase"
    assert mission.objective_for_trigger("bounce") == "bounce_cure"
    assert mission.objective_for_trigger(None) == "dpd_reminder"


# ---------------------------------------------------------------------------
# Cadence
# ---------------------------------------------------------------------------


def test_a_short_backoff_curve_repeats_rather_than_running_out() -> None:
    """[4, 24] on a three-attempt cadence means 4h, 24h, 24h — which is what an
    author writing two numbers means."""
    assert cadence.backoff_for(1, [4, 24]) == timedelta(hours=4)
    assert cadence.backoff_for(2, [4, 24]) == timedelta(hours=24)
    assert cadence.backoff_for(3, [4, 24]) == timedelta(hours=24)


def test_a_backoff_is_capped_however_long_the_card_asks_for() -> None:
    """A 30-day wait is not a cadence, it is a case somebody forgot about."""
    assert cadence.backoff_for(1, [24 * 90]) <= timedelta(
        hours=cadence.max_backoff_hours()
    )


def _open_case(conn, cust, objective="dpd_reminder", case_ref="TD-CADENCE"):
    return cadence.ensure_case(
        conn,
        tenant_id=cust["tenant_id"],
        customer_id=cust["id"],
        objective=objective,
        case_ref=case_ref,
        max_attempts=3,
    )


def _attempt_row(cust, *, state, objective="dpd_reminder", case_ref="TD-CADENCE"):
    return {
        "id": "CA-PROBE",
        "tenant_id": cust["tenant_id"],
        "customer_id": cust["id"],
        "objective": objective,
        "decision_id": case_ref,
        "campaign_run_id": None,
        "state": state,
        "attempt_no": 1,
    }


def test_a_no_answer_schedules_another_attempt(db_tx) -> None:
    cust = _a_customer(db_tx)
    case = _open_case(db_tx, cust)
    state = cadence.on_outcome(
        db_tx,
        attempt=_attempt_row(cust, state="no_answer"),
        connection="no_answer",
        business=None,
        card_outbound=collections_card().outbound,
    )
    assert state == cadence.STATE_OPEN
    nxt = db_tx.execute(
        text("SELECT next_attempt_at FROM call_cadence_state WHERE id = :id"),
        {"id": case["id"]},
    ).scalar()
    assert nxt is not None


def test_a_refusal_is_not_retried(db_tx) -> None:
    """They answered and said no. Dialling again in four hours is harassment
    dressed as persistence."""
    cust = _a_customer(db_tx)
    _open_case(db_tx, cust, case_ref="TD-REFUSED")
    state = cadence.on_outcome(
        db_tx,
        attempt=_attempt_row(cust, state="completed", case_ref="TD-REFUSED"),
        connection="connected",
        business="refused",
        card_outbound=collections_card().outbound,
    )
    assert state == cadence.STATE_STOPPED


def test_a_kept_promise_stops_the_ladder_with_attempts_to_spare(db_tx) -> None:
    cust = _a_customer(db_tx)
    _open_case(db_tx, cust, case_ref="TD-PTP")
    state = cadence.on_outcome(
        db_tx,
        attempt=_attempt_row(cust, state="completed", case_ref="TD-PTP"),
        connection="connected",
        business="ptp_captured",
        card_outbound=collections_card().outbound,
    )
    assert state == cadence.STATE_STOPPED


def test_an_opt_out_stops_the_ladder_immediately(db_tx) -> None:
    cust = _a_customer(db_tx)
    _open_case(db_tx, cust, case_ref="TD-OPTOUT")
    state = cadence.on_outcome(
        db_tx,
        attempt=_attempt_row(cust, state="completed", case_ref="TD-OPTOUT"),
        connection="connected",
        business="opt_out_requested",
        card_outbound=collections_card().outbound,
    )
    assert state == cadence.STATE_STOPPED


def test_the_ladder_runs_out(db_tx) -> None:
    cust = _a_customer(db_tx)
    case = _open_case(db_tx, cust, case_ref="TD-EXHAUST")
    db_tx.execute(
        text("UPDATE call_cadence_state SET attempts = 3 WHERE id = :id"), {"id": case["id"]}
    )
    state = cadence.on_outcome(
        db_tx,
        attempt=_attempt_row(cust, state="no_answer", case_ref="TD-EXHAUST"),
        connection="no_answer",
        business=None,
        card_outbound=collections_card().outbound,
    )
    assert state == cadence.STATE_EXHAUSTED


def test_a_manual_dial_does_not_open_a_ladder(db_tx) -> None:
    """Somebody pressed a button. That is not a campaign."""
    assert cadence._case_ref({"decision_id": None, "campaign_run_id": None}) == ""


# ---------------------------------------------------------------------------
# The outbound compile gates
# ---------------------------------------------------------------------------


def test_an_inbound_card_skips_every_outbound_gate() -> None:
    """Every card that exists today must compile exactly as it did."""
    report = _compile(intake_card())
    ob = [g for g in report.gates if g.gate.startswith("G-OB")]
    assert ob and all(g.status == "skipped" for g in ob)


def test_the_default_collections_card_still_publishes() -> None:
    report = _compile(collections_card())
    blocking = [g.gate for g in report.blocking]
    assert blocking == [], blocking


def test_dialling_with_no_mission_is_not_publishable() -> None:
    card = _card_with(objectives=[])
    assert _gate(_compile(card), "G-OB1").status == "fail"


def test_an_unauthored_flow_fails_g_ob2() -> None:
    """A card that dials with no canvas door is not N/A — it is unpublished."""
    gate = _gate(_compile(collections_card(), flow={}), "G-OB2")
    assert gate.status == "fail"
    assert "unauthored" in (gate.detail or "").lower() or "door" in (gate.detail or "").lower()


def test_the_card_and_the_flow_must_agree_where_a_mission_starts() -> None:
    """Two places can disagree, and the one nobody is looking at is the one
    that drifts."""
    card = collections_card()
    graph = _graph({"greet": ["inbound"], "elsewhere": ["bounce_cure"]})
    gate = _gate(_compile(card, flow=graph), "G-OB2")
    assert gate.status == "fail"
    assert "bounce_cure" in str(gate.issues)


def test_a_cadence_that_outruns_the_borrower_cap_is_not_publishable() -> None:
    card = _card_with(
        cadences=[CardCadence(name="collections", per_day=5)],
    )
    assert _gate(_compile(card), "G-OB3").status == "fail"


def test_four_missions_at_one_call_a_day_is_fine() -> None:
    """A borrower is on one case at a time. Summing every mission would block a
    perfectly sane card."""
    assert _gate(_compile(collections_card()), "G-OB3").status == "pass"


def test_an_offer_on_a_service_number_is_not_publishable() -> None:
    card = collections_card()
    card.outbound.pool_kind = "service_1600"
    card.outbound.objectives[0].allowed_offers = ["personal-loan"]
    assert _gate(_compile(card), "G-OB4").status == "fail"


def test_a_voicemail_without_the_grievance_contact_is_not_publishable() -> None:
    """RBI para 100AA: a voicemail is a recovery communication."""
    card = collections_card()
    card.outbound.objectives[0].voicemail = VoicemailPolicy(
        leave="always", include_grievance_contact=False
    )
    assert _gate(_compile(card), "G-OB5").status == "fail"


def test_a_post_call_action_nobody_implements_is_not_publishable() -> None:
    """A rule that silently does nothing is worse than no rule."""
    from agent_core.cards.schema import PostCallRule

    card = collections_card()
    card.outbound.post_call.on_outcome.append(
        PostCallRule(when="ptp_captured", do=["summon_a_wizard"])
    )
    assert _gate(_compile(card), "G-OB6").status == "fail"


def test_an_escalation_target_off_the_allowlist_is_not_publishable() -> None:
    card = collections_card()
    card.outbound.cadences[0].escalate_to = "intake-v1"
    gate = _gate(_compile(card), "G-OB7")
    assert gate.status == "fail"
    assert "allowlist" in gate.detail


def test_a_cadence_the_card_never_defined_is_not_publishable() -> None:
    """It would silently become the default — a different retry policy than the
    author wrote down."""
    card = collections_card()
    card.outbound.objectives[0].cadence = "gentle"
    assert _gate(_compile(card), "G-OB8").status == "fail"


def test_the_outcome_vocabulary_is_shared_not_copied() -> None:
    """The compiler restates it to avoid importing the post-call module; the
    pair has to stay pinned or a valid rule becomes unpublishable."""
    import call_closer
    from agent_core.cards import compile as compile_mod

    assert compile_mod.OUTCOME_CODES == call_closer.BUSINESS_OUTCOMES


def test_the_mission_vocabulary_is_shared_not_copied() -> None:
    from agent_core.cards.schema import Objective
    from typing import get_args

    assert set(get_args(Objective)) == set(fg.OBJECTIVES)
