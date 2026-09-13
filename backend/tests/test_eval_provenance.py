"""WS6: an eval report is about content, not a row id.

`prompt_version_id` was the wrong identity in both directions -- a draft
restored from a passed version had no report, and a version edited after its
run kept the green one. `content_key` is the sha256 of what the mouth says
and may do; G7/G8 accept a stored pass by it and refuse a different one.
"""

from __future__ import annotations

import pytest

from agent_core.eval.provenance import content_key


def _key(**over):
    base = dict(
        card={"identity": {"bot_id": "b"}},
        flow={"nodes": []},
        prompt="Be kind.",
        persona={"language": "English", "traits": {"empathy": 50}},
        guardrails={"maxTurns": 12},
        voice={"speed": 1.0},
        tuning={},
        skill_packs=[],
    )
    base.update(over)
    return content_key(**base)


def test_editing_the_persona_changes_the_key() -> None:
    assert _key() == _key()
    assert _key(persona={"language": "Hindi", "traits": {"empathy": 50}}) != _key()
    assert _key(prompt="Be kind. ") == _key(), "whitespace at the edges is not content"


def test_a_cached_pass_reports_its_report_id(db_tx, monkeypatch) -> None:
    """The same content on another row is a pass that says which report it
    is standing on -- never `skipped`."""
    import db
    from agent_core.eval.provenance import content_key_for_version

    published = db.get_published_prompt_version("kaia-v2-4")
    if published is None:
        pytest.skip("no published collections prompt")
    key = content_key_for_version(published)
    suite = db_tx.execute(
        __import__("sqlalchemy").text("SELECT id FROM eval_suites WHERE kind = 'regression' LIMIT 1")
    ).scalar()
    if suite is None:
        pytest.skip("no regression suite")
    db.save_eval_report(
        suite_id=suite, bot_id="kaia-v2-4", status="pass", summary={"failed": 0, "total": 1},
        prompt_version_id=None, content_key=key,
    )
    # G-F14 reads every required kind: a redteam verdict for this version
    # keyed to older content (a platform pack bumped under the published
    # card) is exactly what it exists to flag, so this test files one too.
    redteam = db_tx.execute(
        __import__("sqlalchemy").text("SELECT id FROM eval_suites WHERE kind = 'redteam' LIMIT 1")
    ).scalar()
    if redteam is not None:
        db.save_eval_report(
            suite_id=redteam, bot_id="kaia-v2-4", status="pass", summary={"failed": 0, "total": 1},
            prompt_version_id=published["id"], content_key=key,
        )
    monkeypatch.setenv("EVAL_GATE_ENABLED", "true")
    # Compile the row the report was keyed against. Without the id the
    # compiler takes the newest draft, and a draft left by an editor session
    # has different content and so a different key.
    report = db.compile_agent_studio_card("kaia-v2-4", prompt_version_id=published["id"])
    g7 = next(g for g in report["gates"] if g["gate"] == "G7")
    assert g7["status"] == "pass"
    assert g7["detail"].startswith("cached EVR-")
    gf14 = next(g for g in report["gates"] if g["gate"] == "G-F14")
    assert gf14["status"] in {"pass", "warn"}, gf14


def test_a_report_for_different_content_does_not_open_the_gate(db_tx, monkeypatch) -> None:
    import db

    published = db.get_published_prompt_version("kaia-v2-4")
    if published is None:
        pytest.skip("no published collections prompt")
    suite = db_tx.execute(
        __import__("sqlalchemy").text("SELECT id FROM eval_suites WHERE kind = 'regression' LIMIT 1")
    ).scalar()
    if suite is None:
        pytest.skip("no regression suite")
    # A pass filed against this row id, but for other content.
    db.save_eval_report(
        suite_id=suite, bot_id="kaia-v2-4", status="pass", summary={"failed": 0, "total": 1},
        prompt_version_id=published["id"], content_key="not-this-content",
    )
    monkeypatch.setenv("EVAL_GATE_ENABLED", "true")
    report = db.compile_agent_studio_card(
        "kaia-v2-4", prompt_version_id=published["id"], persona={**published["persona"], "language": "Tamil"}
    )
    gf14 = next(g for g in report["gates"] if g["gate"] == "G-F14")
    assert gf14["status"] == "fail"
