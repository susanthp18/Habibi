"""The outbound gate has one owner, and every ``place`` site goes through it.

Every *piece* was tested — ``admit``, ``suppress``, ``place``. The composition
was written by hand at seven sites, in two orderings, and one of them
(``payment_events._try_voice_now``) admitted before it reserved and so left no
attempt row when the gate said no. This file used to pin those seven sequences
so a swap could not hide in one caller. It now pins something stronger: the
sequence exists in exactly one place, ``outbound.gate``, and a function that
calls ``outbound.place`` may not call ``contact_policy.admit`` or
``outbound.suppress`` itself.
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

_STEPS = ("reserve", "gate", "admit", "suppress", "place")

# Every ``outbound.place`` call site, and the gate steps the containing function
# is allowed to touch. ``gate`` then ``place`` is the whole story; the two
# exceptions are named.
_PLACE_SITES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("campaigns.py", "process_one", ("gate", "place")),
    ("cadence.py", "process_one", ("gate", "place")),
    ("routers/telephony.py", "twilio_voice_outbound", ("gate", "place")),
    ("routers/outbound.py", "demo_outbound_call", ("gate", "place")),
    # The dry run reserves and *evaluates* (never admits) so a rehearsal does
    # not spend the borrower's budget; the real path is the gate.
    ("scripts/dial_test.py", "main", ("reserve", "gate", "place")),
    ("agent_core/treatment/enact.py", "_dial_bot", ("gate", "place")),
    # Gates on its own transaction and hands the dial to ``deliver``.
    ("payment_events.py", "_deliver_voice", ("place",)),
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


def _gate_sequence(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    """Source order of the gate steps in ``fn``, nested functions included.

    ``asyncio.to_thread(outbound.place, ...)`` is a use of ``place``, not a
    call of it — Attribute nodes are collected, not only Call.func. Nested
    functions are *not* excluded: the route handlers wrap their transaction
    in a closure to get it off the event loop, and a gate step hidden in one
    is still that handler's gate step.
    """
    hits: list[tuple[int, int, str]] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Attribute) and node.attr in _STEPS:
            hits.append((node.lineno, node.col_offset, node.attr))
    hits.sort()
    return tuple(name for _, _, name in hits)


def _parse(rel: str) -> ast.Module:
    return ast.parse((BACKEND / rel).read_text(encoding="utf-8"))


def _place_sites_in_tree(tree: ast.Module) -> list[str]:
    """Functions in this module that mention ``outbound.place``."""
    found: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Attribute)
                and child.attr == "place"
                and isinstance(child.value, ast.Name)
                and child.value.id == "outbound"
            ):
                found.append(node.name)
                break
    return found


def test_the_extractor_sees_a_hand_written_sequence() -> None:
    """The acceptance criterion: a caller that re-opens the gate turns this red."""
    by_hand = ast.parse(
        "def f():\n"
        "    outbound.reserve()\n"
        "    contact_policy.admit()\n"
        "    outbound.suppress()\n"
        "    outbound.place()\n"
    )
    owned = ast.parse(
        "async def f():\n"
        "    def _g():\n"
        "        return outbound.gate()\n"
        "    g = await asyncio.to_thread(_g)\n"
        "    outbound.place()\n"
    )
    assert _gate_sequence(_module_function(by_hand, "f")) == (
        "reserve",
        "admit",
        "suppress",
        "place",
    )
    assert _gate_sequence(_module_function(owned, "f")) == ("gate", "place")


@pytest.mark.parametrize(
    ("rel", "func", "expected"),
    [
        pytest.param(rel, func, expected, id=f"{rel}:{func}")
        for rel, func, expected in _PLACE_SITES
    ],
)
def test_each_place_site_only_touches_the_gate(
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
        for func in _place_sites_in_tree(tree):
            found.add((rel, func))
    expected = {(rel, func) for rel, func, _expected in _PLACE_SITES}
    assert found == expected


def test_the_gate_itself_is_the_only_hand_written_sequence() -> None:
    """``outbound.gate`` is reserve → admit → suppress, and nothing else in the
    application composes those three."""
    tree = _parse("outbound.py")
    gate_fn = _module_function(tree, "gate")
    # Inside its own module the steps are bare names, not `outbound.` attributes.
    hits = sorted(
        (n.lineno, n.col_offset, n.id if isinstance(n, ast.Name) else n.attr)
        for n in ast.walk(gate_fn)
        if (isinstance(n, ast.Name) and n.id in ("reserve", "suppress"))
        or (isinstance(n, ast.Attribute) and n.attr in _STEPS)
    )
    seq = tuple(name for _, _, name in hits)
    assert [s for s in seq if s != "gate"] == ["reserve", "admit", "suppress"], seq

    elsewhere: list[str] = []
    for path in _application_py():
        rel = path.relative_to(BACKEND).as_posix()
        if rel == "outbound.py":
            continue
        module = ast.parse(path.read_text(encoding="utf-8"))
        for node in module.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = {
                child.attr
                for child in ast.walk(node)
                if isinstance(child, ast.Attribute)
                and isinstance(child.value, ast.Name)
                and (
                    (child.value.id == "outbound" and child.attr in ("reserve", "suppress"))
                    or (child.value.id == "contact_policy" and child.attr == "admit")
                )
            }
            if {"reserve", "admit"} <= names or {"admit", "suppress"} <= names:
                elsewhere.append(f"{rel}:{node.name}")
    assert elsewhere == [], elsewhere


def test_payment_events_gates_on_its_own_transaction_and_dials_after_commit() -> None:
    """The site that used to admit → reserve → place with no suppress. It now
    gates (reserve → admit → suppress inside ``gate``) on a transaction it
    opens itself, and ``ingest`` performs no carrier I/O at all."""
    tree = _parse("payment_events.py")
    assert _gate_sequence(_module_function(tree, "_try_voice_now")) == ("gate",)
    assert "place" not in _gate_sequence(_module_function(tree, "ingest"))
    assert "place" not in _gate_sequence(_module_function(tree, "_first_touch"))
    src = (BACKEND / "payment_events.py").read_text(encoding="utf-8")
    for fn in ("ingest", "_first_touch", "_digital_blocked", "_try_voice_now"):
        node = _module_function(tree, fn)
        body = ast.get_source_segment(src, node) or ""
        assert "twilio_sms.send(" not in body, f"{fn} sends inside the transaction"
