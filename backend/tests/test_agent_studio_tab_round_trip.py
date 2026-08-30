"""Every Studio tab must survive the trip to publish and back.

Each test here is a bug found by walking the twelve tabs against the running
API: an edit that looked saved, a preview that disagreed with the publish it was
previewing, or a count that contradicted the compiler it claimed to quote.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import db
from agent_core.cards.clone import clone_card
from agent_core.cards.compile import compile_card
from agent_core.eval.run import bot_id_for_suite
from agent_core.tools.catalog import CATALOG


@pytest.fixture
def cloned_bot(db_tx):
    row = clone_card(template_id="hardship", name=f"RT {uuid.uuid4().hex[:6]}")
    bot_id = row["botId"]
    yield bot_id
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM eval_reports WHERE bot_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM bot_deployments WHERE bot_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM prompt_versions WHERE bot_id = :b"), {"b": bot_id})
        conn.execute(text("DELETE FROM bots WHERE id = :b"), {"b": bot_id})


def _card(bot_id: str) -> dict:
    return dict(db.get_agent_studio_card(bot_id)["agentCard"])


# --- Ship tab ---------------------------------------------------------------


def test_the_compile_preview_gates_the_canary_it_is_previewing(cloned_bot: str) -> None:
    """The dialog compiled the card's stored experiment while Confirm sent the
    Ship tab's. A 40% split with no rollback trigger previewed green as "full
    ship" and then 422'd on the very next call."""
    card = _card(cloned_bot)

    stale = db.compile_agent_studio_card(cloned_bot, card_raw=card)
    assert _gate(stale, "G12")["status"] == "pass"  # the card itself is a full ship

    previewed = db.compile_agent_studio_card(
        cloned_bot, card_raw=card, traffic_pct=40, auto_rollback=[]
    )
    g12 = _gate(previewed, "G12")
    assert g12["status"] == "fail"
    assert "auto_rollback" in g12["detail"]

    with_trigger = db.compile_agent_studio_card(
        cloned_bot, card_raw=card, traffic_pct=40, auto_rollback=["slo_miss"]
    )
    assert _gate(with_trigger, "G12")["status"] == "pass"


def test_publish_folds_the_shipped_experiment_into_the_card(cloned_bot: str) -> None:
    """The deployment recorded the split; the card did not. So the Ship tab read
    100% after a 40% canary, and the next publish would quietly re-ship at full
    traffic."""
    version_id = db.get_agent_studio_card(cloned_bot)["draftVersionId"]
    assert _card(cloned_bot)["experiment"]["traffic_pct"] == 100

    db.publish_prompt_version(
        version_id, "canary", traffic_pct=40, shadow=True, auto_rollback=["slo_miss"]
    )

    exp = _card(cloned_bot)["experiment"]
    assert exp == {"traffic_pct": 40, "shadow": True, "auto_rollback": ["slo_miss"]}
    assert db.get_agent_studio_card(cloned_bot)["trafficPct"] == 40


def test_an_unknown_rollback_trigger_never_reaches_the_card(cloned_bot: str) -> None:
    """auto_rollback is a Literal on the card. Persisting a trigger the compiler
    ignores would make the card itself unparseable on the next read."""
    version_id = db.get_agent_studio_card(cloned_bot)["draftVersionId"]

    db.publish_prompt_version(
        version_id, "canary", traffic_pct=100, auto_rollback=["slo_miss", "made_up"]
    )

    assert _card(cloned_bot)["experiment"]["auto_rollback"] == ["slo_miss"]
    # Still parseable — the point of filtering.
    from agent_core.cards.schema import parse_card

    parse_card(_card(cloned_bot))


# --- Tools tab --------------------------------------------------------------


def test_the_report_carries_the_count_g6_gates_on(cloned_bot: str) -> None:
    """The tab counted union(include, locked) against max_voice_tools and showed
    a red "over the cap" on a card compiling green: G6 counts idle tools, and
    the platform skill tools do not count at all."""
    card = _card(cloned_bot)
    report = compile_card(
        bot_id=cloned_bot,
        card_raw=card,
        catalog_names=set(CATALOG.specs),
        known_bot_ids=db.list_bot_ids(),
    )

    authored = len(set(card["tools"]["include"]) | set(card["tools"]["locked"]))
    assert report.idle_voice_tools <= report.voice_tool_cap
    assert report.voice_tool_cap == card["tools"]["max_voice_tools"]
    # The three numbers that a UI could quote are genuinely different, which is
    # why quoting the wrong one was not obviously wrong.
    assert report.idle_voice_tools != authored
    assert report.idle_voice_tools != len(report.idle_tools)
    assert f"idle {report.idle_voice_tools} tools" in _gate(
        report.model_dump(), "G6"
    )["detail"]


# --- Agent graph tab --------------------------------------------------------


def test_a_handoff_edit_survives_the_draft(cloned_bot: str) -> None:
    """card.handoffs is the only thing that makes a non-entry card reachable and
    was the one card field with no editor. It has to persist like every other."""
    card = _card(cloned_bot)
    version_id = db.get_agent_studio_card(cloned_bot)["draftVersionId"]
    card["handoffs"] = [*card["handoffs"], {"to_bot_id": "intake-v1", "when": "unidentified"}]

    db.patch_prompt_version(version_id, {"agentCard": card})

    assert "intake-v1" in [h["to_bot_id"] for h in _card(cloned_bot)["handoffs"]]


@pytest.mark.parametrize("target", ["self", "does-not-exist"])
def test_g5_rejects_the_two_handoffs_the_editor_must_not_offer(
    cloned_bot: str, target: str
) -> None:
    """The picker lists known bots and excludes this card, so neither shape is
    reachable through the UI — G5 is the backstop for the API."""
    card = _card(cloned_bot)
    card["handoffs"] = [{"to_bot_id": cloned_bot if target == "self" else target, "when": "x"}]

    report = db.compile_agent_studio_card(cloned_bot, card_raw=card)

    assert _gate(report, "G5")["status"] == "fail"


# --- Evals tab --------------------------------------------------------------


def test_an_eval_run_is_filed_against_the_card_that_launched_it(cloned_bot: str) -> None:
    """run_named_suite guessed the bot from the suite name, so a run started on a
    cloned card landed under kaia-v2-4 and the tab that started it kept reading
    "never run" — and G7/G8 could never find a report for that card."""
    from agent_core.eval.run import run_named_suite

    assert bot_id_for_suite("eval-capability-collections") == "kaia-v2-4"

    run_named_suite("eval-capability-collections", origin="manual", bot_id=cloned_bot)

    mine = db.list_eval_reports(bot_id=cloned_bot)
    assert len(mine) == 1
    assert mine[0]["botId"] == cloned_bot


def test_omitting_the_bot_id_keeps_the_old_guess(cloned_bot: str) -> None:
    """Schedulers and the CLI call this without a card. They must keep the
    suite-name fallback rather than filing everything under nothing."""
    from agent_core.eval.run import run_named_suite

    out = run_named_suite("eval-capability-collections", origin="scheduled")

    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text("SELECT bot_id FROM eval_reports WHERE id = :id"), {"id": out["reportId"]}
            )
        )
    assert row["bot_id"] == "kaia-v2-4"


def _gate(report: dict, gate: str) -> dict:
    return next(g for g in report["gates"] if g["gate"] == gate)


# --- Fleet lifecycle --------------------------------------------------------


def test_a_shipped_card_can_still_be_retired(cloned_bot: str) -> None:
    """Archiving refused while a production deployment was active, but publish
    always leaves one and rollback only swaps which one — so the feature was
    unreachable for every card that had ever shipped."""
    version_id = db.get_agent_studio_card(cloned_bot)["draftVersionId"]
    db.publish_prompt_version(version_id, "ship it")
    assert db.get_active_deployment(bot_id=cloned_bot, environment="production")

    db.archive_agent_studio_card(cloned_bot)

    assert db.get_active_deployment(bot_id=cloned_bot, environment="production") is None
    rows = {c["botId"]: c for c in db.list_agent_studio_cards(include_archived=True)}
    assert rows[cloned_bot]["reachability"] == "archived"


def test_archiving_still_refuses_the_entry_card(cloned_bot: str, monkeypatch) -> None:
    """Dropping the deployment guard must not drop the one that keeps inbound
    traffic resolvable. Pointed at the clone, because the real entry bot is
    first-party and that guard would answer first."""
    monkeypatch.setenv("BOT_ID", cloned_bot)

    with pytest.raises(ValueError, match="entry_card_not_archivable"):
        db.archive_agent_studio_card(cloned_bot)


# --- Autosave ---------------------------------------------------------------


def test_a_draft_patch_rejects_a_bot_id(cloned_bot: str) -> None:
    """PromptVersionPatchRequest forbids extras and a version's bot is not
    patchable. The client shared one body object between create and patch, so
    every autosave PATCH carried botId and came back 422 — the editor showed
    "Autosave failed" and the edit was lost. This pins the contract the client
    now honours by stripping the key.
    """
    from fastapi.testclient import TestClient

    import main

    version_id = db.get_agent_studio_card(cloned_bot)["draftVersionId"]
    client = TestClient(main.app)
    body = {"prompt": "edited", "summary": "draft autosave"}

    assert client.patch(f"/prompt-versions/{version_id}", json=body).status_code == 200
    rejected = client.patch(
        f"/prompt-versions/{version_id}", json={**body, "botId": cloned_bot}
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"][0]["loc"] == ["body", "botId"]


# ---------------------------------------------------------------------------
# JSON responses must state their encoding.
#
# Starlette only appends `charset` to `text/*` media types, so every response
# went out as a bare `application/json`. RFC 8259 makes UTF-8 mandatory for JSON
# exchanged between systems, so that was not wrong -- but a charset nobody
# states is one every client is free to guess, and Windows PowerShell 5.1's
# `Invoke-RestMethod` guesses ISO-8859-1.
#
# The cost was two rounds of a bug hunt. An audit of the skill catalog read the
# three correct UTF-8 bytes of an em dash (E2 80 94) as three ISO-8859-1
# characters (U+00E2 U+0080 U+0094), concluded that a signed first-party pack
# held permanently corrupt text whose contentHash and signature covered the
# corruption, and recommended a repair migration. The database, the disk and the
# wire all held U+2014 throughout; only the reader disagreed.
#
# For a product serving Hindi, Tamil, Telugu, Kannada, Marathi and Bengali, a
# client that silently mangles every non-ASCII character is not a curiosity.
# ---------------------------------------------------------------------------


def test_json_responses_declare_utf8() -> None:
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as client:
        res = client.get("/agent-studio/skills")
    assert res.status_code == 200
    assert "charset=utf-8" in res.headers["content-type"].lower(), (
        "a charset-less application/json response is decoded as ISO-8859-1 by "
        "several mainstream clients, which mangles every non-ASCII character"
    )


def test_a_non_ascii_body_survives_the_round_trip_byte_for_byte() -> None:
    """What the API serves for a first-party pack IS that pack, byte for byte.

    Compares the WHOLE body against the pack on disk rather than probing for one
    character, so corruption in either direction fails here — a mangled decode
    on the way in, a re-encode on the way out, or a stale row that stopped
    matching its own SKILL.md. That is the actual claim the mojibake report
    made, and nothing was asserting it.

    The `.encode("utf-8")` comparison is deliberate: two strings that differ only
    by normalisation form compare equal in some contexts and produce different
    bytes on the wire, and the wire is what the reader gets.
    """
    from pathlib import Path

    from fastapi.testclient import TestClient

    from agent_core.skills.pack import split_skill_md
    import main

    slug = "verify-and-disclose"
    disk_md = (
        Path(main.__file__).resolve().parent
        / "agent_core"
        / "skills"
        / "packs"
        / slug
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    _meta, disk_body = split_skill_md(disk_md)

    em_dash = chr(0x2014)
    assert em_dash in disk_body, "fixture no longer exercises a non-ASCII character"

    with TestClient(main.app) as client:
        served = client.get(f"/agent-studio/skills/{slug}").json()["body"]

    assert served.encode("utf-8") == disk_body.encode("utf-8"), (
        "the served body differs from the pack on disk; compare codepoints, not "
        "rendered text, and check the reader's decoder before concluding the "
        "stored data is corrupt"
    )
    # The specific signature the report chased: a UTF-8 em dash read as
    # ISO-8859-1. Asserted absent by codepoint so no terminal or client encoding
    # sits between the assertion and the truth.
    assert chr(0x00E2) not in served


def test_error_responses_declare_utf8_too() -> None:
    """404s and 422s are JSON, and they carry the strings most likely to be non-ASCII.

    `default_response_class` only covers route responses; FastAPI builds
    HTTPException and validation bodies with its own JSONResponse. Those were
    still going out charset-less after the app default was set, on the path that
    echoes back customer names, KB titles and slugs.
    """
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as client:
        missing = client.get("/agent-studio/skills/definitely-not-a-skill")
        invalid = client.get("/agent-studio/cards?includeArchived=not-a-bool")

    assert missing.status_code == 404
    assert "charset=utf-8" in missing.headers["content-type"].lower()
    assert invalid.status_code == 422
    assert "charset=utf-8" in invalid.headers["content-type"].lower()
