"""Agent Studio card persistence: draft round-trip, publish, runtime parity.

Every case here is a bug that shipped. The editor PATCHed the draft and read
back the published row, so Skills/Tools toggles snapped back; a version created
without a card fell through to the on-disk first-party default (or ``{}`` for a
tenant clone), so publish reset or wiped authored edits; and the sandbox bundle
dropped the card entirely, so "test in sandbox" ran with no skills.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import db
from agent_core.cards.clone import clone_card
from agent_core.deployment import load_active_bundle, resolve_prompt_bundle


@pytest.fixture
def cloned_bot(db_tx):
    """A tenant clone with a draft and no published version — the state every
    freshly cloned card is in, and the one the old code showed as empty."""
    row = clone_card(template_id="lapse", name=f"T {uuid.uuid4().hex[:6]}")
    bot_id = row["botId"]
    yield bot_id
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM bot_deployments WHERE bot_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM prompt_versions WHERE bot_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM bots WHERE id = :b"), {"b": bot_id})


def _skill_ids(card: dict) -> list[str]:
    return [s.get("skill_id") for s in (card or {}).get("skills") or []]


def test_clone_exposes_its_draft_card(cloned_bot) -> None:
    card = db.get_agent_studio_card(cloned_bot)
    assert card is not None
    assert card["cardSource"] == "draft"
    assert card["deploymentStatus"] == "draft"
    assert card["agentCard"], "a clone with a draft must not read back as an empty card"
    assert card["toolCount"] > 0
    assert card["draftVersionId"]


def test_unpublished_card_reports_no_traffic(cloned_bot) -> None:
    # Was hardcoded to 100, so every unpublished clone looked live on the fleet.
    assert db.get_agent_studio_card(cloned_bot)["trafficPct"] is None


def test_card_edit_round_trips_through_the_draft(cloned_bot) -> None:
    before = db.get_agent_studio_card(cloned_bot)
    card = dict(before["agentCard"])
    dropped = _skill_ids(card)[0]
    card["skills"] = [s for s in card["skills"] if s.get("skill_id") != dropped]
    card["tools"] = {**card["tools"], "include": [*card["tools"]["include"], "request_callback"]}
    db.patch_prompt_version(before["draftVersionId"], {"agentCard": card})

    after = db.get_agent_studio_card(cloned_bot)
    assert dropped not in _skill_ids(after["agentCard"])
    assert "request_callback" in after["agentCard"]["tools"]["include"]


def test_version_created_without_a_card_inherits_the_current_one(cloned_bot) -> None:
    """Autosave and publish both create versions with no agentCard."""
    expected = _skill_ids(db.get_agent_studio_card(cloned_bot)["agentCard"])
    created = db.create_prompt_version(
        {
            "botId": cloned_bot,
            "label": "no-card autosave",
            "prompt": "x",
            "persona": db._DEFAULT_PERSONA,
            "voice": db._DEFAULT_VOICE,
            "guardrails": db._DEFAULT_GUARDRAILS,
        }
    )
    # card_dump raises KeyError for a tenant bot id, so the old fallback stored {}.
    assert _skill_ids(created["agentCard"]) == expected


def test_first_party_card_edit_survives_a_card_less_create(db_tx) -> None:
    """The same fallback reset a first-party bot to its on-disk defaults."""
    published = db.get_published_prompt_version("kaia-v2-4")
    assert published is not None
    draft = db.restore_prompt_version_as_draft(published["id"])
    card = dict(draft["agentCard"])
    card["tools"] = {**card["tools"], "include": [*card["tools"]["include"], "request_callback"]}
    db.patch_prompt_version(draft["id"], {"agentCard": card})

    created = db.create_prompt_version(
        {
            "botId": "kaia-v2-4",
            "label": "kaia autosave",
            "prompt": "x",
            "persona": db._DEFAULT_PERSONA,
            "voice": db._DEFAULT_VOICE,
            "guardrails": db._DEFAULT_GUARDRAILS,
        }
    )
    # Inherits the *published* card (status ordering), never the disk default.
    assert created["agentCard"].get("identity", {}).get("bot_id") == "kaia-v2-4"
    assert created["agentCard"]["tools"]["include"]


def test_lapse_template_compiles(cloned_bot) -> None:
    """It pinned a skill the catalog lacks and granted fewer tools than its own
    skills declare — two fail-closed G9 issues, so no Lapse clone could ship."""
    report = db.compile_agent_studio_card(cloned_bot)
    failing = [g["gate"] for g in report["gates"] if g["status"] == "fail"]
    assert failing == [], report["gates"]


def test_publish_carries_the_card_into_the_runtime_bundle(cloned_bot) -> None:
    card = db.get_agent_studio_card(cloned_bot)
    expected = _skill_ids(card["agentCard"])
    published = db.publish_prompt_version(card["draftVersionId"], "test")

    bundle = load_active_bundle("production", bot_id=cloned_bot)
    assert _skill_ids(bundle["agentCard"]) == expected

    from agent_core.skills.runtime import mouth_turn_state

    state = mouth_turn_state(bundle["agentCard"])
    assert state["prefix"], "skill descriptions must reach the system prefix"
    assert state["offered"] is not None

    # Sandbox parity: the explicit-version path used to omit both of these.
    sandbox = resolve_prompt_bundle(prompt_version_id=published["id"])
    assert _skill_ids(sandbox["agentCard"]) == expected
    assert sandbox["botId"] == cloned_bot


def test_compile_preview_reads_the_draft_not_the_published_card(cloned_bot) -> None:
    """Publish ships the draft, so a preview that compiled the published row
    reported green for a card that had never been checked."""
    card_row = db.get_agent_studio_card(cloned_bot)
    db.publish_prompt_version(card_row["draftVersionId"], "baseline")

    published = db.get_published_prompt_version(cloned_bot)
    draft = db.restore_prompt_version_as_draft(published["id"])
    broken = dict(draft["agentCard"])
    broken["tools"] = {**broken["tools"], "include": ["definitely_not_a_tool"]}
    db.patch_prompt_version(draft["id"], {"agentCard": broken})

    report = db.compile_agent_studio_card(cloned_bot)
    assert any(g["status"] == "fail" for g in report["gates"]), report["gates"]
