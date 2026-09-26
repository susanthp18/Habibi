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

import logging
import time
from collections import deque
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

#: Longest the bot is believed to hold the line in one utterance. The voice
#: overlay caps a turn at 45 spoken words, which is under 20 seconds at any
#: Azure rate; a nine-item product list ran 17. Past this, `_bot_speaking` is
#: treated as latched by a lost ``BotStoppedSpeakingFrame`` rather than true, so
#: the dead-air watchdog cannot be disabled for the rest of the call by one
#: dropped frame. Same judgement as the two limits above.
_MAX_BOT_SPEECH_SECONDS = 60.0

logger = logging.getLogger(__name__)

_WATCHED = (
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


class BotTurnStateObserver(BaseObserver):
    """Tracks whether the bot is mid-turn: generating, calling a tool, or speaking."""

    def __init__(
        self, on_first_speech: Any | None = None, on_transition: Any | None = None
    ) -> None:
        super().__init__()
        self._on_first_speech = on_first_speech
        self._on_transition = on_transition
        self._first_speech_emitted = False
        self._generating = False
        self._llm_started_at = 0.0
        self._tool_calls = 0
        self._active_tool_ids: set[str] = set()
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
        self._user_stopped_at = 0.0
        # When the caller connected. The origin for silence that precedes any
        # sound at all — see :meth:`silent_for`.
        self._call_started_at = 0.0
        self._bot_speaking = False
        self._bot_speaking_since = 0.0
        self._bot_has_spoken = False
        self.llm_response_starts = 0
        self._callee_spoke = False
        # Frames already seen. Pipecat calls an observer once per *hop*, not
        # once per frame -- a response start passes the TTS, the output
        # transport and the assistant aggregator, and each push is reported.
        # Pipecat's own observers skip repeats by frame id; this one did not,
        # so `llm_response_starts` counted hops, and the loop-trip watchdog
        # (budget 6 responses before the callee speaks) could close a real call
        # as a voicemail loop after a greeting and one nudge. Bounded: ids only
        # need to outlive one frame's trip through the pipeline.
        self._seen_ids: set[int] = set()
        self._seen_order: deque[int] = deque()

    def _first_sighting(self, frame: Any) -> bool:
        frame_id = getattr(frame, "id", None)
        if frame_id is None:
            return True
        if frame_id in self._seen_ids:
            return False
        self._seen_ids.add(frame_id)
        self._seen_order.append(frame_id)
        if len(self._seen_order) > 2048:
            self._seen_ids.discard(self._seen_order.popleft())
        return True

    async def on_push_frame(self, data: FrameProcessed) -> None:
        frame = data.frame
        # Type first: audio frames arrive fifty times a second per hop and must
        # cost nothing here.
        if not isinstance(frame, _WATCHED) or not self._first_sighting(frame):
            return
        if isinstance(frame, LLMFullResponseStartFrame):
            self._generating = True
            self.llm_response_starts += 1
            self._touch()
            self._llm_started_at = self._last_activity
            self._trace("llm.response_start", response=self.llm_response_starts)
        elif isinstance(frame, LLMFullResponseEndFrame):
            self._generating = False
            self._touch()
            self._trace(
                "llm.response_end",
                response=self.llm_response_starts,
                elapsed_ms=(
                    int((self._last_activity - self._llm_started_at) * 1000)
                    if self._llm_started_at
                    else None
                ),
                pending_tools=self._tool_calls,
            )
            self._llm_started_at = 0.0
        elif isinstance(frame, FunctionCallInProgressFrame):
            tool_id = str(getattr(frame, "tool_call_id", "") or "")
            if tool_id and tool_id in self._active_tool_ids:
                return
            if tool_id:
                self._active_tool_ids.add(tool_id)
            self._tool_calls += 1
            self._touch()
        elif isinstance(frame, FunctionCallResultFrame):
            # Never below zero: a result can arrive for a call that started
            # before this observer was attached.
            tool_id = str(getattr(frame, "tool_call_id", "") or "")
            if tool_id:
                if tool_id not in self._active_tool_ids:
                    return
                self._active_tool_ids.remove(tool_id)
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
            if self._generating or self._tool_calls or self._bot_speaking:
                self._trace(
                    "turn.interrupted",
                    response=self.llm_response_starts,
                    generating=1 if self._generating else 0,
                    pending_tools=self._tool_calls,
                    bot_speaking=1 if self._bot_speaking else 0,
                )
            self._generating = False
            self._llm_started_at = 0.0
            self._tool_calls = 0
            self._active_tool_ids.clear()
            self._touch()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            was_speaking = self._bot_speaking
            if not was_speaking:
                return
            self._bot_speaking = False
            self._touch()
            self._last_audio = time.monotonic()
            self._trace(
                "bot.speech_stop",
                response=self.llm_response_starts,
                speech_ms=(
                    int((self._last_audio - self._bot_speaking_since) * 1000)
                    if was_speaking and self._bot_speaking_since
                    else None
                ),
                paired=1 if was_speaking else 0,
            )
        elif isinstance(frame, UserStartedSpeakingFrame):
            if self._user_speaking:
                return
            bot_was_speaking = self._bot_speaking
            self._user_speaking = True
            self._user_speaking_since = time.monotonic()
            self._last_audio = time.monotonic()
            self._trace("caller.speech_start", bot_speaking=1 if bot_was_speaking else 0)
        elif isinstance(frame, UserStoppedSpeakingFrame):
            was_speaking = self._user_speaking
            if not was_speaking:
                return
            self._user_speaking = False
            self._user_stopped_at = time.monotonic()
            self._last_audio = time.monotonic()
            self._trace(
                "caller.speech_stop",
                speech_ms=(
                    int((self._user_stopped_at - self._user_speaking_since) * 1000)
                    if was_speaking and self._user_speaking_since
                    else None
                ),
                paired=1 if was_speaking else 0,
            )
        elif isinstance(frame, BotStartedSpeakingFrame):
            if self._bot_speaking:
                return
            self._bot_speaking = True
            self._bot_speaking_since = time.monotonic()
            self._bot_has_spoken = True
            self._last_audio = time.monotonic()
            self._trace(
                "bot.speech_start",
                response=self.llm_response_starts,
                since_caller_stop_ms=(
                    int((self._bot_speaking_since - self._user_stopped_at) * 1000)
                    if (
                        self._user_stopped_at
                        and self._bot_speaking_since >= self._user_stopped_at
                    )
                    else None
                ),
                generating=1 if self._generating else 0,
                pending_tools=self._tool_calls,
            )
            if not self._first_speech_emitted:
                self._first_speech_emitted = True
                cb = self._on_first_speech
                if cb is not None:
                    try:
                        cb()
                    except Exception as exc:
                        logger.warning(
                            "first speech callback failed error_type=%s",
                            type(exc).__name__,
                        )
        elif isinstance(frame, TranscriptionFrame):
            letters = sum(1 for ch in str(getattr(frame, "text", "") or "") if ch.isalpha())
            if letters >= 2:
                self._callee_spoke = True

    def _trace(self, name: str, **fields: Any) -> None:
        if self._on_transition is None:
            return
        try:
            self._on_transition(name, **fields)
        except Exception as exc:
            logger.warning(
                "voice turn trace failed event=%s error_type=%s",
                name,
                type(exc).__name__,
            )

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

        And 0.0 while the *bot* is mid-utterance, for the same reason from the
        other side. ``_last_audio`` is stamped when the bot starts speaking, so a
        long turn aged into "silence" while it was still playing: on
        VS-8C1B760F1B a 17-second balance statement and a 17-second product list
        each tripped the watchdog at 14s, which then asked the idle ladder to
        nudge once a second until the caller spoke. The ladder refused only
        because the bot's last sentence happened to end in a question.
        """
        if self._user_speaking and not self._user_turn_is_stale():
            return 0.0
        if self._bot_speaking and not self._bot_speech_is_stale():
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

    def _bot_speech_is_stale(self) -> bool:
        """Has ``_bot_speaking`` been stuck on beyond any real utterance?

        A dropped ``BotStoppedSpeakingFrame`` must not switch the watchdog off
        for the rest of the call. Past the limit, trust the clock over the flag.
        """
        if not self._bot_speaking_since:
            return False
        return (time.monotonic() - self._bot_speaking_since) > _MAX_BOT_SPEECH_SECONDS

    def caller_waiting_for(self) -> float:
        """Seconds since the caller stopped talking with no bot audio since.

        What the caller actually experiences as a slow reply, independent of
        which stage is slow. 0.0 while they are talking, once the bot has
        started answering, and before they have said anything at all.
        """
        if self._user_speaking or not self._user_stopped_at:
            return 0.0
        if self._bot_speaking_since >= self._user_stopped_at:
            return 0.0
        return time.monotonic() - self._user_stopped_at

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
