"""Everything about one call, in one downloadable bundle.

The reason this exists: reviewing a call meant reading a Docker log by hand and
cross-joining it against five Postgres tables. All the material was there —
per-turn classification, the stage-by-stage latency split, every tool call and
its arguments, the KB retrievals, the guardrail flags, the resolved tuning —
just scattered, with no way to get it out of the product.

Two renderings of the same query set:

* :func:`build_bundle` — JSON. Stable keys, camelCase, machine-readable.
* :func:`render_markdown` — the same data as prose and tables, sized to paste
  into an external model and ask "where is this call losing time, and where is
  the agent behaving badly?"

Both are read-only and safe to call on a live interaction; a call still in
progress simply exports fewer turns.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

import db

_MAX_ARG_CHARS = 2000


def _rows(conn, sql: str, **params: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def _num(v: Any) -> Any:
    """Decimal/Numeric → float so json.dumps does not choke."""
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return str(v)


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return {k: _num(v) for k, v in row.items()}


def build_bundle(interaction_id: str) -> dict[str, Any] | None:
    """Assemble the full record for one interaction. ``None`` if unknown."""
    with db.engine.connect() as conn:
        header = _rows(
            conn,
            """
            SELECT i.*, c.name AS customer_name
            FROM interactions i
            LEFT JOIN customers c ON c.id = i.customer_id
            WHERE i.id = :id
            """,
            id=interaction_id,
        )
        if not header:
            return None

        turns = _rows(
            conn,
            """
            SELECT turn_index, speaker, at_sec, text, sentiment_delta, intent,
                   intent_score, ttfb_ms, ttfa_ms, tokens, stt_ttfb_ms,
                   llm_ttfb_ms, tts_ttfb_ms, user_turn_ms, tool_ms,
                   aggregation_ms, created_at
            FROM interaction_transcript
            WHERE interaction_id = :id
            ORDER BY turn_index
            """,
            id=interaction_id,
        )
        tools = _rows(
            conn,
            """
            SELECT tool_name, args, result_ok, error, result_preview,
                   latency_ms, channel, created_at
            FROM bot_tool_calls
            WHERE interaction_id = :id
            ORDER BY created_at
            """,
            id=interaction_id,
        )
        retrievals = _rows(
            conn,
            """
            SELECT query, top_chunks, latency_ms, selected_answer_source, created_at
            FROM retrieval_logs
            WHERE interaction_id = :id
            ORDER BY created_at
            """,
            id=interaction_id,
        )
        flags = _rows(
            conn,
            "SELECT flag, severity, created_at FROM interaction_flags "
            "WHERE interaction_id = :id ORDER BY created_at",
            id=interaction_id,
        )
        sentiment = _rows(
            conn,
            "SELECT at_sec, score, label FROM interaction_sentiment "
            "WHERE interaction_id = :id ORDER BY at_sec",
            id=interaction_id,
        )

    head = _clean(header[0])
    # The tuning/prompt actually used, not the current default — source_payload
    # is what the runtime recorded when the call started.
    config = head.pop("source_payload", None)
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except ValueError:
            pass

    turns = [_clean(t) for t in turns]
    return {
        "schemaVersion": 1,
        "interaction": head,
        "configuration": config,
        "transcript": [_turn_json(t) for t in turns],
        "toolCalls": [_tool_json(t) for t in tools],
        "retrievals": [_clean(r) for r in retrievals],
        "guardrailFlags": [_clean(f) for f in flags],
        "sentimentSeries": [_clean(s) for s in sentiment],
        "latencySummary": summarise_latency(turns),
    }


def _turn_json(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "turnIndex": t.get("turn_index"),
        "speaker": t.get("speaker"),
        "atSec": t.get("at_sec"),
        "text": t.get("text"),
        "sentiment": t.get("sentiment_delta"),
        "intent": t.get("intent"),
        "intentScore": t.get("intent_score"),
        "latency": {
            "userTurnMs": t.get("user_turn_ms"),
            "sttTtfbMs": t.get("stt_ttfb_ms"),
            "toolMs": t.get("tool_ms"),
            "llmTtfbMs": t.get("llm_ttfb_ms"),
            "ttsTtfbMs": t.get("tts_ttfb_ms"),
            "aggregationMs": t.get("aggregation_ms"),
            "ttfbMs": t.get("ttfb_ms"),
            "ttfaMs": t.get("ttfa_ms"),
        },
        "tokens": t.get("tokens"),
    }


def _tool_json(t: dict[str, Any]) -> dict[str, Any]:
    args = t.get("args")
    if isinstance(args, str) and len(args) > _MAX_ARG_CHARS:
        args = args[:_MAX_ARG_CHARS] + "…"
    return {
        "tool": t.get("tool_name"),
        "args": args,
        "ok": t.get("result_ok"),
        "error": t.get("error"),
        "resultPreview": t.get("result_preview"),
        "latencyMs": _num(t.get("latency_ms")),
        "channel": t.get("channel"),
        "at": str(t.get("created_at")) if t.get("created_at") else None,
    }


_STAGES = (
    ("userTurnMs", "user_turn_ms"),
    ("sttTtfbMs", "stt_ttfb_ms"),
    ("toolMs", "tool_ms"),
    ("llmTtfbMs", "llm_ttfb_ms"),
    ("ttsTtfbMs", "tts_ttfb_ms"),
)


def summarise_latency(turns: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-stage p50/p95/max plus the worst end-to-end bot turn.

    Reported per stage rather than as one number because the stages have
    different owners — turn-end detection is VAD tuning, TTS time-to-first-audio
    is mostly reply length, and tool time is the tool. A single average hides
    which one to go and fix.
    """
    out: dict[str, Any] = {"stages": {}, "botTurns": 0}
    bot = [t for t in turns if t.get("speaker") == "bot"]
    out["botTurns"] = len(bot)
    for label, col in _STAGES:
        vals = sorted(float(t[col]) for t in bot if t.get(col) is not None)
        if not vals:
            continue
        out["stages"][label] = {
            "n": len(vals),
            "p50": _pct(vals, 0.50),
            "p95": _pct(vals, 0.95),
            "max": vals[-1],
        }
    totals = [
        (t.get("turn_index"), sum(float(t[c]) for _, c in _STAGES if t.get(c) is not None))
        for t in bot
    ]
    totals = [x for x in totals if x[1] > 0]
    if totals:
        worst = max(totals, key=lambda x: x[1])
        out["worstTurn"] = {"turnIndex": worst[0], "totalMs": round(worst[1])}
        out["medianTotalMs"] = round(_pct(sorted(t[1] for t in totals), 0.50))
    return out


def _pct(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = min(len(sorted_vals) - 1, max(0, round(q * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


# ------------------------------------------------------------------ markdown


def render_markdown(bundle: dict[str, Any]) -> str:
    """The same bundle as a document. Written to be pasted into a chat model."""
    ix = bundle.get("interaction") or {}
    lines: list[str] = []
    add = lines.append

    add(f"# Call {ix.get('id')} — full record")
    add("")
    add(
        "Exported from the Collections agent sandbox. Everything below is "
        "measured, not estimated: turn text and timings come from the live "
        "pipeline, classification from the per-turn analyser."
    )
    add("")
    add("## Call")
    add("")
    for key in (
        "customer_name", "customer_id", "channel", "direction", "status",
        "disposition", "primary_intent", "avg_sentiment", "sentiment_label",
        "started_at", "ended_at", "duration_sec", "deployment_id",
    ):
        if ix.get(key) is not None:
            add(f"- **{key.replace('_', ' ')}**: {ix[key]}")
    add("")

    lat = bundle.get("latencySummary") or {}
    stages = lat.get("stages") or {}
    if stages:
        add("## Latency, by stage")
        add("")
        add("Milliseconds. A caller feels the sum of these between finishing")
        add("their sentence and hearing the reply begin.")
        add("")
        add("| stage | n | p50 | p95 | max |")
        add("|---|---:|---:|---:|---:|")
        for name, s in stages.items():
            add(
                f"| {name} | {s['n']} | {round(s['p50'])} | "
                f"{round(s['p95'])} | {round(s['max'])} |"
            )
        add("")
        if lat.get("medianTotalMs") is not None:
            add(f"- median total per bot turn: **{lat['medianTotalMs']} ms**")
        worst = lat.get("worstTurn")
        if worst:
            add(f"- worst turn: **#{worst['turnIndex']} at {worst['totalMs']} ms**")
        add("")

    add("## Transcript")
    add("")
    for t in bundle.get("transcript") or []:
        who = "BOT" if t.get("speaker") == "bot" else "CALLER"
        meta: list[str] = []
        if t.get("intent"):
            meta.append(f"intent={t['intent']}")
        if t.get("sentiment") is not None:
            meta.append(f"sentiment={t['sentiment']}")
        stage = t.get("latency") or {}
        total = sum(v for v in stage.values() if isinstance(v, (int, float)))
        if who == "BOT" and total:
            bits = [f"{k}={round(v)}" for k, v in stage.items() if isinstance(v, (int, float))]
            meta.append(" ".join(bits))
        suffix = f"  _{' · '.join(meta)}_" if meta else ""
        add(f"**{t.get('turnIndex')} · {who}** ({t.get('atSec')}s): {t.get('text')}{suffix}")
        add("")

    calls = bundle.get("toolCalls") or []
    if calls:
        add("## Tool calls")
        add("")
        add("| tool | ok | ms | args | error |")
        add("|---|---|---:|---|---|")
        for c in calls:
            args = str(c.get("args") or "")[:160].replace("|", "\\|").replace("\n", " ")
            err = str(c.get("error") or "")[:80].replace("|", "\\|")
            add(
                f"| {c.get('tool')} | {'yes' if c.get('ok') else 'NO'} | "
                f"{round(c.get('latencyMs') or 0)} | `{args}` | {err} |"
            )
        add("")

    hits = bundle.get("retrievals") or []
    if hits:
        add("## Knowledge base retrievals")
        add("")
        for r in hits:
            add(
                f"- ({round(r.get('latency_ms') or 0)} ms, "
                f"source={r.get('selected_answer_source')}) {str(r.get('query'))[:200]}"
            )
        add("")

    flags = bundle.get("guardrailFlags") or []
    add("## Guardrail flags")
    add("")
    if flags:
        for f in flags:
            add(f"- `{f.get('flag')}` · severity {f.get('severity')} · {f.get('created_at')}")
    else:
        add("None raised.")
    add("")

    cfg = bundle.get("configuration")
    if cfg:
        add("## Configuration in force")
        add("")
        add("```json")
        add(json.dumps(cfg, indent=2, default=str)[:20000])
        add("```")
        add("")

    add("## Questions worth asking about this call")
    add("")
    add("- Which stage dominates the latency table, and is it tuning or model choice?")
    add("- Does any bot turn restate an earlier one nearly verbatim?")
    add("- Did any tool run that the agent's own instructions told it not to call?")
    add("- Does the intent on each caller turn match what they actually said?")
    add("- Where did the caller have to repeat themselves?")
    return "\n".join(lines)
