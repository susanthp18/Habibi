"""One conversation in, a list of buying signals out. The LLM half.

Forced tool call with a closed vocabulary, on the analysis profile, over the
masked transcript only, with the customer's turns numbered so every signal
points at the turn that said it. Everything the model returns is checked
again here, because a prompt is not a control:

* codes outside :data:`CODES` are dropped;
* a signal whose turn is not a customer turn is dropped;
* a sensitive category (health, hardship, job loss, religion, caste,
  politics, and anything the collections side treats as vulnerability) is
  dropped by a deterministic denylist, whatever code the model gave it;
* a signal that quotes a number the transcript does not contain is dropped.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: Bump to re-judge history (the sweep re-queues older ledger rows).
EXTRACTOR_VERSION = 1

CODES: dict[str, str] = {
    "vehicle_purchase": "planning to buy a car, bike or other vehicle",
    "home_purchase": "planning to buy a home or property",
    "home_renovation": "planning home repairs or renovation",
    "new_job_or_raise": "started a new job or got a raise or promotion",
    "business_expansion": "expanding or starting a business",
    "marriage": "an upcoming wedding in the family",
    "child_education": "paying for a child's education",
    "travel": "planning travel",
    "insurance_need": "asked about or needs insurance cover",
    "credit_limit_need": "needs a higher card limit or more credit",
    "high_interest_debt": "has other expensive debt they want to reduce",
    "gold_holding": "mentions holding gold they could borrow against",
    "product_interest": "asked about a specific product",
    "not_interested": "said they do not want offers or new products",
}
HORIZONS = ("now", "this_month", "this_quarter", "later", "unknown")

#: Never a sales signal, whatever the model calls it. Matched on the model's
#: own evidence note and on the customer turn it points at.
_SENSITIVE = re.compile(
    r"\b(hospital|surgery|illness|sick|cancer|medical|medicine|treatment|"
    r"died|death|funeral|bereave|passed away|"
    r"lost (my|his|her|the) job|laid off|unemploy|no income|salary (cut|stopped)|"
    r"hardship|can'?t pay|cannot pay|struggl|debt trap|"
    r"religio|caste|church|temple|mosque|politic|pregnan|divorce)",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

_SYSTEM = (
    "You read a customer-service conversation between a bank and its customer and list any buying "
    "signals the CUSTOMER expressed in their own words: life events or needs a bank product could "
    "serve. Only report what the customer clearly said; never infer from the agent's words. Never "
    "report health, bereavement, job loss, financial hardship, religion, caste or politics, even if "
    "mentioned. If there is nothing, return an empty list. Codes: "
    + "; ".join(f"{k} = {v}" for k, v in CODES.items())
)

_TOOL = {
    "type": "function",
    "function": {
        "name": "report_signals",
        "description": "Report the buying signals the customer expressed.",
        "parameters": {
            "type": "object",
            "properties": {
                "signals": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "enum": sorted(CODES)},
                            "turn": {"type": "integer", "description": "The number of the customer turn that says it."},
                            "horizon": {"type": "string", "enum": list(HORIZONS)},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "product": {"type": "string", "description": "Product named by the customer, if any."},
                            "note": {"type": "string", "description": "Six words or fewer on what they said."},
                        },
                        "required": ["code", "turn", "confidence"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["signals"],
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True)
class Signal:
    code: str
    turn_id: str
    confidence: float
    horizon: str
    product_hint: str | None


def _prompt(turns: list[dict[str, Any]]) -> tuple[str, dict[int, dict[str, Any]]]:
    """The fenced transcript, customer turns numbered, and the number → turn map."""
    from transcript_view import UNTRUSTED_FENCE, redact_line

    numbered: dict[int, dict[str, Any]] = {}
    lines = [UNTRUSTED_FENCE]
    n = 0
    for t in turns:
        text_ = redact_line(t["text"] or "")
        if t["speaker"] == "customer":
            n += 1
            numbered[n] = {**t, "safe": text_}
            lines.append(f"[{n}] customer: {text_}")
        elif t["speaker"] in {"bot", "agent"}:
            lines.append(f"    {t['speaker']}: {text_}")
    return "\n".join(lines), numbered


def extract(turns: list[dict[str, Any]], *, products: list[str]) -> list[Signal]:
    """The checked signals in one conversation. Raises only on an LLM failure."""
    import azure_openai

    prompt, numbered = _prompt(turns)
    if not numbered:
        return []
    result = azure_openai.chat_with_tools(
        [
            {"role": "system", "content": _SYSTEM + ". Products the bank sells: " + ", ".join(products)},
            {"role": "user", "content": prompt},
        ],
        tools=[_TOOL],
        tool_choice={"type": "function", "function": {"name": "report_signals"}},
        temperature=0.0,
        # A reasoning deployment spends part of this before it answers.
        max_completion_tokens=2000,
        profile=azure_openai.PROFILE_ANALYSIS,
        reasoning_effort="low",
        timeout=60,
    )
    calls = result.get("toolCalls") or []
    raw = calls[0]["arguments"] if calls else "{}"
    items = (json.loads(raw) if isinstance(raw, str) else raw).get("signals") or []
    return check(items, numbered, products=products)


def check(items: list[dict[str, Any]], numbered: dict[int, dict[str, Any]], *, products: list[str]) -> list[Signal]:
    """The deterministic half: whatever the model said, only this survives."""
    out: list[Signal] = []
    seen: set[str] = set()
    for item in items:
        code = str(item.get("code") or "")
        turn = numbered.get(int(item.get("turn") or 0)) if str(item.get("turn") or "").isdigit() else None
        if code not in CODES or turn is None or code in seen:
            continue
        said = turn["safe"]
        note = str(item.get("note") or "")
        if _SENSITIVE.search(said) or _SENSITIVE.search(note):
            continue
        if any(n not in said for n in _NUMBER.findall(note)):
            continue
        product = str(item.get("product") or "").strip() or None
        seen.add(code)
        out.append(
            Signal(
                code=code,
                turn_id=str(turn["id"]),
                confidence=max(0.0, min(1.0, float(item.get("confidence") or 0))),
                horizon=str(item.get("horizon") or "unknown") if item.get("horizon") in HORIZONS else "unknown",
                product_hint=product if product in products else None,
            )
        )
    return out


if __name__ == "__main__":
    turns = {1: {"id": "T1", "safe": "I'm planning to buy a car next month"},
             2: {"id": "T2", "safe": "my father is in hospital so I can't pay"}}
    got = check(
        [
            {"code": "vehicle_purchase", "turn": 1, "confidence": 0.9, "horizon": "this_month"},
            {"code": "insurance_need", "turn": 2, "confidence": 0.8},
            {"code": "made_up", "turn": 1, "confidence": 1},
            {"code": "travel", "turn": 9, "confidence": 1},
        ],
        turns,
        products=["auto-loan"],
    )
    assert [s.code for s in got] == ["vehicle_purchase"], got
    print("ok")
