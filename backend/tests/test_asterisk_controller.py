"""The ARI controller, driven by the event sequences Asterisk sends."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from voice import asterisk_controller as ac
from voice import asterisk_ops as ops


class FakeAri:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        #: exact path -> error to raise instead of answering
        self.fail: dict[str, ops.AriError] = {}
        self.variables: dict[str, str] = {}

    def __call__(self, method: str, path: str, *, query=None, body=None, raw=False, timeout=10) -> Any:
        self.calls.append((method, path, query or {}))
        if path in self.fail:
            raise self.fail[path]
        if path.endswith("/variable") and method == "GET":
            return {"value": self.variables.get(path.split("/")[2], "")}
        if raw:
            return b"RIFFwav"
        return {}

    def paths(self) -> list[tuple[str, str]]:
        return [(m, p) for m, p, _ in self.calls]


@pytest.fixture
def world():
    ari = FakeAri()
    statuses: list[dict] = []
    transferred: list[str] = []
    stored: list[tuple[str, bytes]] = []
    controller = ac.Controller(
        ari=ari,
        status_writer=lambda **kw: statuses.append(kw) or {"id": "CA-1"},
        mark_transferred=transferred.append,
        store_recording=lambda name, wav: stored.append((name, wav)) or "MED-1",
        agents_available=False,
    )
    return controller, ari, statuses, transferred, stored


def run(controller: ac.Controller, *events: dict) -> None:
    async def go() -> None:
        for event in events:
            await controller.handle(event)

    asyncio.run(go())


def ev(kind: str, channel_id: str, **extra: Any) -> dict:
    return {"type": kind, "channel": {"id": channel_id, **extra.pop("channel", {})}, **extra}


# -- status mapping --------------------------------------------------------


@pytest.mark.parametrize(
    "cause, answered, status",
    [
        (16, True, "completed"),
        (17, False, "busy"),
        (19, False, "no-answer"),
        (16, False, "no-answer"),
        (21, False, "rejected"),
        (1, False, "failed"),
        (34, False, "failed"),
        (None, False, "failed"),
    ],
)
def test_hangup_cause_maps_to_an_attempt_status(cause, answered, status) -> None:
    assert ac.status_for(cause, answered=answered) == status


# -- inbound ---------------------------------------------------------------


def test_inbound_answers_only_after_the_bot_is_connected(world) -> None:
    controller, ari, _statuses, _t, _s = world
    sip = "1789.1"
    run(
        controller,
        ev(
            "StasisStart",
            sip,
            args=["inbound"],
            channel={"caller": {"number": "1001"}, "dialplan": {"exten": "1000"}},
        ),
    )
    variable = next(c for c in ari.calls if c[1].endswith("/variable"))
    assert variable[2]["variable"] == "__HABIBI_CTX"
    create = next(c for c in ari.calls if c[1] == "/channels")
    # `originator` is what copies the inherited context onto the media leg.
    assert create[2]["originator"] == sip
    assert create[2]["channelId"] == "1789.1-m"
    # A chan_websocket channel cannot be bridged by ARI; the bot is reached
    # through a Local channel that dials it in the dialplan.
    assert create[2]["endpoint"] == "Local/bot@to-bot/n"
    assert create[2]["app"] == "habibi"
    assert ("POST", f"/channels/{sip}/answer") not in ari.paths()

    run(controller, ev("StasisStart", "1789.1-m"))
    # Each leg joins in its own request: a repeated `channel` parameter is
    # accepted and then only the last one joins.
    added = [c[2]["channel"] for c in ari.calls if c[1].endswith("/addChannel")]
    assert added == [sip, f"{sip}-m"]
    assert ari.paths()[-5:] == [
        ("POST", f"/channels/{sip}/answer"),
        ("POST", "/bridges"),
        ("POST", f"/bridges/br-{sip}/addChannel"),
        ("POST", f"/bridges/br-{sip}/addChannel"),
        ("POST", f"/bridges/br-{sip}/record"),
    ]


def test_inbound_context_carries_caller_and_sip_id(world) -> None:
    controller, ari, *_ = world
    run(
        controller,
        ev("StasisStart", "1789.2", args=["inbound"], channel={"caller": {"number": "1001"}, "dialplan": {"exten": "1000"}}),
    )
    variable = next(c for c in ari.calls if c[1].endswith("/variable"))
    ctx = json.loads(variable[2]["value"])
    assert ctx == {"call_type": "inbound", "from": "1001", "to": "1000", "sip_channel_id": "1789.2"}


def test_unreachable_bot_plays_an_apology_then_hangs_up(world) -> None:
    controller, ari, *_ = world
    ari.fail["/channels"] = ops.AriError(500, "Allocation failed")
    run(controller, ev("StasisStart", "1789.3", args=["inbound"], channel={}))
    paths = ari.paths()
    assert ("POST", "/channels/1789.3/play") in paths
    play = next(c for c in ari.calls if c[1] == "/channels/1789.3/play")
    assert play[2]["media"] == ops.UNREACHABLE_SOUND
    hangup = next(c for c in ari.calls if c[:2] == ("DELETE", "/channels/1789.3"))
    assert hangup[2] == {"reason": "normal"}
    assert ("POST", "/channels/1789.3/continue") not in paths


def test_unreachable_bot_never_dumps_the_caller_to_agents(world) -> None:
    controller, ari, *_ = world
    controller._agents = True
    ari.fail["/channels"] = ops.AriError(500, "Allocation failed")
    run(controller, ev("StasisStart", "1789.4", args=["inbound"], channel={}))
    assert ("POST", "/channels/1789.4/continue") not in ari.paths()
    assert ("POST", "/channels/1789.4/play") in ari.paths()


def test_unreachable_bot_marks_outbound_bot_unreachable(world) -> None:
    controller, ari, statuses, _t, _s = world
    sip = "att-CA-12"
    ari.fail["/channels"] = ops.AriError(500, "Allocation failed")
    run(controller, ev("StasisStart", sip, args=["outbound"]))
    assert statuses[-1]["status"] == "bot-unreachable"
    assert statuses[-1]["error_code"] == "bot_unreachable"
    assert ("POST", f"/channels/{sip}/continue") not in ari.paths()


# -- outbound --------------------------------------------------------------


def test_outbound_answered_call_reaches_completed_with_its_duration(world) -> None:
    controller, ari, statuses, _t, _s = world
    sip = "att-CA-7"
    ari.variables[sip] = json.dumps({"attempt_id": "CA-7", "call_type": "outbound"})
    run(
        controller,
        ev("ChannelStateChange", sip, channel={"state": "Ringing"}),
        ev("StasisStart", sip, args=["outbound"]),
        ev("StasisStart", f"{sip}-m"),
        ev("ChannelDestroyed", sip, cause=16),
    )
    assert [s["status"] for s in statuses] == ["ringing", "in-progress", "completed"]
    assert all(s["provider"] == "asterisk" and s["provider_call_id"] == sip for s in statuses)
    assert statuses[-1]["error_code"] == "q850:16"
    assert statuses[-1]["duration_sec"] is not None
    # The bot's leg and the bridge go with the caller.
    assert ("DELETE", f"/channels/{sip}-m") in ari.paths()
    assert ("DELETE", f"/bridges/br-{sip}") in ari.paths()


@pytest.mark.parametrize("cause, status", [(17, "busy"), (19, "no-answer"), (21, "rejected"), (1, "failed")])
def test_outbound_that_never_answered(world, cause, status) -> None:
    controller, _ari, statuses, _t, _s = world
    run(controller, ev("ChannelDestroyed", "att-CA-8", cause=cause))
    assert statuses[-1]["status"] == status
    assert statuses[-1]["duration_sec"] is None
    assert "att-CA-8" not in controller.calls


def test_a_refusal_that_beats_the_dialers_own_write_is_retried(world, monkeypatch) -> None:
    """busy/declined can arrive before outbound.place has committed the channel id;
    the first write then matches no row and the outcome used to be lost."""
    controller, _ari, statuses, _t, _s = world
    monkeypatch.setattr(ac, "STATUS_WRITE_WAIT_S", 0)
    tries: list[int] = []

    def writer(**kw):
        tries.append(1)
        statuses.append(kw)
        return None if len(tries) < 3 else {"id": "CA-11"}

    controller._write_status = writer
    run(controller, ev("ChannelDestroyed", "att-CA-11", cause=17))
    assert len(tries) == 3
    assert statuses[-1]["status"] == "busy"


def test_another_channel_on_the_pbx_is_not_mistaken_for_a_dial(world) -> None:
    """Local channels report as `<id>;1` / `<id>;2`, and a PBX carries calls this
    process did not place. Treating those as attempts retried status writes for
    rows that never existed."""
    controller, _ari, statuses, _t, _s = world
    run(
        controller,
        ev("ChannelDestroyed", "1789.9", cause=16),
        ev("ChannelDestroyed", "1789.9-m;2", cause=16),
    )
    assert statuses == []
    assert controller.calls == {}


def test_the_bot_hanging_up_clears_the_caller(world) -> None:
    controller, ari, *_ = world
    run(
        controller,
        ev("StasisStart", "1789.5", args=["inbound"], channel={}),
        ev("StasisStart", "1789.5-m"),
        ev("ChannelDestroyed", "1789.5-m", cause=16),
    )
    assert ari.calls[-1][:2] == ("DELETE", "/channels/1789.5")


# -- transfer and recording -------------------------------------------------


def test_the_caller_hanging_up_ends_the_call_and_releases_the_bot(world) -> None:
    """ARI sends StasisEnd and *no* ChannelDestroyed for a leg that entered the
    app. Waiting for the latter left the bot talking to a hung-up line for two
    minutes on a live call, and the attempt never reached a final state."""
    controller, ari, statuses, _t, _s = world
    sip = "att-CA-12"
    ari.variables[sip] = json.dumps({"attempt_id": "CA-12"})
    run(
        controller,
        ev("StasisStart", sip, args=["outbound"]),
        ev("StasisStart", f"{sip}-m"),
        ev("ChannelHangupRequest", sip, cause=16),
        ev("StasisEnd", sip),
    )
    assert statuses[-1]["status"] == "completed"
    assert statuses[-1]["error_code"] == "q850:16"
    assert ("DELETE", f"/channels/{sip}-m") in ari.paths()


def test_an_inbound_caller_hanging_up_releases_the_bot(world) -> None:
    controller, ari, statuses, _t, _s = world
    run(
        controller,
        ev("StasisStart", "1789.7", args=["inbound"], channel={}),
        ev("StasisStart", "1789.7-m"),
        ev("ChannelHangupRequest", "1789.7", cause=16),
        ev("StasisEnd", "1789.7"),
    )
    assert ("DELETE", "/channels/1789.7-m") in ari.paths()
    assert statuses == []  # an inbound call has no attempt to score


def test_a_transfer_marks_the_attempt_and_releases_the_bot(world) -> None:
    controller, ari, statuses, transferred, _s = world
    sip = "att-CA-9"
    ari.variables[sip] = json.dumps({"attempt_id": "CA-9"})
    run(
        controller,
        ev("StasisStart", sip, args=["outbound"]),
        ev("StasisStart", f"{sip}-m"),
        {"type": "ChannelVarset", "channel": {"id": sip}, "variable": "HABIBI_TRANSFER", "value": "x"},
        ev("StasisEnd", sip),
        ev("ChannelDestroyed", f"{sip}-m", cause=16),
    )
    assert transferred == ["CA-9"]
    assert ("DELETE", f"/channels/{sip}-m") in ari.paths()
    # The caller is with an agent now: nobody hangs them up, and no "completed".
    assert ("DELETE", f"/channels/{sip}") not in ari.paths()
    assert [s["status"] for s in statuses] == ["in-progress"]


def test_the_recording_is_stored_then_removed_from_the_pbx(world) -> None:
    controller, ari, _st, _t, stored = world
    run(
        controller,
        ev("StasisStart", "1789.6", args=["inbound"], channel={}),
        ev("StasisStart", "1789.6-m"),
        ev("ChannelDestroyed", "1789.6", cause=16),
        {"type": "RecordingFinished", "recording": {"name": "1789.6"}},
    )
    assert stored == [("1789.6", b"RIFFwav")]
    assert ari.paths()[-1] == ("DELETE", "/recordings/stored/1789.6")
    assert controller.calls == {}


def test_a_recording_that_finishes_first_does_not_rewrite_the_outcome(world) -> None:
    """RecordingFinished can beat the SIP leg's ChannelDestroyed."""
    controller, ari, statuses, _t, _s = world
    sip = "att-CA-10"
    ari.variables[sip] = json.dumps({"attempt_id": "CA-10"})
    run(
        controller,
        ev("StasisStart", sip, args=["outbound"]),
        ev("StasisStart", f"{sip}-m"),
        {"type": "RecordingFinished", "recording": {"name": sip}},
        ev("ChannelDestroyed", sip, cause=16),
    )
    assert statuses[-1]["status"] == "completed"
    assert controller.calls == {}


def test_recording_start_failure_plays_notice_then_hangs_up(world) -> None:
    controller, ari, *_ = world
    sip = "1789.8"
    ari.fail[f"/bridges/br-{sip}/record"] = ops.AriError(500, "record failed")
    run(
        controller,
        ev("StasisStart", sip, args=["inbound"], channel={}),
        ev("StasisStart", f"{sip}-m"),
    )
    paths = ari.paths()
    assert ("POST", f"/channels/{sip}/continue") not in paths
    play = next(c for c in ari.calls if c[1] == f"/channels/{sip}/play")
    assert play[2]["media"] == ops.RECORDING_UNAVAILABLE_SOUND
    hangup = next(c for c in ari.calls if c[:2] == ("DELETE", f"/channels/{sip}"))
    assert hangup[2] == {"reason": "normal"}


def test_recording_start_failure_marks_outbound_recording_unavailable(world) -> None:
    controller, ari, statuses, _t, _s = world
    sip = "att-CA-13"
    ari.fail[f"/bridges/br-{sip}/record"] = ops.AriError(500, "record failed")
    run(
        controller,
        ev("StasisStart", sip, args=["outbound"]),
        ev("StasisStart", f"{sip}-m"),
    )
    assert statuses[-1]["status"] == "recording-unavailable"
    assert statuses[-1]["error_code"] == "recording_unavailable"
    assert ("POST", f"/channels/{sip}/continue") not in ari.paths()
