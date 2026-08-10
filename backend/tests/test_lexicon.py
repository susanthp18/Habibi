"""One abuse/legal lexicon, agreed on by every channel.

Three copies had grown — ``voice/safety.py``, ``agent_core/sentiment.py`` and an
inline tuple in ``bot_runtime.py`` — and all three feed *compliance escalation*.
They disagreed: voice narrowed ``kill`` to require a target and ``fir`` to
require police context after both misfired on real calls; sentiment matched by
bare substring so "skill" contained "kill"; bot_runtime carried eight words and
none of the narrowing.

These tests pin the merged behaviour, and specifically the false positives that
motivated each narrowing. A regression here escalates a cooperative caller to a
human, or fails to escalate an abusive one.
"""

from __future__ import annotations

import pytest

from agent_core import lexicon


# ---------------------------------------------------------------------------
# The false positives that motivated the narrowing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "that would kill the deal for me",
        "I've just been killing time waiting",
        "she has a lot of skill with these things",
        "the bass was too loud",
        "please shut the door",
    ],
)
def test_ordinary_speech_is_not_abuse(text: str) -> None:
    assert lexicon.is_abusive(text) is False


@pytest.mark.parametrize(
    "text",
    [
        # "fir" is the Hinglish spelling of फिर — "then" / "again".
        "fir se try karo na",
        "fir bataunga aapko",
        "he was very courteous about it",
    ],
)
def test_ordinary_speech_is_not_a_legal_threat(text: str) -> None:
    assert lexicon.is_legal_threat(text) is False


# ---------------------------------------------------------------------------
# What must still trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "you idiot",
        "just shut up and listen",
        "stfu",
        "this is fucking ridiculous",
        # Suffixed form — the \w* tail, which a plain \b would have dropped.
        "this is harassment, plain and simple",
        "I will kill you",
        "go to hell",
    ],
)
def test_abuse_trips(text: str) -> None:
    assert lexicon.is_abusive(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "I am speaking to my lawyer about this",
        "I will file an FIR against you",
        "police me FIR karunga",
        "see you in court",
        "I'm going to the ombudsman",
        "this is going to the consumer forum",
    ],
)
def test_legal_threat_trips(text: str) -> None:
    assert lexicon.is_legal_threat(text) is True


# ---------------------------------------------------------------------------
# The three former call sites now agree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("you idiot shut up", True),
        ("this is harassment", True),
        ("that would kill the deal", False),
        ("she has real skill", False),
        ("thanks, that's helpful", False),
    ],
)
def test_voice_guardrails_and_text_agree(text: str, expected: bool) -> None:
    """The whole point of the consolidation. If these ever diverge again, one
    channel escalates a call the others let through."""
    from agent_core.guardrails import evaluate_guardrails
    from voice import safety

    assert safety.detect_abuse(text) is expected

    flags = evaluate_guardrails(
        customer_text=text,
        bot_text="ok",
        intent="other",
        guardrails={"escalateAbuse": True},
        turn_index=1,
        elapsed_seconds=1,
        customer_bot_exchanges=0,
    )
    assert ("auto-escalate" in flags) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I will file an FIR against you", True),
        ("fir se try karo", False),
        ("my lawyer will call", True),
    ],
)
def test_voice_and_guardrails_agree_on_legal(text: str, expected: bool) -> None:
    """guardrails.py previously had a bare `sue\\b` and no `fir` handling at
    all, so it and voice disagreed about the Hinglish false positive."""
    from agent_core.guardrails import evaluate_guardrails
    from voice import safety

    assert safety.detect_legal(text) is expected

    flags = evaluate_guardrails(
        customer_text=text,
        bot_text="ok",
        intent="other",
        guardrails={"escalateLegal": True},
        turn_index=1,
        elapsed_seconds=1,
        customer_bot_exchanges=0,
    )
    assert ("auto-escalate" in flags) is expected


# ---------------------------------------------------------------------------
# Sentiment scoring
# ---------------------------------------------------------------------------


def test_sentiment_no_longer_double_penalises_one_word() -> None:
    """"fucking" used to trip both "fuck" and "fucking" for -1.4 on one word.

    The score is clamped at -1.0 either way, but the pre-clamp value fed the
    rolling average that drives sentiment-collapse escalation.
    """
    from agent_core.sentiment import estimate_sentiment

    assert lexicon.abuse_hits("this is fucking ridiculous") == 1


def test_sentiment_ignores_abuse_inside_other_words() -> None:
    from agent_core.sentiment import estimate_sentiment

    # "skill" must not be scored as "kill"; nothing else here is negative.
    assert estimate_sentiment("she has real skill") >= 0.0


def test_abuse_still_drives_sentiment_negative() -> None:
    from agent_core.sentiment import estimate_sentiment, sentiment_label

    score = estimate_sentiment("you idiot")
    assert score <= -0.5
    assert sentiment_label(score) == "negative"


def test_repeated_abuse_counted_once_per_distinct_term() -> None:
    """The escalation already fired on the first one."""
    assert lexicon.abuse_hits("idiot idiot idiot idiot") == 1
    assert lexicon.abuse_hits("you idiot, this is harassment") == 2


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------


def test_abuse_lexicon_still_importable_from_sentiment() -> None:
    """agent_core.sentiment.ABUSE_LEXICON is the documented import path."""
    from agent_core.sentiment import ABUSE_LEXICON

    assert "stfu" in ABUSE_LEXICON
    assert ABUSE_LEXICON is lexicon.ABUSE_LEXICON
