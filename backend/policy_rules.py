"""Regulatory rules as versioned data, resolved as of an instant.

The calling window, the frequency caps and the cooling-off period lived as
module constants in :mod:`contact_policy`. That works right up to the question a
regulator actually asks, which is not *"would you dial at 19:15?"* but *"why did
you, last March?"*. A constant has no effective date, so the only available
answer was "our current code says we wouldn't have" — which is not an answer,
and which gets worse every time the rules change.

As rows with a validity window, two rule sets are in force at different times
and every decision records which one approved it. A rule change becomes a
**backfill** rather than a fresh start, and a client can tighten policy without a
model deploy.

**Layers, and the direction they may move.** Three scopes resolve together —
statutory, then the tenant's own policy, then the product's — and a later layer
may only ever make the rule *stricter*. That is enforced per kind rather than
asserted: :func:`_tighten` takes the intersection of two calling windows, the
minimum of two caps, the maximum of two cooling-off periods, and it can turn a
permitted mandate return reason into a vetoed one but never the reverse. A
client who could widen the statutory window by adding a row would be a client
who could delete the regulation, and "we only document that they shouldn't" is
not a control.

**The version stamped on a decision is the statutory one.** There are up to
three versions in play and ``treatment_decisions.policy_version`` is one
integer, so it holds the number the regulator's question is about. The full
provenance — every layer, its label and its version — goes into the decision's
feature log via :meth:`RuleSet.to_log`, so nothing is lost and the indexed
column still answers the question it exists for.

**Absent rows mean "unregulated by this table", not "forbidden".** With no rule
set published, :func:`resolve` returns :data:`EMPTY`, every accessor answers
``None``, and each caller falls back to the constant it used before. That is
what makes this safe to deploy ahead of the seed data, and it is why every
accessor is optional rather than defaulted here — a default living in two places
is a default that will disagree with itself.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import text

logger = logging.getLogger(__name__)

SCOPE_STATUTORY = "statutory"
SCOPE_CLIENT = "client"
SCOPE_PRODUCT = "product"

#: Resolution order. Later layers tighten earlier ones and never loosen them.
SCOPE_ORDER: tuple[str, ...] = (SCOPE_STATUTORY, SCOPE_CLIENT, SCOPE_PRODUCT)

KIND_CALLING_WINDOW = "calling_window"
KIND_DAILY_CAP = "daily_cap"
KIND_WEEKLY_CAP = "weekly_cap"
KIND_COOLING_OFF = "cooling_off"
KIND_BUCKET_ACTIONS = "bucket_actions"
KIND_MANDATE_LIMIT = "mandate_presentation_limit"
KIND_MANDATE_RETURN = "mandate_return_action"
KIND_FIELD_PREREQS = "field_prerequisites"
KIND_RECORDING_RETENTION = "recording_retention"
KIND_VISIT_INTIMATION = "visit_intimation"

#: How long a resolved rule set is reused within one process. This is read on
#: every decision, and at book-sweep volumes two queries per decision is two
#: queries per account per day for a value that changes a few times a year.
#: Bounded rather than permanent because a newly published rule set must take
#: effect without a restart — the same reason every other config in this package
#: is read at call time.
CACHE_TTL_SECONDS = 60.0

_CACHE: dict[tuple[str, str, str], tuple[float, "RuleSet"]] = {}
_CACHE_LOCK = threading.Lock()
#: A resolver that grows without bound on a per-tenant key is a memory leak
#: wearing a cache's clothes.
_CACHE_MAX = 512


@dataclass(frozen=True)
class RuleSet:
    """The rules in force at one instant, for one tenant and product."""

    statutory_version: int | None = None
    #: Ordered (scope, label, version) for every layer that contributed.
    provenance: tuple[Mapping[str, Any], ...] = ()
    #: (kind, channel) → params. ``channel`` is None for rules that are not
    #: per-channel, which is most of them.
    rules: Mapping[tuple[str, str | None], Mapping[str, Any]] = field(
        default_factory=dict
    )

    @property
    def version(self) -> int | None:
        """What gets stamped on a decision. See the module docstring."""
        return self.statutory_version

    @property
    def empty(self) -> bool:
        return not self.rules and not self.provenance

    def _params(self, kind: str, channel: str | None = None) -> Mapping[str, Any] | None:
        """Channel-specific rule first, then the all-channel one."""
        if channel is not None:
            specific = self.rules.get((kind, channel))
            if specific is not None:
                return specific
        return self.rules.get((kind, None))

    # -- accessors. Every one may answer None; the caller owns the default. --

    def calling_window(self, channel: str) -> tuple[int, int] | None:
        """Local hours ``[start, end)`` this channel may be used for outreach."""
        params = self._params(KIND_CALLING_WINDOW, channel)
        if not params:
            return None
        start, end = _opt_int(params.get("startHour")), _opt_int(params.get("endHour"))
        if start is None or end is None:
            return None
        return (start, end)

    def daily_cap(self) -> int | None:
        return _opt_int((self._params(KIND_DAILY_CAP) or {}).get("value"))

    def weekly_cap(self, channel: str | None = None) -> int | None:
        return _opt_int((self._params(KIND_WEEKLY_CAP, channel) or {}).get("value"))

    def cooling_off_minutes(self) -> int | None:
        return _opt_int((self._params(KIND_COOLING_OFF) or {}).get("minutes"))

    def mandate_presentation_limit(self) -> int | None:
        """Presentations of the same cycle permitted on one mandate."""
        return _opt_int((self._params(KIND_MANDATE_LIMIT) or {}).get("value"))

    def mandate_return_permits_retry(self, return_reason: str | None) -> bool | None:
        """Whether this return code may be re-presented at all.

        ``None`` means unregulated here, so the caller's own map decides.
        """
        params = self._params(KIND_MANDATE_RETURN)
        if not params:
            return None
        by_reason = params.get("byReason")
        if not isinstance(by_reason, Mapping):
            return None
        verdict = by_reason.get(return_reason or "unknown")
        if verdict is None:
            return None
        return str(verdict).strip().lower() == "allow"

    def bucket_actions(self, bucket: str) -> frozenset[str] | None:
        params = self._params(KIND_BUCKET_ACTIONS)
        if not params:
            return None
        by_bucket = params.get("byBucket")
        if not isinstance(by_bucket, Mapping):
            return None
        allowed = by_bucket.get(bucket)
        if not isinstance(allowed, (list, tuple)):
            return None
        return frozenset(str(a) for a in allowed)

    def visit_intimation_hours(self) -> int | None:
        return _opt_int((self._params(KIND_VISIT_INTIMATION) or {}).get("hours"))

    def recording_retention_months(self) -> int | None:
        return _opt_int((self._params(KIND_RECORDING_RETENTION) or {}).get("months"))

    def to_log(self) -> dict[str, Any]:
        """Provenance for the decision row. Small enough to store per decision."""
        return {
            "version": self.statutory_version,
            "layers": [dict(p) for p in self.provenance],
        }


EMPTY = RuleSet()


def _opt_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Tightening
# ---------------------------------------------------------------------------


def _tighten(
    kind: str, current: Mapping[str, Any], incoming: Mapping[str, Any]
) -> dict[str, Any]:
    """Combine two layers of the same rule so the result is never looser.

    Unknown kinds fall through to "the later layer replaces the earlier one",
    which is the only sensible default for a rule this function has not been
    taught to compare — and it is why adding a kind means adding a branch here
    rather than only a CHECK constraint.
    """
    merged = {**current, **incoming}

    if kind == KIND_CALLING_WINDOW:
        start = _max_opt(_opt_int(current.get("startHour")), _opt_int(incoming.get("startHour")))
        end = _min_opt(_opt_int(current.get("endHour")), _opt_int(incoming.get("endHour")))
        # An empty intersection is a legal outcome, not an error: it says this
        # tenant does not make outbound voice contact on this channel at all.
        if start is not None:
            merged["startHour"] = start
        if end is not None:
            merged["endHour"] = end
        return merged

    if kind in {KIND_DAILY_CAP, KIND_WEEKLY_CAP, KIND_MANDATE_LIMIT}:
        value = _min_opt(_opt_int(current.get("value")), _opt_int(incoming.get("value")))
        if value is not None:
            merged["value"] = value
        return merged

    if kind == KIND_COOLING_OFF:
        value = _max_opt(_opt_int(current.get("minutes")), _opt_int(incoming.get("minutes")))
        if value is not None:
            merged["minutes"] = value
        return merged

    if kind == KIND_VISIT_INTIMATION:
        value = _max_opt(_opt_int(current.get("hours")), _opt_int(incoming.get("hours")))
        if value is not None:
            merged["hours"] = value
        return merged

    if kind == KIND_RECORDING_RETENTION:
        value = _max_opt(_opt_int(current.get("months")), _opt_int(incoming.get("months")))
        if value is not None:
            merged["months"] = value
        return merged

    if kind == KIND_BUCKET_ACTIONS:
        a = current.get("byBucket") if isinstance(current.get("byBucket"), Mapping) else {}
        b = incoming.get("byBucket") if isinstance(incoming.get("byBucket"), Mapping) else {}
        by_bucket: dict[str, list[str]] = {}
        for bucket in {*a, *b}:
            left, right = a.get(bucket), b.get(bucket)
            if not isinstance(left, (list, tuple)):
                by_bucket[bucket] = list(right or [])
            elif not isinstance(right, (list, tuple)):
                by_bucket[bucket] = list(left)
            else:
                # Intersection, order preserved from the outer layer so the
                # result is stable rather than set-ordered.
                allowed = set(right)
                by_bucket[bucket] = [x for x in left if x in allowed]
        merged["byBucket"] = by_bucket
        return merged

    if kind == KIND_MANDATE_RETURN:
        a = current.get("byReason") if isinstance(current.get("byReason"), Mapping) else {}
        b = incoming.get("byReason") if isinstance(incoming.get("byReason"), Mapping) else {}
        by_reason: dict[str, str] = {}
        for reason in {*a, *b}:
            verdicts = [
                str(v).strip().lower()
                for v in (a.get(reason), b.get(reason))
                if v is not None
            ]
            # 'veto' wins. A layer may withdraw permission, never grant it.
            by_reason[reason] = "allow" if all(v == "allow" for v in verdicts) else "veto"
        merged["byReason"] = by_reason
        return merged

    return merged


def _min_opt(a: int | None, b: int | None) -> int | None:
    return min(x for x in (a, b) if x is not None) if (a is not None or b is not None) else None


def _max_opt(a: int | None, b: int | None) -> int | None:
    return max(x for x in (a, b) if x is not None) if (a is not None or b is not None) else None


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def resolve(
    conn: Any,
    *,
    tenant_id: str | None,
    at: datetime | None = None,
    product_id: str | None = None,
) -> RuleSet:
    """The rules in force at ``at``. Never raises; degrades to :data:`EMPTY`.

    A resolver that can throw would take down the contact gate, and a contact
    gate that is down fails closed on every borrower in the book. Returning
    ``EMPTY`` instead means each caller falls back to the constant it used
    before this module existed, which is a known-good state rather than an
    outage.
    """
    instant = _aware(at)
    key = (
        str(tenant_id or ""),
        str(product_id or ""),
        instant.replace(second=0, microsecond=0).isoformat(),
    )
    cached = _cache_get(key)
    if cached is not None:
        return cached

    try:
        resolved = _resolve_uncached(
            conn, tenant_id=tenant_id, at=instant, product_id=product_id
        )
    except Exception:
        logger.exception("policy rule resolution failed for tenant=%s", tenant_id)
        return EMPTY

    _cache_put(key, resolved)
    return resolved


def _resolve_uncached(
    conn: Any, *, tenant_id: str | None, at: datetime, product_id: str | None
) -> RuleSet:
    rows = conn.execute(
        text(
            """
            SELECT s.id, s.scope, s.version, s.label,
                   r.kind, r.channel, r.params
            FROM policy_rule_sets s
            LEFT JOIN policy_rules r ON r.rule_set_id = s.id
            WHERE s.effective_from <= :at
              AND (s.effective_to IS NULL OR s.effective_to > :at)
              AND (
                    (s.scope = 'statutory')
                 OR (s.scope = 'client'  AND s.tenant_id = :tid)
                 OR (s.scope = 'product' AND s.tenant_id = :tid
                     AND s.product_id = :pid)
              )
            -- Latest effective_from wins within a scope. Overlapping windows
            -- are not prevented by a constraint (that would need btree_gist),
            -- so the tie-break is stated here and is deterministic.
            ORDER BY s.effective_from ASC, s.version ASC
            """
        ),
        {"at": at, "tid": tenant_id, "pid": product_id},
    ).mappings().all()

    if not rows:
        return EMPTY

    # Group by set so the fold can walk scopes in order rather than trusting
    # the join's row order to interleave layers correctly.
    by_set: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = by_set.setdefault(
            row["id"],
            {
                "scope": row["scope"],
                "version": int(row["version"]),
                "label": row["label"],
                "rules": [],
            },
        )
        if row["kind"] is not None:
            entry["rules"].append(row)

    ordered = sorted(
        by_set.values(),
        key=lambda e: (SCOPE_ORDER.index(e["scope"]) if e["scope"] in SCOPE_ORDER else 99,
                       e["version"]),
    )

    merged: dict[tuple[str, str | None], dict[str, Any]] = {}
    provenance: list[Mapping[str, Any]] = []
    statutory_version: int | None = None

    for entry in ordered:
        provenance.append(
            {"scope": entry["scope"], "label": entry["label"], "version": entry["version"]}
        )
        if entry["scope"] == SCOPE_STATUTORY:
            statutory_version = entry["version"]
        for row in entry["rules"]:
            params = row["params"] if isinstance(row["params"], Mapping) else {}
            slot = (str(row["kind"]), row["channel"])
            current = merged.get(slot)
            merged[slot] = (
                dict(params) if current is None else _tighten(slot[0], current, params)
            )

    return RuleSet(
        statutory_version=statutory_version,
        provenance=tuple(provenance),
        rules=merged,
    )


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _cache_get(key: tuple[str, str, str]) -> RuleSet | None:
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is None:
            return None
        stamped, resolved = hit
        if time.monotonic() - stamped > CACHE_TTL_SECONDS:
            _CACHE.pop(key, None)
            return None
        return resolved


def _cache_put(key: tuple[str, str, str], resolved: RuleSet) -> None:
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            # Cheapest possible eviction. The keys are minute-stamped, so the
            # working set is small and a full clear costs one query per tenant.
            _CACHE.clear()
        _CACHE[key] = (time.monotonic(), resolved)


def reset_cache() -> None:
    """Test hook, and the thing to call after publishing a rule set."""
    with _CACHE_LOCK:
        _CACHE.clear()
