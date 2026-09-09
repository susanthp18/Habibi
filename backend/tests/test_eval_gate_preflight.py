"""Would flipping an eval gate flag block a publish? Ask before, not after.

G7/G8/G-OB9 fail closed on a missing report and count only a report filed
against the exact prompt version being published. Both are correct, and together
they mean one flag flip can make every card in the tenant unpublishable at once
— arriving as a 422 on somebody's publish rather than as a decision anyone took.
"""

from __future__ import annotations

import db
from scripts.eval_gate_preflight import missing_reports


def test_todays_database_would_block_every_published_card(db_tx) -> None:
    """Not hypothetical: every `eval_reports` row carries a NULL
    `prompt_version_id`, because nothing supplied one until the plumbing landed.
    """
    rows = missing_reports()
    assert rows, "expected the unscoped-report condition to still be present"
    bots = {r["bot"] for r in rows}
    assert "kaia-v2-4" in bots
    # Every row names the gate that would refuse, so the reader knows what to run.
    assert {r["gate"] for r in rows} <= {"G7", "G8", "G-OB9", "G0"}


def test_a_scoped_passing_report_clears_that_requirement(db_tx) -> None:
    """The positive direction, so the check cannot pass by always complaining.

    Deliberately files the report against the published version rather than
    stamping an existing row: a report's provenance is the thing these gates
    read, and back-dating one would fabricate exactly what they check.
    """
    before = [r for r in missing_reports() if r["bot"] == "kaia-v2-4" and r["require"] == "regression"]
    assert before, "precondition: kaia-v2-4 regression is unsatisfied"

    published = db.get_published_prompt_version("kaia-v2-4")
    assert published is not None
    db.save_eval_report(
        suite_id="eval-regression-collections",
        bot_id="kaia-v2-4",
        status="pass",
        summary={"failed": 0, "total": 1},
        prompt_version_id=published["id"],
    )

    after = [r for r in missing_reports() if r["bot"] == "kaia-v2-4" and r["require"] == "regression"]
    assert after == []
    # And it cleared only that one — redteam is still outstanding.
    assert any(r["bot"] == "kaia-v2-4" and r["require"] == "redteam" for r in missing_reports())
