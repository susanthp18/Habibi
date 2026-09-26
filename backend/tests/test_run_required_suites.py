"""The publish dialog's remedy for "regression suite has not been run".

v1.5 of kaia-v2-4 changed only its voice and could not be published: the
nightly runs are filed against no version and no content, so G7/G8 had no
report to read, and nothing on the dialog could file one.
"""

from __future__ import annotations

import pytest


def _draft(db_tx):
    import db

    published = db.get_published_prompt_version("kaia-v2-4")
    if published is None:
        pytest.skip("no published collections prompt")
    return published


def test_running_the_required_suites_opens_the_eval_gates(db_tx, monkeypatch) -> None:
    import db
    from agent_core.eval.run import run_required_suites

    version = _draft(db_tx)
    monkeypatch.setenv("EVAL_GATE_ENABLED", "true")
    monkeypatch.setenv("REDTEAM_GATE_ENABLED", "true")
    out = run_required_suites("kaia-v2-4", version["id"])
    assert {r["kind"] for r in out["ran"]} >= {"regression", "redteam"}, out
    report = db.compile_agent_studio_card("kaia-v2-4", prompt_version_id=version["id"])
    gates = {g["gate"]: g for g in report["gates"]}
    for gate in ("G7", "G8"):
        assert gates[gate]["status"] == "pass", gates[gate]
    assert gates["G-F14"]["status"] == "pass", gates["G-F14"]


def test_a_version_of_another_card_is_refused(db_tx) -> None:
    from agent_core.eval.run import run_required_suites

    version = _draft(db_tx)
    with pytest.raises(ValueError, match="prompt_version_bot_mismatch"):
        run_required_suites("insurance-v1", version["id"])
    with pytest.raises(KeyError):
        run_required_suites("kaia-v2-4", "no-such-version")
