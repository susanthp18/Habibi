"""Asterisk ARI client against a fake ARI HTTP server."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

import pytest

from voice import asterisk_ops


class _Ari(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []
    #: path prefix -> (status, body) to answer with instead of 200 {}
    replies: dict[str, tuple[int, dict]] = {}

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003
        return

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        url = urlparse(self.path)
        _Ari.requests.append(
            {
                "method": self.command,
                "path": url.path,
                "query": {k: v[0] for k, v in parse_qs(url.query).items()},
                "body": body,
                "auth": self.headers.get("Authorization"),
            }
        )
        status, payload = next(
            (r for prefix, r in _Ari.replies.items() if url.path.startswith(prefix)),
            (200, {"state": "Down"}),
        )
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = do_POST = do_DELETE = _handle  # noqa: N815


@pytest.fixture
def ari(monkeypatch: pytest.MonkeyPatch):
    _Ari.requests, _Ari.replies = [], {}
    server = HTTPServer(("127.0.0.1", 0), _Ari)
    Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    monkeypatch.setenv("ASTERISK_ARI_URL", f"http://{host}:{port}")
    monkeypatch.setenv("ASTERISK_ARI_USER", "u")
    monkeypatch.setenv("ASTERISK_ARI_PASSWORD", "p")
    monkeypatch.delenv("ASTERISK_TRUNK_HOST", raising=False)
    monkeypatch.setattr("platform_switches.outbound_enabled", lambda: True)
    yield _Ari
    server.shutdown()


def test_an_outbound_call_enters_the_app_under_the_attempts_id(ari) -> None:
    result = asterisk_ops.originate(
        to="1001",
        custom={"attempt_id": "CA-9", "customer_id": "cust-1", "objective": "dpd_reminder"},
        from_number="1000",
    )

    req = ari.requests[-1]
    assert req["path"] == "/ari/channels"
    assert req["query"]["endpoint"] == "PJSIP/1001"
    assert req["query"]["app"] == "habibi"
    assert req["query"]["channelId"] == "att-CA-9"
    assert req["auth"].startswith("Basic ")
    ctx = json.loads(req["body"]["variables"]["HABIBI_CTX"])
    assert ctx == {
        "attempt_id": "CA-9",
        "customer_id": "cust-1",
        "objective": "dpd_reminder",
        "call_type": "outbound",
        "sip_channel_id": "att-CA-9",
        "to": "1001",
        "from": "1000",
    }
    # The attempt row and the SIP leg share one id.
    assert result["callSid"] == "att-CA-9"
    assert result["provider"] == "asterisk"


def test_an_external_number_needs_a_trunk(ari, monkeypatch) -> None:
    with pytest.raises(asterisk_ops.AriError, match="no trunk"):
        asterisk_ops.originate(to="+919000000001", custom={"attempt_id": "CA-1"})
    assert ari.requests == []

    monkeypatch.setenv("ASTERISK_TRUNK_HOST", "10.0.0.5")
    asterisk_ops.originate(to="+919000000001", custom={"attempt_id": "CA-1"})
    assert ari.requests[-1]["query"]["endpoint"] == "PJSIP/+919000000001@trunk"


def test_an_ari_refusal_is_definitive_and_readable(ari) -> None:
    ari.replies["/ari/channels"] = (500, {"error": "Allocation failed"})
    with pytest.raises(asterisk_ops.AriError) as caught:
        asterisk_ops.originate(to="1002", custom={"attempt_id": "CA-2"})
    assert caught.value.status == 500
    assert caught.value.definitive is True
    assert str(caught.value) == "ari 500: Allocation failed"

    import outbound

    assert outbound._carrier_failure_reason(caught.value) == "dial_failed"


def test_warm_transfer_marks_then_moves_the_caller_out_of_the_bridge(ari) -> None:
    result = asterisk_ops.warm_transfer("att-CA-9", reason="customer_requested")

    assert result["ok"] is True
    steps = [(r["method"], r["path"]) for r in ari.requests]
    assert steps == [
        ("POST", "/ari/channels/att-CA-9/variable"),
        ("POST", "/ari/bridges/br-att-CA-9/removeChannel"),
        ("POST", "/ari/channels/att-CA-9/continue"),
    ]
    assert ari.requests[0]["query"]["variable"] == "HABIBI_TRANSFER"
    assert ari.requests[2]["query"] == {"context": "agents", "extension": "collectors", "priority": "1"}


def test_originate_refused_when_switch_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform_switches.outbound_enabled", lambda: False)
    with pytest.raises(asterisk_ops.OutboundDisabled):
        asterisk_ops.originate(to="1001")


def test_preflight_names_a_missing_controller(ari) -> None:
    ari.replies["/ari/applications/habibi"] = (404, {"message": "Application not found"})
    assert asterisk_ops.preflight() == [
        "the asterisk_controller is not connected (ARI app 'habibi' not registered)"
    ]
