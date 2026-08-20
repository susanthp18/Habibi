"""User-triggered MCP prompts. Not model-invoked sampling (deprecated)."""

from __future__ import annotations

from typing import Any

PROMPTS = [
    {
        "name": "prep_handoff",
        "description": "Prep a warm-transfer brief for a human agent.",
        "arguments": [{"name": "customer_id", "required": True}],
    },
    {
        "name": "draft_ptp_sms",
        "description": "Draft a Promise-to-Pay confirmation SMS from CRM facts. Does not send.",
        "arguments": [{"name": "customer_id", "required": True}, {"name": "amount", "required": False}],
    },
]


def list_prompts() -> list[dict[str, Any]]:
    return list(PROMPTS)


def get_prompt(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = dict(arguments or {})
    cid = str(args.get("customer_id") or "").strip()
    if name == "prep_handoff":
        return {
            "description": "Handoff brief",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Prepare a warm-transfer brief for customer {cid or '(missing)'}. "
                        "Use get_customer_context. Do not invent outstanding or DPD."
                    ),
                }
            ],
        }
    if name == "draft_ptp_sms":
        amount = args.get("amount") or "{amount}"
        return {
            "description": "PTP SMS draft",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Draft one SMS confirming a promise of {amount} for customer {cid or '(missing)'}. "
                        "Do not send. Do not invent a pay-link URL."
                    ),
                }
            ],
        }
    raise KeyError("prompt_not_found")
