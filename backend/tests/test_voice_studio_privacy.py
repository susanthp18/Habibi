"""Agent builders without raw-PII permission see Voice Studio runs masked."""

from __future__ import annotations

import voice_studio_privacy as privacy


def _run() -> dict:
    return {
        "id": 424242,
        "initial_context": {"customer_name": "Anita Desai", "phone_number": "+919876543210", "direction": "outbound"},
        "recording_public_url": "https://x/public/download/t/recording",
        "logs": {"realtime_feedback_events": [
            {"type": "rtf-bot-text", "payload": {"text": "What are the last four digits of your mobile?"}},
            {"type": "rtf-user-transcription", "payload": {"text": "nine nine zero", "final": False}},
            {"type": "rtf-user-transcription", "payload": {"text": "nine nine zero seven", "final": True}},
            {"type": "rtf-function-call-end", "payload": {"result": {"phone": "9876543210"}}},
        ]},
    }


def test_an_unfiled_run_is_masked_by_the_detectors(monkeypatch) -> None:
    monkeypatch.setattr(privacy, "_stored_turns", lambda run_id: None)
    out = privacy.mask_run(_run())
    texts = [e["payload"].get("text") for e in out["logs"]["realtime_feedback_events"]]
    assert texts[2] == "[REDACTED]"  # the answer to "last four digits"
    assert "9876543210" not in out["logs"]["realtime_feedback_events"][3]["payload"]["result"]
    assert out["initial_context"]["customer_name"] == "•••"
    assert out["initial_context"]["phone_number"] == "•••10"
    assert out["recording_public_url"] is None


def test_a_filed_run_shows_the_audited_masked_transcript(monkeypatch) -> None:
    monkeypatch.setattr(privacy, "_stored_turns", lambda run_id: ["What are the last …?", "[REDACTED]"])
    out = privacy.mask_run(_run())
    assert out["logs"]["realtime_feedback_events"][2]["payload"]["text"] == "[REDACTED]"


def test_only_run_views_are_masked() -> None:
    assert privacy.needs_masking("GET", "/workflow/2/runs/11")
    assert privacy.needs_masking("GET", "/organizations/usage/runs")
    assert not privacy.needs_masking("GET", "/workflow/2")
    assert not privacy.needs_masking("POST", "/workflow/2/runs/11")


def test_call_audio_and_raw_transcripts_are_not_signed_for_the_browser() -> None:
    from types import SimpleNamespace

    from routers.agentstudio_gateway import _raw_media

    def req(key: str):
        return SimpleNamespace(query_params={"key": key})

    assert _raw_media("/s3/signed-url", req("recordings/11.wav"))
    assert _raw_media("/s3/signed-url", req("transcripts/11.txt"))
    assert _raw_media("/public/download/workflow/tok/recording", req(""))
    assert not _raw_media("/s3/signed-url", req("knowledge-base/doc.pdf"))  # KB uploads still sign
