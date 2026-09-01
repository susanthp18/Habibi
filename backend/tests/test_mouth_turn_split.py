"""The prompt/tools split must not have moved anything.

``mouth_turn_state`` answered two unrelated questions in one untyped dict:
which tools a mouth may call, and what skill text belongs in its prompt. It is
now a composition over ``resolve_mouth(...).prompt()`` and ``.tools()``.

The values below were captured by **running the pre-split implementation** at
commit 60cb9b7 against the live collections card, then hashing the two long
strings. They are the oracle: comparing the new seam against the current
``mouth_turn_state`` would compare a function to its own inlined body and could
never fail, which is what an earlier version of this file mistakenly did.

Regenerating, if a deliberate behaviour change ever makes that necessary::

    git show <pre-change-sha>:backend/agent_core/skills/runtime.py

load it as a module and project ``mouth_turn_state`` through ``_project``.
Changing a value here without that provenance means the test has stopped being
an oracle.

No database: pack resolution falls back to the on-disk first-party packs, so
every case runs from the filesystem alone.
"""

from __future__ import annotations

import hashlib

import pytest

from agent_core.cards.defaults import COLLECTIONS_BOT_ID, card_dump
from agent_core.skills.runtime import resolve_mouth

# --- golden values, captured from the pre-split implementation --------------

#: sha256("")[:16] — the empty prefix a cardless mouth produces.
_EMPTY_SHA = "e3b0c44298fc1c14"

_PREFIX_SHA = "6087907ee05c0972"
_PREFIX_LEN = 1506
_PTP_BODY_SHA = "609184e1d6d1522f"

_PACK_SLUGS = [
    "broken-ptp-chase",
    "dispute-capture",
    "doc-fulfil",
    "floor-coach",
    "hardship-intake",
    "ptp-negotiate",
    "upsell-pitch",
    "verify-and-disclose",
]

_ALLOWED = [
    "add_customer_note",
    "capture_lead",
    "capture_nonpayment_reason",
    "check_product_eligibility",
    "create_promise_to_pay",
    "decline_offer",
    "escalate_to_human",
    "evaluate_authority",
    "flag_dispute",
    "get_account_position",
    "get_customer_context",
    "get_emi_schedule",
    "get_payment_history",
    "handoff_to_agent",
    "load_skill",
    "recommend_next_offer",
    "request_callback",
    "request_documents",
    "run_skill_script",
    "search_knowledge_base",
    "set_contact_preference",
    "verify_identity",
]

#: Order is part of the contract — it is the order the model sees the tools in.
_OFFERED_IDLE = [
    "recommend_next_offer",
    "evaluate_authority",
    "load_skill",
    "run_skill_script",
    "verify_identity",
    "get_customer_context",
    "get_account_position",
    "get_payment_history",
    "get_emi_schedule",
    "request_callback",
    "escalate_to_human",
    "handoff_to_agent",
    "search_knowledge_base",
    "add_customer_note",
]

#: The two skill-gated writes ptp-negotiate adds, appended after the idle set.
_OFFERED_WITH_PTP = _OFFERED_IDLE + ["create_promise_to_pay", "capture_nonpayment_reason"]

_CARDLESS = {
    "card_is_none": True,
    "pack_slugs": [],
    "allowed": None,
    "offered": None,
    "prefix_sha": _EMPTY_SHA,
    "prefix_len": 0,
    "active_slug": None,
    "body_role": None,
    "body_sha": None,
}


def _authored(active_slug, offered, body_sha):
    return {
        "card_is_none": False,
        "pack_slugs": _PACK_SLUGS,
        "allowed": _ALLOWED,
        "offered": offered,
        "prefix_sha": _PREFIX_SHA,
        "prefix_len": _PREFIX_LEN,
        "active_slug": active_slug,
        "body_role": None if body_sha is None else "developer",
        "body_sha": body_sha,
    }


GOLDEN = {
    "unauthored-none": (None, {}, _CARDLESS),
    "unauthored-empty": ({}, {}, _CARDLESS),
    "unauthored-with-intent": (None, {"intent": "payment_intent"}, _CARDLESS),
    # An unparseable card reaches the same answer by a different route: the
    # pack resolver fails the identical parse, so no packs survive either.
    "unparseable": ({"identity": "not-an-object"}, {}, _CARDLESS),
    "authored-idle": (
        "CARD",
        {},
        _authored(None, _OFFERED_IDLE, None),
    ),
    "authored-payment-intent": (
        "CARD",
        {"intent": "payment_intent"},
        _authored("ptp-negotiate", _OFFERED_WITH_PTP, _PTP_BODY_SHA),
    ),
    "authored-unknown-intent": (
        "CARD",
        {"intent": "nonsense-intent"},
        _authored(None, _OFFERED_IDLE, None),
    ),
    "authored-active-ptp": (
        "CARD",
        {"active_slug": "ptp-negotiate"},
        _authored("ptp-negotiate", _OFFERED_WITH_PTP, _PTP_BODY_SHA),
    ),
    # A slug the card does not attach resolves to itself but loads no body.
    "authored-active-unattached": (
        "CARD",
        {"active_slug": "not-attached"},
        _authored("not-attached", _OFFERED_IDLE, None),
    ),
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _project(mouth) -> dict:
    """The observable contract of one resolved mouth, in comparable form."""
    prompt = mouth.prompt()
    tools = mouth.tools()
    body = prompt.body_message
    return {
        "card_is_none": mouth.card is None,
        "pack_slugs": sorted(p.slug for p in mouth.packs),
        "allowed": sorted(tools.allowed) if tools.allowed is not None else None,
        "offered": list(tools.offered) if tools.offered is not None else None,
        "prefix_sha": _sha(prompt.prefix),
        "prefix_len": len(prompt.prefix),
        "active_slug": mouth.active_slug,
        "body_role": None if body is None else body["role"],
        "body_sha": None if body is None else _sha(body["content"]),
    }


@pytest.mark.parametrize("case", sorted(GOLDEN), ids=sorted(GOLDEN))
def test_the_split_reproduces_the_pre_change_behaviour(case) -> None:
    card_raw, kwargs, expected = GOLDEN[case]
    if card_raw == "CARD":
        card_raw = card_dump(COLLECTIONS_BOT_ID)
    assert _project(resolve_mouth(card_raw, **kwargs)) == expected


# --- what the split is for --------------------------------------------------


def test_prompt_needs_no_tool_facts() -> None:
    """The point of the split: asking for prompt text computes no tool sets."""
    prompt = resolve_mouth(card_dump(COLLECTIONS_BOT_ID), intent="payment_intent").prompt()
    assert prompt.prefix.startswith("## Skills")
    assert prompt.body_message is not None, "payment_intent activates ptp-negotiate"


def test_tools_assemble_no_prompt_text() -> None:
    tools = resolve_mouth(card_dump(COLLECTIONS_BOT_ID), intent="payment_intent").tools()
    assert tools.has_grant
    assert tools.offered is not None and "load_skill" in tools.offered


def test_the_grant_is_frozen() -> None:
    """ADR-0001: a caller holding a mutable set can union onto it. Six formulas
    is what that produced, so the grant leaves its owner immutable."""
    allowed = resolve_mouth(card_dump(COLLECTIONS_BOT_ID)).tools().allowed
    assert isinstance(allowed, frozenset)


def test_has_grant_is_the_only_reading_of_the_sentinel() -> None:
    """A cardless mouth has no grant; an authored one has. Callers ask this
    instead of testing ``allowed is not None``, so the deny-all ticket changes
    one branch rather than four call sites."""
    assert resolve_mouth({}).tools().has_grant is False
    assert resolve_mouth(card_dump(COLLECTIONS_BOT_ID)).tools().has_grant is True


def test_both_questions_come_off_one_resolution() -> None:
    mouth = resolve_mouth(card_dump(COLLECTIONS_BOT_ID), intent="payment_intent")
    assert mouth.packs, "sanity: the collections card attaches packs"
    assert mouth.prompt() == mouth.prompt()
    assert mouth.tools() == mouth.tools()


# --- fail-closed, at the new seam -------------------------------------------
#
# tests/test_skill_packs_fail_closed.py pins this through the legacy dict. That
# suite is deliberately untouched, which leaves the replacement path uncovered
# — so the same property is pinned here too, and the shim can be deleted
# without losing it.


def test_a_pack_resolution_failure_denies_gated_writes_at_the_new_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_core.skills.pack as pack_mod
    import agent_core.skills.persist as skills_persist
    from agent_core.skills.intersect import SKILL_GATED_TOOLS

    def _db_boom(_slugs):
        raise RuntimeError("connection reset by peer")

    def _disk_boom(slug: str):
        raise AssertionError(f"on-disk default consulted for {slug!r} after a DB failure")

    monkeypatch.setattr(skills_persist, "packs_for_slugs", _db_boom)
    monkeypatch.setattr(pack_mod, "pack_for_slug", _disk_boom)

    mouth = resolve_mouth(card_dump(COLLECTIONS_BOT_ID), intent="payment_intent")
    assert mouth.packs == ()
    allowed = mouth.tools().allowed

    # Not "nothing is allowed" — reads are ungated and stay. The property is
    # that every skill-gated write is gone.
    assert allowed is not None
    assert "create_promise_to_pay" not in allowed
    assert not (set(allowed) & SKILL_GATED_TOOLS)
