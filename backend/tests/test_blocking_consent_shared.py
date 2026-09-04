"""One answer to which consent statuses forbid contact.

Four modules restated ``{"opted_out", "dnd", "expired"}`` under three names.
They were member-identical, which is why replacing each copy with an import
is a no-op — and why the pin has to assert identity, not membership.
Membership would stay green after someone re-copies the literal.
"""

from __future__ import annotations

import ast
from pathlib import Path

import capture
import contact_policy
import payment_events
import promise_fulfillment
from agent_core.reco import arbitration

BACKEND = Path(__file__).resolve().parents[1]

_OWNER = (BACKEND / "contact_policy.py").resolve()

_SKIP_DIRS = {
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "alembic",
    "htmlcov",
    "tests",
}

_CONSUMERS = (
    payment_events,
    promise_fulfillment,
    capture,
    arbitration,
)


def test_the_canonical_set_is_the_three_blocking_statuses() -> None:
    assert contact_policy.BLOCKING_CONSENT == {"opted_out", "dnd", "expired"}
    assert isinstance(contact_policy.BLOCKING_CONSENT, frozenset)


def test_every_copy_site_holds_the_canonical_object() -> None:
    """Same object, not a second frozenset that happens to agree today."""
    canonical = contact_policy.BLOCKING_CONSENT
    for module in _CONSUMERS:
        held = module.BLOCKING_CONSENT
        assert held is canonical, (
            f"{module.__name__}.BLOCKING_CONSENT is not "
            "contact_policy.BLOCKING_CONSENT"
        )


def _is_blocking_consent_literal(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Name) or func.id != "frozenset":
        return False
    if len(node.args) != 1 or node.keywords:
        return False
    arg = node.args[0]
    if not isinstance(arg, ast.Set):
        return False
    members: set[str] = set()
    for elt in arg.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            members.add(elt.value)
        else:
            return False
    return members == {"opted_out", "dnd", "expired"}


def _local_definitions(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_blocking_consent_literal(node.value):
            lines.append(node.lineno)
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and _is_blocking_consent_literal(node.value)
        ):
            lines.append(node.lineno)
    return lines


def test_the_literal_is_defined_only_in_contact_policy() -> None:
    """A second ``frozenset({"opted_out", "dnd", "expired"})`` is a new owner."""
    offenders: list[str] = []
    owner_lines = _local_definitions(_OWNER)
    assert owner_lines, "contact_policy.py no longer defines BLOCKING_CONSENT"
    assert len(owner_lines) == 1

    for path in BACKEND.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.resolve() == _OWNER:
            continue
        lines = _local_definitions(path)
        if lines:
            rel = path.relative_to(BACKEND).as_posix()
            offenders.append(f"{rel}:{','.join(str(n) for n in lines)}")
    assert offenders == []
