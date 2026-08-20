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
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
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
    # None (not "voice"): the default previously overrode the interaction's own
    # stored channel, so every WhatsApp rollup was summarised as a voice call.
    channel_hint: str | None = None,
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


# Stable eligibility flag codes. `blocking` on each emitted flag (not the
# English label) decides whether a failure hard-blocks capture, so renaming a
# label for the UI can never silently disable a compliance gate.
ELIGIBILITY_KYC_PROFILE = "kyc_profile"
ELIGIBILITY_BUREAU_SCORE = "bureau_score"
ELIGIBILITY_INCOME_PROOF = "income_proof"
ELIGIBILITY_ACCOUNT_ON_FILE = "account_on_file"
ELIGIBILITY_CONSENT_PROMO = "consent_promo"
ELIGIBILITY_RULE_DPD_MAX = "rule_dpd_max"
ELIGIBILITY_RULE_KYC = "rule_kyc"
ELIGIBILITY_ALREADY_HELD = "already_held"
ELIGIBILITY_RULE_MIN_RELATIONSHIP = "rule_min_relationship_months"
ELIGIBILITY_RULE_MAX_UTILIZATION = "rule_max_utilization"
ELIGIBILITY_RULE_SEGMENT_IN = "rule_segment_in"
ELIGIBILITY_RULE_RISK_NOT_IN = "rule_risk_not_in"
ELIGIBILITY_RULE_CONSENT_CHANNEL = "rule_consent_channel"
ELIGIBILITY_RULE_MIN_TICKET = "rule_min_ticket"
# Emitted when a rule carries a key this build does not implement. It is
# deliberately non-blocking but deliberately *visible*: a typo'd condition used
# to evaluate to nothing at all, which looks identical to a rule that passed.
ELIGIBILITY_RULE_UNSUPPORTED = "rule_unsupported"

# Account states that still represent a live relationship. A closed/written-off
# account is history: it must not satisfy "existing product relationship", and
# it must not make us think the customer already holds the product we are about
# to offer.
_LIVE_ACCOUNT_STATUSES = frozenset({"active", "delinquent", "overdue", "current", "open"})

# Promotional contact is blocked on a channel in any of these states.
_CONSENT_BLOCKING_STATUSES = frozenset({"opted_out", "dnd", "expired"})

# Legacy fallback for flag dicts persisted/round-tripped before `blocking`
# existed (e.g. eligibilityFlags supplied on a create_lead payload).
_LEGACY_BLOCKING_LABEL_KEYWORDS = ("consent", "dnd", "account on file", "dpd")


def account_snapshot(conn: Connection, customer_id: str) -> dict[str, Any]:
    """Aggregate ALL of a customer's live accounts into one risk view.

    Previously eligibility read a single account chosen by
    ``ORDER BY CASE WHEN a.id LIKE 'AC-%' ... LIMIT 1``, so a customer holding a
    clean credit card and a 120-DPD personal loan was judged on whichever
    sorted first — a false block or, worse, a false pass, depending purely on id
    format. Risk is a property of the customer, so it is aggregated: worst DPD
    decides, and every held product is returned so the caller can refuse to
    cross-sell something they already have.
    """
    rows = conn.execute(
        text(
            """
            SELECT a.id, a.dpd, a.outstanding, a.sanctioned_amount, a.minimum_due,
                   a.bucket, a.status, a.opened_on, a.product_id AS held_product_id,
                   p.name AS held_product
            FROM accounts a
            LEFT JOIN products p ON p.id = a.product_id
            WHERE a.customer_id = :cid
            ORDER BY a.created_at, a.id
            """
        ),
        {"cid": customer_id},
    ).mappings().all()

    live = [r for r in rows if (r.get("status") or "").lower() in _LIVE_ACCOUNT_STATUSES]
    # Fall back to every row rather than reporting "no account on file" purely
    # because a deployment uses a status value this list does not know about.
    considered = live or list(rows)

    dpds = [int(r["dpd"] or 0) for r in considered if r.get("dpd") is not None]
    return {
        "accounts": considered,
        "any": bool(considered),
        "dpd_worst": max(dpds) if dpds else None,
        "dpd_best": min(dpds) if dpds else None,
        "held_product_ids": {r["held_product_id"] for r in considered if r.get("held_product_id")},
        "primary": considered[0] if considered else None,
    }


def latest_consent_by_channel(conn: Connection, customer_id: str) -> dict[str, str]:
    """Latest consent status per channel. A stale opt-out on one channel must
    not outrank a fresh opt-in on the same channel."""
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (cc.channel) cc.channel, cc.status
            FROM consent_records cr
            JOIN channel_consents cc ON cc.consent_id = cr.id
            WHERE cr.customer_id = :cid
            ORDER BY cc.channel, cc.captured_at DESC NULLS LAST, cc.id DESC
            """
        ),
        {"cid": customer_id},
    ).mappings().all()
    return {str(r["channel"]): str(r["status"] or "").lower() for r in rows}


def _promo_consent_flag(
    *, dnd: bool, consent: dict[str, str], channel: str | None
) -> tuple[bool, str, str]:
    """(passed, status, detail) for the promotional-consent gate.

    Consent is per channel, so it must be evaluated against the channel we are
    actually on. The previous implementation blocked when *any* channel was
    opted out, which meant an email opt-out silenced a voice upsell — an
    over-block nobody could explain to the business.

    With no channel context (an agent creating a lead by hand, where the
    follow-up channel is not yet known) we block only when DND is set or when
    every recorded channel is closed, and otherwise report ``unknown`` — which,
    per this module's standing rule, never blocks.
    """
    if dnd:
        return False, "fail", "Customer DND is on - promotional offers suppressed"

    # An unknown carries passed=False alongside status="unknown", matching the
    # KYC/bureau/income flags above. eligibility_blocks_capture skips on the
    # status either way, but passed=True would render in the UI as a green tick
    # for something nobody has actually verified.
    if channel:
        status = consent.get(channel)
        if status is None:
            return False, "unknown", f"No {channel} consent record on file - skipped (unknown)"
        if status in _CONSENT_BLOCKING_STATUSES:
            return False, "fail", f"{channel} consent is {status}"
        return True, "pass", f"{channel} consent is {status}"

    if consent and all(s in _CONSENT_BLOCKING_STATUSES for s in consent.values()):
        closed = ", ".join(sorted(consent))
        return False, "fail", f"Every recorded channel is opted out ({closed})"

    blocked = sorted(ch for ch, s in consent.items() if s in _CONSENT_BLOCKING_STATUSES)
    if blocked:
        return (
            False,
            "unknown",
            f"No channel context; opted out on {', '.join(blocked)} - verify before contact",
        )
    return True, "pass", "No channel-level promo opt-out recorded"


def customer_eligibility_facts(conn: Connection, customer_id: str) -> dict[str, Any]:
    """Customer-level inputs to eligibility, gathered once.

    The offer engine evaluates every candidate product for one customer in a
    single pass. Re-reading accounts, consent and the DND flag per product made
    that N× the queries on the audio path of a live call, for facts that cannot
    change between candidates.
    """
    customer = conn.execute(
        text("SELECT dnd, segment, risk FROM customers WHERE id = :id"),
        {"id": customer_id},
    ).mappings().first() or {}
    snapshot = account_snapshot(conn, customer_id)
    return {
        "snapshot": snapshot,
        "dnd": bool(customer.get("dnd")),
        "consent": latest_consent_by_channel(conn, customer_id),
        "segment": customer.get("segment"),
        "risk": customer.get("risk"),
        "relationship_months": _relationship_months(snapshot["accounts"]),
        "utilization": _utilization(snapshot["accounts"]),
        "headroom": _headroom(snapshot["accounts"]),
    }


def _num(value: Any) -> float | None:
    """Decimal/str/None → float|None. Never invents a zero: a missing balance
    and a zero balance mean opposite things to an affordability rule."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _relationship_months(accounts: list[Any]) -> int | None:
    """Months since the earliest account was opened, or None if no dates."""
    opened = [a.get("opened_on") for a in accounts if a.get("opened_on")]
    dates = [d for d in opened if isinstance(d, (datetime, date))]
    if not dates:
        return None
    earliest = min(dates)
    if isinstance(earliest, datetime):
        earliest = (earliest if earliest.tzinfo else earliest.replace(tzinfo=timezone.utc)).date()
    return max(0, int((datetime.now(timezone.utc).date() - earliest).days / 30.44))


def _sum_or_none(accounts: list[Any], column: str) -> float | None:
    """Total across accounts, or None when not one account carries the column.

    Summing with a zero default would turn "we hold no balance data" into a
    confident zero, and a zero outstanding is exactly what makes an
    affordability rule pass.
    """
    values = [_num(a.get(column)) for a in accounts]
    values = [v for v in values if v is not None]
    return sum(values) if values else None


def _headroom(accounts: list[Any]) -> float | None:
    sanctioned = _sum_or_none(accounts, "sanctioned_amount")
    outstanding = _sum_or_none(accounts, "outstanding")
    if sanctioned is None or outstanding is None:
        return None
    return max(0.0, sanctioned - outstanding)


def _utilization(accounts: list[Any]) -> float | None:
    sanctioned = _sum_or_none(accounts, "sanctioned_amount")
    outstanding = _sum_or_none(accounts, "outstanding")
    if not sanctioned or outstanding is None:
        return None
    return round(outstanding / sanctioned, 4)


def evaluate_product_eligibility(
    conn: Connection,
    *,
    customer_id: str,
    product_id: str,
    channel: str | None = None,
    facts: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate product_eligibility_rules against live account/consent facts.

    Returns lead_eligibility-shaped dicts: label, passed, reason, ruleId?.
    Bureau / KYC / income → explicit unknown (not a fake pass).

    ``channel`` is the channel the offer would be made on ("voice", "whatsapp",
    …). Supplying it makes the consent gate channel-accurate; omitting it is
    honest-unknown rather than a guess.

    ``facts`` lets a caller evaluating many products for one customer hoist the
    customer-level reads out of the loop — see customer_eligibility_facts.
    """
    facts = facts if facts is not None else customer_eligibility_facts(conn, customer_id)
    snapshot = facts["snapshot"]
    account = snapshot["primary"]
    consent = facts["consent"]
    promo_ok, promo_status, promo_detail = _promo_consent_flag(
        dnd=bool(facts["dnd"]),
        consent=consent,
        channel=(channel or "").strip().lower() or None,
    )

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
            "code": ELIGIBILITY_KYC_PROFILE,
            "blocking": False,
            "label": "KYC current",
            "passed": False,
            "reason": "KYC status not captured on profile - skipped (unknown)",
            "status": "unknown",
        }
    )
    flags.append(
        {
            "ruleId": None,
            "code": ELIGIBILITY_BUREAU_SCORE,
            "blocking": False,
            "label": "Bureau score >= policy threshold",
            "passed": False,
            "reason": "Bureau score not on file - skipped (unknown)",
            "status": "unknown",
        }
    )
    flags.append(
        {
            "ruleId": None,
            "code": ELIGIBILITY_INCOME_PROOF,
            "blocking": False,
            "label": "Income proof on file",
            "passed": False,
            "reason": "Income proof not captured - skipped (unknown)",
            "status": "unknown",
        }
    )

    # Worst DPD across every live account, not whichever account sorted first.
    dpd = snapshot["dpd_worst"]
    if account is None:
        flags.append(
            {
                "ruleId": None,
                "code": ELIGIBILITY_ACCOUNT_ON_FILE,
                "blocking": True,
                "label": "Account on file",
                "passed": False,
                "reason": "No account linked to customer",
                "status": "fail",
            }
        )
    else:
        held = account.get("held_product") or account.get("held_product_id") or "account"
        extra = len(snapshot["accounts"]) - 1
        also = f" (+{extra} more account{'s' if extra > 1 else ''})" if extra > 0 else ""
        flags.append(
            {
                "ruleId": None,
                "code": ELIGIBILITY_ACCOUNT_ON_FILE,
                "blocking": True,
                "label": "Existing product relationship",
                "passed": True,
                "reason": (
                    f"Active {held}{also} | worst DPD {dpd} | "
                    f"bucket {account.get('bucket') or '-'}"
                ),
                "status": "pass",
            }
        )

    # Cross-selling a product the customer already holds is not an offer, it is
    # a mistake the caller will hear as one. Nothing checked this before: the
    # held product was read and then reported as a *reason to pass*.
    already_held = product_id in snapshot["held_product_ids"]
    flags.append(
        {
            "ruleId": None,
            "code": ELIGIBILITY_ALREADY_HELD,
            "blocking": True,
            "label": "Not already held",
            "passed": not already_held,
            "reason": (
                "Customer already holds this product on a live account"
                if already_held
                else "Product is not already held"
            ),
            "status": "fail" if already_held else "pass",
        }
    )

    flags.append(
        {
            "ruleId": None,
            "code": ELIGIBILITY_CONSENT_PROMO,
            "blocking": True,
            "label": "Consent / DND allows promo",
            "passed": promo_ok,
            "reason": promo_detail,
            "status": promo_status,
        }
    )

    # Apply the seeded JSON conditions DSL.
    for rule in rules:
        flags.extend(_evaluate_conditions(rule, facts))

    return flags


# ---------------------------------------------------------------------------
# The conditions DSL
#
# `product_eligibility_rules.conditions` is a small closed predicate set, not a
# general expression language. That is deliberate: everything in here has to be
# explainable to a compliance officer in one line, and an eval() would be neither
# auditable nor safe to expose to whoever edits campaign config.
#
# Three invariants hold for every predicate, and the tests assert all three:
#   1. A configured predicate ALWAYS emits a flag. Silence is indistinguishable
#      from a pass, and the caller only sees the flag list.
#   2. An unknown fact yields status "unknown", which never blocks.
#   3. A malformed threshold yields "unknown" plus a warning — never a default.
#      Silently substituting a default is how `{"dpdMax": "thirty"}` became a
#      90-day limit nobody chose.
# ---------------------------------------------------------------------------


def _rule_flag(
    *,
    rule_id: Any,
    code: str,
    blocking: bool,
    label: str,
    status: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "ruleId": rule_id,
        "code": code,
        "blocking": blocking,
        "label": label,
        "passed": status == "pass",
        "reason": reason,
        "status": status,
    }


def _as_str_set(raw: Any) -> set[str] | None:
    """Normalise a scalar or list of strings to a lowercase set.

    None when the config is not usable as a membership test — an empty list
    included, since "must be in {}" can never pass and is far more likely a
    mistake than an intent to block everyone.
    """
    values = raw if isinstance(raw, (list, tuple, set)) else [raw]
    out = {str(v).strip().lower() for v in values if str(v or "").strip()}
    return out or None


def _threshold(raw: Any, rule_id: Any, key: str, cast: Any) -> Any | None:
    try:
        return cast(raw)
    except (TypeError, ValueError):
        logger.warning(
            "eligibility rule %s has non-numeric %s=%r; treating as unknown",
            rule_id,
            key,
            raw,
        )
        return None


def _pred_dpd_max(raw: Any, facts: dict[str, Any], rid: Any, rname: str) -> dict[str, Any]:
    limit = _threshold(raw, rid, "dpdMax", int)
    dpd = facts["snapshot"]["dpd_worst"]
    if limit is None or dpd is None:
        detail = (
            "rule threshold is not numeric"
            if limit is None
            else "no account on file so DPD is unknown"
        )
        return _rule_flag(
            rule_id=rid,
            code=ELIGIBILITY_RULE_DPD_MAX,
            blocking=True,
            label=f"DPD limit ({rname})",
            status="unknown",
            reason=f"DPD check skipped (unknown) - {detail}",
        )
    ok = dpd <= limit
    return _rule_flag(
        rule_id=rid,
        code=ELIGIBILITY_RULE_DPD_MAX,
        blocking=True,
        label=f"DPD <= {limit} ({rname})",
        status="pass" if ok else "fail",
        reason=f"Worst account DPD is {dpd}" + ("" if ok else f" (over {limit})"),
    )


def _pred_kyc(raw: Any, facts: dict[str, Any], rid: Any, rname: str) -> dict[str, Any]:
    # KYC is not on the customer profile in this schema. Saying so is the
    # honest answer; inventing a pass would be the dangerous one.
    return _rule_flag(
        rule_id=rid,
        code=ELIGIBILITY_RULE_KYC,
        blocking=False,
        label=f"KYC rule ({rname})",
        status="unknown",
        reason="Rule requires KYC but profile has no KYC field - skipped (unknown)",
    )


def _pred_min_relationship_months(
    raw: Any, facts: dict[str, Any], rid: Any, rname: str
) -> dict[str, Any]:
    limit = _threshold(raw, rid, "minRelationshipMonths", int)
    months = facts.get("relationship_months")
    if limit is None or months is None:
        detail = (
            "rule threshold is not numeric"
            if limit is None
            else "no account opening date on file"
        )
        return _rule_flag(
            rule_id=rid,
            code=ELIGIBILITY_RULE_MIN_RELATIONSHIP,
            blocking=True,
            label=f"Relationship tenure ({rname})",
            status="unknown",
            reason=f"Tenure check skipped (unknown) - {detail}",
        )
    ok = months >= limit
    return _rule_flag(
        rule_id=rid,
        code=ELIGIBILITY_RULE_MIN_RELATIONSHIP,
        blocking=True,
        label=f"Relationship >= {limit} months ({rname})",
        status="pass" if ok else "fail",
        reason=f"Relationship is {months} months" + ("" if ok else f" (under {limit})"),
    )


def _pred_max_utilization(
    raw: Any, facts: dict[str, Any], rid: Any, rname: str
) -> dict[str, Any]:
    limit = _threshold(raw, rid, "maxUtilization", float)
    util = facts.get("utilization")
    if limit is None or util is None:
        detail = (
            "rule threshold is not numeric"
            if limit is None
            else "no sanctioned/outstanding pair on file"
        )
        return _rule_flag(
            rule_id=rid,
            code=ELIGIBILITY_RULE_MAX_UTILIZATION,
            blocking=True,
            label=f"Credit utilisation ({rname})",
            status="unknown",
            reason=f"Utilisation check skipped (unknown) - {detail}",
        )
    ok = util <= limit
    return _rule_flag(
        rule_id=rid,
        code=ELIGIBILITY_RULE_MAX_UTILIZATION,
        blocking=True,
        label=f"Utilisation <= {limit:.0%} ({rname})",
        status="pass" if ok else "fail",
        reason=f"Utilisation is {util:.0%}" + ("" if ok else f" (over {limit:.0%})"),
    )


def _pred_segment_in(raw: Any, facts: dict[str, Any], rid: Any, rname: str) -> dict[str, Any]:
    allowed = _as_str_set(raw)
    segment = (facts.get("segment") or "").strip().lower()
    if allowed is None or not segment:
        detail = (
            "rule lists no segments" if allowed is None else "customer has no segment on file"
        )
        if allowed is None:
            logger.warning("eligibility rule %s has unusable segmentIn=%r", rid, raw)
        return _rule_flag(
            rule_id=rid,
            code=ELIGIBILITY_RULE_SEGMENT_IN,
            blocking=True,
            label=f"Segment eligibility ({rname})",
            status="unknown",
            reason=f"Segment check skipped (unknown) - {detail}",
        )
    ok = segment in allowed
    return _rule_flag(
        rule_id=rid,
        code=ELIGIBILITY_RULE_SEGMENT_IN,
        blocking=True,
        label=f"Segment in {sorted(allowed)} ({rname})",
        status="pass" if ok else "fail",
        reason=f"Customer segment is {segment}"
        + ("" if ok else f" (not in {sorted(allowed)})"),
    )


def _pred_risk_not_in(raw: Any, facts: dict[str, Any], rid: Any, rname: str) -> dict[str, Any]:
    excluded = _as_str_set(raw)
    risk = (facts.get("risk") or "").strip().lower()
    if excluded is None or not risk:
        detail = "rule lists no risk bands" if excluded is None else "customer has no risk band on file"
        if excluded is None:
            logger.warning("eligibility rule %s has unusable riskNotIn=%r", rid, raw)
        return _rule_flag(
            rule_id=rid,
            code=ELIGIBILITY_RULE_RISK_NOT_IN,
            blocking=True,
            label=f"Risk band ({rname})",
            status="unknown",
            reason=f"Risk check skipped (unknown) - {detail}",
        )
    ok = risk not in excluded
    return _rule_flag(
        rule_id=rid,
        code=ELIGIBILITY_RULE_RISK_NOT_IN,
        blocking=True,
        label=f"Risk not in {sorted(excluded)} ({rname})",
        status="pass" if ok else "fail",
        reason=f"Customer risk is {risk}" + ("" if ok else " (excluded band)"),
    )


def _pred_requires_consent_channel(
    raw: Any, facts: dict[str, Any], rid: Any, rname: str
) -> dict[str, Any]:
    """Consent on a *named* channel, independent of the channel we are on.

    Distinct from `consent_promo`, which gates the channel carrying the
    conversation. A product whose fulfilment needs a signed e-mandate can
    require e-mail consent while being pitched on the phone.
    """
    channel = str(raw or "").strip().lower()
    if not channel:
        logger.warning("eligibility rule %s has empty requiresConsentChannel=%r", rid, raw)
        return _rule_flag(
            rule_id=rid,
            code=ELIGIBILITY_RULE_CONSENT_CHANNEL,
            blocking=True,
            label=f"Channel consent ({rname})",
            status="unknown",
            reason="Consent check skipped (unknown) - rule names no channel",
        )
    if facts.get("dnd"):
        return _rule_flag(
            rule_id=rid,
            code=ELIGIBILITY_RULE_CONSENT_CHANNEL,
            blocking=True,
            label=f"{channel} consent ({rname})",
            status="fail",
            reason="Customer DND is on - promotional offers suppressed",
        )
    status = (facts.get("consent") or {}).get(channel)
    if status is None:
        return _rule_flag(
            rule_id=rid,
            code=ELIGIBILITY_RULE_CONSENT_CHANNEL,
            blocking=True,
            label=f"{channel} consent ({rname})",
            status="unknown",
            reason=f"No {channel} consent record on file - skipped (unknown)",
        )
    ok = status not in _CONSENT_BLOCKING_STATUSES
    return _rule_flag(
        rule_id=rid,
        code=ELIGIBILITY_RULE_CONSENT_CHANNEL,
        blocking=True,
        label=f"{channel} consent ({rname})",
        status="pass" if ok else "fail",
        reason=f"{channel} consent is {status}",
    )


def _pred_min_ticket(raw: Any, facts: dict[str, Any], rid: Any, rname: str) -> dict[str, Any]:
    """Is there room on the relationship for at least the minimum ticket?

    Measured against headroom (sanctioned − outstanding) rather than income,
    which this schema does not carry. A product with a ₹1L floor offered to
    someone with ₹12k of room is a decline waiting to happen, and the decline
    costs a cool-down on the whole family.
    """
    floor = _threshold(raw, rid, "minTicket", float)
    headroom = facts.get("headroom")
    if floor is None or headroom is None:
        detail = (
            "rule threshold is not numeric"
            if floor is None
            else "no sanctioned/outstanding pair on file"
        )
        return _rule_flag(
            rule_id=rid,
            code=ELIGIBILITY_RULE_MIN_TICKET,
            blocking=True,
            label=f"Minimum ticket ({rname})",
            status="unknown",
            reason=f"Ticket check skipped (unknown) - {detail}",
        )
    ok = headroom >= floor
    return _rule_flag(
        rule_id=rid,
        code=ELIGIBILITY_RULE_MIN_TICKET,
        blocking=True,
        label=f"Headroom >= {floor:,.0f} ({rname})",
        status="pass" if ok else "fail",
        reason=f"Available headroom is {headroom:,.0f}"
        + ("" if ok else f" (under {floor:,.0f})"),
    )


# Ordered so the flag list reads consistently regardless of JSON key order —
# lead_eligibility rows are keyed positionally, and a stable order keeps a
# re-evaluation diffable against the previous one.
_CONDITION_PREDICATES: tuple[tuple[str, Any], ...] = (
    ("dpdMax", _pred_dpd_max),
    ("minRelationshipMonths", _pred_min_relationship_months),
    ("maxUtilization", _pred_max_utilization),
    ("segmentIn", _pred_segment_in),
    ("riskNotIn", _pred_risk_not_in),
    ("requiresConsentChannel", _pred_requires_consent_channel),
    ("minTicket", _pred_min_ticket),
    ("kyc", _pred_kyc),
)

SUPPORTED_CONDITION_KEYS = frozenset(key for key, _ in _CONDITION_PREDICATES)


def _evaluate_conditions(rule: Any, facts: dict[str, Any]) -> list[dict[str, Any]]:
    conditions = _as_dict(rule.get("conditions"))
    rid = rule["id"]
    rname = str(rule.get("name") or rid)

    out = [
        predicate(conditions[key], facts, rid, rname)
        for key, predicate in _CONDITION_PREDICATES
        if conditions.get(key) is not None
    ]

    # A key we do not implement must be loud, not ignored. `{"dpdMxa": 30}`
    # previously evaluated to nothing and rendered as a clean pass.
    unsupported = sorted(set(conditions) - SUPPORTED_CONDITION_KEYS)
    if unsupported:
        logger.warning(
            "eligibility rule %s has unsupported condition keys %s; ignored",
            rid,
            unsupported,
        )
        out.append(
            _rule_flag(
                rule_id=rid,
                code=ELIGIBILITY_RULE_UNSUPPORTED,
                blocking=False,
                label=f"Unsupported conditions ({rname})",
                status="unknown",
                reason=f"Rule keys not evaluated by this build: {', '.join(unsupported)}",
            )
        )
    return out


def insert_lead_eligibility(
    conn: Connection,
    *,
    lead_id: str,
    flags: list[dict[str, Any]],
) -> None:
    # Ids are positional (`{lead_id}-E{n}`), so a re-evaluation that produces a
    # different flag order or count would leave stale rows behind and
    # ON CONFLICT DO NOTHING would keep the *old* verdict under a reused id.
    # Replace the lead's set wholesale inside the caller's transaction.
    conn.execute(
        text("DELETE FROM lead_eligibility WHERE lead_id = :lead_id"),
        {"lead_id": lead_id},
    )
    for idx, flag in enumerate(flags):
        fid = f"{lead_id}-E{idx + 1}"
        conn.execute(
            text(
                """
                INSERT INTO lead_eligibility (id, lead_id, rule_id, label, passed, reason, created_at)
                VALUES (:id, :lead_id, :rule_id, :label, :passed, :reason, now())
                ON CONFLICT (id) DO UPDATE SET
                  rule_id = EXCLUDED.rule_id,
                  label = EXCLUDED.label,
                  passed = EXCLUDED.passed,
                  reason = EXCLUDED.reason
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
    """Hard-block only on explicit fail of a blocking rule. Unknown never blocks.

    Blocking-ness comes from the flag's ``blocking`` field (set alongside a
    stable ``code`` by evaluate_product_eligibility), not from matching English
    words in the label — a label reworded for the UI must not silently turn a
    compliance gate off.
    """
    for f in flags:
        status = (f.get("status") or "").lower()
        if status in {"unknown", "skipped"}:
            continue
        if status != "fail" and f.get("passed") is not False:
            continue
        blocking = f.get("blocking")
        if blocking is None:
            # Pre-`blocking` flag shape — fall back to the old label heuristic.
            label = (f.get("label") or "").lower()
            blocking = any(k in label for k in _LEGACY_BLOCKING_LABEL_KEYWORDS)
        if blocking:
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
        "offer_suppressed",
        "eligibility_checked",
        "lead_captured",
        # The close probe is its own funnel stage. Without it the analytics
        # cannot tell "asked and declined" from "never asked" — which is the
        # only number that says whether asking is worth the handle time.
        "close_probe_presented",
        "identity_verified",
        "identity_partial",
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
    # Validate before truncation: activity_events.kind drives the analytics
    # rollups and the Inbox timeline icons, so an unrecognised (or silently
    # 80-char-clipped) kind becomes an invisible event nobody reports on.
    if kind not in COMMERCIAL_KINDS:
        raise ValueError(f"unsupported_commercial_event_kind: {kind!r}")
    event_id = _sid("ACT")
    import db as _db  # lazy: capture is imported by db, avoid a circular import at load

    bot_id = actor_bot_id if actor_kind == "bot" else None
    user_id = actor_user_id if actor_kind == "human" else None
    if actor_kind == "bot" and not bot_id:
        bot_id = getattr(_db, "DEFAULT_BOT_ID", None)

    # No SELECT probe: it cost a round trip per event and raced anyway (a bot
    # deleted between probe and insert still blew up on the FK). Resolve the id
    # inside the INSERT — the subselect yields NULL for an unknown bot and the
    # actor_kind degrades to 'system' in the same statement.
    resolve_bot = bot_id is not None and actor_kind == "bot"
    actor_bot_expr = (
        "(SELECT b.id FROM bots b WHERE b.id = :actor_bot_id)" if resolve_bot else ":actor_bot_id"
    )
    actor_kind_expr = (
        "(CASE WHEN EXISTS (SELECT 1 FROM bots b WHERE b.id = :actor_bot_id)"
        " THEN :actor_kind ELSE 'system' END)"
        if resolve_bot
        else ":actor_kind"
    )
    conn.execute(
        text(
            f"""
            INSERT INTO activity_events (
              id, tenant_id, entity_type, entity_id, at,
              actor_kind, actor_user_id, actor_bot_id,
              kind, label, note, tone, payload, created_at
            ) VALUES (
              :id, :tenant, :entity_type, :entity_id, now(),
              {actor_kind_expr}, :actor_user_id, {actor_bot_expr},
              :kind, :label, :note, :tone, CAST(:payload AS jsonb), now()
            )
            """
        ),
        {
            "id": event_id,
            "tenant": _db.current_tenant(),
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_kind": actor_kind if actor_kind in {"human", "bot", "system", "customer"} else "system",
            "actor_user_id": user_id,
            "actor_bot_id": bot_id,
            "kind": kind,
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


# Retries for the auto-allocated turn_index. Contention is between the two
# writers on one interaction (the pipeline and a CRM sink flush), so a handful
# of attempts is far more than the observed depth.
_TURN_ALLOC_ATTEMPTS = 5


def _insert_next_transcript_turn(
    conn: Connection,
    *,
    interaction_id: str,
    speaker: str,
    at_sec: float,
    content: str,
    sentiment_delta: float | None,
    intent: str | None,
    intent_score: float | None,
    ttfb_ms: int | None,
    ttfa_ms: int | None,
    tokens: int | None,
) -> Any:
    """One attempt at MAX(turn_index)+1. Returns the row, or None on conflict."""
    return (
        conn.execute(
            text(
                """
                INSERT INTO interaction_transcript (
                  id, interaction_id, turn_index, speaker, at_sec, text,
                  sentiment_delta, intent, intent_score,
                  ttfb_ms, ttfa_ms, tokens, created_at
                )
                SELECT
                  :id, :interaction_id,
                  COALESCE(
                    (SELECT MAX(turn_index) FROM interaction_transcript WHERE interaction_id = :interaction_id),
                    -1
                  ) + 1,
                  :speaker, :at_sec, :text,
                  :sentiment_delta, :intent, :intent_score,
                  :ttfb_ms, :ttfa_ms, :tokens, now()
                ON CONFLICT (interaction_id, turn_index) DO NOTHING
                RETURNING turn_index
                """
            ),
            {
                # Unique temp id, not a shared "-T-next" sentinel: if a previous
                # auto-allocate hit ON CONFLICT DO NOTHING its rename never ran,
                # leaving "-T-next" in the table — the next insert then failed on
                # the *primary key*, which the (interaction_id, turn_index)
                # conflict target does not cover.
                "id": f"{interaction_id}-T-next-{uuid.uuid4().hex[:12]}",
                "interaction_id": interaction_id,
                "speaker": speaker,
                "at_sec": int(max(0, round(at_sec))),
                "text": content,
                "sentiment_delta": sentiment_delta,
                "intent": intent,
                "intent_score": intent_score,
                "ttfb_ms": ttfb_ms,
                "ttfa_ms": ttfa_ms,
                "tokens": tokens,
            },
        )
        .mappings()
        .first()
    )


def insert_transcript_turn(
    conn: Connection,
    *,
    interaction_id: str,
    speaker: str,
    text_content: str,
    at_sec: float = 0,
    turn_index: int | None = None,
    sentiment_delta: float | None = None,
    intent: str | None = None,
    intent_score: float | None = None,
    ttfb_ms: int | None = None,
    ttfa_ms: int | None = None,
    tokens: int | None = None,
) -> int:
    """Insert one transcript turn; allocate turn_index atomically when omitted."""
    content = (text_content or "").strip()
    if not content:
        raise ValueError("text_content must not be empty")

    if turn_index is None:
        # ON CONFLICT DO NOTHING means a concurrent writer took the index this
        # statement computed. Retry with a freshly computed index — returning
        # next_transcript_turn_index() here reported a turn as persisted that
        # was never inserted, silently losing a turn of a recorded call.
        row = None
        for _ in range(_TURN_ALLOC_ATTEMPTS):
            row = _insert_next_transcript_turn(
                conn,
                interaction_id=interaction_id,
                speaker=speaker,
                at_sec=at_sec,
                content=content,
                sentiment_delta=sentiment_delta,
                intent=intent,
                intent_score=intent_score,
                ttfb_ms=ttfb_ms,
                ttfa_ms=ttfa_ms,
                tokens=tokens,
            )
            if row is not None:
                break
        if row is None:
            raise RuntimeError(
                f"transcript_turn_allocation_failed: interaction={interaction_id}"
            )
        idx = int(row["turn_index"])
        # Stable id after we know the allocated index. Savepoint-guarded: the
        # canonical id could already be taken by an older row for the same
        # (interaction, index) pair, and the turn itself is more valuable than
        # the cosmetic id.
        nested = conn.begin_nested()
        try:
            conn.execute(
                text(
                    "UPDATE interaction_transcript SET id = :id "
                    "WHERE interaction_id = :ix AND turn_index = :ti"
                ),
                {"id": f"{interaction_id}-T{idx}", "ix": interaction_id, "ti": idx},
            )
            nested.commit()
        except Exception:
            nested.rollback()
            logger.warning(
                "transcript turn id normalisation skipped interaction=%s turn=%s",
                interaction_id,
                idx,
                exc_info=True,
            )
        return idx

    conn.execute(
        text(
            """
            INSERT INTO interaction_transcript (
              id, interaction_id, turn_index, speaker, at_sec, text,
              sentiment_delta, intent, intent_score,
              ttfb_ms, ttfa_ms, tokens, created_at
            ) VALUES (
              :id, :interaction_id, :turn_index, :speaker, :at_sec, :text,
              :sentiment_delta, :intent, :intent_score,
              :ttfb_ms, :ttfa_ms, :tokens, now()
            )
            ON CONFLICT (interaction_id, turn_index) DO NOTHING
            """
        ),
        {
            "id": f"{interaction_id}-T{turn_index}",
            "interaction_id": interaction_id,
            "turn_index": turn_index,
            "speaker": speaker,
            "at_sec": int(max(0, round(at_sec))),
            "text": content,
            "sentiment_delta": sentiment_delta,
            "intent": intent,
            "intent_score": intent_score,
            "ttfb_ms": ttfb_ms,
            "ttfa_ms": ttfa_ms,
            "tokens": tokens,
        },
    )
    return turn_index


def record_product_interest(
    conn: Connection,
    *,
    interaction_id: str,
    intent: str,
    snippet: str | None = None,
    actor_bot_id: str | None = None,
    topics: list[str] | None = None,
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
        # `topics` is what the offer engine reads back as kb_topics_queried.
        payload={"intent": intent, "topics": list(topics or [])},
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
    actor_user_id: str | None = None,
) -> None:
    """The offer funnel's numerator, for every capture path.

    Two rows when the capture happened on a call: one against the interaction,
    so Bot Analytics can join it to that call's ``offer_presented``, and one
    against the lead. Anything counting conversions must count distinct leads
    rather than rows — see agent_core/reco/observability.py.

    Now that human captures come through here too, the actor has to be told
    apart. Defaulting to a bot actor would have credited every lead a rep
    raised in the UI to whichever bot id the process happened to configure.
    """
    actor_kind = "bot" if actor_bot_id else ("human" if actor_user_id else "system")
    attribution: dict[str, Any] = {
        "actor_kind": actor_kind,
        "actor_bot_id": actor_bot_id,
        "actor_user_id": actor_user_id,
    }
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
            **attribution,
        )
    emit_commercial_event(
        conn,
        entity_type="lead",
        entity_id=lead_id,
        kind="lead_captured",
        label="Lead captured",
        note=product_id,
        payload={"interactionId": interaction_id, "productId": product_id},
        **attribution,
    )


def record_offer_declined(
    conn: Connection,
    *,
    interaction_id: str | None,
    customer_id: str,
    product_id: str | None,
    reason: str | None = None,
    actor_bot_id: str | None = None,
) -> None:
    """A pitch that was heard and refused.

    Distinct from never pitching: the funnel needs the denominator. Recorded
    against the interaction when there is one so Bot Analytics can join it to
    ``offer_presented`` on the same call.
    """
    emit_commercial_event(
        conn,
        entity_type="interaction" if interaction_id else "customer",
        entity_id=interaction_id or customer_id,
        kind="offer_declined",
        label="Offer declined",
        note=(reason or product_id or "")[:240] or None,
        payload={"productId": product_id, "customerId": customer_id, "reason": reason},
        actor_bot_id=actor_bot_id,
    )


def record_offer_suppressed(
    conn: Connection,
    *,
    interaction_id: str | None,
    customer_id: str,
    reason: str,
    actor_bot_id: str | None = None,
) -> None:
    """The engine had something to say and policy stopped it.

    Logged because a silent suppression is indistinguishable from an engine
    that found nothing, and the two need very different fixes.
    """
    emit_commercial_event(
        conn,
        entity_type="interaction" if interaction_id else "customer",
        entity_id=interaction_id or customer_id,
        kind="offer_suppressed",
        label=f"Offer suppressed | {reason}",
        note=reason[:240],
        payload={"customerId": customer_id, "reason": reason},
        actor_bot_id=actor_bot_id,
    )


def record_close_probe(
    conn: Connection,
    *,
    interaction_id: str,
    with_offer: bool,
    product_id: str | None = None,
    actor_bot_id: str | None = None,
) -> None:
    """The end-of-call "anything else?" question was actually asked."""
    emit_commercial_event(
        conn,
        entity_type="interaction",
        entity_id=interaction_id,
        kind="close_probe_presented",
        label="Close probe presented" + (" with offer" if with_offer else ""),
        note=product_id,
        payload={"withOffer": with_offer, "productId": product_id},
        actor_bot_id=actor_bot_id,
    )


def find_customer_by_account_tail(conn: Connection, tail: str) -> dict[str, Any] | None:
    """Resolve customer by last-4 account digits — fail closed on ambiguity."""
    digits = "".join(ch for ch in (tail or "") if ch.isdigit())
    if len(digits) < 4:
        return None
    tail4 = digits[-4:]
    rows = conn.execute(
        text(
            """
            SELECT c.id, c.name, c.phone_primary, a.id AS account_id
            FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE RIGHT(regexp_replace(a.id, '[^0-9]', '', 'g'), 4) = :tail
               OR RIGHT(a.id, 4) = :tail
            ORDER BY a.updated_at DESC NULLS LAST, a.id
            """
        ),
        {"tail": tail4},
    ).mappings().all()
    if not rows:
        return None
    # Distinct customers — multiple accounts for the same customer is fine.
    # Unbounded on purpose: a LIMIT here could truncate away the very row that
    # proves the tail is ambiguous, turning a fail-closed into a false match.
    customer_ids = {r["id"] for r in rows}
    if len(customer_ids) > 1:
        return None
    return dict(rows[0])


def rebind_interaction_customer(
    conn: Connection,
    *,
    interaction_id: str,
    customer_id: str,
    method: str = "phone_match",
    account_id: str | None = None,
    actor_bot_id: str | None = None,
    verification_status: str = "verified",
) -> dict[str, Any]:
    """Rebind interaction (+ linked conversation) to a verified customer."""
    if method not in {"phone_match", "dob", "otp", "account_tail", "manual"}:
        method = "manual"
    if verification_status not in {"verified", "pending", "failed"}:
        verification_status = "verified"

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

    # Tail-only matches are never treated as full verification (schema: pending).
    if method == "account_tail" and verification_status == "verified":
        verification_status = "pending"

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
              :id, :iid, :cid, :method, :status,
              1, CASE WHEN :status = 'verified' THEN now() ELSE NULL END, now(), now()
            )
            """
        ),
        {
            "id": vid,
            "iid": interaction_id,
            "cid": customer_id,
            "method": method,
            "status": verification_status,
        },
    )
    emit_commercial_event(
        conn,
        entity_type="interaction",
        entity_id=interaction_id,
        kind="identity_verified" if verification_status == "verified" else "identity_partial",
        label=f"Identity {verification_status} | {method}",
        note=cust.get("name"),
        payload={
            "customerId": customer_id,
            "accountId": account_id,
            "method": method,
            "status": verification_status,
            "previousCustomerId": ix.get("customer_id"),
            "verificationId": vid,
        },
        actor_bot_id=actor_bot_id,
    )
    # Never return PII when verification is incomplete.
    if verification_status != "verified":
        return {
            "interactionId": interaction_id,
            "customerId": customer_id,
            "accountId": account_id,
            "method": method,
            "status": verification_status,
            "verificationId": vid,
        }
    return {
        "interactionId": interaction_id,
        "customerId": customer_id,
        "customerName": cust.get("name"),
        "accountId": account_id,
        "method": method,
        "status": verification_status,
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
