"""Skill catalog CRUD guards.

``upsert_skill_from_pack`` keys on (tenant_id, slug) and resets
``signature_status``, so *creating* over an existing slug silently unsigned a
first-party pack and replaced its body — and cloning twice produced one slug, so
the second clone overwrote the first. Delete did not exist at all.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import db
from agent_core.skills.persist import (
    clone_skill,
    create_draft_skill,
    delete_skill,
    get_skill,
    unique_slug,
)


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
    slug = f"t-{uuid.uuid4().hex[:8]}"
    yield slug
    _cleanup(slug, f"{slug}-clone", f"{slug}-clone-2")


def test_create_rejects_an_existing_slug(db_tx) -> None:
    before = get_skill("skill-verify-and-disclose")
    assert before is not None and before["signed"]
    with pytest.raises(ValueError, match="skill_slug_taken"):
        create_draft_skill({"slug": "verify-and-disclose", "description": "hijack"})
    after = get_skill("skill-verify-and-disclose")
    assert after["signed"], "a rejected create must not unsign the existing pack"
    assert after["description"] == before["description"]


@pytest.mark.parametrize("bad", ["Not A Slug", "trailing-", "-leading", "under_score", ""])
def test_create_rejects_malformed_slugs(db_tx, bad: str) -> None:
    with pytest.raises(ValueError):
        create_draft_skill({"slug": bad, "description": "x"})


def test_create_then_delete(scratch_slug: str) -> None:
    created = create_draft_skill({"slug": scratch_slug, "description": "scratch"})
    assert created["slug"] == scratch_slug
    assert not created["signed"]
    delete_skill(created["id"])
    assert get_skill(created["id"]) is None


def test_delete_refuses_first_party(db_tx) -> None:
    # Re-seeded on API boot, so deleting one only looks like it worked.
    with pytest.raises(ValueError, match="skill_first_party_not_deletable"):
        delete_skill("skill-verify-and-disclose")
    assert get_skill("skill-verify-and-disclose") is not None


def test_cloning_twice_does_not_overwrite_the_first_clone(scratch_slug: str) -> None:
    source = create_draft_skill({"slug": scratch_slug, "description": "source"})
    first = clone_skill(source["id"])
    second = clone_skill(source["id"])
    assert first["slug"] != second["slug"]
    assert get_skill(first["id"]) is not None
    delete_skill(first["id"])
    delete_skill(second["id"])
    delete_skill(source["id"])


def test_clone_rejects_a_taken_slug(scratch_slug: str) -> None:
    source = create_draft_skill({"slug": scratch_slug, "description": "source"})
    with pytest.raises(ValueError, match="skill_slug_taken"):
        clone_skill(source["id"], "verify-and-disclose")
    assert get_skill("skill-verify-and-disclose")["signed"]
    delete_skill(source["id"])


def test_unique_slug_skips_taken_names(db_tx) -> None:
    assert unique_slug("verify-and-disclose") == "verify-and-disclose-2"


def test_a_draft_attachment_is_rehearsable_but_not_counted_as_live(db_tx) -> None:
    """Two questions, two answers, deliberately not one column.

    `attachedCards` answers "who is live on this skill" — the number an operator
    reads before deleting or re-signing one, which drafts would inflate.
    `rehearsalCards` answers "which card can rehearse it", and a draft is the
    common case: a tenant skill still being authored has no published version
    anywhere, so the sandbox button fell back to `kaia-v2-4` and rehearsed a
    card that does not carry the skill being edited.
    """
    from sqlalchemy import text as _text

    from agent_core.skills.persist import list_skills

    slug = "ptp-negotiate"
    before = next(s for s in list_skills() if s["slug"] == slug)

    draft_pv = db_tx.execute(
        _text(
            """
            SELECT id, bot_id FROM prompt_versions
             WHERE status = 'draft' AND agent_card IS NOT NULL
             LIMIT 1
            """
        )
    ).mappings().first()
    if not draft_pv:
        pytest.skip("no draft prompt version to attach to")

    version_id = db_tx.execute(
        _text("SELECT id FROM skill_versions WHERE skill_id = (SELECT id FROM skills WHERE slug = :s)"),
        {"s": slug},
    ).scalar()
    db_tx.execute(
        _text(
            """
            INSERT INTO skill_attachments (prompt_version_id, skill_version_id)
            VALUES (:pv, :sv) ON CONFLICT DO NOTHING
            """
        ),
        {"pv": draft_pv["id"], "sv": version_id},
    )

    after = next(s for s in list_skills() if s["slug"] == slug)
    assert draft_pv["bot_id"] in after["rehearsalCards"]
    # The live count is unchanged: a draft is not a consumer.
    assert sorted(after["attachedCards"]) == sorted(before["attachedCards"])
