"""Wave 3: outbound last-4 prefer, CTX fail-closed, embedded admission, AMD skip."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from agent_core.live_qa.checks import TurnFacts, check_hours
from voice.bot_flow import resolve_call_direction
from voice.session import VoiceSession


def test_lookup_prefers_bound_customer_when_tail_collides(monkeypatch) -> None:
    from voice import persist

    preferred = {
        "customer_id": "C-BOUND",
        "name": "Asha",
        "phone_primary": "9876543210",
        "account_id": "AC-1",
        "outstanding": 100,
        "minimum_due": 10,
        "dpd": 5,
    }
    captured: list[dict] = []

    class _Maps:
        def __init__(self, row):
            self._row = row

        def first(self):
            return self._row

        def all(self):
            return [self._row, {**self._row, "customer_id": "C-OTHER"}]

    class _Result:
        def __init__(self, row):
            self._row = row

        def mappings(self):
            return _Maps(self._row)

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, _sql, params):
            captured.append(dict(params))
            if params.get("prefer") == "C-BOUND":
                return _Result(preferred)
            return _Result(None)

    monkeypatch.setattr("db.engine.connect", lambda: _Conn())
    monkeypatch.setattr("db.current_tenant", lambda: "hdfc.retail")
    monkeypatch.setattr("db._find_customer_by_phone", lambda *_a, **_k: None)
    found = persist.lookup_customer_for_verify(
        method="phone_match",
        value="3210",
        prefer_customer_id="C-BOUND",
    )
    assert found is not None
    assert found["customerId"] == "C-BOUND"
    assert any(p.get("prefer") == "C-BOUND" for p in captured)


def test_inbound_last4_collision_still_refuses(monkeypatch) -> None:
    from voice import persist

    row = {
        "customer_id": "C1",
        "name": "A",
        "phone_primary": "11113210",
        "account_id": "AC-1",
        "outstanding": 1,
        "minimum_due": 1,
        "dpd": 1,
    }

    class _Maps:
        def first(self):
            return None

        def all(self):
            return [row, {**row, "customer_id": "C2"}]

    class _Result:
        def mappings(self):
            return _Maps()

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *_a, **_k):
            return _Result()

    monkeypatch.setattr("db.engine.connect", lambda: _Conn())
    monkeypatch.setattr("db.current_tenant", lambda: "hdfc.retail")
    monkeypatch.setattr("db._find_customer_by_phone", lambda *_a, **_k: None)
    found = persist.lookup_customer_for_verify(method="phone_match", value="3210")
    assert found is None


def test_verify_tool_passes_prefer_on_outbound(monkeypatch) -> None:
    from voice import persist
    from voice import tools as voice_tools
    from voice.session import VoiceSession

    captured: list[dict] = []

    def _lookup(**kw):
        captured.append(kw)
        return None

    monkeypatch.setattr(persist, "lookup_customer_for_verify", _lookup)
    monkeypatch.setattr(persist, "record_identity_verification", lambda **_k: None)

    session = VoiceSession(session_id="VS-PREF", customer_id="C-BOUND")
    session.interaction_id = "IX-PREF"
    session.extra["call_direction"] = "outbound"

    async def go():
        _state, tools = voice_tools.build_tools(
            session, bot_id=None, start_recording=None, nodes={}
        )
        return await tools["verify_identity"].handler(
            {"method": "phone_match", "value": "3210"}, None
        )

    asyncio.run(go())
    assert captured
    assert captured[0].get("prefer_customer_id") == "C-BOUND"


def test_invalid_ctx_is_hours_outbound() -> None:
    session = VoiceSession(session_id="VS-CTX")
    session.extra["twilio_params"] = {"ctx_invalid": "1"}
    direction = resolve_call_direction(session, {})
    assert direction == "outbound"
    finding = check_hours(
        TurnFacts(channel="voice", now_hour=19, direction=direction, bot_text="hi")
    )
    assert finding is not None
    assert finding.check_id == "hours-breach"


def test_embedded_bot_holds_slot_until_worker_ends(monkeypatch) -> None:
    from voice import admission
    from voice import bot as bot_mod

    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "1")
    admission.reset_for_tests()
    held: list[int] = []

    async def _session(runner_args):
        async def _hang():
            await asyncio.sleep(0.15)

        task = asyncio.create_task(_hang())
        runner_args.voice_worker = SimpleNamespace(name="w1")
        runner_args.shared_runner = SimpleNamespace(
            _entries={"w1": SimpleNamespace(runner_task=task)}
        )

    monkeypatch.setattr(bot_mod, "_bot_session", _session)

    async def go():
        ws = SimpleNamespace(closed_with=None)

        async def close(code=1000):
            ws.closed_with = code

        ws.close = close
        task = asyncio.create_task(bot_mod.bot(SimpleNamespace(websocket=ws)))
        await asyncio.sleep(0.05)
        held.append(admission.in_flight())
        await task
        held.append(admission.in_flight())

    asyncio.run(go())
    admission.reset_for_tests()
    assert held[0] == 1
    assert held[-1] == 0


def test_has_capacity_reaps_stale_slots(monkeypatch) -> None:
    from voice import admission

    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "1")
    admission.reset_for_tests()
    monkeypatch.setattr(admission, "max_slot_age", lambda: 0.02)
    admission.acquire()
    time.sleep(0.04)
    try:
        assert admission.has_capacity() is True
    finally:
        admission.reset_for_tests()


def test_greeting_incomplete_skip_does_not_close_classifier() -> None:
    from voice.amd import attach_voicemail_handlers

    class _Det:
        def event_handler(self, name):
            def deco(fn):
                setattr(self, name, fn)
                return fn

            return deco

    class _Proc:
        async def push_frame(self, *a, **_k):
            return None

    async def go():
        det = _Det()
        session = SimpleNamespace(session_id="VS-AMD-SKIP", extra={}, interaction_id=None)
        await attach_voicemail_handlers(
            voicemail_detector=det,
            session=session,
            sink=SimpleNamespace(),
            worker=SimpleNamespace(),
            bot_turn_state=SimpleNamespace(
                speaking=lambda: False,
                busy=lambda: False,
                has_spoken=lambda: False,
            ),
        )
        det._habibi_guard = SimpleNamespace(seen_speech=True)
        await det.on_voicemail_detected(_Proc())
        assert session.extra.get("amd") != "voicemail"
        assert session.extra.get("amd_closed") is not True

    asyncio.run(go())
