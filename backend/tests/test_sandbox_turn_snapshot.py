"""What one rehearsed turn returns and leaves behind, pinned before
``sandbox_runtime.append_sandbox_turn`` is taken apart.

``append_sandbox_turn`` is one 590-line function: the contract, the walker,
the cap, the thread, retrieval, assembly, the model (or the tool loop), the
guardrails and the two turn rows. Splitting it into phases must not reorder a
read, change the offer or drop a row. This drives the *real* function on a
fresh run of the published door card with stubbed retrieval and a scripted
gateway -- no network -- and compares the response and the rows with
``tests/snapshots/sandbox_turn.json``.

Two scenarios: a prompt-only rehearsal, and one with tools on for two turns so
the cursor resumes and the tool trace is pinned.

Regenerate deliberately, never to make a red run green:

    UPDATE_SNAPSHOTS=1 pytest tests/test_sandbox_turn_snapshot.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "sandbox_turn.json"
BOT_ID = "kaia-v2-4"
OPENING = "Hello, this is Kaia from the bank about your account."
TURNS = (
    "hi, how much do i owe this month and when is it due?",
    "i can pay half now and the rest next week",
)
VOLATILE = {
    "latencyMs",
    "retrieveLatencyMs",
    "chatLatencyMs",
    "retrievalLogId",
    "compiledBundleHash",
}


def _chunk(n: int) -> dict[str, Any]:
    return {
        "chunkId": f"kbc-{n}",
        "docId": f"doc-{n}",
        "docTitle": f"Policy {n}",
        "heading": "Dues",
        "snippet": f"snippet {n}",
        "score": 0.9 - n / 10,
    }


class _Gateway:
    """Retrieval and the model, scripted: one note-taking tool call when it is
    offered, then a reply."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def retrieve(self, **_kwargs: Any) -> dict[str, Any]:
        return {"results": [_chunk(1), _chunk(2)], "latencyMs": 11, "logId": None}

    def chat_complete_detailed(self, messages, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append({"roles": [m.get("role") for m in messages], "offered": None})
        return {
            "content": "Your dues this month are 4,200 rupees.",
            "latencyMs": 22,
            "totalTokens": 33,
        }

    def chat_with_tools(self, messages, *, tools, temperature, max_completion_tokens):
        offered = sorted((t.get("function") or {}).get("name") or "?" for t in tools)
        self.calls.append(
            {"roles": [m.get("role") for m in messages], "offered": offered}
        )
        n = sum(1 for c in self.calls if c["offered"] is not None)
        if n == 1 and "add_customer_note" in offered:
            return {
                "content": None,
                "latencyMs": 22,
                "totalTokens": 40,
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
            "content": "Noted. Your dues this month are 4,200 rupees.",
            "latencyMs": 22,
            "totalTokens": 33,
        }


def _strip(value: Any, aliases: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: _strip(v, aliases) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [_strip(v, aliases) for v in value]
    if isinstance(value, str):
        for real, alias in aliases.items():
            value = value.replace(real, alias)
    return value


def _rows(conn, run_id: str) -> dict[str, Any]:
    turns = [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT turn_index, speaker, text, detected_intent, sentiment_label,"
                "       retrieved_chunk_ids, guardrail_flags, token_count"
                "  FROM sandbox_run_turns WHERE run_id = :r ORDER BY turn_index"
            ),
            {"r": run_id},
        ).mappings()
    ]
    run = (
        conn.execute(
            text("SELECT status, aggregate_tokens FROM sandbox_runs WHERE id = :r"),
            {"r": run_id},
        )
        .mappings()
        .first()
    )
    return {"turns": turns, "run": dict(run)}


def render(monkeypatch: pytest.MonkeyPatch, conn) -> dict[str, Any]:
    import azure_openai
    import db
    import kb_retrieve
    import sandbox_runtime

    published = db.get_published_prompt_version(BOT_ID)
    if published is None:
        pytest.skip(f"{BOT_ID} has no published version on this stack")
    monkeypatch.setenv("UNDERSTANDING_LLM_ENABLED", "0")
    monkeypatch.delenv("SANDBOX_TEXT_TOOLS", raising=False)
    out: dict[str, Any] = {}
    for name, enable_tools, turns in (
        ("prompt_only", False, TURNS[:1]),
        ("tools", True, TURNS),
    ):
        gateway = _Gateway()
        monkeypatch.setattr(kb_retrieve, "retrieve", gateway.retrieve)
        monkeypatch.setattr(
            azure_openai, "chat_complete_detailed", gateway.chat_complete_detailed
        )
        monkeypatch.setattr(azure_openai, "chat_with_tools", gateway.chat_with_tools)
        run = sandbox_runtime.create_sandbox_run(
            {"promptVersionId": published["id"], "openingTemplate": OPENING}
        )
        aliases = {run["id"]: "<run>", published["id"]: "<version>"}
        results = [
            _strip(
                sandbox_runtime.append_sandbox_turn(
                    run["id"], {"text": t, "enableTools": enable_tools}
                ),
                aliases,
            )
            for t in turns
        ]
        out[name] = {
            "gateway": gateway.calls,
            "results": results,
            **_rows(conn, run["id"]),
        }
    return out


def test_one_sandbox_turn_matches_the_snapshot(
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
        "the rehearsed turn returned or wrote something else -- if the change is "
        "intended, regenerate with UPDATE_SNAPSHOTS=1 and review the diff"
    )
