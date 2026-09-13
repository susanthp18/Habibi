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
from tests.conftest import owner_engine
from agent_core import change_log
from agent_core.cards.clone import clone_card


def _reset_chain_head() -> None:
    """Drop the tenant's persisted chain head so a test starts from genesis.

    `db_tx` rolls the test's own writes back, but `audit_chain_heads` is a
    committed row that survives — so one run that committed a head leaves every
    later run chaining onto a hash no surviving row has, and `verify_chain`
    reports `tail_truncated` forever. Clearing it at *setup* is what makes the
    suite repeatable; a teardown cannot, because after the rollback there are no
    rows left to identify the tenant by.

    Safe, not merely convenient: `_write` falls back to `_chain_head`, which
    re-derives the head from whatever rows survive and returns genesis when none
    do. Deliberately not done in `_persisted_head` itself — automatic self-heal
    in the library would erase exactly the tamper evidence the chain exists to
    provide. Repairing production is an explicit, audited operator action.
    """
    with db.engine.begin() as conn:
        conn.execute(
            text("DELETE FROM audit_chain_heads WHERE tenant_id = :t"),
            {"t": db._tenant()},
        )


@pytest.fixture
def cloned_bot(db_tx):
    _reset_chain_head()
    row = clone_card(template_id="hardship", name=f"CL {uuid.uuid4().hex[:6]}")
    bot_id = row["botId"]
    yield bot_id
    _reset_chain_head()
    owner = owner_engine()
    if owner is not None:
        # audit_log is append-only for the app role (sql/43); the owner cleans.
        with owner.begin() as conn:
            conn.execute(text("DELETE FROM audit_log WHERE entity_id = :b"), {"b": bot_id})
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM bot_deployments WHERE bot_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM prompt_versions WHERE bot_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM bots WHERE id = :b"), {"b": bot_id})


def _entries(bot_id: str) -> list[dict]:
    return db.agent_change_log(bot_id)["entries"]


def _tamperer():
    """Rewriting history is the owner's act by construction (sql/43): the app
    role cannot UPDATE or DELETE audit_log at all. The chain still has to
    notice the owner doing it, which is what these tests prove."""
    owner = owner_engine()
    if owner is None:
        pytest.skip("MIGRATION_DATABASE_URL unset: cannot act as the owner")
    return owner


def test_publishing_records_who_what_and_the_compiler_verdict(cloned_bot: str) -> None:
    version_id = db.get_agent_studio_card(cloned_bot)["draftVersionId"]

    db.publish_prompt_version(version_id, "first ship", traffic_pct=100)

    entry = _entries(cloned_bot)[0]
    assert entry["action"] == "agent.publish"
    assert entry["actorUserId"]
    assert entry["versionId"] == version_id
    assert entry["summary"] == "first ship"
    assert entry["rollout"] == {"trafficPct": 100, "autoRollback": []}
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

    # Hold *everything* else constant, flow included. Omitting flow used to pass
    # only because the cloned card's flow happened to be the empty sentinel:
    # empty-to-empty is not a change, so the diff stayed quiet by luck. Once the
    # source card carried a real authored graph, dropping it here was a genuine
    # change and the log correctly said so — the assertion below is about the
    # diff being precise, not about flow being ignorable.
    previous = db.get_prompt_version(first)
    second = db.create_prompt_version(
        {
            "botId": cloned_bot,
            "label": "v1.1",
            "prompt": "A completely different instruction.",
            "persona": previous["persona"],
            "voice": previous["voice"],
            "guardrails": previous["guardrails"],
            "flow": previous["flow"],
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


def test_restoring_a_card_is_recorded_too(cloned_bot: str) -> None:
    """Archive was chained and restore was not, so the log said a card had been
    retired and never that it came back — a hole shaped exactly like the thing
    someone would want hidden. Both halves of the roster toggle are recorded."""
    db.archive_agent_studio_card(cloned_bot)
    db.restore_agent_studio_card(cloned_bot)

    entries = _entries(cloned_bot)
    assert [e["action"] for e in entries[:2]] == ["agent.restore", "agent.archive"]
    # The retired window is the fact an auditor reconstructs; it is read before
    # the UPDATE nulls the column, so it cannot come back empty.
    assert entries[0]["archivedAt"]
    assert db.agent_change_log(cloned_bot)["chain"]["ok"] is True


def test_every_lifecycle_action_has_a_verb_the_log_can_render(cloned_bot: str) -> None:
    """Introspective: the actions the module can emit, not a list someone has to
    remember to extend. A new `record_*` writing an unlisted action fails here
    rather than rendering as a raw `agent.whatever` on the fleet index."""
    emitted = {
        value
        for name, value in vars(change_log).items()
        if name.isupper() and isinstance(value, str) and value.startswith("agent.")
    }
    assert emitted == {
        "agent.publish",
        "agent.rollback",
        "agent.archive",
        "agent.restore",
        "agent.role_grants",
        "agent.experiment_rollback",
        "agent.entry_binding",
        "agent.platform_sync",
        "agent.fleet_rebuild",
        "agent.connector",
        "agent.mcp_key",
    }

    db.archive_agent_studio_card(cloned_bot)
    db.restore_agent_studio_card(cloned_bot)
    for entry in _entries(cloned_bot):
        assert entry["action"] in emitted


def test_the_screen_knows_every_verb_the_log_can_write() -> None:
    """The half the Python-only test could not see. The two TypeScript maps
    drifted from this list twice (`agent.restore`, then `agent.role_grants`
    rendered as wire strings); there is one table now, and it is pinned here."""
    from pathlib import Path

    table = Path(__file__).resolve().parents[2] / "Habibi" / "src" / "lib" / "change-log-actions.ts"
    if not table.exists():
        pytest.skip("frontend not checked out beside the backend")
    src = table.read_text(encoding="utf-8")
    emitted = {
        value
        for name, value in vars(change_log).items()
        if name.isupper() and isinstance(value, str) and value.startswith("agent.")
    }
    missing = sorted(a for a in emitted if f'"{a}"' not in src)
    assert not missing, f"change-log-actions.ts has no row for {missing}"


def test_a_rollback_records_the_gates_of_the_version_it_reships(cloned_bot: str) -> None:
    """CHANGELOG-10: a rollback never recompiles, so it recorded no verdict at
    all. It records the gates the re-shipped version passed at its publish."""
    from agent_core import change_log as cl

    with db.engine.begin() as conn:
        row = cl.record_rollback(
            conn,
            tenant_id=db.current_tenant(),
            actor_user_id=db._actor_user_id(),
            entry_id="AUD-test-rollback-gates",
            bot_id=cloned_bot,
            to_deployment_id="DEP-x",
            from_deployment_id=None,
            version_id="pv-x",
            report={"gates": [{"gate": "G0", "status": "pass"}, {"gate": "G6", "status": "warn"}]},
        )
    assert row["gates"] == {"G0": "pass", "G6": "warn"}


# ---------------------------------------------------------------------------
# Tampering. audit_log is append-only for the application role (sql/43), so
# these run as the owner -- the only role that can rewrite history -- against
# committed rows (db_real). The chain still has to notice the owner doing it.
# ---------------------------------------------------------------------------


def _committed_chain(db_real, n: int = 2) -> tuple[str, list[str]]:
    """``n`` archive entries for a probe bot, committed; returns (bot_id, entry ids)."""
    from agent_core import change_log

    bot_id = f"chain-tamper-{uuid.uuid4().hex[:8]}"
    db_real.track("audit_log", entity_id=bot_id)
    ids: list[str] = []
    for _ in range(n):
        entry_id = db._id("AUD")
        with db.engine.begin() as conn:
            change_log.record_archive(
                conn,
                tenant_id=db.current_tenant(),
                actor_user_id=db._actor_user_id(),
                entry_id=entry_id,
                bot_id=bot_id,
                retired_deployment_id=None,
            )
        ids.append(entry_id)
    return bot_id, ids


def test_the_application_role_cannot_rewrite_history(db_real) -> None:
    """The stronger property: not "we would notice" but "it cannot be done"."""
    from sqlalchemy.exc import DBAPIError

    _bot, (first, _second) = _committed_chain(db_real)
    with pytest.raises(DBAPIError, match="append-only"):
        with db.engine.begin() as conn:
            conn.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": first})
    with pytest.raises(DBAPIError, match="append-only"):
        with db.engine.begin() as conn:
            conn.execute(
                text("UPDATE audit_log SET action = 'agent.rollback' WHERE id = :id"), {"id": first}
            )


def test_the_chain_detects_an_edited_entry(db_real) -> None:
    """The point of the hash chain. Rewriting history has to be visible, not
    merely unlikely -- even when the owner does it."""
    bot_id, (first, _second) = _committed_chain(db_real)
    assert db.agent_change_log(bot_id)["chain"]["ok"] is True

    with _tamperer().begin() as conn:
        payload = conn.execute(
            text("SELECT payload FROM audit_log WHERE id = :id"), {"id": first}
        ).scalar()
        payload = payload if isinstance(payload, dict) else json.loads(payload)
        payload["retiredDeploymentId"] = "something else entirely"
        conn.execute(
            text("UPDATE audit_log SET payload = CAST(:p AS jsonb) WHERE id = :id"),
            {"id": first, "p": json.dumps(payload)},
        )

    verdict = db.agent_change_log(bot_id)["chain"]
    assert verdict["ok"] is False
    assert verdict["brokenAt"] == first
    assert verdict["reason"] == "entry_hash_mismatch"


def test_the_screen_renders_the_hashed_action_not_the_raw_column(db_real) -> None:
    """`action` and `botId` exist twice: in the digest, and in `audit_log`
    columns that are outside it. The screen used to render the columns, so an
    UPDATE against them changed what a compliance reviewer read while
    `verify_chain` still reported ok -- tamper-visible text sourced from the one
    copy nothing protects."""
    bot_id, (first, _second) = _committed_chain(db_real)
    with _tamperer().begin() as conn:
        conn.execute(
            text("UPDATE audit_log SET action = 'agent.rollback' WHERE id = :id"), {"id": first}
        )

    entries = {e["id"]: e for e in _entries(bot_id)}
    assert entries[first]["action"] == "agent.archive"
    # The digest never covered the column, so the chain cannot see this edit --
    # which is exactly why the screen must not read it.
    assert db.agent_change_log(bot_id)["chain"]["ok"] is True


def test_the_chain_detects_a_deleted_entry(db_real) -> None:
    bot_id, (first, _second) = _committed_chain(db_real)
    with _tamperer().begin() as conn:
        conn.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": first})

    verdict = db.agent_change_log(bot_id)["chain"]
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


# ---------------------------------------------------------------------------
# The three evidence writes that left no chain entry
# ---------------------------------------------------------------------------


def test_connector_registration_and_approval_are_chained(db_tx) -> None:
    """A connector's URL, prefixes and data class bound what a published card
    may call; registering and approving one wrote a timeline row and no
    chain entry."""
    from agent_core.connectors import persist as cp

    _reset_chain_head()
    slug = f"chain-{uuid.uuid4().hex[:6]}"
    row = cp.upsert_connector(
        {
            "slug": slug,
            "kind": "remote_mcp",
            "url": "https://mcp.example.test/rpc",
            "allowPrefixes": [f"ext.{slug}."],
            "dataClass": ["money"],
        }
    )
    cp.approve(row["id"])
    entries = _entries(row["id"])
    actions = [e["action"] for e in entries]
    assert actions[:2] == ["agent.connector", "agent.connector"]
    assert entries[0]["status"] == "approved"
    assert entries[0]["allowPrefixes"] == [f"ext.{slug}."]
    assert entries[0]["actorUserId"]


def test_mcp_key_rotation_is_chained_without_the_secret(db_tx) -> None:
    """Mint, rotate, revoke: each is an entry naming the key, its scopes and
    its prefix -- and never the key or its hash."""
    import json

    from agent_core.mcp_http import auth

    _reset_chain_head()
    minted = auth.mint_key(name="chain-test", scopes=[auth.SCOPE_CRM_READ])
    rotated = auth.rotate_key(minted["id"])
    old = _entries(minted["id"])
    new = _entries(rotated["id"])
    assert [e["action"] for e in old] == ["agent.mcp_key", "agent.mcp_key"]
    assert old[0]["revoked"] is True and old[1]["revoked"] is False
    assert new[0]["rotatedFrom"] == minted["id"]
    blob = json.dumps(old + new)
    assert minted["key"] not in blob and rotated["key"] not in blob
    assert auth.hash_key(minted["key"]) not in blob
