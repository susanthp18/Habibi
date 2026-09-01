"""Dispatch for the MCP tool surface — read-only, audited, out of process.

``ToolSpec`` carries no handler (voice passes one to ``to_flows_schema``, text
dispatches through ``bot_tools.execute_tool``), so a third transport needs its
own map. Kept deliberately small and explicit rather than reflective: the set of
tools an external agent can drive against a bank's CRM should be a list someone
can read in ten seconds, not something derived at import time.

What this is not: a general RPC layer. Every mutating tool is excluded — see
``DENIED`` and the comment on ``catalog.BOTH_AND_MCP``. On voice and text those
writes sit behind ``CallContext.identity_verified``; MCP has no verification
ceremony, so until it does, it reads.

Every call is audited into ``bot_tool_calls`` with ``channel='mcp'``, which is
possible only because migration 0055 made ``job_id`` nullable. A CRM tool
surface with no audit trail is not shippable.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable

from agent_core.tools import domain, kb
from agent_core.tools.catalog import CATALOG
from agent_core.tools.schema import CHANNEL_MCP

logger = logging.getLogger(__name__)


class McpToolError(RuntimeError):
    """A caller-visible failure — bad args, unknown tool, or a denied tool."""


# Explicit deny-list, asserted on in tests. Redundant with `channels` by design:
# if someone adds CHANNEL_MCP to a mutator, this is the second thing that has to
# be edited, and the test that reads it fails loudly.
DENIED: frozenset[str] = frozenset(
    {
        "create_promise_to_pay",
        "flag_dispute",
        "capture_lead",
        "decline_offer",
        "evaluate_authority",
        "apply_goodwill",
        "recommend_next_offer",
        "request_documents",
        "request_callback",
        "add_customer_note",
        "escalate_to_human",
        "identify_customer",
        "verify_identity",
        "get_account_position",
        "mark_upsell_presented",
    }
)


def _get_customer_context(customer_id: str, args: dict[str, Any]) -> dict[str, Any]:
    import db

    customer = db.get_customer(customer_id)
    if not customer:
        raise McpToolError(f"customer not found: {customer_id}")
    account = customer.get("account") or {}
    return {
        "customerId": customer.get("id"),
        "name": customer.get("name"),
        "accountId": customer.get("accountId"),
        "outstanding": customer.get("outstanding"),
        "minimumDue": customer.get("minimumDue"),
        "dpd": account.get("dpd"),
        "product": account.get("product"),
        "bucket": account.get("bucket"),
    }


def _get_payment_history(customer_id: str, args: dict[str, Any]) -> dict[str, Any]:
    import db

    customer = db.get_customer(customer_id)
    if not customer:
        raise McpToolError(f"customer not found: {customer_id}")
    limit = int(args.get("limit") or 8)
    return {"entries": (customer.get("ledger") or [])[:limit]}


def _get_emi_schedule(customer_id: str, args: dict[str, Any]) -> dict[str, Any]:
    import db

    customer = db.get_customer(customer_id)
    if not customer:
        raise McpToolError(f"customer not found: {customer_id}")
    limit = int(args.get("limit") or 6)
    return {"installments": (customer.get("emi") or [])[:limit]}


def _check_product_eligibility(customer_id: str, args: dict[str, Any]) -> dict[str, Any]:
    result = domain.check_product_eligibility(
        customer_id=customer_id,
        product_id=str(args.get("product_id") or ""),
        channel="mcp",
    )
    return result.to_llm()


def _search_knowledge_base(customer_id: str, args: dict[str, Any]) -> dict[str, Any]:
    result = kb.search_knowledge_base(
        query=str(args.get("query") or ""),
        channel="text",
        # No interaction: an external agent's query is not a customer failing to
        # get an answer, so it must not create a KB gap row. record_kb_gap is
        # gated on interaction_id, so passing none is the whole mechanism.
        interaction_id=None,
        apply_intent_gate=False,
    )
    return result.to_llm()


HANDLERS: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]] = {
    "get_customer_context": _get_customer_context,
    "get_payment_history": _get_payment_history,
    "get_emi_schedule": _get_emi_schedule,
    "check_product_eligibility": _check_product_eligibility,
    "search_knowledge_base": _search_knowledge_base,
}


def list_tools() -> list[dict[str, Any]]:
    """MCP ``tools/list``, with ``customer_id`` added to every entry.

    Voice and text bind the customer from session state so the model never
    supplies it. MCP has no session, so it becomes a required argument — and
    because it is not in the catalog spec, it is injected here rather than
    polluting the specs the other two channels share.
    """
    out: list[dict[str, Any]] = []
    for spec in CATALOG.for_channel(CHANNEL_MCP):
        if spec.name in DENIED:
            logger.error("tool %s is both MCP-exposed and denied — omitting", spec.name)
            continue
        tool = spec.to_mcp_tool()
        schema = tool["inputSchema"]
        schema["properties"] = {
            "customer_id": {
                "type": "string",
                "description": "CRM customer id the request is scoped to.",
            },
            **schema["properties"],
        }
        schema["required"] = ["customer_id", *schema.get("required", [])]
        out.append(tool)
    return out


def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run one MCP tool call. Raises :class:`McpToolError` for caller mistakes."""
    raw = dict(arguments or {})
    spec = CATALOG.get(name)
    if spec is None or CHANNEL_MCP not in spec.channels or name in DENIED:
        raise McpToolError(f"unknown or unavailable tool: {name}")

    customer_id = str(raw.pop("customer_id", "") or "").strip()
    if not customer_id:
        raise McpToolError("customer_id is required")

    # Same normalise-then-validate order as bot_tools.execute_tool, so alias
    # keys and defaults behave identically on every channel.
    args = spec.normalize_args(raw)
    missing = spec.missing_required(args)
    if missing:
        raise McpToolError(f"missing required arguments: {', '.join(missing)}")

    handler = HANDLERS.get(name)
    if handler is None:
        raise McpToolError(f"no handler registered for {name}")

    started = time.perf_counter()
    ok = True
    error: str | None = None
    try:
        payload = handler(customer_id, args)
        # The domain layer soft-fails: an invalid product id comes back as
        # ToolResult(ok=False), not an exception. Auditing that as a success
        # would record a check that never happened as one that passed.
        if isinstance(payload, dict) and payload.get("ok") is False:
            ok = False
            error = str(payload.get("error") or "tool_reported_failure")
        return payload
    except McpToolError as exc:
        ok, error = False, str(exc)
        raise
    except Exception as exc:
        ok, error = False, type(exc).__name__
        logger.exception("mcp tool failed · %s", name)
        raise McpToolError(f"{name} failed") from exc
    finally:
        _audit(
            name,
            customer_id=customer_id,
            args=args,
            ok=ok,
            error=error,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _audit(
    name: str,
    *,
    customer_id: str,
    args: dict[str, Any],
    ok: bool,
    error: str | None,
    latency_ms: int,
) -> None:
    """Write the call to ``bot_tool_calls``. Never raises into the caller.

    Rows carry ``channel='mcp'`` with no job or conversation — exactly the shape
    migration 0055 enabled. ``interaction_id`` is the customer's most recent
    interaction so the CHECK constraint is satisfied and the rows are greppable.

    This used to be a hand-written INSERT, which is why MCP was one of the three
    channels storing tool arguments verbatim: the redaction lived at a different
    writer. Going through ``bot_jobs.record_tool_call`` -- the function this
    module's docstring already claimed it audited through -- means the masking
    applies here by construction rather than by being remembered.
    """
    try:
        import bot_jobs
        import db
        from sqlalchemy import text

        with db.engine.begin() as conn:
            interaction_id = conn.execute(
                text(
                    """
                    SELECT i.id FROM interactions i
                     WHERE i.customer_id = :cid
                     ORDER BY i.started_at DESC NULLS LAST
                     LIMIT 1
                    """
                ),
                {"cid": customer_id},
            ).scalar()
            # Deliberately quiet when nothing matches: a customer with no
            # interactions has nothing to attribute the call to, and the CHECK
            # forbids a row with neither key. The structured log below is the
            # record in that case.
            if interaction_id:
                bot_jobs.record_tool_call(
                    conn,
                    interaction_id=interaction_id,
                    channel="mcp",
                    tool_name=name,
                    args=args,
                    result_ok=ok,
                    error=error,
                    latency_ms=latency_ms,
                )
    except Exception:
        logger.warning("mcp audit write failed · %s", name, exc_info=True)

    logger.info(
        "mcp_tool_call tool=%s customer=%s ok=%s latency_ms=%s",
        name,
        customer_id,
        ok,
        latency_ms,
    )


def api_key() -> str:
    return (os.getenv("MCP_API_KEY") or "").strip()
