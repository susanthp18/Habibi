import asyncio
import re
from collections import defaultdict
from types import SimpleNamespace

import pytest
from pipecat.frames.frames import (
    ErrorFrame,
    TranscriptionFrame,
    TTSTextFrame,
)
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    AssistantTurnStoppedMessage,
    LLMAssistantAggregator,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import TransportParams

from api.services.pipecat.in_memory_buffers import InMemoryLogsBuffer
from api.services.pipecat.realtime_feedback_observer import (
    RealtimeFeedbackObserver,
    register_turn_log_handlers,
)
from api.services.pipecat.transcript_log_coordinator import TranscriptLogCoordinator


class _FakeAggregator:
    def __init__(self):
        self.handlers = {}
        self._event_handlers = defaultdict(lambda: SimpleNamespace(is_sync=False))

    def event_handler(self, event_name):
        def decorator(handler):
            self.handlers[event_name] = handler
            return handler

        return decorator


def _frame_pushed(frame, direction, *, source=None):
    return FramePushed(
        source=source or SimpleNamespace(),
        destination=SimpleNamespace(),
        frame=frame,
        direction=direction,
        timestamp=0,
    )


@pytest.mark.asyncio
async def test_observer_streams_upstream_only_transcription_frames():
    messages = []

    async def ws_sender(message):
        messages.append(message)

    observer = RealtimeFeedbackObserver(ws_sender=ws_sender)
    frame = TranscriptionFrame(
        "Hi there",
        user_id="user-1",
        timestamp="2026-01-01T00:00:00+00:00",
    )

    await observer.on_push_frame(_frame_pushed(frame, FrameDirection.UPSTREAM))

    assert messages == [
        {
            "type": "rtf-user-transcription",
            "payload": {
                "text": "Hi there",
                "final": True,
                "timestamp": "2026-01-01T00:00:00+00:00",
                "user_id": "user-1",
            },
        }
    ]


@pytest.mark.asyncio
async def test_observer_ignores_upstream_broadcast_transcription_sibling():
    messages = []

    async def ws_sender(message):
        messages.append(message)

    observer = RealtimeFeedbackObserver(ws_sender=ws_sender)
    frame = TranscriptionFrame(
        "Hi there",
        user_id="user-1",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    frame.broadcast_sibling_id = 1234

    await observer.on_push_frame(_frame_pushed(frame, FrameDirection.UPSTREAM))

    assert messages == []


@pytest.mark.asyncio
async def test_observer_waits_for_tts_text_from_output_transport():
    messages = []

    async def ws_sender(message):
        messages.append(message)

    observer = RealtimeFeedbackObserver(ws_sender=ws_sender)
    frame = TTSTextFrame("Hello", aggregated_by="word")
    frame.pts = 123

    await observer.on_push_frame(_frame_pushed(frame, FrameDirection.DOWNSTREAM))
    assert messages == []

    output_transport = BaseOutputTransport(TransportParams())
    await observer.on_push_frame(
        _frame_pushed(
            frame,
            FrameDirection.DOWNSTREAM,
            source=output_transport,
        )
    )

    assert messages == [
        {
            "type": "rtf-bot-text",
            "payload": {"text": "Hello"},
        }
    ]


@pytest.mark.asyncio
async def test_observer_classifies_each_distinct_error_frame(monkeypatch):
    messages = []
    failures = []

    async def ws_sender(message):
        messages.append(message)

    def capture_failure(failure, **context):
        failures.append((failure, context))

    monkeypatch.setattr(
        "api.services.pipecat.realtime_feedback_observer.log_failure",
        capture_failure,
    )
    processor = type("DeepgramSTTService", (), {})()
    observer = RealtimeFeedbackObserver(ws_sender=ws_sender)

    first = ErrorFrame(
        "Authentication failed",
        processor=processor,
        exception=type("ProviderError", (Exception,), {"status_code": 401})(
            "Authentication failed"
        ),
    )
    repeat = ErrorFrame(
        "Authentication failed again",
        fatal=True,
        processor=processor,
        exception=type("ProviderError", (Exception,), {"status_code": 401})(
            "Authentication failed again"
        ),
    )

    await observer.on_push_frame(_frame_pushed(first, FrameDirection.UPSTREAM))
    await observer.on_push_frame(_frame_pushed(repeat, FrameDirection.UPSTREAM))
    await observer.on_push_frame(_frame_pushed(first, FrameDirection.DOWNSTREAM))

    # Distinct attempts are retained; re-observing the identical frame is not.
    assert len(messages) == 2
    assert len(failures) == 2
    assert failures[0][0].source.value == "stt"
    assert failures[0][0].type.value == "config_error"
    assert failures[0][0].error_owner.value == "user"
    assert failures[0][0].provider == "deepgram"
    assert failures[0][0].code == "deepgram-401"
    assert failures[0][1] == {"fatal": False}
    assert failures[1][1] == {"fatal": True}


@pytest.mark.asyncio
async def test_observer_treats_unusable_processor_error_as_terminal(monkeypatch):
    messages = []
    failures = []

    async def ws_sender(message):
        messages.append(message)

    monkeypatch.setattr(
        "api.services.pipecat.realtime_feedback_observer.log_failure",
        lambda failure, **context: failures.append((failure, context)),
    )
    processor = BaseOutputTransport(TransportParams())
    await processor.set_usable(False)
    observer = RealtimeFeedbackObserver(ws_sender=ws_sender)

    frame = ErrorFrame("Transport can no longer write", processor=processor)
    await observer.on_push_frame(_frame_pushed(frame, FrameDirection.UPSTREAM))

    assert failures[0][1] == {"fatal": True}
    assert messages[0]["payload"]["fatal"] is True


async def _started(assistant_aggregator):
    """The aggregator's generation start (absent before it was handled)."""
    handler = assistant_aggregator.handlers.get("on_assistant_turn_started")
    if handler is not None:
        await handler(assistant_aggregator)


async def _assistant_text(assistant_aggregator, content, generation_started):
    await assistant_aggregator.handlers["on_assistant_turn_stopped"](
        assistant_aggregator,
        SimpleNamespace(content=content, timestamp=generation_started),
    )


@pytest.mark.asyncio
async def test_turn_log_handlers_persist_user_message_added_events():
    logs_buffer = InMemoryLogsBuffer(workflow_run_id=123)
    coordinator = TranscriptLogCoordinator(logs_buffer)
    user_aggregator = _FakeAggregator()
    assistant_aggregator = _FakeAggregator()

    register_turn_log_handlers(coordinator, user_aggregator, assistant_aggregator)

    assert "on_user_turn_message_added" in user_aggregator.handlers
    assert "on_user_turn_stopped" not in user_aggregator.handlers

    logs_buffer.set_current_node("node-a", "Node A")
    await user_aggregator.handlers["on_user_turn_message_added"](
        user_aggregator,
        SimpleNamespace(
            content="Hi there",
            timestamp="2026-01-01T00:00:00+00:00",
        ),
    )
    logs_buffer.set_current_node("node-b", "Node B")
    await coordinator.record_turn_ended(1, interrupted=False)

    events = logs_buffer.get_events()
    assert len(events) == 1
    assert events[0]["type"] == "rtf-user-transcription"
    assert events[0]["payload"] == {
        "text": "Hi there",
        "final": True,
        "timestamp": "2026-01-01T00:00:00+00:00",
    }
    assert events[0]["turn"] == 1
    assert events[0]["node_id"] == "node-a"
    assert events[0]["node_name"] == "Node A"


@pytest.mark.asyncio
async def test_coordinator_attaches_speaking_intervals_to_logged_transcript_events():
    logs_buffer = InMemoryLogsBuffer(workflow_run_id=123)
    coordinator = TranscriptLogCoordinator(logs_buffer)

    user_aggregator = _FakeAggregator()
    assistant_aggregator = _FakeAggregator()
    register_turn_log_handlers(coordinator, user_aggregator, assistant_aggregator)

    await coordinator.record_turn_started(1)
    await coordinator.record_user_started_speaking(1)
    await coordinator.record_user_stopped_speaking(1)
    await user_aggregator.handlers["on_user_turn_message_added"](
        user_aggregator,
        SimpleNamespace(
            content="January fifth",
            timestamp="aggregator-user-start",
        ),
    )

    await _started(assistant_aggregator)
    await coordinator.record_bot_started_speaking(1, "2026-01-01T00:00:01.000+00:00")
    await _assistant_text(assistant_aggregator, "Thank you", "2026-01-01T00:00:00.000+00:00")
    await coordinator.record_bot_stopped_speaking(1, "2026-01-01T00:00:02.000+00:00")
    await _started(assistant_aggregator)
    await coordinator.record_bot_started_speaking(1, "2026-01-01T00:00:03.000+00:00")
    await _assistant_text(
        assistant_aggregator, "You're welcome", "2026-01-01T00:00:02.500+00:00"
    )
    await coordinator.record_bot_stopped_speaking(1, "2026-01-01T00:00:04.000+00:00")
    await coordinator.record_turn_ended(1, interrupted=False)

    user_event, bot_event, second_bot_event = [
        event
        for event in logs_buffer.get_events()
        if event["type"] in {"rtf-user-transcription", "rtf-bot-text"}
    ]

    assert user_event["turn"] == 1
    assert bot_event["turn"] == 1
    assert user_event["payload"]["timestamp"] != "aggregator-user-start"
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00$",
        user_event["payload"]["timestamp"],
    )
    assert user_event["payload"]["end_timestamp"]
    assert bot_event["payload"]["timestamp"] != "2026-01-01T00:00:00.000+00:00"
    assert bot_event["payload"]["text"] == "Thank you"
    assert second_bot_event["payload"]["text"] == "You're welcome"
    assert (bot_event["turn"], second_bot_event["turn"]) == (1, 1)
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00$",
        bot_event["payload"]["timestamp"],
    )
    assert bot_event["payload"]["end_timestamp"]
    assert second_bot_event["payload"]["timestamp"] >= bot_event["payload"]["end_timestamp"]


@pytest.mark.asyncio
async def test_user_speaking_frames_define_full_multi_segment_turn_envelope():
    logs_buffer = InMemoryLogsBuffer(workflow_run_id=123)
    coordinator = TranscriptLogCoordinator(logs_buffer)
    user_aggregator = _FakeAggregator()
    assistant_aggregator = _FakeAggregator()
    register_turn_log_handlers(coordinator, user_aggregator, assistant_aggregator)

    await coordinator.record_turn_started(2)
    await coordinator.record_user_started_speaking(2, "2026-07-14T09:55:22.132+00:00")
    await coordinator.record_user_stopped_speaking(2, "2026-07-14T09:55:27.713+00:00")
    await user_aggregator.handlers["on_user_turn_message_added"](
        user_aggregator,
        SimpleNamespace(
            content="Yeah, yeah. I'm just like,",
            timestamp="2026-07-14T09:55:22.132+00:00",
        ),
    )

    # The user resumes before the bot speaks, so this remains canonical Turn 2.
    await coordinator.record_user_started_speaking(2, "2026-07-14T09:55:28.393+00:00")
    await coordinator.record_user_stopped_speaking(2, "2026-07-14T09:55:29.994+00:00")
    await user_aggregator.handlers["on_user_turn_message_added"](
        user_aggregator,
        SimpleNamespace(
            content="what to get",
            timestamp="2026-07-14T09:55:28.393+00:00",
        ),
    )
    await coordinator.record_turn_ended(2, interrupted=False)

    user_event = logs_buffer.get_events()[0]
    assert user_event["turn"] == 2
    assert user_event["payload"] == {
        "text": "Yeah, yeah. I'm just like,\nwhat to get",
        "final": True,
        "timestamp": "2026-07-14T09:55:22.132+00:00",
        "end_timestamp": "2026-07-14T09:55:29.994+00:00",
    }


@pytest.mark.asyncio
async def test_appended_events_are_not_mutated_by_later_turn_activity():
    logs_buffer = InMemoryLogsBuffer(workflow_run_id=123)
    first = {"type": "rtf-bot-text", "payload": {"text": "First"}}

    await logs_buffer.append(first, turn=1)
    first["payload"]["text"] = "Mutated outside the buffer"
    logs_buffer.set_current_turn(2)
    await logs_buffer.append({"type": "rtf-bot-text", "payload": {"text": "Second"}})

    assert logs_buffer.get_events()[0]["payload"] == {"text": "First"}


@pytest.mark.asyncio
async def test_stored_events_are_sorted_by_event_timestamp_not_payload_timestamp():
    logs_buffer = InMemoryLogsBuffer(workflow_run_id=123)

    await logs_buffer.append(
        {
            "type": "rtf-bot-text",
            "payload": {"text": "Speech started first", "timestamp": "payload-1"},
        },
        timestamp="2026-01-01T00:00:02.000+00:00",
        turn=1,
    )
    await logs_buffer.append(
        {
            "type": "rtf-node-transition",
            "payload": {"timestamp": "payload-2"},
        },
        timestamp="2026-01-01T00:00:01.000+00:00",
        turn=1,
    )

    assert [event["timestamp"] for event in logs_buffer.get_events()] == [
        "2026-01-01T00:00:01.000+00:00",
        "2026-01-01T00:00:02.000+00:00",
    ]


@pytest.mark.asyncio
async def test_completed_user_turn_does_not_reuse_speaking_frame_timestamps():
    logs_buffer = InMemoryLogsBuffer(workflow_run_id=123)
    coordinator = TranscriptLogCoordinator(logs_buffer)

    await coordinator.record_turn_started(1)
    await coordinator.record_user_started_speaking(1, "2026-01-01T00:00:01.000+00:00")
    await coordinator.record_user_stopped_speaking(1, "2026-01-01T00:00:02.000+00:00")
    await coordinator.record_user_transcript(text="First", timestamp=None)
    await coordinator.record_turn_ended(1, interrupted=False)

    await coordinator.record_turn_started(2)
    await coordinator.record_user_started_speaking(2, "2026-01-01T00:00:10.000+00:00")
    await coordinator.record_user_stopped_speaking(2, "2026-01-01T00:00:12.000+00:00")
    await coordinator.record_user_transcript(text="Second", timestamp=None)
    await coordinator.record_turn_ended(2, interrupted=False)

    second_event = logs_buffer.get_events()[-1]
    assert second_event["payload"]["timestamp"] == "2026-01-01T00:00:10.000+00:00"
    assert second_event["payload"]["end_timestamp"] == "2026-01-01T00:00:12.000+00:00"


@pytest.mark.asyncio
async def test_later_words_are_not_backdated_to_an_unheard_turn():
    """Run 58: the recognizer returned nothing for turn 2's "Yes."; "Correct,
    correct." said two minutes later in turn 9 was logged as turn 2's."""
    logs_buffer = InMemoryLogsBuffer(workflow_run_id=58)
    coordinator = TranscriptLogCoordinator(logs_buffer)

    await coordinator.record_turn_started(2)
    await coordinator.record_user_started_speaking(2, "2026-09-28T15:43:34.046+00:00")
    await coordinator.record_user_stopped_speaking(2, "2026-09-28T15:43:34.700+00:00")
    await coordinator.record_turn_ended(2, interrupted=False)

    await coordinator.record_turn_started(9)
    await coordinator.record_user_started_speaking(9, "2026-09-28T15:45:35.000+00:00")
    await coordinator.record_user_transcript(text="Yeah, correct.", timestamp=None)
    await coordinator.record_user_transcript(text="Correct, correct.", timestamp=None)
    await coordinator.record_turn_ended(9, interrupted=False)

    [event] = logs_buffer.get_events()
    assert event["turn"] == 9
    assert event["payload"]["text"] == "Yeah, correct.\nCorrect, correct."


@pytest.mark.asyncio
async def test_interrupted_bot_transcript_keeps_the_interrupted_turn_interval():
    logs_buffer = InMemoryLogsBuffer(workflow_run_id=2122)
    coordinator = TranscriptLogCoordinator(logs_buffer)

    await coordinator.record_turn_started(2)
    coordinator.record_generation_started()
    await coordinator.record_bot_started_speaking(2, "2026-07-14T13:33:02.254+00:00")

    # The user interrupts: logical Turn 2 ends and Turn 3 starts before the
    # output transport reports that Turn 2's audio has physically stopped.
    await coordinator.record_turn_ended(2, interrupted=True)
    await coordinator.record_turn_started(3)
    await coordinator.record_bot_stopped_speaking(2, "2026-07-14T13:33:03.817+00:00")
    await coordinator.record_assistant_transcript(
        text="A minivan, too easy,",
        # The aggregator's stamp: when the generation started.
        timestamp="2026-07-14T13:33:02.000+00:00",
        event_timestamp="2026-07-14T13:33:03.819+00:00",
    )

    [event] = logs_buffer.get_events()
    assert event["type"] == "rtf-bot-text"
    assert event["timestamp"] == "2026-07-14T13:33:03.819+00:00"
    assert event["turn"] == 2
    assert event["payload"] == {
        "text": "A minivan, too easy,",
        "timestamp": "2026-07-14T13:33:02.254+00:00",
        "end_timestamp": "2026-07-14T13:33:03.817+00:00",
    }

    await coordinator.record_bot_started_speaking(3, "2026-07-14T13:33:06.654+00:00")
    assert event["payload"]["timestamp"] == "2026-07-14T13:33:02.254+00:00"


async def _interrupted_empty_turn_12_then_turn_13(coordinator, assistant_aggregator):
    await coordinator.record_turn_started(12)
    await _started(assistant_aggregator)
    await coordinator.record_bot_started_speaking(12, "2026-09-30T10:00:01.000+00:00")
    await coordinator.record_turn_ended(12, interrupted=True)
    await coordinator.record_bot_stopped_speaking(12, "2026-09-30T10:00:01.500+00:00")
    await coordinator.record_turn_started(13)
    await coordinator.record_bot_started_speaking(13, "2026-09-30T10:00:05.000+00:00")


@pytest.mark.asyncio
async def test_later_reply_is_not_filed_under_an_earlier_empty_interrupted_turn():
    """Run 90: turn 12 was interrupted before its text arrived; turn 13's reply
    was then logged with turn 12's number and speech timing."""
    logs_buffer = InMemoryLogsBuffer(workflow_run_id=90)
    coordinator = TranscriptLogCoordinator(logs_buffer)
    user_aggregator = _FakeAggregator()
    assistant_aggregator = _FakeAggregator()
    register_turn_log_handlers(coordinator, user_aggregator, assistant_aggregator)

    await _interrupted_empty_turn_12_then_turn_13(coordinator, assistant_aggregator)
    await _started(assistant_aggregator)
    await assistant_aggregator.handlers["on_assistant_turn_stopped"](
        assistant_aggregator,
        SimpleNamespace(
            content="Turn thirteen reply",
            interrupted=False,
            timestamp="2026-09-30T10:00:04.000+00:00",
        ),
    )
    await coordinator.record_bot_stopped_speaking(13, "2026-09-30T10:00:07.000+00:00")
    await coordinator.record_turn_ended(13, interrupted=False)

    [event] = logs_buffer.get_events()
    assert event["turn"] == 13
    assert event["payload"]["timestamp"] == "2026-09-30T10:00:05.000+00:00"


@pytest.mark.asyncio
async def test_late_reply_still_reaches_its_own_interrupted_turn():
    logs_buffer = InMemoryLogsBuffer(workflow_run_id=90)
    coordinator = TranscriptLogCoordinator(logs_buffer)
    user_aggregator = _FakeAggregator()
    assistant_aggregator = _FakeAggregator()
    register_turn_log_handlers(coordinator, user_aggregator, assistant_aggregator)

    await _interrupted_empty_turn_12_then_turn_13(coordinator, assistant_aggregator)
    await assistant_aggregator.handlers["on_assistant_turn_stopped"](
        assistant_aggregator,
        SimpleNamespace(
            content="Turn twelve reply",
            interrupted=True,
            timestamp="2026-09-30T10:00:00.500+00:00",
        ),
    )

    [event] = logs_buffer.get_events()
    assert event["turn"] == 12
    assert event["payload"]["timestamp"] == "2026-09-30T10:00:01.000+00:00"


@pytest.mark.asyncio
async def test_late_reply_keeps_the_node_that_spoke_it():
    """Run 90 / Codex review: turn 12's late text was filed under the node
    current when the text arrived (turn 13's), not the node that spoke it."""
    logs_buffer = InMemoryLogsBuffer(workflow_run_id=90)
    coordinator = TranscriptLogCoordinator(logs_buffer)
    user_aggregator = _FakeAggregator()
    assistant_aggregator = _FakeAggregator()
    register_turn_log_handlers(coordinator, user_aggregator, assistant_aggregator)

    logs_buffer.set_current_node("node-a", "Node A")
    await coordinator.record_turn_started(12)
    await _started(assistant_aggregator)
    await coordinator.record_bot_started_speaking(12, "2026-09-30T10:00:01.000+00:00")
    await coordinator.record_turn_ended(12, interrupted=True)
    await coordinator.record_bot_stopped_speaking(12, "2026-09-30T10:00:01.500+00:00")
    logs_buffer.set_current_node("node-b", "Node B")
    await coordinator.record_turn_started(13)
    await _assistant_text(
        assistant_aggregator, "Turn twelve reply", "2026-09-30T10:00:00.500+00:00"
    )

    await _started(assistant_aggregator)
    await coordinator.record_bot_started_speaking(13, "2026-09-30T10:00:05.000+00:00")
    await _assistant_text(
        assistant_aggregator, "Turn thirteen reply", "2026-09-30T10:00:04.000+00:00"
    )
    await coordinator.record_bot_stopped_speaking(13, "2026-09-30T10:00:07.000+00:00")
    await coordinator.record_turn_ended(13, interrupted=False)

    assert [
        (event["turn"], event["node_id"], event["payload"]["text"])
        for event in logs_buffer.get_events()
    ] == [
        (12, "node-a", "Turn twelve reply"),
        (13, "node-b", "Turn thirteen reply"),
    ]


@pytest.mark.asyncio
async def test_second_generation_of_an_interrupted_turn_stays_with_that_turn():
    """Codex review: a tool-call round's second generation started after turn
    20's speech had begun, so its text was filed under turn 21."""
    logs_buffer = InMemoryLogsBuffer(workflow_run_id=90)
    coordinator = TranscriptLogCoordinator(logs_buffer)
    user_aggregator = _FakeAggregator()
    assistant_aggregator = _FakeAggregator()
    register_turn_log_handlers(coordinator, user_aggregator, assistant_aggregator)

    await coordinator.record_turn_started(20)
    await _started(assistant_aggregator)
    await coordinator.record_bot_started_speaking(20, "2026-09-30T10:00:10.000+00:00")
    await _assistant_text(
        assistant_aggregator, "Let me check that.", "2026-09-30T10:00:09.500+00:00"
    )
    # The tool runs in the pause; the second generation then speaks.
    await coordinator.record_bot_stopped_speaking(20, "2026-09-30T10:00:11.000+00:00")
    await _started(assistant_aggregator)
    await coordinator.record_bot_started_speaking(20, "2026-09-30T10:00:12.500+00:00")
    await coordinator.record_turn_ended(20, interrupted=True)
    await coordinator.record_turn_started(21)
    await coordinator.record_bot_stopped_speaking(20, "2026-09-30T10:00:13.000+00:00")
    await _assistant_text(
        assistant_aggregator, "Your payment is due.", "2026-09-30T10:00:12.000+00:00"
    )

    await _started(assistant_aggregator)
    await coordinator.record_bot_started_speaking(21, "2026-09-30T10:00:16.000+00:00")
    await _assistant_text(
        assistant_aggregator, "Turn twenty-one reply", "2026-09-30T10:00:15.500+00:00"
    )
    await coordinator.record_bot_stopped_speaking(21, "2026-09-30T10:00:17.000+00:00")
    await coordinator.record_turn_ended(21, interrupted=False)

    assert [
        (event["turn"], event["payload"]["text"], event["payload"]["timestamp"])
        for event in logs_buffer.get_events()
    ] == [
        (20, "Let me check that.", "2026-09-30T10:00:10.000+00:00"),
        (20, "Your payment is due.", "2026-09-30T10:00:12.500+00:00"),
        (21, "Turn twenty-one reply", "2026-09-30T10:00:16.000+00:00"),
    ]


@pytest.mark.asyncio
async def test_a_generation_started_after_an_interruption_belongs_to_the_new_turn():
    """Codex review: a generation that started before the interrupted turn's
    audio had physically stopped was filed under turn 1 instead of turn 2."""
    logs_buffer = InMemoryLogsBuffer(workflow_run_id=91)
    coordinator = TranscriptLogCoordinator(logs_buffer)
    user_aggregator = _FakeAggregator()
    assistant_aggregator = _FakeAggregator()
    register_turn_log_handlers(coordinator, user_aggregator, assistant_aggregator)

    await coordinator.record_turn_started(1)
    await _started(assistant_aggregator)
    await coordinator.record_bot_started_speaking(1, "2026-10-01T10:00:01.000+00:00")
    await coordinator.record_turn_ended(1, interrupted=True)
    await _assistant_text(assistant_aggregator, "Turn one, cut off", "2026-10-01T10:00:00.500+00:00")
    await coordinator.record_turn_started(2)
    await _started(assistant_aggregator)
    # Turn 1's audio stops only after turn 2's reply has started generating.
    await coordinator.record_bot_stopped_speaking(1, "2026-10-01T10:00:01.500+00:00")
    await coordinator.record_bot_started_speaking(2, "2026-10-01T10:00:02.000+00:00")
    await _assistant_text(assistant_aggregator, "Turn two reply", "2026-10-01T10:00:01.200+00:00")
    await coordinator.record_bot_stopped_speaking(2, "2026-10-01T10:00:03.000+00:00")
    await coordinator.record_turn_ended(2, interrupted=False)

    assert [
        (event["turn"], event["payload"]["text"], event["payload"]["timestamp"])
        for event in logs_buffer.get_events()
    ] == [
        (1, "Turn one, cut off", "2026-10-01T10:00:01.000+00:00"),
        (2, "Turn two reply", "2026-10-01T10:00:02.000+00:00"),
    ]


@pytest.mark.asyncio
async def test_a_generation_after_a_node_transition_keeps_the_new_node():
    """Codex review: a second generation in the same turn, after a tool moved
    the call to node B, was logged under node A."""
    logs_buffer = InMemoryLogsBuffer(workflow_run_id=91)
    coordinator = TranscriptLogCoordinator(logs_buffer)
    user_aggregator = _FakeAggregator()
    assistant_aggregator = _FakeAggregator()
    register_turn_log_handlers(coordinator, user_aggregator, assistant_aggregator)

    logs_buffer.set_current_node("node-a", "Node A")
    await coordinator.record_turn_started(1)
    await _started(assistant_aggregator)
    await coordinator.record_bot_started_speaking(1, "2026-10-01T10:00:01.000+00:00")
    await _assistant_text(assistant_aggregator, "One moment.", "2026-10-01T10:00:00.500+00:00")
    await coordinator.record_bot_stopped_speaking(1, "2026-10-01T10:00:01.500+00:00")
    logs_buffer.set_current_node("node-b", "Node B")  # the tool's transition
    await _started(assistant_aggregator)
    await coordinator.record_bot_started_speaking(1, "2026-10-01T10:00:02.500+00:00")
    await _assistant_text(assistant_aggregator, "Here are your options.", "2026-10-01T10:00:02.000+00:00")
    await coordinator.record_bot_stopped_speaking(1, "2026-10-01T10:00:04.000+00:00")
    await coordinator.record_turn_ended(1, interrupted=False)

    assert [
        (event["turn"], event["node_id"], event["payload"]["text"])
        for event in logs_buffer.get_events()
    ] == [
        (1, "node-a", "One moment."),
        (1, "node-b", "Here are your options."),
    ]


@pytest.mark.asyncio
async def test_generation_owner_is_read_when_the_real_aggregator_starts_it():
    """Codex review: pipecat dispatched on_assistant_turn_started as a task, so
    a generation begun in turn 1 / node A was owned by turn 2 / node B, which
    took over before the task ran."""
    logs_buffer = InMemoryLogsBuffer(workflow_run_id=92)
    coordinator = TranscriptLogCoordinator(logs_buffer)
    assistant_aggregator = LLMAssistantAggregator(LLMContext())
    register_turn_log_handlers(coordinator, _FakeAggregator(), assistant_aggregator)

    logs_buffer.set_current_node("node-a", "Node A")
    await coordinator.record_turn_started(1)
    await assistant_aggregator._trigger_assistant_turn_started()
    # The user barges in and a tool moves the call on before the loop yields.
    await coordinator.record_turn_started(2)
    logs_buffer.set_current_node("node-b", "Node B")
    await asyncio.sleep(0)

    await coordinator.record_bot_started_speaking(1, "2026-10-01T10:00:01.000+00:00")
    await coordinator.record_bot_stopped_speaking(1, "2026-10-01T10:00:01.500+00:00")
    await assistant_aggregator._call_event_handler(
        "on_assistant_turn_stopped",
        AssistantTurnStoppedMessage(
            content="Turn one reply",
            interrupted=True,
            timestamp="2026-10-01T10:00:00.500+00:00",
        ),
    )
    await coordinator.record_turn_ended(1, interrupted=True)
    await asyncio.sleep(0)
    await coordinator.flush()

    assert [
        (event["turn"], event["node_id"], event["payload"]["text"])
        for event in logs_buffer.get_events()
    ] == [(1, "node-a", "Turn one reply")]


@pytest.mark.asyncio
async def test_a_reply_that_pauses_keeps_all_of_its_speech():
    """Codex review: one generation spoken in two intervals was logged as
    ending with the first (2.0 s) instead of the second (3.5 s)."""
    logs_buffer = InMemoryLogsBuffer(workflow_run_id=92)
    coordinator = TranscriptLogCoordinator(logs_buffer)
    assistant_aggregator = _FakeAggregator()
    register_turn_log_handlers(coordinator, _FakeAggregator(), assistant_aggregator)

    await coordinator.record_turn_started(1)
    await _started(assistant_aggregator)
    await coordinator.record_bot_started_speaking(1, "2026-10-01T10:00:01.000+00:00")
    await coordinator.record_bot_stopped_speaking(1, "2026-10-01T10:00:02.000+00:00")
    await coordinator.record_bot_started_speaking(1, "2026-10-01T10:00:02.500+00:00")
    await coordinator.record_bot_stopped_speaking(1, "2026-10-01T10:00:03.500+00:00")
    await _assistant_text(
        assistant_aggregator, "First part. Second part.", "2026-10-01T10:00:00.500+00:00"
    )
    await coordinator.record_turn_ended(1, interrupted=False)

    [event] = logs_buffer.get_events()
    assert event["payload"]["timestamp"] == "2026-10-01T10:00:01.000+00:00"
    assert event["payload"]["end_timestamp"] == "2026-10-01T10:00:03.500+00:00"
