"""Recording GET streams bytes and is permission-gated."""

from __future__ import annotations

import io
import wave

from fastapi.testclient import TestClient
import pytest

from tests.test_authz import _hdr


@pytest.fixture()
def gated_client(monkeypatch) -> TestClient:
    import actor_context
    import main as app_main

    monkeypatch.setenv("API_KEY", "authz-test-key")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    monkeypatch.delenv("AUTHZ_ENFORCE", raising=False)
    actor_context.reload_api_key_map()
    return TestClient(app_main.app)


def _wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(b"\x00\x00" * 80)
    return buf.getvalue()


def test_recording_get_403_without_perm(gated_client: TestClient) -> None:
    res = gated_client.get("/interactions/CL-NONE/recording", headers=_hdr("anita-rao"))
    assert res.status_code == 403, res.text


def test_recording_get_streams_wav(gated_client: TestClient, monkeypatch) -> None:
    from voice import recordings

    wav = _wav()

    def _stream(interaction_id: str, *, variant: str = "original"):
        assert interaction_id == "CL-REC"
        assert variant == "original"
        return {
            "bytes": wav,
            "mimeType": "audio/wav",
            "mediaId": "MED-1",
            "kind": "audio",
            "durationSec": 1,
        }

    monkeypatch.setattr(recordings, "stream_recording", _stream)
    monkeypatch.setattr(recordings, "log_recording_download", lambda *a, **k: None)
    res = gated_client.get("/interactions/CL-REC/recording", headers=_hdr("arjun-mehta"))
    assert res.status_code == 200, res.text
    assert res.content == wav
    assert "audio/wav" in (res.headers.get("content-type") or "")


def test_recording_get_fails_closed_when_audit_write_fails(
    gated_client: TestClient, monkeypatch
) -> None:
    from voice import recordings

    wav = _wav()

    def _stream(interaction_id: str, *, variant: str = "original"):
        return {
            "bytes": wav,
            "mimeType": "audio/wav",
            "mediaId": "MED-1",
            "kind": "audio",
            "durationSec": 1,
        }

    def _boom(*_a, **_k):
        raise RuntimeError("audit insert failed")

    monkeypatch.setattr(recordings, "stream_recording", _stream)
    monkeypatch.setattr(recordings, "log_recording_download", _boom)
    res = gated_client.get("/interactions/CL-REC/recording", headers=_hdr("arjun-mehta"))
    assert res.status_code == 503, res.text
    assert res.content != wav
