"""Fail when the demo seed has no rows for the tables hundreds of tests skip on.

436 tests can vanish at runtime when ``customers``, ``accounts``,
``interactions``, ``products`` or ``leads`` is empty. CI runs
``scripts/seed_demo.py``, and a seed that exits 0 with empty tables still
turns those tests into skips. The suite already pins skill-pack emptiness
(``conftest.card_and_packs``); this is the same assertion at the seed
level.

``test_seed_coherence`` checks that the seed is believable. This file
checks that it is adequate.
"""

from __future__ import annotations

from sqlalchemy import text

# Tables whose emptiness is the skip trigger for the seed-conditioned tests.
_FLOOR = (
    "customers",
    "accounts",
    "interactions",
    "products",
    "leads",
)


def test_seed_has_content(db_tx) -> None:
    empty = [
        table
        for table in _FLOOR
        if not db_tx.execute(text(f"SELECT count(*) FROM {table}")).scalar()
    ]
    assert not empty, f"{', '.join(empty)} empty — these tests would go vacuous"
