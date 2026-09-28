"""Regressions from live sandbox call VS-92CDE3F088 (2026-08-19 22:52-22:56).

Four minutes of audio, three separate defects, none of them a wording problem:

* the caller was told the call was recorded three times, minutes apart;
* the line went completely silent for 24 seconds after ``begin_negotiate``,
  and the idle ladder never logged a strike;
* the outstanding and minimum due were read out twice in seven seconds, and
  the caller was asked for "the exact date in YYYY-MM-DD".

Each test below pins the mechanism, not the symptom.
"""

from __future__ import annotations

import pytest

from agent_core.guardrails import evaluate_guardrails

pytest.importorskip("pipecat.flows")


_DISCLOSE = {"alwaysDiscloseRecording": True}


def _flags(bot_text: str, *, turn_index: int, disclosed: bool = False) -> list[str]:
    return evaluate_guardrails(
        customer_text="",
        bot_text=bot_text,
        intent="out_of_scope",
        guardrails=_DISCLOSE,
        turn_index=turn_index,
        elapsed_seconds=1.0,
        customer_bot_exchanges=1,
        recording_disclosed=disclosed,
    )


# --- the disclosure was said three times -----------------------------------


def test_greeting_that_discloses_satisfies_the_rule() -> None:
    assert "missing-recording-disclosure" not in _flags(
        "Hello, this is Priya from BigTapp Bank Collections, and this call is "
        "recorded for quality and compliance.",
        turn_index=0,
    )


def test_second_turn_is_not_asked_to_disclose_again() -> None:
    """The bug. Turn 0 disclosed; turn 1 was flagged for not repeating it.

    The flag reached the turn critic, which injected "you have not yet
    satisfied a required disclosure", and the caller heard it twice more.
    """
    assert "missing-recording-disclosure" not in _flags(
        "Sure, I can help with your past due payments, but first I will need "
        "to verify your account.",
        turn_index=1,
        disclosed=True,
    )


def test_a_call_that_never_discloses_is_still_flagged() -> None:
    """The check must not have been softened into never firing."""
    assert "missing-recording-disclosure" in _flags(
        "Your outstanding is 62,400 rupees.", turn_index=1, disclosed=False
    )


def test_the_opening_turn_alone_is_not_yet_late() -> None:
    """Turn 0 is the greeting; lateness is judged from turn 1."""
    assert "missing-recording-disclosure" not in _flags(
        "Hello, this is Priya.", turn_index=0, disclosed=False
    )


def test_the_rendered_guardrail_says_once_not_always() -> None:
    from agent_core.prompt import guardrail_rules

    rule = " ".join(guardrail_rules(_DISCLOSE)).lower()
    assert "never say it again" in rule
    assert "always disclose" not in rule


# --- 24 seconds of dead air -------------------------------------------------


def test_the_builtin_graph_keeps_its_bridge_lines() -> None:
    """The export used to drop pre_actions, so a reload produced a silent step
    -- a live call sat mute for 24 seconds on negotiate_ptp. The graph is data
    now; the bridge lines it carries are the ones the runtime speaks."""
    from agent_core.cards.clone import _disk_flow
    from agent_core.cards.defaults import COLLECTIONS_BOT_ID

    by_key = {n["key"]: n["data"] for n in _disk_flow(COLLECTIONS_BOT_ID)["nodes"]}
    assert by_key["negotiate_ptp"]["entryLine"]
    assert not by_key["negotiate_ptp"]["respondImmediately"]


# --- the KB judge that never ran -------------------------------------------


def test_the_ending_reason_has_one_owner() -> None:
    """Three handlers latched `ending_reason` with two different rules (first
    wins, last wins), so what the interaction recorded depended on which ran.
    The session owns it: the first claim stands unless the caller overrides,
    which only a terminal flow node does."""
    from voice.session import VoiceSession

    session = VoiceSession(session_id="VS-ENDING01")
    session.mark_ending("dead_air")
    session.mark_ending("bot_farewell")
    assert session.extra["ending"] is True
    assert session.extra["ending_reason"] == "dead_air"
    session.mark_ending("flow_node:collections.escalate_close", override=True)
    assert session.extra["ending_reason"] == "flow_node:collections.escalate_close"
