"""Would flipping an eval gate flag block a publish? Ask before, not after.

G7/G8/G-OB9 fail closed on a missing report and count only a report filed
against the exact prompt version being published. Both are correct, and together
they mean one flag flip can make every card in the tenant unpublishable at once
— arriving as a 422 on somebody's publish rather than as a decision anyone took.
"""

from __future__ import annotations

import db
from scripts.eval_gate_preflight import missing_reports


def _forget_kaias_reports(db_tx) -> None:
    """The unsatisfied state, made rather than assumed: the dev stack now
    carries a keyed pass per required kind (WS6), and the preflight is the
    reason it may."""
    from sqlalchemy import text

    db_tx.execute(
        text("DELETE FROM eval_trials WHERE report_id IN (SELECT id FROM eval_reports WHERE bot_id = 'kaia-v2-4')")
    )
    db_tx.execute(text("DELETE FROM eval_reports WHERE bot_id = 'kaia-v2-4'"))


def test_a_card_with_no_report_for_its_content_is_listed(db_tx) -> None:
    """Every requirement without a report for the published content names
    the gate that would refuse, so the reader knows what to run."""
    _forget_kaias_reports(db_tx)
    rows = missing_reports()
    bots = {r["bot"] for r in rows}
    assert "kaia-v2-4" in bots
    assert {r["gate"] for r in rows} <= {"G7", "G8", "G-OB9", "G0"}


def test_a_scoped_passing_report_clears_that_requirement(db_tx) -> None:
    """The positive direction, so the check cannot pass by always complaining.

    Deliberately files the report against the published version rather than
    stamping an existing row: a report's provenance is the thing these gates
    read, and back-dating one would fabricate exactly what they check.
    """
    _forget_kaias_reports(db_tx)
    before = [r for r in missing_reports() if r["bot"] == "kaia-v2-4" and r["require"] == "regression"]
    assert before, "precondition: kaia-v2-4 regression is unsatisfied"

    published = db.get_published_prompt_version("kaia-v2-4")
    assert published is not None
    from agent_core.eval.provenance import content_key_for_version

    db.save_eval_report(
        suite_id="eval-regression-collections",
        bot_id="kaia-v2-4",
        status="pass",
        summary={"failed": 0, "total": 1},
        prompt_version_id=published["id"],
        content_key=content_key_for_version(published),
    )

    after = [r for r in missing_reports() if r["bot"] == "kaia-v2-4" and r["require"] == "regression"]
    assert after == []
    # And it cleared only that one — redteam is still outstanding.
    assert any(r["bot"] == "kaia-v2-4" and r["require"] == "redteam" for r in missing_reports())
