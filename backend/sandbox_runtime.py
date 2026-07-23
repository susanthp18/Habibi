"""Call Sandbox runtime — prompt version + KB retrieve + Azure chat (PS-3).

bot_deployments is authoritative for the default "live" prompt when the client
does not pass an explicit prompt_version_id. Guardrail violations halt the run.

Shared brain (intent / sentiment / prompt / guardrails / turn assembly) lives in
agent_core — this module owns sandbox_runs persistence only.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
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
    sentiment_label,
    should_halt,
)
from prompt_render import render_prompt

logger = logging.getLogger(__name__)

# Absolute ceiling on customer→bot exchanges per run (cost control).
_HARD_MAX_TURNS = max(1, int(os.getenv("SANDBOX_HARD_MAX_TURNS", "3")))

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


def _real_chunk_ids(results: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for r in results:
        cid = str(r.get("chunkId") or "")
        if not cid or cid.startswith("faq-"):
            continue
        if cid not in out:
            out.append(cid)
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
                        INSERT INTO sandbox_scenarios (id, name, sim_persona, turns)
                        VALUES (:id, :name, CAST(:persona AS jsonb), CAST(:turns AS jsonb))
                        ON CONFLICT (id) DO NOTHING
                        """
                    ),
                    {
                        "id": scenario_id,
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
    }


def append_sandbox_turn(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Customer utterance → retrieve → chat → persist customer + bot turns."""
    customer_text = (payload.get("text") or "").strip()
    if not customer_text:
        raise ValueError("text must not be empty")

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

    guardrails = version["guardrails"] if isinstance(version.get("guardrails"), dict) else {}
    max_turns = int(guardrails.get("maxTurns") or 0)
    effective_max = min(_HARD_MAX_TURNS, max_turns) if max_turns else _HARD_MAX_TURNS
    if prior_customers >= effective_max:
        raise ValueError(f"sandbox_max_turns:{effective_max}")

    persona = version["persona"] if isinstance(version.get("persona"), dict) else {}
    # Server-authoritative history — prefer DB turns over client payload.
    history: list[dict[str, Any]] = []
    with db.engine.connect() as hist_conn:
        hist_rows = hist_conn.execute(
            text(
                """
                SELECT speaker, text
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
                history.append({"role": role, "text": hr["text"]})
    if not history:
        history = payload.get("history") if isinstance(payload.get("history"), list) else []

    kb_snapshot_id = run.get("kb_snapshot_id")
    tuning = version.get("tuning") if isinstance(version.get("tuning"), dict) else {}
    from agent_core.tuning import normalize_tuning

    llm_tuning = normalize_tuning(tuning).get("llm") or {}
    temperature = float(
        llm_tuning.get("temperature") if llm_tuning.get("temperature") is not None else CHAT_TEMPERATURE
    )
    max_tokens = int(llm_tuning.get("max_completion_tokens") or 320)

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

    results = list(retrieval.get("results") or [])
    context_blocks = context_blocks_from_results(results)
    chunk_ids = _real_chunk_ids(results)
    # Prefer real kb_chunks for chips; fall back to FAQ hits so RAG is still visible.
    chip_results = [r for r in results if r.get("chunkId") in set(chunk_ids)]
    if not chip_results:
        chip_results = results[:3]

    assembled = assemble_turn_messages(
        prompt_template=version["prompt"],
        persona=persona,
        guardrails=guardrails,
        customer_text=customer_text,
        context=payload.get("context") if isinstance(payload.get("context"), dict) else None,
        history=history,
        context_blocks=context_blocks,
    )
    messages = assembled["messages"]
    intent = assembled["intent"]
    intent_scores = assembled["intent_scores"]
    sentiment = assembled["sentiment"]
    sent_label = assembled["sentiment_label"]

    t0 = time.perf_counter()
    try:
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

    customer_turn_index = int(turn_count)
    bot_turn_index = customer_turn_index + 1
    exchange_n = prior_customers + 1
    flags = evaluate_guardrails(
        customer_text=customer_text,
        bot_text=bot_text,
        intent=intent,
        guardrails=guardrails,
        turn_index=bot_turn_index,
        elapsed_seconds=elapsed_seconds,
        customer_bot_exchanges=exchange_n,
        hard_max_turns=_HARD_MAX_TURNS,
    )
    halted = should_halt(flags)

    customer_turn_id = f"{run_id}-T{customer_turn_index}"
    bot_turn_id = f"{run_id}-T{bot_turn_index}"

    with db.engine.begin() as conn:
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
                "lat": int(run["aggregate_latency_ms"] or 0) + latency_ms,
                "tok": int(run["aggregate_tokens"] or 0) + tokens,
            },
        )

    return {
        "runId": run_id,
        "promptVersionId": version["id"],
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
                for r in (chip_results or results)
            ],
            "latencyMs": latency_ms,
            "tokens": tokens,
            "guardrailFlags": flags,
            "intent": intent,
            "sentiment": sentiment,
            "sentimentLabel": sent_label,
            "retrievalLogId": retrieval.get("logId"),
            "retrieveLatencyMs": retrieve_latency,
            "chatLatencyMs": chat_latency,
            "halted": halted,
        },
    }


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
