"""The outbound gate sequence, as a contract across every ``place`` site.

Every *piece* is tested — ``admit``, ``suppress``, ``place``. The composition
was tested at zero sites, and ``campaigns.process_one`` was an
``inspect.getsource`` substring. A change to the compliance ordering could land
in six files out of seven and nothing would fail.

The five ordering-A sites are ``reserve → admit → suppress → place``. Treatment
enact splits the same steps across three functions (admit, then either
reserve+suppress or reserve+place). ``payment_events._try_voice_now`` is the
known hole: admit then reserve then place, and no ``suppress`` anywhere in the
module. WP-028 owns closing that hole; this file pins the current sequences so
a swap cannot hide in one caller.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

_SKIP_DIRS = {
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "alembic",
    "htmlcov",
    "tests",
}

_STEPS = ("reserve", "admit", "suppress", "place")

# The seven ``outbound.place`` call sites, and the source order of gate steps
# inside the function that contains ``place``.
_PLACE_SITES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("campaigns.py", "process_one", ("reserve", "admit", "suppress", "place")),
    ("cadence.py", "process_one", ("reserve", "admit", "suppress", "place")),
    ("main.py", "twilio_voice_outbound", ("reserve", "admit", "suppress", "place")),
    ("main.py", "demo_outbound_call", ("reserve", "admit", "suppress", "place")),
    ("scripts/dial_test.py", "main", ("reserve", "admit", "suppress", "place")),
    ("agent_core/treatment/enact.py", "_dial_bot", ("reserve", "place")),
    ("payment_events.py", "_try_voice_now", ("admit", "reserve", "place")),
)


def _application_py() -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(BACKEND):
        dirnames[:] = [
            d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")
        ]
        for name in filenames:
            if name.endswith(".py"):
                found.append(Path(dirpath) / name)
    return found


def _module_function(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    assert isinstance(tree, ast.Module)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"no function named {name}")


def _nested_ranges(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(fn):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node is not fn
        ):
            ranges.append((node.lineno, node.end_lineno or node.lineno))
    return ranges


def _inside(node: ast.AST, ranges: list[tuple[int, int]]) -> bool:
    line = getattr(node, "lineno", None)
    if line is None:
        return False
    return any(start <= line <= end for start, end in ranges)


def _gate_sequence(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    """Source order of reserve / admit / suppress / place in ``fn``.

    ``asyncio.to_thread(outbound.place, ...)`` is a use of ``place``, not a
    call of it — Attribute nodes are collected, not only Call.func.
    """
    nested = _nested_ranges(fn)
    hits: list[tuple[int, int, str]] = []
    for node in ast.walk(fn):
        if _inside(node, nested):
            continue
        if isinstance(node, ast.Attribute) and node.attr in _STEPS:
            hits.append((node.lineno, node.col_offset, node.attr))
        elif isinstance(node, ast.Name) and node.id in _STEPS:
            hits.append((node.lineno, node.col_offset, node.id))
    hits.sort()
    return tuple(name for _, _, name in hits)


def _parse(rel: str) -> ast.Module:
    return ast.parse((BACKEND / rel).read_text(encoding="utf-8"))


def _place_sites_in_tree(rel: str, tree: ast.Module) -> list[str]:
    """Functions in this module that mention ``outbound.place``."""
    found: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        nested = _nested_ranges(node)
        for child in ast.walk(node):
            if _inside(child, nested):
                continue
            if (
                isinstance(child, ast.Attribute)
                and child.attr == "place"
                and isinstance(child.value, ast.Name)
                and child.value.id == "outbound"
            ):
                found.append(node.name)
                break
    return found


def test_the_extractor_fails_when_reserve_and_admit_are_swapped() -> None:
    """The acceptance criterion: a deliberate swap turns this file red."""
    ordered = ast.parse(
        "def f():\n"
        "    outbound.reserve()\n"
        "    contact_policy.admit()\n"
        "    outbound.suppress()\n"
        "    outbound.place()\n"
    )
    swapped = ast.parse(
        "def f():\n"
        "    contact_policy.admit()\n"
        "    outbound.reserve()\n"
        "    outbound.suppress()\n"
        "    outbound.place()\n"
    )
    assert _gate_sequence(_module_function(ordered, "f")) == (
        "reserve",
        "admit",
        "suppress",
        "place",
    )
    assert _gate_sequence(_module_function(swapped, "f")) == (
        "admit",
        "reserve",
        "suppress",
        "place",
    )


@pytest.mark.parametrize(
    ("rel", "func", "expected"),
    [
        pytest.param(rel, func, expected, id=f"{rel}:{func}")
        for rel, func, expected in _PLACE_SITES
    ],
)
def test_each_place_site_keeps_its_gate_order(
    rel: str, func: str, expected: tuple[str, ...]
) -> None:
    seq = _gate_sequence(_module_function(_parse(rel), func))
    assert seq == expected


def test_every_outbound_place_site_is_on_this_contract() -> None:
    """An eighth caller cannot land without being named here."""
    found: set[tuple[str, str]] = set()
    for path in _application_py():
        rel = path.relative_to(BACKEND).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in _place_sites_in_tree(rel, tree):
            found.add((rel, func))
    expected = {(rel, func) for rel, func, _expected in _PLACE_SITES}
    assert found == expected


def test_treatment_enact_admits_before_it_dials_or_suppresses() -> None:
    """Ordering B: the gate lives in ``enact_one``, not in the dial helper.

    ``_dial_bot`` must not re-open the contact question, and a refusal still
    has to leave a suppressed attempt row via ``_record_suppressed_dial``.
    """
    tree = _parse("agent_core/treatment/enact.py")
    enact_one = _gate_sequence(_module_function(tree, "enact_one"))
    suppressed = _gate_sequence(_module_function(tree, "_record_suppressed_dial"))
    dial = _gate_sequence(_module_function(tree, "_dial_bot"))
    assert "admit" in enact_one
    assert "place" not in enact_one
    assert suppressed == ("reserve", "suppress")
    assert dial == ("reserve", "place")


def test_payment_events_is_the_site_that_does_not_suppress() -> None:
    """Pin the hole WP-028 will close. A silent add of suppress must be a diff here."""
    seq = _gate_sequence(_module_function(_parse("payment_events.py"), "_try_voice_now"))
    assert seq == ("admit", "reserve", "place")
    assert "suppress" not in seq
