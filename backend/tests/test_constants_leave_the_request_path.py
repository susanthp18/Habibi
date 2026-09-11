"""The four first-party Agent Cards are seed data, not runtime authorities.

`agent_core.cards.defaults` builds the shipped cards as Python objects. They
are seeded into `prompt_versions` and edited in the Studio from then on; the
published row is the card the compiler gated and the card a regulator is shown.
For months three request paths read the constant instead -- the voice handoff
allowlist, the mission envelope for a bot with no published version, the ops
floor's display name -- so a target removed in the Studio was still reachable
on the phone, and a card could be edited, published and change nothing.

This file pins the boundary: nothing on a request path imports the constants,
and the one-time seed is the only thing that does.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

#: Modules that serve a call, a message or a dial. None may reach for the
#: constants; a bot with no published card gets no card.
_REQUEST_PATH = (
    "voice/bot.py",
    "voice/tools.py",
    "voice/flows_dynamic.py",
    "bot_runtime.py",
    "bot_tools.py",
    "mission.py",
    "cadence.py",
    "campaigns.py",
    "outbound.py",
    "ops_screens.py",
    "agent_core/tools/handoff_allowlist.py",
    "agent_core/tools/domain.py",
    "agent_core/deployment.py",
    "agent_core/treatment/enact.py",
)


def _imports_defaults(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("agent_core.cards.defaults"):
            hits.append(node.lineno)
        elif isinstance(node, ast.Import) and any(a.name.startswith("agent_core.cards.defaults") for a in node.names):
            hits.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module == "agent_core.cards":
            if any(a.name in {"card_for", "card_dump"} for a in node.names):
                hits.append(node.lineno)
    return hits


@pytest.mark.parametrize("rel", _REQUEST_PATH)
def test_no_request_path_module_reads_the_card_constants(rel: str) -> None:
    hits = _imports_defaults(BACKEND / rel)
    assert not hits, f"{rel} imports agent_core.cards.defaults at lines {hits}"


def test_a_bot_with_no_published_card_has_no_card(monkeypatch) -> None:
    import mission

    assert mission.card_for_bot("no-such-bot-anywhere") is None


def test_the_allowlist_denies_when_the_bundle_carries_no_card() -> None:
    from agent_core.tools.handoff_allowlist import handoff_allowlist, handoff_routes

    assert handoff_allowlist(agent_card=None, bot_id="kaia-v2-4") == set()
    assert handoff_routes(agent_card=None, bot_id="kaia-v2-4") == []


def test_intent_activation_is_authored_on_the_pack() -> None:
    """`resolve_intent_skill` reads `metadata.intents` from the packs the card
    carries; there is no module-level map to consult."""
    from agent_core.skills import runtime
    from agent_core.skills.pack import parse_skill_md

    assert not hasattr(runtime, "INTENT_TO_SKILL")
    pack = parse_skill_md(
        "---\nname: tenant-own\ndescription: x\nallowed-tools: []\n"
        "metadata:\n  intents:\n    - hardship\n---\nbody\n"
    )
    assert pack.intents == ["hardship"]
    assert runtime.resolve_intent_skill("hardship", [pack]) is pack
    assert runtime.resolve_intent_skill("hardship", []) is None
    assert runtime.resolve_intent_skill("dispute", [pack]) is None


def test_the_shipped_packs_still_activate_on_their_intents() -> None:
    from agent_core.skills import runtime
    from agent_core.skills.pack import load_pack_dir

    packs = [load_pack_dir(d) for d in sorted((BACKEND / "agent_core/skills/packs").iterdir()) if d.is_dir()]
    by_intent = {
        "hardship": "hardship-intake",
        "dispute": "dispute-capture",
        "payment_intent": "ptp-negotiate",
        "waiver_request": "ptp-negotiate",
        "upsell_opportunity": "upsell-pitch",
        "product_faq": "insurance-lapse",
        "balance_query": "verify-and-disclose",
    }
    for intent, slug in by_intent.items():
        hit = runtime.resolve_intent_skill(intent, packs)
        assert hit is not None and hit.slug == slug, intent


def test_rupees_read_the_indian_way_on_every_borrower_facing_line() -> None:
    import mission
    import promise_fulfillment as pf

    assert pf._fmt_inr(1234567) == "12,34,567"
    assert pf._fmt_inr("1500.50") == "1,500.50"
    assert mission._inr(1234567) == "12,34,567"


def test_the_account_tail_is_digits_on_the_desk_too() -> None:
    from agent_core.context import account_tail
    from db_core import _account_tail

    assert _account_tail("AC-SUSANTH") is None
    assert _account_tail("AC-77410") == "7410"
    assert account_tail("AC-SUSANTH") is None
