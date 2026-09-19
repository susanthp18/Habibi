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


def test_courtesy_is_not_a_legal_escalation():
    intent, _ = classify_intent("this is a courtesy call")
    assert intent != "escalation"


def test_courteous_is_not_a_legal_escalation():
    intent, _ = classify_intent("he was very courteous about it")
    assert intent != "escalation"


def test_court_still_escalates():
    intent, _ = classify_intent("see you in court")
    assert intent == "escalation"


def test_courtesy_does_not_auto_escalate_when_legal_is_on():
    from agent_core.guardrails import evaluate_guardrails

    flags = evaluate_guardrails(
        customer_text="he was very courteous about it",
        bot_text="ok",
        intent=classify_intent("he was very courteous about it")[0],
        guardrails={"escalateLegal": True},
        turn_index=1,
        elapsed_seconds=1,
        customer_bot_exchanges=0,
    )
    assert "auto-escalate" not in flags


def test_discovered_is_not_product_cover():
    intent, _ = classify_intent("I discovered the charge today")
    assert intent != "product_faq"
