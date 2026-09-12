"""A pack's declared surface is intersected with the mouth's actual one.

Two leaks of one shape. A pack's frontmatter names the mouths it belongs on
and nothing read it, so ``floor-coach`` (``mouth: [internal]``) was named in
the skill prefix of every customer-facing collections call. And ``load_skill``
answered with the pack's whole ``allowed-tools`` list, un-intersected with the
turn's grant, so the model was told to call tools the executor would refuse.

No database and no fixtures: both functions under test are pure, and the
first-party packs on disk are the corpus that made the defect real.
"""

from dataclasses import replace

from agent_core.skills.defaults import CARD_SKILLS
from agent_core.skills.pack import pack_for_slug
from agent_core.skills.runtime import load_skill, packs_on_card_channels


def _packs(bot_id: str):
    return [pack_for_slug(slug) for slug in CARD_SKILLS[bot_id]]


def test_an_internal_pack_does_not_ride_a_customer_facing_card():
    packs = _packs("kaia-v2-4")
    slugs = {p.slug for p in packs}
    # The attachment itself is unchanged — this is a runtime filter, not a
    # re-authoring of CARD_SKILLS, so the supervisor tooling still sees it.
    assert "floor-coach" in slugs

    kept = {p.slug for p in packs_on_card_channels(packs, ["voice", "whatsapp"])}
    assert "floor-coach" not in kept
    # Exactly one pack goes. broken-ptp-chase and doc-fulfil declare
    # ``[internal, whatsapp]`` and overlap, so they stay.
    assert kept == slugs - {"floor-coach"}


def test_an_internal_card_keeps_its_internal_packs():
    """The supervisor card declares ``channels=["internal"]`` (cards/defaults)."""
    packs = _packs("supervisor-brief")
    kept = packs_on_card_channels(packs, ["internal"])
    assert {p.slug for p in kept} == {p.slug for p in packs}


def test_a_pack_that_declares_no_mouth_rides_anywhere():
    """Every tenant-authored pack is this case, so the filter cannot disable one."""
    unscoped = replace(pack_for_slug("ptp-negotiate"), mouth=[])
    assert packs_on_card_channels([unscoped], ["voice"]) == [unscoped]


def test_load_skill_announces_only_what_the_grant_allows():
    pack = pack_for_slug("ptp-negotiate")
    assert pack.allowed_tools, "the pack under test must declare tools"

    ungated = set(load_skill(pack.slug, [pack])["allowed_tools"])
    assert ungated, "no grant supplied is the Studio preview — today's answer"

    granted = {sorted(ungated)[0]}
    out = load_skill(pack.slug, [pack], allowed=granted)
    assert out["ok"] is True
    assert set(out["allowed_tools"]) == granted

    # A turn with no grant refuses every tool at execute time, so the reply
    # must not advertise any. This is the case bot_tools passes frozenset()
    # for rather than None.
    assert load_skill(pack.slug, [pack], allowed=frozenset())["allowed_tools"] == []


def test_reverting_to_an_older_signed_version_reaches_the_mouth(db_tx):
    """``revert_skill`` moves ``skills.latest_version_id``; resolution must follow.

    It did not — ``_latest_signed_version`` ordered by ``created_at`` alone, so
    the Studio showed the reverted version while every turn kept loading the
    newest signed row. The same ordering is why an exact version pin read as
    decorative.
    """
    import pytest
    from sqlalchemy import text

    import db
    from agent_core.skills.persist import _latest_signed_version

    slug = "ptp-negotiate"
    with db.engine.connect() as conn:
        signed = db._rows(
            conn.execute(
                text(
                    """
                    SELECT sv.id
                      FROM skills s
                      JOIN skill_versions sv ON sv.skill_id = s.id
                     WHERE s.tenant_id = :t AND s.slug = :s AND sv.status = 'signed'
                     ORDER BY sv.created_at DESC
                    """
                ),
                {"t": db._tenant(), "s": slug},
            )
        )
    if len(signed) < 2:
        pytest.skip(f"{slug} needs two signed versions to tell the orderings apart")

    older = signed[-1]["id"]
    assert older != signed[0]["id"]
    with db.engine.begin() as conn:
        conn.execute(
            text("UPDATE skills SET latest_version_id = :v WHERE tenant_id = :t AND slug = :s"),
            {"v": older, "t": db._tenant(), "s": slug},
        )

    with db.engine.connect() as conn:
        assert _latest_signed_version(conn, slug=slug)["id"] == older
