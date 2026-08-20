"""Import-order landmines.

A circular import only fires when a particular module is the *first* of the
cycle to load, so it is invisible to a normal test session: by the time any
test runs, pytest's collection has already imported half the codebase in a
benign order. Each check therefore runs in a fresh interpreter.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

# Entry points that must survive being the first thing a process imports.
# agent_core.skills.runtime is the one that mattered: voice/bot.py defers
# `from agent_core.skills.runtime import mouth_turn_state` into the function
# that assembles the system prompt, so in the voice worker it was the first
# module to touch the agent_core.cards <-> agent_core.skills cycle and every
# call would have died building its prompt.
FIRST_IMPORTS = [
    "agent_core.skills.runtime",
    "agent_core.skills.intersect",
    "agent_core.cards.schema",
    "agent_core.cards.compile",
    "agent_core.cards",
]


@pytest.mark.parametrize("module", FIRST_IMPORTS)
def test_module_imports_first_in_a_clean_interpreter(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"importing {module} first fails:\n{result.stderr[-1500:]}"
    )


def test_the_cards_package_does_not_drag_in_the_compiler() -> None:
    """The re-exports resolve lazily. Eager imports here are what closed the
    cycle, so a submodule import must not pull agent_core.cards.compile."""
    probe = (
        "import sys; import agent_core.cards.schema;"
        " print('agent_core.cards.compile' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr[-1500:]
    assert result.stdout.strip() == "False", "importing a submodule loaded the compiler"


def test_the_lazy_re_exports_still_work() -> None:
    probe = (
        "from agent_core.cards import compile_card, AgentCard, card_dump, CompileError;"
        " print(compile_card.__name__, AgentCard.__name__)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr[-1500:]
    assert result.stdout.strip() == "compile_card AgentCard"


def test_an_unknown_attribute_still_raises_attribute_error() -> None:
    """__getattr__ must not turn a typo into an ImportError from importlib."""
    probe = (
        "import agent_core.cards as c\n"
        "try:\n"
        "    c.does_not_exist\n"
        "except AttributeError:\n"
        "    print('AttributeError')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr[-1500:]
    assert result.stdout.strip() == "AttributeError"
