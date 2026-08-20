"""The record of what an agent was configured to say.

Publishing changes the words a regulated agent speaks to every caller. These
tests pin the four properties that make the record evidence rather than a log:
it is written, it is complete, it is accurate about what changed, and it cannot
be quietly rewritten.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

import db
from agent_core import change_log
from agent_core.cards.clone import clone_card


@pytest.fixture
def cloned_bot(db_tx):
    row = clone_card(template_id="hardship", name=f"CL {uuid.uuid4().hex[:6]}")
    bot_id = row["botId"]
    yield bot_id
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_log WHERE entity_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM bot_deployments WHERE bot_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM prompt_versions WHERE bot_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM bots WHERE id = :b"), {"b": bot_id})


def _entries(bot_id: str) -> list[dict]:
    return db.agent_change_log(bot_id)["entries"]


def test_publishing_records_who_what_and_the_compiler_verdict(cloned_bot: str) -> None:
    version_id = db.get_agent_studio_card(cloned_bot)["draftVersionId"]

    db.publish_prompt_version(version_id, "first ship", traffic_pct=100)

    entry = _entries(cloned_bot)[0]
    assert entry["action"] == "agent.publish"
    assert entry["actorUserId"]
    assert entry["versionId"] == version_id
    assert entry["summary"] == "first ship"
    assert entry["rollout"] == {"trafficPct": 100, "shadow": False, "autoRollback": []}
    # The gate outcomes at the moment of shipping — previously computed on every
    # publish and then discarded, so "was G9 green when this shipped?" had no
    # answer once the report went out of scope.
    assert entry["gates"]["G0"] == "pass"
    assert "G9" in entry["gates"] and "G12" in entry["gates"]
    # Everything is "changed" on a first publish: there was no live config.
    assert set(entry["changed"]) == set(change_log.COMPONENTS)


def test_the_diff_names_only_what_actually_moved(cloned_bot: str) -> None:
    first = db.get_agent_studio_card(cloned_bot)["draftVersionId"]
    db.publish_prompt_version(first, "v1")

    second = db.create_prompt_version(
        {
            "botId": cloned_bot,
            "label": "v1.1",
            "prompt": "A completely different instruction.",
            "persona": db.get_prompt_version(first)["persona"],
            "voice": db.get_prompt_version(first)["voice"],
            "guardrails": db.get_prompt_version(first)["guardrails"],
        }
    )["id"]
    db.publish_prompt_version(second, "prompt only")

    entry = _entries(cloned_bot)[0]
    assert entry["changed"] == ["prompt"], entry["changed"]
    assert entry["previousVersionId"] == first


def test_the_log_stores_digests_not_a_second_copy_of_the_prompt(cloned_bot: str) -> None:
    """A published prompt_versions row is immutable, so copying the text here
    would only create a second thing to keep in sync — and a second place for
    it to leak from."""
    version_id = db.get_agent_studio_card(cloned_bot)["draftVersionId"]
    prompt = db.get_prompt_version(version_id)["prompt"]
    db.publish_prompt_version(version_id, "ship")

    entry = _entries(cloned_bot)[0]
    assert set(entry["hashes"]) == set(change_log.COMPONENTS)
    assert all(len(h) == 64 for h in entry["hashes"].values())
    assert prompt not in json.dumps(entry)


def test_rollback_and_archive_are_in_the_same_chain(cloned_bot: str) -> None:
    """Every route by which live configuration changes has to be recorded, or
    the history has holes exactly where someone reverted something."""
    version_id = db.get_agent_studio_card(cloned_bot)["draftVersionId"]
    db.publish_prompt_version(version_id, "v1")
    second = db.restore_prompt_version_as_draft(version_id)["id"]
    db.publish_prompt_version(second, "v2")

    deployments = db.list_bot_deployments(bot_id=cloned_bot, environment="production")
    prior = next(d for d in deployments if d["status"] != "active")
    db.rollback_bot_deployment(prior["id"])
    db.archive_agent_studio_card(cloned_bot)

    actions = [e["action"] for e in _entries(cloned_bot)]
    assert actions == [
        "agent.archive",
        "agent.rollback",
        "agent.publish",
        "agent.publish",
    ]


def test_the_chain_detects_an_edited_entry(cloned_bot: str) -> None:
    """The point of the hash chain. Rewriting history has to be visible, not
    merely unlikely."""
    version_id = db.get_agent_studio_card(cloned_bot)["draftVersionId"]
    db.publish_prompt_version(version_id, "as shipped")
    assert db.agent_change_log(cloned_bot)["chain"]["ok"] is True

    entry_id = _entries(cloned_bot)[0]["id"]
    with db.engine.begin() as conn:
        payload = conn.execute(
            text("SELECT payload FROM audit_log WHERE id = :id"), {"id": entry_id}
        ).scalar()
        payload = payload if isinstance(payload, dict) else json.loads(payload)
        payload["summary"] = "something else entirely"
        conn.execute(
            text("UPDATE audit_log SET payload = CAST(:p AS jsonb) WHERE id = :id"),
            {"id": entry_id, "p": json.dumps(payload)},
        )

    verdict = db.agent_change_log(cloned_bot)["chain"]
    assert verdict["ok"] is False
    assert verdict["brokenAt"] == entry_id
    assert verdict["reason"] == "entry_hash_mismatch"


def test_the_chain_detects_a_deleted_entry(cloned_bot: str) -> None:
    version_id = db.get_agent_studio_card(cloned_bot)["draftVersionId"]
    db.publish_prompt_version(version_id, "v1")
    second = db.restore_prompt_version_as_draft(version_id)["id"]
    db.publish_prompt_version(second, "v2")

    first_entry = _entries(cloned_bot)[-1]["id"]
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": first_entry})

    verdict = db.agent_change_log(cloned_bot)["chain"]
    assert verdict["ok"] is False
    assert verdict["reason"] == "prev_hash_mismatch"


def test_a_failed_publish_leaves_no_entry(cloned_bot: str) -> None:
    """The record is written inside the publishing transaction, so a publish the
    compiler rejects must not appear to have happened."""
    version_id = db.get_agent_studio_card(cloned_bot)["draftVersionId"]
    before = len(_entries(cloned_bot))

    with pytest.raises(Exception):
        # 40% canary with no rollback trigger — G12 fails.
        db.publish_prompt_version(version_id, "bad", traffic_pct=40, auto_rollback=[])

    assert len(_entries(cloned_bot)) == before
