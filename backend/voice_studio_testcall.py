"""Settings' test call: ring one of the tenant's test handsets with a chosen
Voice Studio agent, through the same gates as every other call.

Not a shortcut around the dialler. It builds the mission, reserves an attempt,
runs the contact policy and the master switch, and dials through
``outbound.place`` -> ``voice_studio.originate``, so what the room watches is
the product. The test numbers are also the engine's own allow-list for its
editor test calls (``voice_studio.test_numbers``).

Waivers. Frequency (cooling-off, daily and weekly caps) is always waived: the
number is a handset the operator holds, and a second rehearsal is the cap
applying to the wrong person. Calling hours and the borrower's window are
waived only behind the ``outbound.demo_ignores_window`` switch. Consent,
opt-out, DND and the registry are never waived.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy import text

import db

logger = logging.getLogger(__name__)


def _digits(value: str) -> str:
    return re.sub(r"\D+", "", value or "")


def waivers() -> frozenset[str]:
    """The contact-policy refusals a test call overrides right now."""
    import contact_policy
    import platform_switches

    frequency = {contact_policy.REASON_COOLING, contact_policy.REASON_DAILY, contact_policy.REASON_WEEKLY}
    if platform_switches.demo_ignores_window():
        frequency |= {contact_policy.REASON_HOURS, contact_policy.REASON_WINDOW}
    return frozenset(frequency)


# ---------------------------------------------------------------------------
# Test numbers
# ---------------------------------------------------------------------------


def list_numbers() -> list[dict[str, Any]]:
    """Each test handset, with the customer on file for it and whether a call would pass now."""
    import db_outbound

    tenant = db.current_tenant()
    with db.engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, e164, label, added_by_user_id, created_at FROM test_numbers "
            "WHERE tenant_id = :t ORDER BY created_at"
        ), {"t": tenant}).mappings().all()
    out = []
    waived = waivers()
    for r in rows:
        customer = db_outbound.demo_customer(_digits(r["e164"]), tenant_id=tenant)
        verdict: dict[str, Any] = {"blocked": None, "waived": None}
        if customer:
            try:
                v = db_outbound.demo_policy_verdict(customer["id"])
                reason = None if v.allowed else (v.reason or "contact_policy")
                verdict = {"blocked": None, "waived": reason} if reason in waived else {"blocked": reason, "waived": None}
            except Exception:
                logger.exception("test call: contact policy dry-run failed")
                verdict = {"blocked": "policy_unavailable", "waived": None}
        out.append({
            "id": r["id"], "e164": r["e164"], "label": r["label"],
            "addedBy": r["added_by_user_id"],
            "createdAt": r["created_at"].isoformat() if r["created_at"] else None,
            "customer": customer, **verdict,
        })
    return out


def add_number(e164: str, label: str | None, actor: str | None) -> list[dict[str, Any]]:
    import outbound

    number = outbound.to_e164(e164)
    if not 8 <= len(_digits(number)) <= 15:
        raise ValueError("Enter a full phone number with its country code")
    with db.engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO test_numbers (id, tenant_id, e164, label, added_by_user_id) "
            "VALUES (:id, :t, :n, :l, :u) ON CONFLICT (tenant_id, e164) DO UPDATE SET label = EXCLUDED.label"
        ), {"id": f"TN-{uuid.uuid4().hex[:12]}", "t": db.current_tenant(), "n": number,
            "l": (label or "").strip()[:80] or None, "u": actor})
        db._activity(conn, "platform", "test_numbers", "test_number_added",
                     "Test number added", f"…{_digits(number)[-4:]}")
    return list_numbers()


def remove_number(number_id: str) -> list[dict[str, Any]]:
    with db.engine.begin() as conn:
        gone = conn.execute(text("DELETE FROM test_numbers WHERE id = :id AND tenant_id = :t RETURNING e164"),
                            {"id": number_id, "t": db.current_tenant()}).scalar()
        if gone is None:
            raise KeyError("test_number_not_found")
        db._activity(conn, "platform", "test_numbers", "test_number_removed",
                     "Test number removed", f"…{_digits(gone)[-4:]}")
    return list_numbers()


def _number(number_id: str) -> dict[str, Any]:
    with db.engine.connect() as conn:
        row = conn.execute(text("SELECT id, e164 FROM test_numbers WHERE id = :id AND tenant_id = :t"),
                           {"id": number_id, "t": db.current_tenant()}).mappings().first()
    if row is None:
        raise KeyError("test_number_not_found")
    return dict(row)


# ---------------------------------------------------------------------------
# The call
# ---------------------------------------------------------------------------


def options() -> dict[str, Any]:
    """Everything the panel needs to choose and to say whether a call can go."""
    import mission as mission_mod
    import platform_switches
    import voice_studio
    import voice_studio_routing

    problems = list(voice_studio.preflight())
    try:
        routing = voice_studio_routing.list_routing()
    except Exception as exc:
        logger.exception("test call: Voice Studio unreachable")
        routing = {"agents": [], "bindings": []}
        problems.append(f"Voice Studio could not be reached: {exc}")
    try:
        if not any(n["active"] for n in voice_studio.engine_numbers()):
            problems.append("Voice Studio has no active phone number to call from (Telephony)")
    except Exception:
        problems.append("Voice Studio telephony could not be read")
    objectives = sorted({b["objective"] for b in routing["bindings"] if b["objective"] not in ("*", "whatsapp")}
                        | set(mission_mod.OBJECTIVE_BRIEF))
    return {
        "outboundEnabled": platform_switches.outbound_enabled(),
        "ignoresWindow": platform_switches.demo_ignores_window(),
        "agents": routing["agents"],
        "bindings": [b for b in routing["bindings"] if b["objective"] != "whatsapp"],
        "objectives": objectives,
        "numbers": list_numbers(),
        "problems": problems,
    }


def _mission(conn: Any, customer_id: str | None, objective: str, agent_id: int) -> tuple[dict[str, Any], str | None]:
    import mission as mission_mod
    import voice_studio

    if not customer_id:
        return {"objective": objective}, None
    account_id = db._first_account_id(conn, customer_id)
    built = mission_mod.build(conn, customer_id=customer_id, objective=objective, account_id=account_id,
                              bot_id=voice_studio.bot_id_for(agent_id))
    return built or {"objective": objective}, account_id


def preview(agent_id: int, number_id: str, objective: str) -> dict[str, Any]:
    """The exact starting context the agent will get, masked as the run views are."""
    import db_outbound
    import voice_studio
    import voice_studio_privacy

    number = _number(number_id)
    customer = db_outbound.demo_customer(_digits(number["e164"]), tenant_id=db.current_tenant())
    with db.engine.connect() as conn:
        m, account_id = _mission(conn, customer and customer["id"], objective, agent_id)
    ctx = voice_studio.mission_context(m, "(assigned when dialled)", {
        "objective": objective, "customer_id": customer and customer["id"],
        "account_id": account_id, "demo": "1",
    })
    ctx["agent_id"] = agent_id
    return {"context": voice_studio_privacy._mask_context(ctx), "customer": customer}


def place(agent_id: int, number_id: str, objective: str, actor: str | None) -> dict[str, Any]:
    """Reserve, gate and dial. Raises PermissionError with the refusal reason."""
    import db_outbound
    import outbound
    import platform_switches
    import voice_studio

    if not platform_switches.outbound_enabled():
        raise PermissionError("outbound_disabled")
    number = _number(number_id)
    phone = number["e164"]
    customer = db_outbound.demo_customer(_digits(phone), tenant_id=db.current_tenant())
    if customer is None:
        # Nobody on file: the agent gets no account, and nothing to gate.
        result = voice_studio.originate(to=phone, custom={
            "objective": objective, "agent_id": str(agent_id), "demo": "1"})
        return {"placed": True, "attemptId": None, "runId": result.get("callSid"), "customerId": None}

    bot_id = voice_studio.bot_id_for(agent_id)
    waived = waivers()
    with db.engine.begin() as conn:
        voice_studio.ensure_bot(conn, agent_id)  # the attempt's bot_id must exist
        m, account_id = _mission(conn, customer["id"], objective, agent_id)
        gated = outbound.gate(
            conn,
            admit={"source": "voice_outbound", "actor_kind": "human"},
            waivable=waived,
            customer_id=customer["id"],
            to_phone=phone,
            objective=objective,
            account_id=account_id,
            bot_id=bot_id,
            context={"source": "test_call", "mission": m, "requestedBy": actor},
        )
        reason = gated.reason or "contact_policy"
        if gated.allowed and gated.waived:
            db.record_activity(conn, "customer", customer["id"], "demo_window_waived",
                               f"Test call placed despite {reason}", f"waived:{reason}", customer["id"])
    if not gated.allowed:
        raise PermissionError(reason)
    result = outbound.place(db.engine, gated.attempt, to_phone=phone, custom={
        "customer_id": customer["id"], "agent_id": str(agent_id), "demo": "1"})
    if not result.get("placed"):
        raise RuntimeError(result.get("reason") or "dial_failed")
    return {"placed": True, "attemptId": result.get("attemptId"), "runId": result.get("callSid"),
            "customerId": customer["id"]}

