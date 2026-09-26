"""A skill may name a connector tool, and that is how a bound connector
becomes callable.

The grant offers an ``ext.*`` tool only through a pack that names it, while
lint and G9 refused every ``ext.*`` name as not in the catalog. So `paylink`,
bound on kaia-v2-4 since it shipped, could never be called (G18's warning).
"""

from __future__ import annotations

from dataclasses import replace

from agent_core.skills.lint import catalog_tool_names, lint_pack
from agent_core.skills.pack import pack_for_slug


def _unknown(pack) -> list[str]:
    issues = lint_pack(pack, catalog_names=catalog_tool_names())
    return [t for i in issues if i["code"] == "unknown_tools" for t in i["tools"]]


def test_dispute_capture_checks_the_pay_link_before_filing() -> None:
    pack = pack_for_slug("dispute-capture")
    assert "ext.paylink.get_status" in pack.allowed_tools
    assert _unknown(pack) == []


def test_a_name_that_is_neither_catalog_nor_connector_is_still_refused() -> None:
    pack = replace(pack_for_slug("dispute-capture"), allowed_tools=["ext.paylink", "no_such_tool"])
    assert _unknown(pack) == ["ext.paylink", "no_such_tool"]
