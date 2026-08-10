"""The LLM→TTS boundary tap: what the bot said, and whether it said it yet.

This processor answers two questions, both from the same vantage point.

**1. "Has the in-flight response emitted any text yet?"** — the interlock
between the two ways of covering the pause while a tool runs:

1. **Acknowledge-then-call** — the model emits a short clause in the *same*
   response as the tool call ("Sure, I can set that up."), so TTS starts while
   the tool is still executing. This is the good path: it is contextual, and it
   costs nothing extra.
2. **The automatic filler** — ``on_function_calls_started`` in voice/bot.py
   queues a canned phrase for known-slow tools. This is the fallback for tools
   the model calls silently.

Run both unconditionally and the bot talks over itself: the filler fires while
the acknowledgement is already being spoken. The filler reads
:attr:`spoke_this_response` before deciding to speak.

**2. "What did the bot actually say, in the order it said it?"** — the
authoritative bot-turn record. This used to be taken downstream, from
``LLMAssistantAggregator``'s ``on_assistant_turn_stopped``, and that position is
wrong for a CRM transcript in two independent ways. Both were observed on call
``VS-6B252E0479`` (2026-08-01):

*Turns went missing.* ``TTSService`` holds each ``LLMFullResponseEndFrame``
keyed by audio context and only re-pushes it when that context drains
(``tts_service.py:770`` → ``:1523``). Its interruption handler **clears** the
pending map (``tts_service.py:946``). So when the caller barges in before a
reply's audio context closes, the end frame is dropped, the assistant
aggregator's turn never stops, and the turn is never written. Two spoken
re-engagement turns vanished from that call's transcript for exactly this
reason.

*Turns were stamped 10-20s late.* The assistant aggregator sits downstream of
the output transport, which releases frames at audio-playout rate, while
customer turns are stamped on the unpaced input side. The two halves of one
conversation were being indexed on two different clocks, so the persisted order
could differ from the spoken order.

Reading the turn here — before TTS, before the transport, before any pacing —
fixes both: production order is the real order, and nothing downstream can drop
a turn we have already seen in full. It also yields the model's own text rather
than the word-aligned reconstruction, which on that same call had duplicated
spans ("...roughly)? (roughly)?") from
``AggregatedFrameSequencer.force_complete`` re-emitting text whose words Azure's
word-boundary events never reported.

Interruption is still recorded — ``InterruptionFrame`` arriving while a response
is open marks that turn ``interrupted`` — so the "caller cut in" signal that the
aggregator used to provide is preserved.

Placed between ``llm`` and ``tts``. Like the KB speculator it pushes first and
observes after: a processor on the audio path must never be able to gate it.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)

BotTurnHandler = Callable[[str, bool], Awaitable[None]]
"""``(text, interrupted) -> None``. Awaited on the pipeline task, so it must not
block: the handler is expected to enqueue, not to do work."""


class SpokeThisResponseProbe(FrameProcessor):
    """Tracks the in-flight LLM response and reports each completed bot turn."""

    def __init__(self, *, on_bot_turn: BotTurnHandler | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._spoke = False
        self._on_bot_turn = on_bot_turn
        self._parts: list[str] = []
        self._open = False
        self._interrupted = False

    @property
    def spoke_this_response(self) -> bool:
        return self._spoke

    def set_bot_turn_handler(self, handler: BotTurnHandler | None) -> None:
        """Wired after construction — the sink is built before the pipeline."""
        self._on_bot_turn = handler

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        # Push first, always — this is a tap, not a gate.
        await self.push_frame(frame, direction)

        try:
            if isinstance(frame, LLMFullResponseStartFrame):
                # Anything still open was cut off without an end frame; emit it
                # rather than silently losing it to the new response.
                await self._close(interrupted=True)
                self._spoke = False
                self._open = True
                self._interrupted = False
            elif isinstance(frame, InterruptionFrame):
                # Barge-in. The response may still emit an end frame (the LLM
                # keeps streaming); flag it and let _close report it.
                self._spoke = False
                self._interrupted = True
            elif isinstance(frame, LLMFullResponseEndFrame):
                await self._close(interrupted=self._interrupted)
            elif isinstance(frame, TextFrame):
                text = getattr(frame, "text", "") or ""
                if text.strip():
                    self._spoke = True
                if self._open and text:
                    self._parts.append(text)
        except Exception:
            logger.debug("spoke-probe failed", exc_info=True)

    async def _close(self, *, interrupted: bool) -> None:
        parts, self._parts = self._parts, []
        was_open, self._open = self._open, False
        self._interrupted = False
        if not was_open:
            return
        text = "".join(parts).strip()
        if not text or self._on_bot_turn is None:
            return
        try:
            await self._on_bot_turn(text, interrupted)
        except Exception:
            logger.exception("bot-turn handler failed")
