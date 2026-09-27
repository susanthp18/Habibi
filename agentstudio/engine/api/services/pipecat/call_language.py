"""Which language the caller is speaking, for agents that speak several.

Azure reports a language on every transcript (continuous language
identification). ``CallLanguageTracker`` sits right after speech-to-text and
turns that per-phrase signal into the call's current language:

* a switch needs a phrase of at least two words, or two short phrases in a
  row, so a stray "ok" or a name does not flip the conversation;
* on a switch it tells the model, in the conversation itself, before the
  caller's words reach it; the voice then follows the reply's script (see the
  Azure voice map), so nothing else needs to change;
* every language heard is kept, for the call record.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pipecat.frames.frames import Frame, LLMMessagesAppendFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "ta": "Tamil", "ar": "Arabic", "te": "Telugu",
    "kn": "Kannada", "ml": "Malayalam", "mr": "Marathi", "bn": "Bengali", "gu": "Gujarati",
    "ur": "Urdu", "fr": "French", "es": "Spanish", "de": "German",
}
_SCRIPTS = {"hi": "Devanagari", "mr": "Devanagari", "ta": "Tamil", "ar": "Arabic", "ur": "Arabic",
            "te": "Telugu", "kn": "Kannada", "ml": "Malayalam", "bn": "Bengali", "gu": "Gujarati"}

_MIN_WORDS_TO_SWITCH = 2


def language_name(locale: str) -> str:
    return LANGUAGE_NAMES.get(locale.split("-")[0].lower(), locale)


def multilingual_reply_rule(languages: list[str]) -> str:
    """The standing instruction for an agent whose callers may switch language."""
    names = ", ".join(dict.fromkeys(language_name(lang) for lang in languages))
    return (
        f"LANGUAGE: The caller may speak {names}, and may switch at any time. Always reply in the "
        "language of the caller's latest message, written in that language's own script "
        "(for example Devanagari for Hindi, Tamil script for Tamil, Arabic script for Arabic); "
        "never transliterate into Latin letters. Names, amounts and dates stay exactly as they are."
    )


def switch_note(locale: str) -> str:
    name = language_name(locale)
    script = _SCRIPTS.get(locale.split("-")[0].lower())
    in_script = f", in {script} script" if script else ""
    return f"The caller is now speaking {name}. Reply in {name}{in_script} from now on."


class CallLanguageTracker(FrameProcessor):
    """Follows the caller's language through the call; see the module docstring."""

    def __init__(
        self,
        *,
        initial: str,
        on_change: Callable[[str, list[str]], Awaitable[None] | None] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.current = initial
        self.spoken: list[str] = []
        self._pending: str | None = None
        self._on_change = on_change

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame) and frame.language and frame.text.strip():
            await self._observe(str(frame.language), len(frame.text.split()))
        await self.push_frame(frame, direction)

    async def _observe(self, language: str, words: int) -> None:
        changed = not self.spoken  # the first phrase establishes the language
        if language == self.current:
            self._pending = None
        elif words >= _MIN_WORDS_TO_SWITCH or self._pending == language:
            self._pending = None
            self.current = language
            changed = True
            # Before the caller's words, so the model reads them in context.
            await self.push_frame(LLMMessagesAppendFrame(
                [{"role": "system", "content": switch_note(language)}], run_llm=False,
            ))
        else:
            self._pending = language
            return
        if self.current not in self.spoken:
            self.spoken.append(self.current)
        if changed and self._on_change is not None:
            result = self._on_change(self.current, list(self.spoken))
            if result is not None:
                await result
