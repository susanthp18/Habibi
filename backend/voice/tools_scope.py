"""Voice tools -- the scope every handler section shares.

The helpers that used to open ``build_tools``: the audit/gate wrapper every
tool goes through (``_traced``), the spec factory (``_spec``), the node
resolver a hop lands through (``_node``), the RTVI announcer, the context
refresh, and the identity floor (``_require_customer``). ``build(ctx)`` defines
them over the same closure scope and attaches them to ``ctx`` for the
sections. Bodies are byte-for-byte what they were.
"""

from __future__ import annotations

import asyncio
import logging
import time
from functools import wraps
from typing import Any, Callable

# Not `from pipecat.flows import ...` directly: this module is the trunk the
# built-in flow export hangs off, and the API image has no pipecat. See
# agent_core/tools/pipecat_compat.py — under pipecat these are pipecat's own
# objects and nothing about a call changes.

from voice.context_edit import CRM_CARD_PREFIX
from agent_core.tools import ToolResult
from agent_core.tools.catalog import (
    CATALOG,
)
from voice import persist

from voice.tool_state import (
    spawn_session_task,
    ToolBuildContext,
)


logger = logging.getLogger(__name__)


def build(ctx: ToolBuildContext) -> None:
    """Attach the shared helpers to ``ctx``."""
    agent_card = ctx.agent_card
    bot_id = ctx.bot_id
    inject_developer = ctx.inject_developer
    nodes = ctx.nodes
    replace_developer = ctx.replace_developer
    rtvi = ctx.rtvi
    session = ctx.session
    sink = ctx.sink
    state = ctx.state

    _TERMINAL_NODES = frozenset({"wrap_up", "terminate_politely", "escalate_close", "call_ended"})

    def _traced(name: str, handler: Callable[..., Any]) -> Callable[..., Any]:
        """Time a tool handler and queue an audit row for it.

        Voice tool calls were never written to ``bot_tool_calls`` — the table
        was keyed by ``job_id``, which only the WhatsApp/text path has — so the
        CRM audit trail covered one channel out of two while the voice bot was
        the one creating promises and disputes.

        Turn attribution is ``session.turn_index``, i.e. the **customer turn
        that caused the call**. The bot turn index is not allocated until
        ``on_assistant_turn_stopped``, which is after every tool in the turn has
        run, so `+1` would be attributing to a turn that does not exist yet.
        Do not "fix" this.
        """

        @wraps(handler)
        async def _wrapper(*args: Any, **kwargs: Any):
            started = time.perf_counter()
            ok = True
            error: str | None = None
            # Pipecat Flows calls a handler as (args, flow_manager); the audit
            # row wants the first of those. Read defensively rather than
            # unpacking: a handler signature change must break the handler, not
            # silently break the audit trail with it.
            call_args = args[0] if args and isinstance(args[0], dict) else None
            result: Any = None
            try:
                from voice.call_trace import event as _trace_event
                from voice.call_trace import session_fields

                arg_keys = ",".join(sorted(call_args)) if call_args else None
                _trace_event(
                    "tool.called",
                    **session_fields(session),
                    tool=name,
                    node=state.current_node,
                    arg_keys=arg_keys,
                )
            except Exception:
                logger.debug("tool.called trace failed", exc_info=True)
            from agent_core.tools.gates import enforce_human_gate

            identity_ok = bool(session.identity_verified) and bool(session.customer_id) and (
                not persist.is_unknown_caller(session.customer_id)
            )
            blocked = enforce_human_gate(name, card=agent_card, identity_verified=identity_ok)
            try:
                if blocked:
                    result = ({"ok": False, "error": blocked}, None)
                    return result
                result = await handler(*args, **kwargs)
                return result
            except Exception as exc:
                ok = False
                error = type(exc).__name__
                raise
            finally:
                latency_ms = int((time.perf_counter() - started) * 1000)
                payload = result[0] if isinstance(result, tuple) and result else result
                next_node = result[1] if isinstance(result, tuple) and len(result) > 1 else None
                if isinstance(payload, dict):
                    if payload.get("ok") is False or payload.get("error"):
                        ok = False
                        error = str(payload.get("error") or error or "failed")
                    elif payload.get("suppressed"):
                        error = str(payload.get("reason") or "suppressed")
                if sink is not None:
                    try:
                        sink.enqueue_tool_call(
                            tool_name=name,
                            turn_index=session.turn_index,
                            result_ok=ok,
                            error=error,
                            latency_ms=latency_ms,
                            args=call_args,
                        )
                    except Exception:
                        logger.debug("tool call audit enqueue failed", exc_info=True)
                try:
                    from voice.call_trace import event as _trace_event
                    from voice.call_trace import session_fields

                    next_name = next_node if isinstance(next_node, str) else None
                    extra: dict[str, Any] = {}
                    if isinstance(payload, dict):
                        if "confident" in payload:
                            extra["confident"] = 1 if payload.get("confident") else 0
                        if "topScore" in payload:
                            extra["topScore"] = payload.get("topScore")
                        results = payload.get("results")
                        if isinstance(results, list):
                            extra["n"] = len(results)
                    _trace_event(
                        "tool.result",
                        **session_fields(session),
                        tool=name,
                        ok=1 if ok else 0,
                        error=error,
                        next=next_name,
                        ms=latency_ms,
                        **extra,
                    )
                except Exception:
                    logger.debug("tool.result trace failed", exc_info=True)

        return _wrapper

    def _spec(name: str, handler: Callable[..., Any]) -> Any:
        """Flows schema for a catalog tool, with audit tracing attached."""
        spec = CATALOG.get(name)
        if spec is None:
            raise KeyError(f"tool_not_in_catalog:{name}")
        if name == "handoff_to_agent":
            # The card's own handoffs, in the tool the model is offered. Without
            # this the description named two example bot ids and the `when`
            # conditions the Agent graph tab calls "guidance for the model"
            # reached no model at all. Same card, same targets, as the allowlist
            # that then enforces the call.
            from agent_core.tools.handoff_allowlist import handoff_tool_spec

            spec = handoff_tool_spec(spec, agent_card=agent_card, bot_id=bot_id)
        return spec.to_flows_schema(_traced(name, handler))


    def _node(name: str, *, namespace: str | None = None) -> dict[str, Any] | None:
        # Built-in tools transition by literal local name — `_node("wrap_up")`.
        # In a fleet graph every member owns a `wrap_up`, so the name is resolved
        # against the *speaking* member's namespace first. A flat graph resolves
        # to itself, which is why this is not gated on a flag.
        #
        # `namespace` is how a hop lands somewhere else: it names the member
        # being entered, and the resolved key then sets the speaker below.
        from flow_graph import local_key, resolve_key, split_key

        key = resolve_key(nodes, name, namespace=namespace or state.active_specialist) or name
        factory = nodes.get(key)
        if factory is None:
            # Resolve first: an unknown name must not move current_node (which
            # selects the KB corpus) or latch session.extra["ending"] on a call
            # that is not actually ending.
            logger.warning("unknown flow node requested: %s", name)
            return None
        name = key
        # The speaker follows the cursor. This is the whole swap: the offer is
        # narrowed by the node's namespace (flows_dynamic), and the node we just
        # landed on is the receiving member's — so its grant, and its local
        # names, take effect from here. `FlowWalker.move_to` applies the same
        # rule on the text mouths.
        state.active_specialist = split_key(name)[0] or state.active_specialist
        if local_key(name) in _TERMINAL_NODES:
            # Last terminal wins: the first hop (often escalate_close) is not
            # the reason when the caller later asked to hang up.
            session.mark_ending(f"flow_node:{name}", override=True)
        previous = state.current_node
        state.current_node = name
        session.extra["flow_node"] = name
        try:
            from voice.call_trace import event as _trace_event
            from voice.call_trace import session_fields

            _trace_event(
                "flow.node",
                **session_fields(session),
                from_node=previous,
                to=name,
            )
        except Exception:
            logger.debug("flow.node trace failed", exc_info=True)
        # Fire-and-forget: the transition must not wait on the data channel.
        spawn_session_task(session.session_id, rtvi.flow_node(name=name, previous=previous))
        return factory()

    async def _announce(result: ToolResult, tool: str, *, inject_delta: bool = True) -> None:
        """Push a CRM chip to the Inspector and a short developer delta to the LLM.

        ``inject_delta=False`` for tools that also schedule a context refresh:
        the refreshed CRM card supersedes the delta within one event-loop turn,
        and shipping both costs tokens and creates a contradiction surface.
        """
        if not result.ok or not result.entity:
            return
        await rtvi.crm_entity(
            entity=result.entity,
            entity_id=result.entity_id,
            deep_link=result.deep_link,
            tool=tool,
            summary=result.spoken_summary,
        )
        if inject_delta and inject_developer and result.entity_id and state.call_context:
            try:
                await inject_developer(
                    [state.call_context.delta_message(f"{result.entity} {result.entity_id} created")]
                )
            except Exception:
                logger.debug("developer delta injection failed", exc_info=True)

    def _schedule_context_refresh(reason: str) -> None:
        """Re-read the CRM and replace the injected card. Non-blocking.

        The intelligence bug this fixes: CallContext was loaded exactly once, at
        verify_identity, and refresh_from_crm() was never called anywhere in the
        voice path — so after booking a PTP the bot's own context still said the
        account had no open promises, and "what did I just agree to" could not be
        answered from context.

        Deliberately fire-and-forget. The model gets its tool result immediately;
        a get_customer read is single-digit milliseconds against the ~1s the
        model still needs to finish inference and speak, so the refreshed card
        lands before the next turn. Worst case it lands one turn late, which is
        stale-but-not-wrong.

        Scoped to this session's task bucket so a hangup drains it rather than
        leaving it pending (voice/tools.py spawn_session_task).
        """
        ctx = state.call_context
        if ctx is None or replace_developer is None:
            return
        try:
            from voice.config import voice_context_refresh

            if not voice_context_refresh():
                return
        except Exception:
            return

        async def _run() -> None:
            try:
                await asyncio.to_thread(ctx.refresh_from_crm)
                await replace_developer(CRM_CARD_PREFIX, ctx.crm_card_message())
            except Exception:
                logger.debug("context refresh failed (%s)", reason, exc_info=True)

        spawn_session_task(session.session_id, _run())

    def _require_customer() -> tuple[str, None] | tuple[None, dict[str, Any]]:
        """Guard shared by every write tool."""
        if not session.identity_verified:
            return None, {"error": "identity_not_verified"}
        cid = session.customer_id
        if not cid or persist.is_unknown_caller(cid):
            return None, {"error": "customer_unbound"}
        return cid, None

    # ------------------------------------------------------------ lifecycle

    #: Spoken only when the model calls disclose_recording having said nothing.
    #: Carries the disclosure and hands the turn back to the caller, because the
    #: node it transitions into listens rather than speaks.
    _FALLBACK_GREETING = (
        "Hello, this is Priya from HDFC Bank Collections. "
        "This call is recorded for quality and compliance. "
        "How can I help you today?"
    )

    ctx._FALLBACK_GREETING = _FALLBACK_GREETING
    ctx._TERMINAL_NODES = _TERMINAL_NODES
    ctx._announce = _announce
    ctx._node = _node
    ctx._require_customer = _require_customer
    ctx._schedule_context_refresh = _schedule_context_refresh
    ctx._spec = _spec
    ctx._traced = _traced
