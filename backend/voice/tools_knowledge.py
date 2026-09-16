"""Voice tools -- the knowledge base.

One section of the voice tool set: the handlers that used to be closures
inside ``voice.tools.build_tools``. ``build(ctx)`` receives the closure
scope as a ``ToolBuildContext`` and unpacks the names it reads, so every
handler body below is byte-for-byte what it was -- a move, pinned by
``tests/test_voice_tool_schemas_snapshot.py``.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Any

# Not `from pipecat.flows import ...` directly: this module is the trunk the
# built-in flow export hangs off, and the API image has no pipecat. See
# agent_core/tools/pipecat_compat.py — under pipecat these are pipecat's own
# objects and nothing about a call changes.

from agent_core.context import product_keys_for_node
from agent_core.tools.catalog import (
    CATALOG,
)
from agent_core.tools import kb as kb_tool

from voice.tool_state import (
    ToolBuildContext,
    KB_CONFIDENCE_THRESHOLD,
)

logger = logging.getLogger(__name__)


def count_scored_rag_hits(rows: list[dict[str, Any]]) -> int:
    """Count retrieval rows that are actual passages, not catalog titles."""
    hits = 0
    for row in rows:
        if float(row.get("score") or 0) > 0:
            hits += 1
            continue
        if str(row.get("docType") or "") not in {"", "catalog"} and (
            row.get("snippet") or ""
        ).strip():
            hits += 1
    return hits


def build(ctx: ToolBuildContext) -> dict[str, Any]:
    """The tools of this section, keyed by the variable name build_tools used."""
    _gap_sink = ctx._gap_sink
    _sink_call = ctx._sink_call
    _spec = ctx._spec
    kb_snapshot_id = ctx.kb_snapshot_id
    on_kb_tool_used = ctx.on_kb_tool_used
    rtvi = ctx.rtvi
    session = ctx.session
    state = ctx.state


    # ------------------------------------------------------------------ KB

    async def _search_knowledge_base_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Search the knowledge base for policy or FAQ answers.

        Never use this for balances, dues, or payment amounts — CRM is authoritative.
        Honor answer_policy in the result: if confident is false, do not answer
        from snippets — defer to a specialist and offer request_callback.
        """
        args = CATALOG.normalize("search_knowledge_base", args)
        query = str(args.get("query") or "")
        # Tool-first: stand the always-on enricher down so the next few turns
        # don't pay a second embed + ANN query for the same ground truth.
        if on_kb_tool_used is not None:
            try:
                on_kb_tool_used()
            except Exception:
                logger.debug("kb enrich suppress failed", exc_info=True)

        # Corpus scope follows the node, unless the query is clearly about a
        # product. escalate_close / pre_close used to hard-filter to
        # ``collections``, so a travel-insurance exclusions question retrieved
        # nothing and the judge then fail-opened as confident.
        product_keys = product_keys_for_node(state.current_node)
        if kb_tool.query_looks_product(query):
            product_keys = None
        snapshot = kb_snapshot_id
        # Collections FAQs *are* policy text, so bias retrieval that way. On the
        # product corpus, let the query decide — exclusions stay exclusions.
        prefer_policy = (
            kb_tool.wants_policy_detail(query) if product_keys is None else True
        )
        # The run-up, and the caller's own last words out of it.
        #
        # "No customer turn is available here" was true of this function's
        # arguments and never true of the call: the CrmSink has kept an
        # interleaved buffer of both speakers all along, and hands it to the turn
        # analyser on every turn. Retrieval has the same problem the analyser
        # has — a follow-up that names no product is unplannable without the
        # turns before it — so it gets the same answer.
        recent = list(_sink_call("run_up", []) or [])
        caller_text = next(
            (t for who, t in reversed(recent) if str(who).lower() not in {"bot", "agent", "assistant"}),
            "",
        )

        retrieve_query = (caller_text or query or "").strip()
        result = await asyncio.to_thread(
            partial(
                kb_tool.search_knowledge_base,
                query=retrieve_query,
                channel="voice",
                customer_text=caller_text,
                recent=recent or None,
                interaction_id=session.interaction_id,
                product_keys=product_keys,
                kb_snapshot_id=snapshot,
                prefer_policy=prefer_policy,
                confidence_threshold=KB_CONFIDENCE_THRESHOLD,
                # The node graph already scopes the corpus, so the text
                # channel's intent gate would double-block a legitimate hub FAQ.
                apply_intent_gate=False,
                # Keyword expansion stays off here even though the caller's turn
                # is now available. It is the *fallback* steering, and on voice
                # the planner has the run-up, which is strictly better evidence;
                # turning both on would let the keyword tuples re-introduce the
                # padding the planner exists to stop reading.
                should_expand_query=False,
                # Voice upsell analytics ride check_product_eligibility /
                # capture_lead, not KB hits.
                record_offer=False,
                # Defer the gap write to the CrmSink queue — see _gap_sink.
                gap_sink=_gap_sink(),
            )
        )

        if not result.ok:
            payload: dict[str, Any] = {"error": result.error, **(result.data or {})}
            if result.spoken_summary:
                payload["say"] = result.spoken_summary
            return payload, None

        data = result.data
        rows = data["results"]
        # Catalog name-only rows have no retrieval score. Counting them as
        # rag_hits made a names-only listing look like ten grounded passages.
        session.rag_hits += count_scored_rag_hits(rows)
        top = float(data["topScore"] or 0)

        await rtvi.rag_hits(
            query=(query or "").strip(),
            chunk_ids=data["chunkIds"],
            snapshot_id=snapshot,
            top_score=top,
            source="tool",
        )

        # Shaping lives in the shared handler — see `kb.llm_payload`. This
        # block and its text-channel twin had drifted apart on six keys, and
        # both had dropped `mode`, which is what says whether a search ran at
        # all. The voice-only parts that are real (spoken length rule, the
        # `title` field this card's prompt refers to, the untrusted-data note)
        # moved with it rather than being flattened away.
        return {"ok": True, **kb_tool.llm_payload(data, channel="voice")}, None

    search_knowledge_base = _spec("search_knowledge_base", 
        _search_knowledge_base_handler
    )

    return {
        "search_knowledge_base": search_knowledge_base,
    }
