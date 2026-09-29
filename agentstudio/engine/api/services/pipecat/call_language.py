"""Which language the caller is speaking, for agents that speak several.

Azure reports a language on every transcript (continuous language
identification). ``CallLanguageTracker`` sits right after speech-to-text and
turns that per-phrase signal into the call's current language:

* a switch needs a phrase of at least six words, or two phrases in a row in
  the new language; digits are not words. Azure labels short English replies
  as Hindi or Tamil and spells them out in that script: "No thanks" as
  "நோ தாங்க்ஸ்" (run 67), "It is 2324" as "इट इज़। 2324।" and "No worries,
  thanks" as "नो वोर्री थैंक्स।" (run 69, where three words, the digits among
  them, flipped the call to Hindi twice);
* only the agent's languages count: a detection outside them (open-range
  refinement can label a Tamil phrase Arabic) is taken as the listed language
  of the same base language, or ignored;
* on a switch it tells the model, in the conversation itself, before the
  caller's words reach it, and reports the new language (``on_change``) so
  the voice follows it too (see ``PipecatEngine.record_caller_language``);
* every language heard is kept, for the call record.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from loguru import logger
from pipecat.frames.frames import Frame, LLMMessagesAppendFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "ta": "Tamil", "ar": "Arabic", "te": "Telugu",
    "kn": "Kannada", "ml": "Malayalam", "mr": "Marathi", "bn": "Bengali", "gu": "Gujarati",
    "ur": "Urdu", "fr": "French", "es": "Spanish", "de": "German",
}
_SCRIPTS = {"hi": "Devanagari", "mr": "Devanagari", "ta": "Tamil", "ar": "Arabic", "ur": "Arabic",
            "te": "Telugu", "kn": "Kannada", "ml": "Malayalam", "bn": "Bengali", "gu": "Gujarati"}

_MIN_WORDS_TO_SWITCH = 6


def letter_words(text: str) -> int:
    """Words with at least one letter: "2324" and "₹500" say nothing about language."""
    return sum(1 for word in text.split() if any(ch.isalpha() for ch in word))


def language_name(locale: str) -> str:
    return LANGUAGE_NAMES.get(locale.split("-")[0].lower(), locale)


def multilingual_reply_rule(languages: list[str]) -> str:
    """The standing instruction for an agent whose callers may switch language."""
    names = ", ".join(dict.fromkeys(language_name(lang) for lang in languages))
    # Not "the language of the latest message": a lone "हाँ" after an English
    # sentence turned a web call's replies into Hindi (run 65). The tracker
    # decides a switch and says so with switch_note.
    # "By the words, not the script": Azure writes an Indian-English caller's
    # "It is 2324" as "इट इज़ 2324" even when it labels it English, and the
    # model, told to answer in the caller's script, answered in Hindi (run 72).
    # The example has no digits: with "it is 2324" in its prompt the model sent
    # 2324 to verify_identity before the caller said a word (run 76).
    return (
        f"LANGUAGE: The caller may speak {names}, and may switch at any time. Reply in the "
        "language the caller is speaking, written in that language's own script "
        "(for example Devanagari for Hindi, Tamil script for Tamil, Arabic script for Arabic); "
        "never transliterate into Latin letters. Judge the language by the words, not the "
        "script they were transcribed in: speech recognition often writes English in Hindi or "
        "Tamil script (\"नो थैंक्स\" is English, \"no thanks\"), and that caller is speaking "
        "English. A word or two in another language (\"haan\", \"ok\", \"sorry\") does not change "
        "it. If the caller asks for a language, keep to it for the rest of the call. "
        "Names, amounts and dates stay exactly as they are."
    )


def switch_note(locale: str) -> str:
    """A hint, not an order: the recogniser's label can be English in another script."""
    name = language_name(locale)
    script = _SCRIPTS.get(locale.split("-")[0].lower())
    in_script = f", in {script} script" if script else ""
    return (
        f"Speech recognition now hears {name}. If the caller's words really are {name}, not "
        f"English written in another script, reply in {name}{in_script} from now on; if they "
        "asked you to keep to a language, keep to it."
    )


def not_a_switch_note(locale: str, current: str) -> str:
    """For a phrase recognition labelled ``locale`` that the check found was ``current``."""
    return (
        f"Speech recognition wrote the caller's last words in {language_name(locale)} script, "
        f"but they are speaking {language_name(current)}: read them as {language_name(current)} "
        f"and reply in {language_name(current)}."
    )


async def words_are_in(llm, text: str, locale: str, current: str) -> bool:
    """Ask the model whether ``text`` is really ``locale``, not ``current`` in its script.

    Azure labels an Indian caller's English Hindi or Tamil and writes it in that
    script: "what is the last date I can pay" came as "வாட் இஸ் தி லாஸ்ட் டேட் ஐ
    கேன் பி", ta-IN, nine words, and the call and its voice went Tamil (run 79).
    Word counts cannot tell that from Tamil; the words can. Fails open: on a slow
    or failed check the switch goes ahead as it would have.
    """
    from pipecat.processors.aggregators.llm_context import LLMContext

    name, current_name = language_name(locale), language_name(current)
    question = (
        f"A phone caller's words, as speech recognition wrote them: {text}\n\n"
        "Speech recognition often writes English in Hindi or Tamil script. Judge by the "
        f"words, not the script: is the caller speaking {name} or {current_name}? "
        f"Reply {name} or {current_name}."
    )
    try:
        async with asyncio.timeout(3):
            reply = await llm.run_inference(
                LLMContext([{"role": "user", "content": question}]),
                system_instruction="You name the language of one phrase. Reply with the language only.",
                max_tokens=64,
            )
    except Exception as e:
        logger.warning(f"Language check failed open: {type(e).__name__}")
        return True
    answer = (reply or "").strip().lower()
    logger.info(f"Language check {locale} vs {current}: {answer[:20]!r}")
    return not answer.startswith(current_name.lower())


class CallLanguageTracker(FrameProcessor):
    """Follows the caller's language through the call; see the module docstring."""

    def __init__(
        self,
        *,
        initial: str,
        languages: list[str] | None = None,
        on_change: Callable[[str, list[str]], Awaitable[None] | None] | None = None,
        confirm: Callable[[str, str, str], Awaitable[bool]] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.current = initial
        # None: every detected language counts.
        self.languages = list(dict.fromkeys([initial, *languages])) if languages else None
        self.spoken: list[str] = []
        self._pending: str | None = None
        self._on_change = on_change
        # (text, detected, current) -> is it really the detected language?
        self._confirm = confirm

    def _listed(self, detected: str) -> str | None:
        """``detected`` as one of the agent's languages, or None."""
        if self.languages is None or detected in self.languages:
            return detected
        base = detected.split("-")[0].lower()
        return next((lang for lang in self.languages if lang.split("-")[0].lower() == base), None)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame) and frame.language and (words := letter_words(frame.text)):
            language = self._listed(str(frame.language))
            if language is not None:
                await self._observe(language, words, frame.text)
        await self.push_frame(frame, direction)

    async def _observe(self, language: str, words: int, text: str = "") -> None:
        changed = not self.spoken  # the first phrase establishes the language
        if language == self.current:
            self._pending = None
        elif words >= _MIN_WORDS_TO_SWITCH or self._pending == language:
            self._pending = None
            if self._confirm is not None and not await self._confirm(text, language, self.current):
                await self.push_frame(LLMMessagesAppendFrame(
                    [{"role": "system", "content": not_a_switch_note(language, self.current)}],
                    run_llm=False,
                ))
                return
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
