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

from agent_core.tools.schema import CHANNEL_MCP, CHANNEL_TEXT, CHANNEL_VOICE
from tests.conftest import frontend_file


def _contract() -> str:
    return frontend_file("src", "lib", "studio-contract.ts").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The channel map — the drift that already happened
# ---------------------------------------------------------------------------


def _channel_map() -> dict[str, str]:
    """`CARD_CHANNEL_TO_CATALOG`, as a dict."""
    source = _contract()
    start = source.index("const CARD_CHANNEL_TO_CATALOG")
    body = source[start : source.index("};", start)]
    # `[a-z0-9_]` and not `[a-z_]`: `a2a` has a digit in it, and a key the
    # extraction silently misses reads here as an unmapped channel.
    return dict(re.findall(r"^  ([a-z0-9_]+):\s*\"([a-z]+)\",", body, re.M))


# ---------------------------------------------------------------------------
# The vocabularies it restates
# ---------------------------------------------------------------------------


def _mirror_members() -> set[str]:
    """Top-level keys ``compiledBundleSchema`` declares.

    Indentation is what separates them: a top-level key sits four spaces inside
    ``.object({``, and everything nested sits deeper.
    """
    source = _contract()
    start = source.index("export const compiledBundleSchema")
    body = source[start : source.index(".passthrough()", start)]
    return set(re.findall(r"^    ([a-z_]+):", body, re.M))


def test_the_fields_a_panel_actually_reads_are_mirrored() -> None:
    """The few the Effective-contract panel and the flow canvas depend on."""
    mirrored = _mirror_members()
    for member in ("bot_id", "bundle_hash", "grants"):
        assert member in mirrored, f"compiledBundleSchema is missing {member}"
