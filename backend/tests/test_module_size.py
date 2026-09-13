"""No production module is longer than 1,500 lines; the ones that still are may only shrink.

The twin of ``test_function_size`` on files. A 2,500-line module has more than
one owner -- the floor snapshot, the webhook catalogue and provider health
shared one file until pass 6 -- and every reader of one pays for the other. What is
over the ceiling is listed with its measured length; a split lowers the number
or removes the name, and nothing may join the list.

Seeds are data and are not measured; tests, migrations and scripts are not
production modules.
"""

from __future__ import annotations

from pathlib import Path

from tests.source_tree import production_modules

BACKEND = Path(__file__).resolve().parent.parent
CEILING = 1_500
SKIP_DIRS = {"tests", "alembic", ".venv", "node_modules", "scripts", "seeds", "sql", "docs", "__pycache__"}

#: path -> measured lines on 2026-09-12. Shrink or delete; never add.
BASELINE: dict[str, int] = {
    "db.py": 2116,
    "db_inbox.py": 2526,
    "sandbox_runtime.py": 1873,
    "bot_runtime.py": 1836,
    "voice/crm_sink.py": 1713,
    "contact_policy.py": 1644,
    "outbound.py": 1580,
    "bank_boundary/ingest.py": 1545,
}


def _over_ceiling() -> dict[str, int]:
    out: dict[str, int] = {}
    for path in production_modules(prune=SKIP_DIRS):
        rel = path.relative_to(BACKEND)
        if rel.name.startswith("seed_"):
            continue
        lines = path.read_bytes().count(b"\n") + 1
        if lines > CEILING:
            out[rel.as_posix()] = lines
    return out


def test_no_new_module_is_over_the_ceiling() -> None:
    over = _over_ceiling()
    new = {k: v for k, v in over.items() if k not in BASELINE}
    assert not new, f"modules over {CEILING} lines that are not in the baseline: {new}"
    grown = {k: (BASELINE[k], v) for k, v in over.items() if k in BASELINE and v > BASELINE[k]}
    assert not grown, f"baselined modules that grew (baseline, now): {grown}"


def test_the_baseline_is_current() -> None:
    over = _over_ceiling()
    stale = {k: v for k, v in BASELINE.items() if over.get(k) != v}
    assert not stale, f"BASELINE entries that no longer match (set to the measured value, or delete): {stale}"
