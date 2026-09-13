"""THIRD_PARTY_NOTICES.txt is generated from the lockfiles and must match them.

Runs where both trees are present (the host, CI); inside the API container
the console tree is not mounted, so it skips the same way the wire-schema
currency test does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent


def test_third_party_notices_are_current() -> None:
    if not (ROOT / "Habibi" / "node_modules").is_dir() or not (ROOT / "LICENSE").exists():
        pytest.skip("repo root with the console's node_modules is not mounted beside the backend")
    sys.path.insert(0, str(BACKEND / "scripts"))
    import third_party_notices

    current = (ROOT / "THIRD_PARTY_NOTICES.txt").read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert current == third_party_notices.render(), (
        "THIRD_PARTY_NOTICES.txt is stale: run `python scripts/third_party_notices.py`"
    )


def test_the_product_says_it_is_proprietary() -> None:
    if not (ROOT / "LICENSE").exists():
        pytest.skip("repo root is not mounted beside the backend")
    assert "All rights reserved" in (ROOT / "LICENSE").read_bytes().decode("utf-8")
    pkg = (ROOT / "Habibi" / "package.json").read_bytes().decode("utf-8")
    assert '"license": "UNLICENSED"' in pkg
    assert '"private": true' in pkg
