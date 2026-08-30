"""Anti-drift contract for the voice tool surface (voice/tools.py).

``tests/test_tool_catalog.py`` pins the WhatsApp/text side (CATALOG ↔
bot_tools). This is the voice mirror. It exists because seven tools used to
declare their contract *twice* — a ToolSpec in agent_core.tools.catalog **and**
a hand-rolled Pipecat direct function with its own signature and docstring — so
the two could drift silently and nothing failed.

It also happens to be the only test that calls ``build_tools`` at all, which
means it is the only thing that catches a NameError in the tools dict. Nothing
else in the suite constructs the voice tool surface.

The nine zero-argument flow-control tools are deliberately NOT in CATALOG:
ToolSpec exists to stop argument-name drift *between channels*, and these have
no arguments and no other channel. Pinning them by name here is the cheaper and
more honest mechanism.
"""

from __future__ import annotations

import inspect

import pytest
from pipecat.flows import FlowsFunctionSchema

from agent_core.tools.catalog import CATALOG
from voice.session import VoiceSession
from voice.tools import build_tools

# Zero-arg, voice-only flow control. Adding a name here must be a conscious act.
VOICE_CONTROL_TOOLS = frozenset(
    {
        "disclose_recording",
        "refuse_verification",
        "not_account_holder",
        "begin_negotiate",
        "begin_dispute",
        "begin_wrap_up",
        "return_to_position",
        "pause_for_caller",
        "end_call",
    }
)


@pytest.fixture(scope="module")
def tools() -> dict:
    _state, built = build_tools(
        VoiceSession(session_id="VS-REGISTRY1"),
        bot_id=None,
        start_recording=None,
        nodes={},
    )
    return built


def _catalog_backed(tools: dict) -> list[str]:
    return sorted(n for n in tools if CATALOG.get(n) is not None)


def test_build_tools_constructs(tools: dict) -> None:
    """Smoke: a NameError in the tools dict is otherwise invisible to the suite.

    The assertion is on the *names*, not a count. A bare `len(tools) == 23`
    fails with "25 != 23" and tells you nothing about which tools appeared or
    vanished — which is exactly what you need to know to decide whether the
    change was intended. Adding a tool should require adding it here.
    """
    assert set(tools) == {
        # identity / call control
        "disclose_recording",
        # Records why the caller rang, before the identity ceremony, so
        # verification can be framed around their goal instead of preceding it.
        "capture_call_goal",
        "verify_identity",
        "refuse_verification",
        "not_account_holder",
        "pause_for_caller",
        "return_to_position",
        "begin_wrap_up",
        "end_call",
        "escalate_to_human",
        "handoff_to_agent",
        # account servicing
        "get_customer_context",
        "get_account_position",
        "get_payment_history",
        "get_emi_schedule",
        "request_documents",
        "add_customer_note",
        "search_knowledge_base",
        # collections
        "create_promise_to_pay",
        "begin_negotiate",
        "request_callback",
        "begin_dispute",
        "flag_dispute",
        "evaluate_authority",
        "apply_goodwill",
        # Why the borrower has not paid, as a code rather than a paragraph.
        # Skill-gated (see intersect.SKILL_GATED_TOOLS) so it costs nothing in
        # the idle prompt, and node-local on the position/hub nodes where the
        # reason is actually given.
        "capture_nonpayment_reason",
        "set_contact_preference",
        # offers — the engine chooses, the model only speaks
        "recommend_next_offer",
        "check_product_eligibility",
        "capture_lead",
        "decline_offer",
        "load_skill",
        "run_skill_script",
    }


def test_every_voice_tool_is_catalog_backed_or_declared_control(tools: dict) -> None:
    """A new hand-rolled tool that should have been catalogued fails here."""
    uncatalogued = {n for n in tools if CATALOG.get(n) is None}
    assert uncatalogued == VOICE_CONTROL_TOOLS


def test_catalog_backed_voice_tools_render_from_the_spec(tools: dict) -> None:
    """Defines "folded": the object IS the spec's rendering, not a parallel one."""
    for name in _catalog_backed(tools):
        spec = CATALOG.get(name)
        schema = tools[name]
        assert isinstance(schema, FlowsFunctionSchema), f"{name} is not spec-rendered"
        assert schema.name == name
        assert schema.description == spec.description, name
        assert schema.properties == spec.properties(), name
        assert set(schema.required) == set(spec.required_names()), name


def test_flows_options_match_spec(tools: dict) -> None:
    """Folding must not silently drop interruption / timeout behaviour.

    These rode on @flows_tool_options decorators before the fold;
    ToolSpec.cancel_on_interruption / timeout_secs carry them now, and a spec
    that forgot to set them would quietly make a slow tool uninterruptible.
    """
    for name in _catalog_backed(tools):
        spec = CATALOG.get(name)
        schema = tools[name]
        assert schema.cancel_on_interruption == spec.cancel_on_interruption, name
        assert schema.timeout_secs == spec.timeout_secs, name


def test_the_two_tools_that_need_interruption_knobs_still_have_them(tools: dict) -> None:
    """Pin the actual values, not just spec↔schema agreement.

    Both sides could be wrong together: get_account_position is called mid-
    sentence and must die on barge-in, and search_knowledge_base does network
    I/O that must not hang the turn forever.
    """
    assert tools["get_account_position"].cancel_on_interruption is True
    assert tools["search_knowledge_base"].cancel_on_interruption is True
    assert tools["search_knowledge_base"].timeout_secs == 20


def test_voice_control_tools_are_zero_argument(tools: dict) -> None:
    """The justification for keeping them out of CATALOG — hold it true."""
    for name in sorted(VOICE_CONTROL_TOOLS):
        fn = tools[name]
        assert not isinstance(fn, FlowsFunctionSchema), f"{name} is catalog-rendered"
        params = [
            p
            for p in inspect.signature(fn).parameters
            if p not in {"self", "flow_manager"}
        ]
        assert params == [], f"{name} takes arguments — it belongs in CATALOG"


def test_control_tools_are_absent_from_the_text_catalog() -> None:
    """So the WhatsApp channel can never advertise a voice-only node hop."""
    assert VOICE_CONTROL_TOOLS.isdisjoint(CATALOG.specs)


def test_folded_read_tools_apply_their_spec_defaults(tools: dict) -> None:
    """normalize() is what supplies limit=8 / limit=6 now that the Python
    default arguments are gone."""
    assert CATALOG.normalize("get_payment_history", {})["limit"] == 8
    assert CATALOG.normalize("get_emi_schedule", {})["limit"] == 6
