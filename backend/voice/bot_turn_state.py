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

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    FunctionCallInProgressFrame,
    FunctionCallResultFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
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


class BotTurnStateObserver(BaseObserver):
    """Tracks whether the bot is mid-turn: generating, calling a tool, or speaking."""

    def __init__(self) -> None:
        super().__init__()
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

    async def on_push_frame(self, data: FrameProcessed) -> None:
        frame = data.frame
        if isinstance(frame, LLMFullResponseStartFrame):
            self._generating = True
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
        elif isinstance(frame, BotStoppedSpeakingFrame):
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
            self._last_audio = time.monotonic()

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
            return True
        if not self._last_activity:
            return False
        return (time.monotonic() - self._last_activity) < grace_seconds
