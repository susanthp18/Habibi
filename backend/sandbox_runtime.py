"""Call Sandbox runtime — prompt version + KB retrieve + Azure chat (PS-3).

bot_deployments is authoritative for the default "live" prompt when the client
does not pass an explicit prompt_version_id. Guardrail violations halt the run.

Shared brain (intent / sentiment / prompt / guardrails / turn assembly) lives in
agent_core — this module owns sandbox_runs persistence only.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
from dataclasses import dataclass, field
import logging
import os
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from sqlalchemy import text

import azure_openai
import db
import kb_retrieve
from agent_core import (
    CHAT_TEMPERATURE,
    DEFAULT_TOP_K,
    assemble_turn_messages,
    classify_intent,
    context_blocks_from_results,
    default_context,
    estimate_sentiment,
    evaluate_guardrails,
    load_active_bundle,
    mentions_recording_disclosure,
    sentiment_label,
    should_halt,
)
import flow_walk
from env_utils import env_bool, env_float, env_int
from flow_graph import parse_graph
from flow_vars import FlowVariables
from flow_walk import FlowWalker
from prompt_render import render_prompt

logger = logging.getLogger(__name__)

# Grep handle for the per-turn stage breakdown emitted by append_sandbox_turn.
#
# Rehearsal cycles 18-21 measured 3.0s / 6.6s / 7.98s / 8.0s / 10.8s / 12.3s
# per turn on the same card and scenario, and nothing recorded where the time
# went: sandbox_run_turns stores one latency_ms (chat + retrieve, both
# self-reported) and has no jsonb column to hang a breakdown off. Rather than
# add a migration for a diagnostic, the breakdown is logged under a stable
# prefix so a run can be reconstructed with
#   grep 'turn-stage-timings:' <log>
# The numbers are wall-clock perf_counter deltas around each stage, so they
# include the overhead the self-reported latencies miss.
_STAGE_TIMING_LOG_PREFIX = "turn-stage-timings:"

# --- enrichment overlap (cycle 23) -----------------------------------------
#
# Cycle 22 measured the second Azure round trip a turn makes — the
# ``analyze_turn`` intent/sentiment enrichment inside assemble_turn_messages —
# at a 1151ms median, all of it between retrieval and the reply, i.e. squarely
# on the latency the customer waits out.
#
# It cannot simply be dropped from the reply path: ``intent`` picks the skill
# body message that goes *into* the prompt, feeds evaluate_guardrails, is
# written to both sandbox_run_turns rows, and four fields of the response
# contract (customerTurn.intent / intentScores / sentiment / sentimentLabel)
# are read straight off it by the Inspector. So it must be in hand before the
# chat call, and deferring it to a background task would change the contract.
#
# What it does *not* need is anything produced during the turn: the analysis
# reads the customer utterance only — never the KB context, never the reply —
# so it can be started the moment the utterance arrives and run alongside the
# preflight queries and retrieval instead of after them. The wait then costs
# the remainder (enrichment minus whatever the turn was already doing), not the
# whole call.
#
# SANDBOX_ENRICHMENT_ASYNC=0 puts the call back inline, on the old path, with
# no other behaviour change.
_ENRICHMENT_ASYNC_ENV = "SANDBOX_ENRICHMENT_ASYNC"
_ENRICHMENT_FALSEY = frozenset({"0", "false", "no", "off"})

#: How long the turn will wait on the prefetch before giving up on it.
#:
#: analyze_turn budgets itself (UNDERSTANDING_LLM_TIMEOUT_S, 6s by default) and
#: degrades to its keyword classifiers rather than raising, so this is the
#: backstop for the thread never returning at all — a hung socket below that
#: budget. Wider than the callee's own budget on purpose: expiring first would
#: throw away an answer that was about to arrive.
_ENRICHMENT_WAIT_S_ENV = "SANDBOX_ENRICHMENT_WAIT_S"
_DEFAULT_ENRICHMENT_WAIT_S = 10.0

#: Small and shared. One worker per concurrent sandbox turn is plenty — the
#: sandbox is a single-operator rehearsal surface, not a fan-out — and a pool
#: means a burst of turns queues instead of spawning threads without a bound.
_ENRICHMENT_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sandbox-enrich")


def _enrichment_async_enabled() -> bool:
    """Whether enrichment overlaps the turn instead of blocking it. Default on.

    Parsed through ``env_utils`` so an unset or unparseable value falls back to
    the default rather than raising; the word forms are spelled out here
    because ``SANDBOX_ENRICHMENT_ASYNC=false`` is the obvious way to turn a
    flag off and must not read as "unparseable, keep the default".
    """
    raw = (os.getenv(_ENRICHMENT_ASYNC_ENV) or "").strip().lower()
    if raw in _ENRICHMENT_FALSEY:
        return False
    return env_int(_ENRICHMENT_ASYNC_ENV, 1) != 0


def _run_up_for_run(run_id: str, customer_text: str) -> list[tuple[str, str]]:
    """The rehearsal's own transcript, as a run-up. Never raises.

    Reads ``sandbox_run_turns`` rather than the client's ``payload["history"]``,
    matching the server-authoritative rule the prompt assembly already follows:
    an operator's browser is not the record of what was rehearsed.
    """
    from agent_core.compaction import RAW_LAST_N, run_up

    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT speaker AS role, text
                    FROM sandbox_run_turns
                    WHERE run_id = :id AND text IS NOT NULL
                    ORDER BY turn_index DESC
                    LIMIT :limit
                    """
                ),
                {"id": run_id, "limit": RAW_LAST_N},
            ).mappings().all()
        return run_up([dict(r) for r in reversed(rows)], customer_text)
    except Exception:
        logger.exception("sandbox run-up fetch failed; classifying without context")
        return []


def _start_enrichment(customer_text: str, run_id: str) -> Future | None:
    """Kick the analysis off now; the turn collects it just before assembly.

    The context is copied into the worker so tenant / request context vars the
    LLM gateway reads are the ones this turn is running under, not whatever the
    pooled thread last saw.

    The run-up is fetched *inside* the worker rather than passed in. That keeps
    the point of the prefetch intact — this fires before the turn's own preflight
    queries, so doing the lookup on the calling thread would hand back the
    latency the overlap exists to hide — while still giving the classifier the
    thread. Judged on one sentence, "nope i want to see the benefits." is a
    request for a capabilities list; judged against the four turns before it, it
    is a travel-insurance question.
    """
    ctx = contextvars.copy_context()

    def _run() -> tuple[Any, float]:
        started = time.perf_counter()
        from agent_core.understanding import analyze_turn

        try:
            result: Any = analyze_turn(
                customer_text,
                channel="sandbox_text",
                recent=_run_up_for_run(run_id, customer_text) or None,
            )
        except Exception:
            # analyze_turn documents that it never raises; if that ever stops
            # being true the turn still gets its reply, via the inline call.
            logger.exception("sandbox enrichment prefetch failed")
            result = None
        return result, round((time.perf_counter() - started) * 1000.0, 2)

    try:
        return _ENRICHMENT_POOL.submit(ctx.run, _run)
    except RuntimeError:
        # Interpreter shutting down — fall back to the inline call.
        logger.warning("sandbox enrichment pool unavailable; enriching inline")
        return None


def _collect_enrichment(future: Future, customer_text: str) -> tuple[Any, float, float]:
    """Wait out whatever is left of the prefetch.

    Returns ``(understanding_or_None, wall_ms, wait_ms)`` — what the call took
    end to end, and how much of that the turn actually stood still for. The
    difference is the saving, and it is what gets logged.
    """
    wait_start = time.perf_counter()
    try:
        result, wall_ms = future.result(timeout=env_float(_ENRICHMENT_WAIT_S_ENV, _DEFAULT_ENRICHMENT_WAIT_S))
    except FutureTimeout:
        wait_ms = round((time.perf_counter() - wait_start) * 1000.0, 2)
        logger.warning(
            "sandbox enrichment prefetch did not return in %.0fms - using the "
            "deterministic classifiers for this turn",
            wait_ms,
        )
        future.cancel()
        from agent_core.understanding import analyze_turn

        # allow_llm=False is the keyword path: local, immediate, and the same
        # value analyze_turn itself falls back to on any failure.
        with contextlib.suppress(Exception):
            return analyze_turn(customer_text, channel="sandbox_text", allow_llm=False), wait_ms, wait_ms
        return None, wait_ms, wait_ms
    except Exception:
        wait_ms = round((time.perf_counter() - wait_start) * 1000.0, 2)
        logger.exception("sandbox enrichment prefetch raised; enriching inline")
        return None, wait_ms, wait_ms
    wait_ms = round((time.perf_counter() - wait_start) * 1000.0, 2)
    return result, float(wall_ms), wait_ms



def _max_tool_iters() -> int:
    """The live text loop's knob (BOT_MAX_TOOL_ITERATIONS, 6). The sandbox
    allowed 4, so a rehearsal ran out of iterations where the live turn would
    not have -- a parity gap dressed as the card's behaviour."""
    from bot_runtime import _max_tool_iterations

    return _max_tool_iterations()


def sandbox_channel(card: dict[str, Any] | None) -> str:
    """The channel a text rehearsal frames and judges the card as.

    The sandbox is text, so a card with a text mouth is rehearsed as WhatsApp;
    a voice-only card is framed as a call -- otherwise the prompt told it not
    to disclose recording and the guardrail flagged it for not disclosing.
    """
    channels = {str(c).strip().lower() for c in ((card or {}).get("identity") or {}).get("channels") or []}
    if channels & {"whatsapp", "text", "sms", "chat"}:
        return "whatsapp"
    return "voice" if "voice" in channels else "whatsapp"
# Ceiling on a single tool result as handed back to the model. Generous enough
# for a full KB passage, bounded so one wide result cannot dominate the context
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


def _sandbox_tools_enabled(payload: dict[str, Any], context: dict[str, Any] | None) -> bool:
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


def _run_sandbox_tool_loop(
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
    for _ in range(_max_tool_iters()):
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

# Absolute ceiling on customer→bot exchanges per run (cost control).
#: The rehearsal's cost cap in customer turns. Not the card's `maxTurns`,
#: which is judged on the same terms as live (`_LIVE_HARD_MAX_TURNS`).
_HARD_MAX_TURNS = max(1, int(os.getenv("SANDBOX_HARD_MAX_TURNS", "3")))
_LIVE_HARD_MAX_TURNS = max(1, int(os.getenv("BOT_HARD_MAX_TURNS", "12")))

# Re-exports so existing `from sandbox_runtime import classify_intent` keeps working.
__all__ = [
    "append_sandbox_turn",
    "classify_intent",
    "complete_sandbox_run",
    "create_sandbox_run",
    "estimate_sentiment",
    "evaluate_guardrails",
    "sentiment_label",
]


def _stage_timings(
    *,
    run_id: str,
    turn_index: int,
    turn_start: float,
    after_preflight: float,
    retrieve_start: float,
    retrieve_end: float,
    understanding_start: float,
    understanding_end: float,
    llm_start: float,
    llm_end: float,
    guardrails_start: float,
    guardrails_end: float,
    persist_start: float,
    persist_end: float,
    understanding_llm_enabled: bool,
    enrichment_async: bool,
    enrichment_wall_ms: float,
    enrichment_wait_ms: float,
    reported_chat_ms: int,
    reported_retrieve_ms: int,
    tool_calls: int,
    tokens: int,
) -> dict[str, Any]:
    """The wall-clock cost of one turn, split by pipeline stage.

    Pure arithmetic over ``perf_counter`` marks — it must not raise, because a
    diagnostic that can fail a turn is worse than no diagnostic.

    Two stages here make a *model* call, not one, and that is the headline the
    rehearsal logs could not show. ``llm_ms`` is the reply. ``understanding_ms``
    wraps :func:`assemble_turn_messages`, which calls ``analyze_turn`` — a
    second, synchronous Azure round trip for intent/sentiment enrichment
    (``UNDERSTANDING_LLM_ENABLED``). Neither ``chatLatencyMs`` nor
    ``retrieveLatencyMs`` counts it, so the number persisted in
    ``sandbox_run_turns.latency_ms`` is short by however long it took.

    ``non_llm_ms`` is the number the latency budget test asserts on: the work
    the sandbox itself is responsible for, with *both* model calls removed.
    When the enrichment flag is off that stage is local CPU and stays in the
    budget, which is why it is subtracted conditionally rather than always.

    With ``SANDBOX_ENRICHMENT_ASYNC`` on, ``understanding_ms`` is no longer the
    enrichment call — it is assembly plus whatever was *left* of a call that
    started before the preflight. ``enrichment_wall_ms`` still reports the full
    cost and ``enrichment_saved_ms`` the part that came off the reply path.
    """

    def _ms(a: float, b: float) -> float:
        return round(max(0.0, (b - a)) * 1000.0, 2)

    total_ms = _ms(turn_start, persist_end)
    llm_ms = _ms(llm_start, llm_end)
    understanding_ms = _ms(understanding_start, understanding_end)
    billed_to_llm = llm_ms + (understanding_ms if understanding_llm_enabled else 0.0)
    return {
        "run_id": run_id,
        "turn_index": turn_index,
        "total_ms": total_ms,
        # The four preflight queries: run row, turn counts, prompt version,
        # full turn history.
        "preflight_db_ms": _ms(turn_start, after_preflight),
        "retrieval_ms": _ms(retrieve_start, retrieve_end),
        # Grounding selection, the prior-summary lookup and skill selection —
        # the gap between retrieval finishing and assembly starting.
        "prompt_prep_ms": _ms(retrieve_end, understanding_start),
        "understanding_ms": understanding_ms,
        "understanding_llm_enabled": bool(understanding_llm_enabled),
        # What the overlap bought. ``enrichment_wall_ms`` is the analysis call
        # end to end; ``enrichment_saved_ms`` is the part of it the turn did
        # not stand still for because retrieval and the preflight were running
        # underneath it. Both are zero when the flag is off, which is the
        # before-picture: the whole call sat inside understanding_ms.
        "enrichment_async": bool(enrichment_async),
        "enrichment_wall_ms": round(float(enrichment_wall_ms), 2),
        "enrichment_saved_ms": round(
            max(0.0, float(enrichment_wall_ms) - float(enrichment_wait_ms)), 2
        ),
        "llm_ms": llm_ms,
        "guardrails_ms": _ms(guardrails_start, guardrails_end),
        "persist_ms": _ms(persist_start, persist_end),
        "non_llm_ms": round(max(0.0, total_ms - billed_to_llm), 2),
        "reported_chat_ms": int(reported_chat_ms or 0),
        "reported_retrieve_ms": int(reported_retrieve_ms or 0),
        # What sandbox_run_turns.latency_ms will say, versus what the turn
        # actually cost. A large gap is the bug, not a rounding artefact.
        "unattributed_ms": round(
            max(0.0, total_ms - int(reported_chat_ms or 0) - int(reported_retrieve_ms or 0)),
            2,
        ),
        "tool_calls": int(tool_calls),
        "tokens": int(tokens),
    }


def _grounding_sources(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The retrieval hits presented as this turn's grounding, de-duped by id.

    ONE list backs the chips, the "N chunks" counter and the persisted
    ``retrieved_chunk_ids``. They used to be computed separately — the counter
    from real ``kb_chunks`` ids only, the chips from a FAQ fallback — so a turn
    that matched only FAQ rows rendered three "grounded in FAQ" chips under a
    footer reading "0 chunks". Prefer real chunks; when a turn matched FAQ rows
    only, show those, because the alternative is claiming the answer was
    ungrounded when it was not.
    """

    real = [
        r
        for r in results
        if str(r.get("chunkId") or "") and not str(r["chunkId"]).startswith("faq-")
    ]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in real or results[:3]:
        cid = str(r.get("chunkId") or "")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append(r)
    return out


def create_sandbox_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Start a sandbox run bound to a prompt version (explicit or active deployment)."""
    prompt_version_id = payload.get("promptVersionId")
    deployment_id = None
    kb_snapshot_id = payload.get("kbSnapshotId")

    if not prompt_version_id:
        try:
            bundle = load_active_bundle(
                "sandbox",
                fallback_environments=("production",),
            )
        except KeyError as exc:
            if "active_deployment_not_found" in str(exc):
                raise KeyError("active_deployment_not_found") from exc
            raise
        deployment_id = bundle["deploymentId"]
        prompt_version_id = bundle["promptVersionId"]
        if not kb_snapshot_id:
            kb_snapshot_id = bundle.get("kbSnapshotId")

    version = db.get_prompt_version(prompt_version_id)
    if not version:
        raise KeyError(f"prompt_version_not_found: {prompt_version_id}")

    context = default_context(payload.get("context") if isinstance(payload.get("context"), dict) else None)
    opening_template = payload.get("openingTemplate") or ""
    opening_message = render_prompt(opening_template, context) if opening_template else None

    scenario_id = payload.get("scenarioId")

    run_id = f"SBX-{uuid.uuid4().hex[:10].upper()}"
    with db.engine.begin() as conn:
        if scenario_id:
            exists = conn.execute(
                text("SELECT 1 FROM sandbox_scenarios WHERE id = :id"),
                {"id": scenario_id},
            ).fetchone()
            if not exists:
                conn.execute(
                    text(
                        """
                        INSERT INTO sandbox_scenarios
                          (id, tenant_id, name, sim_persona, turns)
                        VALUES (:id, :tenant_id, :name, CAST(:persona AS jsonb),
                                CAST(:turns AS jsonb))
                        ON CONFLICT (id) DO NOTHING
                        """
                    ),
                    {
                        "id": scenario_id,
                        "tenant_id": db.current_tenant(),
                        "name": str(payload.get("scenarioTitle") or scenario_id),
                        "persona": json.dumps(payload.get("persona") or {}),
                        "turns": json.dumps([]),
                    },
                )

        if kb_snapshot_id:
            snap = conn.execute(
                text("SELECT 1 FROM kb_snapshots WHERE id = :id"),
                {"id": kb_snapshot_id},
            ).fetchone()
            if not snap:
                raise ValueError(f"kb_snapshot_not_found: {kb_snapshot_id}")

        if deployment_id is None:
            dep = conn.execute(
                text(
                    """
                    SELECT id FROM bot_deployments
                    WHERE prompt_version_id = :pid
                      AND status = 'active'
                    ORDER BY
                      CASE environment WHEN 'sandbox' THEN 0 WHEN 'production' THEN 1 ELSE 2 END,
                      published_at DESC NULLS LAST
                    LIMIT 1
                    """
                ),
                {"pid": prompt_version_id},
            ).fetchone()
            deployment_id = dep[0] if dep else None

        conn.execute(
            text(
                """
                INSERT INTO sandbox_runs (
                  id, scenario_id, deployment_id, prompt_version_id, kb_snapshot_id,
                  started_by_user_id, status, aggregate_latency_ms, aggregate_tokens,
                  created_at, updated_at
                ) VALUES (
                  :id, :scenario_id, :deployment_id, :prompt_version_id, :kb_snapshot_id,
                  :actor, 'running', 0, 0, now(), now()
                )
                """
            ),
            {
                "id": run_id,
                "scenario_id": scenario_id,
                "deployment_id": deployment_id,
                "prompt_version_id": prompt_version_id,
                "kb_snapshot_id": kb_snapshot_id,
                "actor": db._actor_user_id(),
            },
        )

        if opening_message:
            conn.execute(
                text(
                    """
                    INSERT INTO sandbox_run_turns (
                      id, run_id, turn_index, speaker, text,
                      detected_intent, sentiment_label, retrieved_chunk_ids,
                      guardrail_flags, latency_ms, token_count, created_at
                    ) VALUES (
                      :id, :run_id, 0, 'bot', :text,
                      NULL, 'neutral', CAST('[]' AS jsonb),
                      CAST('[]' AS jsonb), 0, :tokens, now()
                    )
                    """
                ),
                {
                    "id": f"{run_id}-T0",
                    "run_id": run_id,
                    "text": opening_message,
                    "tokens": max(1, len(opening_message) // 4),
                },
            )

    return {
        "id": run_id,
        "scenarioId": scenario_id,
        "deploymentId": deployment_id,
        "promptVersionId": prompt_version_id,
        "kbSnapshotId": kb_snapshot_id,
        "status": "running",
        "openingMessage": opening_message,
        "promptVersion": version,
        "context": context,
        "turnBudget": _HARD_MAX_TURNS,
    }


@dataclass
class SandboxTurn:
    """One rehearsed turn as it moves through the phases below.

    The run and the contract it rehearses, the thread so far, what
    retrieval and classification found, what the model answered, what the
    guardrails said and the rows that were written -- plus the stage clocks
    the timing line reports. Filled in order by ``_sandbox_contract`` /
    ``_sandbox_preflight`` / ``_sandbox_assemble`` / ``_sandbox_model`` /
    ``_sandbox_judge_and_persist`` / ``_sandbox_response``; a phase that
    cannot go on raises, as the one function it was did. Pinned by
    ``tests/test_sandbox_turn_snapshot.py``.
    """

    run_id: str
    payload: dict[str, Any]
    customer_text: str
    bot_text: str = ""
    bot_turn_id: str = ""
    bot_turn_index: int = 0
    chat_latency: int = 0
    chunk_ids: list[str] = field(default_factory=list)
    compiled: dict[str, Any] | None = None
    contract_card: dict[str, Any] | None = None
    contract_flow: dict[str, Any] | None = None
    contract_frozen_tools: list[str] = field(default_factory=list)
    contract_prompt: str = ""
    customer_turn_id: str = ""
    effective_max: int = 0
    elapsed: float = 0.0
    elapsed_seconds: float = 0.0
    enrichment_async: bool = False
    enrichment_future: Any = None
    enrichment_wait_ms: float = 0.0
    enrichment_wall_ms: float = 0.0
    flags: list[str] = field(default_factory=list)
    flow_walker: Any = None
    grounding: list[dict[str, Any]] = field(default_factory=list)
    guardrails: dict[str, Any] = field(default_factory=dict)
    halted: bool = False
    history: list[dict[str, Any]] = field(default_factory=list)
    intent: str | None = None
    intent_scores: dict[str, float] | None = None
    latency_ms: int = 0
    max_tokens: int = 0
    max_turns: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)
    offered_tools: list[str] = field(default_factory=list)
    persona: dict[str, Any] = field(default_factory=dict)
    prior_customers: int = 0
    recording_disclosed: bool = False
    rehearsal_channel: str = ""
    retrieval: dict[str, Any] = field(default_factory=dict)
    retrieve_latency: int = 0
    run: dict[str, Any] | None = None
    sent_label: str | None = None
    sentiment: float | None = None
    skill_prefix: str | None = None
    skill_slug: str | None = None
    t0: float = 0.0
    t_after_preflight: float = 0.0
    t_guardrails_end: float = 0.0
    t_guardrails_start: float = 0.0
    t_persist_end: float = 0.0
    t_persist_start: float = 0.0
    t_retrieve_end: float = 0.0
    t_retrieve_start: float = 0.0
    t_turn_start: float = 0.0
    t_understanding_end: float = 0.0
    t_understanding_start: float = 0.0
    temperature: float = 0.0
    tokens: int = 0
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    turn_count: int = 0
    understanding_llm: bool = False
    version: dict[str, Any] | None = None


def _sandbox_contract(st: SandboxTurn) -> None:
    """The run, its counts, the pinned version and the compiled contract it rehearses."""
    run_id = st.run_id
    customer_text = st.customer_text

    # Stage clocks — report-only, see _STAGE_TIMING_LOG_PREFIX.
    t_turn_start = time.perf_counter()

    # Enrichment starts here — before the preflight queries, before retrieval —
    # and is collected just before assembly needs its intent. See the notes on
    # _ENRICHMENT_ASYNC_ENV for why it may overlap but may not be deferred past
    # the reply.
    from agent_core.understanding import llm_enabled as _understanding_llm_enabled

    understanding_llm = bool(_understanding_llm_enabled())
    enrichment_async = understanding_llm and _enrichment_async_enabled()
    enrichment_future = _start_enrichment(customer_text, run_id) if enrichment_async else None
    enrichment_async = enrichment_future is not None
    enrichment_wall_ms = 0.0
    enrichment_wait_ms = 0.0

    with db.engine.connect() as conn:
        run = conn.execute(
            text(
                """
                SELECT id, prompt_version_id, status, created_at,
                       kb_snapshot_id,
                       COALESCE(aggregate_latency_ms, 0) AS aggregate_latency_ms,
                       COALESCE(aggregate_tokens, 0) AS aggregate_tokens
                FROM sandbox_runs WHERE id = :id
                """
            ),
            {"id": run_id},
        ).mappings().first()
        if not run:
            raise KeyError(f"sandbox_run_not_found: {run_id}")
        if run["status"] != "running":
            raise ValueError(f"sandbox_run_not_active: {run['status']}")

        turn_count = int(
            conn.execute(
                text("SELECT COUNT(*) AS n FROM sandbox_run_turns WHERE run_id = :id"),
                {"id": run_id},
            ).scalar()
            or 0
        )
        prior_customers = int(
            conn.execute(
                text(
                    """
                    SELECT COUNT(*) AS n FROM sandbox_run_turns
                    WHERE run_id = :id AND speaker = 'customer'
                    """
                ),
                {"id": run_id},
            ).scalar()
            or 0
        )

    version = db.get_prompt_version(run["prompt_version_id"])
    if not version:
        raise KeyError(f"prompt_version_not_found: {run['prompt_version_id']}")

    compiled = version.get("compiled") if isinstance(version.get("compiled"), dict) else None
    if not compiled or not compiled.get("bundle_hash"):
        # Drafts are not persisted as compiled artefacts. Compile the exact
        # version pinned on the run, using the same wrapper publish uses.
        compiled_report = db.compile_agent_studio_card(
            str(version.get("botId") or db.DEFAULT_BOT_ID),
            prompt_version_id=str(version["id"]),
        )
        compiled = (
            compiled_report.get("bundle")
            if isinstance(compiled_report.get("bundle"), dict)
            else {}
        )
    from agent_core.fleet.compile import bundle_hash_valid
    from agent_core.fleet.schema import CompiledBundle

    parsed_contract = CompiledBundle.model_validate(compiled)
    if not bundle_hash_valid(parsed_contract):
        raise RuntimeError("sandbox_compiled_bundle_hash_invalid")
    compiled = parsed_contract.model_dump(mode="json")
    contract_prompt = str(compiled.get("prompt") or version.get("prompt") or "")
    contract_card = (
        compiled.get("agent_card")
        if isinstance(compiled.get("agent_card"), dict)
        else version.get("agentCard") or {}
    )
    # The merged fleet graph when there is a fleet, the card's own when there
    # is not -- the same line the live mouth reads (deployment.py). Walking the
    # card's own graph rehearsed a hop that landed nowhere.
    contract_flow = (
        compiled.get("fleet_flow")
        if isinstance(compiled.get("fleet_flow"), dict) and compiled["fleet_flow"].get("nodes")
        else compiled.get("flow") if isinstance(compiled.get("flow"), dict) else {}
    )
    # The connector tools the publish froze, exactly as bot_runtime passes the
    # deployment's frozenTools. An unfrozen resolve read the live registry, so
    # the rehearsal could offer an ext.* tool production would refuse.
    contract_frozen_tools = [
        str(name)
        for connector in (compiled.get("connectors") or [])
        if isinstance(connector, dict)
        for name in connector.get("tool_names") or []
    ]

    st.compiled = compiled
    st.contract_card = contract_card
    st.contract_flow = contract_flow
    st.contract_frozen_tools = contract_frozen_tools
    st.contract_prompt = contract_prompt
    st.enrichment_async = enrichment_async
    st.enrichment_future = enrichment_future
    st.enrichment_wait_ms = enrichment_wait_ms
    st.enrichment_wall_ms = enrichment_wall_ms
    st.prior_customers = prior_customers
    st.run = run
    st.t_turn_start = t_turn_start
    st.turn_count = turn_count
    st.understanding_llm = understanding_llm
    st.version = version


def _sandbox_preflight(st: SandboxTurn) -> None:
    """The walker, the card's ceiling, the persona, the skill, the channel and the thread so far."""
    run_id = st.run_id
    payload = st.payload
    compiled = st.compiled
    contract_card = st.contract_card
    contract_flow = st.contract_flow
    contract_frozen_tools = st.contract_frozen_tools
    prior_customers = st.prior_customers
    version = st.version

    # read `flow` only to render a lozenge saying it had not run it, so "Test in
    # Sandbox" exercised the grant but never the script that narrows it.
    #
    # A flow that will not parse leaves the walker None: the compiler passed the
    # card, this runtime could not walk it, and the honest report of that is the
    # older flowStatus — not a silently prompt-only run that looks identical to
    # a card with no flow at all.
    flow_walker = None
    if contract_flow:
        try:
            flow_walker = FlowWalker(
                parse_graph(contract_flow),
                FlowVariables({}),
                start=None,
            )
            resume = str(payload.get("nodeKey") or "").strip()
            if resume:
                node = flow_walker.node(resume)
                if node is None:
                    logger.warning("sandbox: unknown nodeKey %r — restarting the graph", resume)
                else:
                    flow_walker.move_to(node)
        except Exception:
            logger.exception("sandbox: authored flow will not parse — running prompt-only")
            flow_walker = None
    guardrails = (
        compiled.get("guardrails")
        if isinstance(compiled.get("guardrails"), dict)
        else version["guardrails"] if isinstance(version.get("guardrails"), dict) else {}
    )
    max_turns = int(guardrails.get("maxTurns") or 0)
    effective_max = min(_HARD_MAX_TURNS, max_turns) if max_turns else _HARD_MAX_TURNS
    # Cheap fail-fast so we don't pay for an LLM call on an already-capped run.
    # The authoritative check runs under the row lock in the persist transaction.
    if prior_customers >= effective_max:
        raise ValueError(f"sandbox_budget_reached:{effective_max}")

    persona = (
        compiled.get("persona")
        if isinstance(compiled.get("persona"), dict)
        else version["persona"] if isinstance(version.get("persona"), dict) else {}
    )
    from agent_core.skills.runtime import resolve_mouth

    skill_slug = str(payload.get("skillSlug") or payload.get("skill_slug") or "").strip() or None
    # A slug the card does not carry is refused, not silently ignored: the
    # picker offered the whole library and a no-op looked like a rehearsal.
    if skill_slug:
        attached_slugs = {
            str(s.get("skill_id") or s.get("skillId") or "")
            for s in (contract_card or {}).get("skills") or []
            if isinstance(s, dict)
        }
        if skill_slug not in attached_slugs:
            raise ValueError(f"skill_not_attached:{skill_slug}")
    rehearsal_channel = sandbox_channel(contract_card)
    # Prompt only. Intent is not known until the messages below are assembled,
    # so the active skill body is resolved separately once it is.
    skill_prefix = resolve_mouth(
        contract_card, active_slug=skill_slug, frozen_connector_tools=contract_frozen_tools
    ).prompt().prefix
    # Server-authoritative history — prefer DB turns over client payload.
    history: list[dict[str, Any]] = []
    with db.engine.connect() as hist_conn:
        hist_rows = hist_conn.execute(
            text(
                """
                SELECT speaker, text, turn_index
                FROM sandbox_run_turns
                WHERE run_id = :id
                ORDER BY turn_index ASC
                """
            ),
            {"id": run_id},
        ).mappings().all()
        for hr in hist_rows:
            role = "bot" if hr["speaker"] == "bot" else "customer" if hr["speaker"] == "customer" else None
            if role and hr.get("text"):
                history.append({"role": role, "text": hr["text"], "turn_index": hr["turn_index"]})
    if not history:
        history = payload.get("history") if isinstance(payload.get("history"), list) else []
    t_after_preflight = time.perf_counter()

    st.effective_max = effective_max
    st.flow_walker = flow_walker
    st.guardrails = guardrails
    st.history = history
    st.max_turns = max_turns
    st.persona = persona
    st.rehearsal_channel = rehearsal_channel
    st.skill_prefix = skill_prefix
    st.skill_slug = skill_slug
    st.t_after_preflight = t_after_preflight


def _sandbox_assemble(st: SandboxTurn) -> None:
    """Retrieval, the prior summary, the classification and the messages the model is handed."""
    run_id = st.run_id
    payload = st.payload
    customer_text = st.customer_text
    contract_card = st.contract_card
    contract_frozen_tools = st.contract_frozen_tools
    contract_prompt = st.contract_prompt
    enrichment_future = st.enrichment_future
    enrichment_wait_ms = st.enrichment_wait_ms
    enrichment_wall_ms = st.enrichment_wall_ms
    guardrails = st.guardrails
    history = st.history
    persona = st.persona
    rehearsal_channel = st.rehearsal_channel
    run = st.run
    skill_prefix = st.skill_prefix
    skill_slug = st.skill_slug
    version = st.version

    # Whether the recording disclosure has already been made on this RUN. The
    # opening greeting is stored as bot turn 0, so a template that says "this
    # call is recorded for quality" satisfies the rule for the whole run —
    # evaluate_guardrails sees one turn at a time and cannot know that. Without
    # this the sandbox raised a false "missing-recording-disclosure" from the
    # first customer reply onwards, on every run using a disclosing greeting.
    # The live voice path already threads the same fact (voice/crm_sink.py).
    # Bot turns the *card* produced. Turn 0 is the scenario's opening fixture
    # -- operator-authored text -- and it was what satisfied the disclosure
    # check, so a card that never disclosed rehearsed green.
    recording_disclosed = any(
        h.get("role") == "bot"
        and int(h.get("turn_index") or 0) > 0
        and mentions_recording_disclosure(str(h.get("text") or ""))
        for h in history
        if isinstance(h, dict)
    )

    kb_snapshot_id = run.get("kb_snapshot_id")
    tuning = version.get("tuning") if isinstance(version.get("tuning"), dict) else {}
    from agent_core.tuning import normalize_tuning

    llm_tuning = normalize_tuning(tuning).get("llm") or {}
    temperature = float(
        llm_tuning.get("temperature") if llm_tuning.get("temperature") is not None else CHAT_TEMPERATURE
    )
    max_tokens = int(llm_tuning.get("max_completion_tokens") or 320)

    t_retrieve_start = time.perf_counter()
    try:
        retrieval = kb_retrieve.retrieve(
            query=customer_text,
            top_k=min(int(payload.get("topK") or DEFAULT_TOP_K), 6),
            include_draft_answer=False,
            source="sandbox",
            sandbox_run_id=run_id,
            kb_snapshot_id=kb_snapshot_id,
        )
    except Exception:
        logger.exception("sandbox retrieve failed; continuing without KB")
        retrieval = {"results": [], "latencyMs": 0, "logId": None}
    t_retrieve_end = time.perf_counter()

    results = list(retrieval.get("results") or [])
    context_blocks = context_blocks_from_results(results)
    grounding = _grounding_sources(results)
    chunk_ids = [str(r["chunkId"]) for r in grounding]

    prior_summary = None
    interaction_id = str(payload.get("interactionId") or payload.get("interaction_id") or "").strip() or None
    if interaction_id:
        try:
            row = db.get_latest_context_summary(interaction_id)
            prior_summary = (row or {}).get("summary")
        except Exception:
            prior_summary = None
    # assemble_turn_messages calls analyze_turn, which makes its own Azure call
    # when UNDERSTANDING_LLM_ENABLED is on. Timed separately for that reason.
    # With the overlap on, that call is already in flight and this stage is the
    # remainder of it plus the assembly itself; with the flag off, nothing was
    # started above and the call happens inline here, as it always did.
    t_understanding_start = time.perf_counter()
    prefetched_understanding = None
    if enrichment_future is not None:
        (
            prefetched_understanding,
            enrichment_wall_ms,
            enrichment_wait_ms,
        ) = _collect_enrichment(enrichment_future, customer_text)
    assembled = assemble_turn_messages(
        prompt_template=contract_prompt,
        persona=persona,
        guardrails=guardrails,
        customer_text=customer_text,
        context=payload.get("context") if isinstance(payload.get("context"), dict) else None,
        history=history,
        context_blocks=context_blocks,
        prior_summary=prior_summary,
        skill_catalog=skill_prefix,
        active_skill_message=None,
        understanding=prefetched_understanding,
        channel=rehearsal_channel,
    )
    t_understanding_end = time.perf_counter()
    messages = assembled["messages"]
    intent = assembled["intent"]
    from agent_core.skills.runtime import resolve_mouth

    skill_body = resolve_mouth(
        contract_card,
        intent=str(intent or ""),
        active_slug=skill_slug,
        frozen_connector_tools=contract_frozen_tools,
    ).prompt().body_message
    if skill_body:
        messages.insert(min(2, len(messages)), skill_body)
    intent_scores = assembled["intent_scores"]
    sentiment = assembled["sentiment"]
    sent_label = assembled["sentiment_label"]

    st.chunk_ids = chunk_ids
    st.enrichment_wait_ms = enrichment_wait_ms
    st.enrichment_wall_ms = enrichment_wall_ms
    st.grounding = grounding
    st.intent = intent
    st.intent_scores = intent_scores
    st.max_tokens = max_tokens
    st.messages = messages
    st.recording_disclosed = recording_disclosed
    st.retrieval = retrieval
    st.sent_label = sent_label
    st.sentiment = sentiment
    st.t_retrieve_end = t_retrieve_end
    st.t_retrieve_start = t_retrieve_start
    st.t_understanding_end = t_understanding_end
    st.t_understanding_start = t_understanding_start
    st.temperature = temperature


def _sandbox_model(st: SandboxTurn) -> None:
    """The model: the tool loop when tools are on, one chat call when they are not."""
    payload = st.payload
    compiled = st.compiled
    contract_card = st.contract_card
    contract_frozen_tools = st.contract_frozen_tools
    flow_walker = st.flow_walker
    intent = st.intent
    max_tokens = st.max_tokens
    messages = st.messages
    retrieval = st.retrieval
    run = st.run
    skill_slug = st.skill_slug
    temperature = st.temperature

    t0 = time.perf_counter()
    tool_trace: list[dict[str, Any]] = []
    # Empty on the prompt-only path: no tool loop ran, so the graph offered
    # nothing. Reported as absent rather than as an empty offer.
    offered_tools: list[str] = []
    turn_context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    from agent_core.telemetry import span as _span

    try:
        with _span("gen_ai.invoke_agent", gen_ai_operation_name="invoke_agent", gen_ai_agent_name="sandbox"):
            if _sandbox_tools_enabled(payload, turn_context):
                (
                    bot_text,
                    chat_latency,
                    tokens,
                    tool_trace,
                    offered_tools,
                ) = _run_sandbox_tool_loop(
                    messages=messages,
                    intent=str(intent or "general"),
                    temperature=temperature,
                    max_tokens=max_tokens,
                    agent_card=contract_card,
                    walker=flow_walker,
                    specialist_grants=flow_walk.specialist_grants(compiled),
                    specialist_entries=flow_walk.specialist_entries(compiled),
                    skill_slug=skill_slug,
                    frozen_connector_tools=contract_frozen_tools,
                )
            else:
                with _span("gen_ai.chat", gen_ai_operation_name="chat"):
                    chat = azure_openai.chat_complete_detailed(
                        messages,
                        temperature=temperature,
                        max_completion_tokens=max_tokens,
                    )
                bot_text = chat["content"] or "I understand. Let me help you with that."
                chat_latency = int(chat["latencyMs"] or 0)
                tokens = int(
                    chat.get("totalTokens")
                    or ((chat.get("promptTokens") or 0) + (chat.get("completionTokens") or 0))
                    or max(1, len(bot_text) // 4)
                )
    except Exception as exc:
        logger.exception("sandbox chat failed")
        raise RuntimeError(f"sandbox_chat_failed: {exc}") from exc

    retrieve_latency = int(retrieval.get("latencyMs") or 0)
    latency_ms = chat_latency + retrieve_latency
    elapsed = time.perf_counter() - t0
    created = run["created_at"]
    try:
        if hasattr(created, "timestamp"):
            elapsed_seconds = max(0.0, time.time() - created.timestamp())
        else:
            elapsed_seconds = elapsed
    except Exception:
        elapsed_seconds = elapsed

    st.bot_text = bot_text
    st.chat_latency = chat_latency
    st.elapsed = elapsed
    st.elapsed_seconds = elapsed_seconds
    st.latency_ms = latency_ms
    st.offered_tools = offered_tools
    st.retrieve_latency = retrieve_latency
    st.t0 = t0
    st.tokens = tokens
    st.tool_trace = tool_trace


def _sandbox_judge_and_persist(st: SandboxTurn) -> None:
    """The guardrails on the reply, then both turn rows and the run's aggregates under the row lock."""
    run_id = st.run_id
    customer_text = st.customer_text
    bot_text = st.bot_text
    chunk_ids = st.chunk_ids
    effective_max = st.effective_max
    elapsed_seconds = st.elapsed_seconds
    guardrails = st.guardrails
    intent = st.intent
    latency_ms = st.latency_ms
    max_turns = st.max_turns
    prior_customers = st.prior_customers
    recording_disclosed = st.recording_disclosed
    rehearsal_channel = st.rehearsal_channel
    sent_label = st.sent_label
    tokens = st.tokens
    turn_count = st.turn_count

    customer_turn_index = int(turn_count)
    bot_turn_index = customer_turn_index + 1
    exchange_n = prior_customers + 1
    t_guardrails_start = time.perf_counter()
    flags = evaluate_guardrails(
        customer_text=customer_text,
        bot_text=bot_text,
        intent=intent,
        guardrails=guardrails,
        turn_index=bot_turn_index,
        elapsed_seconds=elapsed_seconds,
        customer_bot_exchanges=exchange_n,
        # The card's own ceiling is what is under test. The sandbox budget is
        # a cost cap and reports itself as one (`sandbox_budget_reached`), not
        # as a guardrail flag against the card.
        hard_max_turns=max_turns or _LIVE_HARD_MAX_TURNS,
        recording_disclosed=recording_disclosed,
        channel=rehearsal_channel,
    )
    halted = should_halt(flags)
    t_guardrails_end = time.perf_counter()

    customer_turn_id = f"{run_id}-T{customer_turn_index}"
    bot_turn_id = f"{run_id}-T{bot_turn_index}"

    t_persist_start = time.perf_counter()
    with db.engine.begin() as conn:
        run_locked = conn.execute(
            text(
                """
                SELECT id, status,
                       COALESCE(aggregate_latency_ms, 0) AS aggregate_latency_ms,
                       COALESCE(aggregate_tokens, 0) AS aggregate_tokens
                FROM sandbox_runs
                WHERE id = :id
                FOR UPDATE
                """
            ),
            {"id": run_id},
        ).mappings().first()
        if not run_locked or run_locked["status"] != "running":
            raise ValueError(f"sandbox_run_not_active: {run_locked['status'] if run_locked else 'missing'}")

        # Counts and the derived turn ids are read *under* the run row lock, so
        # two concurrent appends to the same run serialise instead of both
        # computing the same turn_index and colliding on the primary key.
        counts = conn.execute(
            text(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE speaker = 'customer') AS customers
                FROM sandbox_run_turns WHERE run_id = :id
                """
            ),
            {"id": run_id},
        ).mappings().first()
        turn_count = int((counts or {}).get("total") or 0)
        prior_customers = int((counts or {}).get("customers") or 0)
        # Authoritative cap check — the pre-check above raced.
        if prior_customers >= effective_max:
            raise ValueError(f"sandbox_budget_reached:{effective_max}")
        customer_turn_index = turn_count
        bot_turn_index = customer_turn_index + 1
        customer_turn_id = f"{run_id}-T{customer_turn_index}"
        bot_turn_id = f"{run_id}-T{bot_turn_index}"

        conn.execute(
            text(
                """
                INSERT INTO sandbox_run_turns (
                  id, run_id, turn_index, speaker, text,
                  detected_intent, sentiment_label, retrieved_chunk_ids,
                  guardrail_flags, latency_ms, token_count, created_at
                ) VALUES (
                  :id, :run_id, :turn_index, 'customer', :text,
                  :intent, :sentiment, CAST('[]' AS jsonb),
                  CAST('[]' AS jsonb), NULL, NULL, now()
                )
                """
            ),
            {
                "id": customer_turn_id,
                "run_id": run_id,
                "turn_index": customer_turn_index,
                "text": customer_text,
                "intent": intent,
                "sentiment": sent_label,
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO sandbox_run_turns (
                  id, run_id, turn_index, speaker, text,
                  detected_intent, sentiment_label, retrieved_chunk_ids,
                  guardrail_flags, latency_ms, token_count, created_at
                ) VALUES (
                  :id, :run_id, :turn_index, 'bot', :text,
                  :intent, :sentiment, CAST(:chunks AS jsonb),
                  CAST(:flags AS jsonb), :latency_ms, :tokens, now()
                )
                """
            ),
            {
                "id": bot_turn_id,
                "run_id": run_id,
                "turn_index": bot_turn_index,
                "text": bot_text,
                "intent": intent,
                "sentiment": sent_label,
                "chunks": json.dumps(chunk_ids),
                "flags": json.dumps(flags),
                "latency_ms": latency_ms,
                "tokens": tokens,
            },
        )
        if halted:
            conn.execute(
                text(
                    """
                    INSERT INTO sandbox_run_turns (
                      id, run_id, turn_index, speaker, text,
                      detected_intent, sentiment_label, retrieved_chunk_ids,
                      guardrail_flags, latency_ms, token_count, created_at
                    ) VALUES (
                      :id, :run_id, :turn_index, 'system', :text,
                      NULL, NULL, CAST('[]' AS jsonb),
                      CAST(:flags AS jsonb), NULL, NULL, now()
                    )
                    """
                ),
                {
                    "id": f"{run_id}-T{bot_turn_index + 1}",
                    "run_id": run_id,
                    "turn_index": bot_turn_index + 1,
                    "text": f"Run halted · guardrail {', '.join(flags)}",
                    "flags": json.dumps(flags),
                },
            )
        conn.execute(
            text(
                """
                UPDATE sandbox_runs
                SET status = :status,
                    aggregate_latency_ms = :lat,
                    aggregate_tokens = :tok,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": run_id,
                "status": "completed" if halted else "running",
                "lat": int(run_locked["aggregate_latency_ms"] or 0) + latency_ms,
                "tok": int(run_locked["aggregate_tokens"] or 0) + tokens,
            },
        )
    t_persist_end = time.perf_counter()

    st.bot_turn_id = bot_turn_id
    st.bot_turn_index = bot_turn_index
    st.customer_turn_id = customer_turn_id
    st.flags = flags
    st.halted = halted
    st.prior_customers = prior_customers
    st.t_guardrails_end = t_guardrails_end
    st.t_guardrails_start = t_guardrails_start
    st.t_persist_end = t_persist_end
    st.t_persist_start = t_persist_start
    st.turn_count = turn_count


def _sandbox_response(st: SandboxTurn) -> dict[str, Any]:
    """The stage-timing line and the response the studio renders."""
    run_id = st.run_id
    customer_text = st.customer_text
    bot_text = st.bot_text
    bot_turn_id = st.bot_turn_id
    bot_turn_index = st.bot_turn_index
    chat_latency = st.chat_latency
    chunk_ids = st.chunk_ids
    compiled = st.compiled
    contract_flow = st.contract_flow
    customer_turn_id = st.customer_turn_id
    elapsed = st.elapsed
    enrichment_async = st.enrichment_async
    enrichment_wait_ms = st.enrichment_wait_ms
    enrichment_wall_ms = st.enrichment_wall_ms
    flags = st.flags
    flow_walker = st.flow_walker
    grounding = st.grounding
    halted = st.halted
    intent = st.intent
    intent_scores = st.intent_scores
    latency_ms = st.latency_ms
    offered_tools = st.offered_tools
    retrieval = st.retrieval
    retrieve_latency = st.retrieve_latency
    sent_label = st.sent_label
    sentiment = st.sentiment
    t0 = st.t0
    t_after_preflight = st.t_after_preflight
    t_guardrails_end = st.t_guardrails_end
    t_guardrails_start = st.t_guardrails_start
    t_persist_end = st.t_persist_end
    t_persist_start = st.t_persist_start
    t_retrieve_end = st.t_retrieve_end
    t_retrieve_start = st.t_retrieve_start
    t_turn_start = st.t_turn_start
    t_understanding_end = st.t_understanding_end
    t_understanding_start = st.t_understanding_start
    tokens = st.tokens
    tool_trace = st.tool_trace
    understanding_llm = st.understanding_llm
    version = st.version

    stage_timings = _stage_timings(
        run_id=run_id,
        turn_index=bot_turn_index,
        turn_start=t_turn_start,
        after_preflight=t_after_preflight,
        retrieve_start=t_retrieve_start,
        retrieve_end=t_retrieve_end,
        understanding_start=t_understanding_start,
        understanding_end=t_understanding_end,
        understanding_llm_enabled=understanding_llm,
        enrichment_async=enrichment_async,
        enrichment_wall_ms=enrichment_wall_ms,
        enrichment_wait_ms=enrichment_wait_ms,
        llm_start=t0,
        llm_end=t0 + elapsed,
        guardrails_start=t_guardrails_start,
        guardrails_end=t_guardrails_end,
        persist_start=t_persist_start,
        persist_end=t_persist_end,
        reported_chat_ms=chat_latency,
        reported_retrieve_ms=retrieve_latency,
        tool_calls=len(tool_trace),
        tokens=tokens,
    )
    logger.info("%s %s", _STAGE_TIMING_LOG_PREFIX, json.dumps(stage_timings, sort_keys=True))

    return {
        "runId": run_id,
        "promptVersionId": version["id"],
        "compiledBundleHash": compiled.get("bundle_hash"),
        "flowStatus": (
            "walked"
            if flow_walker is not None
            else "validated_not_executed_in_text_rehearsal"
            if contract_flow
            else "not_authored"
        ),
        "nodeKey": (
            flow_walker.current.key
            if flow_walker is not None and flow_walker.current is not None
            else None
        ),
        "offeredTools": offered_tools or None,
        "customerTurn": {
            "id": customer_turn_id,
            "role": "customer",
            "text": customer_text,
            "intent": intent,
            "intentScores": intent_scores,
            "sentiment": sentiment,
            "sentimentLabel": sent_label,
        },
        "botTurn": {
            "id": bot_turn_id,
            "role": "bot",
            "text": bot_text,
            "chunkIds": chunk_ids,
            "chunks": [
                {
                    "chunkId": r["chunkId"],
                    "docId": r.get("docId"),
                    "docTitle": r.get("docTitle"),
                    "heading": r.get("heading"),
                    "snippet": r.get("snippet"),
                    "score": r.get("score"),
                }
                for r in grounding
            ],
            "latencyMs": latency_ms,
            "tokens": tokens,
            "guardrailFlags": flags,
            "intent": intent,
            "toolCalls": tool_trace,
            "sentiment": sentiment,
            "sentimentLabel": sent_label,
            "retrievalLogId": retrieval.get("logId"),
            "retrieveLatencyMs": retrieve_latency,
            "chatLatencyMs": chat_latency,
            "halted": halted,
        },
    }


def append_sandbox_turn(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Customer utterance → retrieve → chat → persist customer + bot turns."""
    customer_text = (payload.get("text") or "").strip()
    if not customer_text:
        raise ValueError("text must not be empty")

    st = SandboxTurn(run_id=run_id, payload=payload, customer_text=customer_text)
    _sandbox_contract(st)
    _sandbox_preflight(st)
    _sandbox_assemble(st)
    _sandbox_model(st)
    _sandbox_judge_and_persist(st)
    return _sandbox_response(st)


def complete_sandbox_run(run_id: str) -> dict[str, Any]:
    with db.engine.begin() as conn:
        row = conn.execute(
            text("SELECT id, status FROM sandbox_runs WHERE id = :id"),
            {"id": run_id},
        ).mappings().first()
        if not row:
            raise KeyError(f"sandbox_run_not_found: {run_id}")
        conn.execute(
            text(
                """
                UPDATE sandbox_runs
                SET status = 'completed', updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": run_id},
        )
    return {"id": run_id, "status": "completed"}
