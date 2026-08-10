"""Candidate generation — what may be offered at all, before any ranking.

Kept strictly separate from scoring. Exclusions here are categorical ("they
already hold it", "the campaign ended"), not preferences, and every one of them
records *why*. A recommender that returns nothing must be able to say whether
that was because the customer was ineligible for everything or because someone
switched the whole catalog off — those need very different fixes, and "no
offers" looks identical from the outside.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from agent_core.reco.features import CustomerFeatures

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Candidate:
    """A product that survived candidate generation, with its catalog facts."""

    product_id: str
    name: str
    category: str | None
    family: str | None
    description: str | None
    ticket_min: float | None
    ticket_max: float | None
    roi: str | None
    roi_numeric: float | None
    margin_score: float
    # Best affinity from anything the customer already holds, 0..1.
    affinity: float
    # Live campaign priority, or None when the product has no campaign at all
    # (which is allowed — campaigns are an overlay, not a requirement).
    campaign_id: str | None
    campaign_priority: float | None


# Reasons are stable identifiers, not prose: they go into the decision log and
# get counted. Changing the wording of a reason must not silently start a new
# series in the dashboards.
REASON_INACTIVE = "inactive"
REASON_CHANNEL = "channel_not_supported"
REASON_ALREADY_HELD = "already_held"
REASON_OPEN_LEAD = "open_lead_exists"
REASON_EXCLUDED_BY_HOLDING = "excluded_by_holding"
REASON_REQUIRES_MISSING = "requires_product_not_held"
REASON_CAMPAIGN_ENDED = "campaign_not_live"
REASON_CAMPAIGN_QUOTA = "campaign_quota_exhausted"
REASON_CAMPAIGN_SEGMENT = "campaign_segment_mismatch"
REASON_CAMPAIGN_RISK = "campaign_risk_excluded"
REASON_DECLINED_COOLDOWN = "declined_recently"
REASON_FAMILY_COOLDOWN = "family_declined_recently"


def _f(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def generate(
    conn: Any,
    *,
    features: CustomerFeatures,
    channel: str,
    decline_cooldown_days: int,
    family_cooldown_days: int = 0,
) -> tuple[list[Candidate], dict[str, str]]:
    """Return ``(candidates, {product_id: exclusion_reason})``.

    Two cool-downs, because "no" means different things at different scopes: a
    refused product is off the table for ``decline_cooldown_days``, and its
    whole family is off for the shorter ``family_cooldown_days`` — someone who
    just turned down a top-up does not want a personal loan next week either.
    """
    products = conn.execute(
        text(
            """
            SELECT id, name, category, family, description, type,
                   ticket_min, ticket_max, roi, roi_numeric,
                   margin_score, is_active, channels
            FROM products
            ORDER BY id
            """
        )
    ).mappings().all()

    relations = _relations(conn)
    campaigns, campaigned_products = _live_campaigns(conn)
    now = datetime.now(timezone.utc)
    cooldown_cutoff = now - timedelta(days=decline_cooldown_days)
    family_cutoff = now - timedelta(days=family_cooldown_days) if family_cooldown_days else None
    # Families the customer refused recently. Resolved from the declined ids so
    # the rule survives a product being renamed or superseded.
    declined_families = _families_of(products, features.declined_product_ids)

    held = features.held_product_ids
    excluded: dict[str, str] = {}
    out: list[Candidate] = []

    for p in products:
        pid = str(p["id"])

        if not p.get("is_active", True):
            excluded[pid] = REASON_INACTIVE
            continue

        channels = list(p.get("channels") or [])
        if channels and channel not in channels:
            excluded[pid] = REASON_CHANNEL
            continue

        if pid in held:
            excluded[pid] = REASON_ALREADY_HELD
            continue

        if pid in features.open_lead_product_ids:
            # An open lead is already someone's job. Offering it again on a
            # later call is how a customer gets called twice about one thing.
            excluded[pid] = REASON_OPEN_LEAD
            continue

        # `excludes` is directional: holding A rules out B.
        blocked_by = next(
            (h for h in held if (h, pid) in relations.get("excludes", set())), None
        )
        if blocked_by:
            excluded[pid] = REASON_EXCLUDED_BY_HOLDING
            continue

        # `requires` means B is only sellable to a holder of A.
        required = relations.get("requires_by_product", {}).get(pid)
        if required and not (required & held):
            excluded[pid] = REASON_REQUIRES_MISSING
            continue

        if pid in features.declined_product_ids and features.last_offer_at:
            if features.last_offer_at > cooldown_cutoff:
                excluded[pid] = REASON_DECLINED_COOLDOWN
                continue

        family = p.get("family")
        if (
            family_cutoff is not None
            and family
            and family in declined_families
            and features.last_offer_at
            and features.last_offer_at > family_cutoff
        ):
            excluded[pid] = REASON_FAMILY_COOLDOWN
            continue

        campaign = campaigns.get(pid)
        campaign_id = campaign_priority = None
        if campaign is None:
            if pid in campaigned_products:
                # Has campaigns, none live: paused, or the window closed.
                excluded[pid] = REASON_CAMPAIGN_ENDED
                continue
        else:
            reason = _campaign_mismatch(campaign, features)
            if reason:
                excluded[pid] = reason
                continue
            campaign_id = str(campaign["id"])
            campaign_priority = _f(campaign.get("priority"), 0.5)

        affinity = _best_affinity(relations, held, pid)

        out.append(
            Candidate(
                product_id=pid,
                name=str(p["name"]),
                category=(p.get("category") or p.get("type") or None),
                family=p.get("family"),
                description=p.get("description"),
                ticket_min=_f(p.get("ticket_min")),
                ticket_max=_f(p.get("ticket_max")),
                roi=p.get("roi"),
                roi_numeric=_f(p.get("roi_numeric")),
                margin_score=_f(p.get("margin_score"), 0.5) or 0.5,
                affinity=affinity,
                campaign_id=campaign_id,
                campaign_priority=campaign_priority,
            )
        )

    return out, excluded


def _families_of(products: Any, product_ids: "frozenset[str] | set[str]") -> set[str]:
    """Product families for a set of ids, skipping ones with no family set."""
    if not product_ids:
        return set()
    return {
        str(p["family"])
        for p in products
        if p.get("family") and str(p["id"]) in product_ids
    }


def _campaign_mismatch(campaign: dict[str, Any], features: CustomerFeatures) -> str | None:
    if campaign.get("quota_total") is not None:
        used = int(campaign.get("quota_used") or 0)
        if used >= int(campaign["quota_total"]):
            return REASON_CAMPAIGN_QUOTA

    segments = campaign.get("segment_in")
    if segments:
        segment = (features.segment or "").strip().lower()
        if segment not in {str(s).strip().lower() for s in segments}:
            return REASON_CAMPAIGN_SEGMENT

    risks = campaign.get("risk_not_in")
    if risks:
        risk = (features.risk or "").strip().lower()
        if risk and risk in {str(r).strip().lower() for r in risks}:
            return REASON_CAMPAIGN_RISK

    return None


def _live_campaigns(conn: Any) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """``(highest-priority live campaign per product, products with any campaign)``.

    A product with **no** campaign row is still offerable — campaigns are an
    overlay for marketing to push or pause something, not a prerequisite.
    Treating "no campaign" as "not live" would silently switch off every
    product nobody had got round to promoting.

    A product with campaigns of which **none is currently live** is a different
    case and *is* excluded: somebody deliberately gave it a window, or paused
    it, and the window closed. Distinguishing the two needs both sets, which is
    why this returns the second one — an earlier version returned only the live
    map, so an expired campaign was indistinguishable from no campaign and
    ``REASON_CAMPAIGN_ENDED`` could never be emitted.
    """
    rows = conn.execute(
        text(
            """
            SELECT id, product_id, priority, quota_total, quota_used,
                   segment_in, risk_not_in, starts_at, ends_at, enabled,
                   (
                     enabled IS TRUE
                     AND (starts_at IS NULL OR starts_at <= now())
                     AND (ends_at IS NULL OR ends_at >= now())
                   ) AS is_live
            FROM product_campaigns
            ORDER BY product_id, priority DESC, id
            """
        )
    ).mappings().all()

    best: dict[str, dict[str, Any]] = {}
    has_any: set[str] = set()
    for r in rows:
        pid = str(r["product_id"])
        has_any.add(pid)
        if r["is_live"]:
            best.setdefault(pid, dict(r))
    return best, has_any


def _relations(conn: Any) -> dict[str, Any]:
    """Relation graph, shaped for the three lookups generation actually does."""
    rows = conn.execute(
        text("SELECT product_id, related_product_id, relation, affinity FROM product_relations")
    ).mappings().all()

    excludes: set[tuple[str, str]] = set()
    requires_by_product: dict[str, set[str]] = {}
    affinity: dict[tuple[str, str], float] = {}

    for r in rows:
        src, dst = str(r["product_id"]), str(r["related_product_id"])
        rel = str(r["relation"])
        if rel == "excludes":
            # Symmetric: holding either one rules out the other.
            excludes.add((src, dst))
            excludes.add((dst, src))
        elif rel == "requires":
            requires_by_product.setdefault(src, set()).add(dst)
        else:  # complements / upgrades
            affinity[(src, dst)] = _f(r.get("affinity"), 0.5) or 0.5
            affinity.setdefault((dst, src), _f(r.get("affinity"), 0.5) or 0.5)

    return {
        "excludes": excludes,
        "requires_by_product": requires_by_product,
        "affinity": affinity,
    }


def _best_affinity(relations: dict[str, Any], held: frozenset[str], pid: str) -> float:
    """Strongest complementarity between anything held and this candidate.

    0.5 (neutral) when the customer holds nothing or no edge exists — an absent
    edge means "we have not expressed an opinion", not "bad match".
    """
    if not held:
        return 0.5
    scores = [relations["affinity"].get((h, pid)) for h in held]
    scores = [s for s in scores if s is not None]
    return max(scores) if scores else 0.5
