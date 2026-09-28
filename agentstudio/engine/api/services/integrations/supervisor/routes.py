"""AgentStudio: supervise a live call.

    WS   /supervise/{run_id}/listen     hear both sides, live events
    WS   /supervise/{run_id}/takeover   the same, plus: the agent is held and
                                        the supervisor's microphone reaches the
                                        caller; {"type":"release","note":...}
                                        hands the call back, {"type":"end"}
                                        ends it
    POST /supervise/{run_id}/whisper    {"text": ...}: a note the agent follows
                                        on its next reply

PayInt's gateway decides who may use which (and records it); here the run is
only checked to belong to the caller's organization.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel, Field

from api.db import db_client
from api.services.auth.depends import get_user, get_user_ws
from pipecat.frames.frames import InterruptionFrame, InterruptionWorkerFrame, LLMMessagesAppendFrame
from pipecat.processors.frame_processor import FrameDirection

from . import line as lines

router = APIRouter(prefix="/supervise", tags=["supervise"])

#: A takeover socket that drops is given this long to come back before the
#: agent gets the call back -- the caller must never be left in dead air.
RELEASE_GRACE_S = 3.0
#: Largest microphone frame accepted (1 s at 16 kHz).
MAX_FEED_BYTES = 32000

HANDBACK = (
    "A supervisor spoke with the caller directly and has now handed the call back to you. "
    "Continue the conversation from here; do not repeat what was already said."
)


async def _owned(run_id: int, user) -> None:
    if not user.selected_organization_id or not await db_client.get_workflow_run(
        run_id, organization_id=user.selected_organization_id
    ):
        raise HTTPException(status_code=404, detail="run_not_found")


def _live(run_id: int) -> lines.SupervisorLine | None:
    line = lines.get(run_id)
    return line if line is not None and line.task is not None and not line.closed else None


async def _take_floor(line: lines.SupervisorLine, who: str) -> None:
    line.held_by = who
    line.reset_audio()
    line.engine.supervisor_holds_floor = True
    # Cut the agent off mid-sentence; the hold keeps it from starting again.
    # At the bridge: it clears the caller's audio and cancels the agent's reply.
    # From the pipeline head it would pass the user aggregator, which drops
    # interruptions while the caller is muted (nodes that do not allow them).
    bridge = getattr(line.engine, "agent_bridge", None)
    if bridge is not None:
        await bridge.queue_frame(InterruptionFrame())
    else:
        await line.task.queue_frame(InterruptionWorkerFrame(), FrameDirection.UPSTREAM)
    line.note("takeover", by=who)


async def _release(line: lines.SupervisorLine, who: str, note: str | None) -> None:
    if line.held_by != who:
        return
    line.held_by = None
    line.reset_audio()
    line.engine.supervisor_holds_floor = False
    line.note("release", by=who, note=note or None)
    if line.closed:
        return
    content = HANDBACK + (f" Supervisor's note: {note}" if note else "")
    await line.task.queue_frame(LLMMessagesAppendFrame([{"role": "system", "content": content}], run_llm=True))


async def _pump(websocket: WebSocket, queue: asyncio.Queue) -> None:
    try:
        while True:
            item = await queue.get()
            if item is None:  # the call ended: closing wakes the receive loop too
                await websocket.close(code=1000, reason="call_ended")
                return
            if isinstance(item, bytes):
                await websocket.send_bytes(item)
            else:
                await websocket.send_text(json.dumps(item, default=str))
    except (WebSocketDisconnect, RuntimeError):  # the supervisor went away
        return


@router.websocket("/{run_id}/{mode}")
async def supervise(websocket: WebSocket, run_id: int, mode: str, user=Depends(get_user_ws)):
    await _owned(run_id, user)
    await websocket.accept()
    line = _live(run_id)
    if mode not in ("listen", "takeover"):
        await websocket.close(code=4400, reason="unknown_mode")
        return
    if line is None:
        await websocket.close(code=4404, reason="call_not_live")
        return
    if mode == "takeover":
        refusal = (
            "realtime_agent" if line.is_realtime
            else "already_held" if line.held_by
            else "transfer_in_progress" if getattr(line.engine, "transfer_in_progress", False)
            else None
        )
        if refusal:
            await websocket.close(code=4409, reason=refusal)
            return
    try:
        queue = line.listen()
    except OverflowError:
        await websocket.close(code=4429, reason="too_many_listeners")
        return

    who = f"{user.id}:{uuid.uuid4().hex[:8]}"
    await websocket.send_text(json.dumps({
        "type": "hello", "mode": mode, "runId": run_id,
        "sampleRate": line.sample_rate, "heldBy": bool(line.held_by),
    }))
    pump = asyncio.create_task(_pump(websocket, queue))
    released = False
    try:
        if mode == "takeover":
            await _take_floor(line, who)
        else:
            line.note("listen", by=str(user.id))
        while not pump.done():
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if mode != "takeover":
                continue
            if message.get("bytes"):
                line.feed(message["bytes"][:MAX_FEED_BYTES])
            elif message.get("text"):
                try:
                    command = json.loads(message["text"])
                except ValueError:
                    continue
                if command.get("type") == "release":
                    await _release(line, who, str(command.get("note") or "")[:500])
                    released = True
                    break
                if command.get("type") == "end":
                    line.note("end-call", by=who)
                    await line.engine.end_call_with_reason("supervisor_ended")
    except (WebSocketDisconnect, RuntimeError):  # RuntimeError: receive after the pump closed it
        pass
    finally:
        pump.cancel()
        line.unlisten(queue)
        if mode == "takeover" and not released and line.held_by == who:
            async def _grace() -> None:
                await asyncio.sleep(RELEASE_GRACE_S)
                await _release(line, who, None)

            asyncio.get_running_loop().create_task(_grace())
        try:
            await websocket.close()
        except RuntimeError:
            pass


class WhisperRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@router.post("/{run_id}/whisper")
async def whisper(run_id: int, body: WhisperRequest, user=Depends(get_user)) -> dict:
    await _owned(run_id, user)
    line = _live(run_id)
    if line is None:
        raise HTTPException(status_code=409, detail="call_not_live")
    if line.is_realtime:
        raise HTTPException(status_code=409, detail="realtime_agent")
    # In the agent's system prompt, where the model weighs it: as a message in
    # the conversation it was measurably ignored in favour of the node's steps.
    await line.engine.add_supervisor_note(body.text)
    line.note("whisper", by=str(user.id))
    logger.info("supervisor whisper applied to run {}", run_id)
    return {"ok": True}
