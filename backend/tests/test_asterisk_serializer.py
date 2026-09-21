"""Asterisk chan_websocket serializer: protocol, identity and transport build."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("pipecat")

from pipecat.frames.frames import (  # noqa: E402
    EndFrame,
    InputAudioRawFrame,
    InputDTMFFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
)

from voice.asterisk_serializer import AsteriskFrameSerializer, call_data_from_media_start  # noqa: E402

CTX = {
    "call_type": "outbound",
    "attempt_id": "CA-1",
    "objective": "dpd_reminder",
    "from": "1000",
    "to": "1001",
    "sip_channel_id": "att-CA-1",
}


def _media_start(**overrides) -> dict:
    payload = {
        "event": "MEDIA_START",
        "connection_id": "habibi_bot",
        "channel_id": "att-CA-1-m",
        "format": "slin16",
        "optimal_frame_size": 640,
        # The real shape: Asterisk's own variables plus the one the controller sets.
        # Asterisk reports the variable under the name it was set with, and the
        # controller sets it inheritable (__) so it reaches this channel at all.
        "channel_variables": {
            "MEDIA_WEBSOCKET_CONNECTION_ID": "habibi_bot",
            "__HABIBI_CTX": json.dumps(CTX),
        },
    }
    payload.update(overrides)
    return payload


def test_identity_comes_from_habibi_ctx_keyed_by_the_sip_leg() -> None:
    data = call_data_from_media_start(_media_start())

    # The SIP leg's id, not the media leg's: it is the attempt's provider_call_id.
    assert data.call_id == "att-CA-1"
    assert data.body["call_sid"] == "att-CA-1"
    assert data.body["call_type"] == "outbound"
    assert data.body["attempt_id"] == "CA-1"
    assert data.body["objective"] == "dpd_reminder"
    assert (data.from_number, data.to_number) == ("1000", "1001")
    assert data.sample_rate == 16000
    assert data.optimal_frame_size == 640


def test_the_plain_variable_name_is_read_too() -> None:
    data = call_data_from_media_start(_media_start(channel_variables={"HABIBI_CTX": json.dumps(CTX)}))
    assert data.call_id == "att-CA-1"


def test_a_call_without_context_is_an_anonymous_inbound_call() -> None:
    data = call_data_from_media_start(_media_start(channel_variables={}))
    assert data.body["call_type"] == "inbound"
    assert data.call_id == "att-CA-1-m"


def test_the_serializer_is_a_pipecat_serializer() -> None:
    from pipecat.serializers.base_serializer import FrameSerializer

    assert isinstance(AsteriskFrameSerializer(), FrameSerializer)


def test_the_transport_builds() -> None:
    """Every call used to die here: FastAPIWebsocketParams rejected the serializer."""
    from voice.asterisk_ws import build_asterisk_transport

    args = SimpleNamespace(
        websocket=SimpleNamespace(),
        asterisk_serializer=AsteriskFrameSerializer(sample_rate=16000),
        call_data=call_data_from_media_start(_media_start()),
    )
    transport = build_asterisk_transport(args)
    assert transport._params.fixed_audio_packet_size == 640


def test_protocol_round_trip() -> None:
    ser = AsteriskFrameSerializer()

    async def run() -> None:
        assert await ser.deserialize(json.dumps(_media_start())) is None
        assert ser.sample_rate == 16000

        # Binary is always audio, even when the PCM happens to start with "{".
        pcm = b"{" + b"\x01" * 319
        frame = await ser.deserialize(pcm)
        assert isinstance(frame, InputAudioRawFrame) and frame.audio == pcm

        dtmf = await ser.deserialize(json.dumps({"event": "DTMF_END", "digit": "5"}))
        assert isinstance(dtmf, InputDTMFFrame) and dtmf.button.value == "5"

        await ser.deserialize(json.dumps({"event": "MEDIA_XOFF"}))
        out = OutputAudioRawFrame(audio=b"\x02\x00" * 10, sample_rate=16000, num_channels=1)
        assert await ser.serialize(out) is None
        await ser.deserialize(json.dumps({"event": "MEDIA_XON"}))
        assert await ser.serialize(out) == b"\x02\x00" * 20

        assert json.loads(await ser.serialize(InterruptionFrame())) == {"command": "FLUSH_MEDIA"}
        assert json.loads(await ser.serialize(EndFrame())) == {"command": "HANGUP"}

    asyncio.run(run())


def test_no_hangup_is_sent_after_asterisk_hung_up() -> None:
    ser = AsteriskFrameSerializer()

    async def run() -> None:
        assert isinstance(await ser.deserialize(json.dumps({"event": "HANGUP"})), EndFrame)
        assert await ser.serialize(EndFrame()) is None

    asyncio.run(run())


def test_xon_flushes_held_pcm_on_endframe() -> None:
    ser = AsteriskFrameSerializer()

    async def run() -> None:
        await ser.deserialize(json.dumps({"event": "MEDIA_XOFF"}))
        held = OutputAudioRawFrame(audio=b"\x03\x00" * 4, sample_rate=16000, num_channels=1)
        assert await ser.serialize(held) is None
        await ser.deserialize(json.dumps({"event": "MEDIA_XON"}))
        assert await ser.serialize(EndFrame()) == b"\x03\x00" * 4
        assert json.loads(await ser.serialize(EndFrame())) == {"command": "HANGUP"}

    asyncio.run(run())


def test_truncated_ctx_does_not_default_inbound() -> None:
    data = call_data_from_media_start(
        _media_start(channel_variables={"__HABIBI_CTX": "{not-json"})
    )
    assert data.body.get("ctx_invalid") == "1"
    assert data.body["call_type"] == ""
