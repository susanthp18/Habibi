"""Skill catalog ops — boot-sync, draft save, sign, revert, production attach."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from agent_core.skills.pack import iter_first_party_packs
from agent_core.skills.persist import (
    clone_skill,
    ensure_first_party_skills,
    get_skill,
    list_skills,
    packs_for_slugs,
    patch_skill,
    revert_skill,
    sign_skill,
)


def _table_exists(db_tx, name: str) -> bool:
    row = db_tx.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=:n"),
        {"n": name},
    ).first()
    return row is not None


@pytest.fixture
def skills_ready(db_tx):
    if not _table_exists(db_tx, "skills"):
        pytest.skip("skills tables not migrated")
    return db_tx


def test_ensure_first_party_does_not_disable_catalog(skills_ready) -> None:
    stats = ensure_first_party_skills()
    expected = {p.slug for p in iter_first_party_packs()}
    assert stats["created"] + stats["refreshed"] >= len(expected)
    listed = list_skills(_synced=True)
    slugs = {s["slug"] for s in listed}
    assert slugs >= expected
    assert all(s["hasSignedVersion"] for s in listed if s["origin"] == "first_party")


def _signed_tenant_skill() -> dict:
    """A tenant-owned, signed skill: the only kind an editor may draft on.

    First-party packs are not patched in place (AUTHZ-19) -- the lifecycle
    under test runs on a clone, which is what the Studio's clone-first model
    asks of an operator."""
    ensure_first_party_skills()
    ptp = get_skill("ptp-negotiate")
    assert ptp is not None
    return sign_skill(clone_skill(ptp["id"], "ptp-tenant")["id"])


def test_a_first_party_skill_is_cloned_not_patched(skills_ready) -> None:
    """PATCH + sign on a platform pack used to replace it for every card that
    names the slug; delete already refused, patch now does too."""
    ensure_first_party_skills()
    ptp = get_skill("ptp-negotiate")
    assert ptp is not None
    with pytest.raises(ValueError, match="skill_first_party"):
        patch_skill(ptp["id"], {"body": "# not yours\n"})
    assert get_skill("ptp-negotiate")["body"] == ptp["body"]


def test_save_draft_does_not_clobber_signed_version(skills_ready) -> None:
    mine = _signed_tenant_skill()
    signed_hash = mine["contentHash"]
    patched = patch_skill(mine["id"], {"body": "# draft\nDo not clobber production.\n"})
    assert patched["signatureStatus"] == "unsigned"
    assert patched["status"] == "draft"
    versions = patched["versions"]
    signed_rows = [v for v in versions if v["status"] == "signed"]
    assert signed_rows
    assert any(v["contentHash"] == signed_hash for v in signed_rows)
    prod = packs_for_slugs([mine["slug"]])
    assert prod and prod[0].signed
    assert "Do not clobber production" not in prod[0].body


def test_revert_restores_signed_as_latest(skills_ready) -> None:
    mine = _signed_tenant_skill()
    patch_skill(mine["id"], {"body": "# draft\nscratch\n"})
    restored = revert_skill(mine["id"])
    assert restored["signatureStatus"] == "signed"
    assert restored["signed"] is True
    assert "scratch" not in (restored.get("body") or "")


def test_sign_draft_does_not_overwrite_v1(skills_ready) -> None:
    mine = _signed_tenant_skill()
    v1 = next(v for v in mine["versions"] if v["status"] == "signed")
    patched = patch_skill(mine["id"], {"body": "# draft\nnew talk track\n"})
    signed = sign_skill(patched["id"])
    still_v1 = next(v for v in signed["versions"] if v["id"] == v1["id"])
    assert still_v1["status"] == "signed"
    assert still_v1["contentHash"] == v1["contentHash"]
    latest = next(v for v in signed["versions"] if v["id"] == signed["latestVersionId"])
    assert latest["status"] == "signed"
    assert latest["id"] != v1["id"]
