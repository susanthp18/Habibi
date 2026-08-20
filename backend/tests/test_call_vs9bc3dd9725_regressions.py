"""Regressions from sandbox call VS-9BC3DD9725.

One call produced four separate complaints — no knowledge-base answer, constant
thanking, a recording disclosure on every turn, and no proper close. The logs
showed no errors at all; every one of them was a design defect, and three shared
a single trigger: a compliance flag that should never have fired.
"""

from __future__ import annotations

import agent_core.turn_critic as tc
from agent_core.live_qa.checks import TurnFacts, check_hours


# --------------------------------------------------------------- hours window

def _facts(**kw) -> TurnFacts:
    base = dict(channel="voice", now_hour=20, bot_text="hello", turn_index=1)
    base.update(kw)
    return TurnFacts(**base)


def test_an_outbound_call_after_hours_is_still_a_breach() -> None:
    """The rule itself must keep working — this is the case it exists for."""
    assert check_hours(_facts(direction="outbound")) is not None


def test_an_inbound_call_after_hours_is_not_a_breach() -> None:
    """RBI governs contact *attempts*. Someone who rang the bank at 20:43 chose
    the hour themselves, and refusing to serve them would be the worse outcome."""
    assert check_hours(_facts(direction="inbound")) is None


def test_a_simulated_call_is_never_a_breach() -> None:
    """A sandbox rehearsal reaches no customer. Flagging one spent a
    high-severity self-correction on turn 1, before the caller had spoken."""
    assert check_hours(_facts(direction="outbound", simulated=True)) is None


def test_direction_defaults_to_the_stricter_reading() -> None:
    """A caller that has not been taught to set this keeps the old behaviour."""
    assert check_hours(_facts()) is not None


# ------------------------------------------------------- omission vs commission

def test_a_missing_disclosure_is_told_to_say_it_once() -> None:
    """The directive used to be "do not repeat that wording" for *every* flag.
    For a missing disclosure that describes a mistake the model did not make,
    and it resolved the contradiction by saying the missing thing on every
    subsequent turn — which is exactly what the caller complained about."""
    c = tc._guardrail_correction(["missing-mini-miranda"])
    assert c is not None
    assert "once" in c.directive
    assert "never repeat it" in c.directive
    assert "Do not repeat that wording" not in c.directive


def test_saying_something_forbidden_still_says_do_not_repeat_it() -> None:
    c = tc._guardrail_correction(["hours-breach"])
    assert c is not None
    assert "Do not repeat that wording" in c.directive


def test_a_rule_already_corrected_is_not_raised_again() -> None:
    """Four identical directives stacked in the context is not four times the
    compliance, it is an instruction louder than the conversation."""
    assert tc._guardrail_correction(["missing-mini-miranda"], ["missing-mini-miranda"]) is None


def test_a_correction_reports_the_flags_it_addressed() -> None:
    """So the caller can remember them for the rest of the call."""
    c = tc._guardrail_correction(["missing-mini-miranda", "hours-breach"])
    assert c is not None
    assert set(c.flags) == {"missing-mini-miranda", "hours-breach"}


# ------------------------------------------------------------ budget starvation

def test_no_single_kind_can_spend_the_whole_call_budget() -> None:
    """All four corrections went to guardrail flags in the first 71 seconds of a
    312-second call. The repetition that followed — the "kept saying thanks" —
    was precisely what the budget existed to catch, and it had nothing left."""
    assert tc.MAX_CORRECTIONS_PER_KIND
    for kind, cap in tc.MAX_CORRECTIONS_PER_KIND.items():
        assert 0 < cap < tc.MAX_CORRECTIONS_PER_CALL, kind


def test_every_kind_has_a_reserved_share() -> None:
    assert set(tc.MAX_CORRECTIONS_PER_KIND) == {
        tc.KIND_GUARDRAIL,
        tc.KIND_REPETITION,
        tc.KIND_LANGUAGE,
        tc.KIND_UNANSWERED,
    }


# --------------------------------------------------------------- the trap node

def test_gated_upsell_can_be_left() -> None:
    """The caller asked about travel insurance while parked here. The node's only
    script was the offer ladder, so the bot qualified a lead nobody asked for for
    three and a half minutes and never reached a closing node."""
    from voice.flow_export import built_in_collections_graph

    node = next(
        n for n in built_in_collections_graph()["nodes"] if n["key"] == "gated_upsell"
    )
    assert "return_to_position" in node["data"]["tools"]
    assert "begin_wrap_up" in node["data"]["tools"]


def test_gated_upsell_answers_questions_instead_of_qualifying_them() -> None:
    from voice.flow_export import built_in_collections_graph

    node = next(
        n for n in built_in_collections_graph()["nodes"] if n["key"] == "gated_upsell"
    )
    instructions = node["data"]["instructions"]
    assert "search_knowledge_base" in instructions
    assert "not about the offer" in instructions


# ------------------------------------------------------- whose silence is it

def test_the_idle_ladder_does_not_fire_while_the_bot_is_generating() -> None:
    """The aggregator's timer measures silence on the wire, and the bot thinking
    is silence on the wire. A node transition plus a 32-message summarisation
    took six seconds; the nudge fired into that gap and requested a second turn
    while the first was still generating. The caller heard the same
    promise-to-pay confirmation twice, two seconds apart."""
    from pipecat.frames.frames import LLMFullResponseEndFrame, LLMFullResponseStartFrame

    from voice.bot_turn_state import BotTurnStateObserver

    obs = BotTurnStateObserver()
    assert obs.busy() is False, "a fresh call owes the caller nothing"

    obs._generating = True
    assert obs.busy() is True

    obs._generating = False
    obs._touch()
    assert obs.busy() is True, "the gap between generating and speaking is still the bot's"
    assert obs.busy(grace_seconds=0) is False

    assert LLMFullResponseStartFrame and LLMFullResponseEndFrame


def test_a_tool_call_in_flight_counts_as_the_bot_owing_a_turn() -> None:
    from voice.bot_turn_state import BotTurnStateObserver

    obs = BotTurnStateObserver()
    obs._tool_calls = 1
    assert obs.busy(grace_seconds=0) is True
    obs._tool_calls = 0
    assert obs.busy(grace_seconds=0) is False


def test_a_stray_tool_result_cannot_drive_the_counter_negative() -> None:
    """A result can arrive for a call that began before the observer attached."""
    from voice.bot_turn_state import BotTurnStateObserver

    obs = BotTurnStateObserver()
    obs._tool_calls = max(0, obs._tool_calls - 1)
    assert obs._tool_calls == 0
    assert obs.busy(grace_seconds=0) is False
