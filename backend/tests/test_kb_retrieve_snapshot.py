"""What ``kb_retrieve.retrieve`` returns and logs, pinned before it is taken apart.

``retrieve`` is one 640-line function: the rate check, the cache, the query
embedding, the scope and topic derivation, the ANN queries, scoring, the
optional rerank, the draft answer, the gap check and the log row. Splitting it
into phases must not change what ranks, what is returned or what is written.
This runs the *real* function against the dev knowledge base with a fixed
query vector and a scripted chat -- no network -- and compares the payload and
the ``retrieval_logs`` row with ``tests/snapshots/kb_retrieve.json``.

Three scenarios: snippets only, snippets with a draft answer, and an
exclusions topic with a product scope.

Regenerate deliberately, never to make a red run green:

    UPDATE_SNAPSHOTS=1 pytest tests/test_kb_retrieve_snapshot.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "kb_retrieve.json"
VOLATILE = {"latencyMs", "logId", "embeddingModel"}
SCENARIOS = {
    "snippets": {
        "query": "what happens if i miss an emi payment",
        "include_draft_answer": False,
    },
    "draft": {
        "query": "how do i pay my dues online",
        "include_draft_answer": True,
        "source": "inbox",
    },
    "exclusions": {
        "query": "does travel protect360 cover a cancelled flight",
        "include_draft_answer": False,
        "topic": "exclusions",
        "source": "bot",
    },
}


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in VOLATILE:
                continue
            # Stage clocks: which stages ran, never how long they took.
            out[k] = sorted(v) if k == "stageMs" else _strip(v)
        return out
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def render(monkeypatch: pytest.MonkeyPatch, conn) -> dict[str, Any]:
    import azure_openai
    import kb_retrieve

    monkeypatch.setenv("KB_RESULT_CACHE_TTL_S", "0")
    monkeypatch.setenv("KB_RERANK_ENABLED", "0")
    monkeypatch.setenv("KB_GAP_CAPTURE_ENABLED", "0")
    monkeypatch.setattr(
        azure_openai, "embed_texts", lambda texts, **_k: [[0.01] * 1536 for _ in texts]
    )
    monkeypatch.setattr(
        azure_openai,
        "chat_complete_detailed",
        lambda _m, **_k: {
            "content": "You can pay through the app or net banking.",
            "latencyMs": 5,
            "model": "stub",
        },
    )
    monkeypatch.setattr(kb_retrieve, "_log_buffering_enabled", lambda: False)
    if (
        conn.execute(
            text("SELECT count(*) FROM kb_chunks WHERE embedding IS NOT NULL")
        ).scalar()
        == 0
    ):
        pytest.skip("no embedded chunks on this stack")
    out: dict[str, Any] = {}
    for name, kwargs in SCENARIOS.items():
        payload = kb_retrieve.retrieve(**kwargs)
        row = (
            conn.execute(
                text(
                    "SELECT query, top_chunks, selected_answer_source, interaction_id, sandbox_run_id"
                    "  FROM retrieval_logs WHERE id = :id"
                ),
                {"id": payload["logId"]},
            )
            .mappings()
            .first()
        )
        out[name] = {"payload": _strip(payload), "log": dict(row) if row else None}
    return out


def test_retrieve_matches_the_snapshot(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
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
        "retrieval ranked, returned or logged something else -- if the change is "
        "intended, regenerate with UPDATE_SNAPSHOTS=1 and review the diff"
    )
