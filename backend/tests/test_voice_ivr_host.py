"""IVR navigation gating + embedded worker host lifecycle.

Both features are opt-in and telephony-shaped, so the tests that matter are the
*negative* ones: Sandbox Live and inbound legs must not pick up an IVR
classifier, and a disabled embedded host must not mount signalling routes or
claim the voice runtime is up.
"""

from __future__ import annotations

import asyncio

import pytest


# --------------------------------------------------------------------------
# IVR / DTMF gating
# --------------------------------------------------------------------------


@pytest.fixture
def ivr(monkeypatch):
    from voice import ivr as mod

    return mod


def _enable(monkeypatch, **flags):
    for name, value in flags.items():
        monkeypatch.setenv(name, "true" if value else "false")


def test_ivr_off_by_default(ivr, monkeypatch):
    monkeypatch.delenv("VOICE_IVR_ENABLED", raising=False)
    assert ivr.should_enable_ivr({"call_type": "outbound"}, is_twilio=True) is False


def test_ivr_outbound_twilio_only(ivr, monkeypatch):
    _enable(monkeypatch, VOICE_IVR_ENABLED=True)
    assert ivr.should_enable_ivr({"call_type": "outbound"}, is_twilio=True) is True
    # Inbound callers reach a human bot directly — no menu to navigate.
    assert ivr.should_enable_ivr({"call_type": "inbound"}, is_twilio=True) is False
    # Sandbox Live: a browser peer is always a human with no keypad.
    assert ivr.should_enable_ivr({"call_type": "outbound"}, is_twilio=False) is False


def test_ivr_reads_call_type_from_twilio_params(ivr, monkeypatch):
    _enable(monkeypatch, VOICE_IVR_ENABLED=True)
    extra = {"twilio_params": {"call_type": "outbound"}}
    assert ivr.should_enable_ivr(extra, is_twilio=True) is True


def test_dtmf_input_gated_and_telephony_only(ivr, monkeypatch):
    _enable(monkeypatch, VOICE_DTMF_INPUT_ENABLED=True)
    assert ivr.should_enable_dtmf_input(is_twilio=True) is True
    assert ivr.should_enable_dtmf_input(is_twilio=False) is False
    _enable(monkeypatch, VOICE_DTMF_INPUT_ENABLED=False)
    assert ivr.should_enable_dtmf_input(is_twilio=True) is False


def test_default_goal_forbids_disclosing_customer_identifiers(ivr):
    goal = ivr.ivr_goal(None)
    lowered = goal.lower()
    # We are calling a third party's menu on the customer's behalf; keying their
    # account number or PIN into it would be a disclosure.
    assert "account number" in lowered
    assert "pin" in lowered
    assert "human" in lowered or "agent" in lowered


def test_goal_override_per_call(ivr):
    assert ivr.ivr_goal({"twilio_params": {"ivr_goal": "reach billing"}}) == "reach billing"
    assert ivr.ivr_goal({"ivr_goal": "  "}) == ivr.DEFAULT_IVR_GOAL


def test_navigator_construction_failure_is_not_fatal(ivr):
    """A bad LLM handle must degrade to a normal call, not kill the dial."""
    assert ivr.build_ivr_navigator(llm=None, session_extra={}) is None


def test_dtmf_aggregator_labels_keypad_input(ivr):
    agg = ivr.build_dtmf_aggregator()
    if agg is None:
        pytest.skip("DTMFAggregator not available in this Pipecat build")
    assert "keypad" in getattr(agg, "_prefix", "").lower()


# --------------------------------------------------------------------------
# Embedded worker host
# --------------------------------------------------------------------------


def test_host_disabled_mounts_nothing(monkeypatch):
    from voice import host

    monkeypatch.delenv("VOICE_EMBEDDED_HOST", raising=False)
    assert host.embedded_host_enabled() is False

    class _App:
        def post(self, *a, **k):
            raise AssertionError("route mounted while host is disabled")

        patch = post

    host.register_routes(_App())  # must be a no-op


def test_host_enabled_mounts_both_offer_paths(monkeypatch):
    from voice import host

    monkeypatch.setenv("VOICE_EMBEDDED_HOST", "true")
    mounted: list[tuple[str, str]] = []

    class _App:
        def post(self, path, **k):
            mounted.append(("POST", path))
            return lambda fn: fn

        def patch(self, path, **k):
            mounted.append(("PATCH", path))
            return lambda fn: fn

    host.register_routes(_App())
    paths = {p for _, p in mounted}
    # /api/offer serves a dev proxy that strips the prefix; /voice-rtc/api/offer
    # serves a browser hitting the API directly (production, same origin).
    assert paths == {"/api/offer", "/voice-rtc/api/offer"}
    assert len(mounted) == 4


def test_voice_status_does_not_probe_when_embedded(monkeypatch):
    import voice_sandbox

    monkeypatch.setenv("VOICE_EMBEDDED_HOST", "true")

    def _explode(*a, **k):
        raise AssertionError("must not probe :7860 when hosting in-process")

    monkeypatch.setattr(voice_sandbox.httpx, "Client", _explode)
    status = voice_sandbox.voice_status()
    assert status["ok"] is True
    assert status["webrtcUrl"]


def test_shared_runner_hosts_concurrent_calls_and_prunes(monkeypatch):
    """One long-lived runner, many calls, no registry growth across hangups."""
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineWorker
    from pipecat.processors.frame_processor import FrameProcessor

    from voice import host

    monkeypatch.setenv("VOICE_EMBEDDED_HOST", "true")

    async def scenario():
        runner = await host.get_runner()
        try:
            a = PipelineWorker(Pipeline([FrameProcessor()]))
            b = PipelineWorker(Pipeline([FrameProcessor()]))
            await runner.add_workers(a)
            await runner.add_workers(b)
            await asyncio.sleep(0.2)
            assert len(runner._entries) == 2, "concurrent calls must coexist"

            await a.cancel()
            await host.release_worker(runner, a)
            assert a.name not in runner._entries
            # The other call is untouched — the runner outlives any one session.
            assert b.name in runner._entries
        finally:
            await host.shutdown()

    asyncio.run(scenario())
    # shutdown() clears module state so a later call starts a fresh runner.
    assert host._runner is None


def test_release_worker_survives_pipecat_internal_rename(monkeypatch):
    from voice import host

    class _Opaque:
        pass

    async def scenario():
        # No _entries / _registry at all — must not raise.
        await host.release_worker(_Opaque(), type("W", (), {"name": "w"})())

    asyncio.run(scenario())
