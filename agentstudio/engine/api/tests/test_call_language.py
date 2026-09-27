"""The call's language follows the caller, but not on a stray word."""

import pytest
from pipecat.frames.frames import LLMMessagesAppendFrame

from api.services.pipecat.call_language import (
    CallLanguageTracker,
    multilingual_reply_rule,
    switch_note,
)


def _tracker():
    changes: list[tuple[str, list[str]]] = []
    tracker = CallLanguageTracker(initial="en-IN", on_change=lambda lang, spoken: changes.append((lang, spoken)))
    pushed: list = []

    async def push(frame, direction=None):
        pushed.append(frame)

    tracker.push_frame = push
    return tracker, changes, pushed


@pytest.mark.asyncio
async def test_first_phrase_records_the_language_without_a_note():
    tracker, changes, pushed = _tracker()
    await tracker._observe("en-IN", 6)
    assert changes == [("en-IN", ["en-IN"])]
    assert pushed == []


@pytest.mark.asyncio
async def test_a_real_sentence_switches_and_tells_the_model_first():
    tracker, changes, pushed = _tracker()
    await tracker._observe("en-IN", 6)
    await tracker._observe("hi-IN", 7)
    assert tracker.current == "hi-IN"
    assert isinstance(pushed[0], LLMMessagesAppendFrame)
    assert "Hindi" in pushed[0].messages[0]["content"]
    assert changes[-1] == ("hi-IN", ["en-IN", "hi-IN"])


@pytest.mark.asyncio
async def test_one_short_word_does_not_flip_but_two_do():
    tracker, changes, pushed = _tracker()
    await tracker._observe("en-IN", 5)
    await tracker._observe("ta-IN", 1)
    assert tracker.current == "en-IN" and pushed == []
    await tracker._observe("ta-IN", 1)
    assert tracker.current == "ta-IN"


@pytest.mark.asyncio
async def test_switching_back_is_a_change_too():
    tracker, changes, _ = _tracker()
    await tracker._observe("en-IN", 5)
    await tracker._observe("ar-AE", 5)
    await tracker._observe("en-IN", 5)
    assert changes[-1] == ("en-IN", ["en-IN", "ar-AE"])


def test_rules_name_the_languages_and_scripts():
    rule = multilingual_reply_rule(["en-IN", "hi-IN", "ta-IN"])
    assert "English, Hindi, Tamil" in rule and "never transliterate" in rule
    assert "Tamil script" in switch_note("ta-IN")
    assert "Arabic script" in switch_note("ar-AE")
