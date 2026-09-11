"""Agent Studio MINOR cluster 10: the eval pipeline says what happened."""

from __future__ import annotations

from agent_core.eval import graders
from agent_core.eval.harness import run_suite_fixtures


def test_a_grader_that_raises_is_an_errored_trial_not_an_aborted_run(monkeypatch) -> None:
    """EVALS-6: one exception lost the whole report and never wrote `error`."""

    def _boom(name, fixture):
        if name == "explodes":
            raise RuntimeError("fixture missing key")
        return {"grader": name, "passed": True}

    monkeypatch.setattr("agent_core.eval.harness.run_grader", _boom)
    result = run_suite_fixtures(
        [
            {"id": "t1", "name": "ok", "grader": "fine", "fixture": {"a": 1}},
            {"id": "t2", "name": "bad", "grader": "explodes", "fixture": {}},
        ]
    )
    assert result["status"] == "error"
    assert result["errored"] == 1 and result["failed"] == 1 and result["total"] == 2
    bad = next(t for t in result["trials"] if t["taskId"] == "t2")
    assert bad["error"].startswith("RuntimeError")
    assert result["trials"][0]["fixture"] == {"a": 1}


def test_debt_words_match_whole_words_only() -> None:
    """EVALS-9: "emi" inside "reminder" graded a compliant voicemail as a leak."""
    assert graders._debt_words_in("this is a reminder to call us back") == []
    assert graders._debt_words_in("accountability matters") == []
    assert graders._debt_words_in("your emi is due") == ["emi", "due"]


def test_the_scheduler_runs_the_outbound_suite() -> None:
    """EVALS-8: the suite G-OB9 gates on was never scheduled."""
    import inspect

    from agent_core.eval import schedule

    assert '"outbound"' in inspect.getsource(schedule.run_continuous)


def test_a_critique_is_filed_against_the_pack_that_owns_the_grader() -> None:
    """EVALS-11: every critique named ptp-negotiate."""
    from agent_core.eval.critique import _LINES, _PACK_FOR_GRADER

    assert set(_LINES) == set(_PACK_FOR_GRADER)
    assert _PACK_FOR_GRADER["hardship_hold"] == "hardship-intake"
