"""Skill catalog ops — boot-sync, draft save, sign, revert, production attach."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from agent_core.skills.pack import iter_first_party_packs
from agent_core.skills.persist import (
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


def test_save_draft_does_not_clobber_signed_version(skills_ready) -> None:
    ensure_first_party_skills()
    ptp = get_skill("ptp-negotiate")
    assert ptp is not None
    signed_hash = ptp["contentHash"]
    patched = patch_skill(ptp["id"], {"body": "# draft\nDo not clobber production.\n"})
    assert patched["signatureStatus"] == "unsigned"
    assert patched["status"] == "draft"
    versions = patched["versions"]
    signed_rows = [v for v in versions if v["status"] == "signed"]
    assert signed_rows
    assert any(v["contentHash"] == signed_hash for v in signed_rows)
    prod = packs_for_slugs(["ptp-negotiate"])
    assert prod and prod[0].signed
    assert "Do not clobber production" not in prod[0].body


def test_revert_restores_signed_as_latest(skills_ready) -> None:
    ensure_first_party_skills()
    ptp = get_skill("ptp-negotiate")
    assert ptp is not None
    patch_skill(ptp["id"], {"body": "# draft\nscratch\n"})
    restored = revert_skill(ptp["id"])
    assert restored["signatureStatus"] == "signed"
    assert restored["signed"] is True
    assert "scratch" not in (restored.get("body") or "")


def test_sign_draft_does_not_overwrite_v1(skills_ready) -> None:
    ensure_first_party_skills()
    ptp = get_skill("ptp-negotiate")
    assert ptp is not None
    v1 = next(v for v in ptp["versions"] if v["status"] == "signed")
    patched = patch_skill(ptp["id"], {"body": "# draft\nnew talk track\n"})
    signed = sign_skill(patched["id"])
    still_v1 = next(v for v in signed["versions"] if v["id"] == v1["id"])
    assert still_v1["status"] == "signed"
    assert still_v1["contentHash"] == v1["contentHash"]
    latest = next(v for v in signed["versions"] if v["id"] == signed["latestVersionId"])
    assert latest["status"] == "signed"
    assert latest["id"] != v1["id"]
