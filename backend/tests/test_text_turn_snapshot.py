"""What one WhatsApp turn leaves behind, pinned before ``_handle_turn`` is taken apart.

``bot_runtime._handle_turn`` is one 860-line function: idempotency, the policy
gate, the thread fetch, classification, the guardrail pre-checks, the model
loop, the send, the state save and the transcript. Splitting it into phases
must not reorder a read, drop a row or change what the model is handed. This
drives the *real* turn on a fresh inbound thread with a scripted gateway and a
fake transport -- no network -- and compares every row it wrote against
``tests/snapshots/text_turn.json``.

Two scenarios: a plain question that runs the tool loop and sends, and a
request for a human that escalates before the model is ever called.

Regenerate deliberately, never to make a red run green:

    UPDATE_SNAPSHOTS=1 pytest tests/test_text_turn_snapshot.py
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "text_turn.json"

SCENARIOS = {
    "question": "hi, how much do i owe this month and when is it due?",
    "human": "stop. i want to speak to a human agent right now",
}


class _Gateway:
    """The model, scripted: one note-taking tool call when it is offered, then a reply."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat_with_tools(self, messages, *, tools, temperature, max_completion_tokens):
        offered = sorted(
            (t.get("function") or {}).get("name") or t.get("name") or "?" for t in tools
        )
        self.calls.append(
            {
                "roles": [m.get("role") for m in messages],
                "last_user": next(
                    (
                        m.get("content")
                        for m in reversed(messages)
                        if m.get("role") == "user"
                    ),
                    None,
                ),
                "offered": offered,
                "temperature": temperature,
                "max_completion_tokens": max_completion_tokens,
            }
        )
        if len(self.calls) == 1 and "add_customer_note" in offered:
            return {
                "content": None,
                "toolCalls": [
                    {
                        "id": "call_1",
                        "name": "add_customer_note",
                        "arguments": json.dumps(
                            {"text": "asked for this month's dues"}
                        ),
                    }
                ],
            }
        return {
            "content": "Thanks -- I can see your account. Shall we set up a payment today?",
            "toolCalls": [],
        }


def _seed(conn, body: str) -> dict[str, Any]:
    """A never-seen number writes in: customer, interaction, thread, message, job."""
    import db_whatsapp

    out = db_whatsapp._ingest_inbound_whatsapp_message(
        conn,
        wa_message_id=f"wamid.SNAP{secrets.token_hex(6)}",
        from_phone="+9198" + "".join(secrets.choice("0123456789") for _ in range(8)),
        body=body,
        profile_name="Snapshot Borrower",
        sent_at=datetime.now(timezone.utc),
    )
    assert out.get("botJobId"), out
    job = (
        conn.execute(
            text("SELECT * FROM bot_turn_jobs WHERE id = :id"), {"id": out["botJobId"]}
        )
        .mappings()
        .first()
    )
    return dict(job)


def _rows(conn, job: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    def alias(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("wamid.SENT"):
            return "<wamid.sent>"
        return aliases.get(value, value) if isinstance(value, str) else value

    cid = job["conversation_id"]
    jrow = (
        conn.execute(
            text(
                "SELECT status, error, outbound_message_id FROM bot_turn_jobs WHERE id = :id"
            ),
            {"id": job["id"]},
        )
        .mappings()
        .first()
    )
    outbound = conn.execute(
        text(
            "SELECT id, sender, body, delivery_status, provider_ref FROM messages "
            " WHERE conversation_id = :c ORDER BY sender DESC, id"  # now() is the transaction start under db_tx
        ),
        {"c": cid},
    ).mappings()
    messages = []
    for m in outbound:
        if m["sender"] == "bot":
            aliases.setdefault(m["id"], "<outbound>")
        messages.append({k: alias(v) for k, v in dict(m).items()})
    conv = (
        conn.execute(
            text(
                "SELECT status, assigned_user_id, bot_state, interaction_id FROM conversations WHERE id = :c"
            ),
            {"c": cid},
        )
        .mappings()
        .first()
    )
    state = dict(conv["bot_state"] or {})
    state = {k: alias(v) for k, v in state.items() if k != "dialog_reset_at"}
    tool_calls = [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT tool_name, result_ok, error, channel, interaction_id IS NOT NULL AS on_interaction,"
                "       transcript_turn_id IS NOT NULL AS on_turn"
                "  FROM bot_tool_calls WHERE job_id = :j ORDER BY created_at, id"
            ),
            {"j": job["id"]},
        ).mappings()
    ]
    transcript = [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT turn_index, speaker, text, intent"
                "  FROM interaction_transcript WHERE interaction_id = :ix ORDER BY turn_index"
            ),
            {"ix": conv["interaction_id"]},
        ).mappings()
    ]
    ix = (
        conn.execute(
            text(
                "SELECT status, disposition, primary_intent FROM interactions WHERE id = :ix"
            ),
            {"ix": conv["interaction_id"]},
        )
        .mappings()
        .first()
    )
    return {
        "job": {k: alias(v) for k, v in dict(jrow).items()},
        "messages": messages,
        "conversation": {
            "status": conv["status"],
            "assigned_user_id": conv["assigned_user_id"],
        },
        "bot_state": state,
        "tool_calls": tool_calls,
        "transcript": transcript,
        "interaction": dict(ix) if ix else None,
    }


def render(monkeypatch: pytest.MonkeyPatch, conn) -> dict[str, Any]:
    import bot_conversation
    import bot_runtime
    import db

    monkeypatch.setenv("UNDERSTANDING_LLM_ENABLED", "0")
    # The gate is its own function and not what is being moved; a fresh number
    # has no consent on file and the policy would refuse before the turn ran.
    monkeypatch.setattr(bot_conversation, "policy_gate", lambda _engine, _conv: None)
    sent = {"n": 0}

    def _send(*, to_phone, body):
        sent["n"] += 1
        return {"messages": [{"id": f"wamid.SENT{sent['n']}"}]}

    monkeypatch.setattr(bot_runtime.wa, "send_text_message", _send)
    monkeypatch.setattr(
        bot_runtime.wa,
        "mark_read_with_typing",
        lambda *, message_id: None,
    )
    out: dict[str, Any] = {}
    for name, body in SCENARIOS.items():
        gateway = _Gateway()
        monkeypatch.setattr(
            bot_runtime.azure_openai, "chat_with_tools", gateway.chat_with_tools
        )
        job = _seed(conn, body)
        aliases = {
            job["id"]: "<job>",
            job["trigger_message_id"]: "<inbound>",
            job["trigger_provider_ref"]: "<wamid>",
        }
        bot_runtime.handle_turn(db.engine, job)
        out[name] = {"gateway": gateway.calls, **_rows(conn, job, aliases)}
    return out


def test_one_text_turn_matches_the_snapshot(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = (
        json.dumps(render(monkeypatch, db_tx), indent=2, sort_keys=True, default=str)
        + "\n"
    )
    if os.getenv("UPDATE_SNAPSHOTS"):
        SNAPSHOT.write_text(current, encoding="utf-8")
        return
    assert SNAPSHOT.exists(), "no snapshot yet: run once with UPDATE_SNAPSHOTS=1"
    pinned = SNAPSHOT.read_bytes().replace(b"\r\n", b"\n")  # autocrlf checkouts
    assert current.encode("utf-8") == pinned, (
        "the text turn left different rows or handed the model something else -- "
        "if the change is intended, regenerate with UPDATE_SNAPSHOTS=1 and review the diff"
    )
