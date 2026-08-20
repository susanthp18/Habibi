"""Drop extra JSON fields so a connector cannot smuggle tool names."""

from __future__ import annotations

from typing import Any

ALLOWED_RESULT_KEYS = frozenset(
    {
        "ok",
        "status",
        "amount",
        "paidAt",
        "providerRef",
        "outstanding",
        "currency",
        "accountId",
        "error",
        "say",
    }
)


def strip_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"ok": False, "error": "connector_result_not_object"}
    out = {k: v for k, v in payload.items() if k in ALLOWED_RESULT_KEYS}
    # Extra keys that look like tool calls are dropped, never promoted.
    return out
