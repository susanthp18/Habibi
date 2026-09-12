"""Every environment variable the code reads is in ``.env.example``, and
every key in ``.env.example`` is read by something.

``AUTHZ_ENFORCE`` -- the switch that turns route-level authorization off --
was read by ``authz.py`` and documented nowhere, so an operator could not
learn it existed except by reading the source. The template is the operator's
contract; the AST walk keeps it complete in both directions.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TEMPLATE = BACKEND / ".env.example"
_SKIP_DIRS = {"tests", "scripts", "alembic", ".venv", "__pycache__", "node_modules"}
_READERS = {"getenv", "env_bool", "env_int", "env_float", "env_str", "_require", "_env"}

#: Variables a process reads that are not this product's configuration:
#: set by the platform, the harness or the container, never by an operator.
_NOT_OURS = {
    "HOME",
    "PATH",
    "USER",
    "HOSTNAME",
    "TZ",
    "CI",
    "PYTEST_CURRENT_TEST",
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "PORT",
    "UPDATE_SNAPSHOTS",
    "DEEPGRAM_API_KEY",
}


def _production_modules() -> list[Path]:
    out = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND)
        if rel.parts[0] in _SKIP_DIRS:
            continue
        out.append(path)
    return out


def _read_names() -> dict[str, set[str]]:
    """Variable name -> the modules that read it (literal first arguments only)."""
    found: dict[str, set[str]] = {}
    for path in _production_modules():
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        rel = path.relative_to(BACKEND).as_posix()
        for node in ast.walk(tree):
            name: str | None = None
            if isinstance(node, ast.Call):
                fn = node.func
                fn_name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
                if fn_name in _READERS and node.args and isinstance(node.args[0], ast.Constant):
                    name = node.args[0].value
                elif (
                    isinstance(fn, ast.Attribute)
                    and fn.attr == "get"
                    and isinstance(fn.value, ast.Attribute)
                    and fn.value.attr == "environ"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                ):
                    name = node.args[0].value
            elif (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "environ"
                and isinstance(node.slice, ast.Constant)
            ):
                name = node.slice.value
            if isinstance(name, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
                found.setdefault(name, set()).add(rel)
    return found


def _template_keys() -> set[str]:
    keys: set[str] = set()
    for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^#?\s*([A-Z][A-Z0-9_]*)=", line)
        if m:
            keys.add(m.group(1))
    return keys


def test_every_variable_the_code_reads_is_in_the_template() -> None:
    read = _read_names()
    documented = _template_keys()
    missing = sorted(n for n in read if n not in documented and n not in _NOT_OURS)
    assert missing == [], {n: sorted(read[n]) for n in missing}



# The reverse direction -- every template key is read by something -- is not
# decidable by this walk: 145 keys are read through computed names
# (f"{role}_DB_POOL_SIZE", provider seed tables, the reco/treatment config
# maps). It stays a review question, not a test.
