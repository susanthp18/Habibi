"""Injection-safe prompt variable substitution (PS-3).

Replace only whitelist tokens of the form ``{var_name}``. Context values are
inert strings — never fed back through substitution (a customer_name containing
``{overdue_amount}`` must not expand). Do not use ``str.format`` / f-strings /
``Template.safe_substitute`` over untrusted keys.
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

_TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def render_prompt(template: str, context: Mapping[str, Any]) -> str:
    """Whitelist token replacement. Unknown ``{…}`` tokens are left as-is."""
    if not template:
        return ""

    # Snapshot values once as plain strings so nested braces in values stay inert.
    values: dict[str, str] = {}
    for key in KNOWN_VARIABLES:
        if key in context and context[key] is not None:
            values[key] = str(context[key])

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in values:
            return values[name]
        return match.group(0)

    return _TOKEN_RE.sub(_replace, template)
