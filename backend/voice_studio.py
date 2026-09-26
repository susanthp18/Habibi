"""PayInt Voice Studio: what our platform does around the calls the engine runs.

The voice-agent engine (agentstudio/engine) owns the conversation: the flow,
speech, the model, telephony. Everything that is PayInt's business stays here
and is reached from the engine over four seams:

* **Dial** -- ``originate`` (the ``voice.telephony`` adapter ``studio``) starts
  an engine agent through its API trigger with the attempt's mission as the
  call's starting context. Treatment, cadence, campaigns, contact policy, the
  kill switch and the fleet cap all run before it, unchanged, in
  ``outbound.place``.
* **Tools** -- the agent's HTTP tools call ``run_tool``: account position,
  identity verification, promise to pay, callback, dispute. They are the same
  domain functions the previous voice runtime used, attached to one
  interaction per engine run.
* **Pre-call** -- an inbound call asks ``precall`` who is ringing.
* **After the call** -- the engine's webhook calls ``complete_run``: the
  transcript, recording and outcome are filed on the interaction and the
  attempt's state machine advances, so the call closer, QA and analytics see
  the call exactly as they saw calls before.
"""

from __future__ import annotations

import hmac
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import text

from db_promises import REVISION_REASONS
from env_utils import env_str

logger = logging.getLogger(__name__)

#: The engine user our own server-side calls act as (org = the tenant).
SYSTEM_ACTOR = "system:voice-studio"
#: The platform provider name recorded on call attempts dialled by the engine.
PROVIDER = "studio"


class NotBound(RuntimeError):
    """No Voice Studio agent is bound to the attempt's objective."""


# ---------------------------------------------------------------------------
# Engine access
# ---------------------------------------------------------------------------


def engine_url() -> str:
    return env_str("AGENTSTUDIO_ENGINE_URL", "http://agentstudio_engine:8000").rstrip("/")


def _internal_headers(actor: str = SYSTEM_ACTOR) -> dict[str, str]:
    import db

    secret = env_str("AGENTSTUDIO_INTERNAL_SECRET")
    if not secret:
        raise RuntimeError("AGENTSTUDIO_INTERNAL_SECRET is not set")
    return {"X-Internal-Secret": secret, "X-User-Id": actor, "X-Org-Id": db.current_tenant()}


def engine_call(method: str, path: str, *, json: Any = None, timeout: float = 30.0,
                actor: str = SYSTEM_ACTOR) -> Any:
    """A server-side call to the engine API (``path`` below /api/v1) as the system actor."""
    resp = httpx.request(
        method,
        f"{engine_url()}/api/v1{path}",
        json=json,
        headers=_internal_headers(actor),
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else None


def hook_token_ok(authorization: str | None) -> bool:
    """The engine's tools and webhook authenticate with one bearer token."""
    expected = env_str("VOICE_STUDIO_HOOK_TOKEN")
    got = (authorization or "").removeprefix("Bearer ").strip()
    return bool(expected) and hmac.compare_digest(got.encode(), expected.encode())


# ---------------------------------------------------------------------------
# Bindings: which engine agent runs which objective
# ---------------------------------------------------------------------------


def agent_for(conn: Any, objective: str | None, *, allow_default: bool = True) -> dict[str, Any] | None:
    """Return an exact binding, or the outbound default when explicitly allowed."""
    import db

    row = conn.execute(
        text(
            """
            SELECT objective, engine_workflow_id, trigger_path
            FROM voice_studio_agents
            WHERE tenant_id = :t AND objective IN (:o, :fallback) AND enabled
            ORDER BY (objective = '*') ASC
            LIMIT 1
            """
        ),
        {"t": db.current_tenant(), "o": objective or "", "fallback": "*" if allow_default else objective or ""},
    ).mappings().first()
    return dict(row) if row else None


#: Guardrails an engine agent has until someone edits them (agent_core.guardrails keys).
DEFAULT_GUARDRAILS: dict[str, Any] = {
    "prohibited": ["guarantee", "police", "arrest", "threaten", "family will pay", "harassment", "legal action"],
    "escalateAbuse": True,
    "escalateLegal": True,
    "neverQuoteRate": True,
    "neverPromiseWaiver": True,
    "alwaysDiscloseRecording": True,
    "refusePoliticsReligion": True,
    "maxTurns": 20,
}
GUARDRAIL_KEYS = frozenset(DEFAULT_GUARDRAILS)


def guardrails_for(workflow_id: Any) -> dict[str, Any]:
    """PayInt's guardrails for engine agent ``workflow_id`` (defaults when unset)."""
    import db

    if workflow_id in (None, ""):
        return dict(DEFAULT_GUARDRAILS)
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT guardrails FROM voice_studio_guardrails "
                    "WHERE tenant_id = :t AND engine_workflow_id = :w"
                ),
                {"t": db.current_tenant(), "w": int(workflow_id)},
            ).scalar()
    except Exception:
        logger.exception("voice studio: guardrails lookup failed for agent %s", workflow_id)
        row = None
    return {**DEFAULT_GUARDRAILS, **(row or {})}


def save_guardrails(workflow_id: int, guardrails: dict[str, Any], actor: str | None) -> dict[str, Any]:
    """Store an agent's guardrails; unknown keys are dropped."""
    import json

    import db

    clean = {k: v for k, v in guardrails.items() if k in GUARDRAIL_KEYS}
    if "prohibited" in clean:
        clean["prohibited"] = sorted({str(p).strip().lower() for p in clean["prohibited"] or [] if str(p).strip()})
    if "maxTurns" in clean:
        clean["maxTurns"] = max(1, min(200, int(clean["maxTurns"])))
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO voice_studio_guardrails (tenant_id, engine_workflow_id, guardrails, updated_by_user_id)
                VALUES (:t, :w, CAST(:g AS jsonb), :u)
                ON CONFLICT (tenant_id, engine_workflow_id) DO UPDATE
                   SET guardrails = EXCLUDED.guardrails, updated_by_user_id = EXCLUDED.updated_by_user_id,
                       updated_at = now()
                """
            ),
            {"t": db.current_tenant(), "w": int(workflow_id), "g": json.dumps(clean), "u": actor},
        )
    return {**DEFAULT_GUARDRAILS, **clean}


# ---------------------------------------------------------------------------
# Call context (what the agent knows when the call starts)
# ---------------------------------------------------------------------------


def _spoken_inr(value: Any) -> str | None:
    import money_inr

    try:
        return f"₹{money_inr.group_indian(str(abs(int(round(float(value))))))}"
    except (TypeError, ValueError):
        return None


def _position_context(position: dict[str, Any]) -> dict[str, Any]:
    return {
        "account_id": position.get("accountId"),
        "account_tail": position.get("accountTail"),
        "days_past_due": position.get("dpd"),
        "outstanding_amount": _spoken_inr(position.get("outstandingInr")),
        "minimum_due": _spoken_inr(position.get("minimumDueInr")),
        "minimum_due_value": position.get("minimumDueInr"),
        "product_name": position.get("productName"),
        "account_status": position.get("status"),
    }


def outbound_context(conn: Any, attempt_id: str, custom: dict[str, str]) -> dict[str, Any]:
    """The mission, flattened into the variables an engine agent's prompts use."""
    import mission as mission_mod

    m = mission_mod.load(conn, attempt_id) or {}
    ctx: dict[str, Any] = {
        "direction": "outbound",
        "attempt_id": attempt_id,
        "objective": custom.get("objective") or m.get("objective"),
        "customer_id": custom.get("customer_id") or m.get("customerId"),
        "customer_name": m.get("customerName"),
        "first_name": m.get("firstName"),
        "language": m.get("language"),
        "timezone": m.get("timezone"),
        "mission_brief": mission_mod.briefing(m) if m else None,
        "decision_id": custom.get("treatment_decision_id"),
        "campaign_run_id": m.get("campaignRunId"),
    }
    context = m.get("context") or {}
    ctx.update(_position_context(context.get("position") or {}))
    if custom.get("account_id"):
        ctx["account_id"] = custom["account_id"]
    promise = context.get("promise") or {}
    if promise:
        ctx["open_promise_date"] = promise.get("promisedDate") or promise.get("date")
        ctx["open_promise_amount"] = _spoken_inr(promise.get("amountInr") or promise.get("amount"))
    if custom.get("demo"):
        ctx["demo"] = True
    return {k: v for k, v in ctx.items() if v not in (None, "")}


# ---------------------------------------------------------------------------
# Dial: the `studio` telephony adapter
# ---------------------------------------------------------------------------


def originate(
    *,
    to: str,
    custom: dict[str, str] | None = None,
    machine_detection: bool = False,
    from_number: str | None = None,
) -> dict[str, Any]:
    """Start the bound engine agent calling ``to``; returns ``{callSid, status}``.

    ``callSid`` is the engine run id: the attempt records it as its provider
    call id, which is how the after-call webhook finds the attempt again.
    """
    import db
    import platform_switches
    from voice.twilio_ops import OutboundDisabled

    if not platform_switches.outbound_enabled():
        raise OutboundDisabled("outbound_disabled: turn on outbound calling in Roles & access first")
    custom = dict(custom or {})
    attempt_id = custom.get("attempt_id") or ""
    with db.engine.connect() as conn:
        binding = agent_for(conn, custom.get("objective"))
        if binding is None:
            raise NotBound(f"no Voice Studio agent is bound to objective {custom.get('objective')!r}")
        initial_context = outbound_context(conn, attempt_id, custom) if attempt_id else {}
    initial_context["agent_id"] = binding["engine_workflow_id"]

    api_key = env_str("VOICE_STUDIO_API_KEY")
    if not api_key:
        raise RuntimeError("VOICE_STUDIO_API_KEY is not set")
    import voice_studio_routing

    trigger_path = voice_studio_routing.outbound_trigger_path(binding["engine_workflow_id"])
    resp = httpx.post(
        f"{engine_url()}/api/v1/public/agent/{trigger_path}",
        json={"phone_number": to, "initial_context": initial_context},
        headers={"X-API-Key": api_key},
        timeout=30,
    )
    if resp.status_code == 429:
        raise RuntimeError("voice_studio_busy: the engine's concurrent-call limit is reached")
    resp.raise_for_status()
    run_id = resp.json().get("workflow_run_id")
    logger.info("voice studio: attempt %s dialled as engine run %s", attempt_id, run_id)
    return {"callSid": str(run_id), "status": "initiated"}


def hangup(channel_id: str) -> None:  # the engine ends its own calls
    logger.info("voice studio: hangup for run %s is handled by the engine", channel_id)


def warm_transfer(channel_id: str, *, reason: str = "customer_requested") -> dict[str, Any]:
    # Transfers happen inside the call through the agent's transfer tool,
    # resolved by `transfer_destination` below.
    return {"ok": False, "reason": "transfer_is_in_call", "channelId": channel_id}


def default_from_number() -> str:
    return env_str("TWILIO_PHONE_NUMBER")


def configured() -> bool:
    return bool(env_str("VOICE_STUDIO_API_KEY") and env_str("AGENTSTUDIO_INTERNAL_SECRET"))


def preflight() -> list[str]:
    problems = []
    if not env_str("VOICE_STUDIO_API_KEY"):
        problems.append("VOICE_STUDIO_API_KEY is not set (run scripts/voice_studio_seed.py)")
    if not env_str("AGENTSTUDIO_INTERNAL_SECRET"):
        problems.append("AGENTSTUDIO_INTERNAL_SECRET is not set")
    if not env_str("VOICE_STUDIO_HOOK_TOKEN"):
        problems.append("VOICE_STUDIO_HOOK_TOKEN is not set: the engine cannot reach our tools")
    return problems


# ---------------------------------------------------------------------------
# One interaction per engine run
# ---------------------------------------------------------------------------


def bot_id_for(agent_id: Any) -> str:
    """Our bot-registry id for an engine agent ('voice-studio' when unknown)."""
    return f"voice-studio-{agent_id}" if agent_id not in (None, "") else "voice-studio"


def ensure_bot(conn: Any, agent_id: Any, name: str | None = None) -> str:
    """Register the engine agent in ``bots`` so interactions, QA and analytics
    can name the agent that handled a call."""
    import db

    bot_id = bot_id_for(agent_id)
    conn.execute(
        text(
            """
            INSERT INTO bots (id, tenant_id, name, version)
            VALUES (:id, :t, :name, 'voice-studio')
            ON CONFLICT (id) DO UPDATE SET name = COALESCE(:given, bots.name), updated_at = now()
            """
        ),
        {"id": bot_id, "t": db.current_tenant(), "name": name or "PayInt Voice Studio agent", "given": name},
    )
    return bot_id


def _session_id(run_id: Any) -> str:
    return f"VS-studio-{run_id}"


def ensure_interaction(run_id: Any, ctx: dict[str, Any], *, started_at: datetime | None = None) -> str:
    """The interaction for engine run ``run_id``, created on first use.

    Tools and the after-call webhook can arrive concurrently; a transaction
    advisory lock on the run makes creation happen once.
    """
    import db
    import outbound
    from voice import persist

    session_id = _session_id(run_id)
    # Committed before the interaction is written: start_voice_call inserts on
    # its own connection, which must see the bot row its FK points at.
    with db.engine.begin() as conn:
        bot_id = ensure_bot(conn, ctx.get("agent_id") or ctx.get("workflow_id"))
    with db.engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": session_id})
        existing = conn.execute(
            text("SELECT interaction_id FROM voice_sessions WHERE id = :id"), {"id": session_id}
        ).scalar()
        if existing:
            return str(existing)
        customer_id = persist.resolve_known_customer(ctx.get("customer_id"))
        created = persist.start_voice_call(
            session_id=session_id,
            deployment_id=None,
            transport="voice-studio",
            provider_call_id=str(run_id),
            customer_id=customer_id,
            account_id=ctx.get("account_id"),
            bot_id=bot_id,
            direction=str(ctx.get("direction") or "inbound"),
            started_at=started_at,
            hours_waived=bool(ctx.get("demo")),
        )
        interaction_id = created["interactionId"]
    if ctx.get("attempt_id"):
        with db.engine.begin() as conn:
            outbound.bind_interaction(
                conn, attempt_id=str(ctx["attempt_id"]), interaction_id=interaction_id, provider=PROVIDER
            )
    return interaction_id


def _challenge_only(ctx: dict[str, Any]) -> str:
    """On WhatsApp the ingest records the sender's number as ``phone_match`` (the
    endpoint level); only a challenge the customer answers verifies them."""
    return " AND method <> 'phone_match'" if ctx.get("channel") == "whatsapp" else ""


def _identity_verified(conn: Any, interaction_id: str, ctx: dict[str, Any]) -> bool:
    return bool(
        conn.execute(
            text(
                "SELECT 1 FROM identity_verifications "
                "WHERE interaction_id = :ix AND status = 'verified'" + _challenge_only(ctx) + " LIMIT 1"
            ),
            {"ix": interaction_id},
        ).first()
    )


def _verification_attempts(conn: Any, interaction_id: str, ctx: dict[str, Any]) -> int:
    return int(
        conn.execute(
            text("SELECT count(*) FROM identity_verifications WHERE interaction_id = :ix" + _challenge_only(ctx)),
            {"ix": interaction_id},
        ).scalar()
        or 0
    )


# ---------------------------------------------------------------------------
# Tools the engine agent calls
# ---------------------------------------------------------------------------

MAX_VERIFY_ATTEMPTS = 3


def _account_position(customer_id: str | None, account_id: str | None) -> dict[str, Any]:
    import db
    import mission as mission_mod

    with db.engine.connect() as conn:
        position = mission_mod._account_position(conn, account_id)
        promise = mission_mod._open_promise(conn, customer_id) if customer_id else None
        last = mission_mod._last_contact(conn, customer_id) if customer_id else None
    out = _position_context(position)
    if promise:
        out["open_promise"] = promise
    if last:
        out["last_contact"] = last
    return {k: v for k, v in out.items() if v not in (None, "")}


def _tool_account_position(ctx: dict[str, Any], args: dict[str, Any], interaction_id: str) -> dict[str, Any]:
    import db

    with db.engine.connect() as conn:
        if not _identity_verified(conn, interaction_id, ctx):
            return {"ok": False, "error": "identity_not_verified",
                    "say": "Verify the customer's identity before discussing the account."}
    return {"ok": True, **_account_position(ctx.get("customer_id"), ctx.get("account_id"))}


def _tool_verify_identity(ctx: dict[str, Any], args: dict[str, Any], interaction_id: str) -> dict[str, Any]:
    import db
    from voice import persist

    method = str(args.get("method") or "phone_last4").lower()
    value = "".join(ch for ch in str(args.get("value") or "") if ch.isdigit())
    direction = str(ctx.get("direction") or "inbound")
    # Outbound: we chose whom to call, so the factor must be something only
    # they know -- the last four of the registered mobile, never the account
    # tail the agent may already have read out.
    if direction == "outbound" and method != "phone_last4":
        return {"ok": False, "error": "method_not_allowed",
                "say": "Ask for the last four digits of their registered mobile number."}
    # WhatsApp: they are writing from the registered mobile, so its digits prove nothing.
    if ctx.get("channel") == "whatsapp" and method != "account_tail":
        return {"ok": False, "error": "method_not_allowed",
                "say": "Ask for the last four digits of their account number."}
    if len(value) != 4:
        return {"ok": False, "error": "need_four_digits", "say": "Ask for exactly four digits."}

    with db.engine.connect() as conn:
        if _identity_verified(conn, interaction_id, ctx):
            return {"ok": True, "verified": True, "note": "already verified on this call"}
        attempts = _verification_attempts(conn, interaction_id, ctx)
    if attempts >= MAX_VERIFY_ATTEMPTS:
        return {"ok": False, "verified": False, "error": "locked",
                "say": "Explain you cannot discuss the account on this call and offer a callback."}

    match = persist.lookup_customer_for_verify(
        method="phone_match" if method == "phone_last4" else "account_tail",
        value=value,
        prefer_customer_id=ctx.get("customer_id"),
    )
    bound = ctx.get("customer_id")
    verified = bool(match) and (not bound or match["customerId"] == bound)
    customer_id = (match or {}).get("customerId") or bound
    persist.record_identity_verification(
        interaction_id=interaction_id,
        customer_id=customer_id or "",
        method="phone_match" if method == "phone_last4" else "account_tail",
        status="verified" if verified else "failed",
        attempt_count=attempts + 1,
        failure_reason=None if verified else "no_match",
    )
    if not verified:
        left = MAX_VERIFY_ATTEMPTS - attempts - 1
        return {"ok": True, "verified": False, "attempts_left": left,
                "say": "Those digits don't match our records." + (" Ask once more." if left else "")}
    if not bound:  # inbound: the caller is now known
        persist.bind_customer_to_interaction(
            interaction_id=interaction_id, customer_id=match["customerId"], account_id=match.get("accountId")
        )
    return {
        "ok": True,
        "verified": True,
        "customer_name": match.get("name"),
        **_account_position(match["customerId"], ctx.get("account_id") or match.get("accountId")),
    }


def _require_verified(interaction_id: str, ctx: dict[str, Any]) -> dict[str, Any] | None:
    import db

    with db.engine.connect() as conn:
        if _identity_verified(conn, interaction_id, ctx):
            return None
    return {"ok": False, "error": "identity_not_verified",
            "say": "Verify the customer's identity first."}


def _tool_promise_to_pay(ctx: dict[str, Any], args: dict[str, Any], interaction_id: str) -> dict[str, Any]:
    from agent_core.tools import domain

    if (blocked := _require_verified(interaction_id, ctx)) is not None:
        return blocked
    result = domain.create_promise_to_pay(
        customer_id=str(ctx.get("customer_id") or ""),
        amount=args.get("amount"),
        promised_date=str(args.get("date") or ""),
        interaction_id=interaction_id,
        account_id=ctx.get("account_id"),
        channel=str(ctx.get("channel") or "voice"),
        idempotency_key=f"vs-{ctx.get('workflow_run_id')}-ptp-{args.get('date')}-{args.get('amount')}",
    )
    if result.error == "promise_already_open":  # the customer is renegotiating it
        result = domain.revise_promise_to_pay(
            customer_id=str(ctx.get("customer_id") or ""),
            # The model's word for why, when it is one the ledger knows; else "other".
            reason=reason if (reason := str(args.get("reason") or "")) in REVISION_REASONS else "other",
            amount=args.get("amount"),
            promise_date=str(args.get("date") or ""),
            interaction_id=interaction_id,
            account_id=ctx.get("account_id"),
            idempotency_key=f"vs-{ctx.get('workflow_run_id')}-ptp-rev-{args.get('date')}-{args.get('amount')}",
        )
    if result.error == "promise_revision_cap":  # final: a retry cannot succeed
        return {**result.to_llm(), "ok": False, "retry": False,
                "say": ("This promise has been changed the maximum number of times and cannot be changed "
                        "again. Do not retry or confirm a new date; offer to connect a colleague.")}
    return result.to_llm()


def _tool_request_callback(ctx: dict[str, Any], args: dict[str, Any], interaction_id: str) -> dict[str, Any]:
    import db
    from agent_core.tools import domain

    with db.engine.connect() as conn:
        existing = conn.execute(text("""
            SELECT scheduled_at FROM callbacks
            WHERE interaction_id = :interaction_id AND customer_id = :customer_id
              AND status IN ('scheduled', 'reminded')
            ORDER BY created_at DESC LIMIT 1
        """), {"interaction_id": interaction_id,
                "customer_id": str(ctx.get("customer_id") or "")}).scalar_one_or_none()
    if existing is not None:
        return {"ok": False, "error": "callback_already_booked",
                "existingTime": existing.isoformat(),
                "say": "A callback is already booked. Confirm its time; do not book or promise another."}
    result = domain.request_callback(
        customer_id=str(ctx.get("customer_id") or ""),
        scheduled_at=str(args.get("when") or ""),
        interaction_id=interaction_id,
        account_id=ctx.get("account_id"),
        reason=args.get("reason"),
        idempotency_key=f"vs-{ctx.get('workflow_run_id')}-cb-{args.get('when')}",
    )
    return result.to_llm()


def _tool_flag_dispute(ctx: dict[str, Any], args: dict[str, Any], interaction_id: str) -> dict[str, Any]:
    from agent_core.tools import domain

    if (blocked := _require_verified(interaction_id, ctx)) is not None:
        return blocked
    result = domain.flag_dispute(
        customer_id=str(ctx.get("customer_id") or ""),
        dispute_type=str(args.get("type") or "other"),
        interaction_id=interaction_id,
        account_id=ctx.get("account_id"),
        summary=args.get("summary"),
        idempotency_key=f"vs-{ctx.get('workflow_run_id')}-dispute",
    )
    return result.to_llm()


TOOLS = {
    "account_position": _tool_account_position,
    "verify_identity": _tool_verify_identity,
    "promise_to_pay": _tool_promise_to_pay,
    "request_callback": _tool_request_callback,
    "flag_dispute": _tool_flag_dispute,
}

#: Engine-injected call ids, never supplied by the model.
CONTEXT_KEYS = ("workflow_run_id", "workflow_id", "agent_id", "attempt_id", "customer_id",
                "account_id", "direction", "demo", "channel", "interaction_id", "conversation_id", "rehearsal")


def _interaction(ctx: dict[str, Any]) -> str:
    """A WhatsApp thread brings its own interaction; a call gets one per run."""
    return str(ctx.get("interaction_id") or ensure_interaction(ctx["workflow_run_id"], ctx))


def run_tool(name: str, body: dict[str, Any]) -> dict[str, Any]:
    """Run one agent tool call. ``body`` = the engine's preset ids + the model's arguments."""
    from voice import persist

    handler = TOOLS.get(name)
    if handler is None:
        return {"ok": False, "error": "unknown_tool"}
    ctx = {k: body.get(k) for k in CONTEXT_KEYS if body.get(k) not in (None, "")}
    args = {k: v for k, v in body.items() if k not in CONTEXT_KEYS}
    run_id = ctx.get("workflow_run_id")
    if not run_id:
        return {"ok": False, "error": "missing_run"}
    import voice_studio_checks

    if voice_studio_checks.is_test(ctx):  # editor test or scripted check: nothing real is touched
        return voice_studio_checks.rehearsal_tool(name, ctx, args)
    interaction_id = _interaction(ctx)
    started = datetime.now(timezone.utc)
    try:
        result = handler(ctx, args, interaction_id)
    except Exception:
        logger.exception("voice studio tool %s failed for run %s", name, run_id)
        result = {"ok": False, "error": "tool_failed"}
    try:
        persist.record_voice_tool_call(
            interaction_id=interaction_id,
            turn_index=0,
            tool_name=name,
            result_ok=bool(result.get("ok")),
            error=result.get("error"),
            latency_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
            args=args,
            channel=str(ctx.get("channel") or "voice"),
        )
    except Exception:
        logger.exception("voice studio tool %s: audit write failed", name)
    return result


def transfer_destination(body: dict[str, Any]) -> dict[str, Any]:
    """Resolve the agent's transfer-to-human: record the handoff, return where to ring."""
    from voice import persist

    ctx = {k: body.get(k) for k in CONTEXT_KEYS if body.get(k) not in (None, "")}
    import voice_studio_checks

    destination = env_str("SUPERVISOR_CALLBACK_PHONE")
    if voice_studio_checks.is_test(ctx):
        return {"transfer_context": {"destination": "", "custom_message": "This is a test conversation; no one is transferred."}}
    if ctx.get("workflow_run_id"):
        interaction_id = _interaction(ctx)
        persist.record_handoff(
            interaction_id=interaction_id,
            reason=str(body.get("reason") or "customer_requested"),
            bot_id=bot_id_for(ctx.get("agent_id")),
        )
    if ctx.get("channel") == "whatsapp":  # whatsapp_studio escalates the thread to the Inbox
        return {"transfer_context": {"destination": "", "custom_message": "Connecting you to a colleague."}}
    if not destination:
        return {"transfer_context": {"destination": "", "custom_message": "No one is available right now."}}
    return {"transfer_context": {"destination": destination}}


# ---------------------------------------------------------------------------
# Pre-call: who is calling in
# ---------------------------------------------------------------------------


def precall(body: dict[str, Any]) -> dict[str, Any]:
    """Engine pre-call fetch. Inbound: identify the caller by number."""
    import db
    import db_whatsapp

    event = body.get("call_inbound") or {}
    caller = str(event.get("from_number") or "")
    context: dict[str, Any] = {"direction": "inbound", "caller_known": False}
    customer = db_whatsapp.find_customer_by_phone(caller) if caller else None
    if customer:
        customer_id = customer.get("id") or customer.get("customer_id")
        with db.engine.connect() as conn:
            account_id = conn.execute(
                text(
                    "SELECT id FROM accounts WHERE customer_id = :c "
                    "ORDER BY dpd DESC NULLS LAST, id LIMIT 1"
                ),
                {"c": customer_id},
            ).scalar()
        name = customer.get("name") or customer.get("full_name") or ""
        context.update(
            {
                "caller_known": True,
                "customer_id": customer_id,
                "account_id": account_id,
                "customer_name": name,
                "first_name": name.split(" ")[0] if name else None,
            }
        )
    return {"initial_context": {k: v for k, v in context.items() if v not in (None, "")}}


# ---------------------------------------------------------------------------
# After the call
# ---------------------------------------------------------------------------

_UNCONNECTED = {"busy", "no-answer", "failed", "canceled", "error"}


def _ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def flag_turns(interaction_id: str, ctx: dict[str, Any], pairs: list[tuple[str, str, float]],
               *, channel: str = "voice", start_index: int = 0) -> None:
    """Guardrails and live QA on each bot turn -- flags, live alerts and rule
    hits on the interaction, as the previous runtimes wrote them per turn.
    ``pairs`` = (customer text before it, bot text, seconds into the conversation)."""
    import db
    from voice import persist

    with db.engine.connect() as conn:
        verified = _identity_verified(conn, interaction_id, {"channel": channel})
    disclosed = channel != "voice"
    rules = guardrails_for(ctx.get("workflow_id") or ctx.get("agent_id"))
    for offset, (customer_text, bot_text, at_sec) in enumerate(pairs):
        try:
            flags = persist.evaluate_and_flag_bot_turn(
                interaction_id=interaction_id,
                customer_text=customer_text,
                bot_text=bot_text,
                intent="out_of_scope",
                guardrails=rules,
                turn_index=start_index + offset,
                elapsed_seconds=at_sec,
                customer_bot_exchanges=start_index + offset + 1,
                identity_verified=verified,
                channel=channel,
                customer_id=ctx.get("customer_id"),
                account_id=ctx.get("account_id"),
                direction=str(ctx.get("direction") or "inbound"),
                hours_waived=bool(ctx.get("demo")),
                recording_disclosed=disclosed,
            )
            disclosed = disclosed or "missing-recording-disclosure" not in flags
        except Exception:
            logger.exception("voice studio: guardrail check failed on %s", interaction_id)


def complete_run(body: dict[str, Any]) -> dict[str, Any]:
    """The engine's post-call webhook: file the call and advance the attempt."""
    import db
    import outbound
    from voice import persist

    run_id = body.get("workflow_run_id")
    workflow_id = body.get("workflow_id")
    if not run_id or not workflow_id:
        return {"ok": False, "error": "missing_run"}
    run = engine_call("GET", f"/workflow/{workflow_id}/runs/{run_id}") or {}
    ctx = dict(run.get("initial_context") or {})
    if ctx.get("channel") == "whatsapp":  # filed turn by turn by whatsapp_studio
        return {"ok": True, "interactionId": ctx.get("interaction_id")}
    import voice_studio_checks

    if voice_studio_checks.is_test(ctx):  # an editor test or a scripted check: not a customer contact
        return {"ok": True, "interactionId": None, "test": True}
    ctx["workflow_id"] = workflow_id
    ctx.setdefault("agent_id", workflow_id)
    gathered = run.get("gathered_context") or {}
    events = ((run.get("logs") or {}).get("realtime_feedback_events")) or []
    status = str(gathered.get("call_status") or "").lower()

    turns = [
        e for e in events
        if e.get("type") in ("rtf-bot-text", "rtf-user-transcription")
        and (e.get("type") == "rtf-bot-text" or (e.get("payload") or {}).get("final"))
        and ((e.get("payload") or {}).get("text") or "").strip()
    ]
    first_at = _ts((turns[0].get("payload") or {}).get("timestamp")) if turns else None
    last_at = _ts((turns[-1].get("payload") or {}).get("end_timestamp")) if turns else None
    duration = int((last_at - first_at).total_seconds()) if first_at and last_at else None

    connected = status not in _UNCONNECTED and bool(turns)
    interaction_id = None
    if connected:
        interaction_id = ensure_interaction(run_id, ctx, started_at=first_at)
        session_id = _session_id(run_id)
        with db.engine.connect() as conn:
            already = conn.execute(
                text("SELECT count(*) FROM interaction_transcript WHERE interaction_id = :ix"),
                {"ix": interaction_id},
            ).scalar()
        if not already:
            pairs, heard = [], ""
            for index, event in enumerate(turns):
                payload = event.get("payload") or {}
                at = _ts(payload.get("timestamp"))
                persist.append_transcript_turn(
                    interaction_id=interaction_id,
                    turn_index=index,
                    speaker="bot" if event["type"] == "rtf-bot-text" else "customer",
                    text_content=str(payload.get("text")).replace("**", "").strip(),
                    at_sec=max(0.0, (at - first_at).total_seconds()) if at and first_at else float(index),
                )
                said = str(payload.get("text")).replace("**", "").strip()
                if event["type"] == "rtf-bot-text":
                    pairs.append((heard, said, max(0.0, (at - first_at).total_seconds()) if at and first_at else 0.0))
                    heard = ""
                else:
                    heard = f"{heard} {said}".strip()
            flag_turns(interaction_id, ctx, pairs)
        recording = run.get("recording_url") or body.get("recording_url")
        if recording:
            persist.record_media(
                interaction_id=interaction_id,
                kind="audio",
                storage_ref=str(recording),
                duration_sec=duration,
                mime_type="audio/wav",
                size_bytes=None,
            )
        persist.complete_voice_call(
            session_id=session_id,
            interaction_id=interaction_id,
            status="completed",
            disposition=str(gathered.get("mapped_call_disposition") or gathered.get("call_disposition") or "") or None,
            providers=(ctx.get("runtime_configuration") or None),
        )

    if ctx.get("attempt_id"):
        carrier_status = status if status in _UNCONNECTED else "completed"
        answered_by = "machine_start" if "voicemail" in str(gathered.get("call_disposition") or "") else None
        with db.engine.begin() as conn:
            outbound.apply_provider_status(
                conn,
                provider_call_id=str(run_id),
                status="no-answer" if carrier_status == "canceled" else carrier_status,
                provider=PROVIDER,
                duration_sec=duration,
                answered_by=answered_by,
            )
    logger.info(
        "voice studio: run %s filed (status=%s, interaction=%s, attempt=%s)",
        run_id, status or "completed", interaction_id, ctx.get("attempt_id"),
    )
    return {"ok": True, "interactionId": interaction_id}
