"""Every `_node("...")` a handler makes is a hop `flow_graph.TRANSITIONS` declares.

The map is the source of truth for where a call goes; the handlers in
``voice/tools.py`` are the code that goes there. Two statements of one fact
hold only while something compares them, so this file keeps the reader that
used to run at runtime -- three passes over the module's AST, following
delegation and parameter defaults -- and runs it as a test instead. A handler
that moves somewhere the map does not say, or a map entry no handler reaches,
fails here rather than drawing a wrong canvas or stranding a text rehearsal.

Pipecat-free: it parses the file, it does not import it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import flow_graph

_VOICE = Path(__file__).resolve().parents[1] / "voice"
#: The tool set is one module per section now (voice/tools.py plus
#: voice/tools_*.py); the reader parses them as one text, still without
#: importing any of them.
_TOOLS = sorted(_VOICE.glob("tools*.py"))


def _handler_hops() -> dict[str, set[str]]:
    """tool key -> node keys its handler (or any helper it calls) passes to `_node`."""
    tree = ast.parse("\n".join(p.read_text(encoding="utf-8") for p in _TOOLS))

    literals: dict[str, set[str]] = {}

    def _remember(name: str, value: ast.AST) -> None:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            literals.setdefault(name, set()).add(value.value)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            positional = [*args.posonlyargs, *args.args]
            for arg, default in zip(positional[len(positional) - len(args.defaults):], args.defaults):
                _remember(arg.arg, default)
            for arg, default in zip(args.kwonlyargs, args.kw_defaults):
                if default is not None:
                    _remember(arg.arg, default)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    _remember(target.id, node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                _remember(node.target.id, node.value)

    direct: dict[str, set[str]] = {}
    calls: dict[str, set[str]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        hits: set[str] = set()
        callees: set[str] = set()
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id == "_node":
                if not node.args:
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    hits.add(first.value)
                elif isinstance(first, ast.Name):
                    hits |= literals.get(first.id, set())
            else:
                callees.add(node.func.id)
        direct[fn.name] = hits
        calls[fn.name] = callees

    # `capture_call_goal = _spec("capture_call_goal", _capture_call_goal_handler)`
    # binds a name the walk never saw as a function; any function handed to
    # such a factory is the binding's delegate.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        delegates = {
            arg.id
            for arg in (*node.value.args, *(kw.value for kw in node.value.keywords))
            if isinstance(arg, ast.Name) and arg.id in direct
        }
        if not targets or not delegates:
            continue
        for target in targets:
            direct.setdefault(target, set())
            calls.setdefault(target, set()).update(delegates)

    def _closure(name: str) -> set[str]:
        seen: set[str] = set()
        stack = [name]
        found: set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen or current not in direct:
                continue
            seen.add(current)
            found |= direct[current]
            stack.extend(calls.get(current, ()))
        return found

    out: dict[str, set[str]] = {}
    # `tools = {...}` in the trunk, and each section's `return {...}` -- the
    # dict a section hands back keyed by the same tool names.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            if not any(isinstance(t, ast.Name) and t.id == "tools" for t in node.targets):
                continue
        elif not (isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str) and isinstance(value, ast.Name):
                hops = _closure(value.id)
                if hops:
                    out[key.value] = hops
    return out


def test_every_handler_hop_is_declared_and_every_declaration_is_a_hop() -> None:
    handlers = _handler_hops()
    declared = {tool: set(targets) for tool, targets in flow_graph.TRANSITIONS.items()}

    undeclared = {
        tool: sorted(hops - declared.get(tool, set()))
        for tool, hops in handlers.items()
        if hops - declared.get(tool, set())
    }
    assert not undeclared, (
        "handlers move somewhere flow_graph.TRANSITIONS does not say -- add it "
        f"there, or the canvas and the text walker will not know: {undeclared}"
    )

    phantom = {
        tool: sorted(targets - handlers.get(tool, set()))
        for tool, targets in declared.items()
        if targets - handlers.get(tool, set())
    }
    assert not phantom, (
        "flow_graph.TRANSITIONS declares a hop no handler makes -- the canvas "
        f"would draw an edge the runtime never takes: {phantom}"
    )


def test_the_reader_still_reads() -> None:
    """The acceptance criterion for the reader itself: it must find the hops
    that only delegation, a factory binding or a parameter default reveal.
    A reader that silently found nothing would make the test above pass."""
    handlers = _handler_hops()
    assert "escalate_close" in handlers["escalate_to_human"], "delegation not followed"
    assert "verify_identity" in handlers["capture_call_goal"], "factory binding not followed"
    assert "state_position" in handlers["return_to_position"], "parameter default not resolved"
    assert len(handlers) >= 16
