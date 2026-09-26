"""Pure checks for the reviewed live-tool boundary."""

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from api.services.tool_revisions import (
    LiveToolPolicy,
    approved_context,
    context_paths_used,
    live_policy_error,
    mcp_schema_digest,
    validate_external_destination,
    validate_live_snapshot,
)


def test_external_write_requires_result_schema_success_and_idempotency():
    base = {"risk": "write", "channels": ["outbound"], "min_identity": "challenge",
            "success_path": "ok", "result_schema": {"type": "object"}}
    with pytest.raises(ValidationError, match="idempotency"):
        LiveToolPolicy.model_validate(base)
    policy = LiveToolPolicy.model_validate({**base, "idempotency_parameter": "request_id"})
    assert policy.risk == "write"


def test_reviewed_egress_projects_only_named_context_fields():
    source = {"customer": {"id": "c1", "phone": "secret"}, "amount": 17}
    assert approved_context(source, "initial_context", ["initial_context.customer.id"]) == {
        "customer": {"id": "c1"}}


def test_identity_and_channel_are_checked_at_invocation():
    policy = {"channels": ["outbound"], "min_identity": "challenge"}
    assert live_policy_error(policy, {"direction": "inbound"}, True) == "tool_channel_not_approved"
    assert live_policy_error(policy, {"direction": "outbound"}, False) == "identity_not_verified"
    assert live_policy_error(policy, {"direction": "outbound"}, True) is None


def test_destination_rejects_private_dns_answer_even_with_public_first():
    answers = [(None, None, None, None, ("8.8.8.8", 443)),
               (None, None, None, None, ("127.0.0.1", 443))]
    with patch("socket.getaddrinfo", return_value=answers):
        with pytest.raises(ValueError, match="public"):
            validate_external_destination("https://example.com/path")


def test_mcp_digest_covers_full_input_and_output_schema():
    first = {"inputSchema": {"type": "object", "properties": {"x": {"type": "string"}},
                             "additionalProperties": False}, "outputSchema": {"type": "object"}}
    second = {**first, "inputSchema": {**first["inputSchema"], "additionalProperties": True}}
    assert mcp_schema_digest("lookup", {}, [], full_schema=first) != mcp_schema_digest(
        "lookup", {}, [], full_schema=second)


def test_review_requires_every_context_field_the_templates_read():
    """A blank field posted to a customer API must fail review, not the call."""
    snapshot = {
        "name": "promise", "category": "http_api",
        "definition": {"config": {
            "method": "POST", "url": "https://bank.example/promise",
            "parameters": [{"name": "amount"}],
            "preset_parameters": [
                {"name": "phone", "value_template": "{{initial_context.phone_number}}"}],
            "body_template": {"id": "{{gathered_context.reference}}"},
        }},
    }
    policy = LiveToolPolicy.model_validate({
        "risk": "read", "channels": ["outbound"], "min_identity": "challenge",
        "success_path": "ok", "result_schema": {"type": "object"},
        "egress_fields": ["initial_context.phone_number"],
    })
    # Destination resolution is covered separately; pin it so this test is
    # about the egress contract and not about DNS.
    public = [(None, None, None, None, ("93.184.216.34", 443))]
    with patch("socket.getaddrinfo", return_value=public):
        with pytest.raises(ValueError, match="gathered_context.reference"):
            validate_live_snapshot(snapshot, policy)

        policy.egress_fields.append("gathered_context.reference")
        validate_live_snapshot(snapshot, policy)


def test_context_paths_ignores_llm_arguments_and_builtins():
    used = context_paths_used({
        "url": "https://bank.example/{{loan_id}}/{{current_time_Asia/Kolkata}}",
        "preset_parameters": [{"value_template": "{{initial_context.customer_id}}"}],
    })
    assert used == {"initial_context.customer_id"}
