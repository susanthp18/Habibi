"""Turn-aware coordination for immutable persisted transcript events.

The transcript text, speech timing, and logical turn lifecycle are produced by
different parts of the pipeline and can arrive in either order. This module is
the single place where those facts are joined. It emits a transcript event only
after the owning logical turn has ended (or during a final flush), and never
mutates an event after it has been appended to the logs buffer.

Each assistant generation is one event. Its turn and node are recorded when it
starts, not inferred when its text arrives: by then the user may have
interrupted into a new turn, or a tool may have moved the call to another node
(run 90 / Codex review).
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from api.services.pipecat.realtime_feedback_events import (
    build_bot_text_event,
    build_user_transcription_event,
)

if TYPE_CHECKING:
    from api.services.pipecat.in_memory_buffers import InMemoryLogsBuffer
    from pipecat.observers.turn_tracking_observer import TurnTrackingObserver


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass
class _TranscriptSide:
    text: str | None = None
    transcript_timestamp: str | None = None
    event_timestamp: str | None = None
    speech_start_timestamp: str | None = None
    speech_end_timestamp: str | None = None
    speaking: bool = False
    emitted: bool = False
    node_id: str | None = None
    node_name: str | None = None
    language: str | None = None


@dataclass
class _Generation:
    """One assistant generation: its owner, fixed when it started."""

    turn_id: int
    node_id: str | None
    node_name: str | None
    text: str | None = None
    started: str | None = None
    end_timestamp: str | None = None
    event_timestamp: str | None = None
    emitted: bool = False


@dataclass
class _TurnTranscriptState:
    turn_id: int
    ended: bool = False
    interrupted: bool = False
    user: _TranscriptSide = field(default_factory=_TranscriptSide)
    #: The bot's speech intervals in this turn, [start, end or None].
    bot_speech: list[list[str | None]] = field(default_factory=list)
    bot_speaking: bool = False
    generations: list[_Generation] = field(default_factory=list)


class TranscriptLogCoordinator:
    """Join turn, transcript, and speech facts before appending log events."""

    def __init__(self, logs_buffer: "InMemoryLogsBuffer"):
        self._logs_buffer = logs_buffer
        self._states: dict[int, _TurnTranscriptState] = {}
        self._active_turn_id: int | None = None
        # The newest turn the turn tracker has started. A generation belongs
        # to it: the tracker files bot speech outside an active turn under
        # this number too.
        self._latest_turn_id: int | None = None
        self._open_generation: _Generation | None = None
        self._lock = asyncio.Lock()

    def attach_turn_tracking_observer(self, observer: "TurnTrackingObserver") -> None:
        """Subscribe to the canonical turn owner's correlated lifecycle events."""

        @observer.event_handler("on_turn_started")
        async def on_turn_started(_observer, turn_number: int):
            await self.record_turn_started(turn_number)

        @observer.event_handler("on_turn_ended")
        async def on_turn_ended(
            _observer,
            turn_number: int,
            _duration: float,
            was_interrupted: bool,
        ):
            await self.record_turn_ended(turn_number, interrupted=was_interrupted)

        @observer.event_handler("on_user_speech_started_for_turn")
        async def on_user_speech_started_for_turn(_observer, turn_number: int, _data):
            callback_timestamp = _now_iso()
            await self.record_user_started_speaking(turn_number, callback_timestamp)

        @observer.event_handler("on_user_speech_stopped_for_turn")
        async def on_user_speech_stopped_for_turn(_observer, turn_number: int, _data):
            callback_timestamp = _now_iso()
            await self.record_user_stopped_speaking(turn_number, callback_timestamp)

        @observer.event_handler("on_bot_started_speaking")
        async def on_bot_started_speaking(_observer, turn_number: int, _data):
            await self.record_bot_started_speaking(turn_number)

        @observer.event_handler("on_bot_stopped_speaking")
        async def on_bot_stopped_speaking(_observer, turn_number: int, _data):
            await self.record_bot_stopped_speaking(turn_number)

    def _state(self, turn_id: int) -> _TurnTranscriptState:
        state = self._states.get(turn_id)
        if state is None:
            state = _TurnTranscriptState(turn_id=turn_id)
            self._states[turn_id] = state
        return state

    async def record_turn_started(self, turn_id: int) -> None:
        async with self._lock:
            self._state(turn_id)
            if self._latest_turn_id is None or turn_id > self._latest_turn_id:
                self._latest_turn_id = turn_id
            if self._active_turn_id is None or turn_id >= self._active_turn_id:
                self._active_turn_id = turn_id
                self._logs_buffer.set_current_turn(turn_id)

    async def record_turn_ended(self, turn_id: int, *, interrupted: bool) -> None:
        async with self._lock:
            state = self._state(turn_id)
            state.ended = True
            state.interrupted = interrupted
            if self._active_turn_id == turn_id:
                self._active_turn_id = None
            await self._emit_ready_sides(state)

    async def record_user_started_speaking(
        self, turn_id: int, timestamp: str | None = None
    ) -> None:
        async with self._lock:
            state = self._state(turn_id)
            side = state.user
            previous_start = side.speech_start_timestamp
            candidate_start = timestamp or _now_iso()
            side.speech_start_timestamp = (
                min(previous_start, candidate_start)
                if previous_start is not None
                else candidate_start
            )
            side.speaking = True

    async def record_user_stopped_speaking(
        self, turn_id: int, timestamp: str | None = None
    ) -> None:
        async with self._lock:
            side = self._state(turn_id).user
            previous_end = side.speech_end_timestamp
            candidate_end = timestamp or _now_iso()
            side.speech_end_timestamp = (
                max(previous_end, candidate_end)
                if previous_end is not None
                else candidate_end
            )
            side.speaking = False

    async def record_bot_started_speaking(
        self, turn_id: int, timestamp: str | None = None
    ) -> None:
        async with self._lock:
            state = self._state(turn_id)
            state.bot_speech.append([timestamp or _now_iso(), None])
            state.bot_speaking = True

    async def record_bot_stopped_speaking(
        self, turn_id: int, timestamp: str | None = None
    ) -> None:
        async with self._lock:
            state = self._state(turn_id)
            if state.bot_speech and state.bot_speech[-1][1] is None:
                state.bot_speech[-1][1] = timestamp or _now_iso()
            state.bot_speaking = False
            await self._emit_ready_sides(state)

    async def record_user_transcript(
        self,
        *,
        text: str,
        timestamp: str | None,
        end_timestamp: str | None = None,
        event_timestamp: str | None = None,
        language: str | None = None,
    ) -> None:
        async with self._lock:
            state = self._select_user_turn()
            side = state.user
            if language:
                side.language = language
            first_text = side.text is None
            side.text = text if first_text else f"{side.text}\n{text}"
            if first_text:
                side.transcript_timestamp = timestamp
                self._capture_node(side)
            side.event_timestamp = event_timestamp or _now_iso()
            if end_timestamp and not side.speech_end_timestamp:
                side.speech_end_timestamp = end_timestamp
            await self._emit_ready_sides(state)

    def record_generation_started(self) -> None:
        """An assistant generation started: fix its turn and node now.

        Synchronous, so it runs inline at the aggregator's boundary; nothing
        here awaits, so it cannot interleave with a lock holder.
        """
        self._open_generation = self._new_generation()

    async def record_assistant_transcript(
        self,
        *,
        text: str,
        timestamp: str | None,
        end_timestamp: str | None = None,
        event_timestamp: str | None = None,
    ) -> None:
        """The text of the open generation; ``timestamp`` is when it started."""
        async with self._lock:
            generation = self._open_generation or self._new_generation()
            self._open_generation = None
            generation.text = text
            generation.started = timestamp or generation.started
            generation.end_timestamp = end_timestamp
            generation.event_timestamp = event_timestamp or _now_iso()
            await self._emit_ready_sides(self._state(generation.turn_id))

    def _new_generation(self) -> _Generation:
        # Filed with its turn at once: a later generation's start bounds the
        # speech this one can own, even before this one's text arrives.
        generation = _Generation(
            turn_id=self._latest_turn_id or 1,
            node_id=self._logs_buffer.current_node_id,
            node_name=self._logs_buffer.current_node_name,
            started=_now_iso(),
        )
        self._state(generation.turn_id).generations.append(generation)
        return generation

    def _select_user_turn(self) -> _TurnTranscriptState:
        # Words said in the active turn belong to it, appended to any already
        # there. A turn whose speech the recognizer returned empty keeps no
        # claim on later text: it would be back-dated to that turn's start.
        if self._active_turn_id is not None:
            return self._state(self._active_turn_id)
        candidates = [
            state
            for state in self._states.values()
            if state.user.speech_start_timestamp and state.user.text is None
        ]
        if candidates:
            return max(candidates, key=lambda state: state.turn_id)
        if self._states:
            return max(self._states.values(), key=lambda state: state.turn_id)
        return self._state(1)

    def _capture_node(self, side: _TranscriptSide) -> None:
        side.node_id = self._logs_buffer.current_node_id
        side.node_name = self._logs_buffer.current_node_name

    async def _emit_ready_sides(self, state: _TurnTranscriptState) -> None:
        if not state.ended:
            return
        await self._emit_user(state)
        if not state.bot_speaking:
            for generation in state.generations:
                await self._emit_generation(state, generation)

    async def _emit_user(self, state: _TurnTranscriptState) -> None:
        side = state.user
        if side.emitted or not side.text:
            return
        event = build_user_transcription_event(
            text=side.text,
            final=True,
            timestamp=side.speech_start_timestamp or side.transcript_timestamp,
            end_timestamp=side.speech_end_timestamp,
            language=side.language,
        )
        await self._append(state, side, event)

    async def _emit_generation(
        self, state: _TurnTranscriptState, generation: _Generation
    ) -> None:
        if generation.emitted or not generation.text:
            return
        # Its speech is every interval of the turn that started after it did
        # and before the next generation did; a reply can pause mid-sentence
        # (Codex review). Speech before the turn's first generation is its.
        # The clocks are the same (_now_iso / pipecat time_now_iso8601), so
        # the ISO strings compare as text. Unspoken (cut off first): its start.
        speech = [
            interval
            for interval in state.bot_speech
            if self._speaker(state, interval) is generation
        ]
        event = build_bot_text_event(
            text=generation.text,
            timestamp=speech[0][0] if speech else generation.started,
            end_timestamp=(speech[-1][1] if speech else None)
            or generation.end_timestamp,
        )
        await self._logs_buffer.append(
            event,
            timestamp=generation.event_timestamp,
            turn=state.turn_id,
            node_id=generation.node_id,
            node_name=generation.node_name,
            use_current_node=False,
        )
        generation.emitted = True

    @staticmethod
    def _speaker(
        state: _TurnTranscriptState, interval: list[str | None]
    ) -> _Generation | None:
        speaker = state.generations[0] if state.generations else None
        for generation in state.generations:
            if (generation.started or "") <= interval[0]:
                speaker = generation
        return speaker

    async def _append(
        self, state: _TurnTranscriptState, side: _TranscriptSide, event: dict
    ) -> None:
        await self._logs_buffer.append(
            event,
            timestamp=side.event_timestamp,
            turn=state.turn_id,
            node_id=side.node_id,
            node_name=side.node_name,
            use_current_node=False,
        )
        side.emitted = True

    async def flush(self) -> None:
        """Emit any remaining transcript text without inventing missing timing."""
        async with self._lock:
            for state in sorted(self._states.values(), key=lambda item: item.turn_id):
                state.ended = True
                state.user.speaking = False
                state.bot_speaking = False
                await self._emit_ready_sides(state)
