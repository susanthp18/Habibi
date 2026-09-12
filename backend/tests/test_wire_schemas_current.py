"""The frontend's generated wire schemas match the API's response models.

``Habibi/src/api/wire/generated.ts`` is written by
``scripts/gen_wire_schemas.py`` from ``main.app.openapi()``; the browser
parses every response against it. A response model that changes without a
regeneration would fail there at runtime, so it fails here first. Skips
where the frontend tree is not mounted (the voice container sees /app only).
"""

from __future__ import annotations

from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
GENERATED = BACKEND.parent / "Habibi" / "src" / "api" / "wire" / "generated.ts"


def test_generated_wire_schemas_are_current() -> None:
    if not GENERATED.exists():
        pytest.skip("frontend tree not mounted beside the backend")
    import sys

    sys.path.insert(0, str(BACKEND / "scripts"))
    import gen_wire_schemas

    expected = gen_wire_schemas.build()
    current = GENERATED.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert current == expected, (
        "Habibi/src/api/wire/generated.ts is stale: run `python scripts/gen_wire_schemas.py`"
    )


def test_generated_constants_are_current() -> None:
    """constants.json carries the vocabularies and thresholds both ends agree
    on; the TypeScript reads it instead of restating them."""
    constants = GENERATED.with_name("constants.json")
    if not constants.exists():
        pytest.skip("frontend tree not mounted beside the backend")
    import sys

    sys.path.insert(0, str(BACKEND / "scripts"))
    import gen_wire_schemas

    current = constants.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert current == gen_wire_schemas.build_constants(), (
        "Habibi/src/api/wire/constants.json is stale: run `python scripts/gen_wire_schemas.py`"
    )
