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

_SANDBOX_TOOL_NAMES = (
    "get_customer_context",
    "get_payment_history",
    "get_emi_schedule",
    "search_knowledge_base",
    "create_promise_to_pay",
    "flag_dispute",
    "evaluate_authority",
    "apply_goodwill",
    "request_callback",
    "check_product_eligibility",
    "capture_lead",
    "request_documents",
    "load_skill",
    "run_skill_script",
)
_SANDBOX_MAX_TOOL_ITERS = 4
# Ceiling on a single tool result as handed back to the model. Generous enough
# for a full KB passage, bounded so one wide result cannot dominate the context
# for the rest of the loop.
_SANDBOX_MAX_TOOL_RESULT_CHARS = 4000


def _sandbox_tools_enabled(payload: dict[str, Any], context: dict[str, Any] | None) -> bool:
    if payload.get("enableTools") is False:
        return False
    if payload.get("enableTools") is True:
        return True
    flag = (os.getenv("SANDBOX_TEXT_TOOLS") or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    # Auto-enable when a CRM customer is pinned on the run context.
    ctx = context or {}
    return bool(ctx.get("customerId") or ctx.get("customer_id"))


def _run_sandbox_tool_loop(
    *,
    messages: list[dict[str, Any]],
    customer_text: str,
    intent: str,
    customer_id: str,
    run_id: str,
    temperature: float,
    max_tokens: int,
    agent_card: dict[str, Any] | None = None,
) -> tuple[str, int, int, list[dict[str, Any]]]:
    """Shared catalog tools under a max-iteration budget (unification Phase D)."""
    from agent_core.skills.runtime import mouth_turn_state
    from agent_core.tools.catalog import CATALOG
    from bot_tools import ToolContext, execute_tool

    skill_state = mouth_turn_state(agent_card or {}, intent=intent)
    offered = skill_state["offered"]
    tools = CATALOG.openai_tools(list(offered) if offered is not None else list(_SANDBOX_TOOL_NAMES))
    ctx = ToolContext(
        job_id=f"sandbox-{run_id}",
        conversation_id=f"sandbox-{run_id}",
        customer_id=customer_id,
        interaction_id=None,
        bot_id=db.DEFAULT_BOT_ID,
        customer_text=customer_text,
        intent=intent or "general",
    )
    ctx.allowed_tools = skill_state["allowed"]
    ctx.attached_skills = skill_state["packs"]
    ctx.active_skill = skill_state["active_slug"]
    working = list(messages)
    tool_trace: list[dict[str, Any]] = []
    total_tokens = 0
    total_latency = 0
    bot_text = ""

    tools_pending = False
    for _ in range(_SANDBOX_MAX_TOOL_ITERS):
        tools_pending = False
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
                ok, result, tool_ms = execute_tool(ctx, name, args_json)
                # Tool round-trips are real turn latency — dropping them made
                # sandbox latencyMs understate what a live caller experiences.
                total_latency += int(tool_ms or 0)
            except Exception as exc:
                logger.exception("sandbox tool %s failed", name)
                ok = False
                result = {"error": f"tool_failed:{type(exc).__name__}"}
            # Serialize once, and bound what goes into the prompt. An unbounded
            # tool result (a wide KB hit, a long payment history) was appended
            # verbatim and then re-sent on every subsequent loop iteration, so
            # the tokens compounded per iteration.
            serialized = json.dumps(result if isinstance(result, dict) else {"result": result})
            if len(serialized) > _SANDBOX_MAX_TOOL_RESULT_CHARS:
                serialized = (
                    serialized[:_SANDBOX_MAX_TOOL_RESULT_CHARS] + "…[truncated]"
                )
            # The Inspector keeps the structured result; only the model-visible
            # copy is bounded (the response shape is part of the sandbox API).
            tool_trace.append({"name": name, "ok": ok, "result": result})
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
        # back to the model: the tools really ran (a promise row was written),
        # yet the reply was whatever the model said *before* them — or the
        # generic fallback. One tool-free completion turns the results into the
        # answer the customer is owed.
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
    return bot_text, total_latency, max(1, total_tokens), tool_trace

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
    # Cheap fail-fast so we don't pay for an LLM call on an already-capped run.
    # The authoritative check runs under the row lock in the persist transaction.
    if prior_customers >= effective_max:
        raise ValueError(f"sandbox_max_turns:{effective_max}")

    persona = version["persona"] if isinstance(version.get("persona"), dict) else {}
    from agent_core.skills.runtime import mouth_turn_state

    skill_slug = str(payload.get("skillSlug") or payload.get("skill_slug") or "").strip() or None
    skill_state = mouth_turn_state(version.get("agentCard") or {}, active_slug=skill_slug)
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

    prior_summary = None
    interaction_id = str(payload.get("interactionId") or payload.get("interaction_id") or "").strip() or None
    if interaction_id:
        try:
            row = db.get_latest_context_summary(interaction_id)
            prior_summary = (row or {}).get("summary")
        except Exception:
            prior_summary = None
    assembled = assemble_turn_messages(
        prompt_template=version["prompt"],
        persona=persona,
        guardrails=guardrails,
        customer_text=customer_text,
        context=payload.get("context") if isinstance(payload.get("context"), dict) else None,
        history=history,
        context_blocks=context_blocks,
        prior_summary=prior_summary,
        skill_catalog=skill_state["prefix"],
        active_skill_message=None,
    )
    messages = assembled["messages"]
    intent = assembled["intent"]
    skill_state = mouth_turn_state(
        version.get("agentCard") or {},
        intent=str(intent or ""),
        active_slug=skill_slug,
    )
    if skill_state["body_message"]:
        messages.insert(min(2, len(messages)), skill_state["body_message"])
    intent_scores = assembled["intent_scores"]
    sentiment = assembled["sentiment"]
    sent_label = assembled["sentiment_label"]

    t0 = time.perf_counter()
    tool_trace: list[dict[str, Any]] = []
    turn_context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    customer_id = str(
        turn_context.get("customerId")
        or turn_context.get("customer_id")
        or (payload.get("customerId") or "")
    ).strip()
    from agent_core.telemetry import span as _span

    try:
        with _span("gen_ai.invoke_agent", gen_ai_operation_name="invoke_agent", gen_ai_agent_name="sandbox"):
            if _sandbox_tools_enabled(payload, turn_context) and customer_id:
                bot_text, chat_latency, tokens, tool_trace = _run_sandbox_tool_loop(
                    messages=messages,
                    customer_text=customer_text,
                    intent=str(intent or "general"),
                    customer_id=customer_id,
                    run_id=run_id,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    agent_card=version.get("agentCard") if isinstance(version.get("agentCard"), dict) else None,
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
            raise ValueError(f"sandbox_max_turns:{effective_max}")
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
            "toolCalls": tool_trace,
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
