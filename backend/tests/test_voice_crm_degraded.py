"""A collections call must never end with no record that it happened.

Three failures used to compose into that outcome:

* ``bot.py`` caught a failed ``bind_session_start``, logged "call continues
  without DB" and carried on with ``session.interaction_id`` still None;
* every CRM writer in ``crm_sink.py`` guards on that id with a bare ``return``,
  so the whole call's transcript turns, tool-call audit rows, live alerts and
  guardrail violations were discarded — without one line in the log;
* teardown's ``complete`` job hit the same guard, so nothing closed either.

The result was a real call to a real borrower with nothing in the CRM and
nothing in the log to say so. These tests hold the three pieces of the fix: the
flag is set, the loss is visible, and the call is filed anyway.
"""

from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest

from voice import crm_sink as cs
from voice.crm_sink import CRM_DEGRADED_DISPOSITION, CrmSink, mark_crm_degraded
from voice.session import VoiceSession


def _session(**kw: Any) -> VoiceSession:
    session = VoiceSession(session_id="VS-DEGRADED01", **kw)
    session.extra["bot_id"] = "bot-collections"
    session.extra["call_direction"] = "outbound"
    return session


@pytest.fixture
def quiet_persist(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Replace every ``persist`` call the teardown path makes.

    The sink is a database writer, so a test that let it reach Postgres would be
    asserting on the schema rather than on the drop-and-degrade logic.
    """
    seen: dict[str, list[Any]] = {"start": [], "complete": []}

    def _start(**kwargs: Any) -> dict[str, Any]:
        seen["start"].append(kwargs)
        return {
            "sessionId": kwargs["session_id"],
            "interactionId": "CL-DEGRADED1",
            "customerId": "UNKNOWN-CALLER",
            "accountId": None,
            "botId": kwargs.get("bot_id"),
            "startedAt": kwargs.get("started_at"),
        }

    monkeypatch.setattr(cs.persist, "start_voice_call", _start)
    monkeypatch.setattr(
        cs.persist, "complete_voice_call", lambda **kw: seen["complete"].append(kw)
    )
    monkeypatch.setattr(cs.persist, "export_transcript_json", lambda **kw: None)
    monkeypatch.setattr(cs.persist, "heartbeat", lambda *a, **k: None)
    monkeypatch.setattr(CrmSink, "_write_customer_memory", lambda self, ix, p: None)
    return seen


# --- the flag ---------------------------------------------------------------


def test_bind_failure_marks_the_session_degraded(caplog: pytest.LogCaptureFixture) -> None:
    session = _session()
    assert session.crm_degraded is False

    with caplog.at_level(logging.ERROR, logger=cs.__name__):
        try:
            raise RuntimeError("connection refused")
        except RuntimeError as exc:
            mark_crm_degraded(session, exc)

    assert session.crm_degraded is True
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert "crm_persistence_degraded" in errors[0].getMessage()
    assert session.session_id in errors[0].getMessage()
    # The traceback rides along; the cause is the first thing anyone asks for.
    assert errors[0].exc_info is not None


def test_the_connect_path_actually_calls_it() -> None:
    """``bot.py``'s bind handler must degrade, not just log.

    Read from the source rather than by running ``run_bot``, which needs a live
    transport and a Pipecat pipeline. What this pins is the exact regression:
    the handler around ``bind_session_start`` going back to a lone
    ``logger.exception`` that leaves the session looking healthy.
    """
    tree = ast.parse(Path(cs.__file__).with_name("bot.py").read_text(encoding="utf-8"))

    def _names(node: ast.AST) -> set[str]:
        # Plain identifiers, not just call targets: bind_session_start reaches
        # the thread pool as an *argument* to asyncio.to_thread.
        return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}

    binds = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        and any("bind_session_start" in _names(stmt) for stmt in node.body)
    ]
    assert binds, "no try/except around bind_session_start in voice/bot.py"
    for node in binds:
        degraded = any(
            "mark_crm_degraded" in _names(handler) for handler in node.handlers
        )
        assert degraded, "a failed CRM bind must mark the session degraded"


# --- the visible loss -------------------------------------------------------


def test_a_dropped_job_is_logged_once_per_session(caplog: pytest.LogCaptureFixture) -> None:
    sink = CrmSink(_session())

    with caplog.at_level(logging.ERROR, logger=cs.__name__):
        for _ in range(50):
            sink._note_dropped("transcript_turn")
        sink._note_dropped("live_alert")

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    # Once — not 51 times. A line per lost turn would be the loudest thing in
    # the log on exactly the call that already went wrong, and would be filtered.
    assert len(errors) == 1
    assert "transcript_turn" in errors[0].getMessage()
    assert sink._dropped_jobs == {"transcript_turn": 50, "live_alert": 1}


def test_the_per_kind_totals_are_reported_at_teardown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = CrmSink(_session())
    sink._note_dropped("transcript_turn")
    sink._note_dropped("transcript_turn")
    sink._note_dropped("tool_call")

    with caplog.at_level(logging.WARNING, logger=cs.__name__):
        sink._report_dropped()

    summary = "\n".join(r.getMessage() for r in caplog.records)
    assert "transcript_turn=2" in summary
    assert "tool_call=1" in summary
    assert "total=3" in summary


def test_a_clean_session_reports_nothing(caplog: pytest.LogCaptureFixture) -> None:
    sink = CrmSink(_session())
    with caplog.at_level(logging.DEBUG, logger=cs.__name__):
        sink._report_dropped()
    assert caplog.records == []


def test_the_id_guards_count_their_drops(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guards themselves, not just the counter behind them.

    Each of these is a place that used to be a bare ``return``. The drop is
    still the right behaviour — there is no id to write against — so what is
    asserted is that it is now counted rather than silent.
    """
    import agent_core.understanding as understanding

    class _Result:
        intent = "hardship"
        intent_score = 0.9
        sentiment = -0.2
        # The refined result. A keyword one returns before the persist guard —
        # it has nothing to correct — so it is the LLM pass whose loss counts.
        source = "llm"

    monkeypatch.setattr(understanding, "analyze_turn", lambda *a, **k: _Result())

    sink = CrmSink(_session())
    assert sink.session.interaction_id is None

    sink._handle_sync(cs._Job("transcript_turn", {"text": "hello"}))
    sink._handle_sync(cs._Job("tool_call", {"tool_name": "get_account_position"}))
    sink._handle_understanding(cs._Job("understanding", {"turn_index": 1, "text": "hi"}))
    asyncio.run(sink.enqueue_alert("compliance", "hours-breach"))

    assert sink._dropped_jobs == {
        "transcript_turn": 1,
        "tool_call": 1,
        "turn_understanding": 1,
        "live_alert": 1,
    }


def test_escalation_still_happens_when_its_alert_is_dropped() -> None:
    """Losing the audit row must not cost the caller their human.

    The alert that tells the floor console *why* is gone — which is what the
    counter is for — but the escalation handler still runs.
    """
    sink = CrmSink(_session())
    escalated: list[tuple[str, str]] = []

    async def _on_escalate(reason: str, detail: str) -> None:
        escalated.append((reason, detail))

    sink.configure_live_handlers(on_escalate=_on_escalate)
    asyncio.run(sink._trigger_escalate("hardship", "caller asked for a manager"))

    assert escalated == [("hardship", "caller asked for a manager")]
    assert sink._dropped_jobs == {"live_alert_escalation": 1}


# --- the call is filed anyway -----------------------------------------------


def test_teardown_files_a_minimal_interaction_for_a_degraded_call(
    quiet_persist: dict[str, list[Any]],
) -> None:
    session = _session()
    mark_crm_degraded(session)
    sink = CrmSink(session, direction="inbound")

    asyncio.run(sink.stop())

    assert len(quiet_persist["start"]) == 1
    filed = quiet_persist["start"][0]
    # The bind's own resolution, not the sink's default: a thin row must not
    # also be wrong about who answered or which way the call went.
    assert filed["bot_id"] == "bot-collections"
    assert filed["direction"] == "outbound"
    # The moment the borrower answered — so the duration is the real one and
    # not a teardown artefact.
    assert filed["started_at"] == session.call_started_at
    assert session.interaction_id == "CL-DEGRADED1"

    assert len(quiet_persist["complete"]) == 1
    completed = quiet_persist["complete"][0]
    assert completed["interaction_id"] == "CL-DEGRADED1"
    assert completed["disposition"] == CRM_DEGRADED_DISPOSITION
    # force_summary would overwrite the disposition we just wrote, so a summary
    # has to go with it.
    assert completed["summary"]


def test_a_healthy_call_files_nothing_extra_and_keeps_its_disposition(
    quiet_persist: dict[str, list[Any]],
) -> None:
    session = _session(interaction_id="CL-REAL0001")
    sink = CrmSink(session)

    asyncio.run(sink.stop())

    assert quiet_persist["start"] == []
    assert quiet_persist["complete"][0]["disposition"] is None
    assert quiet_persist["complete"][0]["interaction_id"] == "CL-REAL0001"


def test_a_bind_that_succeeded_is_not_labelled_degraded(
    quiet_persist: dict[str, list[Any]],
) -> None:
    """Degraded is "no interaction row", not "something went wrong later".

    ``sink.start()`` shares the connect path's try block, so it can set the flag
    on a call whose bind already succeeded. That call's row exists and the queue
    drains into it at teardown — reporting it as ``crm_degraded`` would file a
    second wrong record instead of a thin true one.
    """
    session = _session(interaction_id="CL-REAL0002")
    mark_crm_degraded(session)
    sink = CrmSink(session)

    asyncio.run(sink.stop())

    assert quiet_persist["start"] == []
    assert quiet_persist["complete"][0]["disposition"] is None


def test_a_degraded_call_that_cannot_be_filed_says_so(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The last resort has a floor: it must not become another quiet return."""

    def _boom(**kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("postgres is still down")

    monkeypatch.setattr(cs.persist, "start_voice_call", _boom)
    session = _session()
    mark_crm_degraded(session)
    sink = CrmSink(session)

    with caplog.at_level(logging.ERROR, logger=cs.__name__):
        sink._file_degraded_interaction()

    assert session.interaction_id is None
    assert any("this call is unrecorded" in r.getMessage() for r in caplog.records)
