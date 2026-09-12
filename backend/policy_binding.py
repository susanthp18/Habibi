"""Canonical policy bindings: every consulted rule, fired or not.

A rule that did not fire is what answers "was the bereavement hold checked?".
The array is hashed as canonical sorted JSON so two evaluations that saw the
same catalogue produce the same digest.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

import policy_rules
from agent_core.clock import as_utc

VERDICT_FIRED = "fired"
VERDICT_NOT_FIRED = "not_fired"
VERDICT_CONSULTED = "consulted"


def entry(
    *,
    rule_id: str,
    rule_version: int,
    scope: str,
    verdict: str,
    citation: str,
    evaluated_at: datetime,
    kind: str | None = None,
) -> dict[str, Any]:
    row = {
        "rule_id": str(rule_id),
        "rule_version": int(rule_version),
        "scope": str(scope),
        "verdict": str(verdict),
        "citation": str(citation or ""),
        "evaluated_at": (as_utc(evaluated_at) or datetime.now(timezone.utc)).isoformat(),
    }
    if kind:
        row["kind"] = str(kind)
    return row


def from_ruleset(
    rules: policy_rules.RuleSet | None,
    *,
    fired_rule_ids: Iterable[str] | None = None,
    evaluated_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """One binding row per consulted catalogue rule."""
    instant = as_utc(evaluated_at) or datetime.now(timezone.utc)
    fired = {str(x) for x in (fired_rule_ids or ())}
    if rules is None or not getattr(rules, "consulted", ()):
        return []
    out: list[dict[str, Any]] = []
    for item in rules.consulted:
        verdict = VERDICT_FIRED if item.rule_id in fired else VERDICT_NOT_FIRED
        out.append(
            entry(
                rule_id=item.rule_id,
                rule_version=item.rule_version,
                scope=item.scope,
                verdict=verdict,
                citation=item.citation,
                evaluated_at=instant,
                kind=item.kind,
            )
        )
    return canonical_sort(out)


def canonical_sort(bindings: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(item) for item in bindings]
    rows.sort(key=lambda r: (r.get("scope") or "", r.get("rule_id") or "", r.get("rule_version") or 0))
    return rows


def digest(bindings: Sequence[Mapping[str, Any]]) -> str:
    payload = json.dumps(canonical_sort(bindings), separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def pair(
    rules: policy_rules.RuleSet | None,
    *,
    fired_rule_ids: Iterable[str] | None = None,
    evaluated_at: datetime | None = None,
) -> tuple[list[dict[str, Any]], str]:
    bindings = from_ruleset(
        rules, fired_rule_ids=fired_rule_ids, evaluated_at=evaluated_at
    )
    return bindings, digest(bindings)
