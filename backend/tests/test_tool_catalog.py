"""The shared tool catalog is the contract both channels render from.

These tests exist to stop the specific regression the unification plan was
written for: voice and WhatsApp independently declaring the same tool and
drifting on argument names (``promise_date`` vs ``promisedDate``,
``dispute_type`` vs ``type``, ``scheduled_at`` vs ``scheduledAt``).
"""

from __future__ import annotations

import pytest

from agent_core.tools.catalog import CATALOG
from agent_core.tools.schema import CHANNEL_TEXT, CHANNEL_VOICE


# --------------------------------------------------------------------------
# One catalog, both channels
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_name",
    [
        "create_promise_to_pay",
        "flag_dispute",
        "evaluate_authority",
        "apply_goodwill",
        "request_callback",
        "search_knowledge_base",
        "capture_lead",
        "check_product_eligibility",
        "request_documents",
        "add_customer_note",
        "escalate_to_human",
    ],
)
def test_shared_tools_are_exposed_on_both_channels(tool_name):
    """A canonical tool must be reachable from voice AND text."""
    spec = CATALOG.get(tool_name)
    assert spec is not None, f"{tool_name} missing from catalog"
    assert CHANNEL_VOICE in spec.channels
    assert CHANNEL_TEXT in spec.channels


def test_whatsapp_definitions_render_from_catalog():
    """bot_tools.TOOL_DEFINITIONS must be exactly what the catalog renders.

    Compares the *whole* definition set — every tool, property, required list
    and default — against CATALOG's own rendering path. Spot-checking a few
    names and one property let schema drift (a re-added hand-rolled entry, a
    dropped required field, a changed enum) through unnoticed, which is the
    exact regression this module exists to prevent.
    """
    import bot_tools

    # Full text-channel set, not just the names bot_tools happens to list —
    # a spec added to the catalog for text must reach the WhatsApp runtime.
    by_name = {t["function"]["name"]: t for t in CATALOG.openai_tools()}
    actual_by_name = {t["function"]["name"]: t for t in bot_tools.TOOL_DEFINITIONS}

    assert set(actual_by_name) == set(by_name), (
        f"only in bot_tools: {set(actual_by_name) - set(by_name)}; "
        f"only in catalog: {set(by_name) - set(actual_by_name)}"
    )
    for name, definition in by_name.items():
        assert actual_by_name[name] == definition, f"{name} drifted from the catalog"

    # The canonical name is snake_case on BOTH channels.
    ptp_props = actual_by_name["create_promise_to_pay"]["function"]["parameters"]["properties"]
    assert "promise_date" in ptp_props
    assert "promisedDate" not in ptp_props


def test_every_handler_has_a_spec_and_vice_versa():
    """A handler without a spec can never be called; a spec without a handler lies to the model."""
    import bot_tools

    declared = {t["function"]["name"] for t in bot_tools.TOOL_DEFINITIONS}
    handled = set(bot_tools.HANDLERS)
    assert declared - handled == set(), f"declared but unhandled: {declared - handled}"
    assert handled - declared == set(), f"handled but undeclared: {handled - declared}"


# --------------------------------------------------------------------------
# Alias normalization — backward compatibility
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool,legacy,canonical",
    [
        ("create_promise_to_pay", {"promisedDate": "2026-08-01"}, {"promise_date": "2026-08-01"}),
        ("flag_dispute", {"type": "fraud"}, {"dispute_type": "fraud"}),
        ("flag_dispute", {"transcriptSnippet": "x"}, {"summary": "x"}),
        ("evaluate_authority", {"feeType": "late_fee"}, {"fee_type": "late_fee"}),
        ("evaluate_authority", {"askedAmount": 200}, {"asked_amount": 200}),
        ("apply_goodwill", {"decisionId": "AD-1"}, {"decision_id": "AD-1"}),
        ("request_callback", {"scheduledAt": "T"}, {"scheduled_at": "T"}),
        ("request_callback", {"windowMins": 45}, {"window_mins": 45}),
        ("capture_lead", {"productId": "topup-loan"}, {"product_id": "topup-loan"}),
        ("capture_lead", {"offerAmount": 5000}, {"offer_amount": 5000}),
        ("check_product_eligibility", {"productId": "gold-loan"}, {"product_id": "gold-loan"}),
        ("identify_customer", {"accountTail": "7410"}, {"account_tail": "7410"}),
        ("request_documents", {"docType": "account_statement"}, {"document_type": "account_statement"}),
    ],
)
def test_legacy_camelcase_names_still_resolve(tool, legacy, canonical):
    """In-flight conversations emitting the old names must not KeyError."""
    assert CATALOG.normalize(tool, legacy) == canonical


def test_canonical_wins_over_alias_when_both_present():
    """A model sending both must not have the alias clobber the real value."""
    out = CATALOG.normalize(
        "create_promise_to_pay", {"promise_date": "CANON", "promisedDate": "ALIAS"}
    )
    assert out["promise_date"] == "CANON"


def test_unknown_args_are_dropped():
    """The contract is the spec, not whatever the model invented."""
    out = CATALOG.normalize("add_customer_note", {"text": "hi", "not_a_real_arg": "x"})
    assert out == {"text": "hi"}


def test_normalize_passes_through_unknown_tool():
    """An unregistered name must not silently lose its arguments."""
    assert CATALOG.normalize("no_such_tool", {"a": 1}) == {"a": 1}


def test_missing_required_is_reported():
    spec = CATALOG.get("create_promise_to_pay")
    assert spec.missing_required({"amount": 100}) == ["promise_date"]
    assert spec.missing_required({"amount": 100, "promise_date": "2026-08-01"}) == []


# --------------------------------------------------------------------------
# Deep links — what the Inspector chips point at
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool,entity,expected",
    [
        ("create_promise_to_pay", "promise", "/promises?id=PR-1"),
        ("flag_dispute", "dispute", "/disputes?id=DI-1"),
        ("request_callback", "callback", "/callbacks?id=CB-1"),
        ("capture_lead", "lead", "/upsell?id=LD-1"),
        ("request_documents", "document_request", "/documents?id=DOC-1"),
    ],
)
def test_crm_writes_deep_link_to_their_domain_page(tool, entity, expected):
    spec = CATALOG.get(tool)
    assert spec.entity == entity
    ident = expected.split("=")[-1]
    assert spec.link_for(ident) == expected


def test_link_for_none_id_is_none():
    """No row id means no chip — never a link to '/promises?id=None'."""
    assert CATALOG.get("create_promise_to_pay").link_for(None) is None


# --------------------------------------------------------------------------
# Voice adapter
# --------------------------------------------------------------------------


def test_specs_render_as_flows_schemas():
    """Voice consumes the same spec through FlowsFunctionSchema."""

    async def _handler(args, flow_manager):  # pragma: no cover - never invoked
        return {}, None

    schema = CATALOG.get("create_promise_to_pay").to_flows_schema(_handler)
    assert schema.name == "create_promise_to_pay"
    assert "promise_date" in schema.properties
    assert set(schema.required) == {"amount", "promise_date"}


def test_voice_and_text_agree_on_argument_names():
    """The regression guard: identical property names on both renderings.

    Covers every BOTH-channel tool the voice side renders from the catalog.
    The last six were folded in later — before that they were hand-rolled
    Pipecat direct functions whose Python signatures were a second, unchecked
    declaration of the same contract. get_account_position is VOICE_ONLY, so it
    has no text rendering to agree with and is covered by
    tests/test_voice_tool_registry.py instead.
    """
    for name in (
        "create_promise_to_pay",
        "flag_dispute",
        "evaluate_authority",
        "apply_goodwill",
        "request_callback",
        "capture_lead",
        "add_customer_note",
        "escalate_to_human",
        "handoff_to_agent",
        "load_skill",
        "run_skill_script",
        "search_knowledge_base",
        "get_customer_context",
        "get_payment_history",
        "get_emi_schedule",
    ):
        spec = CATALOG.get(name)
        openai_props = set(spec.to_openai_tool()["function"]["parameters"]["properties"])
        flows_props = set(spec.properties())
        assert openai_props == flows_props, f"{name} drifted between channels"


def test_openai_tools_render_full_catalog() -> None:
    tools = CATALOG.openai_tools()
    assert len(tools) >= 9
    for t in tools:
        assert t["type"] == "function"
        assert "name" in t["function"]
        assert "parameters" in t["function"]
        assert t["function"]["parameters"]["type"] == "object"


def test_flows_schema_properties_match_openai() -> None:
    async def _handler(args, flow_manager):  # pragma: no cover
        return {}, None

    for name in ("create_promise_to_pay", "flag_dispute", "request_callback"):
        spec = CATALOG.get(name)
        flows = spec.to_flows_schema(_handler)
        assert set(flows.properties) == set(
            spec.to_openai_tool()["function"]["parameters"]["properties"]
        )


def test_arg_defaults_applied_on_normalize() -> None:
    out = CATALOG.normalize("get_emi_schedule", {})
    assert out.get("limit") == 6
