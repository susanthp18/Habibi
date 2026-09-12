"""Voice tools -- the specialist hop, skills, and ending the call.

One section of the voice tool set: the handlers that used to be closures
inside ``voice.tools.build_tools``. ``build(ctx)`` receives the closure
scope as a ``ToolBuildContext`` and unpacks the names it reads, so every
handler body below is byte-for-byte what it was -- a move, pinned by
``tests/test_voice_tool_schemas_snapshot.py``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

# Not `from pipecat.flows import ...` directly: this module is the trunk the
# built-in flow export hangs off, and the API image has no pipecat. See
# agent_core/tools/pipecat_compat.py — under pipecat these are pipecat's own
# objects and nothing about a call changes.

from agent_core.tools.catalog import (
    CATALOG,
)
from agent_core.tools import domain

from voice.tool_state import (
    ToolBuildContext,
    _FAREWELL_TASK,
    _end_node,
)

logger = logging.getLogger(__name__)


def build(ctx: ToolBuildContext) -> dict[str, Any]:
    """The tools of this section, keyed by the variable name build_tools used."""
    _close_probe_node = ctx._close_probe_node
    _node = ctx._node
    _spec = ctx._spec
    agent_card = ctx.agent_card
    bot_id = ctx.bot_id
    replace_developer = ctx.replace_developer
    rtvi = ctx.rtvi
    session = ctx.session
    state = ctx.state


    def _handoff_edge(target: str) -> dict[str, Any]:
        """The card's own edge to ``target``, or an empty dict.

        Read from the raw card rather than a parsed one: this runs on the audio
        path, the fields wanted are three strings, and a card that will not parse
        must still be able to hand off — the allowlist has already decided
        whether it may.
        """
        from agent_core.cards.routing import handoff_edge

        return handoff_edge(agent_card or {}, target)

    def _max_hops() -> int:
        memory = (agent_card or {}).get("memory")
        if isinstance(memory, dict):
            try:
                return max(0, int(memory.get("max_hops_per_call", 2)))
            except (TypeError, ValueError):
                pass
        return 2

    async def _handoff_to_agent_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        args = CATALOG.normalize("handoff_to_agent", args)
        target = str(args.get("target_bot_id") or "").strip()
        reason = str(args.get("reason") or "").strip()
        payload = args.get("payload")
        from agent_core.context import (
            HANDOFF_PACKET_PREFIX,
            handoff_packet,
            handoff_packet_message,
        )
        from agent_core.tools.handoff_allowlist import handoff_allowlist

        allowlist = handoff_allowlist(
            agent_card=agent_card,
            bot_id=bot_id,
        )
        edge = _handoff_edge(target)
        # Three sources because the facts are in three places: disclosure_done
        # is ToolState's, language and sentiment are the turn's understanding.
        packet = handoff_packet(session, state, session.understanding)
        carry = str(edge.get("carry") or "brief")
        result = await asyncio.to_thread(
            domain.handoff_to_agent,
            interaction_id=session.interaction_id,
            from_bot_id=bot_id,
            target_bot_id=target,
            reason=reason,
            payload=str(payload) if payload is not None else None,
            allowlist=allowlist,
            packet=packet,
            carry=carry,
            turn_index=getattr(session, "turn_index", None),
            deployment_id=session.deployment_id,
            max_hops=_max_hops(),
            payload_schema=edge.get("payload_schema") or edge.get("payloadSchema") or None,
        )
        if not result.ok:
            out = result.to_llm()
            # The author's own words for a refusal, when they wrote any. Applied
            # here rather than before the write because the cap is now counted in
            # the same transaction that records the hop — one place, both
            # channels, and a count that survives a reconnect.
            refusal = str(edge.get("refusal_line") or "").strip()
            if refusal and isinstance(out, dict):
                out["say"] = refusal
            return out, None
        if replace_developer:
            message = handoff_packet_message(packet)
            if message:
                # Replace, never append: a second hop must evict the first
                # packet rather than leave the model holding two versions of
                # what was established.
                await replace_developer(HANDOFF_PACKET_PREFIX, message)
        out = result.to_llm()
        bridge = str(edge.get("bridge_line") or "").strip()
        if bridge and isinstance(out, dict):
            out["say"] = bridge
        # The hop, as a *move*. Setting `active_specialist` never swapped
        # anything: the offer is narrowed by the node's namespace, so until the
        # cursor lands on one of the receiving member's nodes the specialist
        # goes on speaking with the sender's tools. `_node` resolves the entry
        # against the target's namespace and sets the speaker from what it
        # resolved, so the grant, the local node names and the offer all follow
        # in one step.
        #
        # Returning the node rather than emitting a `go_to_*` transition tool is
        # deliberate: a second door to the same hop would be one the cap, the
        # ledger row and the packet do not guard.
        entry = str(edge.get("entry_node") or "").strip() or state.specialist_entries.get(target, "")
        landing = _node(entry, namespace=target) if entry else None
        if entry and landing is None:
            # The target has no such node — or no authored graph at all. The hop
            # is still recorded and still announced; what does not happen is the
            # tool swap. G-F15 reports this at publish; mid-call it degrades to
            # exactly the behaviour that shipped before.
            logger.warning("handoff to %s: no entry node %r in the graph", target, entry)
        return out, landing

    handoff_to_agent = _spec("handoff_to_agent", _handoff_to_agent_handler)

    async def _load_skill_handler(args: dict[str, Any], flow_manager) -> tuple[Any, dict[str, Any] | None]:
        args = CATALOG.normalize("load_skill", args)
        from agent_core.skills.runtime import SKILL_BODY_PREFIX, load_skill

        slug = str(args.get("slug") or "").strip()
        result = load_skill(
            slug,
            list(state.attached_skills or []),
            include_references=bool(args.get("include_references")),
            # The turn's grant, so the reply cannot name a tool the registry
            # will not run. Empty rather than None on a grantless session, for
            # the reason bot_tools gives at the same call.
            allowed=state.allowed_tools or frozenset(),
        )
        if not result.get("ok"):
            return result, None
        state.active_skill = slug
        message = result.get("message")
        if message and replace_developer:
            await replace_developer(SKILL_BODY_PREFIX, message)
        return {
            "ok": True,
            "slug": slug,
            "allowed_tools": result.get("allowed_tools") or [],
            "say": "continue with the loaded skill; do not narrate that a skill was loaded",
        }, None

    load_skill_tool = _spec("load_skill", _load_skill_handler)

    async def _run_skill_script_handler(args: dict[str, Any], flow_manager) -> tuple[Any, dict[str, Any] | None]:
        args = CATALOG.normalize("run_skill_script", args)
        from agent_core.skills.scripts import run_script
        import json as _json

        name = str(args.get("name") or "").strip()
        payload = args.get("payload")
        if isinstance(payload, str):
            try:
                payload = _json.loads(payload or "{}")
            except _json.JSONDecodeError:
                return {"ok": False, "error": "payload_must_be_json_object"}, None
        return run_script(name, payload if isinstance(payload, dict) else {}), None

    run_skill_script = _spec("run_skill_script", _run_skill_script_handler)

    async def end_call(flow_manager) -> tuple[Any, dict[str, Any] | None]:
        """End the call when the caller says goodbye mid-conversation.

        Transitions to a terminal node whose post_action is end_conversation
        (Flows waits for TTS, then EndFrame). Do not guess sleep durations.

        Routed through ``_node("call_ended")`` rather than returning an inline
        node: the inline form bypassed the registry, so ``state.current_node``
        never became "call_ended" and the RTVI ``flow.node`` stream missed the
        final hop. That matters more under the hub graph, where wrap_up is gone
        and *every* clean ending comes through here — and it is what makes the
        call's disposition derivable at teardown.
        """
        # The hub graph has no wrap_up node, so EVERY clean ending arrives here.
        # That makes this the one chokepoint where the close probe can be
        # guaranteed to run once, on both graphs, from every path.
        probe = await _close_probe_node()
        if probe is not None:
            return {"ok": True, "probing": True}, probe

        await rtvi.lifecycle(phase="ending", reason="caller_goodbye")
        node = _node("call_ended")
        if node is None:
            # Registry miss (a caller that built tools without nodes) — fall
            # back to the inline node so the call can still end cleanly.
            node = _end_node(farewell_task=_FAREWELL_TASK, session=session)
        return {"ok": True, "ended": True}, node

    return {
        "handoff_to_agent": handoff_to_agent,
        "load_skill_tool": load_skill_tool,
        "run_skill_script": run_skill_script,
        "end_call": end_call,
    }
