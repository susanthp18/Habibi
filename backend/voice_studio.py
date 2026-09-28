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
import unicodedata
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


def kb_search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Passages from the Voice Studio knowledge base -- the one the agents
    answer from -- best first: document, heading, text and similarity."""
    body = engine_call("POST", "/knowledge-base/search", json={"query": query, "limit": limit}) or {}
    return [
        {
            "docTitle": c.get("filename") or "",
            "heading": (c.get("chunk_metadata") or {}).get("heading") or "",
            "snippet": c.get("chunk_text") or "",
            "score": float(c.get("similarity") or 0.0),
        }
        for c in body.get("chunks") or []
    ]


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


def _position_context(position: dict[str, Any]) -> dict[str, Any]:
    from money_inr import spoken_money

    currency = position.get("currency") or "INR"
    return {
        "account_id": position.get("accountId"),
        "account_tail": position.get("accountTail"),
        "days_past_due": position.get("dpd"),
        "currency": currency,
        "outstanding_amount": spoken_money(position.get("outstandingInr"), currency),
        "minimum_due": spoken_money(position.get("minimumDueInr"), currency),
        "minimum_due_value": position.get("minimumDueInr"),
        "product_name": position.get("productName"),
        "account_status": position.get("status"),
    }


def outbound_context(conn: Any, attempt_id: str, custom: dict[str, str]) -> dict[str, Any]:
    """The attempt's mission, flattened into the variables an engine agent's prompts use."""
    import mission as mission_mod

    return mission_context(mission_mod.load(conn, attempt_id) or {}, attempt_id, custom)


def mission_context(m: dict[str, Any], attempt_id: str, custom: dict[str, str]) -> dict[str, Any]:
    """A mission as the agent's starting variables (also the test call's preview)."""
    import mission as mission_mod

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
    from money_inr import spoken_money

    if custom.get("account_id"):
        ctx["account_id"] = custom["account_id"]
    promise = context.get("promise") or {}
    if promise:
        ctx["open_promise_date"] = promise.get("promisedDate") or promise.get("date")
        ctx["open_promise_amount"] = spoken_money(promise.get("amountInr") or promise.get("amount"),
                                                  ctx.get("currency"))
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
        raise OutboundDisabled("outbound_disabled: turn on outbound calling in Settings first")
    custom = dict(custom or {})
    attempt_id = custom.get("attempt_id") or ""
    with db.engine.connect() as conn:
        # A test call names its agent; everything else runs the objective's binding.
        workflow_id = custom.get("agent_id")
        if not workflow_id:
            binding = agent_for(conn, custom.get("objective"))
            if binding is None:
                raise NotBound(f"no Voice Studio agent is bound to objective {custom.get('objective')!r}")
            workflow_id = binding["engine_workflow_id"]
        initial_context = outbound_context(conn, attempt_id, custom) if attempt_id else {}
    initial_context["agent_id"] = int(workflow_id)

    api_key = env_str("VOICE_STUDIO_API_KEY")
    if not api_key:
        raise RuntimeError("VOICE_STUDIO_API_KEY is not set")
    import voice_studio_routing

    # Raises unless the agent is this tenant's, active and published.
    trigger_path = voice_studio_routing.outbound_trigger_path(int(workflow_id))
    payload: dict[str, Any] = {"phone_number": to, "initial_context": initial_context}
    caller = engine_number(from_number) if from_number else None
    if caller:
        payload["telephony_configuration_id"], payload["from_phone_number_id"] = caller
    resp = httpx.post(
        f"{engine_url()}/api/v1/public/agent/{trigger_path}",
        json=payload,
        headers={"X-API-Key": api_key},
        timeout=30,
    )
    if resp.status_code == 429:
        raise RuntimeError("voice_studio_busy: the engine's concurrent-call limit is reached")
    resp.raise_for_status()
    run_id = resp.json().get("workflow_run_id")
    logger.info("voice studio: attempt %s dialled as engine run %s", attempt_id, run_id)
    return {"callSid": str(run_id), "status": "initiated", "provider": PROVIDER}


def engine_numbers() -> list[dict[str, Any]]:
    """The tenant's engine phone numbers: ``{configId, id, address, active}``."""
    configs = engine_call("GET", "/organizations/telephony-configs") or {}
    configs = configs.get("configurations", []) if isinstance(configs, dict) else configs
    out = []
    for config in configs:
        found = engine_call("GET", f"/organizations/telephony-configs/{config['id']}/phone-numbers") or {}
        for number in found.get("phone_numbers", []) if isinstance(found, dict) else found:
            out.append({"configId": config["id"], "id": number["id"],
                        "address": str(number.get("address") or ""), "active": number.get("is_active", True)})
    return out


def engine_number(e164: str) -> tuple[int, int] | None:
    """The engine (config id, phone number id) for a caller ID, if the engine has it."""
    import re

    want = re.sub(r"\D+", "", e164)[-10:]
    try:
        for n in engine_numbers():
            if n["active"] and want and re.sub(r"\D+", "", n["address"])[-10:] == want:
                return int(n["configId"]), int(n["id"])
    except Exception:
        logger.warning("voice studio: caller ID %s could not be matched to an engine number", e164[-4:])
    return None


def hangup(channel_id: str) -> None:  # the engine ends its own calls
    logger.info("voice studio: hangup for run %s is handled by the engine", channel_id)


def warm_transfer(channel_id: str, *, reason: str = "customer_requested") -> dict[str, Any]:
    # Transfers happen inside the call through the agent's transfer tool,
    # resolved by `transfer_destination` below.
    return {"ok": False, "reason": "transfer_is_in_call", "channelId": channel_id}


def default_from_number() -> str:
    return env_str("TWILIO_PHONE_NUMBER")


#: The engine's one inbound webhook: it resolves the org from the account and
#: the agent from the called number's Voice Studio routing.
ENGINE_INBOUND_PATH = "/api/v1/telephony/inbound/run"


def inbound_handoff_twiml() -> str | None:
    """TwiML that hands an inbound call PayInt's webhook received to the engine,
    or None when the engine's public URL is not configured. Twilio signs the
    redirected request for its new URL, so the engine verifies it as its own."""
    from xml.sax.saxutils import escape

    base = env_str("AGENTSTUDIO_PUBLIC_URL").rstrip("/")
    if not base.startswith("https://") and not base.startswith("http://"):
        return None
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        f'  <Redirect method="POST">{escape(base + ENGINE_INBOUND_PATH)}</Redirect>\n'
        "</Response>\n"
    )


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
    from env_utils import is_prod

    if is_prod():
        # The compose file falls back to these committed values when unset.
        weak = [k for k in ("AGENTSTUDIO_INTERNAL_SECRET", "VOICE_STUDIO_HOOK_TOKEN")
                if env_str(k).startswith("dev-only")]
        if weak:
            problems.append(f"{', '.join(weak)} still hold the committed dev-only default in production")
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
            from db_core import UNKNOWN_CALLER_ID

            known = persist.resolve_known_customer(ctx.get("customer_id"))
            if known:
                # Opened by the call-started notice before the pre-call lookup
                # named the caller: join it to them as soon as a hook knows.
                conn.execute(text(
                    "UPDATE interactions SET customer_id = :c, account_id = COALESCE(account_id, :a), "
                    "updated_at = now() WHERE id = :ix AND (customer_id = :u OR customer_id LIKE :u || ':%')"
                ), {"c": known, "a": ctx.get("account_id"), "ix": existing, "u": UNKNOWN_CALLER_ID})
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
        from money_inr import spoken_money

        # In the account's currency: the stored key says Inr for every account.
        out["open_promise"] = {
            "amount": spoken_money(promise.get("amountInr"), out.get("currency")),
            **{k: v for k, v in promise.items() if k != "amountInr"},
        }
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


def ascii_digits(value: Any) -> str:
    """The decimal digits in ``value`` as ASCII, whatever script they came in.

    A caller speaking Arabic, Hindi or Tamil can have their digits transcribed
    as "٤٥٦٧" or "४५६७"; stored identifiers are ASCII, so compare in ASCII.
    """
    return "".join(str(unicodedata.decimal(ch)) for ch in str(value or "") if ch.isdecimal())


def _tool_verify_identity(ctx: dict[str, Any], args: dict[str, Any], interaction_id: str) -> dict[str, Any]:
    import db
    from voice import persist

    method = str(args.get("method") or "phone_last4").lower()
    value = ascii_digits(args.get("value"))
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


def _amount(value: Any) -> float | None:
    """A positive amount the model passed, or None (it is optional)."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


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
        bot_id=_ctx_bot_id(ctx),
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
    said = str(args.get("type") or "").strip().lower()
    result = domain.flag_dispute(
        customer_id=str(ctx.get("customer_id") or ""),
        dispute_type=DISPUTE_ALIASES.get(said, said),
        interaction_id=interaction_id,
        account_id=ctx.get("account_id"),
        amount=_amount(args.get("amount")),
        summary=args.get("summary"),
        source="bot",
        idempotency_key=f"vs-{ctx.get('workflow_run_id')}-dispute",
    )
    return result.to_llm()


def _tool_record_opt_out(ctx: dict[str, Any], args: dict[str, Any], interaction_id: str) -> dict[str, Any]:
    """The person asked us to stop contacting them: record it, now.

    No identity check: this only restricts contact and discloses nothing, and
    whoever answers the registered number or WhatsApp thread may ask for it.
    ``scope`` "all" closes every channel; the default closes this one.
    Contact policy then blocks further calls and messages on it.
    """
    import actor_context
    import db

    customer_id = str(ctx.get("customer_id") or "")
    if not customer_id:
        return {"ok": False, "error": "no_customer",
                "say": "Apologise, say you will pass the request on, and end the conversation politely."}
    whatsapp = ctx.get("channel") == "whatsapp"
    scope = str(args.get("scope") or "this_channel").lower()
    channel = "all" if scope == "all" else ("whatsapp" if whatsapp else "call")
    # The activity log's actor must be a registered bot (activity_events.actor_bot_id
    # references bots): the agent's own row, as its interactions and promises name it.
    with db.engine.begin() as conn:
        bot_id = ensure_bot(conn, ctx.get("agent_id") or ctx.get("workflow_id"))
    actor_context.bind_service_actor("bot", bot_id=bot_id)
    try:
        db.opt_out(customer_id, {
            "channel": channel,
            "source": "WhatsApp Reply" if whatsapp else "Agent",
            "note": f"Asked the Voice Studio agent to stop contact (interaction {interaction_id}).",
        })
    except KeyError:
        return {"ok": False, "error": "no_customer",
                "say": "Apologise, say you will pass the request on, and end the conversation politely."}
    return {"ok": True, "channel": channel,
            "say": ("Confirm they will not be contacted on this channel again"
                    if channel != "all" else "Confirm they will not be contacted again")
                   + ", thank them, and end the conversation."}


def _tool_request_documents(ctx: dict[str, Any], args: dict[str, Any], interaction_id: str) -> dict[str, Any]:
    """Operations sends a statement, certificate or letter (the Document desk)."""
    from agent_core.tools import domain

    if (blocked := _require_verified(interaction_id, ctx)) is not None:
        return blocked
    doc_type = str(args.get("type") or "").strip().lower()
    result = domain.request_documents(
        customer_id=str(ctx.get("customer_id") or ""),
        document_type=doc_type,
        interaction_id=interaction_id,
        account_id=ctx.get("account_id"),
        # On WhatsApp the thread is the natural place for it to arrive.
        delivery_channel=str(args.get("channel") or ("whatsapp" if ctx.get("channel") == "whatsapp" else "")) or None,
        period=args.get("period"),
        requested_via="bot_chat" if ctx.get("channel") == "whatsapp" else "bot_voice",
        idempotency_key=f"vs-{ctx.get('workflow_run_id')}-doc-{doc_type}",
    )
    return result.to_llm()


def _product_id(said: str) -> str | None:
    """The catalogue product the customer named: its id, its name, or the one
    active product whose name contains what they said."""
    import db

    said = said.strip()
    if not said:
        return None
    with db.engine.connect() as conn:
        exact = conn.execute(text(
            "SELECT id FROM products WHERE is_active AND (lower(id) = lower(:s) OR lower(name) = lower(:s)) LIMIT 1"
        ), {"s": said}).scalar()
        if exact:
            return str(exact)
        loose = conn.execute(text(
            "SELECT id FROM products WHERE is_active AND name ILIKE '%' || :s || '%' LIMIT 2"
        ), {"s": said}).scalars().all()
    return str(loose[0]) if len(loose) == 1 else None


def _tool_capture_lead(ctx: dict[str, Any], args: dict[str, Any], interaction_id: str) -> dict[str, Any]:
    """The customer is interested in a product: a lead for Upsell & leads,
    after the same eligibility and consent re-check every channel gets."""
    import db
    from agent_core.tools import domain

    if (blocked := _require_verified(interaction_id, ctx)) is not None:
        return blocked
    product_id = _product_id(str(args.get("product") or ""))
    if product_id is None:
        with db.engine.connect() as conn:
            names = conn.execute(text("SELECT name FROM products WHERE is_active ORDER BY name")).scalars().all()
        return {"ok": False, "error": "product_not_found", "products": list(names),
                "say": "Ask which of these products they mean, or note their interest and move on."}
    whatsapp = ctx.get("channel") == "whatsapp"
    result = domain.capture_lead(
        customer_id=str(ctx.get("customer_id") or ""),
        product_id=product_id,
        interaction_id=interaction_id,
        bot_id=_ctx_bot_id(ctx),
        offer_amount=_amount(args.get("amount")),
        summary=args.get("summary"),
        source="bot_chat" if whatsapp else "bot_voice",
        channel="whatsapp" if whatsapp else "voice",
        idempotency_key=f"vs-{ctx.get('workflow_run_id')}-lead-{product_id}",
    )
    return result.to_llm()


#: The words an agent may use for a dispute, onto the ledger's types.
DISPUTE_ALIASES = {
    "already_paid": "paid_already",
    "amount_mismatch": "wrong_amount",
    "not_my_transaction": "not_my_account",
    "duplicate": "duplicate_charge",
    "waiver": "fee_waiver",
}


TOOLS = {
    "account_position": _tool_account_position,
    "verify_identity": _tool_verify_identity,
    "promise_to_pay": _tool_promise_to_pay,
    "request_callback": _tool_request_callback,
    "flag_dispute": _tool_flag_dispute,
    "record_opt_out": _tool_record_opt_out,
    "request_documents": _tool_request_documents,
    "capture_lead": _tool_capture_lead,
}

#: Engine-injected call ids, never supplied by the model.
CONTEXT_KEYS = ("workflow_run_id", "workflow_id", "agent_id", "attempt_id", "customer_id",
                "account_id", "direction", "demo", "channel", "interaction_id", "conversation_id", "rehearsal")


def _verified_caller(interaction_id: str) -> dict[str, str]:
    """An inbound caller precall could not name, once ``verify_identity`` has
    matched them: the engine keeps its initial context for the whole call, so
    every later tool would otherwise write for no customer."""
    import db

    with db.engine.connect() as conn:
        row = conn.execute(text(
            "SELECT v.customer_id, i.account_id FROM identity_verifications v "
            "JOIN interactions i ON i.id = v.interaction_id "
            "WHERE v.interaction_id = :ix AND v.status = 'verified' AND v.customer_id <> '' "
            "ORDER BY v.created_at DESC LIMIT 1"
        ), {"ix": interaction_id}).first()
    if row is None:
        return {}
    return {k: v for k, v in (("customer_id", row.customer_id), ("account_id", row.account_id)) if v}


def _ctx_bot_id(ctx: dict[str, Any]) -> str:
    """The bots row ensure_interaction registered for this call's agent."""
    return bot_id_for(ctx.get("agent_id") or ctx.get("workflow_id"))


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
    if not ctx.get("customer_id"):
        ctx.update(_verified_caller(interaction_id))
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
            bot_id=_ctx_bot_id(ctx),
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


def call_languages(gathered: dict[str, Any], turns: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The languages of a multilingual call, for the interaction record and QA:
    those heard, how often the caller switched, and each transcript turn's
    language (by turn index). None for a call with no language evidence."""
    by_turn = [(e.get("payload") or {}).get("language") for e in turns]
    spoken = list(gathered.get("languages_spoken") or []) or list(dict.fromkeys(
        lang for e, lang in zip(turns, by_turn) if lang and e.get("type") == "rtf-user-transcription"))
    if not spoken:
        return None
    return {"spoken": spoken, "switches": int(gathered.get("language_switches") or 0), "turns": by_turn}


def test_numbers(conn: Any) -> set[str]:
    """The tenant's test handsets (last 10 digits): Settings' list, plus the
    deprecated ``VOICE_STUDIO_TEST_NUMBERS`` env for one release."""
    import re

    import db

    found = {re.sub(r"\D+", "", n)[-10:] for n in env_str("VOICE_STUDIO_TEST_NUMBERS").split(",") if n.strip()}
    if conn.execute(text("SELECT to_regclass('test_numbers')")).scalar():
        found |= {
            re.sub(r"\D+", "", r)[-10:]
            for r in conn.execute(text("SELECT e164 FROM test_numbers WHERE tenant_id = :t"),
                                  {"t": db.current_tenant()}).scalars()
        }
    return {n for n in found if n}


def admit_engine_call(body: dict[str, Any]) -> dict[str, Any]:
    """May the engine dial this number? For calls the engine starts itself
    (its own campaigns, the editor's "call phone"); PayInt's dialler admits
    its calls in ``outbound.place`` and passes the attempt id, so those are
    not admitted twice.

    A number that is a customer goes through the same contact policy as every
    other contact (DND, consent, calling window, frequency caps), and the call
    is counted in the ledger. A number that is not a customer is refused unless
    it is one of the tenant's test numbers (``VOICE_STUDIO_TEST_NUMBERS``):
    the engine does not dial strangers on the bank's behalf.
    """
    import re

    import contact_policy
    import db
    import platform_switches
    from db_whatsapp import _find_customer_by_phone

    # The master switch covers every dial, the engine's own included.
    if not platform_switches.outbound_enabled():
        return {"admitted": False, "reason": "outbound_disabled"}
    digits = re.sub(r"\D+", "", str(body.get("to_number") or ""))
    with db.engine.begin() as conn:
        if body.get("attempt_id"):
            # PayInt's dialler already gated this call, but only a real attempt
            # it reserved moments ago for this number counts; anything else is
            # admitted like any other engine call.
            owned = conn.execute(text(
                "SELECT 1 FROM call_attempts WHERE id = :a AND tenant_id = :t "
                "AND state IN ('reserved', 'dialing') AND to_phone_last4 = :l4 "
                "AND reserved_at > now() - interval '15 minutes' "
                "AND (provider_call_id IS NULL OR provider_call_id = :run)"
            ), {"a": str(body["attempt_id"]), "t": db.current_tenant(), "l4": digits[-4:],
                "run": str(body.get("workflow_run_id") or "")}).first()
            if owned:
                return {"admitted": True, "reason": "payint_dialler"}
        if digits and digits[-10:] in test_numbers(conn):
            db._activity(conn, "voice_studio_run", str(body.get("workflow_run_id") or ""), "test_call_admitted",
                         "Engine test call to an allow-listed number", f"…{digits[-4:]}")
            return {"admitted": True, "reason": "test_number"}
        customer = _find_customer_by_phone(conn, digits)
        if customer is None:
            db._activity(conn, "voice_studio_run", str(body.get("workflow_run_id") or ""), "engine_call_refused",
                         "Engine call refused: not a customer or test number", f"…{digits[-4:]}")
            return {"admitted": False, "reason": "unknown_number"}
        decision = contact_policy.admit(
            conn,
            customer_id=customer["id"],
            channel="voice",
            purpose="outreach",
            source="voice-studio-engine",
            related_id=f"engine-run:{body.get('workflow_run_id')}",
            endpoint=digits,
        )
    return {"admitted": bool(decision.allowed), "reason": decision.reason, "customerId": customer["id"]}


#: The engine's knowledge-base tool; each call is one RAG hit on the interaction.
KB_TOOL = "retrieve_from_knowledge_base"


def transcript_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The run's spoken turns in order: every bot utterance and every final
    customer transcription. Turn ``i`` here is ``interaction_transcript``
    turn_index ``i``; the call-intelligence pass relies on that to read the
    unmasked words back from the engine."""
    return [
        e for e in events
        if e.get("type") in ("rtf-bot-text", "rtf-user-transcription")
        and (e.get("type") == "rtf-bot-text" or (e.get("payload") or {}).get("final"))
        and ((e.get("payload") or {}).get("text") or "").strip()
    ]


def spoken_text(event: dict[str, Any]) -> str:
    """A turn's words as filed (markdown emphasis the agent emits is not spoken)."""
    return str((event.get("payload") or {}).get("text") or "").replace("**", "").strip()


def _engine_pcm(key: str) -> tuple[bytes, int, int]:
    """(pcm, sample rate, channels) of a 16-bit WAV the engine stored.

    The engine and PayInt share one MinIO; the engine writes to its own bucket.
    """
    import io
    import wave

    import storage

    data = storage.get_bytes(f"minio://{env_str('AGENTSTUDIO_AUDIO_BUCKET', 'agentstudio-audio')}/{key}")
    with wave.open(io.BytesIO(data)) as wf:
        if wf.getsampwidth() != 2:
            raise ValueError(f"{key}: expected 16-bit PCM, got {8 * wf.getsampwidth()}-bit")
        return wf.readframes(wf.getnframes()), wf.getframerate(), wf.getnchannels()


def file_recording(interaction_id: str, run: dict[str, Any]) -> dict[str, Any] | None:
    """Copy the call audio into PayInt's recordings bucket, once.

    Stereo (customer left, agent right) from the engine's aligned per-speaker
    tracks, like the previous runtime wrote, so redaction can beep one speaker
    and QA can tell who spoke. The copy is the evidence Audit, Redaction and
    exports read: hashed, sized and under PayInt's retention, whatever the
    engine later does with its own files.
    """
    import db
    from voice import recording

    with db.engine.connect() as conn:
        if conn.execute(
            text("SELECT 1 FROM interaction_media WHERE interaction_id = :ix AND kind = 'audio' "
                 "AND (storage_ref LIKE 'minio://%' OR storage_ref LIKE 'local://%')"),
            {"ix": interaction_id},
        ).first():
            return None
    user_key, bot_key = run.get("user_recording_url"), run.get("bot_recording_url")
    try:
        if user_key and bot_key:
            user, rate, _ = _engine_pcm(str(user_key))
            bot, bot_rate, _ = _engine_pcm(str(bot_key))
            if rate != bot_rate:
                raise ValueError(f"track rates differ: user {rate} Hz, bot {bot_rate} Hz")
            return recording.upload_recording(
                interaction_id=interaction_id,
                pcm=recording._interleave_stereo(user, bot),
                sample_rate=rate,
                num_channels=2,
            )
        if run.get("recording_url"):
            pcm, rate, channels = _engine_pcm(str(run["recording_url"]))
            return recording.upload_recording(
                interaction_id=interaction_id, pcm=pcm, sample_rate=rate, num_channels=channels
            )
    except Exception:
        # The transcript and outcome still file; the reconciliation sweep retries.
        logger.exception("voice studio: recording for run %s not filed", run.get("id"))
    return None


def meter_run(interaction_id: str | None, run: dict[str, Any]) -> None:
    """The call's model, speech, recognition and carrier spend, from the engine's usage.

    Idempotent: it meters only what is not yet metered for this run, so the
    reconcile sweep can call it again and pick up what arrived later (the QA
    node's tokens are merged into the run after the completion hook).
    """
    import usage_meter

    import db

    usage = run.get("usage_info") or {}
    ref = f"voice-studio-run:{run.get('id')}"
    usage_meter.flush()  # what is still buffered counts as already metered
    with db.engine.connect() as conn:
        # One meterer per run at a time: the hook and the sweep can overlap.
        conn.execute(text("SELECT pg_advisory_lock(hashtext(:r))"), {"r": ref})
        try:
            seen: dict[tuple[str, str], dict[str, float]] = {}
            for row in conn.execute(text(
                "SELECT service_id, COALESCE(model, '') AS model, sum(units) AS units, "
                "sum((meta->>'promptTokens')::numeric) AS p, sum((meta->>'completionTokens')::numeric) AS c, "
                "sum((meta->>'cachedTokens')::numeric) AS k, sum((meta->>'chars')::numeric) AS ch "
                "FROM usage_events WHERE source_ref = :r GROUP BY 1, 2"
            ), {"r": ref}).mappings():
                seen[(row["service_id"], row["model"])] = {k: float(row[k] or 0) for k in ("units", "p", "c", "k", "ch")}
            _meter_delta(usage, ref, interaction_id, seen)
            usage_meter.flush()
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(hashtext(:r))"), {"r": ref})


def price_runs(body: bytes) -> bytes:
    """A page of engine runs with each run's metered cost as ``charge_usd``
    (INR metered in ``usage_events``, shown in the engine's dollars at the
    configured FX)."""
    import json

    import db
    import usage_meter

    data = json.loads(body or b"null")
    runs = data.get("runs") if isinstance(data, dict) else None
    if not runs:
        return body
    refs = [f"voice-studio-run:{r.get('id')}" for r in runs if isinstance(r, dict)]
    with db.engine.connect() as conn:
        cost = {row[0]: row[1] for row in conn.execute(text(
            "SELECT source_ref, sum(cost_inr) FROM usage_events WHERE source_ref = ANY(:r) GROUP BY 1"
        ), {"r": refs})}
    fx = float(usage_meter.fx_rate_decimal())
    for r in runs:
        inr = cost.get(f"voice-studio-run:{r.get('id')}") if isinstance(r, dict) else None
        if inr is not None:
            r["charge_usd"] = round(float(inr) / fx, 4)
    return json.dumps(data, default=str).encode()


def _meter_delta(usage: dict[str, Any], ref: str, interaction_id: str | None,
                 seen: dict[tuple[str, str], dict[str, float]]) -> None:
    import usage_meter as um

    none = {"units": 0.0, "p": 0.0, "c": 0.0, "k": 0.0, "ch": 0.0}
    for service, u in (usage.get("llm") or {}).items():
        model = str(service).rsplit("|||", 1)[-1] or ""
        was = seen.get((um.SERVICE_CHAT, model), none)
        p = int(u.get("prompt_tokens") or 0) - int(was["p"])
        c = int(u.get("completion_tokens") or 0) - int(was["c"])
        k = int(u.get("cache_read_input_tokens") or 0) - int(was["k"])
        if p > 0 or c > 0:
            um.record_chat_usage(prompt_tokens=max(p, 0), completion_tokens=max(c, 0), model=model or None,
                                 cached_tokens=max(k, 0), source_ref=ref, interaction_id=interaction_id)
    for service, chars in (usage.get("tts") or {}).items():
        voice = str(service).rsplit("|||", 1)[-1] or ""
        extra = int(chars or 0) - int(seen.get((um.SERVICE_TTS, voice), none)["ch"])
        if extra > 0:
            um.record_tts_usage(chars=extra, voice=voice or None, source_ref=ref, interaction_id=interaction_id)
    # Streaming recognition listens for the whole call; the engine reports no
    # separate STT usage for Azure, so the call length is the billed quantity.
    # The same length is the carrier's billed minutes.
    minutes = float(usage.get("call_duration_seconds") or 0) / 60.0
    stt = minutes - seen.get((um.SERVICE_STT, "streaming"), none)["units"]
    if stt > 0.001:
        um.record_stt_usage(audio_bytes=0, minutes=stt, source_ref=ref,
                            interaction_id=interaction_id, model="streaming")
    tel = minutes - seen.get((um.SERVICE_TEL, "voice-studio"), none)["units"]
    if tel > 0.001:
        um.record_telephony_usage(minutes=tel, source_ref=ref, interaction_id=interaction_id,
                                  carrier="voice-studio")


def _place_tool_calls(interaction_id: str, turn_times: list[datetime | None]) -> None:
    """Attach each tool call to the transcript turn it answered.

    Tools run live, before the transcript exists, so they are written without a
    turn; at filing each goes to the last turn that started before it ran.
    """
    import db

    with db.engine.begin() as conn:
        turns = conn.execute(
            text("SELECT id, turn_index FROM interaction_transcript WHERE interaction_id = :ix"),
            {"ix": interaction_id},
        ).all()
        ids = {int(r.turn_index): r.id for r in turns}
        calls = conn.execute(
            text("SELECT id, created_at FROM bot_tool_calls "
                 "WHERE interaction_id = :ix AND transcript_turn_id IS NULL"),
            {"ix": interaction_id},
        ).all()
        for call in calls:
            before = [i for i, at in enumerate(turn_times) if at and at <= call.created_at and i in ids]
            if before:
                conn.execute(
                    text("UPDATE bot_tool_calls SET transcript_turn_id = :t WHERE id = :id"),
                    {"t": ids[before[-1]], "id": call.id},
                )


def _version_number(workflow_id: Any, definition_id: Any) -> int | None:
    """The published version a run executed; None for a draft or when unknown."""
    if not definition_id:
        return None
    try:
        versions = engine_call("GET", f"/workflow/{workflow_id}/versions?limit=50") or []
    except httpx.HTTPError:
        logger.warning("voice studio: versions of workflow %s unavailable", workflow_id)
        return None
    return next((v.get("version_number") for v in versions if v.get("id") == definition_id), None)


def _engine_runs(since: str, until: str) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for page in range(1, 11):
        body = engine_call("GET", f"/organizations/usage/runs?start_date={since}&end_date={until}"
                                  f"&page={page}&limit=100") or {}
        runs.extend(body.get("runs") or [])
        if page >= int(body.get("total_pages") or 1):
            break
    return runs


def _workflow_resolver(runs: list[dict[str, Any]], until: str):
    """engine run id -> workflow id. The bot id carries it (``voice-studio-<id>``)
    except on calls filed before it did (plain ``voice-studio``); those are
    looked up in the engine's own run listing, a year back, fetched once."""
    from datetime import timedelta

    known = {str(r["id"]): int(r["workflow_id"]) for r in runs if r.get("workflow_id") is not None}
    wide: dict[str, int] | None = None

    def resolve(run_id: Any, handler_bot_id: Any) -> int | None:
        nonlocal wide
        suffix = str(handler_bot_id or "").removeprefix("voice-studio-")
        if suffix.isdigit():
            return int(suffix)
        if str(run_id) in known:
            return known[str(run_id)]
        if wide is None:
            since = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%S")
            wide = {str(r["id"]): int(r["workflow_id"]) for r in _engine_runs(since, until)
                    if r.get("workflow_id") is not None}
        return wide.get(str(run_id))

    return resolve


def reconcile_runs(*, hours: int = 48, settle_minutes: int = 20, limit: int = 100) -> dict[str, int]:
    """File every finished engine call the webhook missed, and repair bad audio refs.

    The webhook is the fast path; this is the guarantee. A run is due once it
    has settled (no live call lasts ``settle_minutes`` without the engine
    marking it), is a customer contact, and has no PayInt session yet.
    ``complete_run`` is idempotent, so a run the webhook files concurrently is
    filed once.
    """
    import db
    import voice_studio_checks
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    # Naive UTC: the engine compares against its naive created_at, and a "+00:00"
    # offset would arrive as a space in the query string.
    since = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    until = (now - timedelta(minutes=settle_minutes)).strftime("%Y-%m-%dT%H:%M:%S")
    runs = _engine_runs(since, until)
    workflow_of = _workflow_resolver(runs, until)
    due = [
        r for r in runs
        if (r.get("gathered_context") or {}).get("call_status")
        and (r.get("initial_context") or {}).get("channel") != "whatsapp"
        and not voice_studio_checks.is_test(r.get("initial_context") or {})
        and (r.get("recording_url") or (r.get("initial_context") or {}).get("attempt_id"))
    ]
    with db.engine.connect() as conn:
        filed = {
            row[0] for row in conn.execute(
                text("SELECT provider_call_id FROM voice_sessions WHERE id = ANY(:ids) AND status = 'ended' "
                     "UNION SELECT provider_call_id FROM call_attempts "
                     "WHERE provider = :p AND provider_call_id = ANY(:runs) "
                     "AND state NOT IN ('reserved','dialing','ringing','answered','live')"),
                {"ids": [_session_id(r["id"]) for r in due], "p": PROVIDER,
                 "runs": [str(r["id"]) for r in due]},
            )
        }
        # Calls filed before the recording fix hold the engine's bare key.
        broken = conn.execute(
            text("SELECT m.id, m.interaction_id, s.provider_call_id, i.handler_bot_id "
                 "FROM interaction_media m JOIN interactions i ON i.id = m.interaction_id "
                 "JOIN voice_sessions s ON s.interaction_id = m.interaction_id AND s.id LIKE 'VS-studio-%' "
                 "WHERE m.kind = 'audio' AND m.storage_ref NOT LIKE 'minio://%' "
                 "AND m.storage_ref NOT LIKE 'local://%' LIMIT 20")
        ).all()
    report = {"seen": len(runs), "filed": 0, "repaired": 0, "failed": 0}
    for run in [r for r in due if str(r["id"]) not in filed][:limit]:
        try:
            complete_run({"workflow_run_id": run["id"], "workflow_id": run["workflow_id"]})
            report["filed"] += 1
        except Exception:
            report["failed"] += 1
            logger.exception("voice studio reconcile: run %s not filed", run.get("id"))
    # Spend that lands after filing (the QA node's tokens are merged into the
    # run later) and editor test calls, which are never filed: meter_run only
    # adds what is not metered yet.
    report["metered"] = 0
    recent = (now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
    settled = [r for r in runs if (r.get("gathered_context") or {}).get("call_status")
               and (r.get("initial_context") or {}).get("channel") != "whatsapp"
               and str(r.get("created_at") or "") >= recent]
    for run in settled[:limit]:
        try:
            full = engine_call("GET", f"/workflow/{run['workflow_id']}/runs/{run['id']}") or {}
            with db.engine.connect() as conn:
                ix = conn.execute(text("SELECT interaction_id FROM voice_sessions WHERE id = :s"),
                                  {"s": _session_id(run["id"])}).scalar()
            meter_run(ix, full)
            report["metered"] += 1
        except Exception:
            logger.exception("voice studio reconcile: run %s not metered", run.get("id"))
    for media in broken:
        try:
            workflow_id = workflow_of(media.provider_call_id, media.handler_bot_id)
            if workflow_id is None:
                raise LookupError(f"engine run {media.provider_call_id} not in the engine's run listing")
            run = engine_call("GET", f"/workflow/{workflow_id}/runs/{media.provider_call_id}") or {}
            if file_recording(media.interaction_id, run):
                with db.engine.begin() as conn:
                    conn.execute(text("DELETE FROM interaction_media WHERE id = :id"), {"id": media.id})
                    if media.handler_bot_id != f"voice-studio-{workflow_id}":
                        # Filed as plain "voice-studio": name the agent now it is known.
                        conn.execute(text("UPDATE interactions SET handler_bot_id = :bot WHERE id = :ix"),
                                     {"bot": ensure_bot(conn, workflow_id), "ix": media.interaction_id})
                report["repaired"] += 1
        except Exception:
            report["failed"] += 1
            logger.exception("voice studio reconcile: audio of %s not repaired", media.interaction_id)
    # Calls filed before the release was recorded on the interaction: add it,
    # and redo their pass -- without it PII detection ran on the masked store
    # and could not re-mask the transcript from the words as spoken.
    with db.engine.connect() as conn:
        unmarked = conn.execute(text(
            "SELECT i.id, s.provider_call_id, i.handler_bot_id FROM interactions i "
            "JOIN voice_sessions s ON s.interaction_id = i.id AND s.id LIKE 'VS-studio-%' "
            "WHERE NOT (i.source_payload ? 'voiceStudio') "
            "AND (i.handler_bot_id LIKE 'voice-studio-%' OR i.handler_bot_id = 'voice-studio') LIMIT 50"
        )).all()
    report["provenance"] = 0
    for row in unmarked:
        workflow_id = workflow_of(row.provider_call_id, row.handler_bot_id)
        if workflow_id is None:
            logger.warning("voice studio reconcile: run %s has no known agent", row.provider_call_id)
            continue
        try:
            run = engine_call("GET", f"/workflow/{workflow_id}/runs/{row.provider_call_id}") or {}
        except httpx.HTTPError:
            logger.warning("voice studio reconcile: run %s unavailable", row.provider_call_id)
            continue
        import json

        with db.engine.begin() as conn:
            conn.execute(
                text("UPDATE interactions SET source_payload = source_payload || CAST(:p AS jsonb), "
                     "handler_bot_id = :bot WHERE id = :ix"),
                {"ix": row.id, "bot": ensure_bot(conn, workflow_id), "p": json.dumps({"voiceStudio": {
                    "engineRunId": int(row.provider_call_id), "workflowId": int(workflow_id),
                    "definitionId": run.get("definition_id"),
                    "versionNumber": _version_number(workflow_id, run.get("definition_id")),
                }})},
            )
        from call_intel import jobs as call_intel_jobs

        call_intel_jobs.enqueue(row.id, rerun=True)
        report["provenance"] += 1
    # Calls filed before the evidence chain existed get their link, in filing order.
    import evidence_chain

    with db.engine.connect() as conn:
        unchained = conn.execute(text(
            "SELECT i.id, i.source_payload->'voiceStudio' AS studio, "
            "(SELECT m.hash FROM interaction_media m WHERE m.interaction_id = i.id AND m.kind = 'audio' "
            " AND m.storage_ref LIKE 'minio://%' ORDER BY m.created_at DESC LIMIT 1) AS recording_sha "
            "FROM interactions i JOIN voice_sessions s ON s.interaction_id = i.id AND s.id LIKE 'VS-studio-%' "
            "WHERE i.source_payload ? 'voiceStudio' AND i.status IN ('completed', 'abandoned') "
            "AND NOT EXISTS (SELECT 1 FROM interaction_evidence_chain c WHERE c.interaction_id = i.id) "
            "ORDER BY i.started_at LIMIT 50"
        )).all()
    report["chained"] = 0
    for row in unchained:
        from call_intel.inputs import _engine_turns

        spoken = _engine_turns(row.studio)
        if spoken is None:
            continue
        evidence_chain.append(row.id, [(t.speaker, t.text) for t in spoken], row.recording_sha)
        report["chained"] += 1
    # Calls filed before the call-intelligence pass existed, or whose enqueue
    # failed, join the queue.
    with db.engine.begin() as conn:
        report["queued"] = conn.execute(text(
            "INSERT INTO call_intelligence_jobs (id, tenant_id, interaction_id) "
            "SELECT 'CIJ-' || substr(md5(i.id), 1, 12), i.tenant_id, i.id FROM interactions i "
            "JOIN voice_sessions s ON s.interaction_id = i.id AND s.id LIKE 'VS-studio-%' "
            "WHERE i.status IN ('completed', 'abandoned') "
            "AND NOT EXISTS (SELECT 1 FROM call_intelligence_jobs j WHERE j.interaction_id = i.id) "
            "LIMIT 200 ON CONFLICT (interaction_id) DO NOTHING"
        )).rowcount
    if broken:
        # A webhook retry could file the bare key twice; once a readable copy
        # exists every unreadable row for that call is dead weight.
        with db.engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM interaction_media m WHERE m.id = ANY(:ids) AND EXISTS ("
                " SELECT 1 FROM interaction_media g WHERE g.interaction_id = m.interaction_id"
                " AND g.kind = 'audio' AND g.storage_ref LIKE 'minio://%')"
            ), {"ids": [b.id for b in broken]})
    return report


def call_started(body: dict[str, Any]) -> dict[str, Any]:
    """The engine's call-started notice: the call is on the floor from its
    first second (supervisors can listen in), not from its first tool call."""
    import voice_studio_checks

    run_id = body.get("workflow_run_id")
    if not run_id:
        return {"ok": False, "error": "missing_run"}
    ctx = dict(body.get("initial_context") or {})
    if ctx.get("channel") == "whatsapp" or voice_studio_checks.is_test(ctx):
        return {"ok": True, "interactionId": None}
    ctx["workflow_run_id"] = run_id
    if body.get("workflow_id"):
        ctx["workflow_id"] = body["workflow_id"]
        ctx.setdefault("agent_id", body["workflow_id"])
    return {"ok": True, "interactionId": ensure_interaction(run_id, ctx)}


def complete_run(body: dict[str, Any]) -> dict[str, Any]:
    """The engine's post-call webhook: file the call and advance the attempt.

    One filer per run at a time. The engine's own notice and a leftover
    webhook node arrived together for runs 58 and 59: both passed the
    "already filed?" reads, and the second died inserting the transcript
    (interaction_transcript_pkey) with a 500. Serialised, the second sees
    the call filed and returns ``duplicate``.
    """
    import db

    run_id = body.get("workflow_run_id")
    if not run_id or not body.get("workflow_id"):
        return {"ok": False, "error": "missing_run"}
    ref = f"voice-studio-file:{run_id}"
    with db.engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(hashtext(:r))"), {"r": ref})
        try:
            return _complete_run(body)
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(hashtext(:r))"), {"r": ref})


def _complete_run(body: dict[str, Any]) -> dict[str, Any]:
    import db
    import outbound
    from voice import persist

    run_id = body.get("workflow_run_id")
    workflow_id = body.get("workflow_id")
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

    turns = transcript_events(events)
    first_at = _ts((turns[0].get("payload") or {}).get("timestamp")) if turns else None
    last_at = _ts((turns[-1].get("payload") or {}).get("end_timestamp")) if turns else None
    measured = (run.get("usage_info") or {}).get("call_duration_seconds")
    duration = (int(round(float(measured))) if measured is not None
                else int((last_at - first_at).total_seconds()) if first_at and last_at else None)
    # The engine measures the gap from the caller stopping to the agent
    # speaking once per turn; it becomes that bot turn's response time.
    latency_ms = {
        e.get("turn"): int(float((e.get("payload") or {}).get("latency_seconds") or 0) * 1000)
        for e in events if e.get("type") == "rtf-latency-measured"
    }
    rag_hits = sum(
        1 for e in events
        if e.get("type") == "rtf-function-call-end" and (e.get("payload") or {}).get("function_name") == KB_TOOL
    )

    connected = status not in _UNCONNECTED and bool(turns)
    interaction_id = None
    if connected:
        interaction_id = ensure_interaction(run_id, ctx, started_at=first_at)
        session_id = _session_id(run_id)
        with db.engine.connect() as conn:
            filed = conn.execute(
                text("SELECT status FROM voice_sessions WHERE id = :id"), {"id": session_id}
            ).scalar() == "ended"
        if filed:
            # A redelivered notice (the engine's retry, the reconcile sweep, the
            # seeded webhook node): the call is filed once, and re-completing it
            # would move its end time and re-add its media.
            logger.info("voice studio: run %s already filed as %s", run_id, interaction_id)
            return {"ok": True, "interactionId": interaction_id, "duplicate": True}
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
                is_bot = event["type"] == "rtf-bot-text"
                persist.append_transcript_turn(
                    interaction_id=interaction_id,
                    turn_index=index,
                    speaker="bot" if is_bot else "customer",
                    text_content=spoken_text(event),
                    at_sec=max(0.0, (at - first_at).total_seconds()) if at and first_at else float(index),
                    ttfb_ms=latency_ms.get(event.get("turn")) if is_bot else None,
                )
                said = spoken_text(event)
                if event["type"] == "rtf-bot-text":
                    pairs.append((heard, said, max(0.0, (at - first_at).total_seconds()) if at and first_at else 0.0))
                    heard = ""
                else:
                    heard = f"{heard} {said}".strip()
            flag_turns(interaction_id, ctx, pairs)
            _place_tool_calls(interaction_id, [_ts((e.get("payload") or {}).get("timestamp")) for e in turns])
            meter_run(interaction_id, run)
            import json

            # Which agent release handled the call: per-version quality in
            # Voice Studio, and the Audit record's routing, key off this.
            provenance = {"voiceStudio": {
                "engineRunId": run_id,
                "workflowId": workflow_id,
                "definitionId": run.get("definition_id"),
                "versionNumber": _version_number(workflow_id, run.get("definition_id")),
            }}
            languages = call_languages(gathered, turns)
            if languages:
                provenance["languages"] = languages
            with db.engine.begin() as conn:
                conn.execute(
                    text("UPDATE interactions SET source_payload = source_payload || CAST(:p AS jsonb) "
                         "WHERE id = :ix"),
                    {"p": json.dumps(provenance), "ix": interaction_id},
                )
        file_recording(interaction_id, run)
        try:
            import evidence_chain

            with db.engine.connect() as conn:
                recording_sha = conn.execute(
                    text("SELECT hash FROM interaction_media WHERE interaction_id = :ix AND kind = 'audio' "
                         "AND storage_ref LIKE 'minio://%' ORDER BY created_at DESC LIMIT 1"),
                    {"ix": interaction_id},
                ).scalar()
            # The words as spoken and the recording, chained: Audit's "immutable" is checkable.
            evidence_chain.append(
                interaction_id,
                [("bot" if e["type"] == "rtf-bot-text" else "customer", spoken_text(e)) for e in turns],
                recording_sha,
            )
        except Exception:
            logger.exception("voice studio: evidence chain link not written for %s", interaction_id)
        spoken = [v for v in latency_ms.values() if v > 0]
        with db.engine.begin() as conn:
            # A call the agent handed to a person was escalated, whatever its
            # exit node called it (a supervisor's takeover it got back is not).
            # Its handoff ends with it: the hub lists live calls only.
            handed = conn.execute(text(
                "SELECT 1 FROM interaction_handoffs WHERE interaction_id = :ix "
                "AND queue IS DISTINCT FROM 'Supervisor barge' LIMIT 1"
            ), {"ix": interaction_id}).first() is not None
            conn.execute(text(
                "UPDATE interaction_handoffs SET completed_at = now() "
                "WHERE interaction_id = :ix AND completed_at IS NULL"
            ), {"ix": interaction_id})
        persist.complete_voice_call(
            session_id=session_id,
            interaction_id=interaction_id,
            status="completed",
            disposition="escalated" if handed else (
                str(gathered.get("mapped_call_disposition") or gathered.get("call_disposition") or "") or None),
            providers=(ctx.get("runtime_configuration") or None),
            duration_sec=duration,
            latency_ms=int(sorted(spoken)[len(spoken) // 2]) if spoken else None,
            rag_hits=rag_hits,
        )
        try:
            from call_intel import jobs as call_intel_jobs

            # PII masking, the redacted recording, signals and QA: the batch pass.
            call_intel_jobs.enqueue(interaction_id)
        except Exception:
            logger.exception("voice studio: call intelligence not queued for %s", interaction_id)
    else:
        # Opened when the call started (or by a tool), but nobody spoke: it
        # leaves the floor as abandoned instead of waiting for the reaper.
        with db.engine.connect() as conn:
            opened = conn.execute(text(
                "SELECT interaction_id FROM voice_sessions WHERE id = :id AND status IN ('starting', 'live')"
            ), {"id": _session_id(run_id)}).scalar()
        if opened:
            interaction_id = str(opened)
            persist.complete_voice_call(
                session_id=_session_id(run_id), interaction_id=interaction_id,
                status="abandoned", duration_sec=duration,
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
