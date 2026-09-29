"""The call's language follows the caller, but not on a stray word."""

import asyncio

import pytest
from pipecat.frames.frames import LLMMessagesAppendFrame

from api.services.pipecat.call_language import (
    CallLanguageTracker,
    multilingual_reply_rule,
    switch_note,
    words_are_in,
)


def _tracker():
    changes: list[tuple[str, list[str]]] = []
    tracker = CallLanguageTracker(initial="en-IN", on_change=lambda lang, spoken: changes.append((lang, spoken)))
    tracker.checks = []
    tracker.create_task = lambda coro, name=None: tracker.checks.append(asyncio.ensure_future(coro))
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
    await tracker._observe("ar-AE", 6)
    await tracker._observe("en-IN", 6)
    assert changes[-1] == ("en-IN", ["en-IN", "ar-AE"])


@pytest.mark.asyncio
async def test_short_english_written_in_hindi_does_not_flip():
    """Run 69: "It is 2324" and "No worries, thanks" came back as Hindi script
    (hi-IN) and each flipped the call, voice and all, to Hindi."""
    from api.services.pipecat.call_language import letter_words

    tracker, _, pushed = _tracker()
    await tracker._observe("en-IN", 3)
    assert letter_words("इट इज़। 2324।") == 2  # the digits are not a word
    await tracker._observe("hi-IN", letter_words("इट इज़। 2324।"))
    await tracker._observe("en-IN", letter_words("Wait, wait, I I don't understand really."))
    await tracker._observe("hi-IN", letter_words("नो वोर्री थैंक्स।"))
    assert tracker.current == "en-IN" and pushed == []
    assert letter_words("2324") == 0


def test_rules_name_the_languages_and_scripts():
    rule = multilingual_reply_rule(["en-IN", "hi-IN", "ta-IN"])
    assert "English, Hindi, Tamil" in rule and "never transliterate" in rule
    # Digits in an example get sent to verify_identity (run 76).
    assert not any(ch.isdigit() for ch in rule)
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


@pytest.mark.asyncio
async def test_english_in_tamil_script_is_checked_and_does_not_switch():
    """Run 79: "what is the last date I can pay" came as nine Tamil-script words, ta-IN."""
    asked: list = []

    async def confirm(text, locale, current):
        asked.append((text, locale, current))
        return False

    tracker, changes, pushed = _tracker()
    tracker._confirm = confirm
    await tracker._observe("en-IN", 6, "Yeah, speaking.")
    await tracker._observe("ta-IN", 9, "வாட் இஸ் தி லாஸ்ட் டேட் ஐ கேன் பி")
    await _checks_done(tracker)
    assert asked == [("வாட் இஸ் தி லாஸ்ட் டேட் ஐ கேன் பி", "ta-IN", "en-IN")]
    assert tracker.current == "en-IN" and changes == [("en-IN", ["en-IN"])]
    assert "speaking English" in pushed[-1].messages[0]["content"]


@pytest.mark.asyncio
async def test_a_checked_real_switch_goes_ahead():
    async def confirm(text, locale, current):
        return True

    tracker, changes, _ = _tracker()
    tracker._confirm = confirm
    await tracker._observe("en-IN", 6)
    await tracker._observe("ta-IN", 7, "எனக்கு இந்த மாதம் சம்பளம் இன்னும் வரவில்லை")
    assert tracker.current == "en-IN"  # the words went on; the check runs beside them
    await _checks_done(tracker)
    assert tracker.current == "ta-IN"


class _LLM:
    def __init__(self, reply=None, error=None):
        self.reply, self.error = reply, error

    async def run_inference(self, context, **kwargs):
        if self.error:
            raise self.error
        return self.reply


@pytest.mark.asyncio
async def test_the_check_reads_the_models_answer_and_fails_open():
    assert await words_are_in(_LLM("English"), "वाट इज़", "hi-IN", "en-IN") is False
    assert await words_are_in(_LLM("Hindi"), "मुझे पैसे", "hi-IN", "en-IN") is True
    assert await words_are_in(_LLM(error=RuntimeError()), "x", "ta-IN", "en-IN") is True


async def _checks_done(tracker):
    await asyncio.gather(*tracker.checks)
