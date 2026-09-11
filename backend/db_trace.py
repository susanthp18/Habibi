"""Per-turn trace reads (WP-036 peel: the conversation trace).

Peeled from ``db.py``. Call sites stay ``db.*`` via a bottom-of-file
re-export. Reach the engine through :func:`_db`, never ``from db_core import
engine``: the ``db_tx`` fixture wraps ``db.engine``, and a name bound from
``db_core`` bypasses that proxy.
"""

from __future__ import annotations

from sqlalchemy import text
from typing import Any


def _db():
    """The ``db`` module object, resolved at call time."""
    import db as d

    return d


def _trace_redact(value: Any) -> Any:
    """Redact anything that reaches a trace response.

    ``bot_tool_calls.result_preview`` holds up to 1500 chars of raw tool output
    — balances, DPD, phone tails — and ``args`` holds model-supplied customer
    speech (``flag_dispute.summary``, ``capture_lead.summary``). Until now only
    the Inbox read this table; an endpoint widens the audience, so it is masked
    on the way out rather than trusted to be safe.
    """
    import transcript_view

    if value is None:
        return None
    if isinstance(value, str):
        return transcript_view.redact_line(value)
    if isinstance(value, dict):
        return {k: _trace_redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_trace_redact(v) for v in value]
    return value


def get_turn_trace(interaction_id: str) -> list[dict[str, Any]]:
    """Every turn of one interaction, with its tool calls, retrievals and latency."""
    _mod = _db()
    _TRACE_MAX_TURNS = _mod._TRACE_MAX_TURNS
    _one = _mod._one
    _rows = _mod._rows
    engine = _mod.engine
    with engine.connect() as conn:
        exists = _one(
            conn.execute(
                text("SELECT id FROM interactions WHERE id = :id"),
                {"id": interaction_id},
            )
        )
        if not exists:
            raise KeyError(f"interaction not found: {interaction_id}")

        turns = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, turn_index, speaker, at_sec, text, intent, intent_score,
                           sentiment_delta, ttfb_ms, ttfa_ms, tokens,
                           stt_ttfb_ms, llm_ttfb_ms, tts_ttfb_ms,
                           user_turn_ms, tool_ms, aggregation_ms
                    FROM interaction_transcript
                    WHERE interaction_id = :ix
                    ORDER BY turn_index
                    LIMIT :lim
                    """
                ),
                {"ix": interaction_id, "lim": _TRACE_MAX_TURNS},
            )
        )
        tool_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT transcript_turn_id, tool_name, args, result_ok, error,
                           result_preview, latency_ms, channel, created_at,
                           agent_id, skill_id, connector_id
                    FROM bot_tool_calls
                    WHERE interaction_id = :ix
                    ORDER BY created_at
                    """
                ),
                {"ix": interaction_id},
            )
        )
        retrieval_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT transcript_turn_id, query, top_chunks, latency_ms,
                           selected_answer_source, created_at
                    FROM retrieval_logs
                    WHERE interaction_id = :ix
                    ORDER BY created_at
                    """
                ),
                {"ix": interaction_id},
            )
        )

    # Rows whose turn could not be resolved (the tool ran before the transcript
    # row existed) are kept under a null key and surfaced as an "unattributed"
    # bucket rather than dropped — losing an audit record to a race is worse
    # than showing it in the wrong place.
    tools_by_turn: dict[Any, list[dict[str, Any]]] = {}
    for r in tool_rows:
        tools_by_turn.setdefault(r["transcript_turn_id"], []).append(
            {
                "tool": r["tool_name"],
                "ok": bool(r["result_ok"]),
                "error": r["error"],
                "latencyMs": r["latency_ms"],
                "channel": r["channel"],
                "args": _trace_redact(r["args"]),
                "resultPreview": _trace_redact(r["result_preview"]),
                "at": r["created_at"],
                "agentId": r.get("agent_id"),
                "skillId": r.get("skill_id"),
                "connectorId": r.get("connector_id"),
            }
        )

    retrievals_by_turn: dict[Any, list[dict[str, Any]]] = {}
    for r in retrieval_rows:
        chunks = r["top_chunks"] or []
        retrievals_by_turn.setdefault(r["transcript_turn_id"], []).append(
            {
                # Already redacted at write time in kb_retrieve; masked again on
                # the way out because the write-side patterns and these are not
                # guaranteed to stay in sync.
                "query": _trace_redact(r["query"]),
                "hits": len(chunks) if isinstance(chunks, list) else 0,
                "topScore": (
                    chunks[0].get("score")
                    if isinstance(chunks, list)
                    and chunks
                    and isinstance(chunks[0], dict)
                    else None
                ),
                "chunks": chunks,
                "latencyMs": r["latency_ms"],
                "source": r["selected_answer_source"],
                "at": r["created_at"],
            }
        )

    out: list[dict[str, Any]] = []
    for t in turns:
        out.append(
            {
                "turnId": t["id"],
                "turnIndex": t["turn_index"],
                "speaker": t["speaker"],
                "atSec": t["at_sec"],
                "text": _trace_redact(t["text"]),
                "intent": t["intent"],
                "intentScore": float(t["intent_score"])
                if t["intent_score"] is not None
                else None,
                "sentimentDelta": (
                    float(t["sentiment_delta"])
                    if t["sentiment_delta"] is not None
                    else None
                ),
                "latency": {
                    "ttfbMs": t["ttfb_ms"],
                    "ttfaMs": t["ttfa_ms"],
                    "tokens": t["tokens"],
                    "sttTtfbMs": t["stt_ttfb_ms"],
                    "llmTtfbMs": t["llm_ttfb_ms"],
                    "ttsTtfbMs": t["tts_ttfb_ms"],
                    "userTurnMs": t["user_turn_ms"],
                    "toolMs": t["tool_ms"],
                    "aggregationMs": t["aggregation_ms"],
                },
                "toolCalls": tools_by_turn.get(t["id"], []),
                "retrievals": retrievals_by_turn.get(t["id"], []),
            }
        )

    orphan_tools = tools_by_turn.get(None, [])
    orphan_retrievals = retrievals_by_turn.get(None, [])
    if orphan_tools or orphan_retrievals:
        out.append(
            {
                "turnId": None,
                "turnIndex": None,
                "speaker": "system",
                "atSec": None,
                "text": "Events that could not be attributed to a turn.",
                "intent": None,
                "intentScore": None,
                "sentimentDelta": None,
                "latency": {},
                "toolCalls": orphan_tools,
                "retrievals": orphan_retrievals,
            }
        )
    return out
