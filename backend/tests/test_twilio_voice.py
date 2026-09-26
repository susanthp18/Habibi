"""Twilio dial-in TwiML + config smoke tests (no live Twilio network)."""



from __future__ import annotations



import pytest





def test_twiml_connect_stream_uses_voice_public(monkeypatch: pytest.MonkeyPatch) -> None:

    from voice import twilio_ops



    monkeypatch.setenv("VOICE_WS_VIA_API", "false")

    monkeypatch.setenv("VOICE_PUBLIC_BASE_URL", "https://voice.example.ngrok-free.dev")

    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)

    monkeypatch.delenv("VOICE_WS_PROXY_SECRET", raising=False)

    xml = twilio_ops.twiml_connect_stream(custom={"from": "+15551212", "call_type": "inbound"})

    assert xml.index("<Say") < xml.index("<Stream")
    assert "Please stay on the line." in xml
    assert 'voice="Polly.Aditi"' in xml
    assert 'language="en-IN"' in xml
    assert "wss://voice.example.ngrok-free.dev/ws" in xml

    assert "?" not in xml.split("<Stream", 1)[1].split(">", 1)[0]

    assert "statusCallback=" in xml

    assert "/twilio/voice/stream-status" in xml

    assert "<Connect>" in xml

    assert 'name="from"' in xml

    assert 'value="+15551212"' in xml





def test_media_stream_uses_public_when_proxy(monkeypatch: pytest.MonkeyPatch) -> None:

    from voice import twilio_ops



    monkeypatch.setenv("VOICE_WS_VIA_API", "true")

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.example.ngrok-free.dev")

    monkeypatch.delenv("VOICE_PUBLIC_BASE_URL", raising=False)

    monkeypatch.delenv("VOICE_WS_PROXY_SECRET", raising=False)

    assert twilio_ops.media_stream_wss_url() == "wss://api.example.ngrok-free.dev/ws"





def test_media_stream_embeds_proxy_secret_in_path(monkeypatch: pytest.MonkeyPatch) -> None:

    from voice import twilio_ops



    monkeypatch.setenv("VOICE_WS_VIA_API", "true")

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.example.ngrok-free.dev")

    monkeypatch.setenv("VOICE_WS_PROXY_SECRET", "s3cret-value")

    url = twilio_ops.media_stream_wss_url()

    assert url == "wss://api.example.ngrok-free.dev/ws/s3cret-value"

    assert "?" not in url

    xml = twilio_ops.twiml_connect_stream()

    assert xml.index("<Say") < xml.index("<Stream")
    assert "Please stay on the line." in xml
    assert "wss://api.example.ngrok-free.dev/ws/s3cret-value" in xml

    assert "proxy_secret=" not in xml





def test_media_stream_requires_voice_public_when_proxy_off(monkeypatch: pytest.MonkeyPatch) -> None:

    from voice import twilio_ops



    monkeypatch.setenv("VOICE_WS_VIA_API", "false")

    monkeypatch.delenv("VOICE_PUBLIC_BASE_URL", raising=False)

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.example.ngrok-free.dev")

    with pytest.raises(RuntimeError, match="PUBLIC_BASE_URL|VOICE_PUBLIC"):

        twilio_ops.media_stream_wss_url()





def test_handoff_mode_defaults_callback(monkeypatch: pytest.MonkeyPatch) -> None:

    from voice import twilio_ops



    monkeypatch.delenv("VOICE_HANDOFF_MODE", raising=False)

    assert twilio_ops.handoff_mode() == "callback_queue"

    monkeypatch.setenv("VOICE_HANDOFF_MODE", "warm")

    assert twilio_ops.handoff_mode() == "warm"


def test_ws_proxy_is_off_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("voice.ws_proxy.load_env", lambda: None)
    monkeypatch.delenv("VOICE_WS_VIA_API", raising=False)
    from voice.ws_proxy import ws_proxy_enabled

    assert ws_proxy_enabled() is False


def test_outbound_dial_uses_a_document_url_so_a_trial_keypress_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inline twiml has no document for the trial Gather to POST a digit to.

    The prompt says press any key. With twiml= on calls.create, that key ends
    the call. A url= is the document both the keypress and the timeout return to.
    """
    from types import SimpleNamespace

    from voice import twilio_ops

    monkeypatch.setenv("VOICE_WS_VIA_API", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.example.ngrok-free.dev")
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+15550001111")
    monkeypatch.setattr("platform_switches.outbound_enabled", lambda **_kwargs: True)
    monkeypatch.setattr("agent_core.carrier_guard.refuse_real_carrier", lambda _name: None)

    seen: dict = {}

    class _Calls:
        def create(self, **kwargs):
            raise AssertionError("create must be wrapped by carrier_call")

    class _Client:
        calls = _Calls()

    def _carrier(_fn, *_args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(sid="CA123", status="queued")

    monkeypatch.setattr(twilio_ops, "rest_client", lambda: _Client())
    monkeypatch.setattr(twilio_ops, "carrier_call", _carrier)

    result = twilio_ops.start_outbound_call(
        to="+15558675309",
        custom={"attempt_id": "CA-1", "customer_id": "cust-1", "demo": "1"},
    )
    assert result["callSid"] == "CA123"
    assert "twiml" not in seen
    assert seen["method"] == "POST"
    assert seen["url"].startswith("https://api.example.ngrok-free.dev/twilio/voice/connect?")
    assert "attempt_id=CA-1" in seen["url"]
    assert "customer_id=cust-1" in seen["url"]
    assert "demo=1" in seen["url"]


def test_connect_document_streams_after_the_trial_digit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    import main as app_main

    monkeypatch.setattr("routers.telephony._twilio_signature_ok", lambda *_a, **_k: True)
    monkeypatch.setattr("voice.twilio_ops.configured", lambda: True)
    monkeypatch.setenv("VOICE_WS_VIA_API", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.example.ngrok-free.dev")
    monkeypatch.delenv("VOICE_WS_PROXY_SECRET", raising=False)

    client = TestClient(app_main.app)
    res = client.post(
        "/twilio/voice/connect?attempt_id=CA-1&customer_id=cust-1&demo=1",
        data={"Digits": "5", "CallSid": "CAtest"},
    )
    assert res.status_code == 200, res.text
    body = res.text
    assert "<Connect>" in body
    assert "<Stream" in body
    assert 'name="attempt_id"' in body
    assert 'value="CA-1"' in body
    assert "Hangup" not in body
    assert "not available on trial" not in body


def test_ws_proxy_is_dev_compose_only() -> None:
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    prod = (backend / "docker-compose.yml").read_text(encoding="utf-8")
    dev = (backend / "docker-compose.dev.yml").read_text(encoding="utf-8")
    assert "VOICE_WS_VIA_API" not in prod
    assert "VOICE_WS_VIA_API" in dev
