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


# Semantic required args on the text-channel OpenAI rendering. Strict mode
# lists every property as required (optionality is a nullable type); this map
# is the ArgSpec.required set, so dropping ``required=True`` from a money tool
# is a test failure rather than a silent catalog edit.
EXPECTED_TEXT_REQUIRED: dict[str, tuple[str, ...]] = {
    "get_customer_context": (),
    "get_payment_history": (),
    "get_emi_schedule": (),
    "identify_customer": (),
    "create_promise_to_pay": ("amount", "promise_date"),
    "revise_promise_to_pay": ("reason",),
    "flag_dispute": ("dispute_type",),
    "capture_nonpayment_reason": ("reason",),
    "set_contact_preference": (),
    "evaluate_authority": (),
    "apply_goodwill": ("decision_id",),
    "request_callback": ("scheduled_at",),
    "add_customer_note": ("text",),
    "escalate_to_human": ("reason",),
    "handoff_to_agent": ("target_bot_id", "reason"),
    "load_skill": ("slug",),
    "run_skill_script": ("name",),
    "request_documents": ("document_type",),
    "ingest_customer_document": ("filename", "mime_type"),
    "recommend_next_offer": (),
    "decline_offer": (),
    "check_product_eligibility": ("product_id",),
    "capture_lead": ("product_id",),
    "search_knowledge_base": ("query",),
}


def test_whatsapp_definitions_render_from_catalog():
    """The text-channel OpenAI rendering is the WhatsApp wire contract.

    ``TOOL_DEFINITIONS`` is gone — WhatsApp offers ``CATALOG.openai_tools()``
    directly — so there is no second list to deep-equal. Handler names are
    pinned by ``test_every_handler_has_a_spec_and_vice_versa``. This test
    pins what a name check cannot: required fields, and the rule that
    camelCase aliases stay off the published schema.
    """
    rendered = {t["function"]["name"]: t for t in CATALOG.openai_tools()}
    specs = {s.name: s for s in CATALOG.for_channel(CHANNEL_TEXT)}

    assert set(rendered) == set(EXPECTED_TEXT_REQUIRED), (
        f"only in rendering: {set(rendered) - set(EXPECTED_TEXT_REQUIRED)}; "
        f"only in pin: {set(EXPECTED_TEXT_REQUIRED) - set(rendered)}"
    )
    assert set(rendered) == set(specs)

    for name, definition in rendered.items():
        spec = specs[name]
        params = definition["function"]["parameters"]
        props = params["properties"]
        required = params.get("required", [])
        aliases = {alias for arg in spec.args for alias in arg.aliases}

        assert tuple(spec.required_names()) == EXPECTED_TEXT_REQUIRED[name], name
        for field in EXPECTED_TEXT_REQUIRED[name]:
            assert field in required, f"{name} dropped required field {field}"
            assert field in props, f"{name} dropped required property {field}"
        assert aliases.isdisjoint(props), (
            f"{name} re-published aliases {aliases & set(props)}"
        )
        for prop in props:
            assert prop == prop.lower(), f"{name}.{prop} is not snake_case"

    # The unification regression this module exists to prevent.
    ptp_props = rendered["create_promise_to_pay"]["function"]["parameters"]["properties"]
    assert "promise_date" in ptp_props
    assert "promisedDate" not in ptp_props


def test_every_handler_has_a_spec_and_vice_versa():
    """A handler without a spec can never be called; a spec without a handler lies to the model."""
    import bot_tools

    declared = {t["function"]["name"] for t in CATALOG.openai_tools()}
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


def test_declared_ranges_are_enforced_on_every_dispatcher() -> None:
    """CATALOG-6: `limit`'s maximum was clamped on voice by hand and dropped
    from the wire schema on text, so a model could ask for 500 rows."""
    from agent_core.tools.catalog import CATALOG

    spec = next(s for s in CATALOG.specs.values() if any(a.maximum is not None for a in s.args))
    arg = next(a for a in spec.args if a.maximum is not None)
    out = spec.normalize_args({arg.name: arg.maximum * 10})
    assert out[arg.name] == arg.maximum
    if arg.minimum is not None:
        assert spec.normalize_args({arg.name: arg.minimum - 10})[arg.name] == arg.minimum


def test_the_voicemail_names_the_same_agent_as_the_prompt(monkeypatch) -> None:
    """PERSONA-7: the script read persona keys PersonaState never carries."""
    from voice.amd import voicemail_script

    monkeypatch.setenv("AGENT_NAME", "Asha")
    script = voicemail_script({"name": "ignored", "agentName": "ignored"}, contacts={"issuer": "Test Bank", "contactNumber": "1800 000"})
    assert script is None or script.startswith("Hello, this is Asha calling from Test Bank.")
