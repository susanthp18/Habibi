"""Identity-bound CRM / KB tools for the voice FlowManager.

Closure factory (plan §4.4): the model supplies only business args;
customer_id / account_id / interaction_id come from VoiceSession.

Unification (pipecat_unification_plan §2.2 / §4):
- Wire contract comes from ``agent_core.tools.catalog`` — the same specs the
  WhatsApp catalog renders, so ``promise_date`` cannot drift from
  ``promisedDate`` again.
- Upsell / document logic comes from ``agent_core.tools.domain`` — voice and
  WhatsApp execute the *same* eligibility rules and write the same rows.
- CRM writes emit an RTVI ``crm.entity`` message so the Inspector can deep-link.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

# Not `from pipecat.flows import ...` directly: this module is the trunk the
# built-in flow export hangs off, and the API image has no pipecat. See
# agent_core/tools/pipecat_compat.py — under pipecat these are pipecat's own
# objects and nothing about a call changes.
from agent_core.tools.pipecat_compat import NO_RESPONSE, flows_tool_options

from agent_core.tools.catalog import (
    CATALOG,
)
from agent_core.tools.grant import VOICE_ALWAYS as ALWAYS_ON  # live filter; do not restate
from voice.rtvi_events import RtviEmitter
from voice.session import VoiceSession

from voice.tool_state import (  # noqa: F401  -- re-exported: callers import from here
    AsyncStartRecording,
    DeveloperInjector,
    DeveloperReplacer,
    HARDSHIP_UPSELL_REASONS,
    KB_CONFIDENCE_THRESHOLD,
    NextNodeFactory,
    ToolState,
    _FAREWELL_TASK,
    _PRE_CLOSE_TASK,
    _PROBE_SENTIMENT_FLOOR,
    _VERIFY_METHODS,
    _account_tail,
    _end_node,
    _session_tasks,
    _session_tasks_lock,
    _speakable_inr,
    _transfer_mode,
    drain_background_tasks,
    release_session_tasks,
    spawn_session_task,
    ToolBuildContext,
)
from voice import tools_identity
from voice import tools_scope
from voice import tools_offers
from voice import tools_position
from voice import tools_negotiate
from voice import tools_knowledge
from voice import tools_closing
from voice import tools_handoff

logger = logging.getLogger(__name__)

#: The public surface. Every name here was reachable as ``voice.tools.X``
#: before the handler sections became modules; the trunk lives in
#: ``voice.tool_state`` and is re-exported so no caller moved.
__all__ = [
    "build_tools",
    "ToolState",
    "ToolBuildContext",
    "ALWAYS_ON",
    "CATALOG",
    "NO_RESPONSE",
    "flows_tool_options",
    "spawn_session_task",
    "drain_background_tasks",
    "release_session_tasks",
    "KB_CONFIDENCE_THRESHOLD",
    "HARDSHIP_UPSELL_REASONS",
    "NextNodeFactory",
    "AsyncStartRecording",
    "DeveloperInjector",
    "DeveloperReplacer",
    "_session_tasks",
    "_session_tasks_lock",
    "_PRE_CLOSE_TASK",
    "_FAREWELL_TASK",
    "_transfer_mode",
    "_account_tail",
    "_end_node",
]


def build_tools(
    session: VoiceSession,
    *,
    bot_id: str | None,
    start_recording: AsyncStartRecording | None,
    nodes: dict[str, NextNodeFactory],
    emitter: RtviEmitter | None = None,
    kb_snapshot_id: str | None = None,
    inject_developer: DeveloperInjector | None = None,
    replace_developer: DeveloperReplacer | None = None,
    persona: dict[str, Any] | None = None,
    channel: str = "sandbox_live",
    on_kb_tool_used: Callable[[], None] | None = None,
    # Reads voice/turn_probe.py: "has this response already emitted text?".
    # Lets a silent-by-nature tool skip a pointless second inference without
    # risking dead air when the model called it without speaking first.
    spoke_this_response: Callable[[], bool] | None = None,
    # Graph shape. legacy → ("state_position", "gated_upsell");
    # hub → ("collections_hub", None), where a successful PTP stays put.
    hub_node: str = "state_position",
    upsell_node: str | None = "gated_upsell",
    sink: Any | None = None,
    allowed_tool_names: set[str] | None = None,
    attached_skills: list[Any] | None = None,
    agent_card: dict[str, Any] | None = None,
    #: Namespace -> what that fleet member may execute, from
    #: ``CompiledBundle.grant_by_specialist``. Empty (the only case today) keeps
    #: the single grant below exactly as it was.
    specialist_grants: dict[str, set[str]] | None = None,
    specialist_entries: dict[str, str] | None = None,
) -> tuple[ToolState, dict[str, Any]]:
    """Return (state, name→direct_function | FlowsFunctionSchema) bound to this session."""

    state = ToolState()
    # The registry is populated by the caller (build_collections_flow) after
    # this returns — hold the same dict, not a copy, so `state.nodes` reflects
    # the live graph. Exposed for tests and for debugging a bad transition.
    state.nodes = nodes
    state.allowed_tools = allowed_tool_names
    state.specialist_grants = {k: set(v) for k, v in (specialist_grants or {}).items()}
    state.specialist_entries = dict(specialist_entries or {})
    state.attached_skills = list(attached_skills or [])
    rtvi = emitter or RtviEmitter(enabled=False)

    # The closure scope, as an object the sections can read.
    ctx = ToolBuildContext(
        session=session,
        bot_id=bot_id,
        start_recording=start_recording,
        nodes=nodes,
        emitter=emitter,
        kb_snapshot_id=kb_snapshot_id,
        inject_developer=inject_developer,
        replace_developer=replace_developer,
        persona=persona,
        channel=channel,
        on_kb_tool_used=on_kb_tool_used,
        spoke_this_response=spoke_this_response,
        hub_node=hub_node,
        upsell_node=upsell_node,
        sink=sink,
        allowed_tool_names=allowed_tool_names,
        attached_skills=attached_skills,
        agent_card=agent_card,
        specialist_grants=specialist_grants,
        specialist_entries=specialist_entries,
        state=state,
        rtvi=rtvi,
    )
    # Sections in dependency order: `tools_scope` defines the helpers every
    # section reads (_spec, _node, _traced ...) and `tools_offers` the ones the
    # position/knowledge/closing/handoff sections read (_sink_call,
    # _close_probe_node). The final dict is assembled in the order the tools
    # were always listed, which the schema snapshot pins.
    tools_scope.build(ctx)
    built: dict[str, Any] = {}
    built.update(tools_identity.build(ctx))
    built.update(tools_offers.build(ctx))
    built.update(tools_position.build(ctx))
    built.update(tools_negotiate.build(ctx))
    built.update(tools_knowledge.build(ctx))
    built.update(tools_closing.build(ctx))
    built.update(tools_handoff.build(ctx))
    tools = {
        "disclose_recording": built["disclose_recording"],
        "capture_call_goal": built["capture_call_goal"],
        "verify_identity": built["verify_identity"],
        "refuse_verification": built["refuse_verification"],
        "not_account_holder": built["not_account_holder"],
        "get_account_position": built["get_account_position"],
        "get_customer_context": built["get_customer_context"],
        "get_payment_history": built["get_payment_history"],
        "get_emi_schedule": built["get_emi_schedule"],
        "begin_negotiate": built["begin_negotiate"],
        "begin_dispute": built["begin_dispute"],
        "begin_wrap_up": built["begin_wrap_up"],
        "return_to_position": built["return_to_position"],
        "create_promise_to_pay": built["create_promise_to_pay"],
        "flag_dispute": built["flag_dispute"],
        "evaluate_authority": built["evaluate_authority"],
        "apply_goodwill": built["apply_goodwill"],
        "request_callback": built["request_callback"],
        "add_customer_note": built["add_customer_note"],
        "capture_nonpayment_reason": built["capture_nonpayment_reason"],
        "set_contact_preference": built["set_contact_preference"],
        "recommend_next_offer": built["recommend_next_offer"],
        "check_product_eligibility": built["check_product_eligibility"],
        "capture_lead": built["capture_lead"],
        "decline_offer": built["decline_offer"],
        "request_documents": built["request_documents"],
        "search_knowledge_base": built["search_knowledge_base"],
        "pause_for_caller": built["pause_for_caller"],
        "escalate_to_human": built["escalate_to_human"],
        "handoff_to_agent": built["handoff_to_agent"],
        "load_skill": built["load_skill_tool"],
        "run_skill_script": built["run_skill_script"],
        "end_call": built["end_call"],
    }
    # ADR-0002: a missing grant is deny-all. What a cardless voice mouth keeps
    # (the flow-control floor: greet, disclose, verify, hang up) is decided by
    # ToolGrant.for_card(None) -- one statement -- and a carded grant already
    # carries its floor, so nothing is unioned back here.
    #
    # With a fleet this is the *union* over members, and the narrowing to the
    # speaking one happens per node in `flows_dynamic` through
    # `state.may_offer`. Building one dict is what keeps a hop a pointer swap
    # rather than a rebuild of every tool schema mid-call; with no fleet the
    # union is empty and this is the same one-shot filter it always was.
    if allowed_tool_names is None:
        from agent_core.tools.grant import ToolGrant

        allowed_tool_names = ToolGrant.for_card(None, (), channel="voice").allowed
    keep = set(allowed_tool_names)
    for grant in state.specialist_grants.values():
        keep |= set(grant)
    tools = {k: v for k, v in tools.items() if k in keep}
    return state, tools
