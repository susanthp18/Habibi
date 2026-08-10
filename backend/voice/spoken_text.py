"""Normalise model output into text that can actually be spoken.

A language model writes for the eye. It reaches for parenthetical asides,
bracketed qualifiers, markdown emphasis and slash-separated alternatives —
none of which exist in speech. On a phone call that is not merely untidy; on
call ``VS-6B252E0479`` (2026-08-01) it corrupted the transcript.

The failure chain, from that call's log:

1. The model wrote ``…what's the age range of the travellers (roughly)?``
2. Azure TTS synthesised it, but its word-boundary events never reported the
   bracket-adjacent tokens, so ``AggregatedFrameSequencer`` could not match
   them to a slot::

       Word 'and' not recognised by any slot, emitting as passthrough
       force-completing slot with remaining text '(and is it for you only or …)?'

3. The words were emitted once as passthrough and then a second time by
   ``force_complete``, so the assistant context and the CRM transcript both
   recorded ``…the travellers roughly)? (roughly)?``.
4. That duplicated text went back into the model's context, where it read as a
   speech pattern to imitate.

Stripping the constructs at the TTS boundary removes the trigger rather than
patching the symptom, and it is the right behaviour independently: a caller
cannot hear a parenthesis.

**Chunk safety.** ``BaseTextFilter.filter`` is called per aggregated chunk, so an
opening bracket can arrive in one call and its closer in the next. Every rule
here is therefore *stateless and character-local* — brackets are removed, never
matched as pairs — so a chunk boundary can never change the result. That is why
this does not try to be a markdown parser.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pipecat.utils.text.base_text_filter import BaseTextFilter

# Bracketing characters. Removed, not paired: see "Chunk safety" above. The
# words inside are usually meaningful ("(roughly)" → "roughly"), so dropping the
# delimiter and keeping the content is the faithful reading.
_BRACKETS = re.compile(r"[()\[\]{}<>]")

# Markdown emphasis and structure. The role message already forbids these; this
# is the backstop for when the model does it anyway.
_MARKDOWN = re.compile(r"[*_`#|]+")

# "Basic/Silver/Gold" is read by Azure as one run-on token. Spoken, these are
# alternatives — the caller needs to hear the "or".
_SLASH_ALTERNATIVES = re.compile(r"(?<=[^\W\d_])\s*/\s*(?=[^\W\d_])")

# Left over once delimiters go: " , ?" or ",," or " ." Collapse to what a
# person would say.
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")
_REPEATED_PUNCT = re.compile(r"([,;:])(\s*[,.;:!?])+")
_WHITESPACE = re.compile(r"[ \t ]{2,}")


def to_spoken(text: str) -> str:
    """Rewrite one chunk of model output as speakable text.

    Pure and stateless — safe to call on partial text, and used directly by the
    tests and the eval harness as well as by :class:`SpokenTextFilter`.
    """
    if not text:
        return text
    # Preserve leading/trailing spacing: chunks are concatenated downstream, so
    # eating a boundary space would glue two words together.
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()) :]
    body = text.strip()
    if not body:
        return text

    body = _BRACKETS.sub(" ", body)
    body = _MARKDOWN.sub("", body)
    body = _SLASH_ALTERNATIVES.sub(" or ", body)
    body = _SPACE_BEFORE_PUNCT.sub(r"\1", body)
    body = _REPEATED_PUNCT.sub(lambda m: m.group(0)[-1], body)
    body = _WHITESPACE.sub(" ", body).strip()
    return f"{lead}{body}{trail}"


class SpokenTextFilter(BaseTextFilter):
    """``BaseTextFilter`` adapter over :func:`to_spoken`.

    Installed via ``TTSService(text_filters=[...])``, which applies filters
    after aggregation and before synthesis.
    """

    async def update_settings(self, settings: Mapping[str, Any]) -> None:
        """No configurable settings — the transformation is not optional."""

    async def filter(self, text: str) -> str:
        return to_spoken(text)

    async def handle_interruption(self) -> None:
        """Nothing to reset: the filter holds no cross-chunk state."""

    async def reset_interruption(self) -> None:
        """Nothing to reset: the filter holds no cross-chunk state."""
