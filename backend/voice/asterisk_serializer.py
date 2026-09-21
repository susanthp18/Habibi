"""Asterisk ``chan_websocket`` frame serializer (owned copy, BSD-2 ideas).

Not a ``pipecat-asterisk`` install -- that package is not pinned against
``pipecat-ai==1.6.0``. Protocol from Asterisk's WebSocket channel docs:

Inbound: ``MEDIA_START`` (text), binary slin PCM, ``MEDIA_XOFF`` / ``MEDIA_XON``,
``DTMF_END``, ``HANGUP``.
Outbound: binary slin, ``FLUSH_MEDIA``, ``HANGUP``.

Who the call is about arrives in one channel variable, ``HABIBI_CTX``: a JSON
object the ARI controller (``voice/asterisk_controller.py``) sets on the media
channel. Dialplan variables do not survive onto that channel, which is why every
Asterisk call used to reach the bot as an unknown inbound caller.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InputDTMFFrame,
    InterruptionFrame,
    KeypadEntry,
    OutputAudioRawFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer

from voice.asterisk_ops import CTX_VARIABLE

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 16000
_SLIN_RATES = {
    "slin": 8000,
    "slin12": 12000,
    "slin16": 16000,
    "slin24": 24000,
    "slin32": 32000,
    "slin44": 44100,
    "slin48": 48000,
}


def parse_text_event(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw[0] == "{":
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"event": raw.upper()}
        return parsed if isinstance(parsed, dict) else {"event": raw.upper()}
    return {"event": raw.upper()}


def sample_rate_for_format(fmt: str | None) -> int:
    return _SLIN_RATES.get((fmt or "slin16").strip().lower(), DEFAULT_SAMPLE_RATE)


def call_context(variables: dict[str, Any] | None) -> dict[str, str]:
    """``HABIBI_CTX`` from ``MEDIA_START.channel_variables``, as plain strings.

    Asterisk keeps the inheritance prefix in the variable's *name*, so the value
    the controller sets as ``__HABIBI_CTX`` on the caller's channel arrives here
    still called that. Both spellings are read.
    """
    variables = variables or {}
    raw = next((variables[k] for k in (CTX_VARIABLE, f"__{CTX_VARIABLE}", f"_{CTX_VARIABLE}") if variables.get(k)), None)
    if not raw:
        return {}
    try:
        ctx = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        logger.warning("asterisk: %s is not JSON; refusing inbound default", CTX_VARIABLE)
        return {"_ctx_invalid": "1"}
    if not isinstance(ctx, dict):
        logger.warning("asterisk: %s is not an object; refusing inbound default", CTX_VARIABLE)
        return {"_ctx_invalid": "1"}
    return {str(k): str(v) for k, v in ctx.items() if v not in (None, "")}


def call_data_from_media_start(payload: dict[str, Any]) -> SimpleNamespace:
    """The runner's ``call_data`` for one call, keyed the way ``bot_flow`` reads it.

    ``call_id`` is the SIP leg's channel id, not the media channel's: that is the
    id ``call_attempts.provider_call_id`` holds, the one a transfer acts on and the
    one the recording is named after.
    """
    variables = payload.get("channel_variables") or {}
    ctx = call_context(variables if isinstance(variables, dict) else {})
    ctx_invalid = ctx.pop("_ctx_invalid", None)
    media_channel = str(payload.get("channel_id") or "")
    call_id = ctx.get("sip_channel_id") or media_channel
    fmt = str(payload.get("format") or "slin16")
    call_type = str(ctx.get("call_type") or "").strip().lower()
    if not call_type:
        # Truncated CTX must not silently become inbound (AMD off, hours skip).
        # Empty call_type keeps AMD off; ctx_invalid is fail-closed for hours.
        call_type = "" if ctx_invalid else "inbound"
    body = {
        **ctx,
        "call_sid": call_id,
        "call_type": call_type,
        "from": ctx.get("from", ""),
        "to": ctx.get("to", ""),
    }
    if ctx_invalid:
        body["ctx_invalid"] = "1"
    return SimpleNamespace(
        provider="asterisk",
        call_id=call_id,
        from_number=body["from"],
        to_number=body["to"],
        body=body,
        stream_id=str(payload.get("connection_id") or ""),
        encoding=fmt,
        sample_rate=sample_rate_for_format(fmt),
        optimal_frame_size=int(payload.get("optimal_frame_size") or 0),
    )


def encode_command(command: str) -> str:
    return json.dumps({"command": command})


class AsteriskFrameSerializer(FrameSerializer):
    """Pipecat ``FrameSerializer`` for ``chan_websocket`` JSON + binary slin."""

    def __init__(self, sample_rate: int = 0) -> None:
        super().__init__()
        self.sample_rate = int(sample_rate or 0)
        self.num_channels = 1
        self.paused = False
        self._held: list[bytes] = []
        self._pending_hangup = False
        self.call_data: SimpleNamespace | None = None
        #: Asterisk already hung up: sending HANGUP now writes into a closed socket.
        self.remote_hungup = False

    async def setup(self, frame: Frame) -> None:
        rate = getattr(frame, "audio_out_sample_rate", None)
        if rate and not self.sample_rate:
            self.sample_rate = int(rate)

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            self._held.clear()
            self._pending_hangup = False
            return encode_command("FLUSH_MEDIA")
        if isinstance(frame, OutputAudioRawFrame):
            pcm = bytes(frame.audio)
            if self.paused:
                # ponytail: unbounded while Asterisk says XOFF; it only says so briefly.
                self._held.append(pcm)
                return None
            if self._held:
                pcm = b"".join(self._held) + pcm
                self._held.clear()
            return pcm
        if isinstance(frame, (EndFrame, CancelFrame)):
            if self._held:
                pcm = b"".join(self._held)
                self._held.clear()
                self.paused = False
                if not self.remote_hungup:
                    self._pending_hangup = True
                return pcm
            if self._pending_hangup:
                self._pending_hangup = False
            return None if self.remote_hungup else encode_command("HANGUP")
        if self._pending_hangup:
            self._pending_hangup = False
            return None if self.remote_hungup else encode_command("HANGUP")
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        # The transport hands binary WebSocket messages over as bytes and text as
        # str, so audio is never sniffed for a leading "{".
        if isinstance(data, (bytes, bytearray)):
            return InputAudioRawFrame(
                audio=bytes(data),
                sample_rate=self.sample_rate or DEFAULT_SAMPLE_RATE,
                num_channels=self.num_channels,
            )

        payload = parse_text_event(data)
        event = str(payload.get("event") or payload.get("type") or "").strip().upper()
        if event == "MEDIA_START":
            self.call_data = call_data_from_media_start(payload)
            self.sample_rate = self.call_data.sample_rate
            return None
        if event == "MEDIA_XOFF":
            self.paused = True
            return None
        if event == "MEDIA_XON":
            # Unpause. Held PCM is emitted on the next serialize — including
            # EndFrame — so the last phrase is not stuck in `_held`.
            self.paused = False
            return None
        if event == "DTMF_END":
            digit = str(payload.get("digit") or "").strip()
            try:
                return InputDTMFFrame(KeypadEntry(digit))
            except ValueError:
                logger.debug("asterisk DTMF ignored digit=%r", digit)
                return None
        if event == "HANGUP":
            self.remote_hungup = True
            return EndFrame()
        return None
