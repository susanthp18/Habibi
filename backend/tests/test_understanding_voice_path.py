"""Turn understanding never touches the Pipecat audio path.

``CrmSink.attach_aggregators`` installs ``_on_user_turn_stopped`` as a Pipecat
event handler, which Pipecat **awaits on the pipeline task**. Anything slow in
there is added directly to the caller's turn latency, and an Azure call is worth
up to 20 seconds of it.

It is also a single FIFO with a 15-second teardown budget shared with
``live_alert`` (compliance escalations the Inbox renders) and ``complete`` (call
closure), so parking an LLM call in the main queue would head-of-line-block real
CRM writes.

Hence the separate analysis queue. These tests pin that separation, because a
future refactor that "simplifies" the two queues into one would reintroduce both
failures silently — the code would still work, calls would just get slower and
occasionally lose their closing writes.
"""

from __future__ import annotations

import asyncio

import pytest

from voice.crm_sink import CrmSink
from voice.session import VoiceSession


@pytest.fixture
def sink() -> CrmSink:
    return CrmSink(VoiceSession(session_id="VS-TEST", interaction_id="IX-TEST"))


class _Aggregator:
    """Minimal stand-in for a Pipecat aggregator's event_handler decorator."""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def event_handler(self, name: str):
        def _wrap(fn):
            self.handlers[name] = fn
            return fn

        return _wrap


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content
        self.interrupted = False


def _attach(sink: CrmSink) -> tuple[_Aggregator, _Aggregator]:
    user, assistant = _Aggregator(), _Aggregator()
    sink.attach_aggregators(user, assistant)
    return user, assistant


# ---------------------------------------------------------------------------
# The audio path stays clean
# ---------------------------------------------------------------------------


def test_user_turn_handler_makes_no_azure_call(sink: CrmSink, monkeypatch) -> None:
    """The constraint the whole design hangs on."""
    import azure_openai

    def _boom(*_a, **_kw):
        raise AssertionError("Azure called from the audio path")

    monkeypatch.setattr(azure_openai, "chat_with_tools", _boom)
    monkeypatch.setattr(azure_openai, "chat_complete", _boom)
    monkeypatch.setenv("UNDERSTANDING_LLM_ENABLED", "true")

    user, _ = _attach(sink)
    asyncio.run(user.handlers["on_user_turn_stopped"](None, None, _Message("paisa nahi hai")))


def test_user_turn_handler_only_queues(sink: CrmSink, monkeypatch) -> None:
    """No DB write, no thread, no await on anything slow — just two enqueues."""
    monkeypatch.setattr("voice.persist.score_customer_text", lambda t: (-0.2, "negative"))

    user, _ = _attach(sink)
    asyncio.run(user.handlers["on_user_turn_stopped"](None, None, _Message("kitna bakaya hai")))

    assert sink._queue.qsize() == 1  # customer_turn
    assert sink._analysis_queue.qsize() == 1  # understanding
    assert sink._queue.get_nowait().kind == "customer_turn"
    assert sink._analysis_queue.get_nowait().kind == "understanding"


def test_analysis_uses_a_separate_queue_from_crm_writes(sink: CrmSink) -> None:
    """A slow classifier must not delay a compliance alert or call closure."""
    sink.enqueue_understanding(turn_index=1, text="hello", prior_intent=None)
    sink.enqueue("live_alert", alert_kind="escalation", reason="abuse")

    assert sink._analysis_queue.qsize() == 1
    assert sink._queue.qsize() == 1
    assert sink._queue.get_nowait().kind == "live_alert"


def test_self_correction_shares_the_analysis_queue_not_the_crm_one(
    sink: CrmSink, monkeypatch
) -> None:
    """The critic is the second Azure caller on this sink. It inherits the same
    separation for the same reason — its LLM call must never sit in front of a
    compliance escalation."""
    monkeypatch.setenv("TURN_CRITIC_ENABLED", "true")

    async def _noop(_c):
        return None

    sink.configure_live_handlers(on_correction=_noop)
    sink.enqueue_critique(
        bot_text="a bot turn", user_text="a caller turn", guardrail_flags=[], recent_bot_turns=[]
    )
    sink.enqueue("live_alert", alert_kind="escalation", reason="abuse")

    assert sink._analysis_queue.qsize() == 1
    assert sink._analysis_queue.get_nowait().kind == "critique"
    assert sink._queue.get_nowait().kind == "live_alert"


def test_bot_turn_snapshot_excludes_the_turn_being_judged(sink: CrmSink) -> None:
    """`_recent_bot_texts` has already grown by the time the drain runs, so the
    repetition check has to compare against a snapshot taken at enqueue time —
    otherwise every turn matches itself and scores 1.0."""
    line = "Your outstanding balance is sixty two thousand four hundred rupees."
    _attach(sink)
    # Driven from the LLM→TTS probe now, not the assistant aggregator — see
    # CrmSink.record_bot_turn.
    asyncio.run(sink.record_bot_turn(line))

    job = None
    while not sink._queue.empty():
        candidate = sink._queue.get_nowait()
        if candidate is not None and candidate.kind == "bot_turn":
            job = candidate
    assert job is not None
    assert line not in (job.payload.get("prior_bot_turns") or [])
    assert line in sink._recent_bot_texts


# ---------------------------------------------------------------------------
# Backlog handling
# ---------------------------------------------------------------------------


def test_backlog_drops_oldest(sink: CrmSink) -> None:
    """A backlog means Azure is slower than the caller is talking.

    A classification four turns stale is worth less than the keyword one the
    session already has, so the queue is bounded rather than unbounded.
    """
    for i in range(1, 9):
        sink.enqueue_understanding(turn_index=i, text=f"turn {i}", prior_intent=None)

    assert sink._analysis_queue.qsize() <= CrmSink._ANALYSIS_MAX_DEPTH
    remaining = []
    while not sink._analysis_queue.empty():
        remaining.append(sink._analysis_queue.get_nowait().payload["turn_index"])
    # The newest turns survived, not the oldest.
    assert remaining[-1] == 8


def test_closed_sink_ignores_new_analysis(sink: CrmSink) -> None:
    sink._closed = True
    sink.enqueue_understanding(turn_index=1, text="hello", prior_intent=None)
    assert sink._analysis_queue.qsize() == 0


# ---------------------------------------------------------------------------
# Publication onto the session
# ---------------------------------------------------------------------------


def test_result_lands_on_the_session(sink: CrmSink, monkeypatch) -> None:
    monkeypatch.setenv("UNDERSTANDING_LLM_ENABLED", "false")
    monkeypatch.setattr("voice.persist.update_turn_understanding", lambda **kw: True)

    sink._handle_understanding(_job(turn_index=3, text="I cannot pay this month"))

    assert sink.session.understanding is not None
    assert sink.session.understanding.intent == "hardship"
    assert sink.session.understanding_turn_index == 3


def test_a_late_result_cannot_overwrite_a_newer_turn(sink: CrmSink, monkeypatch) -> None:
    """FIFO ordering is not enough: a slow call can land after a later one."""
    monkeypatch.setenv("UNDERSTANDING_LLM_ENABLED", "false")

    sink._handle_understanding(_job(turn_index=5, text="I want to pay now"))
    assert sink.session.understanding.intent == "payment_intent"

    sink._handle_understanding(_job(turn_index=2, text="I cannot pay, lost my job"))

    assert sink.session.understanding_turn_index == 5
    assert sink.session.understanding.intent == "payment_intent"


def test_keyword_result_is_still_published(sink: CrmSink, monkeypatch) -> None:
    """With the LLM off, the session still carries a classification.

    That is what the offer engine and lead capture read — better than each of
    them re-deriving their own from the raw text.
    """
    monkeypatch.setenv("UNDERSTANDING_LLM_ENABLED", "false")

    sink._handle_understanding(_job(turn_index=1, text="what is my balance"))

    assert sink.session.understanding.source == "keyword"
    assert sink.session.understanding.intent == "balance_query"


def test_keyword_result_does_not_rewrite_the_persisted_row(sink: CrmSink, monkeypatch) -> None:
    """The keyword pass already wrote it from the audio path."""
    calls: list[dict] = []
    monkeypatch.setenv("UNDERSTANDING_LLM_ENABLED", "false")
    monkeypatch.setattr(
        "voice.persist.update_turn_understanding", lambda **kw: calls.append(kw) or True
    )

    sink._handle_understanding(_job(turn_index=1, text="what is my balance"))

    assert calls == []


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------


def test_teardown_abandons_a_stuck_analysis(sink: CrmSink) -> None:
    """Nobody is waiting on a refined intent once the call is over.

    Timed around ``_stop_analysis`` itself, not around ``asyncio.run``: a hung
    ``to_thread`` worker cannot be interrupted, so the loop's own shutdown will
    always wait for it. What matters in production is that teardown *returns*
    promptly and hands the 15-second CRM budget over intact — the orphaned
    thread finishes on its own with nobody reading its result.
    """
    import time as _time

    elapsed = 0.0

    async def _run() -> None:
        nonlocal elapsed
        sink._ANALYSIS_STOP_TIMEOUT_S = 0.05
        await sink.start()
        # A handler that never returns, standing in for a hung Azure call.
        sink._analysis_queue.put_nowait(_job(turn_index=1, text="hello"))
        started = _time.perf_counter()
        await sink._stop_analysis()
        elapsed = _time.perf_counter() - started

    def _hang(_job_arg):
        _time.sleep(3)

    original = CrmSink._handle_understanding
    CrmSink._handle_understanding = lambda self, job: _hang(job)  # type: ignore[assignment]
    try:
        asyncio.run(_run())
    finally:
        CrmSink._handle_understanding = original  # type: ignore[assignment]

    # Bounded by the analysis deadline, nowhere near the hung call's 3s.
    assert elapsed < 1.0
    assert sink._analysis_task is None


def _job(*, turn_index: int, text: str):
    from voice.crm_sink import _Job

    return _Job("understanding", {"turn_index": turn_index, "text": text, "prior_intent": None})
