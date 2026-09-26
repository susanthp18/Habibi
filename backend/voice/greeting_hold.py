"""Keep what the caller said while the opening turn could not be interrupted.

The default tuning mutes the caller until the bot's first turn finishes
(``until_first_bot_complete``) so the recording disclosure is always heard in
full. Pipecat implements that mute by *dropping* the caller's frames, transcripts
included. On a phone call people talk over a greeting ("Hello? Who is this?"),
and those words never reached the conversation: on the barge-in test call the
borrower's "I know my payment is late" was simply lost.

This processor sits between STT and the user aggregator. During the first mute
window it holds final transcripts instead of letting the aggregator discard
them; when the aggregator unmutes it replays them as one caller turn. The mute
still does its job -- nothing interrupts the disclosure -- and nothing the caller
said is thrown away.

Only the first window: the function-call mute is short and the model is mid-tool,
so replaying speech there would be a behaviour change beyond this fix.

If ``UserMuteStoppedFrame`` never arrives (a lost unmute), a timeout releases
the hold so the call is not silent for the rest of the session. The timeout
follows the disclosure's own playback, read from the ``BotStartedSpeakingFrame``
/ ``BotStoppedSpeakingFrame`` the output transport sends upstream through this
processor: a ceiling until the greeting starts, a longer one while it plays, and
a short grace once it stops (the unmute follows the stop by milliseconds). It
used to be one fixed 12s from mute-start, which also had to cover the LLM's
first-token wait; a normal opening overran it on every outbound call in the
logs (4 of 4 over 72h), and from the timeout to the real unmute -- 4.8s on
VS-B8A775DEDF -- anything the caller said went to a muted aggregator and was
dropped, the loss this processor exists to prevent.

Interims are forwarded while holding. The speculator sits downstream of this
processor and upstream of the muted aggregator, so it can start retrieval
during the disclosure; the aggregator still drops those interims itself.
Finals stay held so they become one replayed turn on unmute.

The replay must not synthesise ``VADUserStartedSpeakingFrame`` /
``VADUserStoppedSpeakingFrame``. Smart Turn analysing an empty buffer returns
INCOMPLETE, ``_maybe_trigger_user_turn_stopped`` no-ops, and the turn waits
out the 5s aggregator backstop. ``voice/ivr.py`` already documents that trap
for keypad input. The replayed frame is marked ``hold_replay=True`` so a
scoped start strategy can open the turn; ordinary speech transcripts do not
match, which is the VS-39B35AC484 reason the blanket transcription start
strategy was removed.

On a call we placed, what the callee says *before* the greeting starts is
dropped, not replayed (``drop_before_greeting``). They picked up a ringing
phone: "Hello?" is all it can be, and it cannot answer a question not yet
asked. VS-58097BA530 heard that pickup as "No." at 0.9s; replayed after the
greeting it opened a turn that swallowed the real answer, the model read
"No. Yes." as confirmation and called verify_identity with it. Inbound keeps
it: the caller rang us and may open with why.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    TranscriptionFrame,
    UserMuteStartedFrame,
    UserMuteStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

try:
    from pipecat.frames.frames import InterimTranscriptionFrame
except ImportError:  # pragma: no cover - older Pipecat
    InterimTranscriptionFrame = None  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)

#: Mute started, greeting not yet audible: the first LLM token plus TTS
#: first byte. Longer than this and the opening never began.
_DEFAULT_HOLD_TIMEOUT_SECS = 12.0

#: The greeting is playing. The overlay caps a turn at 45 words (under 20s at
#: any Azure rate); past this a lost BotStoppedSpeakingFrame is the likelier
#: story than a still-running disclosure.
_SPEECH_CEILING_SECS = 45.0

#: The greeting stopped. The aggregator unmutes on the same frame, so the
#: UserMuteStoppedFrame is milliseconds behind; this only covers a lost one.
_POST_SPEECH_GRACE_SECS = 3.0

#: Attribute set on the replayed TranscriptionFrame. The start strategy matches
#: this flag, not the text -- a prefix would leak into the model context.
HOLD_REPLAY_ATTR = "hold_replay"


def is_hold_replay(frame: Any) -> bool:
    """True only for the concatenated turn GreetingHold replays on unmute."""
    return bool(getattr(frame, HOLD_REPLAY_ATTR, False))


def mark_hold_replay(frame: TranscriptionFrame) -> TranscriptionFrame:
    """Stamp the frame the greeting-replay start strategy is allowed to match."""
    setattr(frame, HOLD_REPLAY_ATTR, True)
    return frame


def build_greeting_replay_turn_start_strategy() -> Any | None:
    """Open a user turn on the replayed greeting-hold transcript, and nothing else.

    The disclosure has already finished when this fires (unmute is
    ``until_first_bot_complete``), so interruptions are enabled: the bot is no
    longer speaking the line that must be heard in full.
    """
    try:
        from pipecat.turns.types import ProcessFrameResult
        from pipecat.turns.user_start.base_user_turn_start_strategy import (
            BaseUserTurnStartStrategy,
        )
    except ImportError:
        logger.warning("turn start strategy base unavailable — greeting replay turns off")
        return None

    class GreetingReplayUserTurnStartStrategy(BaseUserTurnStartStrategy):
        """Opens a user turn on a GreetingHold replay, and nothing else."""

        async def process_frame(self, frame: Frame) -> Any:
            if isinstance(frame, TranscriptionFrame) and is_hold_replay(frame):
                await self.trigger_user_turn_started()
                return ProcessFrameResult.STOP
            return ProcessFrameResult.CONTINUE

    return GreetingReplayUserTurnStartStrategy(enable_interruptions=True)


class GreetingHold(FrameProcessor):
    def __init__(
        self,
        *,
        timeout_secs: float = _DEFAULT_HOLD_TIMEOUT_SECS,
        speech_ceiling_secs: float = _SPEECH_CEILING_SECS,
        post_speech_grace_secs: float = _POST_SPEECH_GRACE_SECS,
        drop_before_greeting: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._drop_before_greeting = bool(drop_before_greeting)
        self._greeting_started = False
        self._dropped_words = 0
        self._holding = False
        self._done = False
        self._held: list[TranscriptionFrame] = []
        self._timeout_secs = float(timeout_secs)
        self._speech_ceiling_secs = float(speech_ceiling_secs)
        self._post_speech_grace_secs = float(post_speech_grace_secs)
        self._timeout_task: asyncio.Task[None] | None = None

    def _cancel_timeout(self) -> None:
        task = self._timeout_task
        self._timeout_task = None
        if task is not None and not task.done():
            task.cancel()

    def _arm_timeout(self, secs: float, stage: str) -> None:
        """(Re)start the one timer. Each stage replaces the previous deadline."""
        self._cancel_timeout()
        if self._timeout_secs <= 0:
            return  # timeouts switched off entirely
        try:
            self._timeout_task = asyncio.get_running_loop().create_task(
                self._timeout_release(secs, stage)
            )
        except RuntimeError:
            logger.debug("greeting hold has no running loop to arm a timeout")

    async def _timeout_release(self, secs: float, stage: str) -> None:
        try:
            await asyncio.sleep(secs)
        except asyncio.CancelledError:
            return
        if not self._holding or self._done:
            return
        logger.warning(
            "greeting hold timed out %s after %.1fs — releasing without unmute", stage, secs
        )
        self._holding, self._done = False, True
        await self._release()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, UserMuteStartedFrame) and not self._done:
            self._holding = True
            self._arm_timeout(self._timeout_secs, "before the greeting started")
        elif isinstance(frame, BotStartedSpeakingFrame) and self._holding:
            self._greeting_started = True
            self._arm_timeout(self._speech_ceiling_secs, "while the greeting played")
        elif isinstance(frame, BotStoppedSpeakingFrame) and self._holding:
            self._arm_timeout(self._post_speech_grace_secs, "after the greeting stopped")
        elif isinstance(frame, UserMuteStoppedFrame) and self._holding:
            self._cancel_timeout()
            self._holding, self._done = False, True
            await self.push_frame(frame, direction)
            await self._release()
            return

        if self._holding and direction == FrameDirection.DOWNSTREAM:
            # Interims go through: KbSpeculationProcessor is the next stage and
            # the muted aggregator will drop them itself. Finals are held so
            # unmute can replay one concatenated turn.
            if InterimTranscriptionFrame is not None and isinstance(frame, InterimTranscriptionFrame):
                await self.push_frame(frame, direction)
                return
            if isinstance(frame, TranscriptionFrame):
                if self._drop_before_greeting and not self._greeting_started:
                    self._dropped_words += len(frame.text.split())
                    return
                self._held.append(frame)
                return
        await self.push_frame(frame, direction)

    async def _release(self) -> None:
        if self._dropped_words:
            # Words only: the pickup is still the callee's speech.
            logger.info(
                "greeting hold dropped %d word(s) spoken before the greeting on an outbound call",
                self._dropped_words,
            )
            self._dropped_words = 0
        held, self._held = self._held, []
        text = " ".join(f.text.strip() for f in held if f.text.strip())
        if not text:
            return
        last = held[-1]
        # No synthetic VAD. An empty Smart Turn buffer returns INCOMPLETE and
        # the turn waits out user_turn_stop_timeout. The hold_replay marker
        # opens the turn; Pipecat's no-VAD + finalized=True path closes it.
        replay = TranscriptionFrame(
            text=text,
            user_id=last.user_id,
            timestamp=last.timestamp,
            language=last.language,
            finalized=True,
        )
        await self.push_frame(mark_hold_replay(replay))
