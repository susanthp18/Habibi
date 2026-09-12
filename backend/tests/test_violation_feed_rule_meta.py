"""The Compliance Risk feed names the rule it hit.

The browser used to carry its own catalogue of the sixteen rules and look each
violation's ``ruleId`` up in it; a row filed under a legacy disclosure rule
(``rule-recording``) had no entry there and rendered as nothing. The feed now
carries ``ruleCode`` and ``ruleLabel`` resolved from the catalogue row the
alias points at, so the screen has nothing to look up.
"""

from __future__ import annotations

import db
import db_violations


def test_feed_rows_carry_the_aliased_rule_code_and_label(db_tx) -> None:
    rows = db.list_violations(limit=50)
    assert rows, "the dev DB seeds violations"
    for row in rows:
        assert row["ruleCode"] and row["ruleLabel"]
        assert row["ruleId"] not in db_violations._RULE_ID_SCREEN, "legacy ids are aliased away"
    legacy = [r for r in rows if r["ruleId"] == "r-rec"]
    for r in legacy:
        # both the legacy disclosure row and the catalogue row read as the catalogue row
        assert r["ruleCode"] == "RBI-DISC-01"
