"""Whether a bot turn is currently in flight.

The idle ladder asks "has the caller gone quiet?", and answered it purely from
the user aggregator's own timer — which counts silence, not *whose* silence.
On call VS-9BC3DD9725 a node transition plus a 32-message context summarisation
took six seconds; the caller was quiet for all of it because the bot was
thinking, the idle timer reached its threshold, and the nudge fired a second
generation on top of the one already running. The caller heard the same
promise-to-pay confirmation twice, two seconds apart.

An earlier attempt treated this as a wording problem — the nudge prompt still
carries "do NOT restate, re-summarise or rephrase anything you have already
told them", added after the same duplicate was seen on VS-6B252E0479. Wording
cannot fix it: the second turn should never have been requested at all.

This observer answers the question the idle check actually needs to ask. It is
read-only and cannot affect the pipeline: an observer sees frames, it does not
consume or alter them.
"""

from __future__ import annotations

import time
from typing import Any

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver, FrameProcessed

#: Longest a single caller utterance is believed to run. Beyond this the
#: "user is speaking" flag is treated as stuck rather than true — see
#: :meth:`BotTurnStateObserver._user_turn_is_stale`. Generous on purpose: a
#: caller reading out a long reference number is a real turn, a flag latched on
#: by a dropped frame is not, and only the second one should be overridden.
_MAX_USER_TURN_SECONDS = 120.0

#: Longest a bot turn is believed to stay in flight. Past this, `_generating` or
#: an outstanding tool call is treated as latched rather than live — the same
#: judgement :data:`_MAX_USER_TURN_SECONDS` makes for the caller, and for the
#: same reason: a stuck flag and a real turn look identical from a single event.
#:
#: The interruption handler below is the fix for the latch we actually saw. This
#: is the backstop for the ones we have not: whatever strands a turn, the idle
#: ladder must not stay muted for the rest of the call because of it. Generous
#: on purpose — a slow tool behind a summarisation is a real turn, and only a
#: turn that has plainly stopped progressing should be overridden.
_MAX_BOT_TURN_SECONDS = 30.0


class BotTurnStateObserver(BaseObserver):
    """Tracks whether the bot is mid-turn: generating, calling a tool, or speaking."""

    def __init__(self, on_first_speech: Any | None = None) -> None:
        super().__init__()
        self._on_first_speech = on_first_speech
        self._first_speech_emitted = False
        self._generating = False
        self._tool_calls = 0
        self._last_activity = 0.0
        # Audio only — deliberately separate from _last_activity, which also
        # counts the bot thinking. "Has anyone made a sound?" and "does the bot
        # owe a turn?" are different questions and one timestamp cannot answer
        # both.
        self._last_audio = 0.0
        # Is the caller talking *right now*? Start and stop are single events,
        # so a timestamp alone says nothing about the seconds between them —
        # and a caller mid-sentence looks exactly like a caller who has gone
        # quiet. See :meth:`silent_for`.
        self._user_speaking = False
        self._user_speaking_since = 0.0
        # When the caller connected. The origin for silence that precedes any
        # sound at all — see :meth:`silent_for`.
        self._call_started_at = 0.0
        self._bot_speaking = False
        self._bot_has_spoken = False
        self.llm_response_starts = 0
        self._callee_spoke = False

    async def on_push_frame(self, data: FrameProcessed) -> None:
        frame = data.frame
        if isinstance(frame, LLMFullResponseStartFrame):
            self._generating = True
            self.llm_response_starts += 1
            self._touch()
        elif isinstance(frame, LLMFullResponseEndFrame):
            self._generating = False
            self._touch()
        elif isinstance(frame, FunctionCallInProgressFrame):
            self._tool_calls += 1
            self._touch()
        elif isinstance(frame, FunctionCallResultFrame):
            # Never below zero: a result can arrive for a call that started
            # before this observer was attached.
            self._tool_calls = max(0, self._tool_calls - 1)
            self._touch()
        elif isinstance(frame, InterruptionFrame):
            # A barge-in ends the turn it interrupted. Nothing else does.
            #
            # `_generating` is lowered by LLMFullResponseEndFrame and
            # `_tool_calls` by FunctionCallResultFrame — neither of which is
            # guaranteed to arrive once the caller talks over the bot: the
            # response is cancelled where it stands. Both counters then latch,
            # `busy()` answers True forever, and the idle ladder — which asks
            # `busy()` before every nudge — goes quiet for the rest of the call.
            #
            # That is what happened on VS-F93E3B2133. The caller barged in 326ms
            # into "Great, let me verify that quick…", the cancelled response
            # never re-ran, and the dead-air watchdog that would have re-engaged
            # them was suppressed on every tick. They heard 30 seconds of
            # silence and hung up.
            #
            # After an interruption the bot owes nothing: whatever it was going
            # to say has been thrown away.
            self._generating = False
            self._tool_calls = 0
            self._touch()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            self._touch()
            self._last_audio = time.monotonic()
        elif isinstance(frame, UserStartedSpeakingFrame):
            self._user_speaking = True
            self._user_speaking_since = time.monotonic()
            self._last_audio = time.monotonic()
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._user_speaking = False
            self._last_audio = time.monotonic()
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            self._bot_has_spoken = True
            self._last_audio = time.monotonic()
            if not self._first_speech_emitted:
                self._first_speech_emitted = True
                cb = self._on_first_speech
                if cb is not None:
                    try:
                        cb()
                    except Exception:
                        pass
        elif isinstance(frame, TranscriptionFrame):
            letters = sum(1 for ch in str(getattr(frame, "text", "") or "") if ch.isalpha())
            if letters >= 2:
                self._callee_spoke = True

    def _touch(self) -> None:
        self._last_activity = time.monotonic()

    def silent_for(self) -> float:
        """Seconds since either side last made a sound.

        Pipecat's ``UserIdleController`` cannot answer this. It starts its timer
        on ``BotStoppedSpeakingFrame`` and re-arms nowhere else, so a turn where
        the bot never speaks — a transition into a listen-first node, a tool
        that resolved into no reply — leaves no timer running at all and the
        silence is unbounded. VS-92CDE3F088 sat mute for 24 seconds with the
        idle ladder configured and never logged a single strike.

        Before the first sound, silence is measured from the moment the call
        connected — not treated as zero. The original guard here returned 0.0
        whenever no audio had ever been seen, which made the single worst case
        the one case this could not detect: on VS-18FE21E37A the model called
        ``disclose_recording`` and emitted no text with it, so the greeting was
        never spoken, ``discover_intent`` listened, and the line stayed dead for
        77 seconds until the caller hung up. Nothing fired, because nothing had
        ever made a sound. A call that has connected and said nothing is the
        most broken kind of dead air, not the most innocent.

        Still 0.0 before :meth:`mark_call_started`, so an observer attached to
        no call is never "quiet".

        Also 0.0 while the caller is mid-utterance. Start and stop are single
        events and the seconds between them carry no frames, so measuring from
        ``_last_audio`` alone reports a caller who is *talking* as a caller who
        has gone quiet. On VS-EE7F739E11 the caller began speaking at 12:22:55,
        this returned 8.9s at 12:23:04, and the watchdog cut into a nine-second
        sentence with "Are you still there?" — the caller finished half a
        second later. Someone speaking is the opposite of silence.
        """
        if self._user_speaking and not self._user_turn_is_stale():
            return 0.0
        origin = max(self._last_audio, self._call_started_at)
        if not origin:
            return 0.0
        return time.monotonic() - origin

    def mark_call_started(self) -> None:
        """The caller is connected and the clock is running.

        Called from ``on_client_connected``. Without an origin, silence before
        the first sound is unmeasurable and therefore invisible.
        """
        self._call_started_at = time.monotonic()

    def _user_turn_is_stale(self) -> bool:
        """Has ``_user_speaking`` been stuck on beyond any real utterance?

        A dropped ``UserStoppedSpeakingFrame`` would otherwise latch the flag on
        and silently disable the watchdog for the rest of the call — the exact
        failure mode it exists to catch. Past this, trust the clock over the
        flag.
        """
        if not self._user_speaking_since:
            return False
        return (time.monotonic() - self._user_speaking_since) > _MAX_USER_TURN_SECONDS

    def busy(self, *, grace_seconds: float = 1.5) -> bool:
        """True while the bot owes the caller a turn.

        The grace period covers the gap between one stage finishing and the next
        starting — generation ends, TTS has not begun — which is a moment of
        silence that belongs to the bot, not the caller.
        """
        if self._generating or self._tool_calls > 0:
            # ...unless the turn has plainly stopped progressing. See
            # _MAX_BOT_TURN_SECONDS: a latched flag must not mute the idle
            # ladder for the rest of the call.
            if (
                self._last_activity
                and (time.monotonic() - self._last_activity) > _MAX_BOT_TURN_SECONDS
            ):
                return False
            return True
        if not self._last_activity:
            return False
        return (time.monotonic() - self._last_activity) < grace_seconds

    def speaking(self) -> bool:
        """True while TTS is in the ear, or the bot still owes that audio."""
        return self._bot_speaking or self.busy()

    def has_spoken(self) -> bool:
        """True after the first BotStartedSpeakingFrame of the call."""
        return self._bot_has_spoken

    def callee_spoke(self) -> bool:
        """True after a transcription with real words, not a ringtone blip."""
        return self._callee_spoke
