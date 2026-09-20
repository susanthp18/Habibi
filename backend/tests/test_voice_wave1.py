"""Wave-1 compliance floor: direction, redaction, holds, identity, inbox label."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from agent_core.live_qa.checks import TurnFacts, check_hours
from voice.bot_flow import resolve_call_direction
from voice.session import VoiceSession
from voice.tools_closing import compliance_inbox_flag


def test_outbound_without_callDirection_is_still_outbound() -> None:
    session = VoiceSession(session_id="VS-DIR1")
    session.extra["twilio_params"] = {"call_type": "outbound", "attempt_id": "CA-1"}
    assert resolve_call_direction(session, {}) == "outbound"


def test_outbound_bundle_without_callDirection_hours_breach() -> None:
    session = VoiceSession(session_id="VS-DIR2")
    session.extra["twilio_params"] = {"call_type": "outbound"}
    direction = resolve_call_direction(session, {"callDirection": None})
    finding = check_hours(
        TurnFacts(channel="voice", now_hour=19, direction=direction, bot_text="hi")
    )
    assert finding is not None
    assert finding.check_id == "hours-breach"


def test_inbound_unknown_stays_inbound() -> None:
    session = VoiceSession(session_id="VS-DIR3")
    assert resolve_call_direction(session, {}) == "inbound"


def test_compliance_label_uses_detail_not_last_okay() -> None:
    assert compliance_inbox_flag("legal_mention", "okay") == "legal-threat"
    assert compliance_inbox_flag("abuse_detected", "okay") == "abusive-language"
    assert compliance_inbox_flag("compliance", "okay") == "compliance"


def test_suppress_upsell_inserts_no_upsell_kind() -> None:
    import post_call_actions

    captured: dict = {}

    class _Conn:
        def execute(self, sql, params):
            captured["sql"] = str(sql)
            captured["params"] = params
            return MagicMock()

    ctx = {
        "conn": _Conn(),
        "attempt": {"tenant_id": "t", "customer_id": "c", "interaction_id": None},
        "business": "hardship_declared",
    }
    post_call_actions._suppress_upsell(ctx, "90d")
    assert captured["params"]["kind"] == "no_upsell"
    assert captured["params"]["reason"] == "hardship_declared"


def test_media_for_interaction_keeps_newest_audio(monkeypatch) -> None:
    from voice import recordings

    rows = [
        {"id": "new", "kind": "audio", "storage_ref": "new.wav", "created_at": 2},
        {"id": "old", "kind": "audio", "storage_ref": "old.wav", "created_at": 1},
    ]

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *_a, **_k):
            return rows

    monkeypatch.setattr("db.engine.connect", lambda: _Conn())
    monkeypatch.setattr("db._rows", lambda result: result)
    monkeypatch.setattr("db.current_tenant", lambda: "hdfc.retail")
    picked = recordings.media_for_interaction("CL-1", variant="original")
    assert picked is not None
    assert picked["id"] == "new"


def test_redacted_export_omits_original_when_no_redacted(monkeypatch) -> None:
    import io
    import zipfile

    from voice.redaction_export import build_export_zip

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *_a, **_k):
            return SimpleNamespace()

    rec = {
        "id": "RR-1",
        "interaction_id": "CL-1",
        "customer_id": "C1",
        "started_at": None,
        "ended_at": None,
        "direction": "inbound",
        "channel": "voice",
        "handler_bot_id": None,
        "source_payload": {},
    }

    monkeypatch.setattr("db.engine.connect", lambda: _Conn())
    monkeypatch.setattr("db._one", lambda _r: rec)
    monkeypatch.setattr("db.current_tenant", lambda: "hdfc.retail")
    monkeypatch.setattr("voice.redaction_export.write_redacted_wav", lambda *a, **k: None)
    monkeypatch.setattr(
        "voice.recordings.media_for_interaction",
        lambda ix, variant="original": (
            None
            if variant == "redacted"
            else {"kind": "audio", "storage_ref": "local://recordings/x.wav"}
        ),
    )
    monkeypatch.setattr("voice.recordings._load_bytes", lambda _ref: b"ORIGINAL")
    blob = build_export_zip("EX-1", ["RR-1"], ["redacted_audio"])
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
    assert not any(n.endswith("redacted.wav") for n in names)


def test_resolve_known_customer_is_tenant_scoped(monkeypatch) -> None:
    from voice import persist

    captured: list[dict] = []

    class _Result:
        def scalar(self):
            return None

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, _sql, params):
            captured.append(dict(params))
            return _Result()

    monkeypatch.setattr("db.engine.connect", lambda: _Conn())
    monkeypatch.setattr("db.current_tenant", lambda: "hdfc.retail")
    assert persist.resolve_known_customer("C-1") is None
    assert captured == [{"id": "C-1", "tenant": "hdfc.retail"}]
