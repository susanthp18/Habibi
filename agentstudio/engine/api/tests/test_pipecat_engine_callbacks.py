import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pipecat.frames.frames import LLMMessagesAppendFrame
from pipecat.utils.enums import EndTaskReason

from api.services.workflow.pipecat_engine_callbacks import create_max_duration_callback


def _engine(on_hold=False):
    engine = SimpleNamespace(
        generation_on_hold=on_hold,
        active_agent=SimpleNamespace(queue_frame=AsyncMock()),
        agent_can_act=Mock(return_value=True),
        arm_speech_playback=Mock(),
        wait_for_speech_playback=AsyncMock(return_value=True),
        engine_note=lambda content: {"role": "user", "content": content},
        end_call_with_reason=AsyncMock(),
        _mute_pipeline=False,
    )
    return engine


@pytest.mark.asyncio
async def test_at_the_time_limit_the_agent_says_goodbye_then_the_call_ends():
    """Run 88 was cut at 300 s mid-conversation, with no goodbye."""
    engine = _engine()
    callback = create_max_duration_callback(engine)

    assert await callback() is None  # returns at once: the goodbye runs beside the clock
    await callback()  # the clock asks again: still one closing
    await asyncio.wait_for(engine._limit_close_task, 1)

    (frame,), _ = engine.active_agent.queue_frame.await_args
    assert isinstance(frame, LLMMessagesAppendFrame) and frame.run_llm is True
    assert "time limit" in frame.messages[0]["content"]
    engine.arm_speech_playback.assert_called_once()
    engine.wait_for_speech_playback.assert_awaited_once()
    # Gracefully, after the goodbye: no abort_immediately.
    engine.end_call_with_reason.assert_awaited_once_with(EndTaskReason.CALL_DURATION_EXCEEDED.value)


@pytest.mark.asyncio
async def test_the_limit_waits_while_a_supervisor_has_the_call():
    engine = _engine(on_hold=True)
    assert await create_max_duration_callback(engine)() is False
    engine.end_call_with_reason.assert_not_awaited()
