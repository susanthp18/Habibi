"""TELEPHONY_PROVIDER seam."""

from __future__ import annotations


def test_inbound_webhook_hands_the_call_to_voice_studio(monkeypatch) -> None:
    """With Voice Studio as the provider, a number still pointed at PayInt's
    webhook is redirected to the engine's inbound dispatcher -- never streamed
    to the legacy runner -- and refused, not misrouted, when the engine's
    public URL is unknown."""
    from fastapi.testclient import TestClient

    import main as app_main
    from routers import telephony as telephony_router

    monkeypatch.setenv("TELEPHONY_PROVIDER", "studio")
    monkeypatch.setattr(telephony_router, "_twilio_signature_ok", lambda request, form: True)
    client = TestClient(app_main.app)
    form = {"CallSid": "CA1", "From": "+919000000001", "To": "+14155550100"}

    monkeypatch.setenv("AGENTSTUDIO_PUBLIC_URL", "https://payint.example/?a=1&b=2")
    res = client.post("/twilio/voice/incoming", data=form)
    assert res.status_code == 200, res.text
    assert "<Redirect method=\"POST\">https://payint.example/?a=1&amp;b=2/api/v1/telephony/inbound/run</Redirect>" in res.text
    assert "<Stream" not in res.text

    monkeypatch.setenv("AGENTSTUDIO_PUBLIC_URL", "")
    res = client.post("/twilio/voice/incoming", data=form)
    assert res.status_code == 200 and "<Hangup/>" in res.text and "<Redirect" not in res.text
