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





def test_mesh_status_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:

    from voice import mesh



    monkeypatch.setenv("VOICE_MULTI_AGENT_ENABLED", "true")

    monkeypatch.delenv("REDIS_URL", raising=False)

    st = mesh.status()

    assert st["enabled"] is True

    assert st["backend"] == "local"

    assert "insurance" in st["roles"]


