"""Regressions from sandbox call VS-9BC3DD9725.

One call produced four separate complaints — no knowledge-base answer, constant
thanking, a recording disclosure on every turn, and no proper close. The logs
showed no errors at all; every one of them was a design defect, and three shared
a single trigger: a compliance flag that should never have fired.
"""

from __future__ import annotations

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


# ------------------------------------------------------------ budget starvation


# --------------------------------------------------------------- the trap node


# ------------------------------------------------------- whose silence is it


