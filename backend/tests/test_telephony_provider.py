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
