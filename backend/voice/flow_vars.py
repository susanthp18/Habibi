"""Variables and edge-condition evaluation for authored flows.

Deliberately free of Pipecat and of any database: this is the part of the flow
runtime that is pure logic, so it can be tested without a pipeline. The Pipecat
binding lives in :mod:`voice.flows_dynamic`.

Values are stored as strings because they arrive as strings (from the caller's
speech, via the model's extraction tool) and are compared against authored
strings. Numeric operators re-parse both sides and fail closed on anything that
is not a number — a comparison that cannot be evaluated must not be treated as
true, since the edge it guards would then fire on garbage.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Mapping

logger = logging.getLogger(__name__)

#: ``{{ customer_name }}`` — whitespace tolerated, key shape matches flow_graph.
_TEMPLATE_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")

_NUMERIC_OPERATORS = frozenset(
    {"greater_than", "greater_or_equal", "less_than", "less_or_equal"}
)


class FlowVariables:
    """The variable bag for one call."""

    def __init__(self, initial: Mapping[str, Any] | None = None) -> None:
        self._values: dict[str, str] = {}
        for key, value in (initial or {}).items():
            self.set(key, value)

    def set(self, key: str, value: Any) -> None:
        if not key:
            return
        self._values[str(key)] = "" if value is None else str(value)

    def get(self, key: str) -> str | None:
        return self._values.get(key)

    def update(self, values: Mapping[str, Any]) -> None:
        for key, value in values.items():
            self.set(key, value)

    def snapshot(self) -> dict[str, str]:
        """Author-set variables only — system values are recomputed per call."""
        return dict(self._values)

    def _resolved(self) -> dict[str, str]:
        now = datetime.now(timezone.utc)
        # System variables are computed at read time, not stored, so a long call
        # does not keep substituting the timestamp it started at.
        return {
            "date": now.strftime("%d %B %Y"),
            "time": now.strftime("%H:%M UTC"),
            **self._values,
        }

    def render(self, text: str) -> str:
        """Substitute ``{{ key }}``. Unknown keys are left as written.

        Leaving the literal placeholder in place is deliberate: silently
        emptying it produces a fluent, confident sentence with a hole in it,
        which is far harder to notice in a transcript than ``{{amount}}``.
        """
        if not text or "{{" not in text:
            return text or ""
        values = self._resolved()

        def _sub(match: re.Match[str]) -> str:
            key = match.group(1)
            return values.get(key, match.group(0))

        return _TEMPLATE_RE.sub(_sub, text)

    def referenced_in(self, text: str) -> list[str]:
        return sorted({m.group(1) for m in _TEMPLATE_RE.finditer(text or "")})


def evaluate_clause(clause: Any, variables: FlowVariables) -> bool:
    """One condition clause against the variable bag."""
    name = getattr(clause, "variable", "") or ""
    operator = getattr(clause, "operator", "equals") or "equals"
    expected = getattr(clause, "value", None)
    actual = variables.get(name)

    if operator == "exists":
        return actual is not None and actual != ""
    if operator == "not_exists":
        return actual is None or actual == ""
    if actual is None:
        # Every remaining operator compares a value that is not there.
        return False

    if operator == "equals":
        return actual == (expected or "")
    if operator == "not_equals":
        return actual != (expected or "")
    if operator == "contains":
        return (expected or "") in actual
    if operator == "not_contains":
        return (expected or "") not in actual

    if operator in _NUMERIC_OPERATORS:
        try:
            left = float(actual)
            right = float(expected if expected is not None else "")
        except (TypeError, ValueError):
            # Fail closed: an uncomparable pair must not open the edge.
            return False
        if operator == "greater_than":
            return left > right
        if operator == "greater_or_equal":
            return left >= right
        if operator == "less_than":
            return left < right
        return left <= right

    logger.warning("unknown flow condition operator: %s", operator)
    return False


def evaluate_condition(condition: Any, variables: FlowVariables) -> bool:
    """Whether an edge's condition is satisfied.

    ``prompt`` conditions are never evaluated here — the model decides those by
    calling the transition tool — so they always return False.
    """
    kind = getattr(condition, "type", "prompt")
    if kind == "always":
        return True
    if kind != "expression":
        return False

    clauses = list(getattr(condition, "clauses", None) or [])
    if not clauses:
        return False
    results = (evaluate_clause(c, variables) for c in clauses)
    return all(results) if getattr(condition, "match", "all") == "all" else any(results)
