"""Sandbox scenario and run accessors.

Peeled from ``db.py`` (WP-036 peel 5). Call sites stay ``db.*`` via a
bottom-of-file re-export. Reach the engine through :func:`_db`, never
``from db_core import engine``: the ``db_tx`` fixture wraps ``db.engine``,
and a name bound from ``db_core`` bypasses that proxy.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from db_core import _as_dict, _one, _rows, _tenant


def _db():
    """The ``db`` module object, resolved at call time.

    Carved modules must use ``_db().engine``, never ``from db_core import
    engine``. See ``db_core._db``.
    """
    import db as d

    return d


# ---------------------------------------------------------------------------
# Sandbox (PS-3) — scenarios + runs
# ---------------------------------------------------------------------------

_VALID_DIFFICULTIES = frozenset({"easy", "medium", "hard"})


def _sandbox_persona_from_sim(raw: Any) -> dict[str, Any]:
    data = _as_dict(raw)
    overdue = data.get("overdue", 0)
    try:
        overdue_f = float(overdue) if overdue is not None else 0.0
    except (TypeError, ValueError):
        overdue_f = 0.0
    dpd = data.get("dpd", 0)
    try:
        dpd_i = int(dpd) if dpd is not None else 0
    except (TypeError, ValueError):
        dpd_i = 0
    return {
        "name": str(data.get("name") or "Customer"),
        "phoneLast4": str(data.get("phoneLast4") or "0000"),
        "product": str(data.get("product") or "—"),
        "dpd": dpd_i,
        "overdue": overdue_f,
        "mood": str(data.get("mood") or "neutral"),
        "language": str(data.get("language") or "English"),
        "accountNo": data.get("accountNo"),
        "dueDate": data.get("dueDate"),
        "bankName": data.get("bankName"),
        "lastPayment": data.get("lastPayment"),
    }


def _sandbox_scripted_turns(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        customer = item.get("customer") or item.get("text")
        if not customer:
            continue
        turn: dict[str, Any] = {"customer": str(customer)}
        if item.get("expectedIntent") is not None:
            turn["expectedIntent"] = str(item["expectedIntent"])
        sent = item.get("expectedSentiment")
        if isinstance(sent, (int, float)):
            turn["expectedSentiment"] = float(sent)
        out.append(turn)
    return out


def _map_sandbox_scenario(r: dict[str, Any]) -> dict[str, Any]:
    sim = _as_dict(r.get("sim_persona"))
    difficulty = str(sim.get("difficulty") or "medium").lower()
    if difficulty not in _VALID_DIFFICULTIES:
        difficulty = "medium"
    intents_raw = sim.get("intents") or []
    intents = [str(x) for x in intents_raw] if isinstance(intents_raw, list) else []
    persona = _sandbox_persona_from_sim(sim)
    return {
        "id": r["id"],
        "title": str(sim.get("title") or r.get("name") or r["id"]),
        "summary": str(sim.get("summary") or ""),
        "difficulty": difficulty,
        "intents": intents,
        "persona": {
            "name": persona["name"],
            "phoneLast4": persona["phoneLast4"],
            "product": persona["product"],
            "dpd": persona["dpd"],
            "overdue": persona["overdue"],
            "mood": persona["mood"],
            "language": persona["language"],
        },
        "openingBot": str(sim.get("openingBot") or ""),
        "turns": _sandbox_scripted_turns(r.get("turns")),
    }


def sandbox_scenario_call(scenario_id: str | None) -> dict[str, str | None]:
    """Which way a scenario's call goes, and what an outbound one is for.

    Explicit in ``sim_persona`` (``direction``, ``objective``) because nothing
    else can say it: every scenario has an ``openingBot`` and both directions
    have the bot speak first. Absent means inbound, the old behaviour.
    """
    if not scenario_id:
        return {"direction": "inbound", "objective": None}
    with _db().engine.connect() as conn:
        raw = conn.execute(
            text(
                "SELECT sim_persona FROM sandbox_scenarios WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {"id": scenario_id, "tenant_id": _tenant()},
        ).scalar()
    sim = _as_dict(raw)
    direction = str(sim.get("direction") or "").strip().lower()
    return {
        "direction": "outbound" if direction == "outbound" else "inbound",
        "objective": str(sim.get("objective") or "").strip() or None,
    }


def list_sandbox_scenarios() -> list[dict[str, Any]]:
    engine = _db().engine
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, name, sim_persona, turns, created_at
                    FROM sandbox_scenarios
                    WHERE tenant_id = :tenant_id
                    ORDER BY created_at ASC, id ASC
                    """
                ),
                {"tenant_id": _tenant()},
            )
        )
        return [_map_sandbox_scenario(r) for r in rows]


def _chunk_meta_grouped(conn: Any, chunk_ids: list[str]) -> dict[str, dict[str, Any]]:
    ids = [c for c in chunk_ids if c and not str(c).startswith("faq-")]
    if not ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT c.id, c.heading, c.text, d.title AS doc_title
                FROM kb_chunks c
                JOIN kb_documents d ON d.id = c.document_id
                WHERE c.id = ANY(:ids)
                """
            ),
            {"ids": ids},
        )
    )
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        snippet = (r.get("text") or "")[:160]
        out[r["id"]] = {
            "chunkId": r["id"],
            "docTitle": r.get("doc_title") or "Document",
            "heading": r.get("heading") or "",
            "snippet": snippet,
        }
    return out


def _map_sandbox_turn(r: dict[str, Any], chunk_meta: dict[str, dict[str, Any]]) -> dict[str, Any]:
    speaker = str(r.get("speaker") or "bot")
    role = speaker if speaker in ("bot", "customer", "system") else "bot"
    raw_ids = r.get("retrieved_chunk_ids")
    if isinstance(raw_ids, str):
        try:
            raw_ids = json.loads(raw_ids)
        except json.JSONDecodeError:
            raw_ids = []
    if not isinstance(raw_ids, list):
        raw_ids = []
    chunk_ids = [str(x) for x in raw_ids if x]

    raw_flags = r.get("guardrail_flags")
    if isinstance(raw_flags, str):
        try:
            raw_flags = json.loads(raw_flags)
        except json.JSONDecodeError:
            raw_flags = []
    if not isinstance(raw_flags, list):
        raw_flags = []
    flags = [str(x) for x in raw_flags if x]

    grounded: list[dict[str, Any]] = []
    for cid in chunk_ids:
        meta = chunk_meta.get(cid)
        if meta:
            grounded.append(
                {
                    "chunkId": cid,
                    "docTitle": meta["docTitle"],
                    "heading": meta.get("heading") or "",
                    "snippet": meta.get("snippet") or "",
                }
            )
        else:
            grounded.append(
                {
                    "chunkId": cid,
                    "docTitle": cid,
                    "heading": "",
                    "snippet": "",
                }
            )

    created = r.get("created_at")
    if isinstance(created, datetime):
        ts_ms = int(created.timestamp() * 1000)
        created_iso = created.isoformat()
    elif isinstance(created, str):
        created_iso = created
        try:
            ts_ms = int(datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            ts_ms = 0
    else:
        created_iso = None
        ts_ms = 0

    sentiment_label = r.get("sentiment_label")
    sentiment_score: float | None = None
    if sentiment_label == "positive":
        sentiment_score = 0.4
    elif sentiment_label == "negative":
        sentiment_score = -0.4
    elif sentiment_label == "neutral":
        sentiment_score = 0.0

    system_kind = None
    if role == "system":
        text_l = str(r.get("text") or "").lower()
        if "halt" in text_l or "escalat" in text_l or "fail" in text_l:
            system_kind = "warn"
        elif "new session" in text_l:
            system_kind = "info"
        else:
            system_kind = "info"

    return {
        "id": r["id"],
        "turnIndex": int(r["turn_index"]),
        "role": role,
        "text": r.get("text") or "",
        "detectedIntent": r.get("detected_intent"),
        "intent": r.get("detected_intent"),
        "sentiment": sentiment_score,
        "sentimentLabel": sentiment_label,
        "chunkIds": chunk_ids,
        "retrievedChunkIds": chunk_ids,
        "groundedIn": grounded,
        "guardrailFlags": flags,
        "latencyMs": r.get("latency_ms"),
        "tokens": r.get("token_count"),
        "tokenCount": r.get("token_count"),
        "ts": ts_ms,
        "createdAt": created_iso,
        "systemKind": system_kind,
    }


def get_sandbox_run(run_id: str) -> dict[str, Any]:
    engine = _db().engine
    with engine.connect() as conn:
        r = _one(
            conn.execute(
                text(
                    """
                    SELECT
                      id, scenario_id, deployment_id, prompt_version_id, kb_snapshot_id,
                      started_by_user_id, status, aggregate_latency_ms, aggregate_tokens,
                      created_at, updated_at
                    FROM sandbox_runs
                    WHERE id = :id
                    """
                ),
                {"id": run_id},
            )
        )
        if r is None:
            raise KeyError(f"sandbox_run_not_found: {run_id}")

        turn_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT
                      id, run_id, turn_index, speaker, text,
                      detected_intent, sentiment_label, retrieved_chunk_ids,
                      guardrail_flags, latency_ms, token_count, created_at
                    FROM sandbox_run_turns
                    WHERE run_id = :id
                    ORDER BY turn_index ASC
                    """
                ),
                {"id": run_id},
            )
        )
        all_chunk_ids: list[str] = []
        for tr in turn_rows:
            raw_ids = tr.get("retrieved_chunk_ids")
            if isinstance(raw_ids, str):
                try:
                    raw_ids = json.loads(raw_ids)
                except json.JSONDecodeError:
                    raw_ids = []
            if isinstance(raw_ids, list):
                all_chunk_ids.extend(str(x) for x in raw_ids if x)
        chunk_meta = _chunk_meta_grouped(conn, all_chunk_ids)
        turns = [_map_sandbox_turn(tr, chunk_meta) for tr in turn_rows]

        created = r.get("created_at")
        updated = r.get("updated_at")
        return {
            "id": r["id"],
            "scenarioId": r.get("scenario_id"),
            "deploymentId": r.get("deployment_id"),
            "promptVersionId": r.get("prompt_version_id"),
            "kbSnapshotId": r.get("kb_snapshot_id"),
            "startedByUserId": r.get("started_by_user_id"),
            "status": r.get("status") or "running",
            "aggregateLatencyMs": r.get("aggregate_latency_ms"),
            "aggregateTokens": r.get("aggregate_tokens"),
            "createdAt": created.isoformat() if isinstance(created, datetime) else created,
            "updatedAt": updated.isoformat() if isinstance(updated, datetime) else updated,
            "turns": turns,
        }


