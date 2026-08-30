"""A latency budget for everything in a sandbox turn that is not a model call.

Rehearsal cycles 18-21 measured 3.0s / 6.6s / 7.98s / 8.0s / 10.8s / 12.3s per
turn on the *same* card and the *same* scenario. Nothing in the schema could
say where those seconds went: ``sandbox_run_turns`` stores a single
``latency_ms`` that is ``chat + retrieve``, both self-reported by the callee,
so the sandbox's own work — four preflight queries, prompt assembly,
guardrails, the persist transaction — was invisible, and so was the *second*
model call the turn makes.

``append_sandbox_turn`` now emits a per-stage breakdown at INFO under the
``turn-stage-timings:`` prefix (no migration: ``sandbox_run_turns`` has no
jsonb column to hang a breakdown off, and a diagnostic does not justify one).
A real instrumented run against this database, understanding enrichment on,
five turns, medians:

    total 3698ms · retrieval 501ms (max 5804) · understanding 1151ms
    · llm 1709ms · preflight 116ms · persist 34ms · unattributed 1415ms

``unattributed_ms`` is the gap between what the turn cost and what
``latency_ms`` records — about 1.4 seconds a turn, most of it the
``analyze_turn`` enrichment call inside :func:`assemble_turn_messages`, which
no telemetry named. The variance is retrieval: 350ms at the median, 5.8s at the
worst of five turns, all embedding round trip.

These tests hold the *non*-model half to a budget. Both Azure calls are
stubbed and enrichment is off, so what is measured is retrieval SQL, assembly,
guardrails and persist against the real database — the part a code change can
regress, and the part that must not quietly grow while the seconds above are
being chased.
"""

from __future__ import annotations

import json
import logging
import statistics
from typing import Any

import pytest
from sqlalchemy import text as sa_text

import sandbox_runtime
from sandbox_runtime import _STAGE_TIMING_LOG_PREFIX

# Turns measured. Five is enough for a median that is not one sample, and short
# enough that the test stays around a second.
TURNS = 5

#: Per-turn ceiling on everything except the two model calls.
#:
#: Calibrated, not guessed. Five stubbed turns against this database measured a
#: median ``non_llm_ms`` of 216ms (min 187, max 513 — the max is the first turn,
#: which pays connection and query-plan warm-up). Three times the median is
#: 648ms, which sits below that observed first-turn cost and would flake on any
#: box slower than this one, so the budget is set at the wider figure: ~7x the
#: median and ~3x the worst observed turn. It is still a twentieth of the 8-12s
#: turns the rehearsal saw, so it fails on a real regression and not on noise.
NON_LLM_BUDGET_MS = 1500.0

_STUB_CHAT_MS = 1200

_GREETING = (
    "Hello, this is Priya from HDFC Bank Collections. This call is recorded "
    "for quality."
)
_UTTERANCES = [
    "I cannot pay the full amount this month.",
    "Can you tell me what my outstanding balance is?",
    "What happens if I pay only half of it?",
    "I get my salary on the fifth of next month.",
    "Please send me the details in writing.",
]

_STAGE_KEYS = (
    "total_ms",
    "preflight_db_ms",
    "retrieval_ms",
    "prompt_prep_ms",
    "understanding_ms",
    "llm_ms",
    "guardrails_ms",
    "persist_ms",
    "non_llm_ms",
)


def _table_missing(conn, name: str) -> bool:
    row = (
        conn.execute(sa_text("SELECT to_regclass(:n) AS t"), {"n": f"public.{name}"})
        .mappings()
        .first()
    )
    return not row or not row["t"]


@pytest.fixture()
def sandbox_ready(db_tx, monkeypatch: pytest.MonkeyPatch) -> str:
    """A prompt version to rehearse against, or a clean skip.

    Gated the way the other DB-backed suites gate themselves (``test_phase4``,
    ``test_skills_catalog``): probe for the table, skip with the reason rather
    than fail, so an environment without the sandbox migrations still reports
    green instead of red-for-the-wrong-reason.
    """
    for table in ("sandbox_runs", "sandbox_run_turns", "prompt_versions"):
        if _table_missing(db_tx, table):
            pytest.skip(f"{table} missing — sandbox tables not migrated here")

    row = (
        db_tx.execute(
            sa_text(
                """
                SELECT id FROM prompt_versions
                WHERE status = 'published'
                  AND guardrails->>'alwaysDiscloseRecording' = 'true'
                ORDER BY id LIMIT 1
                """
            )
        )
        .mappings()
        .first()
    )
    if not row:
        pytest.skip("no published prompt version in this database")

    # The hard turn cap is 3; these tests want five turns on one run so the
    # aggregate assertion has something to add up. The cap is not under test.
    monkeypatch.setattr(sandbox_runtime, "_HARD_MAX_TURNS", TURNS + 3)
    return str(row["id"])


@pytest.fixture()
def stub_llm(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Remove the network, keep the database.

    Three things reach Azure on this path and all three are closed off: the
    reply (``chat_complete_detailed``), the query embedding inside
    ``kb_retrieve.retrieve`` (``embed_texts``), and the intent/sentiment
    enrichment inside ``assemble_turn_messages`` (switched off at its flag
    rather than stubbed, because that is the switch production has).

    ``kb_retrieve.retrieve`` itself is *not* stubbed — the pgvector query runs
    for real against real chunks, because retrieval is the stage whose variance
    this suite exists to catch.
    """
    import azure_openai

    monkeypatch.setenv("UNDERSTANDING_LLM_ENABLED", "false")
    state: dict[str, Any] = {"chats": 0}

    def _embed(texts: list[str], **_kwargs: Any) -> list[list[float]]:
        # Deterministic vector of the deployment's width (1536).
        return [[0.01] * 1536 for _ in texts]

    def _chat(_messages: Any, **_kwargs: Any) -> dict[str, Any]:
        state["chats"] += 1
        return {
            "content": (
                "I understand. This call is recorded for quality. Let me check "
                "your account and see what we can arrange."
            ),
            "latencyMs": _STUB_CHAT_MS,
            "promptTokens": 400,
            "completionTokens": 40,
            "totalTokens": 440,
            "model": "stub",
        }

    monkeypatch.setattr(azure_openai, "embed_texts", _embed)
    monkeypatch.setattr(azure_openai, "chat_complete_detailed", _chat)
    return state


def _stage_rows(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    """Every ``turn-stage-timings:`` line emitted so far, parsed."""
    out: list[dict[str, Any]] = []
    for record in caplog.records:
        message = record.getMessage()
        if _STAGE_TIMING_LOG_PREFIX not in message:
            continue
        out.append(json.loads(message.split(_STAGE_TIMING_LOG_PREFIX, 1)[1].strip()))
    return out


def _report(rows: list[dict[str, Any]]) -> str:
    """The measured breakdown, so a failure says which stage moved."""
    header = "  turn " + " ".join(k.replace("_ms", "").rjust(11) for k in _STAGE_KEYS)
    lines = ["measured stage breakdown (ms), one line per turn:", header]
    for r in rows:
        lines.append(
            f"  {r['turn_index']:>4} "
            + " ".join(f"{float(r[k]):11.1f}" for k in _STAGE_KEYS)
        )
    non_llm = [r["non_llm_ms"] for r in rows]
    lines.append(
        f"  median non_llm_ms={statistics.median(non_llm):.1f} "
        f"max={max(non_llm):.1f} budget={NON_LLM_BUDGET_MS:.0f}"
    )
    return "\n".join(lines)


@pytest.fixture()
def rehearsal(
    sandbox_ready: str, stub_llm, caplog: pytest.LogCaptureFixture
) -> dict[str, Any]:
    """One run, ``TURNS`` customer turns, with the stage log captured."""
    with caplog.at_level(logging.INFO, logger="sandbox_runtime"):
        run = sandbox_runtime.create_sandbox_run(
            {"promptVersionId": sandbox_ready, "openingTemplate": _GREETING}
        )
        results = [
            sandbox_runtime.append_sandbox_turn(run["id"], {"text": _UTTERANCES[i]})
            for i in range(TURNS)
        ]
        stages = _stage_rows(caplog)
    return {"run": run, "results": results, "stages": stages}


# ---------------------------------------------------------------------------
# The breakdown exists and adds up
# ---------------------------------------------------------------------------


def test_every_turn_logs_a_stage_breakdown(rehearsal) -> None:
    """One greppable line per turn — the only place the split lives."""
    stages = rehearsal["stages"]

    assert len(stages) == TURNS, _report(stages)
    for row in stages:
        assert set(row) >= set(_STAGE_KEYS), sorted(row)


def test_the_stages_account_for_the_turn(rehearsal) -> None:
    """The parts may not exceed the whole — a mismarked clock shows up here."""
    for row in rehearsal["stages"]:
        parts = (
            row["preflight_db_ms"]
            + row["retrieval_ms"]
            + row["prompt_prep_ms"]
            + row["understanding_ms"]
            + row["llm_ms"]
            + row["persist_ms"]
        )
        # Guardrails run between the model and persist marks and are inside
        # total, so parts <= total, with slack for the unmarked gaps.
        assert parts <= row["total_ms"] + 1.0, row


def test_non_llm_excludes_only_what_the_model_actually_took(rehearsal) -> None:
    """With enrichment off, its stage is local CPU and stays inside the budget.

    Pinned because the subtraction is conditional: were ``non_llm_ms`` to start
    discounting ``understanding_ms`` unconditionally, a regression that made
    prompt assembly slow would stop being visible here.
    """
    for row in rehearsal["stages"]:
        assert row["understanding_llm_enabled"] is False, row
        assert row["non_llm_ms"] == pytest.approx(
            row["total_ms"] - row["llm_ms"], abs=0.05
        ), row


# ---------------------------------------------------------------------------
# The budget
# ---------------------------------------------------------------------------


def test_non_llm_turn_overhead_stays_within_budget(rehearsal) -> None:
    """Retrieval + assembly + guardrails + persist, per turn, with no model.

    The regression guard. A per-turn query added to the preflight, an N+1 over
    history, a synchronous write bolted into the persist transaction — each
    moves this number, and the failure prints the stage that moved it.
    """
    stages = rehearsal["stages"]
    assert stages, "no turn-stage-timings lines were logged"

    over = [r for r in stages if r["non_llm_ms"] > NON_LLM_BUDGET_MS]
    assert not over, (
        f"{len(over)} of {len(stages)} turns exceeded the "
        f"{NON_LLM_BUDGET_MS:.0f}ms non-LLM budget\n" + _report(stages)
    )


def test_the_budget_measures_the_sandbox_and_not_the_model(rehearsal) -> None:
    """The stub self-reports 1200ms of chat; none of it may land in the budget.

    Without this, changing the stub's ``latencyMs`` would silently change what
    the budget asserts on — the test would still pass and would be measuring
    something else.
    """
    for row in rehearsal["stages"]:
        assert row["reported_chat_ms"] == _STUB_CHAT_MS, row
        assert row["non_llm_ms"] < _STUB_CHAT_MS, _report(rehearsal["stages"])


# ---------------------------------------------------------------------------
# Integrity: the run's aggregate is the sum of its turns
# ---------------------------------------------------------------------------


def test_aggregate_latency_equals_the_sum_of_turn_latencies(rehearsal, db_tx) -> None:
    """``sandbox_runs.aggregate_latency_ms`` is derived, so it must stay derived.

    It is incremented per turn under the run row lock. A turn that fails to add
    its latency, or adds it twice, makes every rehearsal comparison downstream
    wrong — and nothing else in the suite reads it back. Turn 0 is the opening
    greeting, which is written by ``create_sandbox_run`` and contributes to
    neither aggregate.
    """
    run_id = rehearsal["run"]["id"]

    aggregate = (
        db_tx.execute(
            sa_text(
                """
                SELECT COALESCE(aggregate_latency_ms, 0) AS latency,
                       COALESCE(aggregate_tokens, 0) AS tokens
                FROM sandbox_runs WHERE id = :id
                """
            ),
            {"id": run_id},
        )
        .mappings()
        .first()
    )
    turn_sum = (
        db_tx.execute(
            sa_text(
                """
                SELECT COALESCE(SUM(latency_ms), 0) AS latency,
                       COALESCE(SUM(token_count), 0) AS tokens
                FROM sandbox_run_turns
                WHERE run_id = :id AND speaker = 'bot' AND turn_index > 0
                """
            ),
            {"id": run_id},
        )
        .mappings()
        .first()
    )

    assert int(turn_sum["latency"]) > 0, "no bot turn recorded a latency"
    assert int(aggregate["latency"]) == int(turn_sum["latency"])
    assert int(aggregate["tokens"]) == int(turn_sum["tokens"])


def test_each_turn_latency_is_chat_plus_retrieve(rehearsal) -> None:
    """The persisted ``latency_ms`` is the two self-reported halves, nothing else.

    Pinned because the budget above is defined as *total minus the model*: if
    the persisted number quietly started including sandbox overhead, the two
    would double-count and the budget would be measuring the wrong thing while
    still passing.
    """
    for result in rehearsal["results"]:
        bot = result["botTurn"]
        assert bot["latencyMs"] == bot["chatLatencyMs"] + bot["retrieveLatencyMs"]
        assert bot["chatLatencyMs"] == _STUB_CHAT_MS
