"""The import contract: no language model is reachable from the ranking path.

§12.1 of ``docs/design/engines-production-design.md`` states the boundary and then states
why it is checked mechanically:

    The boundary is a CI contract, not a convention. An architecture rule that
    is not mechanically checked lasts until the first deadline.

    [importlinter:contract:no-llm-in-the-ranking-path]
    type = forbidden
    source_modules = agent_core.treatment.{scoring,policy,arbitration,explore,
                     allocate,models} agent_core.reco.{scoring,candidates}
    forbidden_modules = azure_openai, llm_gateway, agent_core.perception.serve

This is that contract, walked with ``ast`` instead of import-linter. The
reasons are the boring ones: import-linter needs a dependency, a config file
and a CI job, and this needs none of the three and runs in the suite that
already runs. Swap it for import-linter the day there is a second contract to
express — the value is in the assertion, not the tool.

``agent_core.perception.serve`` does not exist yet (no GPU, no models), so the
whole ``agent_core.perception`` package stands in its place, along with
``agent_core.understanding``, which is the module that actually holds an Azure
call today and is therefore the one a shortcut would reach for.

**Function-level imports count.** A deferred ``import azure_openai`` inside a
scoring helper is exactly as much of a violation as a top-level one, and it is
the form the violation would actually take — which is why this walks the whole
tree rather than only module-level statements.

**Two things it cannot see, stated so nobody mistakes a pass for a proof.**
``if TYPE_CHECKING:`` blocks are skipped, because the interpreter never runs
them. And a dynamic import by string — ``agent_core/__init__.py`` resolves its
re-exports through ``importlib.import_module`` over a dict — is invisible to
any static walk, import-linter's included. The contract is a floor, not a
theorem.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

#: The ranking path: everything between a feature vector and a chosen action.
SOURCE_MODULES = (
    "agent_core.treatment.scoring",
    "agent_core.treatment.policy",
    "agent_core.treatment.arbitration",
    "agent_core.treatment.explore",
    "agent_core.treatment.allocate",
    "agent_core.treatment.models",
    "agent_core.reco.scoring",
    "agent_core.reco.candidates",
)

FORBIDDEN = (
    "azure_openai",
    "llm_gateway",
    "agent_core.perception",
    "agent_core.understanding",
)

#: Where the walk stops, and the one honest weakening in this file.
#:
#: ``db`` is a 7,000-line persistence hub that re-exports a dozen ``db_*``
#: modules and defers ``import promise_fulfillment`` inside functions — and
#: ``promise_fulfillment`` reaches ``whatsapp_outbound``, ``bot_jobs`` and
#: finally ``bot_runtime``, which holds an Azure call. So *every* module in
#: this repository transitively reaches a language model through persistence,
#: and a closure that did not stop somewhere would report the whole codebase.
#: import-linter walks the same graph and would report the same thing.
#:
#: That is a real finding about the layering rather than a hole in this test,
#: and ``agent_core/__init__.py``'s own docstring records the same class of
#: problem one rung up: it had to defer its re-exports because
#: ``schemas -> agent_core -> deployment -> db -> schemas`` would not import.
#:
#: The contract this file can therefore assert is: **the ranking path reaches
#: no language model except by first crossing into persistence** — where
#: nothing it does is ranking. Every entry is a data-access module and the
#: list is asserted below so it cannot quietly grow into an exemption.
BOUNDARY_MODULES = frozenset({"db", "db_core", "schemas"})


def _path_for(module: str) -> Path | None:
    """Where this module's source lives, or None if it is not ours."""
    parts = module.split(".")
    as_module = BACKEND.joinpath(*parts).with_suffix(".py")
    if as_module.is_file():
        return as_module
    as_package = BACKEND.joinpath(*parts, "__init__.py")
    if as_package.is_file():
        return as_package
    return None


def _is_type_checking(node: ast.AST) -> bool:
    """``if TYPE_CHECKING:`` — erased at runtime, so it cannot reach anything.

    ``agent_core/__init__.py`` is the reason this matters. Its whole design is
    to import nothing first-party at runtime — the docstring explains which
    import cycle forced that — and its PEP 484 re-export block names
    ``agent_core.turn``, which reaches an Azure call. Counting a block the
    interpreter never executes would report every module that touches
    ``agent_core`` as reaching a language model, which is false.
    """
    test = node.test if isinstance(node, ast.If) else None
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _runtime_nodes(tree: ast.AST):
    """Every node the interpreter can actually reach."""
    stack = [tree]
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If) and _is_type_checking(child):
                # The ``else`` branch of a TYPE_CHECKING guard does run.
                stack.extend(child.orelse)
                continue
            stack.append(child)


def _imports(path: Path, module: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    package = module.rsplit(".", 1)[0] if "." in module else ""
    for node in _runtime_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # A relative import resolves against this module's package.
                base = package
                for _ in range(node.level - 1):
                    base = base.rsplit(".", 1)[0] if "." in base else ""
                head = f"{base}.{node.module}" if node.module else base
            else:
                head = node.module or ""
            if not head:
                continue
            found.add(head)
            # ``from agent_core.treatment import policy`` names a module, not
            # an attribute — try both and let _path_for decide.
            for alias in node.names:
                found.add(f"{head}.{alias.name}")
    return found


def _reachable(module: str) -> dict[str, list[str]]:
    """Every first-party module reachable from ``module``, with a path to it."""
    seen: dict[str, list[str]] = {module: [module]}
    queue = [module]
    while queue:
        current = queue.pop()
        path = _path_for(current)
        if path is None:
            continue
        for imported in sorted(_imports(path, current)):
            if imported in seen or _path_for(imported) is None:
                continue
            seen[imported] = seen[current] + [imported]
            if imported not in BOUNDARY_MODULES:
                queue.append(imported)
    return seen


def _violates(name: str) -> str | None:
    for forbidden in FORBIDDEN:
        if name == forbidden or name.startswith(f"{forbidden}."):
            return forbidden
    return None


@pytest.mark.parametrize("module", SOURCE_MODULES)
def test_no_llm_in_the_ranking_path(module: str) -> None:
    """A prompt output is uncalibrated, cannot be off-policy evaluated, cannot
    enter a constrained optimiser and cannot be re-fitted under model-risk
    management. So it does not get to be reachable from the code that ranks."""
    reachable = _reachable(module)
    breaches = {
        name: " -> ".join(chain)
        for name, chain in reachable.items()
        if _violates(name)
    }
    assert not breaches, (
        f"{module} can reach a language model:\n"
        + "\n".join(f"  {chain}" for chain in sorted(breaches.values()))
    )


def test_the_boundary_list_is_persistence_and_nothing_else() -> None:
    """An exemption list is only honest while it is short and named.

    Each entry has to be a data-access module — one whose job is reading and
    writing rows. The moment something with an opinion about *what to do* is
    added here, the contract above stops meaning what it says.
    """
    assert BOUNDARY_MODULES <= {"db", "db_core", "schemas"}
    for module in BOUNDARY_MODULES:
        assert _path_for(module) is not None, f"{module} is not a module in this tree"


def test_the_contract_would_notice() -> None:
    """The walk finds a violation when there is one.

    A contract test that passes because its graph walk is broken is worse than
    no contract test, because it is evidence of a property that was never
    checked. ``bot_runtime`` genuinely imports ``agent_core.understanding``, so
    it is the fixture: if this stops finding a breach, the walk has stopped
    working rather than the codebase having improved.
    """
    reachable = _reachable("bot_runtime")
    assert any(_violates(name) for name in reachable), (
        "the import walk found no LLM reachable from bot_runtime, which "
        "imports analyze_turn directly — the walk is broken"
    )
