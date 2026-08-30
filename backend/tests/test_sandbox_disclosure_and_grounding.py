"""Two defects found in Prompt rehearsal on 2026-08-25 (card kaia-v2-4).

Both are telemetry lying about a turn that was actually fine:

* the opening greeting said "This call is recorded for quality" and every
  customer reply after it still carried ``missing-recording-disclosure`` — the
  sandbox never told :func:`evaluate_guardrails` that the disclosure had
  already been made, so a per-turn check asked each turn to repeat it. The live
  voice path threads exactly this fact (``voice/crm_sink.py``); the sandbox did
  not.
* turn 2's footer read "0 chunks" directly under three "grounded in FAQ" chips.
  The counter was built from real ``kb_chunks`` ids only while the chips fell
  back to FAQ hits, so an FAQ-only turn contradicted itself.

The tests below pin the mechanism of each: the disclosure is a fact about the
RUN, and the chips and the counter come from ONE list.
"""

from __future__ import annotations

from typing import Any

import pytest

import sandbox_runtime
from agent_core.guardrails import mentions_recording_disclosure
from sandbox_runtime import _grounding_sources

GREETING_THAT_DISCLOSES = (
    "Hello, this is Priya from HDFC Bank Collections. This call is recorded "
    "for quality."
)
GREETING_THAT_DOES_NOT = "Hello, this is Priya from HDFC Bank Collections."


# ---------------------------------------------------------------------------
# What counts as a disclosure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "This call is recorded for quality.",
        "this call is recorded",
        "This conversation may be recorded for training purposes.",
        "I am recording this call.",
        "All calls are recorded.",
        "Just so you know, recorded for quality and compliance.",
    ],
)
def test_disclosure_wordings_are_recognised(text: str) -> None:
    assert mentions_recording_disclosure(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Let me record your promise to pay for the 5th.",
        "I will record that in the CRM.",
        "Your outstanding is 62,400 rupees.",
    ],
)
def test_a_bare_mention_of_recording_is_not_a_disclosure(text: str) -> None:
    """The check backs a compliance gate — it must stay strict.

    "record your promise to pay" is an internal action, not something said to
    the customer about the call being recorded.
    """
    assert not mentions_recording_disclosure(text)


def test_the_lint_and_the_runtime_share_one_pattern() -> None:
    """Prompt Studio's authoring gate and the turn detector must not drift."""
    import prompt_lint

    assert prompt_lint.mentions_recording_disclosure is mentions_recording_disclosure


# ---------------------------------------------------------------------------
# Grounding sources: chips and counter come from one list
# ---------------------------------------------------------------------------


def _faq(n: int) -> dict[str, Any]:
    return {"chunkId": f"faq-collections-{n}", "docTitle": "FAQ · collections", "snippet": "…"}


def _chunk(n: int) -> dict[str, Any]:
    return {"chunkId": f"kbc-{n}", "docTitle": "Collections Policy", "snippet": "…"}


def test_faq_only_retrieval_still_reports_the_chunks_it_shows() -> None:
    """The bug: three FAQ chips over a footer that said "0 chunks"."""
    results = [_faq(1), _faq(2), _faq(3)]

    grounding = _grounding_sources(results)

    assert [r["chunkId"] for r in grounding] == [
        "faq-collections-1",
        "faq-collections-2",
        "faq-collections-3",
    ]


def test_real_chunks_are_preferred_over_faq_hits() -> None:
    """Unchanged behaviour: when real chunks matched, they are the grounding."""
    grounding = _grounding_sources([_faq(1), _chunk(7), _faq(2)])

    assert [r["chunkId"] for r in grounding] == ["kbc-7"]


def test_grounding_sources_are_de_duped_by_id() -> None:
    grounding = _grounding_sources([_chunk(1), _chunk(1), _chunk(2)])

    assert [r["chunkId"] for r in grounding] == ["kbc-1", "kbc-2"]


def test_results_without_an_id_are_not_grounding() -> None:
    grounding = _grounding_sources([{"docTitle": "Orphan"}, _chunk(3)])

    assert [r["chunkId"] for r in grounding] == ["kbc-3"]


# ---------------------------------------------------------------------------
# Through append_sandbox_turn — the path the studio actually takes
# ---------------------------------------------------------------------------


@pytest.fixture()
def prompt_version_id(db_tx) -> str:
    from sqlalchemy import text as sa_text

    row = (
        db_tx.execute(
            sa_text(
                """
                SELECT id FROM prompt_versions
                WHERE guardrails->>'alwaysDiscloseRecording' = 'true'
                ORDER BY id LIMIT 1
                """
            )
        )
        .mappings()
        .first()
    )
    assert row, "no prompt version with alwaysDiscloseRecording in the test DB"
    return str(row["id"])


@pytest.fixture()
def stub_llm(monkeypatch: pytest.MonkeyPatch):
    """No Azure, no embeddings — the retrieval shape is what is under test."""
    import azure_openai
    import kb_retrieve

    state: dict[str, Any] = {
        "results": [],
        "bot_text": "I can help you with your past due payment.",
    }

    def _retrieve(**_kwargs: Any) -> dict[str, Any]:
        return {"results": list(state["results"]), "latencyMs": 11, "logId": None}

    def _chat(_messages: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"content": state["bot_text"], "latencyMs": 22, "totalTokens": 33}

    monkeypatch.setattr(kb_retrieve, "retrieve", _retrieve)
    monkeypatch.setattr(azure_openai, "chat_complete_detailed", _chat)
    return state


def _run_one_turn(*, prompt_version_id: str, opening: str) -> dict[str, Any]:
    run = sandbox_runtime.create_sandbox_run(
        {"promptVersionId": prompt_version_id, "openingTemplate": opening}
    )
    return sandbox_runtime.append_sandbox_turn(
        run["id"], {"text": "I cannot pay the full amount this month."}
    )


def test_a_disclosing_greeting_clears_the_flag_for_the_rest_of_the_run(
    db_tx, prompt_version_id, stub_llm
) -> None:
    """The reported false positive, end to end."""
    result = _run_one_turn(
        prompt_version_id=prompt_version_id, opening=GREETING_THAT_DISCLOSES
    )

    assert "missing-recording-disclosure" not in result["botTurn"]["guardrailFlags"]


def test_the_flag_still_fires_when_nothing_ever_disclosed(
    db_tx, prompt_version_id, stub_llm
) -> None:
    """The check must not have been softened into never firing."""
    stub_llm["bot_text"] = "Your outstanding is 62,400 rupees and it is past due."

    result = _run_one_turn(
        prompt_version_id=prompt_version_id, opening=GREETING_THAT_DOES_NOT
    )

    assert "missing-recording-disclosure" in result["botTurn"]["guardrailFlags"]


def test_a_wording_variant_in_the_greeting_is_recognised(
    db_tx, prompt_version_id, stub_llm
) -> None:
    result = _run_one_turn(
        prompt_version_id=prompt_version_id,
        opening="Namaste. This call is recorded, and I am Priya from HDFC Bank.",
    )

    assert "missing-recording-disclosure" not in result["botTurn"]["guardrailFlags"]


def test_the_chunk_count_and_the_chips_cannot_diverge(
    db_tx, prompt_version_id, stub_llm
) -> None:
    """The turn card's footer count IS the chip list — one source of truth."""
    stub_llm["results"] = [_faq(1), _faq(2), _faq(3)]

    bot = _run_one_turn(
        prompt_version_id=prompt_version_id, opening=GREETING_THAT_DISCLOSES
    )["botTurn"]

    assert [c["chunkId"] for c in bot["chunks"]] == bot["chunkIds"]
    assert len(bot["chunkIds"]) == 3, bot["chunkIds"]


def test_a_turn_with_real_chunks_reports_those(
    db_tx, prompt_version_id, stub_llm
) -> None:
    stub_llm["results"] = [_chunk(1), _faq(9)]

    bot = _run_one_turn(
        prompt_version_id=prompt_version_id, opening=GREETING_THAT_DISCLOSES
    )["botTurn"]

    assert bot["chunkIds"] == ["kbc-1"]
    assert [c["chunkId"] for c in bot["chunks"]] == ["kbc-1"]


def test_an_ungrounded_turn_reports_nothing_on_either_side(
    db_tx, prompt_version_id, stub_llm
) -> None:
    stub_llm["results"] = []

    bot = _run_one_turn(
        prompt_version_id=prompt_version_id, opening=GREETING_THAT_DISCLOSES
    )["botTurn"]

    assert bot["chunkIds"] == []
    assert bot["chunks"] == []
