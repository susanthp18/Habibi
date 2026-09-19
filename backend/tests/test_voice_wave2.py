"""Wave 2: CRM bind before disclosure; proof only after speech or fallback."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from voice.session import VoiceSession
from voice.tool_state import ToolBuildContext, ToolState
from voice.tools_identity import build


class _Rtvi:
    async def lifecycle(self, **_kw) -> None:
        return None


def _ctx(
    *,
    interaction_id: str | None = "IX-1",
    spoke: bool | None = True,
    start_recording=None,
    bind_task=None,
) -> tuple[ToolBuildContext, VoiceSession, ToolState]:
    session = VoiceSession(session_id="VS-W2")
    session.interaction_id = interaction_id
    if bind_task is not None:
        session.extra["_crm_bind_task"] = bind_task
    state = ToolState()
    spoke_fn = None if spoke is None else (lambda: spoke)
    ctx = ToolBuildContext(
        _FALLBACK_GREETING=(
            "Hello, this is Priya from HDFC Bank Collections. "
            "This call is recorded for quality and compliance. "
            "How can I help you today?"
        ),
        _node=lambda k: {"name": k},
        _spec=lambda *a, **k: None,
        bot_id="bot",
        inject_developer=None,
        rtvi=_Rtvi(),
        session=session,
        spoke_this_response=spoke_fn,
        start_recording=start_recording,
        state=state,
    )
    return ctx, session, state


def _handler(ctx: ToolBuildContext):
    fn = build(ctx)["disclose_recording"]
    inner = getattr(fn, "handler", fn)

    async def _call(flow_manager):
        try:
            return await inner(flow_manager)
        except TypeError:
            return await inner({}, flow_manager)

    return _call


def test_disclose_without_interaction_stays_no_interaction() -> None:
    ctx, _session, _state = _ctx(interaction_id=None)

    async def go():
        return await _handler(ctx)(SimpleNamespace())

    result, nxt = asyncio.run(go())
    assert result["error"] == "no_interaction"
    assert nxt is None


def test_disclose_waits_for_crm_bind_then_succeeds(monkeypatch) -> None:
    recorded: list[dict] = []
    monkeypatch.setattr(
        "voice.persist.record_disclosure",
        lambda **kw: recorded.append(kw),
    )
    started: list[int] = []

    async def _start():
        started.append(1)

    async def go():
        ctx, session, _state = _ctx(
            interaction_id=None,
            start_recording=_start,
        )

        async def _bind():
            await asyncio.sleep(0.02)
            session.interaction_id = "IX-BOUND"

        session.extra["_crm_bind_task"] = asyncio.create_task(_bind())
        result, nxt = await _handler(ctx)(SimpleNamespace())
        return result, nxt

    result, nxt = asyncio.run(go())
    assert result.get("ok") is True
    assert result.get("disclosed") is True
    assert recorded and recorded[0]["interaction_id"] == "IX-BOUND"
    assert started == [1]
    assert nxt is not None


def test_disclosure_without_speech_or_fallback_does_not_write(monkeypatch) -> None:
    monkeypatch.setattr(
        "voice.persist.record_disclosure",
        lambda **kw: (_ for _ in ()).throw(AssertionError("wrote disclosure without speech")),
    )
    ctx, _session, state = _ctx(spoke=False)

    async def go():
        return await _handler(ctx)(SimpleNamespace(worker=None))

    result, nxt = asyncio.run(go())
    assert result["error"] == "disclosure_not_spoken"
    assert nxt is None
    assert state.disclosure_done is False


def test_start_recording_failure_is_not_disclosed(monkeypatch) -> None:
    monkeypatch.setattr(
        "voice.persist.record_disclosure",
        lambda **kw: (_ for _ in ()).throw(AssertionError("proof row despite recording failure")),
    )

    async def _fail():
        raise RuntimeError("media down")

    ctx, _session, state = _ctx(start_recording=_fail)

    async def go():
        return await _handler(ctx)(SimpleNamespace())

    result, nxt = asyncio.run(go())
    assert result["error"] == "recording_not_started"
    assert result.get("disclosed") is False
    assert nxt is None
    assert state.disclosure_done is False
