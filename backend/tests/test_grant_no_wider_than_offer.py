"""Agent Studio MINOR cluster 2: the grant is never wider than the offer.

CONNECTORS-2/11/13/15/17 and TOOLS-7 were one shape: a name the executor
would run that nothing had deliberately offered -- an `ext.*` tool in the
grant and in no pack, a prefix the registry had since narrowed, a connector
bound to the sandbox dispatching in production, `load_skill` on a card with
no skills. Enforcement moved to the point of execution and to the bind.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from agent_core.cards.defaults import COLLECTIONS_BOT_ID, card_dump
from agent_core.connectors import persist as cp
from agent_core.skills.pack import pack_for_slug
from agent_core.skills.runtime import resolve_mouth

PAYLINK = "ext.paylink.get_status"


def _connector(**over) -> dict:
    return {
        "id": "conn-paylink",
        "slug": "paylink",
        "kind": "first_party",
        "status": "approved",
        "allowedEnv": "both",
        "allowPrefixes": ["ext.paylink."],
        "circuitOpenedAt": None,
        **over,
    }


def _mouth(*, frozen, packs=None):
    mouth = resolve_mouth(card_dump(COLLECTIONS_BOT_ID), frozen_connector_tools=frozen)
    return mouth if packs is None else replace(mouth, packs=tuple(packs))


def test_an_ext_tool_is_granted_only_through_a_pack_that_offers_it() -> None:
    """CONNECTORS-17: the frozen connector tools sat in the grant while the
    idle offer stripped every `ext.*` name -- executable on a name the model
    was never shown, and around skill gating."""
    state = _mouth(frozen=[PAYLINK], packs=[]).tools()
    assert PAYLINK not in state.allowed

    pack = replace(pack_for_slug("ptp-negotiate"), allowed_tools=[*pack_for_slug("ptp-negotiate").allowed_tools, PAYLINK])
    state = _mouth(frozen=[PAYLINK], packs=[pack]).tools()
    assert PAYLINK in state.allowed


def test_platform_skill_tools_need_skills() -> None:
    """TOOLS-7: `load_skill` was granted to a card with nothing to load."""
    from agent_core.cards.schema import parse_card
    from agent_core.skills.intersect import effective_tools
    from agent_core.tools.catalog import CATALOG

    raw = card_dump(COLLECTIONS_BOT_ID)
    names = set(CATALOG.specs)
    # Not on the include: the platform ride-along is what is under test, an
    # explicit include still grants it.
    include = [t for t in raw["tools"]["include"] if t not in {"load_skill", "run_skill_script"}]
    tools = {**raw["tools"], "include": include}
    assert "load_skill" in effective_tools(parse_card({**raw, "tools": tools}), catalog_names=names)
    bare = parse_card({**raw, "tools": tools, "skills": []})
    assert "load_skill" not in effective_tools(bare, catalog_names=names)


def test_a_card_prefix_cannot_widen_the_registry() -> None:
    """CONNECTORS-11: the card's snapshot overrode the registry, so narrowing
    a connector after a card bound it revoked nothing."""
    assert cp.bound_prefixes(None, ["ext.paylink."]) == ["ext.paylink."]
    assert cp.bound_prefixes(["ext.paylink.get_"], ["ext.paylink."]) == ["ext.paylink.get_"]
    assert cp.bound_prefixes(["ext.paylink."], ["ext.paylink.get_"]) == []


def test_dispatch_refuses_a_name_outside_the_prefixes(monkeypatch) -> None:
    """CONNECTORS-13: prefixes were a bind-time filter; dispatch never asked."""
    monkeypatch.setattr(cp, "mcp_client_enabled", lambda: True)
    monkeypatch.setattr(cp, "get_connector", lambda _id: _connector(allowPrefixes=["ext.paylink.get_"]))
    assert cp.dispatch("ext.paylink.cancel", customer_id="C1", connector_id="conn-paylink") == {
        "ok": False,
        "error": "connector_prefix_not_bound",
    }


def test_dispatch_refuses_a_sandbox_connector_in_production(monkeypatch) -> None:
    """CONNECTORS-2: `allowed_env` was written, displayed and never read."""
    monkeypatch.setattr(cp, "mcp_client_enabled", lambda: True)
    monkeypatch.setattr(cp, "get_connector", lambda _id: _connector(allowedEnv="sandbox"))
    refused = cp.dispatch(PAYLINK, customer_id="C1", connector_id="conn-paylink", env="production")
    assert refused == {"ok": False, "error": "connector_env_not_allowed"}
    monkeypatch.setattr(cp, "dispatch_first_party", lambda _n, _c: {"ok": True})
    assert cp.dispatch(PAYLINK, customer_id="C1", connector_id="conn-paylink", env="sandbox") == {"ok": True}


def test_attaching_an_unapproved_connector_is_refused_at_the_attach() -> None:
    """CONNECTORS-15: the draft took it and G10 failed the publish later."""
    from agent_core.cards import clone

    from unittest.mock import patch

    with patch("agent_core.connectors.persist.get_connector", return_value=_connector(status="draft")):
        with pytest.raises(ValueError, match="connector_not_approved"):
            clone.attach_connector_to_card(COLLECTIONS_BOT_ID, connector_id="conn-paylink")
