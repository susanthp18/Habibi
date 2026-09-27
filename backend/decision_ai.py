"""The LLM's two jobs in the decision engine: explain, and propose. Never choose.

``explain`` turns a stored decision trace into a short plain-language answer
to "why did the engine do this?". It sees only the trace, and a sentence that
contains a number the trace does not is thrown away in favour of the
deterministic ``narrate`` rationale, which stays the audit artefact either way.

``advise`` is the weekly strategy loop. It reads what the engine has learned
and what is blocking it, and may propose up to three setting changes through
``strategy.propose``: bounded, validated, with a reason, and applied only when
a person approves. The fast loop (``treatment.beliefs``) already updates the
response rates by itself; the advisor is for what arithmetic cannot decide,
such as costs, the value floor, exploration and the comparison group's size.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

_EXPLAIN_SYSTEM = (
    "You explain one decision made by a debt-collections decision engine to a "
    "collections supervisor. Use only the JSON you are given. In at most four "
    "short sentences: what it decided, the main reason, what it ruled out and why, "
    "and what happened afterwards if anything. Plain words, no jargon, no "
    "statistics terms. Never invent a number, a name or an event; if the JSON does "
    "not say, do not say it."
)


def _grounded(text: str, source: str) -> bool:
    """Every number in the answer appears in what the model was given."""
    have = {n.replace(",", "") for n in _NUMBER.findall(source)}
    return all(n.replace(",", "") in have for n in _NUMBER.findall(text))


def _compact(trace: dict[str, Any]) -> dict[str, Any]:
    """What the model needs, and nothing that identifies the borrower."""
    return {
        "because": trace["whyNow"]["trigger"],
        "facts": {f["label"]: f["value"] for f in trace["whyNow"]["facts"]},
        "decision": {k: trace["choice"].get(k) for k in ("label", "held", "holdReasonText", "howText", "beat", "scheduledAt")},
        "options": [
            {k: o.get(k) for k in ("label", "status", "reason", "expectedValue", "explanation")}
            for o in trace["options"]
            if o["status"] != "not_considered"
        ],
        "mode": trace["mode"],
        "happened": {
            "carriedOut": trace["happened"]["enacted"],
            "calls": [{k: c.get(k) for k in ("state", "disposition", "business")} for c in trace["happened"]["calls"]],
            "outcome": trace["happened"]["label"],
        },
    }


def explain(decision_id: str) -> dict[str, Any]:
    """``{"text", "source"}``: the model's explanation, or the rule-written one."""
    import azure_openai
    import decision_trace

    trace = decision_trace.trace(decision_id)
    fallback = {"text": trace["choice"].get("rationale") or "", "source": "rule"}
    payload = json.dumps(_compact(trace), default=str)
    try:
        result = azure_openai.chat_with_tools(
            [{"role": "system", "content": _EXPLAIN_SYSTEM}, {"role": "user", "content": payload}],
            tools=None,
            temperature=0.0,
            max_completion_tokens=1200,
            profile=azure_openai.PROFILE_ANALYSIS,
            reasoning_effort="low",
            timeout=30,
        )
    except Exception:
        logger.info("explanation unavailable for %s; using the rule-written one", decision_id)
        return fallback
    # Plain text for the screen: the model likes markdown emphasis.
    text = str(result.get("content") or "").replace("**", "").replace("__", "").strip()
    if not text or not _grounded(text, payload):
        return fallback
    return {"text": text, "source": "llm"}


_ADVISE_TOOL = {
    "type": "function",
    "function": {
        "name": "propose_changes",
        "description": "Propose up to three setting changes, each with the evidence behind it.",
        "parameters": {
            "type": "object",
            "properties": {
                "proposals": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "value": {},
                            "reason": {"type": "string"},
                        },
                        "required": ["key", "value", "reason"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["proposals"],
            "additionalProperties": False,
        },
    },
}

_ADVISE_SYSTEM = (
    "You review a debt-collections decision engine once a week and may propose "
    "changes to its settings. You receive the current settings (with bounds), the "
    "response rates it assumed and what it has since learned from outcomes, what "
    "blocked contact this week, and the measured lift against a comparison group. "
    "Propose a change only when the evidence clearly supports it, and propose "
    "nothing otherwise. Use only the keys listed. Each reason must cite the numbers "
    "from the input that justify it. You never change mode or anything that would "
    "contact customers more aggressively without evidence of lift."
)


def advise(*, tenant_id: str) -> dict[str, Any]:
    """One weekly review for the bound tenant. Returns what it proposed."""
    import azure_openai
    import decision_trace
    import strategy

    settings = [s for s in strategy.settings() if s["key"] != "TREATMENT_MODE"]
    context = {
        "settings": [
            {k: s[k] for k in ("key", "label", "value", "minimum", "maximum")} for s in settings
        ],
        "learned": decision_trace.learned_rates(),
        "blocked": decision_trace.health(days=7)["blockers"],
    }
    try:
        from agent_core.treatment import metrics

        import db

        with db.engine.connect() as conn:
            context["lift"] = metrics.causal(conn, days=56, modes=["shadow", "live"])
    except Exception:
        context["lift"] = {"available": False}
    payload = json.dumps(context, default=str)
    try:
        result = azure_openai.chat_with_tools(
            [{"role": "system", "content": _ADVISE_SYSTEM}, {"role": "user", "content": payload}],
            tools=[_ADVISE_TOOL],
            tool_choice={"type": "function", "function": {"name": "propose_changes"}},
            temperature=0.0,
            max_completion_tokens=2500,
            profile=azure_openai.PROFILE_ANALYSIS,
            reasoning_effort="low",
            timeout=90,
        )
        calls = result.get("toolCalls") or []
        raw = calls[0]["arguments"] if calls else "{}"
        proposals = (json.loads(raw) if isinstance(raw, str) else raw).get("proposals") or []
    except Exception:
        logger.exception("advisor unavailable for %s", tenant_id)
        return {"proposed": [], "error": "advisor_unavailable"}

    allowed = {s["key"] for s in settings}
    made, refused = [], []
    for p in proposals[:3]:
        key, reason = str(p.get("key") or ""), str(p.get("reason") or "").strip()
        if key not in allowed or not reason or not _grounded(reason, payload):
            refused.append({"key": key, "why": "unknown key, empty reason, or a number not in the evidence"})
            continue
        try:
            made.append(
                strategy.propose(
                    {key: p.get("value")}, reason=reason, author="advisor", via="advisor",
                    evidence={"learned": context["learned"], "blocked": context["blocked"]},
                )["id"]
            )
        except ValueError as exc:
            refused.append({"key": key, "why": str(exc)})
    return {"proposed": made, "refused": refused}


if __name__ == "__main__":
    assert _grounded("It held because 3 of 20 were reached.", '{"a": 3, "b": "20"}')
    assert not _grounded("It would recover 5,000.", '{"a": 3}')
    print("ok")
