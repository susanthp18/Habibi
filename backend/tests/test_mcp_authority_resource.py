"""``policy://authority-matrix`` is the matrix's numbers, not a placeholder.

The resource imported ``export_matrix`` from a module that never defined it,
so every read fell into the ``except`` and answered "matrix export
unavailable" -- the one policy export the MCP catalogue advertised was a
constant string.
"""

from __future__ import annotations

import pytest


def test_the_authority_resource_reports_the_live_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_core.mcp_http import resources

    monkeypatch.setenv("AUTHORITY_LATE_FEE_CAP", "750")
    monkeypatch.setenv("AUTHORITY_MODE", "live")
    payload = resources._authority()
    assert payload["mode"] == "live"
    assert payload["lateFee"]["capInr"] == 750.0
    assert "late_fee" in payload["feeTypes"]
    assert "note" not in payload
