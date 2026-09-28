"""The fleet is live on the dev stack: the Door answers and hands off.

These read the deployed state -- the entry binding, the door's active
bundle -- rather than fixtures, because the go-live is a property of the
stack, not of a unit. They skip on a stack that has not been seeded
(`scripts/seed_member_graphs.py --apply`, `scripts/republish_first_party.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest


DOOR = "intake-v1"
COLLECTIONS = "kaia-v2-4"


def test_the_template_ships_the_fleet_on() -> None:
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    lines = {ln.split("=", 1)[0]: ln.split("=", 1)[1] for ln in example.splitlines() if "=" in ln and not ln.startswith("#")}
    assert lines["DOOR_ENABLED"] == "true"


