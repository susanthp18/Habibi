"""Live capture helpers — interaction rollup + product eligibility.

Phase 0 / 2-lite of collections_plan.md.

Design constraints:
- Sync DB only (no Azure on this path).
- Safe to call from CrmSink worker threads and bot_worker jobs.
- Never invent bureau/KYC passes — mark unknown/skipped when facts are missing.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)

PRODUCT_INTENTS = frozenset({"upsell_opportunity", "product_faq"})
RESOLVED_HINT_INTENTS = frozenset(
    {
        "payment_intent",
        "balance_query",
        "product_faq",
        "upsell_opportunity",
    }
)
IGNORE_INTENTS = frozenset({"out_of_scope", "", "unknown"})


def _as_dict(conditions: Any) -> dict[str, Any]:
    if conditions is None:
        return {}
    if isinstance(conditions, dict):
        return conditions
    if isinstance(conditions, str):
        try:
            parsed = json.loads(conditions)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def mark_interaction_flags(
    conn: Connection,
    interaction_id: str | None,
    *,
    primary_intent: str | None = None,
    query_resolved: bool | None = None,
    upsell_presented: bool | None = None,
    ptp_captured: bool | None = None,
    summary: str | None = None,
    disposition: str | None = None,
) -> None:
    """OR-set boolean flags and optionally fill blank summary/disposition/intent."""
    if not interaction_id:
        return
    sets: list[str] = ["updated_at = now()"]
    params: dict[str, Any] = {"id": interaction_id}

    if primary_intent:
        sets.append(
            "primary_intent = COALESCE(NULLIF(trim(primary_intent), ''), :primary_intent)"
        )
        # Prefer a stronger overwrite when explicitly rolling up:
        # callers that want force should pass force_primary=True via rollup.
        params["primary_intent"] = primary_intent[:120]

    if query_resolved is True:
        sets.append("query_resolved = true")
    if upsell_presented is True:
        sets.append("upsell_presented = true")
    if ptp_captured is True:
        sets.append("ptp_captured = true")
    if summary:
        sets.append("summary = COALESCE(NULLIF(trim(summary), ''), :summary)")
        params["summary"] = summary[:2000]
    if disposition:
        sets.append("disposition = COALESCE(NULLIF(trim(disposition), ''), :disposition)")
        params["disposition"] = disposition[:120]

    conn.execute(
        text(f"UPDATE interactions SET {', '.join(sets)} WHERE id = :id"),
        params,
    )


def force_primary_intent(conn: Connection, interaction_id: str | None, intent: str | None) -> None:
    if not interaction_id or not intent or intent in IGNORE_INTENTS:
        return
    conn.execute(
        text(
            """
            UPDATE interactions
            SET primary_intent = :intent, updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": interaction_id, "intent": intent[:120]},
    )


def mark_ptp_captured(conn: Connection, interaction_id: str | None) -> None:
    mark_interaction_flags(conn, interaction_id, ptp_captured=True, query_resolved=True)


def mark_upsell_presented(conn: Connection, interaction_id: str | None) -> None:
    mark_interaction_flags(conn, interaction_id, upsell_presented=True)


def touch_primary_intent(conn: Connection, interaction_id: str | None, intent: str | None) -> None:
    """Set primary_intent once (first non-noise intent wins unless rollup overwrites)."""
    if not interaction_id or not intent or intent in IGNORE_INTENTS:
        return
    mark_interaction_flags(conn, interaction_id, primary_intent=intent)


def dominant_transcript_intent(conn: Connection, interaction_id: str) -> str | None:
    row = conn.execute(
        text(
            """
            SELECT intent, COUNT(*)::int AS n
            FROM interaction_transcript
            WHERE interaction_id = :id
              AND speaker = 'customer'
              AND intent IS NOT NULL
              AND trim(intent) <> ''
              AND intent NOT IN ('out_of_scope', 'unknown')
            GROUP BY intent
            ORDER BY n DESC, intent
            LIMIT 1
            """
        ),
        {"id": interaction_id},
    ).mappings().first()
    return str(row["intent"]) if row and row.get("intent") else None


def _has_product_interest(conn: Connection, interaction_id: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1
            FROM interaction_transcript
            WHERE interaction_id = :id
              AND speaker = 'customer'
              AND intent IN ('upsell_opportunity', 'product_faq')
            LIMIT 1
            """
        ),
        {"id": interaction_id},
    ).first()
    return row is not None


def _promise_on_interaction(conn: Connection, interaction_id: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM promises WHERE interaction_id = :id LIMIT 1"),
        {"id": interaction_id},
    ).first()
    return row is not None


def _turn_counts(conn: Connection, interaction_id: str) -> tuple[int, int]:
    row = conn.execute(
        text(
            """
            SELECT
              COUNT(*) FILTER (WHERE speaker = 'customer')::int AS customers,
              COUNT(*) FILTER (WHERE speaker = 'bot')::int AS bots
            FROM interaction_transcript
            WHERE interaction_id = :id
            """
        ),
        {"id": interaction_id},
    ).mappings().first()
    if not row:
        return 0, 0
    return int(row["customers"] or 0), int(row["bots"] or 0)


def build_template_summary(
    *,
    primary_intent: str | None,
    customer_turns: int,
    ptp: bool,
    upsell: bool,
    channel: str = "voice",
) -> str:
    intent = primary_intent or "unclassified"
    bits = [
        f"{channel} session",
        f"primary={intent}",
        f"customer_turns={customer_turns}",
        f"ptp={'yes' if ptp else 'no'}",
        f"upsell={'yes' if upsell else 'no'}",
    ]
    return " | ".join(bits)


def disposition_from_flags(*, ptp: bool, upsell: bool, query_resolved: bool) -> str:
    if ptp:
        return "ptp_captured"
    if upsell:
        return "upsell_interest"
    if query_resolved:
        return "query_handled"
    return "completed"


def rollup_interaction(
    conn: Connection,
    interaction_id: str,
    *,
    channel_hint: str = "voice",
    force_summary: bool = False,
) -> dict[str, Any]:
    """Compute and persist session-level capture fields from transcript + promises."""
    primary = dominant_transcript_intent(conn, interaction_id)
    cust_n, bot_n = _turn_counts(conn, interaction_id)
    ptp = _promise_on_interaction(conn, interaction_id)
    product_interest = _has_product_interest(conn, interaction_id)
    # Phase 0 heuristic: product intent + at least one bot reply ⇒ upsell discussed.
    upsell = product_interest and bot_n > 0
    query_resolved = ptp or (
        primary in RESOLVED_HINT_INTENTS and cust_n > 0 and bot_n > 0
    )

    existing = conn.execute(
        text(
            """
            SELECT primary_intent, query_resolved, upsell_presented, ptp_captured,
                   summary, disposition, channel
            FROM interactions WHERE id = :id
            """
        ),
        {"id": interaction_id},
    ).mappings().first()
    if existing is None:
        return {"ok": False, "reason": "interaction_not_found"}

    # Honour flags already flipped mid-session by tools.
    ptp = ptp or bool(existing.get("ptp_captured"))
    upsell = upsell or bool(existing.get("upsell_presented"))
    query_resolved = query_resolved or bool(existing.get("query_resolved")) or ptp

    channel = channel_hint or (existing.get("channel") or "voice")
    summary = build_template_summary(
        primary_intent=primary or existing.get("primary_intent"),
        customer_turns=cust_n,
        ptp=ptp,
        upsell=upsell,
        channel=str(channel),
    )
    disposition = disposition_from_flags(
        ptp=ptp, upsell=upsell, query_resolved=query_resolved
    )

    sets = [
        "updated_at = now()",
        "query_resolved = :query_resolved",
        "upsell_presented = :upsell_presented",
        "ptp_captured = :ptp_captured",
    ]
    params: dict[str, Any] = {
        "id": interaction_id,
        "query_resolved": query_resolved,
        "upsell_presented": upsell,
        "ptp_captured": ptp,
    }
    if primary:
        sets.append("primary_intent = :primary_intent")
        params["primary_intent"] = primary[:120]
    if force_summary or not (existing.get("summary") or "").strip():
        sets.append("summary = :summary")
        params["summary"] = summary[:2000]
    if force_summary or not (existing.get("disposition") or "").strip():
        sets.append("disposition = :disposition")
        params["disposition"] = disposition[:120]

    conn.execute(text(f"UPDATE interactions SET {', '.join(sets)} WHERE id = :id"), params)
    return {
        "ok": True,
        "primaryIntent": primary,
        "queryResolved": query_resolved,
        "upsellPresented": upsell,
        "ptpCaptured": ptp,
        "summary": summary,
        "disposition": disposition,
    }


def evaluate_product_eligibility(
    conn: Connection,
    *,
    customer_id: str,
    product_id: str,
) -> list[dict[str, Any]]:
    """Evaluate product_eligibility_rules against live account/consent facts.

    Returns lead_eligibility-shaped dicts: label, passed, reason, ruleId?.
    Bureau / KYC / income → explicit unknown (not a fake pass).
    """
    account = conn.execute(
        text(
            """
            SELECT a.id, a.dpd, a.outstanding, a.bucket, a.status, a.product_id AS held_product_id,
                   p.name AS held_product
            FROM accounts a
            LEFT JOIN products p ON p.id = a.product_id
            WHERE a.customer_id = :cid
            ORDER BY CASE WHEN a.id LIKE 'AC-%' THEN 0 ELSE 1 END, a.created_at, a.id
            LIMIT 1
            """
        ),
        {"cid": customer_id},
    ).mappings().first()

    customer = conn.execute(
        text("SELECT dnd FROM customers WHERE id = :id"),
        {"id": customer_id},
    ).mappings().first()

    promo_ok = True
    promo_detail = "No channel-level promo opt-out recorded"
    if customer and customer.get("dnd"):
        promo_ok = False
        promo_detail = "Customer DND is on — promotional offers suppressed"

    consent = conn.execute(
        text(
            """
            SELECT cc.channel, cc.status
            FROM consent_records cr
            JOIN channel_consents cc ON cc.consent_id = cr.id
            WHERE cr.customer_id = :cid
            ORDER BY cc.captured_at DESC NULLS LAST
            """
        ),
        {"cid": customer_id},
    ).mappings().all()
    for row in consent:
        status = (row.get("status") or "").lower()
        if status in {"opted_out", "dnd", "expired"}:
            promo_ok = False
            promo_detail = f"{row.get('channel')} consent is {status}"
            break

    rules = conn.execute(
        text(
            """
            SELECT id, name, conditions
            FROM product_eligibility_rules
            WHERE product_id = :pid AND enabled IS TRUE
            ORDER BY id
            """
        ),
        {"pid": product_id},
    ).mappings().all()

    flags: list[dict[str, Any]] = []

    # Always emit honest unknown profile facts (not stored on customer yet).
    flags.append(
        {
            "ruleId": None,
            "label": "KYC current",
            "passed": False,
            "reason": "KYC status not captured on profile - skipped (unknown)",
            "status": "unknown",
        }
    )
    flags.append(
        {
            "ruleId": None,
            "label": "Bureau score >= policy threshold",
            "passed": False,
            "reason": "Bureau score not on file - skipped (unknown)",
            "status": "unknown",
        }
    )
    flags.append(
        {
            "ruleId": None,
            "label": "Income proof on file",
            "passed": False,
            "reason": "Income proof not captured - skipped (unknown)",
            "status": "unknown",
        }
    )

    dpd = int(account["dpd"] or 0) if account else None
    if account is None:
        flags.append(
            {
                "ruleId": None,
                "label": "Account on file",
                "passed": False,
                "reason": "No account linked to customer",
                "status": "fail",
            }
        )
    else:
        held = account.get("held_product") or account.get("held_product_id") or "account"
        flags.append(
            {
                "ruleId": None,
                "label": "Existing product relationship",
                "passed": True,
                "reason": f"Active {held} | DPD {dpd} | bucket {account.get('bucket') or '-'}",
                "status": "pass",
            }
        )

    flags.append(
        {
            "ruleId": None,
            "label": "Consent / DND allows promo",
            "passed": promo_ok,
            "reason": promo_detail,
            "status": "pass" if promo_ok else "fail",
        }
    )

    # Apply seeded JSON rules (today: kyc + dpdMax).
    for rule in rules:
        conditions = _as_dict(rule.get("conditions"))
        dpd_max = conditions.get("dpdMax")
        if dpd_max is not None and dpd is not None:
            try:
                limit = int(dpd_max)
            except (TypeError, ValueError):
                limit = 90
            ok = dpd <= limit
            flags.append(
                {
                    "ruleId": rule["id"],
                    "label": f"DPD <= {limit} ({rule.get('name') or 'rule'})",
                    "passed": ok,
                    "reason": f"Account DPD is {dpd}" + ("" if ok else f" (over {limit})"),
                    "status": "pass" if ok else "fail",
                }
            )
        if "kyc" in conditions:
            flags.append(
                {
                    "ruleId": rule["id"],
                    "label": f"KYC rule ({rule.get('name') or rule['id']})",
                    "passed": False,
                    "reason": "Rule requires KYC but profile has no KYC field - skipped (unknown)",
                    "status": "unknown",
                }
            )

    return flags


def insert_lead_eligibility(
    conn: Connection,
    *,
    lead_id: str,
    flags: list[dict[str, Any]],
) -> None:
    for idx, flag in enumerate(flags):
        fid = f"{lead_id}-E{idx + 1}"
        conn.execute(
            text(
                """
                INSERT INTO lead_eligibility (id, lead_id, rule_id, label, passed, reason, created_at)
                VALUES (:id, :lead_id, :rule_id, :label, :passed, :reason, now())
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": fid,
                "lead_id": lead_id,
                "rule_id": flag.get("ruleId"),
                "label": flag.get("label") or "check",
                "passed": bool(flag.get("passed")),
                "reason": flag.get("reason"),
            },
        )


def eligibility_blocks_capture(flags: list[dict[str, Any]]) -> str | None:
    """Hard-block only on explicit fail (DND/consent, DPD, missing account). Unknown never blocks."""
    for f in flags:
        status = (f.get("status") or "").lower()
        if status in {"unknown", "skipped"}:
            continue
        if status != "fail" and f.get("passed") is not False:
            continue
        label = (f.get("label") or "").lower()
        if any(k in label for k in ("consent", "dnd", "account on file", "dpd")):
            return f.get("reason") or f.get("label") or "eligibility_failed"
    return None


# ---------------------------------------------------------------------------
# Phase 1 — structured commercial events (activity_events)
# Phase 3 lite — identify / rebind
# ---------------------------------------------------------------------------

COMMERCIAL_KINDS = frozenset(
    {
        "product_interest",
        "offer_presented",
        "offer_declined",
        "eligibility_checked",
        "lead_captured",
        "identity_verified",
        "identity_failed",
    }
)


def _sid(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def emit_commercial_event(
    conn: Connection,
    *,
    entity_type: str,
    entity_id: str,
    kind: str,
    label: str,
    note: str | None = None,
    payload: dict[str, Any] | None = None,
    actor_kind: str = "bot",
    actor_bot_id: str | None = None,
    actor_user_id: str | None = None,
    tone: str | None = None,
) -> str:
    """Append a commercial/capture event with payload jsonb (bot/system actor)."""
    event_id = _sid("ACT")
    bot_id = actor_bot_id if actor_kind == "bot" else None
    user_id = actor_user_id if actor_kind == "human" else None
    if actor_kind == "bot" and not bot_id:
        try:
            import db as _db

            bot_id = getattr(_db, "DEFAULT_BOT_ID", None)
        except Exception:
            bot_id = None
    if bot_id:
        exists = conn.execute(text("SELECT 1 FROM bots WHERE id = :id"), {"id": bot_id}).first()
        if exists is None:
            actor_kind = "system"
            bot_id = None

    import db as _db

    conn.execute(
        text(
            """
            INSERT INTO activity_events (
              id, tenant_id, entity_type, entity_id, at,
              actor_kind, actor_user_id, actor_bot_id,
              kind, label, note, tone, payload, created_at
            ) VALUES (
              :id, :tenant, :entity_type, :entity_id, now(),
              :actor_kind, :actor_user_id, :actor_bot_id,
              :kind, :label, :note, :tone, CAST(:payload AS jsonb), now()
            )
            """
        ),
        {
            "id": event_id,
            "tenant": _db.TENANT_ID,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_kind": actor_kind if actor_kind in {"human", "bot", "system", "customer"} else "system",
            "actor_user_id": user_id,
            "actor_bot_id": bot_id,
            "kind": kind[:80],
            "label": (label or kind)[:200],
            "note": note,
            "tone": tone,
            "payload": json.dumps(payload or {}),
        },
    )
    return event_id


def next_transcript_turn_index(conn: Connection, interaction_id: str) -> int:
    row = conn.execute(
        text(
            """
            SELECT COALESCE(MAX(turn_index), -1)::int AS m
            FROM interaction_transcript
            WHERE interaction_id = :id
            """
        ),
        {"id": interaction_id},
    ).mappings().first()
    return int(row["m"] if row else -1) + 1


def record_product_interest(
    conn: Connection,
    *,
    interaction_id: str,
    intent: str,
    snippet: str | None = None,
    actor_bot_id: str | None = None,
) -> None:
    if intent not in PRODUCT_INTENTS:
        return
    touch_primary_intent(conn, interaction_id, intent)
    emit_commercial_event(
        conn,
        entity_type="interaction",
        entity_id=interaction_id,
        kind="product_interest",
        label=f"Product interest | {intent}",
        note=(snippet or "")[:240] or None,
        payload={"intent": intent},
        actor_bot_id=actor_bot_id,
    )


def record_offer_presented(
    conn: Connection,
    *,
    interaction_id: str,
    product_id: str | None = None,
    source: str = "kb",
    actor_bot_id: str | None = None,
) -> None:
    mark_upsell_presented(conn, interaction_id)
    emit_commercial_event(
        conn,
        entity_type="interaction",
        entity_id=interaction_id,
        kind="offer_presented",
        label="Offer / product info presented",
        note=product_id,
        payload={"productId": product_id, "source": source},
        actor_bot_id=actor_bot_id,
    )


def record_eligibility_checked(
    conn: Connection,
    *,
    interaction_id: str | None,
    customer_id: str,
    product_id: str,
    flags: list[dict[str, Any]],
    blocked: str | None,
    actor_bot_id: str | None = None,
) -> None:
    entity_type = "interaction" if interaction_id else "customer"
    entity_id = interaction_id or customer_id
    emit_commercial_event(
        conn,
        entity_type=entity_type,
        entity_id=entity_id,
        kind="eligibility_checked",
        label=f"Eligibility checked | {product_id}",
        note=blocked or "eligible_or_unknown_ok",
        payload={
            "productId": product_id,
            "customerId": customer_id,
            "blocked": blocked,
            "flagCount": len(flags),
            "failCount": sum(1 for f in flags if f.get("status") == "fail"),
            "unknownCount": sum(1 for f in flags if f.get("status") == "unknown"),
        },
        actor_bot_id=actor_bot_id,
    )


def record_lead_captured(
    conn: Connection,
    *,
    interaction_id: str | None,
    lead_id: str,
    product_id: str,
    actor_bot_id: str | None = None,
) -> None:
    if interaction_id:
        mark_upsell_presented(conn, interaction_id)
        emit_commercial_event(
            conn,
            entity_type="interaction",
            entity_id=interaction_id,
            kind="lead_captured",
            label="Lead captured from conversation",
            note=lead_id,
            payload={"leadId": lead_id, "productId": product_id},
            actor_bot_id=actor_bot_id,
        )
    emit_commercial_event(
        conn,
        entity_type="lead",
        entity_id=lead_id,
        kind="lead_captured",
        label="Lead captured",
        note=product_id,
        payload={"interactionId": interaction_id, "productId": product_id},
        actor_bot_id=actor_bot_id,
    )


def find_customer_by_account_tail(conn: Connection, tail: str) -> dict[str, Any] | None:
    digits = "".join(ch for ch in (tail or "") if ch.isdigit())
    if len(digits) < 4:
        return None
    tail4 = digits[-4:]
    return conn.execute(
        text(
            """
            SELECT c.id, c.name, c.phone_primary, a.id AS account_id
            FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE RIGHT(regexp_replace(a.id, '[^0-9]', '', 'g'), 4) = :tail
               OR RIGHT(a.id, 4) = :tail
            ORDER BY a.updated_at DESC NULLS LAST, a.id
            LIMIT 1
            """
        ),
        {"tail": tail4},
    ).mappings().first()


def rebind_interaction_customer(
    conn: Connection,
    *,
    interaction_id: str,
    customer_id: str,
    method: str = "phone_match",
    account_id: str | None = None,
    actor_bot_id: str | None = None,
) -> dict[str, Any]:
    """Rebind interaction (+ linked conversation) to a verified customer."""
    if method not in {"phone_match", "dob", "otp", "account_tail", "manual"}:
        method = "manual"

    cust = conn.execute(
        text("SELECT id, name FROM customers WHERE id = :id"),
        {"id": customer_id},
    ).mappings().first()
    if cust is None:
        raise KeyError("customer_not_found")

    ix = conn.execute(
        text("SELECT id, customer_id FROM interactions WHERE id = :id"),
        {"id": interaction_id},
    ).mappings().first()
    if ix is None:
        raise KeyError("interaction_not_found")

    if not account_id:
        acct = conn.execute(
            text(
                """
                SELECT id FROM accounts
                WHERE customer_id = :cid
                ORDER BY CASE WHEN id LIKE 'AC-%' THEN 0 ELSE 1 END, created_at, id
                LIMIT 1
                """
            ),
            {"cid": customer_id},
        ).mappings().first()
        account_id = acct["id"] if acct else None

    conn.execute(
        text(
            """
            UPDATE interactions
            SET customer_id = :cid,
                account_id = COALESCE(:aid, account_id),
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": interaction_id, "cid": customer_id, "aid": account_id},
    )
    conn.execute(
        text(
            """
            UPDATE conversations
            SET customer_id = :cid, updated_at = now()
            WHERE interaction_id = :iid
            """
        ),
        {"cid": customer_id, "iid": interaction_id},
    )

    vid = _sid("VER")
    conn.execute(
        text(
            """
            INSERT INTO identity_verifications (
              id, interaction_id, customer_id, method, status,
              attempt_count, verified_at, created_at, updated_at
            ) VALUES (
              :id, :iid, :cid, :method, 'verified',
              1, now(), now(), now()
            )
            """
        ),
        {"id": vid, "iid": interaction_id, "cid": customer_id, "method": method},
    )
    emit_commercial_event(
        conn,
        entity_type="interaction",
        entity_id=interaction_id,
        kind="identity_verified",
        label=f"Identity verified | {method}",
        note=cust.get("name"),
        payload={
            "customerId": customer_id,
            "accountId": account_id,
            "method": method,
            "previousCustomerId": ix.get("customer_id"),
            "verificationId": vid,
        },
        actor_bot_id=actor_bot_id,
    )
    return {
        "interactionId": interaction_id,
        "customerId": customer_id,
        "customerName": cust.get("name"),
        "accountId": account_id,
        "method": method,
        "verificationId": vid,
    }


def record_identity_failed(
    conn: Connection,
    *,
    interaction_id: str | None,
    reason: str,
    method: str = "phone_match",
    actor_bot_id: str | None = None,
) -> None:
    if not interaction_id:
        return
    emit_commercial_event(
        conn,
        entity_type="interaction",
        entity_id=interaction_id,
        kind="identity_failed",
        label=f"Identity failed | {method}",
        note=reason[:240],
        payload={"method": method, "reason": reason},
        actor_bot_id=actor_bot_id,
        tone="negative",
    )
