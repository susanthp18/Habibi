"""Wave 9: PII snippets, escalated rollup, live-QA handoff, recording audit."""

from __future__ import annotations

from voice.crm_sink import CrmSink
from voice.session import VoiceSession


def test_product_interest_snippet_is_redacted(monkeypatch) -> None:
    import capture_events

    seen: dict[str, object] = {}

    def _emit(*_a, **kw):
        seen["note"] = kw.get("note")

    monkeypatch.setattr(capture_events, "emit_commercial_event", _emit)
    monkeypatch.setattr(capture_events, "touch_primary_intent", lambda *_a, **_k: None)
    capture_events.record_product_interest(
        object(),
        interaction_id="IX-W9",
        intent="product_faq",
        snippet="my card is 4111 1111 1111 1111",
    )
    note = str(seen.get("note") or "")
    assert "4111 1111 1111 1111" not in note
    assert "****" in note


def test_forced_rollup_does_not_overwrite_escalated(monkeypatch) -> None:
    import capture

    monkeypatch.setattr(capture, "dominant_transcript_intent", lambda *_a, **_k: "payment_intent")
    monkeypatch.setattr(capture, "_turn_counts", lambda *_a, **_k: (2, 2))
    monkeypatch.setattr(capture, "_promise_on_interaction", lambda *_a, **_k: False)
    updates: list[tuple[str, dict]] = []

    class _Result:
        def mappings(self):
            return self

        def first(self):
            return {
                "primary_intent": None,
                "query_resolved": True,
                "upsell_presented": False,
                "ptp_captured": False,
                "summary": "",
                "disposition": "escalated",
                "channel": "voice",
            }

    class _Conn:
        def execute(self, sql, params=None):
            text_sql = str(getattr(sql, "text", sql))
            if "UPDATE" in text_sql.upper():
                updates.append((text_sql, params or {}))
            return _Result()

    capture.rollup_interaction(_Conn(), "IX-W9", force_summary=True)
    assert updates
    sql, params = updates[0]
    assert "disposition = :disposition" not in sql
    assert "disposition" not in params


def test_auto_barge_does_not_mark_enacted_when_handoff_fails(monkeypatch) -> None:
    sink = CrmSink(VoiceSession(session_id="VS-W9", interaction_id="IX-W9"))
    monkeypatch.setattr(
        "agent_core.live_qa.enact.barge_audio",
        lambda *_a, **_k: {"reason": "hours"},
    )

    def _boom(**_k):
        raise RuntimeError("handoff insert failed")

    monkeypatch.setattr("voice.persist.record_handoff", _boom)
    monkeypatch.setattr(
        "agent_core.live_qa.decisions.pending_auto_barge",
        lambda _ix: {"id": "LQ-1"},
    )
    marked: list[object] = []
    monkeypatch.setattr(
        "agent_core.live_qa.decisions.mark_enacted",
        lambda *a, **k: marked.append((a, k)),
    )
    sink._auto_barge("IX-W9", "hours")
    assert marked == []


def test_auto_barge_marks_enacted_after_handoff(monkeypatch) -> None:
    sink = CrmSink(VoiceSession(session_id="VS-W9", interaction_id="IX-W9"))
    monkeypatch.setattr(
        "agent_core.live_qa.enact.barge_audio",
        lambda *_a, **_k: {"reason": "hours"},
    )
    monkeypatch.setattr("voice.persist.record_handoff", lambda **_k: "HO-1")
    monkeypatch.setattr(
        "agent_core.live_qa.decisions.pending_auto_barge",
        lambda _ix: {"id": "LQ-1"},
    )
    marked: list[object] = []
    monkeypatch.setattr(
        "agent_core.live_qa.decisions.mark_enacted",
        lambda *a, **k: marked.append((a, k)),
    )
    sink._auto_barge("IX-W9", "hours")
    assert marked
