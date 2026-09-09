"""``studio-contract.ts`` is a hand-written mirror with no pin in either direction.

It restates the compiled bundle, the compile report, the gate-status vocabulary,
the sandbox turn shape and — the one that has already drifted — the map from a
card's channels to the catalog's. ``test_agent_card_schema_drift`` guards
``agent-card.ts`` the same way; this is that guard for the file next to it.

The empirical rule this exists to satisfy: of the duplicated vocabularies in this
repository, every one given a cross-language test has held and every one without
has separated. This file was without.
"""

from __future__ import annotations

import re
from typing import get_args

from agent_core.cards.compile import GateStatus
from agent_core.cards.schema import Channel
from agent_core.fleet.schema import CompiledBundle
from agent_core.tools.schema import CHANNEL_MCP, CHANNEL_TEXT, CHANNEL_VOICE
from tests.conftest import frontend_file


def _contract() -> str:
    return frontend_file("src", "lib", "studio-contract.ts").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The channel map — the drift that already happened
# ---------------------------------------------------------------------------


def test_every_card_channel_is_mapped_to_a_catalog_channel() -> None:
    """A card channel the map does not know silently empties the Tools tab.

    ``catalogToolsForCard`` builds ``wanted`` from the card's own channels and
    keeps a row only if the row declares one of them. The catalog speaks three
    channels (voice / text / mcp); a card may declare six. Anything unmapped
    falls through as itself, matches no row, and the tab renders "The tool
    catalog is empty." — a statement about the catalog produced by a filter,
    on the one screen where the author then cannot grant anything.
    """
    mapping = _channel_map()
    catalog_channels = {CHANNEL_VOICE, CHANNEL_TEXT, CHANNEL_MCP}
    unmapped = [c for c in get_args(Channel) if mapping.get(c) not in catalog_channels]

    assert not unmapped, (
        f"card channels {unmapped} reach catalogToolsForCard unmapped. Each one "
        f"filters the tool list to nothing and the tab then calls the catalog "
        f"empty. Map them to a catalog channel ({sorted(catalog_channels)}) or "
        f"give the filter an explicit 'this channel has no tools' branch."
    )


def _channel_map() -> dict[str, str]:
    """`CARD_CHANNEL_TO_CATALOG`, as a dict."""
    source = _contract()
    start = source.index("const CARD_CHANNEL_TO_CATALOG")
    body = source[start : source.index("};", start)]
    # `[a-z0-9_]` and not `[a-z_]`: `a2a` has a digit in it, and a key the
    # extraction silently misses reads here as an unmapped channel.
    return dict(re.findall(r"^  ([a-z0-9_]+):\s*\"([a-z]+)\",", body, re.M))


def test_the_map_does_not_invent_a_card_channel() -> None:
    """A key no card can declare is dead, and it hides that the card vocabulary
    was never checked against — `chat` belongs to the API's Channel, not this one."""
    invented = sorted(set(_channel_map()) - set(get_args(Channel)))
    assert not invented, (
        f"the map tests for {invented}, which no card can declare "
        f"(Channel is {sorted(get_args(Channel))})"
    )


# ---------------------------------------------------------------------------
# The vocabularies it restates
# ---------------------------------------------------------------------------


def test_gate_status_union_matches() -> None:
    source = _contract()
    match = re.search(r"status:\s*z\.enum\(\[([^\]]*)\]\)", source)
    assert match, "could not find the gate status enum in compileReportSchema"
    ts_values = set(re.findall(r'"([a-z]+)"', match.group(1)))
    assert ts_values == set(get_args(GateStatus))


def _mirror_members() -> set[str]:
    """Top-level keys ``compiledBundleSchema`` declares.

    Indentation is what separates them: a top-level key sits four spaces inside
    ``.object({``, and everything nested sits deeper.
    """
    source = _contract()
    start = source.index("export const compiledBundleSchema")
    body = source[start : source.index(".passthrough()", start)]
    return set(re.findall(r"^    ([a-z_]+):", body, re.M))


def test_the_mirror_declares_no_field_the_bundle_does_not_have() -> None:
    """The direction that actually breaks something.

    The mirror is ``.passthrough()`` and deliberately partial — it carries what
    the panels read, not every field — so a *missing* member is a choice, and
    asserting the full set would only force the mirror to grow. A member Python
    has since renamed or removed is not a choice: zod goes on validating it as
    optional, the panel goes on reading ``undefined``, and nothing says the
    contract moved.
    """
    unknown = sorted(_mirror_members() - set(CompiledBundle.model_fields))
    assert not unknown, (
        f"studio-contract.ts declares {unknown} on compiledBundleSchema, which "
        f"CompiledBundle no longer has"
    )


def test_the_fields_a_panel_actually_reads_are_mirrored() -> None:
    """The few the Effective-contract panel and the flow canvas depend on."""
    mirrored = _mirror_members()
    for member in ("bot_id", "bundle_hash", "grants"):
        assert member in mirrored, f"compiledBundleSchema is missing {member}"
