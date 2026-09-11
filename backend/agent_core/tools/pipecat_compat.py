"""The pipecat names the tool layer needs, resolved for images without pipecat.

``voice/tools.py`` is the trunk of the voice module tree: ``voice/flows.py``
imports it, ``voice/flow_export.py`` imports that, and ``main.py`` imports the
export to serve ``GET /flow/built-in``. Two pipecat dependencies made that whole
tree unusable in the API image, which builds from ``target: base`` and installs
``requirements.txt`` only — pipecat lives in ``requirements-voice.txt``:

* ``voice/tools.py``'s module-level ``from pipecat.flows import ...``, which
  broke the *import*, and
* :meth:`ToolSpec.to_flows_schema`, which broke the *call* — building the
  built-in graph invokes every node factory, and each one renders its tools.

So ``GET /flow/built-in`` raised ``ModuleNotFoundError`` and returned 500, and
the Flow tab's "load the built-in script" never worked in production.

Nothing else in the chain needed pipecat: ``voice.session``, ``voice.persist``
and ``voice.rtvi_events`` all import cleanly in the API image, and
``to_flows_schema`` already deferred its import for exactly this reason ("text-
only processes never pay the pipecat import cost") — it just deferred it to a
moment that still arrived.

Where pipecat is installed these *are* pipecat's objects and voice behaviour is
unchanged, byte for byte. Where it is not, the stand-ins let the modules be read
and the graph be derived. A process without pipecat cannot run a FlowManager, so
nothing there dispatches a handler, returns :data:`NO_RESPONSE`, or reads the
options :func:`flows_tool_options` records.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

_F = TypeVar("_F", bound=Callable[..., Any])

try:  # pragma: no cover - one branch per image; both are exercised in CI
    from pipecat.flows import NO_RESPONSE, flows_tool_options  # pyright: ignore[reportAssignmentType]

    PIPECAT = True
except ModuleNotFoundError:  # pragma: no cover - see above
    PIPECAT = False

    class _NoResponse:
        """Stand-in for pipecat's sentinel, so an ``is`` check still works.

        Deliberately truthy and not ``None``: the next-node slot distinguishes
        "stay on this node and say nothing" from "no transition was requested",
        and a falsy stand-in would collapse the two if it ever reached a
        runtime.
        """

        __slots__ = ()

        def __repr__(self) -> str:
            return "NO_RESPONSE"

        def __bool__(self) -> bool:
            return True

    NO_RESPONSE: Any = _NoResponse()

    def flows_tool_options(**_kwargs: Any) -> Callable[[_F], _F]:
        """Identity decorator. The options it records are read by the
        FlowManager, which does not exist in a process that took this branch."""

        def _decorate(fn: _F) -> _F:
            return fn

        return _decorate


class FlowsSchemaStub:
    """What a tool's wire contract looks like without pipecat installed.

    Carries the same fields ``FlowsFunctionSchema`` is constructed with, so the
    one consumer that survives in a pipecat-free process — ``flow_export``,
    which matches a node's ``functions`` against the registry *by identity* and
    reads ``.name`` — behaves identically. It holds the handler and never calls
    it.
    """

    __slots__ = ("name", "description", "properties", "required", "handler", "extra")

    def __init__(self, **kwargs: Any) -> None:
        self.name: str = kwargs.pop("name", "")
        self.description: str = kwargs.pop("description", "")
        self.properties: dict[str, Any] = kwargs.pop("properties", {}) or {}
        self.required: list[str] = list(kwargs.pop("required", ()) or ())
        self.handler: Any = kwargs.pop("handler", None)
        self.extra: dict[str, Any] = kwargs

    def __repr__(self) -> str:
        return f"FlowsSchemaStub({self.name!r})"


def flows_function_schema(**kwargs: Any) -> Any:
    """``FlowsFunctionSchema(**kwargs)``, or the stub when pipecat is absent."""
    if PIPECAT:
        from pipecat.flows import FlowsFunctionSchema

        return FlowsFunctionSchema(**kwargs)
    return FlowsSchemaStub(**kwargs)


__all__ = [
    "NO_RESPONSE",
    "PIPECAT",
    "FlowsSchemaStub",
    "flows_function_schema",
    "flows_tool_options",
]
