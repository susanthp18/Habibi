"""Deterministic Customer 360 insights / next-best-action derivation.

Mirrors Habibi/src/lib/customerInsights.ts so mock and live stay aligned.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _days_between(iso: str | None, now: datetime | None = None) -> int | None:
    dt = _parse_iso(iso)
    if dt is None:
        return None
    ref = now or _now()
    return int(round((ref - dt).total_seconds() / 86_400))


def _within_window(pref: str) -> bool:
    m = re.search(r"(\d{1,2}):(\d{2})[–-](\d{1,2}):(\d{2})", pref or "")
    if not m:
        return True
    start = int(m.group(1)) * 60 + int(m.group(2))
    end = int(m.group(3)) * 60 + int(m.group(4))
    now = datetime.now()
    cur = now.hour * 60 + now.minute
    return start <= cur <= end


def _inr(n: float | int) -> str:
    return f"₹{int(n):,}".replace(",", ",")


def compute_metrics(customer: dict[str, Any]) -> dict[str, Any]:
    promises = customer.get("promises") or []
    settled = [p for p in promises if p.get("status") in ("kept", "broken")]
    kept = len([p for p in promises if p.get("status") == "kept"])
    ptp_keep_rate = round((kept / len(settled)) * 100) if settled else None

    interactions = sorted(
        customer.get("interactions") or [],
        key=lambda i: i.get("startedAt") or "",
        reverse=True,
    )
    contact_iso = (interactions[0].get("startedAt") if interactions else None) or customer.get("lastContact")
    days_since = _days_between(contact_iso)

    open_dispute_amount = sum(
        float(d.get("amount") or 0)
        for d in (customer.get("disputes") or [])
        if d.get("status") not in ("resolved", "rejected")
    )

    emi = customer.get("emi") or []
    next_emi = next((e for e in emi if e.get("status") == "overdue"), None) or next(
        (e for e in emi if e.get("status") == "upcoming"), None
    )
    broken_count = len([p for p in promises if p.get("status") == "broken"])
    active_amount = sum(float(p.get("amount") or 0) for p in promises if p.get("status") == "upcoming")

    payment_streak = 0
    for e in sorted(emi, key=lambda x: x.get("index") or 0):
        if e.get("status") == "paid":
            payment_streak += 1
        else:
            break

    return {
        "ptpKeepRate": ptp_keep_rate,
        "daysSinceContact": days_since,
        "openDisputeAmount": open_dispute_amount,
        "nextEmiAmount": float(next_emi["amount"]) if next_emi and next_emi.get("amount") is not None else None,
        "nextEmiDate": next_emi.get("dueDate") if next_emi else None,
        "paymentStreak": payment_streak,
        "brokenPromiseCount": broken_count,
        "activePromiseAmount": active_amount,
    }


def _offer_nba(policy: dict[str, Any] | None) -> dict[str, Any] | None:
    """Grow-class action. Never a pitch when the engine said stay quiet."""
    if not policy:
        return None
    status = policy.get("status")
    if status not in {"ready", "presented", "interested", "open_lead"}:
        return None
    product = policy.get("productName") or "an eligible product"
    amount = policy.get("suggestedAmount")
    amt = f" · ₹{int(amount):,}" if amount else ""
    window = policy.get("preferredWindow")
    follow = status in {"open_lead", "interested"}
    reason = policy.get("talkTrack") or "Engine-approved offer for this account."
    if window:
        reason = f"{reason} Preferred window: {window}."
    return {
        "id": "nba-offer",
        "rank": 99,
        "title": f"{'Follow up' if follow else 'Pitch'} {product}{amt}",
        "reason": reason,
        "action": "offer",
        "priority": "medium",
        "leadId": policy.get("leadId"),
    }


def build_nba(
    customer: dict[str, Any],
    metrics: dict[str, Any],
    offer_policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    consent = customer.get("consent") or []
    contact = customer.get("contact") or {}
    account = customer.get("account") or {}

    call_opted_in = next((c.get("optedIn") for c in consent if c.get("channel") == "call"), False)
    in_window = _within_window(contact.get("preferredWindow") or "")
    open_dispute = next(
        (d for d in (customer.get("disputes") or []) if d.get("status") in ("under_review", "new")),
        None,
    )
    upcoming = sorted(
        [p for p in (customer.get("promises") or []) if p.get("status") == "upcoming"],
        key=lambda p: p.get("promisedDate") or "",
    )
    upcoming_ptp = upcoming[0] if upcoming else None
    days_to_ptp = None
    if upcoming_ptp:
        d = _days_between(upcoming_ptp.get("promisedDate"))
        days_to_ptp = -d if d is not None else None

    if contact.get("dnd") or not call_opted_in:
        items.append(
            {
                "id": "nba-callback-channel",
                "rank": 1,
                "title": "Use WhatsApp / email — voice blocked",
                "reason": "DND is active on this account." if contact.get("dnd") else "Customer opted out of voice.",
                "action": "callback",
                "priority": "high",
            }
        )
    elif not in_window:
        items.append(
            {
                "id": "nba-schedule-callback",
                "rank": 1,
                "title": "Schedule callback in contact window",
                "reason": f"Outside preferred window ({contact.get('preferredWindow')}). Do not dial now.",
                "action": "callback",
                "priority": "high",
            }
        )

    if open_dispute:
        items.append(
            {
                "id": "nba-review-dispute",
                "rank": len(items) + 1,
                "title": "Review open dispute before hard collect",
                "reason": f"{open_dispute.get('id')} is {str(open_dispute.get('status', '')).replace('_', ' ')} ({_inr(open_dispute.get('amount') or 0)}).",
                "action": "review",
                "priority": "high",
            }
        )

    if upcoming_ptp and days_to_ptp is not None and days_to_ptp <= 3:
        items.append(
            {
                "id": "nba-confirm-ptp",
                "rank": len(items) + 1,
                "title": "Confirm upcoming PTP channel",
                "reason": (
                    f"{_inr(upcoming_ptp.get('amount') or 0)} promised "
                    f"{'today/overdue' if days_to_ptp <= 0 else f'in {days_to_ptp}d'} "
                    f"via {upcoming_ptp.get('channel')}."
                ),
                "action": "ptp",
                "priority": "high" if days_to_ptp <= 1 else "medium",
            }
        )

    if metrics.get("brokenPromiseCount", 0) > 0:
        items.append(
            {
                "id": "nba-smaller-ptp",
                "rank": len(items) + 1,
                "title": "Offer smaller PTP or payment plan",
                "reason": f"{metrics['brokenPromiseCount']} broken promise(s) on file — avoid repeating full-balance asks.",
                "action": "ptp",
                "priority": "medium",
            }
        )

    dpd = int(account.get("dpd") or 0)
    days_since = metrics.get("daysSinceContact")
    if dpd > 30 and (days_since is None or days_since >= 7) and call_opted_in and not contact.get("dnd"):
        items.append(
            {
                "id": "nba-outbound-call",
                "rank": len(items) + 1,
                "title": "Log outbound collections call",
                "reason": f"DPD {dpd} with {days_since if days_since is not None else 'no'} day(s) since last contact.",
                "action": "call",
                "priority": "medium",
            }
        )

    docs = customer.get("documents") or []
    if not any(d.get("status") in ("sent", "generating") for d in docs):
        items.append(
            {
                "id": "nba-send-statement",
                "rank": len(items) + 1,
                "title": "Send account statement",
                "reason": "No recent statement delivery on file — useful before negotiation.",
                "action": "statement",
                "priority": "low",
            }
        )

    offer_item = _offer_nba(offer_policy)
    if offer_item:
        items.append(offer_item)

    if not items:
        items.append(
            {
                "id": "nba-log-touch",
                "rank": 1,
                "title": "Log a soft touchpoint",
                "reason": "Account is stable — capture a note or confirm next EMI.",
                "action": "call",
                "priority": "low",
            }
        )

    priority_order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: (priority_order.get(x["priority"], 9), x["rank"]))
    for i, item in enumerate(items[:5], start=1):
        item["rank"] = i
    return items[:5]


def build_summary(
    customer: dict[str, Any],
    metrics: dict[str, Any],
    nba: list[dict[str, Any]],
    offer_policy: dict[str, Any] | None = None,
    authority_policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    bullets: list[dict[str, Any]] = []
    account = customer.get("account") or {}
    name = customer.get("name") or "Customer"

    bullets.append(
        {
            "id": "ins-position",
            "text": (
                f"{name} is in bucket {account.get('bucket')} at {account.get('dpd')} DPD with "
                f"{_inr(customer.get('outstanding') or 0)} outstanding "
                f"(min due {_inr(customer.get('minimumDue') or 0)})."
            ),
            "source": "from account position",
            "confidence": "high",
        }
    )

    keep = metrics.get("ptpKeepRate")
    if keep is not None:
        bullets.append(
            {
                "id": "ins-ptp",
                "text": (
                    f"PTP keep-rate is {keep}% — customer has some follow-through; prefer confirmed smaller commitments."
                    if keep >= 50
                    else f"PTP keep-rate is only {keep}% with {metrics.get('brokenPromiseCount', 0)} broken — treat new promises cautiously."
                ),
                "source": "from PTP history",
                "confidence": "high",
            }
        )
    elif (metrics.get("activePromiseAmount") or 0) > 0:
        bullets.append(
            {
                "id": "ins-ptp-active",
                "text": (
                    f"{_inr(metrics['activePromiseAmount'])} in active promises with no settled history yet — "
                    "confirm channel and ability to pay."
                ),
                "source": "from PTP history",
                "confidence": "medium",
            }
        )

    interactions = sorted(
        customer.get("interactions") or [],
        key=lambda i: i.get("startedAt") or "",
        reverse=True,
    )
    if interactions:
        ix = interactions[0]
        summary = (ix.get("summary") or "")[:120]
        if len(ix.get("summary") or "") > 120:
            summary += "…"
        handler = (ix.get("handler") or {}).get("name") or "agent"
        bullets.append(
            {
                "id": "ins-last-ix",
                "text": f"Last {ix.get('channel')} touch ({handler}): “{summary}” — sentiment {ix.get('sentiment')}.",
                "source": "from last interaction",
                "confidence": "high",
            }
        )

    open_dispute = next(
        (d for d in (customer.get("disputes") or []) if d.get("status") not in ("resolved", "rejected")),
        None,
    )
    if open_dispute:
        bullets.append(
            {
                "id": "ins-dispute",
                "text": (
                    f"Open dispute {open_dispute.get('id')} ({_inr(open_dispute.get('amount') or 0)}) is "
                    f"{str(open_dispute.get('status', '')).replace('_', ' ')} — avoid aggressive collection until resolved."
                ),
                "source": "from disputes",
                "confidence": "high",
            }
        )

    if authority_policy and authority_policy.get("status") not in {None, "none"}:
        status = authority_policy.get("status")
        if status == "escalate":
            text = (
                "Live goodwill is out of policy: "
                f"{authority_policy.get('reasonLabel') or authority_policy.get('reason') or 'escalate'}. "
                "Do not quote a waiver or settlement figure."
            )
        elif status == "applied":
            amt = authority_policy.get("approvedAmount")
            text = f"Goodwill already posted{f' ({_inr(amt)})' if amt else ''}."
        else:
            amt = authority_policy.get("approvedAmount")
            text = (
                f"In-policy late-fee goodwill up to {_inr(amt)}."
                if amt
                else "Authority matrix has an allowed move — do not invent a larger figure."
            )
        bullets.append(
            {
                "id": "ins-authority",
                "text": text,
                "source": "from authority matrix",
                "confidence": "high",
            }
        )

    if offer_policy and offer_policy.get("status") == "suppressed":
        label = offer_policy.get("suppressionLabel") or offer_policy.get("suppressionReason") or "stayed quiet"
        bullets.append(
            {
                "id": "ins-offer-quiet",
                "text": f"Offer engine quiet: {label}. Do not freelance a product.",
                "source": "from offer policy",
                "confidence": "high",
            }
        )

    if nba:
        bullets.append(
            {
                "id": "ins-nba",
                "text": f"Recommended next step: {nba[0]['title']}. {nba[0]['reason']}",
                "source": "from next-best-action rules",
                "confidence": "medium",
            }
        )

    return bullets[:5]


def synthesize_activity(customer: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for ix in customer.get("interactions") or []:
        items.append(
            {
                "id": f"act-ix-{ix.get('id')}",
                "kind": "interaction",
                "label": f"{ix.get('channel')} · {ix.get('disposition')}",
                "note": ix.get("summary"),
                "at": ix.get("startedAt"),
                "tone": ix.get("sentiment"),
            }
        )
    for p in customer.get("promises") or []:
        status = p.get("status")
        items.append(
            {
                "id": f"act-ptp-{p.get('id')}",
                "kind": "promise",
                "label": f"PTP {status} · {_inr(p.get('amount') or 0)}",
                "note": f"via {p.get('channel')} · {p.get('handler')}",
                "at": p.get("createdAt"),
                "tone": "negative" if status == "broken" else ("positive" if status == "kept" else None),
            }
        )
    for d in customer.get("disputes") or []:
        items.append(
            {
                "id": f"act-d-{d.get('id')}",
                "kind": "dispute",
                "label": f"Dispute {str(d.get('status', '')).replace('_', ' ')}",
                "note": d.get("transcriptSnippet"),
                "at": d.get("filedAt"),
                "tone": "warning",
            }
        )
    for n in customer.get("notes") or []:
        items.append(
            {
                "id": f"act-n-{n.get('id')}",
                "kind": "note",
                "label": "Pinned note" if n.get("pinned") else "Note added",
                "note": n.get("text"),
                "at": n.get("at"),
                "tone": None,
            }
        )
    for doc in customer.get("documents") or []:
        items.append(
            {
                "id": f"act-doc-{doc.get('id')}",
                "kind": "document",
                "label": f"{doc.get('type')} · {doc.get('status')}",
                "note": f"via {doc.get('deliveryChannel')}",
                "at": doc.get("requestedAt"),
                "tone": None,
            }
        )
    items.sort(key=lambda x: x.get("at") or "", reverse=True)
    return items[:8]


def derive_insights(
    customer: dict[str, Any],
    activity: list[dict[str, Any]] | None = None,
    offer_policy: dict[str, Any] | None = None,
    authority_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = compute_metrics(customer)
    nba = build_nba(customer, metrics, offer_policy)
    summary = build_summary(customer, metrics, nba, offer_policy, authority_policy)
    preview = activity if activity else synthesize_activity(customer)
    return {
        "customerId": customer.get("id"),
        "summary": summary,
        "nba": nba,
        "metrics": metrics,
        "activity": preview[:8],
        "generatedAt": _now().isoformat().replace("+00:00", "Z"),
        "offerPolicy": offer_policy,
        "authorityPolicy": authority_policy,
    }
