"""AgentStudio: attach every live call to its supervisor line.

Also tells PayInt the call has started (``PAYINT_CALL_STARTED_URL``), so the
call is on PayInt's floor from its first second rather than from its first
tool call or its after-call notice.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from loguru import logger

from api.services.integrations.base import (
    IntegrationRuntimeContext,
    IntegrationRuntimeSession,
)
from api.services.pipecat.realtime_feedback_observer import RealtimeFeedbackObserver
from pipecat.frames.frames import InputAudioRawFrame
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.transports.base_input import BaseInputTransport

from . import line as lines

_background: set[asyncio.Task] = set()


class CallerTap(BaseObserver):
    """The caller's audio, as the input transport first pushes it."""

    def __init__(self, line: lines.SupervisorLine) -> None:
        super().__init__()
        self._line = line

    async def on_push_frame(self, data: FramePushed):
        if not self._line.listeners:
            return
        frame = data.frame
        # Observers see a frame at every hop; the input transport's push is the first.
        if isinstance(frame, InputAudioRawFrame) and isinstance(data.source, BaseInputTransport):
            self._line.publish_audio(lines.CALLER, frame.audio, frame.sample_rate)


async def _notify_started(run: Any, context: dict[str, Any]) -> None:
    url = os.getenv("PAYINT_CALL_STARTED_URL", "").strip()
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                url,
                # mode: how the media arrives (twilio, ari, smallwebrtc...), for PayInt's transport.
                json={"workflow_run_id": run.id, "workflow_id": run.workflow_id, "mode": run.mode,
                      "initial_context": context},
                headers={"Authorization": f"Bearer {os.getenv('PAYINT_HOOK_TOKEN', '')}"},
            )
            resp.raise_for_status()
    except Exception as e:  # the call goes on; PayInt files it after it ends either way
        logger.warning(f"PayInt call-started notice failed for run {run.id}: {e}")


class SupervisorSession(IntegrationRuntimeSession):
    name = "supervisor"

    def __init__(self, context: IntegrationRuntimeContext) -> None:
        self._run = context.workflow_run
        self._line = lines.get_or_create(context.workflow_run_id)
        self._line.engine = context.engine
        self._line.is_realtime = context.is_realtime

    def attach(self, task: Any) -> None:
        self._line.task = task
        task.add_observer(RealtimeFeedbackObserver(ws_sender=self._line.publish_event))
        task.add_observer(CallerTap(self._line))
        if self._run is not None:
            # The engine's merged context: the run as stored plus what the
            # caller's session supplied (the in-memory run predates the merge).
            context = {
                **dict(getattr(self._run, "initial_context", None) or {}),
                **dict(getattr(self._line.engine, "_call_context_vars", None) or {}),
            }
            notice = asyncio.get_running_loop().create_task(_notify_started(self._run, context))
            _background.add(notice)
            notice.add_done_callback(_background.discard)

    async def on_call_finished(self, *, gathered_context: dict[str, Any]) -> dict[str, Any] | None:
        events = list(self._line.events)
        lines.drop(self._line.run_id)
        return {"supervisor": events} if events else None


def create_runtime_sessions(context: IntegrationRuntimeContext) -> list[IntegrationRuntimeSession]:
    return [SupervisorSession(context)]
