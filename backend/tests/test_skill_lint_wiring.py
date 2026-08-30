"""The skill linter was dead code.

``agent_core.skills.lint.lint_pack`` existed and was never called — only its
``CATALOG_PREFIX_TOKEN_CAP`` constant was imported anywhere. So every write into
the skill catalog (``POST /agent-studio/skills``, the editor PATCH, the .md/.zip
import, gardener drafts) accepted allowed-tools that are not in the catalog and
descriptions well over the prefix cap. An unknown tool cannot be intersected
with a card's tool set, so the draft was guaranteed to fail G9 at compile time —
the rejection just arrived far too late to be actionable.

Blocking findings are ``unknown_tools`` and ``malformed_tool_name``. Everything
else rides along as a warning: an over-long description is worth telling the
author about, not worth losing their work over.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import db
from agent_core.skills.lint import assert_pack_lints
from agent_core.skills.pack import iter_first_party_packs, parse_skill_md
from agent_core.skills.persist import (
    create_draft_skill,
    get_skill,
    slug_exists,
    upsert_skill_from_pack,
)

LONG_DESCRIPTION = "restate the borrower position in plain language " * 20


def _cleanup(*slugs: str) -> None:
    with db.engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id FROM skills WHERE tenant_id = :t AND slug = ANY(:s)"),
            {"t": db._tenant(), "s": list(slugs)},
        ).fetchall()
        for (sid,) in rows:
            conn.execute(text("UPDATE skills SET latest_version_id = NULL WHERE id = :i"), {"i": sid})
            conn.execute(text("DELETE FROM skill_versions WHERE skill_id = :i"), {"i": sid})
            conn.execute(text("DELETE FROM skills WHERE id = :i"), {"i": sid})


@pytest.fixture
def scratch_slug(db_tx):
    slug = f"lint-{uuid.uuid4().hex[:8]}"
    yield slug
    _cleanup(slug)


def _pack_md(slug: str, tools: list[str], description: str = "a scratch skill") -> str:
    tool_lines = "\n".join(f"  - {t}" for t in tools) or "  []"
    allowed = f"allowed-tools:\n{tool_lines}" if tools else "allowed-tools: []"
    return f"---\nname: {slug}\ndescription: {description}\n{allowed}\n---\n\n# {slug}\n"


def test_create_rejects_a_tool_the_catalog_does_not_have(db_tx, scratch_slug: str) -> None:
    with pytest.raises(ValueError, match="unknown_tools"):
        create_draft_skill(
            {
                "slug": scratch_slug,
                "description": "scratch",
                "allowedTools": ["wire_the_money_somewhere"],
            }
        )
    assert not slug_exists(scratch_slug), "a rejected create must not leave a row"


def test_create_rejects_a_malformed_tool_name(db_tx, scratch_slug: str) -> None:
    with pytest.raises(ValueError, match="malformed_tool_name"):
        create_draft_skill(
            {
                "slug": scratch_slug,
                "description": "scratch",
                "allowedTools": ["create promise to pay"],
            }
        )
    assert not slug_exists(scratch_slug)


def test_an_over_cap_description_warns_but_still_persists(db_tx, scratch_slug: str) -> None:
    created = create_draft_skill(
        {
            "slug": scratch_slug,
            "description": LONG_DESCRIPTION,
            "allowedTools": ["get_customer_context"],
        }
    )

    codes = {w["code"] for w in created.get("lintWarnings") or []}
    assert "description_too_long" in codes, "the author was told nothing"
    assert get_skill(created["id"]) is not None, "a warning must not drop the write"


def test_a_valid_pack_is_unaffected(db_tx, scratch_slug: str) -> None:
    created = create_draft_skill(
        {
            "slug": scratch_slug,
            "description": "Read the account position and leave one note.",
            "allowedTools": ["get_customer_context", "add_customer_note"],
        }
    )

    assert "lintWarnings" not in created
    assert set(created["allowedTools"]) == {"get_customer_context", "add_customer_note"}


def test_upsert_from_pack_rejects_unknown_tools(db_tx, scratch_slug: str) -> None:
    """The import and gardener paths do not go through ``create_draft_skill``."""
    pack = parse_skill_md(_pack_md(scratch_slug, ["definitely_not_a_tool"]), slug_hint=scratch_slug)
    pack.origin = "tenant"
    pack.signed = False

    with pytest.raises(ValueError, match="unknown_tools"):
        upsert_skill_from_pack(pack, origin="tenant", signed=False)
    assert not slug_exists(scratch_slug)


def test_upsert_from_pack_accepts_a_catalog_pack(db_tx, scratch_slug: str) -> None:
    pack = parse_skill_md(_pack_md(scratch_slug, ["verify_identity"]), slug_hint=scratch_slug)
    pack.origin = "tenant"
    pack.signed = False

    saved = upsert_skill_from_pack(pack, origin="tenant", signed=False)

    assert saved["slug"] == scratch_slug
    assert saved["allowedTools"] == ["verify_identity"]


def test_every_first_party_pack_passes_the_linter() -> None:
    """Seeding runs through the same choke point — it must not reject itself."""
    packs = iter_first_party_packs()
    assert packs, "no first-party packs found"
    for pack in packs:
        assert_pack_lints(pack)
