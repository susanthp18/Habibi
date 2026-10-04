"""The Twilio voice webhooks PayInt still answers (no live Twilio network).

Voice Studio is the only voice runtime: a number still pointed at PayInt's
inbound webhook is redirected to the engine, which verifies Twilio's signature
for its own URL and runs the call. The retired media-stream runtime's TwiML,
callbacks and outbound document are gone, and nothing here pins them."""

from __future__ import annotations

import pytest


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    import main as app_main

    monkeypatch.setattr("routers.telephony._twilio_signature_ok", lambda *_a, **_k: True)
    return TestClient(app_main.app)


def test_a_signed_inbound_call_is_handed_to_the_engine(client, monkeypatch: pytest.MonkeyPatch) -> None:
    import voice_studio

    monkeypatch.setenv("AGENTSTUDIO_PUBLIC_URL", "https://studio.example.test/")
    res = client.post("/twilio/voice/incoming", data={"CallSid": "CAtest", "From": "+15550000000"})
    assert res.status_code == 200, res.text
    assert '<Redirect method="POST">' in res.text
    assert f"https://studio.example.test{voice_studio.ENGINE_INBOUND_PATH}" in res.text
    assert "<Stream" not in res.text


def test_without_the_engine_the_caller_hears_why_and_the_call_ends(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTSTUDIO_PUBLIC_URL", "")
    res = client.post("/twilio/voice/incoming", data={"CallSid": "CAtest"})
    assert res.status_code == 200, res.text
    assert "temporarily unavailable" in res.text
    assert "<Hangup" in res.text
    assert "<Redirect" not in res.text


def test_the_fallback_apologises_and_hangs_up(client) -> None:
    res = client.post("/twilio/voice/fallback", data={"CallSid": "CAtest", "ErrorCode": "11200"})
    assert res.status_code == 200, res.text
    assert "could not connect your call" in res.text
    assert "<Hangup" in res.text


def test_ws_proxy_is_off_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("voice.ws_proxy.load_env", lambda: None)
    monkeypatch.delenv("VOICE_WS_VIA_API", raising=False)
    from voice.ws_proxy import ws_proxy_enabled

    assert ws_proxy_enabled() is False
