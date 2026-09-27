"""TELEPHONY_PROVIDER seam."""

from __future__ import annotations

from voice import telephony, twilio_ops


def test_unset_provider_is_twilio(monkeypatch) -> None:
    monkeypatch.delenv("TELEPHONY_PROVIDER", raising=False)
    assert telephony.provider_name() == "twilio"
    assert telephony._adapter() is twilio_ops


def test_asterisk_provider_selects_ops(monkeypatch) -> None:
    monkeypatch.setenv("TELEPHONY_PROVIDER", "asterisk")
    from voice import asterisk_ops

    assert telephony.provider_name() == "asterisk"
    assert telephony._adapter() is asterisk_ops


def test_originate_delegates_to_twilio_start(monkeypatch) -> None:
    monkeypatch.delenv("TELEPHONY_PROVIDER", raising=False)
    seen: dict[str, object] = {}

    def _start(*, to, custom=None, machine_detection=False, from_number=None):
        seen["to"] = to
        seen["custom"] = custom
        return {"callSid": "CA123", "to": to, "status": "queued", "from": "+1555"}

    monkeypatch.setattr(twilio_ops, "start_outbound_call", _start)
    result = telephony.originate(to="+919655282324", custom={"attempt_id": "CA-1"})
    assert result["callSid"] == "CA123"
    assert seen["to"] == "+919655282324"


def test_configured_and_preflight_follow_the_selected_provider(monkeypatch) -> None:
    """Dial endpoints used to 503 `twilio_not_configured` on an Asterisk-only site."""
    from voice import asterisk_ops

    monkeypatch.setenv("TELEPHONY_PROVIDER", "asterisk")
    monkeypatch.setattr(twilio_ops, "configured", lambda: False)
    monkeypatch.setattr(asterisk_ops, "configured", lambda: True)
    monkeypatch.setattr(asterisk_ops, "preflight", lambda: ["controller down"])

    assert telephony.configured() is True
    assert telephony.preflight() == ["controller down"]


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
