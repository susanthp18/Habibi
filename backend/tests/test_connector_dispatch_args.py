"""A remote MCP tool must receive the arguments the model actually sent.

``bot_tools.execute_tool`` parsed the model's argument object, validated that
it was an object, checked the tool against the card — and then called
``connectors.persist.dispatch(name, customer_id=...)``, dropping it. The other
end of the same path hardcoded ``"arguments": {"customer_id": customer_id}``.

So a connector tool declaring ``{"customer_id", "invoice_id"}`` was invoked
with ``invoice_id`` missing on every call. Nothing failed loudly: the remote
answered about *some* invoice, the model read that answer as the one it asked
about, and the caller was told about a payment that was not theirs.

The property under test is the JSON-RPC payload, not the return value — the
bug lived entirely in what went out on the wire.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_core.connectors import persist as cp


def _connector(url: str = "https://mcp.example.com") -> dict[str, Any]:
    return {
        "id": "conn-args-test",
        "slug": "vendor",
        "kind": "remote_mcp",
        "url": url,
        "status": "approved",
        "timeoutMs": 2500,
        "authRef": None,
        "circuitOpenedAt": None,
    }


class _Resp:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": 1, "result": {"ok": True, "status": "paid"}}


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture the outbound JSON-RPC body instead of making a request."""
    import httpx

    bodies: list[dict[str, Any]] = []

    def _post(url: str, **kwargs: Any) -> Any:
        bodies.append(kwargs.get("json") or {})
        return _Resp()

    monkeypatch.setattr(httpx, "post", _post)
    # The SSRF guard has its own suite; here it must simply not resolve DNS.
    monkeypatch.setattr(cp, "_guard_outbound_url", lambda url: str(url))
    return bodies


def _arguments(bodies: list[dict[str, Any]]) -> dict[str, Any]:
    assert len(bodies) == 1, f"expected exactly one outbound call, got {len(bodies)}"
    return bodies[0]["params"]["arguments"]


# --- the payload builder ----------------------------------------------------


def test_no_args_is_exactly_the_old_payload() -> None:
    """Backwards compatibility: an argument-less call is byte-identical."""
    assert cp._remote_arguments("CUST-1", None) == {"customer_id": "CUST-1"}
    assert cp._remote_arguments("CUST-1", {}) == {"customer_id": "CUST-1"}


def test_customer_id_survives_alongside_the_extra_args() -> None:
    assert cp._remote_arguments("CUST-1", {"invoice_id": "INV-9"}) == {
        "customer_id": "CUST-1",
        "invoice_id": "INV-9",
    }


def test_a_non_dict_args_value_is_ignored_rather_than_crashing() -> None:
    """Defence in depth — ``execute_tool`` already rejects non-objects."""
    assert cp._remote_arguments("CUST-1", ["nope"]) == {"customer_id": "CUST-1"}  # type: ignore[arg-type]


# --- what reaches the wire --------------------------------------------------


def test_call_remote_puts_both_customer_id_and_the_extra_arg_on_the_wire(
    sent: list[dict[str, Any]],
) -> None:
    cp._call_remote(
        _connector(),
        "ext.vendor.get_invoice",
        "CUST-1",
        args={"invoice_id": "INV-9", "include_lines": True},
    )
    arguments = _arguments(sent)
    assert arguments["customer_id"] == "CUST-1"
    assert arguments["invoice_id"] == "INV-9"
    assert arguments["include_lines"] is True
    assert sent[0]["params"]["name"] == "get_invoice"


def test_call_remote_without_args_still_sends_only_customer_id(
    sent: list[dict[str, Any]],
) -> None:
    cp._call_remote(_connector(), "ext.vendor.get_invoice", "CUST-1")
    assert _arguments(sent) == {"customer_id": "CUST-1"}


def test_dispatch_threads_args_down_to_the_request(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(cp, "mcp_client_enabled", lambda: True)
    monkeypatch.setattr(cp, "get_connector", lambda _id: _connector())
    monkeypatch.setattr(cp.circuit, "record_success", lambda _cid: None)

    result = cp.dispatch(
        "ext.vendor.get_invoice",
        customer_id="CUST-1",
        connector_id="conn-args-test",
        args={"invoice_id": "INV-9"},
    )

    assert result.get("status") == "paid"
    assert _arguments(sent) == {"customer_id": "CUST-1", "invoice_id": "INV-9"}


# --- the call site the finding names ----------------------------------------


def test_execute_tool_forwards_the_models_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """``bot_tools.py`` is where the arguments were parsed and then dropped."""
    import bot_tools

    seen: dict[str, Any] = {}

    def _dispatch(name: str, **kwargs: Any) -> dict[str, Any]:
        seen["name"] = name
        seen.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(cp, "dispatch", _dispatch)

    ctx = bot_tools.ToolContext(
        job_id="job-1",
        conversation_id="conv-1",
        customer_id="CUST-1",
        interaction_id=None,
        bot_id=None,
        customer_text="which invoice is open?",
        intent="payment_intent",
    )
    ok, result, _latency = bot_tools.execute_tool(
        ctx, "ext.vendor.get_invoice", '{"invoice_id": "INV-9"}'
    )

    assert ok is True
    assert result == {"ok": True}
    assert seen["customer_id"] == "CUST-1"
    assert seen["args"] == {"invoice_id": "INV-9"}
