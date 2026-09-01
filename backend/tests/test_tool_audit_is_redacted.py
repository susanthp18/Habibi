"""Every channel that runs a tool writes the same kind of audit row.

Four executors reach ``bot_tool_calls``, and until now they disagreed about what
they put in it:

* voice redacted arguments through ``voice/persist._audit_args``;
* text (``bot_runtime``) passed the model's arguments straight through, and set
  ``result_preview`` to ``json.dumps(payload)[:1500]`` verbatim;
* MCP wrote its own hand-rolled INSERT, bypassing the writer its module
  docstring claimed it audited through;
* the sandbox wrote **no row at all**, while executing the real catalog tools
  against a real ``customer_id``.

The sharpest case is ``identify_customer``: a text-channel-only spec taking
``phone`` and ``account_tail`` -- exactly the shape voice withholds -- landing
verbatim in a column the Inbox renders.

The fix is not four call sites remembering a helper, because that is what had
already failed. ``bot_jobs.record_tool_call`` is the one function that writes
this row, so the masking happens there and a fifth channel cannot get it wrong.
These tests pin that, at the writer rather than per channel: parameterising over
the channel names is deliberate, so a new executor shows up here as a name to
add rather than as a row nobody checked.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

import bot_jobs
import pii_redact

CARD = "4111 1111 1111 1111"
PHONE = "+91 98765 43210"

#: Every channel that writes to bot_tool_calls. Adding an executor without
#: adding it here is the drift this file exists to catch.
CHANNELS = ("voice", "whatsapp", "mcp", "sandbox")


def _row(conn, tool_call_id: str) -> dict:
    return dict(
        conn.execute(
            text(
                "SELECT tool_name, args, result_preview, channel"
                " FROM bot_tool_calls WHERE id = :id"
            ),
            {"id": tool_call_id},
        )
        .mappings()
        .first()
    )


def _an_interaction(conn) -> str:
    row = conn.execute(text("SELECT id FROM interactions LIMIT 1")).scalar()
    if not row:
        pytest.skip("no seeded interaction")
    return row


# --- the writer masks, whatever the channel ---------------------------------


@pytest.mark.parametrize("channel", CHANNELS)
def test_identity_arguments_are_never_stored(db_tx, channel: str) -> None:
    """The digits are what the verification was protecting."""
    tool_call_id = bot_jobs.record_tool_call(
        db_tx,
        interaction_id=_an_interaction(db_tx),
        channel=channel,
        tool_name="verify_identity",
        args={"method": "account_tail", "value": "7741"},
        result_ok=True,
    )
    assert _row(db_tx, tool_call_id)["args"] == {"_withheld": True}


@pytest.mark.parametrize("channel", CHANNELS)
def test_the_text_only_identify_tool_is_withheld_too(db_tx, channel: str) -> None:
    """``identify_customer`` takes phone and account_tail and is text-only, so
    the one channel that redacted was the one channel it could not reach."""
    tool_call_id = bot_jobs.record_tool_call(
        db_tx,
        interaction_id=_an_interaction(db_tx),
        channel=channel,
        tool_name="identify_customer",
        args={"phone": PHONE, "account_tail": "7741"},
        result_ok=True,
    )
    stored = json.dumps(_row(db_tx, tool_call_id)["args"])
    assert "7741" not in stored and "98765" not in stored


@pytest.mark.parametrize("channel", CHANNELS)
def test_free_text_arguments_are_masked(db_tx, channel: str) -> None:
    tool_call_id = bot_jobs.record_tool_call(
        db_tx,
        interaction_id=_an_interaction(db_tx),
        channel=channel,
        tool_name="flag_dispute",
        args={"summary": f"my card {CARD} was charged twice", "amount": 500},
        result_ok=True,
    )
    args = _row(db_tx, tool_call_id)["args"]
    assert CARD not in args["summary"], "a spoken card number survived in the audit row"
    assert args["amount"] == 500, "non-text arguments are kept as they are"


@pytest.mark.parametrize("channel", CHANNELS)
def test_the_result_preview_is_masked(db_tx, channel: str) -> None:
    """Results are bigger than arguments and come back *from* the CRM, so this
    was the larger of the two leaks."""
    tool_call_id = bot_jobs.record_tool_call(
        db_tx,
        interaction_id=_an_interaction(db_tx),
        channel=channel,
        tool_name="get_customer_context",
        args={},
        result_ok=True,
        result_preview=json.dumps({"phone": PHONE, "card": CARD}),
    )
    preview = _row(db_tx, tool_call_id)["result_preview"]
    assert CARD not in preview and "98765" not in preview


# --- and the masking itself ---------------------------------------------------


def test_a_single_long_argument_is_capped_not_dropped() -> None:
    """Per-value ceiling first: one long note is still worth keeping the head of."""
    kept = pii_redact.audit_args("add_customer_note", {"note": "x" * 20_000})
    assert len(kept["note"]) == 1000


def test_a_wall_of_arguments_cannot_grow_the_table() -> None:
    """The total ceiling is what a model emitting many long fields runs into.

    It takes several capped values to exceed it, because each one is already
    bounded — which is why this asserts on breadth rather than on one huge
    string.
    """
    huge = pii_redact.audit_args(
        "add_customer_note", {f"f{i}": "x" * 2_000 for i in range(6)}
    )
    assert huge == {"_truncated": True}


def test_masking_is_idempotent() -> None:
    """record_tool_call may be reached from a path that already masked."""
    once = pii_redact.audit_args("flag_dispute", {"summary": f"card {CARD}"})
    twice = pii_redact.audit_args("flag_dispute", once)
    assert once == twice


def test_the_voice_alias_still_resolves_to_the_shared_implementation() -> None:
    """voice/persist kept the old private name; it must not become a second copy."""
    from voice import persist

    assert persist._audit_args is pii_redact.audit_args
