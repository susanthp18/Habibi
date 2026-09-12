"""Publishing a member is a fleet act, and the artefact says so.

A door's compiled bundle is *derived* from its members' published versions.
Before this, publishing a member rewrote `compiled` and `bundle_hash` in place
on the door's live deployment row -- the deployment id every hop records
(`interaction_handoffs.deployment_id`) no longer named one artefact. Now the
door gets a new deployment carrying the rebuilt bundle, the change log names
the member version that caused it, and the bundle itself names the member
versions it merged (`member_versions`, part of the hash).

These read the dev stack's fleet (intake -> kaia, insurance; kaia and
insurance -> supervisor-brief) and skip where it is not published.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

import db
from agent_core import change_log

MEMBER = "supervisor-brief"


def _active(conn, bot_id: str) -> dict | None:
    row = conn.execute(
        text(
            "SELECT id, bundle_hash, prompt_version_id FROM bot_deployments "
            " WHERE bot_id = :b AND status = 'active' AND environment = 'production'"
        ),
        {"b": bot_id},
    ).mappings().first()
    return dict(row) if row else None


def _doors(conn, member: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            text(
                "SELECT bot_id FROM prompt_versions WHERE status = 'published' AND tenant_id = :t "
                "  AND compiled -> 'entry_by_specialist' ? :m ORDER BY bot_id"
            ),
            {"t": db.current_tenant(), "m": member},
        )
    ]


def test_a_member_publish_ships_a_new_deployment_on_every_door_that_merges_it(db_tx) -> None:
    doors = _doors(db_tx, MEMBER)
    published = db.get_published_prompt_version(MEMBER)
    if not doors or published is None:
        pytest.skip(f"{MEMBER} is not merged by a published door on this stack")
    before = {d: _active(db_tx, d) for d in doors}
    if any(v is None for v in before.values()):
        pytest.skip("a door has no active deployment on this stack")
    untouched = [
        d for d in ("intake-v1", "kaia-v2-4", "insurance-v1") if d not in doors and _active(db_tx, d)
    ]
    untouched_before = {d: _active(db_tx, d) for d in untouched}

    draft = db.restore_prompt_version_as_draft(published["id"])
    result = db.publish_prompt_version(draft["id"], "member republish")

    rebuilds = {r["doorBotId"]: r for r in result["fleetRebuilds"]}
    assert set(rebuilds) == set(doors), rebuilds
    for door in doors:
        after = _active(db_tx, door)
        assert after is not None
        assert rebuilds[door]["rebuilt"] is True, rebuilds[door]
        assert after["id"] == rebuilds[door]["deploymentId"]
        assert after["id"] != before[door]["id"], "the door's deployment is a new row"
        assert after["bundle_hash"] != before[door]["bundle_hash"]
        assert after["prompt_version_id"] == before[door]["prompt_version_id"], (
            "a rebuild ships the same door version under a new derivation"
        )
        compiled = db_tx.execute(
            text("SELECT compiled FROM prompt_versions WHERE id = :id"),
            {"id": after["prompt_version_id"]},
        ).scalar()
        assert compiled["bundle_hash"] == after["bundle_hash"]
        assert compiled["member_versions"][MEMBER] == result["id"]
        entry = db_tx.execute(
            text(
                "SELECT payload FROM audit_log WHERE entity_type = 'bot' AND entity_id = :b "
                "  AND action = :a ORDER BY created_at DESC LIMIT 1"
            ),
            {"b": door, "a": change_log.FLEET_REBUILD},
        ).scalar()
        assert entry is not None, "the fleet act is on the door's change log"
        assert entry["memberBotId"] == MEMBER
        assert entry["memberVersionId"] == result["id"]
        assert entry["deploymentId"] == after["id"]
        assert entry["previousDeploymentId"] == before[door]["id"]
        retired = db_tx.execute(
            text("SELECT status FROM bot_deployments WHERE id = :id"), {"id": before[door]["id"]}
        ).scalar()
        assert retired == "retired"
    for door, row in untouched_before.items():
        assert _active(db_tx, door) == row, f"{door} does not merge {MEMBER} and must not move"


def test_a_door_with_a_running_experiment_is_not_rebuilt_under_it(db_tx) -> None:
    doors = _doors(db_tx, MEMBER)
    published = db.get_published_prompt_version(MEMBER)
    if not doors or published is None:
        pytest.skip(f"{MEMBER} is not merged by a published door on this stack")
    door = doors[0]
    active = _active(db_tx, door)
    if active is None:
        pytest.skip("no active deployment")
    db_tx.execute(
        text(
            """
            INSERT INTO deployment_experiments
              (id, tenant_id, bot_id, environment, canary_deployment_id, baseline_deployment_id,
               traffic_pct, shadow, auto_rollback, status)
            VALUES ('exp-test-fleet', :t, :b, 'production', :dep, NULL, 20, false, '[]'::jsonb, 'running')
            """
        ),
        {"t": db.current_tenant(), "b": door, "dep": active["id"]},
    )

    draft = db.restore_prompt_version_as_draft(published["id"])
    result = db.publish_prompt_version(draft["id"], "member republish under a canary")

    row = next(r for r in result["fleetRebuilds"] if r["doorBotId"] == door)
    assert row["rebuilt"] is False
    assert row["reason"].startswith("experiment_running:")
    assert _active(db_tx, door)["id"] == active["id"], "the baseline under the experiment is untouched"


def test_the_bundle_hash_covers_the_member_versions() -> None:
    """Two compiles that differ only in which member version was merged hash
    differently: the derivation is part of the artefact's identity."""
    from agent_core.cards.compile import CompileReport, GateResult
    from agent_core.fleet.compile import compile_bundle

    flow = {
        "version": 1,
        "nodes": [
            {"key": "greet", "kind": "say", "data": {"isStart": True}},
            {"key": "route", "kind": "route", "data": {}},
        ],
        "edges": [],
    }
    member_flow = {"version": 1, "nodes": [{"key": "a", "kind": "say", "data": {}}], "edges": []}
    report = CompileReport(bot_id="door", gates=[GateResult(gate="G0", name="schema", status="pass")], card={})

    def _compile(version: str):
        return compile_bundle(
            report=report,
            prompt="p",
            flow=flow,
            prompt_version_id="pv-door",
            members=[{"bot_id": "m1", "prompt_version_id": version, "card": {}, "flow": member_flow}],
        )

    one, two = _compile("pv-1"), _compile("pv-2")
    assert one.member_versions == {"m1": "pv-1"} and two.member_versions == {"m1": "pv-2"}
    assert one.bundle_hash != two.bundle_hash
