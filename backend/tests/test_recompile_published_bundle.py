"""Filling in `compiled` on a live card without republishing it.

`prompt_versions.compiled` was NULL on every published row, because the column
landed after they were published and only `publish_prompt_version` writes it.
While it is NULL, `deployment._dual_compute_parity` returns at its first guard --
no parity is logged and `fleet_enabled()` is never reached -- so the compiled
artefact could not be trusted before switching it on, because nothing had ever
compared it against the live path.

The tempting fix is to republish each card. These tests exist because that is
the wrong fix and the difference is invisible until it is not:
`publish_prompt_version` archives the live row, inserts a *new*
`bot_deployments` row, re-snapshots frozen connector tools, re-applies the
tuning overlay and rewrites the card through `model_dump`. On an unchanged card
that is still a real production swap of the deployment every inbound call
resolves to.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

import db
import db_prompt_studio as dps

BOT = "kaia-v2-4"


def _live(conn) -> dict:
    row = (
        conn.execute(
            text(
                "SELECT d.id, d.prompt_version_id, d.status, d.bundle_hash, "
                "       d.published_at "
                "  FROM bot_deployments d "
                " WHERE d.bot_id = :b AND d.status = 'active'"
            ),
            {"b": BOT},
        )
        .mappings()
        .first()
    )
    assert row is not None, f"{BOT} has no active deployment to test against"
    return dict(row)


def test_the_deployment_every_call_resolves_to_is_not_swapped(db_tx) -> None:
    before = _live(db_tx)
    total_before = db_tx.execute(text("SELECT count(*) FROM bot_deployments")).scalar()

    dps.recompile_published_bundle(BOT)

    after = _live(db_tx)
    assert after["id"] == before["id"], "the active deployment was replaced"
    assert after["prompt_version_id"] == before["prompt_version_id"]
    assert after["published_at"] == before["published_at"]
    assert db_tx.execute(text("SELECT count(*) FROM bot_deployments")).scalar() == total_before


def test_it_stamps_the_hash_of_the_bundle_it_wrote(db_tx) -> None:
    result = dps.recompile_published_bundle(BOT)

    assert result["deploymentsStamped"] == 1
    assert _live(db_tx)["bundle_hash"] == result["bundleHash"]

    stored = db_tx.execute(
        text("SELECT compiled FROM prompt_versions WHERE id = :i"),
        {"i": result["promptVersionId"]},
    ).scalar()
    assert stored is not None
    assert stored["bundle_hash"] == result["bundleHash"]


def test_no_version_changes_status(db_tx) -> None:
    """`publish_prompt_version` archives the live row on its way past. This must
    leave every version exactly where it was."""
    before = dict(
        db_tx.execute(
            text("SELECT id, status FROM prompt_versions WHERE bot_id = :b"),
            {"b": BOT},
        ).all()
    )

    dps.recompile_published_bundle(BOT)

    after = dict(
        db_tx.execute(
            text("SELECT id, status FROM prompt_versions WHERE bot_id = :b"),
            {"b": BOT},
        ).all()
    )
    assert after == before


def test_it_is_idempotent(db_tx) -> None:
    """Same card in, same hash out. A hash that moved on a no-op recompile would
    mean the bundle carries something that is not the contract -- a timestamp, a
    set iteration order -- and every parity comparison downstream would be noise."""
    first = dps.recompile_published_bundle(BOT)
    second = dps.recompile_published_bundle(BOT)

    assert first["bundleHash"] == second["bundleHash"]


def test_it_refuses_a_bot_with_no_published_version(db_tx) -> None:
    with pytest.raises(KeyError, match="no_published_version"):
        dps.recompile_published_bundle("no-such-bot")


def test_it_compiles_the_published_row_not_the_draft(db_tx) -> None:
    """`compile_agent_studio_card(bot_id)` with no version resolves the draft
    when there is one -- right for a preview, wrong here. Stamping the column
    the runtime reads with a draft's artefact would put a contract nobody
    published where the mouth looks for one."""
    live_id = db_tx.execute(
        text(
            "SELECT id FROM prompt_versions "
            " WHERE bot_id = :b AND status = 'published' AND tenant_id = :t"
        ),
        {"b": BOT, "t": db.current_tenant()},
    ).scalar()

    db_tx.execute(
        text(
            "INSERT INTO prompt_versions (id, tenant_id, bot_id, label, status, prompt) "
            "VALUES ('pv-draft-probe', :t, :b, 'Draft probe', 'draft', 'draft text')"
        ),
        {"t": db.current_tenant(), "b": BOT},
    )

    result = dps.recompile_published_bundle(BOT)

    assert result["promptVersionId"] == live_id
    assert (
        db_tx.execute(
            text("SELECT compiled FROM prompt_versions WHERE id = 'pv-draft-probe'")
        ).scalar()
        is None
    )


def test_doors_merging_reads_what_was_compiled_not_the_handoff_graph(db_tx) -> None:
    """The handoff graph cannot answer this. `insurance-v1` and
    `collections-clone-9ff4b6` each hand off to cards the other also reaches, so
    "the owning door" is not a single value and a topology walk would be picking
    by sort order. `entry_by_specialist` is what the compiler actually merged."""
    assert dps.doors_merging(BOT) == []

    db_tx.execute(
        text(
            "UPDATE prompt_versions SET compiled = "
            "  jsonb_set(coalesce(compiled, '{}'::jsonb), '{entry_by_specialist}', "
            "            CAST(:e AS jsonb)) "
            " WHERE bot_id = 'intake-v1' AND status = 'published'"
        ),
        {"e": '{"intake-v1": "greet_disclose", "kaia-v2-4": "state_position"}'},
    )

    assert dps.doors_merging(BOT) == ["intake-v1"]
    # A bundle never lists itself as something it merged in.
    assert dps.doors_merging("intake-v1") == []
