"""A database blip must not re-grant tools a tenant removed.

``skills/runtime.packs_from_card`` is the per-turn entry point: whatever it
returns becomes the pack set that ``intersect.effective_tools`` intersects the
catalog against, so it is the thing standing between the model and
``create_promise_to_pay``. It asked the DB for the tenant's *signed* packs and,
on any exception, fell through to the **unsigned** on-disk platform defaults
with ``except Exception: pass``.

That is the wrong direction to fail. A tenant whose signed pack removes a tool
had it back for the duration of the outage, and because nothing was logged
there was no trace afterwards that the grant had ever widened.

The disk packs are still the right answer when the DB simply has no signed
version for a slug — that is not a failure, it is a first-party bot — so the
last two tests pin that path down as well.
"""

from __future__ import annotations

import logging

import pytest

from agent_core.cards.defaults import COLLECTIONS_BOT_ID, card_dump
from agent_core.skills import runtime


def _card() -> dict:
    return card_dump(COLLECTIONS_BOT_ID)


def _never_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the on-disk fallback loud instead of silent."""
    import agent_core.skills.pack as pack_mod

    def _boom(slug: str):
        raise AssertionError(f"on-disk default consulted for {slug!r} after a DB failure")

    monkeypatch.setattr(pack_mod, "pack_for_slug", _boom)


def _db_raises(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    import agent_core.skills.persist as skills_persist

    def _boom(_slugs):
        raise exc

    monkeypatch.setattr(skills_persist, "packs_for_slugs", _boom)


def test_db_failure_returns_no_packs_and_never_reads_disk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _db_raises(monkeypatch, RuntimeError("connection reset by peer"))
    _never_disk(monkeypatch)
    assert runtime.packs_from_card(_card()) == []


def test_db_failure_is_logged_with_the_slugs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Silent was half the defect — an operator has to be able to see this."""
    _db_raises(monkeypatch, RuntimeError("connection reset by peer"))
    _never_disk(monkeypatch)
    with caplog.at_level(logging.ERROR, logger=runtime.__name__):
        runtime.packs_from_card(_card())
    records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert records, "a DB failure loading skill packs must be logged at ERROR"
    assert "ptp-negotiate" in records[0].getMessage()
    assert records[0].exc_info is not None


def test_the_turn_state_denies_rather_than_reverting_to_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the fix is for: no packs means the gated-write filter denies."""
    _db_raises(monkeypatch, RuntimeError("connection reset by peer"))
    _never_disk(monkeypatch)
    state = runtime.mouth_turn_state(_card(), intent="payment_intent")
    assert state["packs"] == []
    # Not "nothing is allowed" — reads are ungated and stay. The property is
    # that every skill-gated *write* is gone, which is what the disk fallback
    # used to hand back.
    from agent_core.skills.intersect import SKILL_GATED_TOOLS

    allowed = set(state["allowed"] or [])
    assert "create_promise_to_pay" not in allowed
    assert not (allowed & SKILL_GATED_TOOLS)
    assert state["active_slug"] is None
    assert state["body_message"] is None


def test_disk_packs_still_serve_when_the_db_simply_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty result is not a failure — first-party bots live on disk."""
    import agent_core.skills.persist as skills_persist

    monkeypatch.setattr(skills_persist, "packs_for_slugs", lambda _slugs: [])
    packs = runtime.packs_from_card(_card())
    assert {p.slug for p in packs} >= {"ptp-negotiate", "verify-and-disclose"}


def test_signed_db_packs_are_preferred_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half — the DB path is still the one that wins."""
    import agent_core.skills.persist as skills_persist
    from agent_core.skills.pack import pack_for_slug

    only = pack_for_slug("ptp-negotiate")
    monkeypatch.setattr(skills_persist, "packs_for_slugs", lambda _slugs: [only])
    assert [p.slug for p in runtime.packs_from_card(_card())] == ["ptp-negotiate"]


# --- a signed row that will not parse ---------------------------------------
#
# The sibling of the defect above, one layer down. ``packs_for_slugs`` reads the
# latest *signed* version per slug and lets the on-disk platform pack fill any
# slug the DB has nothing for — correct, because a first-party bot the tenant
# never edited genuinely has no DB row.
#
# A signed row that exists but fails to parse is not "nothing for that slug".
# It was treated as one: the parse failure was logged and then the loop fell
# through to ``pack_for_slug(slug)``, so platform-default content was served
# under the tenant's slug, re-granting whatever writes their signed pack had
# removed — while the corrupt row stayed in the DB, invisible.


def _corrupt_row() -> dict:
    """A signed version row whose frontmatter lost its ``name``.

    ``parse_skill_md`` raises ``skill_missing_name`` on it, which is exactly
    the shape of failure the ``except Exception`` was written for.
    """
    return {
        "id": "sv-corrupt",
        "skill_id": "sk-corrupt",
        "version": "3",
        "status": "signed",
        "frontmatter": {"description": "truncated write", "allowed-tools": []},
        "body": "",
        "allowed_tools": [],
        "content_hash": "0" * 64,
        "signature": None,
        "signed_by": None,
        "pack": {},
        "origin": "tenant",
        "slug": "ptp-negotiate",
    }


def _one_corrupt_signed_row(monkeypatch: pytest.MonkeyPatch) -> None:
    import agent_core.skills.persist as skills_persist

    monkeypatch.setattr(
        skills_persist,
        "_latest_signed_version",
        lambda _conn, skill_id=None, slug=None: _corrupt_row() if slug == "ptp-negotiate" else None,
    )


def test_a_corrupt_signed_pack_drops_the_slug_instead_of_substituting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_core.skills.persist as skills_persist

    _one_corrupt_signed_row(monkeypatch)
    packs = skills_persist.packs_for_slugs(["ptp-negotiate"])
    assert [p.slug for p in packs] == []


def test_a_corrupt_signed_pack_does_not_consult_the_disk_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_core.skills.persist as skills_persist

    _one_corrupt_signed_row(monkeypatch)
    _never_disk(monkeypatch)
    assert skills_persist.packs_for_slugs(["ptp-negotiate"]) == []


def test_a_corrupt_slug_does_not_take_its_healthy_neighbours_with_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the unparseable slug is skipped; a slug with no DB row still loads."""
    import agent_core.skills.persist as skills_persist

    _one_corrupt_signed_row(monkeypatch)
    packs = skills_persist.packs_for_slugs(["ptp-negotiate", "verify-and-disclose"])
    assert [p.slug for p in packs] == ["verify-and-disclose"]


def test_the_corrupt_pack_is_still_logged_with_its_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import agent_core.skills.persist as skills_persist

    _one_corrupt_signed_row(monkeypatch)
    with caplog.at_level(logging.ERROR, logger=skills_persist.__name__):
        skills_persist.packs_for_slugs(["ptp-negotiate"])
    records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert records, "a corrupt signed pack must stay visible to an operator"
    assert "ptp-negotiate" in records[0].getMessage()
    assert records[0].exc_info is not None


def test_the_turn_state_denies_writes_for_a_corrupt_signed_pack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: substituted content must not reach the gated-write filter.

    Only the corrupt slug drops, so the other packs keep granting their own
    writes — the property is that nothing the *substituted* pack would have
    granted, and nobody else does, survives into ``allowed``.
    """
    from agent_core.skills.intersect import SKILL_GATED_TOOLS
    from agent_core.skills.pack import pack_for_slug

    substituted = set(pack_for_slug("ptp-negotiate").allowed_tools) & SKILL_GATED_TOOLS
    _one_corrupt_signed_row(monkeypatch)
    state = runtime.mouth_turn_state(_card(), intent="payment_intent")
    assert "ptp-negotiate" not in {p.slug for p in state["packs"]}

    allowed = set(state["allowed"] or [])
    granted_elsewhere = {t for p in state["packs"] for t in p.allowed_tools}
    only_from_the_substitute = substituted - granted_elsewhere
    assert only_from_the_substitute, "sanity: the disk pack must grant something exclusive"
    assert "create_promise_to_pay" in only_from_the_substitute
    assert not (allowed & only_from_the_substitute)
