"""AgentStudio: one supervisor line per live call.

A line is what a supervisor attaches to. It carries three things:

- **Listen**: the caller's audio (tag 1), the agent's outgoing audio (tag 2),
  a supervisor's own voice (tag 3), and the call's realtime events.
- **Take over**: a supervisor's microphone is mixed into what the caller
  hears, and the agent is held (it neither speaks nor is prompted by timers)
  until the supervisor hands the call back.
- **Whisper**: a note to the agent, applied on its next turn.

Binary frames sent to listeners are ``[tag:u8][sample_rate:u32 LE][PCM16 LE mono]``.

The registry is per process: the engine runs one API worker
(``FASTAPI_WORKERS=1``), and the call and the supervisor socket both land on it.
# ponytail: in-process registry; relay through Redis pub/sub (the
# call_transfer_manager pattern) if the engine ever runs several workers.
"""

from __future__ import annotations

import asyncio
import struct
from collections import deque
from typing import Any

import numpy as np
from loguru import logger

from pipecat.audio.mixers.base_audio_mixer import BaseAudioMixer
from pipecat.frames.frames import MixerControlFrame

CALLER, AGENT, SUPERVISOR = 1, 2, 3

#: Supervisor audio buffered before it is played, and the most kept.
PREBUFFER_MS = 60
MAX_BUFFER_MS = 300
#: Frames queued per listener before the oldest are dropped. A slow listener
#: loses audio; it never slows the call.
LISTENER_QUEUE = 200
MAX_LISTENERS = 5

_lines: dict[int, "SupervisorLine"] = {}


def get(run_id: Any) -> "SupervisorLine | None":
    try:
        return _lines.get(int(run_id))
    except (TypeError, ValueError):
        return None


def get_or_create(run_id: Any) -> "SupervisorLine":
    key = int(run_id)
    line = _lines.get(key)
    if line is None:
        line = _lines[key] = SupervisorLine(key)
    return line


def drop(run_id: Any) -> None:
    line = _lines.pop(int(run_id), None)
    if line is not None:
        line.close("call_ended")


class SupervisorLine:
    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        self.sample_rate: int | None = None  # the caller-bound (output) rate
        self.engine: Any = None
        self.task: Any = None
        self.is_realtime = False
        self.listeners: set[asyncio.Queue] = set()
        self.held_by: str | None = None
        self.events: list[dict[str, Any]] = []
        self.closed = False
        self._buffer: deque[bytes] = deque()
        self._buffered = 0
        self._playing = False

    # -- fan-out to listeners --------------------------------------------

    def listen(self) -> asyncio.Queue:
        if len(self.listeners) >= MAX_LISTENERS:
            raise OverflowError("too many listeners on this call")
        queue: asyncio.Queue = asyncio.Queue(maxsize=LISTENER_QUEUE)
        self.listeners.add(queue)
        return queue

    def unlisten(self, queue: asyncio.Queue) -> None:
        self.listeners.discard(queue)

    def _put(self, item: Any) -> None:
        for queue in self.listeners:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(item)

    def publish_audio(self, tag: int, pcm: bytes, sample_rate: int | None) -> None:
        if self.listeners and pcm and sample_rate:
            self._put(struct.pack("<BI", tag, sample_rate) + pcm)

    async def publish_event(self, message: dict) -> None:
        """RealtimeFeedbackObserver's sender: the call's transcript and tool events."""
        if self.listeners:
            self._put(message)

    def note(self, kind: str, **fields: Any) -> None:
        """A supervision event: sent to listeners and kept for the call's logs."""
        from datetime import datetime, timezone

        event = {"type": f"supervisor-{kind}", "at": datetime.now(timezone.utc).isoformat(), **fields}
        self.events.append(event)
        self._put(event)

    def close(self, reason: str) -> None:
        if self.closed:
            return
        self.closed = True
        self._put({"type": "ended", "reason": reason})
        self._put(None)  # end of stream

    # -- supervisor audio into the call ----------------------------------

    def _bytes_per_ms(self) -> int:
        return (self.sample_rate or 8000) * 2 // 1000

    def feed(self, pcm: bytes) -> None:
        """Supervisor microphone audio at ``sample_rate``, PCM16 mono."""
        if not self.held_by or not pcm:
            return
        if len(pcm) % 2:
            pcm = pcm[:-1]
        self._buffer.append(pcm)
        self._buffered += len(pcm)
        cap = MAX_BUFFER_MS * self._bytes_per_ms()
        while self._buffered > cap and self._buffer:
            self._buffered -= len(self._buffer.popleft())
        self.publish_audio(SUPERVISOR, pcm, self.sample_rate)

    def take(self, size: int) -> bytes | None:
        """``size`` bytes of supervisor audio for the next outgoing chunk, or
        None when there is nothing to play (prebuffering, or silent)."""
        if not self._playing:
            if self._buffered < PREBUFFER_MS * self._bytes_per_ms():
                return None
            self._playing = True
        out = bytearray()
        while len(out) < size and self._buffer:
            head = self._buffer.popleft()
            need = size - len(out)
            out += head[:need]
            if len(head) > need:
                self._buffer.appendleft(head[need:])
        self._buffered -= len(out)
        if len(out) < size:  # underrun: pad, and prebuffer again before resuming
            self._playing = False
            out += bytes(size - len(out))
        return bytes(out)

    def reset_audio(self) -> None:
        self._buffer.clear()
        self._buffered = 0
        self._playing = False


def mix_pcm16(base: bytes, extra: bytes) -> bytes:
    a = np.frombuffer(base, dtype=np.int16).astype(np.int32)
    b = np.frombuffer(extra[: len(base)], dtype=np.int16).astype(np.int32)
    if len(b) < len(a):
        b = np.pad(b, (0, len(a) - len(b)))
    return np.clip(a + b, -32768, 32767).astype(np.int16).tobytes()


class SupervisorMixer(BaseAudioMixer):
    """Wraps the call's output mixer: taps what the agent says, and mixes a
    supervisor's voice into what the caller hears.

    The output transport calls ``mix`` for every outgoing chunk on the real
    clock, silence included, so supervisor audio plays even while the agent is
    quiet.
    """

    def __init__(self, inner: BaseAudioMixer, line: SupervisorLine) -> None:
        self._inner = inner
        self._line = line

    async def start(self, sample_rate: int):
        self._line.sample_rate = sample_rate
        await self._inner.start(sample_rate)

    async def stop(self):
        await self._inner.stop()
        drop(self._line.run_id)

    async def process_frame(self, frame: MixerControlFrame):
        await self._inner.process_frame(frame)

    async def mix(self, audio: bytes) -> bytes:
        line = self._line
        line.publish_audio(AGENT, audio, line.sample_rate)
        mixed = await self._inner.mix(audio)
        if line.held_by:
            extra = line.take(len(mixed))
            if extra is not None:
                try:
                    mixed = mix_pcm16(mixed, extra)
                except ValueError:
                    logger.exception("supervisor mix failed on run {}", line.run_id)
        return mixed


def wrap_mixer(mixer: BaseAudioMixer, run_id: Any) -> BaseAudioMixer:
    """The call's mixer, wrapped when the call has a run id to attach to."""
    if run_id in (None, ""):
        return mixer
    return SupervisorMixer(mixer, get_or_create(run_id))


if __name__ == "__main__":
    line = SupervisorLine(1)
    line.sample_rate = 8000
    line.held_by = "sup"
    line.feed(b"\x01\x00" * 200)  # 25 ms: below the 60 ms prebuffer
    assert line.take(320) is None
    line.feed(b"\x01\x00" * 400)  # 75 ms buffered now
    assert line.take(320) == b"\x01\x00" * 160
    rest = line.take(2000)  # underrun: padded with silence
    assert rest is not None and len(rest) == 2000 and rest.endswith(b"\x00\x00")
    assert line.take(320) is None  # prebuffering again
    assert mix_pcm16(struct.pack("<2h", 32000, -32000), struct.pack("<2h", 1000, -1000)) == struct.pack("<2h", 32767, -32768)
    q = line.listen()
    for _ in range(LISTENER_QUEUE + 5):
        line.publish_audio(CALLER, b"\x00\x00", 8000)
    assert q.qsize() == LISTENER_QUEUE
    print("ok")
