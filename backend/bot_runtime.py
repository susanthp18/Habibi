"""Channel-agnostic bot turn runtime (WhatsApp first; Sandbox/voice later).

Loads active bot_deployments (authoritative), runs Azure tool loop, applies
policy gates, persist-then-sends outbound WhatsApp.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

import azure_openai
import bot_jobs
import bot_tools
import db
import whatsapp as wa
from agent_core.deployment import load_active_bundle
from agent_core.intent import classify_intent, resolve_intent
from agent_core.prompt import build_system_prompt, default_context
from agent_core.sentiment import estimate_sentiment, sentiment_label
from prompt_render import render_prompt

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or str(default)).strip())
    except ValueError:
        return default


def _bot_id() -> str | None:
    return (os.getenv("BOT_ID") or "").strip() or None


def _history_limit() -> int:
    return max(4, _env_int("BOT_HISTORY_LIMIT", 16))


def _max_tool_iterations() -> int:
    return max(1, _env_int("BOT_MAX_TOOL_ITERATIONS", 6))


def _hard_max_turns() -> int:
    return max(1, _env_int("BOT_HARD_MAX_TURNS", 12))


def _load_conversation(engine: Engine, conversation_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        return conn.execute(
            text(
                """
                SELECT cv.id, cv.customer_id, cv.interaction_id, cv.status,
                       cv.assigned_user_id, cv.channel, cv.bot_state,
                       c.name AS customer_name, c.phone_primary, c.phone_alt,
                       c.dnd, c.preferred_window, c.language,
                       a.id AS account_id, a.outstanding, a.dpd, a.minimum_due,
                       p.name AS product,
                       (
                         SELECT MAX(COALESCE(m.sent_at, m.created_at))
                         FROM messages m
                         WHERE m.conversation_id = cv.id AND m.sender = 'customer'
                       ) AS last_customer_at
                FROM conversations cv
                JOIN customers c ON c.id = cv.customer_id
                LEFT JOIN LATERAL (
                  SELECT * FROM accounts a
                  WHERE a.customer_id = c.id
                  ORDER BY CASE WHEN a.id LIKE 'AC-%' THEN 0 ELSE 1 END, a.created_at, a.id
                  LIMIT 1
                ) a ON true
                LEFT JOIN products p ON p.id = a.product_id
                WHERE cv.id = :id
                """
            ),
            {"id": conversation_id},
        ).mappings().first()


def _whatsapp_opted_in(engine: Engine, customer_id: str) -> bool | None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT cc.status
                FROM consent_records cr
                JOIN channel_consents cc ON cc.consent_id = cr.id
                WHERE cr.customer_id = :cid
                  AND lower(cc.channel) IN ('whatsapp', 'wa')
                ORDER BY cc.captured_at DESC NULLS LAST
                LIMIT 1
                """
            ),
            {"cid": customer_id},
        ).mappings().first()
    if row is None:
        return None
    return (row.get("status") or "").lower() == "opted_in"


def _within_24h(last_customer_at: Any) -> bool:
    if last_customer_at is None:
        return False
    if isinstance(last_customer_at, str):
        last_customer_at = datetime.fromisoformat(last_customer_at.replace("Z", "+00:00"))
    if getattr(last_customer_at, "tzinfo", None) is None:
        last_customer_at = last_customer_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - last_customer_at.astimezone(timezone.utc)
    return age <= timedelta(hours=24)


def _policy_gate(engine: Engine, conv: dict[str, Any]) -> str | None:
    """Return abort reason or None if send is allowed."""
    if not bot_jobs.bot_runtime_enabled():
        return "bot_runtime_disabled"
    if conv.get("status") != "bot" or conv.get("assigned_user_id"):
        return "takeover_or_not_bot"
    if conv.get("channel") != "whatsapp":
        return "unsupported_channel"
    if conv.get("dnd"):
        return "customer_dnd"
    opted = _whatsapp_opted_in(engine, conv["customer_id"])
    if opted is False:
        return "whatsapp_opted_out"
    if not _within_24h(conv.get("last_customer_at")):
        return "whatsapp_window_closed"
    return None


def _latest_customer_text(engine: Engine, conversation_id: str) -> tuple[str, str | None]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, body FROM messages
                WHERE conversation_id = :cid AND sender = 'customer'
                ORDER BY COALESCE(sent_at, created_at) DESC, id DESC
                LIMIT 1
                """
            ),
            {"cid": conversation_id},
        ).mappings().first()
    if not row:
        return "", None
    return (row.get("body") or "").strip(), row.get("id")


def _message_history(engine: Engine, conversation_id: str, limit: int) -> list[dict[str, str]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT sender, body FROM messages
                WHERE conversation_id = :cid
                  AND sender IN ('customer', 'bot', 'agent')
                ORDER BY COALESCE(sent_at, created_at) ASC, id ASC
                """
            ),
            {"cid": conversation_id},
        ).mappings().all()
    history: list[dict[str, str]] = []
    for r in rows:
        body = (r.get("body") or "").strip()
        if not body:
            continue
        sender = r.get("sender")
        if sender == "customer":
            history.append({"role": "user", "content": body})
        else:
            history.append({"role": "assistant", "content": body})
    return history[-(limit):]


def _bot_state(conv: dict[str, Any]) -> dict[str, Any]:
    raw = conv.get("bot_state")
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _save_bot_state(engine: Engine, conversation_id: str, state: dict[str, Any]) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE conversations
                SET bot_state = CAST(:state AS jsonb), updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": conversation_id, "state": json.dumps(state)},
        )


def _existing_outbound(engine: Engine, job_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        return conn.execute(
            text(
                """
                SELECT id, delivery_status, provider_ref, body
                FROM messages
                WHERE bot_turn_job_id = :job_id
                LIMIT 1
                """
            ),
            {"job_id": job_id},
        ).mappings().first()


def _persist_outbound_sending(
    engine: Engine,
    *,
    conversation_id: str,
    job_id: str,
    body: str,
) -> str:
    msg_id = f"MSG-{uuid.uuid4().hex[:10].upper()}"
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO messages (
                  id, conversation_id, sender, body, delivery_status,
                  bot_turn_job_id, sent_at
                ) VALUES (
                  :id, :conversation_id, 'bot', :body, 'sending',
                  :bot_turn_job_id, :sent_at
                )
                """
            ),
            {
                "id": msg_id,
                "conversation_id": conversation_id,
                "body": body,
                "bot_turn_job_id": job_id,
                "sent_at": now,
            },
        )
        conn.execute(
            text(
                """
                UPDATE bot_turn_jobs
                SET outbound_message_id = :mid, updated_at = now()
                WHERE id = :job_id
                """
            ),
            {"mid": msg_id, "job_id": job_id},
        )
        conn.execute(
            text("UPDATE conversations SET updated_at = now() WHERE id = :id"),
            {"id": conversation_id},
        )
    return msg_id


def _finalize_outbound(
    engine: Engine,
    *,
    message_id: str,
    provider_ref: str | None,
    delivery_status: str,
    customer_id: str | None,
    conversation_id: str,
    body: str,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE messages
                SET provider_ref = COALESCE(:provider_ref, provider_ref),
                    delivery_status = :delivery_status
                WHERE id = :id
                """
            ),
            {
                "id": message_id,
                "provider_ref": provider_ref,
                "delivery_status": delivery_status,
            },
        )
        if delivery_status == "sent":
            db._activity(
                conn,
                "conversation",
                conversation_id,
                "bot_reply_sent",
                "Bot WhatsApp reply sent",
                body[:120],
                customer_id,
            )


def _build_messages(
    *,
    bundle: dict[str, Any],
    conv: dict[str, Any],
    history: list[dict[str, str]],
    customer_text: str,
    intent: str,
) -> list[dict[str, Any]]:
    ctx = default_context(
        {
            "customer_name": conv.get("customer_name") or "Customer",
            "account_no": conv.get("account_id") or "XXXX",
            "overdue_amount": str(conv.get("outstanding") or 0),
            "due_date": "",
            "last_payment": "",
            "language": conv.get("language") or "English",
        }
    )
    rendered = render_prompt(bundle.get("prompt") or "", ctx)
    system = build_system_prompt(
        rendered_prompt=rendered,
        persona=bundle.get("persona") or {},
        guardrails=bundle.get("guardrails") or {},
        context_blocks=[],
    )
    system += (
        "\n\n## Channel\n"
        "- You are replying on WhatsApp text (not voice). For money/collections turns keep "
        "replies short (1–4 sentences). For product / policy / exclusions questions, send "
        "the concrete details from KB (bullet list is fine; up to ~8–12 bullets).\n"
        "- Money facts MUST come from CRM tools (get_customer_context / get_emi_schedule / "
        "get_payment_history). Never invent balances or dues.\n"
        "- search_knowledge_base is only for product/insurance FAQ; it is blocked for "
        "collections intents. Always call it for exclusions, invalidation, coverage, or "
        "\"tell me all / full details\" follow-ups on a product thread.\n"
        "- For upsell/cross-sell interest: check_product_eligibility then capture_lead "
        "(do not invent bureau/KYC passes — unknown is OK). Prefer after the primary "
        "collections question is handled and sentiment is not negative.\n"
        "- If the caller identity is unclear, call identify_customer with phone digits "
        "or account last-4 before money or lead tools.\n"
        "- You cannot collect payments. Offer guidance and PTP / callback / escalate when needed.\n"
        f"- Prefer facts from CRM tools for money and from search_knowledge_base for "
        f"product / policy / exclusions. When KB returns policy chunks, use those snippets: "
        f"list the actual exclusion / invalidation conditions. Never say you cannot access "
        f"policy wording if snippets are present. Prefer Travel/product-matching docs over "
        f"unrelated products.\n"
        f"- Classified intent for this turn: {intent}.\n"
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    # History already includes the latest customer turn when taken from DB;
    # still append customer_text if history is empty.
    if history:
        messages.extend(history)
    else:
        messages.append({"role": "user", "content": customer_text})
    return messages


def handle_turn(engine: Engine, job: dict[str, Any]) -> None:
    job_id = job["id"]
    conversation_id = job["conversation_id"]
    logger.info("bot_turn start job=%s conversation=%s attempt=%s", job_id, conversation_id, job.get("attempt"))

    # Outbound idempotency: never Graph-send twice for the same job.
    existing = _existing_outbound(engine, job_id)
    if existing and (existing.get("delivery_status") or "") == "sent":
        with engine.begin() as conn:
            bot_jobs.mark_succeeded(conn, job_id, outbound_message_id=existing["id"])
        logger.info("bot_turn skip already-sent job=%s message=%s", job_id, existing["id"])
        return

    reuse_outbound_id: str | None = None
    reuse_body: str | None = None
    if existing and (existing.get("delivery_status") or "") in {"sending", "failed"}:
        # Prior attempt reserved a row but Graph never confirmed sent — reuse it
        # (do not INSERT another row; UNIQUE(bot_turn_job_id) would fail).
        reuse_outbound_id = existing["id"]
        reuse_body = (existing.get("body") or "").strip() or None
        logger.info(
            "bot_turn retrying outbound job=%s message=%s prior_status=%s",
            job_id,
            reuse_outbound_id,
            existing.get("delivery_status"),
        )

    conv = _load_conversation(engine, conversation_id)
    if not conv:
        with engine.begin() as conn:
            bot_jobs.mark_cancelled(conn, job_id, "conversation_not_found")
        return

    gate = _policy_gate(engine, conv)
    if gate:
        with engine.begin() as conn:
            bot_jobs.mark_cancelled(conn, job_id, gate)
        logger.info("bot_turn cancelled job=%s reason=%s", job_id, gate)
        return

    customer_text, latest_msg_id = _latest_customer_text(engine, conversation_id)
    if not customer_text:
        with engine.begin() as conn:
            bot_jobs.mark_cancelled(conn, job_id, "no_customer_text")
        return

    # Stale reuse: a newer customer message arrived after this job reserved outbound.
    # Regenerate against latest text (still reuse the message row id).
    if reuse_body and latest_msg_id and latest_msg_id != job.get("trigger_message_id"):
        logger.info(
            "bot_turn stale outbound body job=%s trigger=%s latest=%s — regenerating",
            job_id,
            job.get("trigger_message_id"),
            latest_msg_id,
        )
        reuse_body = None

    state = _bot_state(conv)
    turn_count = int(state.get("turn_count") or 0) + 1
    guardrails = {}
    try:
        bundle = load_active_bundle(
            bot_jobs.bot_environment(),
            bot_id=_bot_id(),
            fallback_environments=("sandbox", "production"),
        )
        guardrails = bundle.get("guardrails") or {}
    except KeyError as exc:
        with engine.begin() as conn:
            bot_jobs.mark_failed_or_retry(conn, job, f"deployment:{exc}")
        return

    # Persist live sentiment for Inbox (even when we escalate before Azure).
    if conv.get("interaction_id"):
        with engine.begin() as conn:
            db._touch_interaction_sentiment(conn, conv.get("interaction_id"), customer_text)

    intent, intent_scores = resolve_intent(
        customer_text,
        prior_intent=str(state.get("last_intent") or "") or None,
    )
    sentiment = estimate_sentiment(customer_text)

    # Phase 0: persist intent onto the linked interaction (bot_worker path — not webhook).
    if conv.get("interaction_id") and intent:
        try:
            import capture

            with engine.begin() as conn:
                capture.touch_primary_intent(conn, conv.get("interaction_id"), intent)
                if intent in {"payment_intent", "balance_query"}:
                    capture.mark_interaction_flags(
                        conn, conv.get("interaction_id"), query_resolved=True
                    )
                if intent in capture.PRODUCT_INTENTS:
                    capture.record_product_interest(
                        conn,
                        interaction_id=conv["interaction_id"],
                        intent=intent,
                        snippet=customer_text[:240],
                        actor_bot_id=_bot_id(),
                    )
        except Exception:
            logger.exception("capture touch_primary_intent failed")

    # Infer product hint from recent customer turns for vague follow-ups.
    product_hint = None
    recent_cust = []
    with engine.connect() as conn:
        recent_cust = [
            (r.get("body") or "").strip()
            for r in conn.execute(
                text(
                    """
                    SELECT body FROM messages
                    WHERE conversation_id = :cid AND sender = 'customer'
                    ORDER BY COALESCE(sent_at, created_at) DESC
                    LIMIT 4
                    """
                ),
                {"cid": conversation_id},
            ).mappings().all()
        ]
    blob = " ".join(recent_cust).lower()
    for token in (
        "travel protect360",
        "travel insurance",
        "car protect",
        "life protect",
        "family protect",
        "maid protect",
        "fraud protect",
        "choice protect",
    ):
        if token in blob:
            product_hint = token.title()
            break
    if not product_hint and "travel" in blob:
        product_hint = "Travel Protect360"

    # Hard escalate on abuse / human-request before spending Azure.
    from agent_core.guardrails import evaluate_guardrails

    cust_l = customer_text.lower()
    hard_abuse = any(
        w in cust_l
        for w in ("stfu", "fuck", "idiot", "stupid", "shut up", "asshole", "bastard", "kill yourself")
    )
    early_flags = evaluate_guardrails(
        customer_text=customer_text,
        bot_text="",
        intent=intent,
        guardrails=guardrails if isinstance(guardrails, dict) else {},
        turn_index=turn_count,
        elapsed_seconds=0,
        customer_bot_exchanges=turn_count,
    )
    if hard_abuse or "auto-escalate" in early_flags or intent == "escalation":
        if hard_abuse:
            reason = "Customer used abusive language — escalated to human"
        elif intent == "escalation":
            reason = "Customer requested a human agent"
        else:
            reason = "Guardrail auto-escalate"
        db.escalate_conversation_to_human(conversation_id, reason=reason)
        state.update(
            {
                "turn_count": turn_count,
                "last_intent": intent,
                "last_sentiment": sentiment_label(sentiment),
                "escalated": True,
                "escalate_reason": reason,
            }
        )
        _save_bot_state(engine, conversation_id, state)
        with engine.begin() as conn:
            bot_jobs.mark_succeeded(conn, job_id)
        logger.info("bot_turn early-escalate job=%s reason=%s", job_id, reason)
        return

    max_turns = int(guardrails.get("maxTurns") or _hard_max_turns())
    max_turns = min(max_turns, _hard_max_turns())
    if turn_count > max_turns:
        db.escalate_conversation_to_human(conversation_id, reason="max_turns_exceeded")
        with engine.begin() as conn:
            bot_jobs.mark_cancelled(conn, job_id, "max_turns_exceeded")
        return

    final_text = ""
    if reuse_body:
        final_text = reuse_body
    else:
        history = _message_history(engine, conversation_id, _history_limit())
        messages = _build_messages(
            bundle=bundle,
            conv=conv,
            history=history,
            customer_text=customer_text,
            intent=intent,
        )

        tool_ctx = bot_tools.ToolContext(
            job_id=job_id,
            conversation_id=conversation_id,
            customer_id=conv["customer_id"],
            interaction_id=conv.get("interaction_id") or job.get("interaction_id"),
            bot_id=_bot_id(),
            customer_text=customer_text,
            intent=intent,
            session_intent=str(state.get("last_intent") or "") or None,
            product_hint=product_hint,
        )

        tool_failures = 0
        for _ in range(_max_tool_iterations()):
            # Re-check take-over race before each Azure call.
            fresh = _load_conversation(engine, conversation_id)
            if not fresh or fresh.get("status") != "bot" or fresh.get("assigned_user_id"):
                with engine.begin() as conn:
                    bot_jobs.mark_cancelled(conn, job_id, "takeover_mid_flight")
                return

            result = azure_openai.chat_with_tools(
                messages,
                tools=bot_tools.TOOL_DEFINITIONS,
                temperature=0.2,
                max_completion_tokens=500,
            )
            tool_calls = result.get("toolCalls") or []
            if not tool_calls:
                final_text = (result.get("content") or "").strip()
                break

            raw_msg = result.get("rawMessage") or {
                "role": "assistant",
                "content": result.get("content"),
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in tool_calls
                ],
            }
            messages.append(raw_msg)

            for tc in tool_calls:
                ok, payload, latency_ms = bot_tools.execute_tool(tool_ctx, tc["name"], tc["arguments"])
                preview = json.dumps(payload)[:1500]
                try:
                    parsed_args = json.loads(tc["arguments"] or "{}")
                    if not isinstance(parsed_args, dict):
                        parsed_args = {"_raw": tc["arguments"]}
                except json.JSONDecodeError:
                    parsed_args = {"_raw": tc["arguments"]}
                with engine.begin() as conn:
                    bot_jobs.record_tool_call(
                        conn,
                        job_id=job_id,
                        conversation_id=conversation_id,
                        tool_name=tc["name"],
                        args=parsed_args,
                        result_ok=ok,
                        error=None if ok else str(payload.get("error") or payload),
                        result_preview=preview,
                        latency_ms=latency_ms,
                    )
                if not ok:
                    tool_failures += 1
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(payload),
                    }
                )
                if tool_ctx.escalated:
                    with engine.begin() as conn:
                        bot_jobs.mark_succeeded(conn, job_id)
                    state.update(
                        {
                            "turn_count": turn_count,
                            "last_intent": intent,
                            "last_sentiment": sentiment_label(sentiment),
                            "escalated": True,
                            "escalate_reason": tool_ctx.escalate_reason,
                        }
                    )
                    _save_bot_state(engine, conversation_id, state)
                    logger.info("bot_turn escalated job=%s reason=%s", job_id, tool_ctx.escalate_reason)
                    return

            if tool_failures >= 3:
                db.escalate_conversation_to_human(conversation_id, reason="repeated_tool_failure")
                with engine.begin() as conn:
                    bot_jobs.mark_cancelled(conn, job_id, "repeated_tool_failure")
                return
        else:
            # Hit iteration ceiling without a final text — escalate rather than silence.
            if not final_text:
                db.escalate_conversation_to_human(conversation_id, reason="tool_loop_exhausted")
                with engine.begin() as conn:
                    bot_jobs.mark_cancelled(conn, job_id, "tool_loop_exhausted")
                return

        if not final_text:
            final_text = (
                "Thanks for your message. I've noted it and a specialist will follow up shortly."
            )

    # Final take-over race check immediately before persist/send.
    fresh = _load_conversation(engine, conversation_id)
    gate = _policy_gate(engine, fresh) if fresh else "conversation_missing"
    if gate:
        with engine.begin() as conn:
            bot_jobs.mark_cancelled(conn, job_id, gate)
        return

    if reuse_outbound_id:
        msg_id = reuse_outbound_id
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE messages
                    SET body = :body,
                        delivery_status = 'sending',
                        provider_ref = NULL,
                        sent_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": msg_id, "body": final_text},
            )
    else:
        msg_id = _persist_outbound_sending(
            engine,
            conversation_id=conversation_id,
            job_id=job_id,
            body=final_text,
        )

    to_phone = wa.normalize_phone(fresh.get("phone_primary")) or wa.normalize_phone(fresh.get("phone_alt"))
    try:
        send_resp = wa.send_text_message(to_phone=to_phone, body=final_text)
        provider_ref = wa.extract_wamid(send_resp)
        _finalize_outbound(
            engine,
            message_id=msg_id,
            provider_ref=provider_ref,
            delivery_status="sent",
            customer_id=fresh.get("customer_id"),
            conversation_id=conversation_id,
            body=final_text,
        )
    except Exception as exc:
        _finalize_outbound(
            engine,
            message_id=msg_id,
            provider_ref=None,
            delivery_status="failed",
            customer_id=fresh.get("customer_id"),
            conversation_id=conversation_id,
            body=final_text,
        )
        raise RuntimeError(f"whatsapp_send_failed:{exc}") from exc

    state.update(
        {
            "turn_count": turn_count,
            "last_intent": intent,
            "last_intent_scores": intent_scores,
            "last_sentiment": sentiment_label(sentiment),
            "last_trigger_message_id": latest_msg_id,
            "last_outbound_message_id": msg_id,
        }
    )
    _save_bot_state(engine, conversation_id, state)

    # Phase 1 gap-fix: WhatsApp previously never wrote interaction_transcript,
    # so rollup/upsell flags could not work like voice. Persist both turns here
    # (bot_worker path — never on the webhook request).
    ix = conv.get("interaction_id") or fresh.get("interaction_id")
    if ix:
        try:
            import capture
            from voice import persist as voice_persist

            with engine.begin() as conn:
                t_idx = capture.next_transcript_turn_index(conn, ix)
            top_score = float(intent_scores.get(intent) or 0.0) if intent_scores else None
            voice_persist.append_transcript_turn(
                interaction_id=ix,
                turn_index=t_idx,
                speaker="customer",
                text_content=customer_text,
                at_sec=0,
                sentiment_delta=float(sentiment) if sentiment is not None else None,
                intent=intent,
                intent_score=top_score,
            )
            voice_persist.append_transcript_turn(
                interaction_id=ix,
                turn_index=t_idx + 1,
                speaker="bot",
                text_content=final_text,
                at_sec=0,
            )
            with engine.begin() as conn:
                capture.rollup_interaction(conn, ix, channel_hint="whatsapp", force_summary=False)
        except Exception:
            logger.exception("whatsapp transcript/rollup capture failed job=%s", job_id)

    with engine.begin() as conn:
        bot_jobs.mark_succeeded(conn, job_id, outbound_message_id=msg_id)
    logger.info("bot_turn succeeded job=%s message=%s", job_id, msg_id)
