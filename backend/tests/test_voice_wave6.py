"""Wave 6 reconstructibility: transcript, sentiment, closer, AMD, analysis drops."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from voice.crm_sink import CrmSink, _Job
from voice.session import VoiceSession


def _sink() -> CrmSink:
    return CrmSink(VoiceSession(session_id="VS-W6", interaction_id="IX-W6"))


class _Aggregator:
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


def _attach(sink: CrmSink):
    user, assistant = _Aggregator(), _Aggregator()
    sink.attach_aggregators(user, assistant)
    return user


def test_sentiment_correction_keys_the_transcript_turn(monkeypatch) -> None:
    """A late LLM correction must not rewrite a newer sparkline point."""
    from voice import persist

    captured: list[tuple[str, dict]] = []

    class _Result:
        rowcount = 1

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            captured.append((str(sql), dict(params or {})))
            return _Result()

    monkeypatch.setattr("db.engine.begin", lambda: _Conn())
    persist.update_turn_understanding(
        interaction_id="IX-W6",
        turn_index=3,
        intent="hardship",
        intent_score=0.9,
        sentiment=-0.4,
    )
    sentiment_sql, sentiment_params = captured[1]
    assert "interaction_transcript" in sentiment_sql
    assert "turn_index" in sentiment_params
    assert sentiment_params["turn_index"] == 3
    assert "ORDER BY at_sec DESC" not in sentiment_sql.replace("\n", " ")


def test_customer_turn_first_write_uses_resolve_intent(monkeypatch) -> None:
    """Audio-path persist and the keyword baseline share one vocabulary."""
    sink = _sink()
    sink.session.understanding = SimpleNamespace(intent="product_faq")
    monkeypatch.setattr("voice.persist.score_customer_text", lambda t: (0.1, "neutral"))
    user = _attach(sink)
    asyncio.run(user.handlers["on_user_turn_stopped"](None, None, _Message("go ahead")))
    job = sink._queue.get_nowait()
    assert job.kind == "customer_turn"
    assert job.payload["intent"] == "product_faq"


def test_bot_turn_intent_stays_on_the_customer_turn_it_answers(monkeypatch) -> None:
    """session.understanding can race ahead; the reply must not follow it."""
    from agent_core.understanding import TurnUnderstanding

    sink = _sink()
    monkeypatch.setattr("voice.persist.score_customer_text", lambda t: (0.0, "neutral"))
    monkeypatch.setattr("voice.persist.record_turn_perception", lambda **_k: None)
    monkeypatch.setattr("voice.persist.update_turn_understanding", lambda **_k: True)
    user = _attach(sink)
    asyncio.run(
        user.handlers["on_user_turn_stopped"](None, None, _Message("what is my balance"))
    )
    assert sink._intent_for_next_bot == "balance_query"
    customer_turn = sink._intent_for_next_bot_turn
    monkeypatch.setattr(
        "agent_core.understanding.analyze_turn",
        lambda *_a, **_k: TurnUnderstanding(
            intent="escalation", abuse=False, legal=False, source="llm"
        ),
    )
    sink._handle_understanding(
        _Job(
            "understanding",
            {
                "turn_index": (customer_turn or 0) + 10,
                "text": "see you in court",
                "prior_intent": None,
                "recent": [],
            },
        )
    )
    assert sink.session.understanding.intent == "escalation"
    assert sink._intent_for_next_bot == "balance_query"
    asyncio.run(sink.record_bot_turn("Your outstanding is sixty thousand."))
    bot = None
    while not sink._queue.empty():
        candidate = sink._queue.get_nowait()
        if candidate is not None and candidate.kind == "bot_turn":
            bot = candidate
    assert bot is not None
    assert bot.payload["intent"] == "balance_query"


def test_analysis_backlog_drop_is_counted() -> None:
    """A shed refinement must show up in the drop tally, not as a silent info line."""
    sink = _sink()
    for i in range(1, 9):
        sink.enqueue_understanding(turn_index=i, text=f"turn {i}", prior_intent=None)
    assert sink._dropped_jobs.get("understanding", 0) >= 4
    assert sink._analysis_queue.qsize() <= CrmSink._ANALYSIS_MAX_DEPTH


def test_bot_turn_persists_spoken_text() -> None:
    """CRM text must match what TTS speaks, not the pre-filter LLM string."""
    from voice.spoken_text import to_spoken

    sink = _sink()
    raw = "Your EMI is due on **14 March**. [quietly] Please pay."
    asyncio.run(sink.record_bot_turn(raw))
    bot = None
    while not sink._queue.empty():
        candidate = sink._queue.get_nowait()
        if candidate is not None and candidate.kind == "bot_turn":
            bot = candidate
    assert bot is not None
    spoken = to_spoken(raw).strip()
    assert bot.payload["text"] == spoken
    assert "[" not in bot.payload["text"]
    assert "**" not in bot.payload["text"]


def test_voicemail_skip_reason_survives_quotes(monkeypatch) -> None:
    """A quoted skip reason must not blow the jsonb patch or roll back the mark."""
    import json

    from voice import amd

    captured: list[dict] = []
    marked: list[tuple] = []

    class _Conn:
        def execute(self, sql, params=None):
            captured.append(dict(params or {}))
            return None

    class _Begin:
        def __enter__(self):
            return _Conn()

        def __exit__(self, *a):
            return False

    class _Engine:
        def begin(self):
            return _Begin()

    monkeypatch.setattr("db.engine", _Engine())
    monkeypatch.setattr(
        "outbound.mark", lambda conn, aid, **kw: marked.append((aid, kw))
    )
    session = SimpleNamespace(extra={"attempt_id": "CA-QUOTE"})
    reason = 'no grievance contact, box said "leave a message"'
    asyncio.run(amd._record_voicemail_state(session, left=False, reason=reason))
    assert marked
    assert marked[0][0] == "CA-QUOTE"
    assert marked[0][1].get("state") == "voicemail_skipped"
    patch = json.loads(captured[0]["patch"])
    assert patch["voicemailSkipped"] == reason


def test_obligation_insert_stores_verbatim() -> None:
    import call_closer

    captured: list[tuple[str, dict]] = []

    class _Conn:
        def execute(self, sql, params=None):
            captured.append((str(sql), dict(params or {})))
            return None

    call_closer._record_obligations(
        _Conn(),
        attempt={
            "id": "CA-OB",
            "tenant_id": "T1",
            "customer_id": "C1",
            "interaction_id": "IX-OB",
            "ended_at": None,
        },
        tools=[
            {
                "tool_name": "request_callback",
                "result_ok": True,
                "args": {
                    "preferredAt": "2026-01-06T18:00:00Z",
                    "verbatim": "I'll call you Tuesday at six",
                },
            }
        ],
    )
    sql, params = captured[0]
    assert "verbatim" in sql.lower()
    assert params["verbatim"] == "I'll call you Tuesday at six"


def test_obligation_insert_uses_empty_verbatim_when_missing() -> None:
    import call_closer

    captured: list[dict] = []

    class _Conn:
        def execute(self, sql, params=None):
            captured.append(dict(params or {}))
            return None

    call_closer._record_obligations(
        _Conn(),
        attempt={
            "id": "CA-OB2",
            "tenant_id": "T1",
            "customer_id": "C1",
            "interaction_id": "IX-OB2",
            "ended_at": None,
        },
        tools=[
            {
                "tool_name": "request_documents",
                "result_ok": True,
                "args": {"document": "income_proof"},
            }
        ],
    )
    assert captured[0]["verbatim"] == ""


def test_closer_claim_sql_defers_active_interactions() -> None:
    import inspect

    import call_closer

    src = inspect.getsource(call_closer.claim_one)
    assert "status = 'active'" in src
    assert "NOT EXISTS" in src
    assert "make_interval(secs => :grace)" in src
