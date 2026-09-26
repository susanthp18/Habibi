from api.services.pipecat.realtime_feedback_events import (
    build_bot_text_event,
    build_function_call_end_event,
    build_node_transition_event,
    build_user_transcription_event,
    realtime_feedback_event_sort_key,
    stamp_realtime_feedback_event,
)
from api.utils.transcript import generate_transcript_text


def test_build_function_call_end_event_serializes_results():
    event = build_function_call_end_event(
        function_name="lookup_contact",
        tool_call_id="tool-1",
        result={"contact_id": 42},
    )

    assert event == {
        "type": "rtf-function-call-end",
        "payload": {
            "function_name": "lookup_contact",
            "tool_call_id": "tool-1",
            "result": "{'contact_id': 42}",
            "result_summary": {"ok": None, "error_code": None, "http_status": None},
        },
    }


def test_failed_promise_metadata_is_redacted():
    event = build_function_call_end_event(
        function_name="promise_to_pay", tool_call_id="tool-2",
        result={"status": "error", "status_code": 200, "data": {
            "ok": False, "error": "promise_revision_cap", "customer_name": "Private Name"}},
    )
    assert event["payload"]["result_summary"] == {
        "ok": False, "error_code": "promise_revision_cap", "http_status": 200,
    }
    assert "Private Name" not in str(event["payload"]["result_summary"])


def test_run_seven_rejected_promise_sequence_stays_failed():
    # Non-calling fixture for the two business rejections observed on run 7.
    events = [
        build_function_call_end_event(
            function_name="promise_to_pay", tool_call_id=f"promise-{index}",
            result={"status": "error", "status_code": 200,
                    "data": {"ok": False, "error": code}},
        )
        for index, code in enumerate(("invalid_revision_reason", "promise_revision_cap"), start=1)
    ]
    assert [event["payload"]["result_summary"]["ok"] for event in events] == [False, False]
    assert [event["payload"]["result_summary"]["error_code"] for event in events] == [
        "invalid_revision_reason", "promise_revision_cap",
    ]


def test_verification_not_completed_is_distinct_from_tool_transport_success():
    event = build_function_call_end_event(
        function_name="verify_identity", tool_call_id="verify-1",
        result={"status": "success", "status_code": 200,
                "data": {"ok": True, "verified": False}},
    )
    assert event["payload"]["result_summary"]["verified"] is False


def test_stamp_and_sort_realtime_feedback_events():
    node_transition = stamp_realtime_feedback_event(
        build_node_transition_event(
            node_id="node-1",
            node_name="Greeting",
            previous_node_id=None,
            previous_node_name=None,
        ),
        timestamp="2026-01-01T00:00:01+00:00",
        turn=0,
        node_id="node-1",
        node_name="Greeting",
    )
    bot_text = stamp_realtime_feedback_event(
        build_bot_text_event(
            text="Hello there",
            # Deliberately earlier than the node's event timestamp: ordering
            # follows the top-level event timestamp, not payload speech time.
            timestamp="2026-01-01T00:00:00+00:00",
        ),
        timestamp="2026-01-01T00:00:02+00:00",
        turn=0,
    )

    events = sorted([node_transition, bot_text], key=realtime_feedback_event_sort_key)

    assert events == [node_transition, bot_text]
    assert node_transition["node_id"] == "node-1"
    assert node_transition["node_name"] == "Greeting"


def test_transcript_can_include_end_timestamps_without_changing_default_format():
    events = [
        stamp_realtime_feedback_event(
            build_bot_text_event(
                text="Can you confirm your date of birth?",
                timestamp="2026-01-01T00:00:01+00:00",
                end_timestamp="2026-01-01T00:00:04+00:00",
            ),
            timestamp="2026-01-01T00:00:05+00:00",
            turn=0,
        ),
        stamp_realtime_feedback_event(
            build_user_transcription_event(
                text="January fifth",
                final=True,
                timestamp="2026-01-01T00:00:06+00:00",
                end_timestamp="2026-01-01T00:00:08+00:00",
            ),
            timestamp="2026-01-01T00:00:09+00:00",
            turn=1,
        ),
    ]

    assert generate_transcript_text(events) == (
        "[2026-01-01T00:00:01+00:00] assistant: Can you confirm your date of birth?\n"
        "[2026-01-01T00:00:06+00:00] user: January fifth\n"
    )
    assert generate_transcript_text(events, include_end_timestamps=True) == (
        "[2026-01-01T00:00:01+00:00 -> 2026-01-01T00:00:04+00:00] "
        "assistant: Can you confirm your date of birth?\n"
        "[2026-01-01T00:00:06+00:00 -> 2026-01-01T00:00:08+00:00] "
        "user: January fifth\n"
    )
