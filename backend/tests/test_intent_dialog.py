"""Dialog-control intent classifiers — greetings, help, corrections, session break."""

from __future__ import annotations

from agent_core.intent import (
    classify_intent,
    is_correction,
    is_greeting,
    is_help_capabilities,
    resolve_intent,
)


def test_what_can_you_do_is_help_not_out_of_scope():
    intent, _ = classify_intent("What can you do")
    assert intent == "help_capabilities"


def test_correction_phrases():
    assert is_correction("Well I didnt ask that")
    assert is_correction("That's not what I asked")
    assert not is_correction("Can I pay next Friday?")


def test_greeting_short():
    assert is_greeting("Hey")
    assert is_greeting("hi")
    assert not is_greeting("Hey can I pay my EMI?")


def test_resolve_intent_breaks_stale_product_session_on_help():
    intent, _ = resolve_intent(
        "What can you do",
        prior_intent="product_faq",
    )
    assert intent == "help_capabilities"


def test_resolve_intent_breaks_on_correction():
    intent, _ = resolve_intent(
        "Well I didnt ask that",
        prior_intent="payment_intent",
    )
    assert intent == "correction"


def test_product_faq_still_wins_for_exclusions():
    intent, _ = resolve_intent(
        "Okay what are the exclusions applicable for travel insurance",
        prior_intent="help_capabilities",
    )
    assert intent == "product_faq"


def test_detail_followup_keeps_product_session():
    intent, _ = resolve_intent("tell me all", prior_intent="product_faq")
    assert intent == "product_faq"


def test_help_capabilities_detector():
    assert is_help_capabilities("what can u do")
    assert is_help_capabilities("How can you help me?")
    assert not is_help_capabilities("I want to pay my EMI")
