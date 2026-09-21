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

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import text

from agent_core.clock import as_utc
from agent_core.clock import utc_now

logger = logging.getLogger(__name__)

#: How many times one promise may be renegotiated before the desk has to
#: decide something else -- a plan, a hardship review, a hold. Three is the
#: point past which a moving date is a broken promise wearing a new one.
PTP_MAX_REVISIONS = 3

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
KIND_SUPPRESSION_STATE = "suppression_state"
KIND_RATIO_CEILING = "ratio_ceiling"
KIND_ASSIGNMENT_CHECK = "assignment_check"
KIND_CHANNEL_SCRUB = "channel_scrub"
KIND_NOTICE = "non_discretionary_notice"

KNOWN_KINDS: frozenset[str] = frozenset(
    {
        KIND_CALLING_WINDOW,
        KIND_DAILY_CAP,
        KIND_WEEKLY_CAP,
        KIND_COOLING_OFF,
        KIND_BUCKET_ACTIONS,
        KIND_MANDATE_LIMIT,
        KIND_MANDATE_RETURN,
        KIND_FIELD_PREREQS,
        KIND_RECORDING_RETENTION,
        KIND_VISIT_INTIMATION,
        KIND_SUPPRESSION_STATE,
        KIND_RATIO_CEILING,
        KIND_ASSIGNMENT_CHECK,
        KIND_CHANNEL_SCRUB,
        KIND_NOTICE,
    }
)

#: Closed registry. A kind without a params schema, a tighten branch, a
#: production consumer, and a fires-on-fixture test is unpublished.
KIND_SPECS: dict[str, dict[str, Any]] = {
    KIND_CALLING_WINDOW: {
        "params_schema": "calling_window.v1",
        "required": ("startHour", "endHour"),
        "consumer": "contact_policy._veto",
    },
    KIND_DAILY_CAP: {
        "params_schema": "daily_cap.v1",
        "required": ("value",),
        "consumer": "contact_policy.daily_cap",
    },
    KIND_WEEKLY_CAP: {
        "params_schema": "weekly_cap.v1",
        "required": ("value",),
        "consumer": "contact_policy.weekly_cap_default",
    },
    KIND_COOLING_OFF: {
        "params_schema": "cooling_off.v1",
        "required": ("minutes",),
        "consumer": "contact_policy.cooling_off",
    },
    KIND_BUCKET_ACTIONS: {
        "params_schema": "bucket_actions.v1",
        "required": ("byBucket",),
        "consumer": "agent_core.treatment.policy.veto",
    },
    KIND_MANDATE_LIMIT: {
        "params_schema": "mandate_presentation_limit.v1",
        "required": ("value",),
        "consumer": "agent_core.treatment.policy.veto",
    },
    KIND_MANDATE_RETURN: {
        "params_schema": "mandate_return_action.v1",
        "required": ("byReason",),
        "consumer": "agent_core.treatment.policy.veto",
    },
    KIND_FIELD_PREREQS: {
        "params_schema": "field_prerequisites.v1",
        "required": ("required",),
        "consumer": "agent_core.treatment.policy._field_veto",
    },
    KIND_RECORDING_RETENTION: {
        "params_schema": "recording_retention.v1",
        "required": ("months",),
        "consumer": "complaint_pack.compose",
    },
    KIND_VISIT_INTIMATION: {
        "params_schema": "visit_intimation.v1",
        "required": ("hours",),
        "consumer": "agent_core.treatment.policy._field_veto",
    },
    KIND_SUPPRESSION_STATE: {
        "params_schema": "suppression_state.v1",
        "required": ("kinds",),
        "consumer": "contact_policy._veto",
    },
    KIND_RATIO_CEILING: {
        "params_schema": "ratio_ceiling.v1",
        "required": ("max",),
        "consumer": "agent_core.treatment.policy.veto",
    },
    KIND_ASSIGNMENT_CHECK: {
        "params_schema": "assignment_check.v1",
        "required": ("requiredCertifications",),
        "consumer": "contact_policy.admit",
    },
    KIND_CHANNEL_SCRUB: {
        "params_schema": "channel_scrub.v1",
        "required": ("lists",),
        "consumer": "contact_policy._veto",
    },
    KIND_NOTICE: {
        "params_schema": "non_discretionary_notice.v1",
        "required": ("obeysWindow",),
        "consumer": "contact_policy._veto",
    },
}

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
class ConsultedRule:
    """One catalogue row the resolver loaded, whether or not it later fired."""

    rule_id: str
    rule_version: int
    scope: str
    kind: str
    channel: str | None
    citation: str
    params: Mapping[str, Any]


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
    consulted: tuple[ConsultedRule, ...] = ()

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

    def field_prerequisites(self) -> tuple[str, ...]:
        params = self._params(KIND_FIELD_PREREQS)
        if not params:
            return ()
        required = params.get("required")
        if not isinstance(required, (list, tuple)):
            return ()
        return tuple(str(item) for item in required)

    def suppression_kinds(self) -> frozenset[str]:
        params = self._params(KIND_SUPPRESSION_STATE)
        if not params:
            return frozenset()
        kinds = params.get("kinds")
        if not isinstance(kinds, (list, tuple)):
            return frozenset()
        return frozenset(str(k) for k in kinds)

    def ratio_ceiling(self) -> float | None:
        params = self._params(KIND_RATIO_CEILING)
        if not params:
            return None
        raw = params.get("max")
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def required_certifications(self) -> tuple[str, ...]:
        params = self._params(KIND_ASSIGNMENT_CHECK)
        if not params:
            return ()
        required = params.get("requiredCertifications")
        if not isinstance(required, (list, tuple)):
            return ()
        return tuple(str(item) for item in required)

    def channel_scrub_lists(self) -> tuple[str, ...]:
        params = self._params(KIND_CHANNEL_SCRUB)
        if not params:
            return ()
        lists = params.get("lists")
        if not isinstance(lists, (list, tuple)):
            return ()
        return tuple(str(item) for item in lists)

    def notice_obeys_window(self) -> bool:
        params = self._params(KIND_NOTICE)
        if not params:
            return True
        return bool(params.get("obeysWindow", True))

    def to_log(self) -> dict[str, Any]:
        """Provenance for the decision row. Small enough to store per decision."""
        return {
            "version": self.statutory_version,
            "layers": [dict(p) for p in self.provenance],
        }


EMPTY = RuleSet()

#: The calling window when no rule set is published: 08:00-19:00 local, the
#: conservative platform bound. It stays because "unregulated by the rules
#: table" must not mean "unrestricted" -- a fresh install obeys it. Every
#: reader of the statutory window goes through :func:`calling_window`; this
#: pair is what that function answers when the tenant has published nothing,
#: and nothing else in the tree restates the numbers.
STATUTORY_VOICE_WINDOW: tuple[int, int] = (8, 19)


def calling_window(
    conn: Any,
    channel: str = "voice",
    *,
    tenant_id: str | None,
    at: datetime | None = None,
    product_id: str | None = None,
) -> tuple[int, int]:
    """The published ``[start, end)`` local hours for ``channel``, else the bound.

    Nine sites decided "is this hour inside the window" and two consulted the
    published rule set; the other seven read the constant, so a tenant that
    published 09-18 narrowed the gate and nothing else -- the scheduler still
    planned 08:30 slots the gate then refused, and the detector flagged
    18:30 calls the gate had admitted. Never raises (``resolve`` degrades to
    ``EMPTY``), so a caller may hold it in a hot path.
    """
    rules = resolve(conn, tenant_id=tenant_id, at=at, product_id=product_id)
    return rules.calling_window(channel) or STATUTORY_VOICE_WINDOW


def _mapping(value: Any) -> Mapping[str, Any]:
    """The value when it is a mapping, else an empty one (typed, for the merge)."""
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> tuple[Any, ...]:
    """The value when it is a list/tuple, else empty (typed, for the merge)."""
    return tuple(value) if isinstance(value, (list, tuple)) else ()


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


def validate_kind(kind: str) -> str:
    name = str(kind or "").strip()
    if name not in KNOWN_KINDS:
        raise ValueError(f"unknown_policy_kind:{name}")
    return name


def validate_params(kind: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
    """Refuse publication of an unknown kind or a payload missing its schema."""
    name = validate_kind(kind)
    payload = dict(params or {})
    spec = KIND_SPECS[name]
    missing = [key for key in spec["required"] if key not in payload]
    if missing:
        raise ValueError(f"invalid_params:{name}:{','.join(missing)}")
    return payload


def _tighten(
    kind: str, current: Mapping[str, Any], incoming: Mapping[str, Any]
) -> dict[str, Any]:
    """Combine two layers of the same rule so the result is never looser.

    Unknown kinds are a publication error, not a merge. A later layer that
    could silently replace an earlier one would be a later layer that could
    delete the regulation.
    """
    if kind not in KNOWN_KINDS:
        raise ValueError(f"unknown_policy_kind:{kind}")
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
        a = _mapping(current.get("byBucket"))
        b = _mapping(incoming.get("byBucket"))
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
        a = _mapping(current.get("byReason"))
        b = _mapping(incoming.get("byReason"))
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

    if kind == KIND_FIELD_PREREQS:
        left = _sequence(current.get("required"))
        right = _sequence(incoming.get("required"))
        seen: list[str] = []
        for item in [*left, *right]:
            name = str(item)
            if name not in seen:
                seen.append(name)
        merged["required"] = seen
        return merged

    if kind == KIND_SUPPRESSION_STATE:
        left = _sequence(current.get("kinds"))
        right = _sequence(incoming.get("kinds"))
        merged["kinds"] = sorted({str(x) for x in (*left, *right)})
        return merged

    if kind == KIND_RATIO_CEILING:
        a = current.get("max")
        b = incoming.get("max")
        try:
            nums = [float(x) for x in (a, b) if x is not None]
        except (TypeError, ValueError):
            nums = []
        if nums:
            merged["max"] = min(nums)
        return merged

    if kind == KIND_ASSIGNMENT_CHECK:
        left = _sequence(current.get("requiredCertifications"))
        right = _sequence(incoming.get("requiredCertifications"))
        if left and right:
            allowed = set(str(x) for x in right)
            merged["requiredCertifications"] = [x for x in left if str(x) in allowed]
        else:
            merged["requiredCertifications"] = [str(x) for x in (right or left)]
        return merged

    if kind == KIND_CHANNEL_SCRUB:
        left = _sequence(current.get("lists"))
        right = _sequence(incoming.get("lists"))
        seen: list[str] = []
        for item in [*left, *right]:
            name = str(item)
            if name not in seen:
                seen.append(name)
        merged["lists"] = seen
        return merged

    if kind == KIND_NOTICE:
        merged["obeysWindow"] = bool(current.get("obeysWindow", True)) and bool(
            incoming.get("obeysWindow", True)
        )
        return merged

    raise ValueError(f"unknown_policy_kind:{kind}")


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
    instant = as_utc(at) or utc_now()
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
        # stack_info: the failure is usually the caller's (a closed connection
        # handed in at call teardown), and the traceback alone stops at this frame.
        logger.exception("policy rule resolution failed for tenant=%s", tenant_id, stack_info=True)
        return EMPTY

    _cache_put(key, resolved)
    return resolved


def _resolve_uncached(
    conn: Any, *, tenant_id: str | None, at: datetime, product_id: str | None
) -> RuleSet:
    from agent_core.treatment import schema_ready

    w4 = schema_ready.w4_ready(conn)
    extra = (
        ", r.rule_id, r.rule_version, r.citation"
        if w4
        else ", NULL AS rule_id, NULL AS rule_version, NULL AS citation"
    )
    published = (
        "AND COALESCE(s.publication_state, 'published') = 'published'" if w4 else ""
    )
    rows = conn.execute(
        text(
            f"""
            SELECT s.id, s.scope, s.version, s.label,
                   r.kind, r.channel, r.params
                   {extra}
            FROM policy_rule_sets s
            LEFT JOIN policy_rules r ON r.rule_set_id = s.id
            WHERE s.effective_from <= :at
              AND (s.effective_to IS NULL OR s.effective_to > :at)
              {published}
              AND (
                    (s.scope = 'statutory')
                 OR (s.scope = 'client'  AND s.tenant_id = :tid)
                 OR (s.scope = 'product' AND s.tenant_id = :tid
                     AND s.product_id = :pid)
              )
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
    consulted: list[ConsultedRule] = []

    for entry in ordered:
        provenance.append(
            {"scope": entry["scope"], "label": entry["label"], "version": entry["version"]}
        )
        if entry["scope"] == SCOPE_STATUTORY:
            statutory_version = entry["version"]
        for row in entry["rules"]:
            kind = str(row["kind"])
            if kind not in KNOWN_KINDS:
                logger.error("skipping unpublished policy kind %s", kind)
                continue
            params = row["params"] if isinstance(row["params"], Mapping) else {}
            slot = (kind, row["channel"])
            current = merged.get(slot)
            merged[slot] = (
                dict(params) if current is None else _tighten(slot[0], current, params)
            )
            consulted.append(
                ConsultedRule(
                    rule_id=str(row["rule_id"] or f"{kind}:{row['channel'] or 'all'}"),
                    rule_version=int(row["rule_version"] or entry["version"]),
                    scope=str(entry["scope"]),
                    kind=kind,
                    channel=row["channel"],
                    citation=str(row["citation"] or entry["label"] or ""),
                    params=dict(params),
                )
            )

    return RuleSet(
        statutory_version=statutory_version,
        provenance=tuple(provenance),
        rules=merged,
        consulted=tuple(consulted),
    )


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


# ---------------------------------------------------------------------------
# Maker-checker publication
# ---------------------------------------------------------------------------


def production_publication_enabled() -> bool:
    from env_utils import env_bool

    return env_bool("POLICY_PRODUCTION_PUBLICATION", False)


def _set_id() -> str:
    return f"PRS-{uuid.uuid4().hex[:10].upper()}"


def _rule_row_id(set_id: str, kind: str, channel: str | None) -> str:
    return f"{set_id}-{kind}-{channel or 'all'}"


def _scope_key(scope: str, tenant_id: str | None, product_id: str | None) -> str:
    if scope == SCOPE_STATUTORY:
        return "statutory"
    if scope == SCOPE_PRODUCT:
        return f"product:{tenant_id or ''}:{product_id or ''}"
    return f"client:{tenant_id or ''}"


def _diff_changed_rules(
    conn: Any,
    *,
    scope: str,
    tenant_id: str | None,
    product_id: str | None,
    rules: Sequence[Mapping[str, Any]],
) -> list[str]:
    predecessor = conn.execute(
        text(
            """
            SELECT id FROM policy_rule_sets
            WHERE scope = :scope
              AND COALESCE(tenant_id, '') = COALESCE(:tid, '')
              AND COALESCE(product_id, '') = COALESCE(:pid, '')
              AND publication_state = 'published'
            ORDER BY version DESC
            LIMIT 1
            """
        ),
        {"scope": scope, "tid": tenant_id, "pid": product_id},
    ).mappings().first()
    incoming = {
        f"{r['kind']}:{r.get('channel') or 'all'}": json.dumps(r.get("params") or {}, sort_keys=True)
        for r in rules
    }
    if not predecessor:
        return sorted({str(r["kind"]) for r in rules})
    prior_rows = conn.execute(
        text(
            """
            SELECT kind, channel, params FROM policy_rules
            WHERE rule_set_id = :id
            """
        ),
        {"id": predecessor["id"]},
    ).mappings().all()
    prior = {
        f"{r['kind']}:{r['channel'] or 'all'}": json.dumps(r["params"] or {}, sort_keys=True)
        for r in prior_rows
    }
    changed = [key.split(":", 1)[0] for key, payload in incoming.items() if prior.get(key) != payload]
    changed.extend(key.split(":", 1)[0] for key in prior if key not in incoming)
    return sorted(set(changed))


def create_draft(
    conn: Any,
    *,
    scope: str,
    version: int,
    label: str,
    effective_from: datetime,
    effective_to: datetime | None,
    rules: Sequence[Mapping[str, Any]],
    tenant_id: str | None = None,
    product_id: str | None = None,
    notes: str | None = None,
    actor_user_id: str | None = None,
    set_id: str | None = None,
) -> str:
    """Insert a draft rule set. Does not take effect."""
    if scope not in SCOPE_ORDER:
        raise ValueError(f"invalid_scope:{scope}")
    if scope == SCOPE_STATUTORY and tenant_id:
        raise ValueError("statutory_has_no_tenant")
    if scope != SCOPE_STATUTORY and not tenant_id:
        raise ValueError("tenant_required")
    if scope == SCOPE_PRODUCT and not product_id:
        raise ValueError("product_required")
    validated: list[dict[str, Any]] = []
    for raw in rules:
        kind = validate_kind(str(raw.get("kind") or ""))
        params = validate_params(kind, _mapping(raw.get("params")))
        citation = str(raw.get("citation") or label or "").strip()
        if not citation:
            raise ValueError("citation_required")
        validated.append(
            {
                "kind": kind,
                "channel": raw.get("channel"),
                "params": params,
                "citation": citation,
                "rule_id": str(raw.get("rule_id") or f"{kind}:{raw.get('channel') or 'all'}"),
                "rule_version": int(raw.get("rule_version") or version),
            }
        )
    new_id = set_id or _set_id()
    conn.execute(
        text(
            """
            INSERT INTO policy_rule_sets (
              id, tenant_id, scope, product_id, version, label,
              effective_from, effective_to, notes, publication_state,
              published_by_user_id, changed_rules
            ) VALUES (
              :id, :tenant_id, :scope, :product_id, :version, :label,
              :effective_from, :effective_to, :notes, 'draft',
              :actor, ARRAY[]::TEXT[]
            )
            """
        ),
        {
            "id": new_id,
            "tenant_id": tenant_id,
            "scope": scope,
            "product_id": product_id,
            "version": version,
            "label": label,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "notes": notes,
            "actor": actor_user_id,
        },
    )
    scope_key = _scope_key(scope, tenant_id, product_id)
    for item in validated:
        conn.execute(
            text(
                """
                INSERT INTO policy_rules (
                  id, rule_set_id, kind, channel, params,
                  rule_id, rule_version, citation, params_schema,
                  effective, scope_key
                ) VALUES (
                  :id, :set_id, :kind, :channel, CAST(:params AS jsonb),
                  :rule_id, :rule_version, :citation, :params_schema,
                  tstzrange(:effective_from, :effective_to, '[)'),
                  :scope_key
                )
                """
            ),
            {
                "id": _rule_row_id(new_id, item["kind"], item["channel"]),
                "set_id": new_id,
                "kind": item["kind"],
                "channel": item["channel"],
                "params": json.dumps(item["params"]),
                "rule_id": item["rule_id"],
                "rule_version": item["rule_version"],
                "citation": item["citation"],
                "params_schema": KIND_SPECS[item["kind"]]["params_schema"],
                "effective_from": effective_from,
                "effective_to": effective_to,
                "scope_key": scope_key,
            },
        )
    return new_id


def submit_for_approval(conn: Any, set_id: str, *, actor_user_id: str | None) -> None:
    row = conn.execute(
        text("SELECT publication_state FROM policy_rule_sets WHERE id = :id"),
        {"id": set_id},
    ).mappings().first()
    if row is None:
        raise KeyError("policy_rule_set_not_found")
    if row["publication_state"] not in {"draft", "rejected"}:
        raise ValueError("not_a_draft")
    conn.execute(
        text(
            """
            UPDATE policy_rule_sets
            SET publication_state = 'pending_approval',
                published_by_user_id = :actor,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": set_id, "actor": actor_user_id},
    )


def approve_publication(conn: Any, set_id: str, *, actor_user_id: str | None) -> None:
    """Promote a pending set. Refuses production until the env flag is on."""
    if not production_publication_enabled():
        raise PermissionError("production_publication_disabled")
    row = conn.execute(
        text(
            """
            SELECT id, scope, tenant_id, product_id, published_by_user_id,
                   publication_state
            FROM policy_rule_sets WHERE id = :id
            """
        ),
        {"id": set_id},
    ).mappings().first()
    if row is None:
        raise KeyError("policy_rule_set_not_found")
    if row["publication_state"] != "pending_approval":
        raise ValueError("not_pending_approval")
    maker = row["published_by_user_id"]
    if not actor_user_id or not maker or actor_user_id == maker:
        raise ValueError("maker_checker_required")
    rules = conn.execute(
        text("SELECT kind, channel, params FROM policy_rules WHERE rule_set_id = :id"),
        {"id": set_id},
    ).mappings().all()
    changed = _diff_changed_rules(
        conn,
        scope=row["scope"],
        tenant_id=row["tenant_id"],
        product_id=row["product_id"],
        rules=list(rules),
    )
    declared = conn.execute(
        text("SELECT changed_rules FROM policy_rule_sets WHERE id = :id"),
        {"id": set_id},
    ).scalar()
    declared_list = list(declared or [])
    if declared_list and sorted(declared_list) != changed:
        raise ValueError("changed_rules_mismatch")
    conn.execute(
        text(
            """
            UPDATE policy_rule_sets
            SET publication_state = 'published',
                approved_by_user_id = :actor,
                published_at = now(),
                changed_rules = :changed,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": set_id, "actor": actor_user_id, "changed": changed},
    )
    reset_cache()


def reject_publication(conn: Any, set_id: str, *, actor_user_id: str | None) -> None:
    conn.execute(
        text(
            """
            UPDATE policy_rule_sets
            SET publication_state = 'rejected',
                approved_by_user_id = :actor,
                updated_at = now()
            WHERE id = :id AND publication_state = 'pending_approval'
            """
        ),
        {"id": set_id, "actor": actor_user_id},
    )


def list_rule_sets(conn: Any, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
    from agent_core.treatment import schema_ready

    extra = (
        ", publication_state, published_by_user_id, approved_by_user_id, changed_rules"
        if schema_ready.w4_ready(conn)
        else ""
    )
    rows = conn.execute(
        text(
            f"""
            SELECT id, scope, tenant_id, product_id, version, label,
                   effective_from, effective_to
                   {extra}
            FROM policy_rule_sets
            WHERE tenant_id IS NULL OR tenant_id = :tid
            ORDER BY scope, version DESC, id
            """
        ),
        {"tid": tenant_id},
    ).mappings().all()
    return [dict(r) for r in rows]
