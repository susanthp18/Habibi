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
async def test_two_english_words_in_tamil_script_do_not_flip():
    """Run 67: "No thanks" came back as "நோ தாங்க்ஸ்" (ta-IN) and the goodbye was in Tamil."""
    tracker, changes, _ = _tracker()
    await tracker._observe("en-IN", 12)
    await tracker._observe("ta-IN", 2)
    assert tracker.current == "en-IN"


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


@pytest.mark.asyncio
async def test_only_the_agents_languages_count():
    changes: list = []
    tracker = CallLanguageTracker(initial="en-IN", languages=["en-IN", "hi-IN", "ar-AE"],
                                  on_change=lambda lang, spoken: changes.append(lang))
    tracker.push_frame = lambda frame, direction=None: _noop()
    assert tracker._listed("ar-SA") == "ar-AE"  # refinement labels Arabic ar-SA
    assert tracker._listed("ta-IN") is None  # not this agent's: ignored
    assert tracker._listed("hi-IN") == "hi-IN"


async def _noop():
    return None


@pytest.mark.asyncio
async def test_the_voice_follows_the_caller_into_a_shared_script():
    """English and French are both Latin: the caller's language picks the voice,
    on a switch and for an agent that takes over the call."""
    from types import SimpleNamespace

    from pipecat.services.azure.tts import AzureTTSService

    from api.services.workflow.pipecat_engine import PipecatEngine

    tts = AzureTTSService(api_key="k", region="southeastasia", settings=AzureTTSService.Settings(
        voice="en-US-AvaNeural", language="en-US",
        voice_map={"en-US": "en-US-AvaNeural", "fr-FR": "fr-FR-DeniseNeural"},
    ))
    assert tts._voice_segments("Merci beaucoup.")[0][0] == "en-US-AvaNeural"
    engine = PipecatEngine.__new__(PipecatEngine)
    engine._call_context_vars = {"caller_language": "fr-FR"}
    await engine._follow_caller_language(SimpleNamespace(tts=tts))
    assert tts._voice_segments("Merci beaucoup.")[0][:2] == ("fr-FR-DeniseNeural", "fr-FR")
    # No voice map: nothing to follow, the agent's language is left alone.
    plain = SimpleNamespace(_settings=SimpleNamespace(voice_map=None))
    await engine._follow_caller_language(SimpleNamespace(tts=plain))
