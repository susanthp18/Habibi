"""What the boundary says when something crosses it.

A rejected webhook signature raised 401 and wrote nothing; an investigation
of "we never got the payment" had no line to start from. The transcript
export left long digit runs that the bundle export masks. A turn Azure
answered after the gateway raised was metered as gateway spend.
"""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient


def test_a_rejected_webhook_signature_is_logged_with_its_request_id(caplog) -> None:
    from main import app

    with caplog.at_level(logging.WARNING, logger="routers.webhooks"):
        with TestClient(app) as client:
            resp = client.post(
                "/webhooks/payments/razorpay",
                content=b'{"x":1}',
                headers={"X-Payment-Signature": "bad", "X-Request-Id": "req-probe-1"},
            )
    assert resp.status_code == 401
    lines = [r.getMessage() for r in caplog.records if "webhook rejected" in r.getMessage()]
    assert lines and "provider=razorpay" in lines[0] and "invalid_signature" in lines[0]
    assert "request_id=" in lines[0]
    assert '"x":1' not in lines[0], "the body is the PSP's; it is not logged"


def test_the_transcript_export_masks_long_identifiers() -> None:
    from voice import persist

    payload = persist.transcript_export_payload(
        "IX-PROBE", None, [{"turn_index": 0, "speaker": "customer", "text": "my card is 4111222233334444"}]
    )
    text = payload["turns"][0]["text"]
    assert "4111222233334444" not in text and "[REDACTED-ID]" in text


def test_azure_fallthrough_is_not_metered_as_gateway_spend() -> None:
    """The gateway meters the turns it serves itself; the kill-switch path is Azure's."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "azure_openai.py"
    tree = ast.parse(src.read_bytes())
    refs = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("azure_openai.chat_with_tools")
    }
    assert "azure_openai.chat_with_tools" in refs
    joined = {
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        and any(isinstance(v, ast.Constant) and v.value.startswith("llm_gateway.") for v in node.values)
    }
    assert not joined, "azure_openai.py must not mint an llm_gateway.* source_ref"
