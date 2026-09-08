"""W2 — one logging contract, two scorers."""

from __future__ import annotations

from agent_core import logging_contract


def test_greedy_action_probability_is_one() -> None:
    drawn = logging_contract.draw(
        ["sms", "whatsapp"], greediness=1.0, arm_probability=0.5, nonce="n1"
    )
    assert drawn is not None
    assert drawn.action_propensity == 1.0
    assert drawn.arm_propensity == 0.5
    assert drawn.propensity == 0.5
    assert drawn.kind == logging_contract.KIND_GREEDY


def test_unsupported_mass_is_absent_from_the_distribution() -> None:
    drawn = logging_contract.draw(["sms"], greediness=0.4, nonce="n")
    assert drawn is not None
    assert "whatsapp" not in drawn.distribution
    assert list(drawn.distribution) == ["sms"]


def test_replay_of_ten_thousand_draws_is_byte_identical() -> None:
    items = ("sms", "whatsapp", "voice_bot")
    mismatches = 0
    for i in range(10_000):
        nonce = f"{i:08x}"
        first = logging_contract.draw(
            items, greediness=0.45, arm_probability=0.7, nonce=nonce, subject_id="c"
        )
        second = logging_contract.draw(
            items, greediness=0.45, arm_probability=0.7, nonce=nonce, subject_id="c"
        )
        assert first is not None and second is not None
        if (
            first.index != second.index
            or first.arm_propensity != second.arm_propensity
            or first.action_propensity != second.action_propensity
            or first.distribution != second.distribution
            or items[first.index] != items[second.index]
        ):
            mismatches += 1
    assert mismatches == 0
