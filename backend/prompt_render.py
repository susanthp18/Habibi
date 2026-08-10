"""Injection-safe prompt variable substitution (PS-3).

Replace only whitelist tokens of the form ``{var_name}``. Context values are
inert strings — never fed back through substitution (a customer- or CRM-controlled
value containing ``{overdue_amount}`` must not expand). Do not use ``str.format``
/ f-strings / ``Template.safe_substitute`` over untrusted keys.

System-role policy templates may only interpolate operator-controlled static
tokens (``SYSTEM_SAFE_VARIABLES``). Customer/CRM fields belong in a delimited
developer/user context card — never the system policy string.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

KNOWN_VARIABLES: frozenset[str] = frozenset(
    {
        "customer_name",
        "account_no",
        "overdue_amount",
        "due_date",
        "last_payment",
        "agent_name",
        "bank_name",
        "language",
        "time_of_day",
    }
)

# Allowed inside system-role policy only (never customer-controlled CRM fields).
SYSTEM_SAFE_VARIABLES: frozenset[str] = frozenset(
    {
        "agent_name",
        "bank_name",
        "language",
        "time_of_day",
    }
)

TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_TOKEN_RE = TOKEN_RE  # backwards-compatible alias


def find_variables(template: str) -> list[str]:
    """Variable names referenced by a template, in order of first appearance."""
    seen: list[str] = []
    for match in TOKEN_RE.finditer(template or ""):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return seen


# Sentinels that delimit the untrusted CRM card. A customer-controlled value
# containing either would let the value close the block early and have the rest
# read as trusted context. Neutralised by inserting a zero-width space, which
# keeps the text human-readable while breaking the literal sentinel.
# Escaped, not a literal: an invisible character in source is silently dropped
# by an editor or a whitespace-stripping formatter, which would disable the
# neutralisation without any visible diff.
_ZWSP = "\u200b"  # zero-width space


def _render(template: str, context: Mapping[str, Any], allowed: frozenset[str]) -> str:
    if not template:
        return ""
    values: dict[str, str] = {}
    for key in allowed:
        if key in context and context[key] is not None:
            values[key] = str(context[key])

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in values:
            return values[key]
        return match.group(0)

    return _TOKEN_RE.sub(repl, template)


def render_prompt(template: str, context: Mapping[str, Any]) -> str:
    """Whitelist token replacement for non-system channels (developer/user cards)."""
    return _render(template, context, KNOWN_VARIABLES)


def render_system_prompt(template: str, context: Mapping[str, Any]) -> str:
    """System-role safe substitution — static operator tokens only."""
    return _render(template, context, SYSTEM_SAFE_VARIABLES)


def _inert_value(value: Any) -> str:
    """Render a CRM value so it cannot escape the untrusted-context block.

    Collapses all whitespace (newlines would otherwise let a value forge extra
    ``key: value`` lines or a closing delimiter on its own line) and breaks the
    ``<<<`` / ``>>>`` sentinels with a zero-width space.

    The ZWSP goes after *every* angle bracket rather than after a matched
    ``<<<``: replacing the triple only is reconstructible, because
    ``str.replace`` scans non-overlapping left to right, so ``"<<<<"`` yields
    ``"<​<<" + "<"`` — a fresh ``<<<`` at the seam. Splitting every bracket
    is boundary-independent and holds for arbitrarily long runs.
    """
    flattened = " ".join(str(value).split())
    return flattened.replace("<", f"<{_ZWSP}").replace(">", f">{_ZWSP}")


def format_untrusted_crm_card(context: Mapping[str, Any]) -> str:
    """Delimited CRM snapshot for a developer-role message (not system policy)."""
    lines = ["<<<UNTRUSTED_CRM_CONTEXT>>>"]
    for key in sorted(KNOWN_VARIABLES - SYSTEM_SAFE_VARIABLES):
        if key in context and context[key] is not None:
            lines.append(f"{key}: {_inert_value(context[key])}")
    lines.append("<<<END_UNTRUSTED_CRM_CONTEXT>>>")
    return "\n".join(lines)
