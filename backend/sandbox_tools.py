"""The sandbox's tools: what each catalog tool does in rehearsal (never a
carrier, a CRM write or a connector) and the loop that offers the current
node's tools to the model under an iteration budget. Carved out of
sandbox_runtime, which is the run and the turn.
"""

from __future__ import annotations

import json
import logging
from typing import Any


import azure_openai
import flow_walk
from env_utils import env_bool

logger = logging.getLogger(__name__)

# for the rest of the loop.
_SANDBOX_MAX_TOOL_RESULT_CHARS = 4000

#: Writes that used to hit production from rehearsal. Simulated only.
_SANDBOX_MUTATING_TOOLS = frozenset(
    {
        "create_promise_to_pay",
        "flag_dispute",
        "evaluate_authority",
        "apply_goodwill",
        "request_callback",
        "add_customer_note",
        "capture_nonpayment_reason",
        "set_contact_preference",
        "escalate_to_human",
        "handoff_to_agent",
        "capture_lead",
        "decline_offer",
        "request_documents",
        "ingest_customer_document",
        "identify_customer",
        "run_skill_script",
    }
)
#: Reads that are still stubbed, because faking them is cheaper than seeding a
#: whole borrower. ``search_knowledge_base`` is deliberately absent — it runs
#: live, see :func:`_rehearse_knowledge_base`. ``load_skill`` is absent for the
#: same reason and is handled earlier in the loop.
#:
#: The stub answers ``{"ok": True, "simulated": True, "data": {}}``, which is a
#: confident empty result. That is a real limitation, not a neutral placeholder:
#: an operator rehearsing against these learns nothing about whether the live
#: read would have found anything. Moving one out of this set is how that gets
#: fixed, one tool at a time, starting with the one that answers questions.
_SANDBOX_READ_TOOLS = frozenset(
    {
        "get_customer_context",
        "get_payment_history",
        "get_emi_schedule",
        "recommend_next_offer",
        "check_product_eligibility",
    }
)


def max_tool_iters() -> int:
    """The live text loop's knob (BOT_MAX_TOOL_ITERATIONS, 6). The sandbox
    allowed 4, so a rehearsal ran out of iterations where the live turn would
    not have -- a parity gap dressed as the card's behaviour."""
    from bot_runtime import _max_tool_iterations

    return _max_tool_iterations()


def _rehearse_knowledge_base(
    args: dict[str, Any], customer_text: str, recent: list[tuple[str, str]] | None = None
) -> tuple[bool, dict[str, Any]]:
    """Run the *real* retrieval for a rehearsal. Read-only, so nothing to fake.

    This used to be stubbed with the rest of the reads, and the stub returned
    ``{"ok": True, "simulated": True, "data": {}}`` — a confident-looking empty
    result, which is the exact shape of the bug the Sandbox exists to catch. An
    operator could rehearse an entire product conversation and never learn that
    live retrieval would hand the model a product name and nothing else.

    ``load_skill`` above is the precedent: it runs the real loader because a
    rehearsal of progressive disclosure that does not disclose anything is not a
    rehearsal. The same argument applies here with less risk, because retrieval
    writes nothing a customer can see.

    What keeps it side-effect-free is the two arguments below, not the stub:

    * ``interaction_id=None`` — gap capture and the product-interest analytics
      are both gated on it (``agent_core/tools/kb.py``), so a rehearsal cannot
      file a KB gap or record interest against a real borrower. This is the same
      mechanism, and the same reasoning, as ``mcp_tools._search_knowledge_base``.
    * ``record_offer=False`` — belt and braces for the analytics half.

    One buffered ``retrieval_logs`` row is still written, with a null
    interaction. That is honest: the retrieval really did happen, and the Test
    Retrieval screen already logs its own the same way.
    """
    from agent_core.tools import kb as kb_tool

    # channel="text" rather than a sandbox-specific value on purpose: the point
    # is to rehearse what WhatsApp will do, so it takes the text top_k, the text
    # snippet caps, the text plan budget and the text intent gate. `source` only
    # sizes the overfetch inside kb_retrieve, and the handler derives it.
    result = kb_tool.search_knowledge_base(
        query=str(args.get("query") or "").strip(),
        channel="text",
        customer_text=customer_text or "",
        recent=recent or None,
        interaction_id=None,
        record_offer=False,
    )
    if not result.ok:
        return False, {"ok": False, "error": result.error, "simulated": True, **(result.data or {})}
    return True, {**result.data, "ok": True, "simulated": True}


def simulate_sandbox_tool(
    name: str,
    args: dict[str, Any],
    *,
    customer_text: str = "",
    recent: list[tuple[str, str]] | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Side-effect-free rehearsal. Never calls a carrier, CRM write, or connector."""
    if name == "search_knowledge_base":
        return _rehearse_knowledge_base(args, customer_text, recent)
    if name.startswith("ext."):
        return False, {
            "ok": False,
            "error": "sandbox_connector_blocked",
            "simulated": True,
            "tool": name,
        }
    if name in _SANDBOX_MUTATING_TOOLS:
        return True, {
            "ok": True,
            "simulated": True,
            "effect": f"{name} would write in production",
            "args": args,
        }
    if name in _SANDBOX_READ_TOOLS:
        return True, {
            "ok": True,
            "simulated": True,
            "notice": "sandbox_read_not_live",
            "tool": name,
            "data": {},
        }
    return False, {
        "ok": False,
        "error": "sandbox_tool_unsupported",
        "simulated": True,
        "tool": name,
    }


def tools_enabled(payload: dict[str, Any], context: dict[str, Any] | None) -> bool:
    if payload.get("enableTools") is False:
        return False
    if payload.get("enableTools") is True:
        return True
    if env_bool("SANDBOX_TEXT_TOOLS"):
        return True
    ctx = context or {}
    return bool(ctx.get("customerId") or ctx.get("customer_id") or payload.get("customerId"))


def _sandbox_hop(
    walker: Any,
    args: dict[str, Any],
    agent_card: dict[str, Any] | None,
    entries: dict[str, str] | None,
) -> Any | None:
    """Move the rehearsal cursor onto the member a handoff named.

    Same resolution the two live mouths use, so what an operator rehearses is
    what a call would do. Returns None when the target has no entry in the
    compiled graph — the hop is still reported, it simply does not swap tools.
    """
    target = str(args.get("target_bot_id") or "").strip()
    if not target:
        return None
    from agent_core.cards import routing

    edge = routing.handoff_edge(agent_card or {}, target)
    entry = str(edge.get("entry_node") or "").strip() or (entries or {}).get(target, "")
    node = walker.node(entry) if entry else None
    return walker.move_to(node) if node is not None else None


def run_tool_loop(
    *,
    messages: list[dict[str, Any]],
    intent: str,
    temperature: float,
    max_tokens: int,
    agent_card: dict[str, Any] | None = None,
    walker: Any | None = None,
    specialist_grants: dict[str, set[str]] | None = None,
    specialist_entries: dict[str, str] | None = None,
    skill_slug: str | None = None,
    frozen_connector_tools: list[str] | None = None,
) -> tuple[str, int, int, list[dict[str, Any]], list[str]]:
    """Shared catalog tools under a max-iteration budget (unification Phase D).

    With a ``walker``, the offer is the *current node's* — the card's grant
    narrowed by the authored script, which is what the voice path does at every
    step. Without one (a card with no authored flow), the offer is the whole
    channel-filtered grant, exactly as before.
    """
    from agent_core.skills.runtime import resolve_mouth
    from agent_core.tools.catalog import CATALOG
    from agent_core.tools.schema import CHANNEL_TEXT

    # The same resolution that chose the skill body above: the offer used to
    # come from a second `resolve_mouth` with no slug, so the loaded skill and
    # the offered tools were two different skills.
    text_channel_tools = {spec.name for spec in CATALOG.for_channel(CHANNEL_TEXT)}
    mouth = resolve_mouth(
        agent_card or {},
        intent=intent,
        active_slug=skill_slug,
        frozen_connector_tools=frozen_connector_tools,
    )
    tool_state = mouth.tools(channel_tools=text_channel_tools, channel="text")
    granted = set(tool_state.offered or ())
    if walker is not None:
        # A step the text mouth cannot stand on -- the greeting, whose only
        # exit is the recording disclosure -- is stepped through to where it
        # leads. Same rule G-F11 gates on; the rehearsal starts where the
        # thread would.
        passed = walker.pass_through(granted=granted)
        if passed:
            logger.info("sandbox: passed through %s on text", ", ".join(passed))

    def _offer() -> tuple[list[dict[str, Any]], list[str]]:
        """This turn's tools, and the names for the response.

        Recomputed inside the loop because a transition changes the offer: the
        step after ``go_to_negotiate`` must not still be offering the step before
        it. Generated tools are built here rather than taken from the catalog —
        they are not catalog tools, they are how the graph moves.
        """
        if walker is None:
            names = sorted(granted)
            return CATALOG.openai_tools(list(tool_state.offered or ())), names
        # Narrowed to the member the cursor stands in before the step narrows
        # it further, so a rehearsal of a hop shows the receiving specialist's
        # tools and not the sending one's.
        # Widen to every member in the graph first, or the receiving
        # specialist's own tools are refused as ungranted the moment a rehearsed
        # hop lands — the mirror of the narrowing below.
        step_grant = walker.narrow(walker.union(granted, specialist_grants), specialist_grants)
        names = walker.offers(granted=step_grant)
        catalog_names = [n for n in names if n in step_grant]
        if not catalog_names and not walker.transitions():
            # Same floor bot_runtime applies: a step with no exit on this channel
            # falls back to the whole grant rather than offering nothing. The
            # built-in script's steps hop on voice-only tools, which is what
            # G-F11 warns about — a rehearsal that offered nothing would be
            # measuring the gap rather than the card.
            catalog_names = list(tool_state.offered or ())
            names = catalog_names
        schemas = CATALOG.openai_tools(catalog_names)
        schemas.extend(flow_walk.openai_graph_tools(walker))
        return schemas, names

    working = list(messages)
    # What the rehearsed customer actually said, for the tools that steer on it
    # rather than on the model's own tool-arg phrasing. Taken from `messages`
    # rather than threaded in as a parameter: the caller has already assembled
    # the turn here, and a second source for the same string is a second thing
    # that can disagree with it.
    rehearsed_customer_text = next(
        (
            str(m.get("content") or "")
            for m in reversed(messages)
            if m.get("role") == "user" and str(m.get("content") or "").strip()
        ),
        "",
    )
    # The rehearsed thread, for tools that resolve a follow-up against it.
    # `messages` also carries the system prompt and the untrusted CRM card, and
    # neither is something anybody said — filtered here rather than in
    # compaction, because a prompt scaffold masquerading as a turn is a quirk of
    # this one assembled list.
    from agent_core.compaction import run_up as _run_up

    rehearsed_recent = _run_up(
        [m for m in messages if m.get("role") in {"user", "assistant", "customer", "bot"}],
        rehearsed_customer_text,
    )
    tool_trace: list[dict[str, Any]] = []
    total_tokens = 0
    total_latency = 0
    bot_text = ""
    # Rehearsed assurance, not a flag. Production tiers tools by how much
    # identity they need (see agent_core.tools.gates), so a rehearsal that only
    # knows "verified / not" cannot show an operator that a promise-to-pay needs
    # a challenge while a callback does not.
    from agent_core.tools import gates as _gates

    simulated_assurance = _gates.LEVEL_NONE
    offered_names: list[str] = []

    tools_pending = False
    for _ in range(max_tool_iters()):
        tools_pending = False
        tools, offered_names = _offer()
        chat = azure_openai.chat_with_tools(
            working,
            tools=tools,
            temperature=temperature,
            max_completion_tokens=max_tokens,
        )
        total_latency += int(chat.get("latencyMs") or 0)
        total_tokens += int(
            chat.get("totalTokens")
            or ((chat.get("promptTokens") or 0) + (chat.get("completionTokens") or 0))
            or 0
        )
        calls = list(chat.get("toolCalls") or chat.get("tool_calls") or [])
        content = (chat.get("content") or "").strip()
        if content:
            bot_text = content
        if not calls:
            break
        # Assistant message with tool_calls (OpenAI wire shape).
        working.append(
            {
                "role": "assistant",
                "content": content or None,
                "tool_calls": [
                    {
                        "id": c.get("id") or f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": c.get("name"),
                            "arguments": c.get("arguments") or "{}",
                        },
                    }
                    for i, c in enumerate(calls)
                ],
            }
        )
        for c in calls:
            name = c.get("name") or ""
            args_json = c.get("arguments") or "{}"
            try:
                args = json.loads(args_json) if isinstance(args_json, str) else (args_json or {})
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}
            allowed = tool_state.allowed
            if walker is not None and name.startswith(flow_walk.TRANSITION_PREFIX):
                # A graph move, not a catalog tool. It is never gated by the
                # grant: the grant says what the agent may *do*, the graph says
                # where it may go, and an author who drew the edge authorised it.
                target = walker.advance(name)
                ok = target is not None
                result = (
                    {"ok": True, "node": target.key}
                    if target is not None
                    else {"ok": False, "error": "unknown_node"}
                )
            elif walker is not None and name == flow_walk.EXTRACT_TOOL:
                captured = walker.capture(args)
                # The variables an expression edge tests just changed, so this is
                # exactly when a deterministic transition can newly become true.
                moved = walker.advance()
                ok = True
                result = {"ok": True, "captured": captured}
                if moved is not None:
                    result["node"] = moved.key
            elif allowed is not None and name not in allowed:
                ok = False
                result = {"ok": False, "error": "tool_not_on_card_or_skill", "tool": name, "simulated": True}
            else:
                from agent_core.tools.gates import gate_failure

                gate_error = gate_failure(
                    name,
                    card=agent_card,
                    assurance=simulated_assurance,
                )
                if gate_error:
                    ok = False
                    result = {**gate_error, "ok": False, "simulated": True}
                elif name == "load_skill":
                    # Progressive disclosure, rehearsable: the real loader, the
                    # pack's body as the next developer message, and the offer
                    # widened to that pack -- exactly what the live loop does.
                    from dataclasses import replace as _replace

                    from agent_core.skills.runtime import body_developer_message, load_skill

                    slug = str(args.get("slug") or "").strip()
                    result = load_skill(slug, list(mouth.packs), allowed=allowed or frozenset())
                    ok = bool(result.get("ok"))
                    result = {k: v for k, v in result.items() if k != "message"} | {"simulated": True}
                    if ok:
                        pack = next((p for p in mouth.packs if p.slug == slug), None)
                        if pack is not None:
                            working.append(body_developer_message(pack))
                        mouth = _replace(mouth, active_slug=slug)
                        tool_state = mouth.tools(channel_tools=text_channel_tools, channel="text")
                        granted = set(tool_state.offered or ())
                else:
                    ok, result = simulate_sandbox_tool(
                        name,
                        args,
                        customer_text=rehearsed_customer_text,
                        recent=rehearsed_recent,
                    )
                    if ok and name == "identify_customer":
                        # Which level the rehearsed ceremony earned, by the same
                        # rule production uses: the number proves the endpoint,
                        # the account tail is a secret only the customer knows.
                        simulated_assurance = (
                            _gates.LEVEL_CHALLENGE
                            if str(args.get("account_tail") or args.get("accountTail") or "").strip()
                            else _gates.LEVEL_ENDPOINT
                        )
                    if ok and walker is not None:
                        if name == "handoff_to_agent":
                            # A handoff has no edge to follow — the card's
                            # allowlist is the edge — so the cursor is moved
                            # onto the target's entry the way both live mouths
                            # do it. This is where a hop first becomes
                            # rehearsable without a phone call.
                            moved = _sandbox_hop(walker, args, agent_card, specialist_entries)
                        else:
                            # A built-in tool is also a transition — the
                            # built-in script moves entirely this way, with no
                            # authored edges.
                            moved = walker.advance(name)
                        if moved is not None and isinstance(result, dict):
                            result["node"] = moved.key
            serialized = json.dumps(result if isinstance(result, dict) else {"result": result})
            if len(serialized) > _SANDBOX_MAX_TOOL_RESULT_CHARS:
                serialized = (
                    serialized[:_SANDBOX_MAX_TOOL_RESULT_CHARS] + "…[truncated]"
                )
            tool_trace.append({"name": name, "ok": ok, "result": result, "simulated": True})
            # The trace is returned on the sandbox turn. Do not write it to
            # bot_tool_calls: that table is a production-job ledger and its FK
            # would either reject this synthetic job or turn rehearsal into a
            # production mutation.
            working.append(
                {
                    "role": "tool",
                    "tool_call_id": c.get("id") or name,
                    "content": serialized,
                }
            )
        tools_pending = True

    if tools_pending:
        # The iteration budget ran out with tool results appended but never fed
        # back to the model. One tool-free completion turns the simulated
        # results into the answer the operator is owed.
        try:
            final = azure_openai.chat_with_tools(
                working,
                tools=None,
                temperature=temperature,
                max_completion_tokens=max_tokens,
            )
            total_latency += int(final.get("latencyMs") or 0)
            total_tokens += int(
                final.get("totalTokens")
                or ((final.get("promptTokens") or 0) + (final.get("completionTokens") or 0))
                or 0
            )
            content = (final.get("content") or "").strip()
            if content:
                bot_text = content
        except Exception:
            logger.exception("sandbox final completion after tool budget failed")

    if not bot_text:
        bot_text = "I understand. Let me help you with that."
    return bot_text, total_latency, max(1, total_tokens), tool_trace, offered_names
