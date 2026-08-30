"""The one mapping between a language's name and its BCP-47 tag.

Three surfaces name a language and, until this module existed, none of them
agreed:

* the Persona tab writes a display name — ``"Hindi"`` — into
  ``prompt_versions.persona.language``;
* ``AgentTuning.stt.language`` holds a BCP-47 tag — ``"hi-IN"`` — and is what
  actually binds the recogniser;
* the ``{language}`` prompt variable substitutes whatever string the context
  carries, which was the hardcoded ``"English"`` on every voice call.

So an operator could set Hindi in the Studio and get an English-listening
recogniser reading an English instruction aloud, with nothing in the product
reporting a conflict. A display name is not convertible to a tag by guesswork —
"Bengali" is ``bn-IN`` here and ``bn-BD`` one border away — so the conversion
has to be a table, and there has to be exactly one of it.

The names are the authoring vocabulary and the tags are the runtime vocabulary;
this module is the only place that is allowed to know both.
"""

from __future__ import annotations

from typing import NamedTuple


class LanguageEntry(NamedTuple):
    #: What an operator picks in the Studio.
    name: str
    #: What binds the recogniser and the synthesiser.
    tag: str


#: Ordered as the Studio lists them: the lingua franca first, then by speaker
#: count. Every tag here must resolve to a real ``pipecat`` ``Language`` member
#: — ``test_language_registry`` holds that line.
LANGUAGES: tuple[LanguageEntry, ...] = (
    LanguageEntry("English", "en-IN"),
    LanguageEntry("Hindi", "hi-IN"),
    LanguageEntry("Tamil", "ta-IN"),
    LanguageEntry("Telugu", "te-IN"),
    LanguageEntry("Kannada", "kn-IN"),
    LanguageEntry("Marathi", "mr-IN"),
    LanguageEntry("Bengali", "bn-IN"),
    LanguageEntry("Gujarati", "gu-IN"),
)

DEFAULT_TAG = "en-IN"
DEFAULT_NAME = "English"

_BY_NAME = {entry.name.casefold(): entry for entry in LANGUAGES}
_BY_TAG = {entry.tag.casefold(): entry for entry in LANGUAGES}


def names() -> list[str]:
    """Display names, in Studio order."""
    return [entry.name for entry in LANGUAGES]


def tags() -> list[str]:
    """BCP-47 tags, in Studio order."""
    return [entry.tag for entry in LANGUAGES]


def _normalise_tag(raw: str) -> str:
    return (raw or "").strip().replace("_", "-").casefold()


def tag_for(name: str | None) -> str | None:
    """BCP-47 tag for a display name, or ``None`` if it is not one of ours.

    ``None`` rather than the default on purpose: the caller needs to tell "the
    operator chose English" from "the operator chose something this build does
    not support", because only the second case should leave an existing tag
    alone.
    """
    entry = _BY_NAME.get((name or "").strip().casefold())
    return entry.tag if entry else None


def name_for(tag: str | None) -> str | None:
    """Display name for a BCP-47 tag, or ``None`` when unrecognised.

    Tolerant of the separator and case variants a tag picks up in transit
    (``hi_IN``, ``HI-in``) for the same reason ``normalize_language`` is: the
    value reaches here from tuning JSON, an operator's typing, and provider
    callbacks, and an exact-match lookup silently mislabels two of the three.
    """
    entry = _BY_TAG.get(_normalise_tag(tag))
    return entry.name if entry else None


def spoken_name(tag: str | None) -> str:
    """What to call this language *to the model*, falling back to English.

    Used for the ``{language}`` substitution, which is an instruction the LLM
    reads — so it must be a word ("Hindi"), never a tag ("hi-IN"). A prompt
    reading "Speak in hi-IN" is a real thing this prevented.
    """
    return name_for(tag) or DEFAULT_NAME
