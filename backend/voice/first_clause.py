"""Flush the first clause of an utterance, then SENTENCE for the rest.

TOKEN-everywhere is the VS-39B35AC484 cut-off class: Azure starts speaking
mid-thought and the caller barges on a fragment. The collections default stays
SENTENCE. The leftover is the *first* wait — a long opening sentence with a
comma (or six words) can start synthesising while the rest of the utterance
still waits for a period.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from pipecat.services.tts_service import TextAggregationMode
from pipecat.utils.text.simple_text_aggregator import SimpleTextAggregator
from pipecat.utils.text.base_text_aggregator import Aggregation, AggregationType

_CLAUSE_PUNCT = ",;:"
_FIRST_CLAUSE_WORDS = 6


class FirstClauseTextAggregator(SimpleTextAggregator):
    """SENTENCE aggregator that releases one early chunk, then waits for EOS."""

    def __init__(self, **kwargs) -> None:
        kwargs.setdefault("aggregation_type", TextAggregationMode.SENTENCE)
        super().__init__(**kwargs)
        self._first_flushed = False

    async def aggregate(self, text: str) -> AsyncIterator[Aggregation]:
        if self._aggregation_type == AggregationType.TOKEN:
            async for item in super().aggregate(text):
                yield item
            return

        for char in text:
            self._text += char
            if not self._first_flushed:
                clause = self._maybe_first_clause()
                if clause:
                    self._first_flushed = True
                    yield Aggregation(text=clause, type=AggregationType.SENTENCE)
                continue
            result = await self._check_sentence_with_lookahead(char)
            if result:
                yield result

    def _maybe_first_clause(self) -> str | None:
        buf = self._text
        for i, ch in enumerate(buf):
            if ch in _CLAUSE_PUNCT:
                result = buf[: i + 1].strip(" ")
                self._text = buf[i + 1 :]
                return result or None
        words = buf.split()
        if len(words) >= _FIRST_CLAUSE_WORDS:
            result = " ".join(words[:_FIRST_CLAUSE_WORDS])
            remainder = " ".join(words[_FIRST_CLAUSE_WORDS:])
            trailing = " " if buf.endswith((" ", "\n", "\t")) and remainder else ""
            self._text = (remainder + trailing) if remainder else trailing
            return result
        return None

    async def handle_interruption(self):
        await super().handle_interruption()
        self._first_flushed = False

    async def reset(self):
        await super().reset()
        self._first_flushed = False
