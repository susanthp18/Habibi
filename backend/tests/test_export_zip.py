"""Export jobs are queued for the worker; the redacted recording beeps each finding."""

from __future__ import annotations

import inspect
import io
import wave

import db_redaction
from voice.redaction_export import beep_ranges


def test_create_export_job_queues_for_the_worker() -> None:
    # Bundles are built by the ml_worker (call_intel/exports.py), not in the request.
    src = inspect.getsource(db_redaction.create_export_job)
    assert "Demo: mark ready immediately" not in src
    assert "_materialize_export_zip" not in src


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


def test_beep_ranges_tones_only_that_speakers_channel() -> None:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(b"\x01\x00\x02\x00" * 8000)  # customer=1, agent=2
    beeped = beep_ranges(buf.getvalue(), [(100, 300, "customer")])
    with wave.open(io.BytesIO(beeped), "rb") as wf:
        samples = memoryview(wf.readframes(wf.getnframes())).cast("h")
    customer, agent = samples[0::2], samples[1::2]
    assert customer[400] == 1 and customer[3200] == 1  # untouched outside 100-300 ms
    assert any(abs(s) > 1000 for s in customer[800:2400])  # an audible tone, not silence
    assert all(s == 2 for s in agent)  # the agent's channel is never touched
