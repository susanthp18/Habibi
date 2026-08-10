"""The tool catalog as an MCP surface — read-only, and provably so.

``agent_core/tools/schema.py`` is a well-specified tool registry that only two
in-house channels can reach. Exposing it over MCP lets an external agent — a
supervisor bot, the bank's own copilot — drive the same contracts.

The entire risk is that it drives the *wrong* ones. Every mutating tool here
writes to a bank's CRM, and on voice and text those writes sit behind
``CallContext.identity_verified``. MCP has no verification ceremony, so that
gate has no analogue. Most of this file exists to make adding a mutator to the
MCP surface impossible to do by accident.
"""

from __future__ import annotations

import json

import pytest

import mcp_tools
from agent_core.tools.catalog import CATALOG
from agent_core.tools.schema import CHANNEL_MCP


# ---------------------------------------------------------------------------
# Nothing that writes is reachable
# ---------------------------------------------------------------------------


def test_no_mutating_tool_is_exposed() -> None:
    """Asserted against an explicit list so adding one fails loudly here."""
    exposed = {s.name for s in CATALOG.for_channel(CHANNEL_MCP)}

    assert exposed.isdisjoint(mcp_tools.DENIED), (
        f"mutating tools reachable over MCP: {sorted(exposed & mcp_tools.DENIED)}"
    )


def test_the_exposed_set_is_exactly_the_read_tools() -> None:
    assert {s.name for s in CATALOG.for_channel(CHANNEL_MCP)} == {
        "get_customer_context",
        "get_payment_history",
        "get_emi_schedule",
        "check_product_eligibility",
        "search_knowledge_base",
    }


def test_handlers_match_the_exposed_specs() -> None:
    """A spec with no handler 500s; a handler with no spec is unreachable."""
    assert set(mcp_tools.HANDLERS) == {s.name for s in CATALOG.for_channel(CHANNEL_MCP)}


@pytest.mark.parametrize("name", sorted(mcp_tools.DENIED))
def test_calling_a_denied_tool_is_refused(name: str) -> None:
    with pytest.raises(mcp_tools.McpToolError):
        mcp_tools.call_tool(name, {"customer_id": "anyone"})


def test_calling_an_unknown_tool_is_refused() -> None:
    with pytest.raises(mcp_tools.McpToolError):
        mcp_tools.call_tool("drop_all_tables", {"customer_id": "x"})


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_every_exposed_tool_renders_valid_json_schema() -> None:
    for tool in mcp_tools.list_tools():
        schema = tool["inputSchema"]
        assert tool["name"] and tool["description"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert isinstance(schema["properties"], dict)
        # Round-trips — an MCP client receives this as JSON.
        json.loads(json.dumps(tool))


def test_customer_id_is_required_on_every_tool() -> None:
    """Voice and text bind the customer from session state; MCP has no session,
    so it must be supplied and must not be optional."""
    for tool in mcp_tools.list_tools():
        schema = tool["inputSchema"]
        assert "customer_id" in schema["properties"]
        assert "customer_id" in schema["required"]


def test_schema_is_non_strict() -> None:
    """The OpenAI strict shape marks optional args nullable AND required, which
    is correct for constrained decoding and misleading to anyone reading it."""
    tool = next(t for t in mcp_tools.list_tools() if t["name"] == "get_payment_history")
    schema = tool["inputSchema"]

    # `limit` is optional in the catalog; only customer_id should be required.
    assert schema["required"] == ["customer_id"]
    assert "strict" not in tool


def test_optional_arg_keeps_its_bounds() -> None:
    """Non-strict rendering preserves minimum/maximum, which strict drops."""
    tool = next(t for t in mcp_tools.list_tools() if t["name"] == "get_payment_history")
    limit = tool["inputSchema"]["properties"]["limit"]

    assert limit["minimum"] == 1
    assert limit["maximum"] == 20


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_missing_customer_id_is_rejected() -> None:
    with pytest.raises(mcp_tools.McpToolError, match="customer_id"):
        mcp_tools.call_tool("get_customer_context", {})


def test_missing_required_arg_is_rejected() -> None:
    with pytest.raises(mcp_tools.McpToolError, match="missing required"):
        mcp_tools.call_tool("check_product_eligibility", {"customer_id": "anita-desai"})


def test_unknown_customer_is_reported_not_crashed(db_tx) -> None:
    with pytest.raises(mcp_tools.McpToolError, match="customer not found"):
        mcp_tools.call_tool("get_customer_context", {"customer_id": "no-such-customer"})


def test_a_read_returns_data(db_tx) -> None:
    from sqlalchemy import text

    cid = db_tx.execute(text("SELECT id FROM customers LIMIT 1")).scalar()

    result = mcp_tools.call_tool("get_customer_context", {"customer_id": cid})

    assert result["customerId"] == cid
    assert "name" in result


def test_limit_default_comes_from_the_spec(db_tx) -> None:
    """normalize_args applies catalog defaults, same as every other channel."""
    from sqlalchemy import text

    cid = db_tx.execute(text("SELECT id FROM customers LIMIT 1")).scalar()

    result = mcp_tools.call_tool("get_payment_history", {"customer_id": cid})

    assert len(result["entries"]) <= 8


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def test_every_call_is_audited(db_tx) -> None:
    """A CRM tool surface with no audit trail is not shippable."""
    from sqlalchemy import text

    cid = db_tx.execute(
        text(
            "SELECT customer_id FROM interactions "
            "WHERE customer_id IS NOT NULL ORDER BY started_at DESC LIMIT 1"
        )
    ).scalar()
    before = db_tx.execute(
        text("SELECT count(*) FROM bot_tool_calls WHERE channel = 'mcp'")
    ).scalar()

    mcp_tools.call_tool("get_customer_context", {"customer_id": cid})

    after = db_tx.execute(
        text("SELECT count(*) FROM bot_tool_calls WHERE channel = 'mcp'")
    ).scalar()
    assert after == before + 1

    row = db_tx.execute(
        text(
            "SELECT tool_name, result_ok, job_id, conversation_id, interaction_id "
            "FROM bot_tool_calls WHERE channel = 'mcp' ORDER BY created_at DESC LIMIT 1"
        )
    ).mappings().first()
    assert row["tool_name"] == "get_customer_context"
    assert row["result_ok"] is True
    # The shape migration 0055 enabled: no job, no conversation, still attributable.
    assert row["job_id"] is None
    assert row["conversation_id"] is None
    assert row["interaction_id"] is not None


def test_a_soft_failure_is_audited_as_a_failure(db_tx) -> None:
    """The domain layer soft-fails: an invalid product id comes back as
    ToolResult(ok=False), not an exception. Recording that as a success would
    put a check that never happened in the audit log as one that passed."""
    from sqlalchemy import text

    cid = db_tx.execute(
        text(
            "SELECT customer_id FROM interactions "
            "WHERE customer_id IS NOT NULL ORDER BY started_at DESC LIMIT 1"
        )
    ).scalar()

    result = mcp_tools.call_tool(
        "check_product_eligibility", {"customer_id": cid, "product_id": "not-a-product"}
    )
    assert result["ok"] is False

    row = db_tx.execute(
        text(
            "SELECT tool_name, result_ok, error FROM bot_tool_calls "
            "WHERE channel = 'mcp' ORDER BY created_at DESC LIMIT 1"
        )
    ).mappings().first()
    assert row["tool_name"] == "check_product_eligibility"
    assert row["result_ok"] is False
    assert row["error"]


# ---------------------------------------------------------------------------
# KB
# ---------------------------------------------------------------------------


def test_an_external_query_does_not_create_a_kb_gap(db_tx, monkeypatch) -> None:
    """An agent's query is not a customer failing to get an answer.

    record_kb_gap is gated on interaction_id, so passing none is the mechanism —
    pinned here so a future edit that "helpfully" threads one through has to
    confront it.
    """
    import db as db_mod
    import kb_retrieve

    monkeypatch.setenv("KB_GAP_CAPTURE_ENABLED", "true")
    monkeypatch.setattr(
        kb_retrieve, "retrieve", lambda **kw: {"results": [], "latencyMs": 3, "logId": "L"}
    )
    calls: list[dict] = []
    monkeypatch.setattr(db_mod, "record_kb_gap", lambda **kw: calls.append(kw))

    mcp_tools.call_tool(
        "search_knowledge_base",
        {"customer_id": "anita-desai", "query": "what does the travel policy exclude"},
    )

    assert calls == []
