"""Export jobs produce a real zip; the stub path is gone."""

from __future__ import annotations

import inspect
import io
import zipfile
import wave

import db_redaction
from voice.redaction_export import _silence_ranges, build_export_zip


def test_create_export_job_is_not_a_stub() -> None:
    src = inspect.getsource(db_redaction.create_export_job)
    assert "Demo: mark ready immediately" not in src
    assert "_materialize_export_zip" in src


def test_create_export_job_dashboard_does_not_touch_redaction_ids(monkeypatch) -> None:
    seen: dict = {}

    def fake(payload):
        seen["payload"] = payload
        return {"id": "EX-DASH", "kind": "dashboard", "recordIds": []}

    monkeypatch.setattr(db_redaction, "_create_dashboard_export_job", fake)
    out = db_redaction.create_export_job({"kind": "dashboard", "range": "30d"})
    assert seen["payload"]["kind"] == "dashboard"
    assert "recordIds" not in seen["payload"] or not seen["payload"].get("recordIds")
    assert out["kind"] == "dashboard"


def test_silence_ranges_zeros_the_span() -> None:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(100)
        wf.writeframes(b"\x01\x00" * 100)
    muted = _silence_ranges(buf.getvalue(), [(0.1, 0.2)])
    with wave.open(io.BytesIO(muted), "rb") as wf:
        pcm = wf.readframes(wf.getnframes())
    samples = memoryview(pcm).cast("h")
    assert samples[0] != 0
    assert all(s == 0 for s in samples[10:30])


def test_build_export_zip_contains_job_and_transcript(monkeypatch) -> None:
    from voice import persist, recordings

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *args, **kwargs):
            return None

    class _Engine:
        def connect(self):
            return _Conn()

    monkeypatch.setattr("db.current_tenant", lambda: "t1")
    monkeypatch.setattr("db.engine", _Engine())
    monkeypatch.setattr(
        "db._one",
        lambda *_a, **_k: {
            "id": "RR-1",
            "interaction_id": "CL-1",
            "customer_id": "CU-1",
            "started_at": None,
            "ended_at": None,
            "direction": "inbound",
            "channel": "voice",
            "handler_bot_id": "bot-1",
            "source_payload": {},
        },
    )
    monkeypatch.setattr(
        persist,
        "list_transcript_turns",
        lambda _id: [{"turnIndex": 0, "speaker": "bot", "atSec": 0, "text": "hello"}],
    )
    monkeypatch.setattr(
        persist,
        "transcript_export_payload",
        lambda ix, sid, turns: {"interactionId": ix, "turns": turns},
    )
    wav = io.BytesIO()
    with wave.open(wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(b"\x00\x00" * 8)
    payload = wav.getvalue()
    monkeypatch.setattr(
        recordings,
        "media_for_interaction",
        lambda *a, **k: {
            "kind": "audio",
            "storage_ref": "local://recordings/x.wav",
            "duration_sec": 1,
        },
    )
    monkeypatch.setattr(recordings, "_load_bytes", lambda _ref: payload)
    blob = build_export_zip("EX-1", ["RR-1"], ["transcript", "audio", "metadata"])
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
    assert "job.json" in names
    assert "RR-1/transcript.json" in names
    assert "RR-1/original.wav" in names
    assert "RR-1/metadata.json" in names
