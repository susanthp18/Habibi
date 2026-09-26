"""The early TTS chunk ends on a whole word and is worth its own sentence.

VS-7956F27B36 spoke "what i" | "nsurance", "For travel t" | "o Singapore" and
a lone "Thanks," -- each chunk synthesised as its own sentence.
"""

from __future__ import annotations

import asyncio

from voice.first_clause import FirstClauseTextAggregator


def _chunks(text: str) -> list[str]:
    async def run() -> list[str]:
        agg = FirstClauseTextAggregator()
        out: list[str] = []
        # Streamed the way the LLM delivers it: a few characters at a time.
        for i in range(0, len(text), 3):
            async for a in agg.aggregate(text[i : i + 3]):
                out.append(a.text)
        tail = await agg.flush()
        if tail:
            out.append(tail.text if hasattr(tail, "text") else str(tail))
        return out

    return asyncio.run(run())


def test_no_chunk_splits_a_word() -> None:
    for text in (
        "I can help with that—what insurance product are you interested in?",
        "I can help. For travel to Singapore, we have a product named Travel Protect360.",
        "I understand you want recommendations and which type to take for Singapore travel.",
    ):
        chunks = _chunks(text)
        joined = " ".join(c.strip() for c in chunks)
        assert joined.split() == text.split(), chunks


def test_a_short_interjection_is_not_its_own_sentence() -> None:
    chunks = _chunks("Thanks, Susanth. I've updated your promise to the tenth of October.")
    assert chunks[0].strip() != "Thanks,", chunks
