"""Voice Studio checks: scripted rehearsals of an engine agent, graded.

The old studio rehearsed cards in its own sandbox; engine agents are rehearsed
through the engine itself. A check plays each scenario's scripted customer
lines (``sandbox_scenarios``) into the agent's text chat, then grades every
agent turn against the agent's PayInt guardrails (``voice_studio.guardrails_for``).
A scenario passes when no agent turn raises a guardrail flag and the agent
answered every line; flags the customer's own words raise (a legal threat) are
shown but do not fail it.

Rehearsals and the editor's own test chats/calls never touch real records:
``rehearsal_tool`` answers the agent's tools from the scenario persona (or a
test persona) and writes nothing. A run is a test when the engine did not stamp
a ``direction`` (only real telephony, API triggers and WhatsApp do) or when it
carries ``rehearsal``.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import threading
import uuid
from typing import Any, Callable

from sqlalchemy import text

import voice_studio
from agent_core.guardrails import evaluate_guardrails

logger = logging.getLogger(__name__)

TEST_PERSONA: dict[str, Any] = {
    "name": "Test Customer", "overdue": 12480, "dpd": 30, "minimumDue": 2100,
    "product": "Personal Loan", "phoneLast4": None, "accountNo": None,
}

#: Raised by what the customer says, not by the agent: expected, never a failure.
CUSTOMER_FLAGS = frozenset({"auto-escalate", "politics-religion"})

#: A placeholder the agent said out loud ("overdue by [overdue_amount]"): the model
#: invented a template because it had no value, and a caller would hear it.
_TEMPLATE_LEAK = re.compile(r"\[[a-z][a-z0-9_]*\]|\{\{[^}]*\}\}|(?<!\{)\{[a-z][a-z0-9_]*\}")

# ponytail: per-process memory of which test runs verified; tests only, lost on restart.
_verified_runs: set[str] = set()


def _inr(value: Any) -> str | None:
    return voice_studio._spoken_inr(value)


def scenarios() -> list[dict[str, Any]]:
    import db

    with db.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, name, sim_persona, turns FROM sandbox_scenarios WHERE tenant_id = :t ORDER BY name"),
            {"t": db.current_tenant()},
        ).mappings().all()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "persona": r["sim_persona"] or {},
            "turns": [str(t.get("customer") or "") for t in (r["turns"] or []) if str(t.get("customer") or "").strip()],
        }
        for r in rows
    ]


def _persona(scenario_id: str | None) -> dict[str, Any]:
    if scenario_id:
        for s in scenarios():
            if s["id"] == scenario_id:
                return {**TEST_PERSONA, **s["persona"]}
    return dict(TEST_PERSONA)


def rehearsal_tool(name: str, ctx: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """A tool call from a test or rehearsal: answered from the persona, nothing written."""
    persona = _persona(ctx.get("rehearsal"))
    run = str(ctx.get("workflow_run_id") or "")
    if name == "verify_identity":
        digits = "".join(ch for ch in str(args.get("value") or "") if ch.isdigit())
        if len(digits) != 4:
            return {"ok": False, "error": "need_four_digits", "say": "Ask for exactly four digits."}
        known = {str(persona.get("phoneLast4") or ""), str(persona.get("accountNo") or "")[-4:]} - {""}
        if known and digits not in known:
            return {"ok": True, "verified": False, "attempts_left": 2, "say": "Those digits don't match our records."}
        _verified_runs.add(run)
        return {"ok": True, "verified": True, "customer_name": persona.get("name"), "rehearsal": True}
    if name == "account_position":
        if run not in _verified_runs:
            return {"ok": False, "error": "identity_not_verified",
                    "say": "Verify the customer's identity before discussing the account."}
        return {
            "ok": True, "rehearsal": True,
            "outstanding_amount": _inr(persona.get("overdue")),
            "days_past_due": persona.get("dpd"),
            "minimum_due": _inr(persona.get("minimumDue")),
            "minimum_due_value": persona.get("minimumDue"),
            "product_name": persona.get("product"),
        }
    if name in ("promise_to_pay", "request_callback", "flag_dispute"):
        if name == "promise_to_pay" and run not in _verified_runs:
            return {"ok": False, "error": "identity_not_verified", "say": "Verify the customer's identity first."}
        return {"ok": True, "rehearsal": True, "reference": f"TEST-{uuid.uuid4().hex[:8].upper()}",
                "note": "Test conversation: nothing was recorded."}
    return {"ok": False, "error": "unknown_tool"}


def is_test(ctx: dict[str, Any]) -> bool:
    return bool(ctx.get("rehearsal")) or not ctx.get("direction")


# ---------------------------------------------------------------------------
# Check runs
# ---------------------------------------------------------------------------


def _transferred(session: dict[str, Any]) -> bool:
    return any(
        e.get("type") == "tool_call_started" and (e.get("payload") or {}).get("function_name") == "transfer_to_human"
        for t in session["session_data"]["turns"] for e in (t.get("events") or [])
    )


def _last_text(session: dict[str, Any]) -> str:
    turns = session["session_data"]["turns"]
    for t in reversed(turns):
        said = str((t.get("assistant_message") or {}).get("text") or "").strip()
        if said:
            return said
    return ""


def _converse(workflow_id: int, *, rehearsal: str, name: str, brief: str,
              next_line: Callable[[list[tuple[str, str]]], str | None], max_turns: int,
              result: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Drive one isolated text-chat rehearsal; ``next_line`` returns None to stop."""
    session = voice_studio.engine_call(
        "POST", f"/workflow/{workflow_id}/text-chat/sessions",
        json={
            "name": f"CHECK-{rehearsal}",
            "initial_context": {
                "rehearsal": rehearsal, "direction": "outbound", "customer_name": name,
                "first_name": name.split(" ")[0], "mission_brief": brief,
            },
            "annotations": {"voice_studio_check": rehearsal},
        },
        timeout=120,
    )
    run_id = session["workflow_run_id"]
    result["workflowRunId"] = run_id
    exchanges = [("", _last_text(session))]
    for _ in range(max_turns):
        if session.get("is_completed"):
            break
        line = next_line(exchanges)
        if not line:
            break
        session = voice_studio.engine_call(
            "POST", f"/workflow/{workflow_id}/text-chat/sessions/{run_id}/messages",
            json={"text": line, "expected_revision": session["revision"]}, timeout=120,
        )
        exchanges.append((line, _last_text(session)))
    if not session.get("is_completed"):
        voice_studio.engine_call("POST", f"/workflow/{workflow_id}/text-chat/sessions/{run_id}/end",
                                 json={}, timeout=60)
    return session, exchanges


def _grade(result: dict[str, Any], session: dict[str, Any], exchanges: list[tuple[str, str]],
           rules: dict[str, Any]) -> None:
    """Every agent turn against the guardrails; customer-raised flags never fail a run."""
    disclosed = False
    for index, (customer, agent) in enumerate(exchanges):
        flags = evaluate_guardrails(
            customer_text=customer, bot_text=agent, intent="out_of_scope", guardrails=rules,
            turn_index=index, elapsed_seconds=0, customer_bot_exchanges=index + 1, hard_max_turns=50,
            recording_disclosed=disclosed, channel="voice",
        )
        if not agent:
            flags.append("no-reply")
        elif _TEMPLATE_LEAK.search(agent):
            flags.append("template-leak")
        disclosed = disclosed or "missing-recording-disclosure" not in flags
        result["turns"].append({"customer": customer, "agent": agent, "flags": flags})
        result["flags"].extend(f for f in flags if f not in result["flags"])
    # A legal threat or abuse must reach a person: raising the flag is the
    # customer's doing, not handing over is the agent's.
    if "auto-escalate" in result["flags"] and not _transferred(session):
        result["flags"].append("escalation-missed")
    result["passed"] = not [f for f in result["flags"] if f not in CUSTOMER_FLAGS]


def _result(scenario_id: str, scenario_name: str) -> dict[str, Any]:
    return {"scenarioId": scenario_id, "scenarioName": scenario_name, "workflowRunId": None,
            "turns": [], "flags": [], "passed": False, "error": None}


def rehearse(workflow_id: int, scenario: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    persona = {**TEST_PERSONA, **scenario["persona"]}
    lines = list(scenario["turns"])
    if persona.get("phoneLast4") and lines:
        lines.insert(1, f"The last four digits are {persona['phoneLast4']}.")
    result = _result(scenario["id"], scenario["name"])
    script = iter(lines)
    try:
        session, exchanges = _converse(
            workflow_id, rehearsal=scenario["id"], name=str(persona.get("name") or ""),
            brief=persona.get("summary") or "", next_line=lambda _ex: next(script, None),
            max_turns=len(lines), result=result,
        )
        _grade(result, session, exchanges, rules)
    except Exception as exc:
        logger.exception("voice studio check %s failed", scenario["id"])
        result["error"] = str(exc)[:300]
    return result


# ---------------------------------------------------------------------------
# AI customer: an LLM plays a described customer against the agent
# ---------------------------------------------------------------------------

SIMULATION_ID = "ai-customer"
SIMULATION_MAX_TURNS = 12
_END = "[END]"
_CUSTOMER_PROMPT = """You are role-playing a customer of {bank} in a conversation with the bank's
collections agent. The chat stands in for a phone call.

Who you are and how you behave:
{persona}

Facts you know about your own account, used only if the agent asks:
- Name: {name}. Product: {product}. Overdue: about INR {overdue}. {dpd} days past due.
- The last four digits of your registered phone number are 4821.

Reply with ONE short thing the customer says next: no narration, no stage
directions, no labels. When the conversation has reached a natural end, or the
agent has handed you to a person, reply exactly {end}."""


def _customer_line(persona_text: str, exchanges: list[tuple[str, str]]) -> str | None:
    import azure_openai
    from agent_core.prompt import bank_name

    persona = TEST_PERSONA
    messages: list[dict[str, str]] = [{"role": "system", "content": _CUSTOMER_PROMPT.format(
        bank=bank_name(), persona=persona_text.strip()[:2000], name=persona["name"],
        product=persona["product"], overdue=persona["overdue"], dpd=persona["dpd"], end=_END)}]
    for customer, agent in exchanges:
        if customer:
            messages.append({"role": "assistant", "content": customer})
        if agent:
            messages.append({"role": "user", "content": agent})
    line = azure_openai.chat_complete(messages, temperature=0.7, max_completion_tokens=120).strip()
    if not line or _END in line:
        return None
    return line[:500]


def simulate(workflow_id: int, persona_text: str, rules: dict[str, Any],
             max_turns: int = SIMULATION_MAX_TURNS) -> dict[str, Any]:
    result = _result(SIMULATION_ID, f"AI customer: {persona_text.strip()[:80]}")
    try:
        session, exchanges = _converse(
            workflow_id, rehearsal=SIMULATION_ID, name=str(TEST_PERSONA["name"]),
            brief=persona_text.strip()[:500],
            next_line=lambda ex: _customer_line(persona_text, ex),
            max_turns=max(1, min(int(max_turns), 30)), result=result,
        )
        _grade(result, session, exchanges, rules)
    except Exception as exc:
        logger.exception("voice studio AI customer run failed")
        result["error"] = str(exc)[:300]
    return result


def _save(check_id: str, **fields: Any) -> None:
    import db

    with db.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE voice_studio_checks SET status = :status, passed = :passed, failed = :failed, "
                "results = CAST(:results AS jsonb), finished_at = now() WHERE id = :id"
            ),
            {"id": check_id, "status": fields["status"], "passed": fields["passed"], "failed": fields["failed"],
             "results": json.dumps(fields["results"])},
        )


def _run(check_id: str, workflow_id: int, rehearsals: list[Callable[[dict[str, Any]], dict[str, Any]]]) -> None:
    rules = voice_studio.guardrails_for(workflow_id)
    results = [play(rules) for play in rehearsals]
    passed = sum(1 for r in results if r["passed"])
    _save(check_id, status="done", passed=passed, failed=len(results) - passed, results=results)


def start(workflow_id: int, scenario_ids: list[str] | None, actor: str | None) -> dict[str, Any]:
    chosen = [s for s in scenarios() if not scenario_ids or s["id"] in scenario_ids]
    if not chosen:
        raise ValueError("no_scenarios")
    return _launch(workflow_id, actor, [lambda rules, s=s: rehearse(workflow_id, s, rules) for s in chosen])


def start_simulation(workflow_id: int, persona_text: str, actor: str | None,
                     max_turns: int = SIMULATION_MAX_TURNS) -> dict[str, Any]:
    if len(persona_text.strip()) < 10:
        raise ValueError("Describe the customer in a sentence or two")
    return _launch(workflow_id, actor, [lambda rules: simulate(workflow_id, persona_text, rules, max_turns)])


def _launch(workflow_id: int, actor: str | None,
            rehearsals: list[Callable[[dict[str, Any]], dict[str, Any]]]) -> dict[str, Any]:
    import db

    check_id = f"VSC-{uuid.uuid4().hex[:10].upper()}"
    with db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO voice_studio_checks (id, tenant_id, engine_workflow_id, created_by_user_id, status) "
                "VALUES (:id, :t, :w, :u, 'running')"
            ),
            {"id": check_id, "t": db.current_tenant(), "w": workflow_id, "u": actor},
        )
    # The request returns at once; the engine conversations take a minute.
    ctx = contextvars.copy_context()
    threading.Thread(target=ctx.run, args=(_run, check_id, workflow_id, rehearsals), daemon=True).start()
    return {"id": check_id, "status": "running"}


def runs(workflow_id: int, limit: int = 20) -> list[dict[str, Any]]:
    import db

    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, engine_workflow_id, status, passed, failed, results, created_by_user_id, created_at "
                "FROM voice_studio_checks WHERE tenant_id = :t AND engine_workflow_id = :w "
                "ORDER BY created_at DESC LIMIT :n"
            ),
            {"t": db.current_tenant(), "w": workflow_id, "n": limit},
        ).mappings().all()
    return [
        {"id": r["id"], "workflowId": r["engine_workflow_id"], "status": r["status"], "passed": r["passed"],
         "failed": r["failed"], "results": r["results"] or [], "createdBy": r["created_by_user_id"],
         "createdAt": r["created_at"].isoformat()}
        for r in rows
    ]


if __name__ == "__main__":  # self-check of the persona tools (no DB, no engine)
    _p = dict(TEST_PERSONA, phoneLast4="4821")
    globals()["_persona"] = lambda _sid: _p
    ctx = {"workflow_run_id": 1}
    assert rehearsal_tool("account_position", ctx, {})["error"] == "identity_not_verified"
    assert rehearsal_tool("verify_identity", ctx, {"value": "1111"})["verified"] is False
    assert rehearsal_tool("verify_identity", ctx, {"value": "4821"})["verified"] is True
    assert rehearsal_tool("account_position", ctx, {})["days_past_due"] == 30
    assert rehearsal_tool("promise_to_pay", ctx, {"amount": 1, "date": "2026-10-01"})["rehearsal"] is True
    assert is_test({}) and not is_test({"direction": "inbound"}) and is_test({"direction": "outbound", "rehearsal": "x"})
    print("ok")
