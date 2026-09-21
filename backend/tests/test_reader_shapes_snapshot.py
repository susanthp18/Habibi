"""The shape of the four screen readers, pinned before they are taken apart.

``db_dashboard.get_dashboard``, ``db_billing.billing_overview``,
``db_bot_analytics.bot_analytics`` and ``db_floor.get_floor_snapshot`` are
each one long function of queries followed by an assembly. Splitting them into
a reads phase and a shape phase must not drop a section or a key. Values move
with the dev database, so what is pinned is the key tree with the type at
every leaf (``tests/snapshots/reader_shapes.json``); occupancy maps such as
``daily.values`` pin as ``<scalar-map>``. The behaviour tests
beside this one (test_dashboard_live, test_floor, test_phase6) pin the values.

Regenerate deliberately, never to make a red run green:

    UPDATE_SNAPSHOTS=1 pytest tests/test_reader_shapes_snapshot.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "reader_shapes.json"


def _shape(value: Any, key: str | None = None) -> Any:
    """The key tree; a list is the shape of its first item (or ``[]``).

    ``daily.values`` / ``serviceTenantSpend.<service>`` are occupancy maps
    (which Azure service, which tenant). Pin them as ``<scalar-map>`` so today's
    spend is not a schema change. Named metric objects (``stats``, ``spendByEnv``,
    ``sentiment``) keep their keys.
    """
    occupancy = key == "values" or (
        isinstance(key, str) and key.startswith(("llm_", "stt_", "tts_"))
    )
    if key == "delta" and (
        value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))
    ):
        return "number|null"
    if isinstance(value, dict):
        if occupancy and all(not isinstance(v, (dict, list)) for v in value.values()):
            return "<scalar-map>"
        return {k: _shape(v, k) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_shape(value[0])] if value else []
    if value is None:
        return "null"
    return type(value).__name__


def render() -> dict[str, Any]:
    import db
    import db_floor

    return {
        "dashboard": {
            r: _shape(db.get_dashboard(range=r)) for r in ("today", "7d", "qtd")
        },
        "billing": {
            p: _shape(db.billing_overview(p, "all", "production"))
            for p in ("mtd", "30d")
        },
        "bot_analytics": _shape(db.bot_analytics("30d", "all")),
        "floor": _shape(db_floor.get_floor_snapshot()),
    }


def test_reader_shapes_match_the_snapshot(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = json.dumps(render(), indent=2, sort_keys=True) + "\n"
    if os.getenv("UPDATE_SNAPSHOTS"):
        SNAPSHOT.write_text(current, encoding="utf-8")
        return
    assert SNAPSHOT.exists(), "no snapshot yet: run once with UPDATE_SNAPSHOTS=1"
    pinned = SNAPSHOT.read_bytes().replace(b"\r\n", b"\n")  # autocrlf checkouts
    assert current.encode("utf-8") == pinned, (
        "a screen reader returned a different key tree -- if the change is intended, "
        "regenerate with UPDATE_SNAPSHOTS=1 and review the diff"
    )
