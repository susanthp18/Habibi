"""The enrichment call must not sit on the reply the customer waits for.

Cycle 22's stage breakdown (see :mod:`tests.test_turn_latency_budget`) named
the second Azure round trip a sandbox turn makes: ``analyze_turn``, 1151ms at
the median, run *between* retrieval and the reply and counted by neither
``chatLatencyMs`` nor ``retrieveLatencyMs``.

It cannot be dropped from the reply path and it cannot be pushed behind the
response: ``intent`` selects the skill body message that goes into the prompt,
feeds ``evaluate_guardrails``, is written to both ``sandbox_run_turns`` rows,
and four fields of the response contract -- ``customerTurn.intent``,
``intentScores``, ``sentiment``, ``sentimentLabel`` -- are read straight off it
by the Inspector. So the fix is overlap, not deferral: the analysis reads the
customer utterance and nothing else the turn produces, so it starts before the
preflight queries and runs underneath them and retrieval, and the turn waits
only for whatever is left of it.

These tests hold that property with the clocks pinned. Both model calls are
stubbed, retrieval is stubbed to the 600ms the rehearsal measured (a real
pgvector query here would vary by an order of magnitude between boxes and the
assertion is about *concurrency*, not about retrieval), and the enrichment is
stubbed to a flat 500ms. What is measured is whether those 500ms land on the
turn or beside it.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import pytest
from sqlalchemy import text as sa_text

import kb_retrieve
import sandbox_runtime
from agent_core.understanding import TurnUnderstanding
from sandbox_runtime import _STAGE_TIMING_LOG_PREFIX

#: The stubbed enrichment call. Below the 1151ms measured, above anything the
#: sandbox's own work costs, so the two are never confusable in a failure.
_ENRICH_MS = 500

#: The stubbed retrieval, at the measured median (501ms) rounded up. This is
#: the work the enrichment gets to hide behind.
_RETRIEVE_MS = 600

#: What "no longer on the path" is allowed to cost: thread hand-off, the
#: contextvar copy, and the residual wait when retrieval finishes first.
_OVERLAP_SLACK_MS = 100.0

#: How much of the enrichment must come off the path before the flag is doing
#: anything. Deliberately short of the full 500ms -- the claim under test is
#: "not on the critical path", not "free".
_MIN_SAVING_MS = 400.0

_GREETING = (
    "Hello, this is Priya from HDFC Bank Collections. This call is recorded "
    "for quality."
)
_UTTERANCE = "I cannot pay the full amount this month."

#: Distinctive enough that finding it in the response or the database proves it
#: came from the stubbed *enrichment* and not from the keyword classifiers.
_STUB_INTENT = "hardship_claim"
_STUB_SENTIMENT_LABEL = "negative"


def _table_missing(conn, name: str) -> bool:
    row = (
        conn.execute(sa_text("SELECT to_regclass(:n) AS t"), {"n": f"public.{name}"})
        .mappings()
        .first()
    )
    return not row or not row["t"]


@pytest.fixture()
def sandbox_ready(db_tx, monkeypatch: pytest.MonkeyPatch) -> str:
    """A published prompt version to rehearse against, or a clean skip."""
    for table in ("sandbox_runs", "sandbox_run_turns", "prompt_versions"):
        if _table_missing(db_tx, table):
            pytest.skip(f"{table} missing - sandbox tables not migrated here")

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

    # Four turns on one run: a warm-up plus the three configurations compared
    # below. The cap is not under test.
    monkeypatch.setattr(sandbox_runtime, "_HARD_MAX_TURNS", 8)
    return str(row["id"])


@pytest.fixture()
def stubs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Every network call replaced by a clock, and the clocks counted.

    The enrichment stub honours the same two gates the real ``analyze_turn``
    honours -- ``UNDERSTANDING_LLM_ENABLED`` and ``allow_llm`` -- because that
    is what makes "enrichment disabled" a fair baseline: with the flag off the
    real call is local CPU, so the stub must not sleep either.
    """
    import agent_core.turn as turn_module
    import agent_core.understanding as understanding
    import azure_openai

    state: dict[str, Any] = {"analyses": 0, "slept": 0, "chats": 0}

    def _analyze(text: str, **kwargs: Any) -> TurnUnderstanding:
        state["analyses"] += 1
        if kwargs.get("allow_llm", True) and understanding.llm_enabled():
            state["slept"] += 1
            time.sleep(_ENRICH_MS / 1000.0)
            return TurnUnderstanding(
                intent=_STUB_INTENT,
                intent_scores={_STUB_INTENT: 0.91},
                sentiment=-0.6,
                sentiment_label=_STUB_SENTIMENT_LABEL,
                source="llm",
                latency_ms=_ENRICH_MS,
            )
        return understanding.keyword_understanding(text)

    def _retrieve(**_kwargs: Any) -> dict[str, Any]:
        time.sleep(_RETRIEVE_MS / 1000.0)
        return {"results": [], "latencyMs": _RETRIEVE_MS, "logId": None}

    def _chat(_messages: Any, **_kwargs: Any) -> dict[str, Any]:
        state["chats"] += 1
        return {
            "content": "I understand. Let me see what we can arrange for you.",
            "latencyMs": 0,
            "promptTokens": 100,
            "completionTokens": 20,
            "totalTokens": 120,
            "model": "stub",
        }

    # Patched in both namespaces: the prefetch imports it from
    # agent_core.understanding at call time, the inline path resolves it as a
    # module global of agent_core.turn.
    monkeypatch.setattr(understanding, "analyze_turn", _analyze)
    monkeypatch.setattr(turn_module, "analyze_turn", _analyze)
    monkeypatch.setattr(kb_retrieve, "retrieve", _retrieve)
    monkeypatch.setattr(azure_openai, "chat_complete_detailed", _chat)
    return state


def _stage_rows(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in caplog.records:
        message = record.getMessage()
        if _STAGE_TIMING_LOG_PREFIX not in message:
            continue
        out.append(json.loads(message.split(_STAGE_TIMING_LOG_PREFIX, 1)[1].strip()))
    return out


def _configure(
    monkeypatch: pytest.MonkeyPatch, *, enrichment: bool, overlap: bool
) -> None:
    monkeypatch.setenv("UNDERSTANDING_LLM_ENABLED", "true" if enrichment else "false")
    monkeypatch.setenv("SANDBOX_ENRICHMENT_ASYNC", "1" if overlap else "0")


#: The rehearsal is measured once for the whole module.
#:
#: It costs four real turns with two stubbed sleeps in them, and every
#: assertion below reads the same three numbers -- re-running it per test would
#: multiply a second-scale cost by six to re-derive an identical result. The
#: database rows are snapshotted inside the fixture for the same reason: they
#: only exist inside the ``db_tx`` transaction of the test that wrote them.
_MEASURED: dict[str, Any] | None = None


@pytest.fixture()
def measured(
    sandbox_ready: str,
    stubs: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    db_tx,
) -> dict[str, Any]:
    """One run, four turns: warm-up, then the three configurations compared.

    Same run, same utterance, same stubs -- the only variable between the three
    measured turns is the two environment flags, so the wall-clock difference
    between them is the flag and nothing else. The warm-up turn is discarded:
    it pays connection set-up and query planning, which would otherwise be
    charged to whichever configuration happened to go first.
    """
    global _MEASURED
    if _MEASURED is not None:
        return _MEASURED

    with caplog.at_level(logging.INFO, logger="sandbox_runtime"):
        _configure(monkeypatch, enrichment=False, overlap=False)
        run = sandbox_runtime.create_sandbox_run(
            {"promptVersionId": sandbox_ready, "openingTemplate": _GREETING}
        )
        sandbox_runtime.append_sandbox_turn(run["id"], {"text": _UTTERANCE})

        out: dict[str, Any] = {"run": run}
        for label, enrichment, overlap in (
            ("off", False, False),
            ("async", True, True),
            ("inline", True, False),
        ):
            _configure(monkeypatch, enrichment=enrichment, overlap=overlap)
            before = stubs["analyses"]
            started = time.perf_counter()
            result = sandbox_runtime.append_sandbox_turn(run["id"], {"text": _UTTERANCE})
            out[label] = {
                "total_ms": (time.perf_counter() - started) * 1000.0,
                "result": result,
                "analyses": stubs["analyses"] - before,
            }
        rows = _stage_rows(caplog)

    # One stage line per turn, warm-up first; attach each measured turn's line.
    assert len(rows) == 4, rows
    for label, row in zip(("off", "async", "inline"), rows[1:]):
        out[label]["stage"] = row
        out[label]["persisted"] = {
            turn_id: dict(
                db_tx.execute(
                    sa_text(
                        """
                        SELECT detected_intent, sentiment_label
                        FROM sandbox_run_turns WHERE id = :id
                        """
                    ),
                    {"id": turn_id},
                )
                .mappings()
                .first()
                or {}
            )
            for turn_id in (
                out[label]["result"]["customerTurn"]["id"],
                out[label]["result"]["botTurn"]["id"],
            )
        }
    _MEASURED = out
    return out


def _report(measured: dict[str, Any]) -> str:
    lines = [
        f"enrichment stub {_ENRICH_MS}ms - retrieval stub {_RETRIEVE_MS}ms",
        "  config       total_ms  understanding_ms  enrichment_wall_ms  saved_ms",
    ]
    for label in ("off", "async", "inline"):
        m = measured[label]
        s = m["stage"]
        lines.append(
            f"  {label:<10} {m['total_ms']:9.1f} {s['understanding_ms']:17.1f} "
            f"{s['enrichment_wall_ms']:19.1f} {s['enrichment_saved_ms']:9.1f}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The reply no longer waits on the enrichment
# ---------------------------------------------------------------------------


def test_overlapped_enrichment_does_not_lengthen_the_turn(measured) -> None:
    """Flag ON: a 500ms enrichment must add ~nothing to the customer's wait.

    Measured against the same turn with enrichment switched off entirely, which
    is the floor -- it is the turn with no analysis call in it at all.
    """
    baseline = measured["off"]["total_ms"]
    overlapped = measured["async"]["total_ms"]
    assert overlapped <= baseline + _OVERLAP_SLACK_MS, (
        f"overlapped turn cost {overlapped:.1f}ms against a {baseline:.1f}ms "
        f"floor - more than the {_OVERLAP_SLACK_MS:.0f}ms allowed\n"
        + _report(measured)
    )


def test_the_flag_off_keeps_todays_behaviour(measured) -> None:
    """Flag OFF: the call is inline and the turn pays for all of it.

    The revert path has to be a real revert. If this stops failing to overlap,
    the flag is not switching anything and the test above proves nothing.
    """
    baseline = measured["off"]["total_ms"]
    inline = measured["inline"]["total_ms"]
    assert inline >= baseline + _MIN_SAVING_MS, (
        f"inline turn cost {inline:.1f}ms against a {baseline:.1f}ms floor - "
        f"the {_ENRICH_MS}ms enrichment did not land on the turn\n"
        + _report(measured)
    )
    assert measured["inline"]["stage"]["enrichment_async"] is False
    assert measured["inline"]["stage"]["enrichment_saved_ms"] == 0.0
    # Inline, the whole call is inside the understanding stage -- the shape the
    # cycle 22 breakdown reported.
    assert measured["inline"]["stage"]["understanding_ms"] >= _MIN_SAVING_MS, _report(
        measured
    )


def test_the_saving_is_reported_per_turn(measured) -> None:
    """The stage line carries what came off the path, under the same prefix.

    Cycle 22 could only name the cost because one greppable line per turn
    carried it; the fix is only auditable in production on the same terms.
    """
    stage = measured["async"]["stage"]
    assert stage["enrichment_async"] is True, _report(measured)
    assert stage["enrichment_wall_ms"] >= _MIN_SAVING_MS, _report(measured)
    assert stage["enrichment_saved_ms"] >= _MIN_SAVING_MS, _report(measured)
    # The wait that remains is the residual, not the call.
    assert stage["understanding_ms"] <= _OVERLAP_SLACK_MS, _report(measured)


# ---------------------------------------------------------------------------
# ...and the data still lands
# ---------------------------------------------------------------------------


def test_the_enrichment_result_still_reaches_the_response(measured) -> None:
    """Overlap, not deferral: the contract fields are enriched on this turn.

    The four fields the Inspector reads come off the analysis, so an overlap
    that returned before the analysis landed would degrade them to the keyword
    classifiers silently.
    """
    for label in ("async", "inline"):
        result = measured[label]["result"]
        customer = result["customerTurn"]
        bot = result["botTurn"]
        assert customer["intent"] == _STUB_INTENT, label
        assert customer["intentScores"] == {_STUB_INTENT: 0.91}, label
        assert customer["sentiment"] == pytest.approx(-0.6), label
        assert customer["sentimentLabel"] == _STUB_SENTIMENT_LABEL, label
        assert bot["intent"] == _STUB_INTENT, label
        assert bot["sentimentLabel"] == _STUB_SENTIMENT_LABEL, label


def test_the_enrichment_result_still_reaches_the_database(measured) -> None:
    """Both persisted rows carry the enriched intent, overlapped or not.

    Read back from ``sandbox_run_turns`` inside the writing transaction, not
    from the response dict, because the response could carry an intent the
    insert never saw.
    """
    for label in ("async", "inline"):
        persisted = measured[label]["persisted"]
        assert len(persisted) == 2, (label, persisted)
        for turn_id, row in persisted.items():
            assert row, f"{label}: {turn_id} not persisted"
            assert row["detected_intent"] == _STUB_INTENT, (label, turn_id)
            assert row["sentiment_label"] == _STUB_SENTIMENT_LABEL, (label, turn_id)


def test_the_overlap_does_not_analyse_the_turn_twice(measured) -> None:
    """One analysis per turn in both modes.

    The failure this pins is the obvious one: prefetching the analysis and then
    letting ``assemble_turn_messages`` make its own call anyway would keep every
    assertion above green while doubling the Azure spend.
    """
    for label in ("off", "async", "inline"):
        assert measured[label]["analyses"] == 1, (label, _report(measured))
