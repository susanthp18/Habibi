"""Asterisk config rendered from env (telephony/render_config.py)."""

from __future__ import annotations

import pytest

from telephony.render_config import ConfigError, render

BASE = {
    "ASTERISK_ARI_USER": "ari",
    "ASTERISK_ARI_PASSWORD": "ari-secret",
    "ASTERISK_WS_USER": "media",
    "ASTERISK_WS_PASSWORD": "media-secret",
}


def test_the_media_client_is_valid_for_per_call_media() -> None:
    """`connection_type = per_call` is not a value; Asterisk skipped the object and
    every call failed with "WebSocket client connection 'habibi_bot' not found"."""
    conf = render(BASE)["websocket_client.conf"]
    assert "connection_type = per_call_config\n" in conf
    assert "username = media\n" in conf and "password = media-secret\n" in conf
    assert "uri = ws://voice:7860/ws/asterisk\n" in conf


def test_softphone_sections_are_named_by_extension() -> None:
    """The registrar finds the AOR by the To-user. Named `softphone`, registration
    of 1001 failed with correct credentials and dials to PJSIP/1001 had no endpoint."""
    pjsip = render({**BASE, "ASTERISK_SOFTPHONES": "1001:a,1002:b"})["pjsip.conf"]
    for ext, secret in (("1001", "a"), ("1002", "b")):
        assert f"[{ext}]\ntype=auth\nauth_type=userpass\nusername={ext}\npassword={secret}\n" in pjsip
        assert f"[{ext}]\ntype=aor\n" in pjsip
        assert f"auth={ext}\naors={ext}\n" in pjsip
    assert "match=" not in pjsip  # no IP identify for phones


def test_an_external_address_is_used_for_every_peer_unless_told_otherwise() -> None:
    """A real handset's SIP arrives through the relay, so Asterisk sees it coming
    from the Docker gateway. With the Docker subnet declared local, the SDP carried
    the container address and the phone sent its audio nowhere."""
    pjsip = render({**BASE, "ASTERISK_EXTERNAL_IP": "192.168.137.1"})["pjsip.conf"]
    assert "external_media_address=192.168.137.1" in pjsip
    assert "local_net=" not in pjsip

    scoped = render({**BASE, "ASTERISK_EXTERNAL_IP": "10.1.1.1", "ASTERISK_LOCAL_NET": "10.1.0.0/16"})["pjsip.conf"]
    assert "local_net=10.1.0.0/16" in scoped


def test_no_trunk_without_a_host() -> None:
    assert "[trunk]" not in render(BASE)["pjsip.conf"]


def test_a_trunk_is_allowlisted_and_asserts_caller_id() -> None:
    pjsip = render({**BASE, "ASTERISK_TRUNK_HOST": "10.2.3.4", "ASTERISK_TRUNK_MATCH": "10.2.3.4/32"})["pjsip.conf"]
    assert "contact=sip:10.2.3.4:5060\n" in pjsip
    assert "match=10.2.3.4/32\n" in pjsip
    assert "send_pai=yes" in pjsip and "context=from-trunk" in pjsip


def test_the_trunk_never_allows_everyone() -> None:
    with pytest.raises(ConfigError, match="0.0.0.0/0"):
        render({**BASE, "ASTERISK_TRUNK_HOST": "10.2.3.4", "ASTERISK_TRUNK_MATCH": "0.0.0.0/0"})


def test_tls_trunk_needs_certificates() -> None:
    with pytest.raises(ConfigError, match="TLS"):
        render({**BASE, "ASTERISK_TRUNK_HOST": "sbc", "ASTERISK_TRUNK_TRANSPORT": "tls"})
    assert "transport-tls" not in render(BASE)["pjsip.conf"]


@pytest.mark.parametrize("missing", sorted(BASE))
def test_credentials_are_required(missing: str) -> None:
    env = {k: v for k, v in BASE.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        render(env)


def test_every_call_enters_the_app_and_nothing_answers_early() -> None:
    ext = render({**BASE, "ASTERISK_BOT_EXTENSION": "1000"})["extensions.conf"]
    assert "exten => 1000,1,Stasis(habibi,inbound)" in ext
    assert "exten => _X.,1,Stasis(habibi,inbound)" in ext
    assert "Answer(" not in ext and "MixMonitor(" not in ext
    # The bot's leg: ARI cannot bridge a chan_websocket channel, so it is dialled
    # from the dialplan through a Local channel the controller originates.
    assert "exten => bot,1,Dial(WebSocket/habibi_bot/c(slin16)f(json),30)" in ext
    assert "allowed_origins" not in render(BASE)["ari.conf"]
