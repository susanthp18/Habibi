"""Tests that assert on source text are a ratchet, not a habit.

A test that reads a module as text (``inspect.getsource``, ``read_text``)
pins where code sits, not what it does, and a pure move breaks it. This
pass moved run_bot and build_tools' pins to snapshots of behaviour; the
rest are converted as their subjects are touched. The count may go down,
never up.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
#: ``open(...).read()`` and the ``tests/voice_tools_source`` helper are source
#: reads too; the first pattern missed them, which is how one pin slipped past
#: the count. Re-measured under the wider net on 2026-09-12: 106; four pins
#: became behaviour tests on 2026-09-13 (the sweep's statements, the
#: dashboard's statements, the scheduler's SUITE_KINDS, a deleted constant).
_PIN = re.compile(r"inspect\.getsource\(|\.read_text\(|\.read\(\)|voice_tools_source")

#: Files that read source text on 2026-09-12. Remove a name when its test
#: stops doing so; never add one -- a new test pins behaviour, not text.
BASELINE = 102


def _pinning_files() -> list[str]:
    out = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        if _PIN.search(path.read_text(encoding="utf-8", errors="replace")):
            out.append(path.name)
    return out


def test_source_text_pins_do_not_grow() -> None:
    files = _pinning_files()
    assert len(files) <= BASELINE, (
        f"{len(files)} test files read source text (baseline {BASELINE}); "
        "a new test should assert behaviour, not where code sits"
    )


def test_baseline_is_current() -> None:
    """When pins are converted, lower BASELINE so the ratchet keeps biting."""
    assert len(_pinning_files()) == BASELINE, (
        f"{len(_pinning_files())} pinning files; set BASELINE to that number"
    )
