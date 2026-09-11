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
from agent_core import lexicon
from agent_core import perception
from agent_core.deployment import load_active_bundle
from agent_core.prompt import build_system_prompt, default_context
from agent_core.sentiment import sentiment_label
from agent_core.understanding import analyze_turn
from prompt_render import (
    format_untrusted_crm_card,
    render_system_prompt,
    strip_unrendered_crm_tokens,
)

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or str(default)).strip())
    except ValueError:
        return default


def _bot_id() -> str | None:
    """Which card answers a text thread.

    Returns ``None`` when nothing is configured, exactly as it always has:
    several call sites below pass this straight through and treat ``None`` as
    "no card", falling back themselves. ``resolve_entry`` never returns None --
    it ends at ``db.DEFAULT_BOT_ID`` -- so it is consulted only when the flag is
    on, and with ``DOOR_ENABLED`` unset this function is byte-for-byte what it
    was.

    The channel default is the row the text mouths reach: there is no address to
    match on, which is why ``entry_bindings`` carries ``address IS NULL`` rows
    rather than WhatsApp growing a second mechanism.
    """
    from agent_core.cards.routing import door_enabled, resolve_entry

    if door_enabled():
        return resolve_entry("whatsapp")
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
                         WHERE m.conversation_id = cv.id
                           AND m.sender = 'customer'
                           AND m.provider_ref IS NOT NULL
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
    try:
        import contact_policy

        with engine.begin() as conn:
            decision = contact_policy.admit(
                conn,
                customer_id=conv.get("customer_id"),
                channel="whatsapp",
                purpose="in_session",
                session_key=conv.get("id"),
                source="bot_reply",
                related_id=conv.get("id"),
                actor_kind="bot",
                endpoint=conv.get("phone_primary"),
            )
        if not decision.allowed:
            return decision.reason or "contact_policy"
    except Exception:
        logger.exception("contact_policy bot gate failed conversation=%s", conv.get("id"))
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


def _message_sent_at(conn: Any, message_id: str | None) -> datetime | None:
    """When a message actually landed — for stamping its transcript offset."""
    if not message_id:
        return None
    row = conn.execute(
        text("SELECT COALESCE(sent_at, created_at) AS at FROM messages WHERE id = :id"),
        {"id": message_id},
    ).first()
    return row[0] if row else None


def _message_history(
    engine: Engine,
    conversation_id: str,
    limit: int,
    *,
    since: datetime | None = None,
) -> list[dict[str, str]]:
    with engine.connect() as conn:
        # Fetch only the newest `limit` rows (avoids loading the whole thread each
        # turn — O(n²) over a long WhatsApp conversation), then restore chrono order.
        if since is not None:
            rows = conn.execute(
                text(
                    """
                    SELECT sender, body FROM messages
                    WHERE conversation_id = :cid
                      AND sender IN ('customer', 'bot', 'agent')
                      AND COALESCE(sent_at, created_at) >= :since
                    ORDER BY COALESCE(sent_at, created_at) DESC, id DESC
                    LIMIT :limit
                    """
                ),
                {"cid": conversation_id, "limit": limit, "since": since},
            ).mappings().all()
        else:
            rows = conn.execute(
                text(
                    """
                    SELECT sender, body FROM messages
                    WHERE conversation_id = :cid
                      AND sender IN ('customer', 'bot', 'agent')
                    ORDER BY COALESCE(sent_at, created_at) DESC, id DESC
                    LIMIT :limit
                    """
                ),
                {"cid": conversation_id, "limit": limit},
            ).mappings().all()
    rows = list(reversed(rows))
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


def _parse_dialog_reset_at(state: dict[str, Any]) -> datetime | None:
    raw = state.get("dialog_reset_at")
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _history_already_disclosed_recording(history: list[dict[str, str]]) -> bool:
    markers = ("recorded for quality", "call is recorded", "whatsapp is recorded", "recorded for compliance")
    for turn in history:
        if turn.get("role") != "assistant":
            continue
        body = (turn.get("content") or "").lower()
        if any(m in body for m in markers):
            return True
    return False


def _dialog_control_block(*, intent: str, customer_text: str, disclosed_recording: bool) -> str:
    """Per-turn dialog rules so stale EMI/PTP history cannot override the latest ask."""
    lines = [
        "## Dialog control (this turn — highest priority)",
        f"- Classified intent: {intent}.",
        f"- Latest customer message: {customer_text!r}",
        "- Answer ONLY that latest message. Older EMI / Promise-to-Pay / outstanding talk in "
        "history is background — do not treat it as what the customer asked now.",
        "- Never invent that the customer asked about EMI, PTP, dues, or WhatsApp confirmation "
        "windows when the latest message did not.",
    ]
    if disclosed_recording:
        lines.append(
            "- Recording disclosure was already given in this session — do not repeat it."
        )
    if intent == "greeting":
        lines.append(
            "- Greeting: reply with a short hello and one line on how you can help "
            "(account dues / PTP, payment guidance, insurance product FAQs, or connect to a human). "
            "Do NOT recite outstanding balance or push a PTP date."
        )
    elif intent in {"help_capabilities", "correction"}:
        lines.append(
            "- Help / correction: if correcting, apologize in one short clause, then list what you "
            "can help with (check dues & set a Promise-to-Pay, payment guidance, insurance product "
            "questions like coverage/exclusions, escalate to a human). Ask what they need next. "
            "Do NOT reopen PTP dates or WhatsApp confirmation slots unless they ask about payment."
        )
    elif intent == "product_faq":
        lines.append(
            "- Product FAQ: use search_knowledge_base and answer the product question. "
            "Do not pivot to EMI/PTP unless they also ask about the loan."
        )
    if _looks_like_closing(customer_text):
        # The text-channel equivalent of the voice close probe. ONE question,
        # asked once. W12 removed its offer half: §9.7 forbids a promotional
        # utterance inside a servicing conversation, so the engine is still
        # asked -- the decision row is what the offer corpus has never had --
        # and the answer is never spoken.
        lines.append(
            "- They are wrapping up: close warmly and ask ONE short question about "
            "whether there is anything else you can help with. Do not list options. "
            "Do not mention any product, offer, top-up or upgrade, whatever any tool "
            "returns. Never ask twice."
        )
    return "\n".join(lines)


# Short sign-offs that mean the customer considers the thread finished.
_CLOSING_PHRASES = (
    "that's all",
    "thats all",
    "that is all",
    "nothing else",
    "no thanks",
    "no thank you",
    "thanks a lot",
    "thank you so much",
    "ok thanks",
    "okay thanks",
    "got it thanks",
    "bye",
    "goodbye",
    "good night",
    "that's it",
    "thats it",
    "all good",
    "we are done",
    "we're done",
)


def _looks_like_closing(text: str) -> bool:
    """Is the customer signing off?

    Conservative on purpose: a false negative costs one un-asked question, a
    false positive tries to close a conversation that is still going.
    """
    t = " ".join((text or "").lower().split()).strip(".,!? ")
    if not t:
        return False
    if any(p in t for p in _CLOSING_PHRASES):
        return True
    return t in {"thanks", "thank you", "ty", "cool", "great"}


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


def _hop_to(
    walker: Any,
    tool_ctx: Any,
    tool_call: dict[str, Any],
    payload: Any,
    entries: dict[str, str],
) -> None:
    """Move the text cursor onto the member a successful handoff named.

    A handoff is not an edge in the graph — the card's allowlist is the edge —
    so ``walker.advance`` has nothing to follow and the cursor would stay in the
    sending member's subgraph, which is exactly the bug this closes on voice.

    Best-effort by design: a hop whose target has no compiled entry is still
    recorded and still announced, it simply does not swap the tools. Raising
    here would turn a degraded handoff into a dead conversation.
    """
    target = ""
    if isinstance(payload, dict):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        target = str(data.get("targetBotId") or data.get("target_bot_id") or "")
    if not target:
        try:
            target = str((json.loads(tool_call.get("arguments") or "{}") or {}).get("target_bot_id") or "")
        except json.JSONDecodeError:
            target = ""
    if not target:
        return
    from agent_core.cards import routing

    edge = routing.handoff_edge(getattr(tool_ctx, "agent_card", None) or {}, target)
    entry = str(edge.get("entry_node") or "").strip() or entries.get(target, "")
    node = walker.node(entry) if entry else None
    if node is None:
        logger.info("text handoff to %s: no entry node %r in the graph", target, entry)
        return
    walker.move_to(node)


def _flow_walker(bundle: dict[str, Any], state: dict[str, Any]) -> Any | None:
    """A walker over the deployment's authored graph, resumed from ``bot_state``.

    Returns None when the card authors no flow, or when the flow will not parse
    — a thread must keep answering either way. A graph the compiler passed and
    this runtime cannot walk is logged rather than swallowed, because that gap
    is the thing worth knowing about.
    """
    flow = bundle.get("flow")
    if not isinstance(flow, dict) or not flow:
        return None
    try:
        from flow_graph import parse_graph
        from flow_vars import FlowVariables
        from flow_walk import FlowWalker

        walker = FlowWalker(parse_graph(flow), FlowVariables({}))
        resume = str(state.get("flow_node") or "").strip()
        if resume:
            node = walker.node(resume)
            if node is None:
                logger.warning("bot_turn: unknown flow_node %r — restarting the graph", resume)
            else:
                walker.move_to(node)
        return walker
    except Exception:
        logger.exception("bot_turn: authored flow will not parse — answering prompt-only")
        return None


def _is_graph_tool(name: str) -> bool:
    import flow_walk

    return name.startswith(flow_walk.TRANSITION_PREFIX) or name == flow_walk.EXTRACT_TOOL


def _walk_graph_tool(walker: Any, name: str, arguments: Any) -> tuple[bool, dict[str, Any]]:
    """Apply a generated tool to the walker. Never touches the tool registry."""
    import flow_walk

    if name == flow_walk.EXTRACT_TOOL:
        try:
            args = json.loads(arguments or "{}") if isinstance(arguments, str) else (arguments or {})
        except json.JSONDecodeError:
            args = {}
        captured = walker.capture(args if isinstance(args, dict) else {})
        # The variables an expression edge tests just changed, so this is exactly
        # when a deterministic transition can newly become true.
        moved = walker.advance()
        out: dict[str, Any] = {"ok": True, "captured": captured}
        if moved is not None:
            out["node"] = moved.key
        return True, out
    target = walker.advance(name)
    if target is None:
        return False, {"ok": False, "error": "unknown_node"}
    return True, {"ok": True, "node": target.key}


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
            db.record_activity(
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
    prior_summary: str | None = None,
    skill_prefix: str = "",
    active_skill_message: dict[str, str] | None = None,
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
    # Same rule as voice and the sandbox: system policy interpolates operator
    # tokens only. render_prompt put CRM fields directly into the system string
    # with no delimiter, so a customer-controlled name landed inside the policy
    # — and before identification the defaults rendered as "Reference their
    # account XXXX and the overdue amount of 0 due on ." The values now ride the
    # delimited untrusted card appended below, which this channel never had.
    rendered = strip_unrendered_crm_tokens(render_system_prompt(bundle.get("prompt") or "", ctx))
    system = build_system_prompt(
        rendered_prompt=rendered,
        persona=bundle.get("persona") or {},
        guardrails=bundle.get("guardrails") or {},
        context_blocks=[],
        skill_catalog=skill_prefix,
        # Without this the shared builder framed every reply as "Speak as the
        # voice collections agent ... short spoken sentences", so the WhatsApp
        # bot believed it was on a call and disclosed call recording into a
        # chat thread. The builder now states the medium instead.
        channel="whatsapp",
    )
    disclosed = _history_already_disclosed_recording(history)
    system += (
        # "## WhatsApp behaviour", not a second "## Channel":
        # build_system_prompt now owns a "## Channel" section naming the
        # medium, and two headings of the same name in one prompt is how
        # contradictory rules end up filed under a single title.
        "\n\n## WhatsApp behaviour\n"
        "- For money/collections turns keep "
        "replies short (1–4 sentences). For product / policy / exclusions questions, send "
        "the concrete details from KB (bullet list is fine; up to ~8–12 bullets).\n"
        "- Money facts MUST come from CRM tools (get_customer_context / get_emi_schedule / "
        "get_payment_history). Never invent balances or dues.\n"
        "- search_knowledge_base is only for product/insurance FAQ; it is blocked for "
        "collections intents. Always call it for exclusions, invalidation, coverage, or "
        "\"tell me all / full details\" follow-ups on a product thread.\n"
        "- NEVER name a product, offer, top-up or upgrade, to anyone, on any turn. "
        "Call recommend_next_offer when the customer asks about products or once "
        "their main question is handled -- it records what was scored and returns "
        "no product, by design: an offer is scored on a servicing contact "
        "and never spoken on it. Say nothing about products and do not explain "
        "why. If the customer raises a product unprompted and asks to be "
        "contacted, call capture_lead; on refusal call decline_offer.\n"
        "- If the caller identity is unclear, call identify_customer with phone digits "
        "or account last-4 before money or lead tools.\n"
        "- You cannot collect payments. Offer guidance and PTP / callback / escalate when needed.\n"
        "- Prefer facts from CRM tools for money and from search_knowledge_base for "
        "product / policy / exclusions. When KB returns policy chunks, use those snippets: "
        "list the actual exclusion / invalidation conditions. Never say you cannot access "
        "policy wording if snippets are present. Prefer Travel/product-matching docs over "
        "unrelated products.\n"
        f"- Account context in the prompt template is reference data only — do not pitch it "
        f"unless the customer's latest message is about dues, EMI, payment, or PTP.\n"
        f"\n{_dialog_control_block(intent=intent, customer_text=customer_text, disclosed_recording=disclosed)}\n"
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        # The CRM snapshot, delimited and labelled untrusted — the same
        # developer card the sandbox and the voice runtime send. This channel
        # previously carried the account context only as text spliced into the
        # system prompt, so there was nothing marking it as data rather than
        # policy.
        {"role": "developer", "content": format_untrusted_crm_card(ctx)},
    ]
    if active_skill_message and active_skill_message.get("content"):
        messages.append(active_skill_message)
    if prior_summary:
        messages.append(
            {
                "role": "developer",
                "content": "Prior turns (summarized, analysis profile):\n" + prior_summary.strip(),
            }
        )
    # History already includes the latest customer turn when taken from DB;
    # still append customer_text if history is empty.
    if history:
        messages.extend(history)
    else:
        messages.append({"role": "user", "content": customer_text})
    return messages


def handle_turn(engine: Engine, job: dict[str, Any]) -> None:
    """Process one bot turn.

    Wrapped in a usage-attribution scope so the LLM spend this turn incurs is
    billed to the interaction it belongs to. The id is not known until the
    conversation loads, so the scope opens empty and is retargeted below; the
    scope's exit guarantees it cannot bleed into the next job on this thread.
    """
    import usage_meter

    with usage_meter.attribute_to(None):
        _handle_turn(engine, job)


def _handle_turn(engine: Engine, job: dict[str, Any]) -> None:
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
    prior_status = (existing.get("delivery_status") or "") if existing else ""
    if existing and prior_status == "sending":
        # Ambiguous: a prior attempt POSTed to Meta but crashed before recording
        # the outcome. WhatsApp Cloud API has no client idempotency key, so
        # re-sending could duplicate a message the customer already received.
        # Fail safe — do not auto-resend; cancel for manual reconciliation.
        with engine.begin() as conn:
            bot_jobs.mark_cancelled(conn, job_id, "outbound_sending_unconfirmed")
        logger.warning(
            "bot_turn outbound stuck 'sending' — not auto-resending (possible duplicate) "
            "job=%s message=%s",
            job_id,
            existing["id"],
        )
        return
    if existing and prior_status == "failed":
        prior_err = str(job.get("error") or "")
        if wa.is_definite_client_error(prior_err):
            with engine.begin() as conn:
                bot_jobs.mark_cancelled(conn, job_id, f"outbound_client_error:{prior_err[:500]}")
            logger.warning(
                "bot_turn outbound prior client error — not re-POSTing job=%s message=%s err=%s",
                job_id,
                existing["id"],
                prior_err[:200],
            )
            return
        if wa.is_ambiguous_transport_error(prior_err):
            # Read timeout / 429 / 5xx: Meta may already have accepted and
            # delivered the message. Cloud API has no client idempotency key, so
            # a retry can double-send to the customer. Park for reconciliation.
            with engine.begin() as conn:
                bot_jobs.mark_cancelled(
                    conn, job_id, f"outbound_ambiguous_transport:{prior_err[:500]}"
                )
            logger.warning(
                "bot_turn outbound prior ambiguous transport error — not re-POSTing "
                "job=%s message=%s err=%s",
                job_id,
                existing["id"],
                prior_err[:200],
            )
            return
        # A failed send definitely never reached Meta (connection refused / DNS
        # / config) — safe to reuse the
        # reserved row (do not INSERT another; UNIQUE(bot_turn_job_id) would fail).
        reuse_outbound_id = existing["id"]
        reuse_body = (existing.get("body") or "").strip() or None
        logger.info(
            "bot_turn retrying outbound job=%s message=%s prior_status=%s",
            job_id,
            reuse_outbound_id,
            prior_status,
        )

    conv = _load_conversation(engine, conversation_id)
    if not conv:
        with engine.begin() as conn:
            bot_jobs.mark_cancelled(conn, job_id, "conversation_not_found")
        return

    # Everything metered from here on belongs to this interaction.
    import usage_meter

    usage_meter.retarget_attribution(conv.get("interaction_id"))

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

    state = _bot_state(conv)

    # Stale reuse: regenerate unless the reserved body was generated against the
    # message that is still the latest one. `last_trigger_message_id` is the
    # message the previous attempt actually generated from; the job's own
    # trigger_message_id is not the same thing, because claim_next_job coalesces
    # sibling queued jobs into this one without rewriting it.
    generated_for = state.get("last_trigger_message_id") or job.get("trigger_message_id")
    if reuse_body and (not latest_msg_id or latest_msg_id != generated_for):
        logger.info(
            "bot_turn stale outbound body job=%s generated_for=%s latest=%s — regenerating",
            job_id,
            generated_for,
            latest_msg_id,
        )
        reuse_body = None

    turn_count = int(state.get("turn_count") or 0) + 1
    guardrails = {}
    try:
        bundle = load_active_bundle(
            bot_jobs.bot_environment(),
            bot_id=_bot_id(),
            fallback_environments=("sandbox", "production"),
            customer_id=conv.get("customer_id"),
        )
        guardrails = bundle.get("guardrails") or {}
    except KeyError as exc:
        with engine.begin() as conn:
            bot_jobs.mark_failed_or_retry(conn, job, f"deployment:{exc}")
        return

    # Stamped before any tool or retrieval runs. The trace backfill at the end
    # of the turn uses it to claim only the retrieval_logs rows this turn
    # produced — those rows carry interaction_id but not job_id, so without a
    # time bound the backfill would also claim the previous turn's retrievals.
    turn_started_at = datetime.now(timezone.utc)

    # One classification per turn, read by everything below. Safe to make an
    # Azure call here: handle_turn runs in bot_worker off the webhook request
    # path, and analyze_turn degrades to the keyword classifiers on any failure.
    understanding = analyze_turn(
        customer_text,
        prior_intent=str(state.get("last_intent") or "") or None,
        channel="text",
    )
    intent = understanding.intent
    intent_scores = understanding.intent_scores
    sentiment = understanding.sentiment

    # Persist live sentiment for Inbox (even when we escalate before Azure).
    # Moved below analyze_turn so it stores the enriched score rather than
    # re-deriving an English-lexicon one from the raw text.
    if conv.get("interaction_id"):
        with engine.begin() as conn:
            db.touch_interaction_sentiment(
                conn, conv.get("interaction_id"), customer_text, score=sentiment
            )

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

    # Was a hardcoded eight-word substring check — the narrowest of the three
    # copies, and the one that matched "kill yourself" by substring so "skill"
    # was safe but "shut up" inside a URL was not. agent_core.lexicon is now the
    # single source; voice/safety.py and guardrails.py read the same patterns.
    hard_abuse = lexicon.is_abusive(customer_text)
    early_flags = evaluate_guardrails(
        customer_text=customer_text,
        bot_text="",
        intent=intent,
        guardrails=guardrails if isinstance(guardrails, dict) else {},
        turn_index=turn_count,
        elapsed_seconds=0,
        customer_bot_exchanges=turn_count,
        channel="whatsapp",
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

    # A non-numeric maxTurns in a deployment bundle must not crash the turn —
    # fall back to the hard ceiling, which is the safe direction.
    try:
        max_turns = int(guardrails.get("maxTurns") or _hard_max_turns())
    except (TypeError, ValueError):
        logger.warning(
            "bot_turn ignoring non-numeric maxTurns=%r job=%s",
            guardrails.get("maxTurns"),
            job_id,
        )
        max_turns = _hard_max_turns()
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
        # Meta / greeting / correction turns must not drown in old EMI seed history.
        hist_limit = _history_limit()
        if intent in {"help_capabilities", "greeting", "correction"}:
            hist_limit = min(hist_limit, 6)
        reset_at = _parse_dialog_reset_at(state)
        history = _message_history(
            engine,
            conversation_id,
            hist_limit * 4,
            since=reset_at,
        )
        from agent_core.compaction import bound_history

        prior_summary = None
        ix = conv.get("interaction_id") or job.get("interaction_id")
        if ix:
            try:
                row = db.get_latest_context_summary(str(ix))
                prior_summary = (row or {}).get("summary")
            except Exception:
                prior_summary = None
        compacted, summary = bound_history(
            history,
            last_n=hist_limit,
            prior_summary=prior_summary,
        )
        if ix and summary and len(history) > hist_limit:
            try:
                db.save_context_summary(
                    interaction_id=str(ix),
                    upto_turn=max(0, len(history) - len(compacted)),
                    summary=summary,
                )
            except Exception:
                logger.exception("context summary persist failed")
        history = compacted
        # If the reset window is empty (race), still answer the latest ask alone.
        if not history:
            history = [{"role": "user", "content": customer_text}]
        from agent_core.skills.runtime import resolve_mouth
        from agent_core.tools.catalog import CATALOG
        from agent_core.tools.grant import TEXT_ALWAYS
        from agent_core.tools.schema import CHANNEL_TEXT

        mouth = resolve_mouth(
            bundle.get("agentCard") or {},
            intent=intent,
            frozen_connector_tools=bundle.get("frozenTools"),
        )
        skill_prompt = mouth.prompt()
        text_channel_tools = {spec.name for spec in CATALOG.for_channel(CHANNEL_TEXT)}
        # TEXT_ALWAYS is the text analogue of the floor voice/tools.py applies to
        # its own registry. Without it the system prompt below told the model to
        # call `identify_customer` on a turn where the name was neither offered
        # nor executable.
        tool_state = mouth.tools(channel_tools=text_channel_tools, floor=TEXT_ALWAYS)
        # The authored graph, on the text channel. `flow` appeared zero times in
        # this module before: WhatsApp answered from the prompt alone while the
        # Studio gated a graph at publish and the canvas drew it. The cursor
        # lives in `bot_state`, which already carries per-conversation state, so
        # a multi-day thread resumes on the step it left. A card with no authored
        # flow leaves the walker None and behaves exactly as it did.
        flow_walker = _flow_walker(bundle, state)
        import flow_walk as _flow_walk_mod

        _specialist_grants = _flow_walk_mod.specialist_grants(bundle.get("compiled"))
        _specialist_entries = _flow_walk_mod.specialist_entries(bundle.get("compiled"))
        if flow_walker is not None:
            # A step this channel cannot stand on is stepped through to where
            # its own contract says it leads -- the greeting's only exit is the
            # recording disclosure, and a WhatsApp thread has none to make.
            # The same rule G-F11 gates on at publish, applied where it runs.
            passed = flow_walker.pass_through(
                granted=flow_walker.union(tool_state.offered or (), _specialist_grants)
            )
            if passed:
                logger.info("bot_turn: passed through %s on text", ", ".join(passed))
        messages = _build_messages(
            bundle=bundle,
            conv=conv,
            history=history,
            customer_text=customer_text,
            intent=intent,
            prior_summary=summary,
            skill_prefix=skill_prompt.prefix,
            active_skill_message=skill_prompt.body_message,
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
            # The offer engine's sentiment floor reads this. Passing the turn's
            # already-classified score keeps a frustrated Hindi caller from
            # being pitched a product because an English lexicon scored 0.00.
            sentiment=sentiment,
        )
        tool_ctx.allowed_tools = tool_state.allowed
        tool_ctx.environment = str(
            (bundle.get("deployment") or {}).get("environment") or bot_jobs.bot_environment()
        )
        tool_ctx.attached_skills = list(mouth.packs)
        tool_ctx.active_skill = mouth.active_slug
        # The handoff allowlist belongs to the card this turn is running, not
        # to whatever BOT_ID the process was started with.
        tool_ctx.agent_card = bundle.get("agentCard") or None

        def _turn_tools(offered: list[str]) -> list[dict]:
            """OpenAI tool dicts for this turn, with the card's own handoffs in
            ``handoff_to_agent``'s schema rather than the catalog's two example
            bot ids. Built from the same card the allowlist enforces."""
            from agent_core.tools.handoff_allowlist import handoff_tool_spec

            specs = [CATALOG.get(n) for n in offered]
            tools = [
                (
                    handoff_tool_spec(s, agent_card=tool_ctx.agent_card, bot_id=_bot_id())
                    if s.name == "handoff_to_agent"
                    else s
                ).to_openai_tool()
                for s in specs
                if s is not None
            ]
            if flow_walker is not None:
                import flow_walk

                tools.extend(flow_walk.openai_graph_tools(flow_walker))
            return tools

        def _offered_names() -> list[str]:
            """The card's grant, narrowed by the step the script is on.

            With a floor: a step whose offer is empty on this channel falls back
            to the whole grant rather than handing the model no tools at all.
            That case is real today and not hypothetical — G-F11 warns on all
            four first-party cards, because the built-in script is a *voice*
            script whose steps hop on voice-only tools (``greet_disclose`` exits
            via ``disclose_recording``, and a WhatsApp thread has no recording to
            disclose). Narrowing to nothing there would strand every live thread
            on the first message.

            So the graph tightens the offer where it has something to say and
            stays out of the way where it does not. When the fleet compiles G-F11
            clean this floor stops firing on its own; it does not need removing.
            """
            granted = flow_walker.union(tool_state.offered or (), _specialist_grants) if flow_walker else set(tool_state.offered or ())
            if flow_walker is None:
                return list(tool_state.offered or ())
            # Narrowed to the speaking member first, then to the step. Same two
            # narrowings, same order, as the audio path and the sandbox.
            step_grant = flow_walker.narrow(granted, _specialist_grants)
            narrowed = [n for n in flow_walker.offers(granted=step_grant) if n in step_grant]
            return narrowed or list(tool_state.offered or ())

        tool_failures = 0
        for _ in range(_max_tool_iterations()):
            # Rebuilt per iteration: a transition changes the offer, and the step
            # after `go_to_negotiate` must not still be offering the step before.
            turn_tools = _turn_tools(_offered_names())
            # Re-check take-over race before each Azure call.
            fresh = _load_conversation(engine, conversation_id)
            if not fresh or fresh.get("status") != "bot" or fresh.get("assigned_user_id"):
                with engine.begin() as conn:
                    bot_jobs.mark_cancelled(conn, job_id, "takeover_mid_flight")
                return

            from agent_core.telemetry import span as _span

            with _span("gen_ai.chat", gen_ai_operation_name="chat"):
                result = azure_openai.chat_with_tools(
                    messages,
                    tools=turn_tools,
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
                if flow_walker is not None and _is_graph_tool(tc["name"]):
                    # A graph move, not a catalog tool: it has no handler in the
                    # registry and must not be routed through execute_tool, which
                    # would refuse it as ungranted. The grant says what the agent
                    # may do; the graph says where it may go.
                    ok, payload = _walk_graph_tool(flow_walker, tc["name"], tc["arguments"])
                    latency_ms = 0
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(payload)[:1500],
                        }
                    )
                    continue
                with _span(
                    "gen_ai.execute_tool",
                    gen_ai_operation_name="execute_tool",
                    gen_ai_tool_name=tc["name"],
                ):
                    ok, payload, latency_ms = bot_tools.execute_tool(tool_ctx, tc["name"], tc["arguments"])
                if ok and flow_walker is not None:
                    if tc["name"] == "handoff_to_agent":
                        # `advance` never moves for a handoff: there is no edge
                        # from this node to another member's subgraph, the card's
                        # allowlist is the edge. Resolve the landing node the way
                        # voice does and move the cursor onto it, which swaps the
                        # namespace and therefore the grant on the next iteration.
                        _hop_to(flow_walker, tool_ctx, tc, payload, _specialist_entries)
                    else:
                        # A built-in tool is also a transition — the built-in
                        # script moves entirely this way, with no authored edges.
                        flow_walker.advance(tc["name"])
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
                if ok and tc["name"] == "load_skill" and tool_ctx.active_skill:
                    from dataclasses import replace as _replace

                    from agent_core.skills.runtime import body_developer_message as _skill_body

                    pack = next((p for p in tool_ctx.attached_skills if getattr(p, "slug", None) == tool_ctx.active_skill), None)
                    if pack:
                        messages.append(_skill_body(pack))
                    if mouth.card is not None:
                        # Only the offer widens. The grant on tool_ctx is
                        # deliberately untouched: activating a skill changes
                        # what the model is shown, never what it may run.
                        activated = _replace(mouth, active_slug=tool_ctx.active_skill)
                        turn_tools = _turn_tools(
                            list(
                                activated.tools(
                                    channel_tools=text_channel_tools, floor=TEXT_ALWAYS
                                ).offered
                            )
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

    to_phone = wa.normalize_phone(fresh.get("phone_primary"))
    if not to_phone:
        # No deliverable number on the customer record. This is not a transport
        # failure — retrying and escalating would both be noise.
        _finalize_outbound(
            engine,
            message_id=msg_id,
            provider_ref=None,
            delivery_status="failed",
            customer_id=fresh.get("customer_id"),
            conversation_id=conversation_id,
            body=final_text,
        )
        with engine.begin() as conn:
            bot_jobs.mark_cancelled(conn, job_id, "missing_recipient")
        logger.warning(
            "bot_turn outbound has no recipient phone job=%s conversation=%s",
            job_id,
            conversation_id,
        )
        return
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
        err_str = str(exc)
        if wa.is_ambiguous_transport_error(err_str):
            # Meta may have accepted the POST. Leave the row in 'sending' so the
            # next pass takes the "stuck sending" branch and parks it for manual
            # reconciliation instead of re-POSTing a possible duplicate.
            logger.warning(
                "bot_turn outbound ambiguous transport error — leaving 'sending' "
                "for reconciliation job=%s message=%s err=%s",
                job_id,
                msg_id,
                err_str[:200],
            )
            with engine.begin() as conn:
                bot_jobs.mark_cancelled(
                    conn, job_id, f"outbound_ambiguous_transport:{err_str[:500]}"
                )
            return
        _finalize_outbound(
            engine,
            message_id=msg_id,
            provider_ref=None,
            delivery_status="failed",
            customer_id=fresh.get("customer_id"),
            conversation_id=conversation_id,
            body=final_text,
        )
        if wa.is_definite_client_error(err_str):
            with engine.begin() as conn:
                bot_jobs.mark_cancelled(conn, job_id, err_str[:2000])
            logger.warning(
                "bot_turn outbound client error (no retry) job=%s err=%s",
                job_id,
                err_str[:200],
            )
            return
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
    if flow_walker is not None and flow_walker.current is not None:
        # Where the script is, so the next inbound message resumes here rather
        # than re-greeting a thread that is four turns in.
        state["flow_node"] = flow_walker.current.key
    _save_bot_state(engine, conversation_id, state)

    # Phase 1 gap-fix: WhatsApp previously never wrote interaction_transcript,
    # so rollup/upsell flags could not work like voice. Persist both turns here
    # (bot_worker path — never on the webhook request).
    ix = conv.get("interaction_id") or fresh.get("interaction_id")
    if ix:
        try:
            import capture

            top_score = float(intent_scores.get(intent) or 0.0) if intent_scores else None
            with engine.begin() as conn:
                # `at_sec` is the offset every timing view is keyed on, and both
                # turns were written at a literal 0 — so the entire WhatsApp
                # channel read as one instantaneous exchange while looking
                # perfectly well-formed. Stamp the customer turn from the
                # message being replied to, and the bot turn from now.
                started_at = capture.interaction_started_at(conn, ix)
                customer_turn_index = capture.insert_transcript_turn(
                    conn,
                    interaction_id=ix,
                    speaker="customer",
                    text_content=customer_text,
                    at_sec=capture.elapsed_seconds(
                        started_at, _message_sent_at(conn, latest_msg_id)
                    ),
                    sentiment_delta=float(sentiment) if sentiment is not None else None,
                    intent=intent,
                    intent_score=top_score,
                )
                # W9: the same classification, kept as provenance-tagged facts
                # instead of only as three untyped columns on the row above.
                # Written here rather than beside `analyze_turn` because this is
                # where the turn index exists — a fact keyed to a different
                # index than the transcript row joins to nothing. Records
                # nothing on a database without 0119, and never raises.
                perception.record_turn_for_interaction(
                    conn,
                    interaction_id=ix,
                    turn_index=customer_turn_index,
                    understanding=understanding,
                    turn_text=customer_text,
                    latency_ms=understanding.latency_ms,
                )
                # Let the bot turn allocate its own index too. Passing t_idx + 1
                # with ON CONFLICT DO NOTHING silently dropped the reply if any
                # other writer had taken that index; MAX()+1 inside the same
                # transaction already sees the customer turn above, so ordering
                # is preserved either way.
                capture.insert_transcript_turn(
                    conn,
                    interaction_id=ix,
                    speaker="bot",
                    text_content=final_text,
                    at_sec=capture.elapsed_seconds(started_at, datetime.now(timezone.utc)),
                )
                # Backfill this turn's tool calls and retrievals with the turn
                # they belong to. Deliberately a backfill rather than a reorder:
                # bot_tool_calls rows are written inside the tool loop, long
                # before the transcript row for the turn exists, and moving that
                # write would change the turn loop's failure semantics.
                #
                # The id is read back via a subquery, never constructed —
                # capture's canonical-id rename is savepoint-guarded and can be
                # skipped, leaving `{ix}-T-next-{uuid}` on the row.
                conn.execute(
                    text(
                        """
                        UPDATE bot_tool_calls
                           SET transcript_turn_id = (
                                 SELECT id FROM interaction_transcript
                                  WHERE interaction_id = :ix AND turn_index = :ti
                               ),
                               interaction_id = :ix,
                               channel = 'whatsapp'
                         WHERE job_id = :job_id AND transcript_turn_id IS NULL
                        """
                    ),
                    {"ix": ix, "ti": customer_turn_index, "job_id": job_id},
                )
                conn.execute(
                    text(
                        """
                        UPDATE retrieval_logs
                           SET transcript_turn_id = (
                                 SELECT id FROM interaction_transcript
                                  WHERE interaction_id = :ix AND turn_index = :ti
                               )
                         WHERE interaction_id = :ix
                           AND transcript_turn_id IS NULL
                           AND created_at >= :turn_started
                        """
                    ),
                    {"ix": ix, "ti": customer_turn_index, "turn_started": turn_started_at},
                )
                capture.rollup_interaction(conn, ix, channel_hint="whatsapp", force_summary=False)
        except Exception:
            logger.exception("whatsapp transcript/rollup capture failed job=%s", job_id)
        try:
            from voice import persist as voice_persist

            voice_persist.evaluate_and_flag_bot_turn(
                interaction_id=ix,
                customer_text=customer_text,
                bot_text=final_text,
                intent=intent or "out_of_scope",
                guardrails=guardrails if isinstance(guardrails, dict) else {},
                turn_index=int(turn_count or 0),
                elapsed_seconds=0,
                customer_bot_exchanges=int(turn_count or 0),
                identity_verified=bool(fresh.get("customer_id")),
                third_party=False,
                channel="whatsapp",
                customer_id=fresh.get("customer_id"),
            )
        except Exception:
            logger.exception("whatsapp live_qa failed job=%s", job_id)

    with engine.begin() as conn:
        bot_jobs.mark_succeeded(conn, job_id, outbound_message_id=msg_id)
    logger.info("bot_turn succeeded job=%s message=%s", job_id, msg_id)
