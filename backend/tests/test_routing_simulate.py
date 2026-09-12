"""The Routing simulator evaluates on the server, with the live evaluator, and writes nothing."""

from __future__ import annotations

from sqlalchemy import text

import db


def _count(conn) -> int:
    return conn.execute(text("SELECT count(*) FROM routing_rule_executions")).scalar_one()


def test_simulate_uses_the_live_evaluator_and_logs_no_execution(db_tx) -> None:
    rules = [r for r in db.list_routing_rules() if r["enabled"]]
    assert rules, "the dev DB seeds routing rules"
    before = _count(db_tx)
    out = db.simulate_routing_rules({"sentiment": "angry", "dpd": 95, "overdue_amount": 250000, "intent": "dispute"})
    assert {r["ruleId"] for r in out["results"]} == {r["id"] for r in rules}
    for r in out["results"]:
        # a rule matches exactly when every node does, and a node is its conditions' OR or AND
        assert r["matched"] == (bool(r["nodes"]) and all(n["matched"] for n in r["nodes"]))
        for n in r["nodes"]:
            wanted = any if n["isOr"] else all
            assert n["matched"] == wanted(c["matched"] for c in n["conditions"])
    firing = [r["ruleId"] for r in out["results"] if r["matched"]]
    assert out["firingRuleId"] == (firing[0] if firing else None)
    assert _count(db_tx) == before
