"""Outbound MCP connector calls must not be usable as a request forgery.

``agent_core/connectors/persist.py`` POSTs to a URL an operator typed into the
Connectors screen, with that connector's bearer token attached. Registration
checked ``_https_ok`` — scheme and netloc — and nothing else, so
``https://169.254.169.254/mcp`` was an approvable connector and the cloud
metadata endpoint received the token.

These tests hold two separate things:

* the guard rejects what it should, resolving the name at *call* time rather
  than trusting a registration-time verdict that DNS is free to invalidate;
* a rejection reaches the caller as a clean error result and does **not** count
  against the circuit breaker — a connector pointed somewhere it may not go is
  misconfigured, not flaky, and burying it behind ``connector_circuit_open``
  hides the one fact that explains it.

Nothing here may make a network call. DNS is mocked exactly as
``test_webhooks_dispatch.py`` mocks it, for the same reason.
"""

from __future__ import annotations

import socket as sock
from typing import Any

import pytest

import webhooks_dispatch as wd
from agent_core.connectors import persist as cp


def _resolves_to(monkeypatch: pytest.MonkeyPatch, *addrs: str) -> None:
    """Pin DNS for every host to ``addrs``.

    The "public" address here is a real routable one, not a TEST-NET literal:
    ``ipaddress`` classifies the 192.0.2/198.51.100/203.0.113 documentation
    ranges as private, so a documentation address makes the pass-case test
    assert the opposite of what it reads like.
    """
    monkeypatch.setattr(
        wd.socket,
        "getaddrinfo",
        lambda *a, **k: [(sock.AF_INET, sock.SOCK_STREAM, 6, "", (a_, 443)) for a_ in addrs],
    )


def _connector(url: str = "https://mcp.example.com") -> dict[str, Any]:
    return {
        "id": "conn-ssrf-test",
        "slug": "vendor",
        "kind": "remote_mcp",
        "url": url,
        "status": "approved",
        "timeoutMs": 2500,
        "authRef": None,
        "circuitOpenedAt": None,
    }


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fail loudly if anything under test actually POSTs.

    The guard's whole job is to run *before* the connect, so a test that lets
    httpx through is not testing the guard.
    """
    import httpx

    posted: list[str] = []

    def _explode(url: str, **kwargs: Any) -> Any:
        posted.append(url)
        raise AssertionError(f"outbound POST escaped the guard: {url}")

    monkeypatch.setattr(httpx, "post", _explode)
    return posted


# --- the guard itself -------------------------------------------------------


def test_private_ipv4_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolves_to(monkeypatch, "10.1.2.3")
    with pytest.raises(ValueError, match="connector_url_private_forbidden"):
        cp._guard_outbound_url("https://mcp.example.com")


def test_loopback_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolves_to(monkeypatch, "127.0.0.1")
    with pytest.raises(ValueError, match="connector_url_private_forbidden"):
        cp._guard_outbound_url("https://mcp.example.com")


def test_cloud_metadata_address_is_rejected() -> None:
    # A literal needs no DNS at all: this is the URL that passed registration.
    with pytest.raises(ValueError, match="connector_url_private_forbidden"):
        cp._guard_outbound_url("https://169.254.169.254")


def test_a_public_hostname_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolves_to(monkeypatch, "93.184.216.34")
    assert cp._guard_outbound_url("https://mcp.example.com") == "https://mcp.example.com"


def test_one_private_answer_among_public_ones_is_enough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The connect may land on any of them.
    _resolves_to(monkeypatch, "93.184.216.34", "10.0.0.5")
    with pytest.raises(ValueError, match="connector_url_private_forbidden"):
        cp._guard_outbound_url("https://mcp.example.com")


def test_plain_http_is_rejected() -> None:
    with pytest.raises(ValueError, match="connector_url_https_only"):
        cp._guard_outbound_url("http://mcp.example.com")


def test_an_empty_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="connector_url_required"):
        cp._guard_outbound_url("   ")


def test_a_name_that_does_not_resolve_is_not_a_private_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DNS failure is a transport fault and must read as one.

    It still blocks the POST, but it must not be reported as
    ``private_forbidden`` — that code is what an operator reads as "your URL is
    not allowed", and a flaky resolver is a different conversation.
    """

    def _fail(*a: Any, **k: Any) -> Any:
        raise sock.gaierror("Name or service not known")

    monkeypatch.setattr(wd.socket, "getaddrinfo", _fail)
    with pytest.raises(ValueError, match="connector_url_unresolvable"):
        cp._guard_outbound_url("https://mcp.example.com")


# --- the guard's placement --------------------------------------------------


def test_call_remote_guards_before_it_posts(
    monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> None:
    _resolves_to(monkeypatch, "169.254.169.254")
    with pytest.raises(ValueError, match="connector_url_private_forbidden"):
        cp._call_remote(_connector(), "ext.vendor.lookup", "CUST-1")
    assert no_network == []


def test_tools_list_guards_before_it_posts(
    monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> None:
    _resolves_to(monkeypatch, "192.168.1.10")
    with pytest.raises(ValueError, match="connector_url_private_forbidden"):
        cp._remote_tools_list(_connector())
    assert no_network == []


# --- what the caller sees ---------------------------------------------------


def test_dispatch_returns_a_clean_error_and_spares_the_circuit(
    monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> None:
    failures: list[str] = []
    monkeypatch.setattr(cp, "mcp_client_enabled", lambda: True)
    monkeypatch.setattr(cp, "get_connector", lambda _id: _connector())
    monkeypatch.setattr(cp.circuit, "record_failure", lambda cid: failures.append(cid))
    monkeypatch.setattr(cp.circuit, "record_success", lambda cid: failures.append("success"))
    _resolves_to(monkeypatch, "10.0.0.5")

    result = cp.dispatch("ext.vendor.lookup", customer_id="CUST-1", connector_id="conn-ssrf-test")

    assert result == {"ok": False, "error": "connector_url_private_forbidden"}
    assert failures == []
    assert no_network == []


def test_health_test_returns_a_clean_error_and_spares_the_circuit(
    monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> None:
    failures: list[str] = []
    monkeypatch.setattr(cp, "get_connector", lambda _id: _connector())
    monkeypatch.setattr(cp.circuit, "record_failure", lambda cid: failures.append(cid))
    monkeypatch.setattr(cp.circuit, "record_success", lambda cid: failures.append("success"))
    _resolves_to(monkeypatch, "127.0.0.1")

    result = cp.health_test("conn-ssrf-test")

    assert result == {"ok": False, "error": "connector_url_private_forbidden"}
    assert failures == []
    assert no_network == []


def test_a_transport_fault_still_counts_against_the_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard must not have made every failure look like a blocked URL.

    ``json.JSONDecodeError`` is a ``ValueError``, so a code that matched all of
    them would stop the breaker from ever opening on a genuinely broken remote.
    """
    failures: list[str] = []
    monkeypatch.setattr(cp, "mcp_client_enabled", lambda: True)
    monkeypatch.setattr(cp, "get_connector", lambda _id: _connector())
    monkeypatch.setattr(cp.circuit, "record_failure", lambda cid: failures.append(cid))

    def _boom(*a: Any, **k: Any) -> Any:
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setattr(cp, "_call_remote", _boom)

    result = cp.dispatch("ext.vendor.lookup", customer_id="CUST-1", connector_id="conn-ssrf-test")

    assert result == {"ok": False, "error": "connector_call_failed"}
    assert failures == ["conn-ssrf-test"]
